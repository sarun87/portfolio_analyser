from __future__ import annotations

import json
import csv
import ipaddress
import io
import re
import sqlite3
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timezone
from html import unescape
from html.parser import HTMLParser

from backend.app.core.external_api_logging import open_external_url
from backend.app.services.models import (
    ExposureAnalysis, ExposureRow, FundComposition, FundCompositionInput,
    FundConstituentInput, FundOverlap, PublicMetadataPreview, PublicMetadataAcceptance, FundMetadata, PeerCandidate, PeerResearch, InsightAllocationRow,
)
from backend.app.services.portfolio_service import list_positions
from backend.app.services.insight_service import list_targets


PUBLIC_PROVIDER = "html-sync"
FRESH_DAYS = 120


def _today() -> date:
    return date.today()


def _is_stale(as_of: str | None, reviewed: str | None) -> bool:
    raw = as_of or (reviewed or "")[:10]
    try:
        return (_today() - date.fromisoformat(raw)).days > FRESH_DAYS
    except ValueError:
        return True


def list_compositions(conn: sqlite3.Connection) -> list[FundComposition]:
    securities = {row["id"]: row["name"] for row in conn.execute("SELECT id, name FROM securities")}
    result: list[FundComposition] = []
    for header in conn.execute("SELECT * FROM fund_compositions ORDER BY security_id"):
        items = [FundConstituentInput(**dict(row)) for row in conn.execute(
            """SELECT constituent_key, identifier, linked_security_id, symbol, name, weight_percent, sector,
                      country, currency, asset_category
               FROM fund_constituents WHERE fund_security_id=? ORDER BY weight_percent DESC, name""",
            (header["security_id"],),
        )]
        result.append(FundComposition(
            security_id=header["security_id"], security_name=securities.get(header["security_id"], "Unknown fund"),
            source=header["source"], source_url=header["source_url"], holdings_scope=header["holdings_scope"],
            as_of_date=header["as_of_date"], reviewed_at=header["reviewed_at"],
            constituents=items, coverage_percent=sum(item.weight_percent for item in items),
            stale=_is_stale(header["as_of_date"], header["reviewed_at"]),
        ))
    return result


def get_composition(conn: sqlite3.Connection, security_id: int) -> FundComposition | None:
    return next((item for item in list_compositions(conn) if item.security_id == security_id), None)


def save_composition(conn: sqlite3.Connection, security_id: int, payload: FundCompositionInput) -> FundComposition:
    security = conn.execute("SELECT name FROM securities WHERE id=?", (security_id,)).fetchone()
    if not security:
        raise ValueError("Security not found.")
    keys = [item.constituent_key.strip().lower() for item in payload.constituents]
    if len(keys) != len(set(keys)):
        raise ValueError("A composition cannot contain duplicate constituent keys.")
    total = sum(item.weight_percent for item in payload.constituents)
    if total > 100.01:
        raise ValueError("Fund constituent weights cannot exceed 100%.")
    weight_scale = 100 / total if total > 100 else 1.0
    for item in payload.constituents:
        if item.linked_security_id == security_id:
            raise ValueError("A fund cannot directly contain itself.")
        if item.linked_security_id and not conn.execute("SELECT 1 FROM securities WHERE id=?", (item.linked_security_id,)).fetchone():
            raise ValueError(f"Linked security {item.linked_security_id} was not found.")
    graph: dict[int, list[int]] = defaultdict(list)
    for row in conn.execute("SELECT fund_security_id, linked_security_id FROM fund_constituents WHERE linked_security_id IS NOT NULL"):
        if row["fund_security_id"] != security_id:
            graph[row["fund_security_id"]].append(row["linked_security_id"])
    graph[security_id] = [item.linked_security_id for item in payload.constituents if item.linked_security_id is not None]
    def reaches_origin(node: int, visited: set[int]) -> bool:
        if node == security_id:
            return True
        if node in visited:
            return False
        return any(reaches_origin(child, visited | {node}) for child in graph.get(node, []))
    if any(reaches_origin(child, set()) for child in graph[security_id]):
        raise ValueError("Fund compositions cannot contain a direct or indirect cycle.")
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO fund_compositions(security_id, source, source_url, holdings_scope, as_of_date, reviewed_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(security_id) DO UPDATE SET source=excluded.source, as_of_date=excluded.as_of_date,
             source_url=excluded.source_url, holdings_scope=excluded.holdings_scope, reviewed_at=excluded.reviewed_at, updated_at=excluded.updated_at""",
        (security_id, payload.source.strip() or "manual", payload.source_url, payload.holdings_scope, payload.as_of_date, now, now),
    )
    conn.execute("DELETE FROM fund_constituents WHERE fund_security_id=?", (security_id,))
    conn.executemany(
        """INSERT INTO fund_constituents(fund_security_id, constituent_key, identifier, linked_security_id, symbol, name,
             weight_percent, sector, country, currency, asset_category) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [(security_id, item.constituent_key.strip(), item.identifier.strip().upper() if item.identifier else None, item.linked_security_id,
          item.symbol.upper().strip() if item.symbol else None, item.name.strip(), item.weight_percent * weight_scale,
          item.sector.strip() or "Unclassified", item.country.strip() or "Unresolved",
          item.currency.upper().strip() or "Unresolved", item.asset_category.strip() or "Unclassified")
         for item in payload.constituents],
    )
    return get_composition(conn, security_id)  # type: ignore[return-value]


def fetch_public_metadata(symbol: str) -> dict:
    modules = "topHoldings,fundProfile,defaultKeyStatistics,fundPerformance,summaryDetail"
    encoded = urllib.parse.quote(symbol)
    url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{encoded}?modules={modules}"
    request = urllib.request.Request(url, headers={"User-Agent": "portfolio-analyser/1.0"})
    with open_external_url(request, provider="yahoo-quote-summary", timeout=12, opener=urllib.request.urlopen) as response:
        payload = json.loads(response.read().decode("utf-8"))
    results = payload.get("quoteSummary", {}).get("result") or []
    if not results:
        raise ValueError("No public fund metadata was returned.")
    return results[0]


def _raw(value):
    return value.get("raw") if isinstance(value, dict) else value


def _percent(value):
    value = _raw(value)
    return value * 100 if isinstance(value, (int, float)) and abs(value) <= 1 else value


def _date_value(value) -> str | None:
    value = _raw(value)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).date().isoformat()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10]).isoformat()
        except ValueError:
            return None
    return None


def _provider_as_of_date(data: dict) -> str | None:
    performance = data.get("fundPerformance", {})
    holdings = data.get("topHoldings", {})
    return _date_value(performance.get("asOfDate") or performance.get("asOf") or holdings.get("asOfDate"))


def _facts(data: dict) -> dict:
    profile, stats, performance, detail = data.get("fundProfile", {}), data.get("defaultKeyStatistics", {}), data.get("fundPerformance", {}), data.get("summaryDetail", {})
    annual = performance.get("annualTotalReturns") or performance.get("annualTotalReturnsTrailing") or {}
    period_returns = {}
    if isinstance(annual, list):
        for item in annual:
            period = str(item.get("period") or "").lower().replace(" ", "")
            period_returns[period] = item.get("annualizedReturn") or item.get("return")
    elif isinstance(annual, dict): period_returns = annual
    def pick(*values): return next((v for v in values if v is not None), None)
    inception = _date_value(profile.get("fundInceptionDate"))
    return {
        "category": profile.get("categoryName") or profile.get("category"), "thesis": profile.get("investmentStrategy"),
        "fund_family": profile.get("family") or profile.get("fundFamily"), "inception_date": inception,
        "assets_under_management": _raw(stats.get("totalAssets")) or _raw(profile.get("totalNetAssets")),
        "yield_percent": _percent(pick(detail.get("yield"), detail.get("trailingAnnualDividendYield"))),
        "turnover_percent": _percent(profile.get("annualHoldingsTurnover")), "beta": _raw(stats.get("beta3Year")),
        "expense_ratio_percent": _percent(pick(stats.get("annualReportExpenseRatio"), profile.get("feesExpensesInvestment", {}).get("annualReportExpenseRatio"))),
        "return_3y_percent": _percent(pick(period_returns.get("3y"), period_returns.get("threeyear"), performance.get("threeYearAverageReturn"))),
        "return_5y_percent": _percent(pick(period_returns.get("5y"), period_returns.get("fiveyear"), performance.get("fiveYearAverageReturn"))),
        "return_10y_percent": _percent(pick(period_returns.get("10y"), period_returns.get("tenyear"), performance.get("tenYearAverageReturn"))),
        "return_since_inception_percent": _percent(pick(period_returns.get("sinceinception"), performance.get("sinceInceptionReturn"))),
    }


def _store_metadata(conn: sqlite3.Connection, security_id: int, facts: dict, provider: str, fetched_at: str, as_of_date: str | None) -> FundMetadata:
    fields = ["category", "thesis", "fund_family", "inception_date", "assets_under_management", "yield_percent", "turnover_percent", "beta", "expense_ratio_percent", "return_3y_percent", "return_5y_percent", "return_10y_percent", "return_since_inception_percent"]
    missing = [key for key in fields if facts.get(key) is None]
    conn.execute(f"""INSERT INTO fund_metadata(security_id,provider,{','.join(fields)},as_of_date,fetched_at,unavailable_fields_json,reviewed_at)
        VALUES ({','.join('?' for _ in range(len(fields)+6))}) ON CONFLICT(security_id) DO UPDATE SET
        provider=excluded.provider,{','.join(f'{key}=excluded.{key}' for key in fields)},as_of_date=excluded.as_of_date,fetched_at=excluded.fetched_at,unavailable_fields_json=excluded.unavailable_fields_json,reviewed_at=excluded.reviewed_at""",
        [security_id, provider, *[facts.get(k) for k in fields], as_of_date, fetched_at, json.dumps(missing), fetched_at])
    return get_fund_metadata(conn, security_id)  # type: ignore[return-value]


def get_fund_metadata(conn: sqlite3.Connection, security_id: int) -> FundMetadata | None:
    row = conn.execute("SELECT * FROM fund_metadata WHERE security_id=?", (security_id,)).fetchone()
    if not row: return None
    data = dict(row); data["unavailable_fields"] = json.loads(data.pop("unavailable_fields_json") or "[]")
    return FundMetadata(**data)


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows=[]; self._row=[]; self._cell=[]; self._in_cell=False
    def handle_starttag(self, tag, attrs):
        if tag == "tr": self._row=[]
        elif tag in {"td", "th"}: self._in_cell=True; self._cell=[]
    def handle_data(self, data):
        if self._in_cell: self._cell.append(data)
    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self._in_cell:
            self._row.append(" ".join(self._cell).strip()); self._in_cell=False
        elif tag == "tr" and self._row: self.rows.append(self._row)


def _public_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Only public HTTPS URLs can be synced.")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        for item in addresses:
            address = ipaddress.ip_address(item[4][0])
            if not address.is_global: raise ValueError("Private or local network URLs are not allowed.")
    except socket.gaierror as exc:
        raise ValueError("The source host could not be resolved.") from exc
    return url


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch_html(url: str, provider: str) -> str:
    request = urllib.request.Request(_public_url(url), headers={"User-Agent": "portfolio-analyser/1.0 (+local personal research)"})
    opener = urllib.request.build_opener(_SafeRedirect())
    with open_external_url(request, provider=provider, timeout=12, opener=opener.open) as response:
        if int(response.headers.get("Content-Length") or 0) > 1_500_000: raise ValueError("The source page is too large to sync.")
        raw = response.read(1_500_001)
    if len(raw) > 1_500_000: raise ValueError("The source page is too large to sync.")
    return raw.decode("utf-8", errors="replace")


def _text(html: str) -> str:
    return unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)))


def _parse_html(html: str) -> tuple[list[FundConstituentInput], dict, str | None, list[str]]:
    parser = _TableParser(); parser.feed(html)
    holdings=[]; warnings=[]
    for row in parser.rows:
        joined = " ".join(row)
        percent = re.search(r"(-?\d+(?:\.\d+)?)\s*%", joined)
        if not percent or len(row) < 2: continue
        weight=float(percent.group(1))
        if not 0 < weight <= 100: continue
        name=next((cell for cell in row if not re.fullmatch(r"-?\d+(?:\.\d+)?%?", cell.strip()) and len(cell.strip()) > 1), "")
        if not name or name.lower() in {"holding", "name", "weight"}: continue
        symbol_match=re.search(r"\b[A-Z]{1,6}(?:\.[A-Z])?\b", " ".join(row))
        symbol=symbol_match.group(0) if symbol_match else None
        key=(symbol or name).lower()
        if any(item.constituent_key == key for item in holdings): continue
        holdings.append(FundConstituentInput(constituent_key=key, symbol=symbol, name=name, weight_percent=weight))
        if len(holdings) == 10: break
    text=_text(html)
    def labeled(label: str) -> str | None:
        match=re.search(r"(?:" + label + r")\s*[:\-]?\s*(.{1,80}?)(?=\s{2,}|$)", text, re.I)
        return match.group(1).strip(" :") if match else None
    expense=labeled("expense ratio|net expense ratio")
    facts={"category": labeled("category"), "fund_family": labeled("fund family|issuer"), "thesis": labeled("strategy|investment objective")}
    if expense:
        amount=re.search(r"(\d+(?:\.\d+)?)\s*%", expense)
        if amount: facts["expense_ratio_percent"]=float(amount.group(1))
    as_of=labeled("as of|holdings as of")
    as_of_date=_date_value(as_of) if as_of else None
    if not holdings: warnings.append("No weighted holdings table was found in the public HTML.")
    if not any(facts.values()): warnings.append("No labelled fund facts were found in the public HTML.")
    return holdings, {key:value for key,value in facts.items() if value is not None}, as_of_date, warnings


def _parse_holdings_csv(raw: str, provider_label: str) -> tuple[list[FundConstituentInput], str | None, list[str]]:
    """Parse public iShares/Vanguard holdings CSVs without fund-specific rules."""
    lines = raw.lstrip("\ufeff").splitlines()
    header_index = next((index for index, line in enumerate(lines)
                         if "name" in line.lower() and ("weight" in line.lower() or "net assets" in line.lower())), None)
    if header_index is None:
        raise ValueError(f"This does not look like a {provider_label} holdings CSV (Name and Weight columns are required).")
    as_of_date = None
    for line in lines[:header_index]:
        match = re.search(r"(?:as of|holdings as of)\D*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})", line, re.I)
        if not match:
            continue
        for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d", "%m-%d-%Y", "%d-%m-%Y"):
            try:
                as_of_date = datetime.strptime(match.group(1), fmt).date().isoformat()
                break
            except ValueError:
                pass
        if as_of_date:
            break
    reader = csv.DictReader(io.StringIO("\n".join(lines[header_index:])))
    holdings: list[FundConstituentInput] = []
    warnings: list[str] = []
    for row in reader:
        normalized = {(key or "").strip().lower(): (value or "").strip() for key, value in row.items()}
        name = normalized.get("name") or normalized.get("security name") or normalized.get("holding name")
        raw_weight = (normalized.get("weight (%)") or normalized.get("weight") or normalized.get("weight percent")
                      or normalized.get("% of net assets") or normalized.get("percent of net assets"))
        if not name or not raw_weight:
            continue
        try:
            weight = float(raw_weight.replace("%", "").replace(",", ""))
        except ValueError:
            continue
        if not 0 < weight <= 100:
            continue
        identifier = next((normalized.get(key) for key in ("isin", "sedol", "cusip") if normalized.get(key)), None)
        symbol = next((normalized.get(key) for key in ("issuer ticker", "holding ticker", "ticker", "symbol") if normalized.get(key)), None)
        constituent_key = identifier or symbol or name
        if any(item.constituent_key.lower() == constituent_key.lower() for item in holdings):
            continue
        holdings.append(FundConstituentInput(
            constituent_key=constituent_key, identifier=identifier, symbol=symbol, name=name, weight_percent=weight,
            sector=normalized.get("sector") or "Unclassified",
            country=normalized.get("location") or normalized.get("country") or "Unresolved",
            currency=normalized.get("market currency") or normalized.get("currency") or "Unresolved",
            asset_category=normalized.get("asset class") or "Unclassified",
        ))
    if not holdings:
        warnings.append(f"No weighted constituents were found in the {provider_label} CSV.")
    return holdings, as_of_date, warnings


def _html_source_url(symbol: str, source: str, custom_url: str | None) -> tuple[str, str]:
    def provider_csv_url(url: str | None, domains: tuple[str, ...], provider_name: str) -> str:
        if not url:
            raise ValueError(f"Provide a public {provider_name} holdings CSV URL.")
        hostname = (urllib.parse.urlparse(url).hostname or "").lower().rstrip(".")
        if not any(hostname == domain or hostname.endswith(f".{domain}") for domain in domains):
            raise ValueError(f"The {provider_name} CSV URL must use an approved {provider_name} domain.")
        return url

    if source == "yahoo_html": return f"https://finance.yahoo.com/quote/{urllib.parse.quote(symbol)}/holdings", "yahoo-html"
    if source == "google_finance_html": return f"https://www.google.com/finance/quote/{urllib.parse.quote(symbol)}:NYSE", "google-finance-html"
    if source == "custom_url" and custom_url: return custom_url, "custom-html"
    if source == "ishares_csv": return provider_csv_url(custom_url, ("ishares.com",), "iShares"), "ishares-csv"
    if source == "vanguard_csv": return provider_csv_url(custom_url, ("vanguard.com",), "Vanguard"), "vanguard-csv"
    raise ValueError("Choose Yahoo Finance, Google Finance, iShares CSV, Vanguard CSV, or provide a custom public URL.")


def preview_public_metadata(conn: sqlite3.Connection, security_id: int, source: str = "yahoo_html", custom_url: str | None = None) -> PublicMetadataPreview:
    row = conn.execute("SELECT symbol FROM securities WHERE id=?", (security_id,)).fetchone()
    if not row or not row["symbol"]:
        raise ValueError("Security has no public-data symbol.")
    try:
        source_url, provider = _html_source_url(row["symbol"], source, custom_url)
        raw = _fetch_html(source_url, provider)
        if source in {"ishares_csv", "vanguard_csv"}:
            holdings, as_of_date, warnings = _parse_holdings_csv(raw, "iShares" if source == "ishares_csv" else "Vanguard")
            facts = {}
        else:
            holdings, facts, as_of_date, warnings = _parse_html(raw)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise ValueError(f"Public HTML sync failed: {exc}") from exc
    fetched = datetime.now(timezone.utc).isoformat()
    expense = facts.get("expense_ratio_percent")
    scope = "full" if source in {"ishares_csv", "vanguard_csv"} else "top_10"
    cache_payload = {"composition": FundCompositionInput(source=provider, source_url=source_url, holdings_scope=scope, as_of_date=as_of_date, constituents=holdings).model_dump() if holdings else None,
                     "as_of_date": as_of_date, "expense_ratio_percent": expense, "facts": facts, "source_url": source_url, "warnings": warnings}
    conn.execute("""INSERT INTO reference_cache(cache_key, provider, payload_json, fetched_at)
                    VALUES (?, ?, ?, ?) ON CONFLICT(cache_key) DO UPDATE SET payload_json=excluded.payload_json,
                    provider=excluded.provider, fetched_at=excluded.fetched_at""",
                 (f"security:{security_id}:metadata", provider, json.dumps(cache_payload), fetched))
    return PublicMetadataPreview(
        security_id=security_id, provider=provider, fetched_at=fetched, as_of_date=as_of_date,
        composition=FundCompositionInput(**cache_payload["composition"]) if holdings else None, facts=facts,
        expense_ratio_percent=expense if isinstance(expense, (int, float)) else None,
        source_url=source_url, warnings=warnings, holdings_count=len(holdings), holdings_scope=scope,
        message="Review this public HTML draft before accepting it. Holdings and facts are best effort.",
    )


def cached_public_preview(conn: sqlite3.Connection, security_id: int) -> PublicMetadataPreview:
    row = conn.execute("SELECT * FROM reference_cache WHERE cache_key=?", (f"security:{security_id}:metadata",)).fetchone()
    if not row:
        raise ValueError("No public metadata preview is available.")
    payload = json.loads(row["payload_json"])
    return PublicMetadataPreview(
        security_id=security_id, provider=row["provider"], fetched_at=row["fetched_at"], as_of_date=payload.get("as_of_date"),
        composition=FundCompositionInput(**payload["composition"]) if payload.get("composition") else None,
        expense_ratio_percent=payload.get("expense_ratio_percent"), facts=payload.get("facts") or {}, source_url=payload.get("source_url"), warnings=payload.get("warnings") or [], holdings_count=len((payload.get("composition") or {}).get("constituents") or []),
        holdings_scope=(payload.get("composition") or {}).get("holdings_scope", "top_10"),
        message="Cached public-data draft. Accept only after review.",
    )


def accept_public_metadata(conn: sqlite3.Connection, security_id: int) -> PublicMetadataAcceptance:
    preview = cached_public_preview(conn, security_id)
    metadata = _store_metadata(conn, security_id, preview.facts, preview.provider, preview.fetched_at, preview.as_of_date)
    composition = save_composition(conn, security_id, preview.composition) if preview.composition else get_composition(conn, security_id)
    return PublicMetadataAcceptance(metadata=metadata, composition=composition)


def _matched_horizon(held: FundMetadata | None, facts: dict) -> tuple[str | None, float | None]:
    for key, label in (("return_5y_percent", "5-year"), ("return_3y_percent", "3-year"), ("return_10y_percent", "10-year")):
        if held and getattr(held, key) is not None and facts.get(key) is not None: return label, facts[key]
    return None, None


def _region_compatible(country: str | None, region: str | None) -> bool:
    if not country or country.lower() in {"unresolved", "unknown"} or not region:
        return True
    expected = {
        "united states": {"us", "usa", "united states"}, "usa": {"us", "usa", "united states"},
        "india": {"in", "india"}, "united kingdom": {"gb", "uk", "united kingdom"},
        "canada": {"ca", "canada"}, "japan": {"jp", "japan"},
    }.get(country.strip().lower(), {country.strip().lower()})
    return region.strip().lower() in expected


def _thesis_compatible(held_thesis: str | None, candidate_thesis: str | None) -> bool:
    if not held_thesis or not candidate_thesis:
        return True
    ignored = {"fund", "investment", "strategy", "the", "and", "of", "to", "a", "an"}
    left = {word for word in held_thesis.lower().split() if len(word) > 2 and word not in ignored}
    right = {word for word in candidate_thesis.lower().split() if len(word) > 2 and word not in ignored}
    return bool(left & right)


def research_peers(conn: sqlite3.Connection, security_id: int) -> PeerResearch:
    held = get_fund_metadata(conn, security_id)
    security = conn.execute("SELECT symbol,name,security_type,investment_country FROM securities WHERE id=?", (security_id,)).fetchone()
    if not security or not security["symbol"]: raise ValueError("Security has no public-data symbol.")
    if not held or not held.category:
        raise ValueError("Accept public fund metadata with a category before researching peers.")
    retrieved = datetime.now(timezone.utc).isoformat(); warnings=[]; candidates=[]
    try:
        url = "https://query1.finance.yahoo.com/v1/finance/search?q=" + urllib.parse.quote((held.category if held and held.category else security["name"])) + "&quotesCount=12&newsCount=0"
        request = urllib.request.Request(url, headers={"User-Agent":"portfolio-analyser/1.0"})
        with open_external_url(request, provider="yahoo-search", timeout=12, opener=urllib.request.urlopen) as response: results=json.loads(response.read().decode()).get("quotes") or []
        for quote in results:
            symbol = str(quote.get("symbol") or "").upper()
            if not symbol or symbol == security["symbol"].upper() or quote.get("quoteType") not in {"ETF", "MUTUALFUND"}: continue
            if not _region_compatible(security["investment_country"], quote.get("region")): continue
            try: facts=_facts(fetch_public_metadata(symbol))
            except Exception: warnings.append(f"Could not retrieve metadata for {symbol}."); continue
            if not facts.get("category") or facts["category"].strip().lower() != held.category.strip().lower(): continue
            if not _thesis_compatible(held.thesis, facts.get("thesis")): continue
            horizon, matched = _matched_horizon(held, facts)
            if horizon and facts.get("expense_ratio_percent") is not None:
                candidates.append(PeerCandidate(symbol=symbol,name=str(quote.get("shortname") or quote.get("longname") or symbol),category=facts.get("category"),thesis=facts.get("thesis"),expense_ratio_percent=facts.get("expense_ratio_percent"),return_3y_percent=facts.get("return_3y_percent"),return_5y_percent=facts.get("return_5y_percent"),return_10y_percent=facts.get("return_10y_percent"),matched_horizon=horizon,matched_return_percent=matched))
    except Exception as exc: warnings.append(f"Peer search is unavailable: {exc}")
    candidates.sort(key=lambda x: (x.expense_ratio_percent if x.expense_ratio_percent is not None else float("inf"),
                                   -(x.matched_return_percent if x.matched_return_percent is not None else float("inf"))))
    for i, candidate in enumerate(candidates, 1): candidate.rank=i
    note="No compatible candidates with matched return and fee data were found."
    if candidates:
        top=candidates[0]; held_return=getattr(held, {"5-year":"return_5y_percent","3-year":"return_3y_percent","10-year":"return_10y_percent"}[top.matched_horizon]) if held and top.matched_horizon else None
        note=(f"{top.name} has lower fees and a higher {top.matched_horizon} annualized return than the held fund." if held_return is not None and top.expense_ratio_percent is not None and held and held.expense_ratio_percent is not None and top.expense_ratio_percent < held.expense_ratio_percent and (top.matched_return_percent or -999) > held_return else "Ranked by lower expense ratio and matched-horizon annualized return; this is informational research, not personalized investment advice.")
    caveat = "Check brokerage availability, taxes, tracking error, holdings overlap, risk, and that past performance is not predictive."
    if warnings and not candidates:
        try:
            cached = cached_peer_research(conn, security_id)
            cached.warnings = list(dict.fromkeys(cached.warnings + warnings + ["Latest peer refresh failed; showing the previous cached research.", caveat]))
            return cached
        except ValueError:
            pass
    result=PeerResearch(security_id=security_id,retrieved_at=retrieved,provider="yahoo-search",candidates=candidates,note=note,warnings=warnings+[caveat])
    conn.execute("INSERT INTO reference_cache(cache_key,provider,payload_json,fetched_at) VALUES(?,?,?,?) ON CONFLICT(cache_key) DO UPDATE SET provider=excluded.provider,payload_json=excluded.payload_json,fetched_at=excluded.fetched_at",(f"security:{security_id}:peers",result.provider,result.model_dump_json(),retrieved))
    return result


def cached_peer_research(conn: sqlite3.Connection, security_id: int) -> PeerResearch:
    row=conn.execute("SELECT payload_json FROM reference_cache WHERE cache_key=?",(f"security:{security_id}:peers",)).fetchone()
    if not row: raise ValueError("No cached peer research is available.")
    return PeerResearch.model_validate_json(row["payload_json"])


def exposure_analysis(conn: sqlite3.Connection) -> ExposureAnalysis:
    positions = list_positions(conn)
    grouped: dict[int, dict] = {}
    for position in positions:
        item = grouped.setdefault(position.security_id, {
            "id": position.security_id, "name": position.security_name, "symbol": position.symbol,
            "type": position.security_type, "sector": position.sector, "country": position.investment_country,
            "currency": position.currency, "category": position.allocation_category, "value": 0.0,
        })
        item["value"] += position.total_fmv_display or 0
    compositions = {item.security_id: item for item in list_compositions(conn)}
    total = sum(item["value"] for item in grouped.values())
    funds = [item for item in grouped.values() if "fund" in item["type"].lower() or "etf" in item["type"].lower()]
    held_fund_ids = {item["id"] for item in funds}
    exposure: dict[str, dict[str, dict]] = {key: {} for key in ("company", "sector", "country", "currency", "asset_category")}

    def add(dimension: str, key: str, label: str, value: float, confidence: str, source: str):
        target = exposure[dimension].setdefault(key, {"label": label, "value": 0.0, "confidence": confidence, "sources": set()})
        target["value"] += value
        target["sources"].add(source)
        if {"low": 0, "medium": 1, "high": 2}[confidence] < {"low": 0, "medium": 1, "high": 2}[target["confidence"]]:
            target["confidence"] = confidence

    def expand(security_id: int, value: float, path: tuple[int, ...], parent_name: str, fallback: dict,
               inherited_confidence: str = "high"):
        composition = compositions.get(security_id)
        if not composition or security_id in path or len(path) >= 10:
            company_key = (fallback.get("symbol") or fallback["name"]).upper()
            confidence = "low" if not fallback.get("symbol") else inherited_confidence
            add("company", company_key, fallback["name"], value, confidence, parent_name)
            for dim, key in (("sector", "sector"), ("country", "country"), ("currency", "currency"), ("asset_category", "category")):
                label = fallback.get(key) or ("Unresolved" if dim in ("country", "currency") else "Unclassified")
                add(dim, label, label, value, confidence, parent_name)
            return
        coverage = min(100.0, composition.coverage_percent)
        child_confidence = "low" if composition.stale else "high" if composition.source == "manual" else "medium"
        if inherited_confidence == "low":
            child_confidence = "low"
        elif inherited_confidence == "medium" and child_confidence == "high":
            child_confidence = "medium"
        for child in composition.constituents:
            child_value = value * child.weight_percent / 100
            child_data = {"name": child.name, "symbol": child.symbol, "sector": child.sector, "country": child.country,
                          "currency": child.currency, "category": child.asset_category}
            if child.linked_security_id and child.linked_security_id in compositions:
                expand(child.linked_security_id, child_value, path + (security_id,), parent_name, child_data, child_confidence)
            else:
                expand(-1, child_value, (), parent_name, child_data, child_confidence)
        if coverage < 100:
            unknown = value * (100 - coverage) / 100
            add("company", f"unmapped:{security_id}", f"Unmapped: {parent_name}", unknown, "low", parent_name)
            for dim in ("sector", "country", "currency", "asset_category"):
                add(dim, "Unmapped", "Unmapped", unknown, "low", parent_name)

    for item in grouped.values():
        expand(item["id"], item["value"], (), item["name"], item)

    def rows(dimension: str) -> list[ExposureRow]:
        return sorted([
            ExposureRow(key=key, label=data["label"], value=data["value"],
                        percent=data["value"] / total * 100 if total else 0,
                        confidence=data["confidence"], sources=sorted(data["sources"]))
            for key, data in exposure[dimension].items()
        ], key=lambda item: item.value, reverse=True)

    # Only held funds and compositions reachable from them can affect this
    # portfolio.  Compute that set before flattening, rather than expanding
    # every composition ever saved in the database.
    relevant_ids = set(held_fund_ids)
    pending = list(held_fund_ids)
    while pending:
        parent = pending.pop()
        composition = compositions.get(parent)
        if not composition:
            continue
        for constituent in composition.constituents:
            child = constituent.linked_security_id
            if child in compositions and child not in relevant_ids:
                relevant_ids.add(child)
                pending.append(child)

    flattened: dict[int, dict[str, float]] = {}
    flatten_cache: dict[tuple[int, int], dict[str, float]] = {}
    in_progress: set[int] = set()
    def flatten(fund_id: int, remaining_depth: int = 10) -> dict[str, float]:
        cached = flatten_cache.get((fund_id, remaining_depth))
        if cached is not None:
            return cached
        result: dict[str, float] = defaultdict(float)
        composition = compositions.get(fund_id)
        if not composition or fund_id in in_progress or remaining_depth <= 0:
            return result
        in_progress.add(fund_id)
        for item in composition.constituents:
            if item.linked_security_id in compositions:
                nested = flatten(item.linked_security_id, remaining_depth - 1)
                if nested:
                    for key, value in nested.items():
                        result[key] += item.weight_percent * value / 100
                    continue
            # ISIN/SEDOL/CUSIP is preferred over a ticker: tickers can be reused across markets.
            result[(item.identifier or item.symbol or item.constituent_key).upper()] += item.weight_percent
        in_progress.remove(fund_id)
        flatten_cache[(fund_id, remaining_depth)] = result
        return result
    for fund_id in relevant_ids:
        flattened[fund_id] = flatten(fund_id)
    overlaps = []
    fund_ids = sorted(held_fund_ids & set(flattened))
    for index, left in enumerate(fund_ids):
        for right in fund_ids[index + 1:]:
            overlap = sum(min(flattened[left][key], flattened[right].get(key, 0)) for key in flattened[left])
            if overlap > 0:
                overlaps.append(FundOverlap(left_security_id=left, left_name=grouped.get(left, {}).get("name", compositions[left].security_name),
                                            right_security_id=right, right_name=grouped.get(right, {}).get("name", compositions[right].security_name), overlap_percent=overlap))
    warnings = []
    stale = [item.security_name for key, item in compositions.items() if key in relevant_ids and item.stale]
    if stale:
        warnings.append(f"Stale composition metadata: {', '.join(stale)}.")
    if any(item.coverage_percent < 99.99 for key, item in compositions.items() if key in relevant_ids):
        warnings.append("Partial fund compositions retain their uncovered weight as Unmapped; exposure totals are not normalized.")
    top_ten = [item.security_name for key, item in compositions.items()
               if key in relevant_ids and item.holdings_scope == "top_10"]
    if top_ten:
        warnings.append(f"Top-10-only compositions may understate overlap and exposure: {', '.join(top_ten)}.")
    missing = [item["name"] for item in funds if item["id"] not in compositions]
    if missing:
        warnings.append(f"No look-through composition is available for: {', '.join(missing)}.")
    fund_value = sum(item["value"] for item in funds)
    mapped_fund_value = sum(item["value"] * min(100, sum(flattened[item["id"]].values())) / 100
                            for item in funds if item["id"] in compositions)
    coverage = mapped_fund_value / fund_value * 100 if fund_value else 100.0
    policy_drift: dict[str, list[InsightAllocationRow]] = {}
    dimension_map = {"asset_category": "asset_category", "country": "country", "currency": "currency"}
    for dimension, exposure_dimension in dimension_map.items():
        actual = {row.label: row.value for row in rows(exposure_dimension)}
        policy_drift[dimension] = [InsightAllocationRow(
            label=target.label, actual_amount=actual.get(target.label, 0),
            actual_percent=actual.get(target.label, 0) / total * 100 if total else 0,
            target_percent=target.target_percent, tolerance_percent=target.tolerance_percent,
            minimum_percent=max(0, target.target_percent - target.tolerance_percent),
            maximum_percent=min(100, target.target_percent + target.tolerance_percent),
            drift_percent=(actual.get(target.label, 0) / total * 100 if total else 0) - target.target_percent,
            rebalance_amount=total * target.target_percent / 100 - actual.get(target.label, 0),
            compliant=max(0, target.target_percent - target.tolerance_percent) <= (actual.get(target.label, 0) / total * 100 if total else 0) <= min(100, target.target_percent + target.tolerance_percent),
            outside_range_percent=(max(0, target.target_percent - target.tolerance_percent) - (actual.get(target.label, 0) / total * 100 if total else 0)
                                   if (actual.get(target.label, 0) / total * 100 if total else 0) < max(0, target.target_percent - target.tolerance_percent)
                                   else (actual.get(target.label, 0) / total * 100 if total else 0) - min(100, target.target_percent + target.tolerance_percent)
                                   if (actual.get(target.label, 0) / total * 100 if total else 0) > min(100, target.target_percent + target.tolerance_percent) else 0),
            policy_gap_amount=total * (max(0, target.target_percent - target.tolerance_percent) - (actual.get(target.label, 0) / total * 100 if total else 0)) / 100
            if (actual.get(target.label, 0) / total * 100 if total else 0) < max(0, target.target_percent - target.tolerance_percent)
            else total * ((actual.get(target.label, 0) / total * 100 if total else 0) - min(100, target.target_percent + target.tolerance_percent)) / 100
            if (actual.get(target.label, 0) / total * 100 if total else 0) > min(100, target.target_percent + target.tolerance_percent) else 0,
        ) for target in list_targets(conn, dimension)]
    return ExposureAnalysis(display_currency=positions[0].display_currency if positions else "USD", portfolio_value=total,
                            composition_coverage_percent=coverage, company=rows("company"), sector=rows("sector"),
                            country=rows("country"), currency=rows("currency"), asset_category=rows("asset_category"),
                            overlaps=sorted(overlaps, key=lambda item: item.overlap_percent, reverse=True),
                            compositions=[compositions[key] for key in sorted(held_fund_ids & set(compositions))], policy_drift=policy_drift, warnings=warnings)
