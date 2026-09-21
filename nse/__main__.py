"""Run with `python -m nse`; model downloads are a separate, explicit step."""

import argparse
import json
import sys
import time
from pathlib import Path

from .artifacts import DEFAULT_MODELS_DIR, MODEL_HANDLES, download_models, find_checkpoint
from .search import SearchPipeline, SearchUnavailable
from .providers import PROVIDERS, validate_provider_limit


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="nse", description="Search live web snippets with trained NSE models.")
    commands = root.add_subparsers(dest="command", required=True)
    download = commands.add_parser("download-models", help="Download the pinned Kaggle retriever and reranker")
    download.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS_DIR)
    for name in ["search", "interactive"]:
        command = commands.add_parser(name, help="Run one query" if name == "search" else "Run queries with models kept in memory")
        if name == "search":
            command.add_argument("query")
        command.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS_DIR)
        command.add_argument("--retriever-dir", type=Path)
        command.add_argument("--reranker-dir", type=Path)
        command.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
        command.add_argument("--provider", choices=PROVIDERS, default="tavily")
        command.add_argument("--max-results", type=int, default=20)
        command.add_argument("--rerank", type=int, default=10)
        command.add_argument("--top", type=int, default=5)
        command.add_argument("--json", action="store_true", help="Emit structured JSON results")
    return root


def display(response: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return
    print(f"\nQuery: {response['query']}")
    print(f"Fetched {response['candidate_count']} candidates; reranked {response['reranked_count']}.")
    if not response["results"]:
        print("No usable search results returned.")
    for item in response["results"]:
        print(f"\n{item['rank']}. [{item['source_id']}] {item['title']}\n   {item['url']}")
        print(f"   {item['snippet']}")
        print(f"   Search rank {item['search_rank']} -> dense rank {item['dense_rank']} -> final rank {item['rank']}")
        print(f"   Relevance scores: bi={item['bi_score']:.4f}, cross={item['cross_score']:.4f}")
    t = response["timings_ms"]
    print(f"\nTimings: fetch {t['fetch_ms']:.0f} ms | dense {t['bi_encoder_ms']:.0f} ms | rerank {t['cross_encoder_ms']:.0f} ms | total {t['total_ms']:.0f} ms")
    print("Scores measure relevance; snippets are not verified answers.")


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        if args.command == "download-models":
            for kind, path in download_models(args.models_dir).items():
                print(f"{kind}: {MODEL_HANDLES[kind]} -> {path}")
            return 0
        if not 1 <= args.top <= args.rerank <= args.max_results <= 50:
            raise ValueError("Expected 1 <= top <= rerank <= max-results <= 50.")
        validate_provider_limit(args.provider, args.max_results)
        if args.command == "search" and (not args.query.strip() or len(args.query.strip()) > 2000):
            raise ValueError("Query must contain 1 to 2000 characters.")
        retriever = find_checkpoint(args.retriever_dir or args.models_dir / "retriever", "retriever")
        reranker = find_checkpoint(args.reranker_dir or args.models_dir / "reranker", "reranker")
        print("Loading trained checkpoints...", file=sys.stderr)
        start = time.perf_counter()
        from .models import NeuralRanker
        ranker = NeuralRanker(retriever, reranker, args.device)
        startup_ms = round((time.perf_counter() - start) * 1000, 2)
        print(f"Models ready on {ranker.device}; startup {startup_ms / 1000:.2f} s.", file=sys.stderr)
        pipeline = SearchPipeline(ranker, backend=args.provider)

        def run(query):
            response = pipeline.search(query, args.max_results, args.rerank, args.top)
            response.update(device=str(ranker.device), model_load_ms=startup_ms,
                            checkpoints={"retriever": str(retriever), "reranker": str(reranker)})
            display(response, args.json)

        if args.command == "search":
            run(args.query)
        else:
            print("Enter a query; type /quit to exit. Models stay loaded between queries.", file=sys.stderr)
            while True:
                print("search> ", end="", file=sys.stderr, flush=True)
                try:
                    query = input()
                except EOFError:
                    break
                if query.strip() == "/quit":
                    break
                if not query.strip():
                    continue
                try:
                    run(query)
                except (ValueError, SearchUnavailable) as exc:
                    print(f"Error: {exc}", file=sys.stderr)
        return 0
    except ImportError as exc:
        print(f"Missing dependency: {exc.name}. Run `uv sync --locked`.", file=sys.stderr)
        return 1
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
