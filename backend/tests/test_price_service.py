import json
import sqlite3
import urllib.error
from unittest.mock import patch

import pytest

from backend.app.db.schema import init_db
from backend.app.services.price_service import fetch_yahoo_price, refresh_security
from backend.app.services.portfolio_service import list_positions
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
    with patch("backend.app.services.price_service.fetch_yahoo_price", return_value=failure if effect is None else None, side_effect=effect):
        result = refresh_security(conn, security_id)

    stored = conn.execute("SELECT per_unit_fmv, total_fmv FROM positions").fetchone()
    assert result.refreshed is False
    assert stored["per_unit_fmv"] == 100
    assert stored["total_fmv"] == 200
    assert conn.execute("SELECT COUNT(*) count FROM price_history").fetchone()["count"] == 0


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
