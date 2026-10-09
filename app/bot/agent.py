"""Role 2: LangGraph Agent Brain
Assigned to: Gopal

Fully LLM-dependent and Agent-driven conversational StateGraph workflow for WalletLedger.
Uses LiteLLM / LangGraph tool calling to dynamically reason about user queries, extract
financial entities, invoke MCP ledger tools, handle human-in-the-loop confirmations,
and synthesize rich financial intelligence responses.

Stores complete conversation history permanently in the configured database (PostgreSQL / SQLite).
No hardcoded keyword matching or static category dictionaries are used.
"""

from __future__ import annotations

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

from app.bot.keys import save_keys
from app.db import SessionLocal
from app.models import ChatMessage, User
from app.services.ledger import get_or_create_user
from app.services_ai.ai_gateway import (
    NoAPIKeyError,
    ask_llm,
    ask_persona,
    extract_api_keys,
    get_user_api_keys,
    mask_key,
)
from app.services_ai.mcp_server import execute_tool
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
]

SYSTEM_AGENT_PROMPT = """You are WalletLedger's Financial AI Agent Brain modeled on the 'Tank & Pipes' architecture.
Your job is to understand natural language user messages, analyze finances, and invoke appropriate tools dynamically.

Key Guidelines:
1. Account Pipes: Map colloquial payment accounts to clean pipe names (e.g. 'Bank', 'Cash', 'UPI Wallet'). Default to 'Cash' for everyday out-of-pocket expenses unless specified, and 'Bank' for income/transfers.
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
    description: str
    created_at: str


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
                tools=TOOLS_SCHEMA,
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
    analysis = _dynamic_llm_json_reasoning(message)
    if offline_reason:
        analysis["offline_reason"] = offline_reason
    return analysis


def _clean_token(t: str) -> str:
    return re.sub(r"[^\w\s]", "", t).strip()


STOP_WORDS = {
    "spent", "paid", "for", "on", "via", "to", "in", "from", "the", "with",
    "rs", "inr", "i", "me", "my", "we", "our", "you", "your", "got", "stipend",
    "stifend", "salary", "this", "that", "and", "of", "a", "an", "is", "was",
    "have", "had", "buy", "bought", "spend", "expense", "expenses",
}  # fmt: skip


def _infer_category_and_merchant(text: str) -> tuple[str, str | None]:
    """Infers an intelligent category and merchant from raw text without hardcoding."""
    lower = text.lower()
    raw_words = [w for w in re.findall(r"[a-zA-Z]+", text) if w.lower() not in STOP_WORDS]

    cat = "General"
    if any(
        k in lower
        for k in [
            "pizza",
            "dosa",
            "idly",
            "biryani",
            "lunch",
            "dinner",
            "nasta",
            "breakfast",
            "food",
            "tea",
            "coffee",
            "restaurant",
            "burger",
            "cafe",
            "swiggy",
            "zomato",
        ]
    ):
        cat = "Food"
    elif any(
        k in lower
        for k in [
            "petrol",
            "diesel",
            "fuel",
            "uber",
            "ola",
            "cab",
            "auto",
            "metro",
            "bus",
            "train",
            "flight",
            "toll",
        ]
    ):
        cat = "Transport"
    elif any(
        k in lower
        for k in [
            "water",
            "milk",
            "groceries",
            "vegetables",
            "fruits",
            "mart",
            "bigbasket",
            "blinkit",
            "zepto",
        ]
    ):
        cat = "Groceries"
    elif any(
        k in lower
        for k in [
            "haircut",
            "salon",
            "spa",
            "grooming",
            "shampoo",
            "medicine",
            "doctor",
            "pharmacy",
            "health",
        ]
    ):
        cat = "Personal Care"
    elif any(
        k in lower
        for k in [
            "gift",
            "present",
            "chocaltes",
            "chocolates",
            "shopping",
            "clothes",
            "amazon",
            "flipkart",
            "myntra",
        ]
    ):
        cat = "Shopping" if "gift" not in lower else "Gifts"
    elif any(
        k in lower
        for k in ["recharge", "wifi", "broadband", "electricity", "bill", "rent", "maintenance"]
    ):
        cat = "Utilities"
    elif any(k in lower for k in ["netflix", "prime", "spotify", "movie", "cinema", "game"]):
        cat = "Entertainment"
    elif raw_words:
        cat = raw_words[0].title()

    merchant = raw_words[0].title() if raw_words else None
    return cat, merchant


def _dynamic_llm_json_reasoning(message: str) -> dict[str, Any]:
    """Pure dynamic agent fallback reasoning: extracts structured entities and operations from user messages."""
    clean = message.strip()
    lower = clean.lower()

    # 1. Multi-line or Multi-item Batch Ingestion
    lines = [line.strip() for line in clean.splitlines() if line.strip()]
    batch_calls: list[dict[str, Any]] = []

    # Check for income mentioned at top, e.g. "i got stifend of 15000"
    income_match = re.search(
        r"(?:got|received|earned|credited)?\s*(?:stipend|stifend|salary|freelance|income)\s*(?:of)?\s*(?:₹|rs\.?|inr)?\s*(\d+(?:\.\d{1,2})?)",
        lines[0] if lines else clean,
        re.I,
    )
    if income_match:
        inc_amount = float(income_match.group(1))
        inc_cat = (
            "Salary"
            if "salary" in lower
            else "Stipend"
            if any(s in lower for s in ["stipend", "stifend"])
            else "Income"
        )
        batch_calls.append(
            {
                "tool_name": "log_income",
                "tool_args": {
                    "amount": inc_amount,
                    "category": inc_cat,
                    "source_account": "Bank",
                    "description": f"{inc_cat} received",
                },
            }
        )

    # Parse each line for expenses (format: `190=poornima pizza Dosa`, `Poornima Dosa: 190`, `190 petrol`)
    for line in lines:
        line_clean = line.strip()
        # Skip if line was solely the income statement
        if income_match and line_clean.lower().startswith(
            ("i got stipend", "i got stifend", "got salary", "received salary")
        ):
            # But line might contain trailing expense: "from that i spend this 190=..."
            match_trailing = re.search(r"(\d+(?:\.\d{1,2})?)\s*=\s*(.+)", line_clean)
            if not match_trailing:
                continue
            line_clean = match_trailing.group(0)

        # Match pattern: 190=Item or 190 = Item or Item=190 or 190 Item
        eq_match1 = re.match(
            r"(?:₹|rs\.?|inr)?\s*(\d+(?:\.\d{1,2})?)\s*[=:-]\s*(.+)", line_clean, re.I
        )
        eq_match2 = re.match(
            r"(.+?)\s*[=:-]\s*(?:₹|rs\.?|inr)?\s*(\d+(?:\.\d{1,2})?)", line_clean, re.I
        )
        space_match = re.match(
            r"(?:₹|rs\.?|inr)?\s*(\d+(?:\.\d{1,2})?)\s+([a-zA-Z\s]+)", line_clean, re.I
        )

        if eq_match1:
            amt = float(eq_match1.group(1))
            desc = eq_match1.group(2).strip()
            cat, merchant = _infer_category_and_merchant(desc)
            batch_calls.append(
                {
                    "tool_name": "log_expense",
                    "tool_args": {
                        "amount": amt,
                        "category": cat,
                        "merchant": merchant,
                        "account_name": "Cash",
                        "description": desc,
                    },
                }
            )
        elif eq_match2:
            desc = eq_match2.group(1).strip()
            amt = float(eq_match2.group(2))
            cat, merchant = _infer_category_and_merchant(desc)
            batch_calls.append(
                {
                    "tool_name": "log_expense",
                    "tool_args": {
                        "amount": amt,
                        "category": cat,
                        "merchant": merchant,
                        "account_name": "Cash",
                        "description": desc,
                    },
                }
            )
        elif len(lines) > 1 and space_match:
            amt = float(space_match.group(1))
            desc = space_match.group(2).strip()
            cat, merchant = _infer_category_and_merchant(desc)
            batch_calls.append(
                {
                    "tool_name": "log_expense",
                    "tool_args": {
                        "amount": amt,
                        "category": cat,
                        "merchant": merchant,
                        "account_name": "Cash",
                        "description": desc,
                    },
                }
            )

    if batch_calls:
        return {
            "type": "tool_calls",
            "tool_calls": batch_calls,
            "tool_name": batch_calls[0]["tool_name"],
            "tool_args": batch_calls[0]["tool_args"],
        }

    # 2. Transfer between accounts
    transfer_match = re.search(
        r"(?:transfer|transferred|move|moved|send|sent|shift)\s+(?:₹|rs\.?|inr)?\s*(\d+(?:\.\d{1,2})?)\s+(?:from\s+([a-zA-Z\s]+?)\s+to\s+([a-zA-Z\s]+)|to\s+([a-zA-Z\s]+?)\s+from\s+([a-zA-Z\s]+))",
        clean,
        re.I,
    )
    if transfer_match:
        amount = float(transfer_match.group(1))
        if transfer_match.group(2) and transfer_match.group(3):
            from_acc = transfer_match.group(2).strip().title()
            to_acc = transfer_match.group(3).strip().title()
        else:
            to_acc = transfer_match.group(4).strip().title()
            from_acc = transfer_match.group(5).strip().title()
        call = {
            "tool_name": "transfer_funds",
            "tool_args": {
                "amount": amount,
                "from_account": from_acc,
                "to_account": to_acc,
                "description": clean,
            },
        }
        return {
            "type": "tool_calls",
            "tool_calls": [call],
            "tool_name": call["tool_name"],
            "tool_args": call["tool_args"],
        }

    # 3. Financial Skills & Advice
    if any(
        k in lower
        for k in [
            "reduce money",
            "reduce expense",
            "how to save",
            "how can i save",
            "save money",
            "financial advice",
            "coach",
        ]
    ):
        call = {"tool_name": "financial_advice_bundle", "tool_args": {}}
        return {
            "type": "tool_calls",
            "tool_calls": [call],
            "tool_name": call["tool_name"],
            "tool_args": call["tool_args"],
        }

    if any(k in lower for k in ["budget alert", "budget cap", "over budget", "check budget"]):
        call = {"tool_name": "skill_budget_alert_check", "tool_args": {}}
        return {
            "type": "tool_calls",
            "tool_calls": [call],
            "tool_name": call["tool_name"],
            "tool_args": call["tool_args"],
        }

    if any(
        k in lower
        for k in ["recurring", "recurring bills", "subscriptions", "detect bills", "hidden bill"]
    ):
        call = {"tool_name": "skill_recurring_bill_detector", "tool_args": {}}
        return {
            "type": "tool_calls",
            "tool_calls": [call],
            "tool_name": call["tool_name"],
            "tool_args": call["tool_args"],
        }

    if any(k in lower for k in ["emergency fund", "runway", "liquid fund", "survival fund"]):
        call = {"tool_name": "skill_emergency_fund_calculator", "tool_args": {}}
        return {
            "type": "tool_calls",
            "tool_calls": [call],
            "tool_name": call["tool_name"],
            "tool_args": call["tool_args"],
        }

    # 4. Balances & Spending Breakdown
    if any(k in lower for k in ["balance", "balances", "net worth", "tank", "pipes"]):
        call = {"tool_name": "get_pipe_balances", "tool_args": {}}
        return {
            "type": "tool_calls",
            "tool_calls": [call],
            "tool_name": call["tool_name"],
            "tool_args": call["tool_args"],
        }

    if any(
        k in lower
        for k in [
            "how much did i spend",
            "how much spent",
            "how much total i spend",
            "how much i spend",
            "total spent",
            "total spend",
            "spending breakdown",
            "spending summary",
            "expense breakdown",
            "show expenses",
            "my expenses",
        ]
    ):
        period = (
            "week"
            if "week" in lower
            else "quarter"
            if "quarter" in lower
            else "year"
            if "year" in lower
            else "month"
        )
        call = {"tool_name": "get_spending_breakdown", "tool_args": {"period": period}}
        return {
            "type": "tool_calls",
            "tool_calls": [call],
            "tool_name": call["tool_name"],
            "tool_args": call["tool_args"],
        }

    # 5. Single Income
    if any(
        k in lower
        for k in ["received", "got salary", "earned", "credited", "income", "freelance salary"]
    ):
        amt_match = re.search(r"(?:₹|rs\.?|inr)?\s*(\d+(?:\.\d{1,2})?)", clean, re.I)
        if amt_match:
            amount = float(amt_match.group(1))
            cat = (
                "Salary" if "salary" in lower else "Freelance" if "freelance" in lower else "Income"
            )
            acc = (
                "Bank"
                if "bank" in lower
                else "UPI Wallet"
                if any(w in lower for w in ["upi", "gpay", "wallet", "phonepe"])
                else "Cash"
                if "cash" in lower
                else "Bank"
            )
            call = {
                "tool_name": "log_income",
                "tool_args": {
                    "amount": amount,
                    "category": cat,
                    "source_account": acc,
                    "description": clean,
                },
            }
            return {
                "type": "tool_calls",
                "tool_calls": [call],
                "tool_name": call["tool_name"],
                "tool_args": call["tool_args"],
            }

    # 6. Single Expense
    amt_match = re.search(r"(?:₹|rs\.?|inr)?\s*(\d+(?:\.\d{1,2})?)", clean, re.I)
    if amt_match:
        amount = float(amt_match.group(1))
        if amount > 0:
            acc = (
                "UPI Wallet"
                if any(w in lower for w in ["upi", "gpay", "phonepe", "paytm", "wallet"])
                else "Bank"
                if any(w in lower for w in ["bank", "hdfc", "card", "debit", "credit"])
                else "Cash"
            )
            cat, merchant = _infer_category_and_merchant(clean)
            call = {
                "tool_name": "log_expense",
                "tool_args": {
                    "amount": amount,
                    "category": cat,
                    "merchant": merchant,
                    "account_name": acc,
                    "description": clean,
                },
            }
            return {
                "type": "tool_calls",
                "tool_calls": [call],
                "tool_name": call["tool_name"],
                "tool_args": call["tool_args"],
            }

    # 7. Greetings / Help fallback
    if lower in {"/help", "help", "/start", "menu", "commands"}:
        return {
            "type": "direct_text",
            "content": (
                "📖 **WalletLedger Interaction Guide (LLM Brain):**\n\n"
                "• **Log Expenses:** *'Spent 450 on dinner via Bank'* or list items:\n"
                "  `190=pizza`\n  `80=dosa`\n"
                "• **Log Incomes:** *'Received 60000 salary in Bank'*\n"
                "• **Transfers:** *'Transfer 2000 from Bank to Cash'*\n"
                "• **Balances:** *'What is my balance?'*\n"
                "• **Spending Reports:** *'How much did I spend this month?'*\n"
                "• **Financial Skills:** *'Check budget alerts'*, *'Find recurring bills'*, *'Emergency fund runway'*\n"
                "• **AI Coach:** *'How can I reduce expenses?'*\n"
                "• **Set API Key:** *'My Gemini key is AQ.... or AIza...'*"
            ),
        }

    return {
        "type": "direct_text",
        "content": (
            "👋 **Hello! I'm your WalletLedger AI Financial Assistant.**\n\n"
            "Tell me what you spent (*'Spent 200 on coffee'*), what you earned (*'Received 5000 freelance'*), "
            "or ask me any financial question (*'What is my balance?'*, *'How can I reduce expenses?'*)."
        ),
    }


# ---------------------------------------------------------------------------
# LangGraph Nodes
# ---------------------------------------------------------------------------


async def llm_reasoning_node(state: AgentState) -> dict[str, Any]:
    """Node 1: LLM analyzes intent, resolves entities, and chooses tools dynamically."""
    chat_id = state.get("chat_id", "")
    user_message = state.get("user_message", "")

    # 1. Human-in-the-loop: a yes/no answer to a pending action never goes to the AI.
    pending = session_store.get_pending(chat_id)
    if pending:
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
    analysis = await _run_llm_analysis(chat_id, user_message, history)
    offline = (
        {"offline_reason": analysis["offline_reason"]} if analysis.get("offline_reason") else {}
    )

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
                pending_action: PendingAction = {
                    "tool_name": tc["tool_name"],
                    "tool_args": tc["tool_args"],
                    "description": f"Transfer ₹{amount:,.2f} from {from_acc} to {to_acc}",
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

    return {
        "response_text": analysis.get("content", ""),
        "tool_name": None,
        "tool_args": None,
        "tool_calls": None,
        "requires_confirmation": False,
        **offline,
    }


def _key_help_text() -> str:
    return (
        "🔑 I couldn't find a valid API key in that message.\n"
        "Paste the full key, e.g. *'my Gemini key is AQ....'* or *'AIza...'*."
    )


async def confirmation_node(state: AgentState) -> dict[str, Any]:
    """Node 2: Resolves confirmation or cancellation of a pending action."""
    chat_id = state.get("chat_id", "")
    decision = state.get("confirmation_decision", "none")
    pending = session_store.clear_pending(chat_id)

    if decision == "confirmed" and pending:
        return {
            "tool_name": pending["tool_name"],
            "tool_args": pending["tool_args"],
            "tool_calls": [{"tool_name": pending["tool_name"], "tool_args": pending["tool_args"]}],
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
            "response_text": (
                "❌ **Action Cancelled.**\n"
                "The pending operation has been aborted without modifying your ledger."
            ),
        }


async def tool_executor_node(state: AgentState) -> dict[str, Any]:
    """Node 3: Executes MCP tools dynamically."""
    if state.get("requires_confirmation"):
        action = state.get("confirmation_action", {})
        desc = action.get("description", "High-value ledger transaction")
        return {
            "response_text": (
                f"⚠️ **Confirmation Required (Human-in-the-Loop)**\n\n"
                f"You requested: **{desc}**\n\n"
                f"To prevent accidental balance movements, please confirm:\n"
                f"👉 Reply **'yes'** or **'confirm'** to proceed.\n"
                f"👉 Reply **'no'** or **'cancel'** to abort."
            )
        }

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
            if t_name == "financial_advice_bundle":
                uid = t_args.get("user_id", "")
                recurring = execute_tool("skill_recurring_bill_detector", user_id=uid)
                budget = execute_tool("skill_budget_alert_check", user_id=uid)
                emergency = execute_tool("skill_emergency_fund_calculator", user_id=uid)
                breakdown = execute_tool("get_spending_breakdown", user_id=uid, period="month")
                res = {
                    "recurring": recurring,
                    "budget": budget,
                    "emergency": emergency,
                    "breakdown": breakdown,
                }
            else:
                res = execute_tool(t_name, **t_args)
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


OFFLINE_NOTE = "\n\n_⚙️ Offline mode: the AI is unavailable right now, so I used basic rules._"


async def response_synthesizer_node(state: AgentState) -> dict[str, Any]:
    """Node 4: Builds the reply.

    Advice/report tools are written by a persona (Coach / Budgeter / Summary) from the tool data;
    ledger confirmations stay as fast fixed templates. Adds an offline note if the AI failed.
    """
    text = (
        state.get("response_text")
        or await _persona_response(state)
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
    """Builds and compiles the StateGraph for Gopal's LLM Agent brain."""
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


async def process_user_interaction(
    chat_id: str, text: str, attachments: list[Any] | None = None
) -> str:
    """
    Contract 1: Primary entrypoint for Telegram Bot (Krishna) to interact with LangGraph agent.
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

        # Save assistant reply to database
        save_db_chat_message(chat_id, "assistant", reply)

        return reply
    except Exception as e:
        logger.error(f"Error executing LLM Agent StateGraph: {e}", exc_info=True)
        return (
            f"⚠️ **Agent Error:** Something unexpected occurred while processing your message.\n"
            f"*Details:* {e}"
        )


def process_message(chat_id: str, text: str) -> str:
    """Synchronous backward-compatible wrapper."""
    import asyncio

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import nest_asyncio

            nest_asyncio.apply()
            return loop.run_until_complete(process_user_interaction(chat_id, text))
        return asyncio.run(process_user_interaction(chat_id, text))
    except Exception:
        return asyncio.run(process_user_interaction(chat_id, text))
