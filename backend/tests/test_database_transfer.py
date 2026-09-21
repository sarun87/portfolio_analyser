import sqlite3

import pytest

from backend.app.db.schema import init_db
from backend.app.services.database_transfer_service import TransferError, create_export, import_export


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
