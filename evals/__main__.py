"""CLI: ``python -m evals replay|live|baseline|history``. Observational only; exit code reflects the replay gate.

Live evaluation calls a real model and costs money, so it is explicit and opt-in: ``live`` does nothing unless
``--confirm-live`` is given AND ``ANTHROPIC_API_KEY`` is set. It is never run by CI or the test suite.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from evals.baseline import write_baseline
from evals.history import append_history, format_history, load_history
from evals.report import write_reports
from evals.runner import DATASETS, run_live, run_replay


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals")
    sub = parser.add_subparsers(dest="command", required=True)
    datasets = sorted(DATASETS)

    replay = sub.add_parser("replay", help="deterministic agent-validation run (CI)")
    replay.add_argument("--out", default="eval-reports")
    replay.add_argument("--dataset", choices=datasets, default="v2", help="golden dataset (default: v2)")
    replay.add_argument("--baseline", default=None, help="baseline file (default: the dataset's own baseline)")

    live = sub.add_parser("live", help="OPT-IN live Claude run (needs --confirm-live and ANTHROPIC_API_KEY)")
    live.add_argument("--out", default="eval-reports")
    live.add_argument("--model", default=None)
    live.add_argument("--limit", type=int, default=None)
    live.add_argument("--confirm-live", action="store_true", help="acknowledge that real model calls will be made")
    live.add_argument("--max-cost-usd", type=float, default=None,
                      help="stop starting new cases once the SDK-reported cost reaches this amount")

    base = sub.add_parser("baseline", help="explicitly (re)write a replay baseline")
    base.add_argument("--reason", required=True)
    base.add_argument("--dataset", choices=datasets, default="v2")
    base.add_argument("--path", default=None)
    base.add_argument("--confirm-overwrite", action="store_true")

    hist = sub.add_parser("history", help="show the local run history (informational)")
    hist.add_argument("--out", default="eval-reports")
    hist.add_argument("--mode", choices=["replay", "live"], default=None)
    hist.add_argument("--last", type=int, default=10)

    args = parser.parse_args(argv)
    previous = logging.root.manager.disable
    logging.disable(logging.INFO)  # keep CI output readable (httpx/agent telemetry logs)
    try:
        return _dispatch(args)
    finally:
        logging.disable(previous)


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "replay":
        dataset_path, default_baseline = DATASETS[args.dataset]
        extra = {} if args.dataset == "v2" else {"dataset_path": dataset_path}  # v2 keeps the original call shape
        report = run_replay(baseline_path=Path(args.baseline or default_baseline), **extra)
        json_path, md_path = write_reports(report, Path(args.out))
        append_history(report, Path(args.out))
        print(report.banner)
        print(f"reports: {json_path} {md_path}")
        if report.regression:
            for finding in report.regression.regressions:
                print(f"REGRESSION: {finding.message}")
        print(f"GATE: {'PASS' if report.passed else 'FAIL'}")
        return 0 if report.passed else 1

    if args.command == "live":
        from app.core.config import get_settings

        has_key = bool(get_settings().anthropic_api_key)
        if has_key and not args.confirm_live:
            print("live evaluation REFUSED: it calls a real model and costs money. Re-run with --confirm-live "
                  "(optionally --limit N and --max-cost-usd X). Nothing was run.", file=sys.stderr)
            return 0  # like a skipped run, an unconfirmed live request is never a CI failure; no model was called
        if args.confirm_live and not has_key:
            print("live evaluation cannot run: --confirm-live was given but ANTHROPIC_API_KEY is not set. "
                  "Nothing was run.", file=sys.stderr)
            write_reports(run_live(model=args.model, api_key=""), Path(args.out))
            return 3
        report = run_live(model=args.model, limit=args.limit, max_cost_usd=args.max_cost_usd)
        write_reports(report, Path(args.out))
        append_history(report, Path(args.out))
        print(report.banner)
        print(f"STATUS: {report.status}")
        return 0

    if args.command == "history":
        print(format_history(load_history(Path(args.out)), mode=args.mode, last=args.last))
        return 0

    dataset_path, default_baseline = DATASETS[args.dataset]
    report = run_replay(baseline_path=None, dataset_path=dataset_path)
    try:
        baseline = write_baseline(report, Path(args.path or default_baseline), reason=args.reason,
                                  confirm_overwrite=args.confirm_overwrite)
    except (FileExistsError, ValueError) as exc:
        print(f"baseline not written: {exc}", file=sys.stderr)
        return 2
    print(f"baseline version {baseline['baseline_version']} written to {args.path or default_baseline}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
