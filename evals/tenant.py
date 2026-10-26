"""P8.1 - tenant-isolation evaluation (system correctness/safety metric ``tenant_isolation``, must stay 1.00).

Deterministic and model-free. Two tenants share one temporary database and the *same logical identifiers* (an incident
id and a service id exist in both). Each check drives the real production components (MCP retrieval tools, tenant-scoped
repositories and services, the HITL decision function, the agent's MCP configuration, the tenant catalog) and asserts
that nothing crosses the tenant boundary. Score = fraction of atomic expectations met; a check passes at 1.0.

Observational only: nothing here changes tenancy, authorization or any production behaviour.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi import HTTPException

import app.api.workflow as workflow_api
from app.agent.service import IdentityContext, IncidentInvestigationAgent
from app.core.security import Principal, PrincipalType
from app.database import DatabaseManager
from app.graph.repository import GraphRepository
from app.mcp.server import build_mcp_server
from app.models.schemas import WorkflowDecisionRequest
from app.repositories.incident_repository import (
    IncidentRepository,
    OperationalEventRepository,
    ServiceRepository,
    WorkflowRepository,
)
from app.repositories.tenant_repository import TenantRepository
from app.services.incident_service import IncidentService
from app.services.workflow_service import WorkflowService
from evals.contracts import MetricAggregate, RetrievalCheckResult

TENANT_METRIC = "tenant_isolation"
TENANT_A, TENANT_B = "eval-tenant-a", "eval-tenant-b"
MARK_A, MARK_B = "A-ONLY-EVIDENCE-MARKER", "B-ONLY-EVIDENCE-MARKER"
_TS = "2026-09-29T09:30:00+00:00"
_ROLES = ("reviewer", "sre", "incident_manager")


def _insert(db: sqlite3.Connection, table: str, **values: Any) -> None:
    columns = ", ".join(values)
    db.execute(f"INSERT INTO {table} ({columns}) VALUES ({', '.join('?' for _ in values)})", tuple(values.values()))


def build_tenant_database(directory: Path) -> str:
    """Two tenants, the same ids in both (svc-payment, INC-T1), plus data that exists in tenant A only."""
    path = directory / "tenant-isolation.db"
    url = "sqlite:" + path.as_posix()
    DatabaseManager(url)
    catalog = TenantRepository(url)
    for tenant in (TENANT_A, TENANT_B):
        catalog.create_tenant(tenant, tenant)
    catalog.create_user("eval-u1", "Eval user one")
    catalog.add_membership(TENANT_A, "eval-u1", "reviewer", domain_roles=["sre"])  # reviewer in A ...
    catalog.add_membership(TENANT_B, "eval-u1", "operator")  # ... only an operator in B
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys = ON")
        for tenant in (TENANT_A, TENANT_B):
            _insert(db, "services", tenant_id=tenant, service_id="svc-payment", service_name="payment", owner_team="t",
                    environment="production", created_at=_TS)
            _insert(db, "incidents", tenant_id=tenant, incident_id="INC-T1", service_id="svc-payment", severity="high",
                    status="open", title="Shared id", description="same logical id in both tenants", environment="production",
                    started_at=_TS, created_at=_TS, updated_at=_TS)
        _insert(db, "services", tenant_id=TENANT_A, service_id="svc-only-a", service_name="only-a", owner_team="t",
                environment="production", created_at=_TS)
        _insert(db, "incidents", tenant_id=TENANT_A, incident_id="INC-A-ONLY", service_id="svc-only-a", severity="high",
                status="open", title="A only", description="exists only in tenant A", environment="production",
                started_at=_TS, created_at=_TS, updated_at=_TS)
        for tenant, marker in ((TENANT_A, MARK_A), (TENANT_B, MARK_B)):
            _insert(db, "logs", tenant_id=tenant, log_id="log-t1", incident_id="INC-T1", service_id="svc-payment",
                    timestamp=_TS, level="error", message=marker, source="eval")
    return url


class _Outcomes:
    def __init__(self) -> None:
        self.results: list[bool] = []
        self.problems: list[str] = []

    def expect(self, condition: bool, message: str) -> None:
        self.results.append(bool(condition))
        if not condition:
            self.problems.append(message)


async def _tool(url: str, tenant: str, name: str, arguments: dict[str, Any]) -> tuple[bool, str]:
    server = build_mcp_server(database_url=url, tenant_id=tenant)
    try:
        result = await server.call_tool(name, arguments)
    except Exception as exc:  # ToolError for not-found
        return False, str(getattr(exc, "__cause__", None) or exc)
    structured = getattr(result, "structured_content", None)
    return True, json.dumps(structured) if structured is not None else (result.content[0].text if result.content else "")


def check_mcp_same_id_isolation(url: str, o: _Outcomes) -> None:
    ok_a, text_a = asyncio.run(_tool(url, TENANT_A, "get_incident_context", {"incident_id": "INC-T1"}))
    ok_b, text_b = asyncio.run(_tool(url, TENANT_B, "get_incident_context", {"incident_id": "INC-T1"}))
    o.expect(ok_a and MARK_A in text_a and MARK_B not in text_a, "tenant A's MCP context must contain only A's evidence")
    o.expect(ok_b and MARK_B in text_b and MARK_A not in text_b, "tenant B's MCP context must contain only B's evidence")


def check_mcp_foreign_resources(url: str, o: _Outcomes) -> None:
    ok, _ = asyncio.run(_tool(url, TENANT_A, "get_incident_context", {"incident_id": "INC-A-ONLY"}))
    o.expect(ok, "tenant A can read its own incident")
    ok, text = asyncio.run(_tool(url, TENANT_B, "get_incident_context", {"incident_id": "INC-A-ONLY"}))
    o.expect(not ok and "not found" in text.lower(), "tenant B must get 'not found' for tenant A's incident")
    _, related = asyncio.run(_tool(url, TENANT_B, "get_related_incidents", {"service_id": "svc-payment"}))
    o.expect("INC-A-ONLY" not in related, "tenant B's related incidents must not list tenant A's incident")
    _, related_foreign = asyncio.run(_tool(url, TENANT_B, "get_related_incidents", {"service_id": "svc-only-a"}))
    o.expect("INC-A-ONLY" not in related_foreign, "tenant B must not enumerate incidents of tenant A's service")
    _, deps = asyncio.run(_tool(url, TENANT_B, "get_service_dependencies", {"service_id": "svc-only-a"}))
    o.expect(json.loads(deps or "null") in ([], {"result": []}, None), "tenant B must see no dependencies for tenant A's service")


def check_repository_scoping(url: str, o: _Outcomes) -> None:
    o.expect(IncidentRepository(url, TENANT_A).get_incident("INC-A-ONLY") is not None, "tenant A reads its own incident")
    o.expect(IncidentRepository(url, TENANT_B).get_incident("INC-A-ONLY") is None, "tenant B must not read tenant A's incident")
    o.expect("INC-A-ONLY" not in [i.incident_id for i in IncidentRepository(url, TENANT_B).list_incidents()],
             "tenant B's incident list must not include tenant A's incident")
    o.expect(ServiceRepository(url, TENANT_B).get_service("svc-only-a") is None, "tenant B must not read tenant A's service")
    o.expect([s.service_id for s in ServiceRepository(url, TENANT_B).list_services()] == ["svc-payment"],
             "tenant B lists only its own services")
    projection = GraphRepository(url, TENANT_B).project_operational_graph()
    items = [*projection["nodes"], *projection["relationships"]]
    o.expect(all(item.get("tenant_id") == TENANT_B for item in items), "every graph node/relationship carries its tenant_id")
    o.expect("INC-A-ONLY" not in {n["id"] for n in projection["nodes"]}, "tenant B's graph projection must not contain A's data")


def _workflow(url: str, tenant: str, **kwargs: Any) -> dict[str, Any]:
    return WorkflowService(url, tenant_id=tenant).evaluate_incident_action("INC-T1", "restart_service", "eval-requester", **kwargs)


def check_workflow_and_audit_isolation(url: str, o: _Outcomes) -> None:
    created = _workflow(url, TENANT_A)
    wid = created["workflow_id"]
    service_b = WorkflowService(url, tenant_id=TENANT_B)
    o.expect(service_b.get_workflow(wid) is None, "tenant B must not read tenant A's workflow")
    o.expect(WorkflowRepository(url, TENANT_B).list_audit_events(wid) == [], "tenant B must not read tenant A's audit events")
    try:
        service_b.record_decision(wid, decision="approve", reviewer="eval-reviewer", actor_type="human", timestamp=_TS,
                                  incident_id="INC-T1", action="restart_service")
        o.expect(False, "tenant B must not be able to record a decision on tenant A's workflow")
    except KeyError:
        o.expect(True, "")
    audits = WorkflowRepository(url, TENANT_A).list_audit_events(wid)
    o.expect(bool(audits) and all(a.tenant_id == TENANT_A for a in audits), "tenant A's audit rows carry tenant A")
    o.expect(WorkflowService(url, tenant_id=TENANT_A).get_workflow(wid)["status"] == "pending", "the workflow was not altered")


@contextmanager
def _tenant_factories(url: str):
    saved = workflow_api.workflow_service_for, workflow_api.incident_service_for
    workflow_api.workflow_service_for = lambda tenant: WorkflowService(url, tenant_id=tenant)
    workflow_api.incident_service_for = lambda tenant: IncidentService(url, tenant)
    try:
        yield
    finally:
        workflow_api.workflow_service_for, workflow_api.incident_service_for = saved


def _principal(tenant: str, kind: PrincipalType, *roles: str) -> Principal:
    return Principal(principal_id=f"eval-{kind.value}", principal_type=kind, roles=roles, tenant_id=tenant, auth_method="eval")


def _decide(wid: str, principal: Principal) -> int:
    payload = WorkflowDecisionRequest(decision="approve", incident_id="INC-T1", action="restart_service", timestamp=_TS)
    try:
        workflow_api.decide_for_principal(wid, payload, principal)
        return 200
    except HTTPException as exc:
        return exc.status_code


def check_hitl_cross_tenant(url: str, o: _Outcomes) -> None:
    wid = _workflow(url, TENANT_A)["workflow_id"]
    with _tenant_factories(url):
        o.expect(_decide(wid, _principal(TENANT_B, PrincipalType.HUMAN, *_ROLES)) == 404,
                 "a fully-privileged reviewer of tenant B must not reach tenant A's workflow (404)")
        o.expect(_decide(wid, _principal(TENANT_A, PrincipalType.SERVICE, "service_n8n")) == 403,
                 "the service principal must not approve, even in its own tenant")
        o.expect(WorkflowService(url, tenant_id=TENANT_A).get_workflow(wid)["status"] == "pending",
                 "rejected attempts must leave the workflow pending")
        o.expect(_decide(wid, _principal(TENANT_A, PrincipalType.HUMAN, *_ROLES)) == 200,
                 "the owning tenant's authorized human reviewer can approve")


def check_dedup_and_idempotency(url: str, o: _Outcomes) -> None:
    a, b = OperationalEventRepository(url, TENANT_A), OperationalEventRepository(url, TENANT_B)
    o.expect(a.claim_event("evt-shared", "h") is True, "tenant A claims the event")
    o.expect(b.claim_event("evt-shared", "h") is True, "the same event id in tenant B is an independent event")
    o.expect(a.claim_event("evt-shared", "h") is False, "a duplicate inside tenant A is still deduplicated")
    first = _workflow(url, TENANT_A, idempotency_key="shared-key")
    other = _workflow(url, TENANT_B, idempotency_key="shared-key")
    replay = _workflow(url, TENANT_A, idempotency_key="shared-key")
    o.expect(first["workflow_id"] != other["workflow_id"], "the same idempotency key in another tenant is not a replay")
    o.expect(first["workflow_id"] == replay["workflow_id"], "the same key inside one tenant replays its workflow")


def check_agent_and_mcp_boundary(url: str, o: _Outcomes) -> None:
    agent = IncidentInvestigationAgent(database_url=url, api_key="eval-not-used")
    options = agent._build_sdk_options("INC-T1", None, IdentityContext(tenant_id=TENANT_A, user_id="u"))
    o.expect(options.mcp_servers["pulseops"]["env"].get("PULSEOPS_TENANT_ID") == TENANT_A,
             "the MCP subprocess is bound to the authenticated principal's tenant")
    try:
        agent._build_sdk_options("INC-T1", None, IdentityContext(user_id="u"))
        o.expect(False, "the agent must refuse to run without a tenant context")
    except RuntimeError:
        o.expect(True, "")

    async def schemas() -> dict[str, set[str]]:
        tools = await build_mcp_server(database_url=url, tenant_id=TENANT_A).list_tools()
        return {t.name: set(t.input_schema.get("properties", {})) for t in tools}

    leaking = [name for name, props in asyncio.run(schemas()).items() if any("tenant" in p.lower() for p in props)]
    o.expect(not leaking, f"MCP tools must not accept a tenant argument: {leaking}")
    try:
        build_mcp_server(database_url=url, tenant_id=" ")
        o.expect(False, "the MCP server must refuse a blank tenant")
    except ValueError:
        o.expect(True, "")


def check_membership_roles(url: str, o: _Outcomes) -> None:
    catalog = TenantRepository(url)
    in_a, in_b = catalog.resolve_active_membership(TENANT_A, "eval-u1"), catalog.resolve_active_membership(TENANT_B, "eval-u1")
    o.expect(in_a is not None and in_a.role == "reviewer", "the user is a reviewer in tenant A")
    o.expect(in_b is not None and in_b.role == "operator" and "reviewer" not in in_b.roles,
             "the reviewer role does not leak into tenant B")
    catalog.set_membership_status(TENANT_A, "eval-u1", "inactive")
    o.expect(catalog.resolve_active_membership(TENANT_A, "eval-u1") is None, "an inactive membership fails closed")
    catalog.set_membership_status(TENANT_A, "eval-u1", "active")
    o.expect(catalog.resolve_active_membership("eval-no-such-tenant", "eval-u1") is None, "a missing tenant fails closed")


CHECKS: tuple[tuple[str, str, Callable[[str, _Outcomes], None]], ...] = (
    ("t01-mcp-same-id-isolation", "mcp", check_mcp_same_id_isolation),
    ("t02-mcp-foreign-resources", "mcp", check_mcp_foreign_resources),
    ("t03-repository-and-graph-scoping", "repository", check_repository_scoping),
    ("t04-workflow-and-audit-isolation", "workflow", check_workflow_and_audit_isolation),
    ("t05-hitl-cross-tenant", "hitl", check_hitl_cross_tenant),
    ("t06-dedup-and-idempotency", "idempotency", check_dedup_and_idempotency),
    ("t07-agent-and-mcp-boundary", "agent", check_agent_and_mcp_boundary),
    ("t08-membership-roles", "rbac", check_membership_roles),
)


def run_tenant_checks() -> list[RetrievalCheckResult]:
    with tempfile.TemporaryDirectory(prefix="pulseops-eval-tenant-", ignore_cleanup_errors=True) as tmp:
        url = build_tenant_database(Path(tmp))
        results: list[RetrievalCheckResult] = []
        for check_id, surface, check in CHECKS:
            outcomes = _Outcomes()
            try:
                check(url, outcomes)
            except Exception as exc:  # a crashing check is an isolation failure, never a silent pass
                outcomes.expect(False, f"check raised {type(exc).__name__}: {str(exc)[:120]}")
            score = sum(outcomes.results) / len(outcomes.results) if outcomes.results else 0.0
            results.append(RetrievalCheckResult(check_id=check_id, tool=surface, score=round(score, 4),
                                                passed=score >= 1.0, details=outcomes.problems))
        return results


def aggregate_tenant(results: list[RetrievalCheckResult]) -> MetricAggregate:
    if not results:
        return MetricAggregate(metric=TENANT_METRIC, applicable_cases=0, mean_score=None, pass_rate=None)
    return MetricAggregate(
        metric=TENANT_METRIC,
        applicable_cases=len(results),
        mean_score=round(sum(r.score for r in results) / len(results), 4),
        pass_rate=round(sum(1 for r in results if r.passed) / len(results), 4),
        failed_cases=[r.check_id for r in results if not r.passed],
    )
