"""Typed financial tools exposed to the conversational agent.

These functions are ordinary Python tools (the project does not currently run an
MCP transport server). The registry gives the agent one stable dispatch point.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Account, ApiKey, Category, Merchant, Transaction, User
from app.services.ledger import (
    get_account_balances,
    get_or_create_user,
    get_spending_summary,
    record_transaction,
    transfer_between_pipes,
)


def _with_db(fn: Callable[..., dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
    db = SessionLocal()
    try:
        return fn(db=db, **kwargs)
    finally:
        db.close()


def _resolve_user(db: Session, user_id: str) -> User:
    """Accept either the internal user UUID or the Telegram chat ID contract."""
    user = db.get(User, str(user_id))
    if user is None:
        user = db.scalar(select(User).where(User.telegram_chat_id == str(user_id)))
    return user or get_or_create_user(db, str(user_id))


def _positive_amount(amount: float) -> float:
    amount = float(amount)
    if amount <= 0:
        raise ValueError("amount must be greater than zero")
    return amount


def log_expense(
    user_id: str,
    amount: float,
    category: str,
    merchant: str | None = None,
    account_name: str = "Cash",
    description: str | None = None,
) -> dict[str, Any]:
    """Record an expense and debit its payment account."""
    def run(db: Session, **values: Any) -> dict[str, Any]:
        user = _resolve_user(db, values.pop("user_id"))
        values["user_id"] = user.id
        values["amount"] = _positive_amount(values["amount"])
        return record_transaction(db, tx_type="expense", **values)

    return _with_db(run, user_id=user_id, amount=amount, category_name=category,
                    merchant_name=merchant, account_name=account_name, description=description)


def log_income(
    user_id: str,
    amount: float,
    source_account: str = "Bank",
    category: str = "Income",
    description: str | None = None,
) -> dict[str, Any]:
    """Record income and credit its destination account."""
    def run(db: Session, **values: Any) -> dict[str, Any]:
        user = _resolve_user(db, values.pop("user_id"))
        values["user_id"] = user.id
        values["amount"] = _positive_amount(values["amount"])
        return record_transaction(db, tx_type="income", **values)

    return _with_db(run, user_id=user_id, amount=amount, account_name=source_account,
                    category_name=category, description=description)


def transfer_funds(
    user_id: str,
    from_account: str,
    to_account: str,
    amount: float,
    description: str | None = None,
) -> dict[str, Any]:
    """Transfer money between accounts without recording an expense."""
    def run(db: Session, **values: Any) -> dict[str, Any]:
        user = _resolve_user(db, values.pop("user_id"))
        values["user_id"] = user.id
        values["amount"] = _positive_amount(values["amount"])
        return transfer_between_pipes(db, **values)

    return _with_db(run, user_id=user_id, from_account_name=from_account,
                    to_account_name=to_account, amount=amount, description=description)


def get_pipe_balances(user_id: str) -> dict[str, Any]:
    def run(db: Session, user_id: str) -> dict[str, Any]:
        return get_account_balances(db, _resolve_user(db, user_id).id)

    return _with_db(run, user_id=user_id)


def get_spending_breakdown(
    user_id: str, period: str = "month", category: str | None = None
) -> dict[str, Any]:
    """Return spending totals; period accepts week, month, quarter, or year."""
    periods = {"week": 7, "month": 30, "quarter": 90, "year": 365}
    if period not in periods:
        raise ValueError("period must be one of: week, month, quarter, year")

    def run(db: Session, user_id: str) -> dict[str, Any]:
        uid = _resolve_user(db, user_id).id
        start = datetime.utcnow() - timedelta(days=periods[period])
        stmt = (
            select(Category.name, func.sum(Transaction.amount))
            .outerjoin(Category, Transaction.category_id == Category.id)
            .where(Transaction.user_id == uid,
                   Transaction.transaction_type == "expense",
                   Transaction.created_at >= start)
            .group_by(Category.name)
        )
        breakdown = {name or "Uncategorized": round(float(total), 2)
                     for name, total in db.execute(stmt)}
        if category:
            breakdown = {name: total for name, total in breakdown.items()
                         if name.casefold() == category.casefold()}
        return {"period": period, "period_days": periods[period],
                "total_expenses": round(sum(breakdown.values()), 2),
                "category_breakdown": breakdown}

    return _with_db(run, user_id=user_id)


def skill_budget_alert_check(user_id: str) -> dict[str, Any]:
    """Report categories at or above 80% of their monthly budget."""
    def run(db: Session, user_id: str) -> dict[str, Any]:
        uid = _resolve_user(db, user_id).id
        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        stmt = (
            select(Category, func.coalesce(func.sum(Transaction.amount), 0.0))
            .outerjoin(Transaction, (Transaction.category_id == Category.id)
                       & (Transaction.user_id == uid)
                       & (Transaction.transaction_type == "expense")
                       & (Transaction.created_at >= month_start))
            .where(Category.user_id == uid, Category.type == "expense",
                   Category.budget_limit.is_not(None))
            .group_by(Category.id)
        )
        alerts = []
        for category, spent in db.execute(stmt):
            limit = float(category.budget_limit or 0)
            if limit > 0 and spent / limit >= 0.8:
                alerts.append({"category": category.name, "spent": round(spent, 2),
                               "budget": limit, "used_percent": round(spent / limit * 100, 1),
                               "level": "exceeded" if spent >= limit else "warning"})
        return {"month": now.strftime("%Y-%m"), "alerts": alerts}

    return _with_db(run, user_id=user_id)


def skill_recurring_bill_detector(user_id: str) -> dict[str, Any]:
    """Find merchants with similar expense amounts in at least three months."""
    def run(db: Session, user_id: str) -> dict[str, Any]:
        uid = _resolve_user(db, user_id).id
        start = datetime.utcnow() - timedelta(days=183)
        rows = db.execute(
            select(Transaction, Account.name, Category.name)
            .outerjoin(Account, Transaction.account_id == Account.id)
            .outerjoin(Category, Transaction.category_id == Category.id)
            .where(Transaction.user_id == uid, Transaction.transaction_type == "expense",
                   Transaction.created_at >= start)
        )
        grouped: dict[str, list[tuple[Transaction, str | None, str | None]]] = {}
        for tx, _account, _category in rows:
            label = tx.merchant_id or (tx.description or "").strip().casefold()
            if label:
                grouped.setdefault(label, []).append((tx, _account, _category))
        bills = []
        for entries in grouped.values():
            months = {entry[0].created_at.strftime("%Y-%m") for entry in entries}
            amounts = [entry[0].amount for entry in entries]
            if len(months) >= 3 and max(amounts) - min(amounts) <= max(5.0, max(amounts) * 0.1):
                latest = max(entries, key=lambda item: item[0].created_at)[0]
                merchant = db.get(Merchant, latest.merchant_id) if latest.merchant_id else None
                bills.append({"merchant": merchant.name if merchant else latest.description,
                              "amount": round(sum(amounts) / len(amounts), 2),
                              "occurrences": len(entries), "months": len(months)})
        return {"recurring_bills": bills}

    return _with_db(run, user_id=user_id)


def skill_emergency_fund_calculator(user_id: str) -> dict[str, Any]:
    """Estimate liquid runway using current cash-like balances and 90-day spend."""
    def run(db: Session, user_id: str) -> dict[str, Any]:
        uid = _resolve_user(db, user_id).id
        balances = list(db.scalars(select(Account).where(Account.user_id == uid)))
        liquid = sum(a.balance for a in balances if a.type.casefold() in {"cash", "bank", "wallet"})
        summary = get_spending_summary(db, uid, 90)
        monthly_burn = summary["total_expenses"] / 3
        months = liquid / monthly_burn if monthly_burn > 0 else None
        return {"liquid_balance": round(liquid, 2), "average_monthly_expenses": round(monthly_burn, 2),
                "runway_months": round(months, 2) if months is not None else None,
                "target_3_month_fund": round(monthly_burn * 3, 2),
                "shortfall_to_3_month_target": round(max(0, monthly_burn * 3 - liquid), 2)}

    return _with_db(run, user_id=user_id)


def save_user_api_key(user_id: str, provider: str, api_key: str) -> dict[str, Any]:
    """Encrypt and store a provider key using the application's configured secret."""
    if not api_key.strip() or not provider.strip():
        raise ValueError("provider and api_key are required")

    def run(db: Session, user_id: str) -> dict[str, Any]:
        from cryptography.fernet import Fernet
        import base64
        import hashlib
        from app.config import settings

        uid = _resolve_user(db, user_id).id
        secret = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
        encrypted = Fernet(base64.urlsafe_b64encode(secret)).encrypt(api_key.encode()).decode()
        record = ApiKey(user_id=uid, provider=provider.strip().lower(), encrypted_key=encrypted)
        db.add(record)
        db.commit()
        return {"status": "success", "provider": record.provider, "key_id": record.id}

    return _with_db(run, user_id=user_id)


# Legacy function names retained for any in-progress agent integration.
def get_balance_tool(customer_id: str) -> dict[str, Any]:
    return get_pipe_balances(customer_id)


def log_expense_tool(customer_id: str, amount: float, category: str) -> dict[str, Any]:
    return log_expense(customer_id, amount, category)


TOOL_REGISTRY: dict[str, Callable[..., dict[str, Any]]] = {
    "log_expense": log_expense,
    "log_income": log_income,
    "transfer_between_pipes": transfer_funds,
    "transfer_funds": transfer_funds,
    "get_pipe_balances": get_pipe_balances,
    "get_spending_breakdown": get_spending_breakdown,
    "save_user_api_key": save_user_api_key,
    "skill_budget_alert_check": skill_budget_alert_check,
    "skill_recurring_bill_detector": skill_recurring_bill_detector,
    "skill_emergency_fund_calculator": skill_emergency_fund_calculator,
}


def execute_tool(tool_name: str, **kwargs: Any) -> dict[str, Any]:
    """Dispatch one registered agent tool and return a JSON-serializable result."""
    try:
        tool = TOOL_REGISTRY[tool_name]
    except KeyError as exc:
        raise ValueError(f"Unknown tool: {tool_name}") from exc
    return tool(**kwargs)
