"""End-to-end tests (stdlib unittest, SQLite temp DB). Run: uv run python -m unittest discover -s tests"""

import asyncio
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["ENABLE_DEV_ENDPOINTS"] = "true"
os.environ["ALLOWED_CHAT_IDS"] = ""
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["WEBHOOK_SECRET"] = ""
os.environ["DEFAULT_LLM_API_KEY"] = ""
os.environ["DEFAULT_LLM_MODEL"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app.bot import agent  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.services import ledger  # noqa: E402
from app.services_ai import mcp_server, transaction_parser, vault  # noqa: E402
from main import app  # noqa: E402

init_db()
_counter = 0


def new_user(db):
    global _counter
    _counter += 1
    return ledger.get_or_create_user(db, f"chat-{_counter}")


def run(coro):
    return asyncio.run(coro)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        self.user = new_user(self.db)

    def tearDown(self):
        self.db.close()

    def test_default_accounts_and_idempotent_user(self):
        again = ledger.get_or_create_user(self.db, self.user.telegram_chat_id)
        self.assertEqual(again.id, self.user.id)
        names = {a["name"] for a in ledger.get_account_balances(self.db, self.user.id)["accounts"]}
        self.assertEqual(names, {"Cash", "Bank"})

    def test_expense_income_balances(self):
        ledger.record_transaction(self.db, self.user.id, 1000, "Bank", tx_type="income")
        r = ledger.record_transaction(self.db, self.user.id, 250.5, "bank", "food", "swiggy")
        self.assertEqual(r["new_balance"], 749.5)
        self.assertEqual(
            ledger.get_account_balances(self.db, self.user.id)["total_net_worth"], 749.5
        )

    def test_transfer_is_not_spending(self):
        ledger.record_transaction(self.db, self.user.id, 5000, "Bank", tx_type="income")
        ledger.transfer_between_pipes(self.db, self.user.id, "Bank", "Cash", 2000)
        bal = {
            a["name"]: a["balance"]
            for a in ledger.get_account_balances(self.db, self.user.id)["accounts"]
        }
        self.assertEqual(bal, {"Bank": 3000.0, "Cash": 2000.0})
        self.assertEqual(ledger.get_spending_summary(self.db, self.user.id)["total_expenses"], 0)

    def test_validation(self):
        for bad in (0, -5, float("nan"), float("inf"), "abc"):
            with self.assertRaises(ledger.LedgerError):
                ledger.record_transaction(self.db, self.user.id, bad, "Bank")
        with self.assertRaises(ledger.LedgerError):
            ledger.record_transaction(self.db, self.user.id, 5, "Bank", tx_type="transfer")
        with self.assertRaises(ledger.LedgerError):
            ledger.transfer_between_pipes(self.db, self.user.id, "Bank", " bank ", 5)
        self.assertEqual(ledger.get_account_balances(self.db, self.user.id)["total_net_worth"], 0)

    def test_summary_has_real_categories_and_merchants(self):
        ledger.record_transaction(self.db, self.user.id, 100, "Cash", "Food & Dining", "Swiggy")
        ledger.record_transaction(self.db, self.user.id, 300, "Cash", "Shopping", "Amazon")
        ledger.record_transaction(self.db, self.user.id, 50, "Cash")
        s = ledger.get_spending_summary(self.db, self.user.id)
        self.assertEqual(
            s["category_breakdown"],
            {"Shopping": 300.0, "Food & Dining": 100.0, "Uncategorized": 50.0},
        )
        self.assertEqual(s["merchant_breakdown"]["Amazon"], 300.0)

    def test_users_are_isolated(self):
        other = new_user(self.db)
        ledger.record_transaction(self.db, other.id, 999, "Cash", "Food")
        self.assertEqual(ledger.get_spending_summary(self.db, self.user.id)["total_expenses"], 0)


class ParserTests(unittest.TestCase):
    def p(self, t):
        return transaction_parser.parse_chat_expense(t)

    def test_expense_via_account(self):
        r = self.p("Spent 450 on dinner via Bank")
        self.assertEqual(
            (r["intent"], r["amount"], r["account"], r["category"]),
            ("expense", 450.0, "Bank", "Food & Dining"),
        )

    def test_expense_merchant(self):
        r = self.p("Paid 150 to Starbucks for coffee")
        self.assertEqual(
            (r["merchant"], r["category"], r["amount"]), ("Starbucks", "Food & Dining", 150.0)
        )

    def test_amount_formats(self):
        self.assertEqual(self.p("spent ₹1,250.50 on uber")["amount"], 1250.5)
        self.assertEqual(self.p("paid 2k for rent")["amount"], 2000.0)

    def test_income(self):
        r = self.p("Received 50000 salary in Bank")
        self.assertEqual(
            (r["intent"], r["amount"], r["account"], r["category"]),
            ("income", 50000.0, "Bank", "Salary"),
        )

    def test_transfer(self):
        r = self.p("Transferred 2000 from Bank to Cash")
        self.assertEqual(
            (r["intent"], r["account"], r["to_account"], r["amount"]),
            ("transfer", "Bank", "Cash", 2000.0),
        )

    def test_other_intents(self):
        self.assertEqual(self.p("what is my balance")["intent"], "balance")
        self.assertEqual(self.p("give me a spending report")["intent"], "report")
        self.assertEqual(self.p("how can I reduce expenses")["intent"], "advice")
        self.assertEqual(self.p("hello there")["intent"], "other")
        self.assertEqual(self.p("")["intent"], "other")

    def test_key_detection(self):
        r = self.p("my api key AIzaSyA1234567890abcdefghijklmnop")
        self.assertEqual(r["intent"], "set_key")

    def test_statement_text(self):
        text = (
            "Transaction Statement\n"
            "Jan 05, 2025\nPaid to Swiggy\nDEBIT ₹450.00\n"
            "Jan 06, 2025\nReceived from Rahul Kumar\nCREDIT ₹1,200.00\n"
            "Jan 07, 2025\nPaid to Netflix\nDEBIT INR 649\n"
            "Page 1 of 1\n"
        )
        items = transaction_parser.parse_statement_text(text)
        self.assertEqual(
            [(i["merchant"], i["type"], i["amount"]) for i in items],
            [
                ("Swiggy", "expense", 450.0),
                ("Rahul Kumar", "income", 1200.0),
                ("Netflix", "expense", 649.0),
            ],
        )
        self.assertEqual(items[0]["category"], "Food & Dining")

    def test_bad_pdf_rejected(self):
        with self.assertRaises(ValueError):
            run(transaction_parser.parse_statement_file(b"not a pdf", "pdf"))
        with self.assertRaises(ValueError):
            run(transaction_parser.parse_statement_file(b"x", "exe"))

    def test_import_dedupes(self):
        with SessionLocal() as db:
            u = new_user(db)
            items = transaction_parser.parse_statement_text(
                "Jan 05, 2025\nPaid to Swiggy\nDEBIT ₹450.00\n"
            )
            a = transaction_parser.import_parsed_transactions(db, u.id, items)
            b = transaction_parser.import_parsed_transactions(db, u.id, items)
        self.assertEqual((a["imported"], b["imported"], b["skipped_duplicates"]), (1, 0, 1))


class VaultTests(unittest.TestCase):
    def test_roundtrip_and_tamper(self):
        token = vault.encrypt_secret("AIza-secret-value")
        self.assertNotIn("secret", token)
        self.assertEqual(vault.decrypt_secret(token), "AIza-secret-value")
        self.assertNotEqual(vault.encrypt_secret("x"), vault.encrypt_secret("x"))  # random nonce
        bad = token[:-4] + ("AAAA" if token[-4:] != "AAAA" else "BBBB")
        with self.assertRaises(ValueError):
            vault.decrypt_secret(bad)
        with self.assertRaises(ValueError):
            vault.decrypt_secret("garbage")


class RotationTests(unittest.TestCase):
    def test_key_rotation(self):
        old = vault.encrypt_secret("AIza-rotate-me")
        settings.secret_key_old, prev = "test-secret", settings.secret_key
        settings.secret_key = "new-secret"
        try:
            self.assertEqual(vault.decrypt_secret(old), "AIza-rotate-me")
            settings.secret_key_old = ""
            with self.assertRaises(ValueError):
                vault.decrypt_secret(old)
        finally:
            settings.secret_key, settings.secret_key_old = prev, ""


class McpTests(unittest.TestCase):
    def setUp(self):
        with SessionLocal() as db:
            self.uid = new_user(db).id

    def test_unknown_and_bad_args_never_raise(self):
        self.assertEqual(mcp_server.execute_tool("nope")["status"], "error")
        self.assertEqual(
            mcp_server.execute_tool("log_expense", user_id=self.uid)["status"], "error"
        )
        self.assertEqual(
            mcp_server.execute_tool("log_expense", user_id=self.uid, amount=-1)["status"], "error"
        )

    def test_tools_and_skills(self):
        x = mcp_server.execute_tool
        x("log_income", user_id=self.uid, amount=30000, source_account="Bank")
        x("set_budget", user_id=self.uid, category="Food", limit=1000)
        x("log_expense", user_id=self.uid, amount=900, category="Food", account_name="Bank")
        alerts = x("skill_budget_alert_check", user_id=self.uid)["alerts"]
        self.assertEqual((alerts[0]["category"], alerts[0]["level"]), ("Food", "warning"))
        x("log_expense", user_id=self.uid, amount=200, category="Food", account_name="Bank")
        self.assertEqual(
            x("skill_budget_alert_check", user_id=self.uid)["alerts"][0]["level"], "exceeded"
        )
        ef = x("skill_emergency_fund_calculator", user_id=self.uid)
        self.assertEqual(ef["liquid_balance"], 28900.0)
        self.assertEqual(ef["monthly_burn"], 1100.0)
        self.assertEqual(
            x("get_spending_breakdown", user_id=self.uid, period="week")["total_expenses"], 1100.0
        )

    def test_recurring_detector(self):
        now = datetime.now(UTC).replace(tzinfo=None)
        with SessionLocal() as db:
            for ago in (5, 35, 65):
                ledger.record_transaction(
                    db,
                    self.uid,
                    18000,
                    "Bank",
                    "Bills & Utilities",
                    "Landlord",
                    created_at=now - timedelta(days=ago),
                )
                ledger.record_transaction(
                    db,
                    self.uid,
                    649,
                    "Bank",
                    "Entertainment",
                    "Netflix",
                    created_at=now - timedelta(days=ago),
                )
            ledger.record_transaction(db, self.uid, 300, "Bank", "Food", "Cafe")
        found = mcp_server.execute_tool("skill_recurring_bill_detector", user_id=self.uid)
        self.assertEqual([r["merchant"] for r in found["recurring"]], ["Landlord", "Netflix"])
        reduce = mcp_server.execute_tool("get_insights", user_id=self.uid, mode="reduce")
        subs = [t["tip"] for t in reduce["tips"] if t["category"] == "Subscription"]
        self.assertEqual(len(subs), 1)
        self.assertIn("Netflix", subs[0])  # rent is recurring but essential: no cancel-tip


class AgentTests(unittest.TestCase):
    def chat(self, cid, text):
        return run(agent.process_user_interaction(cid, text))

    def test_full_conversation(self):
        cid = "agent-1"
        self.assertIn("Income logged", self.chat(cid, "Received 40000 salary in Bank"))
        self.assertIn("Expense logged", self.chat(cid, "Spent 450 on dinner via Bank"))
        self.assertIn("Transferred", self.chat(cid, "Transferred 2000 from Bank to Cash"))
        bal = self.chat(cid, "what's my balance")
        self.assertIn("₹39,550.00", bal)
        self.assertIn("Food & Dining", self.chat(cid, "show my report"))
        self.assertIn("cut back", self.chat(cid, "how can I save money"))

    def test_confirmation_flow(self):
        cid = "agent-2"
        self.assertIn("confirm", self.chat(cid, "Received 90000 salary in Bank").lower())
        self.assertIn("₹0.00", self.chat(cid, "balance"))  # nothing committed yet
        self.assertIn("Income logged", self.chat(cid, "yes"))
        self.assertIn("₹90,000.00", self.chat(cid, "balance"))
        self.chat(cid, "Received 90000 in Bank")
        self.assertIn("Cancelled", self.chat(cid, "no"))
        self.assertIn("₹90,000.00", self.chat(cid, "balance"))

    def test_errors_and_fallbacks(self):
        cid = "agent-3"
        self.assertIn("Try", self.chat(cid, "blah blah"))  # no LLM key -> help hint
        self.assertIn("⚠️", self.chat(cid, "Transferred 5 from Bank to Bank"))
        self.assertIn("too long", self.chat(cid, "x" * 3000))
        self.assertIn("ruthless", self.chat(cid, "ruthless mode"))

    def test_set_key_stores_encrypted(self):
        cid = "agent-4"
        reply = self.chat(cid, "my api key AIzaSyA1234567890abcdefghijklmnop")
        self.assertIn("Gemini key saved", reply)
        from sqlalchemy import select

        from app.models import ApiKey

        with SessionLocal() as db:
            rows = db.scalars(select(ApiKey)).all()
        self.assertTrue(rows)
        self.assertTrue(all("AIza" not in r.encrypted_key for r in rows))


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "healthy"})

    def test_simulate_and_commands(self):
        r = self.client.post("/bot/simulate_chat", json={"chat_id": "77", "text": "/start"})
        self.assertIn("Welcome", r.json()["reply"])
        self.client.post(
            "/bot/simulate_chat", json={"chat_id": "77", "text": "Spent 100 on lunch via Cash"}
        )
        r = self.client.post("/bot/simulate_chat", json={"chat_id": "77", "text": "/balance"})
        self.assertIn("-₹100.00", r.json()["reply"].replace("₹-", "-₹"))
        self.assertIn(
            "Unknown command",
            self.client.post("/bot/simulate_chat", json={"chat_id": "77", "text": "/wat"}).json()[
                "reply"
            ],
        )

    def test_simulate_validation_and_toggle(self):
        self.assertEqual(
            self.client.post(
                "/bot/simulate_chat", json={"chat_id": "a b!", "text": "x"}
            ).status_code,
            422,
        )
        settings.enable_dev_endpoints = False
        try:
            self.assertEqual(
                self.client.post(
                    "/bot/simulate_chat", json={"chat_id": "1", "text": "x"}
                ).status_code,
                404,
            )
        finally:
            settings.enable_dev_endpoints = True

    def test_allowlist_blocks_strangers(self):
        settings.allowed_chat_ids = "1,2"
        try:
            r = self.client.post("/bot/simulate_chat", json={"chat_id": "99", "text": "/balance"})
            self.assertIn("private", r.json()["reply"])
            r = self.client.post("/bot/simulate_chat", json={"chat_id": "1", "text": "/help"})
            self.assertIn("Help", r.json()["reply"])
        finally:
            settings.allowed_chat_ids = ""

    def test_dev_endpoint_off_by_default(self):
        from app.config import Settings

        self.assertFalse(Settings.model_fields["enable_dev_endpoints"].default)

    def test_webhook_and_secret(self):
        upd = {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "chat": {"id": 5, "type": "private"},
                "from": {"id": 5},
                "text": "/help",
            },
        }
        self.assertIn("Help", self.client.post("/bot/webhook", json=upd).json()["reply"])
        self.assertEqual(
            self.client.post("/bot/webhook", json={"update_id": 2}).json()["status"], "ignored"
        )
        settings.webhook_secret = "s3cret"
        try:
            self.assertEqual(self.client.post("/bot/webhook", json=upd).status_code, 403)
            ok = self.client.post(
                "/bot/webhook", json=upd, headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"}
            )
            self.assertEqual(ok.status_code, 200)
        finally:
            settings.webhook_secret = ""


if __name__ == "__main__":
    unittest.main()
