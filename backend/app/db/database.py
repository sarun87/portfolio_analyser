# SPDX-FileCopyrightText: Copyright (C) Arun Sriraman
# SPDX-License-Identifier: GPL-3.0-only
import sqlite3
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet

from backend.app.core.encryption import EncryptionError, key_manager
from backend.app.core.config import DATABASE_PATH, ensure_data_dir


class EncryptedDatabase:
    """Keep SQLite in memory and persist only an encrypted SQL snapshot."""

    def __init__(self, path: Path = DATABASE_PATH) -> None:
        self.path = path
        self._connection: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()
        self._revision = 0

    @property
    def is_unlocked(self) -> bool:
        return self._connection is not None

    @property
    def revision(self) -> int:
        """Incremented after each successfully persisted mutation."""
        return self._revision

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

    def encrypted_snapshot(self, fernet: Fernet) -> bytes:
        """Return the current in-memory database encrypted by a replacement key."""
        with self._lock:
            if self._connection is None:
                raise EncryptionError("Portfolio database is locked.")
            self._connection.commit()
            dump = "\n".join(self._connection.iterdump()).encode("utf-8")
            return fernet.encrypt(dump)

    def replace_encrypted_snapshot(self, encrypted: bytes) -> None:
        with self._lock:
            ensure_data_dir()
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_bytes(encrypted)
            os.chmod(temporary, 0o600)
            temporary.replace(self.path)

    def discard(self) -> None:
        """Close the in-memory database and permanently remove its encrypted snapshot."""
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
            self.path.unlink(missing_ok=True)

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
            # SQLite tracks DML changes for this connection.  Persisting the
            # encrypted SQL dump only after a mutation avoids exporting and
            # encrypting the complete database for every read request.
            changes_before = self._connection.total_changes
            schema_mutated = [False]
            schema_actions = {
                sqlite3.SQLITE_CREATE_INDEX, sqlite3.SQLITE_CREATE_TABLE,
                sqlite3.SQLITE_CREATE_TEMP_INDEX, sqlite3.SQLITE_CREATE_TEMP_TABLE,
                sqlite3.SQLITE_CREATE_TEMP_TRIGGER, sqlite3.SQLITE_CREATE_TEMP_VIEW,
                sqlite3.SQLITE_CREATE_TRIGGER, sqlite3.SQLITE_CREATE_VIEW,
                sqlite3.SQLITE_DROP_INDEX, sqlite3.SQLITE_DROP_TABLE,
                sqlite3.SQLITE_DROP_TEMP_INDEX, sqlite3.SQLITE_DROP_TEMP_TABLE,
                sqlite3.SQLITE_DROP_TEMP_TRIGGER, sqlite3.SQLITE_DROP_TEMP_VIEW,
                sqlite3.SQLITE_DROP_TRIGGER, sqlite3.SQLITE_DROP_VIEW,
                sqlite3.SQLITE_ALTER_TABLE,
            }

            def authorizer(action, _arg1, _arg2, _database, _source):
                if action in schema_actions:
                    schema_mutated[0] = True
                return sqlite3.SQLITE_OK

            self._connection.set_authorizer(authorizer)
            try:
                yield self._connection
                if self._connection.total_changes != changes_before or schema_mutated[0]:
                    self._connection.commit()
                    self._persist()
                    self._revision += 1
            except Exception:
                self._connection.rollback()
                raise
            finally:
                # CPython 3.9's sqlite wrapper treats ``None`` as a callback
                # that denies subsequent statements; leave an allow-all
                # callback instead.
                self._connection.set_authorizer(lambda *_args: sqlite3.SQLITE_OK)


database_manager = EncryptedDatabase()


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    with database_manager.connection() as conn:
        yield conn
