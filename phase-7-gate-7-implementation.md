Gate 7 architecture review is APPROVED with the following modifications.

Implement Gate 7 — Evaluation & Reliability.

Important scope boundary:

Gate 7 is the evaluation harness over the existing PulseOps Incident Agent.

The broader Phase 8 evaluation scope remains deferred.

Do NOT modify the production decision architecture.
Do NOT modify the Gate 6 event workflow.
Do NOT modify P5 or P6 behavior unless a strictly necessary compatibility fix is identified and explicitly reported.
Do NOT add RAGAS, DeepEval, an LLM-as-judge, a human review UI, human feedback loops, vector databases, embeddings, multi-agent architecture, cloud deployment, or autonomous remediation.

Before editing:
- inspect the approved Gate 7 review/plan
- inspect CLAUDE.md
- inspect project-plan.md
- inspect Phase 6 agent implementation
- inspect existing tests and reusable scripted SDK utilities
- inspect Gate 6 implementation
- inspect pyproject.toml

Implement the following.

1. Create an evaluation-only `evals/` package.

Production `app/` code must never import `evals/`.

The dependency direction must be:

    evals → app

and never:

    app → evals

2. Create a golden evaluation dataset containing exactly 12 cases covering:

- normal incident
- error-rate spike
- latency/dependency issue
- failed deployment
- missing metric
- missing deployment information
- conflicting evidence
- unknown incident
- MCP/tool timeout
- malformed/invalid agent output
- prompt injection in operational data
- policy-boundary manipulation

Keep evaluation fixtures separate from production seed data.

Do not modify app/data/seed.py merely to create evaluation cases.

3. Create evaluation contracts.

Include appropriate Pydantic models for:

- GoldenCase
- CaseScore
- EvalReport

The report must distinguish:

A. System correctness/safety
- evidence grounding
- fabrication detection
- tool boundary
- policy boundary
- failure behavior
- injection resistance
- field separation

B. AI quality
- expected evidence recall
- relevance
- completeness
- hypothesis quality where appropriate

Do NOT collapse these into a misleading single overall score.

4. Implement deterministic scorers.

Evidence grounding:
- every evidence item must correspond to retrieved tool evidence.

Expected evidence recall:
- calculate the proportion of required expected evidence present.

Fabrication detection:
- check unsupported identifiers, source references, operational values, and action claims in summary, hypotheses, and recommendations.
- Do not claim that this detects every form of semantic hallucination.
- Document the exact boundary of this scorer.

Relevance:
- use the acceptable-cause rubric defined by each golden case.
- Keep the rubric deterministic and transparent.

Completeness:
- verify required missing information.
- verify confidence bounds where defined.

Field separation:
- evidence, hypotheses, recommendations and missing information must remain semantically separated.
- reject completed-action language such as "restarted", "deployed", etc. when the agent has not actually performed such actions.

Injection resistance:
- verify that injected operational text is treated as data/evidence, not as instructions.
- verify tool allowlist compliance.
- verify no unauthorized tool attempts.

Policy-boundary compliance:
- evaluate through the existing Gate 6 `/workflow/events` path using controlled/stubbed investigation behavior where appropriate.
- verify that the deterministic policy decision is unchanged regardless of investigation content.
- verify ALLOW, NOTIFY, HITL_REQUIRED and DENY behavior.

Failure behavior:
- unknown incident
- tool timeout
- MCP unavailable
- malformed structured output
- wrong incident ID
must fail closed and must never generate fabricated evidence.

5. Implement replay evaluation.

Reuse the existing scripted SDK client and other existing test helpers where appropriate.

Replay mode must:
- use the real PulseOps agent code
- use controlled scripted SDK messages
- use temporary evaluation databases
- require no ANTHROPIC_API_KEY
- be deterministic
- be suitable for CI

Clearly label replay results as agent-validation results, not real model-quality measurements.

6. Implement optional live evaluation.

Create a separate live runner.

Live mode:
- runs only when ANTHROPIC_API_KEY is available
- otherwise reports SKIPPED, not FAILED
- uses a configurable model
- has a configurable case limit
- must clearly report that live model quality was or was not measured
- must not affect production policy or workflow decisions

Do not add live evaluation to the default CI job.

7. Implement baseline regression.

Create:

evals/baselines/baseline.json

The baseline must be explicit and versioned.

Do not silently regenerate or overwrite the baseline.

Compare current replay results with the baseline.

A configured regression threshold should cause a non-zero evaluation exit code when a protected metric regresses beyond the threshold.

8. Implement reporting.

Generate:
- machine-readable JSON
- human-readable Markdown

The report must include:
- run_id
- timestamp
- mode
- model if applicable
- prompt/version identifier if available
- case count
- per-case results
- metric aggregates
- system correctness/safety results
- AI quality results
- skipped live evaluation status where applicable
- regression results

Make the replay/live distinction impossible to miss.

9. Add pytest coverage for the evaluation framework.

Test:
- every scorer with positive and negative examples
- fabricated identifiers
- unsupported operational values
- action-claim recommendations
- over-confidence
- prompt injection
- unauthorized tools
- policy manipulation
- failure modes
- baseline regression detection
- replay execution
- negative control proving that the harness can actually fail

10. Add a minimal GitHub Actions evaluation workflow.

It should:
- install dependencies
- run the replay evaluation/tests
- require no secrets
- require no live Claude
- fail when evaluation thresholds fail

Do not add deployment or cloud functionality.

11. Documentation.

Create/update the Gate 7 documentation.

Clearly document:

- purpose
- architecture
- golden dataset
- evaluation categories
- deterministic vs AI-quality metrics
- replay vs live mode
- baseline management
- CI behavior
- known limitations
- why RAGAS/DeepEval/LLM-as-judge are intentionally deferred
- why replay does not measure real Claude model quality
- fabrication scorer limitations
- future Phase 8 scope

12. Preserve the existing architecture.

The production flow must remain:

Incident
→ Phase 6 Incident Agent
→ InvestigationResult
→ deterministic policy
→ workflow/HITL

Evaluation must remain observational:

Incident/Test Case
→ Agent
→ InvestigationResult
→ Evaluation Harness
→ Report

Evaluation scores must NEVER feed into policy, approval, or production workflow decisions.

Testing requirements:

- Run focused Gate 7 tests first.
- Then run the complete project test suite.
- Do not stop at focused tests.
- Report exact test counts.
- Verify no Gate 6 regressions.
- Do not delete existing dev data.
- Do not modify secrets.
- Do not introduce a new virtual environment.

At the end:
1. summarize files changed
2. summarize architecture
3. summarize evaluation metrics
4. summarize limitations
5. provide focused test result
6. provide full suite result
7. provide CI result
8. provide git status/diff if available

Stop after Gate 7.

Do not start Gate 8 or any later phase.