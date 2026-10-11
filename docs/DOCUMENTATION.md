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
| `app/services_ai/transaction_parser.py` | chat, PDF and SMS parsing; statement formats and categories |
| `scripts/inspect_statement.py` | debug how a statement PDF is read (format, rows, skipped lines) |
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

## Statement import

Send a PDF (or a `.txt` of forwarded bank SMS) to the bot. It shows a short preview (count, date
range, totals, top categories, first rows) and imports only after you reply **yes**. Uploading the
same statement again skips rows already in the ledger.

| Format | Recognised by | Notes |
|---|---|---|
| PhonePe | "PhonePe", or Transaction ID + UTR No + Paid by | "Paid to X DEBIT ₹450" blocks |
| Google Pay | "Google Pay" / "UPI Transaction ID" | one field per line is fine |
| Paytm | "Paytm" / "Money sent to" | `- Rs.450` / `+ Rs.500` signs, dates without a year |
| BHIM | "BHIM" | `Debit`/`Credit`, payee often only a UPI ID |
| Bank table | Date/Narration/Debit/Credit/Balance header, or dated rows with amount + balance | HDFC, SBI, ICICI, Axis, Kotak style; debit vs credit from the running balance, `Dr`/`Cr` suffixes, or the narration |
| Bank SMS | "debited/credited ... A/c" lines | one SMS per line or per paragraph |

Categories come from the user's own earlier choices first, then an Indian merchant/keyword table
(Swiggy, Blinkit, Uber, Amazon, Netflix, BESCOM, LIC, Zerodha, ATM ...). Payments to people go to
`Transfers`; anything unknown stays `Uncategorized` rather than guessed.

All formats are tested with synthetic fixtures only (`tests/test_statement_formats.py`). If a real
statement reads badly, run:

```bash
uv run python scripts/inspect_statement.py statement.pdf --text
```

It prints the detected format, the raw text with line numbers, the parsed rows with categories, and
every skipped line with the reason. `--format bank_table` forces a parser. Password-protected PDFs
must be saved without the password first; scanned (image) PDFs have no text and cannot be read.

## Tests

```bash
uv run python -m unittest discover -s tests
```

All tests run offline: the AI providers and Telegram are mocked.
