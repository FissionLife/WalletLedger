"""The agent: reads a message, picks ledger tools, asks for confirmation when needed, writes the reply.

A small LangGraph flowchart (llm_reasoning -> confirmation -> tool_executor -> response_synthesizer).
Clear messages are read by the rules in nlu.py with no AI; goals and questions go to the multi-step
helper in orchestrator.py when the user has an AI key; without one only fixed requests (balance,
spending, advice) work and anything else gets a short hint, never a guessed expense.
Conversation history is saved in the database (encrypted, API keys redacted).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from sqlalchemy import select

from app.bot import nlu, orchestrator, replies
from app.bot.keys import save_keys
from app.db import SessionLocal
from app.models import ChatMessage, User
from app.services.ledger import get_or_create_user
from app.services_ai import tool_client
from app.services_ai.ai_gateway import (
    NoAPIKeyError,
    ask_llm,
    ask_persona,
    extract_api_keys,
    get_user_api_keys,
    has_server_keys,
    mask_key,
)
from app.services_ai.prompts import detect_mode, get_persona, resolve_mode

logger = logging.getLogger(__name__)

# Transfer amount threshold that requires explicit human-in-the-loop confirmation
CONFIRMATION_TRANSFER_THRESHOLD = 5000.0

# A pending confirmation older than this is discarded, so a stale "yes" can never move money.
PENDING_ACTION_TTL = timedelta(minutes=5)

# Only the most recent N prior messages are sent to the LLM as conversation history.
HISTORY_LIMIT = 20

CONFIRM_WORDS = {
    "yes", "y", "yeah", "yep", "yup", "confirm", "confirmed", "proceed", "ok", "okay",
    "sure", "approve", "approved", "do it", "go ahead", "yes please", "yes go ahead",
}  # fmt: skip
CANCEL_WORDS = {
    "no", "n", "nope", "nah", "cancel", "abort", "reject", "stop", "don't", "dont",
    "no thanks", "dont do it", "don't do it",
}  # fmt: skip

# Tools whose results are turned into a reply by a persona (Coach / Budgeter / Summary).
PERSONA_TOOLS = {
    "financial_advice_bundle",
    "get_spending_breakdown",
    "skill_budget_alert_check",
    "skill_recurring_bill_detector",
    "skill_emergency_fund_calculator",
}
PERSONA_COMMAND = re.compile(r"^\s*/(coach|budgeter|summary)\b(.*)$", re.I | re.S)


def _utc_now() -> datetime:
    """Helper to return current timezone-aware UTC datetime."""
    return datetime.now(UTC)


def classify_reply(text: str) -> Literal["confirmed", "cancelled"] | None:
    """Map a short yes/no style reply to a decision; anything else returns None."""
    normalised = re.sub(r"[^\w\s']", " ", (text or "").lower())
    normalised = re.sub(r"\s+", " ", normalised).strip()
    if normalised in CONFIRM_WORDS:
        return "confirmed"
    if normalised in CANCEL_WORDS:
        return "cancelled"
    return None


def redact_api_keys(text: str) -> str:
    """Replace every recognisable API key in ``text`` with its masked form."""
    for _, key in extract_api_keys(text):
        text = text.replace(key, mask_key(key))
    return text


# ---------------------------------------------------------------------------
# Database-Backed Persistent Conversation History
# ---------------------------------------------------------------------------


def get_db_conversation_history(user_id: str, limit: int | None = None) -> list[BaseMessage]:
    """Fetch a user's stored conversation (oldest first); ``limit`` keeps only the newest N."""
    db = SessionLocal()
    try:
        user = db.get(User, str(user_id))
        if user is None:
            user = db.scalar(select(User).where(User.telegram_chat_id == str(user_id)))
        if not user:
            return []

        stmt = select(ChatMessage).where(ChatMessage.user_id == user.id)
        if limit:
            stmt = stmt.order_by(ChatMessage.created_at.desc()).limit(limit)
            records = list(reversed(list(db.scalars(stmt))))
        else:
            records = list(db.scalars(stmt.order_by(ChatMessage.created_at.asc())))
        messages: list[BaseMessage] = []
        for r in records:
            if r.role == "user":
                messages.append(HumanMessage(content=r.content))
            elif r.role == "assistant":
                messages.append(AIMessage(content=r.content))
        return messages
    finally:
        db.close()


def save_db_chat_message(user_id: str, role: str, content: str) -> None:
    """Persists a chat message permanently into the database."""
    if not content or not content.strip():
        return
    db = SessionLocal()
    try:
        user = db.get(User, str(user_id))
        if user is None:
            user = db.scalar(select(User).where(User.telegram_chat_id == str(user_id)))
        if not user:
            user = get_or_create_user(db, telegram_chat_id=str(user_id))

        msg = ChatMessage(user_id=user.id, role=role, content=content.strip())
        db.add(msg)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Error saving chat message to database: {e}", exc_info=True)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Tool Schemas for LLM Tool Calling (OpenAI / Gemini / LiteLLM format)
# ---------------------------------------------------------------------------

TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "log_expense",
            "description": "Record an expense transaction and debit the specified payment account (pipe).",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {
                        "type": "number",
                        "description": "The amount spent (must be greater than 0).",
                    },
                    "category": {
                        "type": "string",
                        "description": "The expense category (e.g. Food, Groceries, Transport, Shopping, Utilities, Subscriptions, Health, Personal Care, Entertainment, Rent, Gifts).",
                    },
                    "merchant": {
                        "type": "string",
                        "description": "The merchant, vendor, or payee name if identified (e.g. Swiggy, Uber, Starbucks, Amazon, Netflix, Poornima).",
                    },
                    "account_name": {
                        "type": "string",
                        "description": "The source payment account (pipe) used (e.g. Cash, Bank, UPI Wallet). Default to Cash if unspecified.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief description of the expense item.",
                    },
                    "date": {
                        "type": "string",
                        "description": "YYYY-MM-DD, only when the user says it happened on another day (e.g. yesterday). Omit for today.",
                    },
                },
                "required": ["amount", "category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_income",
            "description": "Record an income deposit and credit the specified destination account (pipe).",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {
                        "type": "number",
                        "description": "The income amount received (must be greater than 0).",
                    },
                    "source_account": {
                        "type": "string",
                        "description": "The destination account/pipe receiving the funds (e.g. Bank, Cash, UPI Wallet). Default to Bank.",
                    },
                    "category": {
                        "type": "string",
                        "description": "The income category (e.g. Salary, Freelance, Stipend, Cashback, Refund, Investment). Default to Income.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief description of the income source.",
                    },
                },
                "required": ["amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "transfer_funds",
            "description": "Transfer funds between two account pipes without logging an expense.",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {
                        "type": "number",
                        "description": "The amount to transfer between pipes.",
                    },
                    "from_account": {
                        "type": "string",
                        "description": "The source account to debit (e.g. Bank, Cash, UPI Wallet).",
                    },
                    "to_account": {
                        "type": "string",
                        "description": "The destination account to credit (e.g. Cash, Bank, UPI Wallet).",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional description or note for the transfer.",
                    },
                },
                "required": ["amount", "from_account", "to_account"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pipe_balances",
            "description": "Query liquid balances for all account pipes (Bank, Cash, Wallets) and total net worth.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_spending_breakdown",
            "description": "Query spending totals grouped by category over a time period (week, month, quarter, year).",
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "enum": ["week", "month", "quarter", "year"],
                        "description": "Time period for spending summary. Default is month.",
                    },
                    "category": {
                        "type": "string",
                        "description": "Optional specific category filter.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "skill_budget_alert_check",
            "description": "Check if any category has crossed 80% or 100% of its monthly budget limit.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_accounts",
            "description": "List the user's accounts and current balances.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_categories",
            "description": "List the user's income or expense categories and monthly budgets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "transaction_type": {"type": "string", "enum": ["expense", "income"]}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_transactions",
            "description": "Find prior ledger transactions by text, type, and ISO date range. Use this first to locate a record before editing it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "transaction_type": {
                        "type": "string",
                        "enum": ["expense", "income", "transfer"],
                    },
                    "start_date": {"type": "string", "description": "ISO date or datetime"},
                    "end_date": {"type": "string", "description": "ISO date or datetime"},
                    "limit": {"type": "integer", "description": "1 to 100, default 20"},
                    "offset": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_transaction",
            "description": "Correct a prior expense or income. Search first and use its exact transaction_id. Omit fields that should remain unchanged. Transfers cannot be edited.",
            "parameters": {
                "type": "object",
                "properties": {
                    "transaction_id": {"type": "string"},
                    "amount": {"type": "number"},
                    "transaction_type": {"type": "string", "enum": ["expense", "income"]},
                    "account_name": {"type": "string"},
                    "category": {"type": "string", "description": "Empty string clears category"},
                    "merchant": {"type": "string", "description": "Empty string clears merchant"},
                    "description": {
                        "type": "string",
                        "description": "Empty string clears description",
                    },
                    "transaction_date": {
                        "type": "string",
                        "description": "New ISO-8601 transaction date or datetime",
                    },
                },
                "required": ["transaction_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_category_budget",
            "description": "Set or clear a monthly expense budget for a category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "monthly_budget": {"type": ["number", "null"]},
                },
                "required": ["category", "monthly_budget"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "skill_recurring_bill_detector",
            "description": "Detect repeating monthly bills, subscriptions, or recurring charges from transaction history.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "skill_emergency_fund_calculator",
            "description": "Calculate emergency fund liquid runway (months) based on recent expense burn rate.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "financial_advice_bundle",
            "description": "Fetch holistic financial intelligence (recurring subscriptions, budget overages, emergency runway, and spending breakdown) to provide coaching and Reduce Money recommendations.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_user_api_key",
            "description": "Save and encrypt user's LLM API key for Gemini, OpenAI, Claude, or Groq.",
            "parameters": {
                "type": "object",
                "properties": {
                    "provider": {
                        "type": "string",
                        "enum": ["gemini", "openai", "claude", "groq"],
                        "description": "LLM provider name.",
                    },
                    "api_key": {
                        "type": "string",
                        "description": "The API key string.",
                    },
                },
                "required": ["provider", "api_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_financial_snapshot",
            "description": "Plain summary of the user's finances for a period: income, spending, top categories and merchants, budgets, recurring bills, month-end projection, money now. Call this before giving advice or answering 'how am I doing'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "How many recent days to cover (default 30, max 365).",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "savings_plan",
            "description": "Work out whether the user can save a target amount within some months, using their last 90 days of income and spending, and which discretionary categories to trim if not.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_amount": {"type": "number", "description": "Rupees to save in total."},
                    "months": {"type": "integer", "description": "Months available."},
                },
                "required": ["target_amount", "months"],
            },
        },
    },
]

SYSTEM_AGENT_PROMPT = """You are WalletLedger's Financial AI Agent Brain modeled on the 'Tank & Pipes' architecture.
Your job is to understand natural language user messages, analyze finances, and invoke appropriate tools dynamically.

Key Guidelines:
1. Account Pipes: Map colloquial payment accounts to clean pipe names (e.g. 'Bank', 'Cash', 'UPI Wallet'). If the user clearly specifies the payment medium (e.g. 'via bank', 'from cash', 'through UPI'), use that. If the payment account is NOT mentioned, do NOT assume or guess an account — instead, omit the `account_name` field from the `log_expense` call and do NOT call any tool; instead reply asking the user which account they paid from (e.g. "Which account did you pay from? Your accounts: Bank, Cash"). Use 'Bank' for income/transfers.
2. Categories: Infer accurate, standard expense or income categories based on context (e.g. Food, Groceries, Transport, Shopping, Utilities, Subscriptions, Health, Personal Care, Entertainment, Gifts, Salary, Freelance, Stipend, Cashback).
3. Multi-Item & Batch Transactions:
   When the user provides a list of expenses (e.g. '190=poornima pizza Dosa\\n80=Neeraj Dosa\\n115.62=petrol...'), multiple purchases, or an income together with expenses ('got stipend 15000 and spent 190 on dosa, 80 on coffee'), YOU MUST CALL THE RELEVANT TOOL FOR EACH INDIVIDUAL ITEM (call `log_income` for the stipend, and call `log_expense` for EVERY single expense item). Do not truncate, merge, or ignore any item.
4. Merchants & Descriptions: Identify merchant/payee names and clear descriptions for each transaction.
5. Queries & Reporting:
   - When the user asks 'how much total i spend', 'total expenses', 'show spending breakdown', call `get_spending_breakdown`.
   - When the user asks 'what is my balance', 'net worth', 'show pipes', call `get_pipe_balances`.
   - When the user asks how to save money, reduce expenses, or wants financial advice, call `financial_advice_bundle`.
   - When the user asks for budget checks or alerts, call `skill_budget_alert_check`.
   - When the user asks for recurring bills or subscriptions, call `skill_recurring_bill_detector`.
   - When the user asks for emergency fund or runway calculations, call `skill_emergency_fund_calculator`.
6. General Financial Conversations:
   If the user asks a general question, greetings, or conversational advice where no tools need to be executed, reply with a helpful, friendly, and structured financial response.
"""


# ---------------------------------------------------------------------------
# Pending Confirmation State
# ---------------------------------------------------------------------------


class PendingAction(TypedDict, total=False):
    tool_name: str
    tool_args: dict[str, Any]
    tool_calls: list[dict[str, Any]]  # everything from the same message, run together on Yes
    description: str
    created_at: str
    kind: str  # "transfer_confirm" | "account_selection"


@dataclass
class UserSession:
    chat_id: str
    pending_action: PendingAction | None = None
    last_active: datetime = field(default_factory=_utc_now)


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, UserSession] = {}

    def get_session(self, chat_id: str) -> UserSession:
        if chat_id not in self._sessions:
            self._sessions[chat_id] = UserSession(chat_id=chat_id)
        return self._sessions[chat_id]

    def set_pending(self, chat_id: str, action: PendingAction) -> None:
        session = self.get_session(chat_id)
        session.pending_action = action
        session.last_active = _utc_now()

    def get_pending(self, chat_id: str) -> PendingAction | None:
        """Return the pending action, discarding it if it is older than PENDING_ACTION_TTL."""
        session = self.get_session(chat_id)
        action = session.pending_action
        if action is None:
            return None
        try:
            created_raw = action.get("created_at", "")
            if created_raw.endswith("Z"):
                created = datetime.fromisoformat(created_raw[:-1] + "+00:00")
            elif "+" not in created_raw and "-" in created_raw:
                # Handle naive ISO format by assuming UTC
                created = datetime.fromisoformat(created_raw).replace(tzinfo=UTC)
            else:
                created = datetime.fromisoformat(created_raw)
        except Exception:
            created = session.last_active
        if _utc_now() - created > PENDING_ACTION_TTL:
            logger.info("Pending action for chat %s expired; discarding it.", chat_id)
            session.pending_action = None
            return None
        return action

    def clear_pending(self, chat_id: str) -> PendingAction | None:
        session = self.get_session(chat_id)
        action = session.pending_action
        session.pending_action = None
        session.last_active = _utc_now()
        return action


session_store = SessionStore()


# ---------------------------------------------------------------------------
# LangGraph Agent State
# ---------------------------------------------------------------------------


class AgentState(TypedDict, total=False):
    chat_id: str
    user_id: str
    user_message: str
    attachments: list[Any] | None
    messages: Sequence[BaseMessage]
    llm_thought: str | None
    is_confirmation_reply: bool
    confirmation_decision: Literal["confirmed", "cancelled", "none"]
    requires_confirmation: bool
    confirmation_action: PendingAction | None
    tool_name: str | None
    tool_args: dict[str, Any] | None
    tool_result: dict[str, Any] | None
    tool_calls: list[dict[str, Any]] | None
    tool_results: list[dict[str, Any]] | None
    response_text: str
    error: str | None
    persona_mode: str | None
    offline_reason: str | None


# ---------------------------------------------------------------------------
# LLM Reasoning & Dynamic Analysis
# ---------------------------------------------------------------------------


async def _run_llm_analysis(
    user_id: str, message: str, history: list[dict[str, str]]
) -> dict[str, Any]:
    """Calls the LLM via AI Gateway to parse intent, extract parameters, and select tools dynamically.

    Falls back to deterministic offline rules when no key is configured or the AI call fails.
    On failure the reason is logged and returned as ``offline_reason`` so the reply can say so.
    """
    keys = get_user_api_keys(user_id)
    offline_reason: str | None = None

    if keys:
        try:
            res = await ask_llm(
                user_id=user_id,
                system_prompt=SYSTEM_AGENT_PROMPT,
                user_prompt=message,
                tools=tool_client.available_tools(TOOLS_SCHEMA),
                messages_history=history,
            )
            choice = res.choices[0]
            message_obj = choice.message
            if hasattr(message_obj, "tool_calls") and message_obj.tool_calls:
                parsed_calls = []
                for call in message_obj.tool_calls:
                    fn_name = call.function.name
                    fn_args = json.loads(call.function.arguments or "{}")
                    parsed_calls.append({"tool_name": fn_name, "tool_args": fn_args})
                return {
                    "type": "tool_calls",
                    "tool_calls": parsed_calls,
                    "tool_name": parsed_calls[0]["tool_name"] if parsed_calls else None,
                    "tool_args": parsed_calls[0]["tool_args"] if parsed_calls else None,
                }
            elif getattr(message_obj, "content", None):
                return {"type": "direct_text", "content": message_obj.content}
            offline_reason = "the AI returned an empty response"
        except Exception as e:
            offline_reason = f"{type(e).__name__}: {str(e).splitlines()[0][:200] if str(e) else ''}"
        logger.warning(
            "AI unavailable for chat %s (%s); using offline rules.", user_id, offline_reason
        )

    # Dynamic fallback structured reasoning
    analysis = _offline_intent(message)
    if offline_reason:
        analysis["offline_reason"] = offline_reason
    return analysis


# What a user with no AI key can still ask for in words. Logging is NOT here: the rules in nlu.py read
# entries, and anything they can't read must not be guessed into an expense.
_OFFLINE_INTENTS: list[tuple[tuple[str, ...], str, dict[str, Any]]] = [
    (
        (
            "reduce money",
            "reduce expense",
            "how to save",
            "how can i save",
            "save money",
            "financial advice",
            "coach",
        ),
        "financial_advice_bundle",
        {},
    ),
    (("budget alert", "budget cap", "over budget", "check budget"), "skill_budget_alert_check", {}),
    (
        ("recurring", "subscriptions", "detect bills", "hidden bill"),
        "skill_recurring_bill_detector",
        {},
    ),
    (
        ("emergency fund", "runway", "liquid fund", "survival fund"),
        "skill_emergency_fund_calculator",
        {},
    ),
    (("balance", "net worth", "tank", "pipes"), "get_pipe_balances", {}),
    (
        (
            "how much did i spend",
            "how much spent",
            "how much i spend",
            "how much total",
            "total i spend",
            "total spent",
            "total spend",
            "spending breakdown",
            "spending summary",
            "expense breakdown",
            "show expenses",
            "my expenses",
        ),
        "get_spending_breakdown",
        {"period": "month"},
    ),
]


def _offline_intent(message: str) -> dict[str, Any]:
    """Without an AI key: a few fixed requests by keyword, otherwise a short, honest hint."""
    lower = message.strip().lower()
    if nlu.is_question(lower) and re.search(r"\d", lower):
        return {"type": "direct_text", "content": replies.QUESTION_NEEDS_AI}
    for keywords, tool, args in _OFFLINE_INTENTS:
        if any(k in lower for k in keywords):
            args = dict(args)
            if tool == "get_spending_breakdown":
                args["period"] = next(
                    (w for w in ("week", "quarter", "year") if w in lower), "month"
                )
            call = {"tool_name": tool, "tool_args": args}
            return {
                "type": "tool_calls",
                "tool_calls": [call],
                "tool_name": tool,
                "tool_args": args,
            }
    if lower in {"/help", "help", "/start", "menu", "commands"}:
        return {"type": "direct_text", "content": replies.GREETING}
    if re.search(
        r"\d", lower
    ):  # has a number but the rules could not read it: never guess an expense
        return {"type": "direct_text", "content": replies.NOT_UNDERSTOOD}
    return {"type": "direct_text", "content": replies.GREETING}


# ---------------------------------------------------------------------------
# LangGraph Nodes
# ---------------------------------------------------------------------------


def _nlu_context(chat_id: str) -> nlu.Context:
    """Names the user already uses (accounts, merchants) and where their money usually goes."""
    from sqlalchemy import select as _select

    from app.models import Account, Merchant, Transaction

    with SessionLocal() as db:
        user = db.get(User, str(chat_id)) or db.scalar(
            _select(User).where(User.telegram_chat_id == str(chat_id))
        )
        if user is None:
            return nlu.Context()
        accounts = {
            a.id: a.name for a in db.scalars(_select(Account).where(Account.user_id == user.id))
        }
        merchants = list(
            db.scalars(_select(Merchant.name).where(Merchant.user_id == user.id).limit(300))
        )

        def last_account(kind: str) -> str | None:
            account_id = db.scalar(
                _select(Transaction.account_id)
                .where(Transaction.user_id == user.id, Transaction.transaction_type == kind)
                .order_by(Transaction.created_at.desc())
                .limit(1)
            )
            return accounts.get(account_id) if account_id else None

        names = list(accounts.values())
        bank = next((n for n in names if "cash" not in n.lower()), "Bank")
        return nlu.Context(
            accounts=names,
            merchants=merchants,
            default_expense_account=last_account("expense")
            or ("Cash" if "Cash" in names else bank),
            default_income_account=last_account("income") or bank,
        )


def _account_selection_prompt(chat_id: str) -> str:
    """Build a message asking the user which account they paid from."""
    ctx = _nlu_context(chat_id)
    account_list = ", ".join(ctx.accounts) if ctx.accounts else "Bank, Cash"
    return (
        "💳 Which account did you pay from?\n"
        f"Your accounts: {account_list}\n\n"
        'Just reply with the account name (e.g., "Bank" or "Cash")'
    )


def _resolve_account_from_reply(message: str, chat_id: str) -> str | None:
    """Try to resolve the user's reply to a known account name. Returns None if unrecognised."""
    ctx = _nlu_context(chat_id)
    msg_lower = message.strip().lower()
    for name in ctx.accounts:
        if name.lower() in msg_lower or msg_lower in name.lower():
            return name
    # Also accept generic keywords even if not yet in the user's accounts
    generic_map = {
        "bank": "Bank",
        "cash": "Cash",
        "upi": "UPI Wallet",
        "wallet": "UPI Wallet",
        "card": "Credit Card",
        "credit": "Credit Card",
        "debit": "Bank",
    }
    for keyword, fallback in generic_map.items():
        if keyword in msg_lower:
            # prefer a matching real account name
            for name in ctx.accounts:
                if keyword in name.lower():
                    return name
            return fallback
    return None


def _inject_account_into_calls(
    tool_calls: list[dict[str, Any]], account: str
) -> list[dict[str, Any]]:
    """Return tool_calls with account_name filled in for every log_expense call missing one."""
    result = []
    for tc in tool_calls:
        if tc.get("tool_name") == "log_expense":
            args = dict(tc["tool_args"])
            if not args.get("account_name"):
                args["account_name"] = account
            result.append({"tool_name": tc["tool_name"], "tool_args": args})
        else:
            result.append(tc)
    return result


async def _nlu_analysis(chat_id: str, message: str) -> dict[str, Any] | None:
    """Clear messages ("Spent 200 on chai, 80 on auto") are handled by rules: instant, no AI call."""
    ctx = await asyncio.to_thread(_nlu_context, chat_id)
    entries = nlu.parse_entries(message, ctx)
    if not entries:
        return None

    # Check whether all expense entries are missing an explicit account.
    # If so, hold them as a pending account_selection rather than defaulting to Cash.
    # Exception: if the message also contains a transfer, the transfer-confirmation flow
    # takes priority — we don't interrupt with an account question.
    expense_entries = [e for e in entries if e.kind == "expense"]
    has_transfer = any(e.kind == "transfer" for e in entries)
    has_implicit_expenses = (
        expense_entries
        and all(not e.account_explicit for e in expense_entries)
        and not has_transfer  # transfers take priority; don't layer on account prompts
    )

    calls: list[dict[str, Any]] = []
    for e in entries:
        if e.kind == "transfer":
            args = {"from_account": e.account, "to_account": e.to_account, "amount": e.amount}
            calls.append({"tool_name": "transfer_funds", "tool_args": args})
        elif e.kind == "income":
            args = {
                "amount": e.amount,
                "source_account": e.account,
                "category": e.category or "Income",
                "description": e.note,
                "date": e.when,
            }
            calls.append(
                {
                    "tool_name": "log_income",
                    "tool_args": {k: v for k, v in args.items() if v is not None},
                }
            )
        else:
            # Build expense call; omit account_name so _inject_account_into_calls can fill it later
            args = {
                "amount": e.amount,
                "category": e.category or "Uncategorized",
                "merchant": e.merchant,
                "account_name": e.account if e.account_explicit else None,
                "description": e.note,
                "date": e.when,
            }
            calls.append(
                {
                    "tool_name": "log_expense",
                    "tool_args": {k: v for k, v in args.items() if v is not None},
                }
            )

    if has_implicit_expenses:
        # Suspend all expense calls; ask the user which account they paid from.
        # Non-expense calls (income, transfers) from the same message are included so they
        # are all executed together once the user answers.
        pending_action: PendingAction = {
            "tool_calls": calls,
            "tool_name": "log_expense",
            "description": "Expense account selection pending",
            "created_at": _utc_now().isoformat(),
            "kind": "account_selection",
        }
        session_store.set_pending(chat_id, pending_action)
        return {
            "type": "account_selection",
            "prompt": await asyncio.to_thread(_account_selection_prompt, chat_id),
        }

    return {"type": "tool_calls", "tool_calls": calls}


async def _orchestrate(
    chat_id: str, message: str, history: list[dict[str, str]]
) -> dict[str, Any] | None:
    """Multi-step answer for goals and questions. None -> use the simple one-shot path."""
    try:
        res = await orchestrator.run(
            chat_id,
            message,
            history,
            tools=tool_client.available_tools(TOOLS_SCHEMA),
            system_prompt=SYSTEM_AGENT_PROMPT,
            transfer_threshold=CONFIRMATION_TRANSFER_THRESHOLD,
        )
    except Exception as exc:
        logger.warning("Multi-step helper unavailable for chat %s: %s", chat_id, exc)
        return None

    if res.pending:
        args = res.pending["tool_args"]
        amount = float(args.get("amount", 0))
        action: PendingAction = {
            "tool_name": res.pending["tool_name"],
            "tool_args": args,
            "description": (
                f"Transfer ₹{amount:,.2f} from {args.get('from_account', 'Source')} "
                f"to {args.get('to_account', 'Destination')}"
            ),
            "created_at": _utc_now().isoformat(),
        }
        session_store.set_pending(chat_id, action)
        return {
            "requires_confirmation": True,
            "confirmation_action": action,
            "tool_name": action["tool_name"],
            "tool_args": args,
            "tool_calls": [{"tool_name": action["tool_name"], "tool_args": args}],
        }

    logged = replies.compact({"tool_results": [r for r in res.tool_results if r["result"]]})
    parts = [p for p in (logged, res.text) if p]
    if not parts:
        return None
    return {
        "response_text": "\n\n".join(parts),
        "tool_results": res.tool_results,
        "tool_name": None,
        "tool_args": None,
        "tool_calls": None,
        "requires_confirmation": False,
    }


async def llm_reasoning_node(state: AgentState) -> dict[str, Any]:
    """Node 1: LLM analyzes intent, resolves entities, and chooses tools dynamically."""
    chat_id = state.get("chat_id", "")
    user_message = state.get("user_message", "")

    # 1. Human-in-the-loop: a yes/no answer to a pending action never goes to the AI.
    pending = session_store.get_pending(chat_id)
    if pending:
        # 1a. Account selection reply — user is answering "which account did you pay from?"
        if pending.get("kind") == "account_selection":
            resolved = await asyncio.to_thread(_resolve_account_from_reply, user_message, chat_id)
            if resolved:
                # Inject the resolved account into every log_expense call that lacks one
                raw_pending_calls = pending.get("tool_calls") or []
                injected = _inject_account_into_calls(raw_pending_calls, resolved)
                # Stamp user_id on each call
                tool_calls_with_uid: list[dict[str, Any]] = []
                for tc in injected:
                    t_args = dict(tc.get("tool_args") or {})
                    t_args["user_id"] = chat_id
                    tool_calls_with_uid.append({"tool_name": tc["tool_name"], "tool_args": t_args})
                session_store.clear_pending(chat_id)
                first_name = tool_calls_with_uid[0]["tool_name"] if tool_calls_with_uid else None
                first_args = tool_calls_with_uid[0]["tool_args"] if tool_calls_with_uid else None
                return {
                    "tool_calls": tool_calls_with_uid,
                    "tool_name": first_name,
                    "tool_args": first_args,
                    "requires_confirmation": False,
                }
            # Unrecognised reply → re-prompt (keep pending alive)
            prompt = await asyncio.to_thread(_account_selection_prompt, chat_id)
            return {
                "response_text": f"❓ I didn't recognise that account. {prompt}",
                "tool_name": None,
                "tool_args": None,
                "tool_calls": None,
                "requires_confirmation": False,
            }

        # 1b. Transfer confirmation — yes/no reply
        decision = classify_reply(user_message)
        if decision:
            return {
                "is_confirmation_reply": True,
                "confirmation_decision": decision,
                "confirmation_action": pending,
            }
        # Unrelated message: drop the pending action and handle the new message normally.
        session_store.clear_pending(chat_id)
        logger.info("Chat %s sent a new request; cancelled pending action.", chat_id)

    # 2. API keys pasted in chat (Gemini AIza / AQ., OpenAI, Claude, Groq; several at once).
    if extract_api_keys(user_message):
        return {"response_text": await save_keys(chat_id, user_message)}

    # 3. Explicit persona command, e.g. "/budgeter" or "/summary how did I do?".
    command = PERSONA_COMMAND.match(user_message)
    if command:
        return {
            "tool_name": "financial_advice_bundle",
            "tool_args": {"user_id": chat_id},
            "tool_calls": [
                {"tool_name": "financial_advice_bundle", "tool_args": {"user_id": chat_id}}
            ],
            "requires_confirmation": False,
            "persona_mode": resolve_mode(command.group(1)).value,
        }

    # 4. AI reasoning. History = previous messages only.
    history = [
        {"role": "user" if isinstance(m, HumanMessage) else "assistant", "content": m.content}
        for m in state.get("messages", [])
    ]
    analysis = await _nlu_analysis(chat_id, user_message)
    if (
        analysis is None
        and orchestrator.looks_complex(user_message)
        and (get_user_api_keys(chat_id) or has_server_keys())
    ):
        multi = await _orchestrate(chat_id, user_message, history)
        if multi is not None:
            return multi
    if analysis is None:
        analysis = await _run_llm_analysis(chat_id, user_message, history)
    offline = (
        {"offline_reason": analysis["offline_reason"]} if analysis.get("offline_reason") else {}
    )

    # NLU set a pending account_selection and returned a prompt — surface it to the user.
    if analysis.get("type") == "account_selection":
        return {
            "response_text": analysis["prompt"],
            "tool_name": None,
            "tool_args": None,
            "tool_calls": None,
            "requires_confirmation": False,
        }

    if analysis.get("type") == "tool_calls" or analysis.get("tool_calls"):
        raw_calls = analysis.get("tool_calls") or []
        tool_calls: list[dict[str, Any]] = []
        for tc in raw_calls:
            t_name = tc.get("tool_name")
            t_args = dict(tc.get("tool_args") or {})
            t_args["user_id"] = chat_id
            tool_calls.append({"tool_name": t_name, "tool_args": t_args})

        # Check for transfer confirmations on any transfer >= threshold
        for tc in tool_calls:
            if (
                tc["tool_name"] == "transfer_funds"
                and float(tc["tool_args"].get("amount", 0)) >= CONFIRMATION_TRANSFER_THRESHOLD
            ):
                amount = float(tc["tool_args"].get("amount", 0.0))
                from_acc = tc["tool_args"].get("from_account", "Source")
                to_acc = tc["tool_args"].get("to_account", "Destination")
                others = len(tool_calls) - 1
                extra = (
                    f" (and {others} other entr{'y' if others == 1 else 'ies'} from your message)"
                    if others
                    else ""
                )
                pending_action: PendingAction = {
                    "tool_name": tc["tool_name"],
                    "tool_args": tc["tool_args"],
                    "tool_calls": tool_calls,
                    "description": f"Transfer ₹{amount:,.2f} from {from_acc} to {to_acc}{extra}",
                    "created_at": _utc_now().isoformat(),
                }
                session_store.set_pending(chat_id, pending_action)
                return {
                    "requires_confirmation": True,
                    "confirmation_action": pending_action,
                    "tool_name": tc["tool_name"],
                    "tool_args": tc["tool_args"],
                    "tool_calls": tool_calls,
                    **offline,
                }

        first_name = tool_calls[0]["tool_name"] if tool_calls else None
        first_args = tool_calls[0]["tool_args"] if tool_calls else None
        return {
            "tool_calls": tool_calls,
            "tool_name": first_name,
            "tool_args": first_args,
            "requires_confirmation": False,
            **offline,
        }

    text = analysis.get("content", "")
    if text == replies.GREETING and not get_user_api_keys(chat_id):
        text += "\n\n" + replies.NO_AI_HINT  # bring-your-own-key: tell them how, once
    return {
        "response_text": text,
        "tool_name": None,
        "tool_args": None,
        "tool_calls": None,
        "requires_confirmation": False,
        **offline,
    }


async def confirmation_node(state: AgentState) -> dict[str, Any]:
    """Node 2: Resolves confirmation or cancellation of a pending action."""
    chat_id = state.get("chat_id", "")
    decision = state.get("confirmation_decision", "none")
    pending = session_store.clear_pending(chat_id)

    if decision == "confirmed" and pending:
        return {
            "tool_name": pending["tool_name"],
            "tool_args": pending["tool_args"],
            "tool_calls": pending.get("tool_calls")
            or [{"tool_name": pending["tool_name"], "tool_args": pending["tool_args"]}],
            "requires_confirmation": False,
            "confirmation_decision": "confirmed",
        }
    else:
        return {
            "tool_name": None,
            "tool_args": None,
            "tool_calls": None,
            "requires_confirmation": False,
            "confirmation_decision": "cancelled",
            "response_text": replies.CANCELLED,
        }


async def tool_executor_node(state: AgentState) -> dict[str, Any]:
    """Node 3: Executes MCP tools dynamically."""
    if state.get("requires_confirmation"):
        action = state.get("confirmation_action", {})
        desc = action.get("description", "High-value ledger transaction")
        return {"response_text": replies.confirm_prompt(desc)}

    tool_calls = state.get("tool_calls")
    if not tool_calls and state.get("tool_name"):
        tool_calls = [
            {"tool_name": state.get("tool_name"), "tool_args": state.get("tool_args") or {}}
        ]

    if not tool_calls:
        return {"tool_result": None, "tool_results": None}

    results = []
    first_error = None
    for tc in tool_calls:
        t_name = tc.get("tool_name")
        t_args = dict(tc.get("tool_args") or {})
        if not t_name:
            continue
        try:
            res = await tool_client.call_tool(t_name, **t_args)
            results.append({"tool_name": t_name, "tool_args": t_args, "result": res, "error": None})
        except Exception as e:
            logger.error(f"Error executing MCP tool {t_name}: {e}", exc_info=True)
            results.append(
                {"tool_name": t_name, "tool_args": t_args, "result": None, "error": str(e)}
            )
            if not first_error:
                first_error = str(e)

    first_result = results[0]["result"] if results else None
    return {
        "tool_results": results,
        "tool_result": first_result,
        "error": first_error,
    }


OFFLINE_NOTE = "\n\n_(The AI is busy right now, so I used basic rules.)_"


async def response_synthesizer_node(state: AgentState) -> dict[str, Any]:
    """Node 4: Builds the reply.

    Advice/report tools are written by a persona (Coach / Budgeter / Summary) from the tool data;
    ledger confirmations stay as fast fixed templates. Adds an offline note if the AI failed.
    """
    text = (
        state.get("response_text")
        or await _persona_response(state)
        or replies.compact(state)
        or _multi_tool_or_template_response(state)
    )
    if state.get("offline_reason"):
        text += OFFLINE_NOTE
    return {"response_text": text}


async def _persona_response(state: AgentState) -> str | None:
    """Render advice-type tool results with a prompts.py persona; None -> use the template."""
    tool_name = state.get("tool_name")
    tool_result = state.get("tool_result")
    if tool_name not in PERSONA_TOOLS or not tool_result or state.get("error"):
        return None
    if state.get("offline_reason"):
        return None  # AI already failed this turn; don't spend another call.

    chat_id = state.get("chat_id", "")
    message = state.get("user_message", "")
    command = PERSONA_COMMAND.match(message)
    if command:
        mode = resolve_mode(command.group(1))
        message = command.group(2).strip() or "Review my finances using this data."
    else:
        mode = (
            resolve_mode(state.get("persona_mode"))
            if state.get("persona_mode")
            else detect_mode(message)
        )

    try:
        reply = await ask_persona(chat_id, message, mode=mode.value, context=tool_result)
    except NoAPIKeyError:
        return None
    except Exception as e:
        logger.warning(
            "Persona %s failed for chat %s (%s); using template reply.", mode.value, chat_id, e
        )
        return None
    if not reply or not str(reply).strip():
        return None
    return f"🧠 *{get_persona(mode).name}*\n\n{str(reply).strip()}"


def _multi_tool_or_template_response(state: AgentState) -> str:
    """Renders responses for single or batch multi-tool executions."""
    tool_results = state.get("tool_results")
    if tool_results and len(tool_results) > 1:
        return _batch_template_response(tool_results)
    return _template_response(state)


def _batch_template_response(tool_results: list[dict[str, Any]]) -> str:
    """Renders a comprehensive ledger update card for multiple transactions."""
    incomes = []
    expenses = []
    transfers = []
    other_msgs = []

    total_income = 0.0
    total_expense = 0.0

    for item in tool_results:
        t_name = item.get("tool_name")
        res = item.get("result") or {}
        err = item.get("error")

        if err:
            other_msgs.append(f"⚠️ Failed: {t_name} - {err}")
            continue

        if t_name == "log_income":
            amt = float(res.get("amount", 0.0))
            acc = res.get("account", "Bank")
            cat = res.get("category", "Income")
            total_income += amt
            incomes.append(f"  • **+₹{amt:,.2f}** → {acc} ({cat})")
        elif t_name == "log_expense":
            amt = float(res.get("amount", 0.0))
            acc = res.get("account", "Cash")
            cat = res.get("category", "General")
            merchant = res.get("merchant") or "General"
            desc = item.get("tool_args", {}).get("description") or merchant
            total_expense += amt
            expenses.append(f"  • **₹{amt:,.2f}** - {desc} *({cat})* via {acc}")
        elif t_name == "transfer_funds":
            amt = float(res.get("transferred", 0.0))
            from_acc = res.get("from_account", "Source")
            to_acc = res.get("to_account", "Destination")
            transfers.append(f"  • **₹{amt:,.2f}** from {from_acc} to {to_acc}")
        else:
            other_msgs.append(f"  • {t_name}: Completed")

    sections = ["🧾 **Ledger Transactions Recorded!**\n"]

    if incomes:
        sections.append(f"💰 **Income Logged ({len(incomes)}):**\n" + "\n".join(incomes))
    if expenses:
        sections.append(f"💸 **Expenses Logged ({len(expenses)}):**\n" + "\n".join(expenses))
    if transfers:
        sections.append(f"🔄 **Transfers Logged ({len(transfers)}):**\n" + "\n".join(transfers))
    if other_msgs:
        sections.append("\n".join(other_msgs))

    # Summary
    summary_lines = []
    if total_income > 0:
        summary_lines.append(f"• **Total Inflow:** ₹{total_income:,.2f}")
    if total_expense > 0:
        summary_lines.append(f"• **Total Outflow:** ₹{total_expense:,.2f}")
    if total_income > 0 and total_expense > 0:
        net = total_income - total_expense
        summary_lines.append(f"• **Net Balance Change:** {'+' if net >= 0 else ''}₹{net:,.2f}")

    if summary_lines:
        sections.append("📊 **Summary:**\n" + "\n".join(summary_lines))

    sections.append("✨ *Updated your Tank & Pipes ledger seamlessly.*")
    return "\n\n".join(sections)


def _template_response(state: AgentState) -> str:
    return _template_response_dict(state)["response_text"]


def _template_response_dict(state: AgentState) -> dict[str, Any]:
    """Fixed Markdown templates for every tool result (also the offline fallback for advice)."""
    tool_name = state.get("tool_name")
    tool_result = state.get("tool_result")
    error = state.get("error")

    if error:
        return {
            "response_text": f"⚠️ **Ledger Notice:** Unable to complete request.\n*Details:* {error}"
        }

    if not tool_name or not tool_result:
        return {"response_text": "✨ Action completed successfully."}

    # 1. Expense Log
    if tool_name == "log_expense":
        amt = tool_result.get("amount", 0.0)
        acc = tool_result.get("account", "Cash")
        cat = tool_result.get("category", "General")
        merchant = tool_result.get("merchant", "N/A")
        new_bal = tool_result.get("new_balance", 0.0)
        return {
            "response_text": (
                f"💸 **Expense Recorded!**\n\n"
                f"• **Amount:** ₹{amt:,.2f}\n"
                f"• **Category:** {cat}\n"
                f"• **Merchant:** {merchant}\n"
                f"• **Paid From:** {acc} (New Balance: ₹{new_bal:,.2f})\n\n"
                f"✨ *Updated your Tank & Pipes ledger seamlessly.*"
            )
        }

    # 2. Income Log
    if tool_name == "log_income":
        amt = tool_result.get("amount", 0.0)
        acc = tool_result.get("account", "Bank")
        cat = tool_result.get("category", "Income")
        new_bal = tool_result.get("new_balance", 0.0)
        return {
            "response_text": (
                f"💰 **Income Credited!**\n\n"
                f"• **Amount:** ₹{amt:,.2f}\n"
                f"• **Category:** {cat}\n"
                f"• **Deposited To:** {acc} (New Balance: ₹{new_bal:,.2f})\n\n"
                f"📈 *Net worth increased in your Tank.*"
            )
        }

    # 3. Transfer
    if tool_name == "transfer_funds":
        amt = tool_result.get("transferred", 0.0)
        from_acc = tool_result.get("from_account", "Source")
        to_acc = tool_result.get("to_account", "Destination")
        from_bal = tool_result.get("from_balance", 0.0)
        to_bal = tool_result.get("to_balance", 0.0)
        return {
            "response_text": (
                f"🔄 **Pipe-to-Pipe Transfer Successful!**\n\n"
                f"• **Transferred:** ₹{amt:,.2f}\n"
                f"• **From:** {from_acc} (Balance: ₹{from_bal:,.2f})\n"
                f"• **To:** {to_acc} (Balance: ₹{to_bal:,.2f})\n\n"
                f"ℹ️ *This transfer was balanced internally and was not counted as an expense.*"
            )
        }

    # 4. Pipe Balances
    if tool_name == "get_pipe_balances":
        total = tool_result.get("total_net_worth", 0.0)
        accounts = tool_result.get("accounts", [])
        acc_lines = (
            "\n".join(
                [f"  • **{a['name']}** ({a['type']}): ₹{a['balance']:,.2f}" for a in accounts]
            )
            or "  No active accounts found."
        )
        return {
            "response_text": (
                f"🏦 **Your WalletLedger Tank:**\n"
                f"💰 **Total Net Worth:** ₹{total:,.2f}\n\n"
                f"**Pipes In (Liquid Accounts):**\n{acc_lines}"
            )
        }

    # 5. Spending Breakdown
    if tool_name == "get_spending_breakdown":
        total = tool_result.get("total_expenses", 0.0)
        period = tool_result.get("period", "month")
        breakdown = tool_result.get("category_breakdown", {})
        if breakdown:
            lines = "\n".join([f"  • **{k}:** ₹{v:,.2f}" for k, v in breakdown.items()])
        else:
            lines = "  No recorded expenses for this period."
        return {
            "response_text": (
                f"📊 **Spending Breakdown ({period.title()}):**\n"
                f"💸 **Total Expenses:** ₹{total:,.2f}\n\n"
                f"**Categories:**\n{lines}"
            )
        }

    # 6. Budget Alert Skill
    if tool_name == "skill_budget_alert_check":
        month = tool_result.get("month", "")
        alerts = tool_result.get("alerts", [])
        if not alerts:
            return {
                "response_text": (
                    f"✅ **Budget Status ({month}):** All clear!\n"
                    f"None of your expense categories have crossed 80% of their monthly limit."
                )
            }
        lines = [
            f"{'🚨' if a.get('level') == 'exceeded' else '⚠️'} **{a['category']}**: ₹{a['spent']:,.2f} / ₹{a['budget']:,.2f} ({a['used_percent']}%)"
            for a in alerts
        ]
        return {
            "response_text": (
                f"⚠️ **Budget Alerts for {month}:**\n\n"
                + "\n".join(lines)
                + "\n\n💡 *Tip: Consider cutting discretionary spending in these categories.*"
            )
        }

    # 7. Recurring Bills Skill
    if tool_name == "skill_recurring_bill_detector":
        bills = tool_result.get("recurring_bills", [])
        if not bills:
            return {
                "response_text": (
                    "🔍 **Recurring Bills Detector:**\n"
                    "No repeating monthly subscriptions or bills detected in recent history."
                )
            }
        lines = [
            f"  • **{b['merchant']}**: ~₹{b['amount']:,.2f}/mo ({b['occurrences']} payments over {b['months']} months)"
            for b in bills
        ]
        return {
            "response_text": (
                "🔄 **Detected Recurring Bills & Subscriptions:**\n\n"
                + "\n".join(lines)
                + "\n\n💡 *Tip: Review these regularly to cancel unused memberships!*"
            )
        }

    # 8. Emergency Fund Skill
    if tool_name == "skill_emergency_fund_calculator":
        liquid = tool_result.get("liquid_balance", 0.0)
        burn = tool_result.get("average_monthly_expenses", 0.0)
        runway = tool_result.get("runway_months")
        target_3m = tool_result.get("target_3_month_fund", 0.0)
        shortfall = tool_result.get("shortfall_to_3_month_target", 0.0)
        runway_txt = f"{runway:.1f} months" if runway is not None else "N/A"
        health_icon = "🟢" if runway and runway >= 3 else "🟡" if runway and runway >= 1 else "🔴"
        return {
            "response_text": (
                f"🛡️ **Emergency Fund & Runway Analysis:**\n\n"
                f"• **Liquid Balances:** ₹{liquid:,.2f}\n"
                f"• **Monthly Burn Rate:** ₹{burn:,.2f}/mo\n"
                f"• {health_icon} **Estimated Runway:** **{runway_txt}**\n"
                f"• **Target (3 Months):** ₹{target_3m:,.2f}\n"
                f"• **Shortfall to Target:** ₹{shortfall:,.2f}\n\n"
                f"💡 *A solid emergency fund covers at least 3-6 months of essential burn.*"
            )
        }

    # 9. Financial Advice Bundle (Reduce Money Mode)
    if tool_name == "financial_advice_bundle":
        breakdown = tool_result.get("breakdown", {}).get("category_breakdown", {})
        recurring = tool_result.get("recurring", {}).get("recurring_bills", [])
        alerts = tool_result.get("budget", {}).get("alerts", [])
        emergency = tool_result.get("emergency", {})

        tips = []
        if alerts:
            tips.append(
                f"• **Cap Overages:** You are near/exceeding budget limits in {', '.join([a['category'] for a in alerts])}."
            )
        if recurring:
            tips.append(
                f"• **Audit Subscriptions:** You have {len(recurring)} recurring payments (e.g. {recurring[0]['merchant']}). Cancel any inactive ones."
            )
        if breakdown.get("Food", 0) > 3000:
            tips.append(
                f"• **Food & Dining:** ₹{breakdown.get('Food', 0):,.2f} spent. Cooking at home 2 days/week can save ~₹1,500/month."
            )
        if emergency.get("runway_months") and emergency.get("runway_months") < 3:
            tips.append(
                f"• **Boost Liquid Cushion:** Current runway is {emergency.get('runway_months'):.1f} months. Aim to reach 3.0 months."
            )
        if not tips:
            tips.append(
                "• **Maintain Tracking:** Keep logging every transaction to spot lifestyle creep early."
            )

        return {
            "response_text": (
                "🎯 **Fold-Style Financial Coach - Reduce Money Mode:**\n\n"
                "Here are actionable ways to optimize your finances:\n\n"
                + "\n".join(tips)
                + "\n\n💪 *Small daily optimizations compound into substantial wealth!*"
            )
        }

    # 10. Save API Key
    if tool_name == "save_user_api_key":
        provider = tool_result.get("provider", "LLM").title()
        return {
            "response_text": (
                f"🔑 **API Key Saved Successfully!**\n\n"
                f"• **Provider:** {provider}\n"
                f"• **Security:** Key stored encrypted in your private vault.\n"
                f"• **Rotation:** Round-robin key distribution enabled."
            )
        }

    return {"response_text": "✨ Done."}


# ---------------------------------------------------------------------------
# StateGraph Router Condition
# ---------------------------------------------------------------------------


def route_after_llm_reasoning(state: AgentState) -> str:
    """Routes to confirmation node, tool executor, or response synthesizer."""
    if state.get("is_confirmation_reply"):
        return "confirmation_node"
    if state.get("requires_confirmation") or state.get("tool_name") or state.get("tool_calls"):
        return "tool_executor_node"
    return "response_synthesizer_node"


def route_after_confirmation(state: AgentState) -> str:
    """After confirmation: execute tool if confirmed; else synthesize response."""
    if state.get("confirmation_decision") == "confirmed" and (
        state.get("tool_name") or state.get("tool_calls")
    ):
        return "tool_executor_node"
    return "response_synthesizer_node"


# ---------------------------------------------------------------------------
# StateGraph Workflow Construction
# ---------------------------------------------------------------------------


def build_agent_graph():
    """Builds and compiles the agent's StateGraph."""
    workflow = StateGraph(AgentState)

    # 1. Add Nodes
    workflow.add_node("llm_reasoning", llm_reasoning_node)
    workflow.add_node("confirmation_node", confirmation_node)
    workflow.add_node("tool_executor", tool_executor_node)
    workflow.add_node("response_synthesizer", response_synthesizer_node)

    # 2. Add Edges
    workflow.add_edge(START, "llm_reasoning")

    workflow.add_conditional_edges(
        "llm_reasoning",
        route_after_llm_reasoning,
        {
            "confirmation_node": "confirmation_node",
            "tool_executor_node": "tool_executor",
            "response_synthesizer_node": "response_synthesizer",
        },
    )

    workflow.add_conditional_edges(
        "confirmation_node",
        route_after_confirmation,
        {
            "tool_executor_node": "tool_executor",
            "response_synthesizer_node": "response_synthesizer",
        },
    )

    workflow.add_edge("tool_executor", "response_synthesizer")
    workflow.add_edge("response_synthesizer", END)

    return workflow.compile()


# Compiled LangGraph agent app
agent_app = build_agent_graph()


# ---------------------------------------------------------------------------
# Public Contract Interfaces
# ---------------------------------------------------------------------------


@dataclass
class Outcome:
    """What the agent did, for the UI: the reply plus facts used to add buttons."""

    text: str
    transaction_ids: list[str] = field(default_factory=list)
    needs_confirmation: bool = False


async def process_user_interaction(
    chat_id: str, text: str, attachments: list[Any] | None = None
) -> str:
    """Text-only entry point (kept for the dev endpoint and older callers)."""
    return (await process_user_interaction_ex(chat_id, text, attachments)).text


async def process_user_interaction_ex(
    chat_id: str, text: str, attachments: list[Any] | None = None
) -> Outcome:
    """
    Entry point for the Telegram bot.
    Loads the recent conversation history, runs the graph, and persists both messages.
    """
    clean_text = (text or "").strip()

    # Previous messages only (newest HISTORY_LIMIT); current message is the prompt.
    history = get_db_conversation_history(chat_id, limit=HISTORY_LIMIT)

    initial_state: AgentState = {
        "chat_id": str(chat_id),
        "user_id": str(chat_id),
        "user_message": clean_text,
        "attachments": attachments or [],
        "messages": list(history),
    }

    try:
        # Save user message to database (API keys masked, so they never reach chat history)
        save_db_chat_message(chat_id, "user", redact_api_keys(clean_text))

        # Run StateGraph
        final_state = await agent_app.ainvoke(initial_state)
        reply = final_state.get("response_text", "Done.")
        tx_ids = [
            str(r["result"]["transaction_id"])
            for r in (final_state.get("tool_results") or [])
            if isinstance(r.get("result"), dict) and r["result"].get("transaction_id")
        ]

        # Save assistant reply to database
        save_db_chat_message(chat_id, "assistant", reply)

        return Outcome(reply, tx_ids, bool(final_state.get("requires_confirmation")))
    except Exception as e:
        logger.error(f"Error executing LLM Agent StateGraph: {e}", exc_info=True)
        return Outcome("⚠️ Something went wrong on my side. Please try again in a moment.")
