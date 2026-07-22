"""MCP server surface (P17 ``mcp-server-exposure``).

Exposes the assistant as a Model Context Protocol server so other
sessions and harnesses can invoke it as a tool. See
``assistant.mcp.server`` for the surface and
``assistant serve --mcp`` for the CLI entry point.
"""

from assistant.mcp.server import (
    MCP_PATH,
    MCPServerState,
    build_ask_tool_specs,
    build_mcp_state,
)

__all__ = [
    "MCP_PATH",
    "MCPServerState",
    "build_ask_tool_specs",
    "build_mcp_state",
]
