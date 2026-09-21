import os
import unittest
from unittest.mock import Mock, patch

import requests

from nse.providers import TAVILY_URL, fetch_tavily, normalize_tavily
from nse.search import Candidate, SearchAccessUnavailable, SearchPipeline, SearchUnavailable


class ProviderTests(unittest.TestCase):
    def response(self, status=200, payload=None):
        return Mock(status_code=status, json=Mock(return_value=payload or {"results": []}))

    def test_tavily_normalization_preserves_source_positions_and_filters_invalid_rows(self):
        payload = {"results": [
            {"title": "Empty", "url": "https://example.com/empty", "content": " "},
            {"title": "A", "url": "https://example.com/a#section", "content": "answer", "score": 0.1},
            {"title": "Duplicate", "url": "https://example.com/a", "content": "duplicate"},
            None,
            {"title": "Local", "url": "file:///secret", "content": "bad"},
            {"url": "https://example.com/b", "content": "more"},
        ]}
        result = normalize_tavily(payload, 20)
        self.assertEqual([(c.url, c.snippet, c.search_rank) for c in result],
                         [("https://example.com/a", "answer", 2), ("https://example.com/b", "more", 6)])
        self.assertEqual(result[1].title, "https://example.com/b")

    @patch.dict(os.environ, {}, clear=True)
    @patch("requests.post")
    def test_keyless_request_disables_generation_and_uses_bounded_excerpts(self, post):
        post.return_value = self.response()
        self.assertEqual(fetch_tavily("query", 20), [])
        args, kwargs = post.call_args
        self.assertEqual(args, (TAVILY_URL,))
        self.assertEqual(kwargs["headers"], {"X-Tavily-Access-Mode": "keyless"})
        self.assertFalse(kwargs["allow_redirects"])
        self.assertFalse(kwargs["json"]["include_answer"])
        self.assertFalse(kwargs["json"]["include_raw_content"])
        self.assertFalse(kwargs["json"]["auto_parameters"])
        self.assertEqual(kwargs["json"]["chunks_per_source"], 1)
        self.assertEqual(kwargs["json"]["search_depth"], "basic")
        self.assertEqual(kwargs["json"]["max_results"], 20)

    @patch.dict(os.environ, {"TAVILY_API_KEY": "test-secret"})
    @patch("requests.post")
    def test_api_key_is_header_only_and_access_error_does_not_leak_response(self, post):
        post.return_value = self.response(401, {"error": "test-secret"})
        with self.assertRaises(SearchAccessUnavailable) as raised:
            fetch_tavily("query", 5)
        self.assertNotIn("test-secret", str(raised.exception))
        self.assertEqual(post.call_args.kwargs["headers"], {"Authorization": "Bearer test-secret"})
        self.assertNotIn("api_key", post.call_args.kwargs["json"])
        self.assertEqual(post.call_count, 1)

    @patch("requests.post")
    def test_quota_and_rate_errors_fail_fast(self, post):
        for status in (402, 403, 429, 432, 433):
            post.reset_mock()
            post.return_value = self.response(status)
            with self.assertRaises(SearchAccessUnavailable):
                fetch_tavily("query", 5)
            self.assertEqual(post.call_count, 1)

    @patch("nse.providers.time.sleep")
    @patch("requests.post")
    def test_transient_connection_and_server_errors_retry_but_invalid_responses_do_not(self, post, sleep):
        post.side_effect = [requests.ConnectionError("temporary"), self.response(503), self.response()]
        self.assertEqual(fetch_tavily("query", 5), [])
        self.assertEqual(post.call_count, 3)
        post.reset_mock(side_effect=True)
        post.return_value = self.response(200, {"error": "no results list"})
        with self.assertRaisesRegex(SearchUnavailable, "invalid search response"):
            fetch_tavily("query", 5)
        self.assertEqual(post.call_count, 1)

    @patch("requests.post")
    def test_invalid_limits_fail_before_network(self, post):
        for limit in (0, 21, 50):
            with self.assertRaises(ValueError):
                fetch_tavily("query", limit)
        post.assert_not_called()

    def test_pipeline_reports_selected_backend(self):
        class Ranker:
            def bi_scores(self, *_):
                return [0.4]
            def cross_scores(self, *_):
                return [2.0]
        pipeline = SearchPipeline(Ranker(), fetch=lambda *_: [Candidate("a", "https://example.com", "a", 1)], backend="tavily")
        self.assertEqual(pipeline.search("query")["backend"], "tavily")
        with patch("nse.providers.get_provider") as select:
            SearchPipeline(Ranker())
            select.assert_called_once_with("tavily")


if __name__ == "__main__":
    unittest.main()
