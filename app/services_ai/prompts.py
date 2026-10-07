"""Role 3: System prompts & mode personas for the WalletLedger AI.

Three personas are available:

* ``coach``    - Fold-App style Financial Coach: encouraging, data-driven, highlights savings.
* ``budgeter`` - Ruthless Budgeter: direct, stern feedback when discretionary spend runs high.
* ``summary``  - Telegram Quick-Summary: compact emoji bullet points for mobile chat.

Typical use from the agent (Role 2)::

    from app.services_ai.prompts import build_system_prompt, detect_mode

    mode = detect_mode(user_text)  # or a mode the user picked explicitly
    system_prompt = build_system_prompt(mode, context=tool_results)
    reply = await ask_llm(user_id, system_prompt, user_text)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Mode(StrEnum):
    COACH = "coach"
    BUDGETER = "budgeter"
    SUMMARY = "summary"


DEFAULT_MODE = Mode.COACH

# Shared ground rules every persona follows.
BASE_RULES = """You are WalletLedger, an AI personal-finance assistant inside a Telegram bot.

How WalletLedger models money ("Tank & Pipes"):
- The Tank is the user's combined balance / net worth.
- Pipes In are income sources and accounts (bank accounts, cash, wallets, cards).
- Pipes Out are where money goes (expenses and investments, grouped by category).
- A transfer between the user's own pipes (e.g. Bank -> Cash) is NOT an expense or income.

Rules:
- Use only the numbers given in the context or by the user. Never invent amounts, dates or merchants.
  If data is missing, say so briefly and suggest what the user can log.
- Default currency is Indian Rupees; format amounts like ₹1,250.
- Write Telegram-friendly Markdown: short paragraphs, *bold* for key figures, no tables, no headings.
- Do not ask for or repeat API keys, passwords, OTPs or card numbers.
- You give general budgeting guidance, not regulated investment, tax or legal advice."""


@dataclass(frozen=True)
class Persona:
    mode: Mode
    name: str
    description: str
    prompt: str


PERSONAS: dict[Mode, Persona] = {
    Mode.COACH: Persona(
        mode=Mode.COACH,
        name="Financial Coach",
        description="Encouraging, data-driven guidance that highlights savings opportunities.",
        prompt="""Persona: Financial Coach (Fold-App style).
- Tone: warm, encouraging and positive, but always grounded in the user's actual numbers.
- Start with what is going well (a win, a category under budget, money saved).
- Then point out the 1-3 biggest savings opportunities, each with a concrete amount
  (e.g. "cutting food delivery from 12 to 8 orders saves ~₹1,600/month").
- End with one small, specific next step the user can take this week.
- Keep it under ~150 words unless the user asks for detail.""",
    ),
    Mode.BUDGETER: Persona(
        mode=Mode.BUDGETER,
        name="Ruthless Budgeter",
        description="Direct, stern feedback when discretionary spending runs high.",
        prompt="""Persona: Ruthless Budgeter ("Reduce Money Mode").
- Tone: blunt, direct and no-nonsense. No sugar-coating, no filler, no cheerleading.
  Be stern about the spending, never insulting to the person.
- Lead with the worst offender: the category, merchant or subscription burning the most
  discretionary money, with its exact amount and % of budget if known.
- Separate needs (rent, utilities, EMIs, groceries) from wants (food delivery, shopping,
  entertainment, unused subscriptions). Attack the wants.
- Give a numbered cut-list: what to cancel or reduce, and the monthly ₹ saved for each.
- Call out budget overruns explicitly (e.g. "Food: 132% of budget. Stop.").
- Finish with the total monthly saving if the user follows the list.""",
    ),
    Mode.SUMMARY: Persona(
        mode=Mode.SUMMARY,
        name="Quick Summary",
        description="Compact emoji bullet points formatted for mobile chat.",
        prompt="""Persona: Telegram Quick Summary.
- Output ONLY a compact bullet list, max 6 bullets, one line each. No intro, no outro.
- Start every bullet with a fitting emoji, e.g. 💰 balance, 📥 income, 📤 spent,
  🍔 food, 🚕 travel, 🛒 shopping, 🔁 subscriptions, ⚠️ warning, ✅ on track.
- Put the key number in *bold* in every bullet.
- If something needs attention (budget crossed, low balance), make it the last bullet with ⚠️.""",
    ),
}

# Keyword rules for automatic mode switching. Checked in this order: the first match wins.
_MODE_KEYWORDS: list[tuple[Mode, tuple[str, ...]]] = [
    (
        Mode.BUDGETER,
        (
            "ruthless",
            "budgeter",
            "reduce money",
            "reduce my",
            "reduce expense",
            "reduce spend",
            "cut down",
            "cut back",
            "cut my",
            "cut cost",
            "save more",
            "stop spending",
            "overspend",
            "overspent",
            "over budget",
            "too much",
            "wasting",
            "be strict",
            "be harsh",
            "roast",
        ),
    ),
    (
        Mode.SUMMARY,
        (
            "summary",
            "summarize",
            "summarise",
            "quick",
            "tl;dr",
            "tldr",
            "brief",
            "overview",
            "snapshot",
            "recap",
            "report",
            "analytics",
            "breakdown",
            "where did my money",
            "where most",
            "balance",
        ),
    ),
    (
        Mode.COACH,
        (
            "coach",
            "advice",
            "advise",
            "tips",
            "suggest",
            "help me save",
            "how can i",
            "how do i",
            "plan",
            "goal",
            "improve",
            "motivate",
        ),
    ),
]

_ALIASES: dict[str, Mode] = {
    "coach": Mode.COACH,
    "financial_coach": Mode.COACH,
    "fold": Mode.COACH,
    "budgeter": Mode.BUDGETER,
    "ruthless": Mode.BUDGETER,
    "ruthless_budgeter": Mode.BUDGETER,
    "reduce": Mode.BUDGETER,
    "reduce_money": Mode.BUDGETER,
    "summary": Mode.SUMMARY,
    "quick": Mode.SUMMARY,
    "quick_summary": Mode.SUMMARY,
    "analytics": Mode.SUMMARY,
}


def resolve_mode(mode: str | Mode | None) -> Mode:
    """Normalise a mode name or alias ("ruthless", "Quick Summary", "/coach") to a Mode."""
    if isinstance(mode, Mode):
        return mode
    if not mode:
        return DEFAULT_MODE
    key = re.sub(r"[\s\-]+", "_", mode.strip().lstrip("/").lower())
    if key.endswith("_mode"):
        key = key[: -len("_mode")]
    if key in _ALIASES:
        return _ALIASES[key]
    raise ValueError(f"Unknown mode {mode!r}. Choose one of: {', '.join(m.value for m in Mode)}")


def detect_mode(text: str | None, default: Mode = DEFAULT_MODE) -> Mode:
    """Pick a persona from the user's message using simple keyword rules.

    An explicit command such as ``/budgeter`` or ``/summary`` always wins.
    """
    if not text:
        return default
    lowered = text.lower()
    command = re.match(r"\s*/(\w+)", lowered)
    if command and command.group(1) in _ALIASES:
        return _ALIASES[command.group(1)]
    for mode, keywords in _MODE_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return mode
    return default


def get_persona(mode: str | Mode | None = None) -> Persona:
    return PERSONAS[resolve_mode(mode)]


def list_modes() -> list[dict[str, str]]:
    """Mode catalogue, e.g. for a /modes command in the bot."""
    return [
        {"mode": p.mode.value, "name": p.name, "description": p.description}
        for p in PERSONAS.values()
    ]


def _format_context(context: Any) -> str:
    if isinstance(context, str):
        return context.strip()
    return json.dumps(context, indent=2, default=str, ensure_ascii=False)


def build_system_prompt(
    mode: str | Mode | None = None,
    context: Any = None,
    extra_instructions: str | None = None,
) -> str:
    """Compose the full system prompt: shared rules + persona + optional data context.

    ``context`` can be a string or any JSON-serialisable object, e.g. the dict returned by
    an MCP tool such as ``get_spending_breakdown``.
    """
    parts = [BASE_RULES, get_persona(mode).prompt]
    if context is not None and context != "":
        parts.append("User's financial data (source of truth):\n" + _format_context(context))
    if extra_instructions:
        parts.append(extra_instructions.strip())
    return "\n\n".join(parts)
