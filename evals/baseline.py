"""Explicit, versioned baseline for replay regression. The baseline is never regenerated implicitly."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.contracts import EvalReport, RegressionFinding, RegressionResult

DEFAULT_TOLERANCES = {"system": 0.0, "quality": 0.05}
SYSTEM_FLOOR = 1.0  # a system correctness/safety metric below this fails regardless of the baseline


def load_baseline(path: Path) -> dict[str, Any] | None:
    path = Path(path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def compare_to_baseline(report: EvalReport, baseline: dict[str, Any] | None, path: str | None = None) -> RegressionResult:
    if baseline is None:
        return RegressionResult(
            baseline_path=path, compared=False,
            regressions=[RegressionFinding(metric="baseline", baseline=0.0, current=None, tolerance=0.0,
                                           message="baseline file is missing; create it explicitly with `python -m evals baseline`")],
            notes=["no baseline"],
        )
    tolerances = {**DEFAULT_TOLERANCES, **baseline.get("tolerances", {})}
    result = RegressionResult(baseline_version=baseline.get("baseline_version"), baseline_path=path, compared=True)
    if baseline.get("dataset_version") != report.dataset_version:
        result.regressions.append(RegressionFinding(
            metric="dataset_version", baseline=0.0, current=None, tolerance=0.0,
            message=f"dataset {report.dataset_version} differs from baseline dataset {baseline.get('dataset_version')}; "
                    "update the baseline explicitly",
        ))
    for key, label in (("dataset_sha256", "golden dataset"), ("retrieval_dataset_sha256", "retrieval ground truth")):
        recorded, actual = baseline.get(key), getattr(report, key, None)
        if recorded is None:
            result.regressions.append(RegressionFinding(
                metric=key, baseline=0.0, current=None, tolerance=0.0,
                message=f"baseline has no {key}; rewrite it explicitly with `python -m evals baseline`"))
        elif actual != recorded:
            result.regressions.append(RegressionFinding(
                metric=key, baseline=0.0, current=None, tolerance=0.0,
                message=f"{label} content changed (sha256 {str(actual)[:12]} != baseline {recorded[:12]}) even though "
                        f"the label is '{report.dataset_version}'; review it and update the baseline explicitly"))
    current: dict[str, tuple[str, Any]] = {
        **{m: ("system", a) for m, a in report.system_correctness_safety.items()},
        **{m: ("quality", a) for m, a in report.ai_quality.items()},
    }
    for metric, entry in baseline.get("metrics", {}).items():
        group, agg = current.get(metric, ("quality", None))
        base_score = entry["mean_score"]
        cur = agg.mean_score if agg is not None else None
        tol = tolerances[group]
        if base_score is None:
            continue
        if cur is None:
            result.regressions.append(RegressionFinding(
                metric=metric, baseline=base_score, current=None, tolerance=tol,
                message=f"{metric} is no longer measured (no applicable cases)"))
        elif cur < base_score - tol - 1e-9:
            result.regressions.append(RegressionFinding(
                metric=metric, baseline=base_score, current=cur, tolerance=tol,
                message=f"{metric} regressed from {base_score} to {cur} (tolerance {tol})"))
        elif agg is not None and agg.applicable_cases < entry.get("applicable_cases", 0):
            result.regressions.append(RegressionFinding(
                metric=metric, baseline=base_score, current=cur, tolerance=tol,
                message=f"{metric} coverage dropped from {entry['applicable_cases']} to {agg.applicable_cases} cases"))
    for metric, (group, agg) in current.items():
        if group == "system" and agg.mean_score is not None and agg.mean_score < SYSTEM_FLOOR:
            result.regressions.append(RegressionFinding(
                metric=metric, baseline=SYSTEM_FLOOR, current=agg.mean_score, tolerance=0.0,
                message=f"system metric {metric} is below the required {SYSTEM_FLOOR} (failed cases: {agg.failed_cases})"))
    return result


def build_baseline(report: EvalReport, *, version: int, reason: str) -> dict[str, Any]:
    metrics = {
        name: {"mean_score": agg.mean_score, "applicable_cases": agg.applicable_cases}
        for name, agg in {**report.system_correctness_safety, **report.ai_quality}.items()
        if agg.mean_score is not None
    }
    return {
        "baseline_version": version,
        "dataset_version": report.dataset_version,
        "dataset_sha256": report.dataset_sha256,
        "retrieval_dataset_sha256": report.retrieval_dataset_sha256,
        "mode": "replay",
        "prompt_version": report.prompt_version,
        "created": datetime.now(timezone.utc).date().isoformat(),
        "reason": reason,
        "tolerances": dict(DEFAULT_TOLERANCES),
        "note": "Replay (agent-validation) baseline. Not a Claude model-quality baseline. Latency is informational and excluded. Change only via `python -m evals baseline`.",
        "metrics": metrics,
    }


def write_baseline(report: EvalReport, path: Path, *, reason: str, confirm_overwrite: bool = False) -> dict[str, Any]:
    path = Path(path)
    existing = load_baseline(path)
    if existing is not None and not confirm_overwrite:
        raise FileExistsError(f"{path} exists (version {existing.get('baseline_version')}); pass --confirm-overwrite")
    if not reason.strip():
        raise ValueError("a non-empty --reason is required to write a baseline")
    version = (existing or {}).get("baseline_version", 0) + 1
    baseline = build_baseline(report, version=version, reason=reason.strip())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
    return baseline
