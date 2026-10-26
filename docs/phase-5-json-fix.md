Do NOT run any live API calls.

We have identified the likely root cause of the structured-output failure.

The current implementation uses:

output_format=self._structured_output_schema()

where _structured_output_schema() returns InvestigationResult.model_json_schema().

The Claude Agent SDK expects the output_format contract in the form:

{
    "type": "json_schema",
    "schema": <JSON schema>
}

Anthropic's current Claude Agent SDK examples use:
output_format={"type": "json_schema", "schema": schema}

Implement this correction.

Requirements:

1. Read the current:
   - app/agent/service.py
   - tests/test_phase5.py
   - docs/phase-5a.md
   - docs/phase-5c.md

2. Change ClaudeAgentOptions so output_format is:
   
   {
       "type": "json_schema",
       "schema": InvestigationResult.model_json_schema(),
   }

3. Keep the existing InvestigationResult model as the single application
   output contract.

4. Keep reading ResultMessage.structured_output as the primary result.

5. Keep ToolUseBlock capture unchanged.

6. Keep the four MCP tools unchanged:
   - get_incident_context
   - get_related_incidents
   - get_service_repository
   - get_service_dependencies

7. Keep max_turns=6.

8. Keep the read-only tool boundary.

9. Do not introduce:
   - direct Anthropic Messages API
   - manual MCP ClientSession
   - memory
   - GitHub
   - n8n
   - remediation
   - new tools

10. Update deterministic tests to verify the exact output_format structure:
    
    output_format["type"] == "json_schema"
    output_format["schema"] == InvestigationResult.model_json_schema()

11. Keep the existing test that structured_output takes precedence
    over ResultMessage.result.

12. Run the full pytest suite.

13. Do NOT make a live API call.

At the end report:
- files changed
- exact output_format structure
- tests added/updated
- pytest result
- confirmation that no live API call was made