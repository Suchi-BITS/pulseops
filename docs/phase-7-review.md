Phase 7 implementation review.

Do NOT modify any files.

Read:
1. CLAUDE.md
2. project-plan.md
3. docs/phase-7.md
4. The current Phase 7 implementation
5. Existing Phase 5 and Phase 6 implementation
6. Current tests
7. Docker configuration

Review the implementation against docs/phase-7.md.

Specifically verify:

1. Risk classification
   - LOW
   - MEDIUM
   - HIGH

2. Policy enforcement
   - deterministic policy decisions
   - high-risk actions require HITL
   - AI cannot bypass policy

3. Workflow state transitions

4. Approval/rejection behavior
   - explicit approval
   - explicit rejection
   - malformed/missing approval
   - fail-closed behavior

5. Audit logging
   - all important workflow transitions are auditable
   - actor information
   - timestamps
   - incident/event correlation

6. Idempotency
   - duplicate events
   - duplicate approvals
   - duplicate actions
   - duplicate notifications

7. Security
   - untrusted operational input
   - prompt injection resistance
   - no autonomous production actions
   - no shell execution
   - no production credentials

8. Phase 6 integration
   - Incident Investigation Agent is reused
   - MCP remains the controlled tool boundary
   - Claude Agent SDK remains the reasoning layer
   - existing Phase 5/6 behavior is not unnecessarily changed

9. API design
   - webhook-style workflow route
   - incident-scoped routes
   - approve/reject routes
   - validation and error handling

10. Test coverage

Return:

A. What is correctly implemented
B. What is missing
C. What is partially implemented
D. Security concerns
E. Tests that should be added
F. n8n integration requirements
G. Synthetic event simulator requirements
H. Exact recommended next implementation sequence

Do not implement anything.