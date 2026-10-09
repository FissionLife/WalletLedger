# Role 1: Telegram Bot Core
# Assigned to: Krishna
"""Telegram entry point: commands, statement uploads, and the shared message handler.

Every channel uses the same logic so there is one code path:
    real Telegram (aiogram polling or webhook, see app/bot/telegram.py)
    /bot/webhook without a configured bot (dev curl testing)
    /bot/simulate_chat (teammates without a bot token)
        -> handle_text() / handle_document() -> Gopal's agent (Contract 1) and the ledger.
"""

from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.bot.agent import classify_reply, process_user_interaction
from app.bot.keys import KEY_COMMANDS, handle_key_command
from app.config import dev_endpoints_enabled, is_chat_allowed
from app.db import SessionLocal
from app.services.ledger import get_account_balances, get_or_create_user, get_spending_summary
from app.services_ai.ai_gateway import extract_api_keys
from app.services_ai.mcp_server import execute_tool
from app.services_ai.transaction_parser import parse_statement_file

PRIVATE_BOT_TEXT = "🔒 This bot is private."

logger = logging.getLogger(__name__)

bot_router = APIRouter(prefix="/bot", tags=["Telegram Bot"])

IMPORT_TTL = timedelta(minutes=10)
PREVIEW_ROWS = 5
IMPORT_ACCOUNT = "Bank"
SUPPORTED_UPLOADS = {".pdf": "pdf", ".txt": "text"}

# (command, short description). This list drives BOTH Telegram's "/" menu hints and /help.
COMMAND_MENU: list[tuple[str, str]] = [
    ("start", "Welcome and quick tips"),
    ("balance", "Your accounts and net worth"),
    ("report", "30-day spending summary"),
    ("coach", "Friendly savings coach"),
    ("budgeter", "Strict budget mode"),
    ("summary", "Quick emoji summary"),
    ("keys", "List your AI keys"),
    ("setkey", "Add an AI key (tested first)"),
    ("testkey", "Test your AI keys now"),
    ("editkey", "Replace a key: /editkey 1 <new key>"),
    ("delkey", "Remove a key: /delkey 1"),
    ("pausekey", "Pause a key: /pausekey 1"),
    ("resumekey", "Resume a key: /resumekey 1"),
    ("help", "How to use WalletLedger"),
]
KNOWN_COMMANDS = {f"/{name}" for name, _ in COMMAND_MENU} | {"/start", "/key"}

HELP_TEXT = (
    "ℹ️ **WalletLedger Help**\n\n"
    "💬 **Just talk to me**\n"
    "• *Paid 150 to Starbucks for coffee*\n"
    "• *Received 60000 salary in Bank*\n"
    "• *Transferred 2000 from Bank to Cash*\n"
    "• Send a PhonePe / GPay / bank **PDF** to import transactions\n\n"
    "📊 **Views**\n"
    "• /balance · /report\n\n"
    "🎭 **Advice modes**\n"
    "• /coach (encouraging) · /budgeter (strict) · /summary (short)\n\n"
    "🔑 **AI keys** (I test a key before saving it)\n"
    "• /setkey `<key>` · /keys · /testkey\n"
    "• /editkey `1 <new key>` · /delkey `1` · /pausekey `1` · /resumekey `1`\n"
    "• If your key fails, I fall back to the shared team keys.\n\n"
    "Tip: type / to see the command menu."
)

START_TEXT = (
    "👋 **Welcome to WalletLedger!** 🪙\n\n"
    "Track money in plain language, import bank statements, and get savings advice.\n\n"
    "🚀 **Try one now**\n"
    "• *Spent 450 on dinner via Bank*\n"
    "• /balance · /report\n"
    "• Send a statement PDF\n\n"
    "🔑 Add your own AI key with /setkey `<key>` (I'll test it first), or use the shared one.\n"
    "Type /help for everything, or / for the command menu."
)


def unknown_command_text(command: str) -> str:
    close = difflib.get_close_matches(command, sorted(KNOWN_COMMANDS), n=3, cutoff=0.5)
    hint = "Did you mean " + " or ".join(close) + "?" if close else "Try /help."
    return f"❓ I don't know `{command}`. {hint}"


# ---------------------------------------------------------------------------
# Pending statement imports (same yes/no idea as the agent's transfer confirmation)
# ---------------------------------------------------------------------------


@dataclass
class PendingImport:
    file_name: str
    rows: list[dict[str, Any]]
    created_at: datetime = field(default_factory=datetime.utcnow)


_pending_imports: dict[str, PendingImport] = {}


def _get_pending_import(chat_id: str) -> PendingImport | None:
    pending = _pending_imports.get(chat_id)
    if pending and datetime.utcnow() - pending.created_at > IMPORT_TTL:
        _pending_imports.pop(chat_id, None)
        return None
    return pending


# ---------------------------------------------------------------------------
# Shared message handling
# ---------------------------------------------------------------------------


PERSONA_COMMANDS = {"/coach", "/budgeter", "/summary"}


def should_delete_message(text: str) -> bool:
    """True if the user's message contains an API key and should be removed from the chat."""
    clean = (text or "").strip()
    return clean.lower().startswith(("/setkey", "/key ", "/editkey")) or bool(
        extract_api_keys(clean)
    )


async def handle_text(chat_id: str, text: str) -> str:
    """Single entry point for a text message from any channel. Returns the reply text."""
    chat_id = str(chat_id)
    clean = (text or "").strip()
    if not is_chat_allowed(chat_id):
        return PRIVATE_BOT_TEXT

    pending = _get_pending_import(chat_id)
    if pending:
        decision = classify_reply(clean)
        if decision:
            return _finish_import(chat_id, decision)
        _pending_imports.pop(chat_id, None)  # unrelated message: drop the pending import

    if clean.startswith("/"):
        command, _, args = clean.partition(" ")
        command = command.split("@", 1)[0].lower()  # "/balance@MyBot" in groups
        if command in KEY_COMMANDS:
            return await handle_key_command(chat_id, command, args.strip())
        reply = _handle_command(chat_id, command, args.strip())
        if reply is not None:
            return reply
        if command not in PERSONA_COMMANDS:
            return unknown_command_text(command)

    return await process_user_interaction(chat_id=chat_id, text=clean)


def _handle_command(chat_id: str, command: str, args: str) -> str | None:
    """Fixed commands. Returns None for anything the agent should handle (e.g. /coach)."""
    if command == "/start":
        _ensure_user(chat_id)
        return START_TEXT
    if command == "/help":
        return HELP_TEXT
    if command == "/balance":
        return _balance_text(chat_id)
    if command == "/report":
        return _report_text(chat_id)
    return None


def _ensure_user(chat_id: str) -> str:
    db = SessionLocal()
    try:
        return get_or_create_user(db, telegram_chat_id=chat_id).id
    finally:
        db.close()


def _balance_text(chat_id: str) -> str:
    db = SessionLocal()
    try:
        user = get_or_create_user(db, telegram_chat_id=chat_id)
        balances = get_account_balances(db, user.id)
    finally:
        db.close()
    accounts_txt = "\n".join(
        f"  • **{acc['name']}** ({acc['type']}): ₹{acc['balance']:,.2f}"
        for acc in balances["accounts"]
    )
    return (
        f"🏦 **Your WalletLedger Tank:**\n"
        f"💰 **Total Net Worth:** ₹{balances['total_net_worth']:,.2f}\n\n"
        f"**Pipes In:**\n{accounts_txt or '  No accounts yet.'}"
    )


def _report_text(chat_id: str) -> str:
    db = SessionLocal()
    try:
        user = get_or_create_user(db, telegram_chat_id=chat_id)
        summary = get_spending_summary(db, user.id, days=30)
    finally:
        db.close()
    cats_txt = (
        "\n".join(f"  • {cat}: ₹{amt:,.2f}" for cat, amt in summary["category_breakdown"].items())
        or "  No expenses recorded yet."
    )
    return (
        f"📊 **30-Day Expense Summary:**\n"
        f"💸 **Total Spent:** ₹{summary['total_expenses']:,.2f}\n"
        f"🧾 **Transactions:** {summary['transaction_count']}\n\n"
        f"**Category Breakdown:**\n{cats_txt}"
    )


# ---------------------------------------------------------------------------
# Statement upload -> Surya's parser (Contract 5) -> preview -> Meet's tools on "yes"
# ---------------------------------------------------------------------------


def upload_type(file_name: str) -> str | None:
    """Map an uploaded file name to the parser's file type, or None if unsupported."""
    for ext, kind in SUPPORTED_UPLOADS.items():
        if (file_name or "").lower().endswith(ext):
            return kind
    return None


async def handle_document(chat_id: str, file_name: str, file_bytes: bytes) -> str:
    """Parse an uploaded statement and ask the user to confirm the import."""
    chat_id = str(chat_id)
    if not is_chat_allowed(chat_id):
        return PRIVATE_BOT_TEXT
    kind = upload_type(file_name)
    if kind is None:
        return "📄 Please upload a PDF statement (or a .txt file with bank SMS lines)."

    db = SessionLocal()
    try:
        user_id = get_or_create_user(db, telegram_chat_id=chat_id).id
        rows = await parse_statement_file(file_bytes, kind, user_id=user_id, db=db)
    except ValueError as e:
        return f"⚠️ Could not read `{file_name}`: {e}"
    except Exception as e:
        logger.error("Statement parsing failed for chat %s: %s", chat_id, e, exc_info=True)
        return f"⚠️ Could not read `{file_name}`. Please try another file."
    finally:
        db.close()

    rows = [r for r in rows if float(r.get("amount") or 0) > 0]
    if not rows:
        return f"📄 I couldn't find any transactions in `{file_name}`."

    _pending_imports[chat_id] = PendingImport(file_name=file_name, rows=rows)
    return _import_preview(file_name, rows)


def _import_preview(file_name: str, rows: list[dict[str, Any]]) -> str:
    spent = sum(r["amount"] for r in rows if r.get("type") != "income")
    received = sum(r["amount"] for r in rows if r.get("type") == "income")
    sample = "\n".join(
        f"  • {r.get('date') or '—'}  {'+' if r.get('type') == 'income' else '-'}₹{r['amount']:,.2f}"
        f"  {r.get('merchant') or 'Unknown'} ({r.get('category') or 'Uncategorized'})"
        for r in rows[:PREVIEW_ROWS]
    )
    more = f"\n  …and {len(rows) - PREVIEW_ROWS} more" if len(rows) > PREVIEW_ROWS else ""
    return (
        f"📄 **Statement:** `{file_name}`\n"
        f"Found **{len(rows)} transactions**: ₹{spent:,.2f} spent, ₹{received:,.2f} received.\n\n"
        f"{sample}{more}\n\n"
        f"Import them into your **{IMPORT_ACCOUNT}** pipe?\n"
        f"👉 Reply **'yes'** to import or **'no'** to cancel."
    )


def _finish_import(chat_id: str, decision: str) -> str:
    pending = _pending_imports.pop(chat_id, None)
    if pending is None:
        return "⌛ That import expired. Please upload the statement again."
    if decision != "confirmed":
        return "❌ **Import cancelled.** Nothing was added to your ledger."

    imported, failed = 0, 0
    for row in pending.rows:
        try:
            if row.get("type") == "income":
                execute_tool(
                    "log_income",
                    user_id=chat_id,
                    amount=row["amount"],
                    source_account=IMPORT_ACCOUNT,
                    category=row.get("category") or "Income",
                    description=row.get("description"),
                    source="pdf",
                )
            else:
                execute_tool(
                    "log_expense",
                    user_id=chat_id,
                    amount=row["amount"],
                    category=row.get("category") or "Uncategorized",
                    merchant=row.get("merchant") if row.get("merchant") != "Unknown" else None,
                    account_name=IMPORT_ACCOUNT,
                    description=row.get("description"),
                    source="pdf",
                )
            imported += 1
        except Exception as e:
            failed += 1
            logger.warning("Import row failed for chat %s: %s", chat_id, e)

    text = f"✅ **Imported {imported} transactions** from `{pending.file_name}`."
    if failed:
        text += f"\n⚠️ {failed} rows could not be imported."
    return text + "\nSee them with `/report` or `/balance`."


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------


class SimulateMessageRequest(BaseModel):
    chat_id: str
    text: str


@bot_router.post("/webhook")
async def telegram_webhook(request: Request):
    """Telegram webhook.

    Webhook mode with a bot token: verified with the secret header, then handled by aiogram,
    which sends the reply to Telegram. Otherwise (local dev / curl): the reply is returned
    as JSON so the endpoint stays testable without a token.
    """
    from app.bot import telegram

    if not telegram.webhook_active() and not dev_endpoints_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    update = await request.json()
    if telegram.webhook_active():
        header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if header != telegram.webhook_secret():
            raise HTTPException(status_code=403, detail="invalid webhook secret")
        await telegram.feed_webhook_update(update)
        return {"ok": True}

    message = update.get("message") or {}
    chat_id = str((message.get("chat") or {}).get("id", ""))
    if not chat_id:
        return {"status": "ignored", "reason": "no message payload"}
    if message.get("document"):
        return {
            "status": "ok",
            "reply": "📄 File uploads need the real Telegram bot (set TELEGRAM_BOT_TOKEN).",
        }
    return {"status": "ok", "reply": await handle_text(chat_id, message.get("text") or "")}


@bot_router.post("/simulate_chat")
async def simulate_chat(req: SimulateMessageRequest):
    """Developer endpoint: same logic as Telegram, no bot token needed."""
    if not dev_endpoints_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    return {"status": "ok", "reply": await handle_text(req.chat_id, req.text)}
