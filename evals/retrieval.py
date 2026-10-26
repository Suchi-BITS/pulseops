"""Deterministic retrieval-tool ground truth (Gate 8).

Verifies *expected retrieval vs actual retrieval* for the four controlled tools over an eval-only fixture, through the
real PulseOps MCP server. No vector search, no LLM, no network. A check's score is the fraction of its atomic
expectations that hold; it passes only at 1.0.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from app.database import DatabaseManager
from app.mcp.server import build_mcp_server
from evals.contracts import MetricAggregate, RetrievalCheckResult
from evals.hashing import file_sha256
from evals.harness import _TENANT, _TS, ensure_non_empty_tables

RETRIEVAL_DATASET_PATH = Path(__file__).parent / "datasets" / "retrieval_ground_truth.json"
RETRIEVAL_METRIC = "retrieval_correctness"


def load_retrieval_dataset(path: Path = RETRIEVAL_DATASET_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def retrieval_dataset_sha256(path: Path = RETRIEVAL_DATASET_PATH) -> str:
    return file_sha256(path)


def build_retrieval_database(fixture: dict[str, Any], directory: Path) -> str:
    path = directory / "retrieval-ground-truth.db"
    url = "sqlite:" + path.as_posix()
    DatabaseManager(url)  # schema + default seed (services, repository mapping)
    with sqlite3.connect(path) as db:
        for table in ("logs", "metrics", "deployments", "incidents"):
            db.execute(f"DELETE FROM {table}")  # temp eval DB only
        for svc in fixture.get("services", []):
            db.execute(
                "INSERT INTO services (tenant_id, service_id, service_name, owner_team, environment, repository_id, description,"
                " created_at) VALUES (?,?,?,?,?,?,?,?)",
                (_TENANT, svc["service_id"], svc.get("service_name", svc["service_id"]), "eval",
                 svc.get("environment", "production"), None, None, _TS),
            )
        for inc in fixture["incidents"]:
            db.execute(
                "INSERT INTO incidents (tenant_id, incident_id, service_id, severity, status, title, description, environment,"
                " started_at, resolved_at, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (_TENANT, inc["incident_id"], inc["service_id"], inc.get("severity", "high"), "open", inc["title"],
                 inc.get("description", inc["title"]), "production", _TS, None, _TS, _TS),
            )
            for log in inc.get("logs", []):
                db.execute(
                    "INSERT INTO logs (tenant_id, log_id, incident_id, service_id, timestamp, level, message, source, metadata)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (_TENANT, log["log_id"], inc["incident_id"], inc["service_id"], _TS, "error", log["message"], "eval", None),
                )
            for m in inc.get("metrics", []):
                db.execute(
                    "INSERT INTO metrics (tenant_id, metric_id, incident_id, service_id, timestamp, metric_name, value, unit,"
                    " source) VALUES (?,?,?,?,?,?,?,?,?)",
                    (_TENANT, m["metric_id"], inc["incident_id"], inc["service_id"], _TS, m["metric_name"], m["value"],
                     m.get("unit"), "eval"),
                )
        for d in fixture.get("deployments", []):
            db.execute(
                "INSERT INTO deployments (tenant_id, deployment_id, service_id, version, commit_sha, environment, deployed_at,"
                " deployed_by, status) VALUES (?,?,?,?,?,?,?,?,?)",
                (_TENANT, d["deployment_id"], d["service_id"], d["version"], None, "production", _TS, "eval", "successful"),
            )
        ensure_non_empty_tables(db)
    return url


async def _call(database_url: str, tool: str, arguments: dict[str, Any]) -> tuple[bool, Any]:
    """(ok, value). The value is the tool's structured output with the MCP 'result' wrapper removed."""
    server = build_mcp_server(database_url=database_url, tenant_id=_TENANT)
    try:
        result = await server.call_tool(tool, arguments)
    except Exception as exc:  # ToolError for not-found, or a masked tool failure
        return False, str(getattr(exc, "__cause__", None) or exc)
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict) and set(structured) == {"result"}:
        return True, structured["result"]
    if structured is not None:
        return True, structured
    return True, json.loads(result.content[0].text) if result.content else None


def _same(actual: Any, expected: Any, *, unordered: bool) -> bool:
    if unordered and isinstance(actual, list) and isinstance(expected, list):
        return sorted(map(str, actual)) == sorted(map(str, expected))
    return actual == expected


def _evaluate(ok: bool, value: Any, expect: dict[str, Any]) -> tuple[list[bool], list[str]]:
    outcomes: list[bool] = []
    problems: list[str] = []

    def check(condition: bool, message: str) -> None:
        outcomes.append(condition)
        if not condition:
            problems.append(message)

    if "error_contains" in expect:
        check(not ok and expect["error_contains"].lower() in str(value).lower(),
              f"expected an error containing {expect['error_contains']!r}, got ok={ok} value={str(value)[:120]!r}")
        return outcomes, problems
    check(ok, f"tool call failed: {str(value)[:120]}")
    if not ok:
        return outcomes, problems
    if "value" in expect:
        check(_same(value, expect["value"], unordered=expect.get("unordered", False)),
              f"expected {expect['value']!r}, got {value!r}")
    unordered_fields = set(expect.get("unordered_fields", []))
    for field_name, wanted in expect.get("fields", {}).items():
        actual = value.get(field_name) if isinstance(value, dict) else None
        check(_same(actual, wanted, unordered=field_name in unordered_fields),
              f"field {field_name}: expected {wanted!r}, got {actual!r}")
    if "evidence_source_ids_include" in expect or "evidence_source_ids_exclude" in expect:
        items = ((value or {}).get("context") or {}).get("evidence", []) if isinstance(value, dict) else []
        source_ids = {str(item.get("source_id")) for item in items if isinstance(item, dict)}
        for wanted in expect.get("evidence_source_ids_include", []):
            check(wanted in source_ids, f"evidence is missing source {wanted!r}")
        for forbidden in expect.get("evidence_source_ids_exclude", []):
            check(forbidden not in source_ids, f"evidence leaks unrelated source {forbidden!r}")
    return outcomes, problems


def run_retrieval_checks(path: Path = RETRIEVAL_DATASET_PATH) -> list[RetrievalCheckResult]:
    dataset = load_retrieval_dataset(path)

    async def go(directory: Path) -> list[RetrievalCheckResult]:
        url = build_retrieval_database(dataset["fixture"], directory)
        results: list[RetrievalCheckResult] = []
        for check in dataset["checks"]:
            ok, value = await _call(url, check["tool"], check["arguments"])
            outcomes, problems = _evaluate(ok, value, check["expect"])
            score = sum(outcomes) / len(outcomes) if outcomes else 0.0
            details = list(problems)
            if check.get("observation") and not problems:
                details.append(f"OBSERVATION: {check['observation']}")
            results.append(RetrievalCheckResult(
                check_id=check["check_id"], tool=check["tool"], score=round(score, 4), passed=score >= 1.0,
                details=details,
            ))
        return results

    with tempfile.TemporaryDirectory(prefix="pulseops-eval-retrieval-", ignore_cleanup_errors=True) as tmp:
        return asyncio.run(go(Path(tmp)))


def aggregate_retrieval(results: list[RetrievalCheckResult]) -> MetricAggregate:
    if not results:
        return MetricAggregate(metric=RETRIEVAL_METRIC, applicable_cases=0, mean_score=None, pass_rate=None)
    return MetricAggregate(
        metric=RETRIEVAL_METRIC,
        applicable_cases=len(results),
        mean_score=round(sum(r.score for r in results) / len(results), 4),
        pass_rate=round(sum(1 for r in results if r.passed) / len(results), 4),
        failed_cases=[r.check_id for r in results if not r.passed],
    )
