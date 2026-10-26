"""Authentication (bearer API credentials) and deterministic RBAC for PulseOps (Gate 9).

* A ``Principal`` is the only trusted identity. Caller-supplied names (``reviewer``, ``requested_by``) are never trusted.
* Credentials are configured as SHA-256 hashes (``PULSEOPS_API_CREDENTIALS``); plaintext tokens are never stored,
  logged, returned or audited. Hashes are compared in constant time.
* Gate 9.1: every credential is bound to exactly one ``user_id`` and one ``tenant_id``. The principal's roles come
  from the active ``TenantUser`` membership, never from the credential, so a role never leaks across tenants. A
  missing or inactive tenant, user or membership fails closed (403). The tenant is never taken from a request field.
* ``PULSEOPS_AUTH_MODE=dev`` (development environment only) adds a controlled dev identity. It can never be used
  elsewhere: startup refuses to run, and the dev header is ignored outside development.
* RBAC answers "may this principal perform this operation?". The deterministic policy engine remains the only
  authority on ALLOW / NOTIFY / HITL_REQUIRED / DENY; an LLM or agent can override neither.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from fastapi import Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import (
    AUTH_MODE_APIKEY,
    AUTH_MODE_DEV,
    DEV_TENANT_ID,
    ConfigurationError,
    Settings,
    get_settings,
)

DEV_HEADER = "X-Dev-Principal"
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9._~+/=-]{16,512}$")
_ID_PATTERN = re.compile(r"^[A-Za-z0-9._@:-]{1,128}$")


class PrincipalType(str, Enum):
    HUMAN = "human"
    SERVICE = "service"
    AGENT = "agent"
    SYSTEM = "system"


class Permission(str, Enum):
    EVENTS_INGEST = "events:ingest"
    INCIDENT_READ = "incident:read"
    INCIDENT_WRITE = "incident:write"
    WORKFLOW_READ = "workflow:read"
    WORKFLOW_EVALUATE = "workflow:evaluate"
    WORKFLOW_APPROVE = "workflow:approve"
    AGENT_INVESTIGATE = "agent:investigate"


# Roles are static (no dynamic roles). Domain roles such as "sre" or "incident_manager" may be added to a
# principal's role list in configuration; they carry no application permissions of their own and are only matched
# against a policy rule's ``permitted_roles`` when a HITL decision is made.
ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "service_n8n": frozenset({Permission.EVENTS_INGEST, Permission.WORKFLOW_READ, Permission.INCIDENT_READ}),
    "reviewer": frozenset({Permission.WORKFLOW_READ, Permission.INCIDENT_READ, Permission.WORKFLOW_APPROVE}),
    "operator": frozenset({
        Permission.INCIDENT_READ, Permission.INCIDENT_WRITE, Permission.WORKFLOW_READ,
        Permission.WORKFLOW_EVALUATE, Permission.EVENTS_INGEST, Permission.AGENT_INVESTIGATE,
    }),
    "admin": frozenset(Permission),
}
GATE9_ROLES = frozenset(ROLE_PERMISSIONS)


class Principal(BaseModel):
    """The authenticated caller. Immutable."""

    model_config = ConfigDict(frozen=True)

    principal_id: str
    principal_type: PrincipalType
    user_id: str = ""
    display_name: str = ""
    roles: tuple[str, ...] = ()
    tenant_id: str  # required: there is no default or implicit tenant
    auth_method: str
    authenticated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="before")
    @classmethod
    def _default_user_id(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data.get("user_id"):
            data = {**data, "user_id": data.get("principal_id", "")}
        return data

    @model_validator(mode="after")
    def _require_tenant(self) -> "Principal":
        if not self.tenant_id or not self.tenant_id.strip():
            raise ValueError("a principal must carry a tenant_id")
        return self

    @property
    def permissions(self) -> frozenset[Permission]:
        granted: set[Permission] = set()
        for role in self.roles:
            granted |= ROLE_PERMISSIONS.get(role, frozenset())
        return frozenset(granted)

    def has(self, permission: Permission) -> bool:
        return permission in self.permissions

    @property
    def is_human(self) -> bool:
        return self.principal_type is PrincipalType.HUMAN


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def validate_credentials(credentials: list[dict[str, Any]]) -> None:
    """Startup validation of the configured credential entries (never echoes hash or token values).

    An entry binds a token hash to one ``principal_id`` (the ``user_id``) and one ``tenant_id``. Roles and the
    principal type are deliberately NOT accepted here: they come from the TenantUser membership and the User row.
    """
    seen: set[tuple[str, str]] = set()
    hashes: set[str] = set()
    for index, entry in enumerate(credentials):
        label = f"credential #{index + 1}"
        if not isinstance(entry, dict):
            raise ConfigurationError(f"{label} must be an object")
        principal_id = str(entry.get("principal_id") or "")
        if not _ID_PATTERN.match(principal_id):
            raise ConfigurationError(f"{label} has an invalid principal_id")
        tenant_id = str(entry.get("tenant_id") or "")
        if not _ID_PATTERN.match(tenant_id):
            raise ConfigurationError(f"{label} must be bound to a tenant_id")
        if "roles" in entry or "principal_type" in entry:
            raise ConfigurationError(
                f"{label}: roles and principal_type come from the tenant membership and user record, not the credential"
            )
        if (principal_id, tenant_id) in seen:
            raise ConfigurationError(f"{label} duplicates principal_id '{principal_id}' for tenant '{tenant_id}'")
        seen.add((principal_id, tenant_id))
        token_hash = str(entry.get("token_sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", token_hash):
            raise ConfigurationError(f"{label} must provide token_sha256 (a 64-character lowercase hex SHA-256)")
        if token_hash in hashes:
            raise ConfigurationError(f"{label} reuses a token hash: every credential needs its own token")
        hashes.add(token_hash)


def _unauthorized(detail: str = "Authentication required") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def authenticate_token(token: str, settings: Settings) -> Principal | None:
    """Constant-time lookup: every configured hash is compared, with no early exit.

    The result is a Principal only when the credential's tenant, user and membership are all active; the roles are
    the membership's. An unknown token returns ``None`` (401). A known token without an active membership raises 403.
    """
    from app.repositories.tenant_repository import TenantRepository  # local import: avoids a module cycle

    candidate = hash_token(token)
    matched: dict[str, Any] | None = None
    for entry in settings.api_credentials:
        if hmac.compare_digest(candidate, str(entry.get("token_sha256", ""))):
            matched = entry
    if matched is None:
        return None
    membership = TenantRepository(settings.database_url).resolve_active_membership(
        str(matched["tenant_id"]), str(matched["principal_id"])
    )
    if membership is None:
        raise _forbidden("No active tenant membership for this credential")
    return Principal(
        principal_id=membership.user_id,
        user_id=membership.user_id,
        principal_type=PrincipalType(membership.user_type),
        display_name=membership.display_name,
        roles=membership.roles,
        tenant_id=membership.tenant_id,
        auth_method="api_key",
    )


def _dev_principal(header_value: str | None, settings: Settings) -> Principal:
    """Dev-only identity. ``X-Dev-Principal: <type>:<id>:<role>+<role>[:<tenant>]`` (e.g. ``human:alice:reviewer+sre``).

    The tenant defaults to the ``dev`` tenant. A named tenant must exist and be active. The dev identity is a
    development convenience that stands in for credential + membership; real tenant-membership enforcement is
    exercised with bearer credentials.
    """
    from app.repositories.tenant_repository import TenantRepository  # local import: avoids a module cycle

    tenant_id = DEV_TENANT_ID
    if not header_value:
        principal_id, kind, roles = "dev-admin", PrincipalType.HUMAN, ("admin",)
    else:
        parts = header_value.split(":")
        if len(parts) not in {3, 4} or parts[0] not in {t.value for t in PrincipalType} or not _ID_PATTERN.match(parts[1]):
            raise _unauthorized("Invalid development principal")
        principal_id, kind = parts[1], PrincipalType(parts[0])
        roles = tuple(r for r in parts[2].split("+") if r)
        if len(parts) == 4:
            tenant_id = parts[3]
    tenant = TenantRepository(settings.database_url).get_tenant(tenant_id) if _ID_PATTERN.match(tenant_id) else None
    if tenant is None or tenant.status != "active":
        raise _unauthorized("Invalid development principal")
    return Principal(principal_id=principal_id, principal_type=kind, display_name=principal_id, roles=roles,
                     tenant_id=tenant_id, auth_method="dev")


async def get_principal(request: Request) -> Principal:
    """FastAPI dependency: authenticate the request or raise 401. Applied at router level (deny by default)."""
    settings = get_settings()
    authorization = request.headers.get("authorization")
    principal: Principal | None = None
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not _TOKEN_PATTERN.match(token.strip()):
            raise _unauthorized()
        principal = authenticate_token(token.strip(), settings)
        if principal is None:
            raise _unauthorized()
    elif settings.auth_mode == AUTH_MODE_DEV and settings.is_development:
        principal = _dev_principal(request.headers.get(DEV_HEADER), settings)
    else:
        # apikey mode, or any non-development environment: the dev header is never honoured
        raise _unauthorized()
    request.state.principal = principal
    from app.core.request_context import bind_principal  # local import: avoids a module cycle

    bind_principal(principal)
    return principal


def require_permission(permission: Permission) -> Callable[..., Principal]:
    async def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if not principal.has(permission):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Not authorized: {permission.value} required")
        return principal

    return dependency


def identity_context_for(principal: Principal):
    """Derive the Phase 5/6 agent ``IdentityContext`` from the authenticated principal (never from request fields)."""
    from app.agent.service import IdentityContext

    return IdentityContext(
        tenant_id=principal.tenant_id,  # from the authenticated membership; neither the model nor the request chooses it
        user_id=principal.user_id,
        roles=list(principal.roles),
        permissions=sorted(p.value for p in principal.permissions),
    )
