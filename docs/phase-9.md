# Phase 9 — Modern Application

## 1. Objective

Build the user-facing PulseOps application for incident investigation and human review on top of the authenticated,
tenant-isolated backend delivered by Gates 9 and 9.1. P9 does not rebuild authentication, RBAC, tenancy, the workflow,
HITL or the policy engine. It makes their results readable by a human and adds the small API surface a UI needs.

Core principle unchanged: **AI Pair, Not AI Authority.** The UI shows AI analysis and lets a human decide; the backend
remains the only authority on who may decide and what happens.

## 2. Architecture

```text
Browser (React + Vite + TypeScript, served at /ui/)
   |  fetch, Authorization: Bearer <token held in memory>
   v
FastAPI routers   (app/api: incidents, workflow, retrieval, agent, routes)
   |  authentication + RBAC (Principal)  -> tenant comes ONLY from the principal
   v
Application services   (IncidentService, WorkflowService, OperationalEventService)
   |  deterministic policy engine, HITL rules, idempotency
   v
Tenant-scoped repositories   (every query filtered by tenant_id)
   v
SQLite   (transactional store; investigations are a first-class table)
```

The React app is a static build served by the API itself from the same origin (`app/ui.py`, mounted at `/ui`). Same origin
means no CORS and no token sent cross-origin. The API runs without the UI if no build exists. Neo4j is not used (the UI reads
SQLite-backed data); n8n is unchanged.

Request flow example, approving a workflow: `ApprovalQueue` → `POST /workflow/{id}/decision` →
`decide_for_principal` (human? permission? role permitted for the action? not the requester?) →
`WorkflowService.record_decision` (DENY, final state, idempotency, conflicts) → audit event.

## 3. Authentication model

Unchanged: bearer API credentials (SHA-256 hashes in configuration), each bound to one user and one tenant, roles from the
tenant membership. For the browser, P9 adds only a way to supply that token:

* the user pastes a token into a password field; it is held in a module variable in the page (`frontend/src/api.ts`) and sent
  as `Authorization: Bearer`; `credentials: "omit"` so no cookies are involved;
* it is never written to localStorage, sessionStorage, cookies, IndexedDB, the URL or any file, is not in the bundle, and a
  reload signs the user out;
* a 401 from the API signs the UI out; `Sign out` forgets the token;
* OIDC/SSO and an identity provider are deferred to P10.

Create a token and its hash for local use with `python -m app.core.credentials --generate`; provision the tenant/user/membership
with `python -m app.tenancy_admin` (see `docs/phase-7-gate-9.1-implementation.md`).

## 4. Tenant isolation

Nothing new is trusted from the browser. There is no tenant selector in the UI, no `X-Tenant-ID`, and no endpoint accepts a
tenant from a query parameter, header or body (the OpenAPI contract test asserts it). A `tenant_id` query parameter is
ignored; the tenant is always the authenticated principal's. Another tenant's incident, workflow or investigation is
indistinguishable from a missing one (404).

## 5. Investigation persistence (P9.1)

Table `investigations` (`app/database.py`): `tenant_id` (required), `investigation_id`, `incident_id`, `workflow_id`,
`service_id`, `summary`, and **separate** columns `evidence`, `hypotheses`, `missing_information`, `recommendations`,
`tool_calls` (JSON lists), `confidence`, `source`, `created_at`.

* `UNIQUE (tenant_id, workflow_id)`: one investigation per workflow. `FOREIGN KEY (tenant_id, workflow_id)` to
  `workflow_instances`: a record cannot reference another tenant's workflow (enforced by the database and tested).
* Written only by `WorkflowService.evaluate_incident_action`, only when the investigation outcome is `completed` (grounded).
  Degraded and failed outcomes are closed fail-closed exactly as before and are **never** stored as records.
* The audit trail still carries the result (unchanged) and now also the `investigation_id`.
* `WorkflowResponse.investigation_id` references the record on every workflow read.
* AI-generated content is data: stored verbatim as text, shown as text, never interpreted.

### Migration

Startup only ever adds the empty table (`CREATE TABLE IF NOT EXISTS`); it never alters, copies, rebuilds or drops anything and
never invents rows. For an existing database that already holds pre-P9 workflows, the explicit tool:

```text
python -m app.migrations.p9 sqlite:///./pulseops.db
```

requires a Gate 9.1 (tenant-aware) database (otherwise it refuses and points at `gate9_1`), writes
`<name>.pre-p9.bak` first (refuses to overwrite one), runs in one transaction with a foreign-key check, is idempotent, and
backfills only structurally valid, grounded `INVESTIGATION_COMPLETED` audit results (marked `source = 'backfill'`, original
tenant and timestamp). Nothing else is touched; unrelated database files are never opened.

## 6. Reviewer workflow and the HITL boundary

New read-only endpoints (all authenticated, permission-gated and tenant-scoped; no new write path):

| Endpoint | Permission | Purpose |
|---|---|---|
| `GET /me` | authenticated | identity, tenant, roles, permissions for the UI |
| `GET /incidents?status&severity&service_id&sort&order&limit&offset` | `incident:read` | page of incidents; body is still a list, total in `X-Total-Count` |
| `GET /incidents/{id}/investigations` | `incident:read` | stored investigation records |
| `GET /incidents/{id}/detail` | `incident:read` + `workflow:read` | incident, latest workflow, investigation, status, HITL state, audit timeline |
| `GET /workflow?status&incident_id&requires_approval&sort&order&limit&offset` | `workflow:read` | reviewer queue (`?status=pending&requires_approval=true`) |
| `GET /health/ready` | none | database readiness |

`can_decide` / `decision_blocked_reason` in the queue and detail are a **server-computed hint** that evaluates the same rules
as the decision endpoint (human principal, `workflow:approve`, role permitted for the action, not the requester). The UI shows
Approve/Reject only when the hint is true and implements no authorization logic. A forged request is still refused by the
decision endpoint (service, agent and operator principals: 403; another tenant: 404; self-approval: 403; final state: 409).
The reviewer is always the authenticated principal; the UI never sends one. Approving records a decision; PulseOps executes
nothing.

Investigation status in the detail read model: `completed` (a grounded record is stored), `degraded`, `failed`, `pending`
(held or interrupted) or `unavailable` (no investigation). It is derived from the latest workflow. Earlier investigations of
the same incident are available from `/incidents/{id}/investigations`. The audit timeline omits free-form metadata, which can
carry untrusted event or AI content.

## 7. API contracts (P9.0)

* **Error envelope** on every error: `{"detail", "code", "request_id"}` (validation errors add `errors` with location and
  message only, never the submitted value). `X-Request-ID` equals `request_id`. Codes: `unauthorized`, `forbidden`,
  `not_found`, `conflict`, `bad_request`, `validation_error`, `internal_error`, `not_ready`.
* **Typed handling:** `app/core/errors.py` defines `NotFoundError` (404, also a `KeyError`) and `ConflictError` (409, also a
  `ValueError`). The HTTP status comes from the exception type; the old substring matching on messages is gone. An untyped
  `ValueError` is a 400. Messages are unchanged.
* **Typed responses:** workflow evaluate/decision aliases under `/incidents/...` and `/agent/investigate` now declare
  `WorkflowResponse` / `InvestigationResult` instead of `dict[str, object]`; new endpoints use the models in
  `app/models/schemas.py`. Errors are documented as `ErrorResponse` in OpenAPI.
* **Canonical vs compatibility routes:** canonical are `POST /workflow/evaluate`, `POST /workflow/{id}/decision`,
  `POST /workflow/events`, `POST /incidents/{id}/workflow/evaluate|decision`. `POST /workflow/webhook` and
  `POST /workflow/incidents/{id}/evaluate|decision` remain, marked `deprecated` in OpenAPI, behaving identically. n8n calls
  only `/workflow/events`, which is unchanged.

### Compatibility impact

* Error bodies gain `code` and `request_id` (`detail` is unchanged). Two existing assertions that compared the whole error
  body for equality (`test_phase7_gate9`, `test_phase7_gate9_1`) were updated to the new envelope; no assertion was weakened.
* `/health/ready` is a new unauthenticated route; the Gate 9 "every other route requires authentication" test lists it as the
  one additional public route.
* `GET /incidents` now returns at most `limit` incidents (default 50, maximum 200) instead of all of them.
* Docker/Compose health checks now use `/health/ready`.

## 8. Security considerations

* All incident, log, investigation and AI text is untrusted. React renders it as text nodes; there is no
  `dangerouslySetInnerHTML`/`innerHTML` (a source-hygiene test enforces it, and a test renders hostile markup as inert text).
  An instruction embedded in AI text is only text.
* **CSP** on `/ui` responses: `default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self';
  connect-src 'self'; manifest-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; object-src 'none'`
  (no inline script, no eval). All responses carry `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`. The development-only `/docs` page is not under `/ui` and keeps working.
* No credential in the source or bundle (tests scan both); no secrets in environment variables bundled into the browser.
* Recommendations are labelled as suggestions, never as performed actions; hypotheses are labelled unconfirmed; AI content
  carries an "AI-generated" label; missing information is never invented.
* Backend authentication, RBAC, policy, HITL and tenant rules are unchanged and authoritative.

## 9. Observability

* `GET /health` (liveness, no database) and `GET /health/ready` (opens the database, runs a query, confirms the required
  tables; 503 with the error envelope otherwise; reveals no path, driver message or secret; refuses a pre-Gate-9.1 file).
* The structured access log gains the matched `route` template next to `request_id`, `method`, `path`, `status_code`,
  `duration_ms`, `outcome`, and `tenant_id` / `principal_id` when authenticated. Bearer tokens and keys are never logged
  (redaction unchanged, tested). No metrics platform was added.

## 10. Running it

```text
cd frontend && npm ci && npm run build        # produces frontend/dist
uvicorn app.main:app                          # UI at http://127.0.0.1:8000/ui/
cd frontend && npm run dev                    # Vite dev server on :5173, API calls proxied to :8000
cd frontend && npm test                       # frontend unit tests (Vitest + Testing Library)
docker compose --env-file .env up -d --build  # the image builds the UI in a first stage
```

## 11. Known limitations

* The token is re-entered after every reload (no persistence by design).
* The investigation shown is the latest workflow's; there is no investigation history view.
* No service or tenant management UI or API; no incident editing or status transitions from the UI.
* The decision timestamp is the browser clock; the server records its own audit timestamps.
* The workflow list has no free-text search. The UI has no live updates (manual refresh on navigation or decision).
* UI tests are component/route level with a mocked `fetch`; there is no browser end-to-end suite (P11).
* Compose was validated by build and configuration, not exercised with a live Claude investigation.

## 12. Deferred

* **P10 Cloud + Platform:** OIDC/SSO and a real session model, PostgreSQL/Alembic, secret manager, rate limiting, metrics and
  tracing backends, AWS/containers/Kubernetes/Terraform, HITL expiry and notifications, Neo4j runtime, durable evaluation history.
* **P11 Quality Engineering:** browser end-to-end tests, accessibility and performance testing, security scanning, release
  gates, audit tamper evidence, a live evaluation programme.
* Never in scope here: autonomous remediation, multi-agent, vector stores, LLM-as-judge.

## 13. Decisions

1. **React + Vite + TypeScript for the frontend.** The curriculum's Modern Application phase expects React. The app stays
   deliberately small: three views, hash routing (no server fallback), no state library, no UI framework.
2. **In-memory bearer token, OIDC/SSO deferred.** Reuses the existing authentication unchanged and keeps the token out of every
   persistent store; the cost is re-entering it after a reload. P10 may introduce a real identity provider.
3. **First-class investigation persistence.** A tenant-scoped table with separate fields for evidence, hypotheses, missing
   information and recommendations, instead of reading AI results back out of audit metadata. Only grounded results are stored.
4. **The backend remains authoritative for authorization and HITL.** The UI displays a server-computed hint and never decides
   anything itself; every decision is re-checked by the existing endpoint.

## 14. Verification

| Check | Result |
|---|---|
| Full suite, Windows (`.venv`, Python 3.11) | 334 passed (304 existing + 30 new in `tests/test_phase9.py`) |
| Full suite, Linux (`python:3.11.16-slim`, uid 10001, fresh venv) | 334 passed |
| Replay, golden-v2 / baseline v2 (Windows and Linux) | GATE: PASS |
| Replay, golden-v3 / baseline v3 (Windows and Linux) | GATE: PASS |
| Tenant isolation evaluation | 1.00 (8 checks, in both replays) |
| Frontend (`frontend/`): unit tests | 29 passed |
| Frontend: typecheck and production build | passed (`dist/`: one JS, one CSS asset) |
| Live smoke (real uvicorn, bearer auth, temp database, built UI) | 17/17 checks passed |
| Docker: Compose configuration | valid; health check uses `/health/ready` |
| Docker: image build (UI stage + runtime stage) and container run | built; non-root uid 10001; `/health/ready` 200; `/ui/` served with the CSP; `/docs` 404; container `healthy` |

No evaluation baseline, golden dataset or scorer was changed. No live Claude call was made. Commands: `python -m pytest -q`,
`python -m evals replay`, `python -m evals replay --dataset v3 --out eval-reports/v3`, `cd frontend && npm test && npm run build`.
