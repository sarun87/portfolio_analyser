import json
import math
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

from backend.app.services.models import PriceRefreshResult
from backend.app.services.repositories import record_price


PROVIDER = "yahoo-chart"


def fetch_yahoo_price(symbol: str) -> float:
    encoded = urllib.parse.quote(symbol)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=1d&interval=1d"
    request = urllib.request.Request(url, headers={"User-Agent": "portfolio-analyser/1.0"})
    with urllib.request.urlopen(request, timeout=10) as response:
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


def refresh_security(conn: sqlite3.Connection, security_id: int) -> PriceRefreshResult:
    row = conn.execute(
        "SELECT id, symbol, price_refresh_supported FROM securities WHERE id = ?",
        (security_id,),
    ).fetchone()
    if not row:
        return PriceRefreshResult(security_id=security_id, symbol=None, refreshed=False, message="Security not found.")
    if not row["price_refresh_supported"] or not row["symbol"]:
        return PriceRefreshResult(
            security_id=security_id,
            symbol=row["symbol"],
            refreshed=False,
            message="Security has no refreshable symbol.",
        )
    try:
        price = fetch_yahoo_price(row["symbol"])
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        return PriceRefreshResult(
            security_id=security_id,
            symbol=row["symbol"],
            refreshed=False,
            message=str(exc),
        )

    if not math.isfinite(price) or price <= 0:
        return PriceRefreshResult(
            security_id=security_id,
            symbol=row["symbol"],
            refreshed=False,
            message="Quote response included an invalid price; the stored price was not changed.",
        )

    record_price(conn, security_id, price, PROVIDER, date.today().isoformat())
    return PriceRefreshResult(
        security_id=security_id,
        symbol=row["symbol"],
        refreshed=True,
        price=price,
        message="Price refreshed.",
    )


def refresh_all(conn: sqlite3.Connection) -> list[PriceRefreshResult]:
    rows = conn.execute(
        """
        SELECT DISTINCT s.id
        FROM securities s
        JOIN positions p ON p.security_id = s.id
        WHERE s.price_refresh_supported = 1 AND s.symbol IS NOT NULL
        ORDER BY s.symbol
        """
    ).fetchall()
    return [refresh_security(conn, int(row["id"])) for row in rows]
