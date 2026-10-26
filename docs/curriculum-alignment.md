# PulseOps — Curriculum Alignment

## Purpose

This document maps the 192-hour AI Engineering Apprenticeship curriculum to
the PulseOps project.

The curriculum remains the master learning journey.

PulseOps is the integrated engineering project through which learners apply
the skills from the curriculum.

The PulseOps implementation phases are technical milestones and do not
replace or renumber the curriculum phases.

---

## Master Relationship

```text
192-Hour Curriculum
        |
        v
Learning Competencies
        |
        v
PulseOps Capabilities
        |
        v
Project Artifacts + Labs + Tests
        |
        v
PulseOps v1.0 Capstone
```

---

# Curriculum Phase 1 — Engineering Foundations

## Learning Focus

- software engineering foundations
- Git and GitHub
- Linux
- Agile/Scrum
- DevOps fundamentals
- engineering workflow

## PulseOps Application

PulseOps establishes:

- Git repository
- branch and change workflow
- repository documentation
- local development environment
- Docker-based development
- engineering conventions
- AI-assisted development workflow

## Project Evidence

- Git history
- README
- CLAUDE.md
- architecture documentation
- development conventions
- Docker configuration

## Relevant PulseOps Milestones

```text
P0 — Software Foundation
P1 — Operational Data Foundation
```

---

# Curriculum Phase 2 — API Engineering

## Learning Focus

- HTTP and REST
- FastAPI
- API design
- OpenAPI
- authentication and authorization
- API testing
- webhooks
- performance testing
- API security

## PulseOps Application

PulseOps provides a real operational API rather than isolated examples.

Initial APIs include:

```text
POST /incidents
GET /incidents
GET /incidents/{incident_id}
```

The application will progressively add:

- authentication
- authorization
- OpenAPI documentation
- validation
- integration tests
- API security
- webhook/event interfaces
- performance testing

## Project Evidence

- FastAPI application
- OpenAPI contract
- Pydantic schemas
- pytest/httpx tests
- API security tests
- performance tests

## Relevant PulseOps Milestones

```text
P1 — Operational Data Foundation
Future API Engineering milestones
```

---

# Curriculum Phase 3 — AI-Augmented Engineering

## Learning Focus

- AI-assisted coding
- Claude Code
- AI-assisted testing
- AI-assisted troubleshooting
- AI-assisted documentation
- prompt engineering
- responsible AI
- agentic engineering concepts
- MCP
- workflow automation
- HITL

## PulseOps Application

PulseOps is itself developed using disciplined AI-assisted engineering.

The project demonstrates:

```text
AI Pair, Not AI Authority
```

AI assists with:

- implementation
- tests
- debugging
- documentation
- code review
- architecture exploration

The application itself progressively introduces:

```text
Ontology
   ↓
Knowledge Graph
   ↓
Context Engineering
   ↓
Retrieval Tools
   ↓
MCP
   ↓
Claude Agent SDK
   ↓
Incident Agent
   ↓
n8n
   ↓
Human-in-the-Loop
```

## Prompt Engineering

Create and maintain:

```text
PROMPTS.md
```

This will contain versioned prompts for:

- incident investigation
- evidence summarization
- hypothesis generation
- recommendation generation
- code investigation
- test generation
- documentation
- review

Prompts must be treated as engineering artifacts.

## Responsible AI

PulseOps must demonstrate:

- evidence vs hypothesis separation
- confidence/uncertainty
- prompt injection defense
- data minimization
- least privilege
- human approval for consequential actions
- auditability

## Project Evidence

- CLAUDE.md
- PROMPTS.md
- AI-assisted development history
- context-engineering layer
- ontology
- Neo4j graph
- retrieval tools
- MCP tools
- Incident Agent
- n8n workflow
- HITL gate
- evaluation suite

## Relevant PulseOps Milestones

```text
P0 — Foundation
P1 — Operational Data
P2 — Ontology + Knowledge Graph + Context
P3 — Retrieval Tools
P4 — MCP
P5 — Claude Agent SDK
P6 — Incident Agent
P7 — Workflow + HITL
P8 — Evaluation
```

---

# Curriculum Phase 4 — Modern Application Development

## Learning Focus

- enterprise application architecture
- backend development
- frontend development
- databases
- secure application development
- application integration
- testing
- production-oriented design

## PulseOps Application

PulseOps evolves from a backend prototype into a complete application.

Target architecture:

```text
React UI
   |
FastAPI
   |
Application Services
   |
+-----------------------+
|                       |
SQLite/PostgreSQL     Neo4j
|                       |
Operational Data      Semantic Graph
        \               /
         \             /
          Context Layer
               |
          Agent Layer
```

The application will progressively introduce:

- frontend UI
- authentication
- role-based access
- PostgreSQL migration path
- service boundaries
- secure API integration
- application observability
- production configuration

## Project Evidence

- frontend
- backend
- API contracts
- database layer
- security controls
- integration tests
- architecture decision records

## Relevant PulseOps Milestones

```text
Modern Application milestone
Production Application milestone
```

This work must occur after the semantic/agent foundation where appropriate;
curriculum delivery does not require every technical capability to be
implemented in the same chronological order as the learning modules.

> **Status (P9):** the frontend (React + Vite + TypeScript, three views), typed API contracts and error envelope, authentication
> and role-based access (Gates 9/9.1), service boundaries, application observability (`/health/ready`, access log) and tests are
> delivered; see `docs/phase-9.md`. The PostgreSQL migration path, SSO and production configuration belong to P10; end-to-end
> and release testing to P11. Architecture decision records are kept as the "Decisions" section of each phase document.

---

# Curriculum Phase 5 — Cloud & Platform Engineering

## Learning Focus

- AWS
- Docker
- Kubernetes
- cloud-native architecture
- infrastructure
- observability
- monitoring
- incident management
- deployment

## PulseOps Application

PulseOps is itself deployed as a cloud-native application.

Target progression:

```text
Local
  |
Docker
  |
Containerized Application
  |
AWS
  |
Kubernetes
  |
Observability
  |
Production Incident Intelligence
```

The platform layer should eventually include:

- container images
- deployment configuration
- cloud infrastructure
- secrets management
- logging
- metrics
- tracing
- health checks
- monitoring
- incident workflows

## Project Evidence

- Dockerfile
- Docker Compose
- Kubernetes manifests/Helm where appropriate
- Terraform/IaC
- CI/CD
- cloud deployment
- monitoring dashboards
- observability configuration

## Relevant PulseOps Milestones

```text
Cloud Platform
Production Deployment
Observability
```

---

# Curriculum Phase 6 — Quality Engineering

## Learning Focus

- testing fundamentals
- test automation
- API testing
- UI testing
- CI/CD quality gates
- performance testing
- security testing
- AI-assisted QA
- infrastructure validation

## PulseOps Application

Quality Engineering becomes a first-class layer.

Target quality pipeline:

```text
Code
 |
Lint
 |
Unit Tests
 |
Integration Tests
 |
API Tests
 |
E2E Tests
 |
Security Tests
 |
Performance Tests
 |
AI Evaluation
 |
Quality Gates
 |
Deployment
```

AI-assisted QA will include:

- test generation
- test review
- failure diagnosis
- test maintenance
- coverage analysis
- regression analysis

## Project Evidence

- pytest suite
- API tests
- UI/E2E tests
- performance tests
- security tests
- CI quality gates
- AI evaluation tests
- regression suite

> **Status (P11):** every item above now has repository evidence: the pytest suite with ratcheted coverage, API contract and
> reliability tests, the Playwright browser E2E, the local performance smoke, security tests with Bandit, dependency and secret
> scanning, the AI evaluation replays, the CI quality gates and a one-command local gate (`python scripts/quality_gate.py`).
> See `docs/phase-11.md` and `docs/release-checklist.md`. Cloud and platform engineering (curriculum Phase 5) was intentionally
> skipped (P10) and is not claimed here.

---

# Common Capstone — PulseOps v1.0

The final integrated project should demonstrate all curriculum phases.

## Application

PulseOps — AI Incident Intelligence Platform.

## Core User Journey

```text
Incident Created
      |
      v
Incident Context
      |
      v
Ontology / Knowledge Graph
      |
      v
Evidence Retrieval
      |
      v
AI Investigation
      |
      v
Hypotheses
      |
      v
Recommendations
      |
      v
Human Review
      |
      v
Approved Action / Follow-up
```

## Complete Engineering Stack

```text
Git / GitHub
     |
FastAPI
     |
React
     |
Operational Database
     |
Neo4j
     |
Ontology
     |
Context Engineering
     |
Retrieval
     |
MCP
     |
Claude Agent SDK
     |
Incident Agent
     |
n8n
     |
HITL
     |
AWS / Docker / Kubernetes
     |
Observability
     |
CI/CD
     |
Quality Engineering
```

---

# Curriculum-to-Project Traceability

| Curriculum phase | Primary PulseOps capability | Evidence |
|---|---|---|
| Phase 1 — Engineering Foundations | Engineering workflow | Git, Docker, documentation |
| Phase 2 — API Engineering | Operational API | FastAPI, OpenAPI, tests |
| Phase 3 — AI-Augmented Engineering | AI-assisted development + agentic system | Claude Code, prompts, tools, MCP, Agent SDK, HITL |
| Phase 4 — Modern Application Development | Full-stack application | React, FastAPI, DB, security |
| Phase 5 — Cloud & Platform | Cloud-native operation | AWS, containers, Kubernetes, observability |
| Phase 6 — Quality Engineering | End-to-end quality system | Unit/API/E2E/performance/security/AI evaluation |
| Capstone | PulseOps v1.0 | Complete integrated system |

---

# Technical Milestone Mapping

The technical implementation sequence is intentionally different from the
curriculum numbering.

```text
P0  Foundation
 |
P1  Operational Data
 |
P2  Ontology + Knowledge Graph + Context Engineering
 |
P3  Retrieval Tools
 |
P4  MCP
 |
P5  Claude Agent SDK
 |
P6  Incident Agent
 |
P7  Workflow + HITL
 |
P8  Evaluation
 |
P9  Modern Application
 |
P10 Cloud + Platform
 |
P11 Quality Engineering
 |
P12 PulseOps v1.0 Capstone
```

These milestones are implementation boundaries, not curriculum phases.

---

# 90-Minute Marketing Workshop

The 90-minute workshop is a compressed demonstration of the complete
learning journey.

It is not the complete curriculum.

The workshop should demonstrate the progression:

```text
AI-Assisted Development
        |
        v
Context Engineering
        |
        v
Ontology + Knowledge Graph
        |
        v
Retrieval
        |
        v
Agent
        |
        v
Human-in-the-Loop
```

The full curriculum provides the engineering depth required to build the
complete system.

---

# Commercial Product Structure

The master curriculum remains the complete 192-hour engineering program.

The 90-minute workshop acts as the discovery/marketing experience.

The same underlying curriculum can later be packaged into smaller
commercial programs without changing the master project.

Potential derived programs include:

- AI-Augmented Software Engineering
- AI-Assisted Application Engineering
- Agentic AI Engineering
- Cloud-Native AI Engineering
- AI-Powered Quality Engineering
- Complete AI Engineering Apprenticeship

PulseOps remains the integrated project and common technical narrative.

---

# Source-of-Truth Rule

The curriculum documents define what learners must learn.

PulseOps architecture documents define how the project is engineered.

The two must remain traceable but should not be duplicated.

```text
Curriculum
    = learning requirements

PulseOps
    = implementation vehicle

Curriculum Alignment
    = traceability between them
```

Changes to the curriculum should be reflected here before changing the
implementation roadmap.

Changes to the PulseOps architecture should not automatically change the
curriculum sequence.

---

# Definition of Alignment

The project is curriculum-aligned when every major curriculum competency
has at least one corresponding:

- PulseOps capability
- project artifact
- hands-on exercise
- test/evaluation
- or capstone demonstration

No curriculum phase should be considered complete merely because the
corresponding technology has been introduced.

Learners must demonstrate the competency through the project.
