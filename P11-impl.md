P9 IS COMPLETE AND ACCEPTED.

P9 final validated state:

- Windows full suite: 334 passed
- Linux Python 3.11 non-root: 334 passed
- Golden-v2 replay: GATE PASS
- Golden-v3 replay: GATE PASS
- Tenant-isolation evaluation: 1.00
- Frontend tests/typecheck/build: PASS
- Live application smoke: 17/17 PASS
- Docker image/build/runtime validation: PASS
- /health/ready: PASS
- React + Vite + TypeScript frontend implemented
- Investigation persistence implemented
- Reviewer read APIs implemented
- Authentication/tenant isolation/HITL preserved
- No live Claude model call performed
- P10 is intentionally SKIPPED
- P9 known limitations are intentionally deferred where appropriate

We are now moving to:

P11 — QUALITY ENGINEERING

Do NOT modify anything yet.

Perform a READ-ONLY inspection only.

The objective is to determine the MINIMUM COMPLETE P11 scope required to finish the PulseOps curriculum without reopening or rebuilding P0–P9.

==================================================
P11 OBJECTIVE
==================================================

P11 should prove that PulseOps is a quality-engineered application.

Focus on:

1. Automated quality gates
2. Integration testing
3. End-to-end application testing
4. UI testing
5. Security testing
6. Performance/load testing
7. Reliability/resilience testing
8. Test coverage
9. Flakiness/regression detection
10. CI quality gates
11. Release-readiness validation

P11 is about PROVING the existing system.

It is NOT an excuse to redesign the application.

==================================================
INSPECT
==================================================

Read/inspect:

- project-plan.md
- CLAUDE.md
- docs/architecture.md
- docs/security.md
- docs/curriculum-alignment.md
- docs/phase-8.md
- docs/phase-9.md
- app/
- frontend/
- tests/
- evals/
- Dockerfile
- docker-compose.yml
- .github/workflows/
- pyproject.toml
- frontend/package.json
- existing test configuration
- existing security-related tests
- existing evaluation tests
- existing Docker tests
- existing frontend tests
- existing live application smoke tests

Determine what quality engineering already exists.

==================================================
ASSESS THESE AREAS
==================================================

For each area classify:

DONE
PARTIAL
MISSING
DEFERRED

1. Unit testing

2. API integration testing

3. Database/repository testing

4. Authentication/RBAC testing

5. Tenant-isolation testing

6. HITL/security testing

7. MCP/tool-boundary testing

8. Agent grounding/fabrication testing

9. Evaluation/regression testing

10. React component testing

11. Browser end-to-end testing

12. API contract testing

13. Docker/container testing

14. Performance testing

15. Load/concurrency testing

16. Failure/recovery testing

17. Security scanning

18. Dependency vulnerability scanning

19. Secret scanning

20. Test coverage measurement

21. Mutation testing, if appropriate

22. Flaky-test detection

23. CI quality gates

24. Release-readiness criteria

==================================================
IMPORTANT P11 BOUNDARIES
==================================================

P10 has been intentionally SKIPPED.

Therefore do NOT propose:

- AWS
- Kubernetes
- Terraform
- cloud deployment
- PostgreSQL migration
- OIDC/SSO
- cloud secret manager
- hosted monitoring
- cloud tracing
- cloud cost infrastructure
- production cloud load testing

Do not turn P11 into a cloud/platform phase.

P11 may test the local Docker/Compose deployment.

==================================================
DO NOT REBUILD
==================================================

Do not rebuild:

- authentication
- RBAC
- tenancy
- HITL
- MCP
- Agent SDK
- workflow engine
- evaluation harness
- React application
- investigation persistence

These already exist.

P11 should test them.

==================================================
SPECIAL ATTENTION: SECURITY
==================================================

Inspect whether P11 should add:

- secret scanning
- dependency vulnerability checks
- static analysis
- unsafe frontend rendering checks
- security headers/CSP verification
- authentication abuse tests
- cross-tenant access tests
- malformed input tests
- prompt-injection regression tests
- dependency lock verification

Do not introduce expensive enterprise security tooling unless it provides clear curriculum value and can run locally/CI.

Prefer lightweight deterministic checks.

==================================================
SPECIAL ATTENTION: PERFORMANCE
==================================================

Determine a practical local performance test strategy.

Possible scope:

- health endpoint
- incident listing
- incident detail
- investigation retrieval
- workflow read API
- retrieval tools
- policy evaluation

Do not require production-scale benchmarks.

Do not create unrealistic performance claims.

The goal is to demonstrate measurement and regression detection.

==================================================
SPECIAL ATTENTION: UI
==================================================

P9 already has:

- React + Vite + TypeScript
- three primary views
- component tests
- frontend build
- live application smoke tests

Determine the minimum useful P11 browser E2E coverage.

Likely candidates:

1. User enters token
2. Incident list loads
3. Incident detail opens
4. Investigation is displayed
5. Pending approval queue loads
6. Authorized reviewer can approve/reject
7. Unauthorized user cannot perform approval
8. API failure/degraded investigation is visibly handled

Do not build a large browser testing framework.

==================================================
SPECIAL ATTENTION: RELIABILITY
==================================================

Determine whether P11 should test:

- malformed operational events
- duplicate events
- idempotency
- failed investigation
- degraded investigation
- MCP tool failure
- database failure
- stale workflow claims
- conflicting HITL decisions
- cross-tenant access
- restart/recovery behavior

Use existing mechanisms wherever possible.

==================================================
SPECIAL ATTENTION: COVERAGE
==================================================

Inspect current Python and frontend coverage.

Determine whether a reasonable coverage threshold can be introduced.

Do not choose an arbitrary high number merely to increase the percentage.

Coverage should be used as a quality signal, not as a vanity metric.

==================================================
SPECIAL ATTENTION: CI
==================================================

Inspect the current CI workflow.

Determine which P11 checks should become mandatory CI gates.

Prefer a practical CI pipeline such as:

- Python tests
- frontend tests
- frontend build
- evaluation replay
- security checks
- coverage threshold
- Docker build
- selected integration tests

Live Claude evaluation must remain OUT of normal CI.

==================================================
P11 NON-GOALS
==================================================

Explicitly consider these out of scope unless inspection proves absolutely necessary:

- cloud infrastructure
- AWS
- Kubernetes
- Terraform
- PostgreSQL
- OIDC/SSO
- hosted monitoring
- production observability platforms
- production-scale load testing
- autonomous remediation
- multi-agent architecture
- vector databases
- Neo4j runtime
- LLM-as-judge
- RAGAS/DeepEval gates
- large-scale browser E2E suites
- performance dashboards

==================================================
DELIVER
==================================================

Produce a complete read-only P11 inspection report containing:

1. Current quality-engineering state

2. Area-by-area assessment:
   DONE / PARTIAL / MISSING / DEFERRED

3. What P11 genuinely needs to add

4. What should NOT be touched

5. Proposed minimum-complete P11 scope

6. Proposed implementation order

7. Proposed quality gates

8. Proposed CI gates

9. Security testing strategy

10. Performance testing strategy

11. UI E2E testing strategy

12. Reliability testing strategy

13. Coverage strategy

14. Release-readiness checklist

15. Files likely to change

16. Risks and trade-offs

17. Explicit distinction:
    P11 vs skipped P10

18. Final recommended P11 completion criteria

IMPORTANT:

Do not modify source code.
Do not modify tests.
Do not modify CI.
Do not modify documentation.
Do not modify Docker.
Do not modify datasets or baselines.
Do not run live Claude evaluation.

Stop after the inspection and wait for approval.