# On-demand hybrid demo

The frontend is hosted at **https://neural-search-engine-grazic.vercel.app** in Vercel project
`nse14/nse-demo`. The Python service and both trained BERT models run on the
presenter's Windows PC. A Cloudflare Quick Tunnel connects them. Groq generates
answers with local Ollama fallback. This is live inference, not recorded output.

```text
Browser → Vercel frontend + server proxy → Cloudflare tunnel
        → local NSE service → Tavily → BERT shortlist → BERT reranking
                           → Groq answer / Ollama fallback
MCP client → Vercel /mcp → same local NSE service
```

No AWS resources are required or created for this setup. Hosting uses the free
tunnel and Vercel's included allowances; Tavily/Groq usage still follows the
configured accounts' plans and quotas. This is a small public demonstration,
not an always-on production service. Keep the PC powered, online, and the host
process running. The launcher requests that Windows stay awake while it runs;
manual sleep, shutdown, lid settings, and network loss can still interrupt it.

## Access

Share the website URL directly. Reviewers do not need a demo code, account, or
session cookie. Public HTTP and MCP clients also need no authentication.

MCP endpoint: `https://neural-search-engine-grazic.vercel.app/mcp`. In n8n's MCP
Client node, use Streamable HTTP with authentication set to None. The n8n editor
itself stays local. The remote MCP interface returns ranked evidence; the
frontend's separate `/answer` endpoint handles generation.

```powershell
uv run mcp_demo.py --url https://neural-search-engine-grazic.vercel.app/mcp
```

The tunnel uses a private `NSE_API_TOKEN`, known only to the backend and the
Vercel function. Provider keys and model checkpoints stay on the PC. Vercel
does not receive the root `.env` file. The backend token is not compiled into JavaScript.
Host validation remains enabled, and the tunnel supplies the loopback host and
port expected by the service. Direct tunnel requests still require the private backend token; reviewers access
inference through the public Vercel proxy.

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
4. Open the URL printed by Vercel to try it directly. Optional live test:
   `uv run scripts/check_demo.py https://neural-search-engine-grazic.vercel.app`.

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

## Keep the link; run the backend on demand

There is no scheduled expiry or automatic deployment deletion. The previous
November 1 cleanup has been canceled. Vercel keeps serving the frontend even
when the PC is off; search, answers, and MCP will report the host unavailable.

Start `uv run scripts/demo_host.py`, wait for **Demo host ready**, then run
`uv run scripts/deploy_demo.py` in a second terminal each time you want to demo.
The tunnel address changes on restart; the public Vercel URL stays the same.
Stop the foreground launcher with Ctrl+C, or create `.demo/stop` for the
background launcher. The backend and tunnel stop, while the website stays up.
There is no need to recreate the project or download the models again.

The launcher clears any legacy backend expiry setting. No expiry value is
required in `.env.demo` or Vercel. Hosting still follows the providers' plans and
usage allowances; there are no AWS resources for this project.

## Limits

- Quick Tunnels have no uptime guarantee and change hostname on restart.
- Quick Tunnels do not support SSE. NSE uses stateless MCP with JSON responses;
  the proxy intentionally rejects MCP GET/SSE streams. Use Streamable HTTP,
  not legacy SSE transport.
- The proxy allows only health, search, answer, and MCP routes, caps request
  bodies at 16 KiB, and times out inference after 240 seconds. It forwards no
  browser cookies or origins to the PC.
- The service permits one search and one answer operation at a time. More
  simultaneous requests receive a retryable busy response. There is no visitor login or added per-user rate limiter.
- Groq or Tavily quotas can still affect the demo. Ollama fallback requires
  Ollama to be running locally with the configured model.

## Verification — October 28, 2026

The initial deployment passed browser sign-in, live search, Groq answers, and
MCP tool calls. The visitor gate has since been removed for direct reviewer
access. The current smoke test exercises public health, search, answer, and MCP
without credentials, and checks that the direct tunnel still rejects anonymous
requests. This is a functional smoke test, not a quality or performance benchmark.

The proxy tests cover public access, private backend-token
requirements, cross-origin requests, request size limits, MCP metadata, and safe
handling of unavailable upstream services. The existing Python tests retain
coverage for the private backend gate and local mode.

References: [Cloudflare Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/),
[Vercel function duration](https://vercel.com/docs/functions/configuring-functions/duration).
