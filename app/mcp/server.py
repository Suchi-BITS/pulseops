from __future__ import annotations

import os

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from app.core.config import get_settings
from app.retrieval.service import IncidentRetrievalService


def build_mcp_server(database_url: str | None = None, *, tenant_id: str) -> MCPServer:
    """Build a read-only MCP server exposing the approved Phase 3 retrieval tools.

    The server is bound to one tenant for its whole life. No tool accepts a tenant argument, so a caller (or the
    model) cannot choose or override it; every retrieval runs through a service scoped to ``tenant_id``.
    """
    if not tenant_id or not tenant_id.strip():
        raise ValueError("tenant_id is required to build the MCP server")
    resolved_database_url = database_url or get_settings().database_url
    service = IncidentRetrievalService(database_url=resolved_database_url, tenant_id=tenant_id)
    server = MCPServer(
        name="pulseops",
        title="PulseOps Retrieval Tools",
        description="Read-only incident retrieval and context tools for PulseOps operations.",
        version="0.1.0",
    )

    @server.tool(
        name="get_incident_context",
        description="Return the bounded incident context for a specific incident id using the controlled retrieval layer.",
        structured_output=True,
    )
    def get_incident_context(incident_id: str) -> dict[str, object]:
        try:
            return service.get_incident_context(incident_id).model_dump(mode="json")
        except ValueError as exc:
            # Unknown incident/service is a known retrieval outcome: surface the application message so
            # the agent can report it instead of an opaque crash. Other failures stay masked by MCP.
            if "not found" not in str(exc):
                raise
            raise ToolError(str(exc)) from exc

    @server.tool(
        name="get_related_incidents",
        description="Return related incident ids for a service in deterministic, read-only order.",
        structured_output=True,
    )
    def get_related_incidents(service_id: str) -> list[str]:
        return service.get_related_incidents(service_id)

    @server.tool(
        name="get_service_repository",
        description="Resolve the active repository associated with a service via repository mapping.",
        structured_output=True,
    )
    def get_service_repository(service_id: str) -> str | None:
        return service.get_service_repository(service_id)

    @server.tool(
        name="get_service_dependencies",
        description="Return service dependency ids for a service, derived from the graph projection.",
        structured_output=True,
    )
    def get_service_dependencies(service_id: str) -> list[str]:
        return service.get_service_dependencies(service_id)

    return server


def _main() -> None:
    # The agent service launches this process with the tenant of the authenticated request in the environment.
    # Without it the server refuses to start (fail closed): there is no default tenant.
    tenant_id = os.environ.get("PULSEOPS_TENANT_ID", "").strip()
    if not tenant_id:
        raise SystemExit("PULSEOPS_TENANT_ID is required: the MCP server is tenant-bound")
    build_mcp_server(tenant_id=tenant_id).run(transport="stdio")


if __name__ == "__main__":
    _main()
