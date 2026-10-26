"""P9 - Modern Application: API contract, investigation record, reviewer read APIs, readiness, UI delivery.

Tenant-sensitive tests reuse the two-tenant, bearer-credential fixture of Gate 9.1 (the tenant always comes from the
authenticated membership). Role/permission tests that need a principal without any role use the development identity.
No live Claude call: investigators are scripted stubs.
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.workflow as workflow_api
from app.agent.service import InvestigationResult
from app.core.errors import ConflictError, NotFoundError, PulseOpsError
from app.database import DatabaseManager
from app.main import app
from app.migrations.p9 import MigrationError, migrate
from app.repositories.incident_repository import InvestigationRepository, WorkflowRepository
from app.services.event_service import InvestigationOutcome
from app.ui import CONTENT_SECURITY_POLICY, is_ui_path, mount_ui, security_headers_for
from tests.helpers import ADMIN, N8N, OPERATOR, REVIEWER, as_principal
from tests.test_phase7_gate9_1 import A, B, TOKENS, _approve, _hitl_in, _ingest, bearer, tenants  # noqa: F401
from tests.test_phase7_gate6 import StubInvestigator, _event

ERROR_KEYS = {"detail", "code", "request_id"}
NOBODY = as_principal("nobody")  # authenticated (development identity) but holds no role: no permission at all


def _scripted(monkeypatch, *, grounded: bool = True, fail: bool = False, evidence=("e1",)):
    """Replace the production investigator with a script (no model call)."""

    def build(database_url: str):  # noqa: ARG001
        async def investigate(incident_id: str, objective: str | None):
            if fail:
                raise RuntimeError("scripted failure")
            result = InvestigationResult(
                incident_id=incident_id, service_id="svc-payment", summary="scripted summary",
                evidence=list(evidence), hypotheses=["h1"], missing_information=["m1"], recommendations=["r1"],
                confidence=0.6, tool_calls=["mcp__pulseops__get_incident_context"],
            )
            return InvestigationOutcome(result=result, grounded=grounded)

        return investigate

    monkeypatch.setattr("app.services.event_service.build_investigator", build)


def _create_incident(client, who, severity="high", service="svc-payment", title="t"):
    response = client.post("/incidents", headers=bearer(who), json={
        "service_id": service, "severity": severity, "title": title, "description": "d", "environment": "production"})
    assert response.status_code == 200, response.text
    return response.json()


# ====================================================================================== P9.0 error envelope

def test_error_envelope_on_every_error_class(tenants) -> None:
    client, *_ = tenants
    hitl = _hitl_in(client, "n8n-a")

    cases = {
        "unauthorized": client.get("/incidents"),
        "forbidden": client.post("/incidents", headers=bearer("u1-a"), json={}),
        "not_found": client.get("/incidents/INC-NOPE", headers=bearer("op-a")),
        "validation_error": client.get("/incidents?limit=0", headers=bearer("op-a")),
    }
    approved = _approve(client, "u1-a", hitl)
    assert approved.status_code == 200
    cases["conflict"] = client.post(  # a different decision on a final workflow
        f"/workflow/{hitl['workflow_id']}/decision", headers=bearer("u1-a"),
        json={"decision": "reject", "incident_id": hitl["incident_id"], "action": "restart_service",
              "timestamp": "2026-01-01T00:00:00Z"})
    cases["not_found_route"] = client.get("/no/such/route", headers=bearer("op-a"))
    expected_status = {"unauthorized": 401, "forbidden": 403, "not_found": 404, "validation_error": 422, "conflict": 409,
                       "not_found_route": 404}
    for name, response in cases.items():
        body = response.json()
        assert response.status_code == expected_status[name], (name, response.text)
        assert ERROR_KEYS <= set(body), (name, body)
        assert isinstance(body["detail"], str) and body["detail"]
        assert body["code"] == name.replace("_route", ""), (name, body)
        assert body["request_id"] == response.headers["X-Request-ID"]
    assert cases["unauthorized"].headers["WWW-Authenticate"] == "Bearer"
    # Validation errors name the field and message but never echo the submitted value.
    bad = client.get("/incidents?limit=999999", headers=bearer("op-a")).json()
    assert bad["errors"] and "999999" not in json.dumps(bad["errors"])


def test_http_status_comes_from_the_exception_type_not_its_message() -> None:
    """The old mapping looked for words ("not found", "conflict", "deny", ...) in the message."""
    assert workflow_api._workflow_http_error(ValueError("this item was not found; conflict; DENY; final state")).status_code == 400
    assert workflow_api._workflow_http_error(NotFoundError("anything at all")).status_code == 404
    assert workflow_api._workflow_http_error(ConflictError("anything at all")).status_code == 409
    assert workflow_api._workflow_http_error(KeyError("workflow missing")).status_code == 400  # untyped: not guessed
    assert isinstance(NotFoundError("x"), KeyError) and isinstance(ConflictError("x"), ValueError)  # old catches still work
    assert str(NotFoundError("plain message")) == "plain message"  # KeyError would have added quotes
    assert issubclass(NotFoundError, PulseOpsError)


def test_unhandled_error_is_a_generic_enveloped_500(tenants, monkeypatch) -> None:
    client, *_ = tenants

    def boom(*_a, **_k):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr("app.api.routes.TenantRepository.get_tenant", boom)
    response = TestClient(app, raise_server_exceptions=False).get("/me", headers=bearer("op-a"))
    body = response.json()
    assert response.status_code == 500 and ERROR_KEYS <= set(body) and body["code"] == "internal_error"
    assert "secret" not in response.text and body["request_id"] == response.headers["X-Request-ID"]


# ====================================================================================== /me

def test_me_returns_the_authenticated_context_and_no_secret(tenants) -> None:
    client, *_ = tenants
    body = client.get("/me", headers=bearer("u1-a")).json()
    assert body["principal_id"] == body["user_id"] == "u1" and body["tenant_id"] == A and body["tenant_name"] == "Tenant A"
    assert body["is_human"] is True and body["principal_type"] == "human" and body["auth_method"] == "api_key"
    assert body["roles"][0] == "reviewer" and "workflow:approve" in body["permissions"]
    other = client.get("/me", headers=bearer("u1-b")).json()  # the same user in another tenant: other roles, other tenant
    assert other["tenant_id"] == B and other["roles"] == ["operator"] and "workflow:approve" not in other["permissions"]
    service = client.get("/me", headers=bearer("n8n-a")).json()
    assert service["is_human"] is False and service["principal_type"] == "service"
    text = json.dumps([body, other, service])
    for token in TOKENS.values():
        assert token not in text
    assert "sha256" not in text.lower() and "token" not in set(body)
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers={"Authorization": "Bearer " + "q" * 40}).status_code == 401


# ====================================================================================== incident list

def test_incident_pagination_filtering_sorting_and_tenant_scope(tenants) -> None:
    client, *_ = tenants
    created = [
        _create_incident(client, "op-a", "low", "svc-payment"), _create_incident(client, "op-a", "critical", "svc-only-a"),
        _create_incident(client, "op-a", "medium", "svc-payment"), _create_incident(client, "op-a", "high", "svc-only-a"),
        _create_incident(client, "op-a", "high", "svc-payment"),
    ]
    foreign = _create_incident(client, "op-b", "critical", "svc-payment", title="tenant B only")
    ids = {c["incident_id"] for c in created}

    everything = client.get("/incidents?limit=200", headers=bearer("op-a"))
    assert everything.status_code == 200 and isinstance(everything.json(), list)  # body shape unchanged
    assert ids <= {i["incident_id"] for i in everything.json()}
    assert int(everything.headers["X-Total-Count"]) == len(everything.json()) == 5
    assert all(i["title"] != "tenant B only" for i in everything.json())

    page1 = client.get("/incidents?limit=2&offset=0&sort=incident_id&order=asc", headers=bearer("op-a"))
    page2 = client.get("/incidents?limit=2&offset=2&sort=incident_id&order=asc", headers=bearer("op-a"))
    page3 = client.get("/incidents?limit=2&offset=4&sort=incident_id&order=asc", headers=bearer("op-a"))
    assert [len(p.json()) for p in (page1, page2, page3)] == [2, 2, 1]
    assert {p.headers["X-Total-Count"] for p in (page1, page2, page3)} == {"5"}
    paged = [i["incident_id"] for p in (page1, page2, page3) for i in p.json()]
    assert paged == sorted(ids) and len(set(paged)) == 5
    assert client.get("/incidents?limit=2&offset=50", headers=bearer("op-a")).json() == []

    high = client.get("/incidents?severity=high", headers=bearer("op-a"))
    assert {i["severity"] for i in high.json()} == {"high"} and high.headers["X-Total-Count"] == "2"
    only_a = client.get("/incidents?service_id=svc-only-a", headers=bearer("op-a"))
    assert {i["service_id"] for i in only_a.json()} == {"svc-only-a"} and only_a.headers["X-Total-Count"] == "2"
    assert client.get("/incidents?status=resolved", headers=bearer("op-a")).json() == []
    assert client.get("/incidents?status=open&severity=low", headers=bearer("op-a")).headers["X-Total-Count"] == "1"

    by_severity = [i["severity"] for i in client.get("/incidents?sort=severity&order=desc", headers=bearer("op-a")).json()]
    assert by_severity == ["critical", "high", "high", "medium", "low"]
    assert [i["severity"] for i in client.get("/incidents?sort=severity&order=asc", headers=bearer("op-a")).json()][0] == "low"

    for bad in ("sort=password", "order=sideways", "limit=0", "limit=201", "offset=-1", "severity=urgent", "status=bogus"):
        assert client.get(f"/incidents?{bad}", headers=bearer("op-a")).status_code == 422, bad

    # The tenant is never taken from the request: query parameter and header are ignored, not honoured.
    sneaky = client.get(f"/incidents?tenant_id={B}", headers={**bearer("op-a"), "X-Tenant-ID": B})
    assert sneaky.status_code == 200 and foreign["title"] == "tenant B only"
    assert all(i["title"] != "tenant B only" for i in sneaky.json()) and sneaky.headers["X-Total-Count"] == "5"
    assert client.get("/incidents").status_code == 401
    assert client.get("/incidents", headers=bearer("idle")).status_code == 403


def test_new_read_endpoints_forbid_a_principal_without_permissions() -> None:
    """Authenticated (development identity) but role-less: 403 on every P9 read endpoint; anonymous is 401."""
    client = TestClient(app)
    for path in ("/incidents", "/incidents/INC-1007/investigations", "/incidents/INC-1007/detail", "/workflow"):
        assert client.get(path, headers=NOBODY).status_code == 403, path
        body = client.get(path, headers=NOBODY).json()
        assert ERROR_KEYS <= set(body) and body["code"] == "forbidden"
    assert client.get("/me", headers=NOBODY).status_code == 200  # /me needs authentication only
    assert client.get("/me", headers=NOBODY).json()["permissions"] == []
    assert client.get("/me", headers={"X-Dev-Principal": "garbage"}).status_code == 401


# ====================================================================================== investigation record

def test_grounded_investigation_is_persisted_as_a_tenant_scoped_record(tenants, monkeypatch) -> None:
    client, url, _ = tenants
    _scripted(monkeypatch)
    hitl = _hitl_in(client, "n8n-a")
    assert hitl["investigation_id"] and hitl["investigation_status"] == "completed"

    records = client.get(f"/incidents/{hitl['incident_id']}/investigations", headers=bearer("op-a"))
    assert records.status_code == 200 and len(records.json()) == 1
    record = records.json()[0]
    assert record["investigation_id"] == hitl["investigation_id"]
    assert (record["tenant_id"], record["incident_id"], record["workflow_id"]) == (A, hitl["incident_id"], hitl["workflow_id"])
    # The four epistemic categories stay four separate fields.
    assert record["summary"] == "scripted summary" and record["evidence"] == ["e1"] and record["hypotheses"] == ["h1"]
    assert record["missing_information"] == ["m1"] and record["recommendations"] == ["r1"]
    assert record["confidence"] == 0.6 and record["tool_calls"] == ["mcp__pulseops__get_incident_context"]
    assert record["created_at"] and record["source"] == "workflow"

    # The workflow response carries the reference, on every read path.
    for path in (f"/workflow/{hitl['workflow_id']}",):
        assert client.get(path, headers=bearer("op-a")).json()["investigation_id"] == record["investigation_id"]
    audit = next(e for e in hitl["audit_events"] if e["event_type"] == "INVESTIGATION_COMPLETED")
    assert audit["metadata"]["investigation_id"] == record["investigation_id"]  # the audit trail still has it too

    # Idempotent replay of the same event does not create a second record.
    replay = client.post("/workflow/events", headers=bearer("n8n-a"), json=_event(event_id="evt-replay-1", metadata={"requested_action": "restart_service"}))
    again = client.post("/workflow/events", headers=bearer("n8n-a"), json=_event(event_id="evt-replay-1", metadata={"requested_action": "restart_service"}))
    assert again.json()["idempotent_replay"] is True and again.json()["investigation_id"] == replay.json()["investigation_id"]
    assert len(client.get(f"/incidents/{replay.json()['incident_id']}/investigations", headers=bearer("op-a")).json()) == 1

    # Cross-tenant: tenant B cannot read A's record, list it, or fetch the workflow that references it.
    assert client.get(f"/incidents/{hitl['incident_id']}/investigations", headers=bearer("op-b")).status_code == 404
    assert client.get(f"/workflow/{hitl['workflow_id']}", headers=bearer("op-b")).status_code == 404
    repo_b = InvestigationRepository(url, B)
    assert repo_b.get(record["investigation_id"]) is None and repo_b.list_for_incident(hitl["incident_id"]) == []
    assert InvestigationRepository(url, A).get(record["investigation_id"]).tenant_id == A


def test_investigation_endpoint_authentication_roles_and_unknown_incident(tenants) -> None:
    client, *_ = tenants
    hitl = _hitl_in(client, "n8n-a")
    path = f"/incidents/{hitl['incident_id']}/investigations"
    assert client.get(path).status_code == 401
    assert client.get(path, headers=bearer("idle")).status_code == 403
    assert client.get("/incidents/INC-NOPE/investigations", headers=bearer("op-a")).status_code == 404
    assert client.get(path, headers=bearer("u1-a")).status_code == 200  # a reviewer may read


def test_degraded_and_failed_investigations_are_never_stored(tenants, monkeypatch) -> None:
    client, *_ = tenants
    _scripted(monkeypatch, grounded=False)
    degraded = _ingest(client, "n8n-a").json()
    assert degraded["investigation_status"] == "degraded" and degraded["investigation_id"] is None
    _scripted(monkeypatch, fail=True)
    failed = _ingest(client, "n8n-a").json()
    assert failed["investigation_status"] == "failed" and failed["investigation_id"] is None
    for body, expected in ((degraded, "degraded"), (failed, "failed")):
        assert client.get(f"/incidents/{body['incident_id']}/investigations", headers=bearer("op-a")).json() == []
        detail = client.get(f"/incidents/{body['incident_id']}/detail", headers=bearer("op-a")).json()
        assert detail["investigation_status"] == expected and detail["investigation"] is None
        assert detail["hitl"]["state"] == "not_required" and detail["hitl"]["can_decide"] is False


def test_repository_enforces_the_workflow_and_tenant_relationship(tenants, monkeypatch) -> None:
    client, url, _ = tenants
    _scripted(monkeypatch)
    hitl = _hitl_in(client, "n8n-a")
    repo_a, repo_b = InvestigationRepository(url, A), InvestigationRepository(url, B)
    result = {"incident_id": hitl["incident_id"], "evidence": ["x"]}
    with pytest.raises(ValueError, match="Unknown workflow_id"):  # tenant B has no such workflow
        repo_b.create(hitl["workflow_id"], hitl["incident_id"], result)
    with pytest.raises(ValueError, match="does not belong"):  # right tenant, wrong incident
        repo_a.create(hitl["workflow_id"], "INC-OTHER", {"incident_id": "INC-OTHER"})
    with pytest.raises(sqlite3.IntegrityError):  # one investigation per workflow
        repo_a.create(hitl["workflow_id"], hitl["incident_id"], result)
    with DatabaseManager(url).get_connection() as c:  # the database itself refuses a cross-tenant reference
        with pytest.raises(sqlite3.IntegrityError):
            c.execute(
                "INSERT INTO investigations (tenant_id, investigation_id, incident_id, workflow_id, service_id, summary,"
                " evidence, hypotheses, missing_information, recommendations, confidence, tool_calls, created_at)"
                " VALUES (?, 'INV-X', 'i', ?, 's', '', '[]', '[]', '[]', '[]', 0, '[]', 'now')", (B, hitl["workflow_id"]))
    assert WorkflowRepository(url, A).get_workflow(hitl["workflow_id"]) is not None


# ====================================================================================== reviewer read APIs

def test_workflow_list_filters_pagination_hint_and_tenant_scope(tenants, monkeypatch) -> None:
    client, *_ = tenants
    _scripted(monkeypatch)
    hitl = [_hitl_in(client, "n8n-a") for _ in range(3)]
    low = _ingest(client, "n8n-a", metadata={"requested_action": "notify"}).json()
    foreign = _hitl_in(client, "n8n-b")

    queue = client.get("/workflow?status=pending&requires_approval=true&limit=200", headers=bearer("u1-a"))
    assert queue.status_code == 200
    body = queue.json()
    ids = {i["workflow_id"] for i in body["items"]}
    assert {h["workflow_id"] for h in hitl} <= ids and low["workflow_id"] not in ids and foreign["workflow_id"] not in ids
    assert body["total"] == len(body["items"]) and body["limit"] == 200 and body["offset"] == 0
    item = next(i for i in body["items"] if i["workflow_id"] == hitl[0]["workflow_id"])
    assert item["action"] == "restart_service" and item["requires_approval"] is True and item["status"] == "pending"
    assert item["investigation_summary"] == "scripted summary" and item["investigation_confidence"] == 0.6
    assert item["investigation_id"] == hitl[0]["investigation_id"]
    assert item["can_decide"] is True and item["decision_blocked_reason"] is None  # a hint only
    # The same queue seen by principals who may NOT decide gets can_decide = false with a reason.
    for who in ("op-a", "n8n-a"):
        seen = next(i for i in client.get("/workflow?limit=200", headers=bearer(who)).json()["items"]
                    if i["workflow_id"] == hitl[0]["workflow_id"])
        assert seen["can_decide"] is False and seen["decision_blocked_reason"]

    paged = [client.get(f"/workflow?incident_id={h['incident_id']}", headers=bearer("u1-a")).json() for h in hitl]
    assert all(p["total"] == 1 and len(p["items"]) == 1 for p in paged)
    first = client.get("/workflow?limit=2&offset=0&sort=created_at&order=asc", headers=bearer("u1-a")).json()
    second = client.get("/workflow?limit=2&offset=2&sort=created_at&order=asc", headers=bearer("u1-a")).json()
    assert len(first["items"]) == 2 and first["total"] == second["total"] >= 4
    assert not ({i["workflow_id"] for i in first["items"]} & {i["workflow_id"] for i in second["items"]})

    # Deciding is reflected in the read model (status and latest decision/reviewer).
    assert _approve(client, "u1-a", hitl[0]).status_code == 200
    done = client.get(f"/workflow?incident_id={hitl[0]['incident_id']}", headers=bearer("u1-a")).json()["items"][0]
    assert (done["status"], done["decision"], done["reviewer"], done["can_decide"]) == ("approved", "approve", "u1", False)

    # Tenant scope: B sees only B; no tenant selector exists.
    seen_b = client.get(f"/workflow?limit=200&tenant_id={A}", headers={**bearer("rev-b"), "X-Tenant-ID": A}).json()
    assert {i["workflow_id"] for i in seen_b["items"]} == {foreign["workflow_id"]}
    for bad in ("status=bogus", "sort=requested_by", "limit=0", "limit=500", "order=up"):
        assert client.get(f"/workflow?{bad}", headers=bearer("u1-a")).status_code == 422, bad
    assert client.get("/workflow").status_code == 401
    assert client.get("/workflow", headers=bearer("idle")).status_code == 403


def test_incident_detail_read_model(tenants, monkeypatch) -> None:
    client, *_ = tenants
    _scripted(monkeypatch)
    hitl = _hitl_in(client, "n8n-a")
    path = f"/incidents/{hitl['incident_id']}/detail"
    detail = client.get(path, headers=bearer("u1-a")).json()
    assert detail["incident"]["incident_id"] == hitl["incident_id"]
    assert detail["workflow"]["workflow_id"] == hitl["workflow_id"]
    assert detail["investigation_status"] == "completed" and detail["investigation"]["evidence"] == ["e1"]
    assert detail["hitl"] == {"required": True, "state": "awaiting_decision", "decision": None, "reviewer": None,
                              "can_decide": True, "decision_blocked_reason": None}
    types = [e["event_type"] for e in detail["audit_timeline"]]
    assert types[0] == "INCIDENT_RECEIVED" and "INVESTIGATION_COMPLETED" in types and "HITL_REQUESTED" in types
    # The timeline carries no free-form metadata (which can hold untrusted event or AI content).
    assert all(set(e) == {"audit_id", "event_type", "description", "actor", "actor_type", "timestamp"} for e in detail["audit_timeline"])

    operator_view = client.get(path, headers=bearer("op-a")).json()
    assert operator_view["hitl"]["can_decide"] is False and operator_view["hitl"]["decision_blocked_reason"]
    service_view = client.get(path, headers=bearer("n8n-a")).json()
    assert service_view["hitl"]["can_decide"] is False  # a service principal can never approve

    assert _approve(client, "u1-a", hitl).status_code == 200
    after = client.get(path, headers=bearer("u1-a")).json()
    assert after["hitl"]["state"] == "approved" and after["hitl"]["reviewer"] == "u1" and after["hitl"]["can_decide"] is False
    assert after["workflow"]["status"] == "approved"
    assert "HUMAN_DECISION" in [e["event_type"] for e in after["audit_timeline"]] or len(after["audit_timeline"]) > len(types)

    bare = _create_incident(client, "op-a")  # an incident nothing has investigated yet
    unavailable = client.get(f"/incidents/{bare['incident_id']}/detail", headers=bearer("op-a")).json()
    assert unavailable["workflow"] is None and unavailable["investigation"] is None
    assert unavailable["investigation_status"] == "unavailable" and unavailable["hitl"]["state"] == "not_required"
    assert unavailable["audit_timeline"] == []

    assert client.get(path).status_code == 401
    assert client.get(path, headers=bearer("op-b")).status_code == 404  # cross-tenant: indistinguishable from missing
    assert client.get("/incidents/INC-NOPE/detail", headers=bearer("op-a")).status_code == 404
    assert client.get(path, headers=bearer("idle")).status_code == 403


def test_rejected_decision_is_reported_as_rejected(tenants, monkeypatch) -> None:
    client, *_ = tenants
    _scripted(monkeypatch)
    hitl = _hitl_in(client, "n8n-a")
    rejected = client.post(f"/workflow/{hitl['workflow_id']}/decision", headers=bearer("u1-a"), json={
        "decision": "reject", "incident_id": hitl["incident_id"], "action": "restart_service",
        "timestamp": "2026-01-01T00:00:00Z", "rationale": "not now"})
    assert rejected.status_code == 200
    state = client.get(f"/incidents/{hitl['incident_id']}/detail", headers=bearer("u1-a")).json()["hitl"]
    assert state["state"] == "rejected" and state["decision"] == "reject" and state["reviewer"] == "u1"


# ====================================================================================== HITL stays backend-authoritative

def test_ui_hint_cannot_bypass_backend_authorization(tenants, monkeypatch) -> None:
    """can_decide is advisory. Forging the request the button would send is still refused by the backend."""
    client, *_ = tenants
    _scripted(monkeypatch)
    hitl = _hitl_in(client, "n8n-a")
    for who in ("n8n-a", "op-a", "bot-a"):  # service, operator, agent principals
        refused = _approve(client, who, hitl)
        assert refused.status_code == 403, (who, refused.text)
        assert ERROR_KEYS <= set(refused.json())
    assert _approve(client, "rev-b", hitl).status_code == 404  # another tenant's reviewer cannot even see it
    pending = client.get(f"/incidents/{hitl['incident_id']}/detail", headers=bearer("u1-a")).json()
    assert pending["hitl"]["state"] == "awaiting_decision"  # nothing changed


def test_self_approval_stays_blocked_and_is_reflected_in_the_hint() -> None:
    client = TestClient(app)
    requested = client.post("/workflow/evaluate", headers=ADMIN, json={
        "incident_id": "INC-1007", "action": "restart_service", "severity": "high"})
    assert requested.status_code == 200, requested.text
    wf = requested.json()
    assert wf["requires_approval"] is True and wf["status"] == "pending"
    mine = next(i for i in client.get("/workflow?incident_id=INC-1007&limit=200", headers=ADMIN).json()["items"]
                if i["workflow_id"] == wf["workflow_id"])
    assert mine["can_decide"] is False and "Self-approval" in mine["decision_blocked_reason"]
    theirs = next(i for i in client.get("/workflow?incident_id=INC-1007&limit=200", headers=REVIEWER).json()["items"]
                  if i["workflow_id"] == wf["workflow_id"])
    assert theirs["can_decide"] is True
    forced = client.post(f"/workflow/{wf['workflow_id']}/decision", headers=ADMIN, json={
        "decision": "approve", "incident_id": "INC-1007", "action": "restart_service", "timestamp": "2026-01-01T00:00:00Z"})
    assert forced.status_code == 403 and "Self-approval" in forced.json()["detail"]
    assert client.post(f"/workflow/{wf['workflow_id']}/decision", headers=N8N, json={
        "decision": "approve", "timestamp": "2026-01-01T00:00:00Z"}).status_code == 403


# ====================================================================================== compatibility

def test_duplicate_workflow_routes_remain_as_deprecated_aliases() -> None:
    schema = app.openapi()["paths"]
    for path, method in (("/workflow/webhook", "post"), ("/workflow/incidents/{incident_id}/evaluate", "post"),
                         ("/workflow/incidents/{incident_id}/decision", "post")):
        assert schema[path][method].get("deprecated") is True, path
    for path, method in (("/workflow/events", "post"), ("/workflow/evaluate", "post"), ("/workflow/{workflow_id}/decision", "post"),
                         ("/incidents/{incident_id}/workflow/evaluate", "post"),
                         ("/incidents/{incident_id}/workflow/decision", "post")):
        assert not schema[path][method].get("deprecated"), path
    # The deprecated routes still behave exactly like their canonical twins.
    client = TestClient(app)
    canonical = client.post("/incidents/INC-1007/workflow/evaluate", headers=ADMIN, json={"action": "notify"})
    alias = client.post("/workflow/incidents/INC-1007/evaluate", headers=ADMIN, json={"action": "notify"})
    webhook = client.post("/workflow/webhook", headers=ADMIN, json={"incident_id": "INC-1007", "action": "notify"})
    assert canonical.status_code == alias.status_code == webhook.status_code == 200
    assert canonical.json()["policy_decision"] == alias.json()["policy_decision"] == webhook.json()["policy_decision"]


def test_n8n_workflow_still_targets_the_unchanged_event_endpoint() -> None:
    workflow = json.loads((Path(__file__).resolve().parents[1] / "n8n" / "pulseops-event-workflow.json").read_text("utf-8"))
    urls = [n["parameters"].get("url") for n in workflow["nodes"] if "url" in n.get("parameters", {})]
    assert urls == ["http://pulseops:8000/workflow/events"]
    assert "/workflow/events" in app.openapi()["paths"]


# ====================================================================================== OpenAPI contract

def test_openapi_contract_for_the_application_surface() -> None:
    spec = app.openapi()
    paths, schemas = spec["paths"], spec["components"]["schemas"]
    for path, method in (("/me", "get"), ("/health/ready", "get"), ("/workflow", "get"),
                         ("/incidents/{incident_id}/investigations", "get"), ("/incidents/{incident_id}/detail", "get")):
        assert method in paths[path], path

    def ref(path, method, status="200"):
        return paths[path][method]["responses"][status]["content"]["application/json"]["schema"]

    assert ref("/me", "get")["$ref"].endswith("/MeResponse")
    assert ref("/workflow", "get")["$ref"].endswith("/WorkflowListResponse")
    assert ref("/incidents/{incident_id}/detail", "get")["$ref"].endswith("/IncidentDetailResponse")
    assert ref("/incidents/{incident_id}/investigations", "get")["items"]["$ref"].endswith("/InvestigationRecord")
    assert ref("/incidents/{incident_id}/workflow/evaluate", "post")["$ref"].endswith("/WorkflowResponse")  # no longer dict[str, object]
    assert ref("/incidents/{incident_id}/workflow/decision", "post")["$ref"].endswith("/WorkflowResponse")
    assert ref("/agent/investigate", "post")["$ref"].endswith("/InvestigationResult")
    for status_code in ("401", "403", "404", "422"):  # the documented error shape is the envelope
        assert ref("/incidents/{incident_id}", "get", status_code)["$ref"].endswith("/ErrorResponse")

    def props(name):
        return set(schemas[name]["properties"])

    assert {"detail", "code", "request_id"} <= props("ErrorResponse")
    assert {"principal_id", "tenant_id", "roles", "permissions", "is_human"} <= props("MeResponse")
    assert {"investigation_id", "tenant_id", "incident_id", "workflow_id", "summary", "evidence", "hypotheses",
            "missing_information", "recommendations", "confidence", "tool_calls"} <= props("InvestigationRecord")
    assert {"incident", "workflow", "investigation_status", "investigation", "hitl", "audit_timeline"} <= props("IncidentDetailResponse")
    assert {"items", "total", "limit", "offset"} <= props("WorkflowListResponse")
    assert {"can_decide", "decision_blocked_reason", "investigation_summary"} <= props("WorkflowSummary")
    assert "investigation_id" in props("WorkflowResponse") and "investigation_id" in props("WorkflowEventResponse")
    # No endpoint accepts a tenant selector from the caller.
    for operations in paths.values():
        for operation in operations.values():
            names = {p["name"].lower() for p in operation.get("parameters", [])}
            assert not names & {"tenant_id", "x-tenant-id", "tenant"}, operation.get("operationId")
    assert {p["name"] for p in paths["/incidents"]["get"]["parameters"]} >= {"status", "severity", "service_id", "sort", "order", "limit", "offset"}


# ====================================================================================== readiness and observability

def test_liveness_and_readiness(tenants) -> None:
    client, *_ = tenants
    assert client.get("/health").json()["status"] == "ok"
    ready = client.get("/health/ready")
    assert ready.status_code == 200 and ready.json() == {"status": "ready", "checks": {"database": "ok"}}


def test_readiness_is_not_ready_when_the_database_cannot_serve(tmp_path, monkeypatch) -> None:
    legacy = tmp_path / "legacy.db"
    with sqlite3.connect(legacy) as c:  # a pre-Gate-9.1 file: tenant-owned table without tenant_id
        c.execute("CREATE TABLE incidents (incident_id TEXT PRIMARY KEY)")
    monkeypatch.setenv("PULSEOPS_DATABASE_URL", "sqlite:" + legacy.as_posix())
    response = TestClient(app).get("/health/ready")
    body = response.json()
    assert response.status_code == 503 and body["code"] == "not_ready" and ERROR_KEYS <= set(body)
    assert body["checks"] == {"database": "error"}
    assert "legacy" not in response.text and str(tmp_path) not in response.text  # no path, no driver message
    with sqlite3.connect(legacy) as c:  # readiness never rebuilt or touched the legacy file
        assert [r[1] for r in c.execute("PRAGMA table_info(incidents)")] == ["incident_id"]


def test_access_log_has_route_status_latency_tenant_and_principal_but_no_token(tenants, caplog) -> None:
    client, *_ = tenants
    caplog.set_level(logging.INFO, logger="pulseops.http")
    client.get("/incidents?limit=1", headers={**bearer("op-a"), "X-Request-ID": "req-abcdef123456"})
    client.get("/incidents", headers=bearer("op-a"))
    record = next(r for r in caplog.records if getattr(r, "route", None) == "/incidents" and r.status_code == 200)
    assert record.method == "GET" and record.tenant_id == A and record.principal_id == "op-a"
    assert record.duration_ms >= 0 and record.outcome == "ok"
    from app.core.logging import JsonFormatter
    line = json.loads(JsonFormatter().format(record))
    assert line["route"] == "/incidents" and line["status_code"] == 200 and line["tenant_id"] == A
    everything = " ".join(str(v) for r in caplog.records for v in r.__dict__.values())
    for token in TOKENS.values():
        assert token not in everything
    assert "Authorization" not in everything and "Bearer " not in everything


# ====================================================================================== migration

def _database_with_a_stored_investigation(tmp_path, monkeypatch):
    url = "sqlite:" + (tmp_path / "pre-p9.db").as_posix()
    monkeypatch.setenv("PULSEOPS_DATABASE_URL", url)
    DatabaseManager(url)
    return url


def _drop_table(url: str) -> None:
    with DatabaseManager(url).get_connection() as c:
        c.execute("DROP TABLE investigations")


def test_startup_only_adds_the_empty_table_and_never_touches_existing_data(tenants, monkeypatch) -> None:
    client, url, _ = tenants
    _scripted(monkeypatch)
    hitl = _hitl_in(client, "n8n-a")
    _drop_table(url)  # a database as it was before P9
    with sqlite3.connect(url.removeprefix("sqlite:")) as c:
        before = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("incidents", "workflow_instances", "workflow_audit_events")}
    DatabaseManager(url)  # normal startup path
    with sqlite3.connect(url.removeprefix("sqlite:")) as c:
        assert c.execute("SELECT COUNT(*) FROM investigations").fetchone()[0] == 0  # nothing is invented
        after = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in before}
    assert before == after and hitl["workflow_id"]


def test_p9_migration_backs_up_backfills_only_grounded_results_and_is_idempotent(tenants, monkeypatch) -> None:
    client, url, _ = tenants
    _scripted(monkeypatch)
    good = _hitl_in(client, "n8n-a")
    other = _hitl_in(client, "n8n-b")
    path = Path(url.removeprefix("sqlite:"))
    _drop_table(url)

    # A hand-made completed event with NO evidence (not grounded) and one for another incident are never backfilled.
    with sqlite3.connect(path) as c:
        c.execute(
            "INSERT INTO workflow_audit_events (audit_id, tenant_id, workflow_id, incident_id, event_id, event_type, actor_type,"
            " actor_id, timestamp, details) VALUES ('AUD-BAD1', ?, ?, ?, 'AUD-BAD1', 'INVESTIGATION_COMPLETED', 'agent', 'x',"
            " '2026-01-01T00:00:00+00:00', ?)",
            (A, good["workflow_id"], good["incident_id"], json.dumps({"investigation": {"incident_id": "INC-ELSEWHERE", "evidence": ["x"]}})))

    counts = migrate(url)
    assert counts["table_created"] == 1 and counts["backfilled"] == 2 and counts["skipped"] == 1
    backup = path.with_name(path.name + ".pre-p9.bak")
    assert backup.exists()
    with sqlite3.connect(backup) as c:  # the backup is the pre-migration file: no investigations table
        assert c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'investigations'").fetchone()[0] == 0

    repo_a, repo_b = InvestigationRepository(url, A), InvestigationRepository(url, B)
    restored = repo_a.list_for_incident(good["incident_id"])
    assert len(restored) == 1 and restored[0].source == "backfill" and restored[0].tenant_id == A
    assert restored[0].evidence == ["e1"] and restored[0].hypotheses == ["h1"] and restored[0].recommendations == ["r1"]
    assert restored[0].workflow_id == good["workflow_id"]
    assert len(repo_b.list_for_incident(other["incident_id"])) == 1  # each record keeps its own tenant
    assert all(r.workflow_id != other["workflow_id"] for r in repo_a.list_for_incident(other["incident_id"]))
    assert repo_b.get_for_workflow(good["workflow_id"]) is None and repo_a.get_for_workflow(other["workflow_id"]) is None

    assert migrate(url) == {}  # idempotent: nothing to do, no second backup attempt, no duplicates
    assert len(repo_a.list_for_incident(good["incident_id"])) == 1
    workflow = client.get(f"/workflow/{good['workflow_id']}", headers=bearer("op-a")).json()
    assert workflow["investigation_id"] == restored[0].investigation_id


def test_p9_migration_refuses_unsafe_inputs(tmp_path, monkeypatch) -> None:
    with pytest.raises(MigrationError, match="not found"):
        migrate("sqlite:" + (tmp_path / "missing.db").as_posix())
    legacy = tmp_path / "legacy.db"
    with sqlite3.connect(legacy) as c:
        c.execute("CREATE TABLE incidents (incident_id TEXT PRIMARY KEY)")
        c.execute("CREATE TABLE workflow_instances (workflow_id TEXT PRIMARY KEY)")
    with pytest.raises(MigrationError, match="gate9_1"):
        migrate("sqlite:" + legacy.as_posix())
    assert not legacy.with_name("legacy.db.pre-p9.bak").exists()  # refused before any backup or change
    empty = tmp_path / "other.db"
    sqlite3.connect(empty).close()
    with pytest.raises(MigrationError, match="not a PulseOps database"):
        migrate("sqlite:" + empty.as_posix())


def test_p9_migration_refuses_to_overwrite_an_existing_backup(tenants, monkeypatch) -> None:
    client, url, _ = tenants
    _scripted(monkeypatch)
    _hitl_in(client, "n8n-a")
    path = Path(url.removeprefix("sqlite:"))
    _drop_table(url)
    path.with_name(path.name + ".pre-p9.bak").write_bytes(b"precious")
    with pytest.raises(MigrationError, match="backup already exists"):
        migrate(url)
    assert path.with_name(path.name + ".pre-p9.bak").read_bytes() == b"precious"
    with sqlite3.connect(path) as c:  # and the database itself was not changed
        assert c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'investigations'").fetchone()[0] == 0


# ====================================================================================== UI delivery and CSP

def test_security_headers_and_csp_policy() -> None:
    assert is_ui_path("/ui") and is_ui_path("/ui/") and is_ui_path("/ui/assets/app.js") and not is_ui_path("/uix")
    assert not is_ui_path("/docs") and not is_ui_path("/")
    ui = security_headers_for("/ui/")
    assert ui["Content-Security-Policy"] == CONTENT_SECURITY_POLICY
    for directive in ("default-src 'none'", "script-src 'self'", "style-src 'self'", "connect-src 'self'",
                      "frame-ancestors 'none'", "base-uri 'none'", "object-src 'none'", "form-action 'none'"):
        assert directive in CONTENT_SECURITY_POLICY, directive
    assert "unsafe-inline" not in CONTENT_SECURITY_POLICY and "unsafe-eval" not in CONTENT_SECURITY_POLICY
    assert "http:" not in CONTENT_SECURITY_POLICY and "*" not in CONTENT_SECURITY_POLICY
    api = security_headers_for("/incidents")
    assert "Content-Security-Policy" not in api and api["X-Content-Type-Options"] == "nosniff"
    assert api["X-Frame-Options"] == "DENY" and api["Referrer-Policy"] == "no-referrer"


def test_every_response_carries_baseline_security_headers(tenants) -> None:
    client, *_ = tenants
    for path in ("/", "/health", "/incidents", "/no/such/route"):
        response = client.get(path)
        assert response.headers["X-Content-Type-Options"] == "nosniff" and response.headers["X-Frame-Options"] == "DENY"
        assert "Content-Security-Policy" not in response.headers  # API responses are JSON; the CSP is for the UI


def test_mount_ui_serves_assets_and_is_optional(tmp_path) -> None:
    sandbox = FastAPI()
    assert mount_ui(sandbox, tmp_path / "nothing") is False  # the API works without a UI build
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id='root'></div>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('x')", encoding="utf-8")
    assert mount_ui(sandbox, dist) is True
    client = TestClient(sandbox)
    assert client.get("/ui/").status_code == 200 and "root" in client.get("/ui/").text
    assert client.get("/ui/assets/app.js").status_code == 200
    assert client.get("/ui/assets/missing.js").status_code == 404
    assert client.get("/ui/../secret").status_code in (404, 307, 308, 400)


UI_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"


@pytest.mark.skipif(not (UI_DIST / "index.html").is_file(), reason="frontend not built (npm run build in frontend/)")
def test_built_ui_is_served_by_the_application_with_csp() -> None:
    client = TestClient(app)
    page = client.get("/ui/")
    assert page.status_code == 200 and '<div id="root">' in page.text
    assert page.headers["Content-Security-Policy"] == CONTENT_SECURITY_POLICY
    assert page.headers["X-Frame-Options"] == "DENY" and page.headers["X-Content-Type-Options"] == "nosniff"
    assert "<script" in page.text and "unsafe" not in page.text
    inline = [part for part in page.text.split("<script")[1:] if "src=" not in part.split(">")[0]]
    assert inline == []  # no inline script: the CSP would block it
    assets = sorted((UI_DIST / "assets").glob("*.js"))
    assert assets
    js = client.get(f"/ui/assets/{assets[0].name}")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
    assert js.headers["Content-Security-Policy"] == CONTENT_SECURITY_POLICY
    # The API root is unaffected, and the dev-only docs keep working without the UI CSP.
    assert client.get("/").json()["message"].endswith("is running")
    assert "Content-Security-Policy" not in client.get("/docs").headers


@pytest.mark.skipif(not (UI_DIST / "index.html").is_file(), reason="frontend not built (npm run build in frontend/)")
def test_built_ui_bundle_contains_no_credentials_or_token_storage() -> None:
    bundle = "\n".join(p.read_text("utf-8", errors="ignore") for p in UI_DIST.rglob("*") if p.suffix in {".js", ".html", ".css"})
    for forbidden in ("sk-ant-", "sessionStorage", "indexedDB", "document.cookie", "X-Tenant-ID", "x-tenant-id"):
        assert forbidden not in bundle, forbidden
    for token in TOKENS.values():
        assert token not in bundle
