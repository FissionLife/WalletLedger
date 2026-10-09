# WalletLedger

An AI-powered Telegram expense tracker built on a **Tank & Pipes** ledger: accounts are pipes in,
categories are pipes out, and transfers between your own accounts are never counted as spending.

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (Mermaid diagrams) · [docs/SECURITY.md](docs/SECURITY.md) (data storage and hardening)
- [DEPLOYMENT.md](DEPLOYMENT.md) · [DOCUMENTATION.md](DOCUMENTATION.md) · [TEAM_GUIDE.md](TEAM_GUIDE.md) · [SDLC_AND_SCHEMA.md](SDLC_AND_SCHEMA.md)

> Note: DEPLOYMENT.md / DOCUMENTATION.md still describe the retired "users / orders / wallet" payment
> API and need a rewrite. This README is the source of truth.

## Run it

```bash
uv sync
uv run uvicorn main:app --reload --port 8000     # SQLite by default (walletledger.db)
uv run python scripts/seed_demo_data.py          # demo user "demo" with 50 transactions
```

Try it without Telegram (set `ENABLE_DEV_ENDPOINTS=true` in `.env` first):

```bash
curl -X POST localhost:8000/bot/simulate_chat -H 'content-type: application/json' \
  -d '{"chat_id":"demo","text":"Spent 450 on dinner via HDFC Bank"}'
```

## Configuration (`.env`)

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | default `sqlite:///./walletledger.db`; Postgres works too |
| `TELEGRAM_BOT_TOKEN` | enables Telegram. Empty = only `/bot/simulate_chat` |
| `USE_WEBHOOK`, `WEBHOOK_URL`, `WEBHOOK_SECRET` | webhook mode (otherwise long polling). Always set a secret |
| `SECRET_KEY` | encrypts users' API keys at rest. **Change it** (startup warns on the default) |
| `DEFAULT_LLM_MODEL`, `DEFAULT_LLM_API_KEY` | optional server-side fallback LLM |
| `ENABLE_DEV_ENDPOINTS` | default `false`. Set `true` locally to use `/bot/simulate_chat` (lets the caller act as any chat id) |
| `ALLOWED_CHAT_IDS` | comma-separated Telegram chat ids allowed to use the bot (empty = anyone) |
| `SECRET_KEY_OLD` | previous key(s) for rotation |
| `CONFIRM_THRESHOLD` | amounts at/above this need a "yes" (default 50000) |

## What the bot understands

`Spent 450 on dinner via Bank` · `Paid 150 to Starbucks for coffee` · `Received 50000 salary in Bank` ·
`Transferred 2000 from Bank to Cash` · `/balance` · `/report` · `how can I reduce expenses?` ·
`ruthless mode` / `coach mode` / `quick mode` · `/setkey <key>` · send a PhonePe/GPay PDF.

Everything above works with **no LLM key** (rule-based parsing). Adding a Gemini/OpenAI/Groq/Claude
key (`/setkey`) enables free-form questions, better advice wording and an intent-classifier fallback.

## Layout

```
main.py                         FastAPI app + Telegram lifecycle
app/bot/main.py                 Role 1: webhook / polling / commands / document intake
app/bot/agent.py                Role 2: LangGraph (classify -> act -> respond), confirmations
app/services_ai/ai_gateway.py   Role 3: LiteLLM routing, round-robin keys, fallback
app/services_ai/prompts.py      Role 3: personas
app/services_ai/mcp_server.py   Role 4: tool registry + financial skills (execute_tool)
app/services_ai/transaction_parser.py   Role 5: chat/PDF/SMS parsing, insights
app/services/ledger.py          Core ledger (balances, transfers, summaries)
```

## Tests

```bash
uv run python -m unittest discover -s tests
```
