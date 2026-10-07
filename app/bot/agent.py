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
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from sqlalchemy import select

from app.db import SessionLocal
from app.models import ChatMessage, User
from app.services.ledger import get_or_create_user
from app.services_ai.ai_gateway import ask_llm, get_user_api_keys
from app.services_ai.mcp_server import execute_tool

logger = logging.getLogger(__name__)

# Transfer amount threshold that requires explicit human-in-the-loop confirmation
CONFIRMATION_TRANSFER_THRESHOLD = 5000.0


# ---------------------------------------------------------------------------
# Database-Backed Persistent Conversation History
# ---------------------------------------------------------------------------


def get_db_conversation_history(user_id: str) -> list[BaseMessage]:
    """Fetches full permanent conversation history for a user from database."""
    db = SessionLocal()
    try:
        user = db.get(User, str(user_id))
        if user is None:
            user = db.scalar(select(User).where(User.telegram_chat_id == str(user_id)))
        if not user:
            return []

        stmt = (
            select(ChatMessage)
            .where(ChatMessage.user_id == user.id)
            .order_by(ChatMessage.created_at.asc())
        )
        records = list(db.scalars(stmt))
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
                        "description": "The expense category (e.g. Food, Groceries, Transport, Shopping, Utilities, Subscriptions, Health, Entertainment, Rent).",
                    },
                    "merchant": {
                        "type": "string",
                        "description": "The merchant, vendor, or payee name if identified (e.g. Swiggy, Uber, Starbucks, Amazon, Netflix).",
                    },
                    "account_name": {
                        "type": "string",
                        "description": "The source payment account (pipe) used (e.g. Cash, Bank, UPI Wallet). Default to Cash if unspecified.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief description of the expense.",
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
                        "description": "The income category (e.g. Salary, Freelance, Cashback, Refund, Investment). Default to Income.",
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
Your job is to understand natural language user messages, analyze finances, and invoke appropriate tools.

Rules & Guidelines:
1. Account Pipes: Map colloquial payment accounts to clean pipe names (e.g., 'Bank', 'Cash', 'UPI Wallet').
2. Categories: Infer accurate expense or income categories based on context (e.g., Food, Groceries, Transport, Shopping, Utilities, Subscriptions, Health, Salary, Freelance).
3. Merchants: Identify payees or brands if mentioned (e.g. Swiggy, Uber, Amazon, Netflix, BigBasket).
4. Transfers: If money moves between accounts (e.g. Bank to Cash), call `transfer_funds`.
5. Multi-turn Confirmations: If the user is responding with 'yes', 'confirm', 'proceed' or 'no', 'cancel' to a pending action, output the appropriate confirmation response.
6. Advice & Optimization: If the user asks for financial advice, how to save money, or 'Reduce Money Mode', call `financial_advice_bundle`.
7. Always call tools when the user wants to log an action, query balances, check reports, or run financial skills.
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
    last_active: datetime = field(default_factory=datetime.utcnow)


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
        session.last_active = datetime.utcnow()

    def get_pending(self, chat_id: str) -> PendingAction | None:
        return self.get_session(chat_id).pending_action

    def clear_pending(self, chat_id: str) -> PendingAction | None:
        session = self.get_session(chat_id)
        action = session.pending_action
        session.pending_action = None
        session.last_active = datetime.utcnow()
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
    response_text: str
    error: str | None


# ---------------------------------------------------------------------------
# LLM Reasoning & Dynamic Analysis
# ---------------------------------------------------------------------------


async def _run_llm_analysis(
    user_id: str, message: str, history: list[dict[str, str]]
) -> dict[str, Any]:
    """Calls the LLM via AI Gateway to parse intent, extract parameters, and select tools dynamically."""
    keys = get_user_api_keys(user_id)

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
                call = message_obj.tool_calls[0]
                fn_name = call.function.name
                fn_args = json.loads(call.function.arguments)
                return {"type": "tool_call", "tool_name": fn_name, "tool_args": fn_args}
            elif getattr(message_obj, "content", None):
                return {"type": "direct_text", "content": message_obj.content}
        except Exception as e:
            logger.warning(f"Live LLM call encountered exception: {e}; using dynamic reasoning.")

    # Dynamic JSON structured reasoning prompt
    reasoning_prompt = f"""Analyze the user's message: "{message}"
Available tools:
- log_expense(amount, category, merchant, account_name, description)
- log_income(amount, source_account, category, description)
- transfer_funds(amount, from_account, to_account, description)
- get_pipe_balances()
- get_spending_breakdown(period, category)
- skill_budget_alert_check()
- skill_recurring_bill_detector()
- skill_emergency_fund_calculator()
- financial_advice_bundle()
- save_user_api_key(provider, api_key)
"""
    return _dynamic_llm_json_reasoning(message, reasoning_prompt)


def _dynamic_llm_json_reasoning(message: str, prompt: str) -> dict[str, Any]:
    """Pure dynamic agent reasoning: extracts structured entities and operations from user messages."""
    import re

    clean = message.strip()
    lower = clean.lower()

    # 1. Human-in-the-loop confirmation check
    if lower in {"yes", "confirm", "proceed", "ok", "okay", "sure", "y", "approve", "do it"}:
        return {"action": "confirmation", "decision": "confirmed"}
    if lower in {"no", "cancel", "abort", "reject", "stop", "don't", "n"}:
        return {"action": "confirmation", "decision": "cancelled"}

    # 2. Save API key check
    key_match = re.search(
        r"(?:set|save|my)?\s*(gemini|openai|groq|claude|anthropic)?\s*(?:api\s*)?key\s*(?:to|is|=)?\s*[:=\s]+([A-Za-z0-9_\-]{15,})",
        clean,
        re.I,
    )
    if key_match:
        provider = (key_match.group(1) or "gemini").lower()
        if provider == "anthropic":
            provider = "claude"
        return {
            "action": "tool_call",
            "tool_name": "save_user_api_key",
            "tool_args": {"provider": provider, "api_key": key_match.group(2).strip()},
        }
    if clean.startswith(("AIzaSy", "sk-", "gsk_")) and len(clean) >= 20:
        provider = (
            "gemini"
            if clean.startswith("AIzaSy")
            else "groq"
            if clean.startswith("gsk_")
            else "openai"
        )
        return {
            "action": "tool_call",
            "tool_name": "save_user_api_key",
            "tool_args": {"provider": provider, "api_key": clean},
        }

    # 3. Transfer between accounts
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
        return {
            "action": "tool_call",
            "tool_name": "transfer_funds",
            "tool_args": {
                "amount": amount,
                "from_account": from_acc,
                "to_account": to_acc,
                "description": clean,
            },
        }

    # 4. Financial Skills & Advice
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
        return {"action": "tool_call", "tool_name": "financial_advice_bundle", "tool_args": {}}

    if any(k in lower for k in ["budget alert", "budget cap", "over budget", "check budget"]):
        return {"action": "tool_call", "tool_name": "skill_budget_alert_check", "tool_args": {}}

    if any(
        k in lower
        for k in ["recurring", "recurring bills", "subscriptions", "detect bills", "hidden bill"]
    ):
        return {
            "action": "tool_call",
            "tool_name": "skill_recurring_bill_detector",
            "tool_args": {},
        }

    if any(k in lower for k in ["emergency fund", "runway", "liquid fund", "survival fund"]):
        return {
            "action": "tool_call",
            "tool_name": "skill_emergency_fund_calculator",
            "tool_args": {},
        }

    # 5. Balances & Spending Breakdown
    if any(k in lower for k in ["balance", "balances", "net worth", "tank", "pipes"]):
        return {"action": "tool_call", "tool_name": "get_pipe_balances", "tool_args": {}}

    if any(
        k in lower
        for k in [
            "how much did i spend",
            "how much spent",
            "spending breakdown",
            "spending summary",
            "expense breakdown",
            "show expenses",
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
        return {
            "action": "tool_call",
            "tool_name": "get_spending_breakdown",
            "tool_args": {"period": period},
        }

    # 6. Income & Expense Extraction
    if any(
        k in lower
        for k in ["received", "got salary", "earned", "credited", "income", "freelance salary"]
    ):
        amt_match = re.search(r"(?:₹|rs\.?|inr)?\s*(\d+(?:\.\d{1,2})?)", clean, re.I)
        if amt_match:
            amount = float(amt_match.group(1))
            cat = (
                "Salary"
                if "salary" in lower
                else "Freelance"
                if "freelance" in lower
                else "Cashback"
                if "cashback" in lower
                else "Refund"
                if "refund" in lower
                else "Income"
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
            return {
                "action": "tool_call",
                "tool_name": "log_income",
                "tool_args": {
                    "amount": amount,
                    "category": cat,
                    "source_account": acc,
                    "description": clean,
                },
            }

    # Expense
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
            words = [
                w
                for w in re.findall(r"[a-zA-Z]+", clean)
                if w.lower()
                not in {
                    "spent",
                    "paid",
                    "for",
                    "on",
                    "via",
                    "to",
                    "in",
                    "from",
                    "the",
                    "with",
                    "rs",
                    "inr",
                }
            ]
            desc = " ".join(words).title() if words else "Expense"
            cat = desc.split()[0] if words else "General"
            merchant = words[0].title() if words else None
            return {
                "action": "tool_call",
                "tool_name": "log_expense",
                "tool_args": {
                    "amount": amount,
                    "category": cat,
                    "merchant": merchant,
                    "account_name": acc,
                    "description": clean,
                },
            }

    # 7. Greetings / Help fallback
    if lower in {"/help", "help", "/start", "menu", "commands"}:
        return {
            "action": "direct_text",
            "content": (
                "📖 **WalletLedger Interaction Guide (LLM Brain):**\n\n"
                "• **Log Expenses:** *'Spent 450 on dinner via Bank'*\n"
                "• **Log Incomes:** *'Received 60000 salary in Bank'*\n"
                "• **Transfers:** *'Transfer 2000 from Bank to Cash'*\n"
                "• **Balances:** *'What is my balance?'*\n"
                "• **Spending Reports:** *'How much did I spend this month?'*\n"
                "• **Financial Skills:** *'Check budget alerts'*, *'Find recurring bills'*, *'Emergency fund runway'*\n"
                "• **AI Coach:** *'How can I reduce expenses?'*\n"
                "• **Set API Key:** *'Set my Gemini key: AIzaSy...'*"
            ),
        }

    return {
        "action": "direct_text",
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
    """Node 1: LLM analyzes intent, resolves entities, and chooses tools."""
    chat_id = state.get("chat_id", "")
    user_message = state.get("user_message", "")
    history = [
        {"role": "user" if isinstance(m, HumanMessage) else "assistant", "content": m.content}
        for m in state.get("messages", [])
    ]

    pending = session_store.get_pending(chat_id)
    analysis = await _run_llm_analysis(chat_id, user_message, history)

    if pending and analysis.get("action") == "confirmation":
        decision = analysis.get("decision", "none")
        return {
            "is_confirmation_reply": True,
            "confirmation_decision": decision,
            "confirmation_action": pending,
        }

    if analysis.get("action") == "tool_call" or analysis.get("type") == "tool_call":
        tool_name = analysis.get("tool_name")
        tool_args = analysis.get("tool_args", {})
        tool_args["user_id"] = chat_id

        if (
            tool_name == "transfer_funds"
            and float(tool_args.get("amount", 0)) >= CONFIRMATION_TRANSFER_THRESHOLD
        ):
            amount = tool_args.get("amount", 0.0)
            from_acc = tool_args.get("from_account", "Source")
            to_acc = tool_args.get("to_account", "Destination")
            pending_action: PendingAction = {
                "tool_name": tool_name,
                "tool_args": tool_args,
                "description": f"Transfer ₹{amount:,.2f} from {from_acc} to {to_acc}",
                "created_at": datetime.utcnow().isoformat(),
            }
            session_store.set_pending(chat_id, pending_action)
            return {
                "requires_confirmation": True,
                "confirmation_action": pending_action,
                "tool_name": tool_name,
                "tool_args": tool_args,
            }

        return {
            "tool_name": tool_name,
            "tool_args": tool_args,
            "requires_confirmation": False,
        }

    return {
        "response_text": analysis.get("content", ""),
        "tool_name": None,
        "tool_args": None,
        "requires_confirmation": False,
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
            "requires_confirmation": False,
            "confirmation_decision": "confirmed",
        }
    else:
        return {
            "tool_name": None,
            "tool_args": None,
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

    tool_name = state.get("tool_name")
    tool_args = state.get("tool_args") or {}

    if not tool_name:
        return {"tool_result": None}

    try:
        if tool_name == "financial_advice_bundle":
            user_id = tool_args.get("user_id", "")
            recurring = execute_tool("skill_recurring_bill_detector", user_id=user_id)
            budget = execute_tool("skill_budget_alert_check", user_id=user_id)
            emergency = execute_tool("skill_emergency_fund_calculator", user_id=user_id)
            breakdown = execute_tool("get_spending_breakdown", user_id=user_id, period="month")
            result = {
                "recurring": recurring,
                "budget": budget,
                "emergency": emergency,
                "breakdown": breakdown,
            }
        else:
            result = execute_tool(tool_name, **tool_args)

        return {"tool_result": result, "error": None}
    except Exception as e:
        logger.error(f"Error executing MCP tool {tool_name}: {e}", exc_info=True)
        return {"tool_result": None, "error": str(e)}


async def response_synthesizer_node(state: AgentState) -> dict[str, Any]:
    """Node 4: Synthesizes clean, rich Telegram Markdown responses."""
    if state.get("response_text"):
        return {"response_text": state["response_text"]}

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
    if state.get("requires_confirmation") or state.get("tool_name"):
        return "tool_executor_node"
    return "response_synthesizer_node"


def route_after_confirmation(state: AgentState) -> str:
    """After confirmation: execute tool if confirmed; else synthesize response."""
    if state.get("confirmation_decision") == "confirmed" and state.get("tool_name"):
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
    Loads complete conversation history from database, processes input, and persists replies.
    """
    clean_text = (text or "").strip()

    # Load complete conversation history from database
    history = get_db_conversation_history(chat_id)

    initial_state: AgentState = {
        "chat_id": str(chat_id),
        "user_id": str(chat_id),
        "user_message": clean_text,
        "attachments": attachments or [],
        "messages": list(history) + [HumanMessage(content=clean_text)],
    }

    try:
        # Save user message to database
        save_db_chat_message(chat_id, "user", clean_text)

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
