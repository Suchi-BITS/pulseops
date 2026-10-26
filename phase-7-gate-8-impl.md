Gate 8 — APPROVED. Proceed with implementation.

I approve the Gate 8 Implementation Plan with these decisions:

1. Database resolver:
   YES — change the default database behavior so sqlite:///./pulseops.db is resolved relative to the project/current working directory rather than incorrectly resolving to the filesystem root on Linux.

   Existing D:\pulseops.db data does not need to be automatically migrated or preserved.
   Do not delete the existing D:\pulseops*.db files.

2. Environment variable:
   Use PULSEOPS_DATABASE_URL.

   The application and MCP subprocess must use the same resolved database URL.
   Ensure relative SQLite URLs are resolved consistently and the MCP subprocess receives an absolute SQLite URL so its working directory cannot change the database location.

3. Ungrounded results:
   YES — remove model-supplied recommendations from ungrounded results.

   Also remove model-supplied missing_information from an ungrounded result.
   Only system-authored required next steps / missing information may remain.

   Add/update tests so this behavior is explicitly enforced.

4. Investigation outcome:
   YES, use the following contract:

   COMPLETED:
   The investigation obtained sufficient grounded evidence to produce a valid investigation result.

   DEGRADED:
   The investigation could not establish sufficient grounded context to support the result.

   FAILED:
   The investigation itself failed due to an execution/system error.

   A partial tool failure may remain COMPLETED only when the remaining successful evidence is sufficient to produce a grounded result. If grounding is insufficient, the result must be DEGRADED.

   DEGRADED and FAILED must both fail closed.
   Neither may be approved or treated as a successfully completed investigation.

5. Failure policy semantics:
   YES — do not overload the policy decision DENY for investigation/system failure.

   Use the proposed non-policy values:
   investigation_pending
   investigation_degraded
   investigation_failed

   DENY must remain a genuine deterministic policy decision.

   Preserve the existing rejected/final-state behavior so DEGRADED and FAILED workflows cannot be approved.

6. Documentation:
   YES — fix the stale CLAUDE.md reference from plan.md to project-plan.md.

   YES — once ci.yml exists, make the existing evals.yml manual-only to avoid duplicate automatic execution.

Additional implementation constraints:

- Follow the approved Gate 8 scope exactly.
- Do not implement Gate 9.
- Do not add authentication or RBAC.
- Do not add PostgreSQL.
- Do not add cloud deployment.
- Do not implement real Neo4j runtime integration.
- Do not add RAGAS, DeepEval, or an LLM judge.
- Do not add a frontend.
- Do not add autonomous remediation.
- Do not add Slack/GitHub/AWS/Kubernetes integration.
- Do not introduce vector databases or embeddings.
- Do not perform a major refactor.

Implementation order:

1. Database resolver/env configuration and test DB isolation.
2. MCP subprocess database propagation.
3. Ungrounded-result hardening.
4. Investigation outcome/status/failure-reason changes.
5. Evaluation dataset v2.
6. Retrieval ground truth and retrieval_correctness metric.
7. Tool-selection metric.
8. Latency reporting.
9. Dataset content hashing and baseline v2.
10. Full Linux CI.
11. Documentation reconciliation.
12. Final verification.

Testing requirements:

- Run focused tests after each logical change.
- Preserve all existing tests unless their expected behavior legitimately changes because of the approved Gate 8 contract.
- Run the complete Windows test suite.
- Run the complete suite in a Python 3.11 Linux container as a non-root user.
- Run the Gate 7 replay.
- Verify the negative control still fails correctly.
- Verify dataset tampering causes hash failure.
- Verify n8n manually for:
  - LOW
  - HITL
  - DENY
  - DEGRADED
  - FAILED
- Verify DEGRADED and FAILED cannot be approved.
- Verify no ungrounded model recommendation survives.
- Verify no system failure is represented as policy DENY.
- Verify the MCP subprocess uses the same configured database.
- Verify the full suite and replay run in CI without secrets.

Important:
Do not delete or rename project-plan.md.md during this gate.
Do not delete the existing D:\pulseops*.db files.
Do not modify unrelated P5/P6/P7 behavior.

At the end, provide:

1. Files changed
2. Exact behavior changes
3. Tests added/changed
4. Full Windows test result
5. Full Linux test result
6. Replay result
7. Negative-control result
8. Manual n8n verification result
9. CI result
10. Any remaining known limitations
11. Gate 8 acceptance checklist

Proceed with implementation now. Stop only after Gate 8 implementation and verification are complete.