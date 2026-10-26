# PulseOps Phase 7 — Workflow Orchestration + Human-in-the-Loop

## 1. Objective

Phase 7 extends the completed Phase 6 Incident Intelligence Agent into an operational incident workflow.

Phase 6 established:

Operational Data
→ Context Engineering
→ Controlled Retrieval
→ MCP
→ Claude Agent SDK
→ Incident Intelligence Agent
→ Grounded InvestigationResult

Phase 7 adds:

Incident Event
→ Workflow Orchestration
→ Validation
→ PulseOps API
→ Incident Investigation
→ Policy Evaluation
→ Risk Classification
→ Notification / HITL
→ Approval / Rejection
→ Audit

The objective is to demonstrate how AI reasoning becomes part of a controlled operational workflow without giving the AI unrestricted authority over production systems.

Core principle:

AI Pair, Not AI Authority.

The AI may investigate, summarize, classify, recommend, and request approval.

The AI must not independently execute consequential production actions.

---

# 2. Phase 7 Architectural Goal

The target workflow is:

Operational Event
        ↓
n8n Webhook
        ↓
Input Validation
        ↓
PulseOps API
        ↓
Incident Investigation Agent
        ↓
Grounded InvestigationResult
        ↓
Policy Evaluation
        ↓
Risk Classification
        ↓
+--------------------------+
|                          |
| Low Risk                 | Higher Risk
|                          |
↓                          ↓
Notification            Human Approval
                             ↓
                       +-----+-----+
                       |           |
                    Approve      Reject
                       |           |
                       ↓           ↓
                  Action*       Audit
                       |
                       ↓
                     Audit

* Phase 7 actions must remain safe, bounded, and explicitly approved.