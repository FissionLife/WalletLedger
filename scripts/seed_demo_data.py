#!/usr/bin/env python3
"""Seeds a demo user (chat id "demo") with 3 accounts and ~50 realistic transactions.

Usage:  uv run python scripts/seed_demo_data.py [--chat-id demo] [--reset]
Talk to the demo data via:  POST /bot/simulate_chat {"chat_id": "demo", "text": "/balance"}
"""

import argparse
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Transaction, User  # noqa: E402
from app.services import ledger  # noqa: E402

DAILY = [
    ("Swiggy", "Food & Dining", 250, 650),
    ("Zomato", "Food & Dining", 200, 700),
    ("Starbucks", "Food & Dining", 180, 420),
    ("Uber", "Transport", 120, 480),
    ("Ola", "Transport", 100, 400),
    ("Bigbasket", "Groceries", 600, 2200),
    ("Amazon", "Shopping", 400, 3500),
    ("Myntra", "Shopping", 700, 2800),
    ("Apollo Pharmacy", "Health", 150, 900),
    ("Bookmyshow", "Entertainment", 300, 900),
]
MONTHLY = [
    ("Netflix", "Entertainment", 649, "Credit Card"),
    ("Spotify", "Entertainment", 119, "Credit Card"),
    ("Cult Fit", "Health", 1500, "HDFC Bank"),
    ("Landlord", "Bills & Utilities", 18000, "HDFC Bank"),
    ("Airtel", "Bills & Utilities", 799, "HDFC Bank"),
]


def seed(chat_id: str, reset: bool) -> None:
    init_db()
    rng = random.Random(42)
    now = datetime.now(UTC).replace(tzinfo=None)
    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.telegram_chat_id == chat_id))
        if existing and reset:
            db.delete(existing)
            db.commit()
            existing = None
        if existing and db.scalar(select(Transaction).where(Transaction.user_id == existing.id)):
            print(f"Demo user '{chat_id}' already has data. Use --reset to recreate it.")
            return

        user = ledger.get_or_create_user(db, chat_id)
        for name, kind in (("HDFC Bank", "bank"), ("Credit Card", "credit_card")):
            ledger.get_or_create_account(db, user.id, name, kind)

        for cat, limit in (("Food & Dining", 6000), ("Shopping", 5000), ("Entertainment", 2500)):
            ledger.get_or_create_category(db, user.id, cat).budget_limit = float(limit)
        db.commit()

        # opening balance + salary, two months back and this month
        ledger.record_transaction(
            db,
            user.id,
            40000,
            "HDFC Bank",
            "Opening Balance",
            None,
            "income",
            "Opening balance",
            "manual",
            now - timedelta(days=62),
        )
        for months_ago in (2, 1, 0):
            when = now - timedelta(days=30 * months_ago + 1)
            ledger.record_transaction(
                db,
                user.id,
                85000,
                "HDFC Bank",
                "Salary",
                "Acme Corp",
                "income",
                "Monthly salary",
                "manual",
                when,
            )
            for merchant, cat, amount, account in MONTHLY:
                ledger.record_transaction(
                    db,
                    user.id,
                    amount,
                    account,
                    cat,
                    merchant,
                    "expense",
                    f"{merchant} subscription",
                    "manual",
                    when + timedelta(hours=2),
                )
        ledger.transfer_between_pipes(db, user.id, "HDFC Bank", "Cash", 30000, "ATM withdrawal")

        for _ in range(30):
            merchant, cat, lo, hi = rng.choice(DAILY)
            account = rng.choice(["HDFC Bank", "Cash", "Credit Card"])
            ledger.record_transaction(
                db,
                user.id,
                round(rng.uniform(lo, hi), 2),
                account,
                cat,
                merchant,
                "expense",
                f"{merchant} purchase",
                "manual",
                now - timedelta(days=rng.randint(0, 59), hours=rng.randint(0, 20)),
            )

        count = len(list(db.scalars(select(Transaction).where(Transaction.user_id == user.id))))
        print(f"Seeded demo user '{chat_id}' with {count} transactions.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--chat-id", default="demo")
    ap.add_argument("--reset", action="store_true", help="delete and recreate this demo user")
    args = ap.parse_args()
    seed(args.chat_id, args.reset)
