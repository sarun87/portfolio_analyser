from datetime import date, timedelta
from unittest.mock import patch

import pytest

from backend.app.db.schema import init_db
from backend.app.services.exposure_service import _html_source_url, _parse_holdings_csv, exposure_analysis, get_composition, preview_public_metadata, save_composition
from backend.app.services.advanced_findings import advanced_findings
from backend.app.services.fee_service import (
    fee_analysis, list_security_fees, save_fee_settings, save_portfolio_fee, save_security_fee,
)
from backend.app.services.insight_service import save_assumptions
from backend.app.services.models import (
    FeeSettings, FinancialAssumptions, FundCompositionInput, FundConstituentInput,
    ManualMarketSeriesInput, MarketObservation, PortfolioFeeInput, SecurityFeeInput,
)
from backend.app.services.risk_service import (
    _returns, _store_series, refresh_market_history, risk_analysis, save_manual_market_series, save_risk_settings,
)
from backend.app.services.models import RiskSettings


@pytest.fixture
def advanced_portfolio(sqlite_conn):
    conn = sqlite_conn
    init_db(conn)
    broker = conn.execute("INSERT INTO brokers(name) VALUES ('Fidelity')").lastrowid
    account = conn.execute("INSERT INTO accounts(broker_id, account_number_enc, account_mask, account_fingerprint) VALUES (?, 'x', '****1', 'advanced')", (broker,)).lastrowid
    imported = conn.execute("""INSERT INTO statement_imports(broker_id, account_id, statement_date, row_count, fingerprint,
                              status, detected_columns, errors_json) VALUES (?, ?, '2026-08-01', 4, 'advanced', 'imported', '[]', '[]')""", (broker, account)).lastrowid

    def security(symbol, name, kind, category, sector, country):
        return conn.execute("""INSERT INTO securities(symbol,name,security_type,allocation_category,sector,exchange,investment_country)
                             VALUES (?, ?, ?, ?, ?, 'TEST', ?)""", (symbol, name, kind, category, sector, country)).lastrowid

    stock = security("AAA", "Alpha Ltd", "Stock", "Large Cap", "Information Technology", "United States")
    fund_a = security("FUNDA", "Fund A", "ETF", "Large Cap", "Diversified", "United States")
    fund_b = security("FUNDB", "Fund B", "Mutual Fund", "International", "Diversified", "India")
    cash = security("CASH", "Cash", "Cash", "Cash", "Unclassified", "United States")
    values = [(stock, 100, "USD"), (fund_a, 500, "USD"), (fund_b, 8350, "INR"), (cash, 200, "USD")]
    for security_id, value, currency in values:
        conn.execute("""INSERT INTO positions(import_id,account_id,security_id,snapshot_date,units,per_unit_fmv,total_fmv,currency)
                        VALUES (?, ?, ?, '2026-08-01', 1, ?, ?, ?)""", (imported, account, security_id, value, value, currency))
    save_composition(conn, fund_a, FundCompositionInput(as_of_date=date.today().isoformat(), constituents=[
        FundConstituentInput(constituent_key="AAA", symbol="AAA", name="Alpha Ltd", weight_percent=40,
                             sector="Information Technology", country="United States", currency="USD", asset_category="Large Cap"),
        FundConstituentInput(constituent_key="BBB", symbol="BBB", name="Beta Ltd", weight_percent=50,
                             sector="Financials", country="India", currency="INR", asset_category="Large Cap"),
    ]))
    save_composition(conn, fund_b, FundCompositionInput(as_of_date=date.today().isoformat(), constituents=[
        FundConstituentInput(constituent_key="AAA", symbol="AAA", name="Alpha Ltd", weight_percent=50,
                             sector="Information Technology", country="United States", currency="USD", asset_category="Large Cap"),
    ]))
    return conn, stock, fund_a, fund_b


def test_look_through_overlap_residual_currency_and_cycle_validation(advanced_portfolio):
    conn, stock, fund_a, fund_b = advanced_portfolio
    result = exposure_analysis(conn)
    alpha = next(row for row in result.company if row.key == "AAA")
    assert result.portfolio_value == pytest.approx(900)
    assert alpha.value == pytest.approx(350)
    assert set(alpha.sources) == {"Alpha Ltd", "Fund A", "Fund B"}
    assert result.composition_coverage_percent == pytest.approx(500 / 600 * 100)
    assert result.overlaps[0].overlap_percent == pytest.approx(40)
    assert any(row.label == "Unmapped" for row in result.currency)
    nested = FundCompositionInput(constituents=[FundConstituentInput(
        constituent_key="fund-b", linked_security_id=fund_b, name="Fund B", weight_percent=20,
    )])
    save_composition(conn, fund_a, nested)
    with pytest.raises(ValueError, match="cycle"):
        save_composition(conn, fund_b, FundCompositionInput(constituents=[FundConstituentInput(
            constituent_key="fund-a", linked_security_id=fund_a, name="Fund A", weight_percent=10,
        )]))


def test_public_metadata_is_a_draft_and_does_not_overwrite_manual_composition(advanced_portfolio):
    conn, _, fund_a, _ = advanced_portfolio
    before = get_composition(conn, fund_a)
    html = "<table><tr><th>Holding</th><th>Weight</th></tr><tr><td>Gamma CCC</td><td>12%</td></tr></table><p>Expense Ratio: 0.30%</p>"
    with patch("backend.app.services.exposure_service._fetch_html", return_value=html):
        preview = preview_public_metadata(conn, fund_a)
    after = get_composition(conn, fund_a)
    assert preview.composition.constituents[0].weight_percent == pytest.approx(12)
    assert preview.expense_ratio_percent == pytest.approx(.3)
    assert preview.composition.as_of_date is None
    assert after.constituents == before.constituents
    assert after.source == "manual"
    with patch("backend.app.services.exposure_service._fetch_html", side_effect=ValueError("offline")):
        with pytest.raises(ValueError, match="offline"):
            preview_public_metadata(conn, fund_a)
    assert get_composition(conn, fund_a).constituents == before.constituents


def test_generic_holdings_csv_parser_preserves_stable_identity_and_classification():
    raw = """iShares Fund\nFund Holdings as of,01/31/2026\nIssuer Ticker,Name,Sector,Asset Class,Weight (%),ISIN,Location,Market Currency\nAAPL,APPLE INC,Information Technology,Equity,7.15,US0378331005,United States,USD\nMSFT,MICROSOFT CORP,Information Technology,Equity,6.90,US5949181045,United States,USD\n"""
    holdings, as_of, warnings = _parse_holdings_csv(raw, "iShares")
    assert as_of == "2026-01-31"
    assert not warnings
    assert holdings[0].identifier == "US0378331005"
    assert holdings[0].country == "United States"
    assert holdings[0].asset_category == "Equity"


def test_generic_vanguard_csv_parser_accepts_holding_column_variants():
    raw = """Vanguard holdings\nHoldings as of,2026-01-31\nHolding Ticker,Holding Name,% of Net Assets,CUSIP,Sector\nAAPL,Apple Inc.,6.12,037833100,Technology\nMSFT,Microsoft Corp.,5.43,594918104,Technology\n"""
    holdings, as_of, warnings = _parse_holdings_csv(raw, "Vanguard")
    assert as_of == "2026-01-31"
    assert not warnings
    assert holdings[0].identifier == "037833100"
    assert holdings[0].symbol == "AAPL"


@pytest.mark.parametrize(("source", "url"), [
    ("ishares_csv", "https://www.ishares.com/uk/individual/en/literature/holdings.csv"),
    ("vanguard_csv", "https://investor.vanguard.com/investment-products/etfs/profile/holdings.csv"),
])
def test_provider_csv_urls_allow_their_provider_domains(source, url):
    assert _html_source_url("FUND", source, url)[0] == url


@pytest.mark.parametrize("source", ["ishares_csv", "vanguard_csv"])
def test_provider_csv_urls_reject_unrelated_hosts(source):
    with pytest.raises(ValueError, match="approved"):
        _html_source_url("FUND", source, "https://example.com/holdings.csv")


def _prices(start: float, daily_returns: list[float]):
    value = start
    points = []
    first = date(2026, 1, 1)
    for index, daily_return in enumerate(daily_returns):
        value *= 1 + daily_return
        points.append(((first + timedelta(days=index)).isoformat(), value))
    return points


def test_risk_decomposition_uses_inr_fx_benchmark_and_replaces_series(advanced_portfolio):
    conn, stock, fund_a, fund_b = advanced_portfolio
    returns = [.01 if index % 3 else -.006 for index in range(90)]
    _store_series(conn, f"security:{stock}", "security", "AAA", "USD", _prices(100, returns), "manual", stock)
    _store_series(conn, f"security:{fund_a}", "security", "FUNDA", "USD", _prices(100, [x*.7 for x in returns]), "manual", fund_a)
    _store_series(conn, f"security:{fund_b}", "security", "FUNDB", "INR", _prices(1000, [x*1.2 for x in returns]), "manual", fund_b)
    _store_series(conn, "benchmark:^GSPC", "benchmark", "^GSPC", "USD", _prices(100, [x*.8 for x in returns]), "manual")
    _store_series(conn, "fx:USD:INR", "fx", "USDINR=X", "INR", [(day, 83.5) for day, _ in _prices(1, returns)], "manual")
    save_risk_settings(conn, RiskSettings(benchmark_symbol="^GSPC", benchmark_currency="USD", minimum_observations=60))
    result = risk_analysis(conn)
    assert result.coverage_percent == pytest.approx(100)
    assert sum(item.portfolio_weight_percent for item in result.holdings) == pytest.approx(100)
    assert next(item for item in result.holdings if item.name == "Cash").risk_contribution_percent == 0
    assert result.covered_portfolio_volatility_percent > 0
    assert result.covered_portfolio_volatility_percent < max(item.annualized_volatility_percent for item in result.holdings)
    assert result.covered_portfolio_beta is not None
    assert all(item.risk_contribution_percent is not None for item in result.holdings)
    assert result.correlations
    _store_series(conn, f"security:{stock}", "security", "AAA", "USD", _prices(100, returns[:10]), "manual", stock)
    count = conn.execute("""SELECT COUNT(*) AS count FROM market_series_points p JOIN market_series s ON s.id=p.series_id
                            WHERE s.series_key=?""", (f"security:{stock}",)).fetchone()["count"]
    assert count == 10
    manual_fx = save_manual_market_series(conn, ManualMarketSeriesInput(
        series_key="fx:USD:INR", series_type="fx", symbol="USDINR=X", currency="INR",
        observations=[MarketObservation(date=day, adjusted_close=83.5) for day, _ in _prices(1, returns[:10])],
    ))
    assert manual_fx.observation_count == 10
    with patch("backend.app.services.risk_service.fetch_yahoo_history", side_effect=ValueError("offline")):
        refresh = refresh_market_history(conn)
    security_results = [item for item in refresh if item.series_key.startswith("security:")]
    assert security_results and all("Manual history preserved" in item.message for item in security_results)
    assert conn.execute("""SELECT COUNT(*) AS count FROM market_series_points p JOIN market_series s ON s.id=p.series_id
                           WHERE s.series_key='fx:USD:INR'""").fetchone()["count"] == 10


def test_fee_drag_inr_fixed_fee_reserve_and_long_term_projections(advanced_portfolio):
    conn, _, fund_a, fund_b = advanced_portfolio
    save_assumptions(conn, FinancialAssumptions(expected_annual_return=.05, annual_volatility=.1, inflation_rate=.02,
                                                monthly_household_contribution=0, monthly_expenses=10))
    save_fee_settings(conn, FeeSettings(cash_reserve_months=6))
    # Fund fees are now sourced from the yfinance-backed fund metadata.
    conn.execute("INSERT INTO fund_metadata(security_id, provider, expense_ratio_percent, reviewed_at) VALUES (?, 'yfinance', .5, CURRENT_TIMESTAMP)", (fund_a,))
    conn.execute("INSERT INTO fund_metadata(security_id, provider, expense_ratio_percent, reviewed_at) VALUES (?, 'yfinance', 1, CURRENT_TIMESTAMP)", (fund_b,))
    save_portfolio_fee(conn, PortfolioFeeInput(name="Advice", fee_type="advisory_percent", annual_percent=1,
                                               currency="USD"))
    save_portfolio_fee(conn, PortfolioFeeInput(name="HDFC account", fee_type="fixed_account", annual_amount=83.5,
                                               currency="INR"))
    result = fee_analysis(conn)
    assert result.annual_fund_expenses == pytest.approx(3.5)
    assert result.annual_advisory_fees == pytest.approx(9)
    assert result.annual_fixed_fees == pytest.approx(1)
    assert result.total_annual_fees == pytest.approx(13.5)
    assert result.reserve_target == pytest.approx(60)
    assert result.potential_idle_cash == pytest.approx(140)
    assert result.potential_cash_drag == pytest.approx(7)
    assert [item.years for item in result.projections] == [1, 10, 20, 30]
    assert result.projections[-1].opportunity_cost > result.projections[-1].cumulative_nominal_fees


def test_new_tables_are_added_to_an_existing_database(sqlite_conn):
    sqlite_conn.execute("CREATE TABLE app_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    init_db(sqlite_conn)
    tables = {row["name"] for row in sqlite_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"fund_compositions", "market_series", "security_fee_metadata", "portfolio_fees"} <= tables
    indexes = {row["name"] for row in sqlite_conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"idx_positions_account_snapshot_date", "idx_market_points_series_date", "idx_price_history_security_latest"} <= indexes


def test_rounding_above_100_is_normalized_without_overstating_exposure(advanced_portfolio):
    conn, _, fund_a, _ = advanced_portfolio
    save_composition(conn, fund_a, FundCompositionInput(constituents=[
        FundConstituentInput(constituent_key="round-a", symbol="RA", name="Round A", weight_percent=50.005),
        FundConstituentInput(constituent_key="round-b", symbol="RB", name="Round B", weight_percent=50),
    ]))
    result = exposure_analysis(conn)
    assert get_composition(conn, fund_a).coverage_percent == pytest.approx(100)
    for rows in (result.company, result.sector, result.country, result.currency, result.asset_category):
        assert sum(row.value for row in rows) == pytest.approx(result.portfolio_value)


def test_exited_holdings_are_excluded_from_overlap_fees_and_history_refresh(advanced_portfolio):
    conn, _, fund_a, _ = advanced_portfolio
    account = conn.execute("SELECT id, broker_id FROM accounts WHERE account_fingerprint='advanced'").fetchone()
    old_import = conn.execute("""INSERT INTO statement_imports(broker_id, account_id, statement_date, row_count, fingerprint,
                              status, detected_columns, errors_json) VALUES (?, ?, '2025-12-31', 1, 'exited', 'imported', '[]', '[]')""",
                              (account["broker_id"], account["id"])).lastrowid
    exited = conn.execute("""INSERT INTO securities(symbol,name,security_type,allocation_category,sector,exchange,investment_country)
                           VALUES ('EXIT','Exited Fund','ETF','Large Cap','Diversified','TEST','United States')""").lastrowid
    conn.execute("""INSERT INTO positions(import_id,account_id,security_id,snapshot_date,units,total_fmv,currency)
                    VALUES (?, ?, ?, '2025-12-31', 1, 100, 'USD')""", (old_import, account["id"], exited))
    save_composition(conn, exited, FundCompositionInput(constituents=[
        FundConstituentInput(constituent_key="AAA", symbol="AAA", name="Alpha Ltd", weight_percent=100),
    ]))
    exposure = exposure_analysis(conn)
    assert all(exited not in (row.left_security_id, row.right_security_id) for row in exposure.overlaps)
    assert exited not in [item.security_id for item in exposure.compositions]
    assert exited not in [item.security_id for item in list_security_fees(conn)]
    with patch("backend.app.services.risk_service.fetch_yahoo_history", side_effect=ValueError("offline")):
        refreshed = refresh_market_history(conn)
    assert f"security:{exited}" not in {item.series_key for item in refreshed}


def test_fee_projection_stops_charging_after_portfolio_depletion(advanced_portfolio):
    conn, _, _, _ = advanced_portfolio
    save_assumptions(conn, FinancialAssumptions(expected_annual_return=-1, annual_volatility=.1, inflation_rate=0,
                                                monthly_household_contribution=0, monthly_expenses=0))
    save_portfolio_fee(conn, PortfolioFeeInput(name="Fixed", fee_type="fixed_account", annual_amount=50, currency="USD"))
    result = fee_analysis(conn)
    assert result.projections[-1].ending_value_after_fees == 0
    assert result.projections[-1].cumulative_nominal_fees == 0


def test_returns_do_not_treat_missing_trading_dates_as_one_day():
    calendar = {"2026-01-01", "2026-01-02", "2026-01-03"}
    assert _returns({"2026-01-01": 100, "2026-01-03": 121}, calendar) == {}


def test_single_source_effective_concentration_generates_finding(advanced_portfolio):
    conn, _, fund_a, _ = advanced_portfolio
    save_composition(conn, fund_a, FundCompositionInput(constituents=[
        FundConstituentInput(constituent_key="ONLY", symbol="ONLY", name="Only Company", weight_percent=100),
    ]))
    findings = advanced_findings(conn)
    assert any(item.id == "look-through-ONLY" for item in findings)
