"""Regression tests for the bugs found in the code audit. Offline."""

import os

os.environ["WALLETLEDGER_TESTING"] = "1"
os.environ["LITELLM_MODE"] = "PRODUCTION"
import tempfile

_TMP_DIR = tempfile.mkdtemp(prefix="walletledger-audit-test-")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_TMP_DIR, "test.db").replace("\\", "/")
os.environ["DYNAMIC_MODELS"] = "false"
os.environ["TELEGRAM_BOT_TOKEN"] = ""
for _var in ("GEMINI_API_KEYS", "GEMINI_API_KEY", "OPENAI_API_KEYS", "GROQ_API_KEYS"):
    os.environ[_var] = ""

import asyncio  # noqa: E402
import itertools  # noqa: E402
import threading  # noqa: E402
import unittest  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import patch  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app import db as db_module  # noqa: E402
from app.bot import main as bot  # noqa: E402
from app.bot import nlu, ui  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.services import analytics, ledger  # noqa: E402
from app.services_ai.mcp_server import execute_tool  # noqa: E402
from app.web import tokens  # noqa: E402
from main import app  # noqa: E402

init_db()
_ids = itertools.count(1)


def run(coro):
    return asyncio.run(coro)


def new_chat(prefix="audit"):
    return f"{prefix}-{next(_ids)}"


def balance(chat, account="Cash"):
    with SessionLocal() as db:
        uid = ledger.get_or_create_user(db, chat).id
        for a in ledger.get_account_balances(db, uid)["accounts"]:
            if a["name"] == account:
                return a["balance"]
    return None


def count_transactions(chat):
    with SessionLocal() as db:
        uid = ledger.get_or_create_user(db, chat).id
        return ledger.recent_transactions(db, uid, 1)[1]


class BalanceTests(unittest.TestCase):
    def test_simultaneous_entries_are_all_counted(self):
        chat = new_chat()
        with SessionLocal() as db:
            ledger.get_or_create_user(db, chat)

        def add():
            with SessionLocal() as db:
                uid = ledger.get_or_create_user(db, chat).id
                ledger.record_transaction(db, uid, 10, "Cash", "Food", tx_type="expense")

        threads = [threading.Thread(target=add) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(count_transactions(chat), 20)
        self.assertEqual(balance(chat), -200.0)

    def test_undo_puts_the_balance_back(self):
        chat = new_chat()
        with SessionLocal() as db:
            uid = ledger.get_or_create_user(db, chat).id
            ledger.record_transaction(db, uid, 1000, "Bank", "Salary", tx_type="income")
            tx = ledger.record_transaction(db, uid, 250, "Bank", "Food", tx_type="expense")
            self.assertEqual(
                ledger.undo_transaction(db, uid, tx["transaction_id"])["new_balance"], 1000.0
            )
        self.assertEqual(balance(chat, "Bank"), 1000.0)

    def test_undo_rejects_ids_that_are_not_ids(self):
        with SessionLocal() as db:
            uid = ledger.get_or_create_user(db, new_chat()).id
            for bad in ("%%%%%%", "______", "../etc/x"):
                with self.assertRaises(ledger.LedgerError):
                    ledger.undo_transaction(db, uid, bad)


class UndoOrderTests(unittest.TestCase):
    def test_undo_removes_what_was_entered_last_not_the_latest_date(self):
        chat = new_chat()
        with SessionLocal() as db:
            uid = ledger.get_or_create_user(db, chat).id
            ledger.record_transaction(db, uid, 500, "Bank", "Rent", tx_type="expense")
            chai = ledger.record_transaction(
                db,
                uid,
                20,
                "Bank",
                "Food",
                tx_type="expense",
                created_at=datetime.now() - timedelta(days=1),
            )
            self.assertEqual(ledger.last_entered_transaction_id(db, uid), chai["transaction_id"])
        reply = run(bot.handle_text(chat, "/undo"))
        self.assertIn("₹20", reply)
        self.assertEqual(balance(chat, "Bank"), -500.0)

    def test_a_big_batch_gets_a_working_undo_button(self):
        chat = new_chat()
        with SessionLocal() as db:
            uid = ledger.get_or_create_user(db, chat).id
            ids = [
                ledger.record_transaction(db, uid, 10 + i, "Cash", "Food", tx_type="expense")[
                    "transaction_id"
                ]
                for i in range(10)
            ]
        button = ui.undo_row(ids)[0]
        self.assertLessEqual(len(button.data.encode()), 64)
        from app.bot.callbacks import handle_callback

        reply = run(handle_callback(chat, button.data)).text
        self.assertEqual(reply.count("Undone"), 10)
        self.assertEqual(count_transactions(chat), 0)

    def test_old_databases_get_the_new_column(self):
        engine = create_engine("sqlite://")
        with engine.begin() as conn:
            conn.execute(
                text("CREATE TABLE transactions (id VARCHAR(36) PRIMARY KEY, amount FLOAT)")
            )
        with patch.object(db_module, "engine", engine):
            db_module._add_missing_columns()
            db_module._add_missing_columns()  # safe to repeat
        with engine.connect() as conn:
            columns = {row[1] for row in conn.execute(text("PRAGMA table_info(transactions)"))}
        self.assertIn("entered_at", columns)


class OfflineHonestyTests(unittest.TestCase):
    def test_no_key_never_turns_a_stray_number_into_an_expense(self):
        chat = new_chat()
        for message in (
            "Call mom at 5pm",
            "my flat number is 402",
            "room 12 is booked",
            "meet at 6",
        ):
            reply = run(bot.handle_text(chat, message))
            self.assertNotIn("−₹", reply, message)
        self.assertEqual(count_transactions(chat), 0)

    def test_numbers_the_rules_cannot_read_get_a_hint(self):
        reply = run(bot.handle_text(new_chat(), "invoice 7731 is pending"))
        self.assertIn("didn't record anything", reply)

    def test_a_big_transfer_does_not_swallow_the_other_items(self):
        chat = new_chat()
        ask = run(
            bot.handle_incoming(chat, "Spent 200 on chai and transferred 6000 from Bank to Cash")
        )
        self.assertTrue(ask.rows)  # waiting for Yes
        self.assertIn("1 other", ask.text)
        done = run(bot.handle_text(chat, "yes"))
        self.assertIn("₹200", done)
        self.assertEqual(count_transactions(chat), 2)


class RuleReaderTests(unittest.TestCase):
    def amounts(self, text_):
        return [(e.kind, e.amount) for e in nlu.parse_entries(text_, nlu.Context())]

    def test_counts_are_not_amounts(self):
        self.assertEqual(self.amounts("Bought 3 shirts for 1500"), [("expense", 1500.0)])
        self.assertEqual(self.amounts("Spent 20 on 2 samosas"), [("expense", 20.0)])
        self.assertEqual(self.amounts("chai 20"), [("expense", 20.0)])

    def test_a_new_line_does_not_inherit_income(self):
        got = self.amounts("got stipend of 15000\n190=pizza\n80 = dosa")
        self.assertEqual(got, [("income", 15000.0), ("expense", 190.0), ("expense", 80.0)])

    def test_stray_numbers_are_left_to_the_ai(self):
        self.assertEqual(self.amounts("room 12 is booked"), [])


class ToolValidationTests(unittest.TestCase):
    def setUp(self):
        self.chat = new_chat()
        with SessionLocal() as db:
            uid = ledger.get_or_create_user(db, self.chat).id
            self.tx = ledger.record_transaction(db, uid, 100, "Bank", "Food", tx_type="expense")

    def edit(self, **kw):
        return execute_tool(
            "edit_transaction", user_id=self.chat, transaction_id=self.tx["transaction_id"], **kw
        )

    def test_edit_uses_the_same_rules_as_logging(self):
        for bad in (1e30, float("nan"), 0.004, -5):
            with self.assertRaises(ValueError, msg=str(bad)):
                self.edit(amount=bad)
        for bad_date in ("0500-01-01", "2999-01-01"):
            with self.assertRaises(ValueError, msg=bad_date):
                self.edit(transaction_date=bad_date)

    def test_a_good_edit_still_moves_the_balance(self):
        self.edit(amount=40)
        self.assertEqual(balance(self.chat, "Bank"), -40.0)


class AnalyticsFixTests(unittest.TestCase):
    def test_daily_average_ignores_days_before_the_first_entry(self):
        chat = new_chat()
        with SessionLocal() as db:
            uid = ledger.get_or_create_user(db, chat).id
            when = datetime.now() - timedelta(days=9)
            ledger.record_transaction(
                db, uid, 1000, "Bank", "Food", tx_type="expense", created_at=when
            )
            everything = analytics.report(db, uid, analytics.parse_period("all"))
        self.assertAlmostEqual(everything["summary"]["avg_per_day"], 100.0, delta=12)

    def test_huge_jumps_are_not_shown_as_a_trend(self):
        self.assertIsNone(analytics._change(5000, 100))
        self.assertEqual(analytics._change(150, 100), 50.0)

    def test_csv_cells_cannot_become_formulas(self):
        self.assertEqual(analytics.csv_safe('=HYPERLINK("x")'), '\'=HYPERLINK("x")')
        self.assertEqual(analytics.csv_safe("Swiggy"), "Swiggy")

    def test_budget_for_food_uses_the_food_and_dining_category(self):
        chat = new_chat()
        with SessionLocal() as db:
            uid = ledger.get_or_create_user(db, chat).id
            ledger.record_transaction(db, uid, 900, "Bank", "Food & Dining", tx_type="expense")
        reply = run(bot.handle_text(chat, "/budget food 1000"))
        self.assertIn("Food & Dining", reply)
        self.assertIn("90%", run(bot.handle_text(chat, "/budget")))


class DashboardFixTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.chat = new_chat("dash")
        self.headers = {"X-Dashboard-Token": tokens.make_token(self.chat, 600)}

    def test_infinite_amount_filters_are_rejected(self):
        for value in ("inf", "nan", "-inf"):
            r = self.client.get(f"/api/dashboard?min={value}", headers=self.headers)
            self.assertEqual(r.status_code, 400, value)

    def test_csv_export_neutralises_formulas(self):
        with SessionLocal() as db:
            uid = ledger.get_or_create_user(db, self.chat).id
            ledger.record_transaction(
                db,
                uid,
                5,
                "Bank",
                "Food",
                tx_type="expense",
                description='=HYPERLINK("http://evil")',
            )
        r = self.client.get("/api/export.csv?period=30d", headers=self.headers)
        self.assertEqual(r.status_code, 200)
        self.assertIn("'=HYPERLINK", r.text)

    def test_inline_styles_go_through_the_dom_not_attributes(self):
        # style="..." attributes are blocked by the page's CSP, which silently broke bar widths
        js = Path(__file__).resolve().parent.parent / "app" / "web" / "static" / "dashboard.js"
        text_ = js.read_text(encoding="utf-8")
        self.assertEqual(text_.count('k === "style"'), 2)  # h() and s()
        self.assertIn(
            "style-src 'self'", self.client.get("/d/x").headers["content-security-policy"]
        )


class SecretKeyTests(unittest.TestCase):
    def test_a_public_address_with_a_placeholder_key_refuses_to_start(self):
        from main import lifespan

        async def start():
            async with lifespan(app):
                pass

        with (
            patch.object(tokens, "is_https", return_value=True),
            patch("app.crypto.weak_secret_key", return_value=True),
            self.assertRaises(RuntimeError) as ctx,
        ):
            asyncio.run(start())
        self.assertIn("SECRET_KEY", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
