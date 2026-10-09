"""Tests for Role 2: LangGraph agent (confirmations, chat keys, personas, history, offline mode).

Offline only - litellm.acompletion is mocked, no real LLM calls are made.
Run with:  uv run python -m unittest discover -s tests -v
"""

import os
import tempfile

# Point the app at a throwaway SQLite DB *before* any app module is imported.
_TMP_DIR = tempfile.mkdtemp(prefix="walletledger-agent-test-")
os.environ["DYNAMIC_MODELS"] = "false"  # tests never hit provider model-list APIs
os.environ.setdefault(
    "DATABASE_URL", "sqlite:///" + os.path.join(_TMP_DIR, "test.db").replace("\\", "/")
)
_KEY_VARS = (
    "GEMINI_API_KEYS",
    "OPENAI_API_KEYS",
    "ANTHROPIC_API_KEYS",
    "GROQ_API_KEYS",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GROQ_API_KEY",
)

import asyncio  # noqa: E402
import json  # noqa: E402
import unittest  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from unittest.mock import AsyncMock, patch  # noqa: E402

import litellm  # noqa: E402

from app.bot import agent  # noqa: E402
from app.db import SessionLocal, engine, init_db  # noqa: E402
from app.models import ApiKey, ChatMessage, User  # noqa: E402
from app.services_ai import ai_gateway as gw  # noqa: E402
from app.services_ai.mcp_server import execute_tool  # noqa: E402

AQ_KEY = "AQ.Ab8RN6" + "x" * 40 + "YOQw"
AQ_KEY_2 = "AQ.Ab8RN6" + "y" * 40 + "eDzg"
AIZA_KEY = "AIza" + "B" * 35


def text_response(text: str) -> SimpleNamespace:
    message = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def tool_response(name: str, args: dict) -> SimpleNamespace:
    call = SimpleNamespace(function=SimpleNamespace(name=name, arguments=json.dumps(args)))
    message = SimpleNamespace(content=None, tool_calls=[call])
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def run(coro):
    return asyncio.run(coro)


def chat(chat_id: str, text: str) -> str:
    return run(agent.process_user_interaction(chat_id, text))


class AgentTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    @classmethod
    def tearDownClass(cls):
        engine.dispose()

    def setUp(self):
        self.chat_id = f"test-{uuid.uuid4().hex[:10]}"
        gw.reset_rotation_state()
        self.env = patch.dict(os.environ, {}, clear=False)
        self.env.start()
        for var in _KEY_VARS:
            os.environ.pop(var, None)
        agent.session_store.clear_pending(self.chat_id)
        execute_tool("log_income", user_id=self.chat_id, amount=50000, source_account="Bank")

    def tearDown(self):
        self.env.stop()

    def add_key(self):
        gw.add_api_key(self.chat_id, "gemini", AIZA_KEY)

    def balances(self) -> dict[str, float]:
        result = execute_tool("get_pipe_balances", user_id=self.chat_id)
        return {a["name"]: a["balance"] for a in result["accounts"]}


class TestConfirmationFlow(AgentTestCase):
    """Fix 1: a yes/no reply to a pending transfer must work with or without the AI."""

    def test_yes_executes_transfer_without_ai(self):
        reply = chat(self.chat_id, "Transfer 10000 from Bank to Cash")
        self.assertIn("Confirmation Required", reply)
        self.assertEqual(self.balances()["Bank"], 50000)
        reply = chat(self.chat_id, "yes")
        self.assertIn("Transfer Successful", reply)
        self.assertEqual(self.balances()["Bank"], 40000)
        self.assertEqual(self.balances()["Cash"], 10000)

    def test_no_cancels_transfer(self):
        chat(self.chat_id, "Transfer 10000 from Bank to Cash")
        reply = chat(self.chat_id, "No")
        self.assertIn("Cancelled", reply)
        self.assertEqual(self.balances()["Bank"], 50000)
        self.assertIsNone(agent.session_store.get_pending(self.chat_id))

    def test_yes_with_ai_key_skips_ai_and_executes(self):
        self.add_key()
        transfer = tool_response(
            "transfer_funds", {"amount": 10000, "from_account": "Bank", "to_account": "Cash"}
        )
        with patch.object(litellm, "acompletion", AsyncMock(return_value=transfer)) as mock:
            reply = chat(self.chat_id, "move ten thousand from bank to cash")
            self.assertIn("Confirmation Required", reply)
            self.assertEqual(mock.await_count, 1)
            reply = chat(self.chat_id, "Yes!")
            self.assertEqual(mock.await_count, 1, "a yes/no reply must not call the AI")
        self.assertIn("Transfer Successful", reply)
        self.assertEqual(self.balances()["Bank"], 40000)

    def test_unrelated_message_cancels_pending(self):
        chat(self.chat_id, "Transfer 10000 from Bank to Cash")
        chat(self.chat_id, "what is my balance")
        self.assertIsNone(agent.session_store.get_pending(self.chat_id))
        reply = chat(self.chat_id, "yes")
        self.assertNotIn("Transfer Successful", reply)
        self.assertEqual(self.balances()["Bank"], 50000)

    def test_expired_confirmation_is_ignored(self):
        chat(self.chat_id, "Transfer 10000 from Bank to Cash")
        pending = agent.session_store.get_session(self.chat_id).pending_action
        pending["created_at"] = (datetime.utcnow() - timedelta(minutes=6)).isoformat()
        reply = chat(self.chat_id, "yes")
        self.assertNotIn("Transfer Successful", reply)
        self.assertEqual(self.balances()["Bank"], 50000)

    def test_small_transfer_runs_immediately(self):
        reply = chat(self.chat_id, "Transfer 500 from Bank to Cash")
        self.assertIn("Transfer Successful", reply)

    def test_classify_reply(self):
        self.assertEqual(agent.classify_reply(" OK. "), "confirmed")
        self.assertEqual(agent.classify_reply("go ahead"), "confirmed")
        self.assertEqual(agent.classify_reply("nope"), "cancelled")
        self.assertIsNone(agent.classify_reply("yes but only 5000"))


class TestApiKeysInChat(AgentTestCase):
    """Fix 2: AQ./AIza keys pasted in chat are stored encrypted and never sent to an AI."""

    def test_aq_key_saved_masked_and_encrypted(self):
        with (
            patch.object(litellm, "acompletion", AsyncMock()) as mock,
            patch.object(gw, "validate_api_key", AsyncMock(return_value=gw.KeyCheck("valid"))),
        ):
            reply = chat(self.chat_id, f"my gemini key is {AQ_KEY}")
        mock.assert_not_awaited()
        self.assertIn("works. Saved", reply)
        self.assertIn(gw.mask_key(AQ_KEY), reply)
        self.assertNotIn(AQ_KEY, reply)
        self.assertEqual(gw.get_user_api_keys(self.chat_id), [("gemini", AQ_KEY)])

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.telegram_chat_id == self.chat_id).one()
            stored = db.query(ApiKey).filter(ApiKey.user_id == user.id).one()
            self.assertNotIn(AQ_KEY, stored.encrypted_key)
            history = " ".join(m.content for m in db.query(ChatMessage).filter_by(user_id=user.id))
            self.assertNotIn(AQ_KEY, history, "raw key must not be kept in chat history")
        finally:
            db.close()

    def test_multiple_keys_and_no_expense_logged(self):
        with patch.object(gw, "validate_api_key", AsyncMock(return_value=gw.KeyCheck("valid"))):
            reply = chat(self.chat_id, f"keys: {AQ_KEY}, {AQ_KEY_2}")
        self.assertEqual(reply.count("works. Saved"), 2)
        self.assertEqual(len(gw.get_user_api_keys(self.chat_id)), 2)
        self.assertEqual(self.balances()["Bank"], 50000)

    def test_next_message_uses_ai(self):
        with patch.object(gw, "validate_api_key", AsyncMock(return_value=gw.KeyCheck("valid"))):
            chat(self.chat_id, AQ_KEY)
        with patch.object(
            litellm, "acompletion", AsyncMock(return_value=text_response("Hi from AI"))
        ) as mock:
            reply = chat(self.chat_id, "hello there")
        self.assertEqual(mock.call_args.kwargs["api_key"], AQ_KEY)
        self.assertIn("Hi from AI", reply)


class TestPersonas(AgentTestCase):
    """Fix 3: advice/report tool results are written by the matching prompts.py persona."""

    def test_summary_request_uses_summary_persona(self):
        self.add_key()
        responses = [
            tool_response("get_spending_breakdown", {"period": "month"}),
            text_response("• 💸 Spent ₹0 this month"),
        ]
        with patch.object(litellm, "acompletion", AsyncMock(side_effect=responses)) as mock:
            reply = chat(self.chat_id, "Give me a quick summary of my spending")
        self.assertIn("Quick Summary", reply)
        self.assertIn("Spent ₹0", reply)
        system = mock.call_args_list[1].kwargs["messages"][0]["content"]
        self.assertIn("Quick Summary", system)
        self.assertIn("total_expenses", system, "tool data must be passed as context")

    def test_budgeter_command(self):
        self.add_key()
        with patch.object(
            litellm, "acompletion", AsyncMock(return_value=text_response("1. Cut Swiggy"))
        ) as mock:
            reply = chat(self.chat_id, "/budgeter I overspent")
        self.assertEqual(mock.await_count, 1, "/budgeter skips intent detection")
        self.assertIn("Ruthless Budgeter", reply)
        self.assertIn("1. Cut Swiggy", reply)

    def test_no_key_falls_back_to_template(self):
        reply = chat(self.chat_id, "How can I save money?")
        self.assertIn("Reduce Money Mode", reply)

    def test_persona_failure_falls_back_to_template(self):
        self.add_key()
        responses = [tool_response("financial_advice_bundle", {}), RuntimeError("boom")]
        with (
            patch.object(litellm, "acompletion", AsyncMock(side_effect=responses)),
            self.assertLogs("app.bot.agent", level="WARNING"),
        ):
            reply = chat(self.chat_id, "give me financial advice")
        self.assertIn("Reduce Money Mode", reply)

    def test_ledger_confirmations_stay_templates(self):
        self.add_key()
        expense = tool_response("log_expense", {"amount": 200, "category": "Food"})
        with patch.object(litellm, "acompletion", AsyncMock(return_value=expense)) as mock:
            reply = chat(self.chat_id, "spent 200 on food")
        self.assertEqual(mock.await_count, 1)
        self.assertIn("Expense Recorded", reply)


class TestHistoryAndOfflineMode(AgentTestCase):
    """Fix 4: no duplicate message, bounded history, honest offline mode."""

    def test_ai_is_called_with_message_once(self):
        self.add_key()
        with patch.object(
            litellm, "acompletion", AsyncMock(return_value=text_response("ok"))
        ) as mock:
            chat(self.chat_id, "first message")
            chat(self.chat_id, "second message")
        self.assertEqual(mock.await_count, 2, "agent must call the AI when a key exists")
        contents = [m["content"] for m in mock.call_args.kwargs["messages"]]
        self.assertEqual(contents.count("second message"), 1)
        self.assertEqual(contents[-1], "second message")
        self.assertIn("first message", contents)

    def test_history_is_limited(self):
        for i in range(30):
            agent.save_db_chat_message(self.chat_id, "user", f"old message {i}")
        history = agent.get_db_conversation_history(self.chat_id, limit=agent.HISTORY_LIMIT)
        self.assertEqual(len(history), agent.HISTORY_LIMIT)
        self.assertEqual(history[-1].content, "old message 29")

    def test_ai_failure_reports_offline_mode(self):
        self.add_key()
        error = litellm.AuthenticationError("invalid key", llm_provider="gemini", model="g")
        with (
            patch.object(litellm, "acompletion", AsyncMock(side_effect=error)),
            self.assertLogs("app.bot.agent", level="WARNING") as logs,
        ):
            reply = chat(self.chat_id, "what is my balance")
        self.assertIn("Offline mode", reply)
        self.assertIn("Tank", reply)
        self.assertTrue(any("AI unavailable" in line for line in logs.output))

    def test_no_key_has_no_offline_note(self):
        reply = chat(self.chat_id, "what is my balance")
        self.assertNotIn("Offline mode", reply)


if __name__ == "__main__":
    unittest.main()
