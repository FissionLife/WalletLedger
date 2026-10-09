# Role 1: Telegram bot core.
# One message pipeline (`handle_incoming`) is shared by the webhook, long-polling and the
# /bot/simulate_chat dev endpoint. Replies are sent through the Telegram Bot API (aiogram).
import asyncio
import hmac
import logging
import re
from contextlib import suppress
from typing import Any

from aiogram import Bot
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.bot.agent import process_user_interaction
from app.config import is_chat_allowed, settings
from app.db import SessionLocal
from app.services import ledger
from app.services_ai import transaction_parser

logger = logging.getLogger(__name__)

bot_router = APIRouter(prefix="/bot", tags=["Telegram Bot"])

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
TELEGRAM_MAX_LEN = 4000

START_TEXT = (
    "👋 **Welcome to WalletLedger!** 🪙\n\n"
    "Your personal finance assistant modeled on the **Tank & Pipes** architecture.\n\n"
    "📌 **Quick Commands:**\n"
    "• /balance - Check your pipes (Cash, Bank, Cards)\n"
    "• /report - 30-day spending summary\n"
    "• /setkey <api key> - Add your Gemini/OpenAI/Groq/Claude key for AI answers\n"
    "• /help - Usage tips\n\n"
    "💬 Or just chat: *'Spent 450 on dinner via Bank'* or send a PhonePe statement PDF!"
)
HELP_TEXT = (
    "ℹ️ **WalletLedger Help Guide:**\n\n"
    "• **Log expense:** 'Paid 150 to Starbucks for coffee'\n"
    "• **Log income:** 'Received 50000 salary in Bank'\n"
    "• **Transfer:** 'Transferred 2000 from Bank to Cash'\n"
    "• **Advice:** 'How can I reduce expenses?' (try 'ruthless mode' / 'coach mode')\n"
    "• **Statements:** send a PhonePe/GPay PDF\n"
    "• **AI key:** /setkey <your key>, then delete that message"
)


class TelegramUser(BaseModel):
    id: int
    first_name: str | None = None
    username: str | None = None


class TelegramChat(BaseModel):
    id: int
    type: str


class TelegramMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message_id: int
    from_: TelegramUser | None = Field(default=None, alias="from")
    chat: TelegramChat
    text: str | None = None
    caption: str | None = None
    document: dict[str, Any] | None = None


class TelegramUpdate(BaseModel):
    update_id: int
    message: TelegramMessage | None = None


class SimulateMessageRequest(BaseModel):
    chat_id: str = Field(min_length=1, max_length=64, pattern=r"^[\w-]+$")
    text: str = Field(max_length=4000)


# ------------------------------ Telegram I/O -------------------------------

_bot: Bot | None = None


def get_bot() -> Bot | None:
    global _bot
    if _bot is None and settings.telegram_bot_token:
        _bot = Bot(token=settings.telegram_bot_token)
    return _bot


def to_plain(text: str) -> str:
    """Telegram has no `**bold**`; drop markdown markers so replies render cleanly as plain text."""
    return re.sub(r"[*`]", "", text).replace("\\", "")


async def send_reply(chat_id: str, text: str) -> None:
    bot = get_bot()
    if bot is None:
        return
    plain = to_plain(text)
    for i in range(0, len(plain), TELEGRAM_MAX_LEN):
        try:
            await bot.send_message(chat_id=int(chat_id), text=plain[i : i + TELEGRAM_MAX_LEN])
        except Exception:
            logger.exception("Failed to send Telegram message to %s", chat_id)
            return


# ----------------------------- message pipeline ----------------------------


async def _handle_document(chat_id: str, doc: dict[str, Any]) -> str:
    name = str(doc.get("file_name") or "document")
    if not name.lower().endswith((".pdf", ".txt")):
        return "📄 I can only read PDF statements or .txt SMS exports for now."
    if (doc.get("file_size") or 0) > MAX_DOCUMENT_BYTES:
        return "📄 That file is too large (max 10 MB)."
    bot = get_bot()
    file_id = doc.get("file_id")
    if bot is None or not file_id:
        return f"📄 Received `{name}`, but file download needs TELEGRAM_BOT_TOKEN to be configured."

    try:
        tg_file = await bot.get_file(file_id)
        buf = await bot.download_file(tg_file.file_path)
        data = buf.read() if buf else b""
        kind = "pdf" if name.lower().endswith(".pdf") else "txt"
        items = await transaction_parser.parse_statement_file(data, kind)
    except ValueError as exc:
        return f"⚠️ Could not read `{name}`: {exc}"
    except Exception:
        logger.exception("Document processing failed")
        return "⚠️ Something went wrong while reading that file."

    if not items:
        return f"📄 I read `{name}` but found no transactions I could recognise."

    def _import() -> dict[str, int]:
        with SessionLocal() as db:
            user = ledger.get_or_create_user(db, chat_id)
            return transaction_parser.import_parsed_transactions(db, user.id, items)

    stats = await asyncio.to_thread(_import)
    return (
        f"📥 **Imported from `{name}`**\n"
        f"✅ {stats['imported']} new  •  ♻️ {stats['skipped_duplicates']} duplicates skipped"
        f"  •  ⚠️ {stats['failed']} failed\n"
        "Use /report to see your updated summary."
    )


async def handle_incoming(chat_id: str, text: str, document: dict[str, Any] | None = None) -> str:
    """Single entry point: returns the reply text for one incoming Telegram message."""
    text = (text or "").strip()

    if not is_chat_allowed(chat_id):
        return "🔒 This bot is private."

    if document:
        return await _handle_document(chat_id, document)

    if text.startswith("/"):
        command, _, arg = text.partition(" ")
        command = command.split("@")[0].lower()
        arg = arg.strip()
        if command == "/start":
            await asyncio.to_thread(_ensure_user, chat_id)
            return START_TEXT
        if command == "/help":
            return HELP_TEXT
        if command == "/balance":
            return await process_user_interaction(chat_id, "show my balance")
        if command == "/report":
            return await process_user_interaction(chat_id, "give me my spending report")
        if command in ("/setkey", "/key"):
            if not arg:
                return "Usage: /setkey <your API key>"
            return await process_user_interaction(chat_id, f"my api key {arg}")
        return "Unknown command. Try /help."

    if not text:
        return HELP_TEXT
    return await process_user_interaction(chat_id, text)


def _ensure_user(chat_id: str) -> None:
    with SessionLocal() as db:
        ledger.get_or_create_user(db, chat_id)


# --------------------------------- routes ----------------------------------


@bot_router.post("/webhook")
async def telegram_webhook(
    update: TelegramUpdate,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    """Receives updates from Telegram; verifies the secret token when one is configured."""
    if settings.webhook_secret and not hmac.compare_digest(
        x_telegram_bot_api_secret_token or "", settings.webhook_secret
    ):
        raise HTTPException(status_code=403, detail="Invalid webhook secret")
    if not update.message:
        return {"status": "ignored", "reason": "no message payload"}

    msg = update.message
    chat_id = str(msg.chat.id)
    reply = await handle_incoming(chat_id, msg.text or msg.caption or "", msg.document)
    await send_reply(chat_id, reply)
    return {"status": "ok", "reply": reply}


@bot_router.post("/simulate_chat")
async def simulate_chat(req: SimulateMessageRequest):
    """Dev helper: run a message through the full pipeline without Telegram."""
    if not settings.enable_dev_endpoints:
        raise HTTPException(status_code=404, detail="Not found")
    reply = await handle_incoming(req.chat_id, req.text)
    return {"status": "ok", "reply": reply}


# ------------------------- polling / webhook lifecycle ---------------------


async def _poll_forever(bot: Bot) -> None:
    offset: int | None = None
    await bot.delete_webhook(drop_pending_updates=False)
    logger.info("Telegram long-polling started")
    while True:
        try:
            updates = await bot.get_updates(offset=offset, timeout=30, allowed_updates=["message"])
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("get_updates failed; retrying in 5s")
            await asyncio.sleep(5)
            continue
        for u in updates:
            offset = u.update_id + 1
            m = u.message
            if not m:
                continue
            chat_id = str(m.chat.id)
            try:
                reply = await handle_incoming(
                    chat_id,
                    m.text or m.caption or "",
                    m.document.model_dump() if m.document else None,
                )
                await send_reply(chat_id, reply)
            except Exception:
                logger.exception("Failed handling update %s", u.update_id)


async def start_telegram() -> asyncio.Task | None:
    """Starts polling, or registers the webhook. No-op without a bot token."""
    bot = get_bot()
    if bot is None:
        logger.info("TELEGRAM_BOT_TOKEN not set: Telegram disabled (use /bot/simulate_chat)")
        return None
    if settings.use_webhook:
        if not settings.webhook_url:
            logger.error("USE_WEBHOOK=true but WEBHOOK_URL is empty")
            return None
        if not settings.webhook_secret:
            logger.warning("WEBHOOK_SECRET is empty: webhook requests are not authenticated!")
        await bot.set_webhook(settings.webhook_url, secret_token=settings.webhook_secret or None)
        return None
    return asyncio.create_task(_poll_forever(bot))


async def stop_telegram(task: asyncio.Task | None) -> None:
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    global _bot
    if _bot is not None:
        await _bot.session.close()
        _bot = None
