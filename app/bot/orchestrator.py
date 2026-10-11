"""Multi-step helper for questions that need more than one tool.

"Can I save 50000 in 6 months, and move 2000 to savings now?" needs a plan (analyst), then a
transfer (ledger), then a plain answer (writer). One loop handles it:

    AI picks tools -> we run them -> AI sees the results -> repeat -> AI writes the answer

Guard rails (kept deliberately small so they are easy to explain):
  * at most MAX_STEPS rounds and MAX_TOOL_CALLS tool calls per message
  * the AI can only use the tools we hand in, and never `save_user_api_key`
  * a big transfer is not run: it pauses and asks the user to tap Yes (same rule as everywhere)
  * if the AI breaks before anything was changed, the caller falls back to the simple path
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.services_ai import ai_gateway as gw
from app.services_ai.mcp_server import execute_tool

logger = logging.getLogger(__name__)

MAX_STEPS = 5
MAX_TOOL_CALLS = 12
MAX_RESULT_CHARS = 6000  # what the AI is shown of one tool result

BLOCKED_TOOLS = {"save_user_api_key"}
WRITE_TOOLS = {
    "log_expense",
    "log_income",
    "transfer_funds",
    "edit_transaction",
    "set_category_budget",
}

ROLES = (
    "You work as four helpers in one:\n"
    "- Ledger: record spending, income and transfers exactly as the user said (one tool call per item).\n"
    "- Analyst: look at their numbers with get_financial_snapshot / get_spending_breakdown before "
    "judging anything. Never guess a figure you can look up.\n"
    "- Planner: for goals use savings_plan and say plainly whether it is realistic.\n"
    "- Writer: finish with a short, friendly answer (under 120 words, rupee amounts like ₹4,500, "
    "no tables). Lead with the answer, then at most 3 bullet points.\n"
    "Only change money records when the user clearly asked you to. If something is missing "
    "(for example an amount), ask one short question instead of guessing."
)

# Words that suggest the message needs looking at the numbers or several steps.
_COMPLEX_HINTS = (
    "can i", "could i", "should i", "afford", "plan", "save", "saving", "goal", "target", "why",
    "how much", "how am i", "compare", "advice", "advise", "reduce", "cut", "trim", "improve",
    "suggest", "recommend", "budget", "forecast", "predict", "worth", "enough", "last month",
    "this month", "next month", "per month", "monthly", "and then", "also",
)  # fmt: skip


def looks_complex(message: str) -> bool:
    """Cheap check: is this a question or goal rather than a plain 'spent 200 on tea'?"""
    low = (message or "").lower()
    return len(low) > 25 and any(h in low for h in _COMPLEX_HINTS)


@dataclass
class Result:
    """What the loop produced."""

    text: str = ""
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    pending: dict[str, Any] | None = None  # a tool call waiting for the user's Yes
    tools_run: int = 0
    wrote: bool = False  # did we change the ledger?


def _clip(result: Any) -> str:
    text = json.dumps(result, default=str, ensure_ascii=False)
    return text if len(text) <= MAX_RESULT_CHARS else text[:MAX_RESULT_CHARS] + "…(cut)"


def _call_parts(call: Any) -> tuple[str, str, dict[str, Any]]:
    fn = call.function if hasattr(call, "function") else call["function"]
    name = fn.name if hasattr(fn, "name") else fn["name"]
    raw = fn.arguments if hasattr(fn, "arguments") else fn.get("arguments")
    call_id = call.id if hasattr(call, "id") else call.get("id", name)
    try:
        args = json.loads(raw or "{}")
    except json.JSONDecodeError:
        args = {}
    return str(call_id), name, args if isinstance(args, dict) else {}


async def run(
    chat_id: str,
    message: str,
    history: list[dict[str, str]],
    *,
    tools: list[dict[str, Any]],
    system_prompt: str,
    transfer_threshold: float,
) -> Result:
    """Run the loop. Raises on AI failure only if nothing was changed yet (caller falls back)."""
    allowed = {
        t["function"]["name"]: t for t in tools if t["function"]["name"] not in BLOCKED_TOOLS
    }
    schema = list(allowed.values())
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt + "\n\n" + ROLES}]
    messages.extend(history)
    messages.append({"role": "user", "content": message})
    out = Result()

    for _ in range(MAX_STEPS):
        try:
            response = await gw.complete(chat_id, messages, tools=schema)
        except Exception:
            if out.wrote:
                logger.exception("AI failed mid-way for chat %s; keeping what was done", chat_id)
                out.text = out.text or "I recorded that, but couldn't finish the rest just now."
                return out
            raise
        reply = response.choices[0].message
        calls = getattr(reply, "tool_calls", None) or []
        if not calls:
            out.text = (getattr(reply, "content", "") or "").strip()
            return out

        messages.append(
            {
                "role": "assistant",
                "content": getattr(reply, "content", None) or "",
                "tool_calls": [
                    {
                        "id": _call_parts(c)[0],
                        "type": "function",
                        "function": {
                            "name": _call_parts(c)[1],
                            "arguments": json.dumps(_call_parts(c)[2]),
                        },
                    }
                    for c in calls
                ],
            }
        )
        for call in calls:
            call_id, name, args = _call_parts(call)
            args["user_id"] = chat_id  # never trust an id from the AI
            if out.tools_run >= MAX_TOOL_CALLS:
                body: Any = {"status": "skipped", "reason": "too many steps for one message"}
            elif name not in allowed:
                body = {"status": "error", "message": f"unknown tool {name}"}
            elif name == "transfer_funds" and _big(args, transfer_threshold):
                out.pending = {"tool_name": name, "tool_args": args}
                body = {"status": "waiting", "message": "the user must confirm this transfer"}
            else:
                out.tools_run += 1
                try:
                    body = await asyncio.to_thread(execute_tool, name, **args)
                    out.tool_results.append(
                        {"tool_name": name, "tool_args": args, "result": body, "error": None}
                    )
                    out.wrote = out.wrote or name in WRITE_TOOLS
                except Exception as exc:
                    logger.warning("orchestrator tool %s failed: %s", name, exc)
                    body = {"status": "error", "message": str(exc)[:200]}
                    out.tool_results.append(
                        {"tool_name": name, "tool_args": args, "result": None, "error": str(exc)}
                    )
            messages.append({"role": "tool", "tool_call_id": call_id, "content": _clip(body)})
        if out.pending:  # stop here; the answer comes after the user taps Yes
            return out

    out.text = (
        out.text or "That needed more steps than I allow in one go. Try asking in smaller parts."
    )
    return out


def _big(args: dict[str, Any], threshold: float) -> bool:
    try:
        return float(args.get("amount", 0)) >= threshold
    except TypeError, ValueError:
        return False
