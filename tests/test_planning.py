"""Savings plans, the /plan command and the multi-step helper. Offline: the AI is faked."""

import os

os.environ["WALLETLEDGER_TESTING"] = "1"
os.environ["LITELLM_MODE"] = "PRODUCTION"
import tempfile

_TMP_DIR = tempfile.mkdtemp(prefix="walletledger-planning-test-")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_TMP_DIR, "test.db").replace("\\", "/")
os.environ["DYNAMIC_MODELS"] = "false"
os.environ["TELEGRAM_BOT_TOKEN"] = ""
for _var in ("GEMINI_API_KEYS", "GEMINI_API_KEY", "OPENAI_API_KEYS", "GROQ_API_KEYS"):
    os.environ[_var] = ""

import asyncio  # noqa: E402
import itertools  # noqa: E402
import json  # noqa: E402
import unittest  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from unittest.mock import patch  # noqa: E402

from app.bot import agent, nlu, orchestrator  # noqa: E402
from app.bot import main as bot  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.services import analytics, ledger  # noqa: E402
from app.services_ai import ai_gateway as gw  # noqa: E402
from app.services_ai.mcp_server import execute_tool  # noqa: E402

init_db()
_ids = itertools.count(1)
KEY = "AIza" + "P" * 35


def run(coro):
    return asyncio.run(coro)


def seed(chat: str, income=60000.0, spend_cats=None):
    """Three months of salary and spending, so the plan has real numbers."""
    spend_cats = spend_cats or {"Shopping": 9000.0, "Entertainment": 6000.0, "Rent": 15000.0}
    with SessionLocal() as db:
        uid = ledger.get_or_create_user(db, chat).id
        for m in range(3):
            when = datetime.now() - timedelta(days=10 + 30 * m)
            if income:
                ledger.record_transaction(
                    db, uid, income, "Bank", "Salary", tx_type="income", created_at=when
                )
            for cat, amount in spend_cats.items():
                ledger.record_transaction(
                    db, uid, amount, "Bank", cat, tx_type="expense", created_at=when
                )
    return uid


def fake_call(name, args, call_id="c1"):
    return SimpleNamespace(
        id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(args))
    )


def fake_reply(content="", calls=None):
    msg = SimpleNamespace(content=content, tool_calls=calls or [])
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def scripted(*replies):
    """A stand-in for the AI that answers with the given replies in order."""
    queue = list(replies)
    seen = []

    async def complete(user_id, messages, **kw):
        seen.append((list(messages), kw))
        return queue.pop(0)

    complete.seen = seen
    return complete


class GoalParsingTests(unittest.TestCase):
    def test_goals_are_understood(self):
        cases = {
            "50000 in 6 months": (50000, 6),
            "50k 6": (50000, 6),
            "2 lakh in 1 year": (200000, 12),
            "save ₹1,20,000 in 8 months": (120000, 8),
            "30000 in 12 weeks": (30000, 3),
        }
        for text, expected in cases.items():
            self.assertEqual(nlu.parse_goal(text), expected, text)

    def test_unclear_goals_are_not_guessed(self):
        for text in ("", "hello", "6 months", "50000", "50000 600000"):
            self.assertIsNone(nlu.parse_goal(text), text)

    def test_saving_sentences_open_the_plan_screen(self):
        screen = nlu.detect_screen("I want to save 50000 in 6 months")
        self.assertEqual((screen.command, screen.args), ("/plan", "50000 6"))
        self.assertEqual(nlu.detect_screen("Can I save 2 lakh in 1 year?").args, "200000 12")

    def test_logging_sentences_are_not_plans(self):
        self.assertIsNone(nlu.detect_screen("saved 500 by buying a pass, spent 200 on tea"))
        self.assertIsNone(nlu.detect_screen("I want to save money"))


class QuestionTests(unittest.TestCase):
    def test_questions_are_never_logged(self):
        for text in (
            "is 640 too much for dinner?",
            "Is 5000 a lot to spend on a phone?",
            "Should I buy a 3000 jacket",
            "can I afford 20000 for a trip",
            "I just ate out for 640, is that too much compared to my usual?",
            "what if I spend 500 less on food",
        ):
            self.assertTrue(nlu.is_question(text), text)
            self.assertEqual(nlu.parse_entries(text), [], text)

    def test_statements_still_log(self):
        for text in (
            "Spent 450 on dinner via Bank",
            "paid 300 to my landlord",
            "Received 60000 salary",
            "Spent 200 on chai, 80 on auto",
        ):
            self.assertFalse(nlu.is_question(text), text)
            self.assertTrue(nlu.parse_entries(text), text)

    def test_offline_question_gets_a_hint_not_a_log(self):
        chat = f"q-{next(_ids)}"
        reply = run(bot.handle_text(chat, "is 640 too much for dinner?"))
        self.assertIn("didn't record anything", reply)
        with SessionLocal() as db:
            uid = ledger.get_or_create_user(db, chat).id
            rows, _ = ledger.recent_transactions(db, uid, 5)
        self.assertEqual(rows, [])


class SavingsPlanTests(unittest.TestCase):
    def setUp(self):
        self.chat = f"plan-{next(_ids)}"

    def test_on_track(self):
        uid = seed(self.chat)  # 60000 in, 30000 out -> +30000 a month
        with SessionLocal() as db:
            p = analytics.savings_plan(db, uid, 60000, 6)
        self.assertTrue(p["on_track"])
        self.assertEqual(p["needed_per_month"], 10000)
        self.assertAlmostEqual(p["avg_surplus"], 30000, delta=1)
        self.assertEqual(p["suggested_cuts"], [])

    def test_short_gets_cuts_from_flexible_categories_only(self):
        uid = seed(self.chat, income=32000)  # +2000 a month
        with SessionLocal() as db:
            p = analytics.savings_plan(db, uid, 60000, 6)  # needs 10000
        self.assertFalse(p["on_track"])
        self.assertAlmostEqual(p["gap_per_month"], 8000, delta=1)
        names = {c["category"] for c in p["suggested_cuts"]}
        self.assertTrue(names <= {"Shopping", "Entertainment"})
        self.assertNotIn("Rent", names)
        for c in p["suggested_cuts"]:
            self.assertLessEqual(c["percent"], 40.01)
        self.assertGreater(p["still_short"], 0)

    def test_no_income_is_said_plainly(self):
        uid = seed(self.chat, income=0)
        with SessionLocal() as db:
            p = analytics.savings_plan(db, uid, 1000, 2)
        self.assertFalse(p["has_income_data"])
        self.assertIn("income", run(bot.handle_text(self.chat, "/plan 1000 2")))

    def test_bad_input_is_refused(self):
        with SessionLocal() as db:
            uid = ledger.get_or_create_user(db, self.chat).id
            for target, months in ((0, 3), (100, 0), (-5, 3)):
                with self.assertRaises(ValueError):
                    analytics.savings_plan(db, uid, target, months)

    def test_snapshot_has_the_basics(self):
        uid = seed(self.chat)
        with SessionLocal() as db:
            s = analytics.financial_snapshot(db, uid, 60)
        for key in ("spent", "earned", "top_categories", "budgets", "money_now", "insights"):
            self.assertIn(key, s)
        self.assertGreater(s["spent"], 0)


class PlanCommandTests(unittest.TestCase):
    def setUp(self):
        self.chat = f"plancmd-{next(_ids)}"

    def say(self, text):
        return run(bot.handle_incoming(self.chat, text))

    def test_command_and_sentence_give_the_same_answer(self):
        seed(self.chat, income=32000)
        by_command = self.say("/plan 60000 6")
        by_sentence = self.say("I want to save 60000 in 6 months")
        self.assertEqual(by_command.text, by_sentence.text)
        self.assertIn("Save ₹60,000 in 6 months", by_command.text)
        self.assertIn("Short by", by_command.text)
        self.assertIn("Shopping", by_command.text)

    def test_on_track_message(self):
        seed(self.chat)
        self.assertIn("On track", self.say("/plan 60000 6").text)

    def test_usage_when_unclear(self):
        self.assertIn("/plan 50000 6", self.say("/plan").text)
        self.assertIn("/plan 50000 6", self.say("/plan soon").text)

    def test_plan_is_in_the_menu(self):
        self.assertIn("plan", dict(bot.COMMAND_MENU))
        self.assertLessEqual(len(bot.COMMAND_MENU), 100)


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.chat = f"tools-{next(_ids)}"
        seed(self.chat)

    def test_plan_tool(self):
        res = execute_tool("savings_plan", user_id=self.chat, target_amount=30000, months=3)
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["on_track"])

    def test_snapshot_tool_clamps_days(self):
        res = execute_tool("get_financial_snapshot", user_id=self.chat, days=99999)
        self.assertEqual(res["status"], "success")

    def test_both_tools_are_offered_to_the_ai(self):
        names = {t["function"]["name"] for t in agent.TOOLS_SCHEMA}
        self.assertTrue({"savings_plan", "get_financial_snapshot"} <= names)


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.chat = f"orch-{next(_ids)}"
        seed(self.chat)

    def go(self, *replies, message="Can I afford a 50000 laptop in 5 months?"):
        ai = scripted(*replies)
        with patch.object(gw, "complete", ai):
            res = run(
                orchestrator.run(
                    self.chat,
                    message,
                    [],
                    tools=agent.TOOLS_SCHEMA,
                    system_prompt="test",
                    transfer_threshold=5000,
                )
            )
        return res, ai

    def test_looks_complex(self):
        self.assertTrue(orchestrator.looks_complex("Can I afford a new phone this month?"))
        self.assertFalse(orchestrator.looks_complex("hi"))
        self.assertFalse(orchestrator.looks_complex("Spent 450 on dinner via Bank"))

    def test_plain_answer_needs_no_tools(self):
        res, _ = self.go(fake_reply("Sure, ask away."))
        self.assertEqual(res.text, "Sure, ask away.")
        self.assertEqual(res.tools_run, 0)

    def test_looks_up_then_answers(self):
        res, ai = self.go(
            fake_reply(calls=[fake_call("savings_plan", {"target_amount": 50000, "months": 5})]),
            fake_reply("Yes. You keep about ₹30,000 a month."),
        )
        self.assertEqual(res.text, "Yes. You keep about ₹30,000 a month.")
        self.assertEqual(res.tools_run, 1)
        self.assertFalse(res.wrote)
        second_round = ai.seen[1][0]
        tool_msg = [m for m in second_round if m["role"] == "tool"][0]
        self.assertIn("needed_per_month", tool_msg["content"])

    def test_writes_run_for_this_user_even_if_the_ai_names_another(self):
        args = {
            "amount": 120,
            "category": "Food",
            "account_name": "Bank",
            "user_id": "someone-else",
        }
        res, _ = self.go(
            fake_reply(calls=[fake_call("log_expense", args)]), fake_reply("Logged it.")
        )
        self.assertTrue(res.wrote)
        self.assertEqual(res.tool_results[0]["tool_args"]["user_id"], self.chat)
        with SessionLocal() as db:
            self.assertEqual(
                db.scalar(
                    __import__("sqlalchemy").text(
                        "select count(*) from transactions where amount=120 and user_id=:u"
                    ),
                    {"u": ledger.get_or_create_user(db, self.chat).id},
                ),
                1,
            )

    def test_key_saving_tool_is_never_available(self):
        ai = scripted(fake_reply("ok"))
        with patch.object(gw, "complete", ai):
            run(
                orchestrator.run(
                    self.chat,
                    "x",
                    [],
                    tools=agent.TOOLS_SCHEMA,
                    system_prompt="",
                    transfer_threshold=1,
                )
            )
        offered = {t["function"]["name"] for t in ai.seen[0][1]["tools"]}
        self.assertNotIn("save_user_api_key", offered)
        res, _ = self.go(
            fake_reply(
                calls=[fake_call("save_user_api_key", {"provider": "gemini", "api_key": KEY})]
            ),
            fake_reply("done"),
        )
        self.assertEqual(res.tools_run, 0)

    def test_big_transfer_waits_for_yes(self):
        res, _ = self.go(
            fake_reply(
                calls=[
                    fake_call(
                        "transfer_funds",
                        {"from_account": "Bank", "to_account": "Cash", "amount": 9000},
                    )
                ]
            )
        )
        self.assertIsNotNone(res.pending)
        self.assertEqual(res.tools_run, 0)
        with SessionLocal() as db:
            uid = ledger.get_or_create_user(db, self.chat).id
            bank = ledger.get_account_balances(db, uid)["accounts"]
        self.assertTrue(all(a["name"] != "Cash" or a["balance"] == 0 for a in bank))

    def test_small_transfer_runs(self):
        res, _ = self.go(
            fake_reply(
                calls=[
                    fake_call(
                        "transfer_funds",
                        {"from_account": "Bank", "to_account": "Cash", "amount": 500},
                    )
                ]
            ),
            fake_reply("Moved."),
        )
        self.assertIsNone(res.pending)
        self.assertTrue(res.wrote)

    def test_step_limit(self):
        loop = [
            fake_reply(calls=[fake_call("get_pipe_balances", {}, f"c{i}")])
            for i in range(orchestrator.MAX_STEPS)
        ]
        res, _ = self.go(*loop)
        self.assertIn("smaller parts", res.text)
        self.assertEqual(res.tools_run, orchestrator.MAX_STEPS)

    def test_ai_failure_before_writing_raises_for_fallback(self):
        async def boom(*a, **k):
            raise gw.AllKeysExhaustedError([])

        with patch.object(gw, "complete", boom), self.assertRaises(gw.AllKeysExhaustedError):
            run(
                orchestrator.run(
                    self.chat,
                    "x",
                    [],
                    tools=agent.TOOLS_SCHEMA,
                    system_prompt="",
                    transfer_threshold=1,
                )
            )

    def test_ai_failure_after_writing_keeps_the_result(self):
        with SessionLocal() as db:
            uid = ledger.get_or_create_user(db, self.chat).id
            ledger.record_transaction(db, uid, 1000, "Cash", "Seed", tx_type="income")
        calls = iter(
            [fake_reply(calls=[fake_call("log_expense", {"amount": 77, "category": "Food"})])]
        )

        async def flaky(*a, **k):
            try:
                return next(calls)
            except StopIteration:
                raise gw.AllKeysExhaustedError([]) from None

        with patch.object(gw, "complete", flaky):
            res = run(
                orchestrator.run(
                    self.chat,
                    "x",
                    [],
                    tools=agent.TOOLS_SCHEMA,
                    system_prompt="",
                    transfer_threshold=1e9,
                )
            )
        self.assertTrue(res.wrote)
        self.assertIn("recorded", res.text)


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        gw.reset_rotation_state()
        self.chat = f"e2e-{next(_ids)}"
        seed(self.chat)

    def say(self, text):
        return run(bot.handle_incoming(self.chat, text))

    def with_key(self):
        async def ok(**kw):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="OK"))])

        with patch.object(gw.litellm, "acompletion", ok):
            run(bot.handle_text(self.chat, f"/setkey {KEY}"))

    def test_complex_question_uses_the_helper_and_replies(self):
        self.with_key()
        ai = scripted(
            fake_reply(calls=[fake_call("get_financial_snapshot", {"days": 30})]),
            fake_reply("You are doing fine: you keep about half of what you earn."),
        )
        with patch.object(gw, "complete", ai):
            reply = self.say("How am I doing this month, should I worry about anything?")
        self.assertIn("doing fine", reply.text)
        self.assertEqual(len(ai.seen), 2)

    def test_helper_logs_show_the_compact_line_and_an_undo_button(self):
        self.with_key()
        ai = scripted(
            fake_reply(
                calls=[
                    fake_call(
                        "log_expense",
                        {"amount": 640, "category": "Food & Dining", "account_name": "Bank"},
                    )
                ]
            ),
            fake_reply("Logged. That is a bit above your usual food spend."),
        )
        with patch.object(gw, "complete", ai):
            reply = self.say("I just ate out for 640, is that too much compared to my usual?")
        self.assertIn("−₹640", reply.text)
        self.assertIn("usual food spend", reply.text)
        self.assertTrue(reply.rows)  # undo button

    def test_big_transfer_asks_for_confirmation_then_runs(self):
        self.with_key()
        ai = scripted(
            fake_reply(
                calls=[
                    fake_call(
                        "transfer_funds",
                        {"from_account": "Bank", "to_account": "Cash", "amount": 9000},
                    )
                ]
            )
        )
        with patch.object(gw, "complete", ai):
            first = self.say("Please move some money to cash so I can afford the trip next week")
        self.assertIn("Transfer ₹9,000", first.text)
        done = self.say("yes")
        self.assertIn("9,000", done.text)

    def test_helper_failure_falls_back_to_the_simple_path(self):
        self.with_key()

        async def boom(*a, **k):
            raise gw.AllKeysExhaustedError([])

        with patch.object(gw, "complete", boom), patch.object(gw.litellm, "acompletion", boom):
            reply = self.say("How am I doing this month, should I worry about anything?")
        self.assertTrue(reply.text)  # offline rules answered; no crash

    def test_clear_messages_never_reach_the_helper(self):
        self.with_key()

        async def never(*a, **k):
            raise AssertionError("AI must not be called for a clear message")

        with patch.object(gw, "complete", never):
            reply = self.say("Spent 450 on dinner via Bank")
        self.assertIn("−₹450", reply.text)


if __name__ == "__main__":
    unittest.main()
