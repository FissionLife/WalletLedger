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

## 👥 Team Collaboration & Roles

The architecture has been split into 6 parallel roles so we can all work without merge conflicts. **Claim a role, create a new branch (`git checkout -b feature/role-1`), and submit a Pull Request!**

1. **Telegram Bot Core (`app/bot/main.py`)**: Handle webhooks, basic commands, and parsing Telegram updates using `aiogram`.
2. **LangGraph Agent (`app/bot/agent.py`)**: Build the state machine, "Tank and Pipes" reasoning, and conversational "modes" (Analytics Mode, Reduce Expense Mode).
3. **AI Gateway (`app/services_ai/ai_gateway.py`)**: Implement LiteLLM routing, and fetch user-specific Gemini API keys from the database securely.
4. **MCP Server (`app/services_ai/mcp_server.py`)**: Expose the backend payment API (get balance of specific pipes, log expense, transfer money) as tools for LangGraph.
5. **Transaction Engine (`app/services_ai/transaction_parser.py`)**: Build the logic to extract expenses from chat text and parse PhonePe PDF statements, associating them with the correct "Pipe".
6. **Infrastructure & Deployment**: Manage this `TEAM_GUIDE.md`, the SQLite/Postgres schemas for the Tank model, and CI/CD for our PRs.

## 🛠️ Working with `uv`
- To add a new package: `uv add <package_name>`
- To remove a package: `uv remove <package_name>`
- To run scripts: `uv run python scripts/seed_data.py`
