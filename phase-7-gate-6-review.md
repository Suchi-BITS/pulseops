We are proceeding with Gate 6 only.

Current verified state:
- Phase 6 Incident Agent is complete.
- Phase 7 Gates 1–5 are complete.
- Full project test suite: 95 passed, 0 failed.
- We are currently stopped at Gate 6.
- Do not start Gate 7 or implement anything beyond Gate 6.
- n8n Community Edition is running locally at http://localhost:5678.
- n8n Docker → Windows host → PulseOps FastAPI connectivity has already been verified:
  GET http://host.docker.internal:8000/health
  returned HTTP 200 with:
  {"status":"ok","app":"PulseOps","environment":"development","debug":false}

GATE 6 OBJECTIVE

Integrate the existing Phase 7 workflow with local self-hosted n8n.

Architecture:

Operational Event
→ n8n Webhook
→ Basic Input Validation
→ PulseOps Workflow API
→ Existing Incident Investigation
→ Existing Policy Evaluation
→ LOW/MEDIUM/HIGH branching
→ Simulated notification / HITL path

IMPORTANT ARCHITECTURE RULES

1. n8n is orchestration only.
2. PulseOps remains the owner of:
   - business logic
   - workflow state
   - deterministic policy
   - risk classification
   - HITL enforcement
   - idempotency
   - audit
   - incident investigation
3. Do not duplicate PulseOps business logic inside n8n.
4. Do not introduce n8n AI Agent nodes.
5. Do not connect n8n directly to:
   - Claude
   - MCP
   - Neo4j
   - SQLite
6. Do not modify or rewrite the existing P5/P6 Agent SDK implementation.
7. Do not introduce Slack, GitHub, AWS, Kubernetes, real production remediation, vector databases, embeddings, multi-agent systems, or Gate 7 functionality.
8. No secrets should be placed into the n8n workflow.

BEFORE IMPLEMENTING ANYTHING

Read and inspect:

- CLAUDE.md
- project-plan.md
- docs/phase-7.md
- relevant Gate 1–5 documentation
- existing workflow API implementation
- existing policy implementation
- existing workflow persistence/idempotency/audit implementation
- existing Phase 6 investigation integration
- existing tests
- Docker configuration
- any existing n8n-related files/documentation

Determine the actual existing API endpoint that n8n should call.

Do NOT invent a new API endpoint if an existing endpoint already supports the required workflow.

Then report:

1. Current Gate 6-relevant architecture.
2. Existing API endpoint(s) that n8n should call.
3. Existing request/response contracts.
4. Existing workflow states and policy decisions.
5. Existing idempotency and audit behavior.
6. Exact files that need modification or creation.
7. Proposed n8n workflow structure.
8. Tests that need to be added or changed.
9. Any risks or ambiguities you found.

STOP AFTER THIS ANALYSIS.

Do NOT modify files yet.

Wait for my approval before implementation.