# SPDX-FileCopyrightText: Copyright (C) Arun Sriraman
# SPDX-License-Identifier: GPL-3.0-only
from datetime import date

from backend.app.core.encryption import generate_salt, key_manager
from backend.app.db.schema import init_db
from backend.app.services.fx_service import set_display_currency, set_fx_rate
from backend.app.services.models import FxRateUpdate
from backend.app.services.portfolio_service import capture_net_worth_snapshot, dashboard, net_worth_snapshot_history
from backend.app.services.repositories import clean_portfolio_data


def seed_net_worth(conn):
    init_db(conn)
    key_manager.setup("snapshot test passphrase", generate_salt())

    broker_id = conn.execute("INSERT INTO brokers(name) VALUES ('Snapshot Broker')").lastrowid
    account_id = conn.execute(
        """INSERT INTO accounts(broker_id, account_number_enc, account_mask, account_fingerprint)
           VALUES (?, ?, '1234', 'snapshot-account')""",
        (broker_id, key_manager.encrypt("1234")),
    ).lastrowid
    import_id = conn.execute(
        """INSERT INTO statement_imports(broker_id, account_id, statement_date, row_count, fingerprint,
           status, detected_columns) VALUES (?, ?, '2026-01-01', 1, 'snapshot-import', 'imported', '[]')""",
        (broker_id, account_id),
    ).lastrowid
    security_id = conn.execute(
        "INSERT INTO securities(symbol, name, security_type) VALUES ('SNAP', 'Snapshot Holding', 'Equity')"
    ).lastrowid
    conn.execute(
        """INSERT INTO positions(import_id, account_id, security_id, snapshot_date, units, total_fmv, currency)
           VALUES (?, ?, ?, '2026-01-01', 1, 100, 'USD')""",
        (import_id, account_id, security_id),
    )
    conn.execute(
        """INSERT INTO static_accounts(category, entity_name, account_type, account_holder, currency, amount)
           VALUES ('Bank Account', 'USD Bank', 'Checking', 'Owner', 'USD', 50),
                  ('Bank Account', 'INR Bank', 'Checking', 'Owner', 'INR', 1000)"""
    )
    conn.execute(
        "INSERT INTO real_estate_assets(property_info, purchase_value, current_value, currency) VALUES ('Home', 150, 200, 'USD')"
    )
    conn.execute(
        """INSERT INTO private_equity_assets(company_name, stage, share_class, quantity,
           purchase_price_per_unit, last_valuation_per_unit, currency)
           VALUES ('Private Co', 'Seed', 'Common', 2, 40, 50, 'USD')"""
    )
    conn.execute(
        "INSERT INTO liabilities(entity_name, liability_type, outstanding_balance, currency) VALUES ('Loan', 'Mortgage', 25, 'USD')"
    )
    set_fx_rate(conn, FxRateUpdate(from_currency="INR", to_currency="USD", rate=0.01))
    set_fx_rate(conn, FxRateUpdate(from_currency="USD", to_currency="INR", rate=80))
    conn.commit()


def test_snapshot_includes_all_assets_minus_liabilities_and_is_returned_by_dashboard(sqlite_conn):
    seed_net_worth(sqlite_conn)

    point = capture_net_worth_snapshot(sqlite_conn, date(2026, 1, 1))
    analytics = dashboard(sqlite_conn)

    assert point.value == 435
    assert analytics.total_net_worth == 435
    assert analytics.net_worth_growth == [point]
    assert analytics.portfolio_growth[0].value == 100


def test_snapshot_uses_capture_time_fx_after_currency_and_rates_change(sqlite_conn):
    seed_net_worth(sqlite_conn)
    capture_net_worth_snapshot(sqlite_conn, date(2026, 1, 1))

    set_fx_rate(sqlite_conn, FxRateUpdate(from_currency="USD", to_currency="INR", rate=90))
    set_display_currency(sqlite_conn, "INR")

    point = net_worth_snapshot_history(sqlite_conn)[0]
    assert point.value == 35_000


def test_recapturing_same_local_date_replaces_the_existing_point(sqlite_conn):
    seed_net_worth(sqlite_conn)
    snapshot_date = date(2026, 1, 1)
    first = capture_net_worth_snapshot(sqlite_conn, snapshot_date)
    sqlite_conn.execute("UPDATE static_accounts SET amount = 2000 WHERE entity_name = 'INR Bank'")

    updated = capture_net_worth_snapshot(sqlite_conn, snapshot_date)

    assert first.value == 435
    assert updated.value == 445
    assert sqlite_conn.execute("SELECT COUNT(*) FROM portfolio_net_worth_snapshots").fetchone()[0] == 1
    assert net_worth_snapshot_history(sqlite_conn) == [updated]


def test_cleaning_all_portfolio_data_removes_net_worth_history(sqlite_conn):
    seed_net_worth(sqlite_conn)
    capture_net_worth_snapshot(sqlite_conn, date(2026, 1, 1))

    clean_portfolio_data(sqlite_conn)

    assert net_worth_snapshot_history(sqlite_conn) == []
