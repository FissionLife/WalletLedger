"""Telegram entry point: commands, statement uploads, and the shared message handler.

Every channel uses the same logic so there is one code path:
    real Telegram (aiogram polling or webhook, see app/bot/telegram.py)
    /bot/webhook without a configured bot (dev curl testing)
    /bot/simulate_chat (teammates without a bot token)
        -> handle_incoming() / handle_document() -> the agent (agent.py) and the ledger.
"""

from __future__ import annotations

import difflib
import hmac
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.bot import nlu, replies, ui, views
from app.bot.agent import classify_reply, process_user_interaction_ex, session_store
from app.bot.keys import KEY_COMMANDS, handle_admin_command, handle_key_command
from app.bot.ui import Reply
from app.config import dev_endpoints_enabled, is_chat_allowed
from app.db import SessionLocal
from app.health import user_status_text
from app.models import Transaction
from app.services.ledger import get_or_create_user
from app.services_ai import tool_client
from app.services_ai.ai_gateway import extract_api_keys
from app.services_ai.transaction_parser import parse_statement_file, summarize_statement

PRIVATE_BOT_TEXT = "🔒 This bot is private."

logger = logging.getLogger(__name__)

bot_router = APIRouter(prefix="/bot", tags=["Telegram Bot"])

IMPORT_TTL = timedelta(minutes=10)
PREVIEW_ROWS = 5
IMPORT_ACCOUNT = "Bank"
SUPPORTED_UPLOADS = {".pdf": "pdf", ".txt": "text"}

# (command, short description). This list drives BOTH Telegram's "/" menu hints and /help.
COMMAND_MENU: list[tuple[str, str]] = [
    ("start", "Welcome and quick start"),
    ("menu", "Open the quick menu"),
    ("balance", "Your accounts and total money"),
    ("stats", "Spending stats and charts"),
    ("history", "Recent transactions"),
    ("undo", "Undo the last entry"),
    ("budget", "Monthly budgets: /budget food 6000"),
    ("plan", "Savings goal: /plan 50000 6"),
    ("dashboard", "Open your web dashboard"),
    ("export", "Download your data as CSV"),
    ("coach", "Friendly savings advice"),
    ("budgeter", "Strict budget advice"),
    ("summary", "Quick summary"),
    ("keys", "Manage your AI keys"),
    ("setkey", "Add your AI key"),
    ("status", "AI and storage health"),
    ("help", "How to use WalletLedger"),
]
# Commands that work but are not in the menu (the menu stays short; buttons cover most of these).
HIDDEN_COMMANDS = (
    "report",
    "chart",
    "testkey",
    "editkey",
    "delkey",
    "pausekey",
    "resumekey",
    "key",
    "admin",
)
KNOWN_COMMANDS = {f"/{name}" for name, _ in COMMAND_MENU} | {f"/{c}" for c in HIDDEN_COMMANDS}

HELP_TEXT = (
    "ℹ️ **WalletLedger**\n\n"
    "**Add** (just type)\n"
    "• Spent 450 on dinner via Bank\n"
    "• Received 60000 salary in Bank\n"
    "• Transferred 2000 from Bank to Cash\n"
    "• Send a PhonePe / GPay / bank PDF\n\n"
    "**See**\n"
    "/balance · /stats · /history · /budget · /plan · /dashboard · /export\n"
    "Try: /stats 90d food · /stats last month · /chart categories\n\n"
    "**Fix**\n"
    "/undo removes the last entry you made (or tap ↩️ Undo)\n\n"
    "**Advice**\n"
    "/coach · /budgeter · /summary\n\n"
    "**AI**\n"
    "/setkey <key> · /keys · /status\n"
    "Your own key is used first; a shared key is the backup.\n\n"
    "Tip: type / to see all commands."
)

START_TEXT = (
    "👋 **Welcome to WalletLedger**\n"
    "Tell me what you spend and earn, in plain words. I keep the books.\n\n"
    "Try: *Spent 450 on dinner via Bank*\n"
    "Or send a bank / PhonePe PDF to import it.\n\n"
    "For smart answers, add your AI key: /setkey"
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


async def handle_incoming(chat_id: str, text: str) -> Reply:
    """Single entry point for a text message from any channel: returns text plus optional buttons."""
    chat_id = str(chat_id)
    clean = (text or "").strip()
    if not is_chat_allowed(chat_id):
        return Reply(PRIVATE_BOT_TEXT)

    pending = _get_pending_import(chat_id)
    if pending:
        decision = classify_reply(clean)
        if decision:
            done = await _finish_import(chat_id, decision)
            rows = [[ui.Btn("📊 Stats", "go:stats"), ui.Btn("🧾 History", "go:history")]]
            return Reply(done, rows=rows if "Imported" in done else [])
        _pending_imports.pop(chat_id, None)  # unrelated message: drop the pending import

    if clean.startswith("/"):
        command, _, args = clean.partition(" ")
        command = command.split("@", 1)[0].lower()  # "/balance@MyBot" in groups
        args = args.strip()
        if command == "/keys":
            from app.bot.callbacks import keys_screen

            return await keys_screen(chat_id)
        if command in KEY_COMMANDS:
            return Reply(await handle_key_command(chat_id, command, args))
        if command == "/status":
            return Reply(await user_status_text(chat_id), rows=ui.back_home())
        if command == "/admin":
            return Reply(await handle_admin_command(chat_id, args))
        reply = await _view_command(chat_id, command, args)
        if reply is not None:
            return reply
        if command not in PERSONA_COMMANDS:
            return Reply(unknown_command_text(command))

    if classify_reply(clean) and not session_store.get_pending(chat_id):
        return Reply(replies.NOTHING_PENDING, rows=ui.back_home())
    screen = nlu.detect_screen(clean)  # "how much did I spend on food last month" -> stats screen
    if screen is not None:
        view = await _view_command(chat_id, screen.command, screen.args)
        if view is not None:
            return view

    outcome = await process_user_interaction_ex(chat_id=chat_id, text=clean)
    rows: list[list[ui.Btn]] = []
    if outcome.needs_confirmation:
        rows = ui.confirm_rows()
    elif outcome.transaction_ids:
        rows = [ui.undo_row(outcome.transaction_ids)]
    return Reply(outcome.text, rows=rows)


async def handle_text(chat_id: str, text: str) -> str:
    """Text-only wrapper (dev endpoint, tests): the reply text without buttons."""
    return (await handle_incoming(chat_id, text)).text


async def _view_command(chat_id: str, command: str, args: str) -> Reply | None:
    """Commands that open a screen (stats, history, ...). None if `command` is not one of them."""
    if command == "/start":
        _ensure_user(chat_id)
        return Reply(START_TEXT, rows=ui.home_rows())
    if command == "/menu":
        return views.home()
    if command == "/help":
        return Reply(HELP_TEXT, rows=ui.back_home())
    if command == "/balance":
        return await views.balance(chat_id)
    if command in ("/stats", "/report"):
        return await views.stats(chat_id, args)
    if command == "/chart":
        kind, _, rest = args.partition(" ")
        kind = kind.lower()
        if kind not in dict(ui.CHARTS) | {
            "monthly": "",
            "stack": "",
            "sizes": "",
            "hours": "",
            "accounts": "",
        }:
            names = ", ".join(k for k, _ in ui.CHARTS)
            return Reply(f"Which chart? /chart <name> [period]\nNames: {names}")
        period, words = views.parse_args(rest)
        return await views.chart(chat_id, kind, period, views._remember(words))
    if command == "/history":
        return await views.history(
            chat_id, int(args) - 1 if args.isdigit() and int(args) > 0 else 0
        )
    if command == "/undo":
        return await views.undo(chat_id, "last")
    if command == "/export":
        period, _ = views.parse_args(args)
        return await views.export_csv(chat_id, period)
    if command == "/budget":
        return await views.budgets(chat_id, args)
    if command == "/dashboard":
        return await views.dashboard(chat_id)
    if command == "/plan":
        return await views.plan(chat_id, args)
    return None


def _ensure_user(chat_id: str) -> str:
    db = SessionLocal()
    try:
        return get_or_create_user(db, telegram_chat_id=chat_id).id
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Statement upload -> the parser (transaction_parser.py) -> preview -> the ledger on "yes"
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


async def handle_document_rich(chat_id: str, file_name: str, file_bytes: bytes) -> Reply:
    """Like handle_document, plus Import / Skip buttons when a preview is waiting for an answer."""
    text = await handle_document(chat_id, file_name, file_bytes)
    rows = ui.import_rows() if _get_pending_import(str(chat_id)) else []
    return Reply(text, rows=rows)


def _import_preview(file_name: str, rows: list[dict[str, Any]]) -> str:
    summary = summarize_statement(rows)
    kind = f" ({summary['format_label']})" if summary["format_label"] else ""
    period = f" ({summary['period']})" if summary["period"] else ""
    top = " · ".join(f"{name} ₹{total:,.0f}" for name, total in summary["categories"][:3])
    sample = "\n".join(
        f"  • {r.get('date') or '—'}  {'+' if r.get('type') == 'income' else '-'}₹{r['amount']:,.2f}"
        f"  {r.get('merchant') or 'Unknown'} ({r.get('category') or 'Uncategorized'})"
        for r in rows[:PREVIEW_ROWS]
    )
    more = f"\n  …and {len(rows) - PREVIEW_ROWS} more" if len(rows) > PREVIEW_ROWS else ""
    return (
        f"📄 **Statement:** `{file_name}`{kind}\n"
        f"Found **{summary['count']} transactions**{period}: ₹{summary['total_debit']:,.2f} spent, "
        f"₹{summary['total_credit']:,.2f} received.\n"
        + (f"Top: {top}\n" if top else "")
        + f"\n{sample}{more}\n\n"
        f"Import them into your **{IMPORT_ACCOUNT}** pipe?\n"
        f"👉 Reply **'yes'** to import or **'no'** to cancel."
    )


def _row_day(row: dict[str, Any]) -> str:
    """ISO date of a parsed statement row (today when the statement gave none)."""
    raw = str(row.get("date") or "")[:10]
    return raw if len(raw) == 10 else datetime.utcnow().date().isoformat()


def _drop_already_imported(chat_id: str, rows: list[dict[str, Any]]) -> tuple[list, int]:
    """Skip rows already in the ledger (same type, amount, date and note), so uploading the same
    statement twice never double-counts. Compared in Python because notes are stored encrypted."""
    if not rows:
        return rows, 0
    days = sorted(_row_day(r) for r in rows)
    start = datetime.fromisoformat(days[0])
    end = datetime.fromisoformat(days[-1]) + timedelta(days=1)
    existing: Counter = Counter()
    db = SessionLocal()
    try:
        user_id = get_or_create_user(db, telegram_chat_id=chat_id).id
        found = db.execute(
            select(
                Transaction.transaction_type,
                Transaction.amount,
                Transaction.created_at,
                Transaction.description,
            )
            .where(Transaction.user_id == user_id)
            .where(Transaction.source == "pdf")
            .where(Transaction.created_at >= start)
            .where(Transaction.created_at < end)
        )
        existing.update((t, round(a, 2), c.date().isoformat(), d or "") for t, a, c, d in found)
    finally:
        db.close()
    fresh, duplicates = [], 0
    for row in rows:
        tx_type = "income" if row.get("type") == "income" else "expense"
        key = (tx_type, round(float(row["amount"]), 2), _row_day(row), row.get("description") or "")
        if existing[key] > 0:
            existing[key] -= 1
            duplicates += 1
        else:
            fresh.append(row)
    return fresh, duplicates


async def _finish_import(chat_id: str, decision: str) -> str:
    pending = _pending_imports.pop(chat_id, None)
    if pending is None:
        return "⌛ That import expired. Please upload the statement again."
    if decision != "confirmed":
        return "❌ **Import cancelled.** Nothing was added to your ledger."

    rows, duplicates = _drop_already_imported(chat_id, pending.rows)
    imported, failed = 0, 0
    for row in rows:
        try:
            if row.get("type") == "income":
                await tool_client.call_tool(
                    "log_income",
                    user_id=chat_id,
                    amount=row["amount"],
                    source_account=IMPORT_ACCOUNT,
                    category=row.get("category") or "Income",
                    description=row.get("description"),
                    source="pdf",
                    date=row.get("date"),
                )
            else:
                await tool_client.call_tool(
                    "log_expense",
                    user_id=chat_id,
                    amount=row["amount"],
                    category=row.get("category") or "Uncategorized",
                    merchant=row.get("merchant") if row.get("merchant") != "Unknown" else None,
                    account_name=IMPORT_ACCOUNT,
                    description=row.get("description"),
                    source="pdf",
                    date=row.get("date"),
                )
            imported += 1
        except Exception as e:
            failed += 1
            logger.warning("Import row failed for chat %s: %s", chat_id, e)

    text = f"✅ **Imported {imported} transactions** from `{pending.file_name}`."
    if duplicates:
        text += f"\n↩️ Skipped {duplicates} already in your ledger."
    if failed:
        text += f"\n⚠️ {failed} rows could not be imported."
    return text + "\nSee them in /stats or /history."


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------


class SimulateMessageRequest(BaseModel):
    chat_id: str
    text: str


@bot_router.post("/webhook")
async def telegram_webhook(request: Request):
    return await _webhook(request, None)


@bot_router.post("/webhook/{bot_id}")
async def telegram_webhook_for_bot(bot_id: str, request: Request):
    """Same as /webhook, for one of several bots (each bot's own address is WEBHOOK_URL/<bot id>)."""
    return await _webhook(request, bot_id)


async def _webhook(request: Request, bot_id: str | None):
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
        token = telegram.token_for(bot_id)
        if token is None and bot_id is not None:
            raise HTTPException(status_code=404, detail="Not found")
        header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(header, telegram.webhook_secret(token)):
            raise HTTPException(status_code=403, detail="invalid webhook secret")
        await telegram.feed_webhook_update(update, bot_id)
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
