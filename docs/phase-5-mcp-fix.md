Implement the minimal Phase 5 correction based on the diagnosis in
phase-5-mcp-tool-call-failure.md.

Read:
- docs/phase-5a.md
- docs/phase-5c.md
- docs/phase-5-smoke-test.md
- docs/agent-architecture.md
- app/agent/service.py
- app/mcp/server.py
- tests/test_phase5.py

Also inspect the installed claude-agent-sdk version and its actual
ClaudeAgentOptions / ResultMessage API before modifying the code.

Objective:

Fix the live Claude Agent SDK structured-output and tool-use path.

Requirements:

1. Continue using the official Claude Agent SDK:
   - ClaudeAgentOptions
   - ClaudeSDKClient

2. Continue using the existing PulseOps MCP server.

3. Keep exactly these four allowed MCP tools:
   - get_incident_context
   - get_related_incidents
   - get_service_repository
   - get_service_dependencies

4. Do NOT reintroduce:
   - anthropic.Anthropic
   - messages.create()
   - manual MCP ClientSession orchestration
   - direct SQLite access from the agent
   - direct Neo4j access from the agent

5. Replace the current fragile text-only JSON parsing as the primary
   structured-output mechanism.

6. Use the SDK-native structured-output mechanism supported by the
   installed SDK:
   - ClaudeAgentOptions.output_format
   - ResultMessage.structured_output

7. Define the structured output contract from the existing
   InvestigationResult model. Do not create a second conflicting
   result schema.

8. Validate the structured output through InvestigationResult/Pydantic
   before returning it.

9. Keep text parsing only as a clearly documented last-resort fallback,
   if appropriate. Do not silently accept arbitrary prose as a valid
   InvestigationResult.

10. Increase the default Claude max_turns from the current smoke-test
    value of 2 to a reasonable small value for an actual investigation.
    Use 6 unless the installed SDK/documentation indicates a better
    value.

11. Preserve actual ToolUseBlock capture from AssistantMessage.content.

12. Do not fabricate tool_calls from the final model response.
    tool_calls must represent actual observed SDK ToolUseBlock events.

13. Keep the agent read-only:
    - no Bash
    - no Edit
    - no Write
    - no Read
    - no Grep
    - no Glob
    - no remediation

14. Do not implement Memory.
15. Do not implement GitHub.
16. Do not implement n8n.
17. Do not add authorization or tenant-memory behavior yet.

Testing:

- Update tests/test_phase5.py to verify the new structured-output path.
- Add a deterministic test proving structured_output is preferred over
  textual ResultMessage.result.
- Add/retain a test proving actual ToolUseBlock events are captured.
- Test malformed structured output is rejected by validation.
- Run the complete test suite.

IMPORTANT:
Do not perform another paid live API investigation yet.

First make the code changes and run all deterministic tests.

At the end report:
1. Files changed
2. Exact SDK structured-output mechanism used
3. New max_turns value
4. Tests added/updated
5. Full pytest result
6. Whether any live API call was made
7. Whether the repository is ready for one final live smoke test

Do not expose ANTHROPIC_API_KEY.