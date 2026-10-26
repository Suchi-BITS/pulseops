# PulseOps — Phase 4: MCP Tool Integration

## 1. Objective

Phase 4 introduces Model Context Protocol (MCP) as the standardized
tool interface between PulseOps retrieval capabilities and future AI
agents.

The objective is to expose the existing Phase 3 controlled retrieval
capabilities through an MCP server.

MCP becomes an integration boundary.

It does NOT replace:

- the retrieval layer
- the application security layer
- the context-engineering layer
- SQLite
- Neo4j
- the ontology
- repository abstractions

The architecture must remain:

AI Agent
    ↓
MCP
    ↓
Controlled Retrieval Layer
    ↓
SQLite / Neo4j / Context Layer

The AI agent must never receive direct database access.

---

# 2. Architectural Position

The Phase 4 architecture is:

```text
                         PulseOps

                ┌──────────────────────┐
                │   Future AI Agent    │
                │ Claude Agent SDK     │
                └──────────┬───────────┘
                           │
                           │ MCP
                           ▼
                ┌──────────────────────┐
                │     MCP Server       │
                │                      │
                │  Controlled Tools    │
                └──────────┬───────────┘
                           │
                           ▼
                ┌──────────────────────┐
                │ Retrieval Service    │
                │      Phase 3         │
                └──────────┬───────────┘
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
        ┌───────────┐             ┌───────────┐
        │  SQLite   │             │   Neo4j   │
        │Operational│             │ Semantic  │
        │   Data    │             │   Graph   │
        └───────────┘             └───────────┘
              │                         │
              └────────────┬────────────┘
                           ▼
                    Context Layer