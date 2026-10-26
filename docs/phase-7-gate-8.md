# Phase 7 Gate 8 - Evaluation Integrity & Reliability Hardening

## Purpose

Close the integrity gaps the Gate 7 harness exposed, finish the evaluation work that remained from the original P8
scope, and make the project reproducible and CI-reliable. Gate 8 is bounded: it does **not** add authentication/RBAC,
PostgreSQL, cloud, real Neo4j integration, GitHub integration, RAGAS/DeepEval/an LLM judge, a UI, a full observability
stack, autonomous remediation or any Gate 9 work. Related issues found along the way are listed under "Out-of-scope
findings" and were not fixed.

## What changed

| # | Area | Change |
|---|---|---|
| 1 | Database | `PULSEOPS_DATABASE_URL` drives the application; `sqlite:///./x.db` is relative to the working directory (it used to resolve to the filesystem/drive root, which fails for a non-root Linux user). `sqlite:////abs/x.db` is absolute; legacy `sqlite:/abs` and `sqlite:C:/abs` still work. `DatabaseManager` pins an absolute path at start. |
| 2 | MCP subprocess | The agent passes `PULSEOPS_DATABASE_URL` (resolved to an absolute `sqlite:` URL) to the MCP subprocess, so its working directory cannot change which database it reads. Verified with a real MCP subprocess started from a different directory. |
| 3 | Ungrounded results | `_ungrounded_result` keeps **nothing the model said**: evidence, hypotheses, confidence, recommendations and missing information. Only system-authored reasons, recorded tool failures and required next steps remain. Grounded results are unchanged. |
| 4 | Investigation outcome | `investigation_status` is `completed` / `degraded` / `failed` (see below). DEGRADED and FAILED fail closed. |
| 5 | Failure semantics | System/investigation failure is never represented as policy `DENY`: `policy_decision` is `investigation_pending` (hold), `investigation_degraded` or `investigation_failed`; `failure_reason` is explicit. `DENY` stays a genuine deterministic policy decision. |
| 6 | Dataset v2 | `golden-v2`: the 12 `golden-v1` cases preserved + 12 new (24 total). |
| 7 | Retrieval ground truth | New deterministic dataset for the four retrieval tools and a `retrieval_correctness` system metric. |
| 8 | Tool selection | New `tool_selection` AI-quality metric. |
| 9 | Latency | Informational timings per case and as a run summary. Never gated, not in the baseline. |
| 10 | Content hashing | The baseline records a sha256 of both datasets; same label + changed content fails. Baseline is now version 2 (written explicitly). |
| 11 | CI | New `ci.yml` (full suite + replay on Linux / Python 3.11, no secrets). `evals.yml` is manual-only. |
| 12 | Docs | This document; stale references reconciled (below). |

Also: tests now run against an isolated temporary database (`tests/conftest.py`) and the old tests no longer use
`./pulseops*.db`; `python -m evals` uses a throwaway database unless one is configured; the live smoke script no longer
requires the undeclared `python-dotenv` package at import time (it broke test collection on a clean Linux install).

## Investigation outcome contract

| Status | Meaning | Decided by | Workflow |
|---|---|---|---|
| `completed` | grounded evidence was retrieved; valid result | the agent's audited telemetry (`grounded`), not the model | policy applied: allow / notify / hitl_required / deny |
| `degraded` | grounding could not be established (`failure_reason: investigation_ungrounded`) | `telemetry.grounded == false` | terminal `rejected`, `policy_decision: investigation_degraded` |
| `failed` | the investigation errored: SDK/model/tool failure, invalid or wrong-incident result (`failure_reason: investigation_failed`) | exception or invalid result | terminal `rejected`, `policy_decision: investigation_failed` |

A partial tool failure stays `completed` only when the successful context is enough to ground the result; otherwise the
result is `degraded`. DEGRADED and FAILED are never policy-evaluated, never notified, never HITL-routed, and approval
attempts return 409 ("already in a final state"). A bare result without telemetry (test stubs) is classified by the
agent's own invariant: grounded results always carry evidence.

n8n reports `investigation_degraded` / `investigation_failed` as 502 with the `failure_reason`; it makes no policy
decision. Audit records `INVESTIGATION_DEGRADED` or `INVESTIGATION_FAILED` (exception type only), then `WORKFLOW_FAILED`.

## Evaluation changes

- **Dataset `golden-v2`** (`evals/datasets/golden_incidents.json`): new cases c13-c24 - memory leak, authentication
  failure, network timeout, insufficient capacity, ambiguous cause, missing logs, low-confidence evidence, model timeout
  (scripted SDK error), incomplete tool response (truncated context object), and three injection channels (incident
  description, metric field, a non-context tool result). Every new case has a unique id, a description, an
  `expected_behavior`, expected tools, expected evidence where applicable, a safety expectation and deterministic
  scoring criteria. A test pins that the 12 `golden-v1` ids are preserved, in order.
- **Retrieval ground truth** (`evals/datasets/retrieval_ground_truth.json`, `evals/retrieval.py`): an eval-only fixture
  (two services, four incidents, scoped logs/metrics/deployments) and 13 checks across `get_incident_context`,
  `get_related_incidents`, `get_service_repository`, `get_service_dependencies`, including not-found, empty and
  cross-incident leakage cases. Score = fraction of atomic expectations met; the metric is `retrieval_correctness`
  (system group, must stay 1.00). No vector search, no LLM.
- **`tool_selection`** (AI quality): `recall(expected tools) x precision(actual vs expected + optional)` using the
  SDK-audited tool calls. Not every tool is required, and calling more tools never raises the score.
- **Latency**: per-case `investigation_ms`, `scoring_ms`, `workflow_ms` (end-to-end `/workflow/events` round trips for
  policy probes) and a run summary (count, mean, p50, max, total). In replay, `investigation_ms` times the scripted replay
  through the real agent code, not model latency. Not gated; excluded from the baseline. No token/cost tracking.
- **Content hash** (`evals/hashing.py`): sha256 of canonical JSON (sorted keys, no insignificant whitespace). Changing any
  value, key or list order changes it; reformatting does not.
- **Baseline v2** (`evals/baselines/baseline.json`): records `dataset_sha256` and `retrieval_dataset_sha256`. A baseline
  without hashes is rejected rather than silently accepted. It was written explicitly with
  `python -m evals baseline --confirm-overwrite --reason ...`; a normal run never writes it.
- **Live evaluation**: with the database configurable, live cases now run over their own temporary fixture database (the
  agent's MCP subprocess receives it), and the grounding corpus is fetched independently from the same real retrieval
  tools. `live_eligible` now means "reproducible over a real database with no scripted failure" (19 of 24 cases).
- **`failure_behavior`**: the Gate 7 "observation" about passed-through recommendations is now a hard failure.

## Test isolation

`tests/conftest.py` forces `PULSEOPS_DATABASE_URL` to a per-session temporary database before any `app` import, so no test
reads or writes a developer's `pulseops.db`. The P5/P6 literals became `get_settings().database_url`; the P7 workflow
persistence tests use `tmp_path`. Existing `D:\pulseops*.db` files are left untouched.

## CI

`.github/workflows/ci.yml` (push/PR, `ubuntu-latest`, Python 3.11, no secrets, no API key, no live Claude):
1. `python -m pytest -q` - the full suite.
2. `python -m evals replay --out eval-reports` - fails on regression, a failed system threshold, or changed dataset
   content; uploads the reports and writes the Markdown report to the job summary.

`.github/workflows/evals.yml` is `workflow_dispatch` only, so there is no duplicate automatic run.

**Linux verification (local, equivalent to the runner):** a throwaway `python:3.11-slim` container, **as a non-root user**
(uid 1000), a writable copy of the repo, a fresh venv, `pip install -e ".[dev]"`, then the full suite and the replay.
Before Gate 8 this failed at collection ("unable to open database file", plus the `dotenv` import); both are fixed. The
workflow files themselves have not run on GitHub; their YAML was parsed in a throwaway container.

## Manual verification procedure

1. Run PulseOps against an isolated database: `PULSEOPS_DATABASE_URL=sqlite:///./manual.db` (relative to the working
   directory) and `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`.
2. Start n8n (`docker compose -f docker-compose.n8n.yml up -d`), import `n8n/pulseops-event-workflow.json`, publish it.
3. Post events as in `docs/phase-7-gate-6.md`. Expected: LOW -> 200 `NOTIFIED_SIMULATED`; `requested_action: restart_service`
   -> 202 `HITL_PENDING`; `delete_data` -> 403 `DENIED`; duplicate -> `idempotent_replay: true`; malformed -> 400.
4. Degraded: make the incident context unretrievable (MCP down) -> 502 `investigation_degraded`; `GET /workflow/<id>` shows
   `rejected` + `policy_decision: investigation_degraded` (not `deny`); approval -> 409.
5. Failed: run without `ANTHROPIC_API_KEY` or with the model unreachable -> 502 `investigation_failed`; `policy_decision:
   investigation_failed`; approval -> 409.

## Known limitations

- **Replay is agent validation, not model quality.** Scripted SDK output is authored in the dataset (see Gate 7).
- Live evaluation still excludes cases whose failure is scripted, and has never been run here (no API key configured).
- `tool_selection` in replay measures the audited scripted calls; it is only meaningful about the model in live mode.
- Latency numbers in replay are not model latency.
- Keyword rubrics remain crude; semantic hallucination is still not detected (Gate 7 fabrication-scorer boundary).
- A first-seen event that crashes mid-processing leaves its claim "processing" - **resolved in Gate 9** (stale-claim recovery).
- Existing P5 test helpers still build agents with the test settings database; they are isolated, not rewritten.

## Out-of-scope findings (documented, not fixed - future gates)

- Authentication, RBAC, real HITL identity - **implemented in Gate 9** (bearer API credentials; SSO/OIDC remain deferred).
- PostgreSQL / production persistence; secrets management (default Neo4j password in config and compose).
- Request IDs, token/cost telemetry, full observability, production monitoring.
- n8n webhook authentication and version pinning (`:latest`); production Docker hardening (non-root user, healthcheck, a
  PulseOps service in compose).
- Neo4j runtime integration; cloud deployment; frontend.
- `get_related_incidents` defaulted to the hard-coded incident `INC-1007` - **resolved in Gate 9**.
- `get_service_dependencies` is a same-environment heuristic and is only generated for services with a repository mapping
  (pinned in the retrieval ground truth as a known deviation).
- `DatabaseManager` re-seeds any empty table on start; `WorkflowStatus.AUDITED` is unused; ALLOW/NOTIFY workflows stay
  `pending` forever; raw untrusted text is stored unredacted in audit metadata.
- The stray `D:\pulseops.db`, `D:\pulseops_gate4.db` and `D:\pulseops_phase7.db` from earlier runs are no longer used by
  anything; they were not touched and can be removed manually.

## Documentation reconciliation

1. **Authoritative roadmap:** `project-plan.md` (newer, fuller, used by the Gate prompts). `IMPLEMENTATION-ROADMAP.md` is
   older and is kept only as sequencing guidance for production hardening (its Phase 9 list). Authority notes were added
   to both files.
2. `CLAUDE.md` and `docs/claude-code-context.md` pointed at a non-existent `plan.md`; they now say `project-plan.md`.
3. **Neo4j:** not connected at runtime. 4. **Ontology:** `pulseops.ttl` is a design artifact, not loaded by code.
5. **SQLite:** the only persistence. 6. **Graph projection:** computed in-process from SQLite. Recorded in
   `docs/architecture.md` ("Current runtime reality"), with pointers from `docs/knowledge-graph.md` and `docs/ontology.md`.
7. **`project-plan.md.md`:** a stale 9 KB earlier draft (about 1,180 differing lines). Recommendation: archive it outside
   the repo or delete it. It was **not** deleted or renamed in this gate.

## Verification results

See the Gate 8 final report for exact counts. Summary at the time of writing: full suite 186 tests passing on Windows and
in the Python 3.11 non-root Linux container; replay gate PASS; negative control fails correctly; a dataset hash change
fails the gate with a non-zero exit code; n8n manually verified for LOW, HITL, DENY, DEGRADED and FAILED (with a
scripted SDK client under the real agent code, not live Claude).
