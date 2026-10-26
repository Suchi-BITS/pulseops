P11 — Quality Engineering & Release Readiness
Single Implementation Prompt for Claude Code
Execution model: Implement P11 as one complete change set. Do not split this work into additional gates or phases. Inspect first, implement carefully, run the required validation, and report the final result.

1. Mission
Implement Phase 11 — Quality Engineering & Release Readiness for the existing PulseOps AI Incident Intelligence Platform.
P11 is the final local quality-engineering layer around the existing PulseOps application.
The goal is to prove that the current application is sufficiently tested, secured, reliable, containerized, and release-ready.
Do not redesign PulseOps.
2. Current Project State
PulseOps has completed:
- P0 Foundation
- P1 Operational Data
- P2 Ontology + Knowledge Graph + Context Engineering
- P3 Controlled Retrieval Tools
- P4 MCP
- P5 Claude Agent SDK
- P6 Incident Agent
- P7 Workflow + HITL
- P8 Evaluation
- P9 Modern Application
P10 is intentionally skipped.
P11 is the final quality-engineering stage before declaring the local PulseOps v1.0 application release-ready.
Do not start P10 work.
3. Objective
P11 must establish:
1. Python coverage measurement and ratcheted threshold
2. Frontend coverage measurement and ratcheted threshold
3. Static security analysis
4. Dependency vulnerability checks
5. Repository-wide secret scanning
6. API/security regression coverage
7. Cross-tenant security sweep
8. MCP failure/recovery coverage
9. Database failure/recovery coverage
10. Browser E2E coverage
11. Local performance regression testing
12. Docker build/runtime validation
13. Flaky-test detection
14. One-command local quality gate
15. CI quality gates
16. Release-readiness documentation
4. Explicit Non-Goals
Do NOT introduce or expand:
- AWS
- Kubernetes
- Terraform
- PostgreSQL
- OIDC
- SSO
- cloud secret managers
- cloud monitoring
- production load testing
- autonomous remediation
- multi-agent architecture
- vector database
- embeddings
- Neo4j runtime integration
- LLM-as-judge
- RAGAS/DeepEval expansion
- large browser automation suites
- production performance dashboards
- live Claude evaluation in CI
- production deployment architecture
P11 is quality engineering for the existing local application.
5. Source-Change Policy
Do not proactively modify production source code.
P11 should primarily add:
- tests
- scripts
- CI configuration
- development dependencies
- documentation
- release checks
If a new test exposes a genuine production defect:
1. Confirm that the failure is a real correctness, security, or reliability problem.
2. Make the smallest safe source change necessary.
3. Add a regression test.
4. Re-run the affected tests.
5. Document the defect and fix in the P11 report.
Never fix a failure by:
- weakening an assertion
- skipping the test
- deleting the test
- increasing arbitrary timeouts
- changing evaluation baselines
- changing golden datasets
- changing scorers to hide regressions
- suppressing security findings without justification
6. Deliverables
Create or update, as appropriate:
scripts/quality_gate.py
scripts/perf_smoke.py
scripts/secret_scan.py

tests/test_phase11_security.py
tests/test_phase11_reliability.py
tests/test_phase11_contract.py
tests/test_phase11_performance.py

e2e/
frontend/playwright.config.ts

docs/phase-11.md
docs/release-checklist.md
CHANGELOG.md

.github/workflows/ci.yml
pyproject.toml
frontend/package.json
frontend/vite.config.ts
Follow existing repository conventions if equivalent filenames already exist.
7. One-Command Quality Gate
Create:
python scripts/quality_gate.py
It must orchestrate the relevant P11 checks and return non-zero on failure.
Target sequence:
Python tests + coverage
        ↓
Frontend tests + coverage + build
        ↓
Replay v2
        ↓
Replay v3
        ↓
Tenant isolation
        ↓
Security tests
        ↓
Static security analysis
        ↓
Dependency checks
        ↓
Secret scan
        ↓
API/reliability tests
        ↓
Performance smoke
        ↓
Docker validation
        ↓
PASS / FAIL
Do not include a live Claude evaluation.
8. Python Coverage
Add pytest-cov.
First measure the existing baseline.
Do not invent a target before measuring.
Use:
measured baseline
→ round down
→ establish threshold
→ never lower automatically
This is a ratchet, not an aspirational target.
Where practical, enforce stronger branch coverage for security/policy-critical modules such as:
- core/security.py
- policy_service.py
- workflow security/API paths
Do not gate live Claude code that cannot reasonably be exercised without a real model.
Document exclusions.
9. Frontend Coverage
Add:
@vitest/coverage-v8
Measure current frontend coverage and establish a rounded-down ratchet threshold.
Do not redesign the React application or remove existing tests.
10. Security
Static analysis
Add:
bandit
Run it against Python source.
Do not blindly suppress findings.
Dependency auditing
Use:
pip-audit
npm audit
Do not silently pass when advisory data is unavailable.
For npm, use:
npm ci
to validate the lockfile.
Do not arbitrarily upgrade dependencies.
Python reproducibility
Add a Python constraints strategy. Prefer a constraints file over leaving ranges completely unconstrained.
Document how it is refreshed and used.
11. Secret Scanning
Create:
scripts/secret_scan.py
Scan the repository for:
- Anthropic API-key patterns
- bearer-token patterns
- cloud credential patterns
- private keys
- credentials in configuration
- real credentials in .env
- hard-coded secrets
- credentials in generated artifacts
Never print secret values.
Report only:
file
line
category
with values redacted.
Reuse the existing frontend secret-hygiene checks where practical.
12. API Contract and Security Tests
Strengthen the existing P9 contract tests.
Verify:
- expected routes/methods
- authentication requirements
- expected status classes
- error envelope:
{
  "detail": "...",
  "code": "...",
  "request_id": "..."
}
Test authentication abuse:
- malformed authorization headers
- repeated invalid tokens
- oversized headers
- missing authentication
- malformed token values
- no token leakage
Test malformed input:
- oversized bodies
- wrong JSON types
- malformed operational events
- deeply nested JSON where practical
- invalid IDs
- path/ID injection
- malformed UTF-8 where testable
Expected behavior:
- controlled client error
- correct status
- standard error envelope
- no traceback leakage
- no SQL/query details
- no credentials
13. Cross-Tenant Security Sweep
Enumerate important ID-taking endpoints.
For each:
Tenant A identity
      ↓
Tenant B resource ID
      ↓
must be rejected
Verify no cross-tenant:
- data
- workflow
- investigation
- approval
is exposed.
Tenant isolation must remain:
1.00
Do not change its dataset or baseline.
14. Security Headers and Prompt Injection
Add parametrized tests for existing security headers and CSP across relevant response classes.
Do not loosen CSP just to make tests pass.
Add a named prompt-injection regression set using existing replay mechanisms.
Verify:
- operational content remains untrusted
- embedded instructions are not followed
- fabricated evidence is rejected
- grounding remains enforced
Do not modify evaluation datasets, baselines, or scorers to make P11 pass.
15. MCP Failure Reliability
Add the missing failure case:
Investigation starts
        ↓
MCP retrieval succeeds
        ↓
another MCP tool fails
        ↓
safe degraded/error result
        ↓
no fabricated evidence
Verify failed tool results do not count as successful evidence.
16. Database Reliability
Add tests for:
- locked database
- read-only database
- missing database
- corrupted/unusable database
Expected:
- controlled error
- standard error envelope
- no internal details
- readiness correctly reflects database availability
Do not change database architecture.
17. Restart Recovery
Test:
start server
→ create workflow
→ persist state
→ stop server
→ restart server
→ verify workflow survives
→ verify investigation state survives where applicable
Use a temporary database only.
18. Concurrent HITL and Requests
Add a concurrent decision test:
Reviewer A ──┐
             ├── same workflow
Reviewer B ──┘
Exactly one decision must succeed.
The other must fail safely.
Also add modest concurrent request testing and verify:
- no unexpected 5xx
- no cross-tenant leakage
- no state contamination
This is a reliability smoke test, not production load testing.
19. Browser E2E
Use:
Playwright
Chromium
Keep the suite small.
Create:
e2e/
frontend/playwright.config.ts
The fixture should use:
- temporary database
- two tenants
- test identities
- deterministic/scripted investigation behavior
- built frontend
Do not call Claude live.
Implement these eight scenarios:
1. Enter authentication token.
2. Incident list loads.
3. Open incident detail.
4. Investigation displays with clearly labelled AI content and separate evidence/hypotheses/missing-information/recommendations.
5. Approval queue loads.
6. Reviewer approves and rejects.
7. Operator has no reviewer controls and forced API request returns 403.
8. Degraded investigation/API failure is visibly handled.
Also assert:
- token absent from localStorage
- token absent from sessionStorage
- token absent from cookies
- no CSP violations
Retries must be disabled.
20. Performance Smoke
Create:
scripts/perf_smoke.py
This is a local regression smoke test, not a benchmark.
Measure:
/health
/incidents
/incidents/{id}/detail
/incidents/{id}/investigations
/workflow
retrieval endpoints
policy evaluation
Use sequential and modest concurrent requests.
Record:
- p50
- p95
- request count
- errors
Write JSON results.
Use generous regression thresholds, for example:
p95 <= 3 × stored baseline
plus an absolute pathological ceiling.
Do not make production performance claims.
If repository construction/schema initialization dominates performance, report it rather than automatically optimizing it.
21. Docker Validation
Automate:
docker build
      ↓
start container
      ↓
/health/ready
      ↓
/ui/
Verify:
- image builds
- container starts
- readiness succeeds
- UI is served
- security headers remain present
- non-root execution remains intact
Do not introduce cloud infrastructure.
22. Flaky-Test Detection
Add a lightweight repeat mechanism for the critical test set.
Repeat the critical tests several times, preferably three.
Do not use hidden retries to mask failures.
Any failed repetition means:
P11 flake check = FAIL
Report the failing test.
23. CI
Update:
.github/workflows/ci.yml
Mandatory on push and pull request
- Python tests + coverage
- frontend tests + coverage
- frontend build
- replay v2
- replay v3
- tenant isolation
- security tests
- Bandit
- dependency checks
- secret scan
- API contract tests
- reliability tests
- performance smoke
- lockfile verification
Separate heavier job
- Docker build/run
- Playwright/Chromium E2E
Scheduled/manual
- repeated flake detection
- longer performance run if useful
Never
Run live Claude evaluation in CI.
24. Evaluation Protection
Before and after implementation verify:
v2 dataset unchanged
v3 dataset unchanged
baselines unchanged
scorer unchanged
tenant isolation = 1.00
Run the existing replay v2 and v3 commands.
Use the repository's actual CLI syntax where it differs from examples.
25. Documentation
Create/update:
docs/phase-11.md
docs/release-checklist.md
CHANGELOG.md
Document:
- P11 objective
- implemented quality controls
- coverage thresholds
- security policy
- dependency policy
- E2E scope
- performance methodology
- Docker validation
- flake detection
- CI gates
- known limitations
- migration/rollback notes
- release status
The release checklist must verify:
[ ] Python tests pass
[ ] Frontend tests pass
[ ] Python coverage passes
[ ] Frontend coverage passes
[ ] Replay v2 passes
[ ] Replay v3 passes
[ ] Tenant isolation = 1.00
[ ] Security tests pass
[ ] Bandit passes
[ ] Dependency checks pass
[ ] Secret scan passes
[ ] API contract passes
[ ] Reliability tests pass
[ ] Browser E2E passes
[ ] Performance smoke passes
[ ] Docker validation passes
[ ] Flake check passes
[ ] Documentation updated
[ ] Known limitations documented
[ ] No secrets in repository
[ ] Live Claude evaluation explicitly NOT part of release validation
26. Files/Architecture Not to Redesign
Do not redesign:
- authentication
- RBAC
- tenancy
- workflow
- HITL
- MCP
- Agent SDK
- evaluation harness
- React application
- investigation persistence
Modify production source only when a P11 test proves a genuine defect.
27. Validation
Run one comprehensive validation after implementation.
Primary command:
python scripts/quality_gate.py
Also run the repository's complete Python suite, frontend tests/build, replay v2/v3, tenant isolation, browser E2E, Docker validation, and flake detection as applicable.
Do not run live Claude evaluation.
28. Final Report
Provide:
Environment
- OS
- Python
- Node
- Docker
Results
- Python tests
- frontend tests
- coverage
- API contract
- security
- dependency audit
- secret scan
- reliability
- MCP failure
- browser E2E
- performance
- Docker
- flake detection
- replay v2
- replay v3
- tenant isolation
CI
- jobs added
- final status
Source Changes
List every production source file changed.
If none:
No production source changes.
If defects were fixed, describe each defect, smallest fix, and regression test.
Documentation
List changed documentation.
Known Limitations
List remaining limitations honestly.
Release Decision
Return exactly one:
P11 READY
or:
P11 NOT READY
If NOT READY, list blockers.
29. Absolute Rules
1. Do not start P10.
2. Do not introduce cloud infrastructure.
3. Do not run live Claude evaluation.
4. Do not change evaluation datasets.
5. Do not change evaluation baselines.
6. Do not weaken assertions.
7. Do not delete tests.
8. Do not hide security findings.
9. Do not silently ignore dependency-scan failures.
10. Do not add arbitrary retries to hide flaky behavior.
11. Do not expose secrets in logs.
12. Do not introduce production credentials.
13. Do not redesign the architecture.
14. Do not modify production source unless a test demonstrates a genuine defect.
15. If a genuine defect is found, make the smallest safe fix and add a regression test.
16. Keep P11 focused on local quality engineering and release readiness.
30. Definition of Done
P11 is complete only when:
1. One command runs the local quality gate.
2. Python coverage is measured and ratcheted.
3. Frontend coverage is measured and ratcheted.
4. Security checks pass.
5. Dependency checks pass or accepted findings are documented.
6. Repository secret scan passes.
7. API/security contract tests pass.
8. Cross-tenant sweep passes.
9. MCP failure handling is tested.
10. Database failure/recovery behavior is tested.
11. Concurrent HITL decisions are tested.
12. Browser E2E passes.
13. Performance smoke passes.
14. Docker validation passes.
15. Flake detection passes.
16. CI runs the required gates.
17. Replay v2 passes.
18. Replay v3 passes.
19. Tenant isolation remains 1.00.
20. No evaluation dataset/baseline/scorer was changed.
21. Release checklist is complete.
22. Documentation is updated.
23. Known limitations are documented.
24. No live Claude evaluation was performed.
25. P11 is reported as READY or NOT READY.
Final Instruction
Implement this as one complete P11 implementation, not as a sequence of additional user-approved gates.
Inspect the repository before editing.
Reuse existing conventions and infrastructure wherever possible.
Prefer small, deterministic, maintainable tests and scripts.
Do not expand scope.
Do not start P10.
Do not perform live Claude evaluation.
When finished, provide the complete validation