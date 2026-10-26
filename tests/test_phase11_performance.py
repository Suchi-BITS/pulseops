"""P11 performance smoke tests: the measurement harness works and its regression detection really detects regressions.

This is NOT a benchmark. It checks that scripts/perf_smoke.py measures every endpoint without errors, writes its JSON, and
that a slowdown or a failing request would be reported. The full run against the stored baseline is a quality-gate step.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.performance
ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "perf_smoke.py"
BASELINE = ROOT / "scripts" / "perf_baseline.json"
ENDPOINTS = {
    "health", "incident_list", "incident_detail", "investigations", "workflow_list", "retrieval_incident",
    "retrieval_service_incidents", "retrieval_service_dependencies", "policy_evaluation_api",
}


@pytest.fixture(scope="module")
def perf():
    spec = importlib.util.spec_from_file_location("perf_smoke_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stats(p95, errors=0):
    return {"requests": 10, "errors": errors, "p50_ms": p95 / 2, "p95_ms": p95, "max_ms": p95}


def _results(p95_seq, p95_conc=None, errors=0):
    return {"x": {"sequential": _stats(p95_seq, errors), "concurrent": _stats(p95_conc if p95_conc is not None else p95_seq)}}


def test_percentile_and_summary(perf) -> None:
    values = [float(i) for i in range(1, 101)]
    assert perf.percentile(values, 50) == 50.0 and perf.percentile(values, 95) == 95.0 and perf.percentile(values, 100) == 100.0
    assert perf.percentile([7.0], 95) == 7.0
    summary = perf.summarize(values, errors=2)
    assert summary["requests"] == 102 and summary["errors"] == 2 and summary["p95_ms"] == 95.0
    assert perf.summarize([], errors=3)["p95_ms"] is None


def test_a_slowdown_beyond_the_factor_is_reported(perf) -> None:
    baseline = {"mode": "full", "endpoints": {"x": {"sequential": 100.0, "concurrent": 200.0}}}
    assert perf.compare(_results(290.0, 590.0), baseline, "full") == []  # within 3x
    problems = perf.compare(_results(301.0, 200.0), baseline, "full")
    assert len(problems) == 1 and "x/sequential" in problems[0] and "301.0" in problems[0]
    both = perf.compare(_results(400.0, 700.0), baseline, "full")
    assert len(both) == 2


def test_the_floor_prevents_a_hair_trigger_on_tiny_baselines(perf) -> None:
    baseline = {"mode": "full", "endpoints": {"x": {"sequential": 1.0, "concurrent": 1.0}}}
    assert perf.compare(_results(40.0), baseline, "full") == []  # 3 x 1 ms would be 3 ms; the 50 ms floor applies
    assert perf.compare(_results(60.0), baseline, "full") != []


def test_failed_requests_and_the_pathological_ceiling_are_reported(perf) -> None:
    assert any("failed request" in p for p in perf.compare(_results(10.0, errors=2), None, "full"))
    assert any("pathological" in p for p in perf.compare(_results(perf.PATHOLOGICAL_MS + 1), None, "full"))
    # concurrent clients share one interpreter: their absolute latency alone is not a failure
    assert perf.compare(_results(10.0, p95_conc=perf.PATHOLOGICAL_MS * 3), None, "full") == []
    empty = {"x": {"sequential": perf.summarize([], 5), "concurrent": _stats(10.0)}}
    assert any("no successful request" in p for p in perf.compare(empty, None, "full"))


def test_a_baseline_from_a_different_profile_is_refused(perf) -> None:
    problems = perf.compare(_results(10.0), {"mode": "quick", "endpoints": {}}, "full")
    assert len(problems) == 1 and "mode" in problems[0]


def test_the_stored_baseline_is_complete_and_sane() -> None:
    baseline = json.loads(BASELINE.read_text("utf-8"))
    assert baseline["mode"] == "full" and "never a performance claim" in baseline["note"]
    assert set(baseline["endpoints"]) == ENDPOINTS
    for name, modes in baseline["endpoints"].items():
        assert set(modes) == {"sequential", "concurrent"}
        assert all(isinstance(v, (int, float)) and 0 < v < 60_000 for v in modes.values()), name
    assert baseline["profile"]["sequential_requests"] >= 10


def test_quick_run_measures_every_endpoint_without_errors_and_writes_json(tmp_path) -> None:
    out = tmp_path / "perf.json"
    completed = subprocess.run([sys.executable, str(SCRIPT), "--quick", "--no-compare", "--out", str(out)],
                               capture_output=True, text=True, cwd=ROOT, timeout=600)
    assert completed.returncode == 0, completed.stdout[-1500:] + completed.stderr[-1500:]
    report = json.loads(out.read_text("utf-8"))
    assert set(report["endpoints"]) == ENDPOINTS and report["mode"] == "quick"
    for name, modes in report["endpoints"].items():
        for mode, stats in modes.items():
            assert stats["errors"] == 0 and stats["requests"] > 0, (name, mode, stats)
            assert 0 < stats["p50_ms"] <= stats["p95_ms"] <= stats["max_ms"], (name, mode, stats)
    assert report["policy_engine_in_process"]["iterations"] > 0 and report["policy_engine_in_process"]["p95_ms"] is not None
    assert set(report["thresholds"]) == {"factor", "floor_ms", "pathological_ms"}
    assert "no capacity or production claim" in " ".join(report["notes"]).lower()
    assert "p95" in completed.stdout and "PERF SMOKE: PASS" in completed.stdout
