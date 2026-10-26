# PulseOps — Business Context

## Product

PulseOps is an AI-powered incident intelligence platform for application and service incidents.

## Primary Users

- Incident responder
- Software engineer
- Engineering manager / technical lead
- Platform / SRE engineer

## Problem

Incident investigation often requires correlating information across incidents, services, logs, metrics, deployments, repositories, historical incidents, and ownership/dependency information.

PulseOps creates a semantic representation of these relationships so investigation context can be assembled systematically rather than by dumping unrelated data into an AI model.

## Primary Journey

```text
Incident
  -> Identify affected service
  -> Traverse service/dependency relationships
  -> Find relevant operational evidence
  -> Find relevant deployment/source changes
  -> Build bounded investigation context
  -> AI investigation
  -> Evidence-grounded hypotheses
  -> Recommendations and missing information
  -> Human verification
```

## Product Boundary

PulseOps assists investigation. It does not make the engineer's consequential production decisions.

## AI Role

AI may:

- analyze evidence
- form hypotheses
- identify missing information
- recommend investigation steps
- summarize evidence

AI must not:

- fabricate evidence
- silently alter source records
- bypass authorization
- execute high-risk production actions without approval

## Semantic Layer

The ontology and knowledge graph provide a shared semantic representation of incidents, services, dependencies, deployments, repositories, teams, and evidence.

## Core Principle

> AI should reduce the effort required to investigate an incident without reducing the engineer's responsibility to verify the result.
