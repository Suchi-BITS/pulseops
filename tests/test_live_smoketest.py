import asyncio

from app.core.config import get_settings
from app.agent.service import IncidentInvestigationAgent


async def main():
    agent = IncidentInvestigationAgent(
        database_url=get_settings().database_url,
        max_turns=6,
    )

    result = await agent.investigate(
        "INC-1007",
        objective=(
            "Investigate the payment service latency spike "
            "and determine the likely cause using the available "
            "PulseOps evidence."
        ),
    )

    print(result.model_dump_json(indent=2))
    telemetry = agent.last_telemetry
    print("TELEMETRY:", telemetry.model_dump_json() if telemetry else None)

    # Phase 6: a degraded fallback (MCP/tool access failed) does not count as a successful live run.
    grounded = bool(telemetry and telemetry.grounded)
    used_retrieval = any(name in agent.MCP_TOOL_NAMES for name in result.tool_calls)
    no_unauthorized = bool(telemetry) and not telemetry.unauthorized_tool_attempts
    print("GROUNDED:", grounded)
    print("RETRIEVAL_TOOL_USED:", used_retrieval)
    print("NO_UNAUTHORIZED_TOOLS:", no_unauthorized)
    passed = grounded and used_retrieval and no_unauthorized
    print("INVESTIGATION_RESULT:", "PASS" if passed else "FAIL")
    print("SMOKE_TEST:", "PASS" if passed else "FAIL")
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    # Manual live run only: .env is loaded here, never at import/collection, so pytest cannot pick up a real API key.
    try:  # optional convenience; not a declared dependency
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:  # pragma: no cover - depends on the environment
        pass
    asyncio.run(main())