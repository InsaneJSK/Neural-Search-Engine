import json
import unittest
from unittest.mock import Mock

import requests
from starlette.testclient import TestClient

from nse.answers import AnswerConfig, AnswerFailure, AnswerGenerator, validate_answer
from nse.service import create_app


EVIDENCE = {"query": "What is semantic search?", "results": [
    {"source_id": "S4", "title": "Source", "url": "https://example.com", "snippet": "Search by meaning."}
]}
CONTENT = json.dumps({"answer": "Semantic search uses meaning [S4]."})


def response(provider="groq", content=CONTENT, status=200, finish="stop"):
    data = ({"choices": [{"finish_reason": finish, "message": {"content": content}}]} if provider == "groq"
            else {"done": True, "done_reason": finish, "message": {"content": content}})
    return Mock(status_code=status, json=Mock(return_value=data))


class AnswerTests(unittest.TestCase):
    def generator(self, *outputs, key="secret-test-key"):
        post = Mock(side_effect=outputs)
        return AnswerGenerator(AnswerConfig(groq_api_key=key), post=post), post

    def test_groq_success_and_request_contract(self):
        generator, post = self.generator(response())
        result = generator.generate(EVIDENCE)
        self.assertEqual(result["answer_status"], "available")
        self.assertEqual(result["provider"], "groq")
        self.assertFalse(result["fallback_used"])
        self.assertEqual(post.call_count, 1)
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["json"]["response_format"], {"type": "json_object"})
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret-test-key")
        self.assertFalse(kwargs["allow_redirects"])
        self.assertNotIn("secret-test-key", json.dumps(result))

    def test_fallback_for_transport_http_and_invalid_output(self):
        failures = [requests.Timeout("secret"), requests.ConnectionError("secret"),
                    response(status=429), response(status=503), response(status=401), response(status=400),
                    response(content="not json"), response(finish="length"),
                    response(content='{"answer":"Unknown source [S99]"}')]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                generator, post = self.generator(failure, response("ollama"))
                result = generator.generate(EVIDENCE)
                self.assertEqual(result["provider"], "ollama")
                self.assertTrue(result["fallback_used"])
                self.assertEqual(post.call_count, 2)
                first, second = post.call_args_list
                self.assertEqual(first.kwargs["json"]["messages"], second.kwargs["json"]["messages"])
                self.assertEqual(second.kwargs["headers"], {})
                self.assertFalse(second.kwargs["json"]["think"])
                self.assertNotIn("secret", json.dumps(result))

    def test_missing_key_goes_directly_to_ollama(self):
        generator, post = self.generator(response("ollama"), key="")
        result = generator.generate(EVIDENCE)
        self.assertEqual(result["attempts"][0]["reason"], "not_configured")
        self.assertEqual(post.call_count, 1)
        self.assertIn("11434", post.call_args.args[0])

    def test_both_fail_preserves_evidence_and_redacts_provider_errors(self):
        generator, _ = self.generator(response(status=403), requests.Timeout("secret-test-key"))
        with self.assertLogs("nse.answers", level="WARNING") as logs:
            result = generator.generate(EVIDENCE)
        self.assertEqual(result["answer_status"], "unavailable")
        self.assertIsNone(result["answer"])
        self.assertEqual(result["evidence"], EVIDENCE)
        self.assertNotIn("secret-test-key", "".join(logs.output) + json.dumps(result))

    def test_no_sources_and_oversized_evidence_do_not_call_models(self):
        generator, post = self.generator()
        result = generator.generate({"query": "x", "results": []})
        self.assertEqual(result["answer_status"], "no_sources")
        oversized = {**EVIDENCE, "results": [{**EVIDENCE["results"][0], "snippet": "x" * 15000}]}
        self.assertEqual(generator.generate(oversized)["answer_status"], "unavailable")
        post.assert_not_called()

    def test_validation_rejects_bad_content_and_accepts_grouped_citations(self):
        for content in ["null", "[]", '{"answer":2}', '{"answer":""}', '{"answer":"Uncited"}',
                        '{"answer":"Fact [S4, S99]"}', '{"answer":"Fact [S4] [S99; S2]"}',
                        '{"answer":"<think>draft</think> [S4]"}',
                        '{"answer":"Fact [S4]", "extra":true}', json.dumps({"answer": "word " * 181 + "[S4]"})]:
            with self.subTest(content=content[:50]), self.assertRaises(AnswerFailure):
                validate_answer(content, {"S4"})
        self.assertEqual(validate_answer('{"answer":"Fact [S4, S2]"}', {"S4", "S2"}), "Fact [S4, S2]")

    def test_malformed_provider_envelopes_and_ollama_truncation_fail(self):
        for data in [None, [], {}, {"choices": []}, {"choices": [{"finish_reason": "stop", "message": {"content": None}}]}]:
            generator, _ = self.generator(Mock(status_code=200, json=Mock(return_value=data)), response("ollama", finish="length"))
            self.assertEqual(generator.generate(EVIDENCE)["answer_status"], "unavailable")


class AnswerEndpointTests(unittest.TestCase):
    def test_answer_success_and_retrieval_only_interface(self):
        pipeline = Mock()
        pipeline.search.return_value = EVIDENCE
        post = Mock(return_value=response())
        generator = AnswerGenerator(AnswerConfig(groq_api_key="test"), post=post)
        with TestClient(create_app(pipeline_factory=lambda: pipeline, answer_factory=lambda: generator)) as client:
            self.assertEqual(client.post("/search", json={"query": "x"}).status_code, 200)
            post.assert_not_called()
            result = client.post("/answer", json={"query": EVIDENCE["query"]})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()["provider"], "groq")
            self.assertEqual(result.json()["answer_status"], "available")
            self.assertEqual(result.json()["evidence"]["results"], EVIDENCE["results"])
            self.assertTrue(result.json()["evidence"]["search_id"])
            self.assertFalse(client.get("/health").json()["answer_busy"])

    def test_search_runs_once_even_when_both_providers_fail(self):
        pipeline = Mock()
        pipeline.search.return_value = EVIDENCE
        post = Mock(side_effect=[requests.Timeout(), requests.ConnectionError()])
        generator = AnswerGenerator(AnswerConfig(groq_api_key="test"), post=post)
        with TestClient(create_app(pipeline_factory=lambda: pipeline, answer_factory=lambda: generator)) as client:
            result = client.post("/answer", json={"query": EVIDENCE["query"]})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()["answer_status"], "unavailable")
            self.assertEqual(result.json()["evidence"]["results"], EVIDENCE["results"])
            self.assertEqual(pipeline.search.call_count, 1)
            self.assertEqual(post.call_count, 2)
            self.assertFalse(client.get("/health").json()["answer_busy"])
            self.assertEqual(client.post("/answer", json={"query": " "}).status_code, 422)
            self.assertEqual(client.post("/answer", content="{" ).status_code, 422)
            self.assertEqual(pipeline.search.call_count, 1)

    def test_answer_slot_released_after_search_failure(self):
        from nse.search import SearchUnavailable
        pipeline = Mock()
        pipeline.search.side_effect = SearchUnavailable("Unavailable")
        generator = Mock()
        with TestClient(create_app(pipeline_factory=lambda: pipeline, answer_factory=lambda: generator)) as client:
            self.assertEqual(client.post("/answer", json={"query": "x"}).status_code, 503)
            self.assertFalse(client.get("/health").json()["answer_busy"])
            generator.generate.assert_not_called()

    def test_cached_answers_reuse_evidence_and_reject_client_replacement(self):
        pipeline, generator = Mock(), Mock()
        pipeline.search.return_value = EVIDENCE
        generator.generate.side_effect = lambda evidence: {"answer_status": "available", "evidence": evidence}
        with TestClient(create_app(pipeline_factory=lambda: pipeline, answer_factory=lambda: generator)) as client:
            evidence = client.post("/search", json={"query": "x"}).json()
            result = client.post("/answer", json={"search_id": evidence["search_id"]})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()["evidence"], evidence)
            self.assertEqual(pipeline.search.call_count, 1)
            self.assertEqual(client.post("/answer", json={"search_id": evidence["search_id"], "query": "replace"}).status_code, 422)
            self.assertEqual(client.post("/answer", json={"search_id": "unknown"}).status_code, 410)
            self.assertFalse(client.get("/health").json()["answer_busy"])

    def test_cache_expiry_and_capacity(self):
        from unittest.mock import patch
        pipeline, generator = Mock(), Mock()
        pipeline.search.return_value = EVIDENCE
        generator.generate.return_value = {"answer_status": "available"}
        with TestClient(create_app(pipeline_factory=lambda: pipeline, answer_factory=lambda: generator)) as client:
            ids = [client.post("/search", json={"query": "x"}).json()["search_id"] for _ in range(17)]
            self.assertEqual(client.post("/answer", json={"search_id": ids[0]}).status_code, 410)
            self.assertEqual(client.post("/answer", json={"search_id": ids[-1]}).status_code, 200)
            with patch("nse.service.EVIDENCE_TTL_SECONDS", 0):
                self.assertEqual(client.post("/answer", json={"search_id": ids[-1]}).status_code, 410)

    def test_overlapping_answers_rejected_and_slot_recovers(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        entered, release = Event(), Event()
        pipeline, generator = Mock(), Mock()
        pipeline.search.return_value = EVIDENCE

        def generate(evidence):
            entered.set()
            release.wait(5)
            return {"answer_status": "available", "evidence": evidence}

        generator.generate.side_effect = generate
        with TestClient(create_app(pipeline_factory=lambda: pipeline, answer_factory=lambda: generator)) as client:
            with ThreadPoolExecutor(max_workers=1) as pool:
                first = pool.submit(client.post, "/answer", json={"query": "x"})
                try:
                    self.assertTrue(entered.wait(3))
                    second = client.post("/answer", json={"query": "x"})
                    self.assertEqual(second.status_code, 429)
                    self.assertEqual(pipeline.search.call_count, 1)
                    self.assertTrue(client.get("/health").json()["answer_busy"])
                finally:
                    release.set()
                self.assertEqual(first.result(timeout=3).status_code, 200)
            self.assertFalse(client.get("/health").json()["answer_busy"])


if __name__ == "__main__":
    unittest.main()
