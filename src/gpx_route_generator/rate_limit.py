from __future__ import annotations

import json
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable, MutableMapping
from math import ceil
from threading import Lock
from time import monotonic
from typing import Any

ASGIReceive = Callable[[], Awaitable[MutableMapping[str, Any]]]
ASGISend = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[MutableMapping[str, Any], ASGIReceive, ASGISend], Awaitable[None]]


class SlidingWindowLimiter:
    def __init__(self, *, limit: int, window_seconds: int = 60) -> None:
        if limit < 1:
            raise ValueError("rate limit must be at least one")
        if window_seconds < 1:
            raise ValueError("window_seconds must be at least one")
        self.limit = limit
        self.window_seconds = window_seconds
        self._requests: defaultdict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str, *, now: float | None = None) -> int | None:
        current = monotonic() if now is None else now
        cutoff = current - self.window_seconds
        with self._lock:
            requests = self._requests[key]
            while requests and requests[0] <= cutoff:
                requests.popleft()
            if len(requests) >= self.limit:
                return max(1, ceil(requests[0] + self.window_seconds - current))
            requests.append(current)
            return None


class RateLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        preview_limiter: SlidingWindowLimiter,
        render_limiter: SlidingWindowLimiter,
    ) -> None:
        self.app = app
        self.limiters = {
            "/api/gpx/parse": (preview_limiter, "GPX"),
            "/api/preview": (preview_limiter, "Preview"),
            "/api/render": (render_limiter, "Render"),
        }

    async def __call__(
        self, scope: MutableMapping[str, Any], receive: ASGIReceive, send: ASGISend
    ) -> None:
        if scope.get("type") != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return
        configured = self.limiters.get(scope.get("path"))
        if configured is None:
            await self.app(scope, receive, send)
            return
        limiter, operation = configured
        client = scope.get("client")
        client_key = str(client[0]) if client else "unknown"
        retry_after = limiter.check(client_key)
        if retry_after is None:
            await self.app(scope, receive, send)
            return
        body = json.dumps(
            {"detail": f"{operation} rate limit exceeded. Please try again later."}
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"retry-after", str(retry_after).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
