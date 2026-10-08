# WalletLedger (WalletLedger & AI Financial Bot)

A production-ready FastAPI-based payment processing, wallet ledger, and AI-powered financial assistant system with user management, order processing, wallet transactions, and Telegram Bot integration.

## Quick Links

- 📖 [Complete Deployment Guide](DEPLOYMENT.md) - Step-by-step local setup instructions
- 📚 [Technical Documentation](DOCUMENTATION.md) - Architecture, flows, and development guide
- 👥 [Team & Architecture Guide](TEAM_GUIDE.md) - "Tank and Pipes" model, hackathon roles & bot architecture
- 🔗 [API Documentation](http://localhost:8000/docs) - Interactive Swagger UI (after starting server)

## Prerequisites

- Python 3.14+ (pinned in `.python-version`)
- [uv](https://github.com/astral-sh/uv) (Fast Python package and project manager)
- Docker (for PostgreSQL) or SQLite (for local testing)

## Quick Start

### 1. Database Setup

Copy the settings template first (every setting is explained inside):
```bash
cp .env.example .env
```

**Option A: PostgreSQL via Docker Compose (Default)**
```bash
docker compose up -d      # Postgres 16 on localhost:5433, data kept in a named volume
docker compose ps         # wait until it shows "healthy"
```
Tables are created automatically when the app starts.

**Option B: SQLite (Quick Local Testing)**
In `.env` set:
```env
DATABASE_URL=sqlite:///./walletledger.db
```

### Telegram bot (optional)
Create a bot with @BotFather and put its token in `.env` as `TELEGRAM_BOT_TOKEN`.
With `USE_WEBHOOK=false` the app polls Telegram when it starts, so just message your bot.
Without a token the bot stays off and you can test with `POST /bot/simulate_chat`.
Commands: `/start`, `/help`, `/balance`, `/report`, `/setkey <key>`, `/keys`, `/coach`, `/budgeter`, `/summary`, and PDF statement uploads.

### 2. Install Dependencies

Use `uv` to automatically synchronize the environment and manage `.venv`:
```bash
uv sync
```

### 3. Run the Application

```bash
uv run uvicorn main:app --reload --port 8000
```

*Or run directly:*
```bash
uv run python main.py
```

The API will be available at `http://localhost:8000` (Swagger UI at `http://localhost:8000/docs`).

### 4. Seed Sample Data

```bash
# Seed multiple users with wallets and orders
uv run python scripts/seed_data.py --all

# Or seed a single user
uv run python scripts/seed_data.py CUST-001
```

## API Endpoints

### Users

**Create User**
```bash
curl -X POST http://localhost:8000/users \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "CUST-001",
    "email": "customer@example.com",
    "full_name": "John Doe",
    "phone": "+91-9876543210"
  }'
```

**Get User**
```bash
curl http://localhost:8000/users/CUST-001
```

**List Users**
```bash
curl http://localhost:8000/users
```

### Orders

**Create Order**
```bash
curl -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "CUST-001",
    "amount": 499.99,
    "currency": "INR",
    "idempotency_key": "order-123"
  }'
```

**List Orders**
```bash
curl "http://localhost:8000/orders?customer_id=CUST-001"
```

### Wallet

**Credit Wallet**
```bash
curl -X POST http://localhost:8000/wallet/CUST-001/credit \
  -H "Content-Type: application/json" \
  -d '{"amount": 1000}'
```

**Debit Wallet**
```bash
curl -X POST http://localhost:8000/wallet/CUST-001/debit \
  -H "Content-Type: application/json" \
  -d '{"amount": 200}'
```

**Get Wallet Balance**
```bash
curl http://localhost:8000/wallet/CUST-001
```

### Telegram Bot Webhook

**Simulate a chat message (no bot token needed)**
```bash
curl -X POST http://localhost:8000/bot/simulate_chat \
  -H "Content-Type: application/json" \
  -d '{"chat_id": "12345", "text": "Spent 450 on dinner via Bank"}'
```

**Receive Telegram Update (dev mode, no token: reply returned as JSON)**
```bash
curl -X POST http://localhost:8000/bot/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "update_id": 10001,
    "message": {
      "chat": {"id": 12345},
      "text": "/start"
    }
  }'
```

## Testing Scenarios

Run test scenarios to validate the API and ledger behaviors:

```bash
# Run all scenarios with seeding
uv run python scripts/run_scenarios.py --scenario all --seed

# Run specific scenario
uv run python scripts/run_scenarios.py --scenario orders_retry
uv run python scripts/run_scenarios.py --scenario wallet_concurrency
uv run python scripts/run_scenarios.py --scenario false_success

# Repeat scenario multiple times
uv run python scripts/run_scenarios.py --scenario wallet_concurrency --repeat 5
```

## Database Management

### PostgreSQL via Docker

**Initialize schema manually (optional, the app does this on startup):**
```bash
docker compose exec -T db psql -U postgres -d appdb < sql/schema.sql
```
`sql/schema.sql` is generated from `app/models.py`; after model changes run
`uv run python scripts/generate_schema.py`.

**Load demo data:**
```bash
uv run python scripts/seed_demo_data.py
```

**Connect to database:**
```bash
docker compose exec db psql -U postgres -d appdb    # then \dt lists the 8 tables
```

### SQLite

When using `DATABASE_URL=sqlite:///./fission.db`, tables are automatically initialized on application startup. You can inspect data using standard SQLite tools:
```bash
sqlite3 fission.db
```

## Working with `uv`

- **Sync dependencies**: `uv sync`
- **Add a dependency**: `uv add <package_name>`
- **Remove a dependency**: `uv remove <package_name>`
- **Run scripts**: `uv run python <script.py>`
- **Run server**: `uv run uvicorn main:app --reload --port 8000`
- **Prune unneeded packages**: `uv sync --clean`

## Project Structure

```
WalletLedger/
├── app/
│   ├── __init__.py
│   ├── auth.py                  # Authentication utilities
│   ├── config.py                # Application settings
│   ├── db.py                    # Database session & engine
│   ├── models.py                # SQLAlchemy models (User, Wallet, Order)
│   ├── routes_orders.py         # Order endpoints
│   ├── routes_users.py          # User management endpoints
│   ├── routes_wallet.py         # Wallet balance & transactions
│   ├── schemas.py               # Pydantic validation schemas
│   ├── services.py              # Core business & ledger logic
│   ├── bot/                     # Telegram Bot integration
│   │   ├── __init__.py
│   │   ├── agent.py             # LangGraph state machine & reasoning
│   │   └── main.py              # Telegram webhook endpoint
│   └── services_ai/             # AI service layers
│       ├── __init__.py
│       ├── ai_gateway.py        # LiteLLM routing & API keys
│       ├── mcp_server.py        # Model Context Protocol tools
│       └── transaction_parser.py # PDF statement & chat parser
├── scripts/
│   ├── run_scenarios.py         # Concurrency and idempotency test scenarios
│   └── seed_data.py             # Sample data seeding utility
├── sql/
│   ├── schema.sql               # PostgreSQL schema
│   └── (generated by scripts/generate_schema.py)
├── .github/
│   └── workflows/
│       └── lint.yml             # GitHub Actions CI linting, formatting & auto-heal workflow
├── .pre-commit-config.yaml      # Pre-commit hook definitions (ruff, ruff-format, hooks)
├── project.devprune.json        # dev-prune workspace configuration
├── main.py                      # FastAPI application entry point
├── pyproject.toml               # Project metadata, dependencies & ruff config
├── uv.lock                      # Locked dependency versions
├── .gitignore
├── .python-version              # Python 3.14 pin
├── DEPLOYMENT.md                # Detailed deployment guide
├── DOCUMENTATION.md             # In-depth architectural & API documentation
├── TEAM_GUIDE.md                # Hackathon & "Tank and Pipes" architecture guide
└── README.md
```

## Code Quality, Pre-Commit & CI/CD

### Local Formatting & Linting
The project uses **Ruff** for fast linting and code formatting:
```bash
# Check code and auto-fix issues
uv run ruff check --fix .

# Auto-format all files
uv run ruff format .
```

### Git Pre-Commit Hooks
Pre-commit hooks are pre-configured to ensure clean commits:
```bash
# Install git pre-commit hooks
uv run pre-commit install

# Run against all files manually
uv run pre-commit run --all-files
```

### GitHub Actions CI/CD (Auto-Healing)
A GitHub Actions workflow is set up in `.github/workflows/lint.yml` on push and pull requests:
- Automatically validates code against Ruff formatting and lint rules.
- **Auto-heals**: If any formatting or lint fixes are needed, the workflow automatically fixes them and commits back to the branch.
- **Non-blocking**: Designed not to break commits, maintaining rapid iteration speed for the hackathon team while keeping the repository clean.

## Development

The application uses:
- **FastAPI** for high-performance REST APIs & ASGI webhook handling
- **SQLAlchemy 2.x** for ORM persistence
- **PostgreSQL & SQLite** database backends
- **Pydantic v2** for request/response validation
- **uv** for fast package & environment management
- **aiogram & LangGraph** for AI conversational workflows
- **LiteLLM** for provider-agnostic LLM routing
- **Ruff & Pre-Commit** for linting, formatting, and auto-healing

Database schema is automatically initialized on application startup.
