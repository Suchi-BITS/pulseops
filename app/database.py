from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from app.core.config import DEV_TENANT_ID, get_settings
from app.data.seed import (
    DEPLOYMENT_SEED,
    INCIDENT_SEED,
    LOG_SEED,
    METRIC_SEED,
    REPOSITORY_MAPPING_SEED,
    REPOSITORY_SEED,
    SERVICE_SEED,
)

# Roles a TenantUser membership may hold. Must equal the static RBAC roles in app.core.security (tested).
TENANT_ROLES = ("service_n8n", "reviewer", "operator", "admin")
USER_TYPES = ("human", "service", "agent", "system")

# Tables that carry business data owned by exactly one tenant (Gate 9.1). A database whose copy of any of these lacks
# ``tenant_id`` is a pre-9.1 database and must be migrated explicitly (python -m app.migrations.gate9_1).
TENANT_OWNED_TABLES = (
    "services", "incidents", "logs", "metrics", "deployments", "repositories", "repository_mappings",
    "workflow_instances", "workflow_decisions", "workflow_audit_events", "workflow_idempotency_keys",
    "operational_events",
)


class LegacySchemaError(RuntimeError):
    """The database predates the Gate 9.1 tenant model. Startup never rebuilds tables silently."""


def resolve_database_path(database_url: str) -> Path:
    """Resolve a SQLite URL to an absolute file path.

    ``sqlite:///rel/x.db`` is relative to the current working directory, ``sqlite:////abs/x.db`` is absolute
    (the usual SQLite URL convention). The legacy ``sqlite:/abs/x.db`` and ``sqlite:C:/abs/x.db`` forms are kept.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise ValueError("Only SQLite database URLs are supported in Phase 1")
    if database_url.startswith("sqlite:////"):
        path = Path("/" + parsed.path.lstrip("/"))
    elif database_url.startswith("sqlite:///"):
        path = Path(parsed.path[1:])
    else:
        path = Path(parsed.path)
    return path.expanduser().absolute()


def absolute_sqlite_url(database_url: str) -> str:
    """Absolute, working-directory-independent form of a SQLite URL (for subprocesses)."""
    return "sqlite:" + resolve_database_path(database_url).as_posix()


_ROLE_LIST = ", ".join(f"'{r}'" for r in TENANT_ROLES)
_TYPE_LIST = ", ".join(f"'{t}'" for t in USER_TYPES)

# Tenant-scoped identifiers (incident_id, service_id, event_id, idempotency_key ...) are unique per tenant, not
# globally, so those tables use an internal surrogate row key plus UNIQUE (tenant_id, <business id>). Child tables
# reference the parent through the composite (tenant_id, id) key, so a cross-tenant reference cannot exist.
# Workflow ids are generated globally-unique identifiers and keep their existing primary key.
SCHEMA_STATEMENTS = (
    f"""
    CREATE TABLE IF NOT EXISTS tenants (
        tenant_id TEXT PRIMARY KEY,
        tenant_name TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    f"""
    CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        email TEXT UNIQUE,
        display_name TEXT NOT NULL,
        user_type TEXT NOT NULL DEFAULT 'human' CHECK (user_type IN ({_TYPE_LIST})),
        status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    f"""
    CREATE TABLE IF NOT EXISTS tenant_users (
        tenant_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ({_ROLE_LIST})),
        domain_roles TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (tenant_id, user_id),
        FOREIGN KEY(tenant_id) REFERENCES tenants(tenant_id),
        FOREIGN KEY(user_id) REFERENCES users(user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS services (
        row_id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL,
        service_id TEXT NOT NULL,
        service_name TEXT NOT NULL,
        owner_team TEXT NOT NULL,
        environment TEXT NOT NULL,
        repository_id TEXT,
        description TEXT,
        created_at TEXT NOT NULL,
        UNIQUE (tenant_id, service_id),
        FOREIGN KEY(tenant_id) REFERENCES tenants(tenant_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS incidents (
        row_id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL,
        incident_id TEXT NOT NULL,
        service_id TEXT NOT NULL,
        severity TEXT NOT NULL,
        status TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        environment TEXT NOT NULL,
        started_at TEXT NOT NULL,
        resolved_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (tenant_id, incident_id),
        FOREIGN KEY(tenant_id) REFERENCES tenants(tenant_id),
        FOREIGN KEY(tenant_id, service_id) REFERENCES services(tenant_id, service_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS logs (
        row_id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL,
        log_id TEXT NOT NULL,
        incident_id TEXT,
        service_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        level TEXT NOT NULL,
        message TEXT NOT NULL,
        source TEXT NOT NULL,
        metadata TEXT,
        UNIQUE (tenant_id, log_id),
        FOREIGN KEY(tenant_id) REFERENCES tenants(tenant_id),
        FOREIGN KEY(tenant_id, service_id) REFERENCES services(tenant_id, service_id),
        FOREIGN KEY(tenant_id, incident_id) REFERENCES incidents(tenant_id, incident_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS metrics (
        row_id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL,
        metric_id TEXT NOT NULL,
        incident_id TEXT,
        service_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        metric_name TEXT NOT NULL,
        value REAL NOT NULL,
        unit TEXT,
        source TEXT NOT NULL,
        UNIQUE (tenant_id, metric_id),
        FOREIGN KEY(tenant_id) REFERENCES tenants(tenant_id),
        FOREIGN KEY(tenant_id, service_id) REFERENCES services(tenant_id, service_id),
        FOREIGN KEY(tenant_id, incident_id) REFERENCES incidents(tenant_id, incident_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS deployments (
        row_id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL,
        deployment_id TEXT NOT NULL,
        service_id TEXT NOT NULL,
        version TEXT NOT NULL,
        commit_sha TEXT,
        environment TEXT NOT NULL,
        deployed_at TEXT NOT NULL,
        deployed_by TEXT,
        status TEXT NOT NULL,
        UNIQUE (tenant_id, deployment_id),
        FOREIGN KEY(tenant_id) REFERENCES tenants(tenant_id),
        FOREIGN KEY(tenant_id, service_id) REFERENCES services(tenant_id, service_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS repositories (
        row_id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL,
        repository_id TEXT NOT NULL,
        provider TEXT NOT NULL,
        owner TEXT NOT NULL,
        name TEXT NOT NULL,
        default_branch TEXT NOT NULL,
        access_mode TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        UNIQUE (tenant_id, repository_id),
        FOREIGN KEY(tenant_id) REFERENCES tenants(tenant_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS repository_mappings (
        row_id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL,
        mapping_id TEXT NOT NULL,
        service_id TEXT NOT NULL,
        repository_id TEXT NOT NULL,
        branch TEXT NOT NULL,
        path_prefix TEXT,
        active INTEGER NOT NULL DEFAULT 1,
        UNIQUE (tenant_id, mapping_id),
        FOREIGN KEY(tenant_id) REFERENCES tenants(tenant_id),
        FOREIGN KEY(tenant_id, service_id) REFERENCES services(tenant_id, service_id),
        FOREIGN KEY(tenant_id, repository_id) REFERENCES repositories(tenant_id, repository_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workflow_instances (
        workflow_id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        incident_id TEXT NOT NULL,
        action TEXT NOT NULL,
        status TEXT NOT NULL,
        risk_level TEXT NOT NULL,
        policy_decision TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        requested_by TEXT NOT NULL,
        details TEXT,
        requires_approval INTEGER NOT NULL DEFAULT 0,
        UNIQUE (tenant_id, workflow_id),
        FOREIGN KEY(tenant_id) REFERENCES tenants(tenant_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workflow_decisions (
        decision_id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        workflow_id TEXT NOT NULL,
        decision TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        actor_type TEXT NOT NULL,
        reason TEXT,
        timestamp TEXT NOT NULL,
        FOREIGN KEY(tenant_id, workflow_id) REFERENCES workflow_instances(tenant_id, workflow_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workflow_audit_events (
        audit_id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        workflow_id TEXT NOT NULL,
        incident_id TEXT NOT NULL,
        event_id TEXT,
        event_type TEXT NOT NULL,
        actor_type TEXT,
        actor_id TEXT,
        timestamp TEXT NOT NULL,
        details TEXT,
        FOREIGN KEY(tenant_id, workflow_id) REFERENCES workflow_instances(tenant_id, workflow_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workflow_idempotency_keys (
        row_id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        workflow_id TEXT NOT NULL,
        incident_id TEXT NOT NULL,
        action TEXT NOT NULL,
        request_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (tenant_id, idempotency_key),
        FOREIGN KEY(tenant_id, workflow_id) REFERENCES workflow_instances(tenant_id, workflow_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS operational_events (
        row_id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        request_hash TEXT NOT NULL,
        state TEXT NOT NULL,
        incident_id TEXT,
        workflow_id TEXT,
        created_at TEXT NOT NULL,
        UNIQUE (tenant_id, event_id),
        FOREIGN KEY(tenant_id) REFERENCES tenants(tenant_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS investigations (
        row_id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL,
        investigation_id TEXT NOT NULL,
        incident_id TEXT NOT NULL,
        workflow_id TEXT NOT NULL,
        service_id TEXT NOT NULL,
        summary TEXT NOT NULL,
        evidence TEXT NOT NULL,
        hypotheses TEXT NOT NULL,
        missing_information TEXT NOT NULL,
        recommendations TEXT NOT NULL,
        confidence REAL NOT NULL,
        tool_calls TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'workflow',
        created_at TEXT NOT NULL,
        UNIQUE (tenant_id, investigation_id),
        UNIQUE (tenant_id, workflow_id),
        FOREIGN KEY(tenant_id, workflow_id) REFERENCES workflow_instances(tenant_id, workflow_id)
    )
    """,
)


def legacy_tables(connection: sqlite3.Connection) -> list[str]:
    """Tenant-owned tables that exist without a ``tenant_id`` column (a pre-Gate-9.1 schema)."""
    found: list[str] = []
    for table in TENANT_OWNED_TABLES:
        columns = [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
        if columns and "tenant_id" not in columns:
            found.append(table)
    return found


def ensure_dev_tenant(connection: sqlite3.Connection) -> None:
    """Development-only: the explicit ``dev`` tenant (and its admin membership) that owns the demo data."""
    now = datetime.now(timezone.utc).isoformat()
    connection.execute(
        "INSERT OR IGNORE INTO tenants (tenant_id, tenant_name, status, created_at, updated_at) VALUES (?, ?, 'active', ?, ?)",
        (DEV_TENANT_ID, "Development tenant", now, now),
    )
    connection.execute(
        "INSERT OR IGNORE INTO users (user_id, email, display_name, user_type, status, created_at, updated_at)"
        " VALUES ('dev-admin', NULL, 'Development admin', 'human', 'active', ?, ?)",
        (now, now),
    )
    connection.execute(
        "INSERT OR IGNORE INTO tenant_users (tenant_id, user_id, role, domain_roles, status, created_at, updated_at)"
        " VALUES (?, 'dev-admin', 'admin', '[]', 'active', ?, ?)",
        (DEV_TENANT_ID, now, now),
    )


class DatabaseManager:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.database_path = self._resolve_database_path(database_url)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @staticmethod
    def _resolve_database_path(database_url: str) -> Path:
        return resolve_database_path(database_url)

    def get_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.get_connection() as connection:
            stale = legacy_tables(connection)
            if stale:
                raise LegacySchemaError(
                    f"{self.database_path} uses the pre-Gate-9.1 schema (no tenant_id on: {', '.join(stale)}). "
                    "Startup never rebuilds tables. Run the explicit one-time migration "
                    "'python -m app.migrations.gate9_1 <database-url>' (it backs the file up first), or point "
                    "PULSEOPS_DATABASE_URL at a fresh database."
                )
            for statement in SCHEMA_STATEMENTS:
                connection.execute(statement)

            settings = get_settings()
            if settings.is_development or settings.seed_demo_data:
                ensure_dev_tenant(connection)
            if not settings.seed_demo_data:
                # Synthetic demo data is development-only (PULSEOPS_SEED_DEMO_DATA); never silently recreate it.
                return
            self._seed_dev_tenant(connection)

    @staticmethod
    def _seed_dev_tenant(connection: sqlite3.Connection) -> None:
        """Insert the synthetic demo data into the ``dev`` tenant (only when that tenant has none yet)."""
        tenant = DEV_TENANT_ID

        # All-or-nothing: the demo set is internally linked (mappings -> services, logs -> incidents ...), so it is
        # seeded only into a development tenant that has no services at all, never table by table into existing data.
        if connection.execute("SELECT COUNT(*) FROM services WHERE tenant_id = ?", (tenant,)).fetchone()[0] != 0:
            return

        for service in SERVICE_SEED:
            connection.execute(
                """
                INSERT INTO services (
                    tenant_id, service_id, service_name, owner_team, environment,
                    repository_id, description, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant,
                    service.service_id,
                    service.service_name,
                    service.owner_team,
                    service.environment,
                    service.repository_id,
                    service.description,
                    service.created_at.isoformat(),
                ),
            )

        for repository in REPOSITORY_SEED:
            connection.execute(
                """
                INSERT INTO repositories (
                    tenant_id, repository_id, provider, owner, name, default_branch,
                    access_mode, active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant,
                    repository.repository_id,
                    repository.provider,
                    repository.owner,
                    repository.name,
                    repository.default_branch,
                    repository.access_mode.value,
                    int(repository.active),
                ),
            )

        for mapping in REPOSITORY_MAPPING_SEED:
            connection.execute(
                """
                INSERT INTO repository_mappings (
                    tenant_id, mapping_id, service_id, repository_id, branch, path_prefix, active
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant,
                    mapping.mapping_id,
                    mapping.service_id,
                    mapping.repository_id,
                    mapping.branch,
                    mapping.path_prefix,
                    int(mapping.active),
                ),
            )

        for incident in INCIDENT_SEED:
            connection.execute(
                """
                INSERT INTO incidents (
                    tenant_id, incident_id, service_id, severity, status, title,
                    description, environment, started_at, resolved_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant,
                    incident.incident_id,
                    incident.service_id,
                    incident.severity.value,
                    incident.status.value,
                    incident.title,
                    incident.description,
                    incident.environment,
                    incident.started_at.isoformat(),
                    incident.resolved_at.isoformat() if incident.resolved_at else None,
                    incident.created_at.isoformat(),
                    incident.updated_at.isoformat(),
                ),
            )

        for log_entry in LOG_SEED:
            connection.execute(
                """
                INSERT INTO logs (
                    tenant_id, log_id, incident_id, service_id, timestamp, level,
                    message, source, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant,
                    log_entry.log_id,
                    log_entry.incident_id,
                    log_entry.service_id,
                    log_entry.timestamp.isoformat(),
                    log_entry.level.value,
                    log_entry.message,
                    log_entry.source,
                    json.dumps(log_entry.metadata) if log_entry.metadata is not None else None,
                ),
            )

        for metric in METRIC_SEED:
            connection.execute(
                """
                INSERT INTO metrics (
                    tenant_id, metric_id, incident_id, service_id, timestamp, metric_name,
                    value, unit, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant,
                    metric.metric_id,
                    metric.incident_id,
                    metric.service_id,
                    metric.timestamp.isoformat(),
                    metric.metric_name,
                    metric.value,
                    metric.unit,
                    metric.source,
                ),
            )

        for deployment in DEPLOYMENT_SEED:
            connection.execute(
                """
                INSERT INTO deployments (
                    tenant_id, deployment_id, service_id, version, commit_sha,
                    environment, deployed_at, deployed_by, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant,
                    deployment.deployment_id,
                    deployment.service_id,
                    deployment.version,
                    deployment.commit_sha,
                    deployment.environment,
                    deployment.deployed_at.isoformat(),
                    deployment.deployed_by,
                    deployment.status.value,
                ),
            )
