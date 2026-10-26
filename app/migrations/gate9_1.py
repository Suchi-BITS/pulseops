"""One-time migration of a pre-Gate-9.1 SQLite database to the tenant-aware schema.

    python -m app.migrations.gate9_1 sqlite:///./pulseops.db [--tenant-id dev] [--tenant-name "Development tenant"]

Normal application startup NEVER rebuilds tables: it refuses to run against a pre-9.1 file (``LegacySchemaError``).
This tool is the explicit, controlled alternative. It

* only touches the database URL you pass (never a path it finds on its own),
* writes a byte-for-byte backup next to the file first (``<name>.pre-gate9_1.bak``; it refuses to overwrite one),
* does all schema and data changes in a single transaction (rolled back entirely on any error or FK violation),
* assigns every existing row to one tenant (default ``dev``) and verifies the row counts afterwards.

Users, tenants and memberships are catalog data and are created separately (see docs/phase-7-gate-9.1-implementation.md).
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime, timezone

from app.core.config import DEV_TENANT_ID
from app.database import SCHEMA_STATEMENTS, TENANT_OWNED_TABLES, legacy_tables, resolve_database_path

# Parents before children, so foreign keys are satisfiable while copying.
_COPY_ORDER = (
    "services", "repositories", "incidents", "repository_mappings", "logs", "metrics", "deployments",
    "workflow_instances", "workflow_decisions", "workflow_audit_events", "workflow_idempotency_keys",
    "operational_events",
)
assert set(_COPY_ORDER) == set(TENANT_OWNED_TABLES)  # nosec B101 - import-time sanity check, not an access control


class MigrationError(RuntimeError):
    pass


def _columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]


def migrate(database_url: str, *, tenant_id: str = DEV_TENANT_ID, tenant_name: str = "Development tenant") -> dict[str, int]:
    """Migrate in place (after a backup). Returns ``{table: rows migrated}``; empty if already migrated."""
    path = resolve_database_path(database_url)
    if not path.exists():
        raise MigrationError(f"database file not found: {path}")
    connection = sqlite3.connect(path, isolation_level=None)  # explicit transaction control
    connection.row_factory = sqlite3.Row
    try:
        stale = legacy_tables(connection)
        if not stale:
            return {}
        if set(stale) != {t for t in TENANT_OWNED_TABLES if _columns(connection, t)}:
            raise MigrationError("database is partially migrated; refusing to guess. Restore a backup and retry.")
        backup = path.with_name(path.name + ".pre-gate9_1.bak")
        if backup.exists():
            raise MigrationError(f"backup already exists: {backup}; move it away first")
        shutil.copy2(path, backup)

        counts: dict[str, int] = {}
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("PRAGMA legacy_alter_table = ON")  # renaming must not rewrite other tables' references
        connection.execute("BEGIN IMMEDIATE")
        try:
            for table in stale:
                connection.execute(f"ALTER TABLE {table} RENAME TO _legacy_{table}")
            for statement in SCHEMA_STATEMENTS:
                connection.execute(statement)
            now = datetime.now(timezone.utc).isoformat()
            connection.execute(
                "INSERT OR IGNORE INTO tenants (tenant_id, tenant_name, status, created_at, updated_at)"
                " VALUES (?, ?, 'active', ?, ?)",
                (tenant_id, tenant_name, now, now),
            )
            for table in _COPY_ORDER:
                if table not in stale:
                    continue
                shared = [c for c in _columns(connection, f"_legacy_{table}") if c in _columns(connection, table)]
                column_list = ", ".join(shared)
                # nosec B608 - identifiers come from the fixed TENANT_OWNED_TABLES constant and PRAGMA table_info, never from input
                connection.execute(
                    f"INSERT INTO {table} (tenant_id, {column_list}) SELECT ?, {column_list} FROM _legacy_{table}",  # nosec B608
                    (tenant_id,),
                )
                before = connection.execute(f"SELECT COUNT(*) FROM _legacy_{table}").fetchone()[0]  # nosec B608 - constant table names
                after = connection.execute(f"SELECT COUNT(*) FROM {table} WHERE tenant_id = ?", (tenant_id,)).fetchone()[0]  # nosec B608
                if before != after:
                    raise MigrationError(f"row count mismatch in {table}: {before} -> {after}")
                counts[table] = after
            for table in stale:
                connection.execute(f"DROP TABLE _legacy_{table}")
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise MigrationError(
                    "foreign-key violations after migration (" + ", ".join(sorted({row[0] for row in violations})) + ")"
                )
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        return counts
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.migrations.gate9_1", description=__doc__.split("\n\n")[0])
    parser.add_argument("database_url", help="SQLite URL of the database to migrate, e.g. sqlite:///./pulseops.db")
    parser.add_argument("--tenant-id", default=DEV_TENANT_ID, help="tenant that will own the existing rows (default: dev)")
    parser.add_argument("--tenant-name", default="Development tenant")
    args = parser.parse_args(argv)
    try:
        counts = migrate(args.database_url, tenant_id=args.tenant_id, tenant_name=args.tenant_name)
    except MigrationError as exc:
        print(f"migration failed: {exc}", file=sys.stderr)
        return 1
    if not counts:
        print("nothing to migrate: the database is already tenant-aware")
        return 0
    for table, n in counts.items():
        print(f"{table}: {n} row(s) assigned to tenant '{args.tenant_id}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
