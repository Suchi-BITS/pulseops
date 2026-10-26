"""P11 contract tests: the API surface, authentication per route, status classes, the error envelope, and the frontend types.

Strengthens the P9 OpenAPI assertions. The route table below is a deliberate snapshot: changing the API means changing this
table in the same commit, so an accidental contract change cannot pass unnoticed. Nothing here depends on ordering or on
generated metadata.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import ADMIN
from tests.test_phase7_gate9_1 import _approve, _hitl_in, bearer, tenants  # noqa: F401 (fixture)
from tests.test_phase9 import ERROR_KEYS, _scripted

pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[1]
PUBLIC = {("get", "/"), ("get", "/health"), ("get", "/health/ready")}

# (method, path): (sorted parameter names, deprecated)
EXPECTED_ROUTES: dict[tuple[str, str], tuple[list[str], bool]] = {
    ("get", "/"): ([], False),
    ("post", "/agent/investigate"): ([], False),
    ("get", "/health"): ([], False),
    ("get", "/health/ready"): ([], False),
    ("get", "/incidents"): (["limit", "offset", "order", "service_id", "severity", "sort", "status"], False),
    ("post", "/incidents"): ([], False),
    ("get", "/incidents/{incident_id}"): (["incident_id"], False),
    ("get", "/incidents/{incident_id}/detail"): (["incident_id"], False),
    ("get", "/incidents/{incident_id}/investigations"): (["incident_id"], False),
    ("post", "/incidents/{incident_id}/workflow/decision"): (["incident_id"], False),
    ("post", "/incidents/{incident_id}/workflow/evaluate"): (["incident_id"], False),
    ("get", "/me"): ([], False),
    ("get", "/retrieval/incidents/{incident_id}"): (["incident_id"], False),
    ("get", "/retrieval/services/{service_id}/dependencies"): (["service_id"], False),
    ("get", "/retrieval/services/{service_id}/incidents"): (["service_id"], False),
    ("get", "/workflow"): (["incident_id", "limit", "offset", "order", "requires_approval", "sort", "status"], False),
    ("post", "/workflow/evaluate"): ([], False),
    ("post", "/workflow/events"): ([], False),
    ("post", "/workflow/incidents/{incident_id}/decision"): (["incident_id"], True),
    ("post", "/workflow/incidents/{incident_id}/evaluate"): (["incident_id"], True),
    ("post", "/workflow/webhook"): ([], True),
    ("get", "/workflow/{workflow_id}"): (["workflow_id"], False),
    ("post", "/workflow/{workflow_id}/decision"): (["workflow_id"], False),
}

# Responses that are intentionally free-form JSON objects (everything else must declare a response model).
UNTYPED_200 = {
    ("get", "/"), ("get", "/health"),
    ("get", "/retrieval/incidents/{incident_id}"),
    ("get", "/retrieval/services/{service_id}/dependencies"), ("get", "/retrieval/services/{service_id}/incidents"),
}


def _operations():
    for path, operations in app.openapi()["paths"].items():
        for method, operation in operations.items():
            yield method, path, operation


def test_the_route_table_is_exactly_the_expected_contract() -> None:
    actual = {(m, p): (sorted(x["name"] for x in op.get("parameters", [])), bool(op.get("deprecated"))) for m, p, op in _operations()}
    assert set(actual) == set(EXPECTED_ROUTES), (
        f"added: {sorted(set(actual) - set(EXPECTED_ROUTES))}, removed: {sorted(set(EXPECTED_ROUTES) - set(actual))}; "
        "update EXPECTED_ROUTES deliberately if the API change is intended"
    )
    for key, expected in EXPECTED_ROUTES.items():
        assert actual[key] == expected, (key, actual[key], expected)


def test_expected_methods_and_no_unexpected_verbs() -> None:
    assert {m for m, _, _ in _operations()} <= {"get", "post"}  # no PUT/PATCH/DELETE surface exists
    reads = {(m, p) for m, p, _ in _operations() if m == "get"}
    assert all(not p.endswith(("/decision", "/evaluate", "/events", "/webhook")) for _, p in reads)  # state changes are POST only


def test_authentication_is_required_on_every_route_but_the_three_public_ones(tenants) -> None:
    client, *_ = tenants
    for method, path, _ in _operations():
        concrete = re.sub(r"\{[^}]+\}", "x", path)
        response = client.request(method.upper(), concrete, json={} if method == "post" else None)
        if (method, path) in PUBLIC:
            assert response.status_code in (200, 503), (method, path, response.status_code)  # readiness may be 503, never 401
            continue
        assert response.status_code == 401, (method, path)
        assert set(response.json()) == ERROR_KEYS and response.json()["code"] == "unauthorized"
        assert response.headers["WWW-Authenticate"] == "Bearer"


def test_an_authenticated_caller_never_gets_a_server_error_from_any_route() -> None:
    """Every route with valid credentials and empty, wrong or unknown input answers with a 2xx or a client-error class."""
    client = TestClient(app, raise_server_exceptions=False)
    for method, path, _ in _operations():
        concrete = re.sub(r"\{[^}]+\}", "no-such-id", path)
        for body in (None, {}, {"unexpected": [1, 2, 3]}) if method == "post" else (None,):
            response = client.request(method.upper(), concrete, headers=ADMIN, json=body)
            assert response.status_code < 500, (method, path, body, response.status_code, response.text[:200])
            if response.status_code >= 400:
                assert ERROR_KEYS <= set(response.json()), (method, path, response.json())
                assert response.json()["request_id"] == response.headers["X-Request-ID"]


def test_status_classes_use_the_envelope_with_stable_codes(tenants, monkeypatch, tmp_path) -> None:
    client, *_ = tenants
    _scripted(monkeypatch)
    workflow = _hitl_in(client, "n8n-a")
    assert _approve(client, "u1-a", workflow).status_code == 200
    legacy = tmp_path / "legacy.db"
    with sqlite3.connect(legacy) as c:
        c.execute("CREATE TABLE incidents (incident_id TEXT PRIMARY KEY)")

    produced = {
        400: client.post("/workflow/evaluate", headers=bearer("op-a"), json={"incident_id": "INC-1", "action": "  "}),
        401: client.get("/incidents"),
        403: client.post("/incidents", headers=bearer("u1-a"), json={}),
        404: client.get("/incidents/INC-NOPE", headers=bearer("op-a")),
        405: client.delete("/incidents", headers=bearer("op-a")),
        409: client.post(f"/workflow/{workflow['workflow_id']}/decision", headers=bearer("u1-a"), json={
            "decision": "reject", "incident_id": workflow["incident_id"], "action": "restart_service",
            "timestamp": "2026-01-01T00:00:00Z"}),
        413: client.post("/incidents", headers=bearer("op-a"), json={"title": "A" * 1_500_000}),
        422: client.get("/incidents?limit=0", headers=bearer("op-a")),
    }
    monkeypatch.setenv("PULSEOPS_DATABASE_URL", "sqlite:" + legacy.as_posix())
    produced[503] = client.get("/health/ready")
    expected_codes = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed",
                      409: "conflict", 413: "payload_too_large", 422: "validation_error", 503: "not_ready"}
    for status, response in produced.items():
        body = response.json()
        assert response.status_code == status, (status, response.status_code, response.text[:200])
        assert ERROR_KEYS <= set(body), (status, body)
        assert body["code"] == expected_codes[status] and isinstance(body["detail"], str) and body["request_id"]
        extra = set(body) - ERROR_KEYS
        assert extra <= ({"errors"} if status == 422 else {"status", "checks"} if status == 503 else set()), (status, extra)
        assert response.headers["X-Request-ID"] == body["request_id"]
    assert produced[401].headers["WWW-Authenticate"] == "Bearer"


def test_documented_responses_use_typed_models_and_the_error_model() -> None:
    spec = app.openapi()
    for method, path, operation in _operations():
        if (method, path) in PUBLIC:
            continue
        for status in ("401", "403", "404", "422"):
            schema = operation["responses"][status]["content"]["application/json"]["schema"]
            assert schema["$ref"].endswith("/ErrorResponse"), (method, path, status)
        if (method, path) not in UNTYPED_200:
            schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
            assert "$ref" in schema or "$ref" in schema.get("items", {}), f"{method} {path} has no declared response model"
    assert set(spec["components"]["schemas"]["ErrorResponse"]["properties"]) >= ERROR_KEYS


# ============================================================================================ frontend type contract

TS_TO_API = {  # frontend/src/types.ts interface -> OpenAPI schema it mirrors
    "Me": "MeResponse", "IncidentListItem": "IncidentListItem", "Incident": "IncidentResponse",
    "InvestigationRecord": "InvestigationRecord", "Workflow": "WorkflowResponse", "WorkflowSummary": "WorkflowSummary",
    "WorkflowList": "WorkflowListResponse", "AuditEntry": "AuditTimelineEntry", "HitlState": "HitlState",
    "IncidentDetail": "IncidentDetailResponse",
}


def _ts_interfaces() -> dict[str, set[str]]:
    source = (ROOT / "frontend" / "src" / "types.ts").read_text("utf-8")
    interfaces: dict[str, tuple[str | None, set[str]]] = {}
    for match in re.finditer(r"export interface (\w+)(?: extends (\w+))? \{(.*?)\n\}", source, re.DOTALL):
        fields = set(re.findall(r"^\s+(\w+)\??:", match.group(3), re.MULTILINE))
        interfaces[match.group(1)] = (match.group(2), fields)
    return {name: fields | (interfaces[parent][1] if parent else set()) for name, (parent, fields) in interfaces.items()}


def test_frontend_types_only_use_fields_the_api_actually_returns() -> None:
    schemas = app.openapi()["components"]["schemas"]
    interfaces = _ts_interfaces()
    assert set(TS_TO_API) <= set(interfaces)
    for ts_name, api_name in TS_TO_API.items():
        unknown = interfaces[ts_name] - set(schemas[api_name]["properties"])
        assert not unknown, f"frontend {ts_name} reads fields {sorted(unknown)} that {api_name} does not provide"


def test_frontend_types_cover_the_fields_the_ui_depends_on() -> None:
    interfaces = _ts_interfaces()
    assert {"investigation_status", "investigation", "hitl", "audit_timeline", "workflow", "incident"} <= interfaces["IncidentDetail"]
    assert {"evidence", "hypotheses", "missing_information", "recommendations", "confidence"} <= interfaces["InvestigationRecord"]
    assert {"can_decide", "decision_blocked_reason", "investigation_summary"} <= interfaces["WorkflowSummary"]
    assert {"state", "can_decide", "decision_blocked_reason"} <= interfaces["HitlState"]
