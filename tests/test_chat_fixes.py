"""Regression tests for the chat-logic audit: reading messages, confirmations, buttons, keys. Offline."""

import os

os.environ["WALLETLEDGER_TESTING"] = "1"
os.environ["LITELLM_MODE"] = "PRODUCTION"
import tempfile

_TMP_DIR = tempfile.mkdtemp(prefix="walletledger-chatfix-test-")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_TMP_DIR, "test.db").replace("\\", "/")
os.environ["DYNAMIC_MODELS"] = "false"
os.environ["TELEGRAM_BOT_TOKEN"] = ""
for _var in ("GEMINI_API_KEYS", "GEMINI_API_KEY", "OPENAI_API_KEYS", "GROQ_API_KEYS"):
    os.environ[_var] = ""

import asyncio  # noqa: E402
import itertools  # noqa: E402
import json  # noqa: E402
import unittest  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from unittest.mock import patch  # noqa: E402

from app.bot import agent, nlu, ui  # noqa: E402
from app.bot import main as bot  # noqa: E402
from app.bot.callbacks import handle_callback  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.services import ledger  # noqa: E402
from app.services_ai import ai_gateway as gw  # noqa: E402

init_db()
_ids = itertools.count(1)


def run(coro):
    return asyncio.run(coro)


def chat():
    return f"cf-{next(_ids)}"


def balance(chat_id, account):
    with SessionLocal() as db:
        uid = ledger.get_or_create_user(db, chat_id).id
        for a in ledger.get_account_balances(db, uid)["accounts"]:
            if a["name"] == account:
                return a["balance"]
    return None


def entries(text, accounts=("Bank", "Cash", "HDFC Bank")):
    ctx = nlu.Context(
        accounts=list(accounts), default_expense_account="Cash", default_income_account="Bank"
    )
    return [(e.kind, e.amount) for e in nlu.parse_entries(text, ctx)]


class MessageReadingTests(unittest.TestCase):
    def test_a_purchase_is_not_income_just_because_it_starts_with_got(self):
        self.assertEqual(entries("got petrol 500"), [("expense", 500.0)])
        self.assertEqual(entries("got new shoes 2000"), [("expense", 2000.0)])
        self.assertEqual(entries("got 5000 from dad"), [("income", 5000.0)])

    def test_income_never_leaks_into_the_next_item_on_a_line(self):
        self.assertEqual(
            entries("salary 50000, bonus 5000, rent 15000, food 6000"),
            [("income", 50000.0), ("income", 5000.0), ("expense", 15000.0), ("expense", 6000.0)],
        )

    def test_money_coming_in_is_income(self):
        for text, amount in (
            ("ravi paid me 500", 500.0),
            ("mom gave me 1000", 1000.0),
            ("sold old phone for 8000", 8000.0),
            ("gift from mom 1000", 1000.0),
            ("deposited 5000 in bank", 5000.0),
        ):
            self.assertEqual(entries(text), [("income", amount)], text)

    def test_plans_negations_and_facts_are_not_logged(self):
        for text in (
            "remind me to pay 500 tomorrow",
            "I will spend 500 tomorrow",
            "didn't spend 500",
            "never spent 500 on this",
            "my salary is 80000",
            "ravi owes me 500",
            "order #12345",
        ):
            self.assertEqual(entries(text), [], text)

    def test_statements_that_start_like_questions_are_logged(self):
        self.assertEqual(entries("Was at Dmart, paid 1500 for groceries"), [("expense", 1500.0)])
        self.assertEqual(entries("What a day! spent 200 on chai"), [("expense", 200.0)])
        self.assertEqual(entries("Can't believe I spent 800 on pizza"), [("expense", 800.0)])
        self.assertTrue(nlu.is_question("Should I buy a 3000 jacket"))
        self.assertTrue(nlu.is_question("what if I spend 500 less on food"))

    def test_people_and_machines_are_not_accounts(self):
        ctx = nlu.Context(
            accounts=["Bank", "Cash"], default_expense_account="Cash", default_income_account="Bank"
        )
        atm = nlu.parse_entries("withdrew 2000 from atm", ctx)[0]
        self.assertEqual((atm.kind, atm.account, atm.to_account), ("transfer", "Bank", "Cash"))
        loan = nlu.parse_entries("borrowed 500 from ravi", ctx)[0]
        self.assertEqual(loan.account, "Cash")
        self.assertEqual(nlu.parse_entries("moved 500 to cash", ctx)[0].account, "Bank")

    def test_the_longest_account_name_wins(self):
        ctx = nlu.Context(
            accounts=["Bank", "HDFC Bank", "Cash"],
            default_expense_account="Cash",
            default_income_account="Bank",
        )
        entry = nlu.parse_entries("moved 3000 from hdfc bank to cash", ctx)[0]
        self.assertEqual(entry.account, "HDFC Bank")

    def test_junk_categories_are_not_invented(self):
        ctx = nlu.Context(
            accounts=["Bank", "Cash"], default_expense_account="Cash", default_income_account="Bank"
        )
        for text in ("paid 400 to plumber by upi", "paid 300 to ravi"):
            category = nlu.parse_entries(text, ctx)[0].category
            self.assertNotEqual(category, "Food & Dining", text)
            self.assertNotIn(category, ("Plumber", "Ravi", "Paid"), text)
        self.assertEqual(nlu.parse_entries("spnt 120 on lnch", ctx)[0].category, "Food & Dining")

    def test_dates_are_read_or_refused_never_guessed(self):
        ctx = nlu.Context(
            accounts=["Bank", "Cash"], default_expense_account="Cash", default_income_account="Bank"
        )
        self.assertEqual(
            nlu.parse_entries("spent 500 on 12 October 2025", ctx)[0].when, "2025-10-12"
        )
        self.assertEqual(len(nlu.parse_entries("spent 500 on 12 October 2025", ctx)), 1)
        self.assertEqual(nlu.parse_entries("chai 20 on 05.10.2026", ctx)[0].when, "2026-10-05")
        self.assertEqual(nlu.parse_entries("spent 200 on 2026/10/05", ctx)[0].when, "2026-10-05")
        self.assertEqual(
            nlu.parse_entries("chai 20 last week", ctx), []
        )  # asks instead of logging today
        self.assertEqual(nlu.parse_entries("chai 20 tomorrow", ctx), [])

    def test_totals_and_indian_amount_styles(self):
        self.assertEqual(
            entries("chai 20\nauto 50\nTotal 70"), [("expense", 20.0), ("expense", 50.0)]
        )
        self.assertEqual(entries("paid 1200rs rent"), [("expense", 1200.0)])
        self.assertEqual(entries("500/- chai"), [("expense", 500.0)])


class KeyDetectionTests(unittest.TestCase):
    def test_hyphenated_words_are_not_api_keys(self):
        for text in ("paid 500 for desk-organizer-with-drawers", "ask-me-anything-about-spending"):
            self.assertEqual(gw.extract_api_keys(text), [], text)
        self.assertEqual(len(gw.extract_api_keys("my key sk-proj-" + "a" * 40)), 1)

    def test_secrets_are_hidden_in_logs_and_errors(self):
        text = "failed: https://x/y?key=AIza" + "B" * 35 + "&alt=1 and sk-ant-" + "c" * 30
        hidden = gw.redact_secrets(text)
        self.assertNotIn("B" * 20, hidden)
        self.assertNotIn("c" * 20, hidden)
        self.assertIn("key=***", hidden)


class ConfirmationTests(unittest.TestCase):
    def say(self, chat_id, text):
        return run(bot.handle_incoming(chat_id, text))

    def setUp(self):
        self.chat = chat()
        self.say(self.chat, "Received 30000 in Bank")

    def pending(self):
        return self.say(self.chat, "transfer 7000 from bank to cash")

    def test_more_ways_to_say_yes_and_no(self):
        for text in ("haan", "ok do it", "yes pls", "👍", "kar do", "Yes!"):
            self.assertEqual(agent.classify_reply(text), "confirmed", text)
        for text in ("nahi", "cancel it", "👎", "never mind", "No."):
            self.assertEqual(agent.classify_reply(text), "cancelled", text)
        self.assertIsNone(agent.classify_reply("balance"))

    def test_buttons_carry_the_id_of_their_question(self):
        reply = self.pending()
        data = [b.data for row in reply.rows for b in row]
        self.assertTrue(all(d.count(":") == 2 for d in data[:2]), data)

    def test_an_old_yes_button_cannot_confirm_a_newer_question(self):
        old = [b.data for row in self.pending().rows for b in row][0]
        self.pending()  # a newer question replaces the old one
        stale = run(handle_callback(self.chat, old))
        self.assertIn("no longer waiting", stale.text)
        self.assertEqual(balance(self.chat, "Cash"), 0.0)

    def test_the_right_button_confirms(self):
        data = [b.data for row in self.pending().rows for b in row][0]
        done = run(handle_callback(self.chat, data))
        self.assertIn("7,000", done.text)
        self.assertEqual(balance(self.chat, "Cash"), 7000.0)

    def test_a_command_in_between_cancels_the_question(self):
        self.pending()
        self.say(self.chat, "/balance")
        reply = self.say(self.chat, "yes")
        self.assertIn("Nothing is waiting", reply.text)
        self.assertEqual(balance(self.chat, "Cash"), 0.0)

    def test_commands_split_on_any_whitespace(self):
        reply = self.say(self.chat, "/history\t1")
        self.assertNotIn("don't know", reply.text)

    def test_ai_edits_wait_for_a_yes(self):
        reason = agent.confirmation_reason(
            "edit_transaction", {"transaction_id": "abcdef123456", "amount": 5}
        )
        self.assertIn("Change entry abcdef12", reason)
        self.assertIsNone(agent.confirmation_reason("log_expense", {"amount": 9000}))
        self.assertIsNotNone(
            agent.confirmation_reason(
                "transfer_funds", {"amount": "7,000", "from_account": "A", "to_account": "B"}
            )
        )
        self.assertIsNone(agent.confirmation_reason("transfer_funds", "not a dict"))

    def test_the_ai_cannot_save_keys(self):
        self.assertNotIn("save_user_api_key", {t["function"]["name"] for t in agent.TOOLS_SCHEMA})


def fake_call(name, args, call_id="c1"):
    return SimpleNamespace(
        id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(args))
    )


def fake_reply(content="", calls=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=calls or []))]
    )


def scripted(*replies):
    queue = list(replies)

    async def complete(user_id, messages, **kw):
        return queue.pop(0)

    return complete


class OrchestratorFixTests(unittest.TestCase):
    def setUp(self):
        self.chat = chat()
        run(bot.handle_incoming(self.chat, "Received 30000 in Bank"))

    def test_a_write_with_an_empty_final_answer_is_not_run_twice(self):
        ai = scripted(
            fake_reply(
                calls=[
                    fake_call(
                        "log_expense",
                        {"amount": 200, "category": "Food", "account_name": "Cash"},
                        "a",
                    ),
                    fake_call("get_pipe_balances", {}, "b"),
                ]
            ),
            fake_reply(""),
        )
        with patch.object(gw, "complete", ai):
            result = run(
                agent._orchestrate(self.chat, "log 200 lunch and show balances please", [])
            )
        self.assertIsNotNone(result)
        self.assertEqual(balance(self.chat, "Cash"), -200.0)  # once, not twice

    def test_two_big_transfers_both_wait_and_the_recorded_part_is_mentioned(self):
        ai = scripted(
            fake_reply(
                calls=[
                    fake_call(
                        "log_expense",
                        {"amount": 50, "category": "Food", "account_name": "Bank"},
                        "a",
                    ),
                    fake_call(
                        "transfer_funds",
                        {"from_account": "Bank", "to_account": "Cash", "amount": 6000},
                        "b",
                    ),
                    fake_call(
                        "transfer_funds",
                        {"from_account": "Bank", "to_account": "Savings", "amount": 7000},
                        "c",
                    ),
                ]
            )
        )
        with patch.object(gw, "complete", ai):
            result = run(agent._orchestrate(self.chat, "move money and note chai", []))
        self.assertTrue(result["requires_confirmation"])
        self.assertEqual(len(result["tool_calls"]), 2)
        self.assertIn("₹50", result["preamble"])
        self.assertIn("6,000", result["confirmation_action"]["description"])
        self.assertIn("7,000", result["confirmation_action"]["description"])
        self.assertEqual(balance(self.chat, "Savings"), None)  # nothing moved yet


class ButtonTests(unittest.TestCase):
    def test_key_buttons_carry_the_key_id_not_its_position(self):
        rows = ui.keys_rows(["11111111-aaaa", "22222222-bbbb"])
        data = [b.data for row in rows for b in row]
        self.assertIn("key:del:k11111111", data)
        self.assertIn("key:del:k22222222", data)
        self.assertNotIn("key:del:1", data)

    def test_deleting_by_id_twice_removes_only_one_key(self):
        from app.bot import keys as keys_mod

        chat_id = chat()
        with patch.object(gw, "add_validated_keys"):  # keys are inserted directly: no live test
            for provider, key in (
                ("gemini", "AIza" + "A" * 35),
                ("groq", "gsk_" + "b" * 30),
                ("openai", "sk-proj-" + "c" * 40),
            ):
                gw.add_api_key(chat_id, provider, key)
        before = gw.list_api_keys(chat_id)
        target = "k" + before[0]["key_id"][:8]
        run(keys_mod.handle_key_command(chat_id, "/delkey", target))
        again = run(keys_mod.handle_key_command(chat_id, "/delkey", target))  # a stale second tap
        self.assertEqual(len(gw.list_api_keys(chat_id)), 2)
        self.assertNotIn("removed", again)

    def test_history_undo_button_names_the_entry_so_a_double_tap_is_harmless(self):
        chat_id = chat()
        run(bot.handle_incoming(chat_id, "Spent 100 on chai via Cash"))
        run(bot.handle_incoming(chat_id, "Spent 200 on auto via Cash"))
        history = run(bot.handle_incoming(chat_id, "/history"))
        undo = next(b.data for row in history.rows for b in row if b.data.startswith("undo:"))
        self.assertNotEqual(undo, "undo:last")
        run(handle_callback(chat_id, undo))
        run(handle_callback(chat_id, undo))  # second tap on the same message
        self.assertEqual(balance(chat_id, "Cash"), -100.0)  # only the auto was undone

    def test_an_expired_import_button_says_so(self):
        reply = run(bot.answer_pending_import(chat(), "confirmed"))
        self.assertIn("expired", reply.text)


class StartupTests(unittest.TestCase):
    def test_one_unreachable_bot_does_not_stop_the_others(self):
        from app.bot import telegram
        from app.config import settings

        class FakeBot:
            def __init__(self, token):
                self.token = token
                self.session = SimpleNamespace(close=lambda: asyncio.sleep(0))

            async def get_me(self):
                if self.token.startswith("2222"):
                    raise ConnectionError("no route")
                return SimpleNamespace(username="ok")

            async def delete_webhook(self, **kw):
                pass

        async def go():
            with (
                patch.object(settings, "telegram_bot_token", "1111:AAA"),
                patch.object(settings, "telegram_bot_tokens", "2222:BBB"),
                patch.object(settings, "use_webhook", False),
                patch.object(telegram, "Bot", FakeBot),
                patch.object(telegram, "_publish_profile"),
                patch.object(
                    telegram.Dispatcher, "start_polling", lambda *a, **k: asyncio.sleep(0)
                ),
            ):
                mode = await telegram.start()
                running = telegram.running_bots()
                await telegram.stop()
                return mode, running

        self.assertEqual(asyncio.run(go()), ("polling", 1))


if __name__ == "__main__":
    unittest.main()
