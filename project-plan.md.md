# PulseOps — Master Project Plan

## 1. Vision

PulseOps is an AI-powered incident intelligence platform that helps engineers investigate application incidents by combining operational data, an ontology-grounded knowledge graph, controlled source-code context, and an AI investigation agent.

Core principle:

> AI Pair, Not AI Authority.

The system must distinguish observed evidence from hypotheses and recommendations. Humans remain responsible for consequential engineering and production decisions.

## 2. Primary Use Case

An engineer receives an incident such as elevated error rate for a service.

PulseOps should:

1. Identify the affected service and related operational entities.
2. Traverse semantic relationships represented in the knowledge graph.
3. Retrieve relevant logs, metrics, deployments, historical incidents, and approved repository context.
4. Build a bounded investigation context.
5. Allow an AI agent to analyze that context using controlled tools.
6. Return structured hypotheses, supporting evidence, missing information, recommendations, and confidence.
7. Preserve provenance and auditability.

## 3. Architectural Principles

- Operational records and semantic knowledge are separate but connected.
- SQLite is the initial transactional store.
- Neo4j is the semantic/relationship and retrieval layer.
- An explicit ontology defines the domain vocabulary and relationships.
- The ontology is maintained as a versioned semantic artifact, initially RDF/OWL-compatible Turtle.
- The knowledge graph is a projection of approved operational and semantic data.
- Agents access data through controlled retrieval tools, not unrestricted database access.
- AI-generated content is untrusted until validated.
- External content is treated as untrusted data, not instructions.
- Read-only access is the default for investigation.
- Consequential actions require human approval.
- Every major AI/tool decision should be observable and auditable.

## 4. Target Architecture

```text
                         PulseOps
                            |
             +--------------+--------------+
             |                             |
      Operational Plane              Intelligence Plane
             |                             |
          FastAPI                   Context Engineering
             |                             |
          SQLite                    Ontology / Semantics
             |                             |
      Operational Data                  Neo4j
             |                             |
             +---------------+-------------+
                             |
                    Controlled Retrieval
                             |
                    Evidence / Context
                             |
                     Claude Agent SDK
                             |
                      Incident Agent
                             |
                   Human Review / HITL
                             |
                      Audit / Evaluation
```

## 5. Semantic Architecture

```text
Operational Records
        |
        v
Semantic Mapping
        |
        v
Ontology (RDF/OWL-compatible)
        |
        v
Neo4j Knowledge Graph
        |
        +--> graph traversal
        +--> lexical retrieval
        +--> semantic/vector retrieval (later)
        |
        v
Context Engineering
        |
        v
Investigation Context
```

## 6. Domain Model

Initial operational entities:

- Service
- Incident
- Log
- Metric
- Deployment
- Repository
- RepositoryMapping

Semantic entities introduced by the ontology include:

- Application
- Environment
- Team
- Dependency
- Evidence
- Hypothesis
- Recommendation
- Change

The relational model remains optimized for operational persistence. The graph represents relationships and semantic meaning needed for investigation and retrieval.

## 7. AI Engineering Progression

The project demonstrates six engineering levels:

1. Prompt Engineer — formulate precise AI tasks.
2. Context Engineer — construct bounded, relevant, trusted context.
3. Tool Master — design controlled tools and contracts.
4. Workflow Architect — compose deterministic and AI-assisted workflows.
5. Agent Orchestrator — design agent loops, state, and tool use.
6. AI Engineering Architect — design security, evaluation, observability, governance, and production architecture.

## 8. Implementation Roadmap

### Phase 0 — Software Foundation — COMPLETE

FastAPI, configuration, pytest, Docker, project hygiene.

### Phase 1 — Operational Data Foundation — COMPLETE

SQLite, operational entities, repositories, services, deterministic seed data, incident APIs.

### Phase 2 — Ontology + Knowledge Graph + Context Engineering

- Define PulseOps domain ontology.
- Create versioned Turtle ontology artifact.
- Define semantic mappings from operational entities to ontology concepts.
- Introduce Neo4j.
- Project operational relationships into Neo4j.
- Validate graph structure and ontology constraints.
- Build graph retrieval services.
- Build deterministic context builder.
- Add evidence provenance, trust classification, relevance, and context budgets.
- Serialize InvestigationContext for future agent consumption.

### Phase 3 — Controlled Retrieval Tools

- Define typed retrieval tool contracts.
- Add incident/service/evidence retrieval tools.
- Add graph traversal tools.
- Add repository-context tools using controlled mappings.
- Add tool validation, timeout, permissions, and failure handling.
- Keep tools read-only initially.

### Phase 4 — MCP Integration

- Expose selected retrieval capabilities through MCP where useful.
- Keep MCP behind application policy and tool authorization.
- Validate tool schemas and outputs.
- Prevent arbitrary Cypher or shell execution.

### Phase 5 — Claude Agent SDK

- Introduce Claude Agent SDK as the application-facing agent runtime.
- Connect the agent to approved retrieval tools.
- Implement structured output validation.
- Implement bounded investigation loops and resource limits.

### Phase 6 — Incident Agent

- Implement single-agent investigation workflow.
- Build agent state and evidence grounding.
- Track hypotheses, missing information, recommendations, confidence, tool calls, and errors.
- Add prompt-injection defenses and policy checks.

### Phase 7 — Workflow and Orchestration

- Integrate workflow orchestration where it adds value.
- Use n8n for external workflow coordination rather than core reasoning.
- Add event-driven or scheduled investigation flows.
- Preserve application policy boundaries.

### Phase 8 — Human-in-the-Loop + Evaluation

- Add human review and approval flows.
- Build ground-truth incident scenarios.
- Evaluate retrieval quality, evidence grounding, faithfulness, answer relevance, tool behavior, latency, and failure handling.
- Add regression evaluation.

### Phase 9 — Production Readiness

- PostgreSQL migration path.
- Secure secrets/configuration.
- authentication and authorization.
- observability and tracing.
- auditability.
- deployment architecture.
- resilience and operational controls.

## 9. Retrieval Strategy

The long-term retrieval layer should combine three complementary signals:

```text
Lexical Retrieval
        +
Semantic Retrieval
        +
Graph Retrieval
        |
        v
Candidate Evidence
        |
        v
Ranking / Filtering
        |
        v
Investigation Context
```

Vector retrieval is deliberately deferred until the graph and deterministic context layer are stable.

## 10. GitHub Strategy

GitHub access remains controlled and read-only.

Preferred path:

```text
Incident -> Service -> RepositoryMapping -> Approved Repository
        -> Relevant Commit -> Changed Files -> Relevant Source
```

Do not expose an entire GitHub account or all repositories to the agent.

## 11. Security

- Least privilege.
- No secrets in source, prompts, ontology, logs, or audit events.
- No arbitrary Cypher from the model.
- No arbitrary shell execution by the agent.
- Untrusted content cannot redefine system instructions.
- High-risk actions require human approval.
- Fail closed on authorization or policy failures.

## 12. Evaluation

Evaluation must cover both retrieval and agent behavior.

Retrieval dimensions:

- relevance
- precision@K
- recall@K
- graph-path correctness
- evidence provenance
- context completeness

Agent dimensions:

- faithfulness
- answer relevance
- evidence grounding
- tool correctness
- policy compliance
- hallucination rate
- latency/resource usage

## 13. Source of Truth

- `plan.md` — overall product and implementation roadmap.
- `CLAUDE.md` — persistent development instructions.
- `docs/architecture.md` — system architecture.
- `docs/data-model.md` — operational and semantic data model.
- `docs/ontology.md` — domain ontology design.
- `docs/knowledge-graph.md` — Neo4j projection and retrieval design.
- `docs/agent-architecture.md` — agent boundary and runtime architecture.
- `docs/security.md` — security requirements.
- `ontology/pulseops.ttl` — versioned ontology artifact.
- `docs/phases/*` — phase-specific implementation contracts.

## 14. Current State

Phase 0 and Phase 1 are complete.

The next implementation boundary is Phase 2: ontology, Neo4j knowledge graph, and deterministic context engineering.
