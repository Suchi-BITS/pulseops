"""P11 reliability tests: MCP failure, database failure and recovery, restart recovery, concurrent HITL and requests.

Existing mechanisms are reused (scripted SDK stream, Gate 9.1 two-tenant fixture, the real event service). Temporary
databases only. No model call.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.test_phase6 import (
    CONTEXT,
    RELATED,
    REPOSITORY,
    final,
    grounded_payload,
    init_message,
    real_tool_text,
    run_agent,
    tool_result,
    tool_use,
)
from tests.test_phase7_gate6 import _event
from tests.test_phase7_gate9_1 import A, B, TOKENS, _approve, _hitl_in, _ingest, bearer, tenants  # noqa: F401 (fixture)
from tests.test_phase9 import ERROR_KEYS, _scripted
from tests.test_phase11_security import assert_controlled_error

pytestmark = pytest.mark.reliability
ROOT = Path(__file__).resolve().parents[1]


# ============================================================================================ MCP failure mid-investigation

FABRICATED = "FABRICATED-FROM-FAILED-TOOL-31337"


def _failed_tool_result(tool_id: str, message: str):
    return tool_result(tool_id, [{"type": "text", "text": message}], is_error=True)


def test_a_later_mcp_tool_failure_does_not_become_evidence_or_hide_the_failure() -> None:
    """Context retrieval succeeds, then another MCP tool fails, and the model still 'reports' a fabricated finding."""
    context = real_tool_text("get_incident_context", {"incident_id": "INC-1007"})
    payload = grounded_payload(
        evidence=["Log: 'Database connection pool exhausted' (log-10001).", f"{FABRICATED}: related incident INC-9999 is the cause"],
        hypotheses=[f"{FABRICATED} may explain it"],
    )
    stream = [
        init_message(),
        tool_use(CONTEXT, "t1", incident_id="INC-1007"), tool_result("t1", context),
        tool_use(RELATED, "t2", service_id="svc-payment"),
        _failed_tool_result("t2", "MCP error -32000: related-incidents backend crashed"),
        *final(payload),
    ]
    result, agent, _ = run_agent(stream)
    telemetry = agent.last_telemetry

    # the failure is recorded, attributed to the failing tool, and visible to the human reader
    assert any(RELATED in failure or "related" in failure.lower() for failure in telemetry.tool_failures), telemetry.tool_failures
    assert any("crashed" in failure for failure in telemetry.tool_failures)
    # nothing the failed tool "returned" or the model invented from it is evidence
    assert not any(FABRICATED in item for item in result.evidence)
    assert not any("backend crashed" in item for item in result.evidence)
    assert not any("INC-9999" in item for item in result.evidence)
    # the grounded context retrieval is still the (only) basis of the result
    assert result.evidence and telemetry.grounded is True
    assert set(result.tool_calls) <= {CONTEXT, RELATED}
    assert telemetry.unauthorized_tool_attempts == []
    # and the gap is reported as missing information, not papered over
    assert any("related" in item.lower() or "unavailable" in item.lower() or "failed" in item.lower() or "tool" in item.lower()
               for item in result.missing_information), result.missing_information


def test_when_every_tool_fails_the_result_is_empty_and_zero_confidence() -> None:
    stream = [
        init_message(),
        tool_use(CONTEXT, "t1", incident_id="INC-1007"), _failed_tool_result("t1", "MCP error -32000: database unavailable"),
        tool_use(RELATED, "t2", service_id="svc-payment"), _failed_tool_result("t2", "MCP error -32000: database unavailable"),
        tool_use(REPOSITORY, "t3", service_id="svc-payment"), _failed_tool_result("t3", "MCP error -32000: database unavailable"),
        *final(grounded_payload(evidence=[FABRICATED], confidence=0.95)),
    ]
    result, agent, _ = run_agent(stream)
    assert result.evidence == [] and result.hypotheses == [] and result.confidence == 0.0
    assert FABRICATED not in json.dumps(result.model_dump())
    assert agent.last_telemetry.grounded is False and len(agent.last_telemetry.tool_failures) >= 1


def test_a_failed_follow_up_tool_after_a_successful_one_keeps_only_the_successful_evidence() -> None:
    context = real_tool_text("get_incident_context", {"incident_id": "INC-1007"})
    stream = [
        init_message(),
        tool_use(CONTEXT, "t1", incident_id="INC-1007"), tool_result("t1", context),
        tool_use(REPOSITORY, "t2", service_id="svc-payment"), _failed_tool_result("t2", "MCP error -32001: Request timed out"),
        *final(grounded_payload()),
    ]
    with_failure, agent, _ = run_agent(stream)
    clean, _, _ = run_agent([init_message(), tool_use(CONTEXT, "t1", incident_id="INC-1007"), tool_result("t1", context), *final(grounded_payload())])
    assert with_failure.evidence == clean.evidence  # the failure neither added nor removed grounded evidence
    assert any("timed out" in f for f in agent.last_telemetry.tool_failures)


# ============================================================================================ database failure and recovery

def _production(monkeypatch) -> None:
    monkeypatch.setenv("PULSEOPS_ENVIRONMENT", "production")  # bearer auth is already active
    monkeypatch.setenv("PULSEOPS_SEED_DEMO_DATA", "false")  # as in a real deployment: connecting never writes demo data


def _quiet_client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def test_locked_database_gives_controlled_errors_and_recovers(tenants, monkeypatch) -> None:
    _, url, _ = tenants
    _production(monkeypatch)
    path = url.removeprefix("sqlite:")
    client = _quiet_client()
    assert client.get("/incidents", headers=bearer("op-a")).status_code == 200
    blocker = sqlite3.connect(path, timeout=0, isolation_level=None)
    blocker.execute("BEGIN EXCLUSIVE")  # an exclusive lock held by someone else
    try:
        failing = client.get("/incidents", headers=bearer("op-a"))
        assert failing.status_code in (500, 503), failing.status_code
        body = assert_controlled_error(failing, allowed=(500, 503))
        assert body["code"] in ("internal_error", "service_unavailable") and "locked" not in failing.text.lower()
        not_ready = client.get("/health/ready")
        assert not_ready.status_code == 503 and not_ready.json()["checks"] == {"database": "error"}
        assert "locked" not in not_ready.text.lower() and path not in not_ready.text
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()
    assert client.get("/incidents", headers=bearer("op-a")).status_code == 200  # recovered, no restart needed
    assert client.get("/health/ready").status_code == 200


def test_read_only_database_still_reads_refuses_writes_cleanly_and_reports_not_ready(tenants, monkeypatch) -> None:
    client0, url, _ = tenants
    _production(monkeypatch)
    path = Path(url.removeprefix("sqlite:"))
    before = client0.get("/incidents", headers=bearer("op-a")).headers["X-Total-Count"]
    os.chmod(path, stat.S_IREAD)
    client = _quiet_client()
    try:
        assert client.get("/incidents", headers=bearer("op-a")).status_code == 200  # reads keep working
        write = client.post("/incidents", headers=bearer("op-a"), json={
            "service_id": "svc-payment", "severity": "high", "title": "t", "description": "d", "environment": "p"})
        assert write.status_code in (500, 503)
        assert_controlled_error(write, allowed=(500, 503))
        assert "readonly" not in write.text.lower() and "read-only" not in write.text.lower() and str(path) not in write.text
        not_ready = client.get("/health/ready")
        assert not_ready.status_code == 503 and not_ready.json()["code"] == "not_ready"
    finally:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    assert client.get("/incidents", headers=bearer("op-a")).headers["X-Total-Count"] == before  # the failed write stored nothing
    assert client.get("/health/ready").status_code == 200


def test_missing_database_is_initialised_empty_and_authorises_nobody(tenants, tmp_path, monkeypatch) -> None:
    _production(monkeypatch)
    fresh = tmp_path / "does-not-exist-yet" / "fresh.db"
    monkeypatch.setenv("PULSEOPS_DATABASE_URL", "sqlite:" + fresh.as_posix())
    client = _quiet_client()
    assert client.get("/health/ready").json() == {"status": "ready", "checks": {"database": "ok"}}  # a new empty database is created
    assert fresh.exists()
    denied = client.get("/incidents", headers=bearer("op-a"))  # the valid credential has no tenant or membership in it
    assert_controlled_error(denied, allowed=(403,))
    assert denied.json()["detail"] == "No active tenant membership for this credential"


def test_unusable_database_location_is_a_controlled_failure_without_path_leakage(tenants, tmp_path, monkeypatch) -> None:
    _production(monkeypatch)
    blocker = tmp_path / "a-file-not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("PULSEOPS_DATABASE_URL", "sqlite:" + (blocker / "db.sqlite").as_posix())
    client = _quiet_client()
    not_ready = client.get("/health/ready")
    assert not_ready.status_code == 503 and not_ready.json()["checks"] == {"database": "error"}
    failing = client.get("/incidents", headers=bearer("op-a"))
    assert failing.status_code == 500 and ERROR_KEYS <= set(failing.json())
    for text in (not_ready.text, failing.text):
        assert str(tmp_path) not in text and "a-file-not-a-directory" not in text and "Traceback" not in text


def test_corrupted_database_is_a_controlled_failure_and_recovers_when_restored(tenants, tmp_path, monkeypatch) -> None:
    _, url, _ = tenants
    _production(monkeypatch)
    path = Path(url.removeprefix("sqlite:"))
    good = tmp_path / "good-copy.db"
    shutil.copy2(path, good)
    path.write_bytes(b"this is not a sqlite database " * 200)
    client = _quiet_client()
    try:
        not_ready = client.get("/health/ready")
        assert not_ready.status_code == 503 and not_ready.json()["checks"] == {"database": "error"}
        failing = client.get("/incidents", headers=bearer("op-a"))
        assert failing.status_code == 500 and failing.json()["code"] == "internal_error"
        for text in (not_ready.text, failing.text):
            assert "not a database" not in text.lower() and str(path) not in text and "sqlite" not in text.lower()
    finally:
        shutil.copy2(good, path)
    assert client.get("/health/ready").status_code == 200
    assert client.get("/incidents", headers=bearer("op-a")).status_code == 200


# ============================================================================================ restart recovery

def _wait_ready(base: str, process: subprocess.Popen, seconds: float = 90.0) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"fixture server exited early with {process.returncode}")
        try:
            if httpx.get(base + "/health/ready", timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.4)
    raise AssertionError("fixture server did not become ready")


def _free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_fixture(tmp_path: Path, port: int, *, fresh: bool) -> subprocess.Popen:
    log = open(tmp_path / f"server-{port}.log", "wb")
    args = [sys.executable, str(ROOT / "e2e" / "fixture_server.py"), "--port", str(port), "--db", str(tmp_path / "restart.db"),
            "--runtime-dir", str(tmp_path)]
    if fresh:
        args.append("--fresh")
    return subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)


def test_workflow_and_investigation_survive_a_server_restart(tmp_path) -> None:
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    first = _start_fixture(tmp_path, port, fresh=True)
    try:
        _wait_ready(base, first)
        tokens = json.loads((tmp_path / "tokens.json").read_text("utf-8"))
        reviewer = {"Authorization": f"Bearer {tokens['rita']}"}
        queue = httpx.get(base + "/workflow?status=pending&requires_approval=true&sort=created_at&order=asc", headers=reviewer, timeout=30).json()
        pending = queue["items"][0]
        approve = httpx.post(f"{base}/workflow/{queue['items'][1]['workflow_id']}/decision", headers=reviewer, timeout=30, json={
            "decision": "approve", "incident_id": queue["items"][1]["incident_id"], "action": "restart_service",
            "timestamp": "2026-01-01T00:00:00Z", "rationale": "before restart"})
        assert approve.status_code == 200
        detail_before = httpx.get(f"{base}/incidents/{pending['incident_id']}/detail", headers=reviewer, timeout=30).json()
        assert detail_before["investigation_status"] == "completed" and detail_before["hitl"]["state"] == "awaiting_decision"
    finally:
        first.kill()
        first.wait(timeout=20)

    port2 = _free_port()
    base2 = f"http://127.0.0.1:{port2}"
    second = _start_fixture(tmp_path, port2, fresh=False)  # same database, same credentials, new process
    try:
        _wait_ready(base2, second)
        reviewer = {"Authorization": f"Bearer {tokens['rita']}"}
        detail_after = httpx.get(f"{base2}/incidents/{pending['incident_id']}/detail", headers=reviewer, timeout=30).json()
        assert detail_after["investigation"] == detail_before["investigation"]  # the stored investigation survived byte for byte
        assert detail_after["workflow"]["workflow_id"] == detail_before["workflow"]["workflow_id"]
        assert detail_after["hitl"]["state"] == "awaiting_decision" and detail_after["hitl"]["can_decide"] is True
        decided = httpx.get(f"{base2}/incidents/{queue['items'][1]['incident_id']}/detail", headers=reviewer, timeout=30).json()
        assert decided["hitl"]["state"] == "approved" and decided["hitl"]["reviewer"] == "rita"  # a decision survived too
        count = httpx.get(base2 + "/incidents?limit=1", headers=reviewer, timeout=30).headers["X-Total-Count"]
        assert count == "4"  # restart did not re-seed or duplicate anything
        # and the restarted server still enforces the same boundaries
        operator = {"Authorization": f"Bearer {tokens['omar']}"}
        forged = httpx.post(f"{base2}/workflow/{pending['workflow_id']}/decision", headers=operator, timeout=30, json={
            "decision": "approve", "incident_id": pending["incident_id"], "action": "restart_service", "timestamp": "2026-01-01T00:00:00Z"})
        assert forged.status_code == 403
        globex = {"Authorization": f"Bearer {tokens['gina']}"}
        assert httpx.get(f"{base2}/workflow/{pending['workflow_id']}", headers=globex, timeout=30).status_code == 404 or \
            httpx.get(f"{base2}/workflow/{pending['workflow_id']}", headers=globex, timeout=30).json().get("incident_id") is None
    finally:
        second.kill()
        second.wait(timeout=20)


# ============================================================================================ concurrency

def _add_second_reviewer(url: str, monkeypatch) -> None:
    from app.core.security import hash_token
    from tests.helpers import provision_members

    provision_members(url, A, {"rev-a2": ("human", "reviewer", ("sre", "incident_manager"))})
    TOKENS["rev-a2"] = "rev-a2-token-0123456789abcdefABCDEF"
    credentials = json.loads(os.environ["PULSEOPS_API_CREDENTIALS"])
    credentials.append({"principal_id": "rev-a2", "tenant_id": A, "token_sha256": hash_token(TOKENS["rev-a2"])})
    monkeypatch.setenv("PULSEOPS_API_CREDENTIALS", json.dumps(credentials))


def _decide(workflow: dict, who: str, decision: str, barrier: threading.Barrier):
    client = TestClient(app, raise_server_exceptions=False)
    barrier.wait()
    return client.post(f"/workflow/{workflow['workflow_id']}/decision", headers=bearer(who), json={
        "decision": decision, "incident_id": workflow["incident_id"], "action": "restart_service",
        "timestamp": "2026-01-01T00:00:00Z"})


def test_two_reviewers_deciding_the_same_workflow_concurrently_exactly_one_wins(tenants, monkeypatch) -> None:
    client, url, _ = tenants
    _scripted(monkeypatch)
    _add_second_reviewer(url, monkeypatch)
    for trial in range(12):
        workflow = _hitl_in(client, "n8n-a")
        barrier = threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(_decide, workflow, "u1-a", "approve", barrier)
            second = pool.submit(_decide, workflow, "rev-a2", "reject", barrier)
            responses = [first.result(), second.result()]
        codes = sorted(r.status_code for r in responses)
        assert codes == [200, 409], (trial, codes, [r.text[:160] for r in responses])
        loser = next(r for r in responses if r.status_code == 409)
        assert_controlled_error(loser, allowed=(409,))
        winner_decision = "approve" if responses[0].status_code == 200 else "reject"
        with sqlite3.connect(url.removeprefix("sqlite:")) as c:
            rows = c.execute("SELECT decision, actor_id FROM workflow_decisions WHERE tenant_id = ? AND workflow_id = ?",
                             (A, workflow["workflow_id"])).fetchall()
        assert len(rows) == 1 and rows[0][0] == winner_decision, (trial, rows)  # exactly one decision was recorded
        final_state = client.get(f"/workflow/{workflow['workflow_id']}", headers=bearer("op-a")).json()
        assert final_state["status"] == ("approved" if winner_decision == "approve" else "rejected")


def test_the_same_reviewer_repeating_a_decision_concurrently_is_idempotent(tenants, monkeypatch) -> None:
    client, url, _ = tenants
    _scripted(monkeypatch)
    workflow = _hitl_in(client, "n8n-a")
    barrier = threading.Barrier(4)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = [f.result() for f in [pool.submit(_decide, workflow, "u1-a", "approve", barrier) for _ in range(4)]]
    assert all(r.status_code in (200, 409) for r in responses) and any(r.status_code == 200 for r in responses)
    with sqlite3.connect(url.removeprefix("sqlite:")) as c:
        assert c.execute("SELECT COUNT(*) FROM workflow_decisions WHERE tenant_id = ? AND workflow_id = ?",
                         (A, workflow["workflow_id"])).fetchone()[0] == 1


def test_concurrent_requests_across_tenants_have_no_5xx_no_leakage_and_no_contamination(tenants, monkeypatch) -> None:
    client, url, _ = tenants
    _scripted(monkeypatch)
    errors: list[str] = []
    per_tenant = 6

    def ingest(args):
        who, tenant_marker, index = args
        c = TestClient(app, raise_server_exceptions=False)
        r = c.post("/workflow/events", headers=bearer(who), json=_event(event_id=f"conc-{tenant_marker}-{index}",
                                                                       message=f"{tenant_marker}-MARKER-{index}"))
        if r.status_code != 200:
            errors.append(f"ingest {who} {r.status_code} {r.text[:120]}")

    jobs = [("n8n-a", "ALPHA", i) for i in range(per_tenant)] + [("n8n-b", "BRAVO", i) for i in range(per_tenant)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(ingest, jobs))
    assert errors == []

    def reader(args):
        who, own, other = args
        c = TestClient(app, raise_server_exceptions=False)
        for _ in range(8):
            for path in ("/incidents?limit=200", "/workflow?limit=200", "/me", "/incidents/INC-1001/detail", "/health/ready"):
                r = c.get(path, headers=bearer(who))
                if r.status_code >= 500 or (r.status_code not in (200, 404)):
                    errors.append(f"{who} {path} {r.status_code}")
                if other in r.text:
                    errors.append(f"{who} saw {other} data on {path}")
                if path.startswith("/incidents/INC-1001/detail") and r.status_code == 200 and own not in r.text:
                    errors.append(f"{who} detail lacks own marker")

    readers = [("op-a", "ALPHA", "BRAVO"), ("op-b", "BRAVO", "ALPHA")] * 3
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(reader, readers))
    assert errors == []
    # each tenant has exactly its own events, nothing duplicated and nothing contaminated
    for who, own in (("op-a", "ALPHA"), ("op-b", "BRAVO")):
        listing = client.get("/incidents?limit=200", headers=bearer(who))
        assert int(listing.headers["X-Total-Count"]) == per_tenant
        details = [client.get(f"/incidents/{i['incident_id']}/detail", headers=bearer(who)).json() for i in listing.json()]
        assert sorted(d["incident"]["description"] for d in details) == sorted(f"{own}-MARKER-{i}" for i in range(per_tenant))
