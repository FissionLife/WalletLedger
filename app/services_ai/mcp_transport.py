"""Runnable stdio MCP transport for WalletLedger's typed ledger tools.

Run with ``uv run python -m app.services_ai.mcp_transport``. The LangGraph agent
continues to dispatch through the same registry, so both integrations share logic.
"""

from mcp.server.mcpserver import MCPServer

from app.services_ai.mcp_server import TOOL_REGISTRY

mcp = MCPServer(
    name="WalletLedger",
    instructions=(
        "User-scoped financial ledger tools. Supply the user's Telegram chat ID or internal UUID."
    ),
)

for name, handler in TOOL_REGISTRY.items():
    # The MCP SDK derives the input schema from each typed handler's signature.
    mcp.tool(name=name)(handler)


if __name__ == "__main__":
    mcp.run(transport="stdio")
