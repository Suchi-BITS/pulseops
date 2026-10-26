# Phase 7 Gate 6 — n8n Workflow Integration

n8n is the **orchestration layer only**. Every business decision stays in PulseOps.

| Component | Responsibility |
|---|---|
| n8n | Webhook, boundary validation, call PulseOps, branch on the returned result, respond |
| PulseOps | Business logic, event idempotency, incident creation, workflow state, audit |
| Claude Agent SDK / Incident Agent (P6) | Reasoning — invoked by PulseOps, never by n8n |
| MCP | Controlled tool boundary used by the Incident Agent |
| Policy Engine | Deterministic safety decision (ALLOW / NOTIFY / HITL_REQUIRED / DENY) |
| HITL | Human authorization through the existing approval API |

n8n never talks to Claude, MCP, Neo4j or SQLite, does not create incidents, does not own idempotency, and
makes no policy decision.

## Why `POST /workflow/events` exists

`POST /workflow/evaluate` acts on an *existing* incident. Gate 6 introduces an operational-event ingestion
boundary: something has to create or resolve the incident, correlate `event_id`, enforce event-level
idempotency, run the Incident Agent, and only then evaluate policy. That must live in PulseOps, not be spread
across n8n nodes. The endpoint is thin; the logic is in `app/services/event_service.py`
(`OperationalEventService`). Existing endpoints, the policy engine, HITL enforcement and the workflow
idempotency/audit mechanisms are reused unchanged.

## Flow

```
Operational event
 -> n8n Webhook  POST /webhook/pulseops-event
 -> Validate Event (shape only)           malformed -> 400, never reaches PulseOps
 -> POST /workflow/events                 (no retries, 120 s timeout)
      PulseOps: claim event_id (durable) -> create incident -> workflow created (held rejected / investigation_pending)
             -> Phase 6 Incident Agent (INVESTIGATION_STARTED / COMPLETED | FAILED)
             -> deterministic policy -> workflow state -> response
 -> Inspect Result -> Switch
      ALLOW / NOTIFY  -> simulated notification   200 NOTIFIED_SIMULATED
      HITL_REQUIRED   -> HITL pending             202 HITL_PENDING (+ approval instructions)
      DENY            -> denied                   403 DENIED
      error / investigation not completed -> fail closed (4xx/502)
```

## Event contract

All fields required except `metadata`. All values are untrusted.

```json
{"event_id":"...","event_type":"...","timestamp":"ISO-8601","service_id":"...",
 "severity":"low|medium|high|critical","source":"...","message":"...","metadata":{}}
```

- `service_id` must be a known service (otherwise 400; the event_id is not consumed, so a corrected event can be resent).
- `message` and `metadata` are stored as evidence. They are never interpreted as instructions and never placed in the agent objective.

## `metadata.requested_action`

Optional. If absent the action is deterministically `notify`. The value is untrusted: it is normalized
(case, `-`, `/`, whitespace) and evaluated by the **existing** policy registry. The event cannot override
policy; `severity`, `risk_level`, `requires_approval` etc. in the event have no effect on the decision.

| requested_action | Result |
|---|---|
| (absent) / `notify` | LOW / ALLOW |
| `page_oncall` | MEDIUM / NOTIFY |
| `restart_service`, `deploy` | HIGH / HITL_REQUIRED |
| `delete_data` | HIGH / DENY |
| anything unknown | DENY (fail closed) |

## Idempotency and correlation

- Durable event idempotency: table `operational_events` (`event_id` PRIMARY KEY). The first delivery claims
  the id atomically; concurrent duplicates cannot create a second incident or workflow.
- Replay (same `event_id`, same content): returns the existing incident/workflow with
  `idempotent_replay: true`. No new incident, workflow, audit row or investigation. A concurrent duplicate
  waits (up to 120 s) for the first delivery to finish, then returns the same result.
- Same `event_id`, different content: 409.
- The workflow also carries the existing workflow idempotency key `event:<event_id>`.
- `event_id` is the correlation id (`correlation_id`). Responses carry `event_id`, `incident_id`,
  `workflow_id`, `idempotency_key`, `correlation_id`; n8n adds `n8n_execution_id`.
- A failed investigation is terminal for that `event_id` (replays do not retry). Send a new event to retry.
- If the PulseOps process dies mid-processing, the claim stays "processing" and replays return 409
  (fail closed, needs operator attention).

## Investigation (Phase 6 Incident Agent)

After the incident exists, `OperationalEventService` invokes the existing `IncidentInvestigationAgent`
(Claude Agent SDK + MCP) through `build_investigator`. No second agent, no MCP bypass. The workflow is
created **held as `rejected` with `policy_decision = investigation_pending`** while the investigation runs (a hold,
not a policy decision), so it cannot be approved early; only after a COMPLETED investigation is the deterministic
policy outcome applied.

The investigation is evidence/analysis only. It does not decide risk, approval, the policy decision or
whether an action is safe. Its result (summary / evidence / hypotheses / recommendations / confidence) is
recorded in the audit trail and returned as `investigation`.

**Investigation outcome (Gate 8 contract).** `investigation_status` is exactly one of:

| Status | Meaning | Workflow |
|---|---|---|
| `completed` | grounded evidence was retrieved and a valid result was produced | policy outcome applied (allow / notify / hitl_required / deny) |
| `degraded` | the investigation could not establish grounded context (`failure_reason: investigation_ungrounded`) | terminal `rejected`, `policy_decision = investigation_degraded` |
| `failed` | the investigation itself failed: SDK/model/tool error, invalid or wrong-incident result (`failure_reason: investigation_failed`) | terminal `rejected`, `policy_decision = investigation_failed` |

`degraded` is decided from the agent's own audited telemetry (`telemetry.grounded`, i.e. the incident context was
actually retrieved through MCP), never from the model's claims. A partial tool failure stays `completed` only when
the retrieved evidence is sufficient; otherwise the result is `degraded`. DEGRADED and FAILED both fail closed:
no policy evaluation, no notification path, no HITL, and approval attempts return 409 (final state).

**`DENY` is reserved for genuine deterministic policy denials.** An investigation/system failure is never
represented as `deny`: `policy_decision` is `investigation_degraded` / `investigation_failed`, `policy_reason` is
null (the policy engine never evaluated it), and `failure_reason` says why. Audit records `INVESTIGATION_FAILED`
(exception *type* only, no message or secrets) or `INVESTIGATION_DEGRADED`, then `WORKFLOW_FAILED`. For a degraded
result Phase 6 returns only system-authored guidance: no model evidence, hypotheses, confidence, recommendations or
missing information survive (see Gate 8).

## Audit (source of truth: PulseOps)

Success: `INCIDENT_RECEIVED` → `WORKFLOW_CREATED` → `INVESTIGATION_STARTED` → `INVESTIGATION_COMPLETED` →
`POLICY_EVALUATED` → `HITL_REQUESTED` (HITL) | `NOTIFICATION_REQUESTED` (ALLOW/NOTIFY) |
`WORKFLOW_FAILED` (DENY). Approval later adds `HITL_APPROVED`/`HITL_REJECTED` and `WORKFLOW_COMPLETED`/
`WORKFLOW_FAILED`. ALLOW/NOTIFY workflows stay `pending` (nothing is executed; notification is simulated by n8n).
Failure: `INCIDENT_RECEIVED` → `WORKFLOW_CREATED` → `INVESTIGATION_STARTED` → `INVESTIGATION_FAILED` → `WORKFLOW_FAILED`.
Degraded: the same, with `INVESTIGATION_DEGRADED` in place of `INVESTIGATION_FAILED`.
n8n execution history is n8n's own record and does not replace this.

## HITL and DENY

- HITL_REQUIRED: workflow stays `pending`, `requires_approval: true`, nothing executed. n8n returns the
  approval instructions; a human decides through the existing `POST /workflow/{workflow_id}/decision`.
  n8n cannot approve; AI-named reviewers are rejected (409).
- DENY: terminal `rejected`; cannot be overridden or approved (409).

## n8n error handling

| PulseOps result | Webhook response |
|---|---|
| malformed event (n8n check) | 400 `REJECTED` |
| 400 / 422 | 400 `rejected_by_pulseops` |
| 404 | 404 `not_found` |
| 409 | 409 `conflict` |
| 5xx / unreachable / timeout | 502 `pulseops_unavailable` / `pulseops_error` |
| unknown shape or decision | 502 `unexpected_response` |
| `investigation_status = degraded` | 502 `investigation_degraded` (with `failure_reason`) |
| `investigation_status = failed` | 502 `investigation_failed` (with `failure_reason`) |

No stack traces, credentials or raw errors are returned (only a 300-char `detail` for 404/409/investigation).
No secrets are stored in the workflow.

## Files

`app/api/workflow.py` (thin endpoint), `app/services/event_service.py`, `app/services/workflow_service.py`
(optional `investigate` argument, additive), `app/repositories/incident_repository.py`
(`OperationalEventRepository`), `app/database.py` (`operational_events`), `app/models/schemas.py`,
`n8n/pulseops-event-workflow.json`, `docker-compose.n8n.yml`, `tests/test_phase7_gate6.py`.

## Port 8000 caveat

On the development machine another Docker container (`sla-backend`, unrelated project) also publishes host
port 8000. If it is running, `host.docker.internal:8000` may not reach PulseOps. Before using the workflow,
confirm from the n8n container:

```
docker exec pulseops-n8n wget -qO- http://host.docker.internal:8000/health   # must contain "app":"PulseOps"
```

If it does not, stop that container or run PulseOps on a free port and change the URL in the
"PulseOps Workflow API" node. No infrastructure was changed for this.

## Manual verification

1. Start PulseOps: `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000` (needs `ANTHROPIC_API_KEY`
   for a real investigation; without it every event fails closed, which is itself a valid check).
2. `docker compose -f docker-compose.n8n.yml up -d`, open http://localhost:5678, create the local owner.
3. Import `n8n/pulseops-event-workflow.json`; test with "Execute workflow" and
   `http://localhost:5678/webhook-test/pulseops-event`, or publish it and use `/webhook/pulseops-event`.

```bash
curl -X POST http://localhost:5678/webhook/pulseops-event -H 'content-type: application/json' -d '{
  "event_id":"demo-001","event_type":"latency_spike","timestamp":"2026-01-01T00:00:00Z",
  "service_id":"svc-payment","severity":"low","source":"synthetic",
  "message":"p99 latency above threshold","metadata":{}}'
```

| Check | Event change | Expected |
|---|---|---|
| LOW | as above | 200 `NOTIFIED_SIMULATED`, allow, `investigation.status: completed` |
| Duplicate | resend identical | 200, same ids, `idempotent_replay: true` |
| Conflict | same `event_id`, other content | 409 |
| HITL | `"metadata":{"requested_action":"restart_service"}` | 202 `HITL_PENDING`, pending, approval path |
| DENY | `"metadata":{"requested_action":"delete_data"}` | 403 `DENIED`; approval attempt → 409 |
| Malformed | omit `event_id` / `"metadata":[]` | 400, nothing reaches PulseOps |
| Investigation failure | run without `ANTHROPIC_API_KEY` | 502 `investigation_failed`; `GET /workflow/<id>` shows rejected, `policy_decision: investigation_failed` (not `deny`) + `INVESTIGATION_FAILED` |
| Degraded investigation | MCP unavailable / context not retrievable | 502 `investigation_degraded`; rejected, `policy_decision: investigation_degraded`; approval → 409 |
| Unavailable | stop PulseOps | 502 `pulseops_unavailable` |

Audit: `GET /workflow/<workflow_id>` on PulseOps.

## Verified

Automated tests use a temporary database and a stubbed investigator (no live Claude calls). The n8n workflow
was exercised end to end in a throwaway n8n container against a PulseOps instance with a stubbed
investigator (LOW, duplicate, HITL, DENY, conflict, malformed), and against the real agent without an API
key (fail closed). A live Claude investigation has not been run.

## Update (Gate 9): authentication and Compose networking

The webhook now requires a Header Auth credential, and n8n calls PulseOps with a dedicated `service_n8n` bearer credential
(ingest/read only; it cannot approve). n8n reaches PulseOps at `http://pulseops:8000` on the `pulseops-net` Docker network
instead of `host.docker.internal`. The workflow JSON holds credential references only. The 120 s timeout, disabled retries,
idempotency and fail-closed behaviour are unchanged. Everything above about ports and `host.docker.internal` describes the
Gate 6 setup; the canonical platform is now `docker-compose.yml` (see `docs/phase-7-gate-9-implementation.md`).

