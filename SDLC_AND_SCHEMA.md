# WalletLedger - SDLC & Integration Contracts

To ensure all 5 team members can work in parallel without blocking each other, this document outlines the **System Architecture, Database Schema, and API Contracts**.

WalletLedger is a **comprehensive personal expense tracker** (NOT an e-commerce order system). It infers data to track *what* we paid, *how much*, *to whom* (merchants), *where* it was spent (categories), and *income streams*.

---

## 👥 Team Assignments
- **Role 1 & 6 (You):** Telegram Bot Core & Infrastructure/Schema
- **Role 2 (Gopal):** LangGraph Agent (The Brain)
- **Role 3 (Komal):** AI Gateway (LLM Routing)
- **Role 4 (Meet):** MCP Server (Tool Execution)
- **Role 5 (Surya):** Transaction Engine (Data Extraction & Analytics)

---

## 🗄️ Database Schema ("Personal Finance Engine")

As the Infrastructure lead (Role 6), you will implement this schema (in SQLite/PostgreSQL). This tracks every financial detail perfectly.

```sql
-- 1. Users
CREATE TABLE users (
    id UUID PRIMARY KEY,
    telegram_chat_id VARCHAR UNIQUE,
    created_at TIMESTAMP
);

-- 2. Accounts (The "Pipes In" / Wallets / Cards)
CREATE TABLE accounts (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    name VARCHAR, -- e.g., "HDFC Bank", "Cash", "Amazon Pay"
    type VARCHAR, -- 'bank', 'wallet', 'credit_card'
    balance DECIMAL
);

-- 3. Categories (The "Pipes Out" / Where money goes)
CREATE TABLE categories (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    name VARCHAR, -- e.g., "Food", "Rent", "Salary"
    budget_limit DECIMAL, -- Optional monthly limit
    type VARCHAR -- 'expense', 'income'
);

-- 4. Merchants / Payees (To Whom)
CREATE TABLE merchants (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    name VARCHAR UNIQUE, -- e.g., "Starbucks", "Uber", "Landlord"
    default_category_id UUID REFERENCES categories(id) -- Auto-categorize
);

-- 5. Subscriptions (Recurring tracker)
CREATE TABLE subscriptions (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    merchant_id UUID REFERENCES merchants(id),
    amount DECIMAL,
    billing_cycle VARCHAR, -- 'monthly', 'yearly'
    next_billing_date DATE
);

-- 6. Transactions (The core ledger)
CREATE TABLE transactions (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    account_id UUID REFERENCES accounts(id), -- Which pipe?
    category_id UUID REFERENCES categories(id),
    merchant_id UUID REFERENCES merchants(id),
    amount DECIMAL,
    transaction_type VARCHAR, -- 'expense', 'income', 'transfer'
    description TEXT,
    source VARCHAR, -- 'chat', 'pdf', 'sms'
    created_at TIMESTAMP
);

-- 7. User API Keys (For Komal's AI Gateway)
CREATE TABLE api_keys (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    provider VARCHAR, -- 'gemini', 'openai'
    encrypted_key VARCHAR
);
```

---

## 🤝 Integration Contracts (How the modules talk to each other)

To integrate easily, each role must follow these exact input/output structures.

### Contract A: Telegram Core (You) ➡️ LangGraph Agent (Gopal)
**Function Signature (`app/bot/agent.py`):**
```python
async def process_message(chat_id: str, text: str, attachments: list = None) -> str:
    # 1. Gopal's code takes the raw telegram message.
    # 2. Figures out if it's a query or an expense.
    # 3. Returns the natural language string to send back to the user.
```

### Contract B: LangGraph Agent (Gopal) ➡️ AI Gateway (Komal)
**Function Signature (`app/services_ai/ai_gateway.py`):**
```python
async def generate_response(user_id: str, system_prompt: str, user_prompt: str) -> str:
    # Komal fetches the API key from DB and routes the prompt via LiteLLM.
```

### Contract C: LangGraph Agent (Gopal) ➡️ MCP Server (Meet)
**Function Signatures (`app/services_ai/mcp_server.py`):**
```python
# Meet builds these tools so Gopal's LLM can call them.
def get_account_balance(user_id: str, account_name: str = None) -> dict:
def log_transaction(user_id: str, amount: float, category: str, merchant: str, type: str) -> dict:
def get_spending_by_category(user_id: str, month: str) -> dict:
```

### Contract D: MCP Server (Meet) & Telegram Core ➡️ Transaction Engine (Surya)
**Surya's Transaction Engine is the core intelligence of WalletLedger.** It goes far beyond PDF parsing. It extracts meaning from unstructured data and builds the analytics.

**Function Signatures (`app/services_ai/transaction_parser.py`):**
```python
# 1. NLP Extraction (e.g. "Paid 500 to Uber for travel")
async def extract_expense_from_text(text: str) -> dict:
    # Returns: {"amount": 500.0, "category": "Travel", "merchant": "Uber"}

# 2. PDF / Document Parsing (PhonePe statements, Bank statements)
async def parse_bank_statement_pdf(file_bytes: bytes) -> list[dict]:
    # Returns a list of structured transaction dicts

# 3. Comprehensive Analytics ("Analytics Mode")
def generate_spending_report(user_id: str, time_frame: str) -> dict:
    # Aggregates how much was paid, to whom, and where.
    # Returns: {"total_spent": 15000, "top_merchant": "Starbucks", "biggest_category": "Food"}
```

---

## 🚀 SDLC Workflow for the Team

1. **Phase 1 (Mocking):** Everyone writes their functions, but returns "mock" (fake) data. For example, Meet's `get_account_balance` just returns `5000`. This allows Gopal to test the LangGraph flow immediately without waiting for the DB.
2. **Phase 2 (Database Hookup):** You (Role 6) push the SQLAlchemy database models based on the schema above. Meet and Surya connect their functions to query the real database.
3. **Phase 3 (Integration):** Komal hooks up LiteLLM. Gopal replaces mock LLM calls with Komal's Gateway.
4. **Phase 4 (Testing):** You run the Telegram bot locally, type "I spent $50 on Uber", and watch it flow through the entire stack!
