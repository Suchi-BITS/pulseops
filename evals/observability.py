"""P8.0 evaluation observability: per-case and run-level latency, token and cost reporting.

Informational only. Nothing here affects scoring, the baseline, regression detection or any gate.

* Telemetry is read from the existing ``agent.last_telemetry`` (``InvestigationTelemetry``); there is no second
  telemetry system. A value the SDK did not provide stays ``None`` (unknown). Nothing is estimated, no pricing is
  hard-coded, and totals are ``None`` when no case reported the quantity.
* Replay never reports tokens, cost or a model: its "model" is a script, and its latency is harness latency.
  Telemetry the scripted messages might carry is deliberately not copied, so replay output stays deterministic and
  cannot be mistaken for model usage.
"""

from __future__ import annotations

from typing import Any

from evals.contracts import CaseScore, CaseTelemetry, TelemetryTotals

REPLAY_LATENCY_KIND = "harness_replay"  # scripted replay through the real agent code; NOT model inference latency
LIVE_LATENCY_KIND = "live_model_inclusive"  # includes real model and tool latency

REPLAY_OBSERVABILITY_NOTE = (
    "Replay does NOT measure Claude/model quality. Latency is harness/replay latency, not model inference latency. "
    "Tokens, cost and model are not reported in replay (the model is a script)."
)
LIVE_OBSERVABILITY_NOTE = (
    "Informational only: latency, tokens and cost never affect pass/fail or the baseline. Fields the SDK did not "
    "provide are null (unknown), never estimated."
)


def _int_or_none(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _float_or_none(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def case_telemetry(telemetry: Any, mode: str, investigation_ms: float | None) -> CaseTelemetry:
    """Map the agent's existing telemetry onto the report contract (live), or the harness latency only (replay)."""
    if mode != "live":
        return CaseTelemetry(
            latency_kind=REPLAY_LATENCY_KIND, investigation_ms=investigation_ms, telemetry_available=False
        )
    if telemetry is None:
        return CaseTelemetry(latency_kind=LIVE_LATENCY_KIND, investigation_ms=investigation_ms, telemetry_available=False)
    usage = getattr(telemetry, "usage", None)
    usage = usage if isinstance(usage, dict) else None
    input_tokens = _int_or_none(usage.get("input_tokens")) if usage else None
    output_tokens = _int_or_none(usage.get("output_tokens")) if usage else None
    cost = _float_or_none(getattr(telemetry, "total_cost_usd", None))
    return CaseTelemetry(
        latency_kind=LIVE_LATENCY_KIND,
        model=getattr(telemetry, "model", None),
        investigation_ms=investigation_ms,
        agent_duration_ms=_int_or_none(getattr(telemetry, "duration_ms", None)),
        api_duration_ms=_int_or_none(getattr(telemetry, "api_duration_ms", None)),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens if input_tokens is not None and output_tokens is not None else None,
        usage=usage,
        total_cost_usd=cost,
        telemetry_available=True,
    )


def _sum_or_none(values: list[int | float]) -> int | float | None:
    return sum(values) if values else None


def summarize_telemetry(case_scores: list[CaseScore], mode: str, model: str | None) -> TelemetryTotals:
    """Run-level totals. A total is ``None`` when no case reported that quantity (unknown, not zero)."""
    cases = [cs.telemetry for cs in case_scores if cs.telemetry is not None]
    inputs = [c.input_tokens for c in cases if c.input_tokens is not None]
    outputs = [c.output_tokens for c in cases if c.output_tokens is not None]
    costs = [c.total_cost_usd for c in cases if c.total_cost_usd is not None]
    models = sorted({c.model for c in cases if c.model})
    return TelemetryTotals(
        mode=mode,
        latency_kind=REPLAY_LATENCY_KIND if mode != "live" else LIVE_LATENCY_KIND,
        model=model if mode == "live" else None,
        models_observed=models,
        cases=len(case_scores),
        cases_with_telemetry=sum(1 for c in cases if c.telemetry_available),
        cases_with_tokens=sum(1 for c in cases if c.input_tokens is not None or c.output_tokens is not None),
        cases_with_cost=len(costs),
        input_tokens=_sum_or_none(inputs),
        output_tokens=_sum_or_none(outputs),
        total_tokens=_sum_or_none(inputs + outputs),
        total_cost_usd=round(sum(costs), 6) if costs else None,
        note=REPLAY_OBSERVABILITY_NOTE if mode != "live" else LIVE_OBSERVABILITY_NOTE,
    )
