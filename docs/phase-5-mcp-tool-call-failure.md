The live smoke test now confirms:

- .env loading: PASS
- Anthropic API authentication: PASS
- Claude Agent SDK connection: PASS
- Claude returned a response: PASS
- Actual MCP tool calls: NONE
- InvestigationResult validation: FAIL
- Error: ValueError - Claude returned malformed JSON

Do not move to Memory yet.

Do not modify source files yet.

Read:
- docs/phase-5a.md
- docs/phase-5c.md
- docs/phase-5-smoke-test.md
- docs/agent-architecture.md
- app/agent/service.py
- app/mcp/server.py

Now diagnose the live failure only.

I need you to determine:

1. Did Claude Agent SDK actually receive the four PulseOps MCP tools?
2. What exact tool names were exposed to the SDK?
3. Why did the model make zero MCP tool calls for INC-1007?
4. Did max_turns=2 prevent the agent from completing a tool-call → tool-result → final-response cycle?
5. What exact model response caused the malformed JSON error?
   Do NOT print the API key or any secret.
6. Is the current structured-output mechanism relying only on json.loads() of model text?
7. Does the installed Claude Agent SDK provide a better structured-output mechanism that we should use instead?
8. Does the current implementation correctly capture ToolUseBlock events?
9. Propose the smallest architectural correction required.

Do NOT modify any files.

Do NOT run multiple paid API investigations.

At the end give me:

DIAGNOSIS
ROOT CAUSE
RECOMMENDED FIX
FILES THAT WOULD NEED TO CHANGE
WHY THE FIX PRESERVES THE Phase 5 architecture