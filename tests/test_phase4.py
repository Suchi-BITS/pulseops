import asyncio

from tests.helpers import DEV_TENANT
from app.core.config import get_settings
from app.mcp.server import build_mcp_server


def test_phase4_mcp_server_exposes_read_only_tools() -> None:
    server = build_mcp_server(database_url=get_settings().database_url, tenant_id=DEV_TENANT)
    tools = asyncio.run(server.list_tools())
    tool_names = {tool.name for tool in tools}

    expected = {
        "get_incident_context",
        "get_related_incidents",
        "get_service_repository",
        "get_service_dependencies",
    }
    assert expected.issubset(tool_names)


def test_phase4_mcp_server_calls_investigation_tool() -> None:
    server = build_mcp_server(database_url=get_settings().database_url, tenant_id=DEV_TENANT)
    result = asyncio.run(server.call_tool("get_incident_context", {"incident_id": "INC-1007"}))

    assert getattr(result, "is_error", False) is False
    payload = result.content[0].text
    assert "INC-1007" in payload
    assert "svc-payment" in payload
