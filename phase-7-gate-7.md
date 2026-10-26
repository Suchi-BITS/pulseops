We have completed Phase 7 Gate 6.

Gate 6 is COMPLETE:
- Full suite: 106 passed, 0 failed
- Gate 6 tests: 21
- Event-driven workflow implemented
- Durable event idempotency implemented
- Existing Phase 6 Incident Agent integrated
- Deterministic policy remains authoritative
- Fail-closed investigation behavior implemented
- n8n orchestration implemented and manually verified
- Gate 6 documentation updated
- We have explicitly stopped at Gate 6
- Do NOT start implementation yet

Read:
1. CLAUDE.md
2. project-plan.md
3. docs/phase-7-gate-6.md
4. docs/phase-6.md
5. the current evaluation/testing-related code
6. the existing tests
7. the current Incident Agent implementation
8. pyproject.toml and dependency configuration

Now perform an architecture review for the NEXT phase: Gate 7 — Evaluation & Reliability.

Do NOT modify any files.

Determine the current state of evaluation capabilities and propose a concrete Gate 7 implementation plan.

Gate 7 should evaluate the AI investigation system, not replace the production decision path.

The evaluation architecture should consider:

1. Golden incident evaluation dataset
2. Expected evidence
3. Evidence grounding
4. Answer relevance
5. Completeness / missing information
6. Evidence vs hypothesis vs recommendation separation
7. Fabricated evidence detection
8. Prompt-injection resistance
9. Policy-boundary compliance
10. Investigation failure behavior
11. Regression evaluation
12. Evaluation reporting

First inspect what already exists. Do not assume RAGAS or DeepEval should be added.

Explicitly identify:
- what can be reused
- what is missing
- proposed files/modules
- proposed data contracts
- proposed evaluation metrics
- test strategy
- whether external LLM-as-judge evaluation is necessary
- how evaluation remains separate from production decision-making
- how live Claude/API availability affects evaluation
- how the evaluation suite could eventually run in CI
- risks and design trade-offs

Do not implement anything.
Do not modify P5 or P6.
Do not modify the Gate 6 architecture.
Do not start Gate 8 or later work.

Stop after producing the Gate 7 architecture/implementation plan and wait for approval.