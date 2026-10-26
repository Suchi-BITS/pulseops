We are now preparing for Gate 8 of the PulseOps AI Incident Intelligence Platform.

IMPORTANT:
This is an ARCHITECTURE REVIEW ONLY.

DO NOT modify any files.
DO NOT create new files.
DO NOT refactor existing code.
DO NOT install packages.
DO NOT run destructive commands.
DO NOT implement anything.

First inspect the repository and provide a detailed architecture review.

==================================================
1. CONTEXT
==================================================

PulseOps is an enterprise AI Incident Intelligence Platform.

Core principle:

    AI Pair, Not AI Authority

The system is designed to investigate operational incidents using controlled evidence and AI reasoning while preventing autonomous high-risk production actions.

Current architecture:

Operational Event
      ↓
n8n / webhook
      ↓
PulseOps FastAPI
      ↓
Operational DB
      +
Ontology / Knowledge Graph Context
      ↓
Controlled Retrieval Tools
      ↓
MCP
      ↓
Claude Agent SDK
      ↓
Incident Investigation
      ↓
Structured InvestigationResult
      ↓
Deterministic Policy Engine
      ↓
LOW / MEDIUM / HIGH
      ↓
Notification / HITL
      ↓
Approval / Rejection
      ↓
Audit

Architectural ownership:

- FastAPI = application/business API
- SQLite = operational persistence for current development stage
- Neo4j = semantic/relationship graph projection
- Ontology = semantic source of truth
- Context builder = controlled evidence construction
- Retrieval services = controlled operational/semantic access
- MCP = controlled tool boundary
- Claude Agent SDK = reasoning/application AI layer
- Incident Agent = investigation logic
- Policy Engine = deterministic safety authority
- n8n = workflow orchestration
- HITL = human authorization for consequential actions
- Audit = durable workflow accountability
- Evaluation harness = reliability/safety validation

n8n MUST NOT become the owner of business logic.

Claude MUST NOT become the owner of safety policy.

The LLM MUST NOT override deterministic policy.

High-risk actions MUST require explicit human approval.

==================================================
2. COMPLETED PHASES
==================================================

P0 Foundation
P1 Operational Data
P2 Ontology + Knowledge Graph + Context Engineering
P3 Controlled Retrieval Tools
P4 MCP
P5 Claude Agent SDK
P6 Incident Agent
P7 Operational Workflow

Gate 6:
- Local n8n integration
- Event ingestion
- Event validation
- Existing Incident Agent integration
- Deterministic policy evaluation
- LOW / MEDIUM / HIGH routing
- HITL path
- Idempotency
- Audit
- Fail-closed behavior

Gate 7:
- Evaluation harness
- 12 golden evaluation cases
- Deterministic replay evaluation
- System correctness/safety metrics
- AI quality metrics
- Fabrication detection
- Grounding checks
- Prompt-injection resistance
- Policy-boundary evaluation
- Regression baseline
- Negative-control testing
- Minimal GitHub Actions evaluation workflow
- Live evaluation path which explicitly SKIPs when no API key is configured

Gate 7 result:

141 tests passed.

Gate 7 is considered COMPLETE.

==================================================
3. IMPORTANT GATE 7 OBSERVATION
==================================================

Gate 7 identified the following technical limitation:

When investigation fails or cannot be grounded:

- evidence is cleared
- hypotheses are cleared
- confidence is cleared

However, model-generated recommendations may still remain.

Therefore an unknown incident or failed investigation can potentially contain a recommendation such as:

"Roll back the last deployment."

These recommendations remain subject to deterministic policy and HITL.

This has been recorded as technical debt / known limitation.

DO NOT reopen P6 or Gate 7 automatically.

Instead determine whether this should be addressed in Gate 8 or a later hardening gate.

==================================================
4. ORIGINAL ROADMAP
==================================================

The original roadmap was:

P0 Foundation
P1 Operational Data
P2 Ontology + Knowledge Graph + Context Engineering
P3 Retrieval Tools
P4 MCP
P5 Claude Agent SDK
P6 Incident Agent
P7 Workflow + HITL
P8 Evaluation
P9 Modern Application
P10 Cloud + Platform
P11 Quality Engineering
P12 PulseOps v1.0 Capstone

Gate 7 has already implemented a substantial evaluation harness.

Therefore Gate 8 MUST NOT blindly duplicate Gate 7.

Determine exactly what remains from the original P8 Evaluation scope after Gate 7.

==================================================
5. FIRST: INSPECT THE ACTUAL REPOSITORY
==================================================

Before making recommendations, inspect:

- CLAUDE.md
- project-plan.md
- docs/
- app/
- tests/
- evals/
- ontology/
- Docker configuration
- pyproject.toml
- GitHub Actions configuration
- all Phase 7 gate documents
- Phase 6 implementation
- Phase 7 workflow implementation
- evaluation implementation

Pay particular attention to:

- agent architecture
- workflow state machine
- policy engine
- HITL enforcement
- audit implementation
- idempotency implementation
- event ingestion
- n8n integration
- evaluation contracts
- evaluation datasets
- scoring logic
- regression baseline
- CI workflow
- failure handling
- security boundaries

Do not assume that the repository matches the documentation.

Compare documentation against actual implementation.

==================================================
6. REVIEW QUESTION #1
==================================================

Determine:

WHAT HAS GATE 7 ALREADY SATISFIED?

Create a table:

| Original P8 Requirement | Already Implemented? | Where | Evidence | Remaining Gap |

Do not invent requirements.

Use the existing project-plan.md and phase documentation as the source of truth.

==================================================
7. REVIEW QUESTION #2
==================================================

Determine what a true production-grade evaluation architecture should contain beyond the current Gate 7 harness.

Consider, based on the existing architecture:

A. System correctness
B. Safety
C. Grounding
D. Evidence attribution
E. Fabrication detection
F. Tool-use correctness
G. Failure behavior
H. Policy-boundary enforcement
I. Prompt-injection resistance
J. Regression detection
K. AI output quality
L. Human evaluation
M. LLM-as-judge
N. Evaluation dataset growth
O. Evaluation reproducibility
P. Evaluation observability
Q. Production telemetry
R. Cost/latency evaluation
S. Model/version regression
T. CI/CD evaluation gates

Clearly distinguish:

1. What is required for PulseOps v1.0
2. What is useful but can wait
3. What is unnecessary complexity at this stage

==================================================
8. REVIEW QUESTION #3
==================================================

Evaluate whether we should introduce:

- RAGAS
- DeepEval
- LLM-as-a-judge
- human evaluation
- tracing-based evaluation
- production feedback loops

Do NOT recommend a framework simply because it is popular.

For every proposed technology answer:

1. What problem does it solve?
2. Does PulseOps currently have that problem?
3. What does our current deterministic harness already solve?
4. What additional signal would it provide?
5. What complexity does it introduce?
6. Should it be introduced now, later, or not at all?

Remember:

PulseOps is not currently a generic RAG application.

The current architecture is primarily:

Operational Data
+
Knowledge Graph Context
+
Controlled Retrieval
+
MCP
+
Agent Investigation

Therefore do not force conventional RAG evaluation metrics into the architecture unless justified.

==================================================
9. REVIEW QUESTION #4
==================================================

Evaluate the Gate 7 known limitation:

Investigation failure / ungrounded investigation
        ↓
evidence = []
hypotheses = []
confidence = 0

BUT:

recommendations may still exist.

Determine whether this violates the PulseOps safety contract.

Evaluate at least these possible designs:

Option A:
Clear recommendations whenever investigation is ungrounded.

Option B:
Allow recommendations but mark them explicitly as ungrounded.

Option C:
Allow recommendations but force them through an additional safety gate.

Option D:
Treat recommendations as informational only when grounding is absent.

Recommend ONE approach.

Explain why.

Do not implement it.

==================================================
10. REVIEW QUESTION #5
==================================================

Review the current evaluation architecture for false confidence.

Specifically determine whether:

- 12 golden cases are enough for the current stage
- deterministic replay can be confused with model-quality evaluation
- keyword-based relevance scoring has limitations
- baseline comparison can become stale
- evaluation fixtures are coupled to seed data
- live evaluation coverage is too narrow
- CI gives sufficient confidence
- evaluation can detect semantic hallucination
- evaluation can detect subtle reasoning errors

Explicitly identify what the current evaluation harness CAN prove and CANNOT prove.

==================================================
11. REVIEW QUESTION #6
==================================================

Design the recommended evaluation maturity model.

For example:

Level 1 — Unit / contract tests
Level 2 — Deterministic replay
Level 3 — Golden dataset
Level 4 — Live model evaluation
Level 5 — Regression evaluation
Level 6 — Human evaluation
Level 7 — Production feedback/evaluation

Do not assume this exact model is correct.

Create the model that best fits PulseOps.

Explain which level PulseOps currently occupies and what the next level should be.

==================================================
12. REVIEW QUESTION #7
==================================================

Review production-readiness gaps AFTER Gate 7.

Look across:

Security
Reliability
Observability
Evaluation
Performance
Cost
API
Persistence
Authentication
Authorization
Secrets
Audit
HITL
Failure recovery
Idempotency
n8n reliability
Agent reliability
MCP reliability
Neo4j reliability
Database reliability
Docker
CI/CD
Cloud deployment
Frontend
Operational monitoring

Classify each gap:

P0 — blocks safe production
P1 — required for v1.0
P2 — useful enhancement
P3 — future enterprise enhancement

Do not implement anything.

==================================================
13. REVIEW QUESTION #8
==================================================

Determine whether Gate 8 should be:

A. Advanced Evaluation
B. Production Reliability
C. Security Hardening
D. Observability
E. Evaluation + Reliability
F. Something else

Recommend the most logical next gate.

The decision MUST be based on the actual repository and the completed Gate 7 implementation.

==================================================
14. REVIEW QUESTION #9
==================================================

Propose the exact scope for Gate 8.

The proposal should include:

- Objective
- Scope
- Non-goals
- Files likely to change
- New tests
- Acceptance criteria
- Security requirements
- Failure requirements
- Evaluation requirements
- Documentation requirements
- Manual verification requirements
- Full-suite verification requirements

Do not implement.

==================================================
15. REVIEW QUESTION #10
==================================================

Check for architectural contradictions.

Look specifically for:

- n8n duplicating business logic
- LLM controlling policy
- LLM controlling risk
- AI approving its own action
- HITL bypass
- recommendations without grounding
- audit gaps
- idempotency gaps
- workflow state inconsistencies
- MCP bypass
- direct DB access from agent
- direct Neo4j access from agent
- arbitrary SQL/Cypher
- uncontrolled GitHub access
- autonomous production actions
- evaluation harness importing application state incorrectly
- application importing evaluation code
- CI giving false confidence
- test fixtures masking production behavior

List every contradiction found.

==================================================
16. REQUIRED OUTPUT FORMAT
==================================================

Return exactly these sections:

# Gate 8 Architecture Review

## 1. Repository Findings

## 2. Gate 7 Capabilities Already Satisfied

| Requirement | Status | Evidence | Remaining Gap |

## 3. Original P8 vs Current Implementation

| P8 Capability | Current State | Gap | Recommendation |

## 4. Evaluation Architecture Assessment

Separate:

### System Correctness
### Safety
### Grounding
### AI Quality
### Regression
### Live Model Evaluation
### Human Evaluation
### Production Evaluation

## 5. Known Limitation: Ungrounded Recommendations

Explain the problem and recommend one solution.

## 6. False-Confidence Risks

Explain what current evaluation can and cannot prove.

## 7. Production Readiness Gap Matrix

| Area | Gap | Priority | Why |

## 8. Architecture Contradictions

List any violations or potential violations.

## 9. Recommended Gate 8

### Objective
### Scope
### Non-Goals
### Proposed Architecture
### Files Likely to Change
### Tests
### Acceptance Criteria
### Manual Verification
### Documentation

## 10. Gate 8 Decision

Choose exactly one:

APPROVE GATE 8 SCOPE

or

REVISE GATE 8 SCOPE

or

DO NOT PROCEED

Explain the decision.

==================================================
17. ABSOLUTE CONSTRAINTS
==================================================

DO NOT:

- modify files
- create files
- install dependencies
- change architecture
- change Phase 6
- change Phase 7
- add RAGAS automatically
- add DeepEval automatically
- add an LLM judge automatically
- introduce vector search
- introduce multi-agent architecture
- introduce autonomous remediation
- add production credentials
- add Slack
- add GitHub write access
- add AWS/Kubernetes production actions
- deploy to cloud
- redesign authentication/RBAC
- rewrite existing evaluation infrastructure

This is an architecture review only.

STOP after producing the review.

Wait for explicit approval before making any implementation changes.