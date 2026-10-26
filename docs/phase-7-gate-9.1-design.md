GO, with the following two design changes.

1. CREDENTIAL-TO-TENANT BINDING — APPROVED

Use the proposed default:

- Each API credential is bound to exactly one user_id and one
  tenant_id.
- The authenticated Principal therefore has a resolved tenant_id.
- A user belonging to multiple tenants may have separate
  tenant-bound credentials.
- Do not introduce X-Tenant-ID as the primary tenant-selection
  mechanism in this gate.
- The role must come from the active TenantUser membership, not
  from the credential itself.

2. N8N SERVICE PRINCIPAL — APPROVED

Use the proposed default:

- Represent service_n8n using the existing User/Principal model.
- Bind service_n8n to one tenant.
- Use principal_type to distinguish service from human.
- TenantUser supplies the service principal's role.
- Do NOT introduce a separate service-account table.
- service_n8n must never be authorized as a human reviewer.

3. CHANGE THE DATABASE KEY DESIGN

Do NOT convert the existing tenant-owned tables to composite
primary keys such as:

    PRIMARY KEY (tenant_id, incident_id)

Keep the existing surrogate/global primary identifiers where
appropriate.

Add tenant_id as a required tenant boundary and use composite
UNIQUE constraints where tenant-scoped uniqueness is required.

For example:

    incident_id PRIMARY KEY
    tenant_id NOT NULL
    UNIQUE (tenant_id, incident_id)

Apply the same principle to other entities based on the actual
schema.

In particular:

- incident identity must support the same incident_id in
  different tenants.
- operational event deduplication must be tenant-scoped.
- idempotency keys must be tenant-scoped.
- repository lookups must always include tenant context.
- workflow identity can retain its existing primary identifier
  while all access remains tenant-scoped.

Do not mechanically change every primary key.

4. CHANGE THE DATABASE MIGRATION APPROACH

Do NOT perform an automatic destructive/reconstructive schema
migration on every normal application startup.

Do not make startup silently rebuild existing tables.

Instead, use one of these controlled approaches:

A. an explicit one-time development migration that moves existing
   development records into the dev tenant,

or

B. a controlled fresh development schema if the existing database
   is disposable.

Choose the safer approach after inspecting the actual database
and existing initialization code.

Existing development data may be assigned to:

    tenant_id = "dev"

but do not modify unrelated D:\pulseops*.db files.

Normal application startup must not perform destructive schema
reconstruction.

5. EVERYTHING ELSE IN THE INSPECTION IS APPROVED

Proceed with:

- Tenant
- User
- TenantUser
- tenant-scoped roles
- authenticated tenant context
- tenant-aware repositories
- tenant-aware incidents/services/events/workflows
- tenant-aware HITL
- tenant-aware audit
- tenant-scoped idempotency
- tenant-scoped event deduplication
- n8n tenant binding
- MCP tenant isolation
- agent tenant isolation
- tenant-aware SQLite graph projection
- graph tenant-scoping contract
- shared global PulseOps ontology
- Gate 9.1 tests
- documentation

The ontology remains global/shared.

Do NOT create a separate ontology per tenant.

Do NOT implement Neo4j runtime integration or TTL loading.

Do NOT implement PostgreSQL/Alembic.

Do NOT start Gate 10.

Preserve all existing Gate 9 authentication, RBAC,
HITL, policy, evaluation, n8n and Docker behavior.

After implementation, stop and provide the complete Gate 9.1
implementation report with:

1. files changed
2. schema changes
3. identity/tenant flow
4. authorization flow
5. tenant isolation strategy
6. workflow/HITL isolation
7. MCP/agent isolation
8. graph-ready design
9. tests added
10. Windows test result
11. Linux test result
12. replay result
13. limitations
14. deferred work

Do not begin Gate 10.