from __future__ import annotations

import json
import math
import sqlite3
import statistics
from bisect import bisect_right
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

from backend.app.core.external_api_logging import open_external_url
from backend.app.services.models import (
    CorrelationRow, HistoryRefreshResult, ManualMarketSeriesInput, MarketHistoryInput, RiskAnalysis, RiskHolding, RiskSettings,
)
from backend.app.services.portfolio_service import list_positions
from backend.app.services.fx_service import get_display_currency


BENCHMARKS = {"USD": "^GSPC", "INR": "^NSEI", "GBP": "^FTSE", "EUR": "^STOXX50E"}
PROVIDER = "yahoo-chart-history"


def get_risk_settings(conn: sqlite3.Connection) -> RiskSettings:
    row = conn.execute("SELECT * FROM risk_settings WHERE id=1").fetchone()
    display = get_display_currency(conn)
    return RiskSettings(
        benchmark_symbol=row["benchmark_symbol"] if row and row["benchmark_symbol"] else BENCHMARKS[display],
        benchmark_currency=row["benchmark_currency"] if row and row["benchmark_currency"] else display,
        minimum_observations=row["minimum_observations"] if row else 60,
    )


def save_risk_settings(conn: sqlite3.Connection, payload: RiskSettings) -> RiskSettings:
    display = get_display_currency(conn)
    benchmark = (payload.benchmark_symbol or BENCHMARKS[display]).strip()
    currency = (payload.benchmark_currency or display).upper().strip()
    conn.execute("""INSERT INTO risk_settings(id, benchmark_symbol, benchmark_currency, minimum_observations, updated_at)
                    VALUES (1, ?, ?, ?, CURRENT_TIMESTAMP) ON CONFLICT(id) DO UPDATE SET
                    benchmark_symbol=excluded.benchmark_symbol, benchmark_currency=excluded.benchmark_currency,
                    minimum_observations=excluded.minimum_observations, updated_at=CURRENT_TIMESTAMP""",
                 (benchmark, currency, payload.minimum_observations))
    return get_risk_settings(conn)


def fetch_yahoo_history(symbol: str) -> tuple[str, list[tuple[str, float]]]:
    encoded = urllib.parse.quote(symbol)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=5y&interval=1d&events=div%2Csplits"
    request = urllib.request.Request(url, headers={"User-Agent": "portfolio-analyser/1.0"})
    with open_external_url(request, provider=PROVIDER, timeout=20, opener=urllib.request.urlopen) as response:
        payload = json.loads(response.read().decode("utf-8"))
    results = payload.get("chart", {}).get("result") or []
    if not results:
        raise ValueError("No historical data was returned.")
    result = results[0]
    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    adjusted = (indicators.get("adjclose") or [{}])[0].get("adjclose")
    if not adjusted:
        adjusted = (indicators.get("quote") or [{}])[0].get("close") or []
    points = []
    for timestamp, price in zip(timestamps, adjusted):
        if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
            continue
        day = datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat()
        points.append((day, float(price)))
    if len(points) < 2:
        raise ValueError("Historical response did not include enough valid adjusted prices.")
    return str(result.get("meta", {}).get("currency") or "USD").upper(), points


def _store_series(conn: sqlite3.Connection, key: str, series_type: str, symbol: str, currency: str,
                  points: list[tuple[str, float]], source: str, security_id: int | None = None) -> int:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""INSERT INTO market_series(series_key, series_type, security_id, symbol, currency, source, refreshed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(series_key) DO UPDATE SET symbol=excluded.symbol,
                    currency=excluded.currency, source=excluded.source, refreshed_at=excluded.refreshed_at""",
                 (key, series_type, security_id, symbol, currency, source, now))
    series_id = conn.execute("SELECT id FROM market_series WHERE series_key=?", (key,)).fetchone()["id"]
    conn.execute("DELETE FROM market_series_points WHERE series_id=?", (series_id,))
    conn.executemany("""INSERT INTO market_series_points(series_id, observation_date, adjusted_close)
                        VALUES (?, ?, ?) ON CONFLICT(series_id, observation_date) DO UPDATE SET
                        adjusted_close=excluded.adjusted_close""", [(series_id, day, value) for day, value in points])
    return len(points)


def save_manual_history(conn: sqlite3.Connection, security_id: int, payload: MarketHistoryInput) -> HistoryRefreshResult:
    row = conn.execute("SELECT id FROM securities WHERE id=?", (security_id,)).fetchone()
    if not row:
        raise ValueError("Security not found.")
    unique = {}
    for point in payload.observations:
        try:
            observed = date.fromisoformat(point.date)
        except ValueError as exc:
            raise ValueError("History dates must use YYYY-MM-DD.") from exc
        if observed > date.today():
            raise ValueError("History cannot contain future dates.")
        unique[observed.isoformat()] = point.adjusted_close
    if len(unique) < 2:
        raise ValueError("Manual history needs at least two unique dates.")
    points = sorted(unique.items())
    count = _store_series(conn, f"security:{security_id}", "security", payload.symbol, payload.currency.upper(), points, "manual", security_id)
    return HistoryRefreshResult(series_key=f"security:{security_id}", symbol=payload.symbol, refreshed=True,
                                observation_count=count, message="Manual adjusted-price history saved.")


def save_manual_market_series(conn: sqlite3.Connection, payload: ManualMarketSeriesInput) -> HistoryRefreshResult:
    if payload.series_type not in {"benchmark", "fx"}:
        raise ValueError("Manual reference series must be a benchmark or FX series.")
    expected_prefix = f"{payload.series_type}:"
    if not payload.series_key.startswith(expected_prefix):
        raise ValueError(f"The series key must start with {expected_prefix}")
    unique = {}
    for point in payload.observations:
        try:
            observed = date.fromisoformat(point.date)
        except ValueError as exc:
            raise ValueError("History dates must use YYYY-MM-DD.") from exc
        if observed > date.today():
            raise ValueError("History cannot contain future dates.")
        unique[observed.isoformat()] = point.adjusted_close
    if len(unique) < 2:
        raise ValueError("Manual history needs at least two unique dates.")
    count = _store_series(conn, payload.series_key, payload.series_type, payload.symbol,
                          payload.currency.upper(), sorted(unique.items()), "manual")
    return HistoryRefreshResult(series_key=payload.series_key, symbol=payload.symbol, refreshed=True,
                                observation_count=count, message="Manual reference history saved.")


def _fx_symbol(currency: str) -> str | None:
    return None if currency == "USD" else f"USD{currency}=X"


def refresh_market_history(conn: sqlite3.Connection) -> list[HistoryRefreshResult]:
    results: list[HistoryRefreshResult] = []
    currencies = set()
    rows = conn.execute("""SELECT s.id, s.symbol, MIN(p.currency) AS currency FROM securities s JOIN positions p ON p.security_id=s.id
                           WHERE s.symbol IS NOT NULL AND s.price_refresh_supported=1 AND LOWER(s.security_type) <> 'cash'
                             AND p.snapshot_date=(SELECT MAX(p2.snapshot_date) FROM positions p2 WHERE p2.account_id=p.account_id)
                           GROUP BY s.id, s.symbol""").fetchall()
    for row in rows:
        key = f"security:{row['id']}"
        existing = conn.execute("SELECT source, currency FROM market_series WHERE series_key=?", (key,)).fetchone()
        if existing and existing["source"] == "manual":
            count = conn.execute("""SELECT COUNT(*) AS count FROM market_series_points p JOIN market_series s ON s.id=p.series_id
                                    WHERE s.series_key=?""", (key,)).fetchone()["count"]
            results.append(HistoryRefreshResult(series_key=key, symbol=row["symbol"], refreshed=False,
                                                observation_count=count, message="Manual history preserved; public refresh was skipped."))
            currencies.add(existing["currency"])
            continue
        try:
            currency, points = fetch_yahoo_history(row["symbol"])
            count = _store_series(conn, key, "security", row["symbol"], currency or row["currency"], points, PROVIDER, row["id"])
            currencies.add(currency or row["currency"])
            results.append(HistoryRefreshResult(series_key=key, symbol=row["symbol"], refreshed=True,
                                                observation_count=count, message="Adjusted history refreshed."))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            results.append(HistoryRefreshResult(series_key=key, symbol=row["symbol"], refreshed=False, message=str(exc)))
            currencies.add(row["currency"])
    settings = get_risk_settings(conn)
    key = f"benchmark:{settings.benchmark_symbol}"
    existing = conn.execute("SELECT source FROM market_series WHERE series_key=?", (key,)).fetchone()
    if existing and existing["source"] == "manual":
        count = conn.execute("""SELECT COUNT(*) AS count FROM market_series_points p JOIN market_series s ON s.id=p.series_id
                                WHERE s.series_key=?""", (key,)).fetchone()["count"]
        results.append(HistoryRefreshResult(series_key=key, symbol=settings.benchmark_symbol or "", refreshed=False,
                                            observation_count=count, message="Manual history preserved; public refresh was skipped."))
    else:
        try:
            currency, points = fetch_yahoo_history(settings.benchmark_symbol or BENCHMARKS[get_display_currency(conn)])
            count = _store_series(conn, key, "benchmark", settings.benchmark_symbol or "", currency, points, PROVIDER)
            results.append(HistoryRefreshResult(series_key=key, symbol=settings.benchmark_symbol or "", refreshed=True,
                                                observation_count=count, message="Benchmark history refreshed."))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            results.append(HistoryRefreshResult(series_key=key, symbol=settings.benchmark_symbol or "",
                                                refreshed=False, message=str(exc)))
    currencies.update({get_display_currency(conn), settings.benchmark_currency or get_display_currency(conn)})
    for currency in sorted(currencies - {"USD"}):
        symbol = _fx_symbol(currency)
        if not symbol:
            continue
        key = f"fx:USD:{currency}"
        existing = conn.execute("SELECT source FROM market_series WHERE series_key=?", (key,)).fetchone()
        if existing and existing["source"] == "manual":
            count = conn.execute("""SELECT COUNT(*) AS count FROM market_series_points p JOIN market_series s ON s.id=p.series_id
                                    WHERE s.series_key=?""", (key,)).fetchone()["count"]
            results.append(HistoryRefreshResult(series_key=key, symbol=symbol, refreshed=False,
                                                observation_count=count, message="Manual history preserved; public refresh was skipped."))
            continue
        try:
            _, points = fetch_yahoo_history(symbol)
            count = _store_series(conn, key, "fx", symbol, currency, points, PROVIDER)
            results.append(HistoryRefreshResult(series_key=key, symbol=symbol, refreshed=True,
                                                observation_count=count, message="Historical FX refreshed."))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            results.append(HistoryRefreshResult(series_key=key, symbol=symbol, refreshed=False, message=str(exc)))
    return results


def _series(conn: sqlite3.Connection, key: str) -> tuple[str, dict[str, float]] | None:
    row = conn.execute("SELECT id, currency FROM market_series WHERE series_key=?", (key,)).fetchone()
    if not row:
        return None
    return row["currency"], {point["observation_date"]: point["adjusted_close"] for point in conn.execute(
        "SELECT observation_date, adjusted_close FROM market_series_points WHERE series_id=? ORDER BY observation_date", (row["id"],))}


def _converted_prices(conn: sqlite3.Connection, key: str, display: str) -> dict[str, float]:
    loaded = _series(conn, key)
    if not loaded:
        return {}
    currency, prices = loaded
    if currency == display:
        return prices
    source_fx = _series(conn, f"fx:USD:{currency}")[1] if currency != "USD" and _series(conn, f"fx:USD:{currency}") else None
    target_fx = _series(conn, f"fx:USD:{display}")[1] if display != "USD" and _series(conn, f"fx:USD:{display}") else None
    def rate_for_day(series: dict[str, float] | None, day: str) -> float | None:
        if not series:
            return None
        if day in series:
            return series[day]
        days = sorted(series)
        index = bisect_right(days, day) - 1
        if index < 0:
            return None
        prior = days[index]
        if (date.fromisoformat(day) - date.fromisoformat(prior)).days > 4:
            return None
        return series[prior]
    converted = {}
    for day, price in prices.items():
        source_per_usd = 1.0 if currency == "USD" else rate_for_day(source_fx, day)
        target_per_usd = 1.0 if display == "USD" else rate_for_day(target_fx, day)
        if source_per_usd and target_per_usd:
            converted[day] = price / source_per_usd * target_per_usd
    return converted


def _returns(prices: dict[str, float], trading_calendar: set[str] | None = None) -> dict[str, float]:
    result = {}
    previous = None
    previous_day = None
    calendar_index = {day: index for index, day in enumerate(sorted(trading_calendar or set()))}
    for day, price in sorted(prices.items()):
        if trading_calendar is not None and day not in calendar_index:
            continue
        consecutive = trading_calendar is None or (
            previous_day in calendar_index and calendar_index[day] == calendar_index[previous_day] + 1
        )
        if previous and previous > 0 and consecutive:
            result[day] = price / previous - 1
        previous = price
        previous_day = day
    return result


def _paired(left: dict[str, float], right: dict[str, float]) -> tuple[list[float], list[float]]:
    days = sorted(set(left) & set(right))
    return [left[day] for day in days], [right[day] for day in days]


def _cov(left: list[float], right: list[float]) -> float:
    if len(left) < 2:
        return 0.0
    lm, rm = statistics.fmean(left), statistics.fmean(right)
    return sum((a-lm)*(b-rm) for a, b in zip(left, right)) / (len(left)-1)


def _max_drawdown(returns: list[float]) -> float | None:
    if not returns:
        return None
    value = peak = 1.0
    worst = 0.0
    for item in returns:
        value *= 1 + item
        peak = max(peak, value)
        worst = min(worst, value / peak - 1)
    return worst * 100


def risk_analysis(conn: sqlite3.Connection) -> RiskAnalysis:
    display = get_display_currency(conn)
    settings = get_risk_settings(conn)
    grouped: dict[int, dict] = {}
    cash_grouped: dict[int, dict] = {}
    positions = list_positions(conn)
    total_portfolio = sum(max(0, position.total_fmv_display or 0) for position in positions)
    cash_value = sum(max(0, position.total_fmv_display or 0) for position in positions if position.security_type.lower() == "cash")
    for position in positions:
        if position.security_type.lower() == "cash":
            item = cash_grouped.setdefault(position.security_id, {"name": position.security_name, "symbol": position.symbol, "value": 0.0})
            item["value"] += position.total_fmv_display or 0
            continue
        item = grouped.setdefault(position.security_id, {"name": position.security_name, "symbol": position.symbol, "value": 0.0})
        item["value"] += position.total_fmv_display or 0
    benchmark_key = f"benchmark:{settings.benchmark_symbol}"
    raw_benchmark = _series(conn, benchmark_key)
    trading_calendar = set(raw_benchmark[1]) if raw_benchmark else None
    benchmark_returns = _returns(_converted_prices(conn, benchmark_key, display), trading_calendar)
    returns = {security_id: _returns(_converted_prices(conn, f"security:{security_id}", display), trading_calendar) for security_id in grouped}
    covered_ids = [security_id for security_id, values in returns.items() if len(values) >= settings.minimum_observations]
    covered_value = cash_value + sum(max(0, grouped[security_id]["value"]) for security_id in covered_ids)
    coverage = covered_value / total_portfolio * 100 if total_portfolio else 100.0
    weights = {security_id: max(0, grouped[security_id]["value"]) / covered_value for security_id in covered_ids} if covered_value else {}
    covariances: dict[tuple[int, int], float] = {}
    correlations = []
    for i, left in enumerate(covered_ids):
        for right in covered_ids[i:]:
            lvalues, rvalues = _paired(returns[left], returns[right])
            covariance = _cov(lvalues, rvalues)
            covariances[(left, right)] = covariances[(right, left)] = covariance
            if left != right and len(lvalues) >= settings.minimum_observations:
                denominator = statistics.stdev(lvalues) * statistics.stdev(rvalues)
                if denominator:
                    correlations.append(CorrelationRow(left_security_id=left, right_security_id=right,
                                                       correlation=max(-1, min(1, covariance/denominator)), observation_count=len(lvalues)))
    variance = sum(weights.get(i, 0)*weights.get(j, 0)*covariances.get((i, j), 0) for i in covered_ids for j in covered_ids)
    portfolio_sd = math.sqrt(max(0, variance))
    holdings = []
    betas = {}
    contributions = {}
    for security_id, item in grouped.items():
        values = returns[security_id]
        observation_count = len(values)
        volatility = statistics.stdev(values.values()) * math.sqrt(252) * 100 if observation_count >= 2 else None
        asset, benchmark = _paired(values, benchmark_returns)
        benchmark_variance = statistics.variance(benchmark) if len(benchmark) >= 2 else 0
        beta = _cov(asset, benchmark)/benchmark_variance if len(asset) >= settings.minimum_observations and benchmark_variance else None
        betas[security_id] = beta
        component = None
        if security_id in covered_ids and portfolio_sd:
            component_variance = weights[security_id] * sum(covariances.get((security_id, other), 0)*weights[other] for other in covered_ids)
            component = component_variance / variance * 100 if variance else None
        contributions[security_id] = component
        confidence = "high" if observation_count >= 1000 else "medium" if observation_count >= 252 else "low"
        series_meta = conn.execute("""SELECT MAX(p.observation_date) AS latest FROM market_series s
                                      LEFT JOIN market_series_points p ON p.series_id=s.id WHERE s.series_key=?""",
                                   (f"security:{security_id}",)).fetchone()
        latest = series_meta["latest"] if series_meta else None
        stale = not latest or (date.today() - date.fromisoformat(latest)).days > 14
        warning_parts = []
        if observation_count < settings.minimum_observations:
            warning_parts.append(f"Only {observation_count} returns; at least {settings.minimum_observations} are required.")
        if stale:
            warning_parts.append("Historical prices are more than 14 days old or missing.")
            confidence = "low"
        warning = " ".join(warning_parts) or None
        holdings.append(RiskHolding(security_id=security_id, name=item["name"], symbol=item["symbol"],
                                    portfolio_weight_percent=item["value"]/total_portfolio*100 if total_portfolio else 0,
                                    observation_count=observation_count, annualized_volatility_percent=volatility,
                                    beta=beta, risk_contribution_percent=component,
                                    max_drawdown_percent=_max_drawdown([value for _, value in sorted(values.items())]),
                                    confidence=confidence, warning=warning))
    for security_id, item in cash_grouped.items():
        holdings.append(RiskHolding(
            security_id=security_id, name=item["name"], symbol=item["symbol"],
            portfolio_weight_percent=item["value"] / total_portfolio * 100 if total_portfolio else 0,
            observation_count=0, annualized_volatility_percent=0, beta=0, risk_contribution_percent=0,
            max_drawdown_percent=0, confidence="high", warning="Cash is modeled with zero market volatility and beta.",
        ))
    common_days = set.intersection(*(set(returns[item]) for item in covered_ids)) if covered_ids else set()
    portfolio_returns = [sum(weights[item]*returns[item][day] for item in covered_ids) for day in sorted(common_days)]
    warnings = ["Risk estimates use current static weights and historical adjusted returns; they are not forecasts."]
    if coverage < 99.99:
        warnings.append(f"Risk history covers {coverage:.1f}% of portfolio value, including cash as zero-volatility coverage; metrics are for the covered portfolio only.")
    if not benchmark_returns:
        warnings.append("Benchmark history is unavailable, so beta cannot be estimated.")
    latest_benchmark = conn.execute("""SELECT MAX(p.observation_date) AS latest FROM market_series s
                                       LEFT JOIN market_series_points p ON p.series_id=s.id WHERE s.series_key=?""",
                                    (f"benchmark:{settings.benchmark_symbol}",)).fetchone()
    if latest_benchmark and latest_benchmark["latest"] and (date.today() - date.fromisoformat(latest_benchmark["latest"])).days > 14:
        warnings.append("Benchmark history is more than 14 days old.")
    return RiskAnalysis(display_currency=display, benchmark_symbol=settings.benchmark_symbol or BENCHMARKS[display],
                        coverage_percent=coverage,
                        covered_portfolio_volatility_percent=portfolio_sd*math.sqrt(252)*100 if covered_ids else 0.0 if cash_value else None,
                        covered_portfolio_beta=sum(weights[item]*betas[item] for item in covered_ids if betas[item] is not None) if any(betas.get(item) is not None for item in covered_ids) else None,
                        covered_portfolio_max_drawdown_percent=_max_drawdown(portfolio_returns),
                        holdings=sorted(holdings, key=lambda item: abs(item.risk_contribution_percent) if item.risk_contribution_percent is not None else -1, reverse=True),
                        correlations=sorted(correlations, key=lambda item: abs(item.correlation), reverse=True), warnings=warnings)
