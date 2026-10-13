# SPDX-FileCopyrightText: Copyright (C) Arun Sriraman
# SPDX-License-Identifier: GPL-3.0-only
import json
import sqlite3
import urllib.error
from unittest.mock import patch

import pytest

from backend.app.db.schema import init_db
from backend.app.services.price_service import fetch_google_finance_price, fetch_yahoo_price, google_candidates, refresh_security, yahoo_candidates
from backend.app.services.portfolio_service import list_positions, update_position
from backend.app.services.models import PositionUpdate
from backend.app.services.insight_service import snapshot_comparison


class Response:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class HtmlResponse:
    def __init__(self, html):
        self.html = html

    def read(self):
        return self.html.encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


@pytest.mark.parametrize("price", [0, -1, "not-a-number", float("nan"), True])
def test_fetch_yahoo_price_rejects_invalid_values(price):
    payload = {"chart": {"result": [{"meta": {"regularMarketPrice": price}}]}}
    with patch("backend.app.services.price_service.urllib.request.urlopen", return_value=Response(payload)):
        with pytest.raises(ValueError):
            fetch_yahoo_price("AAPL")


def test_fetch_yahoo_price_accepts_valid_value_and_rejects_missing_value():
    valid = {"chart": {"result": [{"meta": {"regularMarketPrice": 123.45}}]}}
    with patch("backend.app.services.price_service.urllib.request.urlopen", return_value=Response(valid)):
        assert fetch_yahoo_price("AAPL") == 123.45
    missing = {"chart": {"result": [{"meta": {}}]}}
    with patch("backend.app.services.price_service.urllib.request.urlopen", return_value=Response(missing)):
        with pytest.raises(ValueError, match="usable price"):
            fetch_yahoo_price("AAPL")


def test_google_finance_uses_the_primary_quote_not_a_sidebar_index():
    html = '<div class="YMlKec">24,156.95</div><div class="YMlKec fxKbKc">$827.78</div>'
    with patch("backend.app.services.price_service.urllib.request.urlopen", return_value=HtmlResponse(html)):
        assert fetch_google_finance_price("CSPX:LON") == 827.78


def test_google_finance_keeps_provider_qualified_mutual_fund_symbols_intact():
    symbol = "ADIT_BSL_FLEX_1UV3YZW:MUTF_IN"
    assert google_candidates(symbol, "NSE") == [symbol]
    html = '<div class="YMlKec fxKbKc">123.45</div>'
    with patch("backend.app.services.price_service.urllib.request.urlopen", return_value=HtmlResponse(html)) as opener:
        assert fetch_google_finance_price(symbol) == 123.45
    assert ":MUTF_IN" in opener.call_args.args[0].full_url


def test_google_finance_parses_current_mutual_fund_quote_markup():
    html = '<span jsname="Pdsbrc"><span>26,689.85</span></span><div class="N6SYTe"><span jsname="Pdsbrc" class=""><span>₹1,915.87</span></span></div>'
    with patch("backend.app.services.price_service.urllib.request.urlopen", return_value=HtmlResponse(html)):
        assert fetch_google_finance_price("ADIT_BSL_FLEX_1UV3YZW:MUTF_IN") == 1915.87


@pytest.fixture
def priced_security():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    broker_id = conn.execute("INSERT INTO brokers(name) VALUES ('Fidelity')").lastrowid
    account_id = conn.execute("INSERT INTO accounts (broker_id, account_number_enc, account_mask, account_fingerprint) VALUES (?, 'enc', '****1234', 'account')", (broker_id,)).lastrowid
    import_id = conn.execute("INSERT INTO statement_imports (broker_id, account_id, statement_date, row_count, fingerprint, status, detected_columns, errors_json) VALUES (?, ?, '2026-07-31', 1, 'price-test', 'imported', '[]', '[]')", (broker_id, account_id)).lastrowid
    security_id = conn.execute("INSERT INTO securities (symbol, name, security_type, allocation_category, exchange, investment_country) VALUES ('AAPL', 'Apple', 'Stock', 'Large Cap', 'NASDAQ', 'United States')").lastrowid
    conn.execute("INSERT INTO positions (import_id, account_id, security_id, snapshot_date, units, per_unit_fmv, total_fmv, currency) VALUES (?, ?, ?, '2026-07-31', 2, 100, 200, 'USD')", (import_id, account_id, security_id))
    yield conn, security_id
    conn.close()


@pytest.mark.parametrize("failure", [0, -10, urllib.error.URLError("offline")])
def test_refresh_failure_does_not_overwrite_position_fmv(priced_security, failure):
    conn, security_id = priced_security
    effect = failure if isinstance(failure, Exception) else None
    with patch("backend.app.services.price_service.fetch_yahoo_price", return_value=failure if effect is None else None, side_effect=effect), \
         patch("backend.app.services.price_service.fetch_google_finance_price", side_effect=ValueError("no quote")):
        result = refresh_security(conn, security_id)

    stored = conn.execute("SELECT per_unit_fmv, total_fmv FROM positions").fetchone()
    assert result.refreshed is False
    assert stored["per_unit_fmv"] == 100
    assert stored["total_fmv"] == 200
    assert conn.execute("SELECT COUNT(*) count FROM price_history").fetchone()["count"] == 0


def test_cspx_uses_google_london_quote_after_yahoo_failure(priced_security):
    conn, security_id = priced_security
    conn.execute("UPDATE securities SET symbol='CSPX', exchange='LSE' WHERE id=?", (security_id,))
    with patch("backend.app.services.price_service.fetch_yahoo_price", side_effect=urllib.error.HTTPError("url", 404, "not found", None, None)) as yahoo, \
         patch("backend.app.services.price_service.fetch_google_finance_price", return_value=827.78) as google:
        result = refresh_security(conn, security_id)

    assert result.refreshed is True
    assert result.price == 827.78
    assert yahoo.call_args_list[0].args == ("CSPX.L",)
    assert google.call_args_list[0].args == ("CSPX:LON",)
    stored = conn.execute("SELECT price, provider FROM price_history").fetchone()
    assert (stored["price"], stored["provider"]) == (827.78, "google-finance-html")


def test_manual_fmv_update_replaces_cached_market_quote(priced_security):
    conn, security_id = priced_security
    conn.execute("INSERT INTO price_history (security_id, price, price_date, provider) VALUES (?, 250, '2026-08-01', 'manual-test')", (security_id,))
    original = list_positions(conn)[0]
    assert original.total_fmv == 500

    updated = update_position(conn, original.id, PositionUpdate(
        security_name=original.security_name, symbol=original.symbol, security_type=original.security_type,
        allocation_category=original.allocation_category, sector=original.sector, exchange=original.exchange,
        investment_country=original.investment_country, snapshot_date=original.snapshot_date, units=original.units,
        per_unit_cost_basis=original.per_unit_cost_basis, total_cost_basis=original.total_cost_basis,
        per_unit_fmv=None, total_fmv=600, currency=original.currency,
    ))

    assert (updated.per_unit_fmv, updated.total_fmv) == (300, 600)
    assert conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0] == 0


@pytest.mark.parametrize("symbol", ["CSPX", "CNDX", "IWDA", "EIMI", "VDTA"])
def test_lse_funds_resolve_to_yahoo_and_google_london_identifiers(symbol):
    assert yahoo_candidates(symbol, "London Stock Exchange") == [f"{symbol}.L", symbol]
    assert google_candidates(symbol, "London Stock Exchange") == [f"{symbol}:LON", symbol]


@pytest.mark.parametrize("symbol", ["CSPX.L", "CNDX.L", "IWDA.L", "EIMI.L", "VDTA.L"])
def test_lse_yahoo_suffix_is_removed_before_building_google_identifier(symbol):
    assert google_candidates(symbol, "LSE") == [f"{symbol[:-2]}:LON", symbol[:-2]]


def test_valid_refresh_preserves_snapshot_and_overlays_latest_position_value(priced_security):
    conn, security_id = priced_security
    latest = conn.execute("SELECT import_id, account_id FROM positions").fetchone()
    conn.execute("INSERT INTO positions (import_id, account_id, security_id, snapshot_date, units, per_unit_fmv, total_fmv, currency) VALUES (?, ?, ?, '2026-06-30', 2, 75, 150, 'USD')", (latest["import_id"], latest["account_id"], security_id))
    before = snapshot_comparison(conn)
    with patch("backend.app.services.price_service.fetch_yahoo_price", return_value=125.5):
        result = refresh_security(conn, security_id)

    stored = conn.execute("SELECT per_unit_fmv, total_fmv FROM positions WHERE snapshot_date = '2026-07-31'").fetchone()
    assert result.refreshed is True
    assert stored["per_unit_fmv"] == 100
    assert stored["total_fmv"] == 200
    assert conn.execute("SELECT COUNT(*) count FROM price_history").fetchone()["count"] == 1
    current = list_positions(conn)[0]
    assert current.per_unit_fmv == 125.5
    assert current.total_fmv == 251
    after = snapshot_comparison(conn)
    assert after.total_value_change == before.total_value_change == 50
    assert after.unusual_valuation_changes == before.unusual_valuation_changes
