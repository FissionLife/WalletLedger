"""Role 3: AI Gateway (provider agnostic).

One entry point for every LLM call in WalletLedger:

    reply = await ask_llm(user_id, system_prompt, user_prompt, model_preference=None)

What it does:

* **Provider-agnostic routing** via LiteLLM: Gemini, OpenAI, Claude (Anthropic), Groq, Ollama.
* **Key vault**: users' API keys are Fernet-encrypted in the ``api_keys`` table. The cipher is
  derived from ``settings.secret_key`` exactly like ``mcp_server.save_user_api_key``, so keys
  stored by either module are interchangeable.
* **Round-robin rotation**: consecutive requests for a user start from the next key, spreading
  load across free-tier keys (RPM / TPM limits).
* **Automatic fallback**: rate-limit (429), quota, auth and provider-outage errors move on to the
  next key / provider immediately. Rate-limited keys sit out a short cooldown.
* **Tool Calling Support**: seamlessly accepts standard OpenAI/Gemini function calling schemas.

Key sources, in order: the user's own active keys, then optional server keys from environment
variables (``GEMINI_API_KEYS``, ``OPENAI_API_KEYS``, ``ANTHROPIC_API_KEYS``, ``GROQ_API_KEYS``;
comma-separated). Ollama needs no key (``OLLAMA_API_BASE``, default http://localhost:11434).
Default models can be overridden with ``AI_MODEL_<PROVIDER>``, e.g. ``AI_MODEL_GEMINI``.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import litellm
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ApiKey, User

logger = logging.getLogger(__name__)

litellm.telemetry = False
litellm.suppress_debug_info = True

# --------------------------------------------------------------------------------------
# Providers & models
# --------------------------------------------------------------------------------------

DEFAULT_PROVIDER = "gemini"

# provider -> (default LiteLLM model, env var holding comma-separated server keys)
PROVIDERS: dict[str, tuple[str, str | None]] = {
    # "gemini-flash-latest" always points at Google's current Flash model; pinned versions
    # such as gemini-1.5-flash / gemini-2.5-flash are retired for new API keys (404).
    "gemini": ("gemini/gemini-flash-latest", "GEMINI_API_KEYS"),
    "openai": ("openai/gpt-4o-mini", "OPENAI_API_KEYS"),
    "anthropic": ("anthropic/claude-3-5-sonnet-20241022", "ANTHROPIC_API_KEYS"),
    "groq": ("groq/llama-3.3-70b-versatile", "GROQ_API_KEYS"),
    "ollama": ("ollama/llama3.1", None),
}

# provider -> standard single-key env var (used after the *_API_KEYS list for that provider)
SINGLE_KEY_ENV: dict[str, str] = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "groq": "GROQ_API_KEY",
}

PROVIDER_ALIASES = {
    "google": "gemini",
    "gemini": "gemini",
    "openai": "openai",
    "gpt": "openai",
    "chatgpt": "openai",
    "anthropic": "anthropic",
    "claude": "anthropic",
    "groq": "groq",
    "ollama": "ollama",
}

# Recognisable key formats, used when a user pastes keys into chat.
KEY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("anthropic", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("groq", re.compile(r"gsk_[A-Za-z0-9]{20,}")),
    ("openai", re.compile(r"sk-(?!ant-)[A-Za-z0-9_\-]{20,}")),
    ("gemini", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("gemini", re.compile(r"AQ\.[0-9A-Za-z_\-]{30,}")),
]

RATE_LIMIT_COOLDOWN_SECONDS = 60
AUTH_FAILURE_COOLDOWN_SECONDS = 15 * 60
DEFAULT_TIMEOUT_SECONDS = 15


def normalize_provider(provider: str) -> str:
    key = (provider or "").strip().lower()
    if key not in PROVIDER_ALIASES:
        raise ValueError(f"Unsupported provider {provider!r}. Supported: {', '.join(PROVIDERS)}")
    return PROVIDER_ALIASES[key]


def _env(name: str) -> str:
    """Read a setting: real environment variable first, then ``.env`` via app.config.

    pydantic-settings loads ``.env`` into ``settings`` but not into ``os.environ``, so
    reading only ``os.getenv`` would silently ignore keys placed in ``.env``.
    """
    value = os.getenv(name)
    if value is not None:
        return value
    return str(getattr(settings, name.lower(), "") or "")


def default_model(provider: str) -> str:
    provider = normalize_provider(provider)
    return (_env(f"AI_MODEL_{provider.upper()}") or None) or PROVIDERS[provider][0]


def resolve_model(model_preference: str | None) -> tuple[str, str]:
    """Turn a preference ("groq", "claude", "gemini/gemini-2.5-pro", None) into (provider, model)."""
    if not model_preference:
        return DEFAULT_PROVIDER, default_model(DEFAULT_PROVIDER)
    pref = model_preference.strip()
    if "/" in pref:
        prefix = pref.split("/", 1)[0].lower()
        if prefix in PROVIDER_ALIASES:
            return PROVIDER_ALIASES[prefix], pref
        raise ValueError(f"Unsupported model {model_preference!r}")
    lowered = pref.lower()
    if lowered in PROVIDER_ALIASES:
        provider = PROVIDER_ALIASES[lowered]
        return provider, default_model(provider)
    for prefix, provider in (
        ("gemini", "gemini"),
        ("gpt", "openai"),
        ("o1", "openai"),
        ("o3", "openai"),
        ("o4", "openai"),
        ("claude", "anthropic"),
    ):
        if lowered.startswith(prefix):
            return provider, f"{provider}/{pref}"
    raise ValueError(
        f"Cannot infer a provider for model {model_preference!r}; use 'provider/model'"
    )


def detect_provider(api_key: str) -> str | None:
    """Guess the provider from a key's format (None if unknown)."""
    for provider, pattern in KEY_PATTERNS:
        if pattern.fullmatch(api_key.strip()):
            return provider
    return None


def extract_api_keys(text: str) -> list[tuple[str, str]]:
    """Find every recognisable API key in a chat message -> [(provider, key), ...]."""
    found: list[tuple[int, str, str]] = []
    taken: list[tuple[int, int]] = []
    for provider, pattern in KEY_PATTERNS:
        for match in pattern.finditer(text or ""):
            span = match.span()
            if any(span[0] < end and start < span[1] for start, end in taken):
                continue
            taken.append(span)
            found.append((span[0], provider, match.group(0)))
    return [(provider, key) for _, provider, key in sorted(found)]


def mask_key(api_key: str) -> str:
    key = api_key.strip()
    return f"{key[:4]}…{key[-4:]}" if len(key) > 10 else "****"


# --------------------------------------------------------------------------------------
# Encryption
# --------------------------------------------------------------------------------------


def _fernet() -> Fernet:
    # Same derivation as mcp_server.save_user_api_key -> keys are interchangeable.
    secret = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(secret))


def encrypt_api_key(api_key: str) -> str:
    return _fernet().encrypt(api_key.strip().encode("utf-8")).decode("utf-8")


def decrypt_api_key(encrypted_key: str) -> str:
    return _fernet().decrypt(encrypted_key.encode("utf-8")).decode("utf-8")


# --------------------------------------------------------------------------------------
# Key vault (api_keys table)
# --------------------------------------------------------------------------------------


def _session() -> Session:
    from app.db import SessionLocal

    return SessionLocal()


def _find_user(db: Session, user_id: str) -> User | None:
    """Accept either the internal user UUID or the Telegram chat id."""
    user = db.get(User, str(user_id))
    if user is None:
        user = db.scalar(select(User).where(User.telegram_chat_id == str(user_id)))
    return user


def _find_or_create_user(db: Session, user_id: str) -> User:
    user = _find_user(db, user_id)
    if user is None:
        from app.services.ledger import get_or_create_user

        user = get_or_create_user(db, str(user_id))
    return user


def add_api_key(user_id: str, provider: str, api_key: str) -> dict[str, Any]:
    """Encrypt and store one key. Re-adding an existing key just re-activates it."""
    provider = normalize_provider(provider)
    api_key = (api_key or "").strip()
    if not api_key:
        raise ValueError("api_key is required")
    db = _session()
    try:
        user = _find_or_create_user(db, user_id)
        for record in db.scalars(
            select(ApiKey).where(ApiKey.user_id == user.id, ApiKey.provider == provider)
        ):
            try:
                same = decrypt_api_key(record.encrypted_key) == api_key
            except InvalidToken:
                continue
            if same:
                record.is_active = True
                db.commit()
                return {
                    "status": "exists",
                    "key_id": record.id,
                    "provider": provider,
                    "masked_key": mask_key(api_key),
                }
        record = ApiKey(user_id=user.id, provider=provider, encrypted_key=encrypt_api_key(api_key))
        db.add(record)
        db.commit()
        return {
            "status": "added",
            "key_id": record.id,
            "provider": provider,
            "masked_key": mask_key(api_key),
        }
    finally:
        db.close()


def add_api_keys_from_text(
    user_id: str, text: str, default_provider: str | None = None
) -> list[dict[str, Any]]:
    """Store every key found in a chat message (users may paste several Gemini keys at once)."""
    keys = extract_api_keys(text)
    if not keys and default_provider:
        tokens = [t for t in re.split(r"[\s,;]+", text or "") if len(t) >= 20]
        keys = [(normalize_provider(default_provider), token) for token in tokens]
    return [add_api_key(user_id, provider, key) for provider, key in keys]


def list_api_keys(user_id: str) -> list[dict[str, Any]]:
    """Masked view of a user's keys - never returns the plain key."""
    db = _session()
    try:
        user = _find_user(db, user_id)
        if user is None:
            return []
        rows = db.scalars(
            select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at, ApiKey.id)
        )
        result = []
        for record in rows:
            try:
                masked = mask_key(decrypt_api_key(record.encrypted_key))
            except InvalidToken:
                masked = "<undecryptable>"
            result.append(
                {
                    "key_id": record.id,
                    "provider": record.provider,
                    "masked_key": masked,
                    "is_active": record.is_active,
                }
            )
        return result
    finally:
        db.close()


def _set_key_active(user_id: str, key_id: str, active: bool) -> bool:
    db = _session()
    try:
        user = _find_user(db, user_id)
        record = db.get(ApiKey, key_id)
        if user is None or record is None or record.user_id != user.id:
            return False
        record.is_active = active
        db.commit()
        return True
    finally:
        db.close()


def deactivate_api_key(user_id: str, key_id: str) -> bool:
    return _set_key_active(user_id, key_id, False)


def activate_api_key(user_id: str, key_id: str) -> bool:
    return _set_key_active(user_id, key_id, True)


def delete_api_key(user_id: str, key_id: str) -> bool:
    db = _session()
    try:
        user = _find_user(db, user_id)
        record = db.get(ApiKey, key_id)
        if user is None or record is None or record.user_id != user.id:
            return False
        db.delete(record)
        db.commit()
        return True
    finally:
        db.close()


# --------------------------------------------------------------------------------------
# Rotation state
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class KeyCandidate:
    provider: str
    api_key: str = field(repr=False)
    source: str  # "user" or "server"
    key_id: str | None = None

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.api_key.encode("utf-8")).hexdigest()[:16]


class _RotationState:
    """Thread-safe round-robin cursors and per-key cooldowns (in memory, per process)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cursors: dict[str, int] = {}
        self._cooldown_until: dict[str, float] = {}

    def next_offset(self, pool: str, size: int) -> int:
        if size <= 0:
            return 0
        with self._lock:
            offset = self._cursors.get(pool, 0) % size
            self._cursors[pool] = offset + 1
            return offset

    def cool_down(self, fingerprint: str, seconds: float) -> None:
        with self._lock:
            self._cooldown_until[fingerprint] = time.monotonic() + seconds

    def is_cooling(self, fingerprint: str) -> bool:
        with self._lock:
            until = self._cooldown_until.get(fingerprint)
            if until is None:
                return False
            if until <= time.monotonic():
                del self._cooldown_until[fingerprint]
                return False
            return True

    def reset(self) -> None:
        with self._lock:
            self._cursors.clear()
            self._cooldown_until.clear()


_rotation = _RotationState()


def reset_rotation_state() -> None:
    _rotation.reset()


def _rotate(items: list[KeyCandidate], pool: str) -> list[KeyCandidate]:
    if not items:
        return items
    offset = _rotation.next_offset(pool, len(items))
    return items[offset:] + items[:offset]


def _server_keys(provider: str) -> list[str]:
    env_name = PROVIDERS[provider][1]
    if not env_name:
        return []
    raw = _env(env_name)
    return [k.strip() for k in re.split(r"[\s,;]+", raw) if k.strip()]


def _single_env_key(provider: str) -> str | None:
    """Standard single-key variable (GEMINI_API_KEY, OPENAI_API_KEY, ...), if set."""
    env_name = SINGLE_KEY_ENV.get(provider)
    value = _env(env_name).strip() if env_name else ""
    return value or None


def _load_user_keys(user_id: str) -> list[KeyCandidate]:
    db = _session()
    try:
        user = _find_user(db, user_id)
        if user is None:
            return []
        rows = db.scalars(
            select(ApiKey)
            .where(ApiKey.user_id == user.id, ApiKey.is_active.is_(True))
            .order_by(ApiKey.created_at, ApiKey.id)
        )
        keys = []
        for record in rows:
            try:
                provider = normalize_provider(record.provider)
                keys.append(
                    KeyCandidate(provider, decrypt_api_key(record.encrypted_key), "user", record.id)
                )
            except InvalidToken, ValueError:
                logger.warning("Skipping unusable api key %s", record.id)
        return keys
    finally:
        db.close()


def get_user_api_keys(user_id: str) -> list[tuple[str, str]]:
    """Convenience helper: returns active (provider, plain_key) pairs."""
    candidates = build_candidates(user_id)
    return [(c.provider, c.api_key) for c in candidates if c.api_key]


def build_candidates(
    user_id: str, preferred_provider: str = DEFAULT_PROVIDER
) -> list[KeyCandidate]:
    """Ordered list of keys to try for one request (round-robin rotated, cooling keys last)."""
    user_keys = _load_user_keys(user_id)
    candidates: list[KeyCandidate] = []
    if user_keys:
        by_provider: dict[str, list[KeyCandidate]] = {}
        for key in user_keys:
            by_provider.setdefault(key.provider, []).append(key)
        order = [preferred_provider] + [p for p in by_provider if p != preferred_provider]
        for provider in order:
            candidates += _rotate(by_provider.get(provider, []), f"user:{user_id}:{provider}")
    else:
        # Server keys, grouped by provider so the preferred provider is always tried first.
        # Within a provider: the rotated GEMINI_API_KEYS-style list, then the single
        # GEMINI_API_KEY-style variable (skipped if it is already in the list).
        order = [preferred_provider] + [p for p in PROVIDERS if p != preferred_provider]
        for provider in order:
            listed = _server_keys(provider)
            server = [KeyCandidate(provider, k, "server") for k in listed]
            candidates += _rotate(server, f"server:{provider}")
            single = _single_env_key(provider)
            if single and single not in listed:
                candidates.append(KeyCandidate(provider, single, "env"))

    ready = [c for c in candidates if not _rotation.is_cooling(c.fingerprint)]
    cooling = [c for c in candidates if _rotation.is_cooling(c.fingerprint)]
    return ready + cooling


# --------------------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------------------


class AIGatewayError(RuntimeError):
    """Base error raised by the gateway."""


class NoAPIKeyError(AIGatewayError):
    """The user has no usable key and no server key is configured."""


class AllKeysExhaustedError(AIGatewayError):
    """Every candidate key/provider failed with a retryable error."""

    def __init__(self, attempts: list[dict[str, str]]):
        self.attempts = attempts
        summary = "; ".join(f"{a['provider']} {a['key']}: {a['error']}" for a in attempts)
        super().__init__(f"All {len(attempts)} key(s) failed. {summary}")


_RATE_LIMIT_ERRORS = (litellm.RateLimitError,)
_AUTH_ERRORS = (litellm.AuthenticationError, litellm.PermissionDeniedError)
_TRANSIENT_ERRORS = (
    litellm.ServiceUnavailableError,
    litellm.InternalServerError,
    litellm.APIConnectionError,
    litellm.Timeout,
    litellm.BadGatewayError,
    litellm.NotFoundError,
)
_KEY_HINTS = (
    "api key",
    "api_key",
    "apikey",
    "quota",
    "credential",
    "unauthorized",
    "permission",
    "access denied",
    "no access",
    "forbidden",
    "model not found",
    "not found or no access",
)


def _classify(exc: Exception) -> str | None:
    """'rate_limit' | 'auth' | 'transient' -> try next key; None -> not a key problem, raise."""
    if isinstance(exc, _RATE_LIMIT_ERRORS):
        return "rate_limit"
    if isinstance(exc, _AUTH_ERRORS):
        return "auth"
    if isinstance(exc, _TRANSIENT_ERRORS):
        return "transient"
    if isinstance(exc, (litellm.BadRequestError, litellm.APIError)):
        message = str(exc).lower()
        if "429" in message or "resource_exhausted" in message or "rate limit" in message:
            return "rate_limit"
        if any(hint in message for hint in _KEY_HINTS):
            return "auth"
    return None


def _short_error(exc: Exception) -> str:
    text = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
    return f"{type(exc).__name__}: {text[:160]}"


# --------------------------------------------------------------------------------------
# Completion
# --------------------------------------------------------------------------------------


def _model_for(candidate: KeyCandidate, provider: str, model: str) -> str:
    return model if candidate.provider == provider else default_model(candidate.provider)


def _extract_text(response: Any) -> str:
    try:
        content = response.choices[0].message.content
    except AttributeError, IndexError, KeyError, TypeError:
        content = response["choices"][0]["message"]["content"]
    return (content or "").strip()


async def complete(
    user_id: str,
    messages: list[dict[str, Any]],
    model_preference: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    **kwargs: Any,
) -> Any:
    """Run a chat completion with rotation + fallback.
    Returns plain text string if no tools, or full LiteLLM response object if tools are used.
    """
    provider, model = resolve_model(model_preference)
    candidates = await asyncio.to_thread(build_candidates, user_id, provider)
    if provider == "ollama" or not candidates:
        if provider == "ollama":
            candidates = [KeyCandidate("ollama", "", "local")]
        else:
            raise NoAPIKeyError(
                "No AI API key found. Send your key in chat (e.g. 'my Gemini key is AIza...') "
                "or configure GEMINI_API_KEYS on the server."
            )
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT_SECONDS)

    attempts: list[dict[str, str]] = []
    for candidate in candidates:
        call_model = _model_for(candidate, provider, model)
        call_kwargs = dict(kwargs)
        if candidate.provider == "ollama":
            call_kwargs.setdefault("api_base", _env("OLLAMA_API_BASE") or "http://localhost:11434")
        else:
            call_kwargs["api_key"] = candidate.api_key

        if tools:
            call_kwargs["tools"] = tools
            call_kwargs["tool_choice"] = "auto"

        try:
            response = await litellm.acompletion(
                model=call_model, messages=messages, num_retries=0, **call_kwargs
            )
        except Exception as exc:
            kind = _classify(exc)
            if kind is None:
                raise
            masked = mask_key(candidate.api_key) if candidate.api_key else "local"
            logger.warning(
                "AI gateway: %s key %s failed (%s), trying next", candidate.provider, masked, kind
            )
            attempts.append(
                {
                    "provider": candidate.provider,
                    "key": masked,
                    "model": call_model,
                    "error": _short_error(exc),
                }
            )
            if kind == "rate_limit":
                _rotation.cool_down(candidate.fingerprint, RATE_LIMIT_COOLDOWN_SECONDS)
            elif kind == "auth":
                _rotation.cool_down(candidate.fingerprint, AUTH_FAILURE_COOLDOWN_SECONDS)
            continue

        return response if tools else _extract_text(response)

    raise AllKeysExhaustedError(attempts)


async def ask_llm(
    user_id: str,
    system_prompt: str,
    user_prompt: str,
    model_preference: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    messages_history: list[dict[str, str]] | None = None,
) -> Any:
    """Contract 2 (Agent -> Gateway): pull the user's round-robin key and run via LiteLLM."""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if messages_history:
        messages.extend(messages_history)
    messages.append({"role": "user", "content": user_prompt})
    return await complete(user_id, messages, model_preference=model_preference, tools=tools)


async def ask_persona(
    user_id: str,
    user_prompt: str,
    mode: str | None = None,
    context: Any = None,
    model_preference: str | None = None,
) -> str:
    """Convenience: pick a persona (auto-detected from the message if ``mode`` is None)."""
    from app.services_ai.prompts import build_system_prompt, detect_mode

    chosen = mode or detect_mode(user_prompt)
    return await ask_llm(
        user_id, build_system_prompt(chosen, context), user_prompt, model_preference
    )


class AIGateway:
    """Object-style facade over the module functions (kept for backward compatibility)."""

    def __init__(self, model_preference: str | None = None):
        self.default_model = model_preference or default_model(DEFAULT_PROVIDER)

    async def ask(
        self,
        user_id: str,
        system_prompt: str,
        user_prompt: str,
        model_preference: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        messages_history: list[dict[str, str]] | None = None,
    ) -> Any:
        return await ask_llm(
            user_id,
            system_prompt,
            user_prompt,
            model_preference or self.default_model,
            tools=tools,
            messages_history=messages_history,
        )

    async def generate_response(
        self,
        user_id: str,
        system_prompt: str = "",
        user_prompt: str = "",
        prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        model_preference: str | None = None,
        messages_history: list[dict[str, str]] | None = None,
    ) -> Any:
        text = user_prompt or prompt or ""
        return await self.ask(
            user_id,
            system_prompt,
            text,
            model_preference=model_preference,
            tools=tools,
            messages_history=messages_history,
        )

    add_key = staticmethod(add_api_key)
    add_keys_from_text = staticmethod(add_api_keys_from_text)
    list_keys = staticmethod(list_api_keys)
    deactivate_key = staticmethod(deactivate_api_key)
    delete_key = staticmethod(delete_api_key)


ai_gateway = AIGateway()
