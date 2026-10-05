# Role 1: Telegram Bot Core
# Assigned to: Krishna
import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.bot.agent import process_user_interaction
from app.db import get_db
from app.services.ledger import get_account_balances, get_or_create_user, get_spending_summary

logger = logging.getLogger(__name__)

bot_router = APIRouter(prefix="/bot", tags=["Telegram Bot"])


class TelegramUser(BaseModel):
    id: int
    first_name: str | None = None
    username: str | None = None


class TelegramChat(BaseModel):
    id: int
    type: str


class TelegramMessage(BaseModel):
    message_id: int
    from_: TelegramUser | None = Field(default=None, alias="from")
    chat: TelegramChat
    text: str | None = None
    document: dict[str, Any] | None = None


class TelegramUpdate(BaseModel):
    update_id: int
    message: TelegramMessage | None = None


class SimulateMessageRequest(BaseModel):
    chat_id: str
    text: str


@bot_router.post("/webhook")
async def telegram_webhook(update: TelegramUpdate, db: Session = Depends(get_db)):
    """
    Primary Telegram Webhook endpoint. Receives updates from Telegram servers.
    """
    if not update.message:
        return {"status": "ignored", "reason": "no message payload"}

    chat_id = str(update.message.chat.id)
    text = (update.message.text or "").strip()

    # Ensure user exists in WalletLedger database
    user = get_or_create_user(db, telegram_chat_id=chat_id)

    # 1. Handle Commands
    if text.startswith("/"):
        command = text.split()[0].lower()
        if command == "/start":
            reply = (
                "👋 **Welcome to WalletLedger!** 🪙\n\n"
                "Your personal finance assistant modeled on the **Tank & Pipes** architecture.\n\n"
                "📌 **Quick Commands:**\n"
                "• `/balance` - Check your liquid pipes (Cash, Bank, Cards)\n"
                "• `/report` - 30-day spending summary & breakdown\n"
                "• `/help` - Usage tips & commands\n\n"
                "💬 Or simply chat with me: *'Spent 450 on dinner via Bank'* or upload a PhonePe statement PDF!"
            )
            return {"status": "ok", "reply": reply}

        elif command == "/balance":
            balances = get_account_balances(db, user.id)
            accounts_txt = "\n".join(
                [
                    f"  • **{acc['name']}** ({acc['type']}): ₹{acc['balance']:,.2f}"
                    for acc in balances["accounts"]
                ]
            )
            reply = (
                f"🏦 **Your WalletLedger Tank:**\n"
                f"💰 **Total Net Worth:** ₹{balances['total_net_worth']:,.2f}\n\n"
                f"**Pipes In:**\n{accounts_txt}"
            )
            return {"status": "ok", "reply": reply}

        elif command == "/report":
            summary = get_spending_summary(db, user.id, days=30)
            cats_txt = (
                "\n".join(
                    [
                        f"  • {cat}: ₹{amt:,.2f}"
                        for cat, amt in summary["category_breakdown"].items()
                    ]
                )
                or "  No expenses recorded yet."
            )
            reply = (
                f"📊 **30-Day Expense Summary:**\n"
                f"💸 **Total Spent:** ₹{summary['total_expenses']:,.2f}\n"
                f"🧾 **Transactions:** {summary['transaction_count']}\n\n"
                f"**Category Breakdown:**\n{cats_txt}"
            )
            return {"status": "ok", "reply": reply}

        elif command == "/help":
            reply = (
                "ℹ️ **WalletLedger Help Guide:**\n\n"
                "• **Log Expense:** *'Paid 150 to Starbucks for coffee'* \n"
                "• **Transfer Funds:** *'Transferred 2000 from Bank to Cash'* \n"
                "• **Upload Statements:** Send any PhonePe/GPay PDF statement.\n"
                "• **Set API Key:** *'Set my Gemini key to AIza...'* \n"
            )
            return {"status": "ok", "reply": reply}

    # 2. Handle Document / PDF Upload
    if update.message.document:
        doc = update.message.document
        file_name = doc.get("file_name", "document.pdf")
        reply = (
            f"📄 **Received document:** `{file_name}`\n"
            f"Passing to Surya's (Role 5) Transaction Parser for ingestion..."
        )
        return {"status": "ok", "reply": reply}

    # 3. Handle Conversational Text via Gopal's LangGraph Agent (Role 2)
    response_text = await process_user_interaction(chat_id=chat_id, text=text)
    return {"status": "ok", "reply": response_text}


@bot_router.post("/simulate_chat")
async def simulate_chat(req: SimulateMessageRequest, db: Session = Depends(get_db)):
    """
    Developer convenience endpoint for the whole team:
    Simulates sending a Telegram message without needing Telegram BotFather tokens!
    """
    # Create fake update
    fake_update = TelegramUpdate(
        update_id=1,
        message=TelegramMessage(
            message_id=1,
            chat=TelegramChat(
                id=int(req.chat_id) if req.chat_id.isdigit() else 999999, type="private"
            ),
            text=req.text,
        ),
    )
    return await telegram_webhook(update=fake_update, db=db)
