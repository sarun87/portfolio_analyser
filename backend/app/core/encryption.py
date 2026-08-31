from __future__ import annotations

import base64
import json
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from backend.app.core.config import AUTH_CONFIG_PATH, ensure_data_dir


VERIFIER_TEXT = b"portfolio-analyser-verifier-v1"
KDF_ITERATIONS = 390_000
SESSION_TTL_SECONDS = int(os.getenv("PORTFOLIO_SESSION_TTL_SECONDS", str(12 * 60 * 60)))


class EncryptionError(RuntimeError):
    pass


@dataclass
class Session:
    csrf_token: str
    expires_at: float


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
    _sessions: dict[str, Session] = field(default_factory=dict)
    _latest_session_token: Optional[str] = None

    @property
    def is_unlocked(self) -> bool:
        return self._fernet is not None

    def lock(self) -> None:
        self._fernet = None
        self._sessions.clear()
        self._latest_session_token = None

    @property
    def session_token(self) -> Optional[str]:
        return self._latest_session_token

    @property
    def csrf_token(self) -> Optional[str]:
        session = self._session_for(self._latest_session_token)
        return session.csrf_token if session else None

    def authenticate(self, token: Optional[str]) -> bool:
        return self._session_for(token) is not None

    def authenticate_csrf(self, session_token: Optional[str], csrf_token: Optional[str] = None) -> bool:
        # The one-argument form remains useful for internal callers/tests and
        # validates against the most recently created session.
        if csrf_token is None:
            csrf_token, session_token = session_token, self._latest_session_token
        session = self._session_for(session_token)
        return bool(session and csrf_token and secrets.compare_digest(session.csrf_token, csrf_token))

    def revoke_session(self, token: Optional[str]) -> None:
        if token:
            self._sessions.pop(token, None)
            if token == self._latest_session_token:
                self._latest_session_token = next(iter(self._sessions), None)

    def _session_for(self, token: Optional[str]) -> Optional[Session]:
        if not token:
            return None
        session = self._sessions.get(token)
        if not session:
            return None
        if session.expires_at <= time.time():
            self._sessions.pop(token, None)
            if token == self._latest_session_token:
                self._latest_session_token = next(iter(self._sessions), None)
            return None
        return session

    def setup(self, passphrase: str, salt: bytes) -> str:
        key = derive_key(passphrase, salt)
        self._fernet = Fernet(key)
        self._sessions.clear()
        self._new_session()
        return self.encrypt(VERIFIER_TEXT.decode("utf-8"))

    def prepare_passphrase_change(self, passphrase: str) -> tuple[bytes, Fernet, str]:
        salt = generate_salt()
        candidate = Fernet(derive_key(passphrase, salt))
        verifier = candidate.encrypt(VERIFIER_TEXT).decode("utf-8")
        return salt, candidate, verifier

    def activate_fernet(self, fernet: Fernet) -> None:
        self._fernet = fernet
        # A passphrase change must invalidate every session authenticated with
        # the previous encryption key, except for the fresh caller session.
        self._sessions.clear()
        self._new_session()

    def _new_session(self) -> None:
        now = time.time()
        for stale_token, session in list(self._sessions.items()):
            if session.expires_at <= now:
                self._sessions.pop(stale_token, None)
        token = secrets.token_urlsafe(32)
        self._sessions[token] = Session(csrf_token=secrets.token_urlsafe(32), expires_at=now + SESSION_TTL_SECONDS)
        self._latest_session_token = token

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
        self._new_session()

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
