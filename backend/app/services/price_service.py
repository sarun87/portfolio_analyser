import json
import math
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

from backend.app.services.models import PriceRefreshResult
from backend.app.services.repositories import record_price


PROVIDER = "yahoo-chart"
GOOGLE_PROVIDER = "google-finance-html"


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


def fetch_google_finance_price(symbol: str) -> float:
    """Best-effort HTML fallback, used only after a valid Yahoo payload has no quote."""
    url = f"https://www.google.com/finance/quote/{urllib.parse.quote(symbol)}"
    request = urllib.request.Request(url, headers={"User-Agent": "portfolio-analyser/1.0 (+local portfolio tracker)"})
    with urllib.request.urlopen(request, timeout=10) as response:
        html = response.read().decode("utf-8", errors="replace")
    # Google currently marks the primary quote with this class.  Keep a
    # conservative numeric validation rather than accepting arbitrary text.
    match = re.search(r'class="YMlKec[^" ]*"[^>]*>\s*([0-9][0-9,]*(?:\.\d+)?)', html)
    if not match:
        raise ValueError("Google Finance page did not include a usable quote.")
    price = float(match.group(1).replace(",", ""))
    if not math.isfinite(price) or price <= 0:
        raise ValueError("Google Finance page included an invalid price.")
    return price


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
        provider = PROVIDER
    except ValueError as yahoo_exc:
        # A parseable Yahoo response without a quote is a distinct condition;
        # network/JSON failures do not cause a second remote request.
        try:
            price = fetch_google_finance_price(row["symbol"])
            provider = GOOGLE_PROVIDER
        except (urllib.error.URLError, TimeoutError, ValueError) as google_exc:
            return PriceRefreshResult(security_id=security_id, symbol=row["symbol"], refreshed=False, message=f"Yahoo: {yahoo_exc} Google Finance: {google_exc}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
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

    record_price(conn, security_id, price, provider, date.today().isoformat())
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
