============================================================
GATE 9.1 — MULTI-TENANT FOUNDATION
IMPLEMENTATION
============================================================

OBJECTIVE
---------

Extend the completed Gate 9 implementation with a
production-oriented multi-tenant foundation.

Gate 9 security, authentication, RBAC, HITL identity,
request IDs, structured logging, Docker hardening,
n8n authentication, configuration hardening, and existing
workflow/policy behavior are already implemented and tested.

Do NOT rewrite Gate 9.

This is a focused Gate 9.1 extension.

The objective is to establish tenant-aware identity,
authorization, persistence, operational-data isolation,
workflow isolation, audit isolation, and a graph-ready
tenant boundary.

PostgreSQL, Neo4j runtime integration, ontology loading,
AWS/cloud deployment, OIDC/SSO, and other Gate 10+ work
remain OUT OF SCOPE.

============================================================
1. READ FIRST
============================================================

Before changing anything, inspect:

- CLAUDE.md
- project-plan.md
- docs/phase-7-gate-9.md
- docs/phase-7-gate-9-implementation.md
- current authentication/security implementation
- Principal / IdentityContext implementation
- current database schema
- database/repository layer
- incident/service/workflow/event/audit models
- MCP implementation
- retrieval/context-building implementation
- graph projection implementation
- existing tests
- current n8n integration

Do not assume names or schemas.

Use the actual repository structure.

Do not modify files during the initial inspection.

First explain:

1. current identity flow
2. current persistence model
3. current tenant isolation status
4. all tenant-owned entities
5. current workflow/audit boundaries
6. current graph projection boundary
7. proposed minimal Gate 9.1 changes

Then wait for approval before implementation.

============================================================
2. TENANT DATA MODEL
============================================================

Introduce a relational tenant identity model:

Tenant
------

tenant_id
tenant_name
status
created_at
updated_at


User
----

user_id
email
display_name
status
created_at
updated_at


TenantUser
----------

tenant_id
user_id
role
status
created_at
updated_at

Requirements:

- User may belong to multiple tenants.
- A user's role is associated with the tenant membership.
- Enforce uniqueness of (tenant_id, user_id).
- Enforce valid foreign-key relationships.
- Do not duplicate a User record for every tenant.
- Do not put a single tenant_id on User as the primary
  multi-tenancy model.
- Keep the schema migration-friendly for future PostgreSQL.
- Do not introduce PostgreSQL/Alembic in Gate 9.1.

Use the existing persistence mechanism for now.

============================================================
3. PRINCIPAL AND TENANT CONTEXT
============================================================

Extend the existing authenticated Principal so that the
application has an explicit tenant context.

The effective context should contain, as appropriate:

- principal_id
- principal_type
- user_id
- tenant_id
- roles
- auth_method
- authenticated_at

Tenant context MUST originate from authenticated identity
and validated TenantUser membership.

Do NOT trust an arbitrary tenant_id supplied by an
unauthenticated or unauthorized request.

The LLM/agent must never select or override tenant context.

============================================================
4. RBAC + TENANT MEMBERSHIP
============================================================

Existing Gate 9 roles must remain compatible.

A role is evaluated in the context of a tenant membership.

For example:

User U1:
    Tenant A -> reviewer
    Tenant B -> operator

U1 must have reviewer permissions only while operating
within Tenant A.

U1 must not automatically receive reviewer permissions
inside Tenant B.

Validate:

- tenant exists
- user exists
- membership exists
- membership is active
- role is valid
- requested operation is permitted for that tenant

Fail closed when membership or authorization is absent.

============================================================
5. TENANT ISOLATION OF OPERATIONAL DATA
============================================================

Inspect the existing data model and identify every entity
that represents tenant-owned operational/business data.

At minimum evaluate:

- Incident
- Service
- Log
- Metric
- Deployment
- Repository
- RepositoryMapping
- OperationalEvent
- WorkflowInstance
- WorkflowDecision
- AuditEvent
- Idempotency records
- related workflow/event state

Do not blindly add tenant_id to every table.

Determine ownership from the existing architecture.

For every tenant-owned entity:

- associate it with tenant_id
- enforce tenant-scoped access
- ensure repository queries require tenant context
- prevent cross-tenant reads
- prevent cross-tenant writes
- prevent cross-tenant workflow operations
- prevent cross-tenant audit access

Existing business behavior must remain intact.

============================================================
6. INCIDENT AND EVENT ISOLATION
============================================================

The same logical incident identifier may exist in multiple
tenants.

Therefore identity should be treated as:

    (tenant_id, incident_id)

rather than globally assuming incident_id is unique across
all tenants.

Apply the same reasoning to other tenant-scoped identifiers
where appropriate.

Do not break existing development data unnecessarily.

Create an explicit development tenant for existing seed/demo
data when required.

Seed/demo data must remain development-only.

============================================================
7. WORKFLOW AND HITL ISOLATION
============================================================

Every workflow operation must be tenant-aware.

A workflow belonging to Tenant A must not be:

- viewed by Tenant B
- approved by Tenant B
- rejected by Tenant B
- modified by Tenant B
- replayed by Tenant B

HITL approval must require:

1. authenticated principal
2. human principal type
3. appropriate reviewer role
4. active TenantUser membership
5. same tenant as the workflow
6. valid workflow state
7. existing Gate 9 approval/idempotency rules

The supplied reviewer field must never become an
authorization mechanism.

Preserve the Gate 9 security model.

============================================================
8. AUDIT ISOLATION
============================================================

Audit records must carry sufficient identity context,
including where appropriate:

- tenant_id
- principal_id
- principal_type
- roles
- request_id
- incident_id
- workflow_id
- timestamp
- event type

Tenant A users must not be able to retrieve Tenant B audit
records.

Do not expose secrets.

============================================================
9. n8n SERVICE PRINCIPAL
============================================================

The existing n8n service principal must remain compatible.

Do not create a global tenant bypass.

Determine and document how the n8n service principal is
associated with tenant context.

A tenant_id supplied in an event must only be accepted when
the authenticated service principal is authorized for that
tenant.

n8n must not be able to:

- impersonate a human reviewer
- approve HITL
- bypass tenant authorization
- access another tenant without authorization

Preserve the existing Gate 9 behavior.

============================================================
10. MCP AND AGENT TENANT BOUNDARY
============================================================

Inspect the existing MCP and Incident Agent path.

Establish a tenant-aware boundary so that:

    authenticated request
          ↓
    tenant context
          ↓
    workflow/event
          ↓
    incident retrieval
          ↓
    MCP
          ↓
    agent

The agent must not choose its own tenant.

MCP retrieval must not allow a caller to retrieve another
tenant's incident/service/log/metric data.

Do not redesign the Agent SDK.

Do not introduce multi-agent behavior.

Do not introduce embeddings or vector search.

============================================================
11. GRAPH-READY TENANT MODEL
============================================================

DO NOT implement Neo4j runtime integration in Gate 9.1.

DO NOT load pulseops.ttl into Neo4j yet.

However, establish the architectural contract required for
future Neo4j tenant isolation.

The model must distinguish:

GLOBAL SHARED SEMANTIC LAYER
----------------------------

- pulseops.ttl
- ontology classes
- object properties
- data properties
- domain/range
- semantic definitions

from:

TENANT DATA INSTANCES
---------------------

Tenant A operational instances
Tenant B operational instances
Tenant C operational instances

The ontology is shared.

Do not duplicate the ontology for each tenant.

The future graph projection must carry tenant context for
tenant-owned instances, for example:

(:Incident {
    incident_id: "...",
    tenant_id: "..."
})

and retrieval must require tenant scope.

The application/repository layer must enforce this.

Do not rely on an LLM prompt for graph security.

If the current SQLite graph projection can safely be made
tenant-aware without introducing Neo4j runtime integration,
do so.

Otherwise document the exact graph contract and defer the
runtime implementation.

============================================================
12. ONTOLOGY BOUNDARY
============================================================

Do not redesign pulseops.ttl in this gate.

Do not create one ontology per tenant.

Treat the ontology as the shared semantic model.

Tenant-specific operational data are instances mapped to the
shared ontology.

If the current ontology has no explicit Tenant concept,
do not invent one merely for authorization.

Tenant isolation is an application/data security concern;
ontology semantics and access control must remain separated.

============================================================
13. TESTING
============================================================

Add focused Gate 9.1 tests.

At minimum test:

A. Tenant creation
B. User creation
C. TenantUser membership
D. Same user in multiple tenants
E. Different roles per tenant
F. Missing membership
G. Inactive membership
H. Cross-tenant incident read
I. Cross-tenant incident write
J. Cross-tenant service retrieval
K. Cross-tenant workflow access
L. Cross-tenant HITL approval
M. Cross-tenant audit access
N. n8n tenant authorization
O. Agent cannot select another tenant
P. MCP tenant isolation
Q. Tenant-scoped idempotency
R. Tenant-scoped event deduplication
S. Existing Gate 9 authorization remains intact
T. Existing Gate 7/8 evaluation remains intact
U. Existing development seed behavior

Include at least one explicit security test:

    Tenant A authenticated user
          attempts
    Tenant B resource access
          -> DENIED

and:

    Tenant A reviewer
          attempts
    Tenant B workflow approval
          -> DENIED

Also test:

    Same user
       Tenant A = reviewer
       Tenant B = operator

and verify that the role does not leak between tenants.

============================================================
14. REGRESSION SAFETY
============================================================

Do not rewrite:

- Phase 5 Agent SDK
- Phase 6 Incident Agent
- Phase 7 policy engine
- Gate 7 evaluation architecture
- Gate 8 evaluation changes
- Gate 9 authentication/security architecture

unless a small compatibility change is strictly necessary.

Preserve all existing behavior outside tenant isolation.

Run:

- Gate 9.1 focused tests
- full test suite
- evaluation replay
- Windows verification
- Linux Python 3.11 verification

Report exact test counts.

============================================================
15. OUT OF SCOPE
============================================================

DO NOT implement:

- PostgreSQL
- Alembic
- SQLAlchemy migration
- AWS
- cloud deployment
- ECS
- EKS
- Kubernetes
- Terraform
- OIDC
- SSO
- MFA
- Neo4j runtime integration
- Neo4j ontology loading
- production graph ingestion
- Slack
- GitHub write access
- autonomous remediation
- multi-agent architecture
- vector database
- embeddings
- RAGAS
- DeepEval
- LLM-as-judge
- frontend redesign
- rate limiting
- cost budgets
- HITL expiry/escalation
- production notification infrastructure

Those remain later work.

============================================================
16. ACCEPTANCE CRITERIA
============================================================

Gate 9.1 is complete only when:

[ ] Tenant/User/TenantUser model implemented
[ ] Multi-tenant membership works
[ ] Roles are tenant-scoped
[ ] Principal contains validated tenant context
[ ] Tenant-owned operational data are isolated
[ ] Cross-tenant access fails closed
[ ] Workflow is tenant-scoped
[ ] HITL is tenant-scoped
[ ] Audit is tenant-scoped
[ ] n8n cannot bypass tenant authorization
[ ] MCP retrieval is tenant-scoped
[ ] Agent cannot choose tenant
[ ] Idempotency/event deduplication is tenant-safe
[ ] Graph projection contract is tenant-aware
[ ] Shared ontology remains global
[ ] No Neo4j runtime integration introduced
[ ] No PostgreSQL introduced
[ ] Existing Gate 9 tests continue passing
[ ] Full suite passes
[ ] Replay passes
[ ] Windows verification passes
[ ] Linux verification passes
[ ] Documentation updated
[ ] No secrets introduced

============================================================
17. FINAL REPORT
============================================================

At the end report:

1. files changed
2. schema/model changes
3. tenant identity flow
4. authorization flow
5. tenant isolation strategy
6. workflow/HITL isolation
7. MCP/agent isolation
8. graph-ready design
9. tests added
10. Windows result
11. Linux result
12. replay result
13. any limitations
14. anything intentionally deferred

STOP after the Gate 9.1 implementation.

Do not begin Gate 10.

============================================================
END OF GATE 9.1
============================================================