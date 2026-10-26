"""PulseOps one-command local quality gate (P11).

    python scripts/quality_gate.py                 # the whole gate; exit code 0 only if every step passes
    python scripts/quality_gate.py --flake         # repeat the critical test set (default 3 times); any failure = FAIL
    python scripts/quality_gate.py --list          # print the steps
    python scripts/quality_gate.py --only bandit,secret-scan
    python scripts/quality_gate.py --ratchet       # raise coverage thresholds to the last measured values (never lowers)
    python scripts/quality_gate.py --write-eval-manifest   # deliberately re-record evaluation file hashes

Sequence: Python tests + coverage -> coverage ratchet -> frontend install (npm ci, which also verifies the lockfile) ->
frontend tests + coverage -> frontend build -> replay v2 -> replay v3 -> tenant isolation == 1.00 -> evaluation integrity ->
security tests -> Bandit -> dependency audit (pip-audit, npm audit) + constraints check -> secret scan -> API/contract/
reliability tests -> performance smoke -> browser E2E -> Docker build/run. No live Claude evaluation is ever run.

A step that is skipped on request (``--skip-*``) is reported as SKIPPED and the run is marked INCOMPLETE: it is never counted
as a pass. Network-dependent steps (dependency audit, Docker) FAIL when their data is unreachable; they do not pass silently.
Artifacts go to quality-artifacts/ (git-ignored); the summary is written to quality-report.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
ARTIFACTS = ROOT / "quality-artifacts"
THRESHOLDS = ROOT / "quality" / "thresholds.json"
EVAL_MANIFEST = ROOT / "quality" / "eval-integrity.json"
DEP_ALLOWLIST = ROOT / "quality" / "dependency-audit-allowlist.json"
REPORT = ROOT / "quality-report.json"
PY = sys.executable
NPM = shutil.which("npm") or "npm"
NPX = shutil.which("npx") or "npx"
EVAL_FILES = [
    "evals/datasets/golden_incidents.json", "evals/datasets/golden_incidents_v3.json", "evals/datasets/retrieval_ground_truth.json",
    "evals/baselines/baseline.json", "evals/baselines/baseline-v3.json", "evals/scorers.py",
]
PYTEST = [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--show-capture=no"]


# ----------------------------------------------------------------------------------------------------------- helpers

@dataclass
class Result:
    name: str
    status: str  # PASS | FAIL | SKIPPED
    seconds: float = 0.0
    detail: str = ""
    output_tail: list[str] = field(default_factory=list)


def run(command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None, timeout: int = 3600) -> tuple[int, str]:
    completed = subprocess.run(command, cwd=cwd, env={**os.environ, **(env or {})}, capture_output=True, text=True,
                               timeout=timeout, encoding="utf-8", errors="replace")
    return completed.returncode, (completed.stdout or "") + (completed.stderr or "")


def tail(output: str, lines: int = 15) -> list[str]:
    return [line for line in output.strip().splitlines()[-lines:]]


def floor_pct(value: float) -> int:
    return int(math.floor(value + 1e-9))


def file_digest(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n")  # a Windows checkout must hash like a Linux one
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


# ----------------------------------------------------------------------------------------------------------- steps

def step_python_tests() -> tuple[bool, str, str]:
    ARTIFACTS.mkdir(exist_ok=True)
    code, out = run(PYTEST + ["--cov=app", "--cov-branch", f"--cov-report=json:{ARTIFACTS / 'coverage.json'}"])
    summary = next((line for line in reversed(out.splitlines()) if " passed" in line or " failed" in line), "")
    return code == 0, summary.strip(), out


def check_python_coverage() -> tuple[bool, str, str]:
    report = ARTIFACTS / "coverage.json"
    if not report.exists():
        return False, "no coverage.json: run the Python test step first", ""
    data, limits = load_json(report), load_json(THRESHOLDS)["python"]
    total = data["totals"]["percent_covered"]
    problems = []
    if total < limits["total_percent"]:
        problems.append(f"total {total:.2f}% < {limits['total_percent']}%")
    by_path = {name.replace("\\", "/"): info for name, info in data["files"].items()}
    for module, floor in limits["modules"].items():
        info = by_path.get(module)
        if info is None:
            problems.append(f"{module}: not measured")
        elif info["summary"]["percent_covered"] < floor:
            problems.append(f"{module} {info['summary']['percent_covered']:.2f}% < {floor}%")
    detail = f"total {total:.2f}% (floor {limits['total_percent']}%), {len(limits['modules'])} critical module floors"
    return not problems, detail if not problems else "; ".join(problems), ""


def step_frontend_install() -> tuple[bool, str, str]:
    code, out = run([NPM, "ci", "--no-audit", "--no-fund"], cwd=FRONTEND)
    return code == 0, "npm ci succeeded (lockfile consistent with package.json)" if code == 0 else "npm ci failed", out


def step_frontend_tests() -> tuple[bool, str, str]:
    code, out = run([NPM, "run", "test:coverage"], cwd=FRONTEND)
    if code != 0:
        return False, "frontend tests failed", out
    summary = load_json(FRONTEND / "coverage" / "coverage-summary.json")["total"]
    limits = load_json(THRESHOLDS)["frontend"]
    problems = [f"{metric} {summary[metric]['pct']}% < {floor}%" for metric, floor in limits.items() if summary[metric]["pct"] < floor]
    detail = ", ".join(f"{m} {summary[m]['pct']}% (floor {f}%)" for m, f in limits.items())
    return not problems, detail if not problems else "; ".join(problems), out


def step_frontend_build() -> tuple[bool, str, str]:
    code, out = run([NPM, "run", "build"], cwd=FRONTEND)
    return code == 0, "typecheck + production build" if code == 0 else "build failed", out


def _replay(dataset: str | None) -> tuple[bool, str, str]:
    out_dir = ARTIFACTS / ("replay-" + (dataset or "v2"))
    command = [PY, "-m", "evals", "replay", "--out", str(out_dir)] + (["--dataset", dataset] if dataset else [])
    code, out = run(command)
    report = out_dir / "report-replay.json"
    ok = code == 0 and report.exists() and load_json(report)["passed"] is True and "GATE: PASS" in out
    return ok, "GATE: PASS" if ok else "replay failed", out


def step_replay_v2() -> tuple[bool, str, str]:
    return _replay(None)


def step_replay_v3() -> tuple[bool, str, str]:
    return _replay("v3")


def step_tenant_isolation() -> tuple[bool, str, str]:
    scores = {}
    for name in ("replay-v2", "replay-v3"):
        path = ARTIFACTS / name / "report-replay.json"
        if not path.exists():
            return False, f"{name}: no report (run the replay step first)", ""
        scores[name] = load_json(path)["system_correctness_safety"]["tenant_isolation"]["mean_score"]
    ok = all(score == 1.0 for score in scores.values())
    return ok, ", ".join(f"{name} {score:.2f}" for name, score in scores.items()), ""


def step_eval_integrity() -> tuple[bool, str, str]:
    manifest = load_json(EVAL_MANIFEST)["sha256"]
    changed = [f for f in EVAL_FILES if manifest.get(f) != file_digest(ROOT / f)]
    return not changed, "datasets, baselines and scorers unchanged" if not changed else f"CHANGED: {', '.join(changed)}", ""


def step_security_tests() -> tuple[bool, str, str]:
    code, out = run(PYTEST + ["-m", "security"])
    return code == 0, next((l for l in reversed(out.splitlines()) if " passed" in l or " failed" in l), "").strip(), out


def step_bandit() -> tuple[bool, str, str]:
    code, out = run([PY, "-m", "bandit", "-r", "app", "-ll", "-q", "-f", "txt"])
    return code == 0, "no finding of medium severity or above in app/" if code == 0 else "bandit reported findings", out


def _allowlist(ecosystem: str) -> list[dict]:
    entries = load_json(DEP_ALLOWLIST)["allow"] if DEP_ALLOWLIST.exists() else []
    live = []
    for entry in entries:
        if not entry.get("reason", "").strip() or not entry.get("expires"):
            raise SystemExit(f"dependency allowlist entry {entry.get('id')} needs a reason and an expiry date")
        if date.fromisoformat(entry["expires"]) < date.today():
            raise SystemExit(f"dependency allowlist entry {entry['id']} expired on {entry['expires']}: re-assess it")
        if entry.get("ecosystem", "pip") == ecosystem:
            live.append(entry)
    return live


def _npm_unaccepted(output: str, accepted: set[str]) -> tuple[list[str], str]:
    """Advisory ids of high/critical npm findings that are not in the written allowlist. Unreadable output is a failure."""
    try:
        data = json.loads(output)
        vulnerabilities = data["vulnerabilities"]
    except (ValueError, KeyError, TypeError):
        return ["npm audit produced no readable result (advisory data unreachable?)"], "unreadable"
    found = set()
    for vulnerability in vulnerabilities.values():
        for via in vulnerability.get("via", []):
            if isinstance(via, dict) and via.get("severity") in ("high", "critical"):
                found.add(str(via.get("url", "")).rsplit("/", 1)[-1] or str(via.get("source")))
    return sorted(found - accepted), f"{len(found)} high/critical advisory id(s), {len(found & accepted)} accepted"


def step_dependency_audit() -> tuple[bool, str, str]:
    pip_allow, npm_allow = _allowlist("pip"), _allowlist("npm")
    command = [PY, "-m", "pip_audit", "-r", str(ROOT / "constraints.txt"), "--no-deps", "--disable-pip"]
    for entry in pip_allow:
        command += ["--ignore-vuln", entry["id"]]
    code, out = run(command, timeout=900)
    if code != 0:
        return False, "pip-audit failed or reported vulnerabilities (advisory data unreachable counts as a failure)", out
    _, npm_out = run([NPM, "audit", "--json"], cwd=FRONTEND, timeout=900)
    unaccepted, npm_detail = _npm_unaccepted(npm_out, {e["id"] for e in npm_allow})
    if unaccepted:
        return False, "npm audit: unaccepted high/critical advisory: " + ", ".join(unaccepted), out + npm_out[-2000:]
    accepted = ", ".join(e["id"] for e in pip_allow + npm_allow) or "none"
    return True, f"pip-audit clean; npm audit: {npm_detail} (accepted and documented: {accepted})", out


def step_constraints() -> tuple[bool, str, str]:
    """Dependency lock verification: installed versions equal the pinned ones, and pip finds no broken requirement."""
    import importlib.metadata as md

    pinned = {}
    for line in (ROOT / "constraints.txt").read_text("utf-8").splitlines():
        match = re.match(r"^([A-Za-z0-9_.\-]+)==(\S+)$", line.strip())
        if match:
            pinned[re.sub(r"[-_.]+", "-", match.group(1)).lower()] = match.group(2)
    drift = []
    for dist in md.distributions():
        name = re.sub(r"[-_.]+", "-", dist.metadata["Name"] or "").lower()
        if name in pinned and pinned[name] != dist.version:
            drift.append(f"{name} {dist.version} != pinned {pinned[name]}")
    code, out = run([PY, "-m", "pip", "check"])
    problems = drift + ([out.strip()] if code != 0 else [])
    return not problems, f"{len(pinned)} pins match the environment; pip check clean" if not problems else "; ".join(problems)[:400], out


def step_secret_scan() -> tuple[bool, str, str]:
    ARTIFACTS.mkdir(exist_ok=True)
    code, out = run([PY, str(ROOT / "scripts" / "secret_scan.py"), "--json", str(ARTIFACTS / "secret-scan.json")])
    return code == 0, next((l for l in reversed(out.splitlines()) if l.startswith("SECRET SCAN")), "").strip(), out


def step_api_reliability() -> tuple[bool, str, str]:
    code, out = run(PYTEST + ["-m", "contract or reliability"])
    return code == 0, next((l for l in reversed(out.splitlines()) if " passed" in l or " failed" in l), "").strip(), out


def step_performance() -> tuple[bool, str, str]:
    ARTIFACTS.mkdir(exist_ok=True)
    code, out = run([PY, str(ROOT / "scripts" / "perf_smoke.py"), "--out", str(ARTIFACTS / "perf.json")], timeout=1800)
    return code == 0, next((l for l in reversed(out.splitlines()) if l.startswith("PERF SMOKE")), "").strip()[:200], out


def step_e2e() -> tuple[bool, str, str]:
    code, out = run([NPX, "playwright", "test"], cwd=FRONTEND, env={"PULSEOPS_PYTHON": PY}, timeout=1800)
    summary = next((l for l in reversed(out.splitlines()) if re.search(r"\d+ (passed|failed)", l)), "").strip()
    return code == 0, summary, out


DOCKER_ARGS: list[str] = []


def step_docker() -> tuple[bool, str, str]:
    code, out = run([PY, str(ROOT / "scripts" / "docker_check.py"), *DOCKER_ARGS], timeout=3600)
    return code == 0, next((l for l in reversed(out.splitlines()) if l.startswith("DOCKER CHECK")), "").strip()[:240], out


STEPS: list[tuple[str, str, callable]] = [  # (name, skip flag group, function)
    ("python-tests-coverage", "", step_python_tests),
    ("python-coverage-threshold", "", check_python_coverage),
    ("frontend-install", "install", step_frontend_install),
    ("frontend-tests-coverage", "", step_frontend_tests),
    ("frontend-build", "", step_frontend_build),
    ("replay-v2", "", step_replay_v2),
    ("replay-v3", "", step_replay_v3),
    ("tenant-isolation", "", step_tenant_isolation),
    ("eval-integrity", "", step_eval_integrity),
    ("security-tests", "", step_security_tests),
    ("bandit", "", step_bandit),
    ("dependency-audit", "deps", step_dependency_audit),
    ("constraints-check", "", step_constraints),
    ("secret-scan", "", step_secret_scan),
    ("api-reliability-tests", "", step_api_reliability),
    ("performance-smoke", "", step_performance),
    ("browser-e2e", "e2e", step_e2e),
    ("docker-validation", "docker", step_docker),
]


# ----------------------------------------------------------------------------------------------------------- modes

def ratchet() -> int:
    """Raise thresholds to the last measured values (floored). Never lowers a threshold."""
    limits = load_json(THRESHOLDS)
    changed = []
    coverage = ARTIFACTS / "coverage.json"
    if coverage.exists():
        data = load_json(coverage)
        total = floor_pct(data["totals"]["percent_covered"])
        if total > limits["python"]["total_percent"]:
            changed.append(f"python total {limits['python']['total_percent']} -> {total}")
            limits["python"]["total_percent"] = total
        by_path = {n.replace("\\", "/"): i for n, i in data["files"].items()}
        for module, floor in limits["python"]["modules"].items():
            measured = floor_pct(by_path[module]["summary"]["percent_covered"])
            if measured > floor:
                changed.append(f"{module} {floor} -> {measured}")
                limits["python"]["modules"][module] = measured
    summary_path = FRONTEND / "coverage" / "coverage-summary.json"
    if summary_path.exists():
        summary = load_json(summary_path)["total"]
        for metric, floor in limits["frontend"].items():
            measured = floor_pct(summary[metric]["pct"])
            if measured > floor:
                changed.append(f"frontend {metric} {floor} -> {measured}")
                limits["frontend"][metric] = measured
    THRESHOLDS.write_text(json.dumps(limits, indent=2) + "\n", encoding="utf-8")
    print("ratchet:", "; ".join(changed) if changed else "nothing to raise (thresholds already at the measured values)")
    return 0


def write_eval_manifest() -> int:
    EVAL_MANIFEST.parent.mkdir(exist_ok=True)
    EVAL_MANIFEST.write_text(json.dumps({
        "note": "SHA-256 (line endings normalised) of the evaluation datasets, baselines and scorer. P11 must not change them; "
                "re-record only as a deliberate, reviewed evaluation change (python scripts/quality_gate.py --write-eval-manifest).",
        "sha256": {f: file_digest(ROOT / f) for f in EVAL_FILES}}, indent=2) + "\n", encoding="utf-8")
    print("evaluation manifest written")
    return 0


def flake(runs: int) -> int:
    """Repeat the critical tests; there are NO hidden retries. Any failed repetition fails the check."""
    failures: dict[str, list[int]] = {}
    summaries = []
    for index in range(1, runs + 1):
        started = time.time()
        code, out = run(PYTEST + ["-m", "critical", "-rf"])
        summary = next((l for l in reversed(out.splitlines()) if " passed" in l or " failed" in l), "").strip()
        summaries.append({"run": index, "exit": code, "summary": summary, "seconds": round(time.time() - started, 1)})
        print(f"flake run {index}/{runs}: {summary} ({summaries[-1]['seconds']}s)")
        for line in out.splitlines():
            if line.startswith("FAILED "):
                failures.setdefault(line.split(" - ")[0][7:], []).append(index)
        if code != 0 and not any(i == index for runs_ in failures.values() for i in runs_):
            failures.setdefault("<pytest exited non-zero without a FAILED line (collection/setup error)>", []).append(index)
    ARTIFACTS.mkdir(exist_ok=True)
    (ARTIFACTS / "flake-report.json").write_text(json.dumps({"runs": summaries, "failures": failures}, indent=2), encoding="utf-8")
    for test, where in failures.items():
        print(f"FLAKY/FAILING: {test} (runs {where})")
    print("FLAKE CHECK:", "FAIL" if failures else f"PASS ({runs} repetitions, no failure)")
    return 1 if failures else 0


# ----------------------------------------------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--only", default="", help="comma-separated step names")
    parser.add_argument("--flake", action="store_true")
    parser.add_argument("--flake-runs", type=int, default=3)
    parser.add_argument("--ratchet", action="store_true")
    parser.add_argument("--write-eval-manifest", action="store_true")
    for group in ("install", "deps", "e2e", "docker"):
        parser.add_argument(f"--skip-{group}", action="store_true", help=f"skip the {group} step(s); the run is then INCOMPLETE")
    parser.add_argument("--docker-arg", action="append", default=[], help="passed to scripts/docker_check.py (repeatable)")
    args = parser.parse_args(argv)
    DOCKER_ARGS.extend(args.docker_arg)

    if args.list:
        for name, _, _ in STEPS:
            print(name)
        return 0
    if args.ratchet:
        return ratchet()
    if args.write_eval_manifest:
        return write_eval_manifest()
    if args.flake:
        return flake(args.flake_runs)

    selected = {s.strip() for s in args.only.split(",") if s.strip()}
    unknown = selected - {n for n, _, _ in STEPS}
    if unknown:
        print("unknown step(s):", ", ".join(sorted(unknown)))
        return 2
    skipped_groups = {g for g in ("install", "deps", "e2e", "docker") if getattr(args, f"skip_{g}")}
    results: list[Result] = []
    for name, group, function in STEPS:
        if selected and name not in selected:
            continue
        if group and group in skipped_groups:
            results.append(Result(name, "SKIPPED", detail=f"skipped by --skip-{group}"))
            print(f"SKIP  {name}")
            continue
        started = time.time()
        try:
            ok, detail, output = function()
        except subprocess.TimeoutExpired:
            ok, detail, output = False, "timed out", ""
        except Exception as exc:  # noqa: BLE001 - a crashing step is a failing step, never a silent one
            ok, detail, output = False, f"{type(exc).__name__}: {str(exc)[:200]}", ""
        result = Result(name, "PASS" if ok else "FAIL", round(time.time() - started, 1), detail, [] if ok else tail(output))
        results.append(result)
        print(f"{result.status:5s} {name} ({result.seconds}s) {detail}")
        if not ok:
            for line in result.output_tail:
                print("      |", line)

    failed = [r.name for r in results if r.status == "FAIL"]
    skipped = [r.name for r in results if r.status == "SKIPPED"]
    complete = not skipped and not selected
    REPORT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(), "python": sys.version.split()[0], "complete": complete,
        "passed": not failed, "steps": [r.__dict__ for r in results]}, indent=2), encoding="utf-8")
    print("\n" + "=" * 78)
    for r in results:
        print(f"{r.status:7s} {r.name:28s} {r.seconds:>7}s  {r.detail[:90]}")
    verdict = "FAIL (" + ", ".join(failed) + ")" if failed else "PASS" if complete else f"PASS (INCOMPLETE: skipped {', '.join(skipped) or 'a subset via --only'})"
    print(f"QUALITY GATE: {verdict}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
