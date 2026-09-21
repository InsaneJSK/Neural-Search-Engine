# Tavily setup

The CLI and evaluation runner use Tavily as their default search provider. Both
trained ranking models still run locally. Tavily supplies candidate URLs and
excerpts; the local models score those excerpts.

## CLI and evaluations

With the dependencies and checkpoints installed:

```powershell
uv run demo.py
uv run python -m nse search "what is semantic search" --provider tavily --json
uv run eval.py --provider tavily --limit 3 --output .cache/nse/evals/tavily-pilot
```

The default is keyless access when `TAVILY_API_KEY` is absent. This mode is free
but rate-limited. For account access, obtain a key from the Tavily dashboard and
add it to the repository's ignored `.env` file:

```dotenv
TAVILY_API_KEY=your_actual_key_here
```

Do not put a key in command arguments, workflow JSON, or version control. An
existing environment variable takes precedence over `.env`. Remove the variable
from both locations to return to keyless mode. Invalid keys do not silently fall
back to keyless access or to another search provider.

A fresh 30-query evaluation uses a separate directory from the pilot:

```powershell
uv run eval.py --provider tavily
```

This writes to `.cache/nse/evals/tavily-v2/`. Repeat the command to resume.
The old DuckDuckGo results are kept separate. See the
[evaluation guide](../evals/README.md) for metrics and manual judge validation.

## Request configuration

The Python provider sends `POST https://api.tavily.com/search` with:

```json
{
  "query": "what is semantic search",
  "max_results": 20,
  "search_depth": "basic",
  "topic": "general",
  "chunks_per_source": 1,
  "include_answer": false,
  "include_raw_content": false,
  "include_images": false,
  "auto_parameters": false
}
```

Keyless requests use the header `X-Tavily-Access-Mode: keyless`. Account requests
use `Authorization: Bearer <key>` instead. Tavily's `url` and `content` fields map
to the pipeline's URL and snippet fields. Its original returned position is
preserved; its own relevance score is not fed into BERT or the evaluation judge.
Although one short chunk is requested, some returned excerpts can be longer.
The pipeline retains the returned text; the judge uses an 8,192-token context
with a conservative input guard rather than silently shortening evidence.

Tavily already ranks its results, so the evaluation measures the incremental
effect of our models over that provider order. An improvement is not assumed.

## Connecting the search service in n8n

The repository now includes a local HTTP/MCP service and importable n8n workflows.
Start `uv run serve.py`, then import `workflows/nse-search.json` or
`workflows/nse-answer.json`. Follow the [prototype guide](prototype.md).

```text
Query → NSE service (Tavily → bi-encoder → cross-encoder) → ranked evidence → LLM
```

Tavily runs inside the NSE service, so both trained ranking models are applied.
Calling Tavily directly from n8n would bypass those models.

## Connecting Tavily through MCP

Tavily's hosted MCP endpoint is `https://mcp.tavily.com/mcp/`, using Streamable
HTTP. For keyless access, configure the MCP client to send the header
`X-Tavily-Access-Mode: keyless`. This exposes Tavily's search and extraction tools.
The client must support custom headers; otherwise use Tavily's documented
account authentication. Do not place a real key in a shared example URL.

This repository does not require an MCP connection for CLI execution: its direct
API provider calls the same search service. The NSE MCP endpoint at `http://127.0.0.1:8000/mcp` is different: its
`neural_search` tool calls Tavily and then both trained local ranking models.

References: [keyless access](https://docs.tavily.com/documentation/keyless),
[Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search),
[n8n integration](https://docs.tavily.com/documentation/integrations/n8n), and
[MCP setup](https://docs.tavily.com/documentation/mcp).
