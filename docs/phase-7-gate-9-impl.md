# PulseOps — Gate 9 Implementation
## Production Application Hardening & Local Platform Readiness

You are now implementing Gate 9 of the PulseOps AI Incident Intelligence Platform.

This is an IMPLEMENTATION task, not a review-only task.

The Gate 9 architecture review has already been completed and approved.

Before changing anything, read and understand:

1. CLAUDE.md
2. project-plan.md
3. docs/phase-7-gate-9.md
4. docs/architecture.md
5. docs/agent-architecture.md
6. docs/security.md
7. docs/phase-6.md
8. docs/phase-7.md
9. docs/phase-7-gate-8.md
10. Existing application code under app/
11. Existing tests under tests/
12. Existing Docker/n8n configuration

Do not assume that the review document is more current than the repository.
Inspect the actual repository and reconcile the implementation with the approved Gate 9 scope below.

============================================================
1. GATE 9 OBJECTIVE
============================================================

Gate 9 moves PulseOps from a secure engineering prototype toward a locally deployable production-style application.

The objective is:

"Make PulseOps safe to put behind a network while preserving the existing AI safety, deterministic policy, HITL, MCP, n8n, evaluation, and workflow architecture."

Gate 9 is LOCAL APPLICATION HARDENING.

It is NOT the cloud deployment gate.

============================================================
2. IMPORTANT ARCHITECTURAL BOUNDARY
============================================================

Gate 9 MUST NOT implement:

- AWS
- AWS account integration
- ECS
- EKS
- Kubernetes
- Terraform
- CloudFormation
- PostgreSQL
- Alembic
- RDS
- OIDC
- SSO
- OAuth
- multi-tenancy
- production cloud secret managers
- Neo4j runtime integration
- ontology runtime loading into Neo4j
- Neo4j Aura
- advanced observability infrastructure
- Grafana
- Prometheus
- distributed tracing backend
- frontend
- Slack integration
- GitHub write access
- autonomous production remediation
- multi-agent architecture
- vector database
- RAGAS
- DeepEval
- LLM-as-judge
- human evaluation UI

Those are later work.

SQLite remains the Gate 9 persistence layer.

Neo4j Desktop remains a local development environment.
The current application does NOT yet have to connect to Neo4j at runtime.
The ontology TTL does NOT need to be loaded into runtime Neo4j in Gate 9.

However, documentation must accurately state this current architecture.

============================================================
3. PRESERVE EXISTING ARCHITECTURE
============================================================

Do NOT rewrite or redesign the existing:

- Phase 5 Claude Agent SDK integration
- Phase 6 Incident Agent
- MCP retrieval boundary
- deterministic policy engine
- HITL decision model
- Gate 6 n8n orchestration boundary
- Gate 7 evaluation harness
- Gate 8 investigation integrity
- evidence grounding
- fail-closed behavior
- idempotency
- audit architecture

Make small additive changes where possible.

Do not replace working components merely for stylistic reasons.

Do not introduce unnecessary frameworks.

============================================================
4. AUTHENTICATION
============================================================

Implement the approved Gate 9 authentication model.

Create a clear authenticated Principal contract containing, as appropriate:

- principal_id
- principal_type
- display_name
- roles
- tenant_id
- auth_method
- authenticated_at

Supported principal types:

- human
- service
- agent
- system

Gate 9 authentication mechanism:

- bearer API credentials/tokens
- credentials configured through environment/configuration
- store only credential hashes where appropriate
- constant-time credential comparison
- no plaintext credentials in application logs
- no credentials in API responses
- no credentials in health responses
- no credentials in audit details

Authentication must be enforced at the FastAPI boundary.

Only explicitly approved public endpoints may remain unauthenticated:

- /
- /health

All other application endpoints must require an authenticated Principal.

Use the approved local development mechanism:

PULSEOPS_AUTH_MODE=dev

In development mode, allow the controlled dev principal mechanism described in the Gate 9 review.

The development header mechanism must:

- only work in development
- never be accepted in non-development environments
- never bypass production authentication
- be covered by tests

Do not implement OIDC/SSO.

============================================================
5. IDENTITY CONTEXT
============================================================

Replace the current placeholder identity handling with the authenticated Principal where appropriate.

The existing IdentityContext architecture should remain compatible with the Phase 5/6 agent architecture.

The agent should receive identity context derived from the authenticated request where the existing architecture requires it.

Do not allow arbitrary caller-supplied reviewer/requester identity to become trusted identity.

============================================================
6. RBAC
============================================================

Implement minimal deterministic RBAC.

Use the approved Gate 9 roles:

- service_n8n
- reviewer
- operator
- admin

Expected intent:

service_n8n:
- ingest/read
- cannot approve HITL

reviewer:
- read
- approve authorized HITL actions

operator:
- read
- create incidents / operational workflow actions as permitted

admin:
- full application permissions within Gate 9 scope

Do not implement dynamic roles.

Do not implement tenancy isolation.

Do not implement enterprise IAM.

Authorization must be checked separately from policy evaluation.

The deterministic policy engine remains the authority for:

- ALLOW
- NOTIFY
- HITL_REQUIRED
- DENY

RBAC determines whether the authenticated principal is allowed to perform the requested operation.

Never allow the LLM or agent to override RBAC or policy.

============================================================
7. HITL IDENTITY HARDENING
============================================================

This is a critical Gate 9 change.

The current free-text reviewer field must no longer be the source of authorization.

For consequential HITL decisions:

- authenticated principal must be used
- principal must be a human
- principal must possess the required role
- agent principals cannot approve
- service principals cannot approve
- arbitrary reviewer strings cannot authorize approval
- self-approval must be prevented where required by the existing architecture
- policy permitted_roles must actually be enforced

If the existing API continues accepting a reviewer field for compatibility during this release:

- it must not be trusted for authorization
- if supplied, it must match the authenticated human principal
- otherwise reject the request

Preserve existing idempotency and conflict behavior.

Do not redesign HITL expiry/escalation/notification in Gate 9.

============================================================
8. SECRETS AND CONFIGURATION
============================================================

Harden configuration.

Use environment/configuration for:

- authentication credentials/hashes
- Anthropic API configuration
- n8n credentials
- n8n encryption key
- Neo4j password where relevant to existing local configuration

Do not hard-code secrets.

Remove literal default passwords from committed configuration.

For example, do not leave:

NEO4J_PASSWORD=password

Use an environment substitution/configured secret instead.

Create or update:

.env.example

It must contain variable names and safe example placeholders only.

Never commit:

- API keys
- bearer tokens
- passwords
- credential hashes that are intended to be secret
- real Anthropic keys
- real n8n encryption keys

Production/non-development startup must fail closed if required security configuration is missing.

Development mode may have explicit development-only behavior.

Never expose secrets through:

- logs
- health endpoint
- error messages
- audit events
- API responses

============================================================
9. REQUEST IDs AND STRUCTURED LOGGING
============================================================

Implement request correlation.

For each HTTP request:

- accept a safe request ID if supplied
- otherwise generate one
- sanitize/validate the supplied value
- return the request ID in the response
- propagate it through relevant workflow operations

Do not trust arbitrary long or malformed request IDs.

Use structured logging where practical.

Logs should include useful fields such as:

- timestamp
- level
- request_id
- principal_id where available
- event_id
- incident_id
- workflow_id
- operation
- outcome
- error classification

Do not log:

- bearer tokens
- API keys
- passwords
- secrets
- raw authorization headers

Keep logging lightweight.
Do not introduce a full observability platform.

============================================================
10. AI TOKEN/COST RECORDING
============================================================

Record available AI execution metadata where the existing Claude Agent SDK integration exposes it.

At minimum, support fields for:

- duration
- token usage when available
- total_cost_usd when available

Do NOT implement:

- cost budgets
- cost enforcement
- billing dashboards
- external monitoring

This Gate 9 requirement is recording only.

Do not break the existing Agent SDK behavior if metadata is unavailable.

============================================================
11. N8N SECURITY
============================================================

Harden the local n8n integration.

n8n must authenticate when calling PulseOps.

Use a dedicated service principal:

service_n8n

n8n must NOT have permission to approve HITL actions.

The n8n webhook must use authentication/header credentials rather than an unauthenticated public webhook.

Do not put secrets directly into workflow JSON.

Use n8n credential storage/configuration.

Disable unnecessary automatic retries for consequential workflow calls.

Preserve the existing:

- 120 second timeout
- idempotency
- fail-closed behavior
- policy authority in PulseOps

n8n remains orchestration only.

Do NOT add:

- n8n AI Agent nodes
- direct Claude calls
- direct MCP calls
- direct Neo4j access
- direct SQLite access
- business policy logic

============================================================
12. N8N VERSION AND COMPOSE NETWORKING
============================================================

Pin the n8n Docker image version to:

n8n 2.41.6

Do not use:

n8nio/n8n:latest

Create/update the local Compose platform so PulseOps and n8n can communicate through a Docker network.

Where appropriate, n8n should call PulseOps using the Compose service name rather than:

host.docker.internal

The target architecture should be:

n8n container
    |
    | Docker network
    v
pulseops service

Do not remove the existing working n8n setup until the replacement is verified.

Do not make destructive changes.

If the old compose file is retained temporarily, document which configuration is canonical.

============================================================
13. DOCKER HARDENING
============================================================

Harden the PulseOps Docker image.

Requirements:

- non-root runtime user
- pinned base image rather than floating latest
- Python output unbuffered
- healthcheck
- appropriate Docker ignore configuration
- SQLite persistence mounted to /data where applicable
- no secrets baked into image
- application starts predictably

Keep the Docker image simple.

Do not introduce Kubernetes.

Do not introduce Terraform.

Do not introduce AWS-specific configuration.

============================================================
14. SEED DATA
============================================================

Remove production coupling to demo seed data.

In particular:

- no hard-coded INC-1007 as a runtime default
- development seed behavior must be explicitly controlled
- production/non-development startup must not silently recreate synthetic seed data

INC-1007 may remain as a development/test fixture where appropriate.

Do not delete useful test fixtures.

Do not remove valid synthetic data required by tests.

Make the environment boundary explicit.

============================================================
15. STUCK EVENT CLAIM RECOVERY
============================================================

Address the Gate 8/Gate 9 identified issue where an operational event can remain permanently claimed if the process dies during investigation.

Implement a safe recovery mechanism appropriate for the existing SQLite architecture.

Requirements:

- normal duplicate protection must remain
- concurrent duplicate deliveries must remain protected
- a legitimately in-progress event must not be incorrectly reclaimed
- stale processing claims must be recoverable
- recovery must be deterministic
- recovery must be auditable where appropriate
- do not introduce a background distributed worker system

Keep this implementation small and appropriate for local/single-instance SQLite.

============================================================
16. API BEHAVIOR
============================================================

Preserve the existing API contracts unless a security change requires adjustment.

Use appropriate HTTP statuses:

- 401 for unauthenticated access
- 403 for authenticated but unauthorized access
- 404 for unknown resources
- 409 for conflicting state/idempotency
- 400/422 for malformed input according to existing API conventions
- 502/appropriate failure response for downstream investigation failure where already established

Do not leak:

- stack traces
- exception internals
- credentials
- secrets
- filesystem paths unnecessarily

============================================================
17. AUDIT
============================================================

Extend existing audit records where necessary to capture authenticated identity.

Audit events should be able to establish:

- who performed the operation
- principal type
- request ID
- event/incident/workflow correlation
- action
- outcome
- timestamp

For HITL decisions, audit the authenticated principal rather than trusting free-text reviewer input.

Do not implement tamper-evident audit storage yet.

Do not implement audit export.

============================================================
18. TESTING REQUIREMENTS
============================================================

Add focused Gate 9 tests.

At minimum cover:

Authentication:
- unauthenticated access rejected
- health remains accessible
- root remains accessible
- valid service principal
- valid human principal
- invalid credential
- malformed credential
- development header works only in development
- development header rejected outside development

Authorization:
- n8n can ingest
- n8n cannot approve
- reviewer can approve authorized HITL
- operator permissions
- admin permissions
- unauthorized role returns 403
- agent cannot approve
- service cannot approve

HITL:
- authenticated human approval
- spoofed reviewer rejected
- reviewer mismatch rejected
- self-approval behavior
- unauthorized reviewer
- idempotent repeated approval
- conflicting approval remains rejected
- denied workflow cannot be overridden

Secrets/config:
- required production configuration fails closed
- no secrets in health response
- no secrets in error response
- no secrets in logs where testable

Request IDs:
- generated request ID
- supplied valid request ID
- malformed request ID sanitized/rejected
- response includes request ID
- audit correlation

n8n:
- authenticated request accepted
- unauthenticated request rejected
- n8n cannot approve
- no secret embedded in workflow JSON
- expected timeout/retry behavior

Seed:
- development seed works
- non-development does not silently seed
- no hard-coded INC-1007 behavior

Stuck claims:
- claim succeeds
- duplicate remains protected
- stale claim can be recovered
- active claim cannot be incorrectly reclaimed

Regression:
- all existing tests continue passing.

============================================================
19. TEST EXECUTION
============================================================

Use the existing project Python environment.

DO NOT create a new virtual environment.

The existing project uses:

.venv\Scripts\python.exe

Run focused Gate 9 tests first.

Then run:

.venv\Scripts\python.exe -m pytest -q

Also verify Linux/container compatibility as described in the existing project documentation.

Do not weaken or bypass tests.

Do not mark tests xfail simply to make the suite pass.

============================================================
20. DOCUMENTATION
================



============================================

Update the relevant Gate 9 documentation to record:

- what was implemented
- authentication model
- RBAC
- HITL identity
- configuration/secrets
- request IDs/logging
- n8n security
- Docker changes
- seed-data boundary
- stuck-claim recovery
- tests
- known limitations
- deferred Gate 10+ items

Clearly document:

Neo4j Desktop is available as a local development environment, but PulseOps does not yet consume Neo4j at runtime.

The ontology TTL exists, but runtime ontology loading into Neo4j is deferred.

AWS/cloud deployment is deferred.

PostgreSQL is deferred.

OIDC/SSO is deferred.

Do not falsely claim that Neo4j is already part of the runtime path.

============================================================
21. GATE 9 ACCEPTANCE CRITERIA
============================================================

Gate 9 is complete only if:

[ ] All application routes except explicitly public endpoints require authentication.

[ ] Authenticated Principal is available to the application.

[ ] RBAC is enforced.

[ ] n8n service identity exists.

[ ] n8n cannot approve HITL.

[ ] Only authorized human principals can approve HITL.

[ ] Reviewer free text is no longer authoritative.

[ ] AI/agent/service identities cannot approve HITL.

[ ] Secrets are configuration-driven.

[ ] Development-only authentication behavior cannot be used outside development.

[ ] Request IDs exist and are correlated.

[ ] Structured logging does not expose secrets.

[ ] Token/cost metadata is recorded where available.

[ ] n8n webhook is authenticated.

[ ] n8n version is pinned to 2.41.6.

[ ] PulseOps and n8n communicate through the intended local Compose network.

[ ] PulseOps Docker image runs as non-root.

[ ] Docker healthcheck exists.

[ ] SQLite persistence is configured appropriately.

[ ] Synthetic seed data is development-only.

[ ] Hard-coded INC-1007 runtime coupling is removed.

[ ] Stuck operational-event claims can be safely recovered.

[ ] Existing deterministic policy remains authoritative.

[ ] Existing idempotency remains intact.

[ ] Existing HITL fail-closed behavior remains intact.

[ ] Existing Phase 6 agent behavior remains intact.

[ ] Existing MCP boundary remains intact.

[ ] Existing Gate 7 evaluation harness remains intact.

[ ] Existing Gate 8 degraded/failed investigation fail-closed behavior remains intact.

[ ] Full test suite passes.

[ ] Linux/container verification passes.

[ ] Documentation accurately describes current architecture.

============================================================
22. GATE 9 NON-GOALS — DO NOT EXPAND SCOPE
============================================================

If you discover issues involving:

- PostgreSQL
- AWS
- Kubernetes
- Terraform
- OIDC
- SSO
- tenancy
- Neo4j runtime
- ontology runtime loading
- Neo4j Aura
- advanced observability
- HITL expiry
- HITL escalation
- Slack
- GitHub write access
- frontend
- production secret manager
- distributed workers
- rate limiting
- cost budgets

DO NOT implement them.

Record them under:

"Deferred to Gate 10+"

unless they are strictly necessary to satisfy a Gate 9 security requirement.

============================================================
23. IMPLEMENTATION DISCIPLINE
============================================================

Follow CLAUDE.md.

Before implementation:

1. Inspect the repository.
2. Inspect the current Gate 8 implementation.
3. Inspect current tests.
4. Inspect current Docker/n8n configuration.
5. Identify exact files that need modification.
6. Give a concise implementation plan.

Then implement in small verifiable increments.

After each major increment:

- run focused tests
- inspect failures
- fix root causes
- do not bypass tests

At the end:

- run the complete test suite
- run Linux/container verification
- verify Docker build
- verify local Compose startup
- verify n8n → PulseOps authentication
- verify HITL authorization
- verify health endpoint
- verify no secrets are exposed
- verify documentation

Do not stop after merely making the code compile.

============================================================
24. FINAL REPORT
============================================================

When implementation is complete, provide a Gate 9 completion report containing:

1. Files changed
2. Authentication implementation
3. RBAC implementation
4. HITL identity implementation
5. Secrets/configuration changes
6. Request ID/logging changes
7. Token/cost recording
8. n8n security changes
9. Docker/Compose changes
10. Seed-data changes
11. Stuck-claim recovery
12. Tests added
13. Full test result
14. Linux/container verification
15. Docker/Compose verification
16. n8n manual verification
17. Known limitations
18. Explicit Gate 10+ deferred items
19. Any warnings or issues that remain

Most importantly, distinguish:

PASS
PARTIAL
DEFERRED
BLOCKED

Do not claim Gate 9 is complete if any mandatory acceptance criterion failed.

STOP after the Gate 9 implementation and verification report.

Do not start Gate 10 automatically.
Do not start AWS work.
Do not start PostgreSQL.
Do not start Neo4j runtime integration.

============================================================
END OF GATE 9 IMPLEMENTATION PROMPT
============================================================