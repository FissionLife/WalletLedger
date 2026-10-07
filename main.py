from contextlib import asynccontextmanager
import hmac

import uvicorn
from fastapi import FastAPI
from starlette.responses import JSONResponse

from app.bot.main import bot_router
from app.config import settings
from app.db import init_db
from app.services_ai.mcp_server import mcp


class MCPBearerAuth:
    """Require a configured bearer token before entering the MCP HTTP app."""

    def __init__(self, app, api_key: str):
        self.app = app
        self.api_key = api_key

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        authorization = headers.get(b"authorization", b"").decode("latin-1")
        expected = f"Bearer {self.api_key}"
        if not hmac.compare_digest(authorization, expected):
            response = JSONResponse({"detail": "Unauthorized MCP request"}, status_code=401)
            return await response(scope, receive, send)
        return await self.app(scope, receive, send)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables on startup
    init_db()
    if settings.mcp_enabled:
        async with mcp.session_manager.run():
            yield
    else:
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


if settings.mcp_enabled:
    if not settings.mcp_api_key:
        raise RuntimeError("MCP_ENABLED requires a non-empty MCP_API_KEY")
    # Mount last so existing API routes continue to take precedence.
    app.mount("/", MCPBearerAuth(mcp.streamable_http_app(), settings.mcp_api_key))


def start_dev():
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    start_dev()
