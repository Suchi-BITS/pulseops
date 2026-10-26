# Phase 7 — Gate 9.1: Multi-Tenant Foundation

Extends Gate 9 (see `phase-7-gate-9-implementation.md`) with tenant-aware identity, authorization, persistence, workflow,
audit, retrieval and a graph-ready tenant boundary. Local SQLite only. Out of scope and **not** introduced: PostgreSQL,
Alembic, Neo4j runtime integration, ontology loading, cloud, OIDC/SSO, rate limits, cost budgets, HITL expiry.

## 1. Model

| Table | Purpose |
|---|---|
| `tenants` | `tenant_id` (PK), `tenant_name`, `status` (`active`/`inactive`), timestamps |
| `users` | `user_id` (PK), `email` (unique, optional), `display_name`, `user_type` (`human`/`service`/`agent`/`system`), `status`, timestamps. **No tenant column**: a user is global and may belong to many tenants. |
| `tenant_users` | PK `(tenant_id, user_id)` (uniqueness), foreign keys to both, `role` (CHECK: `service_n8n`/`reviewer`/`operator`/`admin`), `domain_roles` (JSON list such as `["sre"]`; matched only against a policy rule's `permitted_roles`, grants no application permission), `status`, timestamps |

The role belongs to the **membership**. User `u1` can be `reviewer` in tenant A and `operator` in tenant B; the reviewer
permission never follows the user into B. Only a human can hold `reviewer` (enforced when a membership is created and
again, fail-closed, when it is resolved).

## 2. Identity and authorization flow

```
Authorization: Bearer <token>
   -> constant-time hash match over all credentials          (unknown token: 401)
   -> credential = (user_id, tenant_id)                      (bound at configuration time)
   -> tenant exists+active, user exists+active, membership active
        any missing / inactive / inconsistent                 (403, fail closed)
   -> Principal(user_id, principal_type from users, tenant_id, roles = membership role + domain roles)
   -> require_permission(...)                                 (static RBAC, unchanged from Gate 9)
   -> tenant-bound services built from principal.tenant_id    (no shared module-level instances)
```

* `PULSEOPS_API_CREDENTIALS` entries are `{"principal_id", "tenant_id", "token_sha256"}`. `roles` / `principal_type` in a
  credential are rejected at startup: they come from the membership and the user record. Token hashes must be unique.
* The tenant is **never** read from a request body, query or header. `X-Tenant-ID` is not a mechanism in this gate.
* A user in several tenants holds one credential per tenant.
* Dev mode (`PULSEOPS_AUTH_MODE=dev`, development only): the header is `type:id:roles[:tenant]`; the tenant defaults to
  `dev`, a named tenant must exist and be active. The dev identity stands in for credential + membership; membership
  enforcement is exercised with bearer credentials.

## 3. Isolation strategy

* Every tenant-owned table has `tenant_id NOT NULL` with a foreign key to `tenants`: `services`, `incidents`, `logs`,
  `metrics`, `deployments`, `repositories`, `repository_mappings`, `workflow_instances`, `workflow_decisions`,
  `workflow_audit_events`, `workflow_idempotency_keys`, `operational_events`.
* **Keys.** Where a business id must repeat across tenants (incident/service/log/metric/deployment/repository/mapping ids,
  event ids, idempotency keys) the table gets an internal surrogate `row_id` primary key and `UNIQUE (tenant_id, <id>)`.
  Keeping `incident_id` as the sole primary key would make "the same `INC-1001` in two tenants" impossible, so for these
  tables the two requirements (keep global PKs / allow repeated ids) cannot both hold; the tenant-scoped UNIQUE is the
  identity. Workflow, decision and audit ids are generated unique ids and keep their primary keys, plus
  `UNIQUE (tenant_id, workflow_id)`.
* **Composite foreign keys** `(tenant_id, service_id) -> services(tenant_id, service_id)` (likewise incident, repository,
  workflow) make a cross-tenant reference impossible at the database level, not just in application code.
* **Repositories cannot exist without a tenant**: `BaseRepository(database_url, tenant_id)` rejects a blank tenant and has
  no default; every query carries `tenant_id = ?`. The same holds for `IncidentService`, `WorkflowService`,
  `OperationalEventService`, `IncidentRetrievalService`, `ContextBuilder`, `GraphRepository` and `build_mcp_server`.
* Another tenant's record is indistinguishable from a missing one (404), checked before any role or state logic.
* The only unscoped code is the tenant catalog (`TenantRepository`) and the explicit migration tool.

## 4. Workflow, HITL and audit

* `GET /workflow/{id}`, decisions, evaluation, replay and `/incidents/...` routes all resolve inside the principal's tenant.
* HITL approval requires, in order: authenticated principal → workflow exists **in the principal's tenant** → human →
  `workflow:approve` → reviewer field (if any) equals the principal → decision valid → policy `permitted_roles`/admin →
  no self-approval → existing Gate 9 idempotency/409 rules. A reviewer in tenant A approving tenant B's workflow gets 404.
* Audit rows carry `tenant_id` (column and metadata), `actor` (user id), `actor_type`, roles and `request_id` (metadata),
  incident id, workflow id, timestamp and event type. The workflow/audit API only returns the caller's tenant's rows.
  Stuck-claim recovery, idempotency and event deduplication are per tenant: the same `event_id` or idempotency key in two
  tenants are independent; reuse with different data conflicts (409) only inside one tenant.

## 5. n8n service principal

`svc-n8n` is an ordinary `User` (`user_type=service`) with a `service_n8n` membership in **one** tenant; its credential is
bound to that tenant (use one service user and token per tenant). An event may carry an optional `tenant_id`; it is
accepted only if it equals the principal's tenant and refused with 403 otherwise. There is no global bypass. n8n still
cannot approve, evaluate, investigate or read another tenant's data, and a service user can never hold `reviewer`.

## 6. MCP and agent

`authenticated request → principal.tenant_id → IdentityContext → agent → MCP subprocess env PULSEOPS_TENANT_ID → tenant-bound
IncidentRetrievalService`. No MCP tool has a tenant argument; the MCP process refuses to start without `PULSEOPS_TENANT_ID`;
the agent refuses to build its options without a tenant context; `/agent/investigate` first checks the incident exists in the
caller's tenant. The model can neither choose nor override the tenant. The agent SDK, prompts and policy engine are unchanged.

## 7. Graph-ready contract (no Neo4j runtime)

* The SQLite graph projection is tenant-scoped (it only reads one tenant's data) and every node and relationship carries
  `tenant_id`.
* `GraphSchema` documents the future contract: tenant-owned classes carry `tenant_id`; identity is
  `(tenant_id, <business id>)` (e.g. `REQUIRE (i.tenant_id, i.incident_id) IS UNIQUE`); every application-owned Cypher
  template must bind `$tenant_id`. Enforcement lives in the application/repository layer, never in a prompt.
* The ontology (`ontology/pulseops.ttl`) stays one shared, global semantic model. No `Tenant` class was added and the file was
  not changed; tenant isolation is an application/data-security concern. Nothing loads the ontology at runtime.

## 8. Database safety and migration

Normal startup **never** rebuilds tables. Opening a pre-9.1 database raises `LegacySchemaError` and leaves the file
untouched. Use the explicit, one-time tool on a database you name:

```
python -m app.migrations.gate9_1 sqlite:///./pulseops.db [--tenant-id dev]
```

It writes `<file>.pre-gate9_1.bak` first (refuses to overwrite one), then renames, recreates and copies in one transaction,
assigns all rows to the `dev` tenant, verifies row counts and foreign keys, and rolls back entirely on any error. It is
idempotent. Alternatively point `PULSEOPS_DATABASE_URL` at a fresh file. The `D:\pulseops*.db` files were not touched.

Seed data stays development-only and now belongs to the explicit `dev` tenant. It is inserted all-or-nothing, only into a
development tenant that has no services (previously each empty table was re-seeded independently).

## 9. Provisioning (operator action)

```
python -m app.tenancy_admin create-tenant acme "Acme"
python -m app.tenancy_admin create-user svc-n8n "n8n" --type service
python -m app.tenancy_admin add-member acme svc-n8n service_n8n
python -m app.tenancy_admin create-user alice "Alice" --email alice@example.com
python -m app.tenancy_admin add-member acme alice reviewer --domain-roles sre,incident_manager
python -m app.core.credentials --generate     # bind the hash in PULSEOPS_API_CREDENTIALS with tenant_id "acme"
```

In Docker Compose run these with `docker compose exec pulseops python -m app.tenancy_admin ...` after the first start (a
non-development deployment has no demo tenant). There is no public tenant-management API.

## 10. Changes outside tenancy

* `/retrieval/services/{id}/dependencies|incidents` declared `dict[str, list[str]]` but return a string `service_id`, so
  they always failed response validation with a 500. The annotation is now `dict[str, Any]`.
* The module-level `workflow_service`/`incident_service`/`event_service` singletons were replaced by per-request,
  tenant-bound factories (`workflow_api.*_for(tenant_id)`); tests and the policy evaluation patch the factories.

## 11. Limitations / deferred

* Dev-mode identity bypasses the membership table by design (development only).
* Credentials are static shared secrets: no rotation or revocation other than deactivating the membership/user/tenant.
* No tenant-management API, no cross-tenant admin role, no per-tenant quotas or encryption.
* `repositories`/`repository_mappings` and services have no creation API (unchanged); a new tenant's catalog must be loaded
  by an operator. The `dev` tenant name is fixed.
* The Neo4j projection, constraints and Cypher templates are a documented contract only. PostgreSQL/Alembic, SSO/OIDC,
  audit tamper-evidence, rate limits and cost budgets remain Gate 10+.

## 12. Verification (Gate 9.1)

| Check | Result |
|---|---|
| Gate 9.1 tests (`tests/test_phase7_gate9_1.py`) | 31 passed |
| Full suite, Windows (`.venv`, Python 3.12) | 266 passed |
| Full suite, Linux (python:3.11, uid 10001) | 266 passed |
| Evaluation replay (Linux) | GATE: PASS |
| Live Claude run / GitHub-hosted CI / Docker Compose re-verification | not run in this gate |
