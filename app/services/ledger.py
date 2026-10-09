from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.models import Account, Category, Merchant, Transaction, User

VALID_TX_TYPES = {"expense", "income"}
MAX_AMOUNT = 10_000_000_000.0


class LedgerError(ValueError):
    """Raised for invalid ledger operations (bad amount, unknown type, same-account transfer)."""


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _validate_amount(amount: float) -> float:
    try:
        value = round(float(amount), 2)
    except (TypeError, ValueError) as exc:
        raise LedgerError(f"Invalid amount: {amount!r}") from exc
    if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
        raise LedgerError("Amount must be a finite number")
    if value <= 0:
        raise LedgerError("Amount must be greater than zero")
    if value > MAX_AMOUNT:
        raise LedgerError("Amount is too large")
    return value


def _infer_account_type(name: str) -> str:
    n = name.lower()
    if "cash" in n:
        return "cash"
    if "card" in n or "credit" in n:
        return "credit_card"
    if any(w in n for w in ("wallet", "paytm", "gpay", "phonepe", "upi")):
        return "wallet"
    return "bank"


# ---------------------------------------------------------------------------
# get-or-create helpers. They only flush; the calling public function commits,
# so a failure anywhere rolls back the whole operation (no half-created rows).
# ---------------------------------------------------------------------------


def get_or_create_user(db: Session, telegram_chat_id: str) -> User:
    """Retrieves an existing user by Telegram chat ID or creates one with default pipes."""
    chat_id = str(telegram_chat_id)
    stmt = select(User).where(User.telegram_chat_id == chat_id)
    user = db.scalar(stmt)
    if user:
        return user
    try:
        user = User(telegram_chat_id=chat_id)
        db.add(user)
        db.flush()
        db.add_all(
            [
                Account(user_id=user.id, name="Cash", type="cash", balance=0.0),
                Account(user_id=user.id, name="Bank", type="bank", balance=0.0),
            ]
        )
        db.commit()
    except IntegrityError:  # concurrent first message from the same chat
        db.rollback()
        user = db.scalar(stmt)
        if user is None:
            raise
    db.refresh(user)
    return user


def _get_or_create_account(
    db: Session, user_id: str, account_name: str, account_type: str | None = None
) -> Account:
    name = (account_name or "").strip()
    if not name:
        raise LedgerError("Account name is required")
    account = db.scalar(
        select(Account).where(Account.user_id == user_id, func.lower(Account.name) == name.lower())
    )
    if not account:
        account = Account(
            user_id=user_id,
            name=name,
            type=account_type or _infer_account_type(name),
            balance=0.0,
        )
        db.add(account)
        db.flush()
    return account


def _get_or_create_category(
    db: Session, user_id: str, category_name: str, cat_type: str = "expense"
) -> Category:
    name = category_name.strip()
    cat = db.scalar(
        select(Category).where(
            Category.user_id == user_id, func.lower(Category.name) == name.lower()
        )
    )
    if not cat:
        cat = Category(user_id=user_id, name=name.title(), type=cat_type)
        db.add(cat)
        db.flush()
    return cat


def _get_or_create_merchant(
    db: Session, user_id: str, merchant_name: str, default_category_id: str | None = None
) -> Merchant:
    name = merchant_name.strip()
    merchant = db.scalar(
        select(Merchant).where(
            Merchant.user_id == user_id, func.lower(Merchant.name) == name.lower()
        )
    )
    if not merchant:
        merchant = Merchant(
            user_id=user_id, name=name.title(), default_category_id=default_category_id
        )
        db.add(merchant)
        db.flush()
    return merchant


# Public wrappers (commit) kept for callers that use them directly.
def get_or_create_account(
    db: Session, user_id: str, account_name: str, account_type: str | None = None
) -> Account:
    account = _get_or_create_account(db, user_id, account_name, account_type)
    db.commit()
    return account


def get_or_create_category(
    db: Session, user_id: str, category_name: str, cat_type: str = "expense"
) -> Category:
    cat = _get_or_create_category(db, user_id, category_name, cat_type)
    db.commit()
    return cat


def get_or_create_merchant(
    db: Session, user_id: str, merchant_name: str, default_category_id: str | None = None
) -> Merchant:
    merchant = _get_or_create_merchant(db, user_id, merchant_name, default_category_id)
    db.commit()
    return merchant


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


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
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Logs an expense or income and updates the account balance in one DB transaction."""
    if tx_type not in VALID_TX_TYPES:
        raise LedgerError(f"Invalid transaction type {tx_type!r}; use 'expense' or 'income'")
    value = _validate_amount(amount)

    try:
        account = _get_or_create_account(db, user_id, account_name)

        cat_id = None
        if category_name and category_name.strip():
            cat_id = _get_or_create_category(db, user_id, category_name, cat_type=tx_type).id

        merchant_id = None
        if merchant_name and merchant_name.strip():
            merchant = _get_or_create_merchant(
                db, user_id, merchant_name, default_category_id=cat_id
            )
            merchant_id = merchant.id
            if not cat_id and merchant.default_category_id:
                cat_id = merchant.default_category_id

        account.balance = round(account.balance + (value if tx_type == "income" else -value), 2)

        tx = Transaction(
            user_id=user_id,
            account_id=account.id,
            category_id=cat_id,
            merchant_id=merchant_id,
            amount=value,
            transaction_type=tx_type,
            description=description,
            source=source,
            **({"created_at": created_at} if created_at else {}),
        )
        db.add(tx)
        db.commit()
    except Exception:
        db.rollback()
        raise
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
    """Moves funds from Pipe A to Pipe B. Not an expense and not income."""
    value = _validate_amount(amount)
    if from_account_name.strip().lower() == to_account_name.strip().lower():
        raise LedgerError("Cannot transfer to the same account")

    try:
        from_account = _get_or_create_account(db, user_id, from_account_name)
        to_account = _get_or_create_account(db, user_id, to_account_name)

        from_account.balance = round(from_account.balance - value, 2)
        to_account.balance = round(to_account.balance + value, 2)

        tx = Transaction(
            user_id=user_id,
            account_id=from_account.id,
            to_account_id=to_account.id,
            amount=value,
            transaction_type="transfer",
            description=description or f"Transfer from {from_account.name} to {to_account.name}",
            source="manual",
        )
        db.add(tx)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(tx)

    return {
        "status": "success",
        "transaction_id": tx.id,
        "from_account": from_account.name,
        "from_balance": round(from_account.balance, 2),
        "to_account": to_account.name,
        "to_balance": round(to_account.balance, 2),
        "transferred": value,
    }


def get_account_balances(db: Session, user_id: str) -> dict[str, Any]:
    """Balances for every account plus the net total (the Tank)."""
    accounts = list(db.scalars(select(Account).where(Account.user_id == user_id)))
    total = sum(acc.balance for acc in accounts)
    return {
        "total_net_worth": round(total, 2),
        "accounts": [
            {"id": acc.id, "name": acc.name, "type": acc.type, "balance": round(acc.balance, 2)}
            for acc in accounts
        ],
    }


def list_transactions(
    db: Session,
    user_id: str,
    days: int = 30,
    tx_type: str | None = None,
    category: str | None = None,
    merchant: str | None = None,
) -> list[Transaction]:
    """Recent transactions (category/merchant eagerly loaded), newest first."""
    stmt = (
        select(Transaction)
        .options(joinedload(Transaction.category), joinedload(Transaction.merchant))
        .where(
            Transaction.user_id == user_id,
            Transaction.created_at >= _now() - timedelta(days=days),
        )
        .order_by(Transaction.created_at.desc())
    )
    if tx_type:
        stmt = stmt.where(Transaction.transaction_type == tx_type)
    txs = list(db.scalars(stmt).unique())
    if category:
        txs = [t for t in txs if t.category and t.category.name.lower() == category.strip().lower()]
    if merchant:
        txs = [t for t in txs if t.merchant and merchant.strip().lower() in t.merchant.name.lower()]
    return txs


def get_spending_summary(
    db: Session, user_id: str, days: int = 30, category: str | None = None
) -> dict[str, Any]:
    """Aggregates recent spending by category and merchant."""
    txs = list_transactions(db, user_id, days=days, tx_type="expense", category=category)

    cat_totals: dict[str, float] = {}
    merchant_totals: dict[str, float] = {}
    for t in txs:
        cat_name = t.category.name if t.category else "Uncategorized"
        cat_totals[cat_name] = cat_totals.get(cat_name, 0.0) + t.amount
        if t.merchant:
            merchant_totals[t.merchant.name] = merchant_totals.get(t.merchant.name, 0.0) + t.amount

    def ranked(d: dict[str, float]) -> dict[str, float]:
        return {k: round(v, 2) for k, v in sorted(d.items(), key=lambda kv: -kv[1])}

    return {
        "period_days": days,
        "total_expenses": round(sum(t.amount for t in txs), 2),
        "transaction_count": len(txs),
        "category_breakdown": ranked(cat_totals),
        "merchant_breakdown": ranked(merchant_totals),
    }
