# SPDX-FileCopyrightText: Copyright (C) Arun Sriraman
# SPDX-License-Identifier: GPL-3.0-only
from backend.app.db.schema import init_db
from backend.app.services.asset_service import create_static_account
from backend.app.services.broker_service import save_broker
from backend.app.services.insight_service import insights, replace_targets
from backend.app.services.models import AllocationTarget, BrokerDraft, StaticAccountCreate
from backend.app.services.portfolio_service import create_position, dashboard, delete_position_history, list_positions
from backend.app.services.models import PositionCreate


def _broker(conn):
    return save_broker(conn, BrokerDraft(name="Draft broker"), None)


def _position(broker_name, snapshot):
    return PositionCreate(broker_name=broker_name, account_number="A1", security_name="Fund", symbol="FND", security_type="ETF", allocation_category="Equity", sector="Diversified", exchange="NYSE", investment_country="United States", snapshot_date=snapshot, acquisition_date="2024-01-01", lot_number="L1", units=1, total_cost_basis=100, total_fmv=100, currency="USD")


def test_delete_position_removes_all_matching_history(sqlite_conn):
    init_db(sqlite_conn); broker = _broker(sqlite_conn)
    first = create_position(sqlite_conn, _position(broker["name"], "2026-01-01"))
    create_position(sqlite_conn, _position(broker["name"], "2026-02-01"))
    delete_position_history(sqlite_conn, first.id)
    assert list_positions(sqlite_conn) == []


def test_retirement_is_dynamic_asset_and_policy_allocation(sqlite_conn):
    init_db(sqlite_conn); broker = _broker(sqlite_conn)
    create_position(sqlite_conn, _position(broker["name"], "2026-01-01"))
    create_static_account(sqlite_conn, StaticAccountCreate(category="Retirement Account", entity_name="IRA", account_type="IRA", account_holder="Owner", amount=100, currency="USD"))
    allocations = {row.label: row.value for row in dashboard(sqlite_conn).asset_allocation}
    assert allocations["Retirement"] == 100
    replace_targets(sqlite_conn, "asset_category", [AllocationTarget(dimension="asset_category", label="Equity", target_percent=50), AllocationTarget(dimension="asset_category", label="Retirement", target_percent=50)])
    drift = {row.label: row for row in insights(sqlite_conn).allocation_drift["asset_category"]}
    assert drift["Retirement"].actual_percent == 50
