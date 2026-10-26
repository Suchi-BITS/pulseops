# PulseOps — Data Model

## 1. Purpose

PulseOps uses a polyglot data architecture with a transactional operational store and a semantic graph projection.

## 2. Operational Store

SQLite is the initial operational persistence layer. PostgreSQL is a future production option.

Initial entities:

- Service
- Incident
- Log
- Metric
- Deployment
- Repository
- RepositoryMapping

Future derived/human entities:

- Evidence
- IncidentAnalysis
- Hypothesis
- HypothesisEvidence
- Recommendation
- HumanReview
- AuditEvent
- AgentExecution

## 3. Semantic Representation

The ontology adds semantic concepts and relationships around operational entities.

```text
Operational entity -> semantic concept -> graph node
Operational relation -> ontology relation -> graph edge
```

## 4. SQLite vs Neo4j

| Concern | SQLite | Neo4j |
|---|---|---|
| Transactional CRUD | Primary | Not primary |
| API persistence | Primary | Projection/retrieval |
| Domain relationships | Foreign keys | Rich graph relationships |
| Dependency traversal | Limited | Primary |
| Semantic ontology | Not primary | Primary representation |
| Graph retrieval | No | Primary |
| Future vector retrieval | Optional | Candidate layer |

## 5. Graph Projection

The graph must preserve stable operational identifiers so an Incident in SQLite can be correlated with the corresponding `:Incident` node in Neo4j.

## 6. Source vs Derived Data

Source operational data must remain distinguishable from:

- graph projections
- derived evidence objects
- AI hypotheses
- recommendations

AI-derived information must never overwrite source evidence.

## 7. Initial Graph Nodes

```text
Incident
Service
Log
Metric
Deployment
Repository
Environment
Team
Evidence
```

## 8. Initial Graph Relationships

```text
Incident -> AFFECTS -> Service
Incident -> HAS_LOG -> Log
Incident -> HAS_METRIC -> Metric
Incident -> HAS_EVIDENCE -> Evidence
Service -> DEPENDS_ON -> Service
Service -> IMPLEMENTED_BY -> Repository
Repository -> HAS_DEPLOYMENT -> Deployment
Deployment -> DEPLOYED_TO -> Environment
Service -> OWNED_BY -> Team
```

## 9. Data Access

The Context Builder and future agent use repository/service abstractions and controlled retrieval interfaces. They must not couple directly to raw SQLite or Neo4j internals.

## 10. Data Minimization

Only evidence relevant to the investigation should enter model context. Entire repositories, entire incident histories, or unrestricted graph neighborhoods must not be dumped into the model.
