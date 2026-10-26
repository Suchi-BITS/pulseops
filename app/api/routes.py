from __future__ import annotations

import os
import sqlite3

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.errors import ErrorResponse
from app.core.request_context import get_request_id
from app.core.security import Principal, get_principal
from app.database import DatabaseManager, resolve_database_path
from app.models.schemas import MeResponse, ReadinessResponse
from app.repositories.tenant_repository import TenantRepository

router = APIRouter()
settings = get_settings()

# Tables the running application cannot work without. A readiness failure never reveals the path or the SQLite error.
REQUIRED_TABLES = frozenset({"tenants", "users", "tenant_users", "incidents", "workflow_instances", "investigations"})


@router.get("/health")
async def health() -> dict[str, str | bool]:
    """Liveness: the process is up. Does not touch the database."""
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
        "debug": settings.debug,
    }


def _database_ready() -> bool:
    """A real check: open the configured database, prove it is writable, and confirm the schema is present."""
    try:
        database_url = get_settings().database_url
        DatabaseManager(database_url)  # idempotent, additive initialisation; refuses a pre-Gate-9.1 database (LegacySchemaError)
        path = resolve_database_path(database_url)
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=rw", uri=True, timeout=2, isolation_level=None)
        try:
            connection.execute("SELECT 1").fetchone()
            # P11: SQLite silently opens a write-protected file read-only even with mode=rw, which would report "ready"
            # while every write fails. Writability of the file and its directory (the journal lives there) is checked
            # without writing anything, and taking the write lock proves no other writer is holding the database.
            if not (os.access(path, os.W_OK) and os.access(path.parent, os.W_OK)):
                return False
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("ROLLBACK")
            present = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        finally:
            connection.close()
        return REQUIRED_TABLES <= present
    except Exception:  # noqa: BLE001 - readiness reports ready/not ready, never the cause
        return False


@router.get("/health/ready", response_model=ReadinessResponse, responses={503: {"model": ErrorResponse}})
async def ready():
    """Readiness: the application can serve requests (database reachable and schema present). Unauthenticated, no secrets."""
    if _database_ready():
        return ReadinessResponse(status="ready", checks={"database": "ok"})
    return JSONResponse(
        status_code=503,
        content={"detail": "Service not ready", "code": "not_ready", "request_id": get_request_id(),
                 "status": "not_ready", "checks": {"database": "error"}},
    )


@router.get("/me", response_model=MeResponse)
async def me(principal: Principal = Depends(get_principal)) -> MeResponse:
    """The authenticated caller's identity, tenant and effective permissions. Never contains a token or credential."""
    tenant = TenantRepository(get_settings().database_url).get_tenant(principal.tenant_id)
    return MeResponse(
        principal_id=principal.principal_id,
        user_id=principal.user_id,
        display_name=principal.display_name,
        principal_type=principal.principal_type.value,
        is_human=principal.is_human,
        tenant_id=principal.tenant_id,
        tenant_name=tenant.tenant_name if tenant else None,
        roles=list(principal.roles),
        permissions=sorted(p.value for p in principal.permissions),
        auth_method=principal.auth_method,
    )
