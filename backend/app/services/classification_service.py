from __future__ import annotations

import json
import sqlite3
from typing import Optional
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from backend.app.services.models import ClassificationRefreshResult


PROVIDER = "yahoo-quote-summary"


KNOWN_SYMBOL_CATEGORIES = {
    "QQQ": "Large Cap",
    "VOO": "Large Cap",
    "VTI": "Hybrid Fund",
    "SCHB": "Hybrid Fund",
    "SCHC": "Small Cap",
    "AGG": "Bonds",
    "BND": "Bonds",
    "SCHZ": "Bonds",
    "VGIT": "Bonds",
    "VCIT": "Bonds",
    "MUB": "Bonds",
    "TLT": "Bonds",
    "VBTLX": "Bonds",
    "VWIUX": "Bonds",
}


def fallback_category(symbol: Optional[str], name: str, security_type: str) -> str:
    normalized_symbol = (symbol or "").upper().strip()
    if normalized_symbol in KNOWN_SYMBOL_CATEGORIES:
        return KNOWN_SYMBOL_CATEGORIES[normalized_symbol]

    text = f"{name} {security_type}".lower()
    if "cash" in text or "money market" in text:
        return "Cash"
    if "bond" in text or "treasury" in text or "municipal" in text or "tax-exempt" in text or "fixed income" in text:
        return "Bonds"
    if "small" in text:
        return "Small Cap"
    if "mid" in text:
        return "Mid Cap"
    if "balanced" in text or "hybrid" in text or "total stock" in text or "broad market" in text:
        return "Hybrid Fund"
    if security_type.lower() in {"stock", "equity"}:
        return "Large Cap"
    return "Unclassified"


def fetch_yahoo_summary(symbol: str) -> dict[str, Any]:
    encoded = urllib.parse.quote(symbol)
    modules = "quoteType,summaryProfile,assetProfile,fundProfile,defaultKeyStatistics,price"
    url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{encoded}?modules={modules}"
    request = urllib.request.Request(url, headers={"User-Agent": "portfolio-analyser/1.0"})
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    result = payload.get("quoteSummary", {}).get("result") or []
    if not result:
        raise ValueError("No classification data returned.")
    return result[0]


def _raw_value(value: Any) -> Any:
    if isinstance(value, dict) and "raw" in value:
        return value["raw"]
    return value


def classify_from_summary(summary: dict[str, Any], fallback: str) -> str:
    quote_type = summary.get("quoteType", {})
    fund_profile = summary.get("fundProfile", {})
    summary_profile = summary.get("summaryProfile", {})
    asset_profile = summary.get("assetProfile", {})
    price = summary.get("price", {})
    stats = summary.get("defaultKeyStatistics", {})

    fields = [
        quote_type.get("quoteType"),
        quote_type.get("longName"),
        quote_type.get("shortName"),
        fund_profile.get("categoryName"),
        summary_profile.get("category"),
        summary_profile.get("longBusinessSummary"),
        asset_profile.get("longBusinessSummary"),
    ]
    text = " ".join(str(item) for item in fields if item).lower()

    if any(term in text for term in ["bond", "treasury", "municipal", "fixed income", "tax-exempt"]):
        return "Bonds"
    if "small" in text:
        return "Small Cap"
    if "mid" in text:
        return "Mid Cap"
    if any(term in text for term in ["balanced", "hybrid", "allocation", "total stock", "broad market"]):
        return "Hybrid Fund"
    if any(term in text for term in ["large", "s&p 500", "nasdaq", "mega cap"]):
        return "Large Cap"

    market_cap = _raw_value(price.get("marketCap")) or _raw_value(stats.get("enterpriseValue"))
    if isinstance(market_cap, (int, float)):
        if market_cap >= 10_000_000_000:
            return "Large Cap"
        if market_cap >= 2_000_000_000:
            return "Mid Cap"
        if market_cap > 0:
            return "Small Cap"

    return fallback


def update_security_category(
    conn: sqlite3.Connection,
    security_id: int,
    category: str,
    source: str,
) -> None:
    from backend.app.services.allocation_category_service import register_category
    register_category(conn, category)
    conn.execute(
        """
        UPDATE securities
        SET allocation_category = ?,
            classification_source = ?,
            classified_at = ?
        WHERE id = ?
        """,
        (category, source, datetime.now(timezone.utc).isoformat(), security_id),
    )


def classify_security(conn: sqlite3.Connection, security_id: int) -> ClassificationRefreshResult:
    row = conn.execute(
        "SELECT id, symbol, name, security_type FROM securities WHERE id = ?",
        (security_id,),
    ).fetchone()
    if not row:
        return ClassificationRefreshResult(
            security_id=security_id,
            symbol=None,
            refreshed=False,
            allocation_category="Unclassified",
            message="Security not found.",
        )

    fallback = fallback_category(row["symbol"], row["name"], row["security_type"])
    if not row["symbol"] or fallback == "Cash":
        update_security_category(conn, security_id, fallback, "local-rules")
        return ClassificationRefreshResult(
            security_id=security_id,
            symbol=row["symbol"],
            refreshed=True,
            allocation_category=fallback,
            message="Classified using local rules.",
        )

    try:
        summary = fetch_yahoo_summary(row["symbol"])
        category = classify_from_summary(summary, fallback)
        update_security_category(conn, security_id, category, PROVIDER)
        return ClassificationRefreshResult(
            security_id=security_id,
            symbol=row["symbol"],
            refreshed=True,
            allocation_category=category,
            message="Classification refreshed.",
        )
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        update_security_category(conn, security_id, fallback, "local-rules")
        return ClassificationRefreshResult(
            security_id=security_id,
            symbol=row["symbol"],
            refreshed=False,
            allocation_category=fallback,
            message=f"Used local fallback: {exc}",
        )


def classify_all(conn: sqlite3.Connection) -> list[ClassificationRefreshResult]:
    rows = conn.execute(
        """
        SELECT DISTINCT s.id
        FROM securities s
        JOIN positions p ON p.security_id = s.id
        ORDER BY s.symbol, s.name
        """
    ).fetchall()
    return [classify_security(conn, int(row["id"])) for row in rows]
