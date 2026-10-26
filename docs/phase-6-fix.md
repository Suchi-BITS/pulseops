The Phase 6 verification review is complete.

I approve fixing the concrete Phase 6 gaps identified in the verification report.

Before changing code:
1. Re-read docs/phase-6-verification.md.
2. Re-read docs/phase-6.md.
3. Re-read CLAUDE.md.
4. Re-read project-plan.md.
5. Inspect the current Phase 6 implementation and tests.
6. Do not rewrite working Phase 5 infrastructure unnecessarily.

Implement ONLY the following Phase 6 corrections.

==================================================
1. FIX THE GROUNDING GAP
==================================================

The verification found that the current implementation can treat a ToolUseBlock for get_incident_context as sufficient evidence of retrieval, even when there is no matching successful ToolResultBlock.

Fix this.

A context investigation must be considered grounded only when:

- the approved context tool was actually invoked;
- a matching ToolResultBlock is received;
- the tool result is successful;
- the tool result contains usable incident evidence.

A ToolUseBlock alone must NEVER establish grounding.

If the context tool:
- fails,
- times out,
- returns an error,
- returns empty/unusable evidence,
- or never produces a matching ToolResultBlock,

the investigation must fail closed.

The resulting InvestigationResult should not contain fabricated evidence or hypotheses.

Use the existing InvestigationResult contract unless a change is absolutely necessary.

==================================================
2. PREVENT UNSUPPORTED MODEL CLAIMS
==================================================

The verification identified that model-generated evidence is currently accepted without sufficient provenance checking.

Strengthen the implementation so that:

- model output cannot manufacture evidence;
- evidence must be grounded in the successful retrieval result;
- if no usable evidence was retrieved, evidence=[] and hypotheses=[] unless the existing contract explicitly allows a safe non-evidentiary statement;
- unsupported claims must not be presented as observed facts.

Do not build a sophisticated semantic fact-verification engine.

Implement the minimum deterministic provenance/grounding boundary required by Phase 6.

Preserve the distinction:

Evidence = observed facts returned by PulseOps tools
Hypothesis = interpretation based on evidence
Missing information = useful information that was unavailable
Recommendation = suggested next step

==================================================
3. ADD DETERMINISTIC TESTS
==================================================

Add tests for at least:

A. ToolUseBlock without matching ToolResultBlock
   -> investigation is not grounded

B. ToolResultBlock with an error
   -> investigation fails safely

C. Successful context ToolResultBlock containing empty/unusable evidence
   -> no fabricated evidence or hypotheses

D. Model returns evidence when context retrieval failed
   -> model evidence is rejected/not trusted

E. Successful context retrieval followed by a model response
   -> grounded evidence is preserved

F. Existing unknown-incident behavior remains correct

G. Existing prompt-injection protection remains correct

H. Existing unauthorized-tool behavior remains correct

Do not weaken or remove existing tests.

Run the complete test suite.

==================================================
4. RECONCILE THE PROJECT ROADMAP DOCUMENTATION
==================================================

There is a documentation mismatch between project-plan.md and the current phase documents.

Current implementation sequence is:

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

The current project-plan.md apparently uses different Phase 6/7 labels.

Update ONLY the relevant roadmap wording in project-plan.md so that it matches the current implementation roadmap above.

Do NOT rename phase documents.
Do NOT create plan.md.
project-plan.md is intentionally the master project plan.

==================================================
5. DO NOT CHANGE THESE
==================================================

Do NOT implement:

- n8n
- Slack
- HITL
- notifications
- automated remediation
- GitHub integration
- React UI
- authentication UI
- RBAC UI
- AWS
- Kubernetes
- Terraform
- Postgres
- vector database
- embeddings
- multi-agent architecture
- Phase 7 functionality

Do NOT initialize Git merely to satisfy the verification report.

Do NOT change the database location as part of this task.

Do NOT change the existing Claude Agent SDK architecture unless required for the grounding fix.

==================================================
6. LIVE VERIFICATION
==================================================

After the deterministic tests pass, prepare for the required live verification.

Do not claim live verification has succeeded unless an actual Claude Agent SDK API call is executed.

Use the existing tests/test_live_smoketest.py or the existing approved live verification mechanism.

Before running the live test:
- verify the API key is loaded from the existing environment;
- do not print or expose the API key;
- use the existing configured model;
- use seeded incident INC-1007;
- perform a real incident investigation;
- verify that MCP tools are actually invoked;
- verify that the final InvestigationResult is structured and validated.

If the live test fails because of environment/authentication/network/API availability, report that clearly rather than changing unrelated project code.

==================================================
7. FINAL REPORT
==================================================

At the end provide:

1. Files changed
2. Exact grounding fix implemented
3. Tests added/modified
4. Complete test result
5. Roadmap documentation change
6. Live verification result
7. Any remaining issues
8. Whether Phase 6 is now COMPLETE

Important:
Do not start Phase 7.

Do not make additional improvements outside these requested corrections.