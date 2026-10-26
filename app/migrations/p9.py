"""Explicit P9.1 migration: the ``investigations`` table and a backfill of pre-P9 investigation results.

    python -m app.migrations.p9 sqlite:///./pulseops.db

Normal application startup only ever *adds* the empty ``investigations`` table (``CREATE TABLE IF NOT EXISTS``); it
never alters, rebuilds, copies or drops anything. This tool is the controlled path for an existing database that
already holds workflows from before P9:

* it requires an already tenant-aware (Gate 9.1) database and refuses a pre-9.1 one (run ``gate9_1`` first),
* it only touches the database URL you pass,
* it writes a byte-for-byte backup first (``<name>.pre-p9.bak``; it refuses to overwrite one),
* it runs in one transaction (all or nothing) and verifies foreign keys before committing,
* it is idempotent: a second run finds nothing to do and changes nothing,
* backfill copies ONLY ``INVESTIGATION_COMPLETED`` audit results that are structurally valid and grounded (they carry
  evidence). Degraded or failed investigations were never "completed" and are never turned into records. Each record
  keeps its original tenant and timestamp and is marked ``source = 'backfill'``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime

from app.database import SCHEMA_STATEMENTS, legacy_tables, resolve_database_path
from app.repositories.incident_repository import InvestigationRepository

_LISTS = ("evidence", "hypotheses", "missing_information", "recommendations", "tool_calls")
_TABLE_STATEMENT = next(s for s in SCHEMA_STATEMENTS if "CREATE TABLE IF NOT EXISTS investigations" in s)


class MigrationError(RuntimeError):
    pass


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _candidates(connection: sqlite3.Connection, table_exists: bool) -> list[sqlite3.Row]:
    """COMPLETED audit events whose workflow has no investigation record yet."""
    if "workflow_audit_events" not in _tables(connection):
        return []
    anti_join = (
        " AND NOT EXISTS (SELECT 1 FROM investigations i WHERE i.tenant_id = a.tenant_id AND i.workflow_id = a.workflow_id)"
        if table_exists else ""
    )
    return connection.execute(
        "SELECT a.tenant_id, a.workflow_id, a.incident_id, a.timestamp, a.details FROM workflow_audit_events a"
        " JOIN workflow_instances w ON w.tenant_id = a.tenant_id AND w.workflow_id = a.workflow_id"
        f" WHERE a.event_type = 'INVESTIGATION_COMPLETED'{anti_join} ORDER BY a.timestamp ASC, a.rowid ASC"  # nosec B608 - anti_join is a constant fragment
    ).fetchall()


def _valid_result(row: sqlite3.Row) -> dict | None:
    try:
        metadata = json.loads(row["details"] or "{}")
        result = metadata.get("investigation")
        datetime.fromisoformat(row["timestamp"])
    except (ValueError, TypeError, AttributeError):
        return None
    if not isinstance(result, dict) or result.get("incident_id") != row["incident_id"]:
        return None
    if not InvestigationRepository._strings(result.get("evidence")):  # not grounded: never stored
        return None
    return result


def migrate(database_url: str) -> dict[str, int]:
    """Create the table if missing and backfill. Returns counts; an empty dict means there was nothing to do."""
    path = resolve_database_path(database_url)
    if not path.exists():
        raise MigrationError(f"database file not found: {path}")
    connection = sqlite3.connect(path, isolation_level=None)  # explicit transaction control
    connection.row_factory = sqlite3.Row
    try:
        stale = legacy_tables(connection)
        if stale:
            raise MigrationError(
                f"database uses the pre-Gate-9.1 schema (no tenant_id on: {', '.join(stale)}); "
                "run 'python -m app.migrations.gate9_1 <database-url>' first"
            )
        if "workflow_instances" not in _tables(connection):
            raise MigrationError("not a PulseOps database (no workflow_instances table)")
        table_exists = "investigations" in _tables(connection)
        candidates = _candidates(connection, table_exists)
        if table_exists and not candidates:
            return {}
        backup = path.with_name(path.name + ".pre-p9.bak")
        if backup.exists():
            raise MigrationError(f"backup already exists: {backup}; move it away first")
        shutil.copy2(path, backup)

        counts = {"table_created": 0 if table_exists else 1, "backfilled": 0, "skipped": 0}
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(_TABLE_STATEMENT)
            for row in candidates:
                result = _valid_result(row)
                if result is None:
                    counts["skipped"] += 1
                    continue
                try:
                    confidence = min(1.0, max(0.0, float(result.get("confidence") or 0.0)))
                except (TypeError, ValueError):
                    confidence = 0.0
                lists = {name: json.dumps(InvestigationRepository._strings(result.get(name))) for name in _LISTS}
                connection.execute(
                    """
                    INSERT INTO investigations (
                        tenant_id, investigation_id, incident_id, workflow_id, service_id, summary, evidence, hypotheses,
                        missing_information, recommendations, confidence, tool_calls, source, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'backfill', ?)
                    """,
                    (
                        row["tenant_id"], f"INV-BF-{row['workflow_id'].removeprefix('WF-')}", row["incident_id"],
                        row["workflow_id"], str(result.get("service_id") or "unknown"), str(result.get("summary") or ""),
                        lists["evidence"], lists["hypotheses"], lists["missing_information"], lists["recommendations"],
                        confidence, lists["tool_calls"], row["timestamp"],
                    ),
                )
                counts["backfilled"] += 1
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise MigrationError("foreign-key violations after migration; rolled back")
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        return counts
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.migrations.p9", description=__doc__.split("\n\n")[0])
    parser.add_argument("database_url", help="SQLite URL of the database to migrate, e.g. sqlite:///./pulseops.db")
    args = parser.parse_args(argv)
    try:
        counts = migrate(args.database_url)
    except MigrationError as exc:
        print(f"migration failed: {exc}", file=sys.stderr)
        return 1
    except sqlite3.Error as exc:
        print(f"migration failed (database error, rolled back): {type(exc).__name__}", file=sys.stderr)
        return 1
    if not counts:
        print("nothing to migrate: the investigations table exists and no pre-P9 results need backfilling")
        return 0
    print(f"investigations table created: {bool(counts['table_created'])}; backfilled: {counts['backfilled']}; "
          f"skipped (not grounded/invalid): {counts['skipped']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
