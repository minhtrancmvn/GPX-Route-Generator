from __future__ import annotations

import asyncio

from gpx_route_generator.rate_limit import RateLimitMiddleware, SlidingWindowLimiter


def run_request(middleware: RateLimitMiddleware, path: str) -> tuple[list[dict], int]:
    sent: list[dict] = []
    receive_calls = 0

    async def receive() -> dict:
        nonlocal receive_calls
        receive_calls += 1
        return {"type": "http.request", "body": b"multipart", "more_body": False}

    async def send(message: dict) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "path": path,
        "method": "POST",
        "client": ("203.0.113.9", 1234),
        "headers": [],
    }
    asyncio.run(middleware(scope, receive, send))
    return sent, receive_calls


def test_rate_limit_middleware_rejects_before_body_read() -> None:
    called = 0

    async def app(scope, receive, send) -> None:
        nonlocal called
        called += 1
        await receive()

    middleware = RateLimitMiddleware(
        app,
        preview_limiter=SlidingWindowLimiter(limit=1),
        render_limiter=SlidingWindowLimiter(limit=1),
    )

    first, first_reads = run_request(middleware, "/api/render")
    second, second_reads = run_request(middleware, "/api/render")

    assert first == []
    assert first_reads == 1
    assert second[0]["status"] == 429
    assert second_reads == 0
    assert called == 1


def test_rate_limit_middleware_shares_parse_and_preview_budget() -> None:
    async def app(scope, receive, send) -> None:
        await receive()

    middleware = RateLimitMiddleware(
        app,
        preview_limiter=SlidingWindowLimiter(limit=1),
        render_limiter=SlidingWindowLimiter(limit=1),
    )

    run_request(middleware, "/api/gpx/parse")
    preview, reads = run_request(middleware, "/api/preview")

    assert preview[0]["status"] == 429
    assert reads == 0


def test_rate_limit_middleware_is_thread_safe_at_limit_boundary() -> None:
    from concurrent.futures import ThreadPoolExecutor

    limiter = SlidingWindowLimiter(limit=10)
    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(lambda _index: limiter.check("client", now=1), range(20)))

    assert results.count(None) == 10
    assert len([result for result in results if result is not None]) == 10


def test_rate_limit_middleware_keeps_preview_and_render_separate() -> None:
    async def app(scope, receive, send) -> None:
        await receive()

    middleware = RateLimitMiddleware(
        app,
        preview_limiter=SlidingWindowLimiter(limit=1),
        render_limiter=SlidingWindowLimiter(limit=1),
    )

    run_request(middleware, "/api/preview")
    render, reads = run_request(middleware, "/api/render")

    assert render == []
    assert reads == 1
