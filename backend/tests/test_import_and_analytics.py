# SPDX-FileCopyrightText: Copyright (C) Arun Sriraman
# SPDX-License-Identifier: GPL-3.0-only
import pytest

from backend.app.core.encryption import generate_salt, key_manager
from backend.app.db.schema import init_db
from backend.app.services.asset_service import create_real_estate_asset, create_static_account
from backend.app.services.broker_service import preview_broker_configuration, save_broker
from backend.app.services.import_service import commit_statement, preview_statement
from backend.app.services.models import BrokerDraft, ImportCommitRequest, ImportPreviewRequest, RealEstateAssetCreate, StaticAccountCreate
from backend.app.services.portfolio_service import dashboard, list_positions, profit_loss, update_position, update_positions
from backend.app.services.models import PositionUpdate
from backend.app.services.repositories import clean_brokerage_data


def unlock():
    key_manager.setup("correct horse battery staple", generate_salt())


def broker_for(conn, csv_text: str, *, name="Configured broker", locks=None):
    headers = csv_text.splitlines()[0].split(",")
    mapping = {
        "account_number": "Account", "symbol": "Symbol", "security_name": "Name", "security_type": "Type",
        "units": "Units", "total_cost_basis": "Cost", "per_unit_cost_basis": "Cost Per Unit",
        "total_fmv": "Value", "per_unit_fmv": "Price", "currency": "Currency", "exchange": "Exchange",
        "investment_country": "Country", "allocation_category": "Allocation", "sector": "Sector", "lot_number": "Lot", "acquisition_date": "Purchase Date",
    }
    mapping = {field: column for field, column in mapping.items() if column in headers}
    draft = BrokerDraft(name=name, default_currency="USD", locked_fields=locks or [], header_signature=headers, mappings=mapping)
    preview = preview_broker_configuration(conn, draft, csv_text, "USD")
    assert preview.valid, preview.errors
    return save_broker(conn, draft, preview)


def request_for(conn, broker, csv_text, statement_date, *, locks=None):
    preview = preview_statement(conn, ImportPreviewRequest(
        broker_id=broker["id"], csv_text=csv_text, statement_date=statement_date, locked_fields=locks,
    ))
    assert not preview.errors, preview.errors
    return ImportCommitRequest(
        broker_id=broker["id"], csv_text=csv_text, statement_date=statement_date,
        locked_fields=locks, expected_configuration_version=preview.configuration_version,
    )


CSV = """Account,Symbol,Name,Type,Units,Cost,Value,Currency,Exchange,Country,Allocation,Sector,Lot
A-1234,AAPL,Apple Inc,Stock,10,1500,2200,USD,NASDAQ,United States,Large Cap,Technology,L1
A-1234,VTI,Vanguard Total Market ETF,ETF,5,1000,1500,USD,NYSE,United States,Hybrid Fund,Diversified,L2
A-1234,CASH,Cash,Cash,550,550,550,USD,Unresolved,United States,Cash,Unclassified,CASH
"""


def test_configured_import_populates_dashboard_and_current_positions(sqlite_conn):
    init_db(sqlite_conn); unlock()
    broker = broker_for(sqlite_conn, CSV)
    result = commit_statement(sqlite_conn, request_for(sqlite_conn, broker, CSV, "2026-06-30"))
    assert result.imported_rows == 3
    assert {p.symbol for p in list_positions(sqlite_conn)} == {"AAPL", "VTI", "CASH"}
    assert next(p for p in list_positions(sqlite_conn) if p.symbol == "AAPL").security_type == "Equity"
    analytics = dashboard(sqlite_conn)
    assert analytics.brokerage_value == 4250
    assert {point.label for point in analytics.asset_allocation} >= {"Large Cap", "Hybrid Fund", "Cash"}


def test_configured_import_is_duplicate_safe_and_derives_values(sqlite_conn):
    init_db(sqlite_conn); unlock()
    csv = "Account,Symbol,Name,Type,Units,Cost Per Unit,Price\nA-1,AAPL,Apple,Stock,10,150,220\n"
    broker = broker_for(sqlite_conn, csv)
    request = request_for(sqlite_conn, broker, csv, "2026-06-30")
    assert not commit_statement(sqlite_conn, request).duplicate
    assert commit_statement(sqlite_conn, request).duplicate
    position = list_positions(sqlite_conn)[0]
    assert (position.total_cost_basis, position.total_fmv) == (1500, 2200)


def test_import_distinguishes_same_security_lots_by_acquisition_date_and_cost_basis(sqlite_conn):
    init_db(sqlite_conn); unlock()
    first = """Account,Symbol,Name,Type,Units,Cost,Value,Currency,Exchange,Country,Allocation,Sector,Purchase Date
A-1,AAPL,Apple,Stock,10,1000,2000,USD,NASDAQ,United States,Large Cap,Technology,2024-01-15
A-1,AAPL,Apple,Stock,10,1500,2000,USD,NASDAQ,United States,Large Cap,Technology,2024-01-15
"""
    broker = broker_for(sqlite_conn, first)
    commit_statement(sqlite_conn, request_for(sqlite_conn, broker, first, "2026-06-30"))

    second = first.replace(",10,1000,2000,", ",11,1100,2200,").replace(",10,1500,2000,", ",12,1800,2400,")
    preview = preview_statement(sqlite_conn, ImportPreviewRequest(broker_id=broker["id"], csv_text=second, statement_date="2026-07-31"))
    assert (len(preview.new_rows), len(preview.modified_rows), len(preview.deleted_rows)) == (0, 2, 0)
    commit_statement(sqlite_conn, ImportCommitRequest(broker_id=broker["id"], csv_text=second, statement_date="2026-07-31", expected_configuration_version=preview.configuration_version))

    current = sorted(list_positions(sqlite_conn), key=lambda position: position.per_unit_cost_basis or 0)
    assert [(position.units, position.per_unit_cost_basis) for position in current] == [(11, 100), (12, 150)]


def test_import_locks_preserve_prior_lot_values_without_changing_broker_defaults(sqlite_conn):
    init_db(sqlite_conn); unlock()
    first = "Account,Symbol,Name,Type,Units,Cost,Value,Lot\nA-1,AAPL,Apple,Stock,10,1000,2000,L1\n"
    second = "Account,Symbol,Name,Type,Units,Cost,Value,Lot\nA-1,AAPL,Changed,Stock,12,1800,2520,L1\n"
    broker = broker_for(sqlite_conn, first)
    commit_statement(sqlite_conn, request_for(sqlite_conn, broker, first, "2026-06-30"))
    preview = preview_statement(sqlite_conn, ImportPreviewRequest(broker_id=broker["id"], csv_text=second, statement_date="2026-07-31", locked_fields=["security_name", "total_cost_basis"]))
    assert preview.rows[0].security_name == "Apple"
    commit_statement(sqlite_conn, ImportCommitRequest(broker_id=broker["id"], csv_text=second, statement_date="2026-07-31", locked_fields=["security_name", "total_cost_basis"], expected_configuration_version=preview.configuration_version))
    current = list_positions(sqlite_conn)[0]
    assert (current.snapshot_date, current.security_name, current.units, current.total_cost_basis) == ("2026-07-31", "Apple", 12, 1000)
    assert broker["locked_fields"] == []


def test_import_currency_and_manual_position_update_keep_native_values(sqlite_conn):
    init_db(sqlite_conn); unlock()
    csv = "Account,Symbol,Name,Type,Units,Cost,Value,Currency\nA-1,INFY,Infosys,Stock,10,15000,18000,INR\n"
    broker = broker_for(sqlite_conn, csv)
    commit_statement(sqlite_conn, request_for(sqlite_conn, broker, csv, "2026-06-30"))
    original = list_positions(sqlite_conn)[0]
    updated = update_position(sqlite_conn, original.id, PositionUpdate(
        security_name=original.security_name, symbol=original.symbol, security_type=original.security_type,
        allocation_category=original.allocation_category, sector=original.sector, exchange=original.exchange,
        investment_country=original.investment_country, snapshot_date=original.snapshot_date, units=4,
        per_unit_cost_basis=100, total_cost_basis=None, per_unit_fmv=None, total_fmv=900, currency="INR",
    ))
    assert (updated.total_cost_basis, updated.per_unit_fmv, updated.total_fmv) == (400, 225, 900)
    assert profit_loss(sqlite_conn)[0].currency == "INR"


def test_position_update_can_move_to_an_encrypted_broker_account(sqlite_conn):
    init_db(sqlite_conn); unlock()
    broker = broker_for(sqlite_conn, CSV)
    commit_statement(sqlite_conn, request_for(sqlite_conn, broker, CSV, "2026-06-30"))
    original = next(position for position in list_positions(sqlite_conn) if position.symbol == "AAPL")
    original_account_id = sqlite_conn.execute("SELECT account_id FROM positions WHERE id=?", (original.id,)).fetchone()[0]
    updated = update_position(sqlite_conn, original.id, PositionUpdate(
        account_number="A-9999", security_name=original.security_name, symbol=original.symbol,
        security_type=original.security_type, allocation_category=original.allocation_category,
        sector=original.sector, exchange=original.exchange, investment_country=original.investment_country,
        snapshot_date=original.snapshot_date, units=original.units,
        per_unit_cost_basis=original.per_unit_cost_basis, total_cost_basis=original.total_cost_basis,
        per_unit_fmv=original.per_unit_fmv, total_fmv=original.total_fmv, currency=original.currency,
    ))
    assert (updated.account_number, updated.account_mask) == ("A-9999", "****9999")
    assert sqlite_conn.execute("SELECT COUNT(*) FROM accounts WHERE account_mask = '****9999'").fetchone()[0] == 1
    target_account_id = sqlite_conn.execute("SELECT id FROM accounts WHERE account_mask = '****9999'").fetchone()[0]
    assert sqlite_conn.execute("SELECT COUNT(*) FROM positions WHERE account_id=?", (original_account_id,)).fetchone()[0] == 0
    assert sqlite_conn.execute("SELECT COUNT(*) FROM statement_imports WHERE account_id=?", (original_account_id,)).fetchone()[0] == 0
    assert sqlite_conn.execute("SELECT COUNT(*) FROM positions WHERE account_id=?", (target_account_id,)).fetchone()[0] == 3
    assert sqlite_conn.execute("SELECT COUNT(*) FROM statement_imports WHERE account_id=?", (target_account_id,)).fetchone()[0] == 1


def test_bulk_position_update_rolls_back_every_item_after_a_validation_failure(sqlite_conn):
    init_db(sqlite_conn); unlock()
    broker = broker_for(sqlite_conn, CSV)
    commit_statement(sqlite_conn, request_for(sqlite_conn, broker, CSV, "2026-06-30"))
    original = next(position for position in list_positions(sqlite_conn) if position.symbol == "AAPL")
    valid = PositionUpdate(
        security_name=original.security_name, symbol=original.symbol, security_type=original.security_type,
        allocation_category=original.allocation_category, sector=original.sector, exchange=original.exchange,
        investment_country=original.investment_country, snapshot_date=original.snapshot_date, units=99,
        per_unit_cost_basis=original.per_unit_cost_basis, total_cost_basis=original.total_cost_basis,
        per_unit_fmv=original.per_unit_fmv, total_fmv=original.total_fmv, currency=original.currency,
    )
    invalid = valid.model_copy(update={"security_name": ""})

    with pytest.raises(ValueError, match="not found"):
        update_positions(sqlite_conn, [(original.id, valid), (999999, invalid)])

    assert sqlite_conn.execute("SELECT units FROM positions WHERE id=?", (original.id,)).fetchone()[0] == original.units


def test_brokerage_cleaning_preserves_config_and_net_worth_includes_other_assets(sqlite_conn):
    init_db(sqlite_conn); unlock()
    broker = broker_for(sqlite_conn, CSV)
    commit_statement(sqlite_conn, request_for(sqlite_conn, broker, CSV, "2026-06-30"))
    create_static_account(sqlite_conn, StaticAccountCreate(category="Bank Account", entity_name="Bank", account_type="Checking", account_holder="Primary", amount=1000, currency="USD"))
    create_real_estate_asset(sqlite_conn, RealEstateAssetCreate(property_info="Home", purchase_value=300000, current_value=350000, currency="USD"))
    value = dashboard(sqlite_conn)
    assert value.total_net_worth == 355250
    clean_brokerage_data(sqlite_conn)
    assert not list_positions(sqlite_conn)
    assert sqlite_conn.execute("SELECT COUNT(*) FROM brokers").fetchone()[0] == 1
