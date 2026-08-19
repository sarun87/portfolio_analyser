from __future__ import annotations

import sqlite3


def list_categories(conn: sqlite3.Connection) -> list[str]:
    names = {row["name"] for row in conn.execute("SELECT name FROM allocation_categories ORDER BY name COLLATE NOCASE")}
    names.add("Retirement")
    return sorted(names, key=str.casefold)


def register_category(conn: sqlite3.Connection, name: str | None) -> None:
    clean = (name or "").strip()
    if clean:
        conn.execute("INSERT OR IGNORE INTO allocation_categories (name) VALUES (?)", (clean,))


def create_category(conn: sqlite3.Connection, name: str) -> str:
    clean = name.strip()
    if not clean:
        raise ValueError("Allocation category name cannot be blank.")
    try:
        conn.execute("INSERT INTO allocation_categories (name) VALUES (?)", (clean,))
    except sqlite3.IntegrityError as exc:
        raise ValueError("Allocation category already exists.") from exc
    return clean


def delete_category(conn: sqlite3.Connection, name: str) -> None:
    category = name.strip()
    if not category:
        raise ValueError("Allocation category name cannot be blank.")
    active = conn.execute("""SELECT 1 FROM positions p JOIN securities s ON s.id=p.security_id
        WHERE s.allocation_category = ? COLLATE NOCASE
          AND p.snapshot_date=(SELECT MAX(p2.snapshot_date) FROM positions p2 WHERE p2.account_id=p.account_id) LIMIT 1""", (category,)).fetchone()
    if active:
        raise ValueError("Allocation category is assigned to a current holding.")
    if conn.execute("SELECT 1 FROM allocation_targets WHERE dimension='asset_category' AND label = ? COLLATE NOCASE", (category,)).fetchone():
        raise ValueError("Allocation category is referenced by an allocation-policy target.")
    if not conn.execute("DELETE FROM allocation_categories WHERE name = ? COLLATE NOCASE", (category,)).rowcount:
        raise ValueError("Allocation category not found.")
