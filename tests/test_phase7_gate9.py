"""Phase 7 Gate 9 - production application hardening & local platform readiness tests."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.api.workflow as workflow_api
from app.agent.service import InvestigationResult
from app.core import security
from app.core.config import ConfigurationError, get_settings, validate_runtime_security
from app.core.logging import JsonFormatter, redact
from app.core.request_context import REQUEST_ID_HEADER, sanitize_request_id
from app.core.security import Permission, Principal, PrincipalType, hash_token
from app.database import DatabaseManager
from app.main import app
from app.services.event_service import InvestigationOutcome
from tests.helpers import ADMIN, AGENT, DEV_TENANT, N8N, OPERATOR, REVIEWER, as_principal, provision_members
from tests.test_phase7_gate6 import StubInvestigator, _event, env  # noqa: F401  (env is a pytest fixture)

REPO = Path(__file__).resolve().parents[1]
TOKENS = {
    "svc-n8n": "n8n-service-token-0123456789abcdef",
    "alice": "alice-reviewer-token-0123456789abcdef",
    "bob": "bob-reviewer-token-0123456789abcdef",
    "omar": "omar-operator-token-0123456789abcdef",
    "root": "root-admin-token-0123456789abcdef",
    "bot": "bot-agent-token-0123456789abcdef",
}


# user -> (type, tenant role, domain roles). Roles live on the TenantUser membership, not on the credential.
MEMBERS = {
    "svc-n8n": ("service", "service_n8n", ()),
    "alice": ("human", "reviewer", ("sre", "incident_manager")),
    "bob": ("human", "reviewer", ()),  # a reviewer with no domain role for any action
    "omar": ("human", "operator", ()),
    "root": ("human", "admin", ()),
    "bot": ("agent", "operator", ()),
}


def _credentials() -> list[dict]:
    """Each credential binds a token to exactly one user and one tenant (here the development tenant)."""
    return [{"principal_id": pid, "tenant_id": DEV_TENANT, "token_sha256": hash_token(TOKENS[pid])} for pid in MEMBERS]


def bearer(principal_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKENS[principal_id]}"}


@pytest.fixture()
def apikey_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    provision_members(get_settings().database_url, DEV_TENANT, MEMBERS)
    monkeypatch.setenv("PULSEOPS_AUTH_MODE", "apikey")
    monkeypatch.setenv("PULSEOPS_API_CREDENTIALS", json.dumps(_credentials()))


def _hitl(client, headers, action="restart_service", **overrides):
    body = client.post("/workflow/events", headers=headers, json=_event(metadata={"requested_action": action}, **overrides)).json()
    assert body["policy_decision"] == "hitl_required", body
    return body


def _decide(client, headers, body, decision="approve", action="restart_service", **extra):
    return client.post(
        f"/workflow/{body['workflow_id']}/decision",
        headers=headers,
        json={"decision": decision, "incident_id": body["incident_id"], "action": action,
              "timestamp": "2026-01-01T00:00:00Z", **extra},
    )


# =========================================================================== authentication


def test_root_and_health_are_public_and_expose_no_secrets(apikey_mode, monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-SECRET-KEY-VALUE")
    client = TestClient(app)
    for path in ("/", "/health", "/health/ready"):  # P9.4 adds the unauthenticated readiness probe
        assert client.get(path).status_code == 200
    text = client.get("/health").text + client.get("/").text + client.get("/health/ready").text
    for secret in ("sk-ant-SECRET-KEY-VALUE", *TOKENS.values(), *(c["token_sha256"] for c in _credentials())):
        assert secret not in text


def test_every_other_route_requires_authentication(apikey_mode) -> None:
    client = TestClient(app)
    public = {"/", "/health", "/health/ready"}  # P9.4: readiness is the only public route added (no data, no secrets)
    checked = 0
    # The OpenAPI schema enumerates the whole application surface (FastAPI wraps included routers lazily, so
    # walking app.routes would miss most of them).
    for path, operations in app.openapi()["paths"].items():
        if path in public:
            continue
        concrete = re.sub(r"\{[^}]+\}", "x", path)
        for method in operations:
            response = client.request(method.upper(), concrete, json={})
            assert response.status_code == 401, f"{method.upper()} {path} is reachable without authentication"
            assert response.headers.get("WWW-Authenticate") == "Bearer"
            checked += 1
    assert checked >= 15  # the whole application surface was enumerated, not a hand-picked sample
    assert set(app.openapi()["paths"]) >= public


def test_valid_service_and_human_principals_authenticate(env, apikey_mode) -> None:
    client, *_ = env
    ingest = client.post("/workflow/events", headers=bearer("svc-n8n"), json=_event(severity="low"))
    assert ingest.status_code == 200
    assert client.get("/incidents", headers=bearer("alice")).status_code == 200


def test_invalid_and_malformed_credentials_are_rejected_without_echo(apikey_mode) -> None:
    client = TestClient(app)
    bad_headers = [
        {"Authorization": "Bearer " + "x" * 32},
        {"Authorization": "Bearer short"},
        {"Authorization": "Bearer bad token with spaces 0123456789"},
        {"Authorization": "Basic YWxpY2U6cGFzcw=="},
        {"Authorization": "Bearer"},
        {"Authorization": TOKENS["alice"]},  # missing scheme
        {"Authorization": "Bearer " + TOKENS["alice"] + "tampered"},
    ]
    for headers in bad_headers:
        response = client.get("/incidents", headers=headers)
        assert response.status_code == 401, headers
        body = response.json()  # P9.0: the error envelope adds code and request_id; the message is unchanged
        assert body["detail"] == "Authentication required" and body["code"] == "unauthorized" and body["request_id"]
        assert set(body) == {"detail", "code", "request_id"}
        assert TOKENS["alice"] not in response.text


def test_credentials_are_compared_in_constant_time_against_every_entry(apikey_mode, monkeypatch) -> None:
    calls: list[int] = []
    real = security.hmac.compare_digest
    monkeypatch.setattr(security.hmac, "compare_digest", lambda a, b: (calls.append(1), real(a, b))[1])
    settings = SimpleNamespace(api_credentials=_credentials(), database_url=get_settings().database_url)
    assert security.authenticate_token(TOKENS["svc-n8n"], settings).principal_id == "svc-n8n"  # first entry matches
    assert len(calls) == len(_credentials())  # no early exit
    calls.clear()
    assert security.authenticate_token("nope-" * 8, settings) is None
    assert len(calls) == len(_credentials())


def test_credential_configuration_stores_hashes_only(monkeypatch) -> None:
    for entry in _credentials():
        assert len(entry["token_sha256"]) == 64 and entry["token_sha256"] not in TOKENS.values()
    with pytest.raises(ConfigurationError):
        security.validate_credentials([{"principal_id": "x", "tenant_id": "dev", "token": "plaintext-token-123456789"}])
    monkeypatch.setenv("PULSEOPS_API_CREDENTIALS", json.dumps(_credentials()))
    assert not any(token in repr(get_settings()) for token in TOKENS.values())


def test_dev_header_works_only_in_the_development_environment() -> None:
    client = TestClient(app)
    created = client.post("/incidents", headers=OPERATOR, json={"service_id": "svc-payment", "severity": "low", "title": "t", "description": "d", "environment": "dev"})
    assert created.status_code == 200  # dev header honoured in development
    no_roles = client.post("/incidents", headers=as_principal("nobody"), json={})
    assert no_roles.status_code == 403  # the header's roles are what authorize, not a blanket pass
    assert client.get("/incidents", headers={"X-Dev-Principal": "garbage"}).status_code == 401


def test_dev_header_is_ignored_and_rejected_outside_development(monkeypatch) -> None:
    monkeypatch.setenv("PULSEOPS_ENVIRONMENT", "production")
    monkeypatch.setenv("PULSEOPS_AUTH_MODE", "apikey")
    monkeypatch.setenv("PULSEOPS_API_CREDENTIALS", json.dumps(_credentials()))
    client = TestClient(app)
    assert client.get("/incidents", headers=ADMIN).status_code == 401  # header alone is never an identity
    # The header cannot upgrade a real credential either: the bearer principal (reviewer, no incident:write) is used.
    mixed = client.post("/incidents", headers={**bearer("bob"), **ADMIN}, json={})
    assert mixed.status_code == 403
    # Even a mis-set dev auth mode is refused outside development, per request and at startup.
    monkeypatch.setenv("PULSEOPS_AUTH_MODE", "dev")
    assert client.get("/incidents", headers=ADMIN).status_code == 401
    with pytest.raises(ConfigurationError):
        validate_runtime_security()


def test_dev_mode_never_falls_back_to_the_dev_identity_for_a_bad_bearer_token() -> None:
    client = TestClient(app)
    assert client.get("/incidents", headers={"Authorization": "Bearer " + "z" * 40}).status_code == 401


# =========================================================================== authorization / RBAC


def test_n8n_can_ingest_but_cannot_approve(env, apikey_mode) -> None:
    client, *_ = env
    body = _hitl(client, bearer("svc-n8n"))
    assert body["status"] == "pending" and body["requires_approval"] is True
    denied = _decide(client, bearer("svc-n8n"), body)
    assert denied.status_code == 403
    assert client.get(f"/workflow/{body['workflow_id']}", headers=bearer("svc-n8n")).json()["status"] == "pending"


def test_authorized_reviewer_can_approve_and_decision_is_audited_with_the_principal(env, apikey_mode) -> None:
    client, *_ = env
    body = _hitl(client, bearer("svc-n8n"))
    response = _decide(client, {**bearer("alice"), REQUEST_ID_HEADER: "approval-req-0001"}, body)
    assert response.status_code == 200 and response.json()["status"] == "approved"
    assert response.headers[REQUEST_ID_HEADER] == "approval-req-0001"
    approved = next(e for e in response.json()["audit_events"] if e["event_type"] == "HITL_APPROVED")
    assert approved["actor"] == "alice" and approved["actor_type"] == "human"
    assert approved["metadata"]["request_id"] == "approval-req-0001"
    assert approved["metadata"]["principal_type"] == "human"
    assert set(approved["metadata"]["principal_roles"]) == {"reviewer", "sre", "incident_manager"}
    assert response.json()["reviewer"] == "alice"


def test_agent_and_service_principals_cannot_approve_even_with_reviewer_roles(env) -> None:
    client, *_ = env
    body = _hitl(client, N8N)
    for headers in (AGENT, as_principal("svc-x", "reviewer", "sre", kind="service"), as_principal("sys", "admin", kind="system")):
        assert _decide(client, headers, body).status_code == 403
    assert client.get(f"/workflow/{body['workflow_id']}").json()["status"] == "pending"


def test_policy_permitted_roles_are_enforced_for_approvals(env, apikey_mode) -> None:
    client, *_ = env
    body = _hitl(client, bearer("svc-n8n"))
    assert _decide(client, bearer("bob"), body).status_code == 403  # reviewer role, but no sre / incident_manager role
    assert _decide(client, bearer("omar"), body).status_code == 403  # operator lacks workflow:approve
    assert _decide(client, bearer("alice"), body).status_code == 200  # sre / incident_manager


def test_admin_may_approve_an_action_regardless_of_domain_roles(env, apikey_mode) -> None:
    client, *_ = env
    body = _hitl(client, bearer("svc-n8n"))
    assert _decide(client, bearer("root"), body).status_code == 200


def test_spoofed_and_mismatched_reviewer_fields_are_rejected(env, apikey_mode) -> None:
    client, *_ = env
    body = _hitl(client, bearer("svc-n8n"))
    spoof = _decide(client, bearer("bob"), body, reviewer="alice")  # bob claiming to be the authorized alice
    assert spoof.status_code == 403 and "does not match" in spoof.json()["detail"]
    assert _decide(client, bearer("alice"), body, reviewer="someone-else").status_code == 403
    assert _decide(client, bearer("alice"), body, reviewer="").status_code == 403
    assert client.get(f"/workflow/{body['workflow_id']}", headers=bearer("alice")).json()["status"] == "pending"
    assert _decide(client, bearer("alice"), body, reviewer="alice").status_code == 200  # a matching field is tolerated


def test_self_approval_is_prevented(env) -> None:
    client, *_ = env
    both = as_principal("dual-dana", "operator", "reviewer", "sre")
    body = client.post("/workflow/evaluate", headers=both, json={"incident_id": client.post(
        "/incidents", headers=both, json={"service_id": "svc-payment", "severity": "high", "title": "t", "description": "d", "environment": "p"},
    ).json()["incident_id"], "action": "restart_service"}).json()
    assert body["requested_by"] == "dual-dana"  # the requester is the principal, not a caller-supplied name
    denied = _decide(client, both, body)
    assert denied.status_code == 403 and "Self-approval" in denied.json()["detail"]
    assert _decide(client, REVIEWER, body).status_code == 200  # a different authorized human can


def test_requested_by_is_never_taken_from_the_request_body(env) -> None:
    client, *_ = env
    incident = client.post("/incidents", headers=OPERATOR, json={"service_id": "svc-payment", "severity": "low", "title": "t", "description": "d", "environment": "p"}).json()
    body = client.post("/workflow/evaluate", headers=OPERATOR, json={"incident_id": incident["incident_id"], "action": "notify", "requested_by": "CEO"}).json()
    assert body["requested_by"] == "operator-omar"


def test_idempotent_repeated_approval_and_conflicts_remain(env) -> None:
    client, *_ = env
    body = _hitl(client, N8N)
    first = _decide(client, REVIEWER, body)
    again = _decide(client, REVIEWER, body)
    assert first.status_code == again.status_code == 200 and again.json()["status"] == "approved"
    assert _decide(client, REVIEWER, body, decision="reject").status_code == 409  # approved -> rejected is a conflict
    other = _decide(client, as_principal("reviewer-ruth", "reviewer", "sre"), body)
    assert other.status_code == 409  # a different human cannot re-decide a final workflow


def test_denied_and_failed_workflows_cannot_be_overridden(env) -> None:
    client, *_ = env
    denied = client.post("/workflow/events", headers=N8N, json=_event(metadata={"requested_action": "delete_data"})).json()
    assert denied["policy_decision"] == "deny"
    assert _decide(client, ADMIN, denied, action="delete_data").status_code == 409
    assert _decide(client, REVIEWER, denied, action="delete_data").status_code == 409


def test_operator_and_admin_permissions(env) -> None:
    client, *_ = env
    incident = {"service_id": "svc-payment", "severity": "low", "title": "t", "description": "d", "environment": "p"}
    assert client.post("/incidents", headers=OPERATOR, json=incident).status_code == 200
    assert client.get("/incidents", headers=OPERATOR).status_code == 200
    assert client.post("/workflow/events", headers=OPERATOR, json=_event(severity="low")).status_code == 200
    assert client.post("/incidents", headers=ADMIN, json=incident).status_code == 200
    assert client.get("/retrieval/incidents/INC-1007", headers=ADMIN).status_code == 200


def test_unauthorized_roles_get_403_not_401(env) -> None:
    client, *_ = env
    incident = {"service_id": "svc-payment", "severity": "low", "title": "t", "description": "d", "environment": "p"}
    assert client.post("/incidents", headers=REVIEWER, json=incident).status_code == 403
    assert client.post("/incidents", headers=N8N, json=incident).status_code == 403
    assert client.post("/workflow/evaluate", headers=N8N, json={"incident_id": "INC-1007", "action": "notify"}).status_code == 403
    assert client.post("/agent/investigate", headers=N8N, json={"incident_id": "INC-1007"}).status_code == 403
    assert client.post("/agent/investigate", headers=REVIEWER, json={"incident_id": "INC-1007"}).status_code == 403
    assert client.post("/workflow/events", headers=REVIEWER, json=_event()).status_code == 403
    assert client.get("/incidents", headers=N8N).status_code == 200  # read is allowed for the service role


def test_the_legacy_incident_decision_route_is_protected_the_same_way(env) -> None:
    client, *_ = env
    body = _hitl(client, N8N)
    url = f"/incidents/{body['incident_id']}/workflow/decision"
    payload = {"decision": "approve", "incident_id": body["incident_id"], "action": "restart_service", "timestamp": "2026-01-01T00:00:00Z"}
    assert client.post(url, headers=N8N, json=payload).status_code == 403
    assert client.post(url, headers=AGENT, json=payload).status_code == 403
    assert client.post(url, headers=REVIEWER, json={**payload, "reviewer": "forged"}).status_code == 403
    assert client.post(url, headers=REVIEWER, json=payload).status_code == 200


def test_agent_identity_context_comes_from_the_authenticated_principal(monkeypatch) -> None:
    import app.api.agent as agent_api

    seen = {}

    class FakeAgent:
        def __init__(self, database_url=None) -> None:
            pass

        async def investigate(self, incident_id, objective=None, identity_context=None):
            seen["identity"] = identity_context
            return InvestigationResult(incident_id=incident_id, summary="s")

    monkeypatch.setattr(agent_api, "IncidentInvestigationAgent", FakeAgent)
    response = TestClient(app).post("/agent/investigate", headers=as_principal("omar", "operator"),
                                    json={"incident_id": "INC-1007", "tenant_id": "evil", "user_id": "evil"})
    assert response.status_code == 200
    identity = seen["identity"]
    assert identity.user_id == "omar" and identity.tenant_id == "dev" and identity.roles == ["operator"]
    assert "agent:investigate" in identity.permissions and "workflow:approve" not in identity.permissions


def test_principal_contract_and_role_permissions() -> None:
    p = Principal(principal_id="x", principal_type=PrincipalType.HUMAN, roles=("reviewer",), tenant_id="t", auth_method="api_key")
    assert p.is_human and p.has(Permission.WORKFLOW_APPROVE) and not p.has(Permission.EVENTS_INGEST)
    assert p.tenant_id == "t" and p.user_id == "x" and p.authenticated_at is not None
    n8n = Principal(principal_id="n", principal_type=PrincipalType.SERVICE, roles=("service_n8n",), tenant_id="t", auth_method="api_key")
    assert n8n.has(Permission.EVENTS_INGEST) and not n8n.has(Permission.WORKFLOW_APPROVE) and not n8n.is_human
    admin = Principal(principal_id="a", principal_type=PrincipalType.HUMAN, roles=("admin",), tenant_id="t", auth_method="api_key")
    assert all(admin.has(permission) for permission in Permission)
    with pytest.raises(Exception):
        p.principal_id = "y"  # frozen


# =========================================================================== configuration / secrets


def test_runtime_security_validation_fails_closed(monkeypatch) -> None:
    valid = json.dumps(_credentials())
    monkeypatch.setenv("PULSEOPS_ENVIRONMENT", "production")
    for var in ("PULSEOPS_AUTH_MODE", "PULSEOPS_API_CREDENTIALS"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ConfigurationError, match="PULSEOPS_API_CREDENTIALS is required"):
        validate_runtime_security()  # production defaults to API credentials, and none are configured
    monkeypatch.setenv("PULSEOPS_API_CREDENTIALS", "not json")
    with pytest.raises(ConfigurationError):
        get_settings()
    monkeypatch.setenv("PULSEOPS_API_CREDENTIALS", json.dumps([{"principal_id": "x", "tenant_id": "dev"}]))
    with pytest.raises(ConfigurationError, match="token_sha256"):
        validate_runtime_security()
    monkeypatch.setenv("PULSEOPS_API_CREDENTIALS", json.dumps([{"principal_id": "svc", "tenant_id": "dev", "roles": ["reviewer"], "token_sha256": "0" * 64}]))
    with pytest.raises(ConfigurationError, match="tenant membership"):
        validate_runtime_security()
    monkeypatch.setenv("PULSEOPS_API_CREDENTIALS", valid)
    validate_runtime_security()  # a complete configuration starts
    monkeypatch.setenv("PULSEOPS_AUTH_MODE", "bogus")
    with pytest.raises(ConfigurationError):
        validate_runtime_security()


def test_startup_refuses_to_run_without_security_configuration_and_never_prints_secrets(tmp_path) -> None:
    base = {k: v for k, v in os.environ.items() if not k.startswith("PULSEOPS_")}
    base["PYTHONPATH"] = str(REPO)
    base["PULSEOPS_DATABASE_URL"] = "sqlite:" + (tmp_path / "startup.db").as_posix()  # never touch a developer database
    probe = [sys.executable, "-c", "import app.main"]
    failed = subprocess.run(probe, env={**base, "PULSEOPS_ENVIRONMENT": "production"}, capture_output=True, text=True, timeout=120, cwd=REPO)
    assert failed.returncode != 0 and "ConfigurationError" in failed.stderr and "refusing to start" in failed.stderr
    dev_in_prod = subprocess.run(probe, env={**base, "PULSEOPS_ENVIRONMENT": "production", "PULSEOPS_AUTH_MODE": "dev"},
                                 capture_output=True, text=True, timeout=120, cwd=REPO)
    assert dev_in_prod.returncode != 0 and "only allowed when PULSEOPS_ENVIRONMENT=development" in dev_in_prod.stderr
    creds = json.dumps(_credentials())
    ok = subprocess.run(
        [sys.executable, "-c", "import app.main as m; print(m.app.docs_url, m.app.openapi_url)"],
        env={**base, "PULSEOPS_ENVIRONMENT": "production", "PULSEOPS_API_CREDENTIALS": creds},
        capture_output=True, text=True, timeout=120, cwd=REPO,
    )
    assert ok.returncode == 0, ok.stderr
    assert ok.stdout.strip() == "None None"  # interactive API docs are development-only
    for output in (failed.stderr, dev_in_prod.stderr, ok.stderr, ok.stdout):
        assert not any(t in output for t in TOKENS.values()) and "token_sha256" not in output


def test_unhandled_errors_return_a_generic_body_with_a_request_id_and_no_internals() -> None:
    @app.get("/__boom")
    async def boom() -> None:
        raise RuntimeError("secret-internal-detail /etc/passwd sk-ant-LEAK")

    try:
        response = TestClient(app, raise_server_exceptions=False).get("/__boom", headers=ADMIN)
    finally:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", "") != "/__boom"]
    assert response.status_code == 500
    assert response.json()["detail"] == "Internal server error" and response.json()["request_id"]
    assert response.headers[REQUEST_ID_HEADER] == response.json()["request_id"]
    assert "secret-internal-detail" not in response.text and "sk-ant-LEAK" not in response.text


def test_error_responses_never_contain_credentials(apikey_mode) -> None:
    client = TestClient(app)
    texts = [
        client.get("/incidents", headers=bearer("bob")).text,
        client.post("/incidents", headers=bearer("bob"), json={}).text,
        client.get("/incidents", headers={"Authorization": "Bearer " + TOKENS["alice"][:-1] + "!"}).text,
        client.get("/workflow/WF-NOPE", headers=bearer("alice")).text,
    ]
    for text in texts:
        assert not any(t in text for t in TOKENS.values())


def test_logs_never_contain_tokens_or_authorization_headers(apikey_mode) -> None:
    lines: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(self.format(record))

    handler = Capture()
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("pulseops")
    logger.addHandler(handler)
    try:
        client = TestClient(app)
        client.get("/incidents", headers=bearer("alice"))
        client.get("/incidents", headers={"Authorization": "Bearer " + TOKENS["alice"] + "x"})
        logging.getLogger("pulseops.test").info("auth header was Authorization: Bearer %s and key sk-ant-ABCDEF123", TOKENS["alice"])
    finally:
        logger.removeHandler(handler)
    blob = "\n".join(lines)
    assert lines and "alice" in blob  # principal ids are logged...
    assert not any(t in blob for t in TOKENS.values()) and "sk-ant-ABCDEF123" not in blob  # ...secrets are not
    assert "[REDACTED]" in blob
    assert redact("Authorization: Bearer abc.def-123") .count("abc.def-123") == 0
    assert redact('{"password": "hunter2", "api_key": "abc123"}') == '{"password": "[REDACTED]", "api_key": "[REDACTED]"}'


# =========================================================================== request IDs / structured logging


def test_request_id_is_generated_supplied_and_sanitised() -> None:
    client = TestClient(app)
    generated = client.get("/health").headers[REQUEST_ID_HEADER]
    assert re.fullmatch(r"[0-9a-f]{32}", generated)
    assert client.get("/health", headers={REQUEST_ID_HEADER: "client-req-12345"}).headers[REQUEST_ID_HEADER] == "client-req-12345"
    for bad in ("short", "x" * 65, "has space in it!", "semi;colon;12345", "<script>alert(1)</script>", "../../etc/passwd"):
        echoed = client.get("/health", headers={REQUEST_ID_HEADER: bad}).headers[REQUEST_ID_HEADER]
        assert echoed != bad and re.fullmatch(r"[0-9a-f]{32}", echoed), bad
    assert sanitize_request_id(None) != sanitize_request_id(None)
    for response in (client.get("/incidents"), client.get("/nope")):  # errors carry the header too
        assert REQUEST_ID_HEADER in response.headers


def test_request_id_correlates_logs_and_audit_events(env) -> None:
    client, *_ = env
    lines: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(self.format(record))

    handler = Capture()
    handler.setFormatter(JsonFormatter())
    logging.getLogger("pulseops").addHandler(handler)
    try:
        response = client.post("/workflow/events", headers={**N8N, REQUEST_ID_HEADER: "corr-request-0001"}, json=_event(severity="low"))
    finally:
        logging.getLogger("pulseops").removeHandler(handler)
    body = response.json()
    assert response.headers[REQUEST_ID_HEADER] == "corr-request-0001"
    audit = body["audit_events"]
    assert audit and all(e["metadata"]["request_id"] == "corr-request-0001" for e in audit)
    assert {e["actor_type"] for e in audit if e["actor"] == "svc-n8n"} == {"service"}
    records = [json.loads(line) for line in lines]
    processed = next(r for r in records if r.get("operation") == "event_ingest")
    assert processed["request_id"] == "corr-request-0001" and processed["principal_id"] == "svc-n8n"
    assert processed["event_id"] and processed["incident_id"] == body["incident_id"] and processed["workflow_id"] == body["workflow_id"]
    assert processed["level"] == "INFO" and "timestamp" in processed and processed["outcome"] == "completed"
    http = next(r for r in records if r.get("operation") == "http_request")
    assert http["request_id"] == "corr-request-0001" and http["status_code"] == 200 and http["method"] == "POST"


# =========================================================================== AI token / cost recording


def test_token_and_cost_metadata_is_recorded_when_the_sdk_provides_it() -> None:
    import dataclasses

    from claude_agent_sdk import ResultMessage
    from tests.test_phase6 import final, run_agent, standard_stream, grounded_payload

    stream = standard_stream(grounded_payload())
    stream[-1] = dataclasses.replace(
        stream[-1], total_cost_usd=0.0123, duration_api_ms=456,
        usage={"input_tokens": 10, "output_tokens": 5, "nested": {"x": 1}, "flag": True},
    )
    assert isinstance(stream[-1], ResultMessage)
    _, agent, _ = run_agent(stream)
    telemetry = agent.last_telemetry
    assert telemetry.total_cost_usd == 0.0123 and telemetry.api_duration_ms == 456
    assert telemetry.usage == {"input_tokens": 10, "output_tokens": 5}  # numeric entries only
    assert telemetry.duration_ms is not None


def test_missing_cost_metadata_never_breaks_an_investigation() -> None:
    from tests.test_phase6 import grounded_payload, run_agent, standard_stream

    result, agent, _ = run_agent(standard_stream(grounded_payload()))
    assert result.evidence and agent.last_telemetry.success is True
    assert agent.last_telemetry.total_cost_usd is None and agent.last_telemetry.usage is None


def test_ai_execution_metadata_is_audited_with_the_investigation(env, monkeypatch) -> None:
    client, *_ = env

    async def investigate(incident_id, objective):
        result = InvestigationResult(incident_id=incident_id, summary="s", evidence=["e"], confidence=0.5)
        return InvestigationOutcome(result=result, grounded=True,
                                    ai_execution={"model": "m", "duration_ms": 12, "total_cost_usd": 0.5, "usage": {"input_tokens": 3}})

    monkeypatch.setattr("app.services.event_service.build_investigator", lambda url: investigate)
    body = client.post("/workflow/events", headers=N8N, json=_event(severity="low")).json()
    done = next(e for e in body["audit_events"] if e["event_type"] == "INVESTIGATION_COMPLETED")
    assert done["metadata"]["ai_execution"] == {"model": "m", "duration_ms": 12, "total_cost_usd": 0.5, "usage": {"input_tokens": 3}}
    assert "token" not in json.dumps(done["metadata"]["ai_execution"]).replace("input_tokens", "")


# =========================================================================== n8n workflow / platform files


def _workflow_json() -> dict:
    return json.loads((REPO / "n8n" / "pulseops-event-workflow.json").read_text(encoding="utf-8"))


def test_n8n_workflow_contains_no_secrets_and_uses_credential_references() -> None:
    raw = (REPO / "n8n" / "pulseops-event-workflow.json").read_text(encoding="utf-8")
    assert "Bearer " not in raw and "sk-ant" not in raw and not re.search(r"[A-Fa-f0-9]{40,}", raw)
    nodes = {n["name"]: n for n in _workflow_json()["nodes"]}
    webhook, call = nodes["Webhook"], nodes["PulseOps Workflow API"]
    assert webhook["parameters"]["authentication"] == "headerAuth"
    assert webhook["credentials"]["httpHeaderAuth"]["id"] == "pulseopsWebhookAuth"
    assert call["parameters"]["authentication"] == "genericCredentialType"
    assert call["parameters"]["genericAuthType"] == "httpHeaderAuth"
    assert call["credentials"]["httpHeaderAuth"]["id"] == "pulseopsServiceAuth"
    for node in (webhook, call):
        assert set(node["credentials"]["httpHeaderAuth"]) == {"id", "name"}  # a reference, never a value


def test_n8n_workflow_keeps_timeout_no_retries_and_no_forbidden_nodes() -> None:
    nodes = {n["name"]: n for n in _workflow_json()["nodes"]}
    call = nodes["PulseOps Workflow API"]
    assert call["parameters"]["options"]["timeout"] == 120000
    assert call.get("retryOnFail", False) is False and "maxTries" not in call and "waitBetweenTries" not in call
    assert call["parameters"]["url"] == "http://pulseops:8000/workflow/events"
    assert "host.docker.internal" not in json.dumps(_workflow_json())
    allowed = {"n8n-nodes-base.webhook", "n8n-nodes-base.code", "n8n-nodes-base.if", "n8n-nodes-base.httpRequest",
               "n8n-nodes-base.switch", "n8n-nodes-base.respondToWebhook"}
    assert {n["type"] for n in _workflow_json()["nodes"]} <= allowed  # no AI agent / langchain / database nodes
    code = "\n".join(n["parameters"].get("jsCode", "") for n in _workflow_json()["nodes"])
    assert "pulseops_unauthorized" in code and "pulseops_forbidden" in code  # credential problems fail closed
    assert "approve" not in json.dumps(call).lower()  # n8n never calls an approval endpoint


def test_n8n_credential_template_has_placeholders_only() -> None:
    template = (REPO / "n8n" / "credentials.template.json").read_text(encoding="utf-8")
    assert "${PULSEOPS_N8N_TOKEN}" in template and "${N8N_WEBHOOK_SECRET}" in template
    assert not re.search(r"[A-Za-z0-9]{32,}", template.replace("${PULSEOPS_N8N_TOKEN}", "").replace("${N8N_WEBHOOK_SECRET}", ""))


def test_images_are_pinned_and_compose_has_no_literal_secrets() -> None:
    compose = (REPO / "docker-compose.yml").read_text(encoding="utf-8")
    legacy = (REPO / "docker-compose.n8n.yml").read_text(encoding="utf-8")
    for text in (compose, legacy):
        assert "n8nio/n8n:2.41.6" in text and "n8nio/n8n:latest" not in text and ":latest" not in text
    neo4j = (REPO / "docker-compose.neo4j.yml").read_text(encoding="utf-8")
    assert "neo4j/password" not in compose + neo4j + legacy and "neo4j/${NEO4J_PASSWORD:?" in neo4j
    assert "N8N_ENCRYPTION_KEY: ${N8N_ENCRYPTION_KEY:?" in compose
    assert "/data" in compose and "healthcheck" in compose and "pulseops-net" in compose
    assert "PULSEOPS_API_CREDENTIALS: ${PULSEOPS_API_CREDENTIALS:?" in compose
    assert "password" not in re.sub(r"\$\{[^}]*\}", "", compose).lower().replace("neo4j_password", "")  # no literal passwords


def test_dockerfile_is_non_root_pinned_and_healthchecked() -> None:
    dockerfile = (REPO / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^FROM python:3\.11\.\d+-slim", dockerfile, re.M) and ":latest" not in dockerfile
    assert re.search(r"^USER (?!root)\S+", dockerfile, re.M)
    assert "HEALTHCHECK" in dockerfile and "PYTHONUNBUFFERED=1" in dockerfile and "VOLUME" in dockerfile
    assert not re.search(r"^\s*(ENV|ARG)\s+(ANTHROPIC_API_KEY|PULSEOPS_API_CREDENTIALS|N8N_)", dockerfile, re.M)  # nothing baked in
    ignore = (REPO / ".dockerignore").read_text(encoding="utf-8")
    for pattern in (".env", ".venv", "*.db", ".git"):
        assert pattern in ignore


def test_env_example_has_placeholders_only() -> None:
    text = (REPO / ".env.example").read_text(encoding="utf-8")
    for name in ("PULSEOPS_ENVIRONMENT", "PULSEOPS_AUTH_MODE", "PULSEOPS_API_CREDENTIALS", "ANTHROPIC_API_KEY",
                 "N8N_ENCRYPTION_KEY", "NEO4J_PASSWORD", "PULSEOPS_DATABASE_URL", "PULSEOPS_N8N_TOKEN", "N8N_WEBHOOK_SECRET"):
        assert name in text, name
    assert "sk-ant-api" not in text and not re.search(r"[0-9a-f]{64}", text)


# =========================================================================== seed data boundary


def test_demo_seed_is_development_only(tmp_path, monkeypatch) -> None:
    def services(name: str) -> int:
        manager = DatabaseManager("sqlite:" + (tmp_path / name).as_posix())
        with manager.get_connection() as c:
            return c.execute("SELECT COUNT(*) FROM services").fetchone()[0]

    monkeypatch.delenv("PULSEOPS_SEED_DEMO_DATA", raising=False)  # the suite forces it on; exercise the defaults
    assert services("dev.db") == 1  # development seeds the synthetic svc-payment
    monkeypatch.setenv("PULSEOPS_ENVIRONMENT", "production")
    assert services("prod.db") == 0  # never silently recreated
    with DatabaseManager("sqlite:" + (tmp_path / "prod.db").as_posix()).get_connection() as c:
        assert c.execute("SELECT COUNT(*) FROM incidents").fetchone()[0] == 0
    monkeypatch.setenv("PULSEOPS_SEED_DEMO_DATA", "true")  # an explicit opt-in is honoured
    assert services("opt-in.db") == 1
    monkeypatch.setenv("PULSEOPS_ENVIRONMENT", "development")
    monkeypatch.setenv("PULSEOPS_SEED_DEMO_DATA", "false")
    assert services("dev-off.db") == 0  # and so is an explicit opt-out in development


def test_related_incidents_has_no_hard_coded_default_incident(tmp_path) -> None:
    import sqlite3

    from app.retrieval.service import IncidentRetrievalService

    url = "sqlite:" + (tmp_path / "related.db").as_posix()
    DatabaseManager(url)
    with sqlite3.connect(tmp_path / "related.db") as db:
        for iid in ("INC-2001", "INC-1007x"):
            db.execute(
                "INSERT INTO incidents (tenant_id, incident_id, service_id, severity, status, title, description, environment,"
                " started_at, resolved_at, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (DEV_TENANT, iid, "svc-payment", "low", "open", iid, iid, "p", "2026-01-01T00:00:00+00:00", None, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
            )
    from app.repositories.incident_repository import IncidentRepository

    service = IncidentRetrievalService(database_url=url, tenant_id=DEV_TENANT)
    natural = [i.incident_id for i in IncidentRepository(url, DEV_TENANT).list_incidents() if i.service_id == "svc-payment"]
    assert set(natural) >= {"INC-1007", "INC-2001", "INC-1007x"}
    assert service.get_related_incidents("svc-payment") == natural  # no implicit hoisting of any incident
    for chosen in ("INC-2001", "INC-1007x", "INC-1007"):  # hoisted only when it is the incident being asked about
        related = service.get_related_incidents("svc-payment", incident_id=chosen)
        assert related[0] == chosen and sorted(related) == sorted(natural)


# =========================================================================== stuck event-claim recovery


def _claim_service(env):
    client, stub, incidents, workflows = env
    return workflow_api.event_service_for(DEV_TENANT), incidents, workflows


def _age_claim(service, event_id: str, seconds: int) -> None:
    from datetime import datetime, timedelta, timezone

    old = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
    with service.events.get_connection() as c:
        c.execute("UPDATE operational_events SET created_at = ? WHERE event_id = ?", (old, event_id))


def test_normal_claims_succeed_and_duplicates_stay_protected(env) -> None:
    client, stub, incidents, _ = env
    event = _event(severity="low")
    before = len(incidents.list_incidents())
    first = client.post("/workflow/events", headers=N8N, json=event).json()
    second = client.post("/workflow/events", headers=N8N, json=event).json()
    assert second["idempotent_replay"] is True and second["workflow_id"] == first["workflow_id"]
    assert len(incidents.list_incidents()) == before + 1 and len(stub.calls) == 1


def test_repository_reclaim_is_atomic_and_never_touches_a_live_claim(env) -> None:
    service, _, _ = _claim_service(env)
    repo = service.events
    assert repo.claim_event("evt-claim-1", "hash") is True
    assert repo.claim_event("evt-claim-1", "hash") is False  # duplicate protected
    assert repo.reclaim_stale("evt-claim-1", ttl_seconds=900) is False  # fresh claim is live
    _age_claim(service, "evt-claim-1", 3600)
    assert repo.reclaim_stale("evt-claim-1", ttl_seconds=900) is True  # stale: exactly one winner
    assert repo.reclaim_stale("evt-claim-1", ttl_seconds=900) is False  # the refreshed claim is live again
    repo.complete_event("evt-claim-1", "WF-X")
    _age_claim(service, "evt-claim-1", 3600)
    assert repo.reclaim_stale("evt-claim-1", ttl_seconds=900) is False  # a completed event is never reclaimed


def test_active_claim_is_not_reclaimed_by_a_duplicate_delivery(env, monkeypatch) -> None:
    client, stub, incidents, _ = env
    service, _, _ = _claim_service(env)
    monkeypatch.setattr("app.services.event_service._REPLAY_WAIT_SECONDS", 0.6)
    event = _event(severity="low")
    from app.models.schemas import OperationalEvent

    parsed = OperationalEvent.model_validate(event)
    assert service.events.claim_event(parsed.event_id, service._request_hash(parsed, "notify")) is True  # a live, in-progress claim
    response = client.post("/workflow/events", headers=N8N, json=event)
    assert response.status_code == 409 and "still being processed" in response.json()["detail"]
    assert stub.calls == []  # not reprocessed
    row = service.events.get_event(parsed.event_id)
    assert row["state"] == "processing"


def test_stale_claim_is_recovered_without_duplicating_the_incident(env) -> None:
    client, stub, incidents, workflows = env
    service, _, _ = _claim_service(env)
    from app.models.schemas import OperationalEvent

    event = _event(severity="low")
    parsed = OperationalEvent.model_validate(event)
    service.events.claim_event(parsed.event_id, service._request_hash(parsed, "notify"))
    crashed = incidents.create_incident(  # the dead process got as far as creating the incident
        service_id="svc-payment", severity="low", title="t", description="d", environment="p")
    service.events.set_incident(parsed.event_id, crashed.incident_id)
    _age_claim(service, parsed.event_id, 3600)
    before = len(incidents.list_incidents())

    response = client.post("/workflow/events", headers=N8N, json=event)
    assert response.status_code == 200
    body = response.json()
    assert body["incident_id"] == crashed.incident_id and len(incidents.list_incidents()) == before  # no second incident
    assert body["investigation_status"] == "completed"
    recovered = next(e for e in body["audit_events"] if e["event_type"] == "EVENT_CLAIM_RECOVERED")
    assert recovered["metadata"]["stale_claim_age_seconds"] >= 3600 and recovered["actor"] == "svc-n8n"
    assert service.events.get_event(parsed.event_id)["state"] == "completed"
    again = client.post("/workflow/events", headers=N8N, json=event).json()
    assert again["idempotent_replay"] is True and again["workflow_id"] == body["workflow_id"]  # protection resumes


def test_stale_claim_with_an_orphaned_investigation_hold_is_closed_fail_closed(env) -> None:
    client, stub, incidents, workflows = env
    service, _, _ = _claim_service(env)
    from app.models.schemas import OperationalEvent

    event = _event(severity="low")
    parsed = OperationalEvent.model_validate(event)
    service.events.claim_event(parsed.event_id, service._request_hash(parsed, "notify"))
    incident = incidents.create_incident(service_id="svc-payment", severity="low", title="t", description="d", environment="p")
    service.events.set_incident(parsed.event_id, incident.incident_id)

    def die() -> dict:
        raise KeyboardInterrupt  # simulates the process dying mid-investigation: not caught by `except Exception`

    with pytest.raises(KeyboardInterrupt):
        workflows.evaluate_incident_action(incident.incident_id, "notify", "svc-n8n", idempotency_key=f"event:{parsed.event_id}",
                                           investigate=die, actor_type="service")
    held = workflows.get_latest_workflow_for_incident(incident.incident_id)
    assert held["policy_decision"] == "investigation_pending" and held["status"] == "rejected"
    _age_claim(service, parsed.event_id, 3600)

    body = client.post("/workflow/events", headers=N8N, json=event).json()
    assert body["workflow_id"] == held["workflow_id"] and stub.calls == []  # not silently re-run
    assert body["investigation_status"] == "failed" and body["failure_reason"] == "investigation_abandoned"
    assert body["policy_decision"] == "investigation_failed" and body["status"] == "rejected"
    types = [e["event_type"] for e in body["audit_events"]]
    assert "INVESTIGATION_FAILED" in types and "EVENT_CLAIM_RECOVERED" in types
    assert _decide(client, REVIEWER, body, action="notify").status_code == 409  # still cannot be approved


def test_a_conflicting_event_cannot_reclaim_a_stale_claim(env) -> None:
    client, *_ = env
    service, _, _ = _claim_service(env)
    from app.models.schemas import OperationalEvent

    event = _event(severity="low")
    parsed = OperationalEvent.model_validate(event)
    service.events.claim_event(parsed.event_id, service._request_hash(parsed, "notify"))
    _age_claim(service, parsed.event_id, 3600)
    assert client.post("/workflow/events", headers=N8N, json={**event, "message": "different content"}).status_code == 409
