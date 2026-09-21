# Local retrieval evaluation

This runner compares the selected search provider's order, the trained bi-encoder order,
and the production bi-encoder → cross-encoder pipeline. It uses one frozen
candidate pool per query and independently grades each query–snippet pair with
local Ollama. The judge is never called by production search.

## Run

From the repository root, with dependencies and the trained checkpoints installed:

```powershell
uv run eval.py
```

Tavily is the default candidate source. It uses keyless access unless
`TAVILY_API_KEY` is set in the environment or repository `.env` file. Search uses
basic depth, one content chunk per source, and no generated answer or raw page
content. DuckDuckGo remains available with `--provider duckduckgo`.

Ollama must already be running with `qwen3:4b` installed. If the model is missing,
install it explicitly with `ollama pull qwen3:4b`. The runner does not download it.
The default Ollama address is `http://localhost:11434`; only HTTP loopback
addresses are accepted. Requests bypass environment proxies and reject redirects.

The default run uses the 30 queries in [queries.json](queries.json), requests up
to 20 candidates, reranks up to 10, and evaluates the top 5. The ranking models
run on CPU; Ollama manages the judge's device independently. The BERT models are
released after the ranking stage before judging starts.

Outputs go to `.cache/nse/evals/tavily-v2/` by default (or
`.cache/nse/evals/duckduckgo-v2/` with `--provider duckduckgo`).
**Run the same command again to resume**:
successful searches, rankings, and judgments are reused. Failed searches and
judgments are retried; successful empty searches remain frozen. Each judgment
is saved immediately, so interruption does not discard completed grades.
Capture spaces new search requests two seconds apart, in addition to the search
client’s retry waits. Provider availability can still leave a run incomplete.

The initial DuckDuckGo run encountered automated-access challenges (HTTP 202).
Those protocol-v1 artifacts remain archived in their original directories; this
provider-aware protocol uses new directories and refuses to overwrite or mix
older runs. Authentication, quota, and rate-limit failures stop further capture
requests in a batch and leave missing queries pending.

For a small separate run:

```powershell
uv run eval.py --provider tavily --limit 3 --output .cache/nse/evals/tavily-pilot
```

For a fresh full run, use a new directory:

```powershell
uv run eval.py --output .cache/nse/evals/run-02
```

Provider settings and query contents are pinned to the run directory. Changed queries,
ranking parameters, checkpoint contents, inference code, library versions, or
judge provenance cannot silently replace saved results. Use a new directory to
compare different configurations. Model weights are identified by SHA-256 file
hashes; the judge record includes its Ollama model digest, server version,
prompt, output schema, and generation settings.

Do not run concurrent processes against the same output directory. A `.running`
file locks the directory. Normal exits and Ctrl+C release it; after a forcibly
terminated process, remove a stale lock only after confirming that process has
stopped.

## Separate stages

```powershell
uv run eval.py --stage capture
uv run eval.py --stage rank
uv run eval.py --stage judge
uv run eval.py --stage report
```

Each stage reads the saved manifest if present, so a pilot directory does not
need `--limit 3` repeated when resuming. Pass `--output` on each command when using
a nondefault run directory. `--stage report` needs neither Ollama nor BERT
inference. Partial reports show which queries are excluded; `run` and `report`
return exit code 1 while any requested query remains incomplete.

Additional options are `--queries PATH`, `--max-results`, `--rerank`, `--top`,
`--provider tavily|duckduckgo`, `--models-dir PATH`, `--device cpu|cuda`,
`--judge MODEL`, and `--ollama-url URL`.
The constraints match search: `1 <= top <= rerank <= max-results <= 20` for
Tavily, or `<= 50` for DuckDuckGo.
Use `uv run eval.py --help` for the complete interface.

Custom query files contain a nonempty JSON array:

```json
[
  {"id": "q01", "category": "technical", "query": "what is semantic search"}
]
```

IDs must be unique and contain only letters, digits, underscores, and hyphens.
Query text must also be unique, with 1–2,000 characters. Category is optional.

## Judging protocol

The judge sees only the query and snippet, one pair per request. It receives no
URL, title, source rank, model score, ranking-method name, or candidate identifier.
Requests are shuffled with a fixed seed, and each request starts a new chat.
The prompt treats snippets as untrusted text and explicitly forbids following
embedded instructions or filling gaps from the model's memory.

| Grade | Rubric |
|---|---|
| 0 | Unrelated or no useful information for the query |
| 1 | Mentions the topic without providing a substantive answer |
| 2 | Provides a useful partial answer; key requested information is missing |
| 3 | Directly and substantially answers the query |

Ambiguous queries are assessed against a plausible interpretation. These grades
measure snippet usefulness, not verified factual truth. A snippet can be relevant
and still contain an incorrect claim.

Generation uses temperature 0, seed 42, thinking disabled, an 8,192-token context,
and a 256-token output budget. These settings improve repeatability but do not
guarantee identical output across hardware or software versions. A JSON schema
requires an integer grade and a short explanation; the application validates both.
Truncated output, invalid grades, network errors, and oversized input are saved
as failures and retried once. They never become grade 0. A conservative byte
budget rejects potentially oversized inputs instead of silently cutting evidence.

## Metrics and comparison

- **nDCG@k:** gains are `2^grade - 1`; the ideal ranking uses every judged candidate
  in the frozen pool. Queries with no positive gain have undefined nDCG and are
  omitted from that average, with the contributing count saved in the report.
- **Precision@k:** grades 2 and 3 count as relevant. The denominator is always k,
  so missing result slots count as nonrelevant. Successful empty searches score 0.
- **Retrieval latency:** the sum of saved fetch time and the scoring stages used
  by each method. Model startup and judge generation time are recorded separately
  and are excluded from this comparison.

The cross-encoder reranks the same dense shortlist used by production, rather
than an artificially expanded candidate set. All candidates are judged, including
ones outside that shortlist, so every method shares the same ideal ranking.

A query contributes to the comparison only after it has a snapshot, rankings,
and valid judgments for **every** candidate. Partially judged queries and provider
failures are excluded from all three methods together and listed explicitly.
Aggregates are unweighted means over completed queries; per-query scores are
also saved. The query set is a small convenience sample, with related clean/typo
queries, so these results do not establish statistical significance or web-wide
recall. They are provisional until the judge is checked against human labels.

## Human review

The runner exports up to **100 query–snippet pairs** in `human-review.json`,
sampling across queries with a fixed seed. It omits machine grades and ranking
information. Fill `human_grade` with 0–3 and optionally add `human_reason`; leave
unreviewed grades as `null`. Keep the query, snippet, and identifiers unchanged.
Review the evidence before looking at the machine judgments.

Then calculate agreement:

```powershell
uv run eval.py --stage agreement
```

`agreement.json` reports the number reviewed, exact agreement, mean absolute
grade error, unweighted Cohen's kappa, and a 4×4 confusion matrix with human
grades as rows. Undefined statistics are `null`. No human labels are fabricated,
and no automatic threshold declares the judge trustworthy. Inspect disagreements,
especially topic-only snippets, ambiguity, and partial answers.

The first nonempty human-review export is preserved on subsequent runs, including
your edits. If it was created while capture was incomplete, its coverage reflects
the snapshots available at that time.

## Saved artifacts

| File or directory | Contents |
|---|---|
| `manifest.json` | Frozen query set, settings, creation time, protocol version |
| `snapshots/` | Full usable candidate pools, original ranks, URLs, snippets, fetch timestamps and timing |
| `ranker.json` | Checkpoint hashes, inference code hashes, versions, requested device |
| `rankings/` | Three top-k orders, scores, stage timing, snapshot fingerprint |
| `startup.jsonl` | BERT checkpoint initialization timings for ranking sessions |
| `judge.json` | Ollama model digest, prompt, schema, options, server version |
| `judgments/` | Valid grades, reasons, complete raw responses, provenance hashes, timing |
| `failures.jsonl` | Append-only per-item failures, including invalid raw judge responses |
| `report.json` / `report.md` | Aggregate and per-query results, coverage and exclusions |
| `human-review.json` | Blind sample for manual grading; never overwritten automatically |
| `agreement.json` | Comparison of user-supplied human grades and machine grades |

Artifacts stay in the ignored `.cache/` directory. Successful records are written
atomically. Do not edit snapshots or judgments: fingerprint checks reject stale
rankings and labels, and retained raw responses allow inspection of judge behavior.

Reports identify the actual provider, and JSON uses `provider` for its baseline
ranking key. Snapshots from different providers cannot be mixed into one run.
Provider API keys are never included in manifests or saved request parameters.

Implementation: [evaluation.py](../nse/evaluation.py).

The [full 30-query Tavily evaluation](results/2026-09-21-tavily.md) is now recorded
with its exact summary, per-query report, and provenance. Provider / bi-encoder /
full reranking nDCG@5 was **0.8788 / 0.7153 / 0.8711**, with precision@5
**0.96 / 0.82 / 0.96**. The full pipeline did not beat the provider baseline and
added latency. These are unvalidated local-LLM judgments.

The initial Tavily pilot completed all three queries with 58 saved candidate
judgments using the 8,192-token Qwen context. It validates the end-to-end path;
the small sample and unvalidated machine labels do not establish general ranking
quality. The separate 30-query command above runs the complete query set.

API references: [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs),
[chat API](https://docs.ollama.com/api/chat), and
[model metadata](https://docs.ollama.com/api/tags).
