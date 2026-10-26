"""Lightweight structured (JSON) logging with request correlation and secret redaction. No external platform."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from app.core.request_context import get_bound_fields, get_principal_id, get_request_id

LOGGER_NAME = "pulseops"
# Extra fields a log call may attach with ``extra={...}``; anything else is ignored (no accidental secret dumps).
_EXTRA_FIELDS = (
    "operation", "outcome", "error_class", "event_id", "incident_id", "workflow_id", "method", "path", "route", "status_code",
    "duration_ms", "principal_type", "principal_id", "tenant_id",
)
_REDACTIONS = (
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [REDACTED]"),
    (re.compile(r"sk-ant-[A-Za-z0-9_-]+"), "[REDACTED]"),
    (re.compile(r"(?i)(authorization|x-api-key|password|token_sha256|api[_-]?key)(\"?\s*[:=]\s*\"?)[^\s\",}]+"), r"\1\2[REDACTED]"),
)


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "request_id": get_request_id(),
            "principal_id": get_principal_id(),
        }
        payload.update(get_bound_fields())
        for name in _EXTRA_FIELDS:
            value = getattr(record, name, None)
            if value is not None:
                payload[name] = value
        return json.dumps({k: v for k, v in payload.items() if v is not None}, default=str)


def configure_logging() -> None:
    """Idempotent: attach one JSON handler to the 'pulseops' logger hierarchy (propagation stays on)."""
    logger = logging.getLogger(LOGGER_NAME)
    if any(getattr(h, "_pulseops_json", False) for h in logger.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler._pulseops_json = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    if logger.level == logging.NOTSET:
        logger.setLevel(logging.INFO)


def get_logger(name: str = LOGGER_NAME) -> logging.Logger:
    return logging.getLogger(name)
