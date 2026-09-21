"""Fresh web snippets -> dense scoring -> cross-encoder reranking."""

import logging
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol
from urllib.parse import urldefrag, urlsplit


class SearchUnavailable(RuntimeError):
    pass


class SearchAccessUnavailable(SearchUnavailable):
    """Authentication or quota failure: stop batch capture until access recovers."""


class Ranker(Protocol):
    def bi_scores(self, query: str, passages: list[str]) -> list[float]: ...
    def cross_scores(self, query: str, passages: list[str]) -> list[float]: ...


@dataclass(frozen=True)
class Candidate:
    title: str
    url: str
    snippet: str
    search_rank: int


def normalize_results(rows: list[dict], limit: int) -> list[Candidate]:
    candidates, seen = [], set()
    for rank, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            continue
        url, snippet = row.get("href"), row.get("body")
        if not isinstance(url, str) or not isinstance(snippet, str) or not snippet.strip():
            continue
        try:
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                continue
            url = urldefrag(url)[0]
        except ValueError:
            continue
        if url in seen:
            continue
        seen.add(url)
        candidates.append(Candidate(str(row.get("title") or url), url, snippet.strip(), rank))
        if len(candidates) == limit:
            break
    return candidates


def fetch_ddg(query: str, max_results: int) -> list[Candidate]:
    from ddgs import DDGS

    for attempt in range(3):
        try:
            # ddgs is now a metasearch client: explicitly retain the DDG backend.
            rows = DDGS(timeout=15).text(query, max_results=max_results, backend="duckduckgo")
            return normalize_results(rows, max_results)
        except Exception as exc:
            logging.getLogger(__name__).warning("DuckDuckGo attempt %s failed (%s)", attempt + 1, type(exc).__name__)
            if attempt == 2:
                raise SearchUnavailable("DuckDuckGo search failed after 3 attempts. Try again later.") from exc
            time.sleep(2**attempt)
    return []


def validate_scores(scores: list[float], expected: int) -> None:
    if len(scores) != expected or any(not math.isfinite(score) for score in scores):
        raise ValueError("Model returned incomplete or non-finite relevance scores.")


class SearchPipeline:
    def __init__(self, ranker: Ranker, fetch: Callable | None = None, backend: str | None = None):
        self.ranker = ranker
        if fetch is None:
            from .providers import get_provider
            self.backend = backend or "tavily"
            self.fetch = get_provider(self.backend)
        else:
            self.backend = backend or ("duckduckgo" if fetch is fetch_ddg else "custom")
            self.fetch = fetch

    def search(self, query: str, max_results: int = 20, rerank: int = 10, top: int = 5) -> dict:
        query = query.strip()
        if not query:
            raise ValueError("Query must not be empty.")
        if len(query) > 2000:
            raise ValueError("Query must be at most 2000 characters.")
        if not 1 <= top <= rerank <= max_results <= 50:
            raise ValueError("Expected 1 <= top <= rerank <= max-results <= 50.")
        started = time.perf_counter()
        candidates = self.fetch(query, max_results)
        fetched = time.perf_counter()
        timings = {"fetch_ms": (fetched - started) * 1000, "bi_encoder_ms": 0.0, "cross_encoder_ms": 0.0}
        results = []
        if candidates:
            bi_scores = self.ranker.bi_scores(query, [c.snippet for c in candidates])
            validate_scores(bi_scores, len(candidates))
            selected = sorted(range(len(candidates)), key=lambda i: bi_scores[i], reverse=True)[:rerank]
            dense_done = time.perf_counter()
            cross_scores = self.ranker.cross_scores(query, [candidates[i].snippet for i in selected])
            validate_scores(cross_scores, len(selected))
            cross_done = time.perf_counter()
            order = sorted(range(len(selected)), key=lambda i: cross_scores[i], reverse=True)[:top]
            for final_rank, j in enumerate(order, 1):
                i = selected[j]
                results.append({
                    **asdict(candidates[i]), "source_id": f"S{candidates[i].search_rank}",
                    "rank": final_rank, "dense_rank": j + 1,
                    "bi_score": bi_scores[i], "cross_score": cross_scores[j],
                })
            timings.update(bi_encoder_ms=(dense_done - fetched) * 1000, cross_encoder_ms=(cross_done - dense_done) * 1000)
        timings["total_ms"] = (time.perf_counter() - started) * 1000
        return {
            "query": query, "backend": self.backend, "rewriter_used": False,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "candidate_count": len(candidates), "reranked_count": min(rerank, len(candidates)),
            "results": results, "timings_ms": {k: round(v, 2) for k, v in timings.items()},
        }
