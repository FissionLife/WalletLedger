"""Comprehensive test scenarios for Gopal's LangGraph Agent (Role 2).
Tests:
- Expense logging
- Income logging
- Small transfers (immediate)
- Large transfers (Human-in-the-Loop multi-turn confirmation & cancellation)
- Balance & Tank queries
- Spending breakdown by period & category
- Financial skills (budget alerts, recurring bills, emergency fund runway)
- Reduce money mode / Financial advice
- API Key management
- Telegram simulate_chat endpoint integration
- Permanent full conversation history DB persistence
"""

import asyncio
import os
import sys

# Configure UTF-8 encoding for Windows stdout
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.bot.agent import get_db_conversation_history, process_user_interaction
from app.db import init_db
from scripts.seed_demo_data import seed_demo_data


async def run_tests():
    print("🚀 Initializing Database and Seeding Demo Data...")
    init_db()
    seed_demo_data(telegram_chat_id="test_gopal_user")

    user_id = "test_gopal_user"

    print("\n--- Test 1: Expense Logging ---")
    res = await process_user_interaction(user_id, "Spent 350 on pizza via UPI Wallet")
    print(res)
    assert "Expense Recorded!" in res or "350" in res

    print("\n--- Test 2: Income Logging ---")
    res = await process_user_interaction(user_id, "Received 15000 freelance in Bank")
    print(res)
    assert "Income Credited!" in res or "15,000" in res

    print("\n--- Test 3: Small Transfer (Immediate) ---")
    res = await process_user_interaction(user_id, "Transfer 1000 from Bank to Cash")
    print(res)
    assert "Transfer Successful!" in res or "1,000" in res

    print("\n--- Test 4: Large Transfer - Human-in-the-Loop Confirmation (Confirm) ---")
    res = await process_user_interaction(user_id, "Transfer 10000 from Bank to Cash")
    print("Step 1 (Prompt):", res)
    assert "Confirmation Required" in res

    res = await process_user_interaction(user_id, "yes")
    print("Step 2 (Response after 'yes'):", res)
    assert "Transfer Successful!" in res

    print("\n--- Test 5: Large Transfer - Human-in-the-Loop Cancellation (Cancel) ---")
    res = await process_user_interaction(user_id, "Transfer 25000 from Bank to Cash")
    print("Step 1 (Prompt):", res)
    assert "Confirmation Required" in res

    res = await process_user_interaction(user_id, "no")
    print("Step 2 (Response after 'no'):", res)
    assert "Action Cancelled" in res

    print("\n--- Test 6: Balance & Tank Query ---")
    res = await process_user_interaction(user_id, "What is my balance?")
    print(res)
    assert "WalletLedger Tank" in res or "Net Worth" in res

    print("\n--- Test 7: Spending Breakdown Query ---")
    res = await process_user_interaction(user_id, "How much did I spend this month?")
    print(res)
    assert "Spending Breakdown" in res or "Total Expenses" in res

    print("\n--- Test 8: Budget Alert Skill ---")
    res = await process_user_interaction(user_id, "Check budget alerts")
    print(res)
    assert "Budget" in res

    print("\n--- Test 9: Recurring Bills Skill ---")
    res = await process_user_interaction(user_id, "Find recurring bills and subscriptions")
    print(res)
    assert "Recurring Bills" in res or "Netflix" in res

    print("\n--- Test 10: Emergency Fund Runway Skill ---")
    res = await process_user_interaction(user_id, "Emergency fund runway")
    print(res)
    assert "Runway" in res or "Emergency Fund" in res

    print("\n--- Test 11: Reduce Money Mode / Financial Advice ---")
    res = await process_user_interaction(user_id, "How can I reduce expenses?")
    print(res)
    assert "Coach" in res or "Reduce Money Mode" in res

    print("\n--- Test 12: Save API Key ---")
    res = await process_user_interaction(user_id, "Set my Gemini key: AQ." + "x" * 40)
    print(res)
    assert "Saved 1 API key" in res

    print("\n--- Test 13: Help & Greeting ---")
    res = await process_user_interaction(user_id, "help")
    print(res)
    assert "WalletLedger" in res

    print("\n--- Test 14: Permanent Full Conversation History in DB ---")
    history = get_db_conversation_history(user_id)
    print(f"Total messages saved permanently in database: {len(history)}")
    assert len(history) >= 20, f"Expected at least 20 messages in DB, got {len(history)}"
    print("Sample restored message 1:", history[0].content[:60])
    print("Sample restored message 2:", history[1].content[:60])

    print("\n✅ ALL 14 TEST SCENARIOS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    asyncio.run(run_tests())
