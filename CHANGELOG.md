# Changelog

All notable changes to PulseOps. The project follows its phase plan (`project-plan.md`); each entry names the phase.
The application version in `app/core/config.py` is still `0.1.0`: choosing a release number is part of the release decision
in `docs/release-checklist.md`, not something P11 changes.

## P11 — Quality Engineering and Release Readiness

### Added
- `scripts/quality_gate.py`: one command that runs every quality gate (and `--flake`, `--ratchet`, `--list`).
- Python and frontend coverage measurement with ratcheted thresholds (`quality/thresholds.json`).
- Bandit static analysis, `pip-audit` / `npm audit` with a written, expiring allowlist (`quality/dependency-audit-allowlist.json`),
  `constraints.txt` (exact Python versions, also used by the Docker image), repository secret scan (`scripts/secret_scan.py`).
- Tests: `tests/test_phase11_security.py`, `_reliability.py`, `_contract.py`, `_performance.py`.
- Browser E2E: `e2e/p11.spec.ts` (Playwright, Chromium, 8 scenarios, no retries) and the deterministic `e2e/fixture_server.py`.
- `scripts/perf_smoke.py` and its recorded baseline; `scripts/docker_check.py`; `quality/eval-integrity.json`.
- CI: python / frontend / evaluation / security / contract-reliability-performance / docker-and-e2e jobs; scheduled `flake.yml`.
- `docs/phase-11.md`, `docs/release-checklist.md`.

### Fixed (found by the P11 tests)
- Request bodies were unbounded: a 1 MiB limit now returns 413 in the standard error envelope (`PULSEOPS_MAX_BODY_BYTES`).
- Two reviewers could both record a decision on one workflow concurrently: the status change is now an atomic compare-and-set.
- Concurrent incident creation could overwrite an incident with the same allocated id: allocation now retries on conflict.
- `/health/ready` reported ready for a read-only database: it now checks writability.
- Env files nested in the build context (for example `app/agent/.env`) could be copied into the Docker image: `.dockerignore`
  now excludes them at every depth.

### Changed
- Docker image installs from `constraints.txt`; its health check uses `/health/ready`.
- Comment-only `# nosec B608/B101` annotations with written justifications on reviewed Bandit findings.

## P9 — Modern Application
- React + Vite + TypeScript UI (incident list, incident detail, pending approvals) served at `/ui` with a strict CSP.
- First-class tenant-scoped investigation records; reviewer read APIs; `/me`; `/health/ready`; typed error envelope
  (`detail`, `code`, `request_id`); paginated/filterable `GET /incidents`; explicit `app.migrations.p9`.

## P8 — Evaluation
- Replay and guarded live evaluation, golden datasets v2 and v3 with baselines, tenant-isolation evaluation, run history.

## P7 — Workflow and HITL (Gates 1–9.1)
- n8n event workflow, deterministic policy engine, human-in-the-loop decisions, authentication and RBAC (Gate 9),
  multi-tenancy (Gate 9.1), local Docker Compose platform.

## P0–P6
- Foundation, operational data, ontology and graph context, retrieval tools, MCP, Claude Agent SDK, incident agent.
