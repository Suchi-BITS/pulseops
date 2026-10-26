# PulseOps — Knowledge Graph Architecture

> **Current runtime status (Gate 8):** this describes the target design. At runtime today the "graph" is a projection computed in-process from SQLite (`app/graph/repository.py`); PulseOps does not connect to Neo4j. See `docs/architecture.md`, section "Current runtime reality".

## 1. Purpose

Neo4j provides the semantic relationship and retrieval layer for PulseOps. It complements rather than replaces SQLite.

## 2. Responsibility Split

### SQLite

- transactional operational records
- CRUD operations
- API persistence
- deterministic local tests

### Neo4j

- semantic relationships
- service dependency topology
- incident-to-evidence relationships
- repository/deployment relationships
- graph traversal
- graph-based retrieval
- future hybrid retrieval

## 3. Projection Model

```text
SQLite operational data
        |
        v
Semantic mapping
        |
        v
Ontology concepts / relationships
        |
        v
Neo4j graph
```

The graph should be reproducible from approved source data and mapping rules.

## 4. Initial Graph Model

Example:

```text
(:Incident)-[:AFFECTS]->(:Service)
(:Incident)-[:HAS_LOG]->(:Log)
(:Incident)-[:HAS_METRIC]->(:Metric)
(:Incident)-[:HAS_EVIDENCE]->(:Evidence)
(:Service)-[:DEPENDS_ON]->(:Service)
(:Service)-[:IMPLEMENTED_BY]->(:Repository)
(:Repository)-[:HAS_DEPLOYMENT]->(:Deployment)
(:Deployment)-[:DEPLOYED_TO]->(:Environment)
(:Service)-[:OWNED_BY]->(:Team)
```

## 5. Identifiers

Operational identifiers must remain stable and should be used to correlate relational and graph representations.

## 6. Graph Access Boundary

The model must not generate arbitrary Cypher for execution.

Preferred boundary:

```text
Agent / Application
        |
        v
Typed Retrieval Tool
        |
        v
Validated parameters
        |
        v
Application-owned Cypher/query
        |
        v
Neo4j
```

## 7. Retrieval Evolution

Phase 2:

- deterministic graph traversal
- explicit relationships
- controlled Cypher

Later:

- full-text retrieval
- vector retrieval
- hybrid retrieval
- graph-aware ranking

## 8. Context Construction

Graph retrieval is one input into the Context Engineering layer. The context builder combines graph-derived relationships with operational evidence and applies relevance, trust, provenance, and budget rules.

## 9. Consistency

Neo4j is a semantic projection, not the only source of truth for operational records. Projection processes must be repeatable and observable.

## 10. Security

- read-only initial access
- least privilege
- no model-provided arbitrary Cypher
- no secrets in graph properties
- controlled repository mapping
- audit important graph retrieval operations
