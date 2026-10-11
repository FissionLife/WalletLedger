# Code map

Plain-language overview: [HOW_IT_WORKS.md](HOW_IT_WORKS.md). Diagrams: [ARCHITECTURE.md](ARCHITECTURE.md).

| Path | Responsibility |
|---|---|
| `main.py` | FastAPI app; starts the database and the Telegram bot |
| `app/config.py` | settings from `.env`; who is allowed / admin |
| `app/db.py`, `app/models.py` | database engine (SQLite or Postgres) and tables |
| `app/services/ledger.py` | the only code that changes balances; validates every amount |
| `app/bot/telegram.py` | aiogram: polling or webhook, sending replies, command menu |
| `app/bot/main.py` | command routing, PDF import, access checks, `/simulate_chat` (dev) |
| `app/bot/agent.py` | LangGraph agent: understand message, call tools, write the reply |
| `app/bot/keys.py` | `/setkey`, `/keys`, `/testkey`, `/editkey`, `/admin` |
| `app/bot/profile.py` | the bot's Telegram profile (menu, description) |
| `app/health.py` | `/status` and the setup health check |
| `app/envfile.py` | safe `.env` editor used by the wizard |
| `app/services_ai/ai_gateway.py` | AI calls, key order, rotation, fallback, live key tests |
| `app/services_ai/model_catalog.py` | picks the best model per provider automatically |
| `app/services_ai/mcp_server.py` | the tool registry the agent calls (also served over MCP stdio) |
| `app/services_ai/prompts.py` | the three advice personas |
| `app/services_ai/transaction_parser.py` | chat, PDF and SMS parsing |
| `scripts/setup.py` | setup wizard and `--check` |
| `scripts/setup_bot.py` | publish/refresh the Telegram command menu |
| `scripts/seed_demo_data.py` | demo user with sample transactions |

## Endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/`, `/health` | status |
| POST | `/bot/webhook` | Telegram updates (verified with a secret header) |
| POST | `/bot/simulate_chat` | dev only: on while no bot token is set, or `ENABLE_DEV_ENDPOINTS=true` |

## Adding a tool for the agent

Add a function in `app/services_ai/mcp_server.py`, register it, and describe it in `TOOLS_SCHEMA` in
`app/bot/agent.py`. The agent can then call it, and the MCP server exposes it too.

## Tests

```bash
uv run python -m unittest discover -s tests
```

All tests run offline: the AI providers and Telegram are mocked.
