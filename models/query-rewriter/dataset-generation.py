"""
Query Rewriter - Synthetic Dataset Generation
===============================================
Reads clean queries from triples_train_200k.jsonl.
Applies random noise via rule-based corruption + LLM colloquial rephrasing.
Outputs (clean, noisy, flags) pairs for T5-small fine-tuning.

Noise flags (independently sampled per query):
  0: typos / misspellings
  1: missing words
  2: extra filler words
  3: mixed case / no punctuation
  4: colloquial rephrasing (LLM)

Ollama (gemma3:1b, must be running locally)

Output format (JSONL):
  {"clean": "...", "noisy": "...", "flags": [1, 0, 1, 1, 0]}
"""

import json
import os
import random
import re
import threading
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

import requests
from tqdm import tqdm
from dotenv import load_dotenv

load_dotenv()

# CONFIG

CONFIG = {
    "input_path": "models\\query-rewriter\\data\\triples_train.jsonl",
    "output_path": "models\\query-rewriter\\data\\query_rewriter_data.jsonl",
    "ollama_model": "gemma3:1b",
    "ollama_url": "http://localhost:11434",
    "noise_prob": [0.5, 0.5, 0.5, 0.5, 0.2],      # probability each flag independently fires
    "max_samples": 200000,
    "save_every": 1000,    # checkpoint save frequency
    "max_workers": 32,       # for parallel LLM calls
}

# TYPO TABLES

# common keyboard-adjacency typos
KEYBOARD_ADJACENCY = {
    'a': ['s', 'q', 'z'], 'b': ['v', 'n', 'g'], 'c': ['x', 'v', 'd'],
    'd': ['s', 'f', 'e', 'c'], 'e': ['w', 'r', 'd'], 'f': ['d', 'g', 'r'],
    'g': ['f', 'h', 't'], 'h': ['g', 'j', 'y'], 'i': ['u', 'o', 'k'],
    'j': ['h', 'k', 'u'], 'k': ['j', 'l', 'i'], 'l': ['k', 'o', 'p'],
    'm': ['n', 'k'], 'n': ['b', 'm', 'h'], 'o': ['i', 'p', 'l'],
    'p': ['o', 'l'], 'q': ['w', 'a'], 'r': ['e', 't', 'f'],
    's': ['a', 'd', 'w', 'z'], 't': ['r', 'y', 'g'], 'u': ['y', 'i', 'j'],
    'v': ['c', 'b', 'f'], 'w': ['q', 'e', 's'], 'x': ['z', 'c', 's'],
    'y': ['t', 'u', 'h'], 'z': ['a', 's', 'x'],
}

# common filler phrases
FILLERS = [
    "can you tell me", "i want to know", "please explain",
    "hey so", "like", "basically", "i was wondering",
    "could you help me understand", "so basically", "umm",
    "what exactly is", "lol", "pls", "thanks",
]

# NOISE FUNCTIONS

def apply_typos(text):
    """Randomly corrupt ~15% of characters with keyboard-adjacent swaps,
    duplications, or deletions."""
    chars  = list(text)
    result = []
    for ch in chars:
        r = random.random()
        lower = ch.lower()
        if r < 0.05 and lower in KEYBOARD_ADJACENCY:
            # replace with adjacent key
            result.append(random.choice(KEYBOARD_ADJACENCY[lower]))
        elif r < 0.08:
            # duplicate character
            result.append(ch)
            result.append(ch)
        elif r < 0.11:
            continue
        else:
            result.append(ch)
    return "".join(result)


def apply_missing_words(text):
    """Randomly drop 20-40% of words, keeping at least 2."""
    words = text.split()
    if len(words) <= 2:
        return text
    keep_prob = random.uniform(0.6, 0.8)
    kept = [w for w in words if random.random() < keep_prob]
    if len(kept) < 2:
        kept = random.sample(words, 2)
    return " ".join(kept)


def apply_filler(text):
    """Add filler phrase at start or end."""
    filler = random.choice(FILLERS)
    if random.random() < 0.5:
        return f"{filler} {text}"
    else:
        return f"{text} {filler}"

def apply_case_punct(text):
    """Random case + remove punctuation."""
    choice = random.random()
    if choice < 0.33:
        text = text.lower()
    elif choice < 0.66:
        text = text.upper()
    else:
        text = text.title()
    # randomly remove punctuation
    if random.random() < 0.7:
        text = re.sub(r"[^\w\s]", "", text)
    return text


def apply_rule_based_noise(text, flags):
    """Apply flags 0-3 in sequence."""
    if flags[0]:
        text = apply_typos(text)
    if flags[1]:
        text = apply_missing_words(text)
    if flags[2]:
        text = apply_filler(text)
    if flags[3]:
        text = apply_case_punct(text)
    return text

# LLM COLLOQUIAL REPHRASING

SYSTEM_PROMPT = (
    "You are helping generate training data for a query rewriting model. "
    "Your task is to rephrase search queries in a colloquial, informal, "
    "conversational way — as if typed quickly by someone unfamiliar with "
    "formal search syntax. Keep the meaning but make it sound casual and messy. "
    "Return ONLY the rephrased query, nothing else. No explanation, no quotes. No emojis."
)

THREAD_LOCAL = threading.local()

def get_session():
    if not hasattr(THREAD_LOCAL, "session"):
        THREAD_LOCAL.session = requests.Session()
    return THREAD_LOCAL.session

def call_ollama(text):
    session = get_session()

    payload = {
        "model": CONFIG["ollama_model"],
        "prompt": f"{SYSTEM_PROMPT}\n\nRephrase this query colloquially: {text}",
        "stream": False,
        "options": {
            "temperature": 0.9,
            "num_predict": 64,
        },
    }

    r = session.post(
        f"{CONFIG['ollama_url']}/api/generate",
        json=payload,
        timeout=60,
    )

    r.raise_for_status()
    return r.json()["response"].strip()

def colloquial_rephrase(text):
    """Call Ollama."""
    try:
        return call_ollama(text)
    except Exception as e:
        print(f"\n  Ollama failed ({type(e).__name__}), skipping colloquial flag...")
        return text

def process_query(query):
    flags = [
        1 if random.random() < CONFIG["noise_prob"][i] else 0
        for i in range(5)
    ]

    noisy = apply_rule_based_noise(query, flags)

    ollama_used = False

    if flags[4]:
        noisy = colloquial_rephrase(noisy)
        ollama_used = True

    return {
        "clean": query,
        "noisy": noisy,
        "flags": flags,
        "_ollama_used": ollama_used,
    }

# MAIN GENERATION

def generate():
    # load queries — deduplicate since same query can appear in multiple triples
    print(f"Loading queries from {CONFIG['input_path']}...")
    queries = set()
    with open(CONFIG["input_path"]) as f:
        for line in f:
            obj = json.loads(line)
            queries.add(obj["query"])
    queries = list(queries)[:CONFIG["max_samples"]]
    print(f"Unique queries: {len(queries):,}")

    # check ollama availability
    try:
        requests.get(f"{CONFIG['ollama_url']}/api/tags", timeout=3)
        print("Ollama ready")
    except Exception:
        print("Ollama not reachable — will skip colloquial rephrasing")

    # load existing progress if resuming
    done = set()
    out_file = CONFIG["output_path"]
    if os.path.exists(out_file):
        with open(out_file) as f:
            for line in f:
                obj = json.loads(line)
                done.add(obj["clean"])
        print(f"Resuming — {len(done):,} already done")

    queries = [q for q in queries if q not in done]
    print(f"Remaining: {len(queries):,}")

    stats = {"ollama": 0, "skipped": 0, "no_noise": 0}
    stats_lock = threading.Lock()
    completed = 0
    MAX_PENDING = CONFIG["max_workers"] * 8

    with open(out_file, "a", encoding="utf-8") as f:
        with ThreadPoolExecutor(
            max_workers=CONFIG["max_workers"]
        ) as executor:

            query_iter = iter(queries)

            pending = {
                executor.submit(process_query, next(query_iter))
                for _ in range(
                    min(MAX_PENDING, len(queries))
                )
            }

            pbar = tqdm(
                total=len(queries),
                desc="Generating",
                mininterval=2.0,
            )

            while pending:

                done_futures, pending = wait(
                    pending,
                    return_when=FIRST_COMPLETED,
                )

                for future in done_futures:

                    record = future.result()

                    with stats_lock:
                        completed += 1

                        if record["_ollama_used"]:
                            stats["ollama"] += 1

                        if sum(record["flags"]) == 0:
                            stats["no_noise"] += 1

                        current_ollama = stats["ollama"]

                    del record["_ollama_used"]

                    f.write(
                        json.dumps(record, ensure_ascii=False)
                        + "\n"
                    )

                    pbar.update(1)

                    if completed % 100 == 0:
                        pbar.set_postfix(
                            ollama=f"{current_ollama:,}",
                            pct=f"{current_ollama/completed:.1%}",
                        )

                    try:
                        q = next(query_iter)

                        pending.add(
                            executor.submit(
                                process_query,
                                q
                            )
                        )

                    except StopIteration:
                        pass

            pbar.close()

    # final stats
    total = len(queries)
    print(f"\n{'='*50}")
    print(f"Generation Complete")
    print(f"  Total pairs     : {total:,}")
    print(f"  Ollama calls    : {stats['ollama']:,}")
    print(f"  No-noise pairs  : {stats['no_noise']:,}  "
          f"({stats['no_noise']/max(total,1)*100:.1f}%)")
    print(f"  Saved to        : {out_file}")
    print(f"{'='*50}")

    # sanity check
    print("\nSample pairs:")
    with open(out_file) as f:
        for i, line in enumerate(f):
            if i >= 5:
                break
            obj = json.loads(line)
            print(f"\n  [{i+1}] flags={obj['flags']}")
            print(f"  clean : {obj['clean']}")
            print(f"  noisy : {obj['noisy']}")


if __name__ == "__main__":
    generate()
