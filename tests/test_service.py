import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from starlette.testclient import TestClient
from nse.service import create_app
from nse.search import SearchUnavailable


class Pipeline:
    def __init__(self):
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["query"] == "fail":
            raise SearchUnavailable("Provider unavailable")
        return {"query": kwargs["query"], "results": [], "backend": "tavily"}


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.pipeline = Pipeline()
        self.loads = 0
        def factory():
            self.loads += 1
            return self.pipeline
        self.client = TestClient(create_app(pipeline_factory=factory), base_url="http://127.0.0.1:8000")
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def test_load_once_and_validate_before_search(self):
        for body in [{"query": " "}, {"query": "x", "max_results": 21},
                     {"query": "x", "top": 11}, {"query": "x", "top": True},
                     {"query": "x", "unexpected": 1}]:
            self.assertEqual(self.client.post("/search", json=body).status_code, 422)
        self.assertEqual(self.pipeline.calls, [])
        for _ in range(2):
            self.assertEqual(self.client.post("/search", json={"query": " valid "}).json()["query"], "valid")
        self.assertEqual(self.loads, 1)
        self.assertEqual(self.client.get("/health").json()["status"], "ready")

    def test_failure_is_not_empty_success(self):
        response = self.client.post("/search", json={"query": "fail"})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("results", response.json())
        self.assertFalse(self.client.get("/health").json()["busy"])

    def test_body_limit_and_invalid_json(self):
        self.assertEqual(self.client.post("/search", content="x" * 16385).status_code, 413)
        self.assertEqual(self.client.post("/search", content="{").status_code, 422)
        self.assertEqual(self.client.get("/health", headers={"Host": "evil.example"}).status_code, 400)

    def test_internal_model_error_is_not_reported_as_invalid_input(self):
        def invalid_scores(**kwargs):
            raise ValueError("private model failure details")
        self.pipeline.search = invalid_scores
        with self.assertLogs("nse.service", level="ERROR"):
            response = self.client.post("/search", json={"query": "valid"})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("private", response.text)

    def test_mcp_discovery_and_call_share_pipeline(self):
        headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18"}
        def rpc(method, params):
            response = self.client.post("/mcp", headers=headers,
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()["result"]
        init = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                  "clientInfo": {"name": "test", "version": "1"}})
        self.assertIn("tools", init["capabilities"])
        self.assertEqual(rpc("tools/list", {})["tools"][0]["name"], "neural_search")
        result = rpc("tools/call", {"name": "neural_search", "arguments": {"query": "mcp test"}})
        self.assertFalse(result.get("isError", False))
        self.assertEqual(result["structuredContent"]["query"], "mcp test")
        error = rpc("tools/call", {"name": "neural_search", "arguments": {"query": "fail"}})
        self.assertTrue(error["isError"])
        self.assertEqual(self.loads, 1)

    def test_overlapping_search_is_rejected_and_slot_recovers(self):
        entered, release = Event(), Event()
        original = self.pipeline.search
        def slow(**kwargs):
            entered.set()
            release.wait(5)
            return original(**kwargs)
        self.pipeline.search = slow
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(self.client.post, "/search", json={"query": "first"})
            try:
                self.assertTrue(entered.wait(3))
                second = self.client.post("/search", json={"query": "second"})
                self.assertEqual(second.status_code, 429)
                self.assertEqual(second.headers["retry-after"], "5")
            finally:
                release.set()
            self.assertEqual(first.result(timeout=3).status_code, 200)
        self.assertFalse(self.client.get("/health").json()["busy"])


if __name__ == "__main__":
    unittest.main()
