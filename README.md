# FissionLifebot - AI Telegram Financial Assistant

FissionLifebot is an AI-powered Telegram bot (similar to Fold App) that helps users track their expenses, categorize them, and generate comprehensive statistics. 

This project is a preparatory round for our hackathon, designed for a 6-person team to collaborate effectively. It uses an AI Gateway (provider-agnostic), LangGraph for conversational flows, and Model Context Protocol (MCP) to interact with our backend database.

## Prerequisites
- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (Extremely fast Python package manager)
- Docker (for PostgreSQL)

## Quick Start (with `uv`)

This project uses `uv` for lightning-fast dependency management and virtual environments.

### 1. Start PostgreSQL Database
```bash
docker run --name app_pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_USER=postgres -e POSTGRES_DB=appdb -p 5432:5432 -d postgres:16
```

### 2. Install Dependencies
Instead of `pip install`, use `uv` to automatically sync the environment:
```bash
uv sync
```
*Note: This will automatically create a `.venv` directory and install everything from `pyproject.toml`.*

### 3. Run the Application
```bash
uv run uvicorn app.main:app --reload --port 8000
```
The FastAPI (which now includes the Telegram Bot Webhook) will run on `http://localhost:8000`.

## Team Collaboration & Roles

The architecture has been split into 6 parallel roles so we can all work without merge conflicts. **Claim a role, create a new branch (`git checkout -b feature/role-1`), and submit a Pull Request!**

1. **Telegram Bot Core (`app/bot/main.py`)**: Handle webhooks, basic commands, and parsing Telegram updates using `aiogram`.
2. **LangGraph Agent (`app/bot/agent.py`)**: Build the state machine and conversational "brain" of the bot.
3. **AI Gateway (`app/services_ai/ai_gateway.py`)**: Implement LiteLLM routing, and fetch user-specific Gemini API keys from the database securely.
4. **MCP Server (`app/services_ai/mcp_server.py`)**: Expose the backend payment API (get balance, log expense) as tools for LangGraph.
5. **Transaction Engine (`app/services_ai/transaction_parser.py`)**: Build the logic to extract expenses from chat text and parse PhonePe PDF statements.
6. **Infrastructure & Deployment**: Manage this `README`, the Docker compose files, CI/CD for our PRs, and database schemas.

## Working with `uv`
- To add a new package: `uv add <package_name>`
- To remove a package: `uv remove <package_name>`
- To run scripts: `uv run python scripts/seed_data.py`

## Git Workflow
1. Pull the latest from `main`: `git pull origin main`
2. Branch out: `git checkout -b feature/<your-role-name>`
3. Work on your specific files (e.g. `app/bot/agent.py`).
4. Commit: `git commit -m "feat: setup langgraph state machine"`
5. Push & Create PR: `git push origin feature/<your-role-name>`
