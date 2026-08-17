import sqlite3
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from backend.app.core.encryption import EncryptionError, key_manager
from backend.app.core.config import DATABASE_PATH, ensure_data_dir


class EncryptedDatabase:
    """Keep SQLite in memory and persist only an encrypted SQL snapshot."""

    def __init__(self, path: Path = DATABASE_PATH) -> None:
        self.path = path
        self._connection: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()

    @property
    def is_unlocked(self) -> bool:
        return self._connection is not None

    def unlock(self) -> None:
        if not key_manager.is_unlocked:
            raise EncryptionError("Portfolio database is locked.")
        with self._lock:
            if self._connection is not None:
                return
            conn = sqlite3.connect(":memory:", check_same_thread=False)
            conn.row_factory = sqlite3.Row
            try:
                if self.path.exists():
                    encrypted = self.path.read_bytes()
                    script = key_manager.decrypt_bytes(encrypted).decode("utf-8")
                    # SQL dumps are ordered by table name, not dependency order.
                    # Restore with FK checks disabled, then enforce them normally.
                    conn.execute("PRAGMA foreign_keys = OFF")
                    conn.executescript(script)
                    conn.commit()
                conn.execute("PRAGMA foreign_keys = ON")
            except (OSError, UnicodeDecodeError, sqlite3.DatabaseError, EncryptionError) as exc:
                conn.close()
                if isinstance(exc, EncryptionError):
                    raise
                raise EncryptionError("Encrypted database could not be opened.") from exc
            self._connection = conn

    def lock(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def _persist(self) -> None:
        if self._connection is None:
            raise EncryptionError("Portfolio database is locked.")
        ensure_data_dir()
        dump = "\n".join(self._connection.iterdump()).encode("utf-8")
        encrypted = key_manager.encrypt_bytes(dump)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_bytes(encrypted)
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self._connection is None:
                raise EncryptionError("Portfolio database is locked.")
            try:
                yield self._connection
                self._connection.commit()
                self._persist()
            except Exception:
                self._connection.rollback()
                raise


database_manager = EncryptedDatabase()


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    with database_manager.connection() as conn:
        yield conn
