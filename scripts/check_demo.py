"""Live smoke test: uv run scripts/check_demo.py https://your-demo.vercel.app.

Uses .env.demo without printing credentials. Performs two real searches.
"""
import argparse
import asyncio
from datetime import timedelta
import json
from pathlib import Path
import httpx
from dotenv import dotenv_values
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[1]


async def main(url):
    config = dotenv_values(ROOT / ".env.demo")
    async with httpx.AsyncClient(timeout=240) as client:
        response = await client.get(url + "/health")
        assert response.status_code == 401, f"Public API not gated: {response.status_code}"
        login = await client.post(url + "/demo-session", json={"code": config["NSE_DEMO_CODE"]}, headers={"Origin": url})
        login.raise_for_status()
        response = await client.get(url + "/health")
        response.raise_for_status()
        print("Authenticated health:", response.json(), flush=True)
        response = await client.post(url + "/search", json={"query":"What is semantic search, and how does it differ from keyword search?", "max_results":10, "rerank":5, "top":3})
        response.raise_for_status()
        evidence = response.json()
        assert evidence["results"] and evidence["search_id"]
        print("HTTP search:", len(evidence["results"]), "sources", flush=True)
        response = await client.post(url + "/answer", json={"search_id":evidence["search_id"]})
        response.raise_for_status()
        answer = response.json()
        print("Answer:", answer["answer_status"], "via", answer.get("provider"), flush=True)
        assert answer["answer_status"] == "available"
        (ROOT / ".demo/last-check.json").write_text(json.dumps({"evidence":evidence,"answer":answer},indent=2),encoding="utf-8")
    async with httpx.AsyncClient(headers={"Authorization":"Bearer " + config["NSE_DEMO_CODE"]},timeout=240) as client:
        async with streamable_http_client(url + "/mcp", http_client=client) as (read,write,_):
            async with ClientSession(read,write,read_timeout_seconds=timedelta(seconds=240)) as session:
                await session.initialize()
                listed = await session.list_tools()
                assert "neural_search" in [tool.name for tool in listed.tools]
                result = await session.call_tool("neural_search", {"query":"Why use a cross-encoder to rerank search results?", "max_results":10, "rerank":5, "top":3})
                assert not result.isError, str(result.content)
                assert result.structuredContent["results"]
                print("MCP initialize, tools/list, neural_search: passed", flush=True)
    state = json.loads((ROOT / ".demo/host.json").read_text())
    async with httpx.AsyncClient(timeout=15) as client:
        assert (await client.get(state["url"] + "/health")).status_code == 401
    print("Direct tunnel authentication: passed", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    args = parser.parse_args()
    asyncio.run(main(args.url.rstrip("/")))
