import unittest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Category, Merchant, Transaction, User
from app.services_ai.transaction_parser import (
    categorize_transaction,
    generate_financial_insights,
    parse_chat_expense,
    parse_receipt_text,
)


class TransactionParserTests(unittest.TestCase):
    def test_parses_debit_sms_without_guessing_a_new_merchant_category(self):
        rows = parse_receipt_text(
            "02/10/2026 Your A/c XX1234 debited Rs. 450.50 to UPI-SWIGGY-182390@upi ref 123456"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["amount"], 450.50)
        self.assertEqual(rows[0]["type"], "expense")
        self.assertEqual(rows[0]["category"], "Uncategorized")
        self.assertEqual(rows[0]["date"], "2026-10-02")

    def test_parses_chat_expense(self):
        row = parse_chat_expense("Spent Rs 200 at Uber on 02-10-2026")
        self.assertIsNotNone(row)
        self.assertEqual(row["amount"], 200.0)
        self.assertEqual(row["category"], "Uncategorized")

    def test_income_and_unknown_category_are_safe(self):
        rows = parse_receipt_text("Salary credited INR 100000 from Acme Corp")
        self.assertEqual(rows[0]["type"], "income")
        self.assertEqual(rows[0]["category"], "Income")
        self.assertEqual(categorize_transaction("Something New"), "Uncategorized")

    def test_learns_category_from_users_confirmed_merchant_mapping(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine)()
        user = User(telegram_chat_id="parser-test")
        session.add(user)
        session.flush()
        category = Category(user_id=user.id, name="Entertainment", type="expense")
        session.add(category)
        session.flush()
        merchant = Merchant(user_id=user.id, name="Netflix", default_category_id=category.id)
        session.add(merchant)
        session.flush()
        self.assertEqual(
            categorize_transaction("netflix", user_id=user.id, db=session), "Entertainment"
        )
        session.add_all(
            [
                Transaction(
                    user_id=user.id,
                    category_id=category.id,
                    merchant_id=merchant.id,
                    amount=199,
                    transaction_type="expense",
                    created_at=datetime.utcnow(),
                ),
                Transaction(
                    user_id=user.id,
                    category_id=category.id,
                    merchant_id=merchant.id,
                    amount=199,
                    transaction_type="expense",
                    created_at=datetime.utcnow(),
                ),
            ]
        )
        session.commit()
        insights = generate_financial_insights(user.id, mode="reduce_money", db=session)
        self.assertEqual(insights["total_expenses"], 398.0)
        self.assertEqual(insights["top_merchants"][0]["merchant"], "Netflix")
        self.assertEqual(insights["recurring_subscriptions"][0]["occurrences"], 2)
        self.assertTrue(insights["reduce_money_tips"])
        session.close()
