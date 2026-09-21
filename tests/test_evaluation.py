import argparse
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nse.evaluation import (
    JUDGE_OPTIONS, agreement, capture, fingerprint, judge, judge_payload,
    load_queries, manifest, metrics, parser, pin, rank_snapshot, read,
    report, run_lock, save, validate_judgment,
)
from nse.search import Candidate, SearchPipeline


class Ranker:
    def bi_scores(self, query, snippets):
        return [{"a": 0.1, "b": 0.9, "c": 0.7}[s] for s in snippets]

    def cross_scores(self, query, snippets):
        return [{"a": 0.0, "b": -1.0, "c": 2.0}[s] for s in snippets]


class Judge:
    provenance = {"digest": "test-model", "prompt": "test"}

    def __init__(self, broken=False):
        self.calls = []
        self.broken = broken

    def score(self, query, snippet):
        self.calls.append((query, snippet))
        return {"done": True, "done_reason": "length" if self.broken else "stop",
                "message": {"content": json.dumps({"grade": 2, "reason": "Partial answer."})}}


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.run = {"config": {"max_results": 3, "rerank": 2, "top": 2, "provider": "duckduckgo",
                               "judge": "test", "ollama_url": "http://localhost:11434"},
                    "queries": [{"id": "q1", "query": "test query", "category": "test"}]}
        self.candidates = [Candidate(s.upper(), f"https://example.com/{s}", s, i)
                           for i, s in enumerate("abc", 1)]
        self.output = io.StringIO()
        self.stdout = redirect_stdout(self.output)
        self.stderr = redirect_stderr(self.output)
        self.stdout.__enter__()
        self.stderr.__enter__()

    def tearDown(self):
        self.stderr.__exit__(None, None, None)
        self.stdout.__exit__(None, None, None)
        self.temp.cleanup()

    def snapshot(self):
        capture(self.root, self.run, fetch=lambda *_: self.candidates)
        return read(self.root / "snapshots/q1.json")

    def ranked(self):
        snapshot = self.snapshot()
        ranking = rank_snapshot(snapshot, Ranker(), self.run["config"])
        save(self.root / "rankings/q1.json", ranking)
        return snapshot, ranking

    def test_metrics_use_entire_candidate_pool_and_fixed_precision_denominator(self):
        labels = {"a": 3, "b": 2, "c": 0}
        measured = metrics(["b", "c"], labels, 2)
        ideal = 7 + 3 / math.log2(3)
        self.assertAlmostEqual(measured["ndcg"], 3 / ideal)
        self.assertEqual(measured["precision"], 0.5)
        self.assertEqual(metrics(["a"], labels, 5)["precision"], 0.2)
        self.assertEqual(metrics(["a"], {"a": 0}, 5), {"ndcg": None, "precision": 0})
        self.assertEqual(metrics([], {}, 5), {"ndcg": None, "precision": 0})
        with self.assertRaises(ValueError):
            metrics(["missing"], labels, 2)
        with self.assertRaises(ValueError):
            metrics(["a", "a"], labels, 2)

    def test_eval_reranking_matches_production_and_preserves_dense_shortlist(self):
        snapshot, ranking = self.ranked()
        ids = {r["snippet"]: r["id"] for r in snapshot["candidates"]}
        self.assertEqual(ranking["rankings"]["provider"], [ids["a"], ids["b"]])
        self.assertEqual(ranking["rankings"]["bi_encoder"], [ids["b"], ids["c"]])
        self.assertEqual(ranking["rankings"]["cross_encoder"], [ids["c"], ids["b"]])
        prod = SearchPipeline(Ranker(), fetch=lambda *_: self.candidates).search("test query", 3, 2, 2)
        self.assertEqual(ranking["rankings"]["cross_encoder"], [ids[r["snippet"]] for r in prod["results"]])
        self.assertEqual(set(ranking["cross_scores"]), {ids["b"], ids["c"]})

    def test_snapshots_resume_without_refetch_and_judgments_without_regeneration(self):
        self.snapshot()
        def forbidden(*_):
            self.fail("A frozen query was fetched again")
        capture(self.root, self.run, fetch=forbidden)
        client = Judge()
        judge(self.root, self.run, client)
        self.assertEqual(len(client.calls), 3)
        judge(self.root, self.run, client)
        self.assertEqual(len(client.calls), 3)
        self.assertEqual({s for _, s in client.calls}, {"a", "b", "c"})

    def test_judge_payload_has_no_rank_score_title_or_source_identifiers(self):
        payload = judge_payload("query", "snippet", "model")
        self.assertEqual(json.loads(payload["messages"][1]["content"]), {"query": "query", "snippet": "snippet"})
        self.assertEqual(payload["options"], JUDGE_OPTIONS)
        self.assertFalse(payload["think"])
        with self.assertRaisesRegex(ValueError, "context budget"):
            judge_payload("query", "a" * 10000, "model")

    def test_invalid_judgments_are_rejected_and_truncation_recorded_not_scored(self):
        for value in [{"grade": True, "reason": "x"}, {"grade": 4, "reason": "x"},
                      {"grade": "3", "reason": "x"}, {"grade": 1, "reason": " "},
                      {"grade": 1, "reason": "x", "extra": "x"}]:
            with self.assertRaises(ValueError):
                validate_judgment(value)
        self.snapshot()
        client = Judge(broken=True)
        with patch("nse.evaluation.time.sleep"):
            judge(self.root, self.run, client)
        self.assertEqual(len(client.calls), 6)
        self.assertFalse((self.root / "judgments").exists())
        self.assertEqual(len((self.root / "failures.jsonl").read_text().splitlines()), 6)

    def test_partial_labels_exclude_query_for_all_methods_and_human_export_is_blind(self):
        snapshot, _ = self.ranked()
        judge(self.root, self.run, Judge())
        result = report(self.root, self.run)
        self.assertEqual(result["completed_queries"], 1)
        review = read(self.root / "human-review.json")
        self.assertEqual(len(review), 3)
        self.assertTrue(all(r["human_grade"] is None for r in review))
        self.assertTrue(all("grade" not in r and "rank" not in r and "judge_grade" not in r for r in review))
        review[0]["human_grade"] = 3
        save(self.root / "human-review.json", review)
        (self.root / "judgments/q1" / (snapshot["candidates"][0]["id"] + ".json")).unlink()
        result = report(self.root, self.run)
        self.assertEqual(result["completed_queries"], 0)
        self.assertEqual(result["excluded_queries"][0]["reason"], "incomplete_judgments")
        self.assertTrue(all(r["precision"] is None for r in result["aggregate"].values()))
        self.assertEqual(read(self.root / "human-review.json")[0]["human_grade"], 3)

    def test_changed_snapshot_or_judge_is_rejected(self):
        snapshot, _ = self.ranked()
        judge(self.root, self.run, Judge())
        snapshot["candidates"][0]["snippet"] = "changed"
        save(self.root / "snapshots/q1.json", snapshot)
        with self.assertRaisesRegex(ValueError, "changed"):
            judge(self.root, self.run, Judge())
        with self.assertRaisesRegex(ValueError, "changed"):
            report(self.root, self.run)
        with self.assertRaisesRegex(ValueError, "Provenance changed"):
            pin(self.root / "judge.json", {"digest": "different"})

    def test_empty_success_and_fetch_failure_are_distinct(self):
        self.candidates = []
        self.ranked()
        result = report(self.root, self.run)
        self.assertEqual(result["empty_queries"], 1)
        self.assertEqual(result["completed_queries"], 1)
        self.assertEqual(result["aggregate"]["provider"]["precision"], 0)
        self.run["queries"].append({"id": "q2", "query": "fails", "category": "test"})
        def broken(*_):
            raise RuntimeError("provider down")
        capture(self.root, self.run, fetch=broken)
        result = report(self.root, self.run)
        self.assertEqual(result["completed_queries"], 1)
        self.assertEqual(result["excluded_queries"][0]["reason"], "fetch_failed_or_not_run")

    def test_human_agreement_uses_user_labels_and_checks_evidence(self):
        self.ranked()
        judge(self.root, self.run, Judge())
        report(self.root, self.run)
        review = read(self.root / "human-review.json")
        for item, grade in zip(review, [1, 2, 3]):
            item["human_grade"] = grade
        save(self.root / "human-review.json", review)
        agreement(self.root)
        result = read(self.root / "agreement.json")
        self.assertEqual(result["reviewed_pairs"], 3)
        self.assertAlmostEqual(result["exact_agreement"], 1 / 3)
        self.assertAlmostEqual(result["mean_absolute_error"], 2 / 3)
        self.assertAlmostEqual(result["cohens_kappa"], 0)
        review[0]["snippet"] = "different evidence"
        save(self.root / "human-review.json", review)
        with self.assertRaisesRegex(ValueError, "evidence"):
            agreement(self.root)

    def test_manifest_uses_saved_queries_and_rejects_changed_settings(self):
        args = parser().parse_args(["--limit", "3"])
        first = manifest(self.root, args)
        resumed = manifest(self.root, parser().parse_args([]))
        self.assertEqual(first, resumed)
        with self.assertRaises(ValueError):
            manifest(self.root, parser().parse_args(["--judge", "another-model"]))
        with self.assertRaises(ValueError):
            manifest(self.root, parser().parse_args(["--limit", "2"]))

    def test_query_paths_and_run_lock(self):
        path = self.root / "queries.json"
        save(path, [{"id": "../escape", "query": "x"}])
        with self.assertRaises(ValueError):
            load_queries(path)
        with run_lock(self.root):
            with self.assertRaises(ValueError):
                with run_lock(self.root):
                    self.fail("Concurrent run was allowed")
        self.assertFalse((self.root / ".running").exists())

    def test_providers_cannot_be_mixed_or_resumed_into_old_protocol(self):
        args = parser().parse_args(["--limit", "3", "--provider", "tavily"])
        first = manifest(self.root, args)
        self.assertEqual(first["search_provider"]["settings"]["search_depth"], "basic")
        with self.assertRaises(ValueError):
            manifest(self.root, parser().parse_args(["--provider", "duckduckgo"]))
        first["protocol"] = 1
        save(self.root / "manifest.json", first)
        with self.assertRaisesRegex(ValueError, "older evaluation protocol"):
            manifest(self.root, args)
        self.ranked()
        self.run["config"]["provider"] = "tavily"
        with self.assertRaisesRegex(ValueError, "provider"):
            report(self.root, self.run)

    def test_capture_stops_on_provider_quota_without_marking_pending_queries_empty(self):
        from nse.search import SearchAccessUnavailable
        self.run["queries"].append({"id": "q2", "query": "other", "category": "test"})
        calls = []
        def limited(query, limit):
            calls.append(query)
            raise SearchAccessUnavailable("rate limit")
        capture(self.root, self.run, fetch=limited)
        self.assertEqual(len(calls), 1)
        self.assertFalse((self.root / "snapshots").exists())
        result = report(self.root, self.run)
        self.assertEqual(result["completed_queries"], 0)
        self.assertEqual(len(result["excluded_queries"]), 2)


if __name__ == "__main__":
    unittest.main()
