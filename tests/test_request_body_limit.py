from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from gpx_route_generator.request_limits import RequestBodyLimitMiddleware

ASGIMessage = MutableMapping[str, Any]
ASGIReceive = Callable[[], Awaitable[ASGIMessage]]
ASGISend = Callable[[ASGIMessage], Awaitable[None]]


class MessageSink:
    def __init__(self) -> None:
        self.messages: list[ASGIMessage] = []

    async def __call__(self, message: ASGIMessage) -> None:
        self.messages.append(message)


def test_chunked_body_stops_receiving_after_limit() -> None:
    received_messages = 0
    messages: list[ASGIMessage] = [
        {"type": "http.request", "body": b"abc", "more_body": True},
        {"type": "http.request", "body": b"def", "more_body": True},
        {"type": "http.request", "body": b"must-not-be-read", "more_body": False},
    ]
    sent = MessageSink()

    async def receive() -> ASGIMessage:
        nonlocal received_messages
        message = messages[received_messages]
        received_messages += 1
        return message

    async def downstream(
        scope: ASGIMessage,
        receive: ASGIReceive,
        send: ASGISend,
    ) -> None:
        while (await receive()).get("more_body", False):
            pass
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = RequestBodyLimitMiddleware(downstream, max_body_bytes=5)
    asyncio.run(
        middleware(
            {"type": "http", "method": "POST", "path": "/api/gpx/parse", "headers": []},
            receive,
            sent,
        )
    )

    assert received_messages == 2
    assert sent.messages[0]["status"] == 413
    assert b"Request body is too large." in sent.messages[1]["body"]
    assert b"must-not-be-read" not in sent.messages[1]["body"]


def test_declared_oversized_body_is_rejected_without_receiving() -> None:
    receive_called = False
    sent = MessageSink()

    async def receive() -> ASGIMessage:
        nonlocal receive_called
        receive_called = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def downstream(
        scope: ASGIMessage,
        receive: ASGIReceive,
        send: ASGISend,
    ) -> None:
        raise AssertionError("oversized request reached downstream app")

    middleware = RequestBodyLimitMiddleware(downstream, max_body_bytes=5)
    asyncio.run(
        middleware(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/gpx/parse",
                "headers": [(b"content-length", b"6")],
            },
            receive,
            sent,
        )
    )

    assert receive_called is False
    assert sent.messages[0]["status"] == 413
