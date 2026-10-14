# SPDX-FileCopyrightText: Copyright (C) Arun Sriraman
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date
from typing import Optional

from backend.app.core.encryption import key_manager
from backend.app.services.classification_service import fallback_category


def get_setting(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO app_settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def get_brokers(conn: sqlite3.Connection) -> list[dict]:
    brokers = [dict(row) for row in conn.execute("SELECT id, name, default_currency, notes, locked_fields_json, header_signature_json, mappings_json, configuration_version FROM brokers ORDER BY name")]
    for broker in brokers:
        broker["locked_fields"] = json.loads(broker.pop("locked_fields_json") or "[]")
        broker["header_signature"] = json.loads(broker.pop("header_signature_json") or "[]")
        broker["mappings"] = json.loads(broker.pop("mappings_json") or "{}")
    return brokers


def get_broker(conn: sqlite3.Connection, broker_id: int) -> Optional[dict]:
    return next((item for item in get_brokers(conn) if item["id"] == broker_id), None)


def get_broker_by_name(conn: sqlite3.Connection, name: str) -> Optional[dict]:
    normalized = name.strip()
    return next((item for item in get_brokers(conn) if item["name"] == normalized), None)


def get_or_create_broker(conn: sqlite3.Connection, name: str) -> int:
    normalized = name.strip()
    conn.execute("INSERT OR IGNORE INTO brokers (name) VALUES (?)", (normalized,))
    row = conn.execute("SELECT id FROM brokers WHERE name = ?", (normalized,)).fetchone()
    if not row:
        raise ValueError(f"Broker not found: {name}")
    return int(row["id"])


def mask_account(account_number: Optional[str]) -> str:
    cleaned = (account_number or "UNKNOWN").strip()
    if cleaned == "UNKNOWN":
        return "Unknown"
    last_four = cleaned[-4:] if len(cleaned) >= 4 else cleaned
    return f"****{last_four}"


def fingerprint_account(account_number: Optional[str]) -> str:
    value = (account_number or "UNKNOWN").strip().lower()
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def get_or_create_account(conn: sqlite3.Connection, broker_id: int, account_number: Optional[str]) -> int:
    fingerprint = fingerprint_account(account_number)
    row = conn.execute(
        "SELECT id FROM accounts WHERE broker_id = ? AND account_fingerprint = ?",
        (broker_id, fingerprint),
    ).fetchone()
    if row:
        return int(row["id"])

    encrypted = key_manager.encrypt((account_number or "UNKNOWN").strip())
    cursor = conn.execute(
        """
        INSERT INTO accounts (broker_id, account_number_enc, account_mask, account_fingerprint)
        VALUES (?, ?, ?, ?)
        """,
        (broker_id, encrypted, mask_account(account_number), fingerprint),
    )
    return int(cursor.lastrowid)


def get_or_create_security(
    conn: sqlite3.Connection,
    *,
    name: str,
    security_type: str,
    symbol: Optional[str],
    exchange: str = "Unresolved",
    investment_country: str = "Unresolved",
    location_source: Optional[str] = None,
) -> int:
    normalized_symbol = symbol.upper().strip() if symbol else None
    normalized_name = name.strip() or normalized_symbol or "Unknown Security"
    normalized_type = security_type.strip() or "Other"
    allocation_category = fallback_category(normalized_symbol, normalized_name, normalized_type)
    row = conn.execute(
        """
        SELECT id FROM securities
        WHERE COALESCE(symbol, '') = COALESCE(?, '')
          AND exchange = ?
        """,
        (normalized_symbol, exchange),
    ).fetchone()
    if row:
        conn.execute(
            """
            UPDATE securities
            SET name = ?, security_type = ?, investment_country = ?, location_source = ?,
                location_resolved_at = CURRENT_TIMESTAMP,
                price_refresh_supported = ?
            WHERE id = ?
            """,
            (
                normalized_name,
                normalized_type,
                investment_country,
                location_source,
                0 if normalized_type.lower() == "cash" else 1,
                row["id"],
            ),
        )
        return int(row["id"])

    supported = 0 if normalized_type.lower() == "cash" else 1
    cursor = conn.execute(
        """
        INSERT INTO securities (
          symbol, name, security_type, allocation_category, classification_source, price_refresh_supported,
          exchange, investment_country, location_source, location_resolved_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (normalized_symbol, normalized_name, normalized_type, allocation_category, "local-rules", supported,
         exchange, investment_country, location_source),
    )
    return int(cursor.lastrowid)


def insert_import(
    conn: sqlite3.Connection,
    *,
    broker_id: int,
    account_id: Optional[int],
    statement_date: str,
    source_filename: Optional[str],
    row_count: int,
    fingerprint: str,
    detected_columns: list[str],
    errors: list[str],
    locked_fields: list[str],
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO statement_imports (
          broker_id, account_id, statement_date, source_filename, row_count,
          fingerprint, status, detected_columns, errors_json, locked_fields_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            broker_id,
            account_id,
            statement_date,
            source_filename,
            row_count,
            fingerprint,
            "imported" if not errors else "imported_with_warnings",
            json.dumps(detected_columns),
            json.dumps(errors),
            json.dumps(locked_fields),
        ),
    )
    return int(cursor.lastrowid)


def import_exists(conn: sqlite3.Connection, fingerprint: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM statement_imports WHERE fingerprint = ?",
        (fingerprint,),
    ).fetchone()
    return bool(row)


def insert_position(
    conn: sqlite3.Connection,
    *,
    import_id: int,
    account_id: int,
    security_id: int,
    snapshot_date: str,
    acquisition_date: Optional[str],
    lot_number: Optional[str],
    units: float,
    per_unit_cost_basis: Optional[float],
    total_cost_basis: Optional[float],
    per_unit_fmv: Optional[float],
    total_fmv: Optional[float],
    currency: str,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO positions (
          import_id, account_id, security_id, snapshot_date, acquisition_date,
          lot_number, units, per_unit_cost_basis, total_cost_basis, per_unit_fmv,
          total_fmv, currency
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            import_id,
            account_id,
            security_id,
            snapshot_date,
            acquisition_date,
            lot_number,
            units,
            per_unit_cost_basis,
            total_cost_basis,
            per_unit_fmv,
            total_fmv,
            currency,
        ),
    )
    return int(cursor.lastrowid)


def record_price(conn: sqlite3.Connection, security_id: int, price: float, provider: str, price_date: Optional[str] = None) -> None:
    conn.execute(
        """
        INSERT INTO price_history (security_id, price, price_date, provider)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(security_id, price_date, provider) DO UPDATE SET price = excluded.price
        """,
        (security_id, price, price_date or date.today().isoformat(), provider),
    )


def _delete_tables(conn: sqlite3.Connection, tables: list[str]) -> None:
    for table in tables:
        conn.execute(f"DELETE FROM {table}")
    for table in tables:
        conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))


def clean_brokerage_data(conn: sqlite3.Connection) -> None:
    tables = [
        "saved_scenarios",
        "reference_cache",
        "price_history",
        "positions",
        "statement_imports",
        "securities",
        "accounts",
    ]
    _delete_tables(conn, tables)


def clean_static_account_data(conn: sqlite3.Connection) -> None:
    _delete_tables(conn, ["static_accounts"])


def clean_real_estate_data(conn: sqlite3.Connection) -> None:
    _delete_tables(conn, ["real_estate_assets"])


def clean_private_equity_data(conn: sqlite3.Connection) -> None:
    _delete_tables(conn, ["private_equity_assets"])


def clean_liability_data(conn: sqlite3.Connection) -> None:
    _delete_tables(conn, ["liabilities"])


def clean_portfolio_data(conn: sqlite3.Connection) -> None:
    clean_brokerage_data(conn)
    clean_static_account_data(conn)
    clean_real_estate_data(conn)
    clean_private_equity_data(conn)
    clean_liability_data(conn)
    _delete_tables(conn, ["portfolio_fees", "risk_settings", "fee_settings"])
