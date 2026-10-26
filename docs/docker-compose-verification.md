Do NOT modify any files.

We are verifying the Gate 9.1 tenant-aware Docker Compose deployment.

The command:

docker compose config

currently fails because PULSEOPS_API_CREDENTIALS is not set.

Inspect the existing PulseOps repository and determine the exact supported way to create/configure the API credential required by docker-compose.yml.

Specifically inspect:
- app/core/credentials.py
- app/core/security.py
- app/tenancy_admin.py
- docs/security.md
- docs/phase-7-gate-9-implementation.md
- docs/phase-7-gate-9.1-implementation.md
- .env.example
- docker-compose.yml
- any existing credential-generation scripts/CLI commands

Answer only; do not edit anything.

Tell me:

1. What command generates a real API credential/token?
2. What command provisions the corresponding tenant/user/service principal?
3. How is the raw token supplied to n8n?
4. How is PULSEOPS_API_CREDENTIALS generated?
5. Whether the raw token should ever be stored in .env.
6. Whether docker-compose expects the SHA-256 hash or the raw token.
7. The exact safe sequence of commands I should run for this local verification.
8. Whether any existing credential can be reused, without exposing its secret.

Do not print any existing secret, token, API key, or credential value.

Do not modify .env, docker-compose.yml, or application code.

We want to use the existing Gate 9.1 design, not introduce a new authentication mechanism.