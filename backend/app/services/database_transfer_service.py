"""Portable, plain-SQLite database transfers.

Exports intentionally contain unencrypted financial data.  They are created
only on demand and are never retained by the application.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from backend.app.db.schema import MIGRATIONS, init_db


FORMAT_VERSION = 1
CATEGORIES = (
    "brokerage", "broker-definitions", "bank-accounts", "retirement-accounts", "other-static-accounts",
    "real-estate", "private-equity", "liabilities", "planning-settings",
)

BROKERAGE_TABLES = (
    "brokers", "accounts", "statement_imports", "securities", "positions", "price_history",
    "fund_compositions", "fund_constituents", "fund_metadata", "fund_sector_weights",
    "fund_ohlcv_history", "fund_refresh_status", "security_fee_metadata", "market_series",
    "market_series_points", "reference_cache",
)
PLANNING_TABLES = (
    "app_settings", "fx_rates", "financial_assumptions", "scheduled_expenses",
    "allocation_targets", "goals", "saved_scenarios", "allocation_categories", "risk_settings",
    "portfolio_fees", "fee_settings", "report_branding",
)
SINGLE_TABLE_CATEGORIES = {
    "real-estate": ("real_estate_assets",),
    "private-equity": ("private_equity_assets",),
    "liabilities": ("liabilities",),
}
STATIC_CATEGORY_VALUES = {
    "bank-accounts": "Bank Account",
    "retirement-accounts": "Retirement Account",
    "other-static-accounts": "Other",
}
BROKER_DEFINITION_COLUMNS = (
    "name", "default_currency", "notes", "locked_fields_json", "header_signature_json",
    "mappings_json", "configuration_version",
)


class TransferError(ValueError):
    pass


def validate_categories(categories: Iterable[str]) -> list[str]:
    values = list(dict.fromkeys(str(value).strip() for value in categories if str(value).strip()))
    invalid = sorted(set(values) - set(CATEGORIES))
    if invalid:
        raise TransferError(f"Unsupported transfer category: {', '.join(invalid)}.")
    if not values:
        raise TransferError("Select at least one data category.")
    return values


def _migration_versions(conn: sqlite3.Connection) -> list[int]:
    return [int(row[0]) for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]


def _reset_sequence(conn: sqlite3.Connection, table: str) -> None:
    try:
        conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))
    except sqlite3.OperationalError:
        pass


def _delete_brokerage(conn: sqlite3.Connection, preserve_brokers: bool = False) -> None:
    # Child rows first, even when foreign-key enforcement is enabled.
    for table in reversed(BROKERAGE_TABLES):
        if preserve_brokers and table == "brokers":
            continue
        conn.execute(f"DELETE FROM {table}")
        _reset_sequence(conn, table)


def _delete_planning(conn: sqlite3.Connection) -> None:
    for table in PLANNING_TABLES:
        conn.execute(f"DELETE FROM {table}")
        _reset_sequence(conn, table)


def clear_categories(conn: sqlite3.Connection, categories: Iterable[str]) -> None:
    """Clear precisely the requested transfer domains from a database."""
    for category in categories:
        if category == "brokerage":
            _delete_brokerage(conn)
        elif category == "broker-definitions":
            # Broker definitions are imported as an upsert by name. They are
            # never deleted by a definitions-only transfer because active
            # accounts and statement history may still refer to them.
            continue
        elif category == "planning-settings":
            _delete_planning(conn)
        elif category in STATIC_CATEGORY_VALUES:
            conn.execute("DELETE FROM static_accounts WHERE category = ?", (STATIC_CATEGORY_VALUES[category],))
        else:
            for table in SINGLE_TABLE_CATEGORIES[category]:
                conn.execute(f"DELETE FROM {table}")
                _reset_sequence(conn, table)


def _create_manifest(conn: sqlite3.Connection, categories: list[str]) -> None:
    conn.execute("DROP TABLE IF EXISTS portfolio_transfer_manifest")
    conn.execute("""CREATE TABLE portfolio_transfer_manifest (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        format_version INTEGER NOT NULL,
        migration_versions_json TEXT NOT NULL,
        categories_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""")
    conn.execute(
        "INSERT INTO portfolio_transfer_manifest VALUES (1, ?, ?, ?, ?)",
        (FORMAT_VERSION, json.dumps(_migration_versions(conn)), json.dumps(categories), datetime.now(timezone.utc).isoformat()),
    )


def create_export_file(conn: sqlite3.Connection, categories: Iterable[str]) -> Path:
    """Build a compact transfer file; the caller owns and removes its path."""
    categories = validate_categories(categories)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp:
            temp_path = Path(temp.name)
        export = sqlite3.connect(temp_path)
        try:
            conn.backup(export)
            export.execute("PRAGMA foreign_keys = ON")
            excluded = [category for category in CATEGORIES if category not in categories]
            # A definitions-only export keeps brokers while stripping the
            # dependent brokerage data. A full brokerage export remains a
            # self-contained bundle and always includes its broker rows.
            if "brokerage" not in categories:
                _delete_brokerage(export, preserve_brokers="broker-definitions" in categories)
                excluded.remove("brokerage")
            clear_categories(export, excluded)
            selected_static_values = [STATIC_CATEGORY_VALUES[category] for category in categories if category in STATIC_CATEGORY_VALUES]
            if selected_static_values:
                export.execute(
                    f"DELETE FROM static_accounts WHERE category NOT IN ({', '.join('?' for _ in selected_static_values)})",
                    selected_static_values,
                )
            else:
                export.execute("DELETE FROM static_accounts")
            _create_manifest(export, categories)
            export.commit()
            # A deleted row can otherwise remain in SQLite's unused pages and
            # leak an unselected account in a plain export.  Compact before
            # download so the snapshot contains only the requested data.
            export.execute("VACUUM")
        finally:
            export.close()
        return temp_path
    except Exception:
        if temp_path:
            temp_path.unlink(missing_ok=True)
        raise


def create_export(conn: sqlite3.Connection, categories: Iterable[str]) -> bytes:
    """Compatibility helper for callers that explicitly need export bytes."""
    temp_path = create_export_file(conn, categories)
    try:
        return temp_path.read_bytes()
    finally:
        temp_path.unlink(missing_ok=True)


def _normalise_sql(value: str | None) -> str:
    return " ".join((value or "").lower().split())


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _table_schema_signature(conn: sqlite3.Connection, table: str) -> tuple:
    """Return all schema features that affect compatible data import."""
    master = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    if not master:
        raise TransferError(f"The export schema is missing table '{table}'.")
    foreign_keys = tuple(
        tuple(row) for row in conn.execute(f"PRAGMA foreign_key_list({_quote_identifier(table)})")
    )
    indexes = []
    for index in conn.execute(f"PRAGMA index_list({_quote_identifier(table)})"):
        name = index[1]
        index_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?", (name,)
        ).fetchone()
        columns = tuple(tuple(row) for row in conn.execute(f"PRAGMA index_xinfo({_quote_identifier(name)})"))
        # Keep index properties/columns and SQL, rather than relying on its
        # generated name, which can differ across otherwise valid SQLite files.
        indexes.append((index[2], index[3], index[4], columns, _normalise_sql(index_sql[0] if index_sql else None)))
    triggers = tuple(
        _normalise_sql(row[0]) for row in conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND tbl_name = ? ORDER BY name", (table,)
        )
    )
    return (_normalise_sql(master[0]), tuple(foreign_keys), tuple(sorted(indexes)), triggers)


def _has_unique_column_index(conn: sqlite3.Connection, table: str, column: str) -> bool:
    for index in conn.execute(f"PRAGMA index_list({_quote_identifier(table)})"):
        if not index[2]:
            continue
        name = index[1]
        indexed_columns = tuple(
            row[2] for row in conn.execute(f"PRAGMA index_info({_quote_identifier(name)})")
        )
        if indexed_columns == (column,):
            return True
    return False


def _validate_broker_definition_schema(source: sqlite3.Connection, target: sqlite3.Connection) -> None:
    """Check the columns and constraints used by definitions-only merge.

    This transfer intentionally ignores broker IDs and creation timestamps and
    merges the layout fields by name. Comparing the complete CREATE TABLE SQL
    would reject otherwise compatible databases for unrelated DDL differences.
    """
    source_columns = {
        row[1] for row in source.execute("PRAGMA table_info(\"brokers\")")
    }
    target_columns = {
        row[1] for row in target.execute("PRAGMA table_info(\"brokers\")")
    }
    missing = sorted(set(BROKER_DEFINITION_COLUMNS) - source_columns | set(BROKER_DEFINITION_COLUMNS) - target_columns)
    if missing:
        raise TransferError(
            "The export schema is incompatible for broker definitions; required columns are missing: "
            f"{', '.join(missing)}."
        )
    if not _has_unique_column_index(source, "brokers", "name") or not _has_unique_column_index(target, "brokers", "name"):
        raise TransferError("The export schema is incompatible for broker definitions; broker names must be unique.")

    # New local columns are safe if inserts can omit them. Reject required
    # columns without defaults before any live rows are changed.
    for column in target.execute("PRAGMA table_xinfo(\"brokers\")"):
        name, not_null, default, primary_key = column[1], column[3], column[4], column[5]
        hidden = column[6] if len(column) > 6 else 0
        if (
            name not in BROKER_DEFINITION_COLUMNS
            and name != "id"
            and not hidden
            and not_null
            and default is None
            and not primary_key
        ):
            raise TransferError(
                f"The export schema is incompatible for broker definitions; local column '{name}' "
                "requires a value the import cannot provide."
            )


def _tables_for_categories(categories: Iterable[str]) -> set[str]:
    tables: set[str] = set()
    for category in categories:
        if category == "brokerage":
            tables.update(BROKERAGE_TABLES)
        elif category == "broker-definitions":
            tables.add("brokers")
        elif category == "planning-settings":
            tables.update(PLANNING_TABLES)
        elif category in STATIC_CATEGORY_VALUES:
            tables.add("static_accounts")
        else:
            tables.update(SINGLE_TABLE_CATEGORIES[category])
    return tables


def _read_manifest(conn: sqlite3.Connection) -> tuple[list[str], list[int]]:
    try:
        row = conn.execute("SELECT format_version, migration_versions_json, categories_json FROM portfolio_transfer_manifest WHERE id = 1").fetchone()
    except sqlite3.DatabaseError as exc:
        raise TransferError("This file is not a Portfolio Analyser export.") from exc
    if not row or row[0] != FORMAT_VERSION:
        raise TransferError("The export format is unsupported or missing its manifest.")
    try:
        versions = [int(value) for value in json.loads(row[1])]
        categories = validate_categories(json.loads(row[2]))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TransferError("The export manifest is invalid.") from exc
    return categories, versions


def _open_and_validate(source_path: Path, requested: list[str], target: sqlite3.Connection) -> sqlite3.Connection:
    if source_path.stat().st_size < 100 or source_path.read_bytes()[:16] != b"SQLite format 3\x00":
        raise TransferError("The selected file is not a valid SQLite database export.")
    source = sqlite3.connect(source_path)
    source.row_factory = sqlite3.Row
    try:
        available, manifest_versions = _read_manifest(source)
        missing = set(requested) - set(available)
        if missing:
            raise TransferError(f"The export does not contain: {', '.join(sorted(missing))}.")
        known = {version for version, _ in MIGRATIONS}
        if not set(manifest_versions).issubset(known):
            raise TransferError("The export was created by a newer or incompatible database schema.")
        source_versions = _migration_versions(source)
        if source_versions != manifest_versions:
            raise TransferError("The export migration history does not match its manifest.")
        current = [version for version, _ in MIGRATIONS]
        if source_versions != current:
            # Upgrade only the isolated upload copy.  The live database has not
            # been opened for mutation at this point.
            init_db(source)
        if _migration_versions(source) != current:
            raise TransferError("The export could not be upgraded to the current database schema.")
        for table in sorted(_tables_for_categories(requested)):
            if table == "brokers" and "brokerage" not in requested:
                _validate_broker_definition_schema(source, target)
            elif _table_schema_signature(source, table) != _table_schema_signature(target, table):
                raise TransferError(f"The export schema is incompatible for table '{table}'.")
        if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise TransferError("The export database integrity check failed.")
        return source
    except Exception:
        source.close()
        raise


def inspect_export(target: sqlite3.Connection, source_path: Path) -> list[str]:
    """Return the manifest categories after file, migration, and integrity checks."""
    source = _open_and_validate(source_path, [], target)
    try:
        categories, _ = _read_manifest(source)
        return categories
    finally:
        source.close()


def _copy_table(source: sqlite3.Connection, target: sqlite3.Connection, table: str, where: str = "", params: tuple = (), omit_id: bool = False) -> int:
    columns = [row["name"] for row in source.execute(f"PRAGMA table_info({table})")]
    if omit_id:
        columns = [column for column in columns if column != "id"]
    quoted = ", ".join(columns)
    rows = source.execute(f"SELECT {quoted} FROM {table} {where}", params).fetchall()
    if rows:
        target.executemany(f"INSERT INTO {table} ({quoted}) VALUES ({', '.join('?' for _ in columns)})", [tuple(row[column] for column in columns) for row in rows])
    return len(rows)


def _copy_broker_definitions(source: sqlite3.Connection, target: sqlite3.Connection) -> int:
    """Merge imported broker layouts by name while preserving local IDs/links."""
    rows = source.execute("""SELECT name,default_currency,notes,locked_fields_json,header_signature_json,
        mappings_json,configuration_version FROM brokers ORDER BY name""").fetchall()
    for row in rows:
        existing = target.execute("SELECT id,configuration_version FROM brokers WHERE name=?", (row["name"],)).fetchone()
        if existing:
            target.execute("""UPDATE brokers SET default_currency=?,notes=?,locked_fields_json=?,
                header_signature_json=?,mappings_json=?,configuration_version=? WHERE id=?""",
                (row["default_currency"], row["notes"], row["locked_fields_json"],
                 row["header_signature_json"], row["mappings_json"],
                 max(int(existing["configuration_version"]), int(row["configuration_version"])) + 1,
                 existing["id"]))
        else:
            target.execute("""INSERT INTO brokers(name,default_currency,notes,locked_fields_json,
                header_signature_json,mappings_json,configuration_version) VALUES(?,?,?,?,?,?,?)""",
                (row["name"], row["default_currency"], row["notes"], row["locked_fields_json"],
                 row["header_signature_json"], row["mappings_json"], row["configuration_version"]))
    return len(rows)


def import_export(target: sqlite3.Connection, source_path: Path, categories: Iterable[str]) -> dict[str, int]:
    requested = validate_categories(categories)
    source = _open_and_validate(source_path, requested, target)
    counts: dict[str, int] = {}
    try:
        target.execute("SAVEPOINT database_transfer")
        clear_categories(target, requested)
        for category in requested:
            count = 0
            if category == "brokerage":
                for table in BROKERAGE_TABLES:
                    count += _copy_table(source, target, table)
            elif category == "broker-definitions":
                # A brokerage bundle already copied its brokers together with
                # the dependent accounts and statements; avoid re-upserting
                # those definitions a second time in the same import.
                if "brokerage" not in requested:
                    count += _copy_broker_definitions(source, target)
            elif category == "planning-settings":
                for table in PLANNING_TABLES:
                    count += _copy_table(source, target, table)
            elif category in STATIC_CATEGORY_VALUES:
                count += _copy_table(source, target, "static_accounts", "WHERE category = ?", (STATIC_CATEGORY_VALUES[category],), omit_id=True)
            else:
                for table in SINGLE_TABLE_CATEGORIES[category]:
                    count += _copy_table(source, target, table)
            counts[category] = count
        violations = target.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise TransferError("The import would create invalid related records.")
        target.execute("RELEASE SAVEPOINT database_transfer")
        return counts
    except Exception:
        target.execute("ROLLBACK TO SAVEPOINT database_transfer")
        target.execute("RELEASE SAVEPOINT database_transfer")
        raise
    finally:
        source.close()
