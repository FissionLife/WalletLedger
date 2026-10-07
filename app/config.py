from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration settings for WalletLedger."""

    # Database configuration (defaults to local SQLite for instant local dev without Docker)
    database_url: str = "sqlite:///./walletledger.db"

    # Telegram Bot Token (from BotFather)
    telegram_bot_token: str = ""

    # Webhook vs Polling mode (True = webhook, False = polling for local dev)
    use_webhook: bool = False
    webhook_url: str = ""

    # Security key for encrypting user API keys
    secret_key: str = "walletledger-insecure-dev-key-change-in-prod"

    # Optional Streamable HTTP MCP endpoint. Requires a bearer token when enabled.
    mcp_enabled: bool = False
    mcp_api_key: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
