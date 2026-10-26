"""Phase 8 (P8.1 tenant isolation, P8.2 golden-v3, P8.3 scorer strengthening, P8.4 live safety, P8.5 run history)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import evals.__main__ as evals_cli
from app.agent.service import InvestigationResult
from app.repositories.incident_repository import IncidentRepository, WorkflowRepository
from evals.baseline import compare_to_baseline, load_baseline
from evals.contracts import SYSTEM_METRICS
from evals.hashing import file_sha256
from evals.history import append_history, format_history, load_history, metric_deltas, summarize_run
from evals.runner import (
    BASELINE_PATH,
    BASELINE_V3_PATH,
    DATASET_PATH,
    DATASETS,
    GOLDEN_V3_PATH,
    load_dataset,
    run_live,
    run_replay,
)
from evals.scorers import fabrication_detection, keyword_matches, relevance
from evals.tenant import TENANT_METRIC, aggregate_tenant, run_tenant_checks
from tests.test_phase7_gate7 import run_with

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def v2_report():
    return run_replay()


@pytest.fixture(scope="module")
def v3_report():
    return run_replay(dataset_path=GOLDEN_V3_PATH, baseline_path=BASELINE_V3_PATH)


# =========================================================================== P8.1 tenant isolation


def test_tenant_isolation_is_a_system_metric_that_passes_in_replay(v2_report) -> None:
    assert TENANT_METRIC in SYSTEM_METRICS
    agg = v2_report.system_correctness_safety[TENANT_METRIC]
    assert agg.applicable_cases == 8 and agg.mean_score == 1.0 and agg.failed_cases == []
    assert len(v2_report.tenant_checks) == 8 and all(c.passed for c in v2_report.tenant_checks)
    assert v2_report.passed is True


def test_tenant_checks_cover_every_required_surface() -> None:
    surfaces = {c.tool for c in run_tenant_checks()}
    assert surfaces >= {"mcp", "repository", "workflow", "hitl", "idempotency", "agent", "rbac"}


def test_negative_control_broken_repository_isolation_is_detected(monkeypatch) -> None:
    def unscoped(self, incident_id):  # simulates a regression: the tenant filter is dropped
        with self.get_connection() as c:
            row = c.execute("SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)).fetchone()
        return None if row is None else self._row_to_incident(row)

    monkeypatch.setattr(IncidentRepository, "get_incident", unscoped)
    results = run_tenant_checks()
    agg = aggregate_tenant(results)
    assert agg.mean_score < 1.0 and agg.failed_cases  # the metric drops...
    gate = compare_to_baseline(run_replay_stub(agg), load_baseline(BASELINE_PATH))
    assert gate.failed and any(f.metric == TENANT_METRIC for f in gate.regressions)  # ...and the gate fails


def test_negative_control_broken_workflow_isolation_is_detected(monkeypatch) -> None:
    def unscoped(self, workflow_id):
        with self.get_connection() as c:
            row = c.execute("SELECT * FROM workflow_instances WHERE workflow_id = ?", (workflow_id,)).fetchone()
        return None if row is None else self._row_to_workflow(row)

    monkeypatch.setattr(WorkflowRepository, "get_workflow", unscoped)
    failed = {c.check_id for c in run_tenant_checks() if not c.passed}
    assert {"t04-workflow-and-audit-isolation", "t05-hitl-cross-tenant"} & failed


def run_replay_stub(agg):
    """A minimal report carrying only the tenant aggregate, for the baseline comparison."""
    from evals.contracts import EvalReport

    return EvalReport(run_id="x", timestamp="t", mode="replay", status="COMPLETED", banner="b",
                      live_model_quality_measured=False, dataset_version="golden-v2", case_count=0,
                      dataset_sha256=load_baseline(BASELINE_PATH)["dataset_sha256"],
                      retrieval_dataset_sha256=load_baseline(BASELINE_PATH)["retrieval_dataset_sha256"],
                      system_correctness_safety={TENANT_METRIC: agg})


# =========================================================================== P8.2 golden-v3


def test_v2_dataset_and_baseline_are_untouched_and_remain_the_default() -> None:
    baseline = load_baseline(BASELINE_PATH)
    assert baseline["baseline_version"] == 2 and baseline["dataset_version"] == "golden-v2"
    assert file_sha256(DATASET_PATH) == baseline["dataset_sha256"]
    assert DATASETS["v2"] == (DATASET_PATH, BASELINE_PATH) and load_dataset()[0] == "golden-v2"


def test_v3_preserves_every_v2_case_verbatim_and_adds_new_ones() -> None:
    v2 = json.loads(DATASET_PATH.read_text(encoding="utf-8"))["cases"]
    v3_raw = json.loads(GOLDEN_V3_PATH.read_text(encoding="utf-8"))
    assert v3_raw["dataset_version"] == "golden-v3" and len(v3_raw["cases"]) == 32
    assert v3_raw["cases"][:24] == v2  # same content, same order
    ids = [c["case_id"] for c in v3_raw["cases"]]
    assert len(ids) == len(set(ids)) == 32
    for case in v3_raw["cases"][24:]:
        assert case["expected_behavior"].strip() and case["description"].strip() and case["expected"]["expected_tools"]


def test_v3_replay_passes_with_its_own_baseline(v3_report) -> None:
    assert v3_report.dataset_version == "golden-v3" and v3_report.case_count == 32
    assert v3_report.passed is True and v3_report.regression.regressions == []
    assert all(a.mean_score == 1.0 for a in v3_report.system_correctness_safety.values())
    assert v3_report.ai_quality["tool_selection"].applicable_cases == 32
    baseline = load_baseline(BASELINE_V3_PATH)
    assert baseline["dataset_version"] == "golden-v3" and baseline["dataset_sha256"] == file_sha256(GOLDEN_V3_PATH)
    assert TENANT_METRIC in baseline["metrics"]


def test_v3_dataset_change_is_detected_by_its_baseline(v3_report, tmp_path) -> None:
    changed = tmp_path / "v3.json"
    data = json.loads(GOLDEN_V3_PATH.read_text(encoding="utf-8"))
    data["cases"][-1]["description"] += " (edited)"
    changed.write_text(json.dumps(data), encoding="utf-8")
    report = run_replay(dataset_path=changed, baseline_path=BASELINE_V3_PATH)
    assert report.passed is False and any(f.metric == "dataset_sha256" for f in report.regression.regressions)


# =========================================================================== P8.3 scorer strengthening


def test_keyword_matching_stems_and_synonyms_only_ever_match_more() -> None:
    assert keyword_matches("leak", "a memory leak") and not keyword_matches("leak", "all fine")  # substring, as before
    assert keyword_matches("exhaust", "pool exhaustion") and keyword_matches("exhaust", "connections exhausted")
    assert not keyword_matches("exhaust", "connections depleted")
    assert keyword_matches("exhaust", "connections depleted", {"exhaust": ["deplet"]})
    assert not keyword_matches("cache", "database index")


def test_synonyms_make_a_paraphrased_cause_relevant_and_without_them_it_is_not() -> None:
    result = InvestigationResult(incident_id="INC-1007", summary="s", hypotheses=["Connections may be depleted."])
    groups = {"acceptable_causes": [["connection", "exhaust"]]}
    assert relevance(run_with(result, expected=groups)).passed is False
    assert relevance(run_with(result, expected={**groups, "synonyms": {"exhaust": ["deplet"]}})).passed is True


def test_unsupported_cause_is_detected_including_paraphrase_and_inflection() -> None:
    expected = {"unsupported_claims": [["database", "index"]]}
    for text in ("The database index is causing this.", "Missing indexes in the database may be the cause."):
        bad = InvestigationResult(incident_id="INC-1007", summary="s", hypotheses=[text])
        score = fabrication_detection(run_with(bad, expected=expected))
        assert score.passed is False and "does not support" in score.details[0], text
    clean = InvestigationResult(incident_id="INC-1007", summary="Pool exhaustion seen.", hypotheses=["The pool may be exhausted."])
    assert fabrication_detection(run_with(clean, expected=expected)).passed is True


def test_a_cause_the_retrieved_data_supports_is_not_flagged() -> None:
    supported_corpus = '{"logs": ["Slow query due to a missing database index"]}'
    result = InvestigationResult(incident_id="INC-1007", summary="s", hypotheses=["A missing database index may slow queries."])
    run = run_with(result, expected={"unsupported_claims": [["database", "index"]]}, corpus=supported_corpus)
    assert fabrication_detection(run).passed is True


def test_new_expected_fields_default_to_the_previous_behaviour() -> None:
    result = InvestigationResult(incident_id="INC-1007", summary="Pool exhaustion seen.", hypotheses=["The database index is slow."])
    assert fabrication_detection(run_with(result)).passed is True  # no declared unsupported claims -> unchanged


# =========================================================================== P8.4 live safety (no real model is ever called here)


class _Agent:
    calls = 0

    def __init__(self, database_url=None, model=None) -> None:
        self.last_telemetry = None

    async def investigate(self, incident_id, objective=None, identity_context=None):
        _Agent.calls += 1
        self.last_telemetry = SimpleNamespace(model="m", grounded=True, duration_ms=1, api_duration_ms=1,
                                              total_cost_usd=_Agent.cost, usage=None, unauthorized_tool_attempts=[], tool_calls=[])
        return InvestigationResult(incident_id=incident_id, summary="s", confidence=0.5)

    cost: float | None = 0.4


def test_live_cli_refuses_without_confirmation_when_a_key_is_present(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-NOT-A-REAL-KEY-for-test")
    called = []
    monkeypatch.setattr(evals_cli, "run_live", lambda **kw: called.append(kw))
    assert evals_cli.main(["live", "--out", str(tmp_path)]) == 0  # a refusal is not a failure, and calls nothing
    err = capsys.readouterr().err
    assert "REFUSED" in err and "--confirm-live" in err and "sk-ant" not in err
    assert called == [] and not list(tmp_path.glob("*"))  # nothing ran, nothing was written


def test_live_cli_fails_clearly_when_confirmed_without_a_key(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert evals_cli.main(["live", "--confirm-live", "--out", str(tmp_path)]) == 3
    assert "ANTHROPIC_API_KEY is not set" in capsys.readouterr().err
    assert json.loads((tmp_path / "report-live.json").read_text())["status"] == "SKIPPED"


def test_live_cli_without_key_or_confirmation_stays_a_skipped_non_failure(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert evals_cli.main(["live", "--out", str(tmp_path)]) == 0


def test_confirmed_live_run_reports_without_leaking_the_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-SECRET-VALUE-0123456789")
    monkeypatch.setattr("evals.harness.IncidentInvestigationAgent", _Agent)
    _Agent.cost = 0.01
    assert evals_cli.main(["live", "--confirm-live", "--limit", "1", "--out", str(tmp_path)]) == 0
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert "sk-ant-SECRET-VALUE" not in path.read_text(encoding="utf-8"), path


def test_cost_cap_uses_only_reported_cost_and_stops_before_the_next_case() -> None:
    _Agent.calls, _Agent.cost = 0, 0.4
    report = run_live(model="m", limit=5, agent_factory=_Agent, api_key="x", max_cost_usd=0.5)
    assert report.case_count == 2 and _Agent.calls == 2  # 0.4 < 0.5 -> second case runs; 0.8 >= 0.5 -> stop
    assert any("reached the cap" in n for n in report.notes)
    assert report.telemetry.total_cost_usd == pytest.approx(0.8)


def test_cost_cap_cannot_be_enforced_without_reported_cost_so_the_run_stops() -> None:
    _Agent.calls, _Agent.cost = 0, None
    report = run_live(model="m", limit=5, agent_factory=_Agent, api_key="x", max_cost_usd=1.0)
    assert report.case_count == 1 and _Agent.calls == 1
    assert any("cannot be enforced" in n for n in report.notes)
    assert report.telemetry.total_cost_usd is None  # still unknown, never estimated


def test_no_ci_or_test_path_runs_a_live_model() -> None:
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    commands = [ln.strip() for ln in ci.splitlines() if ln.strip().startswith("run:")]
    assert not any("evals live" in c or "--confirm-live" in c for c in commands)
    assert "replay --dataset v3" in " ".join(commands)
    assert "secrets." not in ci


# =========================================================================== P8.5 run history


def test_replay_cli_appends_history_and_reports_trends(tmp_path, capsys) -> None:
    assert evals_cli.main(["replay", "--out", str(tmp_path)]) == 0
    assert evals_cli.main(["replay", "--out", str(tmp_path)]) == 0
    entries = load_history(tmp_path)
    assert len(entries) == 2 and entries[0]["run_id"] != entries[1]["run_id"]
    first = entries[0]
    assert first["mode"] == "replay" and first["dataset_version"] == "golden-v2" and first["case_count"] == 24
    assert first["metrics"][TENANT_METRIC] == 1.0 and first["tokens"]["total"] is None and first["total_cost_usd"] is None
    assert first["latency"]["kind"] == "harness_replay"
    assert evals_cli.main(["history", "--out", str(tmp_path)]) == 0
    printed = capsys.readouterr().out
    assert "first run" in printed and "none" in printed  # the second run shows no change vs the first


def test_history_is_informational_and_robust(tmp_path, v2_report) -> None:
    assert append_history(v2_report, tmp_path) is not None
    skipped = run_live(api_key="")
    assert append_history(skipped, tmp_path) is None  # a skipped run is not history
    path = tmp_path / "history" / "history.jsonl"
    path.write_text(path.read_text() + "{torn line\n", encoding="utf-8")
    assert len(load_history(tmp_path)) == 1  # a torn line is ignored
    assert format_history([]) == "no evaluation history"
    summary = summarize_run(v2_report)
    assert "prompt" not in json.dumps(summary).lower().replace("prompt_version", "")
    earlier = {"metrics": {"relevance": 0.9, "x": 1.0}}
    assert metric_deltas({"metrics": {"relevance": 0.95, "x": 1.0, "y": None}}, earlier) == {"relevance": 0.05}


def test_history_does_not_influence_pass_fail_or_the_baseline(v2_report) -> None:
    before = file_sha256(BASELINE_PATH)
    summarize_run(v2_report)
    assert file_sha256(BASELINE_PATH) == before and v2_report.passed is True


def test_v3_cli_replay_uses_its_own_baseline(tmp_path) -> None:
    assert evals_cli.main(["replay", "--dataset", "v3", "--out", str(tmp_path)]) == 0
    assert json.loads((tmp_path / "report-replay.json").read_text())["dataset_version"] == "golden-v3"
    assert sys.modules["evals.runner"].DATASETS["v3"][1] == BASELINE_V3_PATH
