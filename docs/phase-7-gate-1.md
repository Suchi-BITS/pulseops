Implement Phase 7 Gate 1: Deterministic Policy Engine.

Before changing anything:

1. Read CLAUDE.md.
2. Read project-plan.md.
3. Read docs/phase-7.md.
4. Read the Phase 7 review findings.
5. Inspect the existing Phase 7 implementation.
6. Inspect the existing Phase 5 and Phase 6 implementation and tests.

Do NOT implement n8n, the synthetic event simulator, or later Phase 7 gates yet.

Goal:

Replace the current heuristic risk classification with an explicit, deterministic, reviewable policy contract.

The policy engine must be independent of the LLM.

Define a policy model that explicitly represents at least:

- action
- risk level
- approval requirement
- allowed action class
- permitted actor/role information
- whether the action is executable or informational

At minimum support:

LOW
MEDIUM
HIGH

and policy decisions:

ALLOW
NOTIFY
HITL_REQUIRED
DENY

Important rules:

1. The LLM must never be the authority that decides whether an action is permitted.

2. Risk must be derived from the deterministic policy registry, not from free-form LLM text matching.

3. Unknown actions must fail closed.

4. High-risk actions must result in HITL_REQUIRED or DENY.

5. No production action may be executed by this policy engine.

6. Preserve the existing Phase 6 Incident Investigation Agent behavior.

7. Do not change MCP behavior.

8. Do not introduce n8n yet.

9. Do not introduce GitHub, Slack, AWS, Kubernetes, production credentials, or autonomous remediation.

10. Keep the implementation small and testable.

Create deterministic tests covering at least:

- known LOW action
- known MEDIUM action
- known HIGH action
- unknown action
- denied action
- approval-required action
- informational/non-executable action
- invalid policy configuration
- case/format normalization if applicable
- policy decision cannot be overridden by an LLM-provided risk value

Also verify that all existing tests continue to pass.

Before implementation, explain the proposed policy model and files that will change.

Then implement the smallest coherent change.

Run:

pytest -q

Return:

1. Files changed
2. Policy model
3. Policy decisions supported
4. Security/fail-closed behavior
5. Tests added
6. Full test result
7. Any remaining Phase 7 gaps

Do not proceed to Gate 2.