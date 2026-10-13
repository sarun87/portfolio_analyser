# SPDX-FileCopyrightText: Copyright (C) Arun Sriraman
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone

from backend.app.services.fx_service import SUPPORTED_CURRENCIES, convert_amount, get_display_currency
from backend.app.services.insight_service import get_assumptions
from backend.app.services.models import (
    FeeAnalysis, FeeHoldingCost, FeeProjection, FeeSettings, PortfolioFee, PortfolioFeeInput,
    SecurityFee, SecurityFeeInput,
)
from backend.app.services.portfolio_service import list_positions


FRESH_DAYS = 365


def _stale(as_of: str | None, reviewed: str) -> bool:
    raw = as_of or reviewed[:10]
    try:
        return (date.today() - date.fromisoformat(raw)).days > FRESH_DAYS
    except ValueError:
        return True


def list_security_fees(conn: sqlite3.Connection) -> list[SecurityFee]:
    rows = conn.execute("""SELECT s.id, s.name, m.expense_ratio_percent, m.provider AS source, m.as_of_date, m.reviewed_at
                           FROM securities s LEFT JOIN fund_metadata m ON m.security_id=s.id
                           WHERE EXISTS (SELECT 1 FROM positions p WHERE p.security_id=s.id)
                             AND EXISTS (SELECT 1 FROM positions current WHERE current.security_id=s.id
                               AND current.snapshot_date=(SELECT MAX(p2.snapshot_date) FROM positions p2 WHERE p2.account_id=current.account_id))
                             AND LOWER(s.security_type) <> 'cash'
                           ORDER BY s.name""").fetchall()
    return [SecurityFee(security_id=row["id"], security_name=row["name"], expense_ratio_percent=row["expense_ratio_percent"],
                        source=row["source"] or "yfinance refresh required", as_of_date=row["as_of_date"], reviewed_at=row["reviewed_at"] or "",
                        stale=True if not row["reviewed_at"] else _stale(row["as_of_date"], row["reviewed_at"])) for row in rows]


def save_security_fee(conn: sqlite3.Connection, security_id: int, payload: SecurityFeeInput) -> SecurityFee:
    if not conn.execute("SELECT 1 FROM securities WHERE id=?", (security_id,)).fetchone():
        raise ValueError("Security not found.")
    current = conn.execute("""SELECT 1 FROM positions p WHERE p.security_id=? AND
                              p.snapshot_date=(SELECT MAX(p2.snapshot_date) FROM positions p2 WHERE p2.account_id=p.account_id)
                              LIMIT 1""", (security_id,)).fetchone()
    if not current:
        raise ValueError("Security is not in the current portfolio.")
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""INSERT INTO security_fee_metadata(security_id, expense_ratio_percent, source, as_of_date, reviewed_at)
                    VALUES (?, ?, ?, ?, ?) ON CONFLICT(security_id) DO UPDATE SET expense_ratio_percent=excluded.expense_ratio_percent,
                    source=excluded.source, as_of_date=excluded.as_of_date, reviewed_at=excluded.reviewed_at""",
                 (security_id, payload.expense_ratio_percent, payload.source.strip() or "manual", payload.as_of_date, now))
    return next(item for item in list_security_fees(conn) if item.security_id == security_id)


def accept_public_fee(conn: sqlite3.Connection, security_id: int) -> SecurityFee:
    raise ValueError("Expense ratios are read-only and refreshed with Fund data.")


def list_portfolio_fees(conn: sqlite3.Connection) -> list[PortfolioFee]:
    return [PortfolioFee(id=row["id"], name=row["name"], fee_type=row["fee_type"], annual_percent=row["annual_percent"],
                         annual_amount=row["annual_amount"], currency=row["currency"], enabled=bool(row["enabled"]))
            for row in conn.execute("SELECT * FROM portfolio_fees ORDER BY id")]


def save_portfolio_fee(conn: sqlite3.Connection, payload: PortfolioFeeInput, fee_id: int | None = None) -> PortfolioFee:
    if payload.fee_type not in {"advisory_percent", "fixed_account"}:
        raise ValueError("Fee type must be advisory_percent or fixed_account.")
    if payload.fee_type == "advisory_percent" and payload.annual_percent is None:
        raise ValueError("An advisory fee requires an annual percentage.")
    if payload.fee_type == "fixed_account" and payload.annual_amount is None:
        raise ValueError("A fixed account fee requires an annual amount.")
    if payload.currency.upper() not in SUPPORTED_CURRENCIES:
        raise ValueError("Unsupported fee currency.")
    if fee_id is None:
        fee_id = conn.execute("""INSERT INTO portfolio_fees(name, fee_type, annual_percent, annual_amount, currency, enabled)
                                  VALUES (?, ?, ?, ?, ?, ?)""", (payload.name.strip(), payload.fee_type, payload.annual_percent,
                                  payload.annual_amount, payload.currency.upper(), int(payload.enabled))).lastrowid
    else:
        if not conn.execute("SELECT 1 FROM portfolio_fees WHERE id=?", (fee_id,)).fetchone():
            raise ValueError("Portfolio fee not found.")
        conn.execute("""UPDATE portfolio_fees SET name=?, fee_type=?, annual_percent=?, annual_amount=?, currency=?,
                        enabled=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""", (payload.name.strip(), payload.fee_type,
                        payload.annual_percent, payload.annual_amount, payload.currency.upper(), int(payload.enabled), fee_id))
    return next(item for item in list_portfolio_fees(conn) if item.id == fee_id)


def delete_portfolio_fee(conn: sqlite3.Connection, fee_id: int) -> None:
    if conn.execute("DELETE FROM portfolio_fees WHERE id=?", (fee_id,)).rowcount == 0:
        raise ValueError("Portfolio fee not found.")


def get_fee_settings(conn: sqlite3.Connection) -> FeeSettings:
    row = conn.execute("SELECT cash_reserve_months FROM fee_settings WHERE id=1").fetchone()
    return FeeSettings(cash_reserve_months=row["cash_reserve_months"] if row else 6)


def save_fee_settings(conn: sqlite3.Connection, payload: FeeSettings) -> FeeSettings:
    conn.execute("""INSERT INTO fee_settings(id, cash_reserve_months, updated_at) VALUES (1, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(id) DO UPDATE SET cash_reserve_months=excluded.cash_reserve_months,
                    updated_at=CURRENT_TIMESTAMP""", (payload.cash_reserve_months,))
    return get_fee_settings(conn)


def fee_analysis(conn: sqlite3.Connection) -> FeeAnalysis:
    display = get_display_currency(conn)
    grouped: dict[int, dict] = {}
    cash = 0.0
    for position in list_positions(conn):
        value = position.total_fmv_display or 0
        if position.security_type.lower() == "cash":
            cash += value
        item = grouped.setdefault(position.security_id, {"name": position.security_name, "value": 0.0,
                                                         "cash": position.security_type.lower() == "cash",
                                                         "type": position.security_type.lower()})
        item["value"] += value
    metadata = {item.security_id: item for item in list_security_fees(conn)}
    holdings = []
    fund_expenses = 0.0
    for security_id, item in grouped.items():
        meta = metadata.get(security_id)
        ratio = meta.expense_ratio_percent if meta else None
        cost = item["value"] * ratio / 100 if ratio is not None else None
        if cost is not None:
            fund_expenses += cost
        holdings.append(FeeHoldingCost(security_id=security_id, name=item["name"], value=item["value"],
                                       expense_ratio_percent=ratio, annual_cost=cost,
                                       confidence="low" if not meta or meta.stale else "high" if meta.source == "manual" else "medium"))
    portfolio_value = sum(item["value"] for item in grouped.values())
    schedules = list_portfolio_fees(conn)
    advisory = sum(portfolio_value * (fee.annual_percent or 0) / 100 for fee in schedules
                   if fee.enabled and fee.fee_type == "advisory_percent")
    fixed = sum(convert_amount(conn, fee.annual_amount or 0, fee.currency, display) or 0 for fee in schedules
                if fee.enabled and fee.fee_type == "fixed_account")
    total_fees = fund_expenses + advisory + fixed
    assumptions = get_assumptions(conn)
    settings = get_fee_settings(conn)
    reserve = assumptions.monthly_expenses * settings.cash_reserve_months if assumptions.monthly_expenses is not None else None
    idle = max(0, cash - reserve) if reserve is not None else None
    drag = idle * assumptions.expected_annual_return if idle is not None and assumptions.expected_annual_return is not None else None
    projections = []
    if assumptions.expected_annual_return is not None and portfolio_value > 0:
        proportional_rate = (fund_expenses + advisory) / portfolio_value
        for years in (1, 10, 20, 30):
            without = portfolio_value
            after = portfolio_value
            nominal = 0.0
            for _ in range(years):
                without *= 1 + assumptions.expected_annual_return
                after *= 1 + assumptions.expected_annual_return
                annual = min(after, max(0, after * proportional_rate + fixed))
                nominal += annual
                after = max(0, after - annual)
            projections.append(FeeProjection(years=years, cumulative_nominal_fees=nominal,
                                             ending_value_without_fees=without, ending_value_after_fees=after,
                                             opportunity_cost=without-after))
    warnings = ["Expense ratios and advisory fees are estimates applied to current portfolio values; actual billed fees may differ."]
    if any(item.expense_ratio_percent is None and ("fund" in grouped[item.security_id]["type"] or "etf" in grouped[item.security_id]["type"])
           for item in holdings):
        warnings.append("Some fund holdings have no expense-ratio metadata; total fund expenses may be understated.")
    stale_count = sum(1 for item in metadata.values() if item.expense_ratio_percent is not None and item.stale)
    if stale_count:
        warnings.append(f"Expense-ratio metadata is stale for {stale_count} holding{'s' if stale_count != 1 else ''}.")
    if assumptions.expected_annual_return is None:
        warnings.append("Set an expected annual return to calculate long-term opportunity cost and potential cash drag.")
    if reserve is None:
        warnings.append("Set monthly expenses to separate planned reserves from potentially idle cash.")
    return FeeAnalysis(display_currency=display, portfolio_value=portfolio_value, annual_fund_expenses=fund_expenses,
                       annual_advisory_fees=advisory, annual_fixed_fees=fixed, total_annual_fees=total_fees,
                       annual_fee_percent=total_fees/portfolio_value*100 if portfolio_value else 0,
                       cash_value=cash, reserve_target=reserve, potential_idle_cash=idle, potential_cash_drag=drag,
                       holdings=sorted(holdings, key=lambda item: item.annual_cost or 0, reverse=True),
                       portfolio_fees=schedules, projections=projections, warnings=warnings)
