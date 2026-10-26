# Phase 11 — Quality Engineering and Release Readiness

## 1. Objective

Prove that the existing local PulseOps application is quality-engineered: tested, secured, reliable, containerised and
release-ready. P11 adds tests, scripts, CI and documentation **around** P0–P9; it does not redesign them. P10 (cloud and
platform) was intentionally skipped and is not started here. No live Claude evaluation is part of P11 or of CI.

## 2. One command

```text
python scripts/quality_gate.py            # everything below; non-zero exit if any step fails
python scripts/quality_gate.py --flake    # repeat the critical tests (3 times); any failure = FAIL
python scripts/quality_gate.py --list     # the steps
python scripts/quality_gate.py --ratchet  # raise coverage thresholds to the last measured values (never lowers)
```

Sequence: Python tests + coverage → coverage thresholds → `npm ci` (verifies the lockfile) → frontend tests + coverage →
frontend build → replay v2 → replay v3 → tenant isolation = 1.00 → evaluation integrity → security tests → Bandit →
dependency audit → constraints check → secret scan → API contract + reliability tests → performance smoke → browser E2E →
Docker build/run. Skipping a step (`--skip-install|deps|e2e|docker`) marks the run **INCOMPLETE**; a skip is never a pass.
Network-dependent steps fail rather than pass silently when their data is unreachable. Results: `quality-report.json`,
artifacts in `quality-artifacts/` (git-ignored).

## 3. Implemented quality controls

| Area | Control | Where |
|---|---|---|
| Python coverage | `pytest-cov`, branch coverage, ratcheted total + per-module floors | `quality/thresholds.json`, gate steps 1–2 |
| Frontend coverage | `@vitest/coverage-v8`, ratcheted floors | `frontend/vite.config.ts`, gate step 4 |
| Static analysis | Bandit over `app/`, medium severity and above fails | gate `bandit` |
| Dependencies | `pip-audit` on `constraints.txt`, `npm audit`, written + expiring allowlist, `npm ci`, constraints-vs-environment check | gate `dependency-audit`, `constraints-check` |
| Secrets | repository-wide scan incl. generated artifacts, redacted output | `scripts/secret_scan.py` |
| Security tests | auth abuse, malformed input, cross-tenant sweep, headers/CSP, prompt injection, secret scanner | `tests/test_phase11_security.py` |
| Contract | route/method/param snapshot, auth per route, status classes, error envelope, frontend types ↔ OpenAPI | `tests/test_phase11_contract.py` |
| Reliability | MCP failure, DB failure/recovery, restart recovery, concurrent HITL, concurrent requests | `tests/test_phase11_reliability.py` |
| Performance | local p50/p95 smoke with regression detection | `scripts/perf_smoke.py`, `tests/test_phase11_performance.py` |
| Browser E2E | 8 scenarios, Chromium, no retries | `e2e/p11.spec.ts`, `frontend/playwright.config.ts`, `e2e/fixture_server.py` |
| Docker | build, run, readiness, UI, headers, non-root, no env files/keys in the image | `scripts/docker_check.py` |
| Flakiness | critical set repeated, no hidden retries | `--flake`, `.github/workflows/flake.yml` |
| Evaluation protection | datasets, baselines and scorer hashed; replay v2/v3 and tenant isolation in the gate | `quality/eval-integrity.json` |

pytest markers (`security`, `reliability`, `contract`, `performance`, `critical`) are registered in `pyproject.toml`.
`critical` is applied by `tests/conftest.py` to a set of files, so no existing test file was edited.

## 4. Coverage thresholds (a ratchet, not a target)

Rule: measured value → rounded down → threshold → raised only by `--ratchet`, never lowered without a reviewed reason.
Measured with coverage.py (branch coverage; percent = covered statements + branches over statements + branches).

COVERAGE_TABLE

Exclusions: none configured for Python. `app/agent/service.py` (the Claude SDK client path) is measured but has no separate
floor because it is exercised through a scripted SDK client, never a live model. Frontend excludes `src/test/**` and
`src/main.tsx` (a one-line bootstrap that only mounts `<App/>`).

## 5. Security policy

* **Static analysis:** Bandit, `app/` only, fail on medium+. Findings are never blanket-suppressed. The eight B608 (string-built
  SQL) findings were each reviewed: they interpolate only fixed column names, whitelisted sort keys or constant table names,
  with every value bound. Each carries an inline `# nosec B608` with that reason. One low B101 (an import-time sanity
  `assert` in a migration) is justified inline; low severity is not gating.
* **Secret scan:** categories are Anthropic/OpenAI-style keys, bearer tokens, AWS/GitHub/Slack/Google credentials, private keys,
  credentials in URLs, hard-coded secret assignments and env-file policy. Output is `file:line: category` only. A git-ignored
  local `.env` is informational; a non-ignored one fails; `.env.example` must hold placeholders. Accepted exceptions
  (deliberately fake values in tests/evals) are in `scripts/secret_scan_allowlist.json`, each with a written reason.
* **Prompt injection:** a named set of nine hostile payloads is run through the real MCP tool path, the agent audit (obedience
  fails closed, model-authored evidence is replaced), the HTTP event boundary (policy, approval and tenant cannot be changed),
  and the existing replay harness on the golden-v3 injection cases.
* **Headers/CSP:** the exact policy is asserted on UI responses and baseline headers on every API response class; the policy
  is not loosened to pass tests.

## 6. Dependency policy

* Python versions are pinned in `constraints.txt` (`pip install -c constraints.txt -e ".[dev]"`; the Dockerfile uses it for the
  runtime image too). Refresh: clean venv → install → `pip freeze --exclude-editable` → re-run the gate → review the diff.
  `pyproject.toml` keeps compatible ranges.
* `pip-audit` runs against the pins; `npm audit` against the lockfile; `npm ci` fails if the lockfile and `package.json`
  disagree. Advisory data being unreachable is a failure.
* Accepted findings live in `quality/dependency-audit-allowlist.json` with a reason and an **expiry date**; the gate fails
  after the expiry. Accepted today: PYSEC-2026-1845 (pytest 8.4.2, dev-only) and GHSA-5gmw-xhrv-c9v3 / GHSA-85c8-ppgw-ccpr
  (tinypool via vitest 3.2.7, dev-only). The fix for the latter is a vitest 5 major upgrade; it was attempted and reverted
  because its worker pool failed to start in this environment. No dependency was upgraded arbitrarily.

## 7. E2E scope

One browser (Chromium), eight scenarios, one spec file, serial, retries disabled, against the real server
(`e2e/fixture_server.py`: temporary database, tenants `acme` and `globex`, scripted investigations, the built UI):
(1) enter a token, (2) incident list, (3) incident detail, (4) AI-labelled investigation with the four categories kept apart,
(5) approval queue, (6) reviewer approves and rejects, (7) operator has no controls and forced requests return 403,
(8) degraded investigation and API failure are visible. It also asserts the token is absent from `localStorage`,
`sessionStorage`, cookies, the page and the URL, and that no CSP violation occurred. Run: `cd frontend && npm run e2e`
(needs `npx playwright install chromium` once).

## 8. Performance methodology

`scripts/perf_smoke.py` starts the application in-process on a temporary SQLite database (demo data plus extra
incidents/workflows/investigations), warms each endpoint, then measures sequential requests and a few concurrent clients for
`/health`, `/incidents`, incident detail, investigations, `/workflow`, the three retrieval endpoints and policy evaluation
(the API call and the engine in-process). It records request count, errors, p50, p95, max as JSON. A regression is: any error;
p95 > max(3 × stored baseline, 50 ms); or a sequential p95 above a 5 s pathological ceiling. The baseline
(`scripts/perf_baseline.json`) was recorded once on a developer machine with `--write-baseline`; CI widens the factor to 6
for shared runners (`PULSEOPS_PERF_FACTOR`). **This is a regression detector, not a benchmark, and supports no capacity or
production claim.**

Findings reported by the harness (nothing was optimised):

* Retrieval is the slow path. `/retrieval/incidents/{id}` and `/retrieval/services/{id}/dependencies` are more than 10× slower
  than the incident list and grow with data volume (about 0.6 s p50 with ~20 incidents and ~1.6 s with ~60 in the sequential
  profile). The likely cause is the graph projection built on demand from SQLite on every request.
* Constructing a service or repository costs ~8 ms because every construction re-runs the idempotent schema statements; that
  is about a third of the incident-list p50.

## 9. Docker validation

`scripts/docker_check.py` builds the repository Dockerfile, starts a container with a random throw-away token (only its hash
is passed), and checks readiness, the UI and its headers, that docs are off and unauthenticated calls are refused, uid
10001, no `.env*` file and no API-key-shaped string anywhere in the image, no Node/npm in the runtime image, and that the
Docker health check reaches `healthy`. The container (and, by default, the image) is always removed.

## 10. Flake detection

`python scripts/quality_gate.py --flake [--flake-runs N]` repeats `pytest -m critical` (event ingestion and idempotency,
tenancy, P9 contracts and HITL boundary, and the P11 security/reliability/contract tests) three times with **no retries and
no rerun plugin**. Any failed repetition fails the check and names the test. It runs weekly and on demand
(`.github/workflows/flake.yml`).

## 11. CI gates

Mandatory on every push and pull request (`.github/workflows/ci.yml`): Python tests + coverage + constraints; frontend
lockfile + tests + coverage + build; replay v2, replay v3, tenant isolation, evaluation integrity; security tests, Bandit,
dependency audit, secret scan; contract + reliability tests and performance smoke. A separate heavier job runs the Docker
build/run and the Playwright E2E. Scheduled/manual: flake detection. Never in CI: live Claude evaluation.

## 12. Defects found and fixed

The P11 tests exposed four genuine defects and one configuration defect. Each has the smallest safe fix and a regression test.

| # | Defect | Fix | Regression test |
|---|---|---|---|
| 1 | **No request-size limit.** The API accepted and stored multi-megabyte bodies (an incident title, workflow details, an event message that is forwarded to the investigator). | ASGI `BodySizeLimitMiddleware` (`app/core/limits.py`): 413 in the standard envelope, default 1 MiB (`PULSEOPS_MAX_BODY_BYTES`). A chunked upload without `Content-Length` is also rejected (as 400 or 413). | `test_oversized_bodies_are_rejected_with_413_and_nothing_is_stored`, `test_chunked_oversized_upload_without_content_length_is_rejected` |
| 2 | **HITL double decision race.** Two reviewers deciding the same pending workflow concurrently both succeeded (the check-then-write was not atomic). | The status change is an atomic compare-and-set (`update_workflow_if_status`); the loser is re-evaluated against the now-final state (409, or an idempotent repeat). | `test_two_reviewers_deciding_the_same_workflow_concurrently_exactly_one_wins` (12 trials), `test_the_same_reviewer_repeating_a_decision_concurrently_is_idempotent` |
| 3 | **Incident id collision overwrote data.** Ids are allocated "highest + 1"; two concurrent creates could pick the same id and `INSERT OR REPLACE` silently replaced the first incident. | A plain `INSERT` for allocation plus retry on the unique-id conflict (`create_incident(replace=False)`). | `test_concurrent_requests_across_tenants_have_no_5xx_no_leakage_and_no_contamination` |
| 4 | **Readiness reported "ready" for a read-only database.** SQLite silently opens a write-protected file read-only, so every write would fail while `/health/ready` said ready. | The readiness check also verifies file and directory writability and takes the write lock (no data is written). | `test_read_only_database_still_reads_refuses_writes_cleanly_and_reports_not_ready` |
| 5 | **A secret could be baked into the Docker image.** `.dockerignore` patterns without `**` match only the context root; a stray `app/agent/.env` (holding an API key, read by nothing) would have been copied by `COPY app ./app`. | `.dockerignore` now excludes env files at every depth. The stray file itself is a developer's local file and was **not** deleted; remove it (and rotate the key if any image built from this tree was shared). | `test_dockerignore_excludes_env_files_at_every_depth`, Docker check "no env file inside the image" |

Bandit's B608/B101 comments are comment-only changes (no behaviour change).

## 14. Known limitations

* There is no rate limiting or lockout; repeated bad tokens are rejected but unthrottled (P10-class).
* A locked or failing database yields a generic 500 envelope (not 503); readiness reports not-ready.
* A chunked oversized upload is rejected as 400 (FastAPI turns the body-read failure into a parse error); declared-length
  uploads get 413.
* Performance numbers describe one machine and an in-process harness; thresholds are relative and generous by design.
* Retrieval latency grows with data volume (graph projection on demand); not optimised.
* The E2E suite is deliberately small (8 scenarios, one browser); no cross-browser or accessibility testing.
* Mutation testing was not run (the suite takes minutes; it would be a one-off exercise on the security/policy modules).
* Dependency scans depend on public advisory feeds, so a new advisory can fail the gate without a code change.
* On a machine whose antivirus intercepts TLS (as the development machine did), npm/pip/Docker network steps need the local CA
  supplied through `NODE_EXTRA_CA_CERTS` / `REQUESTS_CA_BUNDLE`, and the Docker build needed a local-only Dockerfile variant
  (see the report). CI on GitHub is unaffected.

## 15. Migration and rollback notes

* **No schema change.** P11 adds no table or column. The P9 notes (`app.migrations.gate9_1`, `app.migrations.p9`) still apply.
* **New configuration:** `PULSEOPS_MAX_BODY_BYTES` (default 1048576). Clients sending bodies over 1 MiB now get 413.
* **Behaviour changes to be aware of:** a concurrent second decision on a workflow now gets 409 (previously it could also
  succeed); `/health/ready` is stricter (a read-only or write-locked database is not ready); Docker images no longer contain
  env files and install exact versions from `constraints.txt`.
* **Rollback:** revert the P11 change set; it contains no data migration. Source changes are confined to
  `app/core/limits.py`, `app/main.py`, `app/core/{config,errors}.py`, `app/api/routes.py`, `app/services/{workflow,incident}_service.py`,
  `app/repositories/incident_repository.py` plus comment-only `# nosec` annotations.

## 16. Release status

RELEASE_STATUS

## 17. P11 versus the skipped P10

P11 proves the existing local application. P10 would have changed where and how it runs (cloud, PostgreSQL, SSO, secret
manager, hosted monitoring) and none of that was added. Rate limiting, a real session model and cloud-grade observability
remain P10-class and are listed as limitations, not hidden.
