# WalletLedger - Team Guide & Architecture

WalletLedger is an AI-powered Telegram bot (similar to Fold App) that helps users track their expenses, categorize them, and generate comprehensive statistics.

This project is a preparatory round for our hackathon, designed for a 6-person team to collaborate effectively.

## 🏗️ Architecture & Constraints: "The Tank & Pipes Model"
To make the bot highly adaptable to the real world, we are modeling user finances as a **Tank with Pipes**:
- **The Tank**: The user's total net worth or combined balance.
- **Pipes In (Income Streams)**: Multiple payment methods or accounts (e.g., Salary Account, Cash Wallet, Crypto Wallet, Freelance Gig).
- **Pipes Out (Expenses/Investments)**: Where the money goes (e.g., Rent, Food, Mutual Funds).

**Constraints & Requirements for the Team:**
1. **Multitude of Payment Methods**: Users must be able to define unlimited "Pipes In" (e.g., HDFC Bank, SBI Bank, Paytm Wallet).
2. **Transfer Tracking**: Money moving from Pipe A to Pipe B (e.g., Bank to Cash) should not be counted as an expense, just a transfer.
3. **Different Modes**: The AI agent should be able to switch modes based on user query (e.g., "Reduce Money Mode" to find subscriptions to cut, or "Analytics Mode" to see where the most was spent).

## 💽 Storage & Database (SQLite3 Support)
The system is built to be highly adaptable. Users can store their data wherever they want.
While we default to PostgreSQL, **SQLite3 is fully supported and recommended for easy local testing**.
- To use SQLite, simply set the environment variable: `DATABASE_URL="sqlite:///./fission.db"`
- LangGraph checkpointing can also be configured to use `sqlite3` locally.

---

## 🚀 Quick Start (with `uv`)

This project uses `uv` for lightning-fast dependency management.

### 1. Install Dependencies
Use `uv` to automatically sync the environment and create a `.venv`:
```bash
uv sync
```
*(If you need to prune old dependencies, you can run `uv sync --clean`)*

### 2. Set up SQLite Database
Create a `.env` file in the root directory:
```env
DATABASE_URL=sqlite:///./fission.db
```

### 3. Run the Application
```bash
uv run uvicorn main:app --reload --port 8000
```
The FastAPI (which includes the Telegram Bot Webhook) will run on `http://localhost:8000`.

---

## 👥 Team Collaboration & Assignments

The architecture has been split so everyone can work in parallel without merge conflicts. **Create a branch for your assigned role and submit PRs!**

- **Krishna (Role 1 & 6 + Core Ledger)** (`app/bot/main.py`, `app/db.py`, `app/models.py`, `app/services/ledger.py`):
  Telegram bot router (`aiogram`), SQLite3/Postgres schema, core balance ledger & pipe transfers, CI/CD.
- **Gopal (Role 2 - LangGraph Agent)** (`app/bot/agent.py`):
  Conversational StateGraph brain, intent detection, MCP tool invocation, multi-turn confirmations.
- **Komal (Role 3 - AI Gateway & Mode Personas)** (`app/services_ai/ai_gateway.py`, `app/services_ai/prompts.py`):
  LiteLLM provider-agnostic routing, user API key encryption/vault, round-robin rotation, prompt personas (*Coach*, *Ruthless Budgeter*, *Quick Summary*).
- **Meet (Role 4 - MCP Server, Financial Skills & Seeder)** (`app/services_ai/mcp_server.py`, `scripts/seed_demo_data.py`):
  Standardized MCP tools (`log_expense`, `log_income`, `transfer_funds`), financial skills (`skill_budget_alert_check`, `skill_recurring_bill_detector`, `skill_emergency_fund_calculator`), demo data seeder script.
- **Surya (Role 5 - Document Ingestion & Insights)** (`app/services_ai/transaction_parser.py`):
  PhonePe / bank PDF statement parser, receipt OCR/chat extraction, smart financial insights & "Reduce Money Mode".

---

## ⚡ Quickstart Commands for the Whole Team

Copy and run these commands to get right to work on your role:

### 1. Clone & Setup Project (All Members)
```bash
# Clone the repository
git clone https://github.com/FissionLife/WalletLedger.git
cd WalletLedger

# Install uv if you don't have it already
# Windows: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# Mac/Linux: curl -LsSf https://astral.sh/uv/install.sh | sh

# Sync dependencies and create .venv automatically
uv sync
```

### 2. Create Your Feature Branch
Pick your role and create your branch:
```bash
# For Krishna (Role 1 & 6)
git checkout -b feature/role-1-6-core-ledger

# For Gopal (Role 2)
git checkout -b feature/role-2-langgraph-agent

# For Komal (Role 3)
git checkout -b feature/role-3-ai-gateway

# For Meet (Role 4)
git checkout -b feature/role-4-mcp-tools

# For Surya (Role 5)
git checkout -b feature/role-5-ingestion-insights
```

### 3. Run Application on Localhost
```bash
# Start the FastAPI + Telegram Webhook server
uv run uvicorn main:app --reload --port 8000
```

### 4. Seed Demo Data (Meet's script)
```bash
uv run python scripts/seed_demo_data.py
```

### 5. Git Commit & Push PR
```bash
git add .
git commit -m "feat(role): implement component according to SDLC contract"
git push -u origin <your-feature-branch>
```

## 🛠️ Working with `uv`
- To add a new package: `uv add <package_name>`
- To remove a package: `uv remove <package_name>`
- To clean/prune unused packages: `uv sync --clean`
