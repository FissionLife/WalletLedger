"""First contact and everyday chat: the one setup question, default account, corrections, balances. Offline."""

import os

os.environ["WALLETLEDGER_TESTING"] = "1"
os.environ["LITELLM_MODE"] = "PRODUCTION"
import tempfile

_TMP_DIR = tempfile.mkdtemp(prefix="walletledger-onboarding-test-")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_TMP_DIR, "test.db").replace("\\", "/")
os.environ["DYNAMIC_MODELS"] = "false"
os.environ["TELEGRAM_BOT_TOKEN"] = ""
for _var in ("GEMINI_API_KEYS", "GEMINI_API_KEY", "OPENAI_API_KEYS", "GROQ_API_KEYS"):
    os.environ[_var] = ""

import asyncio  # noqa: E402
import itertools  # noqa: E402
import unittest  # noqa: E402
from unittest.mock import patch  # noqa: E402

from app.bot import main as bot_main  # noqa: E402
from app.bot import nlu, onboarding  # noqa: E402
from app.bot.callbacks import handle_callback  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.services import ledger  # noqa: E402

_ids = itertools.count(700000)


def say(chat, text):
    return asyncio.run(bot_main.handle_incoming(chat, text))


def tap(chat, data):
    return asyncio.run(handle_callback(chat, data))


def balances(chat):
    with SessionLocal() as db:
        user = ledger.get_or_create_user(db, chat)
        data = ledger.get_account_balances(db, user.id)
    return {a["name"]: a["balance"] for a in data["accounts"]}


class NewUserTests(unittest.TestCase):
    def setUp(self):
        init_db()
        self.chat = str(next(_ids))
        onboarding.reset()
        patcher = patch.object(settings, "onboarding", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_start_asks_one_question_with_buttons(self):
        r = say(self.chat, "/start")
        self.assertIn("where do you usually pay from", r.text)
        labels = [b.text for row in r.rows for b in row]
        self.assertTrue(any("Bank" in x for x in labels) and any("Cash" in x for x in labels))

    def test_answering_then_giving_a_balance_finishes_setup(self):
        say(self.chat, "/start")
        r = tap(self.chat, "ob:acct:bank")
        self.assertIn("how much is in Bank", r.text)
        r = say(self.chat, "25000")
        self.assertIn("starts at ₹25,000", r.text)
        self.assertEqual(balances(self.chat)["Bank"], 25000)
        # the opening balance is money, not earnings
        stats = say(self.chat, "/stats")
        self.assertNotIn("25,000", stats.text)

    def test_skip_button_and_typed_skip_both_work(self):
        say(self.chat, "/start")
        tap(self.chat, "ob:acct:cash")
        self.assertIn("all set", tap(self.chat, "ob:skip").text)
        other = str(next(_ids))
        say(other, "/start")
        say(other, "bank")
        self.assertIn("all set", say(other, "skip").text)

    def test_the_default_account_takes_expenses_that_name_none(self):
        say(self.chat, "/start")
        say(self.chat, "cash")
        say(self.chat, "skip")
        with SessionLocal() as db:
            uid = ledger.get_or_create_user(db, self.chat).id
            ledger.record_transaction(db, uid, 1000, "Cash", "Seed", tx_type="income")
        say(self.chat, "chai 20")
        self.assertEqual(balances(self.chat)["Cash"], 980)
        self.assertEqual(balances(self.chat)["Bank"], 0)

    def test_a_first_message_that_is_an_entry_is_logged_after_the_answer(self):
        r = say(self.chat, "spent 450 on dinner")
        self.assertIn("where do you usually pay from", r.text)
        self.assertEqual(balances(self.chat).get("Bank", 0), 0)  # nothing yet
        r = tap(self.chat, "ob:acct:bank")
        self.assertIn("not enough balance", r.text.lower())
        self.assertEqual(balances(self.chat)["Bank"], 0)

    def test_ignoring_the_question_is_never_a_dead_end(self):
        say(self.chat, "spent 450 on dinner")
        r = say(self.chat, "also got salary 50000")  # not an answer
        self.assertIn("not enough balance", r.text.lower())
        self.assertIn("+₹50,000", r.text)
        self.assertEqual(balances(self.chat)["Bank"], 50000)
        # and the next message is plain chat again, not another question
        self.assertNotIn("where do you usually pay", say(self.chat, "coffee 100").text)

    def test_a_returning_user_is_not_asked(self):
        say(self.chat, "/start")
        tap(self.chat, "ob:acct:bank")
        say(self.chat, "skip")
        self.assertNotIn("where do you usually pay", say(self.chat, "/start").text)

    def test_commands_work_for_a_new_user_without_the_question(self):
        self.assertIn("Total", say(self.chat, "/balance").text)

    def test_default_can_be_changed_in_chat(self):
        say(self.chat, "/start")
        say(self.chat, "bank")
        say(self.chat, "skip")
        self.assertIn("Cash", say(self.chat, "use cash by default").text)
        with SessionLocal() as db:
            uid = ledger.get_or_create_user(db, self.chat).id
            ledger.record_transaction(db, uid, 1000, "Cash", "Seed", tx_type="income")
        say(self.chat, "chai 20")
        self.assertEqual(balances(self.chat)["Cash"], 980)

    def test_a_stale_button_does_not_crash(self):
        self.assertTrue(tap(self.chat, "ob:acct:nonsense").notice)


class EverydayChatTests(unittest.TestCase):
    """The new user is set up; these are the things people actually type."""

    def setUp(self):
        init_db()
        self.chat = str(next(_ids))
        onboarding.reset()
        with patch.object(settings, "onboarding", True):
            say(self.chat, "/start")
            say(self.chat, "bank")
            say(self.chat, "skip")

    def test_set_the_real_balance_in_words(self):
        r = say(self.chat, "bank balance is 25000")
        self.assertIn("Bank is now ₹25,000", r.text)
        self.assertEqual(balances(self.chat)["Bank"], 25000)
        say(self.chat, "I have 5000 in cash")
        self.assertEqual(balances(self.chat)["Cash"], 5000)
        say(self.chat, "my balance is 24000")  # no account named: the default one
        self.assertEqual(balances(self.chat)["Bank"], 24000)

    def test_setting_a_balance_is_not_spending_or_earning(self):
        say(self.chat, "bank balance is 25000")
        say(self.chat, "bank balance is 20000")
        stats = say(self.chat, "/stats").text
        self.assertNotIn("Spent ₹5,000", stats)
        self.assertNotIn("Earned ₹25,000", stats)

    def test_something_that_is_not_an_account_is_left_alone(self):
        self.assertIsNone(
            asyncio.run(onboarding.balance_command(self.chat, "my phone balance is 500"))
        )

    def test_correcting_an_entry_by_name_and_by_position(self):
        with SessionLocal() as db:
            uid = ledger.get_or_create_user(db, self.chat).id
            ledger.record_transaction(db, uid, 100000, "Bank", "Seed", tx_type="income")
        say(self.chat, "coffee 120")
        say(self.chat, "paid 450 for dinner")
        r = say(self.chat, "oops the dinner was actually 540 not 450")
        self.assertIn("450 → ", r.text.replace("₹", "").replace("−", ""))
        self.assertEqual(balances(self.chat)["Bank"], 100000 - 660)
        say(self.chat, "change the last one to 600")
        self.assertEqual(balances(self.chat)["Bank"], 100000 - 720)

    def test_a_plain_statement_is_a_new_entry_not_a_correction(self):
        with SessionLocal() as db:
            uid = ledger.get_or_create_user(db, self.chat).id
            ledger.record_transaction(db, uid, 100000, "Bank", "Seed", tx_type="income")
        say(self.chat, "paid 450 for dinner")
        say(self.chat, "dinner was 400")
        self.assertEqual(balances(self.chat)["Bank"], 100000 - 850)

    def test_a_correction_with_nothing_to_correct_is_not_logged_twice(self):
        r = say(self.chat, "delete the pizza")
        self.assertIn("couldn't find", r.text)

    def test_deleting_an_entry_by_name(self):
        with SessionLocal() as db:
            uid = ledger.get_or_create_user(db, self.chat).id
            ledger.record_transaction(db, uid, 100000, "Bank", "Seed", tx_type="income")
        say(self.chat, "coffee 120")
        say(self.chat, "uber 250")
        say(self.chat, "delete the coffee")
        self.assertEqual(balances(self.chat)["Bank"], 100000 - 250)

    def test_minus_sign_is_an_expense(self):
        with SessionLocal() as db:
            uid = ledger.get_or_create_user(db, self.chat).id
            ledger.record_transaction(db, uid, 1000, "Bank", "Seed", tx_type="income")
        say(self.chat, "-60 chai")
        self.assertEqual(balances(self.chat)["Bank"], 940)

    def test_greetings_and_thanks_get_a_human_reply(self):
        self.assertIn("Hey", say(self.chat, "hi").text)
        self.assertIn("Anytime", say(self.chat, "thanks").text)

    def test_a_bare_number_asks_what_it_was(self):
        r = say(self.chat, "450")
        self.assertIn("spend it or receive it", r.text)
        self.assertEqual(balances(self.chat)["Bank"], 0)

    def test_budget_and_biggest_expense_questions_open_the_right_screen(self):
        self.assertEqual(nlu.detect_screen("how is my food budget").command, "/budget")
        self.assertEqual(nlu.detect_screen("what is my biggest expense").command, "/chart")
        self.assertEqual(nlu.detect_screen("how much in cash").command, "/balance")
        self.assertEqual(nlu.detect_screen("show me what I have logged so far").command, "/history")
        self.assertEqual(nlu.detect_screen("spent on food this week").command, "/stats")

    def test_ok_without_a_question_is_friendly(self):
        self.assertIn("Nothing is waiting", say(self.chat, "ok").text)


class ParserTests(unittest.TestCase):
    def test_parse_fix_shapes(self):
        fix = nlu.parse_fix("oops the dinner was actually 540 not 450")
        self.assertEqual(
            (fix.action, fix.amount, fix.old_amount, fix.keyword), ("edit", 540, 450, "dinner")
        )
        self.assertIsNone(nlu.parse_fix("make it 200").keyword)
        self.assertEqual(nlu.parse_fix("edit coffee to 150").keyword, "coffee")
        self.assertEqual(nlu.parse_fix("delete the coffee").action, "delete")
        self.assertIsNone(nlu.parse_fix("delete the last one"))  # that is Undo
        self.assertIsNone(nlu.parse_fix("dinner was 400"))

    def test_item_and_cost_is_an_entry(self):
        entry = nlu.parse_entries("the rent was 5000")[0]
        self.assertEqual((entry.kind, entry.amount, entry.category), ("expense", 5000, "Rent"))
        self.assertEqual(nlu.parse_entries("the total was 900"), [])


if __name__ == "__main__":
    unittest.main()
