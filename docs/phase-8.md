# Phase 8 — Evaluation Maturity

Builds on Gate 7/8 (harness, `golden-v2`, baseline v2, replay + live) without rebuilding it. Increments: P8.0 observability,
P8.1 tenant isolation evaluation, P8.2 golden dataset v3, P8.3 scorer strengthening, P8.4 first live evaluation, P8.5 run history.
All six increments are implemented (see the status table). No real Claude model has been evaluated: see P8.4.

## P8.0 — Evaluation observability

Reports now carry latency, token and cost information. It is **informational**: it never affects pass/fail, regression
detection or the baseline, and it adds no metric to the system or quality groups.

* **Source.** The existing `agent.last_telemetry` (`InvestigationTelemetry`: `model`, `duration_ms`, `api_duration_ms`,
  `usage`, `total_cost_usd`). No second telemetry system. Code: `evals/observability.py`.
* **Contracts (extended minimally).** `CaseScore.telemetry: CaseTelemetry | None` and `EvalReport.telemetry: TelemetryTotals | None`.
  Existing fields are unchanged; `timings` and `timings_ms` keep their meaning.
* **Unknown stays unknown.** A value the SDK did not provide is `null` in JSON and `n/a` in Markdown, never `0`. Cost is only
  what the SDK reports; no pricing is stored and nothing is estimated. `total_tokens` exists only when both input and output
  were reported. A run total is `null` when no case reported the quantity.
* **Per case:** `latency_kind`, `model`, `investigation_ms`, `agent_duration_ms`, `api_duration_ms`, `input_tokens`,
  `output_tokens`, `total_tokens`, `usage`, `total_cost_usd`, `telemetry_available`.
* **Per run:** `mode`, `latency_kind`, `model`, `models_observed`, case counts with telemetry/tokens/cost, summed
  input/output/total tokens, summed cost, and a note. Latency statistics (count, mean, p50, max) remain in `timings`.
  Dataset version and sha256 stay at the report top level and are repeated in the Markdown section.

| | Replay | Live |
|---|---|---|
| `latency_kind` | `harness_replay`: scripted replay through the real agent code, **not model inference latency** | `live_model_inclusive` |
| Model, tokens, cost | always `null`, even if scripted messages carry them (the model is a script) | as reported by the SDK, else `null` |
| States | "Replay does NOT measure Claude/model quality" in the banner, note and Markdown | non-deterministic, never compared with the baseline |
| CI | runs in `ci.yml` | not run in CI; a skipped live run has no telemetry |

Report output: JSON `telemetry` fields and a Markdown section "Observability (informational, never gated)".

Not done in P8.0 (later increments or out of scope): tenant evaluation, new dataset or baseline versions, scorer changes,
a live run, run history, cost budgets, pricing tables.


## Status

| Increment | Status |
|---|---|
| P8.0 observability | implemented, verified |
| P8.1 tenant isolation evaluation | implemented, verified (replay, deterministic) |
| P8.2 golden dataset v3 | implemented, verified (replay) |
| P8.3 scorer strengthening | implemented, verified (replay and unit negative controls) |
| P8.4 first live evaluation | live pathway implemented and tested with fakes; **no real live run was performed** |
| P8.5 run history | implemented, verified |

## P8.1 — Tenant isolation evaluation

`evals/tenant.py`, new system metric `tenant_isolation` (must stay 1.00; part of the existing system floor, so a drop fails the
gate on every dataset). Eight deterministic, model-free checks run the real production components over one temporary
database holding two tenants that **share ids** (`svc-payment`, `INC-T1`) plus data only tenant A has:
MCP same-id isolation, MCP foreign resources (not found / empty), repository and graph scoping (every node carries
`tenant_id`), workflow and audit isolation, cross-tenant HITL (tenant B's fully privileged reviewer gets 404; the service
principal 403; the owning tenant's reviewer succeeds), event deduplication and idempotency per tenant, the agent/MCP tenant
boundary (MCP env bound to the principal's tenant, no tenant tool argument, refusal without a tenant), and membership roles
(reviewer in A, operator in B, inactive/missing fail closed). Tests include negative controls that break isolation and
show the metric and the gate fail. Report section: "Tenant isolation". No production code changed.

## P8.2 — Golden dataset v3

`evals/datasets/golden_incidents_v3.json` (`golden-v3`): the 24 golden-v2 cases verbatim and in order + 8 new cases
(c25 unsupported-cause trap, c26 paraphrase tolerance, c27 two plausible causes, c28 unmapped repository, c29 contradicting
signals, c30 injection with an unsupported cause, c31 unsupported deployment claim, c32 strong evidence). It is additive and
has its own baseline `evals/baselines/baseline-v3.json` (version 1, written explicitly with
`python -m evals baseline --dataset v3 --reason ...`). `golden_incidents.json`, `retrieval_ground_truth.json` and `baseline.json`
(golden-v2, baseline v2) are byte-for-byte unchanged and remain the default (`python -m evals replay`). Select v3 with
`--dataset v3`. CI runs both replays.

## P8.3 — Scorer strengthening

Deterministic and dataset-declared; it can only match *more* than before in the quality group, so golden-v2 scores did not move.
* Rubric keywords match by substring (previous behaviour), then light stemming (`exhaust` ~ `exhausted` ~ `exhaustion`), then
  the case's `synonyms`. Used by `relevance` and `hypothesis_quality`.
* `unsupported_claims` (new `Expected` field): keyword groups naming causes the evidence does not support. A summary,
  hypothesis or recommendation containing all keywords of a group (stem-matched, so paraphrases and inflections count), when
  the retrieved data does not contain them all, fails `fabrication_detection`.
* Limits: it finds the causes a case author listed, not arbitrary invented ones, and it ignores negation. No judge, no
  embeddings, no LLM: an optional semantic check was **not** added.

## P8.4 — Live evaluation (opt-in)

`python -m evals live --confirm-live [--limit N] [--max-cost-usd X] [--model M]`.
* Never run by CI or the test suite. With a key and no `--confirm-live` it refuses with a clear message (exit 0 like a skipped run, nothing runs); with
  `--confirm-live` and no key it fails clearly (exit 3); with neither it stays a SKIPPED, exit-0 non-failure (as before).
* `--max-cost-usd` stops before starting the next case once the **SDK-reported** cost reaches the cap. If a case reports no
  cost the cap cannot be enforced, so the run stops after that case. Cost is never estimated; no pricing is stored.
* Reports and history never contain the API key. Live results are never compared with a baseline or used as a gate.
* Telemetry: only fields that exist on `agent.last_telemetry` are read; missing or malformed values stay null/n/a.
  `investigation_ms` is total investigation time (model + tools), not model latency.
* **Verified:** the pathway, refusal/failure modes, cost cap, report contract and secret hygiene, using a fake agent.
  **Not verified:** a real model run, real SDK token/cost field shapes, real-model quality. No such run was performed.

## P8.5 — Run history

Every completed `replay` or `live` CLI run appends one compact line to `<out>/history/history.jsonl` (run id, timestamp,
mode, model, dataset version/hash, case count, pass flag, mean score per metric, latency mean/p50, tokens, cost).
`python -m evals history [--mode replay|live] [--last N]` prints a table with the metric change versus the previous run of the
same mode and dataset. Informational only: it never affects pass/fail or any baseline, skipped runs are not recorded, and a
torn line is ignored. The file is local; durable shared history and dashboards are a later platform concern.

## Verification commands

```
.venv\Scripts\python.exe -m pytest -q                      # full suite (Windows)
.venv\Scripts\python.exe -m pytest -q tests/test_phase8_0.py tests/test_phase8.py
.venv\Scripts\python.exe -m evals replay                   # golden-v2, baseline v2
.venv\Scripts\python.exe -m evals replay --dataset v3 --out eval-reports/v3
.venv\Scripts\python.exe -m evals history
```
Linux: the python:3.11-slim non-root container procedure used in Gates 8-9 (full suite + `python -m evals replay`).
Observability (latency, tokens, cost, model) and history remain informational and never gate pass/fail.
