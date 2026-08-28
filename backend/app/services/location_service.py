from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from backend.app.core.external_api_logging import open_external_url

EXCHANGE_COUNTRIES = {
    "NASDAQ": "United States",
    "NYSE": "United States",
    "NYSEARCA": "United States",
    "AMEX": "United States",
    "NSE": "India",
    "BSE": "India",
    "LSE": "United Kingdom",
    "LONDON": "United Kingdom",
    "SIX": "Switzerland",
    "SWX": "Switzerland",
    "Euronext Dublin": "Ireland",
    "DUBLIN": "Ireland",
    "XETRA": "Germany",
    "FWB": "Germany",
    "EURONEXT": "Europe",
    "TSX": "Canada",
    "ASX": "Australia",
    "TSE": "Japan",
    "HKSE": "Hong Kong",
}

YAHOO_SUFFIXES = {"NSE": ".NS", "BSE": ".BO", "LSE": ".L", "SIX": ".SW", "SWX": ".SW", "ASX": ".AX", "TSX": ".TO"}


def normalize_exchange(value: Optional[str]) -> str:
    text = (value or "").strip()
    if not text:
        return "Unresolved"
    upper = text.upper()
    aliases = {
        "NASDAQGS": "NASDAQ", "NASDAQCM": "NASDAQ", "NASDAQGM": "NASDAQ", "NYSE ARCA": "NYSEARCA",
        "NSE INDIA": "NSE", "NATIONAL STOCK EXCHANGE": "NSE", "NATIONAL STOCK EXCHANGE OF INDIA": "NSE",
        "BSE INDIA": "BSE", "BOMBAY STOCK EXCHANGE": "BSE", "BSE LIMITED": "BSE",
        "SIX SWISS EXCHANGE": "SIX", "LSEIOB": "LSE", "LONDON": "LSE", "LON": "LSE", "XLON": "LSE",
        "LONDON STOCK EXCHANGE": "LSE", "LONDON STOCK EXCHANGE PLC": "LSE", "LONDON STOCK EXCHANGE GROUP": "LSE",
    }
    return aliases.get(upper, text)


def country_for_exchange(exchange: str) -> str:
    normalized = normalize_exchange(exchange)
    return EXCHANGE_COUNTRIES.get(normalized, EXCHANGE_COUNTRIES.get(normalized.upper(), "Unresolved"))


def _candidates(symbol: str, statement_exchange: Optional[str]) -> list[str]:
    base = symbol.strip().upper()
    exchange = normalize_exchange(statement_exchange)
    suffix = YAHOO_SUFFIXES.get(exchange.upper())
    return list(dict.fromkeys([f"{base}{suffix}" if suffix and "." not in base else base, base]))


def resolve_security_location(symbol: Optional[str], statement_exchange: Optional[str] = None) -> tuple[str, str, str]:
    """Return exchange, country, source without making an import fail on lookup errors."""
    if not symbol:
        fallback_exchange = normalize_exchange(statement_exchange)
        return fallback_exchange, country_for_exchange(fallback_exchange), "statement" if fallback_exchange != "Unresolved" else "unresolved"
    for candidate in _candidates(symbol, statement_exchange):
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(candidate)}?range=1d&interval=1d"
            request = urllib.request.Request(url, headers={"User-Agent": "portfolio-analyser/1.0"})
            with open_external_url(request, provider="yahoo-chart-location", timeout=5, opener=urllib.request.urlopen) as response:
                payload = json.loads(response.read().decode("utf-8"))
            result = payload.get("chart", {}).get("result") or []
            meta = result[0].get("meta", {}) if result else {}
            exchange = normalize_exchange(meta.get("fullExchangeName") or meta.get("exchangeName"))
            if exchange != "Unresolved":
                return exchange, country_for_exchange(exchange), "yahoo-chart"
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
            continue
    fallback_exchange = normalize_exchange(statement_exchange)
    return fallback_exchange, country_for_exchange(fallback_exchange), "statement" if fallback_exchange != "Unresolved" else "unresolved"
