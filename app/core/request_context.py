"""Per-request correlation context (request ID, principal, business ids) carried through contextvars."""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar
from typing import Any

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,63}$")

_request_id: ContextVar[str | None] = ContextVar("pulseops_request_id", default=None)
_principal: ContextVar[Any] = ContextVar("pulseops_principal", default=None)
_fields: ContextVar[dict[str, Any]] = ContextVar("pulseops_log_fields", default={})


def sanitize_request_id(candidate: str | None) -> str:
    """Accept a caller-supplied ID only if it is short and made of safe characters; otherwise generate one."""
    if candidate and _SAFE_REQUEST_ID.match(candidate.strip()):
        return candidate.strip()
    return uuid.uuid4().hex


def set_request_id(value: str) -> None:
    _request_id.set(value)
    _principal.set(None)
    _fields.set({})


def get_request_id() -> str | None:
    return _request_id.get()


def bind_principal(principal: Any) -> None:
    """Remember the authenticated Principal for this request (and threads/tasks that copy its context)."""
    _principal.set(principal)


def current_principal() -> Any:
    return _principal.get()


def get_principal_id() -> str | None:
    principal = _principal.get()
    return getattr(principal, "principal_id", None)


def bind(**fields: Any) -> None:
    """Attach business correlation ids (event_id, incident_id, workflow_id, ...) to subsequent log lines."""
    _fields.set({**_fields.get(), **{k: v for k, v in fields.items() if v is not None}})


def get_bound_fields() -> dict[str, Any]:
    return dict(_fields.get())
