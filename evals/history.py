"""P8.5 - run history. Informational only: an append-only JSON-lines summary of completed evaluation runs.

``<out>/history/history.jsonl`` gets one compact line per completed run (replay or live) so scores, latency, tokens
and cost can be compared across runs. It never affects pass/fail, the baseline or any gate, never contains prompts,
tool output or credentials, and stores the same "unknown stays null" telemetry as the report. Durable, shared history
(storage, dashboards, retention) is a later platform concern; here it is a local file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals.contracts import EvalReport

HISTORY_DIR = "history"
HISTORY_FILE = "history.jsonl"


def summarize_run(report: EvalReport) -> dict[str, Any]:
    metrics = {name: agg.mean_score for name, agg in {**report.system_correctness_safety, **report.ai_quality}.items()}
    inv = report.timings.get("investigation_ms")
    totals = report.telemetry
    return {
        "run_id": report.run_id,
        "timestamp": report.timestamp,
        "mode": report.mode,
        "status": report.status,
        "passed": report.passed,
        "model": report.model,
        "prompt_version": report.prompt_version,
        "dataset_version": report.dataset_version,
        "dataset_sha256": report.dataset_sha256,
        "case_count": report.case_count,
        "regressions": len(report.regression.regressions) if report.regression else None,
        "metrics": metrics,  # mean score per metric; null = not applicable / not measured
        "latency": {"kind": totals.latency_kind if totals else None,
                    "investigation_mean_ms": inv.mean_ms if inv else None,
                    "investigation_p50_ms": inv.p50_ms if inv else None},
        "tokens": {"input": totals.input_tokens, "output": totals.output_tokens, "total": totals.total_tokens} if totals else None,
        "total_cost_usd": totals.total_cost_usd if totals else None,
    }


def append_history(report: EvalReport, out_dir: Path) -> Path | None:
    """Append a summary line for a COMPLETED run; skipped runs are not history. Returns the file written."""
    if report.status != "COMPLETED":
        return None
    path = Path(out_dir) / HISTORY_DIR / HISTORY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(summarize_run(report), sort_keys=True) + "\n")
    return path


def load_history(out_dir: Path) -> list[dict[str, Any]]:
    path = Path(out_dir) / HISTORY_DIR / HISTORY_FILE
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a torn line never breaks reading the rest
    return entries


def metric_deltas(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, float]:
    """current - previous for metrics measured in both runs (informational trend, not a gate)."""
    out: dict[str, float] = {}
    for name, value in current.get("metrics", {}).items():
        before = previous.get("metrics", {}).get(name)
        if value is not None and before is not None and round(value - before, 4) != 0:
            out[name] = round(value - before, 4)
    return out


def format_history(entries: list[dict[str, Any]], mode: str | None = None, last: int = 10) -> str:
    rows = [e for e in entries if mode is None or e.get("mode") == mode][-last:]
    if not rows:
        return "no evaluation history"
    lines = ["| Timestamp | Mode | Dataset | Cases | Passed | Model | Mean ms | Tokens | Cost USD | Change vs previous |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    previous: dict[tuple[str, str], dict[str, Any]] = {}
    for e in entries:
        if e not in rows:
            previous[(e.get("mode"), e.get("dataset_version"))] = e
            continue
        key = (e.get("mode"), e.get("dataset_version"))
        deltas = metric_deltas(e, previous[key]) if key in previous else None
        change = "first run" if deltas is None else (", ".join(f"{k} {v:+}" for k, v in deltas.items()) or "none")
        tokens = (e.get("tokens") or {}).get("total")
        lines.append(
            f"| {e['timestamp'][:19]} | {e['mode']} | {e['dataset_version']} | {e['case_count']} | {e['passed']} | "
            f"{e.get('model') or 'n/a'} | {(e.get('latency') or {}).get('investigation_mean_ms', 'n/a')} | "
            f"{'n/a' if tokens is None else tokens} | {'n/a' if e.get('total_cost_usd') is None else e['total_cost_usd']} | {change} |"
        )
        previous[key] = e
    return "\n".join(lines)
