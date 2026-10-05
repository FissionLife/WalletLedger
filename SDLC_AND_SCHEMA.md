# WalletLedger - SDLC, Team Division & Integration Contracts

WalletLedger is a **comprehensive personal expense tracker and financial intelligence assistant** (inspired by Fold App). It models user finances as a **Tank & Pipes** system to track *what* was paid, *how much*, *to whom* (merchants), *where* it was spent (categories), *income pipes*, and *transfers between accounts*.

---

## 👥 Rebalanced Team Roles & Workload Analysis

### Workload Assessment:
Previously, Role 5 (Surya) was overloaded with PDF parsing, chat NLP, database calculations, AND financial advice.
We have rebalanced the work so **You (Role 1 & 6)** also own the **Core Ledger Engine** (since you are designing the database schema anyway), while **Surya (Role 5)** focuses on **Document Ingestion & Financial Intelligence**.

| Member | Role ID | Primary Focus | Scope & Complexity |
|---|---|---|---|
| **You** | **Role 1 & 6 + Core Ledger** | Telegram Bot Interface, DB Schema & Core Balance Math | **Balanced (Medium-High)**: Owns DB models, balance calculations, Telegram routing & deployment. |
| **Gopal** | **Role 2** | LangGraph Agent Workflow ("The Brain") | **Balanced (Medium)**: State machine, intent routing, tool calling, multi-turn confirmations. |
| **Komal** | **Role 3** | AI Gateway & Round-Robin Key Vault | **Balanced (Medium)**: LiteLLM provider abstraction, user key encryption & round-robin rotation. |
| **Meet** | **Role 4** | MCP Server & Tool Registry | **Balanced (Medium)**: Exposing ledger & analytics actions as standardized MCP / LangChain tools. |
| **Surya** | **Role 5** | Document Ingestion & Financial Insights | **Balanced (Medium-High)**: PhonePe/bank PDF statement parsing, receipt extraction, smart savings insights. |

---

## 📋 Detailed Task Breakdown per Person

### 1. You (Role 1 & 6 + Core Ledger Engine)
- **Database Layer (`app/db.py`, `app/models.py`)**:
  - Implement SQLite3 / PostgreSQL schema using SQLAlchemy 2.0.
  - Models: `User`, `Account`, `Category`, `Merchant`, `Transaction`, `Subscription`, `ApiKey`.
- **Core Ledger Services (`app/services/ledger.py`)**:
  - Account balance mutations (atomic updates when transactions are recorded).
  - Pipe-to-Pipe Transfers (e.g., Bank -> Cash wallet without marking as expense).
  - Core SQL aggregations: total net worth, balance by account, category totals.
- **Telegram Bot (`app/bot/main.py`)**:
  - `aiogram 3.x` router with polling/webhook modes.
  - Command handlers: `/start`, `/help`, `/balance`, `/setkey`, `/report`.
  - Document/Photo listener: accepts PhonePe statement PDFs or receipt images and passes bytes to Surya's parser.
  - Message router: passes user text to Gopal's LangGraph agent and sends formatted replies.
- **Infrastructure**:
  - `docker-compose.yml`, `.env.example`, `uv` environment synchronization, and CI verification.

### 2. Gopal (Role 2 - LangGraph Agent Brain)
- **Agent Workflow (`app/bot/agent.py`)**:
  - Implement `langgraph.graph.StateGraph` with a defined `AgentState` (`messages`, `user_id`, `chat_id`, `intent`).
  - **Intent Detection Node**:
    - Expense/Income logging ("Spent 200 on pizza via GPay")
    - Financial query ("How much did I spend on Swiggy this month?")
    - Advice query ("How can I reduce expenses?")
    - API key management ("Here is my Gemini key: AIza...")
  - **Tool Execution Node**: Calls Meet's MCP tools dynamically when data needs to be read or written.
  - **Confirmation / Human-in-the-Loop Node**: For large transfers or ambiguous transactions, ask confirmation before committing to the DB.
  - **Response Synthesis Node**: Generates friendly, concise Telegram-friendly Markdown responses.

### 3. Komal (Role 3 - AI Gateway & Round-Robin Key Vault)
- **Gateway Module (`app/services_ai/ai_gateway.py`)**:
  - Wrap `litellm.completion` to make the bot 100% provider agnostic (Gemini, OpenAI, Claude, Groq, Ollama).
  - **Dynamic User Key Management**:
    - Encrypt and store API keys in the `api_keys` table.
    - Allow users to chat-enter multiple Gemini API keys.
  - **Round-Robin Key Rotation**:
    - Cycle through the user's active API keys on consecutive requests to bypass rate limits (RPM / TPM).
  - **Automatic Fallback**:
    - If a key throws a `RateLimitError` (429) or quota failure, switch immediately to the next available key/provider.

### 4. Meet (Role 4 - MCP Server & Tool Registry)
- **MCP Server & Tool Definitions (`app/services_ai/mcp_server.py`)**:
  - Expose clean, typed tools for the LangGraph agent to execute:
    - `log_expense(user_id, amount, category, merchant, account_name, description)`
    - `log_income(user_id, amount, source_account, description)`
    - `transfer_between_pipes(user_id, from_account, to_account, amount)`
    - `get_pipe_balances(user_id)`
    - `get_spending_breakdown(user_id, period, category)`
    - `save_user_api_key(user_id, provider, api_key)`
  - Interface between Gopal's agent and the Database / Core Ledger service.
  - Validate parameters with Pydantic schemas.

### 5. Surya (Role 5 - Document Ingestion & Financial Insights)
- **Statement & Receipt Ingestion (`app/services_ai/transaction_parser.py`)**:
  - **PDF Statement Parsing**: Parse PhonePe / Google Pay / Bank statement PDFs using `pypdf` / pdfplumber.
  - Extract tabular data: Date, Merchant, VPA/UPI ID, Type (Debit/Credit), Amount, and Bank Account.
  - **Receipt Image / Text OCR**: Extract expense data from receipts or forwarded bank SMS messages.
- **Smart Financial Insights & "Reduce Money Mode"**:
  - Categorization AI: Auto-map cryptic UPI strings (e.g., `UPI-SWIGGY-182390`) to Merchant (`Swiggy`) and Category (`Food & Dining`).
  - **Analytics Engine**:
    - "Where most was spent" breakdown (Top 5 merchants & categories).
    - Recurring subscription detection (identifying Netflix, Spotify, gym charges).
    - "Reduce Money Mode": Generates actionable tips to cut discretionary spending based on historical burn rates.

---

## 🗄️ Full Database Schema (SQLite3 & PostgreSQL Compatible)

```sql
-- 1. Users
CREATE TABLE users (
    id VARCHAR(36) PRIMARY KEY,
    telegram_chat_id VARCHAR(64) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Accounts (The "Pipes In" - Bank accounts, Wallets, Cash)
CREATE TABLE accounts (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) REFERENCES users(id),
    name VARCHAR(100) NOT NULL, -- e.g., "HDFC Bank", "Cash", "Paytm Wallet"
    type VARCHAR(30) NOT NULL, -- 'bank', 'wallet', 'credit_card', 'cash'
    balance DECIMAL(12, 2) DEFAULT 0.00,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. Categories (The "Pipes Out" - Budgeting)
CREATE TABLE categories (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) REFERENCES users(id),
    name VARCHAR(100) NOT NULL, -- e.g., "Food", "Rent", "Salary", "Investment"
    budget_limit DECIMAL(12, 2) NULL, -- Optional monthly spending cap
    type VARCHAR(20) DEFAULT 'expense', -- 'expense' or 'income'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. Merchants / Payees (To Whom)
CREATE TABLE merchants (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) REFERENCES users(id),
    name VARCHAR(150) NOT NULL, -- e.g., "Starbucks", "Uber", "Landlord"
    default_category_id VARCHAR(36) REFERENCES categories(id) NULL
);

-- 5. Subscriptions (Recurring expenses)
CREATE TABLE subscriptions (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) REFERENCES users(id),
    merchant_id VARCHAR(36) REFERENCES merchants(id),
    amount DECIMAL(12, 2) NOT NULL,
    billing_cycle VARCHAR(20) DEFAULT 'monthly', -- 'weekly', 'monthly', 'yearly'
    next_billing_date DATE NULL
);

-- 6. Transactions (Core Ledger)
CREATE TABLE transactions (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) REFERENCES users(id),
    account_id VARCHAR(36) REFERENCES accounts(id), -- Source Pipe
    to_account_id VARCHAR(36) REFERENCES accounts(id) NULL, -- Destination Pipe (if transfer)
    category_id VARCHAR(36) REFERENCES categories(id) NULL,
    merchant_id VARCHAR(36) REFERENCES merchants(id) NULL,
    amount DECIMAL(12, 2) NOT NULL,
    transaction_type VARCHAR(20) NOT NULL, -- 'expense', 'income', 'transfer'
    description TEXT,
    source VARCHAR(20) DEFAULT 'chat', -- 'chat', 'pdf', 'sms', 'manual'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 7. User API Keys (For Komal's AI Gateway)
CREATE TABLE api_keys (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) REFERENCES users(id),
    provider VARCHAR(50) NOT NULL, -- 'gemini', 'openai', 'groq', 'claude'
    encrypted_key TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 🤝 Code Contracts & Interfaces

### Contract 1: Bot (You) ➡️ LangGraph Agent (Gopal)
```python
# app/bot/agent.py
async def process_user_interaction(chat_id: str, text: str, attachments: list = None) -> str:
    """Passes user chat or file info into the LangGraph state machine."""
    ...
```

### Contract 2: LangGraph Agent (Gopal) ➡️ AI Gateway (Komal)
```python
# app/services_ai/ai_gateway.py
async def ask_llm(user_id: str, system_prompt: str, user_prompt: str, model_preference: str = None) -> str:
    """Pulls user's round-robin API key and executes via LiteLLM."""
    ...
```

### Contract 3: LangGraph Agent (Gopal) ➡️ MCP Tools (Meet)
```python
# app/services_ai/mcp_server.py
def execute_tool(tool_name: str, **kwargs) -> dict:
    """Executes registered tools (log_expense, get_balance, etc.) and returns structured JSON."""
    ...
```

### Contract 4: MCP Tools (Meet) ➡️ Core Ledger Service (You)
```python
# app/services/ledger.py
def record_transaction(user_id: str, amount: float, account_name: str, category_name: str, merchant_name: str = None, tx_type: str = "expense") -> dict:
    """Applies atomic debit/credit to account balance and creates transaction record."""
    ...

def transfer_funds(user_id: str, from_account: str, to_account: str, amount: float) -> dict:
    """Transfers funds between pipes without counting as an expense."""
    ...
```

### Contract 5: Bot (You) ➡️ Ingestion & Insights Engine (Surya)
```python
# app/services_ai/transaction_parser.py
async def parse_statement_file(file_bytes: bytes, file_type: str = "pdf") -> list[dict]:
    """Parses a PhonePe / bank statement PDF and returns a list of extracted transactions."""
    ...

def generate_financial_insights(user_id: str, mode: str = "summary") -> dict:
    """Generates analytics for 'where most was spent' or 'reduce money mode'."""
    ...
```

---

## 🏁 Immediate Action Items for the Team

1. **Pull the latest `main` branch**: `git pull origin main`
2. **Setup virtual environment**: `uv sync`
3. **Branch out**:
   - You: `feature/role-1-6-core-ledger`
   - Gopal: `feature/role-2-langgraph`
   - Komal: `feature/role-3-ai-gateway`
   - Meet: `feature/role-4-mcp-tools`
   - Surya: `feature/role-5-ingestion-insights`
4. **Build with mocks first**, verify integration contracts, then plug in the real implementations.
