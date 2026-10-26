Read docs/phase-5a.md, docs/phase-5c.md, and the current implementation of app/agent/service.py.

Do not modify any files.
Run the live smoke test again, but explicitly call python-dotenv load_dotenv() before importing or instantiating IncidentInvestigationAgent.

I have now verified that:
- ANTHROPIC_API_KEY is loaded from .env
- CLAUDE_MODEL is set to claude-sonnet-5

Perform ONE live smoke test of the current Claude Agent SDK implementation.

Requirements:
1. Use the existing IncidentInvestigationAgent entry point.
2. Use the existing seeded PulseOps incident data.
3. Use the Claude Agent SDK, not direct anthropic.messages.create().
4. Use the existing PulseOps MCP server.
5. Use the existing four retrieval tools:
   - get_incident_context
   - get_related_incidents
   - get_service_repository
   - get_service_dependencies
6. Do not modify source files, tests, configuration, or documentation.
7. Do not print, expose, or log ANTHROPIC_API_KEY.
8. Keep max_turns low to minimize API usage.
9. Capture actual ToolUseBlock/tool-call events from the SDK rather than inferring tool calls from the final text.
10. Report:
    - whether Claude authentication succeeded
    - incident ID used
    - actual MCP tools called
    - whether InvestigationResult validation succeeded
    - confidence
    - any error
11. Clearly report PASS or FAIL at the end.

This is a LIVE API smoke test. Do not replace it with a mocked test.