import unittest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient
from nse.access import DemoAccessMiddleware, parse_expiry


class AccessTests(unittest.TestCase):
    def client(self, token="secret", expiry=None):
        async def endpoint(request):
            return JSONResponse({"ok": True})
        return TestClient(Starlette(routes=[Route("/health", endpoint)], middleware=[
            Middleware(DemoAccessMiddleware, token=token, expires_at=expiry)]))

    def test_gate_requires_exact_bearer(self):
        with self.client() as client:
            self.assertEqual(client.get("/health").status_code, 401)
            self.assertEqual(client.get("/health", headers={"Authorization":"Bearer wrong"}).status_code, 401)
            self.assertEqual(client.get("/health", headers={"Authorization":"Bearer secret"}).status_code, 200)

    def test_expired_demo_fails_even_with_valid_token(self):
        with self.client(expiry="2020-01-01T00:00:00+00:00") as client:
            self.assertEqual(client.get("/health", headers={"Authorization":"Bearer secret"}).status_code, 410)

    def test_normal_local_mode_is_unchanged(self):
        with self.client(token="") as client:
            self.assertEqual(client.get("/health").status_code, 200)

    def test_ambiguous_expiry_rejected(self):
        with self.assertRaises(ValueError):
            parse_expiry("2030-01-01T00:00:00")
