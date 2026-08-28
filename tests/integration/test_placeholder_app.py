import asyncio
from typing import cast

from starlette.types import Message, Receive, Scope, Send

from privilab.main import create_app


async def request_root() -> tuple[int, bytes]:
    app = create_app()
    messages: list[Message] = []
    request_sent = False

    async def receive() -> Message:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        messages.append(message)

    scope = cast(
        Scope,
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"127.0.0.1")],
            "client": ("127.0.0.1", 50000),
            "server": ("127.0.0.1", 8000),
        },
    )
    await app(scope, cast(Receive, receive), cast(Send, send))

    start = next(
        message for message in messages if message["type"] == "http.response.start"
    )
    body = b"".join(
        cast(bytes, message.get("body", b""))
        for message in messages
        if message["type"] == "http.response.body"
    )
    return cast(int, start["status"]), body


def test_placeholder_page_is_explicitly_non_product() -> None:
    status, body = asyncio.run(request_root())

    assert status == 200
    assert b"Synthetic/reference demo only" in body
    assert b"P0 bootstrap placeholder" in body
    assert b"No research" in body
