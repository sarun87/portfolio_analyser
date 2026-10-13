# SPDX-FileCopyrightText: Copyright (C) Arun Sriraman
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import json
import math
import sqlite3
from numbers import Real
from datetime import datetime, timezone
from typing import Any

import yfinance as yf

from backend.app.services.exposure_service import _store_metadata, save_composition
from backend.app.services.location_service import normalize_exchange
from backend.app.services.mfapi_service import PROVIDER as MFAPI_PROVIDER, fetch_latest as fetch_mfapi_latest, fetch_schemes, is_indian_mutual_fund, resolve_scheme
from backend.app.services.price_service import GOOGLE_PROVIDER, fetch_security_quote, is_google_finance_symbol
from backend.app.services.repositories import record_price
from backend.app.services.models import (
    FundCompositionInput, FundConstituentInput, FundDataHolding,
    FundDataRefreshResult, FundDataSecurity,
)


PROVIDER = "yfinance"


def _eligible_type(security_type: str) -> bool:
    value = security_type.lower()
    return "etf" in value or value == "mutual fund"


def yahoo_symbol(symbol: str | None, exchange: str) -> str:
    if not symbol or not symbol.strip():
        raise ValueError("This fund has no ticker symbol to send to Yahoo Finance.")
    result = symbol.strip().upper()
    if normalize_exchange(exchange) == "LSE" and not result.endswith(".L"):
        result += ".L"
    return result


def _percent(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        return None
    return float(value * 100 if abs(value) <= 1 else value)


def _expense_ratio_percent(value: Any) -> float | None:
    """Yahoo's ``netExpenseRatio`` is already expressed in percentage points.

    Unlike yield, return, and holding-weight fields, a value of ``0.07`` means
    0.07%, not the fraction 0.07.  Keep that unit as-is because all persisted
    expense ratios and the UI use percentage points.
    """
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        return None
    return float(value) if 0 <= value <= 100 else None


def _facts(info: dict[str, Any]) -> dict[str, Any]:
    inception = info.get("fundInceptionDate")
    if isinstance(inception, (int, float)):
        inception = datetime.fromtimestamp(inception, timezone.utc).date().isoformat()
    else:
        inception = None
    return {
        "category": info.get("category"),
        "thesis": info.get("longBusinessSummary"),
        "fund_family": info.get("fundFamily"),
        "inception_date": inception,
        "assets_under_management": info.get("totalAssets") or info.get("netAssets"),
        "yield_percent": _percent(info.get("yield") or info.get("trailingAnnualDividendYield")),
        "turnover_percent": None,
        "beta": info.get("beta3Year"),
        "expense_ratio_percent": _expense_ratio_percent(info.get("netExpenseRatio")),
        "return_3y_percent": _percent(info.get("threeYearAverageReturn")),
        "return_5y_percent": _percent(info.get("fiveYearAverageReturn")),
        "return_10y_percent": None,
        "return_since_inception_percent": None,
    }


def _holdings(frame: Any) -> list[FundConstituentInput]:
    if frame is None or getattr(frame, "empty", True):
        return []
    records: list[FundConstituentInput] = []
    for symbol, row in frame.iterrows():
        weight = _percent(row.get("Holding Percent"))
        if not weight or weight <= 0:
            continue
        symbol_text = str(symbol).strip().upper()
        name = str(row.get("Name") or symbol_text).strip()
        records.append(FundConstituentInput(
            constituent_key=symbol_text or name.lower(), symbol=symbol_text or None,
            name=name, weight_percent=weight, sector="Unclassified", country="Unresolved",
            currency="Unresolved", asset_category="Equity",
        ))
    return records


def _sectors(data: Any) -> dict[str, float]:
    if not isinstance(data, dict):
        return {}
    result: dict[str, float] = {}
    for key, value in data.items():
        weight = _percent(value)
        if weight is not None and weight >= 0:
            result[str(key).replace("_", " ").title()] = weight
    return result


def _history(frame: Any) -> list[tuple[str, float | None, float | None, float | None, float | None, float | None, float | None]]:
    if frame is None or getattr(frame, "empty", True):
        return []
    rows = []
    for timestamp, row in frame.iterrows():
        close = row.get("Close")
        if not isinstance(close, Real) or not math.isfinite(close) or close <= 0:
            continue
        def number(name: str) -> float | None:
            value = row.get(name)
            return float(value) if isinstance(value, Real) and math.isfinite(value) else None
        rows.append((timestamp.date().isoformat(), number("Open"), number("High"), number("Low"), number("Close"), number("Adj Close"), number("Volume")))
    return rows


def _fund_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("""SELECT DISTINCT s.id, s.name, s.symbol, s.security_type, s.exchange, s.investment_country, s.mfapi_scheme_code
        FROM securities s JOIN positions p ON p.security_id=s.id
        WHERE p.snapshot_date=(SELECT MAX(p2.snapshot_date) FROM positions p2 WHERE p2.account_id=p.account_id)
        ORDER BY s.name""").fetchall()


def list_fund_data(conn: sqlite3.Connection) -> list[FundDataSecurity]:
    result = []
    for row in _fund_rows(conn):
        if not _eligible_type(row["security_type"]):
            continue
        status = conn.execute("SELECT * FROM fund_refresh_status WHERE security_id=?", (row["id"],)).fetchone()
        metadata = conn.execute("SELECT expense_ratio_percent FROM fund_metadata WHERE security_id=?", (row["id"],)).fetchone()
        holdings = [FundDataHolding(symbol=item["symbol"] or item["constituent_key"], name=item["name"], weight_percent=item["weight_percent"])
                    for item in conn.execute("SELECT constituent_key,symbol,name,weight_percent FROM fund_constituents WHERE fund_security_id=? ORDER BY weight_percent DESC", (row["id"],))]
        sectors = {item["sector"]: item["weight_percent"] for item in conn.execute("SELECT sector,weight_percent FROM fund_sector_weights WHERE fund_security_id=? ORDER BY weight_percent DESC", (row["id"],))}
        history_count = conn.execute("SELECT COUNT(*) AS count FROM fund_ohlcv_history WHERE fund_security_id=?", (row["id"],)).fetchone()["count"]
        try:
            resolved = yahoo_symbol(row["symbol"], row["exchange"])
        except ValueError:
            resolved = None
        indian_mf = is_indian_mutual_fund(row["security_type"], row["investment_country"])
        google_symbol = indian_mf and is_google_finance_symbol(row["symbol"])
        default_provider = GOOGLE_PROVIDER if google_symbol else MFAPI_PROVIDER if indian_mf else PROVIDER
        default_identifier = row["symbol"] if google_symbol else row["mfapi_scheme_code"] if indian_mf else resolved
        result.append(FundDataSecurity(
            security_id=row["id"], security_name=row["name"], security_type=row["security_type"], symbol=row["symbol"],
            yahoo_symbol=status["yahoo_symbol"] if status else resolved, provider=status["provider"] if status and status["provider"] else default_provider,
            provider_identifier=status["provider_identifier"] if status and status["provider_identifier"] else default_identifier, last_refreshed_at=status["refreshed_at"] if status else None,
            holdings_count=len(holdings), sector_count=len(sectors), history_count=history_count,
            expense_ratio_percent=metadata["expense_ratio_percent"] if metadata else None,
            warnings=json.loads(status["warnings_json"]) if status else [], holdings=holdings, sectors=sectors,
        ))
    return result


def _refresh_one_mfapi(conn: sqlite3.Connection, row: sqlite3.Row, schemes: list[dict[str, Any]] | None) -> FundDataRefreshResult:
    code = row["mfapi_scheme_code"]
    if not code:
        if schemes is None:
            raise ValueError("MFAPI scheme list is unavailable.")
        code, _ = resolve_scheme(row["name"], schemes)
    quote = fetch_mfapi_latest(code)
    now = datetime.now(timezone.utc).isoformat()
    # MFAPI latest supplies a NAV only. Existing composition and Yahoo-derived
    # facts/history remain intact rather than being erased by this refresh.
    warnings = ["MFAPI provides latest NAV only; existing holdings, sectors, and fund facts were retained."]
    conn.execute("UPDATE securities SET mfapi_scheme_code=? WHERE id=?", (quote.scheme_code, row["id"]))
    record_price(conn, row["id"], quote.nav, MFAPI_PROVIDER, quote.nav_date)
    conn.execute("""INSERT INTO fund_refresh_status(security_id,yahoo_symbol,provider,provider_identifier,refreshed_at,warnings_json) VALUES(?,?,?,?,?,?)
        ON CONFLICT(security_id) DO UPDATE SET provider=excluded.provider, provider_identifier=excluded.provider_identifier, refreshed_at=excluded.refreshed_at, warnings_json=excluded.warnings_json""", (row["id"], row["symbol"] or quote.scheme_code, MFAPI_PROVIDER, quote.scheme_code, now, json.dumps(warnings)))
    return FundDataRefreshResult(security_id=row["id"], security_name=row["name"], yahoo_symbol=None, refreshed=True, message="MFAPI NAV refreshed.", warnings=warnings)


def _refresh_one_google_price(conn: sqlite3.Connection, row: sqlite3.Row) -> FundDataRefreshResult:
    result = fetch_security_quote(row["id"], row["symbol"], row["exchange"])
    if not result.refreshed or result.price is None:
        raise ValueError(result.message)
    now = datetime.now(timezone.utc).isoformat()
    warnings = ["Google Finance provides latest price only; existing holdings, sectors, and fund facts were retained."]
    record_price(conn, row["id"], result.price, GOOGLE_PROVIDER)
    conn.execute("""INSERT INTO fund_refresh_status(security_id,yahoo_symbol,provider,provider_identifier,refreshed_at,warnings_json) VALUES(?,?,?,?,?,?)
        ON CONFLICT(security_id) DO UPDATE SET provider=excluded.provider, provider_identifier=excluded.provider_identifier, refreshed_at=excluded.refreshed_at, warnings_json=excluded.warnings_json""", (row["id"], row["symbol"], GOOGLE_PROVIDER, row["symbol"], now, json.dumps(warnings)))
    return FundDataRefreshResult(security_id=row["id"], security_name=row["name"], yahoo_symbol=None, refreshed=True, message="Google Finance price refreshed.", warnings=warnings)


def _refresh_one(conn: sqlite3.Connection, row: sqlite3.Row) -> FundDataRefreshResult:
    symbol = yahoo_symbol(row["symbol"], row["exchange"])
    fund = yf.Ticker(symbol)
    info = fund.info or {}
    history = _history(fund.history(period="1mo", auto_adjust=False))
    if len(history) < 2:
        raise ValueError("Yahoo Finance did not return enough valid 30-day price history.")
    funds_data = fund.funds_data
    holdings = _holdings(funds_data.top_holdings)
    sectors = _sectors(funds_data.sector_weightings)
    warnings = []
    if not holdings:
        warnings.append("Yahoo Finance did not provide top holdings for this fund.")
    if not sectors:
        warnings.append("Yahoo Finance did not provide sector weights for this fund.")
    facts = _facts(info)
    missing = [key for key, value in facts.items() if value is None]
    if missing:
        warnings.append("Unavailable fund facts: " + ", ".join(missing) + ".")
    now = datetime.now(timezone.utc).isoformat()
    save_composition(conn, row["id"], FundCompositionInput(source=PROVIDER, holdings_scope="top_10", as_of_date=None, constituents=holdings))
    _store_metadata(conn, row["id"], facts, PROVIDER, now, None)
    conn.execute("DELETE FROM fund_sector_weights WHERE fund_security_id=?", (row["id"],))
    conn.executemany("INSERT INTO fund_sector_weights(fund_security_id,sector,weight_percent) VALUES(?,?,?)", [(row["id"], sector, weight) for sector, weight in sectors.items()])
    conn.execute("DELETE FROM fund_ohlcv_history WHERE fund_security_id=?", (row["id"],))
    conn.executemany("""INSERT INTO fund_ohlcv_history(fund_security_id,price_date,open,high,low,close,adjusted_close,volume)
        VALUES(?,?,?,?,?,?,?,?)""", [(row["id"], *point) for point in history])
    conn.execute("""INSERT INTO fund_refresh_status(security_id,yahoo_symbol,provider,provider_identifier,refreshed_at,warnings_json) VALUES(?,?,?,?,?,?)
        ON CONFLICT(security_id) DO UPDATE SET yahoo_symbol=excluded.yahoo_symbol, provider=excluded.provider, provider_identifier=excluded.provider_identifier, refreshed_at=excluded.refreshed_at, warnings_json=excluded.warnings_json""", (row["id"], symbol, PROVIDER, symbol, now, json.dumps(warnings)))
    return FundDataRefreshResult(security_id=row["id"], security_name=row["name"], yahoo_symbol=symbol, refreshed=True,
                                 message="Fund data refreshed.", warnings=warnings)


def refresh_fund_data(conn: sqlite3.Connection, security_ids: list[int]) -> list[FundDataRefreshResult]:
    rows = {row["id"]: row for row in _fund_rows(conn)}
    results = []
    schemes: list[dict[str, Any]] | None = None
    for security_id in dict.fromkeys(security_ids):
        row = rows.get(security_id)
        if not row or not _eligible_type(row["security_type"]):
            results.append(FundDataRefreshResult(security_id=security_id, security_name="Unknown fund", refreshed=False, message="Security is not an eligible current fund."))
            continue
        conn.execute("SAVEPOINT fund_refresh")
        try:
            if is_indian_mutual_fund(row["security_type"], row["investment_country"]) and is_google_finance_symbol(row["symbol"]):
                result = _refresh_one_google_price(conn, row)
            elif is_indian_mutual_fund(row["security_type"], row["investment_country"]):
                if not row["mfapi_scheme_code"] and schemes is None:
                    schemes = fetch_schemes()
                result = _refresh_one_mfapi(conn, row, schemes)
            else:
                result = _refresh_one(conn, row)
        except Exception as exc:
            conn.execute("ROLLBACK TO SAVEPOINT fund_refresh")
            result = FundDataRefreshResult(security_id=row["id"], security_name=row["name"], refreshed=False,
                                           message=f"Refresh failed: {exc}")
        finally:
            conn.execute("RELEASE SAVEPOINT fund_refresh")
        results.append(result)
    return results
