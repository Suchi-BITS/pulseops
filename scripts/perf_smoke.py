"""PulseOps local performance SMOKE test (P11). A regression detector, not a benchmark.

    python scripts/perf_smoke.py                 # measure, compare with scripts/perf_baseline.json, exit 1 on regression
    python scripts/perf_smoke.py --quick         # fewer requests (used by the test suite)
    python scripts/perf_smoke.py --write-baseline  # deliberately record this machine's numbers as the new baseline

What it does: starts the real application in-process against a temporary database (development identity, synthetic demo
data plus a few dozen extra incidents/workflows/investigations), then times each endpoint with sequential requests and
with a small number of concurrent clients. It records request count, errors, p50 and p95 and writes JSON.

What it does NOT do: it makes no capacity, scalability or production claim. The numbers describe one machine running
an in-process TestClient against SQLite and are only meaningful relative to the baseline recorded on comparable hardware.

Regression rule (deliberately generous, to avoid noise): an endpoint fails when p95 > max(FACTOR x baseline p95, FLOOR_MS),
or a SEQUENTIAL p95 > PATHOLOGICAL_MS (an absolute ceiling that only catches something badly wrong), or any request errored.
Concurrent clients share one interpreter in this in-process harness, so they are compared with the baseline only.
FACTOR defaults to 3 (override with PULSEOPS_PERF_FACTOR on a slower runner).

It also reports, without changing anything, how long constructing a repository/service takes (every construction re-runs
the idempotent schema statements) relative to the incident-list p50, because that is the likely dominant cost.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import statistics
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = ROOT / "scripts" / "perf_baseline.json"
DEFAULT_OUT = ROOT / "perf-results" / "latest.json"
FACTOR = float(os.getenv("PULSEOPS_PERF_FACTOR", "3"))
FLOOR_MS = 50.0  # a tiny baseline must not produce a hair-trigger threshold
PATHOLOGICAL_MS = 5000.0
CONSTRUCTION_DOMINANCE = 0.30  # reported (not acted on) when construction exceeds this share of the list p50


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(pct / 100 * len(ordered)) - 1))]


def summarize(samples: list[float], errors: int) -> dict:
    return {"requests": len(samples) + errors, "errors": errors, "p50_ms": round(statistics.median(samples), 2) if samples else None,
            "p95_ms": round(percentile(samples, 95), 2) if samples else None, "max_ms": round(max(samples), 2) if samples else None}


def build_environment(workdir: Path, extra_incidents: int, workflows: int):
    """Return (app, ids). Environment must be configured BEFORE the application is imported."""
    os.environ.update({"PULSEOPS_ENVIRONMENT": "development", "PULSEOPS_AUTH_MODE": "dev", "PULSEOPS_SEED_DEMO_DATA": "true",
                       "PULSEOPS_DATABASE_URL": "sqlite:" + (workdir / "perf.db").as_posix()})
    os.environ.pop("PULSEOPS_API_CREDENTIALS", None)
    os.environ.pop("ANTHROPIC_API_KEY", None)
    sys.path.insert(0, str(ROOT))
    from app.core.config import DEV_TENANT_ID, get_settings
    from app.services.incident_service import IncidentService
    from app.services.workflow_service import WorkflowService

    url = get_settings().database_url
    incidents = IncidentService(database_url=url, tenant_id=DEV_TENANT_ID)
    workflow_service = WorkflowService(database_url=url, tenant_id=DEV_TENANT_ID)
    created = [incidents.create_incident("svc-payment", "high" if i % 3 else "low", f"Perf incident {i}", "synthetic", "production")
               for i in range(extra_incidents)]
    investigated = None
    for index in range(workflows):
        incident = created[index % len(created)]

        def investigate(incident_id=incident.incident_id):
            return {"status": "completed", "failure_reason": None, "result": {
                "incident_id": incident_id, "service_id": "svc-payment", "summary": "perf summary", "evidence": ["e1", "e2"],
                "hypotheses": ["h1"], "missing_information": ["m1"], "recommendations": ["r1"], "confidence": 0.5, "tool_calls": []}}

        workflow_service.evaluate_incident_action(incident.incident_id, "restart_service" if index % 2 else "notify", "perf-runner",
                                                  details={"i": index}, severity="high", idempotency_key=f"perf-{index}",
                                                  investigate=investigate, actor_type="service")
        investigated = investigated or incident.incident_id
    from app.main import app

    return app, {"incident": investigated or "INC-1007", "service": "svc-payment", "tenant": DEV_TENANT_ID, "url": url}


def measure(app, ids: dict, sequential: int, concurrent_clients: int, concurrent_each: int) -> dict:
    from fastapi.testclient import TestClient

    dev = {"X-Dev-Principal": "human:perf-admin:admin"}
    incident = ids["incident"]
    endpoints = {
        "health": ("GET", "/health", None),
        "incident_list": ("GET", "/incidents?limit=50", None),
        "incident_detail": ("GET", f"/incidents/{incident}/detail", None),
        "investigations": ("GET", f"/incidents/{incident}/investigations", None),
        "workflow_list": ("GET", "/workflow?limit=50", None),
        "retrieval_incident": ("GET", "/retrieval/incidents/INC-1007", None),
        "retrieval_service_incidents": ("GET", f"/retrieval/services/{ids['service']}/incidents", None),
        "retrieval_service_dependencies": ("GET", f"/retrieval/services/{ids['service']}/dependencies", None),
        "policy_evaluation_api": ("POST", "/workflow/evaluate", {"incident_id": incident, "action": "notify", "severity": "low"}),
    }
    results: dict[str, dict] = {}
    for name, (method, path, body) in endpoints.items():
        client = TestClient(app)
        for _ in range(3):  # warm-up: imports, connection setup, caches
            client.request(method, path, headers=dev, json=body)
        samples, errors = [], 0
        for _ in range(sequential):
            started = time.perf_counter()
            response = client.request(method, path, headers=dev, json=body)
            elapsed = (time.perf_counter() - started) * 1000
            if response.status_code != 200:
                errors += 1
            else:
                samples.append(elapsed)
        concurrent_samples: list[float] = []
        concurrent_errors = 0
        lock = threading.Lock()

        def worker(_):
            nonlocal concurrent_errors
            own = TestClient(app)
            for _ in range(concurrent_each):
                started = time.perf_counter()
                response = own.request(method, path, headers=dev, json=body)
                elapsed = (time.perf_counter() - started) * 1000
                with lock:
                    if response.status_code != 200:
                        concurrent_errors += 1
                    else:
                        concurrent_samples.append(elapsed)

        with ThreadPoolExecutor(max_workers=concurrent_clients) as pool:
            list(pool.map(worker, range(concurrent_clients)))
        results[name] = {"sequential": summarize(samples, errors), "concurrent": summarize(concurrent_samples, concurrent_errors)}
    return results


def measure_policy_engine(iterations: int = 2000) -> dict:
    from app.services.policy_service import PolicyEngine

    engine = PolicyEngine()
    samples = []
    for index in range(iterations):
        started = time.perf_counter()
        engine.evaluate("restart_service" if index % 2 else "notify")
        samples.append((time.perf_counter() - started) * 1000)
    return {"iterations": iterations, **{k: v for k, v in summarize(samples, 0).items() if k != "requests"}}


def measure_construction(ids: dict, repeats: int = 15) -> dict:
    from app.services.incident_service import IncidentService

    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        IncidentService(database_url=ids["url"], tenant_id=ids["tenant"])
        samples.append((time.perf_counter() - started) * 1000)
    return {"service_construction_p50_ms": round(statistics.median(samples), 2), "repeats": repeats}


def compare(results: dict, baseline: dict | None, mode: str) -> list[str]:
    problems: list[str] = []
    if baseline is not None and baseline.get("mode") != mode:
        return [f"the baseline was recorded in '{baseline.get('mode')}' mode; run the same mode (or record a new baseline deliberately)"]
    for name, modes in results.items():
        for mode, stats in modes.items():
            if stats["errors"]:
                problems.append(f"{name}/{mode}: {stats['errors']} failed request(s)")
            p95 = stats["p95_ms"]
            if p95 is None:
                problems.append(f"{name}/{mode}: no successful request")
                continue
            if mode == "sequential" and p95 > PATHOLOGICAL_MS:  # concurrent clients share one GIL: relative check only
                problems.append(f"{name}/{mode}: p95 {p95} ms exceeds the pathological ceiling {PATHOLOGICAL_MS} ms")
            recorded = (baseline or {}).get("endpoints", {}).get(name, {}).get(mode)
            if recorded is not None:
                limit = max(FACTOR * recorded, FLOOR_MS)
                if p95 > limit:
                    problems.append(f"{name}/{mode}: p95 {p95} ms > {limit:.0f} ms (= max({FACTOR:g} x baseline {recorded} ms, {FLOOR_MS:g} ms))")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--quick", action="store_true", help="fewer requests")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--write-baseline", action="store_true", help="record this run as the baseline (deliberate action)")
    parser.add_argument("--no-compare", action="store_true", help="measure and write JSON only")
    args = parser.parse_args(argv)

    sequential, clients, each, extra, workflows = (6, 2, 3, 15, 4) if args.quick else (15, 3, 5, 40, 10)
    with tempfile.TemporaryDirectory(prefix="pulseops-perf-", ignore_cleanup_errors=True) as tmp:  # Windows may still hold SQLite handles
        app, ids = build_environment(Path(tmp), extra, workflows)
        endpoints = measure(app, ids, sequential, clients, each)
        policy = measure_policy_engine(500 if args.quick else 2000)
        construction = measure_construction(ids, 8 if args.quick else 15)

    list_p50 = endpoints["incident_list"]["sequential"]["p50_ms"] or 0
    share = round(construction["service_construction_p50_ms"] / list_p50, 2) if list_p50 else None
    notes = ["Local in-process measurement against SQLite; relative to the recorded baseline only. No capacity or production claim."]
    if share is not None and share > CONSTRUCTION_DOMINANCE:
        notes.append(f"FINDING: constructing a service/repository (which re-runs the idempotent schema statements) costs "
                     f"{construction['service_construction_p50_ms']} ms = {share:.0%} of the incident-list p50; it likely dominates "
                     "latency. Reported only; nothing was optimised.")
    slow = sorted(((name, modes["sequential"]["p50_ms"]) for name, modes in endpoints.items()
                   if list_p50 and modes["sequential"]["p50_ms"] and modes["sequential"]["p50_ms"] > 10 * list_p50), key=lambda x: -x[1])
    if slow:
        notes.append("FINDING: " + ", ".join(f"{n} (p50 {v} ms)" for n, v in slow) + f" are more than 10x slower than the incident list "
                     f"(p50 {list_p50} ms). These are the retrieval endpoints, which build the graph projection on demand per request. "
                     "Reported only; nothing was optimised.")
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(), "mode": "quick" if args.quick else "full",
        "python": platform.python_version(), "platform": platform.platform(),
        "profile": {"sequential_requests": sequential, "concurrent_clients": clients, "requests_per_client": each,
                    "extra_incidents": extra, "workflows_with_investigation": workflows},
        "endpoints": endpoints, "policy_engine_in_process": policy,
        "repository_construction": {**construction, "share_of_incident_list_p50": share},
        "thresholds": {"factor": FACTOR, "floor_ms": FLOOR_MS, "pathological_ms": PATHOLOGICAL_MS}, "notes": notes,
    }
    baseline = None
    if args.baseline.exists() and not args.no_compare and not args.write_baseline:
        baseline = json.loads(args.baseline.read_text("utf-8"))
    problems = [] if args.write_baseline or args.no_compare else compare(endpoints, baseline, report["mode"])
    if baseline is None and not args.write_baseline and not args.no_compare:
        problems.append(f"no baseline at {args.baseline}; record one deliberately with --write-baseline")
    report["regressions"], report["passed"] = problems, not problems
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if args.write_baseline:
        recorded = {name: {mode: stats["p95_ms"] for mode, stats in modes.items()} for name, modes in endpoints.items()}
        args.baseline.write_text(json.dumps({
            "note": "p95 in ms per endpoint, recorded on one development machine by `python scripts/perf_smoke.py --write-baseline`. "
                    "Used only as a relative reference (see scripts/perf_smoke.py); never a performance claim.",
            "mode": report["mode"], "recorded_at": report["generated_at"], "python": report["python"], "platform": report["platform"],
            "profile": report["profile"], "endpoints": recorded}, indent=2), encoding="utf-8")
        print(f"baseline written to {args.baseline}")
    for name, modes in endpoints.items():
        s, c = modes["sequential"], modes["concurrent"]
        print(f"{name:34s} seq p50={s['p50_ms']:>8} p95={s['p95_ms']:>8} err={s['errors']}   conc p50={c['p50_ms']:>8} p95={c['p95_ms']:>8} err={c['errors']}")
    print(f"policy engine (in-process)         p50={policy['p50_ms']} ms p95={policy['p95_ms']} ms over {policy['iterations']} calls")
    print(f"service construction p50={construction['service_construction_p50_ms']} ms ({share:.0%} of incident-list p50)" if share is not None else "")
    for note in notes[1:]:
        print(note)
    for problem in problems:
        print("REGRESSION:", problem)
    print("PERF SMOKE:", "PASS" if not problems else "FAIL", f"-> {args.out}")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
