"""Machine-readable JSON and human-readable Markdown reports."""

from __future__ import annotations

from pathlib import Path

from evals.contracts import EvalReport, MetricAggregate


def to_json(report: EvalReport) -> str:
    return report.model_dump_json(indent=2)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _table(aggregates: dict[str, MetricAggregate]) -> list[str]:
    lines = ["| Metric | Applicable cases | Mean score | Pass rate | Failed cases |", "|---|---|---|---|---|"]
    for name, agg in aggregates.items():
        failed = ", ".join(agg.failed_cases) or "-"
        lines.append(f"| {name} | {agg.applicable_cases} | {_fmt(agg.mean_score)} | {_fmt(agg.pass_rate)} | {failed} |")
    return lines


def _n(value: object) -> str:
    return "n/a" if value is None else str(value)


def _observability(report: EvalReport) -> list[str]:
    """P8.0: informational latency / token / cost section. Unknown values are shown as n/a, never as 0."""
    t = report.telemetry
    assert t is not None
    live = t.mode == "live"
    out = [
        "", "## Observability (informational, never gated)", "",
        f"- evaluation mode: **{t.mode}**",
        f"- latency kind: **{t.latency_kind}**" + ("" if live else " (harness/replay latency, NOT model inference latency)"),
        f"- model: {_n(t.model) if live else 'none (scripted replay)'}",
        f"- dataset: {report.dataset_version} (sha256 {(report.dataset_sha256 or 'n/a')[:16]})",
        f"- cases with telemetry / tokens / cost: {t.cases_with_telemetry} / {t.cases_with_tokens} / {t.cases_with_cost} of {t.cases}",
        f"- total tokens: input {_n(t.input_tokens)}, output {_n(t.output_tokens)}, total {_n(t.total_tokens)}",
        f"- total cost (USD, as reported by the SDK): {_n(t.total_cost_usd)}",
        f"- {t.note}",
        "",
        "| Case | Investigation ms | API ms | Input tokens | Output tokens | Cost USD |",
        "|---|---|---|---|---|---|",
    ]
    for case in report.cases:
        c = case.telemetry
        if c is None:
            out.append(f"| {case.case_id} | n/a | n/a | n/a | n/a | n/a |")
        else:
            out.append(
                f"| {case.case_id} | {_n(c.investigation_ms)} | {_n(c.api_duration_ms)} | {_n(c.input_tokens)} | "
                f"{_n(c.output_tokens)} | {_n(c.total_cost_usd)} |"
            )
    return out


def to_markdown(report: EvalReport) -> str:
    out = [
        f"# PulseOps Evaluation Report - {report.mode.upper()} ({report.status})",
        "",
        f"> **{report.banner}**",
        "",
        f"- run_id: `{report.run_id}`",
        f"- timestamp: {report.timestamp}",
        f"- mode: **{report.mode}**",
        f"- live model quality measured: **{'YES' if report.live_model_quality_measured else 'NO'}**",
        f"- model: {report.model or 'n/a'}",
        f"- prompt version: {report.prompt_version or 'n/a'}",
        f"- dataset: {report.dataset_version} (sha256 {(report.dataset_sha256 or 'n/a')[:16]})",
        f"- retrieval ground truth sha256: {(report.retrieval_dataset_sha256 or 'n/a')[:16]}",
        f"- case count: {report.case_count}",
    ]
    if report.skipped_reason:
        out.append(f"- skipped: {report.skipped_reason}")
    out += [f"- note: {note}" for note in report.notes]
    out += [
        "",
        "## A. System correctness / safety",
        "These must stay at 1.00. They are reported separately from AI quality and are never merged into one score.",
        "",
        *_table(report.system_correctness_safety),
        "",
        "## B. AI quality",
        "Rubric-based and tolerant; in replay mode these reflect the authored scripts, not Claude.",
        "",
        *_table(report.ai_quality),
        "",
        "## Per-case results",
        "",
        "| Case | Category | Outcome | Failed metrics |",
        "|---|---|---|---|",
    ]
    for case in report.cases:
        failed = [s.metric for s in case.scores if s.applicable and not s.passed]
        out.append(f"| {case.case_id} | {case.category} | {case.outcome} | {', '.join(failed) or '-'} |")
    problems = [
        (case.case_id, s.metric, detail)
        for case in report.cases for s in case.scores if s.applicable and not s.passed for detail in s.details
    ]
    if problems:
        out += ["", "### Failure details", ""]
        out += [f"- `{cid}` / {metric}: {detail}" for cid, metric, detail in problems]
    if report.retrieval_checks:
        out += ["", "## Retrieval ground truth (deterministic, 4 controlled tools)", "",
                "| Check | Tool | Score | Result |", "|---|---|---|---|"]
        out += [f"| {c.check_id} | {c.tool} | {c.score:.2f} | {'PASS' if c.passed else 'FAIL'} |" for c in report.retrieval_checks]
        failures = [(c.check_id, d) for c in report.retrieval_checks if not c.passed for d in c.details]
        if failures:
            out += ["", "### Retrieval failure details", ""] + [f"- `{cid}`: {d}" for cid, d in failures]
    if report.tenant_checks:
        out += ["", "## Tenant isolation (deterministic, two tenants sharing ids)", "",
                "| Check | Surface | Score | Result |", "|---|---|---|---|"]
        out += [f"| {c.check_id} | {c.tool} | {c.score:.2f} | {'PASS' if c.passed else 'FAIL'} |" for c in report.tenant_checks]
        tenant_failures = [(c.check_id, d) for c in report.tenant_checks if not c.passed for d in c.details]
        if tenant_failures:
            out += ["", "### Tenant isolation failure details", ""] + [f"- `{cid}`: {d}" for cid, d in tenant_failures]
    if report.timings:
        out += ["", "## Timing (informational, never gated)", "",
                "| Measure | Count | Mean ms | p50 ms | Max ms |", "|---|---|---|---|---|"]
        out += [f"| {name} | {t.count} | {t.mean_ms} | {t.p50_ms} | {t.max_ms} |" for name, t in report.timings.items()]
    if report.telemetry is not None:
        out += _observability(report)
    observations = [
        (case.case_id, s.metric, d)
        for case in report.cases for s in case.scores for d in s.details if d.startswith("OBSERVATION:")
    ] + [
        (c.check_id, "retrieval_correctness", d) for c in report.retrieval_checks for d in c.details
        if d.startswith("OBSERVATION:")
    ]
    if observations:
        out += ["", "## Observations (reported, not failed)", ""]
        out += [f"- `{cid}` / {metric}: {d.removeprefix('OBSERVATION: ')}" for cid, metric, d in observations]
    out += ["", "## Regression"]
    if report.regression is None:
        out.append("Not compared against a baseline in this mode.")
    else:
        r = report.regression
        out.append(f"- baseline: {r.baseline_path} (version {r.baseline_version}), compared: {r.compared}")
        out.append(f"- result: **{'REGRESSION' if r.failed else 'no regression'}**")
        out += [f"- {f.message}" for f in r.regressions]
    out += ["", f"**Overall gate: {'PASS' if report.passed else 'FAIL'}**", ""]
    return "\n".join(out)


def write_reports(report: EvalReport, out_dir: Path) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"report-{report.mode}.json"
    md_path = out_dir / f"report-{report.mode}.md"
    json_path.write_text(to_json(report), encoding="utf-8")
    md_path.write_text(to_markdown(report), encoding="utf-8")
    return json_path, md_path
