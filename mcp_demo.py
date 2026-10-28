"""Real MCP client demo: uv run mcp_demo.py 'your question'."""
import argparse
import asyncio
import json
import os
import httpx
from datetime import timedelta
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def run(url, query):
    token = os.getenv("NSE_MCP_TOKEN") or os.getenv("NSE_DEMO_CODE")
    async with httpx.AsyncClient(headers={"Authorization": "Bearer " + token} if token else {}, timeout=240) as client, streamable_http_client(url, http_client=client) as (read, write, _):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=180)) as session:
            await session.initialize()
            listed = await session.list_tools()
            if "neural_search" not in [tool.name for tool in listed.tools]:
                raise RuntimeError("NSE tool is missing")
            result = await session.call_tool("neural_search", {"query": query})
            if result.isError:
                raise RuntimeError(str(result.content))
            print(json.dumps(result.structuredContent, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?", default="What is semantic search?")
    parser.add_argument("--url", default="http://127.0.0.1:8000/mcp")
    args = parser.parse_args()
    asyncio.run(run(args.url, args.query))
