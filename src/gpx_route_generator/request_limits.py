from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

ASGIReceive = Callable[[], Awaitable[MutableMapping[str, Any]]]
ASGISend = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[MutableMapping[str, Any], ASGIReceive, ASGISend], Awaitable[None]]

BODY_TOO_LARGE_DETAIL = "Request body is too large."

# Bounded multipart framing allowance added on top of the configured GPX byte
# limit: boundary delimiters, per-part headers, and form fields such as
# duration or avatar selection. The endpoint-level reader still enforces the
# exact file-byte limit.
MULTIPART_OVERHEAD_BYTES = 64 * 1024


class _BodyTooLarge(Exception):
    pass


class RequestBodyLimitMiddleware:
    """Reject HTTP request bodies above a byte limit at the ASGI receive layer.

    The limit is enforced while ``http.request`` messages are consumed, so
    oversized chunked uploads are rejected before multipart parsing or
    handler dispatch. Messages after the offending chunk are never consumed.
    """

    def __init__(self, app: ASGIApp, *, max_body_bytes: int) -> None:
        if max_body_bytes <= 0:
            raise ValueError("max_body_bytes must be greater than zero.")
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(
        self, scope: MutableMapping[str, Any], receive: ASGIReceive, send: ASGISend
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        declared_length = _declared_content_length(scope)
        if declared_length is not None and declared_length > self.max_body_bytes:
            await _send_too_large(send)
            return

        consumed = 0

        async def bounded_receive() -> MutableMapping[str, Any]:
            nonlocal consumed
            message = await receive()
            if message.get("type") == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > self.max_body_bytes:
                    raise _BodyTooLarge
            return message

        try:
            await self.app(scope, bounded_receive, send)
        except _BodyTooLarge:
            await _send_too_large(send)


def _declared_content_length(scope: MutableMapping[str, Any]) -> int | None:
    for name, value in scope.get("headers") or ():
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


async def _send_too_large(send: ASGISend) -> None:
    body = json.dumps({"detail": BODY_TOO_LARGE_DETAIL}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
