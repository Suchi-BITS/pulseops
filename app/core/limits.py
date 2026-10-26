"""Request body size limit (P11 defect fix).

Found by the P11 malformed-input tests: the API accepted and stored multi-megabyte bodies (an incident title, workflow
details, an operational-event message that is forwarded to the investigator). Untrusted input must be bounded.

A pure ASGI middleware, so it also bounds chunked uploads that carry no Content-Length: the declared length is checked
up front and the bytes actually received are counted as the body is read. Over the limit the response is 413 in the
standard error envelope (``{"detail", "code", "request_id"}``); nothing is stored.
"""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

DEFAULT_MAX_BODY_BYTES = 1_048_576  # 1 MiB: far above any legitimate incident, event or decision payload


class _BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int = DEFAULT_MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = 0  # a malformed length is left to the server; the byte counter below still applies
                if declared > self.max_bytes:
                    await self._reject(scope, send)
                    return
        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if not response_started:
                await self._reject(scope, send)

    async def _reject(self, scope: Scope, send: Send) -> None:
        request_id = (scope.get("state") or {}).get("request_id")
        body = json.dumps({
            "detail": f"Request body exceeds the {self.max_bytes}-byte limit",
            "code": "payload_too_large",
            "request_id": request_id,
        }).encode()
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                                (b"connection", b"close")]})
        await send({"type": "http.response.body", "body": body})
