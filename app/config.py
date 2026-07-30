from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application configuration settings."""
    
    # Database configuration
    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/appdb"
    
    # Order processing configuration
    enable_strict_idempotency_check: bool = False
    transaction_settlement_window: float = 0.0
    enable_graceful_degradation: bool = False
    
    # Wallet operation configuration
    wallet_operation_lock_timeout: int = 0
    
    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
