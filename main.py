import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.bot.main import bot_router, start_telegram, stop_telegram
from app.config import INSECURE_DEV_KEY, settings
from app.db import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if settings.secret_key == INSECURE_DEV_KEY:
        logger.warning(
            "SECRET_KEY is the insecure default: set a real one before storing user keys"
        )
    telegram_task = await start_telegram()
    try:
        yield
    finally:
        await stop_telegram(telegram_task)


app = FastAPI(
    title="WalletLedger API",
    version="0.1.0",
    description="AI-powered Telegram financial assistant & personal expense tracker",
    lifespan=lifespan,
)

app.include_router(bot_router)


@app.get("/")
def root():
    return {
        "project": "WalletLedger",
        "status": "online",
        "description": "Telegram AI expense tracker & ledger",
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


def start_dev():
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    start_dev()
