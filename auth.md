Do NOT modify any files, database records, .env, or Docker configuration.

We just completed Gate 9.1 Docker verification.

The PulseOps container is healthy and the API credential is recognized, but an authenticated request using PULSEOPS_N8N_TOKEN returns:

HTTP 403
{"detail":"No active tenant membership for this credential"}

The credential is configured as:
principal_id = svc-n8n
tenant_id = acme

The Docker containers are:
pulseops-app = healthy
pulseops-n8n = running

Diagnose why the running PulseOps container cannot find the active membership.

Inspect the existing implementation and database/provisioning behavior. In particular verify:

1. How get_principal resolves principal_id and tenant_id.
2. How active tenant membership is looked up.
3. Which database file the running Docker container is actually using.
4. Whether the tenancy_admin commands I ran inside the container modify that same database.
5. Whether the expected records should exist:
   - tenant acme
   - user svc-n8n
   - tenant_users membership acme/svc-n8n/service_n8n
6. Whether there is any distinction between the configured credential tenant_id and the membership tenant_id.
7. Whether the membership may be inactive.
8. Give me read-only commands to verify the three records inside the running container.

Do NOT create, delete, update, migrate, reseed, or modify anything.
Do NOT print any secrets or tokens.