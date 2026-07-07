# ai_doc_creator/core/ratelimit.py
from __future__ import annotations

import os
import time
from collections import deque

from starlette.responses import JSONResponse

# Keep the per-client state map from growing without bound on a public
# endpoint: once it holds this many keys, fully-expired ones are evicted.
_PRUNE_THRESHOLD = 10_000


class SlidingWindowLimiter:
    """In-memory sliding-window request limiter.

    State is per-process: a multi-instance deployment needs a shared store
    (e.g. Redis) for a global limit; a single instance — the current hosted
    reality — is enforced exactly.
    """

    def __init__(self, limit: int, window_s: float = 60.0):
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str, now: float | None = None) -> tuple[bool, float]:
        """Record a hit for *key*; return (allowed, retry_after_seconds)."""
        if self.limit <= 0:  # 0 or negative disables limiting
            return True, 0.0
        now = time.monotonic() if now is None else now
        cutoff = now - self.window_s
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= self.limit:
            return False, max(0.0, hits[0] + self.window_s - now)
        hits.append(now)
        if len(self._hits) > _PRUNE_THRESHOLD:
            self._prune(cutoff)
        return True, 0.0

    def _prune(self, cutoff: float) -> None:
        stale = [k for k, q in self._hits.items() if not q or q[-1] <= cutoff]
        for k in stale:
            del self._hits[k]


def client_key(scope) -> str:
    """Client identity for limiting: first X-Forwarded-For hop when present
    (the hosted deployment sits behind a TLS-terminating proxy that sets it),
    else the socket peer address."""
    for name, value in scope.get("headers", []):
        if name == b"x-forwarded-for":
            first = value.decode("latin-1").split(",")[0].strip()
            if first:
                return first
    client = scope.get("client")
    return client[0] if client else "unknown"


class RateLimitMiddleware:
    """Pure-ASGI per-client rate limit for the HTTP transports.

    limit=None reads RATE_LIMIT_RPM (default 20; 0 disables).
    /health stays exempt so platform liveness probes are never throttled.
    """

    def __init__(
        self,
        app,
        limit: int | None = None,
        window_s: float = 60.0,
        exempt_paths: tuple[str, ...] = ("/health",),
    ):
        if limit is None:
            try:
                limit = int(os.getenv("RATE_LIMIT_RPM", "20"))
            except ValueError:
                limit = 20
        self.app = app
        self.exempt_paths = exempt_paths
        self.limiter = SlidingWindowLimiter(limit, window_s)

    async def __call__(self, scope, receive, send) -> None:
        if (
            scope["type"] != "http"
            or self.limiter.limit <= 0
            or scope.get("path") in self.exempt_paths
        ):
            await self.app(scope, receive, send)
            return
        allowed, retry_after = self.limiter.allow(client_key(scope))
        if allowed:
            await self.app(scope, receive, send)
            return
        response = JSONResponse(
            {
                "error": "rate_limited",
                "detail": "Too many requests; slow down and retry.",
            },
            status_code=429,
            headers={"Retry-After": str(int(retry_after) + 1)},
        )
        await response(scope, receive, send)
