import sqlite3
from datetime import date
from unittest.mock import patch

import pytest

from backend.app.db.schema import init_db
from backend.app.services.insight_service import (
    create_goal,
    get_assumptions,
    insights,
    list_goals_summary,
    replace_targets,
    save_assumptions,
    snapshot_comparison, save_scheduled_expense, list_scheduled_expenses,
)
from backend.app.services.models import AllocationTarget, FinancialAssumptions, GoalCreate, ScheduledExpenseInput
from backend.app.services.fx_service import fetch_latest_rates


@pytest.fixture
def configured_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_db(conn)
    conn.execute("INSERT INTO brokers(name) VALUES ('Fidelity')")
    yield conn
    conn.close()


def test_goal_conversion_allocation_warning_and_projection_setup(configured_conn):
    conn = configured_conn
    conn.execute("INSERT INTO static_accounts (category, entity_name, account_type, account_holder, currency, amount) VALUES ('Bank Account', 'Bank', 'Savings', 'A', 'USD', 1000)")
    create_goal(conn, GoalCreate(name="Deposit", target_amount=2000, target_currency="USD", target_month="2030-01", allocated_amount=1500, allocated_currency="USD", monthly_contribution=100, contribution_currency="USD"))
    summary = list_goals_summary(conn)
    assert summary.investable_financial_assets == 1000
    assert summary.over_allocated is True
    assert insights(conn).projection_setup_required is True

    save_assumptions(conn, FinancialAssumptions(expected_annual_return=.07, annual_volatility=.1, inflation_rate=.02, monthly_household_contribution=50, monthly_expenses=100, current_age=40, end_age=85))
    projected_goal = list_goals_summary(conn).goals[0]
    assert projected_goal.projected_shortfall_surplus == pytest.approx(projected_goal.projected_value - projected_goal.target_amount_display)
    result = insights(conn)
    assert result.projection_setup_required is False
    assert result.forecast["monte_carlo_terminal"]["p50"] >= 0
    assert result.forecast["end_age"] == 85
    assert result.forecast["series"][-1]["age"] == 85


def test_target_sets_must_total_100_and_goal_date_is_valid(configured_conn):
    with pytest.raises(ValueError, match="100%"):
        replace_targets(configured_conn, "currency", [AllocationTarget(dimension="currency", label="USD", target_percent=99)])
    targets = replace_targets(configured_conn, "currency", [AllocationTarget(dimension="currency", label="USD", target_percent=100, tolerance_percent=27)])
    assert targets[0].target_percent == 100
    assert targets[0].tolerance_percent == 27
    with pytest.raises(ValueError, match="YYYY-MM"):
        create_goal(configured_conn, GoalCreate(name="Bad", target_amount=1, target_currency="USD", target_month="January", allocated_amount=0, allocated_currency="USD", monthly_contribution=0, contribution_currency="USD"))


def test_lifetime_projection_includes_scheduled_expenses_and_validates_ages(configured_conn):
    conn = configured_conn
    conn.execute("INSERT INTO static_accounts (category, entity_name, account_type, account_holder, currency, amount) VALUES ('Bank Account', 'Bank', 'Savings', 'A', 'USD', 1000)")
    with pytest.raises(ValueError, match="End age"):
        save_assumptions(conn, FinancialAssumptions(current_age=85, end_age=85))
    save_assumptions(conn, FinancialAssumptions(expected_annual_return=0, annual_volatility=0, inflation_rate=0, monthly_household_contribution=0, monthly_expenses=0, current_age=84, end_age=85))
    next_month = date.today().replace(day=1)
    year, month = (next_month.year + 1, 1) if next_month.month == 12 else (next_month.year, next_month.month + 1)
    expense = save_scheduled_expense(conn, ScheduledExpenseInput(name="Education", expense_type="date_range", amount=120, currency="USD", start_date=f"{year}-{month:02d}-01", end_date=f"{year}-{month:02d}-01"))
    assert list_scheduled_expenses(conn) == [expense]
    save_scheduled_expense(conn, ScheduledExpenseInput(name="Due now", expense_type="one_time", amount=100, currency="USD", expense_date=date.today().isoformat()))
    result = insights(conn).forecast
    assert result["series"][0]["p50"] == pytest.approx(900)
    assert result["monte_carlo_terminal"]["p50"] == pytest.approx(780)
    assert {"p10", "p50", "p80", "p95"} <= result["series"][-1].keys()


def test_allocation_policy_ranges_replace_fixed_drift_threshold(configured_conn):
    conn = configured_conn
    broker_id = conn.execute("SELECT id FROM brokers WHERE name = 'Fidelity'").fetchone()["id"]
    account_id = conn.execute("INSERT INTO accounts (broker_id, account_number_enc, account_mask, account_fingerprint) VALUES (?, 'enc', '****1', 'policy-account')", (broker_id,)).lastrowid
    import_id = conn.execute("INSERT INTO statement_imports (broker_id, account_id, statement_date, row_count, fingerprint, status, detected_columns, errors_json) VALUES (?, ?, '2026-08-01', 2, 'policy-import', 'imported', '[]', '[]')", (broker_id, account_id)).lastrowid
    large_id = conn.execute("INSERT INTO securities (symbol, name, security_type, allocation_category, exchange, investment_country) VALUES ('LARGE', 'Large', 'Stock', 'Large Cap', 'NYSE', 'United States')").lastrowid
    small_id = conn.execute("INSERT INTO securities (symbol, name, security_type, allocation_category, exchange, investment_country) VALUES ('SMALL', 'Small', 'Stock', 'Small Cap', 'NYSE', 'United States')").lastrowid
    conn.executemany("INSERT INTO positions (import_id, account_id, security_id, snapshot_date, units, total_fmv, currency) VALUES (?, ?, ?, '2026-08-01', 1, ?, 'USD')", [(import_id, account_id, large_id, 70), (import_id, account_id, small_id, 30)])
    replace_targets(conn, "asset_category", [
        AllocationTarget(dimension="asset_category", label="Large Cap", target_percent=50, tolerance_percent=10),
        AllocationTarget(dimension="asset_category", label="Small Cap", target_percent=50, tolerance_percent=10),
    ])

    result = insights(conn)
    policy_rows = {row.label: row for row in result.allocation_drift["asset_category"]}
    assert policy_rows["Large Cap"].minimum_percent == 40
    assert policy_rows["Large Cap"].maximum_percent == 60
    assert policy_rows["Large Cap"].outside_range_percent == pytest.approx(10)
    assert policy_rows["Large Cap"].compliant is False
    assert result.allocation_policy.breached_targets == 2
    finding = next(item for item in result.findings if item.id == "policy-asset_category-Large Cap")
    assert finding.category == "allocation_policy"
    assert finding.navigation["page"] == "analytics"
    assert finding.navigation["section"] == "allocation_policy"
    assert "40.0%–60.0%" in finding.title


def test_fx_refresh_parses_frankfurter_v2_list_response():
    class Response:
        def read(self):
            return b'[{"base":"USD","quote":"INR","rate":83.5},{"base":"USD","quote":"EUR","rate":0.92}]'

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    with patch("backend.app.services.fx_service.urllib.request.urlopen", return_value=Response()):
        assert fetch_latest_rates("USD") == {"INR": 83.5, "EUR": 0.92}


def test_concentration_aggregates_lots_and_accounts_and_includes_cash(configured_conn):
    conn = configured_conn
    broker_id = conn.execute("SELECT id FROM brokers WHERE name = 'Fidelity'").fetchone()["id"]
    for index in (1, 2):
        conn.execute("INSERT INTO accounts (broker_id, account_number_enc, account_mask, account_fingerprint) VALUES (?, ?, ?, ?)", (broker_id, f"enc-{index}", f"****000{index}", f"account-{index}"))
    account_ids = [row["id"] for row in conn.execute("SELECT id FROM accounts ORDER BY id")]
    conn.execute("INSERT INTO statement_imports (broker_id, account_id, statement_date, row_count, fingerprint, status, detected_columns, errors_json) VALUES (?, ?, '2026-07-31', 4, 'insights-test', 'imported', '[]', '[]')", (broker_id, account_ids[0]))
    import_id = conn.execute("SELECT id FROM statement_imports WHERE fingerprint = 'insights-test'").fetchone()["id"]
    securities = [("AAPL", "Apple", "Stock"), (None, "Cash", "Cash"), ("MSFT", "Microsoft", "Stock")]
    for symbol, name, security_type in securities:
        conn.execute("INSERT INTO securities (symbol, name, security_type, allocation_category, exchange, investment_country, price_refresh_supported) VALUES (?, ?, ?, ?, 'Unresolved', 'United States', ?)", (symbol, name, security_type, security_type, 0 if security_type == "Cash" else 1))
    security_ids = {row["name"]: row["id"] for row in conn.execute("SELECT id, name FROM securities")}
    positions = [
        (account_ids[0], security_ids["Apple"], 100, "USD"),
        (account_ids[0], security_ids["Apple"], 50, "USD"),
        (account_ids[1], security_ids["Apple"], 150, "USD"),
        (account_ids[1], security_ids["Cash"], 100, "USD"),
        (account_ids[1], security_ids["Microsoft"], 92, "EUR"),
    ]
    conn.executemany("INSERT INTO positions (import_id, account_id, security_id, snapshot_date, units, total_fmv, currency) VALUES (?, ?, ?, '2026-07-31', 1, ?, ?)", [(import_id, account, security, value, currency) for account, security, value, currency in positions])

    result = insights(conn)

    assert {row.label: round(row.value, 2) for row in result.concentration} == {"Apple": 300, "Microsoft": 100, "Cash": 100}
    assert result.concentration[0].label == "Apple"
    assert result.top_5_share == pytest.approx(100)
    assert result.top_10_share == pytest.approx(100)


def test_review_inbox_and_snapshot_comparison_are_explainable_and_non_destructive(configured_conn):
    conn = configured_conn
    broker_id = conn.execute("SELECT id FROM brokers WHERE name = 'Fidelity'").fetchone()["id"]
    conn.execute("INSERT INTO accounts (broker_id, account_number_enc, account_mask, account_fingerprint) VALUES (?, 'enc', '****1234', 'comparison-account')", (broker_id,))
    account_id = conn.execute("SELECT id FROM accounts WHERE account_fingerprint = 'comparison-account'").fetchone()["id"]
    conn.execute("INSERT INTO statement_imports (broker_id, account_id, statement_date, row_count, fingerprint, status, detected_columns, errors_json) VALUES (?, ?, '2026-08-01', 6, 'comparison-import', 'imported', '[]', '[]')", (broker_id, account_id))
    import_id = conn.execute("SELECT id FROM statement_imports WHERE fingerprint = 'comparison-import'").fetchone()["id"]
    for symbol, name, kind, category in [("AAPL", "Apple", "Stock", "Large Cap"), (None, "Cash", "Cash", "Cash"), ("MSFT", "Microsoft", "Stock", "Large Cap"), ("GOOG", "Alphabet", "Stock", "Large Cap")]:
        conn.execute("INSERT INTO securities (symbol, name, security_type, allocation_category, exchange, investment_country) VALUES (?, ?, ?, ?, 'NASDAQ', 'United States')", (symbol, name, kind, category))
    ids = {row["name"]: row["id"] for row in conn.execute("SELECT id, name FROM securities")}
    conn.execute("INSERT INTO accounts (broker_id, account_number_enc, account_mask, account_fingerprint) VALUES (?, 'enc2', '****5678', 'staggered-account')", (broker_id,))
    staggered_account_id = conn.execute("SELECT id FROM accounts WHERE account_fingerprint = 'staggered-account'").fetchone()["id"]
    rows = [
        ("2026-07-01", ids["Apple"], 5, 500), ("2026-07-01", ids["Cash"], 100, 100),
        ("2026-08-01", ids["Apple"], 5, 600), ("2026-08-01", ids["Cash"], 400, 400),
        ("2026-08-01", ids["Microsoft"], 1, 100),
    ]
    conn.executemany("INSERT INTO positions (import_id, account_id, security_id, snapshot_date, units, total_fmv, currency) VALUES (?, ?, ?, ?, ?, ?, 'USD')", [(import_id, account_id, security_id, snapshot_date, units, value) for snapshot_date, security_id, units, value in rows])
    conn.execute("INSERT INTO positions (import_id, account_id, security_id, snapshot_date, units, total_fmv, currency) VALUES (?, ?, ?, '2026-07-15', 2, 200, 'USD')", (import_id, staggered_account_id, ids["Alphabet"]))
    before = conn.execute("SELECT COUNT(*) count FROM positions").fetchone()["count"]

    result = insights(conn)
    comparison = snapshot_comparison(conn)

    assert result.findings[0].category == "concentration"
    assert result.findings[0].confidence == "high"
    assert result.findings[0].evidence
    assert result.findings[0].suggested_actions
    assert len([finding for finding in result.findings if finding.category == "concentration"]) == 2
    assert comparison.available is True
    assert comparison.cash_change == 300
    assert comparison.new_holdings[0].security_name == "Microsoft"
    assert comparison.unusual_valuation_changes[0].security_name == "Apple"
    assert "Alphabet" not in {change.security_name for change in comparison.new_holdings + comparison.exited_holdings + comparison.position_changes + comparison.unusual_valuation_changes}
    assert "inferred" in comparison.disclosure.lower()
    assert conn.execute("SELECT COUNT(*) count FROM positions").fetchone()["count"] == before

    conn.execute("INSERT INTO app_settings (key, value) VALUES ('display_currency', 'INR') ON CONFLICT(key) DO UPDATE SET value='INR'")
    changed_display = insights(conn)
    assert not [finding for finding in changed_display.findings if finding.category == "currency_risk"]


def test_first_account_snapshot_is_coverage_not_inferred_activity(configured_conn):
    conn = configured_conn
    broker_id = conn.execute("SELECT id FROM brokers WHERE name = 'Fidelity'").fetchone()["id"]
    import_id = None
    for index, snapshot_date in enumerate(("2026-07-01", "2026-08-01"), start=1):
        account_id = conn.execute("INSERT INTO accounts (broker_id, account_number_enc, account_mask, account_fingerprint) VALUES (?, ?, ?, ?)", (broker_id, f"enc{index}", f"****{index}", f"coverage-{index}")).lastrowid
        current_import = conn.execute("INSERT INTO statement_imports (broker_id, account_id, statement_date, row_count, fingerprint, status, detected_columns, errors_json) VALUES (?, ?, ?, 1, ?, 'imported', '[]', '[]')", (broker_id, account_id, snapshot_date, f"coverage-import-{index}")).lastrowid
        security_id = conn.execute("INSERT INTO securities (symbol, name, security_type, allocation_category, exchange, investment_country) VALUES (?, ?, 'Stock', 'Large Cap', 'NYSE', 'United States')", (f"C{index}", f"Coverage {index}")).lastrowid
        conn.execute("INSERT INTO positions (import_id, account_id, security_id, snapshot_date, units, total_fmv, currency) VALUES (?, ?, ?, ?, 1, 100, 'USD')", (current_import, account_id, security_id, snapshot_date))
        import_id = current_import

    comparison = snapshot_comparison(conn)
    assert [change.security_name for change in comparison.coverage_changes] == ["Coverage 2"]
    assert comparison.new_holdings == []
    assert "cannot be inferred" in comparison.coverage_changes[0].activity_label


def test_stale_snapshot_is_checked_per_account(configured_conn):
    conn = configured_conn
    broker_id = conn.execute("SELECT id FROM brokers WHERE name = 'Fidelity'").fetchone()["id"]
    security_id = conn.execute("INSERT INTO securities (symbol, name, security_type, allocation_category, exchange, investment_country) VALUES ('OLD', 'Old holding', 'Stock', 'Large Cap', 'NYSE', 'United States')").lastrowid
    for index, snapshot_date in enumerate(("2025-01-01", date.today().isoformat()), start=1):
        account_id = conn.execute("INSERT INTO accounts (broker_id, account_number_enc, account_mask, account_fingerprint) VALUES (?, ?, ?, ?)", (broker_id, f"stale{index}", f"****S{index}", f"stale-account-{index}")).lastrowid
        import_id = conn.execute("INSERT INTO statement_imports (broker_id, account_id, statement_date, row_count, fingerprint, status, detected_columns, errors_json) VALUES (?, ?, ?, 1, ?, 'imported', '[]', '[]')", (broker_id, account_id, snapshot_date, f"stale-import-{index}")).lastrowid
        conn.execute("INSERT INTO positions (import_id, account_id, security_id, snapshot_date, units, total_fmv, currency) VALUES (?, ?, ?, ?, 1, 100, 'USD')", (import_id, account_id, security_id, snapshot_date))

    finding = next(finding for finding in insights(conn).findings if finding.id == "stale-snapshot")
    assert finding.title.startswith("1 account snapshot")


def test_snapshot_comparison_requires_two_snapshots(configured_conn):
    result = snapshot_comparison(configured_conn)
    assert result.available is False
    assert result.new_holdings == []
    assert "not confirmed" in result.disclosure.lower()
