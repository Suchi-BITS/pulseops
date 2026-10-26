Phase 7 Gate 4 — Audit Completeness + Idempotency

Gate 1, Gate 2, and Gate 3 are APPROVED.

Implement ONLY Gate 4.

Read:

1. CLAUDE.md
2. project-plan.md
3. docs/phase-7.md
4. Current policy_service.py
5. Current workflow_service.py
6. Current workflow persistence/repository implementation
7. Current schemas/API routes
8. Current Phase 7 tests

Goal:

Harden the workflow against duplicate submissions, retries, replayed approvals, and incomplete audit trails.

Do NOT implement:

- n8n
- synthetic event simulator
- Slack
- GitHub
- AWS/Kubernetes
- real production actions
- authentication/RBAC infrastructure
- Phase 8 evaluation

Scope this gate strictly to audit completeness and idempotency.

### 1. Idempotency

Introduce a deterministic idempotency mechanism for workflow creation.

The same logical event/request must not create multiple workflow instances.

Support an idempotency key associated with the incoming workflow event.

Required behavior:

- first request with a new key creates the workflow
- repeated request with the same key returns/reuses the existing workflow
- duplicate request must not create a second workflow
- duplicate request must not create duplicate audit events for the same logical transition
- conflicting reuse of the same idempotency key with materially different workflow data must fail closed

Do not implement distributed locking or Redis yet.

Use the existing SQLite persistence architecture.

### 2. Approval idempotency

Prevent duplicate/conflicting approval effects.

Examples:

- repeated identical approval must not create multiple effective approvals
- approval after rejection remains blocked
- rejection after approval remains blocked
- duplicate decision requests must not create duplicate workflow transitions
- persisted decision history must remain consistent

### 3. Audit completeness

Create a canonical audit trail for important workflow lifecycle events.

At minimum cover:

- INCIDENT_RECEIVED
- WORKFLOW_CREATED
- POLICY_EVALUATED
- HITL_REQUESTED
- HITL_APPROVED
- HITL_REJECTED
- WORKFLOW_COMPLETED
- WORKFLOW_FAILED

Use the existing audit persistence model.

Each audit record should contain, where applicable:

- audit_id
- workflow_id
- incident_id
- event_id
- event type
- actor type
- actor id
- action
- timestamp
- result/details

Do not duplicate audit events merely because an idempotent request was retried.

### 4. Ordering and consistency

Ensure audit events reflect the actual workflow transition.

Do not write an audit event claiming an action occurred if the action did not occur.

Do not treat an AI recommendation as an executed action.

Do not allow audit records to become a mechanism for bypassing policy or HITL.

### 5. Fail closed

Unknown or malformed idempotency keys must not silently bypass the workflow.

Conflicting reuse of an idempotency key must fail.

Duplicate/conflicting decisions must remain blocked.

### 6. Tests

Add deterministic tests covering:

1. first workflow request creates one workflow
2. identical retry returns the same workflow
3. repeated request does not create duplicate workflow
4. conflicting idempotency-key reuse fails
5. duplicate approval does not create a second effective transition
6. approval after rejection fails
7. rejection after approval fails
8. canonical audit events are created
9. audit events contain workflow and incident correlation
10. retries do not duplicate lifecycle audit events
11. workflow failure is auditable
12. existing Gate 1 tests pass
13. existing Gate 2 tests pass
14. existing Gate 3 tests pass
15. existing Phase 5/6 tests pass

Before implementation:

1. Explain the idempotency-key design.
2. Explain where uniqueness is enforced.
3. Explain the canonical audit lifecycle.
4. Explain how retries behave.
5. Identify files that will change.

Then implement the smallest coherent change.

Run:

pytest -q

Do not proceed to Gate 5.

Final report must contain:

1. Files changed
2. Idempotency design
3. Audit lifecycle
4. Duplicate/replay behavior
5. Tests added
6. Full pytest result
7. Remaining Phase 7 gaps

Stop after Gate 4.