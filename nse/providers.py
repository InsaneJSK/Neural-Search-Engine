"""Search providers return a common Candidate list; inference stays local."""

import logging
import os
import time

from .search import SearchAccessUnavailable, SearchUnavailable, fetch_ddg, normalize_results

PROVIDERS = ("tavily", "duckduckgo")
TAVILY_URL = "https://api.tavily.com/search"
TAVILY_SETTINGS = {
    "search_depth": "basic", "topic": "general", "chunks_per_source": 1,
    "include_answer": False, "include_raw_content": False,
    "include_images": False, "auto_parameters": False,
}


def provider_config(name):
    if name == "tavily":
        return {"provider": name, "endpoint": TAVILY_URL, "settings": dict(TAVILY_SETTINGS), "max_results": 20}
    if name == "duckduckgo":
        return {"provider": name, "backend": "duckduckgo", "max_results": 50}
    raise ValueError(f"Unknown search provider: {name}")


def validate_provider_limit(name, max_results):
    maximum = provider_config(name)["max_results"]
    if not 1 <= max_results <= maximum:
        raise ValueError(f"{name} requires 1 <= max-results <= {maximum}.")


def normalize_tavily(payload, limit):
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise SearchUnavailable("Tavily returned an invalid search response (missing results list).")
    rows = [{"title": row.get("title"), "href": row.get("url"), "body": row.get("content")}
            if isinstance(row, dict) else {} for row in payload["results"]]
    return normalize_results(rows, limit)


def fetch_tavily(query, max_results):
    import requests

    validate_provider_limit("tavily", max_results)
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {"X-Tavily-Access-Mode": "keyless"}
    payload = {**TAVILY_SETTINGS, "query": query, "max_results": max_results}
    for attempt in range(3):
        try:
            response = requests.post(TAVILY_URL, headers=headers, json=payload,
                                     timeout=(5, 30), allow_redirects=False)
        except requests.RequestException as exc:
            if attempt == 2:
                raise SearchUnavailable("Tavily connection failed after 3 attempts.") from None
            logging.getLogger(__name__).warning("Tavily attempt %s failed (%s)", attempt + 1, type(exc).__name__)
            time.sleep(2**attempt)
            continue
        # Do not echo response bodies or headers: they may contain credentials.
        if response.status_code in {401, 402, 403, 429, 432, 433}:
            if response.status_code in {401, 403}:
                message = "Tavily access denied. Configure a valid TAVILY_API_KEY in .env if keyless access is unavailable."
            else:
                message = "Tavily rate or credit limit reached. Wait for access to recover or configure your own TAVILY_API_KEY."
            raise SearchAccessUnavailable(f"{message} (HTTP {response.status_code})")
        if response.status_code >= 500 and attempt < 2:
            time.sleep(2**attempt)
            continue
        if response.status_code != 200:
            raise SearchUnavailable(f"Tavily search failed (HTTP {response.status_code}).")
        try:
            value = response.json()
        except ValueError:
            raise SearchUnavailable("Tavily returned invalid JSON.") from None
        return normalize_tavily(value, max_results)
    raise SearchUnavailable("Tavily search failed.")


def get_provider(name):
    provider_config(name)
    return fetch_tavily if name == "tavily" else fetch_ddg
