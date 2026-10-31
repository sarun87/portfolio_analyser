# SPDX-FileCopyrightText: Copyright (C) Arun Sriraman
# SPDX-License-Identifier: GPL-3.0-only
import sqlite3
from typing import Optional

import pytest

from backend.app.db.schema import init_db
from backend.app.services.database_transfer_service import (
    TransferError,
    create_export,
    import_export,
    inspect_export,
)


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_db(conn)
    return conn


def _static(conn: sqlite3.Connection, category: str, name: str, amount: float) -> None:
    conn.execute(
        """INSERT INTO static_accounts(category, entity_name, account_type, account_holder, amount, currency)
           VALUES (?, ?, 'Account', 'Owner', ?, 'USD')""",
        (category, name, amount),
    )
    conn.commit()


def _broker(
    conn: sqlite3.Connection,
    name: str,
    *,
    default_currency: str = "USD",
    notes: Optional[str] = None,
    mappings_json: str = "{}",
    configuration_version: int = 1,
) -> int:
    cursor = conn.execute(
        """INSERT INTO brokers(name, default_currency, notes, mappings_json, configuration_version)
           VALUES (?, ?, ?, ?, ?)""",
        (name, default_currency, notes, mappings_json, configuration_version),
    )
    conn.commit()
    return int(cursor.lastrowid)


def _account(conn: sqlite3.Connection, broker_id: int, fingerprint: str) -> int:
    cursor = conn.execute(
        """INSERT INTO accounts(broker_id, account_number_enc, account_mask, account_fingerprint)
           VALUES (?, 'encrypted-number', '1234', ?)""",
        (broker_id, fingerprint),
    )
    conn.commit()
    return int(cursor.lastrowid)


def test_bank_export_import_replaces_only_bank_accounts(tmp_path):
    source = _connection()
    _static(source, "Bank Account", "Source bank", 100)
    _static(source, "Retirement Account", "Source retirement", 200)
    export_path = tmp_path / "bank.db"
    export_path.write_bytes(create_export(source, ["bank-accounts"]))

    target = _connection()
    _static(target, "Bank Account", "Old bank", 1)
    _static(target, "Retirement Account", "Keep retirement", 2)

    result = import_export(target, export_path, ["bank-accounts"])

    assert result == {"bank-accounts": 1}
    rows = [tuple(row) for row in target.execute("SELECT category, entity_name, amount FROM static_accounts ORDER BY category")]
    assert rows == [("Bank Account", "Source bank", 100.0), ("Retirement Account", "Keep retirement", 2.0)]


def test_portfolio_history_export_import_replaces_only_history(tmp_path):
    source = _connection()
    source.execute("INSERT INTO portfolio_net_worth_snapshots(snapshot_date, captured_at) VALUES ('2026-01-01', 'captured')")
    source.execute("INSERT INTO portfolio_net_worth_snapshot_balances VALUES ('2026-01-01', 'USD', 123.0)")
    source.execute("INSERT INTO portfolio_net_worth_snapshot_fx_rates VALUES ('2026-01-01', 'USD', 'USD', 1.0)")
    _static(source, "Bank Account", "Source bank", 100)
    export_path = tmp_path / "portfolio-history.db"
    export_path.write_bytes(create_export(source, ["portfolio-history"]))

    target = _connection()
    target.execute("INSERT INTO portfolio_net_worth_snapshots(snapshot_date, captured_at) VALUES ('2025-12-31', 'old')")
    target.execute("INSERT INTO portfolio_net_worth_snapshot_balances VALUES ('2025-12-31', 'USD', 7.0)")
    _static(target, "Bank Account", "Keep bank", 8)

    assert inspect_export(target, export_path) == ["portfolio-history"]
    assert import_export(target, export_path, ["portfolio-history"]) == {"portfolio-history": 3}
    assert [tuple(row) for row in target.execute("SELECT snapshot_date, captured_at FROM portfolio_net_worth_snapshots")] == [("2026-01-01", "captured")]
    assert target.execute("SELECT net_amount FROM portfolio_net_worth_snapshot_balances").fetchone()[0] == 123
    assert target.execute("SELECT entity_name FROM static_accounts").fetchone()[0] == "Keep bank"


def test_incompatible_export_does_not_change_target(tmp_path):
    source = _connection()
    _static(source, "Bank Account", "Source bank", 100)
    export_path = tmp_path / "broken.db"
    export_path.write_bytes(create_export(source, ["bank-accounts"]))
    broken = sqlite3.connect(export_path)
    broken.execute("UPDATE portfolio_transfer_manifest SET format_version = 999")
    broken.commit()
    broken.close()

    target = _connection()
    _static(target, "Bank Account", "Keep bank", 7)

    with pytest.raises(TransferError, match="unsupported"):
        import_export(target, export_path, ["bank-accounts"])
    assert target.execute("SELECT entity_name FROM static_accounts").fetchone()[0] == "Keep bank"


def test_schema_constraint_or_index_difference_is_rejected(tmp_path):
    source = _connection()
    _static(source, "Bank Account", "Source bank", 100)
    export_path = tmp_path / "altered-schema.db"
    export_path.write_bytes(create_export(source, ["bank-accounts"]))
    altered = sqlite3.connect(export_path)
    altered.execute("CREATE INDEX unexpected_static_account_index ON static_accounts(entity_name)")
    altered.commit()
    altered.close()

    target = _connection()
    _static(target, "Bank Account", "Keep bank", 7)

    with pytest.raises(TransferError, match="incompatible"):
        import_export(target, export_path, ["bank-accounts"])
    assert target.execute("SELECT entity_name FROM static_accounts").fetchone()[0] == "Keep bank"


def test_broker_definitions_export_excludes_brokerage_data(tmp_path):
    source = _connection()
    broker_id = _broker(source, "Example Broker", notes="Statement mapping")
    _account(source, broker_id, "source-account")
    export_path = tmp_path / "brokers.db"
    export_path.write_bytes(create_export(source, ["broker-definitions"]))

    target = _connection()
    assert inspect_export(target, export_path) == ["broker-definitions"]
    assert target.execute("SELECT COUNT(*) FROM brokers").fetchone()[0] == 0

    exported = sqlite3.connect(export_path)
    try:
        assert exported.execute("SELECT name FROM brokers").fetchall() == [("Example Broker",)]
        assert exported.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0
        assert exported.execute("SELECT COUNT(*) FROM securities").fetchone()[0] == 0
        assert exported.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 0
        manifest = exported.execute(
            "SELECT categories_json FROM portfolio_transfer_manifest WHERE id = 1"
        ).fetchone()[0]
        assert manifest == '["broker-definitions"]'
    finally:
        exported.close()


def test_broker_definitions_import_merges_without_changing_local_links(tmp_path):
    source = _connection()
    _broker(
        source,
        "Shared Broker",
        default_currency="CAD",
        notes="Imported definition",
        mappings_json='{"symbol":"Ticker"}',
        configuration_version=4,
    )
    _broker(source, "New Broker", default_currency="EUR", configuration_version=2)
    source_path = tmp_path / "brokers.db"
    source_path.write_bytes(create_export(source, ["broker-definitions"]))

    target = _connection()
    target.execute("ALTER TABLE brokers ADD COLUMN local_metadata TEXT")
    shared_id = _broker(
        target,
        "Shared Broker",
        notes="Old definition",
        mappings_json="{}",
        configuration_version=7,
    )
    local_account_id = _account(target, shared_id, "local-account")
    _broker(target, "Local-only Broker")

    assert inspect_export(target, source_path) == ["broker-definitions"]
    result = import_export(target, source_path, ["broker-definitions"])

    assert result == {"broker-definitions": 2}
    assert {row[0] for row in target.execute("SELECT name FROM brokers")} == {
        "Shared Broker",
        "New Broker",
        "Local-only Broker",
    }
    shared = target.execute(
        "SELECT id, default_currency, notes, mappings_json, configuration_version "
        "FROM brokers WHERE name = ?",
        ("Shared Broker",),
    ).fetchone()
    assert tuple(shared) == (shared_id, "CAD", "Imported definition", '{"symbol":"Ticker"}', 8)
    assert target.execute(
        "SELECT broker_id FROM accounts WHERE id = ?", (local_account_id,)
    ).fetchone()[0] == shared_id
    assert target.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1
    assert target.execute(
        "SELECT local_metadata FROM brokers WHERE name = ?", ("New Broker",)
    ).fetchone()[0] is None
    assert target.execute("PRAGMA foreign_key_check").fetchall() == []


def test_brokerage_and_broker_definitions_import_brokers_only_once(tmp_path):
    source = _connection()
    broker_id = _broker(source, "Full Brokerage")
    _account(source, broker_id, "full-account")
    export_path = tmp_path / "full-brokerage.db"
    export_path.write_bytes(create_export(source, ["brokerage", "broker-definitions"]))

    target = _connection()
    result = import_export(target, export_path, ["brokerage", "broker-definitions"])

    assert result == {"brokerage": 2, "broker-definitions": 0}
    assert target.execute("SELECT COUNT(*) FROM brokers WHERE name = 'Full Brokerage'").fetchone()[0] == 1
    assert target.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1
    assert target.execute("PRAGMA foreign_key_check").fetchall() == []
