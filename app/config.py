from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_DEV_KEY = "walletledger-insecure-dev-key-change-in-prod"


class Settings(BaseSettings):
    """Application configuration settings for WalletLedger."""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    # Database (defaults to local SQLite for instant local dev without Docker)
    database_url: str = "sqlite:///./walletledger.db"

    # Telegram
    telegram_bot_token: str = ""
    use_webhook: bool = False  # True = Telegram pushes to /bot/webhook; False = long polling
    webhook_url: str = ""
    webhook_secret: str = ""  # sent by Telegram as X-Telegram-Bot-Api-Secret-Token

    # Used to encrypt user API keys at rest
    secret_key: str = INSECURE_DEV_KEY
    secret_key_old: str = ""  # comma-separated previous keys, for rotation

    # Optional server-side fallback LLM (used when a user has not supplied their own key)
    default_llm_model: str = ""  # e.g. "gemini/gemini-2.5-flash"
    default_llm_api_key: str = ""

    # Dev-only /bot/simulate_chat lets the caller act as ANY chat id: keep off outside local dev.
    enable_dev_endpoints: bool = False

    # Comma-separated Telegram chat ids allowed to use the bot. Empty = anyone (open bot).
    allowed_chat_ids: str = ""

    # Ask for confirmation before committing amounts at/above this value
    confirm_threshold: float = 50000.0


settings = Settings()


def is_chat_allowed(chat_id: str) -> bool:
    allowed = {c.strip() for c in settings.allowed_chat_ids.split(",") if c.strip()}
    return not allowed or str(chat_id) in allowed
