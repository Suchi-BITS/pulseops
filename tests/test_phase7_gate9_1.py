"""Phase 7 Gate 9.1 - multi-tenant foundation tests.

Two real tenants live in one temporary database. Requests authenticate with bearer credentials, so tenant context
always comes from the credential's validated TenantUser membership (never from a header or body field).
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.agent as agent_api
from app.agent.service import IdentityContext, IncidentInvestigationAgent, InvestigationResult
from app.core import security
from app.core.config import DEV_TENANT_ID, ConfigurationError, get_settings
from app.core.security import Principal, PrincipalType, ROLE_PERMISSIONS, hash_token
from app.database import TENANT_ROLES, DatabaseManager, LegacySchemaError
from app.graph.repository import GraphRepository
from app.main import app
from app.mcp.server import build_mcp_server
from app.migrations.gate9_1 import MigrationError, migrate
from app.repositories.incident_repository import (
    IncidentRepository,
    ServiceRepository,
    TenantContextError,
    WorkflowRepository,
)
from app.repositories.tenant_repository import TenantRepository
from app.retrieval.service import IncidentRetrievalService
from tests.helpers import as_principal, provision_members
from tests.test_phase7_gate6 import StubInvestigator, _event

REPO = Path(__file__).resolve().parents[1]
A, B = "tenant-a", "tenant-b"
TOKENS = {name: f"{name}-token-0123456789abcdefABCDEF" for name in (
    "u1-a", "u1-b", "rev-b", "op-a", "op-b", "n8n-a", "n8n-b", "bot-a", "ghost", "idle", "off-user",
)}


def bearer(name: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKENS[name]}"}


def _add_service(url: str, tenant: str, service_id: str) -> None:
    with DatabaseManager(url).get_connection() as c:
        c.execute(
            "INSERT INTO services (tenant_id, service_id, service_name, owner_team, environment, created_at)"
            " VALUES (?, ?, ?, 'team', 'production', '2026-01-01T00:00:00+00:00')",
            (tenant, service_id, service_id),
        )


@pytest.fixture()
def tenants(tmp_path, monkeypatch):
    """Two tenants (A, B) with their own services, plus users with different roles in each."""
    url = "sqlite:" + (tmp_path / "gate91.db").as_posix()
    monkeypatch.setenv("PULSEOPS_DATABASE_URL", url)
    DatabaseManager(url)
    repo = TenantRepository(url)
    repo.create_tenant(A, "Tenant A")
    repo.create_tenant(B, "Tenant B")
    # u1 is ONE user: reviewer (+ domain roles) in A, a plain operator in B.
    repo.create_user("u1", "User One", email="u1@example.com")
    repo.add_membership(A, "u1", "reviewer", domain_roles=["sre", "incident_manager"])
    repo.add_membership(B, "u1", "operator")
    provision_members(url, B, {"rev-b": ("human", "reviewer", ("sre", "incident_manager"))})
    provision_members(url, A, {"op-a": ("human", "operator", ())})
    provision_members(url, B, {"op-b": ("human", "operator", ())})
    provision_members(url, A, {"svc-n8n-a": ("service", "service_n8n", ())})
    provision_members(url, B, {"svc-n8n-b": ("service", "service_n8n", ())})
    provision_members(url, A, {"bot-a": ("agent", "operator", ())})
    repo.create_user("idle", "No membership anywhere")
    credentials = [
        ("u1", A, "u1-a"), ("u1", B, "u1-b"), ("rev-b", B, "rev-b"), ("op-a", A, "op-a"), ("op-b", B, "op-b"),
        ("svc-n8n-a", A, "n8n-a"), ("svc-n8n-b", B, "n8n-b"), ("bot-a", A, "bot-a"),
        ("idle", A, "idle"),  # valid token, but no membership in the tenant it names
        ("nobody", A, "ghost"),  # valid token for a user that does not exist
    ]
    monkeypatch.setenv("PULSEOPS_AUTH_MODE", "apikey")
    monkeypatch.setenv("PULSEOPS_API_CREDENTIALS", json.dumps(
        [{"principal_id": uid, "tenant_id": tid, "token_sha256": hash_token(TOKENS[tok])} for uid, tid, tok in credentials]
    ))
    for tenant in (A, B):
        _add_service(url, tenant, "svc-payment")
    _add_service(url, A, "svc-only-a")
    stub = StubInvestigator()
    monkeypatch.setattr("app.services.event_service.build_investigator", stub.build)
    return TestClient(app), url, repo


def _ingest(client, who, **overrides):
    return client.post("/workflow/events", headers=bearer(who), json=_event(**overrides))


def _hitl_in(client, who="n8n-a"):
    body = _ingest(client, who, metadata={"requested_action": "restart_service"}).json()
    assert body["policy_decision"] == "hitl_required", body
    return body


def _approve(client, who, body, **extra):
    return client.post(
        f"/workflow/{body['workflow_id']}/decision", headers=bearer(who),
        json={"decision": "approve", "incident_id": body["incident_id"], "action": "restart_service",
              "timestamp": "2026-01-01T00:00:00Z", **extra},
    )


# =========================================================================== A-D tenant model

def test_a_tenant_creation_and_validation(tenants) -> None:
    _, _, repo = tenants
    assert repo.get_tenant(A).tenant_name == "Tenant A" and repo.get_tenant(A).status == "active"
    with pytest.raises(ValueError, match="already exists"):
        repo.create_tenant(A, "again")
    with pytest.raises(ValueError):
        repo.create_tenant("bad id!", "x")
    with pytest.raises(ValueError):
        repo.create_tenant("t-ok", "  ")
    with pytest.raises(ValueError):
        repo.create_tenant("t-ok2", "x", status="deleted")
    assert repo.get_tenant("missing") is None


def test_b_user_creation_and_validation(tenants) -> None:
    _, _, repo = tenants
    user = repo.get_user("u1")
    assert (user.email, user.display_name, user.user_type, user.status) == ("u1@example.com", "User One", "human", "active")
    with pytest.raises(ValueError, match="already exists"):
        repo.create_user("u1", "dup")
    with pytest.raises(ValueError):
        repo.create_user("u-dup-email", "x", email="u1@example.com")  # email is unique
    with pytest.raises(ValueError):
        repo.create_user("u-bad-type", "x", user_type="superuser")
    # Users carry no tenant: there is no tenant_id column to be the multi-tenancy model.
    with DatabaseManager(repo.database_url).get_connection() as c:
        assert "tenant_id" not in [r[1] for r in c.execute("PRAGMA table_info(users)")]


def test_c_membership_rules_are_enforced(tenants) -> None:
    _, url, repo = tenants
    with pytest.raises(ValueError, match="already a member"):
        repo.add_membership(A, "u1", "operator")  # UNIQUE (tenant_id, user_id)
    with pytest.raises(ValueError, match="unknown tenant"):
        repo.add_membership("nope", "u1", "operator")  # valid foreign keys
    with pytest.raises(ValueError, match="unknown user"):
        repo.add_membership(A, "nope", "operator")
    with pytest.raises(ValueError, match="invalid role"):
        repo.add_membership(A, "idle", "root")
    repo.create_user("svc-extra", "s", user_type="service")
    with pytest.raises(ValueError, match="reviewer"):
        repo.add_membership(A, "svc-extra", "reviewer")  # only a human may review
    with pytest.raises(ValueError):
        repo.add_membership(A, "idle", "operator", domain_roles=["admin"])  # a domain role cannot smuggle an app role
    with DatabaseManager(url).get_connection() as c:  # the database itself rejects what the API would
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO tenant_users (tenant_id, user_id, role, created_at, updated_at) VALUES ('ghost','u1','admin','x','x')")
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO tenant_users (tenant_id, user_id, role, created_at, updated_at) VALUES (?,?,'wizard','x','x')", (B, "idle"))


def test_d_same_user_in_multiple_tenants_without_duplicating_the_user(tenants) -> None:
    _, url, repo = tenants
    assert repo.list_memberships("u1") == [(A, "reviewer", "active"), (B, "operator", "active")]
    with DatabaseManager(url).get_connection() as c:
        assert c.execute("SELECT COUNT(*) FROM users WHERE user_id = 'u1'").fetchone()[0] == 1


# =========================================================================== E-G tenant-scoped roles / fail closed

def test_e_roles_are_per_tenant_and_do_not_leak(tenants) -> None:
    client, _, repo = tenants
    in_a, in_b = repo.resolve_active_membership(A, "u1"), repo.resolve_active_membership(B, "u1")
    assert in_a.roles == ("reviewer", "sre", "incident_manager") and in_b.roles == ("operator",)
    hitl = _hitl_in(client, "n8n-a")
    # Same user, same kind of request: reviewer inside A ...
    assert _approve(client, "u1-a", hitl).status_code == 200
    # ... but only an operator inside B: the reviewer permission does not follow the user across tenants.
    hitl_b = _hitl_in(client, "n8n-b")
    denied = _approve(client, "u1-b", hitl_b)
    assert denied.status_code == 403 and "workflow:approve" in denied.json()["detail"]
    assert client.get("/incidents", headers=bearer("u1-b")).status_code == 200  # operator still reads in B
    assert client.post("/incidents", headers=bearer("u1-a"), json={}).status_code == 403  # reviewer cannot write in A


def test_f_missing_membership_fails_closed(tenants) -> None:
    client, *_ = tenants
    for who in ("idle", "ghost"):
        response = client.get("/incidents", headers=bearer(who))
        body = response.json()  # P9.0 error envelope: same message, plus code and request_id
        assert response.status_code == 403 and body["detail"] == "No active tenant membership for this credential"
        assert body["code"] == "forbidden" and body["request_id"]
    assert client.get("/incidents", headers={"Authorization": "Bearer " + "z" * 40}).status_code == 401


def test_g_inactive_membership_user_or_tenant_fails_closed(tenants) -> None:
    client, _, repo = tenants
    assert client.get("/incidents", headers=bearer("op-a")).status_code == 200
    repo.set_membership_status(A, "op-a", "inactive")
    assert client.get("/incidents", headers=bearer("op-a")).status_code == 403
    repo.set_membership_status(A, "op-a", "active")
    repo.set_user_status("op-a", "inactive")
    assert client.get("/incidents", headers=bearer("op-a")).status_code == 403
    repo.set_user_status("op-a", "active")
    repo.set_tenant_status(A, "inactive")
    assert client.get("/incidents", headers=bearer("op-a")).status_code == 403  # a suspended tenant locks everyone out
    assert client.get("/incidents", headers=bearer("op-b")).status_code == 200  # ...and only that tenant
    repo.set_tenant_status(A, "active")
    assert client.get("/incidents", headers=bearer("op-a")).status_code == 200


def test_credentials_cannot_carry_roles_or_share_tokens() -> None:
    base = {"principal_id": "x", "tenant_id": A, "token_sha256": "a" * 64}
    security.validate_credentials([base])
    with pytest.raises(ConfigurationError, match="tenant membership"):
        security.validate_credentials([{**base, "roles": ["admin"]}])
    with pytest.raises(ConfigurationError, match="tenant_id"):
        security.validate_credentials([{k: v for k, v in base.items() if k != "tenant_id"}])
    with pytest.raises(ConfigurationError, match="reuses a token hash"):
        security.validate_credentials([base, {**base, "principal_id": "y"}])
    with pytest.raises(ConfigurationError, match="duplicates"):
        security.validate_credentials([base, {**base, "token_sha256": "b" * 64}])


def test_principal_requires_a_tenant_and_the_tenant_is_never_a_request_field(tenants) -> None:
    client, *_ = tenants
    with pytest.raises(Exception):
        Principal(principal_id="x", principal_type=PrincipalType.HUMAN, roles=("admin",), auth_method="api_key", tenant_id=" ")
    # Neither a header nor a body/query field can move a principal into another tenant.
    incident = _ingest(client, "n8n-a", severity="low").json()["incident_id"]
    assert client.get(f"/incidents/{incident}", headers=bearer("op-a")).status_code == 200
    for headers in ({"X-Tenant-ID": A}, {"X-Tenant": A}, {"tenant_id": A}):
        assert client.get(f"/incidents/{incident}", headers={**bearer("op-b"), **headers}).status_code == 404
    assert client.get(f"/incidents/{incident}?tenant_id={A}", headers=bearer("op-b")).status_code == 404


# =========================================================================== H-K operational data isolation

def test_h_i_j_cross_tenant_incident_service_isolation(tenants) -> None:
    client, url, _ = tenants
    a = _ingest(client, "n8n-a", severity="low", message="only in A").json()
    b = _ingest(client, "n8n-b", severity="low", message="only in B").json()
    assert a["incident_id"] == b["incident_id"] == "INC-1001"  # the same logical id in two tenants
    assert client.get("/incidents/INC-1001", headers=bearer("op-a")).json()["description"] == "only in A"
    assert client.get("/incidents/INC-1001", headers=bearer("op-b")).json()["description"] == "only in B"
    assert [i["incident_id"] for i in client.get("/incidents", headers=bearer("op-b")).json()] == ["INC-1001"]
    # H: read of an id that only exists in A returns 404 for B
    only_a = _ingest(client, "n8n-a", severity="low", message="second").json()["incident_id"]
    assert only_a == "INC-1002"
    assert client.get(f"/incidents/{only_a}", headers=bearer("op-b")).status_code == 404
    # I: B cannot write against A's service or incident
    created = client.post("/incidents", headers=bearer("op-b"), json={
        "service_id": "svc-only-a", "severity": "low", "title": "t", "description": "d", "environment": "p"})
    assert created.status_code == 400 and "Unknown service_id" in created.json()["detail"]
    assert client.post(f"/workflow/incidents/{only_a}/evaluate", headers=bearer("op-b"), json={"action": "notify"}).status_code == 404
    assert client.post(f"/incidents/{only_a}/workflow/evaluate", headers=bearer("op-b"), json={"action": "notify"}).status_code == 404
    event = _ingest(client, "n8n-b", service_id="svc-only-a")
    assert event.status_code == 400  # an event cannot be raised against another tenant's service
    # J: service data is tenant-scoped at the repository, the retrieval API and the graph
    assert ServiceRepository(url, A).get_service("svc-only-a") is not None
    assert ServiceRepository(url, B).get_service("svc-only-a") is None
    assert [s.service_id for s in ServiceRepository(url, B).list_services()] == ["svc-payment"]
    assert client.get("/retrieval/services/svc-only-a/incidents", headers=bearer("op-b")).json()["incidents"] == []
    assert client.get("/retrieval/incidents/INC-1002", headers=bearer("op-b")).status_code == 404
    assert client.get("/retrieval/incidents/INC-1002", headers=bearer("op-a")).status_code == 200


def test_the_same_identifier_is_allowed_in_two_tenants_but_not_twice_in_one(tenants) -> None:
    _, url, _ = tenants
    with DatabaseManager(url).get_connection() as c:
        for tenant in (A, B):
            c.execute("INSERT INTO incidents (tenant_id, incident_id, service_id, severity, status, title, description,"
                      " environment, started_at, created_at, updated_at) VALUES (?, 'INC-X', 'svc-payment', 'low', 'open',"
                      " 't', 'd', 'p', 'x', 'x', 'x')", (tenant,))
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO incidents (tenant_id, incident_id, service_id, severity, status, title, description,"
                      " environment, started_at, created_at, updated_at) VALUES (?, 'INC-X', 'svc-payment', 'low', 'open',"
                      " 't', 'd', 'p', 'x', 'x', 'x')", (A,))
        # composite foreign keys: a row cannot reference another tenant's parent
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO incidents (tenant_id, incident_id, service_id, severity, status, title, description,"
                      " environment, started_at, created_at, updated_at) VALUES (?, 'INC-Y', 'svc-only-a', 'low', 'open',"
                      " 't', 'd', 'p', 'x', 'x', 'x')", (B,))


def test_repositories_cannot_exist_without_a_tenant(tenants) -> None:
    _, url, _ = tenants
    for bad in ("", "  ", None):
        with pytest.raises(TenantContextError):
            IncidentRepository(url, bad)
    with pytest.raises(TypeError):
        IncidentRepository(url)  # type: ignore[call-arg]  # no default tenant
    with pytest.raises(TypeError):
        WorkflowRepository(url)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        IncidentRetrievalService(database_url=url)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        build_mcp_server(database_url=url)  # type: ignore[call-arg]


# =========================================================================== K-M workflow, HITL, audit isolation

def test_k_l_m_cross_tenant_workflow_hitl_and_audit_are_denied(tenants) -> None:
    client, url, _ = tenants
    hitl = _hitl_in(client, "n8n-a")
    wid = hitl["workflow_id"]
    # K: B (even a fully-privileged reviewer) cannot see, evaluate or replay A's workflow
    assert client.get(f"/workflow/{wid}", headers=bearer("rev-b")).status_code == 404
    assert client.get(f"/workflow/{wid}", headers=bearer("op-b")).status_code == 404
    # L: Tenant A's reviewer-equivalent in tenant B cannot approve OR reject it; nothing changes
    for decision in ("approve", "reject"):
        r = client.post(f"/workflow/{wid}/decision", headers=bearer("rev-b"), json={
            "decision": decision, "incident_id": hitl["incident_id"], "action": "restart_service", "timestamp": "2026-01-01T00:00:00Z"})
        assert r.status_code == 404, r.text
    legacy = client.post(f"/incidents/{hitl['incident_id']}/workflow/decision", headers=bearer("rev-b"), json={
        "decision": "approve", "incident_id": hitl["incident_id"], "action": "restart_service", "timestamp": "2026-01-01T00:00:00Z"})
    assert legacy.status_code == 404  # B has no such workflow (its own incident ids are a different namespace)
    state = client.get(f"/workflow/{wid}", headers=bearer("u1-a")).json()
    assert state["status"] == "pending" and state["requires_approval"] is True
    assert not [e for e in state["audit_events"] if e["event_type"] == "HITL_APPROVED"]
    # M: audit rows are tenant-owned and unreachable from B
    assert all(e["tenant_id"] == A for e in state["audit_events"])
    assert all(e["metadata"]["tenant_id"] == A for e in state["audit_events"])
    assert WorkflowRepository(url, B).list_audit_events(wid) == []
    assert WorkflowRepository(url, B).get_workflow(wid) is None
    assert WorkflowRepository(url, A).list_audit_events(wid)
    # the legitimate approval still works, with the Gate 9 audit trail
    approved = _approve(client, "u1-a", hitl)
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    event = next(e for e in approved.json()["audit_events"] if e["event_type"] == "HITL_APPROVED")
    assert event["actor"] == "u1" and event["actor_type"] == "human" and event["tenant_id"] == A
    assert event["metadata"]["principal_roles"] == ["reviewer", "sre", "incident_manager"] and event["metadata"]["request_id"]


def test_a_tenant_a_reviewer_cannot_approve_a_tenant_b_workflow(tenants) -> None:
    """The explicit security case: a fully-privileged reviewer in one tenant against another tenant's workflow."""
    client, *_ = tenants
    hitl_b = _hitl_in(client, "n8n-b")
    assert _approve(client, "u1-a", hitl_b).status_code == 404  # u1 is a reviewer with sre/incident_manager in A only
    assert client.get(f"/workflow/{hitl_b['workflow_id']}", headers=bearer("u1-a")).status_code == 404
    assert client.get(f"/workflow/{hitl_b['workflow_id']}", headers=bearer("rev-b")).json()["status"] == "pending"
    assert _approve(client, "rev-b", hitl_b).status_code == 200  # the owning tenant's reviewer can


def test_hitl_still_requires_gate9_rules_inside_the_right_tenant(tenants) -> None:
    client, *_ = tenants
    hitl = _hitl_in(client, "n8n-a")
    assert _approve(client, "n8n-a", hitl).status_code == 403  # the service principal is never a reviewer
    assert _approve(client, "bot-a", hitl).status_code == 403  # nor an agent
    assert _approve(client, "u1-a", hitl, reviewer="somebody-else").status_code == 403  # reviewer field is not authority
    assert _approve(client, "u1-a", hitl).status_code == 200
    assert _approve(client, "u1-a", hitl).status_code == 200  # idempotent replay inside the tenant
    reject = client.post(f"/workflow/{hitl['workflow_id']}/decision", headers=bearer("u1-a"), json={
        "decision": "reject", "incident_id": hitl["incident_id"], "action": "restart_service", "timestamp": "2026-01-01T00:00:00Z"})
    assert reject.status_code == 409


# =========================================================================== N n8n service principal

def test_n_n8n_is_bound_to_its_tenant_and_has_no_bypass(tenants) -> None:
    client, _, repo = tenants
    assert _ingest(client, "n8n-a", severity="low", tenant_id=A).status_code == 200  # naming its own tenant is fine
    forged = _ingest(client, "n8n-a", severity="low", tenant_id=B)
    assert forged.status_code == 403 and "not authorized" in forged.json()["detail"]
    assert client.get("/incidents", headers=bearer("op-b")).json() == []  # nothing leaked into B
    ok = _ingest(client, "n8n-b", severity="low", message="b event").json()
    assert client.get(f"/incidents/{ok['incident_id']}", headers=bearer("op-b")).json()["description"] == "b event"
    # service principals cannot review, evaluate, investigate or read another tenant's records
    hitl = _hitl_in(client, "n8n-a")
    assert _approve(client, "n8n-a", hitl).status_code == 403
    assert _approve(client, "n8n-b", hitl).status_code == 404  # another tenant's workflow does not exist for n8n-b
    assert client.get(f"/workflow/{hitl['workflow_id']}", headers=bearer("n8n-b")).status_code == 404
    assert client.post("/agent/investigate", headers=bearer("n8n-a"), json={"incident_id": hitl["incident_id"]}).status_code == 403
    # a service user can never hold the reviewer role, at the catalog or in a corrupted row
    with pytest.raises(ValueError, match="reviewer"):
        repo.add_membership(B, "svc-n8n-a", "reviewer")
    with DatabaseManager(repo.database_url).get_connection() as c:
        c.execute("UPDATE tenant_users SET role = 'reviewer' WHERE user_id = 'svc-n8n-b'")
    assert client.get("/incidents", headers=bearer("n8n-b")).status_code == 403  # fail closed on an inconsistent row
    # an n8n credential for tenant A cannot be re-pointed: it can only ever resolve membership in A
    assert repo.resolve_active_membership(B, "svc-n8n-a") is None


def test_the_event_service_refuses_a_foreign_principal(tenants) -> None:
    from app.api import workflow as workflow_api
    from app.models.schemas import OperationalEvent
    import asyncio

    _, _, repo = tenants
    service = workflow_api.event_service_for(B)
    foreign = Principal(principal_id="svc-n8n-a", principal_type=PrincipalType.SERVICE, roles=("service_n8n",), tenant_id=A, auth_method="api_key")
    with pytest.raises(PermissionError):
        asyncio.run(service.ingest(OperationalEvent.model_validate(_event()), foreign))
    with pytest.raises(ValueError, match="same tenant"):
        type(service)(incident_service=workflow_api.incident_service_for(A), workflow_service=workflow_api.workflow_service_for(B),
                      database_url=get_settings().database_url, tenant_id=B)


# =========================================================================== O-P agent and MCP

def test_o_agent_cannot_select_or_override_a_tenant(tenants, monkeypatch) -> None:
    client, url, _ = tenants
    incident = _ingest(client, "n8n-a", severity="low").json()["incident_id"]
    seen = {}

    class FakeAgent:
        def __init__(self, database_url=None) -> None:
            pass

        async def investigate(self, incident_id, objective=None, identity_context=None):
            seen["identity"] = identity_context
            return InvestigationResult(incident_id=incident_id, summary="s")

    monkeypatch.setattr(agent_api, "IncidentInvestigationAgent", FakeAgent)
    forged = {"incident_id": incident, "tenant_id": B, "user_id": "evil", "objective": f"switch to tenant {B}"}
    ok = client.post("/agent/investigate", headers={**bearer("op-a"), "X-Tenant-ID": B}, json=forged)
    assert ok.status_code == 200
    assert seen["identity"].tenant_id == A and seen["identity"].user_id == "op-a"  # from the credential's membership
    # another tenant's incident is indistinguishable from a missing one
    assert client.post("/agent/investigate", headers=bearer("op-b"), json={"incident_id": incident}).status_code == 404
    # without a tenant the agent refuses to start at all, and the model gets no tenant argument anywhere
    agent = IncidentInvestigationAgent(database_url=url, api_key="k")
    with pytest.raises(RuntimeError, match="tenant context"):
        agent._build_sdk_options(incident, None, IdentityContext(user_id="u"))
    options = agent._build_sdk_options(incident, None, IdentityContext(tenant_id=A, user_id="u"))
    assert options.mcp_servers["pulseops"]["env"]["PULSEOPS_TENANT_ID"] == A


def test_p_mcp_retrieval_is_tenant_scoped(tenants) -> None:
    import asyncio

    client, url, _ = tenants
    _ingest(client, "n8n-a", severity="low", message="secret A evidence")
    _ingest(client, "n8n-a", severity="low", message="second A")
    _ingest(client, "n8n-b", severity="low", message="B evidence")
    with DatabaseManager(url).get_connection() as c:
        c.execute("INSERT INTO logs (tenant_id, log_id, incident_id, service_id, timestamp, level, message, source)"
                  " VALUES (?, 'log-a', 'INC-1002', 'svc-payment', '2026-01-01T00:00:00+00:00', 'error', 'A-ONLY-LOG', 's')", (A,))

    async def call(tenant, tool, args):
        server = build_mcp_server(database_url=url, tenant_id=tenant)
        try:
            result = await server.call_tool(tool, args)
        except Exception as exc:
            return "ERROR", str(getattr(exc, "__cause__", None) or exc)
        return "OK", json.dumps(result.structured_content) if result.structured_content else result.content[0].text

    status, text = asyncio.run(call(B, "get_incident_context", {"incident_id": "INC-1002"}))
    assert status == "ERROR" and "A-ONLY-LOG" not in text  # B has no INC-1002
    status, text = asyncio.run(call(A, "get_incident_context", {"incident_id": "INC-1002"}))
    assert status == "OK" and "A-ONLY-LOG" in text
    status, text = asyncio.run(call(B, "get_incident_context", {"incident_id": "INC-1001"}))
    assert status == "OK" and "B evidence" in text and "secret A evidence" not in text  # same id, B's own data
    assert "INC-1002" not in asyncio.run(call(B, "get_related_incidents", {"service_id": "svc-payment"}))[1]
    assert "INC-1002" in asyncio.run(call(A, "get_related_incidents", {"service_id": "svc-payment"}))[1]
    assert "null" in asyncio.run(call(B, "get_service_repository", {"service_id": "svc-only-a"}))[1]  # no mapping visible to B

    async def schemas():
        tools = await build_mcp_server(database_url=url, tenant_id=A).list_tools()
        return {t.name: set(t.input_schema.get("properties", {})) for t in tools}

    for name, properties in asyncio.run(schemas()).items():
        assert not any("tenant" in p for p in properties), f"{name} lets the caller name a tenant"
    with pytest.raises(ValueError):
        build_mcp_server(database_url=url, tenant_id=" ")


def test_the_mcp_process_refuses_to_start_without_a_tenant(tenants) -> None:
    _, url, _ = tenants
    env = {k: v for k, v in os.environ.items() if k != "PULSEOPS_TENANT_ID"}
    env.update(PYTHONPATH=str(REPO), PULSEOPS_DATABASE_URL=url)
    result = subprocess.run([sys.executable, "-m", "app.mcp.server"], env=env, capture_output=True, text=True, timeout=120, cwd=REPO)
    assert result.returncode != 0 and "PULSEOPS_TENANT_ID is required" in result.stderr


# =========================================================================== Q-R idempotency and dedup

def test_q_idempotency_keys_are_tenant_scoped(tenants) -> None:
    client, *_ = tenants
    a = client.post("/workflow/evaluate", headers=bearer("op-a"), json={"incident_id": "INC-9", "action": "notify", "idempotency_key": "same-key"})
    b = client.post("/workflow/evaluate", headers=bearer("op-b"), json={"incident_id": "INC-9", "action": "notify", "idempotency_key": "same-key"})
    assert a.status_code == b.status_code == 200
    assert a.json()["workflow_id"] != b.json()["workflow_id"]  # not treated as a replay across tenants
    again = client.post("/workflow/evaluate", headers=bearer("op-a"), json={"incident_id": "INC-9", "action": "notify", "idempotency_key": "same-key"})
    assert again.json()["workflow_id"] == a.json()["workflow_id"]
    conflict = client.post("/workflow/evaluate", headers=bearer("op-a"), json={"incident_id": "INC-9", "action": "restart_service", "idempotency_key": "same-key"})
    assert conflict.status_code == 409  # conflicts are detected within the tenant only


def test_r_event_deduplication_is_tenant_scoped(tenants) -> None:
    client, *_ = tenants
    shared = _event(event_id="evt-shared", severity="low")
    a1 = client.post("/workflow/events", headers=bearer("n8n-a"), json=shared).json()
    b1 = client.post("/workflow/events", headers=bearer("n8n-b"), json=shared).json()
    assert a1["idempotent_replay"] is False and b1["idempotent_replay"] is False  # B's event is not A's duplicate
    assert a1["workflow_id"] != b1["workflow_id"]
    a2 = client.post("/workflow/events", headers=bearer("n8n-a"), json=shared).json()
    assert a2["idempotent_replay"] is True and a2["workflow_id"] == a1["workflow_id"]
    different = client.post("/workflow/events", headers=bearer("n8n-b"), json={**shared, "message": "changed"})
    assert different.status_code == 409  # event_id reuse with different data conflicts only inside B
    assert client.post("/workflow/events", headers=bearer("n8n-a"), json={**shared, "message": "changed"}).status_code == 409


# =========================================================================== S-U regression, seed, dev identity

def test_s_gate9_authorization_remains_intact(tenants) -> None:
    client, *_ = tenants
    assert TestClient(app).get("/incidents").status_code == 401
    assert client.get("/health").status_code == 200 and client.get("/").status_code == 200
    assert client.post("/workflow/events", headers=bearer("op-b"), json=_event()).status_code == 200  # operator may ingest
    assert client.post("/workflow/events", headers=bearer("u1-a"), json=_event()).status_code == 403  # reviewer may not
    assert set(TENANT_ROLES) == set(ROLE_PERMISSIONS)  # the catalog CHECK constraint matches the static RBAC


def test_u_development_seed_and_dev_identity(tmp_path, monkeypatch) -> None:
    url = "sqlite:" + (tmp_path / "seed.db").as_posix()
    monkeypatch.setenv("PULSEOPS_DATABASE_URL", url)
    DatabaseManager(url)
    repo = TenantRepository(url)
    assert repo.get_tenant(DEV_TENANT_ID) is not None  # the explicit development tenant owns the demo data
    assert [i.incident_id for i in IncidentRepository(url, DEV_TENANT_ID).list_incidents()] == ["INC-1007"]
    assert IncidentRepository(url, "other").list_incidents() == []
    client = TestClient(app)
    assert client.get("/incidents").status_code == 200  # default dev principal -> dev tenant
    repo.create_tenant(B, "B")
    assert client.get("/incidents", headers=as_principal("x", "operator")).status_code == 200
    on_b = client.get("/incidents", headers={"X-Dev-Principal": f"human:x:operator:{B}"})
    assert on_b.status_code == 200 and on_b.json() == []  # the dev header can name a tenant, and it is isolated
    assert client.get("/incidents", headers={"X-Dev-Principal": "human:x:operator:no-such-tenant"}).status_code == 401
    # production: no demo data, no dev tenant
    prod = "sqlite:" + (tmp_path / "prod.db").as_posix()
    monkeypatch.setenv("PULSEOPS_ENVIRONMENT", "production")
    monkeypatch.setenv("PULSEOPS_SEED_DEMO_DATA", "false")
    DatabaseManager(prod)
    assert TenantRepository(prod).get_tenant(DEV_TENANT_ID) is None
    with DatabaseManager(prod).get_connection() as c:
        assert c.execute("SELECT COUNT(*) FROM incidents").fetchone()[0] == 0


def test_t_replay_evaluation_database_is_tenant_scoped(tmp_path) -> None:
    from evals.harness import build_eval_database
    from evals.runner import load_dataset

    _, cases = load_dataset()
    url = build_eval_database(cases[0], tmp_path)
    with DatabaseManager(url).get_connection() as c:
        tenants_in_use = {r[0] for t in ("services", "incidents", "logs", "metrics", "deployments") for r in c.execute(f"SELECT DISTINCT tenant_id FROM {t}")}
    assert tenants_in_use == {DEV_TENANT_ID}


# =========================================================================== graph-ready contract and ontology

def test_graph_projection_is_tenant_scoped_and_tenant_tagged(tenants) -> None:
    client, url, _ = tenants
    _ingest(client, "n8n-a", severity="low")
    _add_service(url, B, "svc-b-extra")
    a, b = GraphRepository(url, A).project_operational_graph(), GraphRepository(url, B).project_operational_graph()
    a_ids = {n["id"] for n in a["nodes"]}
    assert {"svc-payment", "svc-only-a", "INC-1001"} <= a_ids and "svc-b-extra" not in a_ids
    assert {n["id"] for n in b["nodes"]} == {"svc-payment", "svc-b-extra"}  # no INC-1001: that one is A's
    for projection, tenant in ((a, A), (b, B)):
        assert all(item["tenant_id"] == tenant for item in (*projection["nodes"], *projection["relationships"]))
    assert GraphRepository(url, B).get_incident_graph_context("INC-1001")["graph_relationships"] == []
    with pytest.raises(ValueError):
        from app.services.context_builder import ContextBuilder
        ContextBuilder(graph_repository=GraphRepository(url, A), database_url=url, tenant_id=B)


def test_graph_schema_documents_the_tenant_contract_and_ontology_stays_global() -> None:
    from app.graph.schema import GraphSchema

    assert all("tenant_id" in c for c in GraphSchema.tenant_scoped_constraints)
    assert GraphSchema.tenant_owned_classes <= GraphSchema.required_classes
    ontology = (REPO / "ontology" / "pulseops.ttl").read_text(encoding="utf-8")
    assert "tenant" not in ontology.lower()  # no Tenant concept was invented in the shared semantic model
    assert len(list((REPO / "ontology").glob("*.ttl"))) == 1  # one shared ontology, not one per tenant


def test_no_neo4j_runtime_or_postgres_was_introduced() -> None:
    sources = "\n".join(p.read_text(encoding="utf-8") for p in (REPO / "app").rglob("*.py"))
    assert "import neo4j" not in sources and "from neo4j" not in sources
    assert "psycopg" not in sources and "alembic" not in sources.lower().replace("no alembic", "")
    assert "rdflib" not in sources and "owlready" not in sources  # the ontology is still not loaded at runtime
    mentions = [p.name for p in (REPO / "app").rglob("*.py") if "pulseops.ttl" in p.read_text(encoding="utf-8")]
    assert mentions == ["schema.py"]  # only the documentation comment of the graph contract names it


# =========================================================================== schema safety and migration

_LEGACY_DDL = [
    "CREATE TABLE services (service_id TEXT PRIMARY KEY, service_name TEXT NOT NULL, owner_team TEXT NOT NULL,"
    " environment TEXT NOT NULL, repository_id TEXT, description TEXT, created_at TEXT NOT NULL)",
    "CREATE TABLE incidents (incident_id TEXT PRIMARY KEY, service_id TEXT NOT NULL, severity TEXT NOT NULL, status TEXT NOT NULL,"
    " title TEXT NOT NULL, description TEXT NOT NULL, environment TEXT NOT NULL, started_at TEXT NOT NULL, resolved_at TEXT,"
    " created_at TEXT NOT NULL, updated_at TEXT NOT NULL, FOREIGN KEY(service_id) REFERENCES services(service_id))",
    "CREATE TABLE logs (log_id TEXT PRIMARY KEY, incident_id TEXT, service_id TEXT NOT NULL, timestamp TEXT NOT NULL,"
    " level TEXT NOT NULL, message TEXT NOT NULL, source TEXT NOT NULL, metadata TEXT,"
    " FOREIGN KEY(service_id) REFERENCES services(service_id), FOREIGN KEY(incident_id) REFERENCES incidents(incident_id))",
    "CREATE TABLE workflow_instances (workflow_id TEXT PRIMARY KEY, incident_id TEXT NOT NULL, action TEXT NOT NULL,"
    " status TEXT NOT NULL, risk_level TEXT NOT NULL, policy_decision TEXT NOT NULL, created_at TEXT NOT NULL,"
    " updated_at TEXT NOT NULL, requested_by TEXT NOT NULL, details TEXT, requires_approval INTEGER NOT NULL DEFAULT 0)",
    "CREATE TABLE workflow_audit_events (audit_id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL, incident_id TEXT NOT NULL,"
    " event_id TEXT, event_type TEXT NOT NULL, actor_type TEXT, actor_id TEXT, timestamp TEXT NOT NULL, details TEXT,"
    " FOREIGN KEY(workflow_id) REFERENCES workflow_instances(workflow_id))",
    "CREATE TABLE operational_events (event_id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, state TEXT NOT NULL,"
    " incident_id TEXT, workflow_id TEXT, created_at TEXT NOT NULL)",
]


def _legacy_db(path: Path) -> str:
    with sqlite3.connect(path) as db:
        for ddl in _LEGACY_DDL:
            db.execute(ddl)
        db.execute("INSERT INTO services VALUES ('svc-1', 'one', 'team', 'prod', NULL, NULL, '2026-01-01T00:00:00+00:00')")
        db.execute("INSERT INTO incidents VALUES ('INC-1', 'svc-1', 'low', 'open', 't', 'd', 'prod', '2026-01-01T00:00:00+00:00', NULL, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')")
        db.execute("INSERT INTO logs VALUES ('log-1', 'INC-1', 'svc-1', 'x', 'info', 'm', 's', NULL)")
        db.execute("INSERT INTO workflow_instances VALUES ('WF-1', 'INC-1', 'notify', 'pending', 'low', 'notify', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', 'me', NULL, 0)")
        db.execute("INSERT INTO workflow_audit_events VALUES ('AUD-1', 'WF-1', 'INC-1', NULL, 'X', NULL, NULL, 'x', NULL)")
        db.execute("INSERT INTO operational_events VALUES ('evt-1', 'h', 'completed', 'INC-1', 'WF-1', 'x')")
    return "sqlite:" + path.as_posix()


def test_startup_never_rebuilds_a_legacy_schema_and_the_migration_is_explicit(tmp_path) -> None:
    path = tmp_path / "legacy.db"
    url = _legacy_db(path)
    before = path.read_bytes()
    with pytest.raises(LegacySchemaError, match="app.migrations.gate9_1"):
        DatabaseManager(url)
    assert path.read_bytes() == before  # refusing left the file untouched
    counts = migrate(url)
    assert counts["services"] == counts["incidents"] == counts["logs"] == counts["workflow_instances"] == 1
    assert counts["workflow_audit_events"] == counts["operational_events"] == 1
    assert path.with_name("legacy.db.pre-gate9_1.bak").read_bytes() == before  # backup is the original, byte for byte
    assert [i.incident_id for i in IncidentRepository(url, DEV_TENANT_ID).list_incidents()] == ["INC-1"]
    assert IncidentRepository(url, A).list_incidents() == []
    assert WorkflowRepository(url, DEV_TENANT_ID).get_workflow("WF-1") is not None
    assert migrate(url) == {}  # idempotent: nothing left to migrate
    with pytest.raises(MigrationError, match="not found"):
        migrate("sqlite:" + (tmp_path / "missing.db").as_posix())


def test_migration_rolls_back_completely_on_failure(tmp_path) -> None:
    path = tmp_path / "bad.db"
    url = _legacy_db(path)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO logs VALUES ('log-orphan', 'INC-MISSING', 'svc-1', 'x', 'info', 'm', 's', NULL)")  # FK violation
    with pytest.raises(MigrationError, match="foreign-key"):
        migrate(url)
    with sqlite3.connect(path) as db:  # the original tables are intact and no tenant tables leaked in half-done
        assert db.execute("SELECT COUNT(*) FROM incidents").fetchone()[0] == 1
        assert "tenant_id" not in [r[1] for r in db.execute("PRAGMA table_info(incidents)")]
        assert db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name LIKE '\\_legacy\\_%' ESCAPE '\\'").fetchone()[0] == 0


def test_the_tenancy_admin_cli_provisions_tenants_users_and_members(tmp_path, capsys) -> None:
    from app import tenancy_admin

    url = "sqlite:" + (tmp_path / "cli.db").as_posix()
    base = ["--database-url", url]
    assert tenancy_admin.main(base + ["create-tenant", "acme", "Acme"]) == 0
    assert tenancy_admin.main(base + ["create-user", "carol", "Carol", "--email", "c@example.com"]) == 0
    assert tenancy_admin.main(base + ["add-member", "acme", "carol", "reviewer", "--domain-roles", "sre"]) == 0
    assert TenantRepository(url).resolve_active_membership("acme", "carol").roles == ("reviewer", "sre")
    assert tenancy_admin.main(base + ["add-member", "acme", "carol", "admin"]) == 1  # already a member
    assert tenancy_admin.main(base + ["set-membership", "acme", "carol", "inactive"]) == 0
    assert TenantRepository(url).resolve_active_membership("acme", "carol") is None
