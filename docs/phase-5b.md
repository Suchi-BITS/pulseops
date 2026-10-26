Do not modify any files.

Review the current Phase 5A implementation in app/agent/service.py
against the installed Claude Agent SDK version.

Verify specifically:

1. What are the actual MCP tool names exposed to Claude when the
   server is registered as "pulseops"?

2. Does:
       allowed_tools=[
           "get_incident_context",
           ...
       ]
   correctly authorize the MCP tools?

3. If the SDK requires names such as:
       mcp__pulseops__get_incident_context
   report that explicitly.

4. Verify whether tools=[] together with allowed_tools is correct
   for this SDK version.

5. Determine whether the current implementation can reliably capture
   actual MCP tool invocations from SDK messages/events, rather than
   relying on Claude returning a "tool_calls" field in its JSON.

6. Verify whether ClaudeSDKClient + the current MCP stdio configuration
   actually allows Claude to invoke the four PulseOps tools.

7. Review the structured JSON parsing and identify whether malformed
   model output is silently accepted.

8. Review the asyncio.run() wrapper and determine whether it is safe
   with the existing FastAPI endpoint.

9. Confirm that the current implementation does NOT implement:
   semantic memory
   procedural memory
   episodic memory
   persistent memory
   Neo4j memory
   tenant/user memory isolation.

10. Do not change anything.

Give me only:
- VERIFIED
- ISSUES FOUND
- RECOMMENDED CHANGES

Do not implement the recommended changes yet.