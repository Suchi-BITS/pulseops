Read docs/phase-5.md and the Phase 5 gap analysis above.

Proceed with implementing Phase 5.

Before modifying code:

1. Inspect the current repository and existing Phase 0–4 implementation.
2. Inspect the installed/available claude-agent-sdk package and its current API.
3. Verify the exact APIs for:
   - ClaudeAgentOptions
   - ClaudeSDKClient
   - MCP server configuration
   - allowed_tools
   - disallowed_tools
   - max_turns
   - message/response handling
4. Do not assume an API from an older SDK example.

Implementation requirements:

1. Replace the current manual MCP ClientSession orchestration in
   app/agent/service.py.

2. Remove the direct Anthropic Messages API path:
       from anthropic import Anthropic
       client.messages.create(...)

3. Use the official claude-agent-sdk package.

4. Use ClaudeSDKClient as the primary PulseOps agent interface.

5. Use ClaudeAgentOptions for:
   - model
   - MCP server configuration
   - allowed tool configuration
   - disallowed tool configuration where appropriate
   - max_turns
   - system prompt

6. Reuse the existing PulseOps MCP server from Phase 4.

7. Do NOT duplicate the retrieval logic inside the agent.

8. Do NOT manually invoke all four MCP tools from Python.

9. Claude must be able to decide which MCP tools to invoke.

10. Keep the agent strictly read-only.

11. The agent must not have:
    - arbitrary SQL
    - arbitrary Cypher
    - Bash
    - filesystem modification
    - source-code modification
    - GitHub write access
    - deployment capability
    - remediation capability

12. Add configuration for:
    ANTHROPIC_API_KEY
    CLAUDE_MODEL
    CLAUDE_MAX_TURNS

13. Add/update .env.example and ensure .env is ignored.

14. Keep configuration centralized in app/core/config.py rather than
    scattering os.getenv() calls throughout the application.

15. Refactor the FastAPI agent endpoint only as necessary to work with
    the new SDK-backed service.

16. Introduce an IdentityContext interface/hook for future tenant/user
    authorization, but DO NOT implement memory or tenant memory yet.

17. Keep InvestigationResult as a validated Pydantic response model.

18. Remove the previous hard-coded confidence rule. Do not fabricate
    confidence from a fixed evidence count.

19. Capture the MCP tools actually used by the agent if the SDK version
    provides a reliable way to do so.

20. Handle:
    - authentication errors
    - SDK initialization errors
    - MCP connection errors
    - MCP tool errors
    - malformed responses
    - maximum-turn termination

21. Never log:
    - API keys
    - JWTs
    - passwords
    - secrets

Testing:

1. Rewrite tests/test_phase5.py for the new SDK architecture.

2. Keep ordinary unit tests deterministic and free of Anthropic API
   calls.

3. Add clearly separated live/integration tests for the real Claude
   Agent SDK.

4. The live test must demonstrate the actual path:

       PulseOps application
           ↓
       Claude Agent SDK
           ↓
       Claude
           ↓
       PulseOps MCP
           ↓
       retrieval tool
           ↓
       tool result
           ↓
       Claude
           ↓
       InvestigationResult

5. A test that manually calls MCP from Python and then calls the
   Anthropic Messages API does NOT satisfy the Phase 5 requirement.

6. Preserve all existing Phase 0–4 tests.

7. Run the complete test suite after implementation.

8. Review the final git diff and remove obsolete Phase 5 code.

Important boundaries:

DO NOT implement:
- semantic memory
- procedural memory
- episodic memory
- meta memory
- persistent memory
- Neo4j memory storage
- JWT-based memory partitioning
- GitHub integration
- n8n
- human-in-the-loop remediation

Those belong to later phases.

The final implementation must represent a genuine Claude Agent SDK
application, not an Anthropic API wrapper with manually orchestrated MCP.

Before coding, provide a concise implementation plan based on the
actual installed SDK version. Then implement the plan and run tests.