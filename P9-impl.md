P9 — MODERN APPLICATION
FULL IMPLEMENTATION APPROVED

The read-only P9 inspection is complete and approved.

P9 objective:

Build the user-facing PulseOps application for incident investigation and human review on top of the existing authenticated, tenant-isolated backend.

IMPORTANT:
Implement the ENTIRE approved P9 scope in one pass.
Do not stop after individual gates for approval.
Do not split P9 into separate implementation requests.

After implementation, perform the complete P9 validation described below and report everything.

==================================================
APPROVED ARCHITECTURE DECISIONS
==================================================

1. UI TECHNOLOGY

Use:

- React
- Vite
- TypeScript

This is required because the curriculum explicitly expects React for the Modern Application phase.

Do not replace React with a plain static HTML/JS application.

The frontend should remain intentionally small and focused.

2. BROWSER AUTHENTICATION

P9 does NOT introduce OIDC/SSO.

Use the existing bearer-token authentication model.

For the browser:

- provide a simple token entry/session mechanism;
- keep the bearer token in memory only;
- do NOT store the token in:
  - localStorage
  - sessionStorage
  - cookies
  - IndexedDB
  - source code
  - repository files

The token is supplied by the user for the current browser session.

P10 may later introduce proper identity/SSO.

Do not weaken backend authentication.

3. INVESTIGATION PERSISTENCE

Create a first-class tenant-scoped investigation record.

Do NOT rely exclusively on audit-event metadata.

The investigation record must preserve the structured InvestigationResult:

- incident_id
- service_id
- summary
- evidence
- hypotheses
- missing_information
- recommendations
- confidence
- tool_calls
- relevant workflow relationship
- tenant_id
- timestamps as appropriate

AI-generated content remains untrusted data.

It must never become an instruction to the UI or backend.

==================================================
P9 SCOPE
==================================================

Implement all of the following.

--------------------------------------------------
P9.0 — API CONTRACT AND CONSISTENCY
--------------------------------------------------

1. Introduce a consistent API error envelope:

{
  "detail": "...",
  "code": "...",
  "request_id": "..."
}

Use typed error/exception handling.

Do NOT rely on substring matching of exception messages to determine HTTP status.

Preserve existing security behavior.

2. Use typed response models for the relevant application-facing API routes.

Avoid unnecessary dict[str, object] responses where a stable response model is appropriate.

3. Add:

GET /me

It must return the authenticated principal/user/tenant context appropriate for the UI.

Do not expose secrets or credentials.

Include only information the current authenticated principal is authorized to see.

4. Improve:

GET /incidents

Support appropriate:

- pagination
- filtering
- sorting

Keep it tenant-scoped.

Do not expose another tenant's incidents.

5. Preserve the existing duplicate workflow routes for compatibility.

Do NOT break n8n.

Where appropriate:

- establish one canonical route;
- retain the existing route as an alias/deprecated compatibility route.

Do not remove an existing route if n8n depends on it.

--------------------------------------------------
P9.1 — INVESTIGATION RECORD
--------------------------------------------------

Create a new tenant-scoped investigation table/model/repository/service.

Requirements:

- tenant_id is mandatory;
- investigation must belong to the correct incident/workflow tenant;
- cross-tenant access must fail closed;
- use the existing migration philosophy from Gate 9.1;
- do not perform destructive automatic startup migrations;
- provide a controlled migration path;
- preserve existing databases.

The investigation should be persisted when a workflow produces a valid grounded InvestigationResult.

Do NOT store fabricated/untrusted model output when the existing grounding/agent safeguards reject the result.

The persistence layer must preserve the distinction:

Evidence
Hypotheses
Missing Information
Recommendations

Do not merge these into one text field.

Add:

GET /incidents/{incident_id}/investigations

Tenant scoped and permission controlled.

Return the stored investigation records in typed response models.

Where appropriate, expose the investigation reference from workflow responses.

--------------------------------------------------
P9.2 — REVIEWER READ APIs
--------------------------------------------------

Add a reviewer-oriented workflow read API.

For example:

GET /workflow

Support useful filtering such as:

- status
- incident_id
- pagination
- sorting

The exact query contract should follow existing project conventions.

It must be:

- authenticated
- tenant scoped
- permission gated
- read-only

Add an incident-detail API/read model that allows the UI to obtain:

- incident
- latest workflow
- investigation
- audit timeline
- relevant status
- HITL state

Do not create new write paths unnecessarily.

Do not bypass existing WorkflowService, authorization, tenancy, policy or HITL rules.

A reviewer must never be able to approve merely because the UI displays an approval button.

The existing backend HITL enforcement remains authoritative.

--------------------------------------------------
P9.3 — REACT USER INTERFACE
--------------------------------------------------

Create a minimal React + Vite + TypeScript frontend.

Keep the UI intentionally small.

ONLY THREE PRIMARY VIEWS:

1. Incident List
2. Incident Detail
3. Pending Approval Queue

Do not build a dashboard.

Do not build analytics.

Do not build tenant administration.

Do not build a graph visualization.

Do not build a settings system.

Do not add unnecessary UI features.

--------------------------------
VIEW 1 — INCIDENT LIST
--------------------------------

Display tenant-scoped incidents.

Support:

- pagination
- basic filtering
- status
- severity where available
- service
- timestamp
- incident ID

Clicking an incident opens its detail view.

--------------------------------
VIEW 2 — INCIDENT DETAIL
--------------------------------

Display:

Incident information

Investigation status

AI-generated summary

Evidence

Hypotheses

Missing information

Recommendations

Confidence

Workflow status

HITL status where applicable

Audit timeline

Clearly label investigation content:

"AI-generated"

Make the semantic distinction visually obvious:

Evidence ≠ Hypothesis ≠ Recommendation.

Recommendations must NEVER be presented as actions that were already performed.

For example:

BAD:
"Service restarted."

GOOD:
"Recommendation: consider restarting the service."

If no grounded investigation exists, clearly show:

- degraded
- failed
- unavailable

as appropriate.

Never fabricate missing information in the UI.

--------------------------------
VIEW 3 — PENDING APPROVAL QUEUE
--------------------------------

Show workflows requiring human approval.

Display:

- incident
- requested action
- risk level
- workflow status
- relevant investigation summary
- approval state

Provide:

Approve
Reject

ONLY when the authenticated principal has permission.

The UI must not implement its own authorization logic as the source of truth.

Backend authorization remains authoritative.

If backend returns 403/409/etc., display the error clearly.

Do not allow self-approval or service-principal approval.

--------------------------------
UI SECURITY
--------------------------------

Treat all incident, log, investigation and AI-generated content as untrusted.

React rendering must safely escape content.

Do not use dangerous HTML rendering unless absolutely required.

Do not interpret AI text as HTML, JavaScript, instructions or executable content.

Add an appropriate Content-Security-Policy for the local application.

Do not put secrets in frontend source code.

Do not put API credentials into environment variables that are bundled into browser JavaScript.

Do not commit any real API token.

--------------------------------------------------
P9.4 — APPLICATION OBSERVABILITY
--------------------------------------------------

Add:

GET /health/ready

It must perform an actual database readiness check.

Keep:

GET /health

for basic liveness.

Do not expose secrets or database credentials.

Improve application access logging where practical:

- request_id
- method
- route
- status
- latency
- tenant where authorized
- principal where authorized

Do not log bearer tokens.

Do not log API keys.

Do not log sensitive credentials.

Do not turn observability into a large monitoring platform.

--------------------------------------------------
API CONTRACTS
--------------------------------------------------

Introduce/extend typed Pydantic schemas for the new application-facing contracts.

Keep the OpenAPI schema coherent.

Add contract tests for:

- error envelope
- /me
- incident pagination/filtering
- workflow read API
- investigation read API
- incident detail
- health readiness

Where practical, add an OpenAPI contract/snapshot assertion.

Do not make the snapshot brittle by asserting irrelevant ordering or generated metadata.

--------------------------------------------------
AUTHORIZATION / TENANCY
--------------------------------------------------

Every new backend endpoint must be tested for:

1. unauthenticated → 401
2. authenticated but wrong role → 403 where appropriate
3. cross-tenant resource → 404 or existing project-standard behavior

The investigation record must contain tenant_id.

The UI must never provide a tenant-selection mechanism that can override the authenticated tenant.

The backend principal remains the source of tenant identity.

Do not introduce X-Tenant-ID.

Do not allow tenant_id from:

- query parameters
- request body
- arbitrary browser headers

to override authenticated identity.

--------------------------------------------------
MIGRATION
--------------------------------------------------

Follow the established Gate 9.1 migration discipline.

Do NOT:

- automatically rebuild databases on startup
- destructively recreate tables
- modify unrelated D:\pulseops*.db files
- silently discard existing data

Provide an explicit migration mechanism for the investigation table/schema if needed.

Fresh development databases may be initialized through the normal schema path.

Existing legacy databases must remain safe.

--------------------------------------------------
N8N COMPATIBILITY
--------------------------------------------------

Do not break the existing n8n workflow.

Preserve:

POST /workflow/events

and all required existing payload/response compatibility.

Run the existing n8n-related tests.

Do not change n8n architecture.

--------------------------------------------------
DO NOT IMPLEMENT
--------------------------------------------------

Explicit P9 non-goals:

- AWS
- Kubernetes
- Terraform
- cloud deployment
- OIDC
- SSO
- external identity provider
- PostgreSQL
- Alembic
- Neo4j runtime
- vector database
- embeddings
- multi-agent architecture
- autonomous remediation
- Slack integration
- GitHub integration
- tenant administration API
- dashboard
- analytics platform
- LLM-as-judge
- RAGAS
- DeepEval
- policy-engine redesign
- HITL architecture redesign
- evaluation baseline changes
- golden dataset changes
- cloud observability platform

Do not expand P9 into P10 or P11.

--------------------------------------------------
DOCUMENTATION
--------------------------------------------------

Create:

docs/phase-9.md

Document:

- P9 objective
- application architecture
- React → FastAPI → service → repository flow
- authentication model
- tenant isolation
- investigation persistence
- reviewer workflow
- HITL boundary
- security considerations
- observability
- API contracts
- known limitations
- P10/P11 deferred items

Update only where necessary:

- docs/architecture.md
- docs/security.md
- docs/curriculum-alignment.md

Add appropriate ADRs if the repository already has an ADR convention.

At minimum document these decisions:

1. React + Vite for the P9 frontend.
2. In-memory browser bearer token for P9, with OIDC/SSO deferred.
3. First-class investigation persistence.
4. Backend remains authoritative for authorization/HITL.

--------------------------------------------------
TESTING
--------------------------------------------------

Create appropriate P9 tests.

At minimum cover:

API:

- /me
- error envelope
- incident pagination/filtering
- workflow read API
- investigation API
- incident detail
- health readiness

Persistence:

- investigation creation
- investigation retrieval
- tenant isolation
- incident/workflow relationship
- migration behavior

Security:

- 401
- 403
- cross-tenant denial
- service principal cannot approve
- self approval remains blocked
- browser/UI cannot bypass backend authorization

Regression:

- existing 304+ tests remain passing
- n8n compatibility remains passing
- Gate 7/8 evaluation tests remain passing
- tenant isolation evaluation remains 1.00
- replay evaluation remains PASS

UI:

- frontend builds successfully
- assets are served
- basic route/navigation smoke test
- CSP/security headers
- API error rendering
- degraded/failed investigation rendering

Do NOT build a large browser E2E framework.

Full UI E2E belongs to P11.

--------------------------------------------------
VALIDATION
--------------------------------------------------

After implementation, run:

1. Windows full test suite
2. Linux Python 3.11 non-root full test suite
3. Evaluation replay
4. Golden-v2 replay
5. Golden-v3 replay
6. Existing tenant isolation evaluation
7. Frontend production build
8. Relevant API/UI smoke tests
9. Docker Compose validation if the UI is integrated into Docker
10. Review the complete diff

Expected baseline:

304 existing tests must remain passing unless legitimate new P9 tests increase the count.

Do not weaken existing assertions to make tests pass.

Do not skip failing tests.

Do not bypass security checks.

Do not modify evaluation baselines to hide regressions.

If a test fails because P9 legitimately changes an API contract, update the contract and its tests deliberately and document the compatibility impact.

--------------------------------------------------
ACCEPTANCE CRITERIA
--------------------------------------------------

P9 is complete only if:

1. React frontend exists and builds.
2. Incident list works.
3. Incident detail works.
4. Pending approval queue works.
5. Backend remains the authorization source of truth.
6. InvestigationResult is persisted as a first-class tenant-scoped record.
7. Reviewer APIs exist and are tenant scoped.
8. /me exists.
9. Error responses have a consistent typed envelope.
10. Incident pagination/filtering exists.
11. /health/ready performs a DB readiness check.
12. n8n remains compatible.
13. Existing authentication/RBAC/HITL behavior remains intact.
14. Cross-tenant isolation remains intact.
15. Existing evaluation remains PASS.
16. No cloud/P10 work has been introduced.
17. No P11-scale testing framework has been introduced.
18. Documentation is updated.
19. Windows validation passes.
20. Linux Python 3.11 validation passes.
21. Frontend build passes.

--------------------------------------------------
FINAL REPORT
--------------------------------------------------

At the end, report:

1. P9 implementation status
2. Complete list of changed files
3. Complete list of new files
4. API changes
5. Database/schema changes
6. Migration instructions
7. React application structure
8. Authentication approach
9. Tenant-isolation approach
10. Investigation persistence design
11. HITL behavior
12. Security controls
13. Observability changes
14. Documentation changes
15. Test count
16. Windows test result
17. Linux test result
18. v2 replay result
19. v3 replay result
20. tenant-isolation evaluation result
21. frontend build result
22. Docker result
23. Any failures
24. Any deferred items
25. Git/diff summary

Do not start P10.

Do not start P11.

Do not perform a real Claude live evaluation.

Implement P9 completely, validate it completely, and stop.