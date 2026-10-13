# SPDX-FileCopyrightText: Copyright (C) Arun Sriraman
# SPDX-License-Identifier: GPL-3.0-only
import sqlite3

import pytest

from backend.app.db.schema import init_db
from backend.app.services import mfapi_service
from backend.app.services.price_service import refresh_security


SCHEMES = [
    {"schemeCode": 1, "schemeName": "Aditya Birla Sun Life Flexi Cap Fund - Regular Plan - Growth"},
    {"schemeCode": 2, "schemeName": "Bandhan Small Cap Fund - Regular Plan - Growth"},
    {"schemeCode": 3, "schemeName": "Invesco India Large & Mid Cap Fund - Direct Plan - Growth"},
    {"schemeCode": 4, "schemeName": "Invesco India Large & Mid Cap Fund - Regular Plan - Growth"},
]


def test_scheme_matching_normalizes_statement_plan_names_and_rejects_ambiguous_names():
    assert mfapi_service.resolve_scheme("ADITYA BIRLA SUN LIFE FLEXI CAP FUND REGULAR-GROWTH", SCHEMES)[0] == "1"
    assert mfapi_service.resolve_scheme("bandhan small cap fund regular - growth", SCHEMES)[0] == "2"
    with pytest.raises(ValueError, match="ambiguous"):
        mfapi_service.resolve_scheme("Invesco India Large & Mid Cap Fund", SCHEMES)


def test_indian_mutual_fund_price_refresh_uses_stored_mfapi_code(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    security_id = conn.execute("""INSERT INTO securities(symbol,name,security_type,allocation_category,exchange,
        investment_country,mfapi_scheme_code) VALUES (NULL,'Bandhan Small Cap Fund','Mutual Fund','Equity','NSE','India','100')""").lastrowid
    monkeypatch.setattr(mfapi_service, "fetch_latest", lambda code: mfapi_service.MfapiQuote("100", "Bandhan Small Cap Fund", 42.5, "2026-09-26"))
    # price_service imported this symbol directly, so replace its bound reference too.
    monkeypatch.setattr("backend.app.services.price_service.fetch_mfapi_latest", mfapi_service.fetch_latest)

    result = refresh_security(conn, security_id)

    assert result.refreshed and result.price == 42.5
    row = conn.execute("SELECT price, price_date, provider FROM price_history").fetchone()
    assert tuple(row) == (42.5, "2026-09-26", "mfapi")


def test_latest_rejects_invalid_nav_and_date(monkeypatch):
    monkeypatch.setattr(mfapi_service, "_request_json", lambda _url: {"meta": {"scheme_name": "Fund"}, "data": [{"nav": "0", "date": "bad"}]})
    with pytest.raises(ValueError, match="invalid NAV"):
        mfapi_service.fetch_latest("100")


def test_scheme_list_is_cached_locally_and_can_be_forced_to_refresh(monkeypatch, tmp_path):
    monkeypatch.setattr(mfapi_service, "MFAPI_SCHEMES_PATH", tmp_path / "mfapi_schemes.json")
    calls = []
    monkeypatch.setattr(mfapi_service, "_download_schemes", lambda: calls.append(True) or SCHEMES)

    assert mfapi_service.fetch_schemes() == SCHEMES
    assert mfapi_service.fetch_schemes() == SCHEMES
    assert calls == [True]
    result = mfapi_service.refresh_scheme_cache()
    assert result["scheme_count"] == len(SCHEMES)
    assert calls == [True, True]
