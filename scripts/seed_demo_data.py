#!/usr/bin/env python3
"""Fill a Telegram chat with 3 months of realistic demo data, for showing the bot to someone.

    uv run python scripts/seed_demo_data.py --chat-id 123456789   # your own Telegram id
    uv run python scripts/seed_demo_data.py                       # a standalone "demo" user
    uv run python scripts/seed_demo_data.py --chat-id 123456789 --reset --yes   # wipe that chat's ledger data, re-seed

Then message the bot: /balance, /stats, /dashboard. The data is the same every time (fixed seed).
Use --reset only on a demo chat: it deletes that chat's ledger data first (needs --yes; keys and chat history stay).
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, func, select  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Account, Category, Merchant, Subscription, Transaction, User  # noqa: E402
from app.services import ledger  # noqa: E402

DAYS = 90

# (merchant, category, low, high, account, weight)
EVERYDAY = [
    ("Swiggy", "Food & Dining", 220, 680, "HDFC Bank", 5),
    ("Zomato", "Food & Dining", 200, 720, "HDFC Bank", 4),
    ("Starbucks", "Food & Dining", 180, 460, "Credit Card", 2),
    ("Chai Point", "Food & Dining", 60, 220, "Cash", 4),
    ("Blinkit", "Groceries", 250, 900, "HDFC Bank", 4),
    ("BigBasket", "Groceries", 900, 2600, "HDFC Bank", 2),
    ("Uber", "Transport", 110, 520, "HDFC Bank", 4),
    ("Rapido", "Transport", 50, 190, "Cash", 3),
    ("HP Petrol", "Transport", 600, 1800, "Credit Card", 1),
    ("Amazon", "Shopping", 400, 4200, "Credit Card", 2),
    ("Myntra", "Shopping", 700, 3200, "Credit Card", 1),
    ("Apollo Pharmacy", "Health", 140, 950, "HDFC Bank", 1),
    ("BookMyShow", "Entertainment", 300, 1100, "Credit Card", 1),
]
# (merchant, category, amount, account, day of month)
MONTHLY = [
    ("Landlord", "Rent", 18000, "HDFC Bank", 3),
    ("Netflix", "Entertainment", 649, "Credit Card", 7),
    ("Spotify", "Entertainment", 119, "Credit Card", 9),
    ("Cult Fit", "Health", 1500, "HDFC Bank", 12),
    ("Airtel", "Bills & Utilities", 799, "HDFC Bank", 15),
    ("BESCOM", "Bills & Utilities", 1650, "HDFC Bank", 18),
]
BUDGETS = {"Food & Dining": 7000, "Shopping": 5000, "Entertainment": 2500, "Transport": 4000}


def seed(chat_id: str, reset: bool, confirmed: bool = False) -> None:
    init_db()
    rng = random.Random(42)
    now = datetime.now(UTC).replace(tzinfo=None)
    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.telegram_chat_id == chat_id))
        if existing is not None:
            has_data = db.scalar(select(Transaction.id).where(Transaction.user_id == existing.id))
            if has_data and not reset:
                print(f"Chat '{chat_id}' already has data. Use --reset to wipe and re-seed it.")
                return
            if reset:
                counts = {
                    label: db.scalar(
                        select(func.count()).select_from(model).where(model.user_id == existing.id)
                    )
                    for label, model in (
                        ("transactions", Transaction),
                        ("accounts", Account),
                        ("categories", Category),
                        ("merchants", Merchant),
                        ("subscriptions", Subscription),
                    )
                }
                print(f"--reset will delete this chat's ledger data: {counts}")
                print("(API keys and chat history are kept.)")
                if not confirmed:
                    print("Nothing deleted. Add --yes to go ahead.")
                    return
                for model in (Transaction, Subscription, Merchant, Category, Account):
                    db.execute(delete(model).where(model.user_id == existing.id))
                db.commit()

        user = ledger.get_or_create_user(db, chat_id)
        uid = user.id
        for name, kind in (("HDFC Bank", "bank"), ("Credit Card", "credit_card")):
            ledger.get_or_create_account(db, uid, name, kind)
        for cat, limit in BUDGETS.items():
            ledger.get_or_create_category(db, uid, cat).budget_limit = float(limit)
        db.commit()

        def tx(days_ago, amount, account, category, merchant, kind="expense", note=None, hour=None):
            when = now - timedelta(days=days_ago)
            when = when.replace(
                hour=hour if hour is not None else rng.randint(8, 22), minute=rng.randint(0, 59)
            )
            when = min(when, now)  # never a time that has not happened yet
            ledger.record_transaction(
                db, uid, amount, account, category, merchant, kind, note or merchant, "manual", when
            )

        tx(DAYS, 60000, "HDFC Bank", "Opening Balance", None, "income", "Opening balance", 9)
        # salary on the 1st of each month in range, recurring bills on their day
        for months_back in range(3, -1, -1):
            base = (now.replace(day=1) - timedelta(days=30 * months_back)).replace(day=1)
            salary_day = base
            if salary_day <= now:
                tx(
                    (now - salary_day).days,
                    85000,
                    "HDFC Bank",
                    "Salary",
                    "Acme Corp",
                    "income",
                    "Salary",
                    10,
                )
            for merchant, cat, amount, account, dom in MONTHLY:
                when = base.replace(day=dom)
                if when <= now:
                    tx((now - when).days, amount, account, cat, merchant)
        # everyday spending: a few per day, weekends a bit heavier
        weights = [w for *_, w in EVERYDAY]
        for d in range(DAYS - 1, -1, -1):
            day = now - timedelta(days=d)
            for _ in range(rng.choice([0, 1, 1, 2, 2, 3]) + (1 if day.weekday() >= 5 else 0)):
                merchant, cat, lo, hi, account, _w = rng.choices(EVERYDAY, weights)[0]
                tx(d, round(rng.uniform(lo, hi), 2), account, cat, merchant)
        # a one-off big purchase this month and moving cash around
        tx(6, 24999, "Credit Card", "Shopping", "Croma", note="Headphones")
        ledger.transfer_between_pipes(db, uid, "HDFC Bank", "Cash", 5000, "ATM withdrawal")

        count = len(list(db.scalars(select(Transaction).where(Transaction.user_id == uid))))
        print(f"Seeded chat '{chat_id}' with {count} transactions over {DAYS} days.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--chat-id", default="demo", help="Telegram chat id to fill (default: demo)")
    ap.add_argument("--reset", action="store_true", help="delete that chat's ledger data first")
    ap.add_argument("--yes", action="store_true", help="confirm --reset")
    args = ap.parse_args()
    seed(args.chat_id, args.reset, args.yes)
