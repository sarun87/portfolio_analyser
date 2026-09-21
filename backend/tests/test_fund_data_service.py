import sqlite3
from types import SimpleNamespace

import pandas as pd

from backend.app.db.schema import init_db
from backend.app.services import fund_data_service
from backend.app.services.exposure_service import exposure_analysis
from backend.app.services.exposure_service import save_composition
from backend.app.services.insight_service import insights
from backend.app.services.models import FundCompositionInput, FundConstituentInput


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    broker = conn.execute("INSERT INTO brokers(name) VALUES ('Broker')").lastrowid
    account = conn.execute("INSERT INTO accounts(broker_id,account_number_enc,account_mask,account_fingerprint) VALUES (?, 'x', 'x', 'x')", (broker,)).lastrowid
    imported = conn.execute("INSERT INTO statement_imports(broker_id,account_id,statement_date,row_count,fingerprint,status,detected_columns) VALUES (?, ?, '2026-09-01', 1, 'f', 'ok', '[]')", (broker, account)).lastrowid
    security = conn.execute("INSERT INTO securities(symbol,name,security_type,allocation_category,exchange,investment_country) VALUES ('CNDX','Fund','ETFs and Closed End Funds','Equity','LSE','United Kingdom')").lastrowid
    conn.execute("INSERT INTO positions(import_id,account_id,security_id,snapshot_date,units,total_fmv,currency) VALUES (?, ?, ?, '2026-09-01', 1, 100, 'USD')", (imported, account, security))
    return conn, security


def test_refresh_uses_lse_symbol_and_preserves_old_data_on_error(monkeypatch):
    conn, security = _conn()
    history = pd.DataFrame({"Open":[1, 2], "High":[2, 3], "Low":[.5, 1], "Close":[1.5, 2.5], "Adj Close":[1.4, 2.4], "Volume":[10, 11]}, index=pd.to_datetime(["2026-09-01", "2026-09-02"]))
    holdings = pd.DataFrame({"Name":["Apple"], "Holding Percent":[.1]}, index=["AAPL"])
    fake = SimpleNamespace(info={"netExpenseRatio": .0003, "category":"Large Blend"}, history=lambda **_: history,
                           funds_data=SimpleNamespace(top_holdings=holdings, sector_weightings={"technology": .2}))
    seen = []
    def ticker(symbol):
        seen.append(symbol)
        return fake
    monkeypatch.setattr(fund_data_service.yf, "Ticker", ticker)
    result = fund_data_service.refresh_fund_data(conn, [security])[0]
    assert result.refreshed and seen == ["CNDX.L"]
    assert conn.execute("SELECT COUNT(*) FROM fund_constituents").fetchone()[0] == 1
    monkeypatch.setattr(fund_data_service.yf, "Ticker", lambda _: (_ for _ in ()).throw(RuntimeError("offline")))
    failed = fund_data_service.refresh_fund_data(conn, [security])[0]
    assert not failed.refreshed
    assert conn.execute("SELECT COUNT(*) FROM fund_constituents").fetchone()[0] == 1


def test_provider_sector_weights_do_not_add_top_holding_residual_twice(monkeypatch):
    conn, security = _conn()
    history = pd.DataFrame({"Close":[1.0, 2.0]}, index=pd.to_datetime(["2026-09-01", "2026-09-02"]))
    holdings = pd.DataFrame({"Name":["Apple"], "Holding Percent":[.1]}, index=["AAPL"])
    fake = SimpleNamespace(info={}, history=lambda **_: history,
                           funds_data=SimpleNamespace(top_holdings=holdings, sector_weightings={"technology": 1.0}))
    monkeypatch.setattr(fund_data_service.yf, "Ticker", lambda _: fake)
    assert fund_data_service.refresh_fund_data(conn, [security])[0].refreshed
    result = exposure_analysis(conn)
    assert [(row.label, row.value) for row in result.sector] == [("Technology", 100)]


def test_alphabet_share_classes_merge_in_direct_and_look_through_analytics():
    conn, _ = _conn()
    conn.execute("DELETE FROM positions")
    account = conn.execute("SELECT id FROM accounts").fetchone()["id"]
    imported = conn.execute("SELECT id FROM statement_imports").fetchone()["id"]
    def security(symbol, name, kind):
        return conn.execute("INSERT INTO securities(symbol,name,security_type,allocation_category,exchange,investment_country) VALUES (?,? ,? ,'Equity','NASDAQ','United States')", (symbol, name, kind)).lastrowid
    goog, googl, qqq = security("GOOG", "Alphabet Class C", "Stock"), security("GOOGL", "Alphabet Class A", "Stock"), security("QQQ", "QQQ", "ETF")
    conn.executemany("INSERT INTO positions(import_id,account_id,security_id,snapshot_date,units,total_fmv,currency) VALUES (?, ?, ?, '2026-09-01', 1, ?, 'USD')", [(imported, account, goog, 100000), (imported, account, googl, 50000), (imported, account, qqq, 500000)])
    save_composition(conn, qqq, FundCompositionInput(source="yfinance", holdings_scope="top_10", constituents=[
        FundConstituentInput(constituent_key="GOOG", symbol="GOOG", name="Alphabet Inc.", weight_percent=10),
    ]))
    direct = insights(conn)
    alphabet = next(row for row in direct.concentration if row.label == "Alphabet (GOOG/GOOGL)")
    assert alphabet.value == 150000
    effective = exposure_analysis(conn)
    alphabet_effective = next(row for row in effective.company if row.label == "Alphabet (GOOG/GOOGL)")
    assert alphabet_effective.value == 200000
    assert alphabet_effective.percent == 200000 / 650000 * 100


def test_alphabet_classes_overlap_even_when_provider_identifiers_differ():
    conn, _ = _conn()
    account = conn.execute("SELECT id FROM accounts").fetchone()["id"]
    imported = conn.execute("SELECT id FROM statement_imports").fetchone()["id"]
    left = conn.execute("INSERT INTO securities(symbol,name,security_type,allocation_category,exchange,investment_country) VALUES ('FUND1','Fund 1','ETF','Equity','NYSE','United States')").lastrowid
    right = conn.execute("INSERT INTO securities(symbol,name,security_type,allocation_category,exchange,investment_country) VALUES ('FUND2','Fund 2','ETF','Equity','NYSE','United States')").lastrowid
    conn.executemany("INSERT INTO positions(import_id,account_id,security_id,snapshot_date,units,total_fmv,currency) VALUES (?, ?, ?, '2026-09-01', 1, 100, 'USD')", [(imported, account, left), (imported, account, right)])
    save_composition(conn, left, FundCompositionInput(constituents=[FundConstituentInput(constituent_key="GOOG", identifier="US02079K1079", symbol="GOOG", name="Alphabet", weight_percent=8)]))
    save_composition(conn, right, FundCompositionInput(constituents=[FundConstituentInput(constituent_key="GOOGL", identifier="US02079K3059", symbol="GOOGL", name="Alphabet", weight_percent=6)]))
    overlap = next(item for item in exposure_analysis(conn).overlaps if {item.left_security_id, item.right_security_id} == {left, right})
    assert overlap.overlap_percent == 6
