# Technical Documentation

Diagrams: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Security and storage:
[docs/SECURITY.md](docs/SECURITY.md). Setup: [README.md](README.md), [DEPLOYMENT.md](DEPLOYMENT.md).

## Modules

| Module | Responsibility |
|---|---|
| `main.py` | FastAPI app, lifespan (create tables, start Telegram polling or webhook) |
| `app/config.py` | Settings from env / `.env`; `is_chat_allowed` |
| `app/db.py`, `app/models.py` | SQLAlchemy engine/session and models (users, accounts, categories, merchants, subscriptions, transactions, api_keys) |
| `app/services/ledger.py` | Money logic: record income/expense, transfers, balances, summaries. Raises `LedgerError` on bad input |
| `app/bot/main.py` | `/bot/webhook`, polling loop, `/bot/simulate_chat`, commands, PDF intake, reply sending |
| `app/bot/agent.py` | LangGraph `classify -> act -> respond`, confirmations, persona mode |
| `app/services_ai/ai_gateway.py` | LiteLLM calls, per-user encrypted keys, round-robin and fallback |
| `app/services_ai/vault.py` | Fernet encryption of API keys, key rotation |
| `app/services_ai/prompts.py` | Persona and extraction prompts |
| `app/services_ai/mcp_server.py` | Tool registry (`execute_tool`) and financial skills |
| `app/services_ai/transaction_parser.py` | Chat/PDF/SMS parsing, categorisation, recurring detection, insights |

## HTTP endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/`, `/health` | status |
| POST | `/bot/webhook` | Telegram updates; requires `X-Telegram-Bot-Api-Secret-Token` when `WEBHOOK_SECRET` is set |
| POST | `/bot/simulate_chat` | `{"chat_id","text"}`; 404 unless `ENABLE_DEV_ENDPOINTS=true` |

## Contracts between components

```python
# Bot -> agent
async def process_user_interaction(chat_id: str, text: str, attachments=None) -> str
# Agent -> gateway
async def ask_llm(user_id, system_prompt, user_prompt, model_preference=None) -> str
# Agent -> tools (never raises; returns {"status": "error", "error": ...} on failure)
def execute_tool(tool_name: str, **kwargs) -> dict
# Tools -> ledger
def record_transaction(db, user_id, amount, account_name, category_name=None,
                       merchant_name=None, tx_type="expense", description=None,
                       source="chat", created_at=None) -> dict
def transfer_between_pipes(db, user_id, from_account_name, to_account_name, amount) -> dict
# Bot -> parser
async def parse_statement_file(file_bytes: bytes, file_type="pdf") -> list[dict]
def generate_financial_insights(user_id: str, mode="summary") -> dict
```

## Tools (`execute_tool`)
`log_expense`, `log_income`, `transfer_between_pipes`, `get_pipe_balances`, `get_spending_breakdown`,
`set_budget`, `save_user_api_key`, `get_insights`, and the skills `skill_budget_alert_check`,
`skill_recurring_bill_detector`, `skill_emergency_fund_calculator`.

## Behaviour notes
- Intent parsing is rule-based first; an LLM is consulted only when rules find nothing and the user
  (or server) has a key. LLM output is validated before use.
- Balances are stored as floats rounded to 2 decimals (known limitation; see SECURITY/README).
- Amounts at or above `CONFIRM_THRESHOLD` are held until the user replies yes/no (5 minute expiry).
- Statement import skips rows with the same date, amount and payee that were already imported.

## Development
```bash
uv sync
uv run python -m unittest discover -s tests
uv run ruff check . && uv run ruff format .
```
New tools: add a function decorated with `@tool` in `mcp_server.py`; it is automatically available
to `execute_tool`.
