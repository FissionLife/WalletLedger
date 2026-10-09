# Role 4: MCP-style tool registry + financial skills.
# The LangGraph agent calls `execute_tool(name, **kwargs)`; every tool returns plain JSON-able dicts
# and never raises (errors come back as {"status": "error", "error": ...}).
import inspect
import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Category
from app.services import ledger
from app.services_ai import ai_gateway, transaction_parser

logger = logging.getLogger(__name__)

PERIOD_DAYS = {"day": 1, "today": 1, "week": 7, "month": 30, "quarter": 90, "year": 365}

TOOLS: dict[str, Callable[..., dict]] = {}


def tool(fn: Callable[..., dict]) -> Callable[..., dict]:
    TOOLS[fn.__name__] = fn
    return fn


def _period_to_days(period: str | int) -> int:
    if isinstance(period, int):
        return max(1, min(period, 3650))
    try:
        return max(1, min(int(period), 3650))
    except Exception:
        return PERIOD_DAYS.get(str(period).lower(), 30)


# ----------------------------- core tools ---------------------------------


@tool
def log_expense(
    user_id: str,
    amount: float,
    category: str | None = None,
    merchant: str | None = None,
    account_name: str = "Cash",
    description: str | None = None,
) -> dict:
    with SessionLocal() as db:
        return ledger.record_transaction(
            db, user_id, amount, account_name, category, merchant, "expense", description
        )


@tool
def log_income(
    user_id: str,
    amount: float,
    source_account: str = "Bank",
    description: str | None = None,
    category: str | None = "Income",
) -> dict:
    with SessionLocal() as db:
        return ledger.record_transaction(
            db, user_id, amount, source_account, category, None, "income", description
        )


@tool
def transfer_between_pipes(user_id: str, from_account: str, to_account: str, amount: float) -> dict:
    with SessionLocal() as db:
        return ledger.transfer_between_pipes(db, user_id, from_account, to_account, amount)


@tool
def get_pipe_balances(user_id: str) -> dict:
    with SessionLocal() as db:
        return ledger.get_account_balances(db, user_id)


@tool
def get_spending_breakdown(
    user_id: str, period: str | int = "month", category: str | None = None
) -> dict:
    with SessionLocal() as db:
        return ledger.get_spending_summary(db, user_id, _period_to_days(period), category)


@tool
def set_budget(user_id: str, category: str, limit: float) -> dict:
    value = ledger._validate_amount(limit)
    with SessionLocal() as db:
        cat = ledger.get_or_create_category(db, user_id, category)
        cat.budget_limit = value
        db.commit()
        return {"status": "success", "category": cat.name, "budget_limit": value}


@tool
def save_user_api_key(user_id: str, provider: str | None, api_key: str) -> dict:
    with SessionLocal() as db:
        return ai_gateway.save_api_key(db, user_id, api_key, provider)


# ----------------------------- financial skills ---------------------------


@tool
def skill_budget_alert_check(user_id: str) -> dict:
    """Flags categories at >=80% (warning) or >=100% (exceeded) of their monthly budget."""
    from datetime import UTC, datetime

    now = datetime.now(UTC).replace(tzinfo=None)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    with SessionLocal() as db:
        cats = db.scalars(
            select(Category).where(Category.user_id == user_id, Category.budget_limit.is_not(None))
        ).all()
        spent: dict[str, float] = {}
        for t in ledger.list_transactions(db, user_id, days=32, tx_type="expense"):
            if t.created_at >= month_start and t.category_id:
                spent[t.category_id] = spent.get(t.category_id, 0.0) + t.amount
        alerts = []
        for c in cats:
            if not c.budget_limit or c.budget_limit <= 0:
                continue
            used = spent.get(c.id, 0.0)
            pct = used / c.budget_limit
            if pct >= 0.8:
                alerts.append(
                    {
                        "category": c.name,
                        "spent": round(used, 2),
                        "budget": c.budget_limit,
                        "percent_used": round(pct * 100, 1),
                        "level": "exceeded" if pct >= 1 else "warning",
                    }
                )
        alerts.sort(key=lambda a: -a["percent_used"])
        return {"status": "success", "alerts": alerts, "budgets_tracked": len(cats)}


@tool
def skill_recurring_bill_detector(user_id: str) -> dict:
    with SessionLocal() as db:
        found = transaction_parser.detect_recurring(db, user_id)
    return {
        "status": "success",
        "recurring": found,
        "total_monthly_cost": round(sum(r["monthly_cost"] for r in found), 2),
    }


@tool
def skill_emergency_fund_calculator(user_id: str, target_months: int = 6) -> dict:
    """Liquid balances (cash/bank/wallet, not credit cards) vs. monthly burn rate."""
    with SessionLocal() as db:
        balances = ledger.get_account_balances(db, user_id)
        burn = ledger.get_spending_summary(db, user_id, 30)["total_expenses"]
    liquid = round(sum(a["balance"] for a in balances["accounts"] if a["type"] != "credit_card"), 2)
    runway = round(liquid / burn, 1) if burn > 0 else None
    target = round(burn * target_months, 2)
    return {
        "status": "success",
        "liquid_balance": liquid,
        "monthly_burn": burn,
        "runway_months": runway,
        "target_months": target_months,
        "target_amount": target,
        "shortfall": round(max(0.0, target - liquid), 2),
        "verdict": (
            "no spending data yet"
            if runway is None
            else "healthy"
            if runway >= target_months
            else "build your buffer"
        ),
    }


@tool
def get_insights(user_id: str, mode: str = "summary") -> dict:
    return {"status": "success", **transaction_parser.generate_financial_insights(user_id, mode)}


# ----------------------------- dispatcher ---------------------------------


def list_tools() -> list[str]:
    return sorted(TOOLS)


def execute_tool(tool_name: str, **kwargs: Any) -> dict:
    """Executes a registered tool and returns structured JSON. Never raises."""
    fn = TOOLS.get(tool_name)
    if fn is None:
        return {"status": "error", "error": f"Unknown tool: {tool_name}"}
    try:
        inspect.signature(fn).bind(**kwargs)
    except TypeError as exc:
        return {"status": "error", "error": f"Bad arguments for {tool_name}: {exc}"}
    try:
        return fn(**kwargs)
    except (ledger.LedgerError, ValueError) as exc:
        return {"status": "error", "error": str(exc)}
    except Exception:
        logger.exception("Tool %s crashed", tool_name)
        return {"status": "error", "error": "Internal error while running the tool"}


# Backward-compatible names from the original stubs
def get_balance_tool(customer_id: str) -> dict:
    return execute_tool("get_pipe_balances", user_id=customer_id)


def log_expense_tool(customer_id: str, amount: float, category: str) -> dict:
    return execute_tool("log_expense", user_id=customer_id, amount=amount, category=category)


__all__ = ["TOOLS", "execute_tool", "list_tools"]
