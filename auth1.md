Do NOT modify any files.

We have now successfully verified:
- PulseOps Docker container is healthy
- n8n container is running
- /health returns 200
- unauthenticated /incidents returns 401
- PULSEOPS_N8N_TOKEN authenticates successfully
- svc-n8n has active membership in tenant acme
- authenticated access now succeeds

Now inspect the existing Gate 9 / Gate 9.1 tests and implementation to determine the exact existing test sequence for proving:

1. service_n8n can authenticate and access permitted tenant-scoped operations.
2. service_n8n CANNOT approve a HITL/consequential workflow.
3. A human reviewer with the appropriate reviewer role CAN approve when the workflow requires HITL, if that is already supported by the implementation.
4. Cross-tenant approval remains rejected.

Do NOT change code, tests, database, .env, or Docker configuration.

Find the existing tests that cover:
- service_n8n RBAC
- HITL approval
- reviewer identity
- self-approval
- tenant isolation

Give me the exact commands/request payloads needed to run the existing verification manually against the running Docker stack.

Do not print any token, API key, password, or secret.

Prefer existing test fixtures/payloads over inventing new ones.