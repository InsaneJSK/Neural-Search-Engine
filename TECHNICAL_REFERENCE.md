# Neural Search Engine — Technical Reference

Detailed CLI/API contracts, checkpoint loading, data preparation, and recorded
training experiments. For the project overview and local setup, see the
[README](README.md) and [workflow guide](docs/prototype.md).

- [Command-line usage and Python API](#command-line-usage)
- [Models and checkpoint storage](#models-and-checkpoint-storage)
- [Data preparation](#data-preparation)
- [Training and recorded results](#training-and-recorded-results)
- [Local validation](#local-validation)

## Command-line usage

### Interactive demo

```powershell
uv run demo.py
uv run demo.py --max-results 20 --rerank 10 --top 5
```

`demo.py` delegates to the same CLI and pipeline as this equivalent command:

```powershell
uv run python -m nse interactive
```

Blank input is ignored. Invalid queries and search-provider failures are reported
without ending the interactive session.

### Single query and JSON output

```powershell
uv run python -m nse search "what is semantic search"
uv run python -m nse search "what is semantic search" --json
uv run python -m nse search "what is semantic search" --provider duckduckgo
```

Results go to standard output. Model-loading messages, interactive prompts, and
errors go to standard error, allowing JSON results to be captured separately.
Interactive `--json` emits one formatted JSON object per query, not one JSON array
for the entire session.

### Options

These options apply to `search`, `interactive`, and `demo.py`:

| Option | Default | Purpose |
|---|---|---|
| `--provider` | `tavily` | Select `tavily` or `duckduckgo`; no automatic provider fallback |
| `--max-results` | `20` | Maximum number of search candidates |
| `--rerank` | `10` | Maximum number of dense-ranked candidates passed to the cross-encoder |
| `--top` | `5` | Maximum number of final results |
| `--device` | `auto` | Select `auto`, `cpu`, or `cuda` |
| `--models-dir` | `.cache/nse/models/` in this repository | Root containing the retriever and reranker downloads |
| `--retriever-dir` | Discovered under the model root | Explicit retriever checkpoint location |
| `--reranker-dir` | Discovered under the model root | Explicit reranker checkpoint location |
| `--json` | Off | Emit structured results |

Limits must satisfy `1 <= top <= rerank <= max-results <= 20` for Tavily, or
`<= 50` for DuckDuckGo. Queries must contain
between 1 and 2,000 characters after trimming whitespace.

`auto` selects CUDA when it is available to PyTorch, otherwise CPU. The checked-in
uv configuration installs CPU PyTorch, so `--device cuda` alone does not enable
GPU execution; it requires both a CUDA-enabled PyTorch installation and a
compatible available GPU. The recorded local checks used CPU.

For complete command help:

```powershell
uv run python -m nse --help
uv run python -m nse search --help
```

### Response fields

| Field | Meaning |
|---|---|
| `query` | The query after trimming surrounding whitespace |
| `backend` | Selected provider: `tavily` or `duckduckgo` |
| `rewriter_used` | `false` |
| `retrieved_at` | UTC timestamp recorded when the pipeline finishes |
| `candidate_count` | Usable candidates after filtering and deduplication |
| `reranked_count` | Candidates scored by the cross-encoder |
| `results` | Final ranked source records |
| `timings_ms` | `fetch_ms`, `bi_encoder_ms`, `cross_encoder_ms`, and `total_ms` |
| `device` | Execution device; added by the CLI |
| `model_load_ms` | Startup time including model-library import and checkpoint loading; added by the CLI |
| `checkpoints` | Local retriever and reranker paths; added by the CLI |

Each result contains `title`, `url`, `snippet`, `source_id`, `search_rank`,
`dense_rank`, `rank`, `bi_score`, and `cross_score`. All ranks are one-based.
`source_id` is derived from the original search position, such as `S7`, and stays
attached to that source through both ranking stages. IDs are local to a query's
result set and can have gaps after filtering.

`bi_score` is cosine similarity between normalized embeddings. `cross_score` is
the reranker's raw scalar score. The two scales are not interchangeable.
Query timings exclude model startup; interactive sessions reuse the same startup
measurement. An empty successful search returns an empty `results` list, while
an exhausted provider retry raises a search error.

### Python API

The same components can be used directly from Python:

```python
from nse.artifacts import DEFAULT_MODELS_DIR, find_checkpoint
from nse.models import NeuralRanker
from nse.search import SearchPipeline

retriever = find_checkpoint(DEFAULT_MODELS_DIR / "retriever", "retriever")
reranker = find_checkpoint(DEFAULT_MODELS_DIR / "reranker", "reranker")
ranker = NeuralRanker(retriever, reranker, device="cpu")
pipeline = SearchPipeline(ranker)

response = pipeline.search(
    "what is semantic search", max_results=20, rerank=10, top=5
)
for result in response["results"]:
    print(result["rank"], result["title"], result["url"])
```

Download the checkpoints before running this example. Reuse the `pipeline`
instance for additional queries. `SearchPipeline` also accepts an injected
fetch function and a ranker implementing `bi_scores` and `cross_scores`, which
allows the ranking flow to be tested independently of live search and large
model files.

## Models and checkpoint storage

### Models used by the pipeline

| Component | Architecture | Training objective | Token limit |
|---|---|---|---|
| Dense retriever | `bert-base-uncased`, attention-mask-aware mean pooling, `768 → 256 → 256` projection with ReLU, L2 normalization | InfoNCE with in-batch negatives | 180 per text |
| Cross-encoder reranker | `bert-base-uncased`, joint query–passage input, `[CLS]` representation, linear `768 → 1` scoring head | Pairwise margin ranking loss, margin `1.0` | 192 per pair |

The retriever shares encoder weights between queries and passages. Its normalized
256-dimensional embeddings allow dot products to serve as cosine scores. The
cross-encoder reads the query and passage together to produce a relevance score.
Both run in evaluation mode with gradients disabled during inference.

### Pinned artifacts

The explicit download command uses these versioned Kaggle handles:

| Component | Kaggle handle |
|---|---|
| Retriever | `insanejsk/denseretriever/pytorch/default/1` |
| Reranker | `insanejsk/crossencoderreranker/pytorch/default/1` |

The downloaded checkpoints are discovered under this ignored directory:

```text
.cache/nse/models/
├── retriever/
│   └── best_biencoder/
│       ├── config.json
│       ├── model.safetensors
│       ├── proj.safetensors
│       ├── tokenizer.json
│       └── tokenizer_config.json
└── reranker/
    └── best_reranker/
        ├── config.json
        ├── model.safetensors
        ├── tokenizer.json
        └── tokenizer_config.json
```

Checkpoint discovery requires exactly one complete checkpoint under each supplied
location. In particular, the retriever's `proj.safetensors` must be present, and
the reranker weights must include its trained scoring head.

The loader normalizes saved `module.` prefixes and legacy LayerNorm parameter
names, then loads model parameters strictly. It rejects incomplete or mismatched
weights instead of silently using an untrained projection or scoring head.
Search loads local configurations, tokenizers, and weights; downloading is a
separate command.

To use another storage location:

```powershell
uv run python -m nse download-models --models-dir ./.cache/custom-models
uv run python -m nse search "what is semantic search" --models-dir ./.cache/custom-models
```

Existing Kaggle authentication can be used for artifact access. The CLI also
loads environment variables from the repository's ignored `.env` file. Downloaded
weights, environment files, and credentials do not belong in source control.

Implementation: [artifact download and discovery](nse/artifacts.py),
[checkpoint loading](nse/models.py).

## Data preparation

The retrieval experiments use **MS MARCO v2.1** query–passage records. Preparation
selects a labeled positive passage and constructs training examples from the
remaining passages. Records without a usable positive or negative are skipped.

| Data | Size | Construction and use |
|---|---|---|
| Retriever training set | 200,000 triples | One query, one selected positive, and one sampled negative |
| Retriever validation set | 5,000 triples | Produces a corpus of 9,945 unique positive/negative passages |
| Mined-negative training file | 200,000 triples | Replaces sampled negatives with high-scoring non-positive passages found by the trained retriever |
| Reranker training set | 1,783,707 triples | Expands 200,000 eligible source records by pairing the positive with each available negative |
| Reranker validation corpus | 48,738 unique passages | Constructed from the expanded validation records |
| Synthetic query-rewriter data | 200,000 training pairs; 5,000 validation pairs | Noisy input paired with the original clean query |

Retrieval triples use `query`, `positive`, and `negative` fields. Synthetic rewrite
records use `clean`, `noisy`, and `flags` fields. The local retriever files checked
during development contain 200,000 distinct training queries and 5,000 distinct
validation queries, with no exact query overlap between those splits.

The synthetic-noise workflow includes typos, dropped words, filler words, case and
punctuation changes, and optional colloquial rewrites generated with
`Qwen/Qwen2.5-1.5B-Instruct`. Word deletion was revised to preserve more of short
queries after the original corruption removed too much meaning.

The repository also contains a separate local
[Ollama data-generation script](models/query-rewriter/dataset-generation.py),
configured to use `gemma3:1b` at `localhost:11434`. It generates synthetic rewrite
pairs from retrieval triples and is independent of the search runtime. Its local
partial output should not be confused with the full Kaggle training dataset.

[scripts/download_training_data.py](scripts/download_training_data.py) is a small Kaggle dataset download helper for
`insanejsk/nse-dr`; [demo.py](demo.py) is the search demo.

Data preparation sources:
[retriever triples and BM25](models/retriever/BM25%20baseline%20on%20MS%20MARCO.ipynb),
[reranker pairs](models/reranker/Reranker%20Data%20Prep.ipynb), and
[synthetic query data](models/rewriter/Query%20Rewriter%20Data%20prep.ipynb).

## Training and recorded results

The author reports **100+ hours across setup, training, and model experimentation**
for the BERT retriever, BERT reranker, and T5 rewriter work. This is a combined
project-effort estimate supplied by the author; it is not an audited total of
GPU-hours or a measured duration for any one checkpoint. The training sizes and
metrics below come from the recorded experiments rather than this time estimate.

The following numbers come from saved notebook outputs, including Git history
where outputs were cleared from the current notebook. They describe the recorded
experiments; they are not results from a fresh training run.

These evaluations use constructed validation corpora and a designated positive
passage per example. They are not full MS MARCO leaderboard evaluations or
benchmarks of live web-search quality. Scores from different corpora and query
samples should not be treated as directly comparable.

**Recall@10** measures how often the designated positive appears in the first ten
results. **MRR** averages the reciprocal of its rank, rewarding earlier placement.
**nDCG@10** measures ranking quality in the first ten positions, with larger
rewards for relevant passages near the top. Higher values are better for all
three metrics; the MRR candidate limits are described with each experiment.

### BM25 and dense retrieval

The BM25 baseline lowercases and whitespace-tokenizes text. The untuned BERT
baseline uses masked mean pooling without the trained projection. Fine-tuning
adds the projection and optimizes query–positive similarity against other
positives in the batch using InfoNCE with temperature `0.07`.

Dense training uses a batch size of **32**, learning rate **2e-5**, and **3 epochs**.
The v1 checkpoint is selected by the highest recorded Recall@10.

| Recorded run | Evaluated queries | Recall@10 | MRR |
|---|---:|---:|---:|
| BM25 | 5,000 | 0.7680 | 0.5805 |
| Untuned BERT mean pooling | 500 | 0.4060 | 0.2739 |
| Dense retriever v1, epoch 1 | 1,000 | 0.9660 | 0.8223 |
| Dense retriever v1, epoch 2 — best Recall@10 | 1,000 | **0.9760** | 0.8120 |
| Dense retriever v1, epoch 3 | 1,000 | 0.9690 | **0.8276** |

All rows use the **9,945-passage** validation corpus, but their query samples
differ. Dense evaluation draws a new 1,000-query sample on each invocation, so
epoch-to-epoch changes include sampling variation. MRR here uses the full corpus
ranking. The best Recall@10 and best MRR occurred in different epochs.

Sources: [BM25 notebook](models/retriever/BM25%20baseline%20on%20MS%20MARCO.ipynb),
[dense retriever notebook](models/retriever/Dense%20Retriever%20Train.ipynb).

#### Mined-negative experiment

The trained retriever was used to create 200,000 mined-negative triples. The
notebook also records a second run labeled v2, with a best Recall@10 of **0.9670**
and accompanying MRR of **0.8179**.

There is an important limitation in that experiment: the v2 cell replaces
`train_dataset` without rebuilding `train_loader`, and the training loop ignores
the explicit negative field. Its InfoNCE loss still uses in-batch positives as
negatives. The recorded decline therefore does **not** demonstrate that the
mined negatives harmed training; the saved code does not establish that they were
used by the loss.

### Cross-encoder reranking

The reranker was fine-tuned on **1,783,707** query–positive–negative triples using
batch size **48**, learning rate **2e-5**, margin **1.0**, and a **10% warmup**.
The first epoch produced the best recorded checkpoint by nDCG@10.

Evaluation retrieves the bi-encoder's top **50** candidates from the
**48,738-passage** validation corpus, then reranks them:

| Recorded run | Recall@10 | MRR | nDCG@10 |
|---|---:|---:|---:|
| Bi-encoder baseline in this evaluation | 0.8940 | 0.3815 | 0.5025 |
| Bi-encoder + reranker, epoch 1 | Not recorded | **0.6170** | **0.6906** |
| Continued training, epoch 2 / step 6,000 | Not recorded | 0.5758 | 0.6591 |
| Continued training, epoch 2 / step 12,000 | Not recorded | 0.5527 | 0.6378 |

Continued training stopped after two evaluations without improvement, and the
epoch-1 artifact was restored. Reranked Recall@10 was not printed in these outputs.

Although the notebook calls its evaluation size “500 queries,” the code actually
uses the **first 500 validation pair rows**, which can repeat queries. MRR is
computed within the 50 retrieved candidates. These details, and the larger
corpus, distinguish this evaluation from the dense-retrieval table above. The
live CLI also uses different limits: 20 requested results and 10 reranked by
default.

Sources: [current reranker notebook](models/reranker/CrossEncoder%20Reranker%20Train.ipynb),
[retained epoch-1 outputs](https://github.com/InsaneJSK/Neural-Search-Engine/blob/371834950ea29017e7b5736339b4f580b1989dc4/models/reranker/CrossEncoder%20Reranker%20Train.ipynb),
and [continued-training outputs](https://github.com/InsaneJSK/Neural-Search-Engine/blob/0933f6afe8f8f53ac11d798d435774d0f2edf112/models/reranker/CrossEncoder%20Reranker%20Train.ipynb).

### T5 query rewriter

**T5-small was fine-tuned to turn noisy queries into clean queries. Its current
v1 is excluded from the search pipeline because the experiment did not establish
a sufficiently reliable retrieval benefit.**

The training input is `rewrite query: <noisy query>`, with the original clean
query as the target. The recorded configuration uses batch size **64**, learning
rate **3e-4**, **3 epochs**, **5% warmup**, and input/target limits of **64/48
tokens**. The work included exact-match-based checkpoint selection and a
token-F1-based variant; the current notebook retains the F1 implementation.

Training uses the normal sequence-to-sequence token loss. Token F1 is a
**checkpoint-selection metric**, not a replacement training loss. The F1 routine
evaluates the first 50 validation batches, or up to **3,200 examples**, using
four-beam generation.

The saved retrieval evaluation compares **5,000 matched queries** against the
same **9,945-passage** corpus:

| Query input to the dense retriever | Recall@10 |
|---|---:|
| Original clean queries | 0.9716 |
| Synthetic noisy queries, unchanged | 0.5702 |
| Synthetic noisy queries after T5 F1 rewriting | 0.6330 |

Rewriting recovered **6.28 percentage points** over the noisy baseline, but
remained **33.86 points** below the clean-query result. Some sample rewrites also
changed the intended meaning. This limited recovery does not establish that
rewriting helps ordinary live queries, so the current runtime keeps the supplied
query and reports `rewriter_used: false`.

The evaluated F1 checkpoint is referenced in the notebook as
`insanejsk/queryrewriter-finetuned-t5-small/pytorch/default/1`, under
`query_rewriter_f1/`. The pipeline's model-download command only retrieves the two
BERT models.

Sources: [rewriter training and retrieval evaluation](models/rewriter/Query%20Rewriter%20Train.ipynb),
[synthetic data preparation](models/rewriter/Query%20Rewriter%20Data%20prep.ipynb).

## Local validation

The completed [30-query Tavily evaluation](evals/results/2026-09-21-tavily.md)
records nDCG@5 of **0.8788** for provider order, **0.7153** for the bi-encoder,
and **0.8711** after cross-encoder reranking. Precision@5 is **0.96 / 0.82 / 0.96**;
mean retrieval latency is **3.17 / 6.57 / 8.25 seconds**, respectively.
The trained pipeline does not outperform the provider baseline in this run.
The linked report preserves exact numbers and provenance; its local LLM labels
have not been validated against human judgments.

### Local LLM evaluation

The separate evaluation runner freezes live search candidates, compares
the selected provider's order, bi-encoder, and cross-encoder rankings, and grades snippets with
local Ollama `qwen3:4b`:

```powershell
uv run eval.py
```

It includes 30 varied queries, resumable per-candidate judgments, nDCG@5 and
precision@5, retrieval timings, saved model provenance, and a blind sample for
human review. Results use provisional machine labels until agreement with human
grades has been checked. The judge is independent of production search.

See the [evaluation guide](evals/README.md) for setup, stage commands, metric
definitions, output files, and manual grading instructions.

### Automated checks

```powershell
uv run python -m unittest discover -s tests -v
```

The automated suite covers:

- Checkpoint round-trips with the custom projection and scoring head, including
  legacy parameter-name compatibility and rejection of invalid weights.
- Alignment of source IDs, snippets, scores, and original/dense/final ranks.
- Invalid queries and limits, fewer-than-requested results, and empty results.
- Provider failures, URL normalization, and incomplete or non-finite model scores.
- Evaluation metric calculations, frozen-input reuse, production ranking parity,
  blind judge inputs, invalid judgments, provenance checks, incomplete reports,
  and agreement with manually supplied labels.

Tests use tiny local model fixtures and injected search responses. They do not
download trained checkpoints or call live search providers, and they do not measure learned
retrieval quality.

### Live CPU checks

Two successful single-query runs were recorded on **20 September 2026 (UTC)**
using DuckDuckGo, the downloaded trained checkpoints, and CPU PyTorch. Both received 10
usable candidates, reranked all 10, and returned 5 results.

| Query | Model startup | Search fetch | Dense scoring | Reranking | Query total |
|---|---:|---:|---:|---:|---:|
| `what is semantic search` | 12.34 s | 2.17 s | 0.92 s | 0.73 s | 3.83 s |
| `how does a transformer use attention` | 53.58 s | 1.85 s | 0.90 s | 0.69 s | 3.44 s |

These are individual functional checks, not latency guarantees or a relevance
benchmark. Startup varied substantially and is excluded from the query-total
column. An earlier attempt at the second query exhausted DuckDuckGo retries; a
later attempt succeeded. The interactive demo avoids reloading models for every
query. GPU performance was not measured.

### Runtime errors

| Symptom | Meaning and action |
|---|---|
| Missing dependency | Run `uv sync --locked` from the repository root. |
| No complete checkpoint found | Run `uv run python -m nse download-models`, or select a complete local checkpoint with the directory flags. |
| Multiple checkpoints found | Select the intended checkpoint directory explicitly. |
| Missing or mismatched model weights | Use the complete pinned artifact, including the retriever projection and reranker scoring head. |
| DuckDuckGo search failed after 3 attempts | The provider request failed; retry the query after the service or connection recovers. |
| Tavily access denied or rate/credit limit reached | Check account access or configure `TAVILY_API_KEY`; keyless access is rate-limited. Evaluation capture stops rather than repeatedly sending blocked requests. |
| CUDA requested but unavailable | Use `--device cpu` with the default environment. |

The DuckDuckGo client is configured with a 15-second timeout and up to three attempts,
with one- and two-second waits between failed attempts. A provider error is
reported separately from a successful search with no usable results.
Tavily uses a 5-second connection timeout and 30-second read timeout, retries
connection/server failures up to three attempts, and reports access or quota
errors immediately. It does not follow redirects or switch providers silently.

