Implement only the following Phase 5 corrections identified during
the architecture verification.

Do not implement Phase 5B memory.
Do not implement semantic memory.
Do not implement procedural memory.
Do not implement episodic memory.
Do not implement Neo4j memory.
Do not implement tenant/user memory isolation.

1. Remove the asyncio.run() wrapper from the agent service.

Make IncidentInvestigationAgent fully async so the existing async
FastAPI endpoint can call it safely.

The intended flow is:

    FastAPI async endpoint
        ↓
    await agent.investigate(...)
        ↓
    ClaudeSDKClient
        ↓
    Claude
        ↓
    MCP

Do not introduce nested event loops.

2. Replace the current tool_calls inference.

Do not rely on Claude returning a "tool_calls" field in its JSON.

Inspect the actual Claude Agent SDK message blocks, including
ToolUseBlock and ToolResultBlock where available.

Capture the actual tools invoked during the SDK session.

The resulting InvestigationResult.tool_calls must represent actual
SDK-observed tool invocations.

3. Verify the runtime MCP tool names.

Do not assume that the names in MCP_TOOL_NAMES are necessarily the
runtime names surfaced to Claude.

Use the installed SDK/runtime behavior to determine the actual tool
names exposed by the registered "pulseops" MCP server.

Do not change names unnecessarily.

If the current names are correct, keep them.

If names need to be namespaced, update the configuration and tests
consistently.

4. Strengthen structured-output validation.

The final Claude response must be validated against
InvestigationResult.

Do not silently convert malformed or partial JSON into a successful
InvestigationResult.

If the model response is malformed, return an explicit validation
failure rather than pretending the investigation succeeded.

Do not fabricate evidence, confidence, or tool calls.

5. Preserve the existing read-only security boundary.

The agent must remain restricted to the approved PulseOps MCP
retrieval tools.

Do not add:
- Bash
- Edit
- Write
- arbitrary SQL
- arbitrary Cypher
- GitHub
- remediation
- production actions

6. Keep IdentityContext as a placeholder only.

Do not implement authorization or memory yet.

7. Update tests.

Add/update tests for:

- async agent invocation
- actual SDK message parsing
- ToolUseBlock/ToolResultBlock handling
- malformed final output
- MCP tool-name configuration
- existing read-only restrictions

Keep normal tests deterministic and free of live Anthropic API calls.

8. Run:

    pytest -q

9. Review the final diff.

Do not modify unrelated files.

At the end, report:

- files changed
- tests passed
- actual MCP tool-name behavior
- how actual tool calls are captured
- confirmation that no memory was implemented

Stop after these corrections.