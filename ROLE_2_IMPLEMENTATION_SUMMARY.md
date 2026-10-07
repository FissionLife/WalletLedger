# 🧠 Role 2: LangGraph Agent Brain — Implementation & Hand-off Summary
**Assignee:** Gopal (Role 2)  
**Component:** `app/bot/agent.py`, `app/models.py`, `app/services_ai/ai_gateway.py`  
**Feature Branch:** `feature/role-2-langgraph-agent`  

---

## 📌 1. Executive Summary

This document provides a comprehensive technical overview of the **LangGraph Conversational Agent Brain** built for the **WalletLedger** project according to the `SDLC_AND_SCHEMA.md` and `TEAM_GUIDE.md` specifications.

The agent coordinates user interactions from Telegram, interprets natural language with dynamic LLM function calling, enforces Human-in-the-Loop safety for high-value balance mutations, dispatches operations to Meet's MCP tool registry, and permanently persists full conversation history across both **PostgreSQL** and **SQLite**.

---

## 🏗️ 2. LangGraph StateGraph Architecture

The agent workflow is implemented as a compiled `langgraph.graph.StateGraph` in `app/bot/agent.py`.

```mermaid
flowchart TD
    Start([Telegram User Message]) --> LoadHistory[Load Full Chat History from DB]
    LoadHistory --> Node1["Node 1: LLM Reasoning & Intent Classification"]
    
    Node1 -->|Confirmation Reply yes/no| Node2["Node 2: Confirmation Handler (HITL)"]
    Node1 -->|High-Value Transfer >= ₹5,000| Node3_Prompt["Node 3: Tool Executor (HITL Prompt)"]
    Node1 -->|Standard Tool Operation| Node3["Node 3: Tool Executor (MCP Dispatch)"]
    Node1 -->|Direct Greeting / Help| Node4["Node 4: Response Synthesizer"]

    Node2 -->|Confirmed| Node3
    Node2 -->|Cancelled| Node4
    Node3 --> Node4
    Node3_Prompt --> Node4
    
    Node4 --> SaveHistory[Save User & Agent Messages to DB]
    SaveHistory --> End([Telegram Markdown Reply])
```

### 🔹 The 4 Core Graph Nodes:

1. **`llm_reasoning_node`**:
   - Analyzes user input via LiteLLM / AI Gateway with registered `TOOLS_SCHEMA` function definitions.
   - Dynamically resolves intent, entities (amount, categories, payees, source/destination account pipes) **without static keyword dictionaries**.
   - Identifies whether the user is answering a pending confirmation (`yes`/`no`).

2. **`confirmation_node` (Human-in-the-Loop Safety)**:
   - Protects users against unintended balance changes by intercepting transfers $\ge \text{₹}5,000$.
   - Manages multi-turn state: executes the pending ledger mutation upon `"yes"` or safely aborts on `"no"`.

3. **`tool_executor_node`**:
   - Calls Meet's standardized MCP tool registry via `execute_tool(tool_name, **kwargs)` in `app/services_ai/mcp_server.py`.
   - Supports: `log_expense`, `log_income`, `transfer_funds`, `get_pipe_balances`, `get_spending_breakdown`, `skill_budget_alert_check`, `skill_recurring_bill_detector`, `skill_emergency_fund_calculator`, `save_user_api_key`.

4. **`response_synthesizer_node`**:
   - Formats tool results into clean, emoji-rich Telegram Markdown messages.
   - Provides proactive financial coaching recommendations in "Reduce Money Mode".

---

## 🤝 3. Integration Contracts Satisfied

| Contract | Parties | Interface Definition | Status |
|---|---|---|---|
| **Contract 1** | Bot (Krishna) ➡️ LangGraph Agent (Gopal) | `async def process_user_interaction(chat_id: str, text: str, attachments: list = None) -> str` | ✅ **Fully Implemented** |
| **Contract 2** | LangGraph Agent (Gopal) ➡️ AI Gateway (Komal) | `async def ask_llm(user_id: str, system_prompt: str, user_prompt: str, ...) -> dict` | ✅ **Fully Implemented** |
| **Contract 3** | LangGraph Agent (Gopal) ➡️ MCP Tools (Meet) | `execute_tool(tool_name: str, **kwargs) -> dict` | ✅ **Fully Implemented** |

---

## 🗄️ 4. Permanent Conversation History (PostgreSQL & SQLite)

To satisfy long-term memory requirements, full conversation history is stored permanently in the database rather than ephemeral memory.

### Schema Addition (`app/models.py` & `sql/schema.sql`):
```sql
CREATE TABLE chat_messages (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL, -- 'user', 'assistant'
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### How Conversation Persistence Works:
1. When a user sends a message, `get_db_conversation_history(user_id)` fetches all prior messages from the DB in chronological order.
2. The incoming message is written to `chat_messages` via `save_db_chat_message(user_id, 'user', text)`.
3. The LangGraph agent executes with full multi-turn conversational context.
4. The final assistant reply is saved via `save_db_chat_message(user_id, 'assistant', reply)`.

---

## ❓ 5. Team Lead FAQ & Architecture Clarifications

### Q1: How does this work when the Team Lead connects to PostgreSQL?
> **Answer:** All database operations are dialect-agnostic via SQLAlchemy 2.0 (`app/db.py`). The application reads `DATABASE_URL` from the environment. Whether the Team Lead points `.env` to `postgresql://user:pass@remote-db:5432/walletledger` or a local database, all tables (including `chat_messages`) work out-of-the-box without code changes.

### Q2: Does the agent rely on hardcoded keyword lists?
> **Answer:** **No.** All hardcoded keyword dictionaries were eliminated. The agent uses dynamic LLM tool schemas (`TOOLS_SCHEMA`) and semantic reasoning to parse categories, merchants, and accounts.

### Q3: What happens if no external LLM API key is configured yet?
> **Answer:** The agent includes a robust dynamic reasoning fallback that parses financial entities and runs MCP tools deterministically so the system never crashes or hangs during local development, demoing, or unit testing.

### Q4: How are user API keys secured?
> **Answer:** User API keys for Gemini, OpenAI, Claude, and Groq are encrypted using Fernet symmetric encryption with the application's secret key (`app/config.py`) before being stored in the `api_keys` table.

### Q5: How was this verified?
> **Answer:** We created a comprehensive test suite `scripts/test_agent_scenarios.py` containing 14 automated test scenarios covering every intent, skill, confirmation branch, and database history recovery. All 14 tests pass with 100% success.

---

## 🧪 6. Automated Test Verification Results

Run test suite:
```bash
uv run python scripts/test_agent_scenarios.py
```

```
🚀 Initializing Database and Seeding Demo Data...
--- Test 1: Expense Logging --- Passed!
--- Test 2: Income Logging --- Passed!
--- Test 3: Small Transfer (Immediate) --- Passed!
--- Test 4: Large Transfer - Human-in-the-Loop Confirmation (Confirm) --- Passed!
--- Test 5: Large Transfer - Human-in-the-Loop Cancellation (Cancel) --- Passed!
--- Test 6: Balance & Tank Query --- Passed!
--- Test 7: Spending Breakdown Query --- Passed!
--- Test 8: Budget Alert Skill --- Passed!
--- Test 9: Recurring Bills Skill --- Passed!
--- Test 10: Emergency Fund Runway Skill --- Passed!
--- Test 11: Reduce Money Mode / Financial Advice --- Passed!
--- Test 12: Save API Key --- Passed!
--- Test 13: Help & Greeting --- Passed!
--- Test 14: Permanent Full Conversation History in DB --- Passed! (30+ messages restored)

✅ ALL 14 TEST SCENARIOS PASSED SUCCESSFULLY!
```

---

## 📂 7. Files Changed in this PR

- **`app/bot/agent.py`**: Complete LangGraph StateGraph agent, LLM tool definitions, confirmation store, and DB history hooks.
- **`app/models.py`**: Added `ChatMessage` SQLAlchemy model and relationship on `User`.
- **`app/services_ai/ai_gateway.py`**: Implemented `ask_llm` contract, round-robin key decryption, and LiteLLM provider routing.
- **`SDLC_AND_SCHEMA.md`**: Documented `chat_messages` table and contract specifications.
- **`scripts/test_agent_scenarios.py`**: End-to-end automated integration test suite for Role 2.
- **`ROLE_2_IMPLEMENTATION_SUMMARY.md`**: Team hand-off and architectural documentation.

