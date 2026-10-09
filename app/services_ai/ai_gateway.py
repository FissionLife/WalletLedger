# Role 3: AI Gateway (provider agnostic)
# LLM routing via LiteLLM, per-user encrypted keys, round-robin rotation and fallback.
import asyncio
import itertools
import logging
import re
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import ApiKey
from app.services_ai.vault import decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)

PROVIDER_MODELS = {
    "gemini": "gemini/gemini-2.5-flash",
    "openai": "gpt-4o-mini",
    "groq": "groq/llama-3.3-70b-versatile",
    "claude": "anthropic/claude-haiku-4-5-20251001",
}
LLM_TIMEOUT_SECONDS = 45


class LLMUnavailableError(RuntimeError):
    """No usable API key, or every key/provider failed."""


@dataclass
class _Credential:
    provider: str
    api_key: str
    model: str


def detect_provider(api_key: str) -> str | None:
    k = api_key.strip()
    if k.startswith("AIza"):
        return "gemini"
    if k.startswith("sk-ant-"):
        return "claude"
    if k.startswith("gsk_"):
        return "groq"
    if k.startswith("sk-"):
        return "openai"
    return None


def save_api_key(db: Session, user_id: str, api_key: str, provider: str | None = None) -> dict:
    """Encrypts and stores a user's key. Re-activates an identical key instead of duplicating."""
    api_key = api_key.strip()
    provider = (provider or detect_provider(api_key) or "").lower()
    if provider not in PROVIDER_MODELS:
        raise ValueError(
            f"Could not determine provider. Supported: {', '.join(sorted(PROVIDER_MODELS))}"
        )
    if len(api_key) < 12 or re.search(r"\s", api_key):
        raise ValueError("That does not look like a valid API key")

    for row in db.scalars(select(ApiKey).where(ApiKey.user_id == user_id)):
        try:
            same = decrypt_secret(row.encrypted_key) == api_key
        except ValueError:
            continue
        if same:
            row.is_active = True
            db.commit()
            return {"status": "success", "provider": provider, "duplicate": True}

    db.add(ApiKey(user_id=user_id, provider=provider, encrypted_key=encrypt_secret(api_key)))
    db.commit()
    return {"status": "success", "provider": provider, "duplicate": False}


def _load_credentials(user_id: str, model_preference: str | None) -> list[_Credential]:
    creds: list[_Credential] = []
    with SessionLocal() as db:
        rows = db.scalars(
            select(ApiKey)
            .where(ApiKey.user_id == user_id, ApiKey.is_active.is_(True))
            .order_by(ApiKey.created_at, ApiKey.id)
        ).all()
        for row in rows:
            try:
                key = decrypt_secret(row.encrypted_key)
            except ValueError:
                logger.warning("Skipping undecryptable API key %s", row.id)
                continue
            model = model_preference or PROVIDER_MODELS.get(row.provider)
            if model:
                creds.append(_Credential(row.provider, key, model))
    if settings.default_llm_api_key and settings.default_llm_model:
        creds.append(
            _Credential("server", settings.default_llm_api_key, settings.default_llm_model)
        )
    return creds


_rotation: dict[str, itertools.count] = defaultdict(itertools.count)


def has_llm_access(user_id: str) -> bool:
    return bool(_load_credentials(user_id, None))


async def ask_llm(
    user_id: str,
    system_prompt: str,
    user_prompt: str,
    model_preference: str | None = None,
) -> str:
    """Runs a completion with the user's next round-robin key, falling back to the others."""
    creds = await asyncio.to_thread(_load_credentials, user_id, model_preference)
    if not creds:
        raise LLMUnavailableError("No API key configured")

    import litellm  # imported lazily: it is slow to import and not needed for non-LLM paths

    start = next(_rotation[user_id]) % len(creds)
    last_error: Exception | None = None
    for offset in range(len(creds)):
        cred = creds[(start + offset) % len(creds)]
        try:
            resp = await litellm.acompletion(
                model=cred.model,
                api_key=cred.api_key,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                timeout=LLM_TIMEOUT_SECONDS,
                num_retries=0,
            )
            content = resp.choices[0].message.content
            if content:
                return content.strip()
            last_error = RuntimeError("empty completion")
        except Exception as exc:  # rate limit, auth, quota, network: try the next key
            last_error = exc
            logger.warning(
                "LLM call failed via %s (%s): %s", cred.provider, cred.model, type(exc).__name__
            )
    raise LLMUnavailableError(f"All API keys failed: {type(last_error).__name__}") from last_error
