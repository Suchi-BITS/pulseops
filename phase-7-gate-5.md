Phase 7 Gate 5 — API Hardening

Gates 1–4 are approved.

Implement ONLY Gate 5.

Read:

1. CLAUDE.md
2. project-plan.md
3. docs/phase-7.md
4. policy_service.py
5. workflow_service.py
6. incident_repository.py
7. workflow.py
8. incidents.py
9. schemas.py
10. Current Phase 7 tests

Goal:

Harden the PulseOps workflow API so it is a reliable boundary for the future n8n orchestration layer.

Do NOT implement:

- n8n
- synthetic event simulator
- Slack
- GitHub
- AWS/Kubernetes
- production action execution
- authentication/RBAC infrastructure
- Phase 8 evaluation

Implement:

1. Request validation

Validate:
- required incident identifier
- required action
- valid severity where applicable
- valid idempotency key
- valid approval decision
- required reviewer for HITL decisions
- required timestamp for consequential approval

2. HTTP error contract

Use appropriate status codes:

400:
- malformed request
- invalid field values

404:
- unknown incident
- unknown workflow

409:
- conflicting idempotency key
- invalid/conflicting workflow state
- duplicate/conflicting approval

422:
- structurally invalid request where appropriate under FastAPI/Pydantic conventions

Do not expose internal stack traces.

3. Response schemas

Ensure workflow endpoints return explicit typed responses containing the information required by callers.

Do not expose secrets or internal implementation details.

4. Correlation

Where appropriate, preserve:
- workflow_id
- incident_id
- event_id
- idempotency_key/correlation identifier

Ensure these identifiers remain consistent through workflow operations.

5. API state safety

The API must not allow callers to bypass:

- deterministic policy
- HITL requirements
- DENY decisions
- idempotency
- audit logging

6. Approval endpoint

Ensure the API cannot convert:
- rejected → approved
- approved → rejected
- denied → approved

and cannot accept an AI identity as a human approval.

7. Tests

Add API-level tests for:

- valid workflow request
- malformed workflow request
- missing incident
- missing workflow
- invalid action
- invalid severity
- missing idempotency key where required
- conflicting idempotency key
- valid approval
- invalid approval
- missing reviewer
- invalid decision
- duplicate approval
- conflicting approval
- denied workflow cannot be approved
- appropriate HTTP status codes
- typed response validation
- no internal error leakage

Run:

python -m pytest -q

Verify the COMPLETE project suite, not only test_phase7.py.

Do not proceed to Gate 6.

Before implementation, explain:
1. Current API weaknesses
2. Proposed validation/error contract
3. Files that will change
4. Test strategy

Then implement the smallest coherent change.

Final report must contain:
1. Files changed
2. API contract
3. Validation rules
4. HTTP status mapping
5. Tests added
6. COMPLETE pytest result
7. Remaining Phase 7 gaps

Stop after Gate 5.