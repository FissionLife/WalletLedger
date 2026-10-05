from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.bot.main import bot_router
from app.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables on startup
    init_db()
    yield


app = FastAPI(
    title="WalletLedger API",
    version="0.1.0",
    description="AI-powered Telegram financial assistant & personal expense tracker",
    lifespan=lifespan,
)

# Include Telegram Bot Router
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
