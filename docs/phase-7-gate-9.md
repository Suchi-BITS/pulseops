Gate 9 — Production Platform & Application Architecture Review
PLAN ONLY — DO NOT MODIFY FILES

Gate 8 is COMPLETE and APPROVED.

Gate 8 verification:
- 187 tests passed on Windows
- 187 tests passed in Python 3.11 Linux container as non-root
- Gate 7 replay passes
- negative control works
- dataset tampering detection works
- n8n LOW/HITL/DENY/DEGRADED/FAILED manually verified
- CI workflow created and locally verified
- GitHub-hosted CI has not yet run
- live Claude evaluation has not yet run because no API key is configured

Do NOT modify any files during this task.

The purpose of this task is to perform a READ-ONLY architecture review and implementation plan for Gate 9.

==================================================
1. READ THESE FIRST
==================================================

Read:

- CLAUDE.md
- project-plan.md
- IMPLEMENTATION-ROADMAP.md
- docs/architecture.md
- docs/business-context.md
- docs/data-model.md
- docs/security.md
- docs/agent-architecture.md
- docs/phase-7-gate-6.md
- docs/phase-7-gate-7.md
- docs/phase-7-gate-8.md
- docs/knowledge-graph.md
- docs/ontology.md

Also inspect the actual application structure:

- app/
- tests/
- evals/
- n8n/
- Dockerfile
- docker-compose.yml
- .github/workflows/
- pyproject.toml

Do not rely only on documentation.
Inspect the actual code and tests.

==================================================
2. IMPORTANT: GATE 9 IS NOT IMPLEMENTATION YET
==================================================

Do not:

- modify files
- create files
- delete files
- rename files
- install packages
- modify databases
- run live Claude
- modify n8n workflows
- migrate PostgreSQL
- connect production services

This is architecture review and implementation planning only.

Stop after producing the plan and wait for explicit approval.

==================================================
3. GATE 9 OBJECTIVE
==================================================

Determine the smallest coherent scope that should move PulseOps from the current validated AI-engineering prototype toward a production-oriented application/platform foundation.

Gate 9 must NOT become a catch-all phase.

Separate:

A. Required for Gate 9
B. Useful but should remain later
C. Explicitly out of scope

==================================================
4. REVIEW THE FOLLOWING DEFERRED ITEMS
==================================================

A. AUTHENTICATION

Inspect the current identity model.

Determine:

- Where authentication should occur
- What user identity should look like
- How IdentityContext should be populated
- Whether API authentication should be introduced
- How service-to-service authentication should work
- How n8n should authenticate to PulseOps
- How MCP authentication should be handled
- Whether local development needs a simple development identity mechanism

Do NOT implement authentication.

Recommend the minimum architecture appropriate for Gate 9.

==================================================
5. AUTHORIZATION / RBAC
==================================================

Inspect:

- roles
- permissions
- permitted_roles
- HITL approval checks
- workflow authorization

Determine whether Gate 9 should introduce:

- role-based access control
- action-level authorization
- approval permissions
- tenant/user boundaries

Explicitly identify what must NOT be implemented yet.

==================================================
6. REAL HITL IDENTITY
==================================================

The current AI-reviewer protection uses a heuristic.

Inspect the implementation.

Design a proper future contract for:

- authenticated human identity
- reviewer ID
- reviewer role
- approval authorization
- audit identity
- separation of AI identity from human identity

Do not implement it.

Explain what Gate 9 should actually implement and what should remain later.

==================================================
7. DATABASE / PERSISTENCE
==================================================

Review the current SQLite architecture.

Determine whether Gate 9 should introduce PostgreSQL.

If yes, define:

- migration strategy
- SQLAlchemy/database abstraction implications
- connection configuration
- transaction boundaries
- test database strategy
- local Docker PostgreSQL
- production PostgreSQL boundary
- compatibility with current SQLite development/testing

Do not perform migration.

If PostgreSQL should remain later, explain why.

==================================================
8. SECRETS AND CONFIGURATION
==================================================

Inspect:

- .env handling
- configuration classes
- Docker configuration
- Neo4j credentials
- n8n credentials
- Claude API configuration

Design the minimum Gate 9 secrets/configuration architecture.

Explicitly distinguish:

- local development secrets
- CI secrets
- application runtime secrets
- future production secret manager

Do not introduce a cloud secret manager unless you determine it is genuinely required.

==================================================
9. OBSERVABILITY
==================================================

Review current telemetry.

Determine what Gate 9 should introduce for:

- request ID
- correlation ID
- event ID
- incident ID
- workflow ID
- investigation duration
- model duration
- tool-call duration
- token usage
- estimated cost
- structured logs
- error classification

Separate:

MUST HAVE NOW

from

LATER / PRODUCTION SCALE

Do not introduce a full observability platform unless justified.

==================================================
10. DOCKER / LOCAL PLATFORM
==================================================

Review:

- Dockerfile
- docker-compose.yml
- n8n container
- PulseOps container
- Neo4j configuration
- health checks
- non-root execution
- pinned image versions
- environment configuration
- networking

Determine whether Gate 9 should establish a coherent local platform:

PulseOps
+
PostgreSQL
+
Neo4j
+
n8n

or whether some components should remain outside Docker.

Do not implement yet.

==================================================
11. N8N SECURITY
==================================================

Review the current n8n integration.

Determine:

- webhook authentication
- service-to-service authentication
- timeout handling
- retry behavior
- pinned n8n version
- credential handling
- failure semantics
- duplicate handling

Do not introduce Slack or other external integrations.

==================================================
12. NEO4J / ONTOLOGY RUNTIME STATUS
==================================================

Review the current architecture carefully.

The current documented reality is:

- SQLite is operational persistence
- graph is currently derived from SQLite
- Neo4j is not yet connected at runtime
- pulseops.ttl is not loaded by runtime code

Determine whether actual Neo4j runtime integration belongs in Gate 9.

If yes, define the minimal implementation boundary.

If no, explicitly defer it.

Do not silently change the architecture.

==================================================
13. REMOVE PROTOTYPE COUPLING
==================================================

Review:

- hard-coded INC-1007
- synthetic seed behavior
- dependency placeholder
- default data assumptions
- workflow-state ambiguity
- stuck processing event claims

Classify each item:

Gate 9 required
Gate 10+
Future / acceptable prototype limitation

Do not fix them yet.

==================================================
14. PRODUCTION APPLICATION BOUNDARY
==================================================

Determine whether Gate 9 should introduce a cleaner application architecture around:

API
↓
Authentication
↓
Authorization
↓
Workflow
↓
Agent
↓
MCP
↓
Operational data
↓
Audit

Identify any architectural boundaries that need to be established before cloud deployment.

==================================================
15. DO NOT EXPAND THE SCOPE
==================================================

Explicitly exclude unless you find a critical architectural dependency:

- AWS deployment
- Kubernetes
- Terraform
- cloud networking
- frontend
- Slack
- GitHub write access
- autonomous remediation
- multi-agent architecture
- vector database
- embeddings
- RAGAS
- DeepEval
- LLM-as-judge
- human evaluation UI
- production feedback system
- large observability platform
- advanced event streaming
- Kafka
- microservice decomposition

These belong to later stages unless the architecture review proves otherwise.

==================================================
16. REQUIRED OUTPUT
==================================================

Produce a detailed Gate 9 architecture review containing:

1. Executive summary

2. Current architecture after Gate 8

3. Current production-readiness assessment

4. Deferred-item classification table:

   Item
   Current state
   Risk
   Gate 9?
   Reason
   Dependencies

5. Authentication architecture

6. Authorization/RBAC architecture

7. HITL identity architecture

8. Database architecture

9. Secrets/configuration architecture

10. Observability architecture

11. Docker/local platform architecture

12. n8n security architecture

13. Neo4j/ontology decision

14. Prototype-coupling cleanup decision

15. Proposed Gate 9 architecture diagram

16. Proposed Gate 9 implementation sequence

17. Tests required

18. Security tests required

19. Migration/rollback considerations

20. What remains explicitly deferred to Gate 10+

21. Gate 9 acceptance criteria

22. Risks and trade-offs

23. Estimated implementation complexity:
    - Small
    - Medium
    - Large
    for each proposed workstream

24. Final recommendation:

    READY FOR IMPLEMENTATION
    or
    REVISE PLAN

==================================================
17. MOST IMPORTANT RULE
==================================================

Do not try to solve everything.

Gate 9 should establish the minimum trustworthy application/platform foundation required before later cloud/platform work.

Preserve the existing working architecture.

Do not rewrite P5/P6/P7/P8.

Do not change working behavior merely for stylistic reasons.

Do not implement anything.

STOP after the architecture review and wait for my approval.