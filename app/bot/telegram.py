# Role 1: Telegram Bot Core
# Assigned to: Krishna
"""Real Telegram connection via aiogram (polling for local dev, webhook for production).

Lifecycle (called from main.py's FastAPI lifespan):
    no TELEGRAM_BOT_TOKEN        -> bot off; /bot/simulate_chat still works
    USE_WEBHOOK=false (default)  -> long polling in a background task
    USE_WEBHOOK=true             -> register WEBHOOK_URL with Telegram; /bot/webhook feeds aiogram

All handlers delegate to app.bot.main (handle_text / handle_document) so Telegram, the dev
webhook and /bot/simulate_chat share one code path.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import logging
import re
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatAction, ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from app.bot.main import handle_document, handle_text, should_delete_message, upload_type
from app.config import settings

logger = logging.getLogger(__name__)

TELEGRAM_LIMIT = 4096
CHUNK_SIZE = 4000  # leave room so Markdown fallbacks never exceed the limit


_bot: Bot | None = None
_dispatcher: Dispatcher | None = None
_polling_task: asyncio.Task | None = None
_mode: str = "off"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def split_message(text: str, limit: int = CHUNK_SIZE) -> list[str]:
    """Split a long reply into Telegram-sized chunks, preferring paragraph/line breaks."""
    text = text or ""
    chunks: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n\n", 0, limit)
        if cut <= 0:
            cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = text.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip("\n ")
    if text.strip() or not chunks:
        chunks.append(text)
    return chunks


def to_telegram_markdown(text: str) -> str:
    """Convert **bold** (used across the codebase and by LLMs) to Telegram's legacy *bold*."""
    return re.sub(r"\*\*(.+?)\*\*", r"*\1*", text or "", flags=re.S)


async def send_reply(message: Message, text: str) -> None:
    """Send a (possibly long) Markdown reply; resend as plain text if Telegram rejects it."""
    for chunk in split_message(text):
        try:
            await message.answer(to_telegram_markdown(chunk), parse_mode=ParseMode.MARKDOWN)
        except TelegramBadRequest as e:
            logger.info("Markdown rejected by Telegram (%s); sending plain text.", e)
            plain = chunk.replace("**", "").replace("`", "")
            await message.answer(plain, parse_mode=None)


def webhook_secret() -> str:
    """Secret Telegram must echo in X-Telegram-Bot-Api-Secret-Token on every webhook call."""
    if settings.telegram_webhook_secret:
        return settings.telegram_webhook_secret
    return hashlib.sha256(f"walletledger:{settings.telegram_bot_token}".encode()).hexdigest()[:48]


def webhook_active() -> bool:
    return _mode == "webhook" and _bot is not None and _dispatcher is not None


async def feed_webhook_update(update: dict[str, Any]) -> None:
    if not webhook_active():
        raise RuntimeError("Telegram webhook mode is not running")
    await _dispatcher.feed_webhook_update(_bot, update)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def on_document(message: Message, bot: Bot) -> None:
    doc = message.document
    file_name = doc.file_name or "statement.pdf"
    if upload_type(file_name) is None:
        await send_reply(message, "📄 Please upload a PDF statement (or a .txt file of bank SMS).")
        return
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if doc.file_size and doc.file_size > max_bytes:
        await send_reply(message, f"📄 That file is too large (max {settings.max_upload_mb} MB).")
        return

    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    buffer = io.BytesIO()
    await bot.download(doc, destination=buffer)
    reply = await handle_document(str(message.chat.id), file_name, buffer.getvalue())
    await send_reply(message, reply)


async def on_text(message: Message, bot: Bot) -> None:
    text = message.text or ""
    if should_delete_message(text):
        # Remove the user's message so the API key does not stay in the chat history.
        with contextlib.suppress(Exception):
            await message.delete()
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    reply = await handle_text(str(message.chat.id), text)
    await send_reply(message, reply)


async def on_other(message: Message) -> None:
    await send_reply(message, "I can read text messages and PDF statements. Try /help.")


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def build_router() -> Router:
    """A fresh router per start(): aiogram routers can only be attached to one Dispatcher."""
    router = Router(name="walletledger")
    router.message.register(on_document, F.document)
    router.message.register(on_text, F.text)
    router.message.register(on_other)
    return router


async def start() -> str:
    """Start the bot according to settings. Returns the mode: off, polling or webhook."""
    global _bot, _dispatcher, _polling_task, _mode
    token = settings.telegram_bot_token.strip()
    if not token:
        logger.info("TELEGRAM_BOT_TOKEN not set; Telegram bot disabled (/bot/simulate_chat works).")
        _mode = "off"
        return _mode

    _bot = Bot(token=token)
    _dispatcher = Dispatcher()
    _dispatcher.include_router(build_router())
    me = await _bot.get_me()

    if settings.use_webhook:
        if not settings.webhook_url:
            raise RuntimeError(
                "USE_WEBHOOK=true requires WEBHOOK_URL (e.g. https://host/bot/webhook)"
            )
        await _bot.set_webhook(
            settings.webhook_url,
            secret_token=webhook_secret(),
            allowed_updates=_dispatcher.resolve_used_update_types(),
            drop_pending_updates=False,
        )
        _mode = "webhook"
        logger.info("Telegram bot @%s: webhook registered at %s", me.username, settings.webhook_url)
    else:
        # A webhook left over from production would block polling, so clear it first.
        await _bot.delete_webhook(drop_pending_updates=False)
        _polling_task = asyncio.create_task(
            _dispatcher.start_polling(_bot, handle_signals=False, close_bot_session=False),
            name="telegram-polling",
        )
        _mode = "polling"
        logger.info("Telegram bot @%s: polling started", me.username)
    return _mode


async def stop() -> None:
    """Stop polling and close the HTTP session. The webhook stays registered on purpose."""
    global _bot, _dispatcher, _polling_task, _mode
    if _dispatcher is not None and _polling_task is not None:
        with contextlib.suppress(Exception):
            await _dispatcher.stop_polling()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await asyncio.wait_for(_polling_task, timeout=10)
    if _bot is not None:
        await _bot.session.close()
    _bot, _dispatcher, _polling_task, _mode = None, None, None, "off"
