import sqlite3

import pytest

from backend.app.db.schema import init_db
from backend.app.services.allocation_category_service import create_category, delete_category, list_categories


def test_categories_seed_and_reject_blank_or_duplicates(sqlite_conn):
    init_db(sqlite_conn)
    assert "Cash" in list_categories(sqlite_conn)
    assert create_category(sqlite_conn, "  Thematic  ") == "Thematic"
    with pytest.raises(ValueError, match="already exists"):
        create_category(sqlite_conn, "thematic")
    with pytest.raises(ValueError, match="cannot be blank"):
        create_category(sqlite_conn, " ")


def test_category_migration_preserves_unversioned_data():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    conn.execute("INSERT INTO brokers(name) VALUES ('Legacy broker')")
    conn.execute("DROP TABLE schema_migrations")
    init_db(conn)
    assert conn.execute("SELECT name FROM brokers").fetchone()["name"] == "Legacy broker"
    assert [row["version"] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")] == [1, 2, 3, 4]


def test_category_delete_is_allowed_when_unused(sqlite_conn):
    init_db(sqlite_conn)
    create_category(sqlite_conn, "Disposable")
    delete_category(sqlite_conn, "Disposable")
    assert "Disposable" not in list_categories(sqlite_conn)
