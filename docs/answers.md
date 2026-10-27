# Shared answer API

`POST /answer` accepts the same input as `POST /search`: `query`, `max_results`
(default 20), `rerank` (10), and `top` (5). The same validation and body-size limit
apply. Retrieval happens once through the resident BERT pipeline. Generation uses
Groq first, then local Ollama on a provider or answer-validation failure. `/search`
and the MCP `neural_search` tool remain retrieval-only.

For a website that displays sources first, call `/search`, then send
`{"search_id":"<returned search_id>"}` to `/answer`. The service reuses the exact
server-held evidence without another search. This form cannot be combined with
`query` or client-supplied evidence. The in-memory cache holds the latest 16 searches
for up to 15 minutes and clears on service restart. Expired or unknown IDs return
HTTP 410; clients should ask users to search again. This local cache is not a
multi-user authentication or session-isolation mechanism.

## Configuration

Use the ignored repository-root `.env` file and restart the service after changes:

| Variable | Default | Purpose |
| --- | --- | --- |
| `GROQ_API_KEY` | Empty | Groq credential; an empty key skips the Groq network call |
| `GROQ_MODEL` | `openai/gpt-oss-20b` | Groq chat model supporting JSON-object output |
| `OLLAMA_MODEL` | `qwen3:4b` | Installed local backup model |

Groq uses `https://api.groq.com/openai/v1/chat/completions`; Ollama uses
`http://127.0.0.1:11434/api/chat` on the backend host. Requests are server-side.
Groq receives the query and selected source titles, URLs, IDs, and excerpts.
Ollama must already be running, with the configured model installed.

The provider requests follow [Groq's JSON-mode documentation](https://console.groq.com/docs/structured-outputs)
and [Ollama's chat API](https://docs.ollama.com/api/chat). Model availability and
account access can change; select a model available to your Groq account.

## Result contract

- `query` and `evidence`: original normalized query and complete retrieval response.
- `answer_status`: `available`, `unavailable`, or `no_sources`.
- `answer`: validated text, or `null` when no answer is accepted.
- `provider` and `model`: successful provider and requested model; otherwise `null`.
- `fallback_used`: whether the Ollama fallback was attempted, including when it failed.
- `attempts`: ordered provider outcomes, with safe failure codes rather than raw errors.
- `answer_latency_ms`: generation/fallback/validation elapsed time, excluding retrieval.
- `factual_verification`: always `not performed`.
- `error`: user-readable explanation when no answer is available.

HTTP 200 means retrieval succeeded, not necessarily generation. Always inspect
`answer_status`. If generation fails, sources remain in `evidence.results`.
Input errors are HTTP 422 (oversized bodies: 413), overlapping operations 429,
retrieval unavailability 503, and unexpected internal failures 500.

## Fallback and resource bounds

There is one attempt per provider, without automatic retries. Failure categories
include `not_configured`, `timeout`, `connection_error`, `authentication_error`,
`rate_limited`, `server_error`, `request_error`, `incomplete_output`,
`invalid_output`, and `invalid_citations`. Authentication/configuration failures
also fall back but are logged explicitly; provider bodies, credentials, and answer
contents are not logged by this layer. Redirects are not followed.

Connection timeout is 5 seconds; read inactivity timeouts are 30 seconds for Groq
and 120 seconds for Ollama. These are not total wall-clock deadlines. Each request
allows up to 4,096 completion tokens on Groq (including reasoning) and 768 output
tokens on Ollama. GPT-OSS models use low reasoning effort. Serialized answer messages have a 14,000-byte
budget; oversized evidence returns an unavailable answer without provider calls,
and can be retried with fewer sources. Empty results also skip both providers.

Only one `/answer` operation runs at a time. `/health` exposes `answer_busy`
separately from the existing search `busy` flag. The search slot is released before
generation; HTTP/MCP retrieval remains available during generation. Overlapping
answer requests receive HTTP 429 with `Retry-After: 5`.

## Answer validation

Both providers receive the same evidence-only prompt. Outputs must be complete,
parse as a JSON object containing exactly one nonempty `answer` string, contain no
thinking tags, remain within 180 words, and cite supplied source IDs. Unknown IDs
and malformed source-like citation brackets are rejected. Grouped citations such
as `[S4, S7]` are accepted. Prompts ask for at most 120 words.

These checks validate structure and citation references, not whether sources
support every claim. Excerpts are treated as untrusted data. Clients should render
answer text safely and resolve source links from the returned evidence.

## Validation

On 2026-10-10, all 51 Python tests, all 7 existing JavaScript workflow tests, and
2 frontend utility tests passed. Thirteen Python tests cover the shared answer
layer and endpoint, including cached evidence. Two more cover frontend serving.

`tests/test_answers.py` exercises provider payloads, fallback, missing keys,
timeouts, HTTP failures, malformed outputs, unknown citations, empty/oversized
evidence, secret-safe failures, single retrieval across fallback, and concurrent
answer rejection. Provider calls and ranking are mocked: these tests do not claim
live Groq account access or live Ollama/model availability. Separate live checks
confirmed accepted Groq GPT-OSS 20B answers and Ollama Qwen3 4B fallback using a
synthetic excerpt. A browser run also completed live Tavily retrieval, both BERT
ranking stages, and a Groq answer with source citations. These are integration
checks, not additional relevance or answer-quality evaluations.

```powershell
uv run --locked python -m unittest discover -s tests -v
```

The three existing n8n workflow exports retain their behavior. An HTTP Request
node can call `/answer` with the body shown in the README to use shared fallback.
