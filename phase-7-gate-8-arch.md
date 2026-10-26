# Gate 8 — Evaluation Integrity & Reliability Hardening
# IMPLEMENTATION REVIEW / PLAN ONLY

Gate 8 architecture scope has been reviewed and APPROVED.

The approved Gate 8 title is:

    Evaluation Integrity & Reliability Hardening

IMPORTANT:
We are now moving from architecture review toward implementation.

However, DO NOT modify files yet.

First inspect the repository, map the approved scope to the actual code, and provide the implementation plan.

After presenting the plan, STOP and wait for my explicit approval before modifying any files.

==================================================
1. AUTHORITATIVE DECISION
==================================================

Gate 8 has been approved with the following scope:

1. Investigation integrity
2. Ungrounded recommendation removal
3. Explicit investigation states
4. Explicit failure reasons
5. Configurable database for application + MCP subprocess
6. Evaluation dataset v2
7. Retrieval-tool ground truth evaluation
8. Tool-selection evaluation
9. Latency reporting
10. Dataset content hashing
11. Full-suite Linux CI
12. Documentation reconciliation

The objective is:

    Close integrity gaps exposed by Gate 7
    +
    complete the remaining evaluation work
    +
    improve reproducibility and CI reliability.

==================================================
2. ABSOLUTE SCOPE BOUNDARY
==================================================

DO NOT implement any of the following in Gate 8:

- Authentication
- Authorization / RBAC
- PostgreSQL
- Cloud deployment
- Real Neo4j runtime integration
- GitHub integration
- RAGAS
- DeepEval
- LLM-as-a-judge
- Human-review UI
- Full observability stack
- Autonomous remediation
- Production actions
- Slack integration
- AWS/Kubernetes production integration
- Multi-agent architecture
- Vector database
- Embeddings
- Frontend
- Major P6/P7 refactoring

These belong to later gates.

Do not expand the scope even if you discover related issues.

Document them as future work instead.

==================================================
3. FIRST READ THESE
==================================================

Before proposing implementation changes, inspect:

- CLAUDE.md
- project-plan.md
- docs/phase-6.md
- docs/phase-7.md
- docs/phase-7-gate-6.md
- docs/phase-7-gate-7.md
- the Gate 8 architecture review/report
- app/agent/
- app/services/
- app/api/
- app/core/
- app/models/
- app/repositories/
- tests/
- evals/
- .github/workflows/
- Docker configuration
- n8n configuration/workflow files

Also inspect:

- IMPLEMENTATION-ROADMAP.md
- project-plan.md.md

Determine which roadmap is currently intended to be authoritative.

DO NOT delete or rename anything yet.

==================================================
4. IMPORTANT FROZEN-AREA RULE
==================================================

Gate 8 requires limited changes to P6/P7 behavior.

Potential frozen-area changes include:

A. P6:
    app/agent/service.py

    _ungrounded_result()

B. P7:
    app/services/event_service.py

C. Workflow state handling:
    workflow_service.py

D. Configuration:
    app/core/config.py

E. MCP subprocess configuration

These are sensitive changes.

Therefore:

DO NOT modify them during this turn.

Instead:

1. Inspect the exact current implementation.
2. Identify the smallest required change.
3. Show the current behavior.
4. Show the proposed behavior.
5. Identify affected tests.
6. Explain compatibility impact.
7. Wait for explicit approval.

==================================================
5. APPROVED IMPLEMENTATION DESIGN
==================================================

## A. Investigation Integrity

Introduce explicit investigation outcomes.

At minimum:

    COMPLETED
    DEGRADED
    FAILED

The exact implementation may use the project's existing naming conventions if equivalent.

Required semantics:

COMPLETED
    Valid grounded investigation.

DEGRADED
    Investigation completed technically but evidence is insufficient,
    incomplete, unavailable, or otherwise not trustworthy.

FAILED
    Investigation could not complete because of a system/tool/runtime failure.

DEGRADED and FAILED MUST fail closed.

They MUST NOT be treated as:

    investigation_status = completed

==================================================
6. UNGROUNDED RECOMMENDATIONS

Current problem:

When the investigation is ungrounded:

- evidence is cleared
- hypotheses are cleared
- confidence is cleared

but model-generated recommendations may remain.

Gate 8 approved solution:

OPTION A

When the investigation is ungrounded, remove model-generated recommendations.

Keep only explicitly system-authored recovery/diagnostic next steps if the existing architecture already distinguishes them.

Examples:

- Verify the incident identifier.
- Restore access to retrieval tools.
- Retry investigation after retrieval becomes available.

Do NOT invent a new second policy engine.

Do NOT use an LLM to determine whether a recommendation is safe.

Required behavior:

Ungrounded investigation
        ↓
evidence = []
hypotheses = []
recommendations = []
confidence = 0
        ↓
fail closed

==================================================
7. FAILURE REASON

Separate investigation failure from policy denial.

Do NOT overload:

    DENY

to represent infrastructure or investigation failure.

For example, conceptually:

INVESTIGATION_FAILED
    !=
POLICY_DENIED

Add a minimal explicit failure reason where appropriate.

Do not redesign the entire workflow state machine.

Inspect the existing model and use the smallest compatible change.

==================================================
8. POLICY BOUNDARY

The deterministic policy engine remains authoritative.

The LLM MUST NOT:

- decide risk
- override policy
- approve itself
- change policy
- execute actions

Gate 8 must not introduce another semantic safety/policy system.

==================================================
9. CONFIGURABLE DATABASE

Current issue:

DATABASE_URL is not actually used consistently.

Gate 8 requirement:

Make the database configuration environment-driven.

The application and MCP subprocess must use the same configured database.

This is required for:

- isolated evaluation
- live evaluation fixtures
- Docker
- CI
- reproducibility

Do NOT redesign the persistence architecture.

Do NOT introduce PostgreSQL.

Use the existing SQLite architecture.

==================================================
10. EVALUATION DATASET V2

Expand the current golden dataset from approximately:

    12 cases
        ↓
    approximately 24 cases

Add coverage for scenarios identified in the Gate 8 review, including:

- memory leak
- authentication failure
- network timeout
- insufficient capacity
- ambiguous cause
- missing logs
- low-confidence evidence
- model timeout
- incomplete tool response
- additional prompt-injection channels

Preserve the existing cases.

Do not delete existing regression cases unless there is a documented reason.

Every new case must have:

- unique case ID
- scenario description
- expected behavior
- expected evidence where appropriate
- expected tool behavior where appropriate
- expected safety behavior
- deterministic scoring criteria

==================================================
11. RETRIEVAL EVALUATION

Add deterministic evaluation for the four controlled retrieval tools:

- get_incident_context
- get_related_incidents
- get_service_repository
- get_service_dependencies

Do NOT replace the existing retrieval architecture.

Do NOT introduce vector search.

Do NOT introduce RAGAS.

Create deterministic ground truth suitable for the existing evaluation harness.

The goal is to verify:

    expected retrieval
        vs
    actual retrieval

==================================================
12. TOOL-SELECTION EVALUATION

Add an evaluation metric for tool selection.

Measure:

- expected tools
- actual tools
- unnecessary tools

Do not require every available tool to be called.

The metric must respect the fact that different incidents may legitimately require different retrieval paths.

Do not make the evaluation artificially reward excessive tool usage.

==================================================
13. LATENCY

Add basic latency reporting.

At minimum distinguish useful timings such as:

- investigation duration
- evaluation duration where practical
- end-to-end workflow duration where available

Do not introduce a full observability platform.

Do not introduce token/cost infrastructure in Gate 8.

==================================================
14. DATASET CONTENT HASH

Current baseline can become stale because it relies on a dataset version identifier.

Improve this by recording a deterministic content hash of the evaluation dataset.

The baseline should be able to detect:

    same version label
    +
    changed dataset content

Do not create a complicated artifact-management system.

Use a simple deterministic hashing mechanism.

==================================================
15. CI

The Gate 8 CI requirement is:

Linux
+
Python 3.11
+
full pytest suite
+
evaluation replay

The existing Gate 7 evaluation workflow must not be the only CI confidence signal.

Ensure CI runs the complete test suite.

Where practical, validate locally using a Python 3.11 Linux Docker environment.

Do not add secrets.

Do not run live Claude in CI.

Do not require an Anthropic API key in CI.

==================================================
16. TEST DATABASE ISOLATION

Inspect the older tests that write to:

    ./pulseops.db

Determine the smallest safe change to move them toward isolated temporary databases.

Do not casually rewrite the entire test suite.

The goal is:

- tests should not pollute developer data
- tests should not depend on previous test execution
- CI should be reproducible

==================================================
17. DOCUMENTATION RECONCILIATION

Resolve the documentation contradictions.

Specifically document:

1. Which roadmap is authoritative.
2. Current actual Neo4j status.
3. Current actual ontology runtime status.
4. Current SQLite role.
5. Current graph projection behavior.
6. Current evaluation architecture.
7. Gate 8 scope.
8. Deferred production-hardening items.

Do NOT delete project-plan.md.md yet.

Recommend what should happen to it, but wait for approval before deletion.

==================================================
18. KNOWN ISSUES TO DOCUMENT, NOT FIX

The Gate 8 review found several issues outside this gate.

Do NOT implement them now.

Document as future gates:

- authentication
- RBAC
- real HITL identity
- PostgreSQL
- secrets management
- request IDs
- token/cost telemetry
- full observability
- n8n authentication
- n8n version pinning
- production Docker hardening
- Neo4j runtime integration
- cloud deployment
- frontend
- production monitoring

==================================================
19. REQUIRED IMPLEMENTATION PLAN

After inspecting the repository, return:

# Gate 8 Implementation Plan

## 1. Current Code Mapping

For every approved change:

| Gate 8 Requirement | Current File | Current Behavior | Proposed Change |

## 2. Frozen P6/P7 Changes

For every proposed change to P6/P7:

- file
- function/class
- current behavior
- exact problem
- proposed minimal change
- tests affected
- compatibility risk

## 3. Evaluation Changes

List:

- dataset files
- scorer files
- baseline files
- new metrics
- new fixtures
- new tests

## 4. CI Changes

Show:

- existing workflow
- proposed workflow changes
- commands to run
- Linux verification approach

## 5. Documentation Changes

List exact documents that need updating.

## 6. Implementation Order

Provide a numbered implementation sequence.

The implementation order should minimize risk.

## 7. Test Strategy

Explain:

- focused tests
- Gate 8 tests
- existing full suite
- Linux suite
- evaluation replay
- negative-control verification
- manual n8n verification

## 8. Acceptance Criteria

Provide a precise checklist.

## 9. Out-of-Scope Findings

List issues discovered that must be deferred.

## 10. Final Recommendation

Choose:

READY FOR IMPLEMENTATION

or

REVISE PLAN

==================================================
20. STOP CONDITION
==================================================

DO NOT modify files in this turn.

DO NOT implement the plan.

DO NOT install anything.

DO NOT delete anything.

DO NOT rename anything.

DO NOT change the database.

DO NOT change P6/P7 behavior.

DO NOT run live Claude.

After presenting the implementation plan, STOP and wait for my explicit approval.

We will then implement Gate 8 in small, verifiable steps.