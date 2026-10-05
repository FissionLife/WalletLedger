# WalletLedger - SDLC & Integration Contracts

To ensure all 5 team members can work in parallel without blocking each other, this document outlines the **System Architecture, Database Schema, and API Contracts**. Following this SDLC (Software Development Life Cycle) approach guarantees that when we merge our branches, everything integrates seamlessly.

---

## 👥 Team Assignments
- **Role 1 & 6 (You):** Telegram Bot Core & Infrastructure/Schema
- **Role 2 (Gopal):** LangGraph Agent (The Brain)
- **Role 3 (Komal):** AI Gateway (LLM Routing)
- **Role 4 (Meet):** MCP Server (Tool Execution)
- **Role 5 (Surya):** Transaction Engine (Data Extraction & Analytics)

---

## 🗄️ Database Schema ("Tank & Pipes")

As the Infrastructure lead (Role 6), you will need to implement this schema (in SQLite/PostgreSQL) so the rest of the team can query it.

```sql
-- The Users
CREATE TABLE users (
    id UUID PRIMARY KEY,
    telegram_chat_id VARCHAR UNIQUE,
    created_at TIMESTAMP
);

-- The 'Pipes In' (Wallets, Bank Accounts)
CREATE TABLE accounts (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    name VARCHAR, -- e.g., "HDFC Bank", "Cash Wallet"
    balance DECIMAL
);

-- The 'Pipes Out' (Expense Categories)
CREATE TABLE categories (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    name VARCHAR, -- e.g., "Food", "Rent"
    budget_limit DECIMAL
);

-- The Flow (Expenses, Incomes, Transfers)
CREATE TABLE transactions (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    from_account_id UUID REFERENCES accounts(id), -- Null if pure income
    to_category_id UUID REFERENCES categories(id), -- Null if pure transfer
    amount DECIMAL,
    transaction_type VARCHAR, -- 'expense', 'income', 'transfer'
    description TEXT,
    source VARCHAR, -- 'chat', 'pdf', 'sms'
    created_at TIMESTAMP
);

-- User API Keys (For Komal's AI Gateway)
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
When you receive a message from Telegram, you pass it to Gopal's agent like this:
**Function Signature (`app/bot/agent.py`):**
```python
async def process_message(chat_id: str, text: str, attachments: list = None) -> str:
    # Returns the string response to send back to the user
```

### Contract B: LangGraph Agent (Gopal) ➡️ AI Gateway (Komal)
When Gopal needs the LLM to think, he doesn't call Gemini directly. He calls Komal's gateway.
**Function Signature (`app/services_ai/ai_gateway.py`):**
```python
async def generate_response(user_id: str, system_prompt: str, user_prompt: str) -> str:
    # Komal's code will fetch the API key from the DB and route it via LiteLLM
```

### Contract C: LangGraph Agent (Gopal) ➡️ MCP Server (Meet)
When the LLM decides it needs to check a balance or log an expense, Gopal's agent will trigger Meet's MCP tools.
**Function Signatures (`app/services_ai/mcp_server.py`):**
```python
def get_balance(user_id: str, account_name: str = None) -> dict:
    # Returns: {"status": "success", "balance": 5000, "account": "HDFC"}

def log_transaction(user_id: str, amount: float, category: str, description: str) -> dict:
    # Returns: {"status": "success", "transaction_id": "123"}
```

### Contract D: MCP Server (Meet) & Telegram Core ➡️ Transaction Engine (Surya)
**Answering your question:** Does Surya *only* do PDF parsing?
**No.** Surya's engine handles *all* complex data extraction and analytics. The Transaction Engine is the heavy lifter for financial logic.

**Function Signatures (`app/services_ai/transaction_parser.py`):**
```python
# 1. Parsing unstructured chat (e.g. "I bought coffee for $5")
async def extract_expense_from_text(text: str) -> dict:
    # Returns: {"amount": 5.0, "category": "Food", "description": "coffee"}

# 2. Parsing PDFs
async def parse_bank_statement_pdf(file_bytes: bytes) -> list[dict]:
    # Returns a list of structured transaction dicts

# 3. Analytics & "Reduce Money" Mode
def generate_spending_report(user_id: str, time_frame: str = "weekly") -> str:
    # Returns: "You spent 40% on Food. Try cutting down on coffee!"
```

---

## 🚀 SDLC Workflow for the Team

1. **Phase 1 (Mocking):** Everyone writes their functions, but returns "mock" (fake) data. For example, Meet's `get_balance` just returns `5000` without checking the database. This allows Gopal to test the LangGraph flow immediately.
2. **Phase 2 (Database Hookup):** You (Role 6) push the database schema. Meet and Surya connect their mock functions to the real database.
3. **Phase 3 (Integration):** Komal hooks up LiteLLM. Gopal removes the mock LLM calls and connects to Komal's Gateway.
4. **Phase 4 (Testing):** You run the Telegram bot on localhost and test the full end-to-end flow!
