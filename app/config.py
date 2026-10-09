from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_DEV_KEY = "walletledger-insecure-dev-key-change-in-prod"


class Settings(BaseSettings):
    """Application configuration for WalletLedger.

    Values come from real environment variables first, then the ``.env`` file.
    See ``.env.example`` for every setting with a short explanation.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # unknown lines in .env must not stop the app
    )

    # Database (defaults to local SQLite for instant local dev without Docker)
    database_url: str = "sqlite:///./walletledger.db"

    # Telegram bot (token from BotFather). Empty token = bot disabled, /bot/simulate_chat still works.
    telegram_bot_token: str = ""
    # False = long polling (local dev). True = webhook (production, needs a public HTTPS URL).
    use_webhook: bool = False
    # Full public URL Telegram should call, e.g. https://example.com/bot/webhook
    webhook_url: str = ""
    # Secret Telegram echoes back on every webhook call. Empty = derived from the bot token.
    telegram_webhook_secret: str = ""
    # Largest statement upload accepted from chat, in megabytes.
    max_upload_mb: int = 10

    # Only these Telegram chat ids may use the bot (comma-separated). Empty = anyone.
    allowed_chat_ids: str = ""
    # /bot/simulate_chat and the token-less /bot/webhook let the caller act as ANY chat id.
    # Unset = enabled only while no bot token is configured; true/false overrides.
    enable_dev_endpoints: bool | None = None

    # Security key for encrypting user API keys
    secret_key: str = INSECURE_DEV_KEY

    # Optional server-side AI keys, used only when a user has not added their own key.
    # *_API_KEYS accept several keys separated by commas (round-robin rotation).
    gemini_api_keys: str = ""
    openai_api_keys: str = ""
    anthropic_api_keys: str = ""
    groq_api_keys: str = ""
    gemini_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    groq_api_key: str = ""

    # Optional model overrides (LiteLLM names, e.g. gemini/gemini-flash-latest)
    ai_model_gemini: str = ""
    ai_model_openai: str = ""
    ai_model_anthropic: str = ""
    ai_model_groq: str = ""
    ai_model_ollama: str = ""
    ollama_api_base: str = ""


settings = Settings()


def is_chat_allowed(chat_id: str) -> bool:
    allowed = {c.strip() for c in settings.allowed_chat_ids.split(",") if c.strip()}
    return not allowed or str(chat_id) in allowed


def dev_endpoints_enabled() -> bool:
    if settings.enable_dev_endpoints is not None:
        return settings.enable_dev_endpoints
    return not settings.telegram_bot_token
