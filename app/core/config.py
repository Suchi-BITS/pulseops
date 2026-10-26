from __future__ import annotations

import json
import os
from typing import Any

from pydantic import BaseModel, Field

DEVELOPMENT = "development"
AUTH_MODE_DEV = "dev"
AUTH_MODE_APIKEY = "apikey"
DEV_TENANT_ID = "dev"  # the explicit development tenant that owns the synthetic demo data (Gate 9.1)
_TRUE = {"1", "true", "yes", "on"}


class ConfigurationError(RuntimeError):
    """Raised at startup when security-relevant configuration is missing or unsafe (fail closed)."""


def _environment() -> str:
    return (os.getenv("PULSEOPS_ENVIRONMENT") or DEVELOPMENT).strip().lower()


def _auth_mode() -> str:
    explicit = (os.getenv("PULSEOPS_AUTH_MODE") or "").strip().lower()
    if explicit:
        return explicit
    return AUTH_MODE_DEV if _environment() == DEVELOPMENT else AUTH_MODE_APIKEY


def _seed_demo_data() -> bool:
    explicit = os.getenv("PULSEOPS_SEED_DEMO_DATA")
    if explicit is not None and explicit.strip():
        return explicit.strip().lower() in _TRUE
    return _environment() == DEVELOPMENT  # synthetic demo data is development-only unless explicitly enabled


def _credentials() -> list[dict[str, Any]]:
    raw = os.getenv("PULSEOPS_API_CREDENTIALS")
    if not raw or not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigurationError("PULSEOPS_API_CREDENTIALS is not valid JSON") from exc
    if not isinstance(parsed, list):
        raise ConfigurationError("PULSEOPS_API_CREDENTIALS must be a JSON list")
    return parsed


class Settings(BaseModel):
    """Application configuration values for the PulseOps service (environment-driven)."""

    app_name: str = Field(default="PulseOps")
    environment: str = Field(default_factory=_environment)
    debug: bool = Field(default=False)
    api_version: str = Field(default="0.1.0")
    database_url: str = Field(default_factory=lambda: os.getenv("PULSEOPS_DATABASE_URL") or "sqlite:///./pulseops.db")
    # Neo4j is not consumed at runtime yet. No default password is committed; supply NEO4J_PASSWORD if it is used.
    neo4j_uri: str = Field(default_factory=lambda: os.getenv("NEO4J_URI") or "bolt://localhost:7687")
    neo4j_user: str = Field(default_factory=lambda: os.getenv("NEO4J_USER") or "neo4j")
    neo4j_password: str = Field(default_factory=lambda: os.getenv("NEO4J_PASSWORD", ""), repr=False)
    anthropic_api_key: str = Field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""), repr=False)
    claude_model: str = Field(default_factory=lambda: os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514"))
    claude_max_turns: int = Field(default_factory=lambda: int(os.getenv("CLAUDE_MAX_TURNS", "6")))
    # Gate 9: authentication, seed boundary, event-claim recovery
    auth_mode: str = Field(default_factory=_auth_mode)
    api_credentials: list[dict[str, Any]] = Field(default_factory=_credentials, repr=False)
    seed_demo_data: bool = Field(default_factory=_seed_demo_data)
    event_claim_ttl_seconds: int = Field(default_factory=lambda: int(os.getenv("PULSEOPS_EVENT_CLAIM_TTL_SECONDS", "900")))
    # P11: upper bound for any request body (413 beyond it)
    max_body_bytes: int = Field(default_factory=lambda: int(os.getenv("PULSEOPS_MAX_BODY_BYTES", "1048576")))

    @property
    def is_development(self) -> bool:
        return self.environment == DEVELOPMENT


def get_settings() -> Settings:
    return Settings()


def validate_runtime_security(settings: Settings | None = None) -> None:
    """Fail closed at startup if security configuration is missing or unsafe.

    Development may use the explicit dev identity mechanism. Anything else must use bearer API credentials, and the
    dev mechanism must never be enabled outside development.
    """
    settings = settings or get_settings()
    if settings.auth_mode not in {AUTH_MODE_DEV, AUTH_MODE_APIKEY}:
        raise ConfigurationError(f"PULSEOPS_AUTH_MODE must be '{AUTH_MODE_DEV}' or '{AUTH_MODE_APIKEY}'")
    if settings.auth_mode == AUTH_MODE_DEV and not settings.is_development:
        raise ConfigurationError(
            "PULSEOPS_AUTH_MODE=dev is only allowed when PULSEOPS_ENVIRONMENT=development; refusing to start"
        )
    needs_credentials = settings.auth_mode == AUTH_MODE_APIKEY
    if needs_credentials and not settings.api_credentials:
        raise ConfigurationError(
            "PULSEOPS_API_CREDENTIALS is required when authentication uses API credentials; refusing to start"
        )
    from app.core.security import validate_credentials  # local import: security depends on config

    validate_credentials(settings.api_credentials)
