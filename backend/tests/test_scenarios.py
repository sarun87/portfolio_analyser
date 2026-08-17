import sqlite3
import csv
from datetime import date
from pathlib import Path

import pytest

from backend.app.db.schema import init_db
from backend.app.services.insight_service import create_goal, replace_targets, save_assumptions
from backend.app.services.models import (
    AllocationTarget, FinancialAssumptions, GoalCreate, ScenarioInput, ScenarioPositionChange,
    StressTestRequest,
)
from backend.app.services.scenario_service import (
    analyze_scenario, delete_scenario, list_scenarios, run_stress_test, save_scenario, update_scenario,
)


@pytest.fixture
def portfolio():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_db(conn)
    broker_id = conn.execute("INSERT INTO brokers(name) VALUES ('Fidelity')").lastrowid
    account_id = conn.execute("INSERT INTO accounts (broker_id, account_number_enc, account_mask, account_fingerprint) VALUES (?, 'enc', '****1234', 'scenario-account')", (broker_id,)).lastrowid
    import_id = conn.execute("INSERT INTO statement_imports (broker_id, account_id, statement_date, row_count, fingerprint, status, detected_columns, errors_json) VALUES (?, ?, ?, 2, 'scenario-import', 'imported', '[]', '[]')", (broker_id, account_id, date.today().isoformat())).lastrowid
    stock_id = conn.execute("INSERT INTO securities (symbol, name, security_type, allocation_category, exchange, investment_country) VALUES ('AAA', 'Alpha', 'Stock', 'Large Cap', 'NYSE', 'United States')").lastrowid
    cash_id = conn.execute("INSERT INTO securities (symbol, name, security_type, allocation_category, exchange, investment_country, price_refresh_supported) VALUES (NULL, 'Cash', 'Cash', 'Cash', 'Unresolved', 'Unresolved', 0)").lastrowid
    conn.execute("INSERT INTO positions (import_id, account_id, security_id, snapshot_date, acquisition_date, units, total_cost_basis, total_fmv, currency) VALUES (?, ?, ?, ?, '2020-01-01', 8, 400, 800, 'USD')", (import_id, account_id, stock_id, date.today().isoformat()))
    conn.execute("INSERT INTO positions (import_id, account_id, security_id, snapshot_date, units, total_cost_basis, total_fmv, currency) VALUES (?, ?, ?, ?, 200, 200, 200, 'USD')", (import_id, account_id, cash_id, date.today().isoformat()))
    replace_targets(conn, "asset_category", [AllocationTarget(dimension="asset_category", label="Large Cap", target_percent=80), AllocationTarget(dimension="asset_category", label="Cash", target_percent=20)])
    save_assumptions(conn, FinancialAssumptions(expected_annual_return=.05, annual_volatility=.1, inflation_rate=.02, monthly_household_contribution=0, monthly_expenses=100, short_term_tax_rate=.3, long_term_tax_rate=.15))
    goal = create_goal(conn, GoalCreate(name="Immediate goal", target_amount=1000, target_currency="USD", target_month=date.today().strftime("%Y-%m"), allocated_amount=500, allocated_currency="USD", monthly_contribution=0, contribution_currency="USD"))
    yield conn, stock_id, goal.id
    conn.close()


@pytest.fixture
def multi_currency_portfolio(portfolio):
    conn, stock_id, goal_id = portfolio
    base = conn.execute("SELECT import_id, account_id, security_id FROM positions WHERE security_id != ? LIMIT 1", (stock_id,)).fetchone()
    conn.execute("UPDATE securities SET sector='Information Technology' WHERE id=?", (stock_id,))
    conn.execute("INSERT INTO positions (import_id, account_id, security_id, snapshot_date, acquisition_date, units, total_cost_basis, total_fmv, currency) VALUES (?, ?, ?, ?, '2020-01-01', 10, 4175, 8350, 'INR')", (base["import_id"], base["account_id"], stock_id, date.today().isoformat()))
    conn.execute("INSERT INTO positions (import_id, account_id, security_id, snapshot_date, units, total_cost_basis, total_fmv, currency) VALUES (?, ?, ?, ?, 8350, 8350, 8350, 'INR')", (base["import_id"], base["account_id"], base["security_id"], date.today().isoformat()))
    bond_id = conn.execute("INSERT INTO securities (symbol, name, security_type, allocation_category, sector, exchange, investment_country) VALUES ('BONDETF', 'Bond ETF', 'ETF', 'Bonds', 'Diversified', 'NYSE', 'United States')").lastrowid
    conn.execute("INSERT INTO positions (import_id, account_id, security_id, snapshot_date, acquisition_date, units, total_cost_basis, total_fmv, currency) VALUES (?, ?, ?, ?, '2020-01-01', 1, 100, 100, 'USD')", (base["import_id"], base["account_id"], bond_id, date.today().isoformat()))
    return conn, stock_id, bond_id, goal_id


def test_scenario_is_non_destructive_and_compares_cash_tax_drift_and_goals(portfolio):
    conn, stock_id, goal_id = portfolio
    before = [tuple(row) for row in conn.execute("SELECT id, units, total_fmv FROM positions ORDER BY id")]
    payload = ScenarioInput(name="Fund and rebalance", contribution=100, position_changes=[ScenarioPositionChange(security_id=stock_id, value_change=100)], goal_allocation_changes={goal_id: 600})

    result = analyze_scenario(conn, payload)

    assert result.current.portfolio_value == 1000
    assert result.proposed.portfolio_value == 1100
    assert result.proposed.cash_value == 200
    assert result.goals[0].current_probability == 0
    assert result.goals[0].proposed_probability == 100
    assert [tuple(row) for row in conn.execute("SELECT id, units, total_fmv FROM positions ORDER BY id")] == before

    sale = analyze_scenario(conn, ScenarioInput(name="Sale", position_changes=[ScenarioPositionChange(security_id=stock_id, value_change=-200)]))
    assert sale.proposed.portfolio_value == 1000
    assert sale.proposed.cash_value == 400
    assert sale.estimated_realized_gain == 100
    assert sale.estimated_tax == 15


def test_saved_scenario_crud(portfolio):
    conn, stock_id, _ = portfolio
    created = save_scenario(conn, ScenarioInput(name="Saved", position_changes=[ScenarioPositionChange(security_id=stock_id, value_change=10)]))
    assert list_scenarios(conn)[0].name == "Saved"
    updated = update_scenario(conn, created.id, ScenarioInput(name="Renamed"))
    assert updated.name == "Renamed"
    delete_scenario(conn, created.id)
    assert list_scenarios(conn) == []


def test_stress_presets_custom_shocks_contributors_and_goals(portfolio):
    conn, stock_id, _ = portfolio
    result = run_stress_test(conn, StressTestRequest(preset="market_crash"))
    assert result.current_value == 1000
    assert result.stressed_value == 760
    assert result.projected_loss == -240
    assert result.projected_loss_percent == -24
    assert result.cash_runway_months == 2
    assert result.contributors[0].security_name == "Alpha"
    assert result.goals[0].stressed_allocated == 380
    assert result.assumptions

    custom = run_stress_test(conn, StressTestRequest(category_shocks={"Large Cap": -10}, security_shocks={stock_id: -5}))
    assert custom.contributors[0].shock_percent == -15
    assert custom.projected_loss == -120


def test_scenario_rejects_negative_holdings_and_unavailable_cash(portfolio):
    conn, stock_id, _ = portfolio
    with pytest.raises(ValueError, match="negative"):
        analyze_scenario(conn, ScenarioInput(name="Too much", position_changes=[ScenarioPositionChange(security_id=stock_id, value_change=-900)]))
    with pytest.raises(ValueError, match="more cash"):
        analyze_scenario(conn, ScenarioInput(name="Overspend", withdrawal=300))


def test_inr_fixture_and_currency_specific_scenarios(multi_currency_portfolio):
    conn, stock_id, _, _ = multi_currency_portfolio
    with Path("backend/fixtures/scenario_inr_positions.csv").open() as fixture:
        rows = list(csv.DictReader(fixture))
    assert rows and {row["Currency"] for row in rows} == {"INR"}
    with pytest.raises(ValueError, match="multiple currencies"):
        analyze_scenario(conn, ScenarioInput(name="Ambiguous", position_changes=[ScenarioPositionChange(security_id=stock_id, value_change=10)]))
    result = analyze_scenario(conn, ScenarioInput(name="INR sale", position_changes=[ScenarioPositionChange(security_id=stock_id, currency="INR", value_change=-50)]))
    assert result.current.portfolio_value == pytest.approx(1300)
    assert result.proposed.portfolio_value == pytest.approx(1300)
    assert result.estimated_realized_gain == pytest.approx(25)


def test_scenario_uses_all_cash_holdings_and_preserves_negative_balances(multi_currency_portfolio):
    conn, _, _, _ = multi_currency_portfolio
    withdrawn = analyze_scenario(conn, ScenarioInput(name="Use both cash currencies", withdrawal=250))
    assert withdrawn.proposed.cash_value == pytest.approx(50)
    assert withdrawn.proposed.portfolio_value == pytest.approx(1050)

    base = conn.execute("SELECT import_id, account_id FROM positions LIMIT 1").fetchone()
    debt_cash_id = conn.execute("INSERT INTO securities (symbol, name, security_type, allocation_category, sector, exchange, investment_country, price_refresh_supported) VALUES (NULL, 'Margin cash', 'Cash', 'Cash', 'Unclassified', 'Margin', 'United States', 0)").lastrowid
    conn.execute("INSERT INTO positions (import_id, account_id, security_id, snapshot_date, units, total_fmv, currency) VALUES (?, ?, ?, ?, -400, -400, 'USD')", (base["import_id"], base["account_id"], debt_cash_id, date.today().isoformat()))
    signed = analyze_scenario(conn, ScenarioInput(name="Signed balances"))
    assert signed.current.portfolio_value == pytest.approx(900)
    assert signed.current.cash_value == pytest.approx(-100)
    assert signed.current.cash_runway_months == 0


def test_unknown_acquisition_date_makes_tax_unknown(portfolio):
    conn, _, _ = portfolio
    base = conn.execute("SELECT import_id, account_id FROM positions LIMIT 1").fetchone()
    unknown_id = conn.execute("INSERT INTO securities (symbol, name, security_type, allocation_category, sector, exchange, investment_country) VALUES ('UNKNOWN', 'Unknown date', 'Stock', 'Large Cap', 'Industrials', 'NYSE', 'United States')").lastrowid
    conn.execute("INSERT INTO positions (import_id, account_id, security_id, snapshot_date, units, total_cost_basis, total_fmv, currency) VALUES (?, ?, ?, ?, 1, 50, 100, 'USD')", (base["import_id"], base["account_id"], unknown_id, date.today().isoformat()))
    result = analyze_scenario(conn, ScenarioInput(name="Unknown tax", position_changes=[ScenarioPositionChange(security_id=unknown_id, currency="USD", value_change=-50)]))
    assert result.estimated_realized_gain == 25
    assert result.estimated_tax is None


def test_stress_handles_inr_cash_bond_etfs_sectors_and_multiple_shocks(multi_currency_portfolio):
    conn, stock_id, bond_id, _ = multi_currency_portfolio
    currency = run_stress_test(conn, StressTestRequest(currency_shocks={"INR": -10}))
    inr_rows = [row for row in currency.contributors if row.currency == "INR"]
    assert len(inr_rows) == 2
    assert all(row.shock_percent == -10 for row in inr_rows)
    assert currency.projected_loss == pytest.approx(-20)
    assert currency.cash_runway_months == pytest.approx(2.9)

    rate = run_stress_test(conn, StressTestRequest(interest_rate_change_bps=200))
    bond = next(row for row in rate.contributors if row.security_id == bond_id)
    assert bond.shock_percent == -10
    historical = run_stress_test(conn, StressTestRequest(preset="2008_style"))
    assert next(row for row in historical.contributors if row.security_id == bond_id).shock_percent == 5

    combined = run_stress_test(conn, StressTestRequest(sector_shocks={"Information Technology": -10}, security_shocks={stock_id: -5}))
    stock_rows = [row for row in combined.contributors if row.security_id == stock_id]
    assert {row.shock_percent for row in stock_rows} == {-15}
    with pytest.raises(ValueError, match="base currency"):
        run_stress_test(conn, StressTestRequest(currency_shocks={"USD": -5}))


def test_existing_database_gets_sector_column_migration():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE securities (
        id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, name TEXT NOT NULL, security_type TEXT NOT NULL,
        allocation_category TEXT NOT NULL DEFAULT 'Unclassified', classification_source TEXT, classified_at TEXT,
        price_refresh_supported INTEGER NOT NULL DEFAULT 1, exchange TEXT NOT NULL DEFAULT 'Unresolved',
        investment_country TEXT NOT NULL DEFAULT 'Unresolved', location_source TEXT, location_resolved_at TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(symbol, exchange)
    )""")
    init_db(conn)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(securities)")}
    assert "sector" in columns
    assert conn.execute("SELECT sector FROM securities").fetchall() == []
    conn.close()
