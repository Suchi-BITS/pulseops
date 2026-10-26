"""P8.0 - evaluation observability: latency, token and cost reporting (informational only)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.service import InvestigationResult
from evals.baseline import compare_to_baseline, load_baseline
from evals.contracts import CaseScore, CaseTelemetry, EvalReport
from evals.observability import (
    LIVE_LATENCY_KIND,
    REPLAY_LATENCY_KIND,
    case_telemetry,
    summarize_telemetry,
)
from evals.hashing import file_sha256
from evals.report import to_json, to_markdown
from evals.runner import BASELINE_PATH, DATASET_PATH, load_dataset, run_live, run_replay, summarize_timings

REPO = Path(__file__).resolve().parents[1]


def _case(case_id: str, telemetry: CaseTelemetry | None, investigation_ms: float | None = None) -> CaseScore:
    timings = {"investigation_ms": investigation_ms} if investigation_ms is not None else {}
    return CaseScore(case_id=case_id, category="x", outcome="result", scores=[], timings_ms=timings, telemetry=telemetry)


def _live(model="m", **kw) -> CaseTelemetry:
    return CaseTelemetry(latency_kind=LIVE_LATENCY_KIND, model=model, telemetry_available=True, **kw)


# =========================================================================== aggregation


def test_token_aggregation_sums_only_what_was_reported() -> None:
    cases = [
        _case("a", _live(input_tokens=100, output_tokens=40)),
        _case("b", _live(input_tokens=50, output_tokens=None)),  # partial: only input reported
        _case("c", CaseTelemetry(latency_kind=LIVE_LATENCY_KIND)),  # no telemetry at all
    ]
    totals = summarize_telemetry(cases, "live", "m")
    assert (totals.input_tokens, totals.output_tokens, totals.total_tokens) == (150, 40, 190)
    assert totals.cases == 3 and totals.cases_with_tokens == 2 and totals.cases_with_telemetry == 2


def test_cost_aggregation_is_the_sum_of_reported_costs_and_unknown_when_none() -> None:
    totals = summarize_telemetry([_case("a", _live(total_cost_usd=0.0123)), _case("b", _live(total_cost_usd=0.02)),
                                  _case("c", _live())], "live", "m")
    assert totals.total_cost_usd == pytest.approx(0.0323) and totals.cases_with_cost == 2
    none = summarize_telemetry([_case("a", _live()), _case("b", _live())], "live", "m")
    assert none.total_cost_usd is None and none.cases_with_cost == 0  # unknown, not 0.0


def test_latency_aggregation_is_unchanged_and_the_report_carries_it() -> None:
    cases = [_case("a", None, 10.0), _case("b", None, 20.0), _case("c", None, 60.0)]
    summary = summarize_timings(cases, 500.0)["investigation_ms"]
    assert (summary.count, summary.mean_ms, summary.p50_ms, summary.max_ms) == (3, 30.0, 20.0, 60.0)
    per_case = case_telemetry(None, "replay", 12.5)
    assert per_case.investigation_ms == 12.5 and per_case.latency_kind == REPLAY_LATENCY_KIND


# =========================================================================== no fabrication


def test_missing_telemetry_yields_nulls_not_invented_values() -> None:
    t = case_telemetry(None, "live", 7.0)
    assert t.telemetry_available is False
    assert (t.model, t.input_tokens, t.output_tokens, t.total_tokens, t.total_cost_usd, t.usage) == (None,) * 6
    assert t.investigation_ms == 7.0  # the harness' own wall clock is real and kept
    empty = summarize_telemetry([_case("a", t)], "live", "m")
    assert (empty.input_tokens, empty.output_tokens, empty.total_tokens, empty.total_cost_usd) == (None,) * 4


def test_non_numeric_or_boolean_sdk_values_are_ignored() -> None:
    telemetry = SimpleNamespace(model="m", duration_ms=5, api_duration_ms="fast", total_cost_usd=True,
                                usage={"input_tokens": True, "output_tokens": "9"})
    t = case_telemetry(telemetry, "live", 1.0)
    assert t.input_tokens is None and t.output_tokens is None and t.total_cost_usd is None and t.api_duration_ms is None
    assert t.agent_duration_ms == 5 and t.model == "m"


def test_total_tokens_needs_both_directions() -> None:
    assert case_telemetry(SimpleNamespace(model="m", usage={"input_tokens": 3}), "live", None).total_tokens is None
    full = case_telemetry(SimpleNamespace(model="m", usage={"input_tokens": 3, "output_tokens": 4}), "live", None)
    assert full.total_tokens == 7


# =========================================================================== replay identity


def test_replay_never_reports_tokens_cost_or_a_model_even_if_the_script_carried_them() -> None:
    carried = SimpleNamespace(model="claude-x", duration_ms=9, total_cost_usd=1.0, usage={"input_tokens": 5, "output_tokens": 5})
    t = case_telemetry(carried, "replay", 3.0)
    assert (t.model, t.input_tokens, t.total_cost_usd, t.usage) == (None,) * 4
    assert t.latency_kind == REPLAY_LATENCY_KIND and t.telemetry_available is False


@pytest.fixture(scope="module")
def replay_report() -> EvalReport:
    return run_replay()


def test_replay_report_identifies_itself_and_denies_model_quality(replay_report: EvalReport) -> None:
    r = replay_report
    assert r.mode == "replay" and r.live_model_quality_measured is False
    assert "does NOT measure real Claude model quality" in r.banner
    t = r.telemetry
    assert t is not None and t.mode == "replay" and t.latency_kind == REPLAY_LATENCY_KIND
    assert "does NOT measure Claude/model quality" in t.note and "not model inference latency" in t.note
    assert (t.model, t.input_tokens, t.output_tokens, t.total_tokens, t.total_cost_usd) == (None,) * 5
    assert t.cases == r.case_count == 24
    assert all(c.telemetry is not None and c.telemetry.investigation_ms is not None for c in r.cases)
    markdown = to_markdown(r)
    assert "## Observability (informational, never gated)" in markdown
    assert "NOT model inference latency" in markdown and "none (scripted replay)" in markdown
    assert json.loads(to_json(r))["telemetry"]["latency_kind"] == "harness_replay"


def test_replay_scoring_and_baseline_comparison_are_unchanged(replay_report: EvalReport) -> None:
    assert replay_report.passed is True and replay_report.regression.compared is True
    assert replay_report.regression.regressions == []
    assert all(a.pass_rate == 1.0 for a in replay_report.system_correctness_safety.values())
    # the observability data cannot influence the comparison: it is not a metric and not part of the baseline
    baseline = load_baseline(BASELINE_PATH)
    assert "telemetry" not in json.dumps(baseline)
    mutated = replay_report.model_copy(update={"telemetry": None, "timings": {}})
    assert compare_to_baseline(mutated, baseline).failed is False


def test_dataset_and_baseline_files_are_the_p7_p8_artifacts() -> None:
    # pinned by content hash in the baseline itself; P8.0 must not have rewritten either file
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    assert baseline["baseline_version"] == 2 and baseline["dataset_version"] == "golden-v2"
    assert load_dataset()[0] == "golden-v2" and len(load_dataset()[1]) == 24
    assert file_sha256(DATASET_PATH) == baseline["dataset_sha256"]  # the dataset content is exactly what was baselined


# =========================================================================== live contract


class _FakeAgent:
    usage: dict | None = {"input_tokens": 120, "output_tokens": 30}
    cost: float | None = 0.05
    telemetry_present = True

    def __init__(self, database_url=None, model=None) -> None:
        self.last_telemetry = None

    async def investigate(self, incident_id, objective=None, identity_context=None):
        if _FakeAgent.telemetry_present:
            self.last_telemetry = SimpleNamespace(
                model="claude-test", grounded=True, duration_ms=250, api_duration_ms=200,
                total_cost_usd=_FakeAgent.cost, usage=_FakeAgent.usage, unauthorized_tool_attempts=[], tool_calls=[],
            )
        return InvestigationResult(incident_id=incident_id, summary="s", confidence=0.5)


def test_live_report_accepts_available_telemetry_and_totals_it() -> None:
    _FakeAgent.telemetry_present, _FakeAgent.usage, _FakeAgent.cost = True, {"input_tokens": 120, "output_tokens": 30}, 0.05
    report = run_live(model="claude-test", limit=2, agent_factory=_FakeAgent, api_key="unused")
    assert report.mode == "live" and report.status == "COMPLETED" and report.case_count == 2
    t = report.telemetry
    assert t.mode == "live" and t.latency_kind == LIVE_LATENCY_KIND and t.model == "claude-test"
    assert (t.input_tokens, t.output_tokens, t.total_tokens) == (240, 60, 300)
    assert t.total_cost_usd == pytest.approx(0.10) and t.cases_with_cost == 2 and t.models_observed == ["claude-test"]
    first = report.cases[0].telemetry
    assert (first.input_tokens, first.output_tokens, first.total_tokens, first.total_cost_usd) == (120, 30, 150, 0.05)
    assert (first.agent_duration_ms, first.api_duration_ms) == (250, 200) and first.investigation_ms is not None
    assert report.passed is True and report.regression is None  # live is never compared or gated
    assert "claude-test" in to_markdown(report) and "0.05" in to_markdown(report)


def test_live_report_without_telemetry_completes_with_unknowns() -> None:
    _FakeAgent.telemetry_present = True
    _FakeAgent.usage, _FakeAgent.cost = None, None  # the SDK exposed no usage and no cost
    report = run_live(model="claude-test", limit=1, agent_factory=_FakeAgent, api_key="unused")
    t = report.telemetry
    assert report.status == "COMPLETED" and report.passed is True
    assert t.cases_with_telemetry == 1 and t.cases_with_tokens == 0 and t.cases_with_cost == 0
    assert (t.input_tokens, t.output_tokens, t.total_tokens, t.total_cost_usd) == (None,) * 4
    assert "| n/a | n/a |" in to_markdown(report)  # unknowns are printed as n/a, never 0
    _FakeAgent.telemetry_present = False  # no telemetry object at all
    bare = run_live(model="claude-test", limit=1, agent_factory=_FakeAgent, api_key="unused")
    assert bare.status == "COMPLETED" and bare.telemetry.cases_with_telemetry == 0
    assert bare.cases[0].telemetry.telemetry_available is False and bare.cases[0].telemetry.input_tokens is None
    _FakeAgent.telemetry_present, _FakeAgent.usage, _FakeAgent.cost = True, {"input_tokens": 120, "output_tokens": 30}, 0.05


def test_skipped_live_has_no_telemetry_and_ci_needs_no_live_run() -> None:
    skipped = run_live(api_key="")
    assert skipped.status == "SKIPPED" and skipped.telemetry is None and skipped.passed is True
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    commands = [ln.strip() for ln in ci.splitlines() if ln.strip().startswith("run:")]
    assert commands and not any("evals live" in c for c in commands)  # a comment may mention it; no step may run it
    assert "secrets." not in ci and "env:" not in ci


def test_telemetry_fields_are_never_part_of_the_gate() -> None:
    from evals.contracts import QUALITY_METRICS, SYSTEM_METRICS

    assert not any("cost" in m or "token" in m or "latency" in m for m in (*SYSTEM_METRICS, *QUALITY_METRICS))
