"""Encryption-at-rest for user-supplied API keys (Fernet = AES-128-CBC + HMAC-SHA256).

Rotation: set SECRET_KEY to the new value and SECRET_KEY_OLD to the previous one. New data is
encrypted with the new key; old rows still decrypt until you re-save them.
"""

import base64

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import settings


def _fernet_for(secret: str) -> Fernet:
    raw = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"walletledger-fernet").derive(
        secret.encode()
    )
    return Fernet(base64.urlsafe_b64encode(raw))


def _multi() -> MultiFernet:
    secrets_ = [settings.secret_key] + [s for s in settings.secret_key_old.split(",") if s.strip()]
    return MultiFernet([_fernet_for(s.strip()) for s in secrets_])


def encrypt_secret(plaintext: str) -> str:
    return _multi().encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str) -> str:
    """Raises ValueError if malformed, tampered with, or encrypted under an unknown key."""
    try:
        return _multi().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError) as exc:
        raise ValueError("Cannot decrypt value (wrong SECRET_KEY, malformed or tampered)") from exc
