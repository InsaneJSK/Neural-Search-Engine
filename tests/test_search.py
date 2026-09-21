import math
import unittest

from nse.search import Candidate, SearchPipeline, SearchUnavailable, normalize_results


class FakeRanker:
    def bi_scores(self, query, passages):
        return [{"a": 0.1, "b": 0.9, "c": 0.7}[p] for p in passages]

    def cross_scores(self, query, passages):
        return [{"a": 0.0, "b": -1.0, "c": 2.0}[p] for p in passages]


class SearchTests(unittest.TestCase):
    def test_reranking_preserves_source_metadata_and_each_stage_rank(self):
        candidates = [Candidate(p.upper(), f"https://example.com/{p}", p, i) for i, p in enumerate("abc", 1)]
        pipeline = SearchPipeline(FakeRanker(), fetch=lambda *_: candidates)
        result = pipeline.search(" query ", max_results=3, rerank=2, top=2)
        first, second = result["results"]
        self.assertEqual(first["snippet"], "c")
        self.assertEqual(first["url"], "https://example.com/c")
        self.assertEqual(first["source_id"], "S3")
        self.assertEqual((first["search_rank"], first["dense_rank"], first["rank"]), (3, 2, 1))
        self.assertEqual(second["snippet"], "b")
        self.assertEqual(result["query"], "query")
        self.assertEqual(result["reranked_count"], 2)

    def test_fewer_results_than_requested(self):
        pipeline = SearchPipeline(FakeRanker(), fetch=lambda *_: [Candidate("B", "https://example.com", "b", 1)])
        result = pipeline.search("query")
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["reranked_count"], 1)

    def test_no_results_does_not_call_models(self):
        pipeline = SearchPipeline(object(), fetch=lambda *_: [])
        self.assertEqual(pipeline.search("query")["results"], [])

    def test_invalid_queries_and_limits_fail_before_search(self):
        def never_fetch(*_):
            self.fail("Invalid input reached search provider")
        pipeline = SearchPipeline(object(), fetch=never_fetch)
        for query in [" ", "a" * 2001]:
            with self.assertRaises(ValueError):
                pipeline.search(query)
        for limits in [(0, 0, 0), (3, 4, 1), (3, 2, 3), (51, 10, 5)]:
            with self.assertRaises(ValueError):
                pipeline.search("query", *limits)

    def test_search_failure_is_distinct_from_no_results(self):
        def fail(*_):
            raise SearchUnavailable("Unavailable")
        with self.assertRaises(SearchUnavailable):
            SearchPipeline(object(), fetch=fail).search("query")

    def test_normalization_filters_and_deduplicates_without_mixing_fields(self):
        rows = [
            {"title": "Empty", "href": "https://example.com/empty", "body": " "},
            {"title": "B", "href": "https://example.com/b#fragment", "body": "b"},
            {"title": "Duplicate", "href": "https://example.com/b", "body": "other"},
            {"title": "Invalid", "href": "file:///local", "body": "bad"},
            {"title": "C", "href": "https://example.com/c", "body": "c"},
        ]
        result = normalize_results(rows, 20)
        self.assertEqual([(c.title, c.snippet, c.search_rank) for c in result], [("B", "b", 2), ("C", "c", 5)])

    def test_invalid_model_scores_are_rejected(self):
        class BrokenRanker(FakeRanker):
            def bi_scores(self, *_):
                return [math.nan]
        with self.assertRaisesRegex(ValueError, "non-finite"):
            SearchPipeline(BrokenRanker(), fetch=lambda *_: [Candidate("B", "https://example.com", "b", 1)]).search("query")


if __name__ == "__main__":
    unittest.main()
