# Temporary hybrid demo

The frontend is hosted at **https://neural-search-engine-jsk.vercel.app** in Vercel project
`nse14/nse-demo`. The Python service and both trained BERT models run on the
presenter's Windows PC. A Cloudflare Quick Tunnel connects them. Groq generates
answers with local Ollama fallback. This is live inference, not recorded output.

```text
Browser → Vercel frontend + authenticated proxy → Cloudflare tunnel
        → local NSE service → Tavily → BERT shortlist → BERT reranking
                           → Groq answer / Ollama fallback
MCP client → Vercel /mcp → same local NSE service
```

No AWS resources are required or created for this setup. Hosting uses the free
tunnel and Vercel's included allowances; Tavily/Groq usage still follows the
configured accounts' plans and quotas. This is a small private demonstration,
not an always-on production service. Keep the PC powered, online, and the host
process running. The launcher requests that Windows stay awake while it runs;
manual sleep, shutdown, lid settings, and network loss can still interrupt it.

## Access

Share the website URL and the `NSE_DEMO_CODE` value from the ignored `.env.demo`
file privately. The browser receives an eight-hour HttpOnly session cookie,
limited by the deployment cutoff. API and MCP clients send that same demo code
as `Authorization: Bearer <demo-code>`.

MCP endpoint: `https://neural-search-engine-jsk.vercel.app/mcp`. In n8n's MCP Client node, use
Streamable HTTP and a header authentication credential with that Authorization
header. The n8n editor itself stays local. The remote MCP interface returns ranked
evidence; the frontend's separate `/answer` endpoint handles generation.

From the host repo, test the MCP client without putting secrets in arguments:

```powershell
uv run --env-file .env.demo mcp_demo.py --url https://neural-search-engine-jsk.vercel.app/mcp
```

The tunnel uses a different `NSE_API_TOKEN`, known only to the backend and the
Vercel function. Provider keys and model checkpoints stay on the PC. Vercel
does not receive the root `.env` file. Neither token is compiled into JavaScript.
Host validation remains enabled, and the tunnel supplies the loopback host and
port expected by the service. Anonymous requests cannot invoke inference.

## Start or rehost

First complete the normal local setup in the README (uv environment, model
checkpoints, provider keys, and Node.js). These scripts target Windows x64.

1. Inside `frontend/`, run `npx vercel login`, then
   `npx vercel link --project nse-demo --scope nse14`. For your own account, use
   your own scope and a new project name. The current deployment uses CLI
   uploads; GitHub auto-deployment is not connected.
2. From the repository root, run `uv run scripts/demo_host.py` and leave that
   terminal running. On first use this creates ignored `.env.demo` credentials,
   downloads the pinned cloudflared executable, verifies its SHA-256 checksum,
   loads the models on port 8001, and starts the tunnel.
3. In a second terminal, run `uv run scripts/deploy_demo.py`. It uploads server
   environment variables through stdin and deploys only the `frontend/` folder.
4. Open the URL printed by Vercel and enter the demo code. Optional live test:
   `uv run scripts/check_demo.py https://neural-search-engine-jsk.vercel.app`.

**Every host restart gets a new tunnel address. Run the deployment script again.**
The public Vercel alias remains stable. `.demo/host.json` records the current
tunnel and owned processes; logs and the latest live-check output live in
`.demo/`. These files and `.env.demo` are ignored by Git.

The code installed during setup uses a hidden background host process. To stop
it, run `New-Item -ItemType File .demo/stop -Force`. Wait for `.demo/host.json` to
disappear before restarting. In a foreground terminal, Ctrl+C also stops the
backend and tunnel. Closing a terminal forcefully may require checking the
recorded process IDs; never terminate unrelated Python or tunnel processes.

Normal local use remains `uv run serve.py`; it does not load `.env.demo`.

## November 1 cutoff and cleanup

The current demo expires at **2026-11-01 23:59:59 Asia/Calcutta**. The backend
and Vercel proxy independently reject requests after that time. The launcher
also stops its child processes. A Codex cleanup is scheduled for November 1 at
23:59 IST to stop the demo and remove only this project's Vercel deployments,
while keeping the project settings, source, secrets, and cached models reusable.
Scheduled cleanup requires Codex to be available; API expiry does not.

To rehost later, set a new timezone-aware `NSE_DEMO_EXPIRES_AT` in `.env.demo`,
start the host and redeploy. Update or cancel any still-pending cleanup schedule
before extending an active demo. Rotating both demo secrets before a new event
is recommended. To remove a deployment manually, select only this project's
deployment in Vercel, or use `npx vercel remove <deployment-url> --yes` from
`frontend/`. Preserve the project if you want to reuse its public alias.

## Limits

- Quick Tunnels have no uptime guarantee and change hostname on restart.
- Quick Tunnels do not support SSE. NSE uses stateless MCP with JSON responses;
  the proxy intentionally rejects MCP GET/SSE streams. Use Streamable HTTP,
  not legacy SSE transport.
- The proxy allows only health, search, answer, and MCP routes, caps request
  bodies at 16 KiB, and times out inference after 240 seconds. It forwards no
  browser cookies or origins to the PC.
- The service permits one search and one answer operation at a time. More
  simultaneous requests receive a retryable busy response. A shared demo code
  is suitable for trusted reviewers, not public multi-user authentication.
- Groq or Tavily quotas can still affect the demo. Ollama fallback requires
  Ollama to be running locally with the configured model.

## Verification — October 28, 2026

The deployed production alias passed browser sign-in, a live ranked search and
cited Groq answer, MCP initialization, tool discovery, and a `neural_search`
tool call using the Python MCP SDK. Anonymous requests to both the Vercel API
and direct tunnel were rejected. The browser displayed five ranked sources,
trace timings, and a Groq `openai/gpt-oss-20b` answer. This is a functional smoke
test, not a performance or answer-quality benchmark. Ollama fallback was not
forced during this deployment check.

Automated validation passed: 55 Python tests, 6 frontend/proxy tests, 7 workflow
tests, and the production frontend build. Authentication tests cover wrong
credentials, altered/expired cookies, cutoff enforcement, cross-origin requests,
request size limits, and safe handling of unavailable upstream services.

References: [Cloudflare Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/),
[Vercel function duration](https://vercel.com/docs/functions/configuring-functions/duration).
