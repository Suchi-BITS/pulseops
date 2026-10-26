"""Dataset loading, case execution and metric aggregation (observational only)."""

from __future__ import annotations

import json
import statistics
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.agent.prompts import INVESTIGATION_PROMPT_VERSION
from app.core.config import get_settings
from evals.baseline import compare_to_baseline, load_baseline
from evals.contracts import (
    QUALITY_METRICS,
    SYSTEM_METRICS,
    CaseScore,
    EvalReport,
    GoldenCase,
    MetricAggregate,
    TimingSummary,
)
from evals.hashing import canonical_sha256, file_sha256
from evals.harness import CaseRun, live_all, replay_all
from evals.policy import score_policy_boundary
from evals.retrieval import (
    RETRIEVAL_METRIC,
    aggregate_retrieval,
    retrieval_dataset_sha256,
    run_retrieval_checks,
)
from evals.observability import case_telemetry, summarize_telemetry
from evals.scorers import score_run
from evals.tenant import TENANT_METRIC, aggregate_tenant, run_tenant_checks

DATASET_PATH = Path(__file__).parent / "datasets" / "golden_incidents.json"
BASELINE_PATH = Path(__file__).parent / "baselines" / "baseline.json"
# P8.2: golden-v3 is a separate, additive dataset (golden-v2's 24 cases + new ones) with its own baseline file. The
# golden-v2 dataset and baseline.json are historical artifacts and stay byte-for-byte unchanged.
GOLDEN_V3_PATH = Path(__file__).parent / "datasets" / "golden_incidents_v3.json"
BASELINE_V3_PATH = Path(__file__).parent / "baselines" / "baseline-v3.json"
DATASETS: dict[str, tuple[Path, Path]] = {"v2": (DATASET_PATH, BASELINE_PATH), "v3": (GOLDEN_V3_PATH, BASELINE_V3_PATH)}

REPLAY_BANNER = (
    "REPLAY MODE - AGENT-VALIDATION RESULTS. Scripted SDK messages were run through the real PulseOps agent code. "
    "This does NOT measure real Claude model quality."
)
TIMING_NOTE_REPLAY = (
    "Timings are informational and never gated. In replay mode 'investigation_ms' measures the scripted replay through "
    "the real agent code, not model latency."
)


def load_dataset(path: Path = DATASET_PATH) -> tuple[str, list[GoldenCase]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = [GoldenCase.model_validate(item) for item in raw["cases"]]
    ids = [c.case_id for c in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate case_id in golden dataset")
    return raw["dataset_version"], cases


def aggregate(case_scores: list[CaseScore]) -> tuple[dict[str, MetricAggregate], dict[str, MetricAggregate]]:
    def build(metrics: tuple[str, ...]) -> dict[str, MetricAggregate]:
        out: dict[str, MetricAggregate] = {}
        for metric in metrics:
            applicable = [
                (cs.case_id, s) for cs in case_scores for s in cs.scores if s.metric == metric and s.applicable
            ]
            if not applicable:
                out[metric] = MetricAggregate(metric=metric, applicable_cases=0, mean_score=None, pass_rate=None)
                continue
            scores = [s.score for _, s in applicable if s.score is not None]
            out[metric] = MetricAggregate(
                metric=metric,
                applicable_cases=len(applicable),
                mean_score=round(sum(scores) / len(scores), 4),
                pass_rate=round(sum(1 for _, s in applicable if s.passed) / len(applicable), 4),
                failed_cases=[cid for cid, s in applicable if not s.passed],
            )
        return out

    return build(SYSTEM_METRICS), build(QUALITY_METRICS)


def _score_all(runs: list[CaseRun], mode: str = "replay") -> list[CaseScore]:
    scored: list[CaseScore] = []
    for run in runs:
        started = time.perf_counter()
        policy = score_policy_boundary(run)  # records run.timings["workflow_ms"] when it has probes
        agent_scored = score_run(run, policy)
        total_ms = (time.perf_counter() - started) * 1000
        scoring_ms = max(0.0, total_ms - run.timings.get("workflow_ms", 0.0))
        agent_scored.timings_ms = {
            **{k: round(v, 1) for k, v in run.timings.items()},
            "scoring_ms": round(scoring_ms, 1),
        }
        agent_scored.telemetry = case_telemetry(run.telemetry, mode, agent_scored.timings_ms.get("investigation_ms"))
        scored.append(agent_scored)
    return scored


def summarize_timings(case_scores: list[CaseScore], total_run_ms: float) -> dict[str, TimingSummary]:
    summaries: dict[str, TimingSummary] = {}
    for key in ("investigation_ms", "workflow_ms", "scoring_ms"):
        values = [cs.timings_ms[key] for cs in case_scores if key in cs.timings_ms]
        if values:
            summaries[key] = TimingSummary(
                count=len(values),
                mean_ms=round(statistics.fmean(values), 1),
                p50_ms=round(statistics.median(values), 1),
                max_ms=round(max(values), 1),
            )
    summaries["total_run_ms"] = TimingSummary(
        count=1, mean_ms=round(total_run_ms, 1), p50_ms=round(total_run_ms, 1), max_ms=round(total_run_ms, 1)
    )
    return summaries


def _base_report(mode: str) -> dict[str, Any]:
    return {
        "run_id": uuid.uuid4().hex[:12],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "prompt_version": INVESTIGATION_PROMPT_VERSION,
    }


def run_replay(
    cases: list[GoldenCase] | None = None,
    dataset_version: str | None = None,
    baseline_path: Path | None = BASELINE_PATH,
    dataset_sha256: str | None = None,
    dataset_path: Path = DATASET_PATH,
) -> EvalReport:
    started = time.perf_counter()
    if cases is None:
        dataset_version, cases = load_dataset(dataset_path)
        dataset_sha256 = file_sha256(dataset_path)
    else:
        dataset_version = dataset_version or "custom"
        dataset_sha256 = dataset_sha256 or canonical_sha256(
            {"dataset_version": dataset_version, "cases": [c.model_dump(mode="json") for c in cases]}
        )
    case_scores = _score_all(replay_all(cases), "replay")
    system, quality = aggregate(case_scores)
    checks = run_retrieval_checks()
    system[RETRIEVAL_METRIC] = aggregate_retrieval(checks)
    tenant_checks = run_tenant_checks()  # P8.1: deterministic, system group, must stay 1.00
    system[TENANT_METRIC] = aggregate_tenant(tenant_checks)
    report = EvalReport(
        **_base_report("replay"),
        status="COMPLETED",
        banner=REPLAY_BANNER,
        live_model_quality_measured=False,
        model="scripted (no model)",
        dataset_version=dataset_version,
        dataset_sha256=dataset_sha256,
        retrieval_dataset_sha256=retrieval_dataset_sha256(),
        case_count=len(cases),
        cases=case_scores,
        retrieval_checks=checks,
        tenant_checks=tenant_checks,
        system_correctness_safety=system,
        ai_quality=quality,
        notes=[
            "Replay validates PulseOps' own grounding, validation, tool-boundary and fail-closed logic.",
            "Scripted 'model' output is authored in the dataset; it says nothing about how Claude would answer.",
            TIMING_NOTE_REPLAY,
        ],
        timings=summarize_timings(case_scores, (time.perf_counter() - started) * 1000),
        telemetry=summarize_telemetry(case_scores, "replay", None),
    )
    if baseline_path is not None:
        report.regression = compare_to_baseline(report, load_baseline(baseline_path), str(baseline_path))
        report.passed = not report.regression.failed
    return report


def _live_with_cost_cap(
    cases: list[GoldenCase], model: str | None, agent_factory: Callable[..., Any] | None, cap: float
) -> tuple[list[CaseRun], str]:
    """Run live cases one at a time and stop before the next one once the SDK-reported cost reaches the cap.

    Cost is only what the SDK reports; nothing is estimated. If a case reports no cost, the cap cannot be enforced, so
    the run stops after that case rather than continue unmetered.
    """
    runs: list[CaseRun] = []
    spent = 0.0
    for case in cases:
        run = live_all([case], model=model, agent_factory=agent_factory)[0]
        runs.append(run)
        cost = getattr(run.telemetry, "total_cost_usd", None)
        if not isinstance(cost, (int, float)) or isinstance(cost, bool):
            return runs, f"stopped after {len(runs)} case(s): the SDK reported no cost, so the cap cannot be enforced."
        spent += float(cost)
        if spent >= cap and len(runs) < len(cases):
            return runs, f"stopped after {len(runs)} of {len(cases)} case(s): reported cost {spent:.6f} reached the cap."
    return runs, f"all {len(runs)} case(s) ran; reported cost {spent:.6f}."


def run_live(
    *,
    model: str | None = None,
    limit: int | None = None,
    agent_factory: Callable[..., Any] | None = None,
    api_key: str | None = None,
    max_cost_usd: float | None = None,
) -> EvalReport:
    """Optional live evaluation. SKIPPED (not FAILED) without an API key. Never gates CI or production."""
    started = time.perf_counter()
    dataset_version, cases = load_dataset()
    key = api_key if api_key is not None else get_settings().anthropic_api_key
    base = _base_report("live")
    if not key and agent_factory is None:
        return EvalReport(
            **base,
            status="SKIPPED",
            banner="LIVE EVALUATION SKIPPED - no ANTHROPIC_API_KEY is available. Live model quality was NOT measured.",
            live_model_quality_measured=False,
            model=model,
            dataset_version=dataset_version,
            case_count=0,
            skipped_reason="ANTHROPIC_API_KEY not set",
            passed=True,
        )
    eligible = [c for c in cases if c.live_eligible]
    selected = eligible[:limit] if limit is not None else eligible
    notes = [
        f"{len(cases) - len(eligible)} case(s) are not live-eligible because their failure mode is scripted "
        "(tool timeout, malformed output, SDK/model timeout, truncated or injected tool results) and cannot be "
        "reproduced over a real database.",
        "Live cases run over their own temporary database; the Phase 6 MCP subprocess receives that database via "
        "PULSEOPS_DATABASE_URL. The grounding corpus is fetched independently from the same real retrieval tools.",
        "Live results are non-deterministic and are never compared with the baseline or used to gate anything.",
        "Timings are informational and never gated; live 'investigation_ms' includes real model latency.",
    ]
    if max_cost_usd is None:
        runs = live_all(selected, model=model, agent_factory=agent_factory)
    else:
        runs, stop_note = _live_with_cost_cap(selected, model, agent_factory, max_cost_usd)
        notes.append(f"Cost cap {max_cost_usd} USD (SDK-reported cost only): " + stop_note)
        selected = selected[: len(runs)]
    case_scores = _score_all(runs, "live")
    system, quality = aggregate(case_scores)
    return EvalReport(
        **base,
        status="COMPLETED",
        banner=(
            f"LIVE MODE - real Claude model ({model or 'default configured model'}) was run on "
            f"{len(selected)} eligible case(s). Results are non-deterministic."
        ),
        live_model_quality_measured=bool(selected),
        model=model or get_settings().claude_model,
        dataset_version=dataset_version,
        dataset_sha256=file_sha256(DATASET_PATH),
        case_count=len(selected),
        cases=case_scores,
        system_correctness_safety=system,
        ai_quality=quality,
        notes=notes,
        timings=summarize_timings(case_scores, (time.perf_counter() - started) * 1000),
        telemetry=summarize_telemetry(case_scores, "live", model or get_settings().claude_model),
        passed=True,
    )
