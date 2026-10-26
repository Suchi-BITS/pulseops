We have completed and accepted Gate 9.1.

Current status:
- Gate 9 COMPLETE
- Gate 9.1 COMPLETE
- Docker Compose verification COMPLETE
- PulseOps authentication verified
- Tenant-scoped authentication verified
- n8n service principal verified
- Gate 9/9.1 RBAC, HITL, self-approval and cross-tenant behavior verified by automated tests
- Do NOT modify any files yet.

We are now moving to the next curriculum phase: P8 — Evaluation.

Before implementation, perform a read-only architecture and repository inspection for P8.

Review:
- project-plan.md
- CLAUDE.md
- docs/architecture.md
- docs/agent-architecture.md
- docs/security.md
- docs/curriculum-alignment.md
- existing evaluation documentation
- existing evaluation implementation
- tests/
- app/
- any existing evaluation dataset/golden cases
- Gate 7 and Gate 8 evaluation implementation/reports

Determine the current state of evaluation and what P8 should add without duplicating work already completed in Gate 7/Gate 8.

P8 must clearly distinguish:

1. System correctness
2. Safety/security correctness
3. Retrieval/tool correctness
4. AI answer quality
5. Grounding/fabrication
6. Regression testing
7. Latency
8. Token/cost efficiency
9. Evaluation dataset/versioning
10. CI execution

Inspect what already exists and identify the remaining gaps.

Also identify:
- what is already implemented and should NOT be rebuilt
- what should be extended
- what belongs to P8 versus P11 Quality Engineering
- what should remain deferred to P10 Cloud + Platform
- how P8 should fit into the existing PulseOps architecture

Do not modify code, tests, documentation, configuration, databases, Docker, or CI.

Produce:
1. Current-state assessment
2. Existing evaluation capabilities
3. Remaining P8 gaps
4. Proposed P8 scope
5. Explicit non-goals
6. Implementation order
7. Proposed gates/checkpoints
8. Test strategy
9. Files likely to change
10. Risks/trade-offs

Stop and wait for approval.