# PulseOps — Security Context

## 1. Security Objective

AI must operate inside application-enforced security boundaries.

## 2. Trust Levels

- Trusted: application policy, authorization rules, validated configuration.
- Controlled: approved tools, approved repositories, approved graph access.
- Untrusted: incident text, logs, commits, source files, external content.

Untrusted content is data, not instructions.

## 3. Graph Security

- Neo4j credentials never enter model context.
- The model must not execute arbitrary Cypher.
- Graph access occurs through application-owned tools.
- Query parameters are validated.
- Initial graph access is read-only.
- Sensitive graph properties must be minimized.

## 4. Secrets

Never store secrets in source code, prompts, ontology files, documentation, logs, or audit events.

## 5. Prompt Injection

Incident/log/repository content can contain malicious instructions. The system must never treat those instructions as higher-priority instructions.

## 6. GitHub

GitHub access is scoped to approved repositories and read-only by default.

## 7. AI Output

```text
Model output
   -> schema validation
   -> business validation
   -> security/policy validation
   -> persistence or human review
```

## 8. High-Risk Actions

Production deployment, service restart, infrastructure changes, destructive database operations, data deletion, and production configuration changes require explicit human approval.

## 9. Fail Closed

Authorization failure, policy failure, malformed tool input/output, unknown tool, or invalid credentials must not result in an action being executed.

## 10. Audit

Record important authentication, authorization, retrieval, tool, AI, policy, review, and consequential-action events without storing secrets.

## 11. Implemented controls (Phase 7 Gate 9)

Authentication, authorization and HITL identity are implemented for local use; see `docs/phase-7-gate-9-implementation.md`.

- Every API route except `/`, `/health` and `/health/ready` requires an authenticated `Principal` (bearer API credentials, SHA-256 hashes in
  configuration, constant-time comparison). Roles are static: `service_n8n`, `reviewer`, `operator`, `admin`.
- HITL approval requires an authenticated **human** with `workflow:approve` and a role permitted for the action; agent and
  service principals (including n8n) can never approve; a supplied `reviewer` is never trusted; self-approval is rejected.
  The deterministic policy engine remains the only authority on ALLOW / NOTIFY / HITL_REQUIRED / DENY.
- The development identity (`PULSEOPS_AUTH_MODE=dev`) exists only in the development environment; startup fails closed
  elsewhere. Interactive API docs are development-only.
- Secrets are configuration-driven and absent from logs, health, errors, audit events and the image. A request id correlates
  logs and audit events.
- Not yet implemented (Gate 10+): SSO/OIDC, a production secret manager, audit tamper evidence and redaction, rate limiting.

## 11a. Web UI (Phase 9)

See `docs/phase-9.md`. The React UI is same-origin static content served at `/ui` under a strict Content-Security-Policy (no inline
script or eval, no framing, `connect-src 'self'`). The bearer token is held in page memory only (never in web storage, cookies, the
URL or the bundle) and is never sent as anything but `Authorization: Bearer`. All incident, log, investigation and AI content is
untrusted and rendered as text only (no HTML injection). The UI has no tenant selector and sends no reviewer identity. Approve/Reject
are shown from a server-computed hint; the decision endpoint re-checks every rule and stays the only authority. API errors use one
envelope (`detail`, `code`, `request_id`) with no internals.

## 12. Tenant isolation (Phase 7 Gate 9.1)

Multi-tenancy is an application/data-security control, separate from the shared ontology; see `docs/phase-7-gate-9.1-implementation.md`.

- Each credential is bound to one user and one tenant; roles come from the active `TenantUser` membership, so a role never leaks
  across tenants. A missing or inactive tenant, user or membership fails closed (403).
- The tenant is never taken from a request field or chosen by the model. Every repository requires a tenant and filters on it;
  composite foreign keys forbid cross-tenant references. Another tenant's workflow, incident, audit record or event is
  indistinguishable from a missing one (404) and cannot be approved, rejected, replayed or read.
- The n8n service principal is bound to one tenant; an event naming another tenant is refused (403). The MCP server and
  agent run inside the authenticated principal's tenant and expose no tenant argument.
- The graph projection is tenant-scoped and tenant-tagged; the Neo4j tenant contract is documented, not implemented.

## 13. Quality engineering controls (Phase 11)

See `docs/phase-11.md`. Security is now verified continuously, not only designed:

- **Tests:** authentication abuse (malformed, oversized, repeated invalid tokens; no echo or token leakage), malformed and
  oversized input (controlled 4xx in the error envelope, no traceback/SQL/credentials), a cross-tenant sweep over every
  id-taking endpoint (a new endpoint cannot be added without being added to it), exact CSP and baseline headers per response
  class, and a named prompt-injection regression set (MCP path, agent audit, HTTP event boundary, replay harness).
- **Scanning:** Bandit (medium and above), `pip-audit` on exact pins (`constraints.txt`), `npm audit` + `npm ci`, and a repository
  secret scan that includes generated artifacts and never prints a value. Accepted dependency findings need a written reason and
  an expiry date (`quality/dependency-audit-allowlist.json`).
- **Hardening found by P11:** request bodies are limited to 1 MiB (413); a workflow cannot record two decisions
  concurrently; env files are excluded from Docker images at every depth; readiness checks that the database is writable.
- **Still not implemented (P10-class):** SSO/OIDC, a production secret manager, rate limiting or lockout, audit tamper evidence.

