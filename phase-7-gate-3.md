Phase 7 Gate 3 — Fail-Closed Approval Enforcement

Gate 1 and Gate 2 are APPROVED.

Implement ONLY Gate 3.

Read:

1. CLAUDE.md
2. project-plan.md
3. docs/phase-7.md
4. Current policy_service.py
5. Current workflow_service.py
6. Current workflow persistence/repository implementation
7. Current Phase 7 tests
8. Existing Phase 5/6 agent implementation

Goal:

Enforce a real fail-closed approval boundary for consequential workflow actions.

Do NOT implement:
- n8n
- synthetic event simulator
- Slack
- GitHub
- external production actions
- AWS/Kubernetes
- Phase 8
- full authentication UI

Required behavior:

1. LOW / informational actions

If the deterministic policy says the action is ALLOW or NOTIFY and no human approval is required, the workflow may proceed to the appropriate non-consequential workflow state.

2. HIGH-RISK actions

If policy returns HITL_REQUIRED:

- workflow must enter an approval-pending state
- no action may be treated as executable
- no simulated or real consequential action may occur
- approval must be explicitly recorded

3. DENY

If policy returns DENY:

- workflow must stop
- no approval can convert DENY into ALLOW
- no action can execute

4. Approval

A valid approval must:

- reference the correct workflow_id
- reference the correct incident/workflow action
- contain an explicit APPROVED or REJECTED decision
- contain reviewer/actor information
- contain a timestamp
- be persisted
- be associated with the current workflow state

5. Rejection

REJECTED must permanently prevent the current action from proceeding.

6. Invalid approval

Missing, malformed, conflicting, stale, or mismatched approval must fail closed.

7. Duplicate/conflicting decisions

For this gate, prevent contradictory state transitions such as:

APPROVED → REJECTED

or

REJECTED → APPROVED

Do not implement the full idempotency framework yet; that belongs to the later gate.

8. AI cannot approve its own recommendation.

The Claude Agent SDK output must never be interpreted as human approval.

9. No production execution.

Keep the existing no-autonomous-action boundary.

Add deterministic tests for:

- high-risk action enters approval-pending state
- high-risk action cannot proceed without approval
- valid approval permits the workflow to move past approval
- rejection blocks progression
- DENY cannot be overridden
- malformed approval fails closed
- wrong workflow_id fails
- wrong action fails
- missing reviewer fails
- missing timestamp fails
- duplicate approval is rejected
- approval after rejection is rejected
- rejection after approval is rejected
- AI-generated approval/recommendation cannot satisfy HITL
- existing Gate 1 and Gate 2 tests continue to pass

Important:

Do not add authentication infrastructure yet.

Use the existing actor/reviewer fields and establish the authorization contract needed by this gate. A later gate can integrate a real auth/RBAC system.

Before implementation:

1. Explain the current approval flow.
2. Explain exactly where the fail-closed enforcement will be placed.
3. Explain the workflow state transitions.
4. Identify files that will change.

Then implement the smallest coherent change.

Run:

pytest -q

Do not proceed to Gate 4.

Final report must contain:

1. Files changed
2. Approval state machine
3. Fail-closed rules
4. Tests added
5. Full test result
6. Remaining Phase 7 gaps

Stop after Gate 3.