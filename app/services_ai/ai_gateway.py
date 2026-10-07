"""Role 3: AI Gateway (Provider Agnostic)
Handles LLM routing, round-robin user key vault, and LiteLLM abstraction.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from typing import Any

from cryptography.fernet import Fernet
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import ApiKey, User

logger = logging.getLogger(__name__)

# Fallback provider default models
DEFAULT_MODELS = {
    "gemini": "gemini/gemini-1.5-flash",
    "openai": "gpt-4o-mini",
    "groq": "groq/llama-3.3-70b-versatile",
    "claude": "claude-3-5-sonnet-20241022",
}


def _decrypt_key(encrypted_text: str) -> str:
    secret = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(secret)).decrypt(encrypted_text.encode()).decode()


def get_user_api_keys(user_id: str) -> list[tuple[str, str]]:
    """Retrieve and decrypt active API keys for a user from DB or environment."""
    keys: list[tuple[str, str]] = []

    # 1. Query database
    db = SessionLocal()
    try:
        user = db.get(User, str(user_id))
        if user is None:
            user = db.scalar(select(User).where(User.telegram_chat_id == str(user_id)))

        if user:
            stmt = (
                select(ApiKey)
                .where(ApiKey.user_id == user.id, ApiKey.is_active.is_(True))
                .order_by(ApiKey.created_at.desc())
            )
            records = list(db.scalars(stmt))
            for rec in records:
                try:
                    decrypted = _decrypt_key(rec.encrypted_key)
                    keys.append((rec.provider.lower(), decrypted))
                except Exception as e:
                    logger.warning(f"Could not decrypt key {rec.id}: {e}")
    finally:
        db.close()

    # 2. Check environment variables if no DB keys found
    if not keys:
        if os.environ.get("GEMINI_API_KEY"):
            keys.append(("gemini", os.environ["GEMINI_API_KEY"]))
        if os.environ.get("OPENAI_API_KEY"):
            keys.append(("openai", os.environ["OPENAI_API_KEY"]))
        if os.environ.get("GROQ_API_KEY"):
            keys.append(("groq", os.environ["GROQ_API_KEY"]))
        if os.environ.get("ANTHROPIC_API_KEY"):
            keys.append(("claude", os.environ["ANTHROPIC_API_KEY"]))

    return keys


class AIGateway:
    """LiteLLM Provider-Agnostic Gateway with Round-Robin Key Vault."""

    def __init__(self) -> None:
        self._key_indexes: dict[str, int] = {}

    def _get_next_key(self, user_id: str) -> tuple[str, str] | None:
        keys = get_user_api_keys(user_id)
        if not keys:
            return None
        idx = self._key_indexes.get(user_id, 0) % len(keys)
        self._key_indexes[user_id] = idx + 1
        return keys[idx]

    async def generate_response(
        self,
        user_id: str,
        system_prompt: str,
        user_prompt: str,
        tools: list[dict[str, Any]] | None = None,
        model_preference: str | None = None,
        messages_history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """
        Executes an LLM call via LiteLLM with round-robin key rotation and tool calling.
        """
        import litellm

        # Configure LiteLLM
        litellm.telemetry = False
        litellm.suppress_debug_info = True
        litellm.num_retries = 1

        key_info = self._get_next_key(user_id)
        provider = key_info[0] if key_info else "gemini"
        api_key = key_info[1] if key_info else None

        model = model_preference or DEFAULT_MODELS.get(provider, "gemini/gemini-1.5-flash")

        messages = [{"role": "system", "content": system_prompt}]
        if messages_history:
            messages.extend(messages_history)
        messages.append({"role": "user", "content": user_prompt})

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.1,
            "timeout": 10,
        }

        if api_key:
            kwargs["api_key"] = api_key

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = await litellm.acompletion(**kwargs)
        return response


ai_gateway = AIGateway()


async def ask_llm(
    user_id: str,
    system_prompt: str,
    user_prompt: str,
    model_preference: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    messages_history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """
    Contract 2: Passes user prompt and tools to AI Gateway / LiteLLM.
    """
    return await ai_gateway.generate_response(
        user_id=user_id,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        tools=tools,
        model_preference=model_preference,
        messages_history=messages_history,
    )
