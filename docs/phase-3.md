# PulseOps — Phase 3: Controlled Retrieval Tools

## 1. Objective

Phase 3 introduces the controlled retrieval layer between the PulseOps
application data/context layers and the future AI agent.

The objective is to expose well-defined, read-only retrieval capabilities
that can gather incident evidence from:

- SQLite operational data
- Neo4j semantic/relationship data
- the existing context-engineering layer

The retrieval layer must provide deterministic, typed, bounded access to
incident information.

This phase does NOT introduce an LLM, Claude Agent SDK, MCP, n8n,
autonomous agents, GitHub API integration, embeddings, or vector search.

The result of this phase is a stable retrieval interface that future
MCP tools and the Incident Agent can consume.

---

# 2. Architectural Position

The retrieval layer sits between the operational/semantic data layers
and the future AI intelligence layer.

```text
                   PulseOps

              ┌─────────────────┐
              │  Future AI Agent │
              │ Claude Agent SDK│
              └────────┬────────┘
                       │
                       ▼
              ┌─────────────────┐
              │ Retrieval Tools │
              │   Read-Only     │
              └────────┬────────┘
                       │
             ┌─────────┴─────────┐
             │                   │
             ▼                   ▼
      ┌──────────────┐    ┌──────────────┐
      │    SQLite    │    │    Neo4j     │
      │ Operational  │    │   Semantic   │
      │    Data      │    │    Graph     │
      └──────────────┘    └──────────────┘
             │                   │
             └─────────┬─────────┘
                       ▼
                Context Layer