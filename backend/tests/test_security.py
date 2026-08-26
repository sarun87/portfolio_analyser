import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response
from fastapi.routing import APIRoute

from backend.app.api import routes
from backend.app.api.routes import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME, clear_session_cookies, require_unlocked, set_session_cookies
from backend.app.core.encryption import EncryptionError, generate_salt, key_manager
from backend.app.db.database import EncryptedDatabase
from backend.app.main import app


def test_every_non_auth_api_route_requires_unlocked_database():
    public = {"/api/auth/status", "/api/auth/setup", "/api/auth/unlock"}
    api_routes = [
        route for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api")
    ]

    assert api_routes
    for route in api_routes:
        dependencies = {dependency.call for dependency in route.dependant.dependencies}
        if route.path in public:
            assert require_unlocked not in dependencies
        else:
            assert require_unlocked in dependencies, route.path


def test_database_file_is_encrypted_and_restores_relational_data(tmp_path):
    database_path = tmp_path / "portfolio.db.encrypted"
    salt = generate_salt()
    verifier = key_manager.setup("correct horse battery staple", salt)
    database = EncryptedDatabase(database_path)

    try:
        database.unlock()
        with database.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE parent (id INTEGER PRIMARY KEY, secret TEXT NOT NULL);
                CREATE TABLE child (
                  id INTEGER PRIMARY KEY,
                  parent_id INTEGER NOT NULL REFERENCES parent(id),
                  amount REAL NOT NULL
                );
                INSERT INTO parent (id, secret) VALUES (1, 'private-holding-name');
                INSERT INTO child (id, parent_id, amount) VALUES (1, 1, 123456.78);
                """
            )

        encrypted = database_path.read_bytes()
        assert not encrypted.startswith(b"SQLite format 3")
        assert b"private-holding-name" not in encrypted
        assert b"123456.78" not in encrypted
        assert os.stat(database_path).st_mode & 0o777 == 0o600

        database.lock()
        key_manager.lock()
        key_manager.unlock("correct horse battery staple", salt, verifier)
        database.unlock()
        with database.connection() as conn:
            row = conn.execute(
                "SELECT p.secret, c.amount FROM parent p JOIN child c ON c.parent_id = p.id"
            ).fetchone()
            assert row["secret"] == "private-holding-name"
            assert row["amount"] == 123456.78
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        database.lock()
        key_manager.lock()


def test_unlock_session_token_is_random_and_required():
    salt = generate_salt()
    verifier = key_manager.setup("correct horse battery staple", salt)
    first_token = key_manager.session_token

    try:
        assert first_token
        assert key_manager.authenticate(first_token)
        assert not key_manager.authenticate(None)
        assert not key_manager.authenticate("incorrect-token")

        key_manager.lock()
        assert not key_manager.authenticate(first_token)
        key_manager.unlock("correct horse battery staple", salt, verifier)
        assert key_manager.session_token
        assert key_manager.session_token != first_token
        assert not key_manager.authenticate(first_token)
        assert key_manager.authenticate(key_manager.session_token)
    finally:
        key_manager.lock()


def test_reencrypting_database_rejects_the_old_passphrase_and_preserves_data(tmp_path):
    database_path = tmp_path / "portfolio.db.encrypted"
    old_salt = generate_salt()
    key_manager.setup("correct horse battery staple", old_salt)
    database = EncryptedDatabase(database_path)

    try:
        database.unlock()
        with database.connection() as conn:
            conn.execute("CREATE TABLE holdings (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
            conn.execute("INSERT INTO holdings (name) VALUES ('preserved holding')")

        new_salt, replacement_fernet, new_verifier = key_manager.prepare_passphrase_change("new correct battery staple")
        database.replace_encrypted_snapshot(database.encrypted_snapshot(replacement_fernet))
        key_manager.activate_fernet(replacement_fernet)

        database.lock()
        key_manager.lock()
        with pytest.raises(EncryptionError):
            key_manager.unlock("correct horse battery staple", new_salt, new_verifier)
        key_manager.unlock("new correct battery staple", new_salt, new_verifier)
        database.unlock()
        with database.connection() as conn:
            assert conn.execute("SELECT name FROM holdings").fetchone()["name"] == "preserved holding"
    finally:
        database.lock()
        key_manager.lock()


def test_discard_removes_the_encrypted_database_snapshot(tmp_path):
    database_path = tmp_path / "portfolio.db.encrypted"
    key_manager.setup("correct horse battery staple", generate_salt())
    database = EncryptedDatabase(database_path)
    try:
        database.unlock()
        with database.connection() as conn:
            conn.execute("CREATE TABLE reset_check (id INTEGER PRIMARY KEY)")
        assert database_path.exists()
        database.discard()
        assert not database.is_unlocked
        assert not database_path.exists()
    finally:
        database.lock()
        key_manager.lock()


def test_unlock_session_cookies_are_http_only_for_auth_and_require_csrf_for_writes(monkeypatch):
    salt = generate_salt()
    key_manager.setup("correct horse battery staple", salt)

    try:
        monkeypatch.setattr(routes, "database_manager", SimpleNamespace(is_unlocked=True))
        response = Response()
        set_session_cookies(response)
        cookies = response.headers.getlist("set-cookie")
        assert any(f"{SESSION_COOKIE_NAME}=" in cookie and "HttpOnly" in cookie and "Path=/api" in cookie for cookie in cookies)
        assert any(f"{CSRF_COOKIE_NAME}=" in cookie and "HttpOnly" not in cookie and "Path=/" in cookie for cookie in cookies)

        request = Request({"type": "http", "method": "POST", "headers": [(b"origin", b"http://localhost:5173")]})
        require_unlocked(request, key_manager.session_token, key_manager.csrf_token, key_manager.csrf_token)
        direct_request = Request({"type": "http", "method": "POST", "headers": [(b"origin", b"http://127.0.0.1:8000")]})
        require_unlocked(direct_request, key_manager.session_token, key_manager.csrf_token, key_manager.csrf_token)
        with pytest.raises(HTTPException, match="CSRF"):
            require_unlocked(request, key_manager.session_token, key_manager.csrf_token, "wrong")
        untrusted_request = Request({"type": "http", "method": "POST", "headers": [(b"origin", b"http://untrusted.example")]})
        with pytest.raises(HTTPException, match="not trusted"):
            require_unlocked(untrusted_request, key_manager.session_token, key_manager.csrf_token, key_manager.csrf_token)

        clear_session_cookies(response)
        assert any(f"{SESSION_COOKIE_NAME}=\"\"" in cookie or f"{SESSION_COOKIE_NAME}=" in cookie and "Max-Age=0" in cookie for cookie in response.headers.getlist("set-cookie"))
    finally:
        key_manager.lock()
