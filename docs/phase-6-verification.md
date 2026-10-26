Phase 6 implementation is complete.

Do NOT modify any code yet.

I want you to perform a post-implementation review of Phase 6.

Important project context:
- The original plan.md was intentionally renamed to project-plan.md.
- project-plan.md is the master project plan and should be treated as the equivalent of the original plan.md.
- Do not rename it back.
- Do not create another plan.md.
- phase-6.md is the Phase 6 implementation specification.

Please review the implementation against docs/phase-6.md and the project context.

Inspect:
1. project-plan.md
2. CLAUDE.md
3. docs/phase-6.md
4. PROMPTS.md
5. app/agent/service.py
6. app/agent/prompts.py, if present
7. all Phase 6-related tests
8. the existing Phase 5 implementation
9. the MCP implementation
10. the current git/repository state

Do NOT change any files.

Evaluate the implementation against every Phase 6 acceptance criterion.

Specifically verify:

1. Incident investigation flow
   - incident + objective
   - context retrieval
   - related incidents
   - service dependencies
   - repository information
   - evidence correlation
   - hypotheses
   - missing information
   - recommendations
   - confidence

2. MCP/tool boundaries
   - only the four approved PulseOps retrieval tools are available
   - no direct SQLite access by the agent
   - no direct Neo4j access by the agent
   - no arbitrary SQL/Cypher
   - no shell/filesystem access
   - no GitHub/external API access
   - no autonomous remediation

3. Tool-call auditing
   - tool calls are captured from actual SDK ToolUseBlock events
   - model-generated text is not treated as authoritative tool-call evidence
   - tool failures are detected correctly

4. Evidence safety
   - evidence is separated from hypotheses
   - missing information is explicitly represented
   - the agent never fabricates evidence
   - conflicting evidence is preserved
   - confidence is constrained to 0.0–1.0

5. Failure handling
   - unknown incident
   - MCP/tool failure
   - malformed model output
   - unavailable evidence
   - unauthorized tool use
   - conflicting evidence

6. Prompt-injection resistance
   - operational data is treated as untrusted
   - instructions embedded inside logs/incidents/evidence cannot override the system prompt
   - no unsafe action is taken because of operational-data instructions

7. Structured output
   - Claude Agent SDK structured output is used
   - InvestigationResult is validated through Pydantic
   - malformed output is handled safely

8. Prompt management
   - PROMPTS.md exists
   - the investigation prompt is versioned
   - runtime prompt and documented prompt are consistent

9. Security
   - allow-list behavior is enforced
   - disallowed Claude Code tools remain blocked
   - fail-closed behavior is preserved

10. Observability
   - investigation execution can be traced
   - tool usage is recorded
   - failures are recorded
   - no secrets are logged

11. Tests
   - identify exactly which Phase 6 acceptance criteria have deterministic tests
   - identify any acceptance criterion that is only indirectly tested
   - identify any missing test

12. Live verification
   - determine whether a real Claude Agent SDK investigation was actually executed
   - distinguish deterministic tests from live API verification
   - do not count a mocked test as live verification

Also verify the current test result independently if practical.

IMPORTANT:
Do not make any changes.
Do not refactor.
Do not "fix" anything yet.

Return a structured report with exactly these sections:

1. PHASE 6 STATUS
   - COMPLETE / COMPLETE WITH GAPS / NOT COMPLETE
   - concise explanation

2. ACCEPTANCE CRITERIA
   - table with:
     Criterion | Status | Evidence

3. FILES CHANGED
   - list the files changed for Phase 6
   - explain the purpose of each

4. TEST COVERAGE
   - tests added/modified
   - total test result
   - missing tests, if any

5. LIVE VERIFICATION
   - whether a real Claude Agent SDK investigation was executed
   - result
   - distinguish it from deterministic tests

6. GAPS OR RISKS
   - only concrete issues
   - do not invent issues

7. RECOMMENDATION
   - state whether Phase 6 is ready to proceed to Phase 7
   - if not, list the specific changes required

Do not implement any fixes until I explicitly approve them.