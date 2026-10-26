# Phase 7 Gate 9 - Production Application Hardening & Local Platform Readiness

Objective: make PulseOps **safe to put behind a network** while preserving the existing AI safety, deterministic policy,
HITL, MCP, n8n, evaluation and workflow architecture. This is local application hardening, **not** the cloud gate.

## What was implemented

| Area | Change |
|---|---|
| Authentication | Bearer API credentials -> an authenticated `Principal`, enforced at router level (deny by default). Only `/` and `/health` are public. |
| RBAC | Static roles `service_n8n`, `reviewer`, `operator`, `admin`; authorization is separate from, and never overrides, the deterministic policy engine. |
| HITL identity | The reviewer is the authenticated human principal; the free-text `reviewer` field is no longer authoritative; policy `permitted_roles` are enforced; self-approval is prevented. |
| Secrets / config | Everything environment-driven; credentials stored as SHA-256 hashes; no literal default passwords; startup fails closed outside development. |
| Request IDs / logging | `X-Request-ID` (sanitised or generated), JSON logs with correlation ids and secret redaction, request id + principal in every audit event. |
| AI cost recording | Duration, token usage and `total_cost_usd` recorded from the SDK when exposed (recording only). |
| n8n | Authenticated webhook and a dedicated `service_n8n` credential (referenced, never embedded), pinned to 2.41.6, called by Compose service name. |
| Docker / Compose | Non-root, pinned, healthchecked image; Compose platform `pulseops` + `n8n` on a Docker network; SQLite on `/data`. |
| Seed data | Demo data is development-only; the hard-coded `INC-1007` default is gone. |
| Stuck claims | A stale `processing` event claim is atomically recoverable; live claims are never reclaimed. |

## Authentication model

- **Principal** (`app/core/security.py`): `principal_id`, `principal_type` (`human` | `service` | `agent` | `system`),
  `display_name`, `roles`, `tenant_id` (always `default`; tenancy is not implemented), `auth_method`, `authenticated_at`.
  Immutable.
- **Credentials:** `PULSEOPS_API_CREDENTIALS` is a JSON list; each entry carries `principal_id`, `principal_type`, `roles`
  and `token_sha256`. Create a token and its hash with `python -m app.core.credentials --generate`. Only hashes are
  configured; plaintext tokens are never stored, logged, returned or audited. Comparison is constant time against **every**
  entry (no early exit). Only a human principal may hold the `reviewer` role (checked at startup).
- **Enforcement:** every router except the public routes has a router-level `get_principal` dependency, and each endpoint adds
  `require_permission(...)`. A test enumerates the full OpenAPI surface and asserts that every route other than `/` and
  `/health` returns 401 without credentials. Responses: 401 (`WWW-Authenticate: Bearer`) unauthenticated, 403 authenticated
  but unauthorized. A 401 never says whether a token was unknown or malformed.
- **Development identity:** `PULSEOPS_AUTH_MODE=dev` (the default **only** when `PULSEOPS_ENVIRONMENT=development`).
  With no header the principal is `dev-admin` (human, role `admin`). `X-Dev-Principal: <type>:<id>:<role>+<role>`
  (for example `human:alice:reviewer+sre`) acts as another principal. The mechanism works only in the development
  environment: startup refuses `dev` elsewhere, and per request the header is ignored (401 without a real bearer token)
  and can never upgrade a real credential. A bad bearer token in development is a 401, never a silent fallback to the dev
  identity.
- **Docs:** interactive API docs and `openapi.json` are enabled only in development.
- **IdentityContext:** the Phase 5/6 `IdentityContext` (tenant, user, roles, permissions) is derived from the authenticated
  principal for `/agent/investigate` and for the event-ingestion investigation; request fields cannot set it. MCP remains a
  process-local stdio subprocess and does not authenticate (any network MCP transport would have to).

## RBAC

| Role | Permissions |
|---|---|
| `service_n8n` | `events:ingest`, `workflow:read`, `incident:read` (cannot approve) |
| `reviewer` | `workflow:read`, `incident:read`, `workflow:approve` |
| `operator` | `incident:read/write`, `workflow:read`, `workflow:evaluate`, `events:ingest`, `agent:investigate` |
| `admin` | all |

Roles are static; there are no dynamic roles, no tenancy isolation and no enterprise IAM. A principal may additionally carry
**domain roles** (for example `sre`, `incident_manager`, `release_manager`) that have no application permissions of their own
and are matched only against a policy rule's `permitted_roles`.

## HITL identity

`POST /workflow/{id}/decision` (and the legacy `/incidents/{id}/workflow/decision`, which now shares the same code):

1. the principal must be a **human** with `workflow:approve` (agents, services and system principals get 403);
2. a supplied `reviewer` is never trusted: if present it must equal the principal id, otherwise 403;
3. for a live HITL decision (`requires_approval` and `pending`) the principal needs a role listed in the action's policy
   `permitted_roles` (or `admin`), and the requester cannot approve their own workflow (403);
4. then the unchanged workflow rules apply: DENY cannot be overridden, final states and conflicting decisions return 409,
   repeated identical approvals are idempotent.

`requested_by` on workflow evaluation is also never trusted: it is the principal's id. The decision is audited with
`actor` = principal id, `actor_type`, `principal_roles` and `request_id`. The old name heuristic remains only as a guard for
direct service calls that pass no principal.

## Secrets and configuration

All settings come from the environment (`.env.example` lists names and placeholders only; use
`uvicorn --env-file .env` or `docker compose --env-file .env`). Defaults by environment:

| Setting | development | any other environment |
|---|---|---|
| `PULSEOPS_AUTH_MODE` | `dev` | `apikey` (`dev` is refused) |
| `PULSEOPS_SEED_DEMO_DATA` | true | false |
| API docs | on | off |
| `PULSEOPS_API_CREDENTIALS` | optional | **required**, validated at startup |

Startup validation (`validate_runtime_security`, called when `app.main` is imported) refuses to run on: an unknown auth mode,
`dev` outside development, missing/invalid JSON credentials, a missing `token_sha256`, a non-human `reviewer`, duplicate
principals. Messages never contain token or hash values. The Neo4j password has no default in code or compose
(`NEO4J_PASSWORD`, and only in the optional `docker-compose.neo4j.yml`). Secrets are not baked into the image and never appear
in logs, `/health`, errors, audit events or API responses (tested). A production secret manager is deferred.

## Request IDs and structured logging

`X-Request-ID` is accepted only if it matches `^[A-Za-z0-9][A-Za-z0-9._-]{7,63}$`; anything else is replaced by a generated
id. The id is echoed on every response (including 401/404/500), carried in contextvars (including worker threads), written to
every JSON log line and to the metadata of every workflow audit event. Log lines carry timestamp, level, logger, message,
request_id, principal_id, and where available event_id, incident_id, workflow_id, operation, outcome, error class, status and
duration. A redaction filter removes bearer tokens, `sk-ant-` keys and common secret key/value pairs. Unhandled exceptions
return `{"detail": "Internal server error", "request_id": ...}` with no internals. No observability platform was added.

## AI token / cost recording

`InvestigationTelemetry` gains `total_cost_usd`, `usage` (numeric entries only) and `api_duration_ms`, copied from the SDK
`ResultMessage` when present; absent or odd values are ignored and never break an investigation. The event path also stores
`ai_execution` (model, duration, api duration, cost, usage) in the `INVESTIGATION_COMPLETED` / `DEGRADED` audit metadata.
There are no budgets, no enforcement and no external monitoring.

## n8n security

- The webhook uses a **Header Auth** credential (`X-PulseOps-Webhook-Key`), so event sources authenticate to n8n.
- n8n calls PulseOps with a dedicated `service_n8n` principal via a Header Auth credential (`Authorization: Bearer ...`). That
  role can ingest and read but cannot approve; 401/403 from PulseOps are reported as `pulseops_unauthorized` /
  `pulseops_forbidden` (502, fail closed).
- The workflow JSON contains credential **references** only (`id`, `name`). `n8n/credentials.template.json` holds placeholders;
  `n8n/bootstrap.sh` (the container entrypoint) substitutes them from environment variables into n8n's encrypted credential
  store (keyed by `N8N_ENCRYPTION_KEY`), imports and publishes the workflow, then starts n8n. `N8N_BLOCK_ENV_ACCESS_IN_NODE`
  is on.
- Unchanged: 120 s timeout, retries disabled, idempotency and policy authority in PulseOps, no AI-agent nodes and no direct
  Claude/MCP/Neo4j/SQLite access.
- Image pinned to `docker.n8n.io/n8nio/n8n:2.41.6` (no `latest`).

## Docker and Compose

- **Image** (`Dockerfile`): `python:3.11.16-slim` pinned by tag and digest; non-root user `pulseops` (uid 10001);
  `PYTHONUNBUFFERED=1`; `HEALTHCHECK` on `/health`; `VOLUME /data` with `PULSEOPS_DATABASE_URL=sqlite:////data/pulseops.db`;
  `PULSEOPS_ENVIRONMENT` defaults to `production`, so the container refuses to start without credentials; no secrets in the
  image; `.dockerignore` excludes `.env`, `.venv`, `*.db`, `.git`, tests, docs.
- **Canonical Compose file: `docker-compose.yml`** - services `pulseops` and `n8n` on the `pulseops-net` network; n8n calls
  `http://pulseops:8000`; n8n waits for the PulseOps healthcheck; both published on `127.0.0.1` only; required variables use
  `${VAR:?...}` so a missing secret stops `docker compose up`.
- `docker-compose.neo4j.yml`: the former Neo4j service, now optional, with no default password.
- `docker-compose.n8n.yml`: **legacy**, kept temporarily (only its image pin changed). It cannot run the updated workflow by
  itself; remove it once the new stack is accepted.
- `PULSEOPS_PORT` changes the host port (the dev machine has another container on 8000).

## Seed data boundary

Synthetic demo data (`svc-payment`, `INC-1007`, ...) is seeded only when `PULSEOPS_ENVIRONMENT=development`, or when
`PULSEOPS_SEED_DEMO_DATA=true` is set explicitly; non-development startup never silently recreates it. The hard-coded
`INC-1007` default in `get_related_incidents` was removed (an incident is hoisted only when it is the one being asked
about). `INC-1007` remains a development/test fixture. Consequence: a seed-free deployment needs another way to create
services (there is no service-creation API yet; see Deferred).

## Stuck event-claim recovery

`operational_events` claims are timestamped. A claim that is still `processing` with no workflow for longer than
`PULSEOPS_EVENT_CLAIM_TTL_SECONDS` (default 900) is reclaimed by the next delivery with a single atomic `UPDATE ... WHERE`
(exactly one concurrent reclaimer wins; a younger claim, a completed event and a conflicting payload are never reclaimed;
the TTL is far above the 120 s wait). Recovery reuses the incident the dead delivery created (no duplicate incident). If a
workflow was created but its investigation was still held (the process died mid-investigation), it is closed fail-closed as
`investigation_failed` / `investigation_abandoned` (never silently re-run). Recovery is audited as `EVENT_CLAIM_RECOVERED`
(stale age, TTL, recovering principal). No background workers.

## Tests

`tests/test_phase7_gate9.py` (48 tests) covers: public vs protected endpoints (whole OpenAPI surface), valid/invalid/malformed
credentials, constant-time comparison, hashed storage, dev header in/out of development, RBAC matrix, n8n ingest-but-not-approve,
agent/service cannot approve, permitted_roles, spoofed/mismatched reviewer, self-approval, idempotent/conflicting approvals,
DENY not overridable, agent identity from the principal, startup fail-closed (real subprocess), generic 500, no secrets in
health/errors/logs, request ids (generated, supplied, sanitised, correlated with audit and logs), token/cost recording, workflow
JSON/Dockerfile/Compose/`.env.example` checks, seed boundary, and stuck-claim recovery. Existing Gate 5-8 tests were adapted
only where approval semantics legitimately changed (reviewer now comes from the authenticated principal; an agent approval is
403, not 409).

## Known limitations

- API keys are shared secrets: manual rotation, no per-person revocation, no expiry, no MFA. OIDC/SSO is deferred.
- A dev-mode process trusts the `X-Dev-Principal` header; it is refused outside development, but a developer who runs a
  reachable server in development mode is exposing a development identity.
- Single-tenant (`default`); no tenant isolation. SQLite remains single-writer and the investigation still runs inside the
  HTTP request.
- A seed-free (non-development) deployment has no API to create services.
- Compose verification of the full LOW/HITL/DENY flow uses a scripted agent outside the image; inside the image without an
  `ANTHROPIC_API_KEY` every investigation fails closed (502 `investigation_failed`), which is the intended behaviour.
- Neo4j Desktop is available as a local development environment, but **PulseOps does not yet consume Neo4j at runtime**; the
  graph is derived from SQLite. The ontology TTL exists, but runtime ontology loading into Neo4j is deferred.

## Deferred to Gate 10+

PostgreSQL / Alembic / transactions / app factory; OIDC / SSO / OAuth; multi-tenancy; Neo4j runtime integration and ontology
loading; AWS / ECS / EKS / Kubernetes / Terraform / cloud secret manager; HITL expiry, escalation and notification;
rate limiting, event dedupe and cost budgets; audit redaction and tamper evidence; per-tool timing, metrics and tracing
backends; a service-creation API; workflow-state redesign (`AUDITED`, terminal states for notify workflows); real
dependency data; frontend; Slack; GitHub integration; `project-plan.md.md` removal.

> **Gate 9.1 note.** Credentials no longer carry `roles` or `principal_type`: each is bound to a `user_id` and `tenant_id`, and roles
> come from the tenant membership (see `phase-7-gate-9.1-implementation.md`). Everything else in this document still applies.

## Verification (Gate 9)

| Check | Result |
|---|---|
| Gate 9 tests (`tests/test_phase7_gate9.py`) | 48 passed |
| Full suite, Windows (`.venv\Scripts\python.exe -m pytest -q`) | 235 passed (187 existing + 48 new) |
| Full suite, Linux (python:3.11.16-slim, uid 1000, fresh venv) + replay | 235 passed; replay gate PASS |
| Docker image | builds; runs as uid 10001; `/app` read-only to the app, `/data` writable; refuses to start without credentials and with `PULSEOPS_AUTH_MODE=dev` in production; no secrets in image env or history |
| Compose (`pulseops` + `n8n 2.41.6`, Docker network) | `pulseops-app` healthy; public `/health`; `/incidents` 401; n8n bootstrap imported 2 credentials + the workflow and published it; webhook 403 without/with a wrong key; with the key n8n called `http://pulseops:8000` as `svc-n8n` (no Anthropic key, so the investigation failed closed, 502 `investigation_failed`); replay idempotent; malformed 400; n8n token cannot approve (403); alice's approval of the failed workflow 409; SQLite survived a container restart; no secret in either container's logs |
| n8n scenario matrix (real n8n 2.41.6 + real `bootstrap.sh`; PulseOps with a scripted SDK client and real bearer auth) | LOW 200, duplicate replay, HITL 202, DENY 403, DEGRADED 502, FAILED 502, malformed 400; approval: n8n 403, anonymous 401, reviewer without domain role 403, spoofed reviewer 403, authorized human 200, idempotent repeat 200, reject-after-approve 409, DENY 409; audit shows actor/actor_type/request_id/roles |

Notes from verification:

- The stack's PulseOps container was run with `PULSEOPS_ENVIRONMENT=development`, so `/docs` is open in that stack (docs are
  development-only; use `production` for a docs-free, seed-free deployment).
- n8n answers its readiness probe slightly before it has registered the published webhook; wait for the first successful
  probe on `/webhook/pulseops-event` (a 404 "not registered" means it is still activating).
- Importing the `evals` package deliberately resets the process to the development environment and clears API
  credentials (it only ever drives the app in-process). Never import `evals` in a long-running server process.
- The container verification with the real image used no Anthropic key, so it exercised authentication, networking,
  persistence and fail-closed behaviour but not a live investigation. The LOW/HITL/DENY flow was verified with the
  scripted-agent server described above. A live Claude run has still not been performed (no API key configured).
- GitHub-hosted CI has not run; `ci.yml` is unchanged from Gate 8 and both of its commands were run locally on Linux.

