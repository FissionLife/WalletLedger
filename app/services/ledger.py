from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Account, Category, Merchant, Transaction, User


def get_or_create_user(db: Session, telegram_chat_id: str) -> User:
    """Retrieves an existing user by Telegram chat ID or creates a new one."""
    stmt = select(User).where(User.telegram_chat_id == str(telegram_chat_id))
    user = db.scalar(stmt)
    if not user:
        user = User(telegram_chat_id=str(telegram_chat_id))
        db.add(user)
        db.commit()
        db.refresh(user)

        # Create default primary accounts (Pipes In)
        default_accounts = [
            Account(user_id=user.id, name="Cash", type="cash", balance=0.0),
            Account(user_id=user.id, name="Bank", type="bank", balance=0.0),
        ]
        db.add_all(default_accounts)
        db.commit()
    return user


def get_or_create_account(
    db: Session, user_id: str, account_name: str, account_type: str = "bank"
) -> Account:
    """Finds an account by name (case-insensitive) or creates it."""
    stmt = select(Account).where(
        Account.user_id == user_id,
        func.lower(Account.name) == account_name.strip().lower(),
    )
    account = db.scalar(stmt)
    if not account:
        account = Account(
            user_id=user_id,
            name=account_name.strip(),
            type=account_type,
            balance=0.0,
        )
        db.add(account)
        db.commit()
        db.refresh(account)
    return account


def get_or_create_category(
    db: Session, user_id: str, category_name: str, cat_type: str = "expense"
) -> Category:
    """Finds a category by name or creates it."""
    stmt = select(Category).where(
        Category.user_id == user_id,
        func.lower(Category.name) == category_name.strip().lower(),
    )
    cat = db.scalar(stmt)
    if not cat:
        cat = Category(
            user_id=user_id,
            name=category_name.strip().title(),
            type=cat_type,
        )
        db.add(cat)
        db.commit()
        db.refresh(cat)
    return cat


def get_or_create_merchant(
    db: Session, user_id: str, merchant_name: str, default_category_id: str | None = None
) -> Merchant:
    """Finds a merchant by name or creates it."""
    stmt = select(Merchant).where(
        Merchant.user_id == user_id,
        func.lower(Merchant.name) == merchant_name.strip().lower(),
    )
    merchant = db.scalar(stmt)
    if not merchant:
        merchant = Merchant(
            user_id=user_id,
            name=merchant_name.strip().title(),
            default_category_id=default_category_id,
        )
        db.add(merchant)
        db.commit()
        db.refresh(merchant)
    return merchant


def record_transaction(
    db: Session,
    user_id: str,
    amount: float,
    account_name: str,
    category_name: str | None = None,
    merchant_name: str | None = None,
    tx_type: str = "expense",
    description: str | None = None,
    source: str = "chat",
) -> dict[str, Any]:
    """
    Logs an expense or income and updates the corresponding account balance atomically.
    """
    account = get_or_create_account(db, user_id, account_name)

    cat_id = None
    if category_name:
        cat = get_or_create_category(db, user_id, category_name, cat_type=tx_type)
        cat_id = cat.id

    merchant_id = None
    if merchant_name:
        merchant = get_or_create_merchant(db, user_id, merchant_name, default_category_id=cat_id)
        merchant_id = merchant.id
        if not cat_id and merchant.default_category_id:
            cat_id = merchant.default_category_id

    # Update balance according to Pipe flow
    if tx_type == "expense":
        account.balance -= float(amount)
    elif tx_type == "income":
        account.balance += float(amount)

    tx = Transaction(
        user_id=user_id,
        account_id=account.id,
        category_id=cat_id,
        merchant_id=merchant_id,
        amount=float(amount),
        transaction_type=tx_type,
        description=description,
        source=source,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)

    return {
        "status": "success",
        "transaction_id": tx.id,
        "amount": tx.amount,
        "type": tx.transaction_type,
        "account": account.name,
        "new_balance": round(account.balance, 2),
        "category": category_name or "Uncategorized",
        "merchant": merchant_name or "N/A",
    }


def transfer_between_pipes(
    db: Session,
    user_id: str,
    from_account_name: str,
    to_account_name: str,
    amount: float,
    description: str | None = None,
) -> dict[str, Any]:
    """
    Transfers funds from Pipe A to Pipe B without logging an external expense.
    """
    from_account = get_or_create_account(db, user_id, from_account_name)
    to_account = get_or_create_account(db, user_id, to_account_name)

    from_account.balance -= float(amount)
    to_account.balance += float(amount)

    tx = Transaction(
        user_id=user_id,
        account_id=from_account.id,
        to_account_id=to_account.id,
        amount=float(amount),
        transaction_type="transfer",
        description=description or f"Transfer from {from_account.name} to {to_account.name}",
        source="transfer",
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)

    return {
        "status": "success",
        "transaction_id": tx.id,
        "from_account": from_account.name,
        "from_balance": round(from_account.balance, 2),
        "to_account": to_account.name,
        "to_balance": round(to_account.balance, 2),
        "transferred": float(amount),
    }


def get_account_balances(db: Session, user_id: str) -> dict[str, Any]:
    """Fetches balances for all accounts associated with user and calculates net balance."""
    stmt = select(Account).where(Account.user_id == user_id)
    accounts = list(db.scalars(stmt))

    total = sum(acc.balance for acc in accounts)
    return {
        "total_net_worth": round(total, 2),
        "accounts": [
            {"id": acc.id, "name": acc.name, "type": acc.type, "balance": round(acc.balance, 2)}
            for acc in accounts
        ],
    }


def get_spending_summary(db: Session, user_id: str, days: int = 30) -> dict[str, Any]:
    """Aggregates recent spending by category and merchant."""
    start_date = datetime.utcnow() - timedelta(days=days)

    stmt = select(Transaction).where(
        Transaction.user_id == user_id,
        Transaction.transaction_type == "expense",
        Transaction.created_at >= start_date,
    )
    txs = list(db.scalars(stmt))

    total_spent = sum(t.amount for t in txs)

    # Categories breakdown
    cat_totals: dict[str, float] = {}
    for t in txs:
        cat_name = t.category.name if getattr(t, "category", None) else "Uncategorized"
        cat_totals[cat_name] = cat_totals.get(cat_name, 0.0) + t.amount

    return {
        "period_days": days,
        "total_expenses": round(total_spent, 2),
        "transaction_count": len(txs),
        "category_breakdown": {k: round(v, 2) for k, v in cat_totals.items()},
    }
