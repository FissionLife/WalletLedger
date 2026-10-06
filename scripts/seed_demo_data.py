#!/usr/bin/env python3
"""Create a repeatable demo profile with accounts and 50 realistic transactions."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta

from sqlalchemy import delete, select

from app.db import SessionLocal, init_db
from app.models import Account, Category, Merchant, Transaction, User

DEMO_USER_ID = "demo-meet"

# (days ago, kind, amount, account, category, merchant, description)
EXPENSES = [
    (1, "expense", 420, "UPI Wallet", "Food", "Swiggy", "Lunch order"),
    (2, "expense", 180, "UPI Wallet", "Transport", "Uber", "Ride to office"),
    (3, "expense", 1250, "Bank", "Groceries", "BigBasket", "Weekly groceries"),
    (4, "expense", 250, "Cash", "Food", "Chai Point", "Coffee and snacks"),
    (5, "expense", 899, "Bank", "Utilities", "Airtel", "Mobile and broadband"),
    (6, "expense", 320, "UPI Wallet", "Food", "Zomato", "Dinner order"),
    (8, "expense", 210, "UPI Wallet", "Transport", "Uber", "Ride home"),
    (9, "expense", 2400, "Bank", "Shopping", "Myntra", "Clothing"),
    (10, "expense", 540, "Cash", "Food", "Cafe Coffee Day", "Cafe"),
    (11, "expense", 1600, "Bank", "Health", "Apollo Pharmacy", "Medicines"),
    (12, "expense", 400, "UPI Wallet", "Food", "Swiggy", "Dinner order"),
    (13, "expense", 190, "Cash", "Transport", "Metro", "Metro card recharge"),
    (14, "expense", 2850, "Bank", "Groceries", "DMart", "Household supplies"),
    (16, "expense", 650, "UPI Wallet", "Food", "Zomato", "Weekend meal"),
    (17, "expense", 300, "Cash", "Personal", "Salon", "Haircut"),
    (18, "expense", 540, "UPI Wallet", "Transport", "Uber", "Airport ride"),
    (19, "expense", 499, "Bank", "Subscriptions", "Netflix", "Monthly subscription"),
    (20, "expense", 3100, "Bank", "Utilities", "Electricity Board", "Electricity bill"),
    (22, "expense", 380, "UPI Wallet", "Food", "Swiggy", "Lunch order"),
    (23, "expense", 1700, "Bank", "Shopping", "Amazon", "Home supplies"),
    (25, "expense", 220, "UPI Wallet", "Transport", "Uber", "Ride to station"),
    (27, "expense", 1150, "Bank", "Groceries", "BigBasket", "Groceries"),
    (29, "expense", 500, "Cash", "Food", "Local Restaurant", "Dinner with friends"),
    (31, "expense", 410, "UPI Wallet", "Food", "Zomato", "Dinner order"),
    (33, "expense", 185, "UPI Wallet", "Transport", "Uber", "Ride home"),
    (35, "expense", 1350, "Bank", "Groceries", "DMart", "Monthly groceries"),
    (37, "expense", 499, "Bank", "Subscriptions", "Netflix", "Monthly subscription"),
    (39, "expense", 280, "Cash", "Food", "Chai Point", "Coffee"),
    (41, "expense", 1500, "Bank", "Health", "Apollo Pharmacy", "Health supplies"),
    (43, "expense", 360, "UPI Wallet", "Food", "Swiggy", "Lunch order"),
    (45, "expense", 260, "UPI Wallet", "Transport", "Uber", "Ride to office"),
    (47, "expense", 2200, "Bank", "Shopping", "Myntra", "Shoes"),
    (49, "expense", 680, "Cash", "Food", "Local Restaurant", "Dinner"),
    (51, "expense", 1250, "Bank", "Groceries", "BigBasket", "Groceries"),
    (53, "expense", 499, "Bank", "Subscriptions", "Netflix", "Monthly subscription"),
    (55, "expense", 310, "UPI Wallet", "Food", "Zomato", "Lunch order"),
    (57, "expense", 260, "UPI Wallet", "Transport", "Uber", "Ride home"),
    (59, "expense", 920, "Bank", "Utilities", "Airtel", "Mobile plan"),
    (61, "expense", 480, "Cash", "Food", "Chai Point", "Cafe"),
    (63, "expense", 1800, "Bank", "Shopping", "Amazon", "Kitchen items"),
    (65, "expense", 330, "UPI Wallet", "Food", "Swiggy", "Dinner order"),
    (67, "expense", 210, "UPI Wallet", "Transport", "Uber", "Ride to office"),
    (69, "expense", 499, "Bank", "Subscriptions", "Netflix", "Monthly subscription"),
]

INCOMES = [
    (3, "income", 82000, "Bank", "Salary", "Acme Technologies", "Monthly salary"),
    (15, "income", 2400, "Bank", "Freelance", "Design client", "Website design work"),
    (32, "income", 82000, "Bank", "Salary", "Acme Technologies", "Monthly salary"),
    (40, "income", 1800, "UPI Wallet", "Refund", "Amazon", "Order refund"),
    (48, "income", 3500, "Bank", "Freelance", "Design client", "Logo design work"),
    (62, "income", 82000, "Bank", "Salary", "Acme Technologies", "Monthly salary"),
    (70, "income", 500, "Cash", "Other Income", "Cashback", "Card cashback"),
]


def seed_demo_data(telegram_chat_id: str = DEMO_USER_ID) -> dict[str, int | str]:
    init_db()
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.telegram_chat_id == telegram_chat_id))
        if user is None:
            user = User(telegram_chat_id=telegram_chat_id)
            db.add(user)
            db.flush()

        # Re-running the script refreshes its demo dataset without touching other users.
        db.execute(delete(Transaction).where(Transaction.user_id == user.id))
        db.execute(delete(Merchant).where(Merchant.user_id == user.id))
        db.execute(delete(Category).where(Category.user_id == user.id))
        db.execute(delete(Account).where(Account.user_id == user.id))
        db.flush()

        accounts = {
            "Bank": Account(user_id=user.id, name="Bank", type="bank", balance=45000),
            "Cash": Account(user_id=user.id, name="Cash", type="cash", balance=6000),
            "UPI Wallet": Account(user_id=user.id, name="UPI Wallet", type="wallet", balance=2500),
        }
        categories: dict[str, Category] = {}
        merchant_map: dict[str, Merchant] = {}
        db.add_all(accounts.values())
        db.flush()

        now = datetime.utcnow()
        items = sorted(EXPENSES + INCOMES, key=lambda item: item[0])
        for (
            days_ago,
            kind,
            amount,
            account_name,
            category_name,
            merchant_name,
            description,
        ) in items:
            cat_type = "income" if kind == "income" else "expense"
            cat_key = f"{cat_type}:{category_name}"
            if cat_key not in categories:
                categories[cat_key] = Category(
                    user_id=user.id,
                    name=category_name,
                    type=cat_type,
                    budget_limit=(
                        12000
                        if category_name == "Food"
                        else 10000
                        if category_name == "Shopping"
                        else None
                    ),
                )
                db.add(categories[cat_key])
                db.flush()
            if merchant_name not in merchant_map:
                merchant_map[merchant_name] = Merchant(
                    user_id=user.id,
                    name=merchant_name,
                    default_category_id=categories[cat_key].id,
                )
                db.add(merchant_map[merchant_name])
                db.flush()
            account = accounts[account_name]
            tx = Transaction(
                user_id=user.id,
                account_id=account.id,
                category_id=categories[cat_key].id,
                merchant_id=merchant_map[merchant_name].id,
                amount=amount,
                transaction_type=kind,
                description=description,
                source="demo",
                created_at=now - timedelta(days=days_ago),
            )
            db.add(tx)
            account.balance += amount if kind == "income" else -amount

        db.commit()
        return {
            "user_id": user.id,
            "telegram_chat_id": telegram_chat_id,
            "accounts": len(accounts),
            "transactions": len(items),
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--telegram-chat-id", default=DEMO_USER_ID)
    args = parser.parse_args()
    result = seed_demo_data(args.telegram_chat_id)
    print(
        f"Seeded demo user {result['telegram_chat_id']}: "
        f"{result['accounts']} accounts and {result['transactions']} transactions."
    )


if __name__ == "__main__":
    main()
