# SPDX-FileCopyrightText: Copyright (C) Arun Sriraman
# SPDX-License-Identifier: GPL-3.0-only
import json
import math
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from typing import Optional

from backend.app.core.external_api_logging import open_external_url
from backend.app.services.location_service import normalize_exchange
from backend.app.services.models import PriceRefreshResult
from backend.app.services.repositories import record_price
from backend.app.services.mfapi_service import PROVIDER as MFAPI_PROVIDER, fetch_latest as fetch_mfapi_latest, fetch_schemes, is_indian_mutual_fund, resolve_scheme


PROVIDER = "yahoo-chart"
GOOGLE_PROVIDER = "google-finance-html"
YAHOO_SUFFIXES = {"NSE": ".NS", "BSE": ".BO", "LSE": ".L", "SIX": ".SW", "SWX": ".SW", "ASX": ".AX", "TSX": ".TO"}
GOOGLE_EXCHANGES = {
    "LSE": "LON", "LONDON": "LON", "NASDAQ": "NASDAQ", "NYSE": "NYSE", "NYSEARCA": "NYSEARCA",
    "NSE": "NSE", "BSE": "BOM", "SIX": "SWX", "SWX": "SWX", "ASX": "ASX", "TSX": "TSE",
    "TSE": "TYO", "HKSE": "HKG", "XETRA": "ETR",
}


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def yahoo_candidates(symbol: str, exchange: Optional[str]) -> list[str]:
    base = symbol.strip().upper()
    suffix = YAHOO_SUFFIXES.get(normalize_exchange(exchange).upper())
    return _unique([f"{base}{suffix}" if suffix and "." not in base else base, base])


def google_candidates(symbol: str, exchange: Optional[str]) -> list[str]:
    base = symbol.strip().upper()
    normalized_exchange = normalize_exchange(exchange).upper()
    google_exchange = GOOGLE_EXCHANGES.get(normalized_exchange)
    yahoo_suffix = YAHOO_SUFFIXES.get(normalized_exchange)
    # Imports may already contain Yahoo-style listing symbols (for example
    # CSPX.L). Google Finance expects the base symbol plus its own exchange
    # code (CSPX:LON), not the Yahoo suffix.
    if yahoo_suffix and base.endswith(yahoo_suffix):
        base = base[:-len(yahoo_suffix)]
    return _unique([f"{base}:{google_exchange}" if google_exchange and ":" not in base else base, base])


def is_google_finance_symbol(symbol: Optional[str]) -> bool:
    """A provider-qualified ``SYMBOL:EXCHANGE`` identifier must stay on Google."""
    return bool(symbol and symbol.count(":") == 1 and all(part.strip() for part in symbol.split(":")))


def fetch_yahoo_price(symbol: str) -> float:
    encoded = urllib.parse.quote(symbol)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=1d&interval=1d"
    request = urllib.request.Request(url, headers={"User-Agent": "portfolio-analyser/1.0"})
    with open_external_url(request, provider=PROVIDER, timeout=10, opener=urllib.request.urlopen) as response:
        payload = json.loads(response.read().decode("utf-8"))
    result = payload.get("chart", {}).get("result", [])
    if not result:
        raise ValueError("No quote data returned.")
    meta = result[0].get("meta", {})
    price = meta.get("regularMarketPrice")
    if price is None:
        price = meta.get("previousClose")
    if price is None:
        raise ValueError("Quote response did not include a usable price.")
    if isinstance(price, bool):
        raise ValueError("Quote response included a non-numeric price.")
    try:
        numeric_price = float(price)
    except (TypeError, ValueError) as exc:
        raise ValueError("Quote response included a non-numeric price.") from exc
    if not math.isfinite(numeric_price) or numeric_price <= 0:
        raise ValueError("Quote response included an invalid price; the stored price was not changed.")
    return numeric_price


def fetch_google_finance_price(symbol: str) -> float:
    """Fetch the primary quote, never a market-index quote from the page chrome."""
    # Google Finance treats a colon as part of its symbol route (for example
    # ``ADIT_BSL_FLEX_1UV3YZW:MUTF_IN``). Encoding it produces a 404.
    url = f"https://www.google.com/finance/quote/{urllib.parse.quote(symbol, safe=':')}"
    # Google Finance serves some mutual-fund quote routes only to a standard
    # browser user agent; the lightweight app identifier is redirected to 404.
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36"})
    with open_external_url(request, provider=GOOGLE_PROVIDER, timeout=10, opener=urllib.request.urlopen) as response:
        html = response.read().decode("utf-8", errors="replace")
    # `fxKbKc` distinguishes the instrument quote from sidebar/index values
    # which also use `YMlKec` (CSPX:LON is a concrete example).
    match = re.search(r'class="(?=[^"]*\bYMlKec\b)(?=[^"]*\bfxKbKc\b)[^"]*"[^>]*>\s*([^<]+)', html)
    # Google Finance's current mutual-fund template uses Pdsbrc rather than
    # the fxKbKc quote class used by equities and ETFs. Restrict it to the
    # N6SYTe primary-quote container: Pdsbrc also appears in unrelated rows
    # further down the page.
    if not match:
        match = re.search(r'<div\s+class="N6SYTe"[^>]*>\s*<span\s+jsname="Pdsbrc"[^>]*>\s*<span>\s*([^<]+)', html)
    if not match:
        raise ValueError("Google Finance page did not include a usable quote.")
    numeric = re.search(r"[0-9][0-9,]*(?:\.\d+)?", match.group(1))
    if not numeric:
        raise ValueError("Google Finance page did not include a numeric quote.")
    price = float(numeric.group(0).replace(",", ""))
    if not math.isfinite(price) or price <= 0:
        raise ValueError("Google Finance page included an invalid price.")
    return price


def refresh_security(conn: sqlite3.Connection, security_id: int) -> PriceRefreshResult:
    row = conn.execute(
        "SELECT id, symbol, exchange, security_type, investment_country, mfapi_scheme_code, price_refresh_supported FROM securities WHERE id = ?",
        (security_id,),
    ).fetchone()
    if not row:
        return PriceRefreshResult(security_id=security_id, symbol=None, refreshed=False, message="Security not found.")
    if not row["price_refresh_supported"]:
        return PriceRefreshResult(
            security_id=security_id,
            symbol=row["symbol"],
            refreshed=False,
            message="Security does not support price refresh.",
        )
    if is_indian_mutual_fund(row["security_type"], row["investment_country"]) and not is_google_finance_symbol(row["symbol"]):
        name = conn.execute("SELECT name FROM securities WHERE id=?", (security_id,)).fetchone()["name"]
        return apply_quote_result(conn, fetch_indian_mutual_fund_quote(security_id, row["symbol"], name, row["mfapi_scheme_code"]))
    if not row["symbol"]:
        return PriceRefreshResult(security_id=security_id, symbol=None, refreshed=False, message="Security has no refreshable symbol.")
    return apply_quote_result(conn, fetch_security_quote(security_id, row["symbol"], row["exchange"]))


def fetch_indian_mutual_fund_quote(security_id: int, symbol: Optional[str], name: str, scheme_code: Optional[str], schemes: Optional[list[dict]] = None) -> PriceRefreshResult:
    """Fetch an MFAPI quote without SQLite access; suitable for refresh workers."""
    try:
        code = scheme_code
        if not code:
            code, _ = resolve_scheme(name, schemes if schemes is not None else fetch_schemes())
        quote = fetch_mfapi_latest(code)
        return PriceRefreshResult(security_id=security_id, symbol=symbol, refreshed=True, price=quote.nav,
                                  price_date=quote.nav_date, mfapi_scheme_code=quote.scheme_code, message=MFAPI_PROVIDER)
    except Exception as exc:
        return PriceRefreshResult(security_id=security_id, symbol=symbol, refreshed=False, message=f"MFAPI: {exc}")


def fetch_security_quote(security_id: int, symbol: str, exchange: Optional[str]) -> PriceRefreshResult:
    """Fetch a quote without touching SQLite; safe to call from worker threads."""
    if is_google_finance_symbol(symbol):
        try:
            price = fetch_google_finance_price(symbol)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            return PriceRefreshResult(security_id=security_id, symbol=symbol, refreshed=False, message=f"Google Finance: {symbol}: {exc}")
        return PriceRefreshResult(security_id=security_id, symbol=symbol, refreshed=True, price=price, message=GOOGLE_PROVIDER)
    yahoo_errors = []
    price = None
    for candidate in yahoo_candidates(symbol, exchange):
        try:
            price = fetch_yahoo_price(candidate)
            provider = PROVIDER
            break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            yahoo_errors.append(f"{candidate}: {exc}")
    if price is None:
        google_errors = []
        for candidate in google_candidates(symbol, exchange):
            try:
                price = fetch_google_finance_price(candidate)
                provider = GOOGLE_PROVIDER
                break
            except (urllib.error.URLError, TimeoutError, ValueError) as exc:
                google_errors.append(f"{candidate}: {exc}")
    if price is None:
        return PriceRefreshResult(
            security_id=security_id, symbol=symbol,
            refreshed=False,
            message=f"Yahoo: {'; '.join(yahoo_errors)} Google Finance: {'; '.join(google_errors)}",
        )

    if not math.isfinite(price) or price <= 0:
        return PriceRefreshResult(
            security_id=security_id, symbol=symbol,
            refreshed=False,
            message="Quote response included an invalid price; the stored price was not changed.",
        )
    return PriceRefreshResult(
        security_id=security_id, symbol=symbol,
        refreshed=True,
        price=price,
        message=provider,
    )


def apply_quote_result(conn: sqlite3.Connection, result: PriceRefreshResult, price_date: Optional[str] = None) -> PriceRefreshResult:
    """Persist a successfully fetched quote using the caller's short transaction."""
    if not result.refreshed or result.price is None:
        return result
    # Provider is kept in the fetch result message until it is persisted.
    provider = result.message if result.message in {PROVIDER, GOOGLE_PROVIDER, MFAPI_PROVIDER} else PROVIDER
    record_price(conn, result.security_id, result.price, provider, price_date or result.price_date or date.today().isoformat())
    if result.mfapi_scheme_code:
        conn.execute("UPDATE securities SET mfapi_scheme_code=? WHERE id=?", (result.mfapi_scheme_code, result.security_id))
    return result.model_copy(update={"message": "Price refreshed."})


def refresh_all(conn: sqlite3.Connection) -> list[PriceRefreshResult]:
    rows = conn.execute(
        """
        SELECT DISTINCT s.id
        FROM securities s
        JOIN positions p ON p.security_id = s.id
        WHERE s.price_refresh_supported = 1
          AND (s.symbol IS NOT NULL OR (LOWER(s.security_type) = 'mutual fund' AND LOWER(s.investment_country) = 'india'))
        ORDER BY s.symbol
        """
    ).fetchall()
    return [refresh_security(conn, int(row["id"])) for row in rows]
