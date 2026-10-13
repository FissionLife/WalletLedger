"""Balance overdraw guard and budget tracking/overage behavior. Offline.

Covers the fixes for: a funded account can't go negative on a live spend or transfer;
never-funded accounts stay a pure ledger; budgets attach to the canonical category and
track spend; and an overspend of a budget asks the user first.
"""

import os

os.environ["WALLETLEDGER_TESTING"] = "1"
os.environ["LITELLM_MODE"] = "PRODUCTION"
import tempfile

_TMP_DIR = tempfile.mkdtemp(prefix="walletledger-guard-test-")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_TMP_DIR, "test.db").replace("\\", "/")
os.environ["DYNAMIC_MODELS"] = "false"
os.environ["TELEGRAM_BOT_TOKEN"] = ""

import itertools  # noqa: E402
import unittest  # noqa: E402

from sqlalchemy import select  # noqa: E402

from app.bot import nlu  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Account  # noqa: E402
from app.services import ledger  # noqa: E402
from app.services_ai.mcp_server import execute_tool  # noqa: E402

init_db()
_ids = itertools.count(1)


def new_user():
    chat = f"guard-{next(_ids)}"
    with SessionLocal() as db:
        return chat, ledger.get_or_create_user(db, chat).id


def fund(chat, account, amount):
    """Give an account a real opening balance via income (so it counts as 'funded')."""
    execute_tool("log_income", user_id=chat, amount=amount, source_account=account)


def balance_of(uid, name):
    with SessionLocal() as db:
        acc = db.scalar(select(Account).where(Account.user_id == uid, Account.name == name))
        return acc.balance if acc else None


class OverdrawGuardTests(unittest.TestCase):
    def test_funded_account_cannot_go_negative_on_a_live_spend(self):
        chat, uid = new_user()
        fund(chat, "Cash", 500)
        with self.assertRaises(Exception) as ctx:
            execute_tool(
                "log_expense", user_id=chat, amount=700, category="Food", account_name="Cash"
            )
        self.assertIn("not enough balance", str(ctx.exception).lower())
        self.assertEqual(balance_of(uid, "Cash"), 500)  # nothing deducted

    def test_drained_account_blocks_the_next_spend(self):
        # Kevin's case: funded, drained to 0, then overspent.
        chat, uid = new_user()
        fund(chat, "Cash", 1000)
        execute_tool("log_expense", user_id=chat, amount=1000, category="Food", account_name="Cash")
        self.assertEqual(balance_of(uid, "Cash"), 0)
        with self.assertRaises(Exception) as ctx:
            execute_tool(
                "log_expense", user_id=chat, amount=2000, category="Food", account_name="Cash"
            )
        self.assertIn("not enough balance", str(ctx.exception).lower())

    def test_never_funded_account_stays_a_pure_ledger(self):
        # No opening balance ever: expenses still log and the balance goes negative, as before.
        chat, uid = new_user()
        execute_tool("log_expense", user_id=chat, amount=300, category="Food", account_name="Cash")
        self.assertEqual(balance_of(uid, "Cash"), -300)

    def test_transfer_out_cannot_overdraw_a_funded_source(self):
        chat, uid = new_user()
        fund(chat, "Bank", 100)
        with self.assertRaises(Exception) as ctx:
            execute_tool(
                "transfer_funds", user_id=chat, from_account="Bank", to_account="Cash", amount=500
            )
        self.assertIn("not enough balance", str(ctx.exception).lower())

    def test_a_spend_within_balance_is_allowed(self):
        chat, uid = new_user()
        fund(chat, "Cash", 500)
        execute_tool("log_expense", user_id=chat, amount=200, category="Food", account_name="Cash")
        self.assertEqual(balance_of(uid, "Cash"), 300)


class BudgetTrackingTests(unittest.TestCase):
    def test_budget_sets_on_canonical_category_and_tracks_spend(self):
        chat, uid = new_user()
        fund(chat, "Bank", 5000)
        res = execute_tool(
            "set_category_budget", user_id=chat, category="food", monthly_budget=1000
        )
        self.assertEqual(res["category"], "Food & Dining")
        # a spend on "food" counts against the same canonical category
        execute_tool("log_expense", user_id=chat, amount=400, category="food", account_name="Bank")
        from app.services import analytics

        with SessionLocal() as db:
            rows = analytics.budget_status(db, uid)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["category"], "Food & Dining")
        self.assertEqual(rows[0]["spent"], 400)
        self.assertEqual(rows[0]["left"], 600)

    def test_meals_maps_to_food_and_dining(self):
        self.assertEqual(nlu.canonical_category("meals"), "Food & Dining")
        self.assertEqual(nlu.canonical_category("food"), "Food & Dining")


class BudgetOverageConfirmTests(unittest.TestCase):
    def test_overspending_a_budget_asks_first(self):
        import asyncio

        from app.bot import agent

        chat, uid = new_user()
        fund(chat, "Bank", 50000)
        execute_tool("set_category_budget", user_id=chat, category="food", monthly_budget=1000)
        execute_tool("log_expense", user_id=chat, amount=700, category="food", account_name="Bank")

        # An expense that pushes Food over 1000 should require confirmation, not run immediately.
        outcome = asyncio.run(agent.process_user_interaction_ex(chat, "I ate 600 for meals"))
        self.assertTrue(outcome.needs_confirmation)
        self.assertIn("budget", outcome.text.lower())

    def test_a_spend_within_budget_does_not_ask(self):
        import asyncio

        from app.bot import agent

        chat, uid = new_user()
        fund(chat, "Bank", 50000)
        execute_tool("set_category_budget", user_id=chat, category="food", monthly_budget=1000)
        outcome = asyncio.run(agent.process_user_interaction_ex(chat, "I ate 200 for meals"))
        self.assertFalse(outcome.needs_confirmation)


class BudgetCommandParsingTests(unittest.TestCase):
    def test_a_complaint_is_not_a_budget_command(self):
        text = (
            "Hey I told you I have allotted budget of 1k for food but I overused "
            "why didn't you give a reminder"
        )
        self.assertIsNone(nlu.detect_screen(text))

    def test_plain_budget_phrasings_are_commands(self):
        for text, cat in [
            ("I want to have a budget 1k alloted to food", "food"),
            ("budget for food 2k", "food"),
            ("set food budget to 2000", "food"),
        ]:
            screen = nlu.detect_screen(text)
            self.assertIsNotNone(screen, text)
            self.assertEqual(screen.command, "/budget")
            self.assertTrue(screen.args.startswith(cat), f"{text} -> {screen.args}")


if __name__ == "__main__":
    unittest.main()
