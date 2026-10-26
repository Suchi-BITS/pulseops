Phase 7 Gate 2 — Durable Workflow State

Gate 1 is APPROVED.

Implement ONLY Gate 2: durable workflow state.

Before changing anything:

1. Read CLAUDE.md.
2. Read project-plan.md.
3. Read docs/phase-7.md.
4. Review the completed Gate 1 deterministic policy engine.
5. Inspect the current workflow models, workflow_service.py, workflow.py, incidents.py, database/repository patterns, and tests.
6. Preserve all existing Phase 5, Phase 6, and Gate 1 behavior.

Goal:

Replace the current in-memory workflow state with durable SQLite persistence using the existing PulseOps persistence architecture.

Do NOT implement:
- n8n
- synthetic event simulator
- authenticated reviewer enforcement
- external action execution
- Slack
- GitHub
- AWS/Kubernetes
- Phase 8 evaluation

Scope this gate strictly to persistence.

Create appropriate durable models/repositories for:

1. Workflow instance
   - workflow_id
   - incident_id
   - event_id if applicable
   - action
   - status
   - risk level
   - policy decision
   - created_at
   - updated_at

2. Workflow decision
   - decision_id
   - workflow_id
   - decision
   - actor information
   - reason
   - timestamp

3. Audit event
   - audit_id
   - workflow_id
   - incident_id
   - event_id if applicable
   - event type
   - actor type
   - actor id
   - timestamp
   - details

4. Idempotency information where appropriate, but do not implement the full idempotency gate yet.

Requirements:

- Use the existing SQLite/database architecture.
- Do not introduce a second persistence mechanism.
- Do not store workflow state only in Python dictionaries.
- Workflow state must survive application restart.
- Preserve the existing API behavior where possible.
- Keep policy evaluation deterministic.
- Do not allow persistence changes to bypass the Gate 1 policy engine.
- Do not execute any production actions.

Tests must verify:

1. workflow record can be persisted
2. workflow can be retrieved after creation
3. workflow state survives service/repository recreation
4. decision can be persisted
5. audit event can be persisted
6. workflow, decision, and audit records maintain correct IDs
7. unknown workflow returns the expected error
8. existing Gate 1 tests still pass
9. existing Phase 5/6 tests still pass

Run:

pytest -q

Do not proceed to Gate 3.

Before implementation, briefly explain:
- the persistence model
- repository changes
- schema/database changes
- how existing workflow_service.py will use persistence

Then implement the smallest coherent change.

Final report must contain:

1. Files changed
2. Database/model changes
3. Repository changes
4. Workflow service changes
5. Tests added
6. Full pytest result
7. Any remaining Gate 2 limitations

Stop after Gate 2.