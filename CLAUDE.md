# WalletLedger: notes for AI coding assistants

**Read these first, in order, instead of exploring the code from scratch** (it costs far fewer tokens):

1. `docs/PROJECT_MAP.md` (about 6k tokens): every file with a plain-language note, its public
   functions/classes with line numbers, and which files it imports; plus commands, tables and request tours.
   Read this before opening any source file. (`docs/project-map.json` is the same data for tools.)
2. `docs/PROJECT_GUIDE.md`: what is where and how each part works.
3. The interactive version for humans: `site/explore/index.html` (published at `/explore/` on the site).

Both the map and the explorer are rebuilt by `scripts/build_map.py` (CI does it on every push).
When you add or rename a file, add a line to `NOTES` in that script; `tests/test_project_map.py` fails
until you do.

## What it is
A Telegram expense-tracker bot (FastAPI + aiogram + LangGraph + LiteLLM, SQLite or Postgres).
Free-text messages are understood by an LLM agent (LangGraph, see `docs/AGENT_GRAPH.md`); commands
and buttons need no AI. Users bring their own key (or the server's shared keys).

## Rules of the codebase
- Only `app/services/ledger.py` changes balances. Everything else calls it.
- Free text goes to the agent's LLM planner, which picks ledger tools. Do not add regex intent parsers.
- Risky calls (big transfers, edits, deletes, balance resets, budget overspend) pause with
  LangGraph `interrupt()` in the guard node; the user answers with Yes/Cancel.
- A message that is a question is never logged as spending (planner prompt rule, tested).
- Identity is the Telegram chat id; every query filters by `user_id`.
- `transactions.description`, `chat_messages.content` and `api_keys.encrypted_key` are encrypted.
  Never use `EncryptedText` columns in WHERE / ORDER BY / GROUP BY.
- Never print or commit real keys or tokens. `.env` holds real ones.
- Tests must be offline: every test file starts with `WALLETLEDGER_TESTING=1` and `LITELLM_MODE=PRODUCTION`
  (otherwise litellm loads `.env` and spends real quota). Any ad-hoc script must do the same.

## Commands
```bash
uv sync
uv run python -m unittest discover -s tests     # runs offline, under a minute
uv run ruff check . && uv run ruff format .
uv run uvicorn main:app --reload --port 8000    # run the bot (asks setup questions on the very first start)
uv run python scripts/build_map.py              # refresh the project map and explorer
uv run python scripts/setup_bot.py              # publish the Telegram command menu
```

## Workflow
Commit straight to `main` (no PRs). Commit messages end with the Co-Authored-By trailer.
