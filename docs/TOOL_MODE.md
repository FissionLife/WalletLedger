# Tool mode: direct vs MCP

`TOOL_MODE` in `.env` (asked by `scripts/setup.py`) decides how the AI's ledger tools run.
Default is `direct`.

```
agent.py / orchestrator.py / PDF import (bot/main.py)
                 │  tool_client.call_tool(name, **args)
                 ▼
     app/services_ai/tool_client.py
        │                                 │
 TOOL_MODE=direct                    TOOL_MODE=mcp
        │                                 │  MCP ClientSession (opened in main.py lifespan)
        │                                 │  stdio JSON-RPC
        │                                 ▼
        │              python -m app.services_ai.mcp_transport   (child process)
        │                                 │  MCPServer "WalletLedger"
        ▼                                 ▼
          mcp_server.TOOL_REGISTRY  ──►  ledger.py  ──►  database
```

- **direct**: plain Python calls in the bot process. Fastest, nothing extra to run.
- **mcp**: the bot starts the real MCP server as a child process and calls every tool over the MCP
  protocol. The LLM is only offered tools the server lists (`list_tools`). Failing to start the
  server stops app startup, so a broken demo is visible right away.
- `/health` reports the active mode: `{"tools": "direct" | "mcp"}`.
- Tool validation errors (`ValueError`) reach MCP clients with their message; other crashes stay
  hidden behind a generic "Error executing tool" message.

Switch: set `TOOL_MODE=mcp` in `.env` (or the environment) and restart the server.
