# PulseOps — Agent Architecture

## 1. Agent Objective

The Incident Agent investigates an incident using controlled, evidence-grounded context and produces structured analysis.

## 2. Agent Boundary

The agent is not the database layer, policy engine, or unrestricted execution engine.

```text
                 Incident Agent
                       |
                       v
              Controlled Tools
                       |
                       v
              Retrieval Services
                /          \
               v            v
           SQLite          Neo4j
               \            /
                v          v
             Evidence / Context
                       |
                       v
                Agent Reasoning
```

## 3. Agent Input

The agent receives:

- incident information
- affected service
- investigation objective
- bounded evidence
- graph-derived relationships
- relevant source/repository context
- known missing information

## 4. Agent State

Initial state should include:

- incident
- objective
- evidence
- hypotheses
- missing_information
- recommendations
- tool_calls
- errors
- confidence
- status

## 5. Investigation Loop

```text
Receive incident
      |
      v
Inspect context
      |
      v
Identify information gaps
      |
      v
Use approved retrieval tool
      |
      v
Validate returned evidence
      |
      v
Update hypotheses
      |
      v
Determine whether more evidence is required
      |
      +---- yes ---> retrieve more
      |
      no
      v
Produce structured result
```

## 6. Context First

The agent should consume the Context Engineering output rather than receive unrestricted database access.

## 7. Tool Categories

Initial read-only tools:

- get_incident
- get_service
- get_related_graph_entities
- get_recent_logs
- get_metrics
- get_recent_deployment
- get_historical_incidents
- get_repository
- get_recent_commits
- get_commit_changes
- get_file
- search_code

Tool availability must be controlled by policy and phase.

## 8. Graph Retrieval

Graph tools should expose domain operations rather than arbitrary Cypher.

Examples:

```text
get_service_dependencies(service_id)
get_service_repository(service_id)
get_incident_related_entities(incident_id)
get_recent_deployment(service_id)
```

## 9. Evidence Grounding

Every important hypothesis should reference supporting evidence. The system should distinguish:

```text
Observed evidence
AI hypothesis
Recommendation
```

## 10. Structured Output

Future agent output should contain:

- summary
- evidence
- hypotheses
- missing_information
- recommendations
- confidence
- uncertainty

Output must pass schema and business validation.

## 11. Security

- No unrestricted Cypher.
- No unrestricted shell execution.
- No production credentials.
- External content is untrusted.
- High-risk actions require human approval.

## 12. Claude Agent SDK

Claude Agent SDK is introduced only after the retrieval and context boundaries are stable. It becomes the application-facing agent runtime, not the source of truth for domain data.

## 13. MCP

MCP can expose selected retrieval capabilities, but application authorization and policy remain authoritative.

## 14. Single-Agent First

Start with one Incident Agent. Multi-agent orchestration should only be introduced if evaluation demonstrates a real need.

## 15. Agent Memory

Persistent memory is not required for the first agent. Investigation state should be explicit, bounded, and auditable.
