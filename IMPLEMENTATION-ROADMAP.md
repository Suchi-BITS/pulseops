# PulseOps — Revised Implementation Roadmap

> **Status (Gate 8):** older than `project-plan.md`, which is the authoritative roadmap for phase scope and naming. Use this file only as sequencing guidance for production hardening (see its Phase 9 and `docs/phase-7-gate-8.md`).

Phase 0 and Phase 1 are complete. This roadmap supersedes the earlier Phase 2+ roadmap.

| Phase | Focus | Depends on |
|---|---|---|
| 2 | Ontology + Neo4j + Context Engineering | 1 |
| 3 | Controlled Retrieval Tools | 2 |
| 4 | MCP Integration | 3 |
| 5 | Claude Agent SDK | 3, 4 where applicable |
| 6 | Incident Agent | 5 |
| 7 | Workflow / n8n | 6 |
| 8 | HITL + Evaluation | 6, 7 |
| 9 | Production Readiness | 8 |

## Phase 2

Ontology artifact, semantic mapping, Neo4j projection, graph retrieval, bounded InvestigationContext.

## Phase 3

Typed retrieval tools for operational, graph, and controlled source-code context.

## Phase 4

Selected retrieval capabilities exposed through MCP under application policy.

## Phase 5

Claude Agent SDK runtime with structured output and bounded tool use.

## Phase 6

Single Incident Agent with investigation state, evidence grounding, hypotheses, missing information, recommendations, and confidence.

## Phase 7

Workflow coordination and event-driven investigation using n8n where appropriate.

## Phase 8

Human review, approval boundaries, ground-truth incidents, retrieval evaluation, agent evaluation, and regression testing.

## Phase 9

PostgreSQL, authentication/authorization, secrets, observability, deployment, resilience, governance, and production operations.
