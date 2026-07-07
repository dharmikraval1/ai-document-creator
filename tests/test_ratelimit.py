# tests/test_ratelimit.py
import asyncio

from ai_doc_creator.core.ratelimit import (
    RateLimitMiddleware,
    SlidingWindowLimiter,
    client_key,
)


def test_limiter_allows_up_to_limit_then_blocks():
    lim = SlidingWindowLimiter(limit=3, window_s=60)
    assert lim.allow("a", now=0.0) == (True, 0.0)
    assert lim.allow("a", now=1.0) == (True, 0.0)
    assert lim.allow("a", now=2.0) == (True, 0.0)
    allowed, retry_after = lim.allow("a", now=3.0)
    assert not allowed
    assert retry_after == 57.0  # first hit (t=0) expires at t=60


def test_limiter_window_slides():
    lim = SlidingWindowLimiter(limit=1, window_s=10)
    assert lim.allow("a", now=0.0)[0]
    assert not lim.allow("a", now=5.0)[0]
    assert lim.allow("a", now=10.1)[0]  # old hit expired


def test_limiter_keys_are_independent():
    lim = SlidingWindowLimiter(limit=1, window_s=60)
    assert lim.allow("a", now=0.0)[0]
    assert lim.allow("b", now=0.0)[0]


def test_limiter_zero_limit_disables():
    lim = SlidingWindowLimiter(limit=0)
    for _ in range(100):
        assert lim.allow("a")[0]


def test_client_key_prefers_first_xff_hop():
    scope = {
        "headers": [(b"x-forwarded-for", b"203.0.113.7, 10.0.0.1")],
        "client": ("127.0.0.1", 1234),
    }
    assert client_key(scope) == "203.0.113.7"


def test_client_key_falls_back_to_socket_peer():
    assert client_key({"headers": [], "client": ("9.9.9.9", 1)}) == "9.9.9.9"
    assert client_key({"headers": []}) == "unknown"


def _run_middleware(mw, path="/mcp", headers=None):
    """Drive the ASGI middleware once; return (status, sent_body_chunks)."""
    sent = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    mw.app = app
    scope = {
        "type": "http",
        "path": path,
        "method": "POST",
        "headers": headers or [],
        "client": ("1.2.3.4", 1),
        "query_string": b"",
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(mw(scope, receive, send))
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    return status, sent


def test_middleware_429_after_limit_with_retry_after():
    mw = RateLimitMiddleware(app=None, limit=2, window_s=60)
    assert _run_middleware(mw)[0] == 200
    assert _run_middleware(mw)[0] == 200
    status, sent = _run_middleware(mw)
    assert status == 429
    start = next(m for m in sent if m["type"] == "http.response.start")
    header_names = {name for name, _ in start["headers"]}
    assert b"retry-after" in header_names


def test_middleware_health_exempt():
    mw = RateLimitMiddleware(app=None, limit=1, window_s=60)
    for _ in range(5):
        assert _run_middleware(mw, path="/health")[0] == 200


def test_middleware_limit_zero_disables():
    mw = RateLimitMiddleware(app=None, limit=0)
    for _ in range(5):
        assert _run_middleware(mw)[0] == 200


def test_middleware_reads_env_default(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_RPM", "7")
    mw = RateLimitMiddleware(app=None)
    assert mw.limiter.limit == 7
    monkeypatch.setenv("RATE_LIMIT_RPM", "not-a-number")
    assert RateLimitMiddleware(app=None).limiter.limit == 20
