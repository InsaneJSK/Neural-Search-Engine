# Local workflow and MCP prototype

See the [recorded validation](prototype-validation.md) for executed workflows,
test results, timings, and observed answer-quality limitations.

The same resident service exposes the trained search pipeline through HTTP and
MCP. It loads the bi-encoder and cross-encoder once, fetches live Tavily excerpts,
and returns ranked evidence. No model download occurs during server startup.

```text
n8n query → NSE HTTP service → Tavily → bi-encoder → cross-encoder → evidence
                                                               ↓
                                                     Ollama → cited answer

MCP client → neural_search tool → the same NSE pipeline → evidence for its LLM
```

## Start the service

From the repository root:

```powershell
uv sync --locked
# Only if checkpoints are not installed:
uv run python -m nse download-models
uv run serve.py
```

Wait for `Application startup complete`. The service is at
`http://127.0.0.1:8000`. Stop it with Ctrl+C. Options include `--port`,
`--models-dir`, `--device cpu`, and `--provider duckduckgo`.
The repository `.env` is loaded; `TAVILY_API_KEY` is optional for keyless access.

Both models run in this Python process. n8n orchestrates requests; it does not
host or download the BERT models. Ollama separately hosts `qwen3:4b` for the answer
workflow. The evidence-only workflow and MCP server do not require Ollama.

## HTTP

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/search -Method Post `
  -ContentType application/json `
  -Body '{"query":"What is semantic search?","max_results":20,"rerank":10,"top":5}'
```

`POST /search` returns the CLI's evidence schema: query, backend, timestamp,
candidate counts, ranked sources (IDs, URLs, excerpts, stage ranks and scores),
and timings. Scores measure relevance, not truth. An empty result list means a
successful search found no usable evidence; provider failures return HTTP 503.
Invalid input returns 422; oversized HTTP bodies return 413. Only one search
runs at a time; concurrent requests return 429 with `Retry-After: 5`.

## MCP

Configure a client that supports **Streamable HTTP**:

| Setting | Value |
| --- | --- |
| URL | `http://127.0.0.1:8000/mcp` |
| Transport | Streamable HTTP |
| Tool | `neural_search` |
| Authentication | None, local prototype |

The tool accepts `query`, `max_results=20`, `rerank=10`, and `top=5`.
Require `1 <= top <= rerank <= max_results <= 20` for Tavily.
The MCP response includes structured evidence and a text representation for
clients that consume tool text. Tool failures are MCP errors, not empty results.

Test with the included actual MCP client (the server must be running):

```powershell
uv run mcp_demo.py "What is semantic search?"
```

An agent can discover and call this tool, then synthesize its own answer using
the returned source IDs and URLs. Source text is untrusted input. Citations
provide traceability; neither BERT relevance scores nor an LLM's answer establish
factual correctness.

## n8n workflows

Use n8n running **natively on the same PC**. The Windows helper installs pinned
n8n 2.39.8 and Node 24 in `.cache/n8n-runtime`, with a separate database in
`.cache/n8n-data`:

```powershell
./n8n.ps1 Install  # First setup only; requires npm
./n8n.ps1 Import  # Imports the three demo workflows; reimport replaces these IDs
./n8n.ps1 Start
```

Open `http://localhost:5678`, complete n8n's local owner setup if prompted, and
open a demo workflow. Stop n8n with Ctrl+C. With the editor stopped, you can also
execute imported workflows using `./n8n.ps1 Search`, `./n8n.ps1 Mcp`, or
`./n8n.ps1 Answer`. Keep the NSE service running in another terminal.

For an existing native n8n installation, import a file through the
workflow editor's **Import from File** menu:

- [`nse-search.json`](../workflows/nse-search.json): manual trigger → editable
  query → HTTP search → ranked evidence.
- [`nse-answer.json`](../workflows/nse-answer.json): the same search → validated
  structured request → Ollama `qwen3:4b` → validated answer together with the
  complete evidence response.
- [`nse-mcp.json`](../workflows/nse-mcp.json): manual query → n8n's native MCP
  Client node → `neural_search` → ranked evidence (n8n 2.39.8).

Open **Demo query** to change the question, then execute the workflow. Inspect
**Rank sources** for model scores and **Answer and evidence** for the cited answer.
For the answer workflow, Ollama must be listening on `127.0.0.1:11434` with
`qwen3:4b` installed. HTTP/provider errors stop the workflow rather than being
passed to the LLM as evidence. The prompt requests citations and admits missing
evidence. The final node rejects empty or truncated generations, answers without
source citations when evidence is available, and unknown source IDs (including
grouped citations). This checks citation IDs, not whether a source supports a claim;
generated claims still need review.

The answer request uses a 16,384-token context and rejects prompts above a
conservative 14,000-byte input budget. If unusually long excerpts trigger that
guard, reduce `top` in **Rank sources** and rerun. The workflow does not silently
shorten excerpts to fit.

`Prepare answer request` and `Answer and evidence` are JavaScript Code nodes.
Ollama's `format` specifies a JSON schema with an `answer` field. The final node
parses that object, rejects incomplete/invalid responses and reasoning tags, and
checks citations against the same execution's sources. Validation throws a
readable node error rather than an exception inside a Set-node expression.

The search and answer workflows use HTTP; the MCP workflow uses the native MCP
Client node. Both paths run the same trained models. These are deterministic
workflows, not an autonomous agent loop. An external agent can choose when to
call the exposed MCP tool.

n8n may print a warning about its optional internal Python task runner. These
workflows use HTTP/MCP nodes, not Python Code nodes; the NSE Python service runs
separately through uv. The warning does not prevent these workflows from running.

This service binds to loopback only and has no public authentication layer.
The supplied localhost URLs do not work from n8n Cloud or a Docker container.
Run the native local prototype as documented; this is not a remote deployment.

## Automated checks

```powershell
uv run python -m unittest discover -s tests -v
node --test tests/workflow-answer.test.cjs
```

Transport tests exercise startup/model reuse, input validation, body limits,
provider failures, MCP initialization/discovery/calls and structured responses
using a fake pipeline. The MCP demo exercises the real models and live search.

Implementation references: [MCP Python SDK v1](https://py.sdk.modelcontextprotocol.io/v1/)
and [n8n workflow import/export](https://docs.n8n.io/workflows/export-import/).
