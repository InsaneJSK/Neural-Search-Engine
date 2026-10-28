"""Optional bearer gate for a short-lived remote demo; local mode stays unchanged."""

import secrets
from datetime import datetime, timezone

from starlette.datastructures import Headers
from starlette.responses import JSONResponse


def parse_expiry(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Demo expiry must include a timezone.")
    return parsed


class DemoAccessMiddleware:
    def __init__(self, app, token, expires_at=None):
        self.app = app
        self.token = token
        self.expires_at = parse_expiry(expires_at)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not self.token:
            return await self.app(scope, receive, send)
        if self.expires_at and datetime.now(timezone.utc) >= self.expires_at:
            response = JSONResponse({"error": "This demo has ended."}, status_code=410)
        elif not secrets.compare_digest(Headers(scope=scope).get("authorization", "").encode(),
                                        ("Bearer " + self.token).encode()):
            response = JSONResponse({"error": "Demo authentication required."}, status_code=401,
                                    headers={"WWW-Authenticate": "Bearer"})
        else:
            return await self.app(scope, receive, send)
        await response(scope, receive, send)
