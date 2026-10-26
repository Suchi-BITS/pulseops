# PulseOps — Domain Ontology

> **Current runtime status (Gate 8):** `ontology/pulseops.ttl` is a versioned design artifact. No runtime code loads or queries it today. See `docs/architecture.md`, section "Current runtime reality".

## 1. Purpose

The PulseOps ontology provides the semantic vocabulary for incident investigation. It defines domain concepts and relationships independently from a particular database schema.

The ontology is represented as a versioned RDF/OWL-compatible Turtle artifact at `ontology/pulseops.ttl`.

## 2. Core Classes

- Incident
- Service
- Application
- Repository
- Deployment
- Environment
- Log
- Metric
- Team
- Evidence
- Hypothesis
- Recommendation
- Change
- Dependency

## 3. Core Relationships

- Incident `affects` Service
- Incident `hasEvidence` Evidence
- Incident `hasLog` Log
- Incident `hasMetric` Metric
- Incident `relatedTo` Incident
- Service `implements` Application
- Service `dependsOn` Service
- Service `ownedBy` Team
- Service `implementedBy` Repository
- Repository `hasDeployment` Deployment
- Deployment `deployedTo` Environment
- Deployment `introducesChange` Change
- Evidence `supports` Hypothesis
- Hypothesis `aboutService` Service
- Recommendation `addresses` Hypothesis
- Change `affects` Service

## 4. Semantic Design Rules

1. Classes represent stable domain concepts.
2. Relationships represent meaningful domain semantics, not database joins copied blindly.
3. Operational identifiers remain available as identifiers/properties.
4. Source evidence retains provenance.
5. AI-derived concepts such as Hypothesis and Recommendation must remain distinguishable from observed evidence.
6. Ontology changes are version-controlled.
7. Application validation must not depend solely on inferred graph relationships.

## 5. Ontology vs Operational Schema

The ontology is not a replacement for the operational schema.

```text
Operational Schema -> persistence and transactional operations
Ontology           -> semantic meaning and relationships
Neo4j              -> graph projection and retrieval
```

## 6. Future Extensions

The ontology can later incorporate:

- cloud resources
- deployment pipelines
- alerts
- traces
- ownership hierarchies
- business impact
- FinOps/resource relationships
- security events

These are not required for Phase 2.
