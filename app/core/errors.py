"""Typed application errors and the single API error envelope (P9.0).

Every error response has the same shape::

    {"detail": "<human readable>", "code": "<stable machine code>", "request_id": "<correlation id>"}

The HTTP status of a domain failure comes from its *type*, never from matching words in an exception message.
Domain errors deliberately subclass the built-in exception they replaced (``KeyError`` / ``ValueError``) so existing
callers that catch those keep working.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel

STATUS_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "validation_error",
    500: "internal_error",
    503: "not_ready",
}


def code_for_status(status_code: int) -> str:
    return STATUS_CODES.get(status_code, f"http_{status_code}")


class ErrorResponse(BaseModel):
    """The documented error envelope (OpenAPI ``responses``)."""

    detail: str
    code: str
    request_id: str | None = None
    errors: list[dict[str, Any]] | None = None  # validation failures only: location + message, never the input values


class ApiError(HTTPException):
    """An HTTP error with an explicit machine code."""

    def __init__(self, status_code: int, detail: str, code: str | None = None, headers: dict[str, str] | None = None) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code or code_for_status(status_code)


class PulseOpsError(Exception):
    """Base of typed domain errors. ``status_code`` and ``code`` are part of the type."""

    status_code = 400
    code = "bad_request"

    def __str__(self) -> str:  # KeyError would otherwise render its message with quotes
        return str(self.args[0]) if self.args else ""

    def to_api_error(self) -> ApiError:
        return ApiError(self.status_code, str(self), self.code)


class NotFoundError(PulseOpsError, KeyError):
    """The addressed resource does not exist in the caller's tenant (another tenant's is indistinguishable)."""

    status_code = 404
    code = "not_found"


class ConflictError(PulseOpsError, ValueError):
    """The request conflicts with current state (final workflow, idempotency or decision conflict, HITL rule)."""

    status_code = 409
    code = "conflict"
