We are proceeding to Phase 7 Gate 6 of the PulseOps AI Engineering project.

Before making any code changes, read and understand the current repository state.

MANDATORY PRE-READ

Read these files first:

1. CLAUDE.md
2. project-plan.md
3. docs/phase-7.md
4. docs/phase-7-gate-5.md
5. docs/phase-7-gate-4.md
6. docs/phase-7-gate-3.md
7. docs/phase-7-review.md
8. relevant current Phase 7 implementation files
9. relevant Phase 7 tests
10. existing Docker configuration
11. existing API routes and schemas
12. existing P6 Incident Agent implementation

Do not assume the repository matches an earlier conversation.
Inspect the actual current files.

==================================================
PHASE 7 — GATE 6
n8n WORKFLOW INTEGRATION
==================================================

OBJECTIVE

Integrate the existing PulseOps Phase 7 workflow with a locally
self-hosted n8n instance.

n8n is an ORCHESTRATION layer only.

PulseOps remains the owner of:

- business logic
- incident workflow state
- policy evaluation
- risk classification
- HITL enforcement
- idempotency
- audit
- Incident Agent execution
- MCP
- Claude Agent SDK

Do not move business logic into n8n.

==================================================
CURRENT ENVIRONMENT
==================================================

The current local development environment is:

Windows
|
+-- PulseOps FastAPI
|      http://127.0.0.1:8000
|
+-- Neo4j Desktop
|      local Neo4j instance
|
+-- Claude Agent SDK
|      existing Anthropic configuration
|
+-- n8n
       Docker
       http://localhost:5678

A connectivity test has already been verified:

n8n Docker
    |
    | GET
    v
http://host.docker.internal:8000/health
    |
    v
PulseOps FastAPI

The request returned HTTP 200 with:

{
  "status": "ok",
  "app": "PulseOps",
  "environment": "development",
  "debug": false
}

Do not redesign this networking setup.

Neo4j Desktop is NOT being moved into Docker.

Do not require n8n Cloud.

Do not require an n8n API key.

Do not introduce paid infrastructure.

==================================================
GATE 6 SCOPE
==================================================

Implement the first real n8n orchestration path:

Operational Event
        |
        v
n8n Webhook
        |
        v
Input Validation
        |
        v
PulseOps Workflow API
        |
        v
Existing Incident Investigation
        |
        v
Existing Policy Evaluation
        |
        +----------------+
        |                |
       LOW        HIGH/MEDIUM
        |                |
     Notify             HITL
                         |
                  Existing approval API

The n8n workflow must use existing PulseOps APIs wherever possible.

Do not duplicate PulseOps business rules inside n8n.

==================================================
1. n8n WEBHOOK
==================================================

Create a local n8n workflow with a webhook trigger.

The webhook must accept the existing operational event contract
defined in docs/phase-7.md.

Expected event structure:

{
  "event_id": "...",
  "event_type": "...",
  "timestamp": "...",
  "service_id": "...",
  "severity": "...",
  "source": "...",
  "message": "...",
  "metadata": {}
}

The webhook should accept JSON.

Do not introduce a second incompatible event schema.

==================================================
2. INPUT VALIDATION
==================================================

n8n should perform only basic orchestration-boundary validation.

Validate that:

- request is JSON
- event_id exists
- event_type exists
- timestamp exists
- service_id exists
- severity exists
- source exists
- message exists
- metadata, when present, is an object

Do not duplicate complex domain validation that belongs to PulseOps.

Malformed events must not proceed to the workflow API.

Return an appropriate failure response.

Do not expose stack traces or secrets.

==================================================
3. PULSEOPS API INTEGRATION
==================================================

n8n must call the existing PulseOps workflow API.

Inspect the actual Gate 5 implementation and use the real
current endpoint and request schema.

Do NOT invent a new API if an existing endpoint already satisfies
the requirement.

Preserve:

- event_id
- incident_id
- workflow_id
- correlation information
- idempotency information

The n8n workflow must not bypass:

- policy evaluation
- HITL enforcement
- idempotency
- audit
- approval validation

==================================================
4. IDEMPOTENCY
==================================================

The same operational event must not create duplicate workflow state.

Use the existing PulseOps idempotency mechanism.

Do not implement a second independent idempotency mechanism
inside n8n unless it is strictly required for transport-level
workflow behavior.

PulseOps remains the source of truth.

==================================================
5. POLICY RESULT
==================================================

n8n must consume the policy result returned by PulseOps.

Do not allow an LLM to determine the safety decision.

The deterministic PulseOps policy engine remains authoritative.

The workflow must support the existing policy outcomes:

ALLOW
NOTIFY
HITL_REQUIRED
DENY

Use n8n branching only to orchestrate the already-determined result.

==================================================
6. LOW-RISK PATH
==================================================

For a LOW-risk/informational workflow:

PulseOps
   |
   v
policy result
   |
   v
n8n
   |
   v
simulated notification / workflow response

Do NOT integrate Slack yet.

Do NOT send real external notifications yet.

A simulated notification is sufficient for Gate 6.

Record enough information for verification.

==================================================
7. HITL PATH
==================================================

For HITL_REQUIRED:

n8n must not execute the consequential action.

It must preserve the existing PulseOps HITL boundary.

The workflow should reach a HITL_PENDING state and expose
the information necessary for a human approval/rejection.

Use the existing approval API.

Do not create a second approval mechanism inside n8n.

No AI-generated approval is valid.

No automatic approval is permitted.

==================================================
8. DENY PATH
==================================================

For DENY:

n8n must not continue to execution.

The denied result must remain terminal according to the existing
PulseOps workflow rules.

Do not allow n8n to override a DENY decision.

==================================================
9. AUDIT
==================================================

Do not duplicate the audit system.

PulseOps remains authoritative for workflow audit.

n8n may contribute orchestration/execution information where
appropriate, but it must not replace PulseOps audit persistence.

Preserve correlation identifiers so an n8n execution can be related
to the PulseOps workflow and incident.

==================================================
10. ERROR HANDLING
==================================================

The workflow must fail safely.

Handle at minimum:

- malformed webhook payload
- missing required event fields
- PulseOps API unavailable
- PulseOps 400
- PulseOps 404
- PulseOps 409
- policy DENY
- HITL required
- unexpected PulseOps response
- timeout

Do not retry operations in a way that could create duplicate
incidents, approvals, notifications, or actions.

Respect existing PulseOps idempotency.

Do not expose:

- API keys
- Anthropic credentials
- database credentials
- internal stack traces

==================================================
11. CORRELATION
==================================================

Every n8n execution should be traceable to:

event_id
incident_id
workflow_id

Use existing identifiers where available.

Do not invent competing identifiers unless n8n requires an
execution-local identifier.

==================================================
12. n8n WORKFLOW DESIGN
==================================================

The initial workflow should remain understandable and small.

Target conceptual structure:

Webhook
   |
Validate Event
   |
HTTP Request → PulseOps
   |
Inspect Result
   |
Switch / IF
   |
   +---- ALLOW/NOTIFY ----> Simulated Notification
   |
   +---- HITL_REQUIRED ----> HITL Pending / Approval Path
   |
   +---- DENY -------------> Stop / Return Denied

Do not add unnecessary AI Agent nodes.

Do not connect n8n directly to Claude.

Do not connect n8n directly to MCP.

Do not connect n8n directly to Neo4j.

Do not connect n8n directly to SQLite.

All business interaction goes through the appropriate
PulseOps interfaces.

==================================================
13. TESTING
==================================================

Add or update tests where appropriate for the PulseOps side.

At minimum verify:

1. valid event reaches the PulseOps workflow
2. malformed event is rejected
3. duplicate event does not create duplicate workflow state
4. LOW-risk path reaches simulated notification
5. HITL_REQUIRED path does not execute consequential action
6. DENY path stops safely
7. PulseOps 404 is handled
8. PulseOps 409 is handled
9. PulseOps unavailable/error is handled safely
10. correlation identifiers are preserved

Do not weaken existing tests.

Do not modify P5/P6 behavior.

Do not bypass any existing Phase 7 Gate 1–5 protections.

==================================================
14. MANUAL VERIFICATION
==================================================

Provide a clear manual n8n verification procedure.

At minimum document:

- how to start n8n
- how to open the workflow
- how to activate/test the webhook
- sample JSON event
- expected PulseOps response
- how to verify the LOW-risk path
- how to verify HITL_REQUIRED
- how to verify DENY
- how to verify duplicate/idempotency behavior

Do not require n8n Cloud.

==================================================
15. DOCUMENTATION
==================================================

Update the appropriate Phase 7 documentation to reflect the
actual implementation.

Do not rewrite unrelated project documentation.

Document the distinction:

n8n = orchestration
PulseOps = business/application logic
Claude Agent SDK = reasoning
MCP = controlled tool boundary
Policy Engine = deterministic safety decision
HITL = human authorization

==================================================
16. NON-GOALS — DO NOT IMPLEMENT
==================================================

Do NOT implement:

- n8n Cloud
- n8n API management
- Slack integration
- GitHub integration
- AWS integration
- Kubernetes integration
- production monitoring integrations
- real production remediation
- autonomous restart
- autonomous deployment
- production shell execution
- production credentials
- data deletion
- real external ticket creation
- multi-agent orchestration
- vector database
- embeddings
- Phase 8 evaluation framework
- cloud deployment
- authentication/RBAC redesign
- changes to P5/P6 architecture

==================================================
17. SECURITY PRINCIPLES
==================================================

Maintain:

- least privilege
- fail closed
- untrusted operational input
- no prompt injection trust
- no secrets in workflow data
- no autonomous consequential actions
- explicit human approval
- deterministic policy enforcement
- auditability
- idempotency

Never treat operational event text as trusted instructions.

==================================================
18. IMPLEMENTATION DISCIPLINE
==================================================

Before changing code:

1. Inspect the repository.
2. Inspect current Gate 5 implementation.
3. Inspect actual API routes and schemas.
4. Inspect current Docker configuration.
5. Inspect current Phase 7 tests.
6. Inspect existing n8n-related configuration, if any.
7. Explain the proposed implementation.
8. Identify which files will change.
9. Do not rewrite stable P5/P6/P7 code unnecessarily.

Make small, verifiable changes.

After implementation:

1. Run focused tests.
2. Run the complete project test suite.
3. Verify n8n workflow manually.
4. Verify the webhook.
5. Verify one valid operational event.
6. Verify duplicate/idempotency behavior.
7. Verify HITL behavior.
8. Verify DENY behavior.
9. Report exact test counts and failures, if any.
10. Stop after Gate 6.

Do not proceed to Gate 7 without explicit approval.

==================================================
ACCEPTANCE CRITERIA
==================================================

Gate 6 is complete only when:

[ ] n8n runs locally
[ ] n8n webhook receives the operational event contract
[ ] malformed events are rejected
[ ] n8n reaches PulseOps through the existing API
[ ] incident/workflow identifiers are preserved
[ ] existing PulseOps policy remains authoritative
[ ] LOW/NOTIFY path works
[ ] HITL_REQUIRED path works without autonomous execution
[ ] DENY path stops safely
[ ] duplicate events remain idempotent
[ ] PulseOps remains audit source of truth
[ ] error handling is fail-closed
[ ] no secrets are exposed
[ ] no P5/P6 behavior is changed
[ ] focused tests pass
[ ] complete pytest suite passes
[ ] manual n8n verification succeeds
[ ] documentation reflects actual implementation
[ ] no Gate 7 or later scope is implemented

STOP after Gate 6.

Do not proceed to Gate 7 until I explicitly approve Gate 6.