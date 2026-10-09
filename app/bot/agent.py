# Role 2: LangGraph agent workflow.
#   classify -> act -> respond
# Works with no LLM key (rule-based intent parsing + templated replies); when the user has a key,
# the LLM is used for free-form questions, advice wording and as an intent-classifier fallback.
import asyncio
import json
import logging
import re
import time
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.config import settings
from app.db import SessionLocal
from app.services import ledger
from app.services_ai import ai_gateway, mcp_server, prompts, transaction_parser

logger = logging.getLogger(__name__)

PENDING_TTL_SECONDS = 300
_YES = re.compile(r"^\s*(y|yes|yep|yeah|confirm|ok|okay|sure|do it)\s*[.!]?\s*$", re.I)
_NO = re.compile(r"^\s*(n|no|nope|cancel|stop|abort)\s*[.!]?\s*$", re.I)
_MODE = re.compile(
    r"\b(coach|ruthless|quick)\s+mode\b|\bmode\s*[:=]\s*(coach|ruthless|quick)\b", re.I
)

# chat_id -> (tool_name, kwargs, created_at). In-memory: lost on restart, which is safe
# (the user just re-sends the request).
_pending: dict[str, tuple[str, dict[str, Any], float]] = {}
_modes: dict[str, str] = {}

HELP_HINT = (
    "🤔 I didn't catch that. Try:\n"
    "• *Spent 450 on dinner via Bank*\n"
    "• *Received 50000 salary in Bank*\n"
    "• *Transferred 2000 from Bank to Cash*\n"
    "• */balance*, */report*, or *how can I reduce expenses?*"
)


class AgentState(TypedDict, total=False):
    chat_id: str
    user_id: str
    text: str
    intent: str
    entities: dict[str, Any]
    result: dict[str, Any]
    reply: str


# ------------------------------- helpers ----------------------------------


def _inr(x: float) -> str:
    return f"₹{x:,.2f}"


def _json_from_llm(raw: str) -> dict | None:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _get_user_id(chat_id: str) -> str:
    with SessionLocal() as db:
        return ledger.get_or_create_user(db, chat_id).id


async def _tool(name: str, **kwargs: Any) -> dict:
    return await asyncio.to_thread(mcp_server.execute_tool, name, **kwargs)


async def _llm(user_id: str, system: str, prompt: str) -> str | None:
    """Returns None when there is no key or every provider failed (caller falls back)."""
    try:
        return await ai_gateway.ask_llm(user_id, system, prompt)
    except ai_gateway.LLMUnavailableError:
        return None


def _tool_for(intent: str, e: dict[str, Any], user_id: str) -> tuple[str, dict[str, Any]] | None:
    if intent == "expense" and e.get("amount"):
        return "log_expense", {
            "user_id": user_id,
            "amount": e["amount"],
            "category": e.get("category"),
            "merchant": e.get("merchant"),
            "account_name": e.get("account") or "Cash",
            "description": e.get("description"),
        }
    if intent == "income" and e.get("amount"):
        return "log_income", {
            "user_id": user_id,
            "amount": e["amount"],
            "source_account": e.get("account") or "Bank",
            "description": e.get("description"),
            "category": e.get("category") or "Income",
        }
    if intent == "transfer" and e.get("amount") and e.get("account") and e.get("to_account"):
        return "transfer_between_pipes", {
            "user_id": user_id,
            "from_account": e["account"],
            "to_account": e["to_account"],
            "amount": e["amount"],
        }
    return None


# -------------------------------- nodes -----------------------------------


async def classify_node(state: AgentState) -> AgentState:
    text = state["text"]
    entities = transaction_parser.parse_chat_expense(text)
    if entities["intent"] == "other" and len(text) > 3:
        raw = await _llm(state["user_id"], prompts.INTENT_CLASSIFIER_PROMPT, text)
        parsed = _json_from_llm(raw) if raw else None
        if parsed and parsed.get("intent") in {
            "expense",
            "income",
            "transfer",
            "balance",
            "report",
            "advice",
        }:
            entities = {k: v for k, v in parsed.items() if v is not None}
            entities["description"] = text
            # never trust the model's amount blindly
            if "amount" in entities:
                try:
                    entities["amount"] = float(entities["amount"])
                except Exception:
                    entities.pop("amount")
    return {"intent": entities["intent"], "entities": entities}


async def act_node(state: AgentState) -> AgentState:
    intent, e, user_id, chat_id = (
        state["intent"],
        state["entities"],
        state["user_id"],
        state["chat_id"],
    )

    if intent in ("expense", "income", "transfer"):
        call = _tool_for(intent, e, user_id)
        if call is None:
            return {
                "result": {
                    "status": "error",
                    "error": "I need an amount (and accounts for transfers).",
                }
            }
        name, kwargs = call
        if kwargs["amount"] >= settings.confirm_threshold:
            _pending[chat_id] = (name, kwargs, time.monotonic())
            return {
                "result": {
                    "status": "needs_confirmation",
                    "tool": name,
                    "amount": kwargs["amount"],
                }
            }
        return {"result": {**await _tool(name, **kwargs), "_tool": name}}

    if intent == "balance":
        return {"result": {**await _tool("get_pipe_balances", user_id=user_id), "_tool": "balance"}}

    if intent == "report":
        result = await _tool(
            "get_spending_breakdown", user_id=user_id, period="month", category=e.get("category")
        )
        return {"result": {**result, "_tool": "report"}}

    if intent == "advice":
        insights, bills, alerts = await asyncio.gather(
            _tool("get_insights", user_id=user_id, mode="reduce"),
            _tool("skill_recurring_bill_detector", user_id=user_id),
            _tool("skill_budget_alert_check", user_id=user_id),
        )
        return {
            "result": {
                "status": "success",
                "_tool": "advice",
                "insights": insights,
                "bills": bills,
                "alerts": alerts,
            }
        }

    if intent == "set_key":
        result = await _tool(
            "save_user_api_key", user_id=user_id, provider=None, api_key=e["api_key"]
        )
        return {"result": {**result, "_tool": "set_key"}}

    return {"result": {"status": "unhandled", "_tool": "other"}}


def _format_tool_result(r: dict[str, Any]) -> str:
    tool = r.get("_tool")
    if r.get("status") == "error":
        return f"⚠️ {r.get('error', 'Something went wrong.')}"
    if tool == "log_expense":
        merchant = "" if r["merchant"] == "N/A" else f" @ {r['merchant']}"
        return (
            f"✅ **Expense logged:** {_inr(r['amount'])} → {r['category']}{merchant}\n"
            f"🏦 {r['account']} balance: {_inr(r['new_balance'])}"
        )
    if tool == "log_income":
        return (
            f"✅ **Income logged:** {_inr(r['amount'])} ({r['category']})\n"
            f"🏦 {r['account']} balance: {_inr(r['new_balance'])}"
        )
    if tool == "transfer_between_pipes":
        return (
            f"🔁 **Transferred {_inr(r['transferred'])}** (not counted as spending)\n"
            f"• {r['from_account']}: {_inr(r['from_balance'])}\n"
            f"• {r['to_account']}: {_inr(r['to_balance'])}"
        )
    if tool == "balance":
        lines = "\n".join(
            f"  • **{a['name']}** ({a['type']}): {_inr(a['balance'])}" for a in r["accounts"]
        )
        return f"🏦 **Your Tank:** {_inr(r['total_net_worth'])}\n\n**Pipes In:**\n{lines}"
    if tool == "report":
        cats = "\n".join(f"  • {c}: {_inr(a)}" for c, a in r["category_breakdown"].items())
        return (
            f"📊 **{r['period_days']}-Day Expense Summary:**\n"
            f"💸 **Total Spent:** {_inr(r['total_expenses'])}\n"
            f"🧾 **Transactions:** {r['transaction_count']}\n\n"
            f"**Category Breakdown:**\n{cats or '  No expenses recorded yet.'}"
        )
    if tool == "set_key":
        extra = " (already saved, re-activated)" if r.get("duplicate") else ""
        return (
            f"🔑 **{r['provider'].title()} key saved{extra}.** It is stored encrypted.\n"
            "⚠️ Please delete your message containing the key from this chat."
        )
    return "Done."


def _template_advice(r: dict[str, Any]) -> str:
    ins = r["insights"]
    lines = ["💡 **Where you can cut back:**"]
    tips = ins.get("tips", [])
    for t in tips[:5]:
        lines.append(f"• {t['tip']}")
    if not tips:
        lines.append("• No obvious savings yet. Log more expenses and ask again.")
    for a in r["alerts"].get("alerts", [])[:3]:
        icon = "🚨" if a["level"] == "exceeded" else "⚠️"
        lines.append(f"{icon} {a['category']}: {a['percent_used']}% of budget used")
    if ins.get("potential_monthly_saving"):
        lines.append(f"\n💰 Potential saving: {_inr(ins['potential_monthly_saving'])}/month")
    return "\n".join(lines)


async def respond_node(state: AgentState) -> AgentState:
    r = state["result"]
    user_id, chat_id = state["user_id"], state["chat_id"]

    if r.get("status") == "needs_confirmation":
        return {
            "reply": (
                f"🛑 That's a large amount ({_inr(r['amount'])}). "
                "Reply **yes** to confirm or **no** to cancel."
            )
        }

    if r.get("_tool") == "advice":
        template = _template_advice(r)
        facts = json.dumps(
            {"insights": r["insights"], "bills": r["bills"], "alerts": r["alerts"]}, default=str
        )
        llm = await _llm(
            user_id,
            prompts.get_persona(_modes.get(chat_id)),
            f"User question: {state['text']}\nUse ONLY this data:\n{facts}",
        )
        return {"reply": llm or template}

    if r.get("status") == "unhandled":
        facts = await _tool("get_pipe_balances", user_id=user_id)
        llm = await _llm(
            user_id,
            prompts.get_persona(_modes.get(chat_id)),
            f"User message: {state['text']}\nTheir balances: {json.dumps(facts, default=str)}",
        )
        return {"reply": llm or HELP_HINT}

    return {"reply": _format_tool_result(r)}


# ------------------------------- the graph --------------------------------

_builder = StateGraph(AgentState)
_builder.add_node("classify", classify_node)
_builder.add_node("act", act_node)
_builder.add_node("respond", respond_node)
_builder.add_edge(START, "classify")
_builder.add_edge("classify", "act")
_builder.add_edge("act", "respond")
_builder.add_edge("respond", END)
agent_graph = _builder.compile()


async def _handle_pending(chat_id: str, text: str) -> str | None:
    entry = _pending.get(chat_id)
    if entry is None:
        return None
    name, kwargs, created = entry
    if time.monotonic() - created > PENDING_TTL_SECONDS:
        _pending.pop(chat_id, None)
        return None
    if _YES.match(text):
        _pending.pop(chat_id, None)
        result = await _tool(name, **kwargs)
        return _format_tool_result({**result, "_tool": name})
    if _NO.match(text):
        _pending.pop(chat_id, None)
        return "👍 Cancelled. Nothing was recorded."
    return None  # unrelated message: leave the pending action alone, process normally


async def process_user_interaction(
    chat_id: str, text: str, attachments: list[Any] | None = None
) -> str:
    """Contract 1: Bot -> agent. Returns the Markdown reply for Telegram. Never raises."""
    chat_id = str(chat_id)
    clean = (text or "").strip()
    if not clean:
        return HELP_HINT
    if len(clean) > 2000:
        return "⚠️ That message is too long. Please keep it under 2000 characters."

    try:
        if (reply := await _handle_pending(chat_id, clean)) is not None:
            return reply
        if m := _MODE.search(clean):
            mode = (m.group(1) or m.group(2)).lower()
            _modes[chat_id] = mode
            return f"🎭 Switched to **{mode}** mode."
        user_id = await asyncio.to_thread(_get_user_id, chat_id)
        final = await agent_graph.ainvoke({"chat_id": chat_id, "user_id": user_id, "text": clean})
        return final["reply"]
    except Exception:
        logger.exception("Agent failed for chat %s", chat_id)
        return "⚠️ Something went wrong on my side. Please try again."


# Backward compatibility
def process_message(chat_id: str, text: str) -> str:
    return asyncio.run(process_user_interaction(chat_id, text))
