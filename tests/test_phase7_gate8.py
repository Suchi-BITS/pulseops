"""Phase 7 Gate 8 - evaluation integrity & reliability hardening tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.database import DatabaseManager, absolute_sqlite_url, resolve_database_path


# --------------------------------------------------------------------------- 1. database resolver / env config


def test_relative_sqlite_url_resolves_against_the_working_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    resolved = resolve_database_path("sqlite:///./pulseops.db")
    assert resolved == (tmp_path / "pulseops.db").absolute()
    assert resolved.parent != Path(resolved.anchor)  # never the filesystem/drive root


def test_three_slash_relative_and_four_slash_absolute_forms(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert resolve_database_path("sqlite:///data/x.db") == (tmp_path / "data" / "x.db").absolute()
    absolute = (tmp_path / "abs.db").as_posix()
    # sqlite:////abs/path on POSIX; sqlite:///C:/path on Windows
    url = f"sqlite:///{absolute}"
    assert resolve_database_path(url) == Path(absolute)


def test_legacy_absolute_forms_are_still_supported(tmp_path: Path) -> None:
    target = tmp_path / "legacy.db"
    assert resolve_database_path("sqlite:" + target.as_posix()) == target.absolute()


def test_non_sqlite_urls_are_rejected() -> None:
    with pytest.raises(ValueError):
        resolve_database_path("postgresql://user@host/db")


def test_database_manager_pins_an_absolute_path_independent_of_later_cwd_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.mkdir()
    second.mkdir()
    monkeypatch.chdir(first)
    manager = DatabaseManager("sqlite:///./pinned.db")
    monkeypatch.chdir(second)
    assert manager.database_path.is_absolute()
    assert manager.database_path == (first / "pinned.db").absolute()
    assert (first / "pinned.db").exists() and not (second / "pinned.db").exists()


def test_absolute_sqlite_url_round_trips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    absolute = absolute_sqlite_url("sqlite:///./x.db")
    monkeypatch.chdir(tmp_path.parent)
    assert resolve_database_path(absolute) == (tmp_path / "x.db").absolute()


def test_pulseops_database_url_environment_variable_drives_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PULSEOPS_DATABASE_URL", "sqlite:///./custom.db")
    assert get_settings().database_url == "sqlite:///./custom.db"
    monkeypatch.setenv("PULSEOPS_DATABASE_URL", "")
    assert get_settings().database_url == "sqlite:///./pulseops.db"
    monkeypatch.delenv("PULSEOPS_DATABASE_URL")
    assert get_settings().database_url == "sqlite:///./pulseops.db"


def test_test_session_is_isolated_from_the_developer_database() -> None:
    url = os.environ["PULSEOPS_DATABASE_URL"]
    assert "pulseops-tests-" in url
    assert resolve_database_path(url) != (Path.cwd() / "pulseops.db").absolute()


# --------------------------------------------------------------------------- 2. MCP subprocess database propagation


def _mcp_env(database_url: str) -> dict[str, str]:
    from app.agent.service import IncidentInvestigationAgent

    agent = IncidentInvestigationAgent(database_url=database_url, api_key="test-key")
    return dict(agent._build_sdk_options("INC-1008", None, DEV_IDENTITY).mcp_servers["pulseops"]["env"])


def test_mcp_subprocess_receives_an_absolute_database_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    env = _mcp_env("sqlite:///./agent.db")
    url = env["PULSEOPS_DATABASE_URL"]
    assert resolve_database_path(url) == (tmp_path / "agent.db").absolute()
    assert Path(resolve_database_path(url)).is_absolute()
    monkeypatch.chdir(tmp_path.parent)
    assert resolve_database_path(url) == (tmp_path / "agent.db").absolute()  # cwd-independent
    assert env["PYTHONPATH"]  # existing keys are preserved
    assert env["PULSEOPS_INCIDENT_ID"] == "INC-1008"


def _call_incident_context(env: dict[str, str], cwd: Path) -> str:
    import asyncio
    import sys

    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    async def go() -> str:
        params = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp.server"], env=env, cwd=cwd)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("get_incident_context", {"incident_id": "INC-1008"})
                return "ERROR" if result.is_error else result.content[0].text

    return asyncio.run(go())


def test_real_mcp_subprocess_reads_the_same_configured_database(tmp_path: Path) -> None:
    from app.services.incident_service import IncidentService

    database_url = "sqlite:" + (tmp_path / "configured.db").as_posix()
    created = IncidentService(database_url=database_url, tenant_id=DEV_TENANT).create_incident(
        service_id="svc-payment", severity="high", title="Only in the configured database",
        description="d", environment="production",
    )
    assert created.incident_id == "INC-1008"  # seed has INC-1007; this exists nowhere else
    elsewhere = tmp_path / "other-cwd"
    elsewhere.mkdir()
    repo_root = str(Path(__file__).resolve().parents[1])

    env = _mcp_env(database_url)
    assert "Only in the configured database" in _call_incident_context(env, elsewhere)

    # Without the propagated variable the subprocess falls back to its own default database and cannot see it.
    unconfigured = {k: v for k, v in env.items() if k != "PULSEOPS_DATABASE_URL"}
    unconfigured["PYTHONPATH"] = repo_root
    assert _call_incident_context(unconfigured, elsewhere) == "ERROR"


# --------------------------------------------------------------------------- 3. ungrounded-result hardening

MODEL_REC = "MODEL-REC: Roll back the last deployment."
MODEL_MISSING = "MODEL-MISSING: the database was deleted."


def _hostile_payload(**overrides):
    from tests.test_phase6 import grounded_payload

    return grounded_payload(
        incident_id=overrides.pop("incident_id", "INC-1007"),
        recommendations=[MODEL_REC], missing_information=[MODEL_MISSING], hypotheses=["MODEL-HYP may be it."],
        evidence=["MODEL-EVIDENCE"], confidence=0.9, **overrides,
    )


def _assert_nothing_from_the_model_survives(result) -> None:
    assert result.evidence == [] and result.hypotheses == [] and result.confidence == 0.0
    assert result.service_id == "unknown"
    blob = " ".join([result.summary, *result.recommendations, *result.missing_information])
    for marker in ("MODEL-REC", "MODEL-MISSING", "MODEL-HYP", "MODEL-EVIDENCE", "Roll back"):
        assert marker not in blob, marker
    assert result.recommendations, "system-authored next steps must remain"
    assert result.missing_information, "system-authored reasons must remain"


def test_unknown_incident_keeps_only_system_authored_guidance() -> None:
    from tests.test_phase6 import CONTEXT, final, init_message, run_agent, tool_result, tool_use

    stream = [
        init_message(), tool_use(CONTEXT, "t1", incident_id="INC-9999"),
        tool_result("t1", "Error executing tool get_incident_context: Incident 'INC-9999' not found", is_error=True),
        *final(_hostile_payload(incident_id="INC-9999")),
    ]
    result, _, _ = run_agent(stream, incident_id="INC-9999")
    _assert_nothing_from_the_model_survives(result)
    assert any("Verify that incident identifier INC-9999" in item for item in result.recommendations)
    assert any("not found" in item for item in result.missing_information)


def test_tool_timeout_keeps_only_system_authored_guidance() -> None:
    from tests.test_phase6 import CONTEXT, final, init_message, run_agent, tool_result, tool_use

    stream = [
        init_message(), tool_use(CONTEXT, "t1", incident_id="INC-1007"),
        tool_result("t1", [{"type": "text", "text": "MCP error -32001: Request timed out"}], is_error=True),
        *final(_hostile_payload()),
    ]
    result, _, _ = run_agent(stream)
    _assert_nothing_from_the_model_survives(result)
    assert any("Restore access" in item for item in result.recommendations)


def test_mcp_unavailable_with_a_model_payload_keeps_only_system_guidance() -> None:
    from tests.test_phase6 import final, init_message, run_agent

    result, _, _ = run_agent([init_message(status="failed"), *final(_hostile_payload())])
    _assert_nothing_from_the_model_survives(result)


def test_model_output_without_any_retrieval_keeps_only_system_guidance() -> None:
    from tests.test_phase6 import final, init_message, run_agent

    result, _, _ = run_agent([init_message(), *final(_hostile_payload())])
    _assert_nothing_from_the_model_survives(result)
    assert any("Re-run the investigation" in item for item in result.recommendations)


def test_context_without_usable_evidence_keeps_only_system_guidance() -> None:
    from tests.test_phase6 import CONTEXT, empty_context_result, final, init_message, run_agent, tool_result, tool_use

    stream = [
        init_message(), tool_use(CONTEXT, "t1", incident_id="INC-1007"),
        tool_result("t1", empty_context_result()), *final(_hostile_payload()),
    ]
    result, agent, _ = run_agent(stream)
    _assert_nothing_from_the_model_survives(result)
    assert agent.last_telemetry.grounded is False


def test_grounded_results_still_keep_model_recommendations_and_missing_information() -> None:
    from tests.test_phase6 import run_agent, standard_stream

    result, agent, _ = run_agent(standard_stream(_hostile_payload()))
    assert agent.last_telemetry.grounded is True
    assert MODEL_REC in result.recommendations and MODEL_MISSING in result.missing_information


# --------------------------------------------------------------------------- 4. investigation outcome / status / failure reason

from types import SimpleNamespace  # noqa: E402

from app.agent.service import InvestigationResult  # noqa: E402
from app.services.event_service import InvestigationOutcome  # noqa: E402
from tests.helpers import DEV_IDENTITY, DEV_TENANT, REVIEWER  # noqa: E402
from tests.test_phase7_gate6 import StubInvestigator, _event, env  # noqa: E402,F401  (env is a pytest fixture)


def _types(body: dict) -> list[str]:
    return [e["event_type"] for e in body["audit_events"]]


def _approve(client, body: dict, action: str = "notify"):
    return client.post(
        f"/workflow/{body['workflow_id']}/decision",
        headers=REVIEWER,
        json={"decision": "approve", "incident_id": body["incident_id"],
              "action": action, "timestamp": "2026-01-01T00:00:00Z"},
    )


def test_ungrounded_investigation_is_degraded_fails_closed_and_cannot_be_approved(env, monkeypatch) -> None:
    client, stub, _, _ = env
    ungrounded = InvestigationResult(
        incident_id="PLACEHOLDER", service_id="unknown", summary="not found", evidence=[], confidence=0.0,
        missing_information=["Incident could not be retrieved."], recommendations=["Verify the incident id."],
    )

    async def fixed(incident_id: str, objective):
        return ungrounded.model_copy(update={"incident_id": incident_id})

    monkeypatch.setattr("app.services.event_service.build_investigator", lambda url: fixed)
    event = _event(severity="low")
    response = client.post("/workflow/events", json=event)
    assert response.status_code == 200
    body = response.json()
    assert body["investigation_status"] == "degraded"
    assert body["failure_reason"] == "investigation_ungrounded"
    assert body["policy_decision"] == "investigation_degraded"
    assert body["policy_decision"] != "deny" and body["policy_reason"] is None
    assert body["status"] == "rejected" and body["requires_approval"] is False
    types = _types(body)
    assert "INVESTIGATION_DEGRADED" in types and "WORKFLOW_FAILED" in types
    assert "INVESTIGATION_COMPLETED" not in types and "POLICY_EVALUATED" not in types
    assert "NOTIFICATION_REQUESTED" not in types
    assert body["investigation"]["evidence"] == []
    assert body["investigation"]["recommendations"] == ["Verify the incident id."]
    approve = _approve(client, body)
    assert approve.status_code == 409 and "final state" in approve.json()["detail"]
    persisted = client.get(f"/workflow/{body['workflow_id']}").json()
    assert persisted["status"] == "rejected" and persisted["policy_decision"] == "investigation_degraded"
    assert persisted["details"]["investigation"] == {"status": "degraded", "failure_reason": "investigation_ungrounded"}

    replay = client.post("/workflow/events", json=event).json()
    assert replay["idempotent_replay"] is True
    assert replay["investigation_status"] == "degraded" and replay["failure_reason"] == "investigation_ungrounded"
    assert replay["policy_decision"] == "investigation_degraded"
    assert replay["investigation"]["recommendations"] == ["Verify the incident id."]


def test_agent_telemetry_grounding_overrides_a_result_that_merely_has_evidence(env, monkeypatch) -> None:
    client, _, _, _ = env

    async def ungrounded(incident_id: str, objective):
        result = InvestigationResult(incident_id=incident_id, summary="s", evidence=["looks like evidence"], confidence=0.5)
        return InvestigationOutcome(result=result, grounded=False)

    monkeypatch.setattr("app.services.event_service.build_investigator", lambda url: ungrounded)
    body = client.post("/workflow/events", json=_event(severity="low")).json()
    assert body["investigation_status"] == "degraded" and body["policy_decision"] == "investigation_degraded"


def test_build_investigator_maps_agent_telemetry_to_grounded(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    import app.agent.service as agent_module
    from app.services.event_service import build_investigator

    class FakeAgent:
        grounded = True

        def __init__(self, database_url=None, **_kw) -> None:
            self.last_telemetry = None

        async def investigate(self, incident_id, objective=None, identity_context=None):
            self.last_telemetry = SimpleNamespace(grounded=FakeAgent.grounded, model='m', duration_ms=1, api_duration_ms=None,
                                                  total_cost_usd=None, usage=None)
            return InvestigationResult(incident_id=incident_id, summary="s")

    from app.core.request_context import bind_principal
    from app.core.security import Principal, PrincipalType

    bind_principal(Principal(principal_id="p", principal_type=PrincipalType.HUMAN,
                             roles=("operator",), tenant_id=DEV_TENANT, auth_method="dev"))
    monkeypatch.setattr(agent_module, "IncidentInvestigationAgent", FakeAgent)
    outcome = asyncio.run(build_investigator("sqlite:///x.db")("INC-1", None))
    assert outcome.grounded is True
    FakeAgent.grounded = False
    assert asyncio.run(build_investigator("sqlite:///x.db")("INC-1", None)).grounded is False


@pytest.mark.parametrize("failure", ["raise", "bad_result", "wrong_incident"])
def test_failed_investigation_is_failed_not_denied_and_cannot_be_approved(env, failure: str) -> None:
    client, stub, _, _ = env
    if failure == "raise":
        stub.fail_with = RuntimeError("sdk crashed")
    elif failure == "bad_result":
        stub.bad_result = "not a result"
    else:
        stub.bad_result = InvestigationResult(incident_id="INC-OTHER")
    body = client.post("/workflow/events", json=_event(severity="low")).json()
    assert body["investigation_status"] == "failed"
    assert body["failure_reason"] == "investigation_failed"
    assert body["policy_decision"] == "investigation_failed" and body["policy_decision"] != "deny"
    assert "INVESTIGATION_FAILED" in _types(body) and "POLICY_EVALUATED" not in _types(body)
    assert _approve(client, body).status_code == 409


def test_deny_remains_a_genuine_policy_decision_distinct_from_failures(env) -> None:
    client, _, _, _ = env
    denied = client.post("/workflow/events", json=_event(metadata={"requested_action": "delete_data"})).json()
    assert denied["policy_decision"] == "deny"
    assert denied["investigation_status"] == "completed" and denied["failure_reason"] is None
    assert denied["policy_reason"]  # produced by the policy engine
    assert denied["policy_decision"] not in {"investigation_pending", "investigation_degraded", "investigation_failed"}


def test_workflow_is_held_as_investigation_pending_not_deny_while_investigating(env, monkeypatch) -> None:
    client, _, _, workflows = env
    observed: dict = {}

    def build(url: str):
        async def investigate(incident_id: str, objective):
            workflow = workflows.get_latest_workflow_for_incident(incident_id)
            observed["decision"], observed["status"] = workflow["policy_decision"], workflow["status"]
            try:
                workflows.record_decision(
                    workflow["workflow_id"], decision="approve", reviewer="incident-manager",
                    incident_id=incident_id, action="notify", timestamp="2026-01-01T00:00:00Z",
                )
                observed["approved_while_held"] = True
            except ValueError as exc:
                observed["blocked"] = str(exc)
            return InvestigationResult(incident_id=incident_id, summary="s", evidence=["e"], confidence=0.5)

        return investigate

    monkeypatch.setattr("app.services.event_service.build_investigator", build)
    body = client.post("/workflow/events", json=_event(severity="low")).json()
    assert observed["decision"] == "investigation_pending" and observed["status"] == "rejected"
    assert "approved_while_held" not in observed and "final state" in observed["blocked"]
    assert body["investigation_status"] == "completed" and body["policy_decision"] == "allow"
    assert body["status"] == "pending"  # the hold is released only after a completed investigation


# --------------------------------------------------------------------------- 5-9. evaluation: dataset v2, retrieval, tool selection,
# latency, content hashing

import copy  # noqa: E402
import json  # noqa: E402

from evals import scorers  # noqa: E402
from evals.baseline import compare_to_baseline, load_baseline  # noqa: E402
from evals.contracts import AgentScript, Expected, GoldenCase  # noqa: E402
from evals.hashing import canonical_sha256, file_sha256  # noqa: E402
from evals.harness import CaseRun, live_all  # noqa: E402
from evals.report import to_markdown  # noqa: E402
from evals.retrieval import (  # noqa: E402
    RETRIEVAL_DATASET_PATH,
    _evaluate,
    aggregate_retrieval,
    retrieval_dataset_sha256,
    run_retrieval_checks,
)
from evals.runner import BASELINE_PATH, DATASET_PATH, load_dataset, run_replay  # noqa: E402

V1_CASE_IDS = [
    "c01-normal-pool-exhaustion", "c02-error-rate-spike", "c03-latency-dependency", "c04-failed-deployment",
    "c05-missing-metric", "c06-missing-deployment", "c07-conflicting-evidence", "c08-unknown-incident",
    "c09-tool-timeout", "c10-malformed-output", "c11-prompt-injection", "c12-policy-boundary-manipulation",
]
CTX_TOOL = "mcp__pulseops__get_incident_context"
REPO_TOOL = "mcp__pulseops__get_service_repository"


@pytest.fixture(scope="module")
def v2_report():
    return run_replay()


def _run(tool_calls: list[str], expected: dict) -> CaseRun:
    from tests.test_phase7_gate7 import case_with, result_with

    return CaseRun(case=case_with(expected), result=result_with(tool_calls=tool_calls), corpus="")


# --- dataset v2 ---------------------------------------------------------------------------------


def test_dataset_v2_preserves_every_v1_case_and_adds_twelve_documented_ones() -> None:
    version, cases = load_dataset()
    ids = [c.case_id for c in cases]
    assert version == "golden-v2" and len(cases) == len(set(ids)) == 24
    assert ids[:12] == V1_CASE_IDS, "golden-v1 cases must be preserved, in order"
    new_cases = cases[12:]
    assert len(new_cases) == 12
    for case in new_cases:
        assert case.expected_behavior.strip(), f"{case.case_id} needs an expected_behavior"
        assert case.description.strip()
        assert case.expected.expected_tools is not None, f"{case.case_id} needs expected tool behaviour"
        has_safety_expectation = (
            case.expected.injection_markers or case.expected.expect_failure != "none"
            or case.expected.max_confidence is not None or case.policy_probes
        )
        assert has_safety_expectation, f"{case.case_id} needs a safety expectation"
        assert case.expected.evidence_must_include or case.expected.expect_failure != "none"


def test_dataset_v2_covers_the_gate_8_scenarios() -> None:
    _, cases = load_dataset()
    categories = " | ".join(c.category for c in cases[12:])
    for scenario in (
        "memory leak", "authentication failure", "network timeout", "insufficient capacity", "ambiguous cause",
        "missing logs", "low-confidence", "model timeout", "incomplete tool response",
    ):
        assert scenario in categories, scenario
    assert categories.count("prompt injection") >= 3  # three additional injection channels


def test_new_failure_cases_fail_closed_in_replay(v2_report) -> None:
    by_case = {c.case_id: c for c in v2_report.cases}
    assert by_case["c20-model-timeout"].outcome == "raised:RuntimeError"
    assert by_case["c21-incomplete-tool-response"].outcome == "result"
    scores = {s.metric: s for s in by_case["c21-incomplete-tool-response"].scores}
    assert scores["failure_behavior"].passed is True and scores["policy_boundary"].passed is True
    assert {s.metric: s for s in by_case["c24-injection-via-tool-result"].scores}["injection_resistance"].passed is True
    for agg in v2_report.system_correctness_safety.values():
        assert agg.mean_score == 1.0, (agg.metric, agg.failed_cases)


# --- tool selection -----------------------------------------------------------------------------


def test_tool_selection_positive_missing_unnecessary_and_optional() -> None:
    expected = {"expected_tools": [CTX_TOOL, REPO_TOOL], "optional_tools": ["mcp__pulseops__get_related_incidents"]}
    assert scorers.tool_selection(_run([CTX_TOOL, REPO_TOOL], expected)).passed is True
    assert scorers.tool_selection(_run([CTX_TOOL, REPO_TOOL, "mcp__pulseops__get_related_incidents"], expected)).passed is True
    missing = scorers.tool_selection(_run([CTX_TOOL], expected))
    assert missing.passed is False and missing.score == 0.5 and "expected tool not called" in missing.details[0]
    extra = scorers.tool_selection(_run([CTX_TOOL, REPO_TOOL, "mcp__pulseops__get_service_dependencies"], expected))
    assert extra.passed is False and "unnecessary tool called" in extra.details[0]


def test_tool_selection_never_rewards_calling_every_tool() -> None:
    from app.agent.service import IncidentInvestigationAgent

    expected = {"expected_tools": [CTX_TOOL]}
    lean = scorers.tool_selection(_run([CTX_TOOL], expected))
    everything = scorers.tool_selection(_run(list(IncidentInvestigationAgent.MCP_TOOL_NAMES), expected))
    assert lean.score == 1.0 and everything.score < lean.score


def test_tool_selection_not_applicable_without_expectation_and_uses_telemetry_when_the_run_raised() -> None:
    from types import SimpleNamespace

    from tests.test_phase7_gate7 import case_with

    assert scorers.tool_selection(_run([CTX_TOOL], {})).applicable is False
    raised = CaseRun(case=case_with({"expected_tools": [CTX_TOOL]}), exception=ValueError("x"),
                     telemetry=SimpleNamespace(tool_calls=[CTX_TOOL]))
    assert scorers.tool_selection(raised).passed is True
    no_calls = CaseRun(case=case_with({"expected_tools": []}), exception=RuntimeError("x"),
                       telemetry=SimpleNamespace(tool_calls=[]))
    assert scorers.tool_selection(no_calls).passed is True


def test_tool_selection_is_reported_as_ai_quality_not_system(v2_report) -> None:
    assert "tool_selection" in v2_report.ai_quality and "tool_selection" not in v2_report.system_correctness_safety
    assert v2_report.ai_quality["tool_selection"].applicable_cases == 24


# --- retrieval ground truth ---------------------------------------------------------------------


def test_retrieval_ground_truth_passes_for_all_four_tools() -> None:
    results = run_retrieval_checks()
    assert {r.tool for r in results} == {
        "get_incident_context", "get_related_incidents", "get_service_repository", "get_service_dependencies",
    }
    assert all(r.passed for r in results), [(r.check_id, r.details) for r in results if not r.passed]
    aggregate = aggregate_retrieval(results)
    assert aggregate.mean_score == 1.0 and aggregate.applicable_cases == len(results)


def test_retrieval_evaluator_detects_wrong_missing_and_leaked_data() -> None:
    value = {"service_id": "svc-payment", "logs": ["a", "b"], "context": {"evidence": [{"source_id": "log-1"}]}}
    ok = {"fields": {"service_id": "svc-payment", "logs": ["b", "a"]}, "unordered_fields": ["logs"],
          "evidence_source_ids_include": ["log-1"], "evidence_source_ids_exclude": ["log-9"]}
    outcomes, problems = _evaluate(True, value, ok)
    assert all(outcomes) and problems == []
    bad = {"fields": {"service_id": "svc-ledger", "logs": ["a"]}, "evidence_source_ids_include": ["log-2"],
           "evidence_source_ids_exclude": ["log-1"]}
    outcomes, problems = _evaluate(True, value, bad)
    assert not all(outcomes) and len(problems) == 4
    outcomes, _ = _evaluate(False, "boom", {"value": []})
    assert not all(outcomes)
    outcomes, _ = _evaluate(False, "Incident 'x' not found", {"error_contains": "not found"})
    assert all(outcomes)
    outcomes, _ = _evaluate(True, ["x"], {"error_contains": "not found"})
    assert not all(outcomes)


def test_tampered_retrieval_ground_truth_fails_the_check_and_the_hash(tmp_path: Path) -> None:
    dataset = json.loads(RETRIEVAL_DATASET_PATH.read_text(encoding="utf-8"))
    tampered = copy.deepcopy(dataset)
    for check in tampered["checks"]:
        if check["check_id"] == "repository-svc-payment":
            check["expect"]["value"] = "repo-someone-else"
    path = tmp_path / "retrieval.json"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    results = run_retrieval_checks(path)
    failed = [r.check_id for r in results if not r.passed]
    assert failed == ["repository-svc-payment"]
    assert aggregate_retrieval(results).mean_score < 1.0
    assert file_sha256(path) != retrieval_dataset_sha256()


def test_retrieval_correctness_is_a_system_metric_in_the_report(v2_report) -> None:
    agg = v2_report.system_correctness_safety["retrieval_correctness"]
    assert agg.mean_score == 1.0 and agg.applicable_cases == 13
    assert len(v2_report.retrieval_checks) == 13
    markdown = to_markdown(v2_report)
    assert "Retrieval ground truth" in markdown and "KNOWN DEVIATION" in markdown


def test_a_retrieval_regression_fails_the_gate(v2_report) -> None:
    baseline = load_baseline(BASELINE_PATH)
    worse = copy.deepcopy(v2_report)
    worse.system_correctness_safety["retrieval_correctness"].mean_score = 0.9
    result = compare_to_baseline(worse, baseline)
    assert result.failed and any(f.metric == "retrieval_correctness" for f in result.regressions)


# --- latency ------------------------------------------------------------------------------------


def test_latency_is_reported_per_case_and_summarised_but_never_gated(v2_report) -> None:
    assert {"investigation_ms", "workflow_ms", "scoring_ms", "total_run_ms"} <= set(v2_report.timings)
    assert v2_report.timings["investigation_ms"].count == 24
    assert v2_report.timings["workflow_ms"].count == 11  # cases with policy probes
    for summary in v2_report.timings.values():
        assert summary.mean_ms >= 0 and summary.p50_ms >= 0 and summary.max_ms >= summary.p50_ms
    assert all("investigation_ms" in c.timings_ms and "scoring_ms" in c.timings_ms for c in v2_report.cases)
    assert "Timing (informational, never gated)" in to_markdown(v2_report)
    assert any("not model latency" in note for note in v2_report.notes)

    slow = copy.deepcopy(v2_report)
    for summary in slow.timings.values():
        summary.max_ms = summary.mean_ms = summary.p50_ms = 10**9
    assert not compare_to_baseline(slow, load_baseline(BASELINE_PATH)).failed
    assert not any("ms" in key for key in load_baseline(BASELINE_PATH)["metrics"])


# --- dataset content hashing --------------------------------------------------------------------


def test_canonical_hash_is_deterministic_and_content_sensitive() -> None:
    assert canonical_sha256({"a": 1, "b": [1, 2]}) == canonical_sha256({"b": [1, 2], "a": 1})
    assert canonical_sha256({"a": 1}) != canonical_sha256({"a": 2})
    assert canonical_sha256({"b": [1, 2]}) != canonical_sha256({"b": [2, 1]})
    assert file_sha256(DATASET_PATH) == file_sha256(DATASET_PATH)


def test_baseline_v2_records_both_dataset_hashes_and_matches_the_committed_files() -> None:
    baseline = load_baseline(BASELINE_PATH)
    assert baseline["baseline_version"] >= 2
    assert baseline["dataset_sha256"] == file_sha256(DATASET_PATH)
    assert baseline["retrieval_dataset_sha256"] == file_sha256(RETRIEVAL_DATASET_PATH)


def test_same_label_with_changed_content_is_detected(v2_report, tmp_path: Path) -> None:
    baseline = load_baseline(BASELINE_PATH)
    assert not compare_to_baseline(v2_report, baseline).failed

    raw = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    assert raw["dataset_version"] == "golden-v2"
    raw["cases"][0]["expected"]["evidence_must_include"] = ["something silently weakened"]  # label unchanged
    tampered = tmp_path / "golden.json"
    tampered.write_text(json.dumps(raw), encoding="utf-8")
    assert json.loads(tampered.read_text(encoding="utf-8"))["dataset_version"] == baseline["dataset_version"]

    changed = copy.deepcopy(v2_report)
    changed.dataset_sha256 = file_sha256(tampered)
    result = compare_to_baseline(changed, baseline)
    assert result.failed
    assert any(f.metric == "dataset_sha256" and "content changed" in f.message for f in result.regressions)

    changed_retrieval = copy.deepcopy(v2_report)
    changed_retrieval.retrieval_dataset_sha256 = "0" * 64
    assert any(f.metric == "retrieval_dataset_sha256" for f in compare_to_baseline(changed_retrieval, baseline).regressions)


def test_a_baseline_without_hashes_is_not_silently_accepted(v2_report) -> None:
    legacy = {k: v for k, v in load_baseline(BASELINE_PATH).items() if not k.endswith("sha256")}
    result = compare_to_baseline(v2_report, legacy)
    assert result.failed and {f.metric for f in result.regressions} >= {"dataset_sha256", "retrieval_dataset_sha256"}


def test_report_carries_the_dataset_hashes(v2_report) -> None:
    assert v2_report.dataset_sha256 == file_sha256(DATASET_PATH)
    assert v2_report.retrieval_dataset_sha256 == file_sha256(RETRIEVAL_DATASET_PATH)
    assert json.loads(v2_report.model_dump_json())["dataset_sha256"]


def test_negative_control_still_fails_with_gate_8_metrics() -> None:
    from tests.test_phase7_gate7 import _broken_case

    report = run_replay(cases=[_broken_case()], dataset_version="golden-v2")
    assert report.passed is False
    assert report.system_correctness_safety["fabrication_detection"].mean_score == 0.0
    assert any(f.metric == "dataset_sha256" for f in report.regression.regressions)  # also a tampered dataset


# --- live eligibility over real fixtures --------------------------------------------------------


def test_live_cases_run_over_their_own_fixture_database_with_an_independent_corpus() -> None:
    from app.agent.service import InvestigationResult
    from app.database import resolve_database_path

    _, cases = load_dataset()
    case = next(c for c in cases if c.case_id == "c13-memory-leak")
    assert case.live_eligible
    seen: dict = {}

    class FakeAgent:
        def __init__(self, database_url=None, model=None) -> None:
            seen["url"], seen["model"] = database_url, model
            self.last_telemetry = None

        async def investigate(self, incident_id, objective=None, identity_context=None):
            import sqlite3

            with sqlite3.connect(resolve_database_path(seen["url"])) as db:
                seen["incident"] = db.execute(
                    "SELECT title FROM incidents WHERE incident_id = ?", (incident_id,)
                ).fetchone()
            return InvestigationResult(incident_id=incident_id, summary="s", confidence=0.5)

    run = live_all([case], model="test-model", agent_factory=FakeAgent)[0]
    assert seen["model"] == "test-model"
    assert seen["incident"] == ("Payment workers restarting",)  # the agent was handed the case's own database
    assert "memory_usage" in run.corpus and "OutOfMemoryError" in run.corpus  # fetched from the real tools
    assert "investigation_ms" in run.timings


def test_scripted_failure_cases_are_not_live_eligible() -> None:
    _, cases = load_dataset()
    by_id = {c.case_id: c for c in cases}
    for cid in ("c09-tool-timeout", "c10-malformed-output", "c20-model-timeout", "c21-incomplete-tool-response",
                "c24-injection-via-tool-result"):
        assert by_id[cid].live_eligible is False
    assert sum(c.live_eligible for c in cases) >= 16


# --------------------------------------------------------------------------- evals never touch a developer database


def test_evals_cli_does_not_create_a_developer_database_in_the_working_directory(tmp_path: Path) -> None:
    import subprocess
    import sys

    repo_root = Path(__file__).resolve().parents[1]
    env = {k: v for k, v in os.environ.items() if k != "PULSEOPS_DATABASE_URL"}
    env["PYTHONPATH"] = str(repo_root)
    proc = subprocess.run(
        [sys.executable, "-m", "evals", "live", "--out", str(tmp_path / "out")],  # SKIPPED without a key: fast
        cwd=tmp_path, env={**env, "ANTHROPIC_API_KEY": ""}, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "STATUS: SKIPPED" in proc.stdout
    assert not list(tmp_path.glob("*.db")), "evals created a database in the working directory"
