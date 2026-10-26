"""MCP tool boundary for PulseOps read-only retrieval capabilities."""

__all__ = ["build_mcp_server"]


def __getattr__(name: str):
    if name == "build_mcp_server":
        from app.mcp.server import build_mcp_server

        return build_mcp_server
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
