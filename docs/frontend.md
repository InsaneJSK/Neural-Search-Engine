# Web frontend

The React/TypeScript frontend is a local interface to the existing Python service.
It shows live sources first, then optionally requests an answer from Groq with
local Ollama fallback. HTTP, MCP, and n8n clients continue to use the same models.

## Run the complete application

From the repository root, with Node.js 22.12+ and uv installed:

```powershell
uv sync --locked
uv run python -m nse download-models # First setup only
npm --prefix frontend ci
npm --prefix frontend run build
uv run serve.py
```

Open `http://127.0.0.1:8000` after startup completes. Python serves the built page
and assets; no separate frontend process is needed. Rebuild after frontend edits.
The `.env` file stays in the repository root and is read only by the backend.
Never prefix a secret with `VITE_` or put it in frontend source.

For live-editing the frontend, run `uv run serve.py` and, in a second terminal,
`npm --prefix frontend run dev`. Open Vite's printed local URL (normally port
5173). The development proxy forwards `/search`, `/answer`, and `/health` to
the backend on port 8000. Both development and built operation use same-origin
browser requests; no permissive CORS configuration is needed.

## Features

- Question entry with Enter to submit and Shift+Enter for a new line.
- Example questions, a 3/5/10-source selector, and optional automatic cited answers.
- Ranked source cards with safe external links and expandable long excerpts.
- Citation links to the corresponding source card and copy-answer-with-sources.
- Original, dense, and final ranks with separately labeled model relevance scores.
- Real retrieval-stage timings and provider/model attribution for answers.
- Session-only search history; refreshing the page clears it.
- Model information with training scale and links to evaluation limitations.
- Responsive layouts, keyboard controls, native modal focus handling, and
  reduced-motion support. Model output is rendered as text, never executable HTML.

## Request flow

1. `/health` supplies service readiness; the browser checks every 15 seconds.
2. `/search` retrieves and ranks sources, returning evidence plus an opaque `search_id`.
3. The frontend immediately displays those sources.
4. `/answer` receives only that `search_id` and uses the same server-held evidence.
5. Answer failure leaves the source cards available; retry uses the same cache entry.

The cache retains at most 16 searches for 15 minutes and clears on restart.
Expired IDs return HTTP 410 with a request to search again. The service is a
localhost prototype, without accounts or multi-user cache isolation. Generation
is non-streaming; sources are visible while the answer request is in progress.
The UI does not simulate completion percentages or model stage progress.

Google Fonts supplies DM Sans and Instrument Serif; system fonts are fallbacks.
No queries or credentials are sent by the frontend to LLM providers. The backend
sends the selected evidence to Groq, as described in [the answer contract](answers.md).

## Validation

```powershell
npm --prefix frontend run build
npm --prefix frontend test
uv run --locked python -m unittest discover -s tests -v
node --test tests/workflow-answer.test.cjs
```

The build checks TypeScript. Frontend unit tests cover safe URLs and citation
link parsing. Python tests verify cached-evidence reuse, cache expiry/capacity,
answer concurrency, static serving, and continued API operation. Browser checks
exercise live search and answer generation separately from the mocked tests.

On 10 October 2026, browser checks verified the desktop (1280 px) and mobile
(390 px) layouts, automatic Groq answers after retrieval, a three-source
retrieval-only search followed by on-demand Groq generation, citation navigation, excerpt/ranking expansion, copying,
and the model-information dialog. The mobile results had no horizontal overflow.
Real screenshots are included in the [demo gallery](demo-gallery.md).
