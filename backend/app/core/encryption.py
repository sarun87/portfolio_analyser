from __future__ import annotations

import base64
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from backend.app.core.config import AUTH_CONFIG_PATH, ensure_data_dir


VERIFIER_TEXT = b"portfolio-analyser-verifier-v1"
KDF_ITERATIONS = 390_000


class EncryptionError(RuntimeError):
    pass


def generate_salt() -> bytes:
    return os.urandom(16)


def derive_key(passphrase: str, salt: bytes) -> bytes:
    if not passphrase:
        raise EncryptionError("Passphrase cannot be empty.")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=KDF_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


@dataclass
class KeyManager:
    _fernet: Optional[Fernet] = None
    _session_token: Optional[str] = None
    _csrf_token: Optional[str] = None

    @property
    def is_unlocked(self) -> bool:
        return self._fernet is not None

    def lock(self) -> None:
        self._fernet = None
        self._session_token = None
        self._csrf_token = None

    @property
    def session_token(self) -> Optional[str]:
        return self._session_token

    @property
    def csrf_token(self) -> Optional[str]:
        return self._csrf_token

    def authenticate(self, token: Optional[str]) -> bool:
        return bool(self._session_token and token and secrets.compare_digest(self._session_token, token))

    def authenticate_csrf(self, token: Optional[str]) -> bool:
        return bool(self._csrf_token and token and secrets.compare_digest(self._csrf_token, token))

    def setup(self, passphrase: str, salt: bytes) -> str:
        key = derive_key(passphrase, salt)
        self._fernet = Fernet(key)
        self._session_token = secrets.token_urlsafe(32)
        self._csrf_token = secrets.token_urlsafe(32)
        return self.encrypt(VERIFIER_TEXT.decode("utf-8"))

    def unlock(self, passphrase: str, salt: bytes, verifier_token: str) -> None:
        key = derive_key(passphrase, salt)
        candidate = Fernet(key)
        try:
            verifier = candidate.decrypt(verifier_token.encode("utf-8"))
        except InvalidToken as exc:
            raise EncryptionError("Invalid passphrase.") from exc
        if verifier != VERIFIER_TEXT:
            raise EncryptionError("Invalid passphrase.")
        self._fernet = candidate
        self._session_token = secrets.token_urlsafe(32)
        self._csrf_token = secrets.token_urlsafe(32)

    def encrypt(self, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not self._fernet:
            raise EncryptionError("Database is locked.")
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def encrypt_bytes(self, value: bytes) -> bytes:
        if not self._fernet:
            raise EncryptionError("Database is locked.")
        return self._fernet.encrypt(value)

    def decrypt(self, token: Optional[str]) -> Optional[str]:
        if token is None:
            return None
        if not self._fernet:
            raise EncryptionError("Database is locked.")
        return self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")

    def decrypt_bytes(self, token: bytes) -> bytes:
        if not self._fernet:
            raise EncryptionError("Database is locked.")
        try:
            return self._fernet.decrypt(token)
        except InvalidToken as exc:
            raise EncryptionError("Encrypted database is corrupt or uses a different passphrase.") from exc


key_manager = KeyManager()


def load_encryption_config(path: Path = AUTH_CONFIG_PATH) -> tuple[Optional[bytes], Optional[str]]:
    if not path.exists():
        return None, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        salt = bytes.fromhex(str(payload["salt"]))
        verifier = str(payload["verifier"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise EncryptionError("Encryption configuration is invalid.") from exc
    return salt, verifier


def save_encryption_config(salt: bytes, verifier: str, path: Path = AUTH_CONFIG_PATH) -> None:
    ensure_data_dir()
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps({"salt": salt.hex(), "verifier": verifier}), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
