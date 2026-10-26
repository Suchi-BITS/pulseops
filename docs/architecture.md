# PulseOps — System Architecture

## 1. Architecture Goal

PulseOps is a semantic, graph-enhanced AI incident investigation platform. The architecture separates transactional operational data, semantic knowledge, retrieval/context engineering, agent reasoning, and consequential actions.

## 2. High-Level Architecture

```text
                              +----------------------+
                              |       Users          |
                              +----------+-----------+
                                         |
                                         v
                              +----------------------+
                              |       FastAPI        |
                              +----------+-----------+
                                         |
                    +--------------------+--------------------+
                    |                                         |
                    v                                         v
          +-------------------+                    +-------------------+
          | Operational Layer |                    | Intelligence Layer|
          +---------+---------+                    +---------+---------+
                    |                                      |
                    v                                      v
                +-------+                         +-------------------+
                |SQLite |                         | Context Engineering|
                +---+---+                         +---------+---------+
                    |                                       |
                    |                           +-----------+-----------+
                    |                           |                       |
                    |                           v                       v
                    |                     +-----------+          +-------------+
                    |                     | Ontology  |          | Neo4j Graph |
                    |                     +-----+-----+          +------+------+ 
                    |                           |                       |
                    |                           +-----------+-----------+
                    |                                       |
                    +-------------------+-------------------+
                                        |
                                        v
                              +-------------------+
                              | Controlled        |
                              | Retrieval Tools   |
                              +---------+---------+
                                        |
                                        v
                              +-------------------+
                              | Claude Agent SDK  |
                              +---------+---------+
                                        |
                                        v
                              +-------------------+
                              | Incident Agent    |
                              +---------+---------+
                                        |
                              +---------+---------+
                              |                   |
                              v                   v
                       Human Review          Audit/Eval
```

## 3. Architectural Planes

### Operational Plane

FastAPI, domain services, repositories, SQLite, and deterministic operational APIs.

### Semantic Plane

Ontology, semantic mappings, Neo4j knowledge graph, graph validation, and graph retrieval.

### Intelligence Plane

Context engineering, controlled tools, Claude Agent SDK, incident agent, evaluation, and human review.

## 4. Context Engineering

Context engineering is a first-class application layer, not merely prompt text.

```text
Incident
  -> semantic identification
  -> graph traversal
  -> operational evidence retrieval
  -> source/repository context
  -> trust classification
  -> relevance filtering
  -> budget enforcement
  -> InvestigationContext
```

## 5. Retrieval

Retrieval evolves in stages:

1. deterministic relational retrieval
2. deterministic graph traversal
3. lexical retrieval
4. semantic/vector retrieval
5. hybrid graph + lexical + semantic retrieval

## 6. Ontology

The ontology is a versioned semantic contract. It is maintained outside Neo4j as a Turtle artifact and projected into the graph as required.

## 7. Neo4j Boundary

Application-owned retrieval services control graph access. The model must not receive unrestricted Cypher execution capability.

## 8. Agent Boundary

The Incident Agent consumes structured context and uses approved retrieval tools. It does not directly own database credentials or bypass application policy.

## 9. GitHub Boundary

```text
Incident -> Service -> RepositoryMapping -> approved repository
       -> relevant commit -> changed files -> relevant source
```

GitHub access is read-only initially.

## 10. MCP

MCP is an integration boundary for selected tools, not the core reasoning engine. MCP tools remain subject to application policy, validation, and authorization.

## 11. Human-in-the-Loop

Consequential actions require human approval. Investigation and recommendations may be automated; production changes are not implicitly authorized by model output.

## 12. Observability

Track request, retrieval, graph traversal, tool, model, policy, review, latency, error, and audit events without exposing secrets.

## 13. Testing

Testing spans:

- domain behavior
- API behavior
- repository behavior
- graph projection
- ontology constraints
- retrieval correctness
- context construction
- tool contracts
- agent behavior
- prompt injection
- policy enforcement
- evaluation regression

## 14. Dependency Direction

```text
API -> Application -> Domain -> Repository
                    |
                    +-> Context/Retrieval
                              |
                              +-> SQLite adapter
                              +-> Neo4j adapter
                              +-> GitHub adapter
```

Agent runtime depends on controlled retrieval interfaces, not storage internals.

## Current runtime reality (as of Phase 9; Phase 7 Gate 8 baseline plus the rows below)

The sections above describe the target architecture. This section states what the code actually does today.

| Component | Actual status |
|---|---|
| Tenancy | Since Gate 9.1 every tenant-owned row carries `tenant_id`; `tenants`/`users`/`tenant_users` hold the catalog and role-per-membership. Identity, repositories, workflows, audit, retrieval, MCP and the SQLite graph projection are tenant-scoped; the ontology stays one global model. |
| SQLite | The only persistence. Incidents, logs, metrics, deployments, workflows, decisions, audit events and event/idempotency records all live in SQLite. The location is configured by `PULSEOPS_DATABASE_URL` (default `sqlite:///./pulseops.db`, relative to the working directory). The application and the MCP subprocess use the same absolute URL. |
| Graph projection | `GraphRepository.project_operational_graph()` builds nodes and relationships in-process from SQLite on demand. `DEPENDS_ON` is a same-environment heuristic and is only generated for services that have a repository mapping, so it is not real dependency data. |
| Neo4j | Not connected at runtime. Only unused connection settings exist in `app/core/config.py`; the Neo4j container in `docker-compose.yml` is not used by the application. Runtime integration is future work. |
| Ontology | `ontology/pulseops.ttl` is a versioned design artifact. No runtime code loads or queries it. |
| Retrieval / MCP | Four read-only tools (`get_incident_context`, `get_related_incidents`, `get_service_repository`, `get_service_dependencies`) over SQLite and the projection above, exposed through the PulseOps MCP server. |
| Policy / HITL | Deterministic policy registry; every rule is non-executable. HITL approval is recorded but no action is executed. Since Gate 9 the approver is the authenticated human principal with a permitted role (bearer API credentials; SSO/OIDC deferred). |
| Evaluation | `evals/` (replay + optional live), a 24-case golden dataset, deterministic retrieval ground truth, content-hashed baseline. See `docs/phase-7-gate-7.md` and `docs/phase-7-gate-8.md`. |
| CI | `.github/workflows/ci.yml` runs the full test suite and the replay evaluation on Linux / Python 3.11 with no secrets. |
| Application (P9) | A React + Vite + TypeScript UI (`frontend/`, three views: incident list, incident detail, pending approvals) is built into static files and served by the API at `/ui` (same origin, strict CSP). It reads through the existing authenticated API; the backend stays authoritative for authorization and HITL. Investigation results are a first-class tenant-scoped `investigations` table. See `docs/phase-9.md`. |
| Quality (P11) | `python scripts/quality_gate.py` runs coverage (ratcheted), frontend tests/build, replay v2/v3 with tenant isolation, evaluation integrity, security tests, Bandit, dependency audit, secret scan, contract/reliability tests, a performance smoke, the Playwright E2E and a Docker build/run check. CI runs the same checks in separate jobs. Request bodies are bounded (413 above 1 MiB), a workflow records at most one decision (atomic compare-and-set), incident ids cannot collide silently and `/health/ready` verifies writability. See `docs/phase-11.md`. |
| Local platform | `docker-compose.yml`: `pulseops` (non-root, healthchecked, SQLite on `/data`) and a pinned, authenticated `n8n` on the `pulseops-net` network. Neo4j is an optional, unused container (`docker-compose.neo4j.yml`); Neo4j Desktop remains a local development environment. See `docs/phase-7-gate-9-implementation.md`. |

