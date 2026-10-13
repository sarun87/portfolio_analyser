# SPDX-FileCopyrightText: Copyright (C) Arun Sriraman
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from backend.app.core.external_api_logging import open_external_url
from backend.app.services.models import CurrencySetting, FxRate, FxRateUpdate
from backend.app.services.repositories import get_setting, set_setting


SUPPORTED_CURRENCIES = ["USD", "INR", "GBP", "EUR"]
FX_PROVIDER = "frankfurter"
DEFAULT_USD_RATES = {
    "USD": 1.0,
    "INR": 83.5,
    "GBP": 0.79,
    "EUR": 0.92,
}


def get_display_currency(conn: sqlite3.Connection) -> str:
    currency = get_setting(conn, "display_currency") or "USD"
    return currency if currency in SUPPORTED_CURRENCIES else "USD"


def set_display_currency(conn: sqlite3.Connection, currency: str) -> CurrencySetting:
    normalized = currency.upper()
    if normalized not in SUPPORTED_CURRENCIES:
        raise ValueError("Unsupported display currency.")
    set_setting(conn, "display_currency", normalized)
    return CurrencySetting(display_currency=normalized, supported_currencies=SUPPORTED_CURRENCIES)


def list_fx_rates(conn: sqlite3.Connection) -> list[FxRate]:
    return [
        FxRate(
            from_currency=row["from_currency"],
            to_currency=row["to_currency"],
            rate=row["rate"],
            source=row["source"],
            updated_at=row["updated_at"],
        )
        for row in conn.execute(
            """
            SELECT from_currency, to_currency, rate, source, updated_at
            FROM fx_rates
            ORDER BY from_currency, to_currency
            """
        )
    ]


def set_fx_rate(conn: sqlite3.Connection, update: FxRateUpdate, source: str = "manual") -> FxRate:
    from_currency = update.from_currency.upper()
    to_currency = update.to_currency.upper()
    if from_currency not in SUPPORTED_CURRENCIES or to_currency not in SUPPORTED_CURRENCIES:
        raise ValueError("Unsupported currency pair.")
    if update.rate <= 0:
        raise ValueError("FX rate must be greater than zero.")
    updated_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO fx_rates (from_currency, to_currency, rate, source, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(from_currency, to_currency)
        DO UPDATE SET rate = excluded.rate, source = excluded.source, updated_at = excluded.updated_at
        """,
        (from_currency, to_currency, update.rate, source, updated_at),
    )
    return FxRate(
        from_currency=from_currency,
        to_currency=to_currency,
        rate=update.rate,
        source=source,
        updated_at=updated_at,
    )


def get_fx_rate(conn: sqlite3.Connection, from_currency: Optional[str], to_currency: Optional[str]) -> float:
    source = (from_currency or "USD").upper()
    target = (to_currency or "USD").upper()
    if source == target:
        return 1.0
    row = conn.execute(
        "SELECT rate FROM fx_rates WHERE from_currency = ? AND to_currency = ?",
        (source, target),
    ).fetchone()
    if row:
        return float(row["rate"])

    source_to_usd = DEFAULT_USD_RATES["USD"] / DEFAULT_USD_RATES.get(source, 1.0)
    usd_to_target = DEFAULT_USD_RATES.get(target, 1.0)
    derived = source_to_usd * usd_to_target
    set_fx_rate(conn, FxRateUpdate(from_currency=source, to_currency=target, rate=derived), "default-derived")
    return derived


def fx_rate_lookup(conn: sqlite3.Connection) -> dict[tuple[str, str], float]:
    """Load stored rates once for calculations that convert many values."""
    return {(row["from_currency"], row["to_currency"]): float(row["rate"])
            for row in conn.execute("SELECT from_currency, to_currency, rate FROM fx_rates")}


def ensure_default_fx_rates(conn: sqlite3.Connection) -> None:
    for source in SUPPORTED_CURRENCIES:
        for target in SUPPORTED_CURRENCIES:
            row = conn.execute(
                "SELECT 1 FROM fx_rates WHERE from_currency = ? AND to_currency = ?",
                (source, target),
            ).fetchone()
            if row:
                continue
            rate = (DEFAULT_USD_RATES["USD"] / DEFAULT_USD_RATES[source]) * DEFAULT_USD_RATES[target]
            set_fx_rate(conn, FxRateUpdate(from_currency=source, to_currency=target, rate=rate), "default-derived")


def convert_amount(conn: sqlite3.Connection, amount: Optional[float], from_currency: Optional[str], to_currency: str,
                   rates: Optional[dict[tuple[str, str], float]] = None) -> Optional[float]:
    if amount is None:
        return None
    source = (from_currency or "USD").upper()
    target = to_currency.upper()
    if source == target:
        return amount
    if rates is not None and (source, target) in rates:
        return amount * rates[(source, target)]
    return amount * get_fx_rate(conn, source, target)


def fetch_latest_rates(base: str) -> dict[str, float]:
    """Fetch rates from Frankfurter's v2 API (which returns a list of rate rows).

    The small mapping branch keeps compatibility with the older response shape.
    """
    symbols = ",".join(currency for currency in SUPPORTED_CURRENCIES if currency != base)
    url = f"https://api.frankfurter.dev/v2/rates?{urllib.parse.urlencode({'base': base, 'quotes': symbols})}"
    request = urllib.request.Request(url, headers={"User-Agent": "portfolio-analyser/1.0"})
    with open_external_url(request, provider=FX_PROVIDER, timeout=10, opener=urllib.request.urlopen) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if isinstance(payload, list):
        result: dict[str, float] = {}
        for item in payload:
            if not isinstance(item, dict):
                continue
            currency = str(item.get("quote") or item.get("currency") or "").upper()
            rate = item.get("rate")
            if currency in SUPPORTED_CURRENCIES and rate is not None:
                result[currency] = float(rate)
        return result
    if isinstance(payload, dict):
        rates = payload.get("rates") or {}
        if not isinstance(rates, dict):
            raise ValueError("Unexpected FX provider response.")
        return {currency: float(rate) for currency, rate in rates.items() if currency in SUPPORTED_CURRENCIES}
    raise ValueError("Unexpected FX provider response.")


def refresh_fx_rates(conn: sqlite3.Connection) -> list[FxRate]:
    refreshed: list[FxRate] = []
    for base in SUPPORTED_CURRENCIES:
        refreshed.append(set_fx_rate(conn, FxRateUpdate(from_currency=base, to_currency=base, rate=1), "identity"))
        try:
            rates = fetch_latest_rates(base)
        except (urllib.error.URLError, TimeoutError, ValueError, TypeError, json.JSONDecodeError):
            continue
        for target, rate in rates.items():
            refreshed.append(set_fx_rate(conn, FxRateUpdate(from_currency=base, to_currency=target, rate=rate), FX_PROVIDER))
    return refreshed
