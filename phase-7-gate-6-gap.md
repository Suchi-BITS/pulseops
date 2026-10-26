Proceed with Gate 6 implementation based on the review.

DECISION

Keep the new:

POST /workflow/events

Do NOT rework Gate 6 to force n8n through the existing /workflow/evaluate endpoint.

Rationale:
POST /workflow/evaluate operates on an existing incident, while Gate 6 introduces an operational-event ingestion boundary. Creating the incident, correlating event_id, enforcing event idempotency, invoking the Incident Agent, and then evaluating policy must remain inside PulseOps rather than being distributed across n8n.

REQUIRED GATE 6 FLOW

Operational Event
→ n8n Webhook
→ basic boundary validation
→ POST /workflow/events
→ event idempotency/correlation
→ create or resolve incident
→ existing Phase 6 Incident Agent
→ InvestigationResult
→ existing deterministic Policy Engine
→ workflow state
→ ALLOW / NOTIFY / HITL_REQUIRED / DENY
→ response to n8n

IMPORTANT:
Do not duplicate these responsibilities in n8n.

1. KEEP /workflow/events

Keep the new endpoint as the PulseOps operational-event boundary.

It must remain thin at the API layer and delegate business logic to appropriate application services.

2. ADD THE EXISTING PHASE 6 INVESTIGATION STEP

Inspect the actual current Phase 6 Incident Agent implementation before changing anything.

Do not rewrite the Agent SDK/MCP implementation.

Reuse the existing IncidentInvestigationAgent / investigation service.

After an operational event has been accepted and an incident has been created/resolved, invoke the existing Incident Agent for that incident.

The investigation must occur before policy evaluation.

Do not create a second agent implementation.

Do not bypass MCP.

Do not call Claude directly from n8n.

Do not connect n8n directly to MCP, Neo4j, SQLite, or Claude.

3. EVENT IDEMPOTENCY

event_id must provide durable event-level idempotency.

Two concurrent first deliveries of the same event must not create two incidents.

Required behavior:

First event:
event_id E1 → create incident INC-X

Repeated event:
event_id E1 → return the existing result/incident/workflow

Concurrent duplicate:
E1 + E1 → exactly one incident/workflow

Do not rely on n8n to maintain event idempotency.

Use the existing PulseOps persistence layer.

If a new persistence structure is required, keep it minimal and scoped to Gate 6.

4. REQUESTED ACTION

The existing Gate 6 implementation currently derives action from:

metadata.requested_action

Make this explicit and documented rather than leaving it as an implementation invention.

Use:

metadata.requested_action

as an optional field.

If absent, default deterministically to:

notify

The requested action is untrusted input.

Normalize and validate it through the existing deterministic policy registry.

The event must never be able to override policy.

Examples:

notify
→ LOW / ALLOW according to existing policy

page_oncall
→ MEDIUM / NOTIFY according to existing policy

restart_service
→ HIGH / HITL_REQUIRED

delete_data
→ HIGH / DENY

Unknown action
→ DENY

Do not create a second policy system.

5. INVESTIGATION FAILURE

Fail closed if the Incident Agent cannot produce a valid investigation result.

Do not fabricate an InvestigationResult.

Do not allow n8n to interpret a missing/invalid investigation as success.

Preserve useful failure information in PulseOps audit/workflow state without exposing secrets.

6. POLICY AUTHORITY

The existing deterministic PulseOps Policy Engine remains authoritative.

The LLM/Incident Agent must not decide:

- risk level
- approval requirement
- policy decision
- whether an action is safe

The investigation result is evidence/analysis only.

7. HITL

For HITL_REQUIRED:

- create/retain the pending workflow
- return the appropriate workflow status to n8n
- do not execute the consequential action
- n8n must not approve the action
- human approval must continue through the existing PulseOps approval API

For DENY:

- terminal denied/rejected state
- n8n cannot override it

8. AUDIT

Preserve PulseOps as the audit source of truth.

At minimum ensure the event lifecycle can be reconstructed:

INCIDENT_RECEIVED
WORKFLOW_CREATED
INVESTIGATION_STARTED
INVESTIGATION_COMPLETED
POLICY_EVALUATED
HITL_REQUESTED / relevant notification event
WORKFLOW_COMPLETED / WORKFLOW_FAILED

Use the existing audit mechanisms where possible.

9. N8N

Keep n8n as orchestration only.

Target workflow:

Webhook
  ↓
Validate Event
  ↓
HTTP Request → POST /workflow/events
  ↓
Inspect Result
  ↓
Switch
 ├── ALLOW / NOTIFY → simulated notification
 ├── HITL_REQUIRED → return/display HITL pending
 ├── DENY → return denied
 └── error → fail closed

Do not add AI Agent nodes.

Do not duplicate policy logic in n8n.

Do not make n8n responsible for idempotency.

Do not make n8n responsible for incident creation.

10. PORT 8000

Inspect the existing Docker/container port mappings.

There is currently another container reported as publishing port 8000.

Verify that:

n8n Docker
→ host.docker.internal:8000
→ PulseOps FastAPI

is deterministic.

Do not make unrelated infrastructure changes.

11. DEV DATA

The existing Gate 6 end-to-end test created INC-1123 through INC-1125 in the development database.

Do not delete data destructively.

If cleanup is required for deterministic tests, use the existing test database/test fixtures rather than destructive manual deletion.

12. TESTS

Extend the Gate 6 tests to cover:

- valid operational event
- event creates/resolves incident
- event idempotency
- concurrent duplicate event behavior
- conflicting duplicate event
- Phase 6 investigation is invoked
- valid InvestigationResult is propagated/handled
- investigation failure fails closed
- default requested_action = notify
- explicit requested_action
- unknown action → DENY
- LOW/ALLOW
- MEDIUM/NOTIFY
- HIGH/HITL_REQUIRED
- DENY
- prompt injection/untrusted event text
- 400 malformed event
- 404 where applicable
- 409 conflict
- audit trail
- correlation identifiers
- n8n-compatible response

Use mocks/stubs for the Agent SDK in deterministic tests where appropriate. Do not make the unit test suite depend on live Claude API calls.

13. DOCUMENTATION

Update:

docs/phase-7-gate-6.md

to document:

- why /workflow/events exists
- event contract
- event_id idempotency
- incident creation/correlation
- Incident Agent invocation
- policy authority
- requested_action semantics
- n8n workflow
- HITL behavior
- DENY behavior
- failure handling
- security boundaries
- manual verification procedure

14. DO NOT CHANGE

Do not modify the architecture of:

- P5 Claude Agent SDK
- P6 Incident Agent
- MCP retrieval tools
- existing deterministic policy engine
- existing HITL approval enforcement
- existing workflow idempotency/audit mechanisms

unless a minimal integration adapter is required.

Do not implement Gate 7.

Do not add Slack, GitHub, AWS, Kubernetes, production remediation, vector DB, embeddings, multi-agent functionality, or authentication/RBAC redesign.

IMPLEMENTATION DISCIPLINE

Before editing:
- inspect the relevant existing files
- identify the smallest required changes
- explain the implementation plan

Then implement in small changes.

After implementation:
1. run focused Gate 6 tests
2. run the complete project suite
3. inspect git diff
4. verify no P5/P6 regressions
5. verify the n8n workflow manually
6. verify at least:
   - one LOW/ALLOW path
   - one HITL_REQUIRED path
   - one DENY path
   - duplicate event
   - malformed event
7. report exact results

STOP AFTER GATE 6.

Do not begin Gate 7.