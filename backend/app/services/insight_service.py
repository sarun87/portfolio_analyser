from __future__ import annotations

import math
import random
import sqlite3
from datetime import date, datetime
from typing import Optional, Union

from backend.app.services.fx_service import SUPPORTED_CURRENCIES, convert_amount, get_display_currency
from backend.app.services.company_identity import ALPHABET_LABEL, company_identity
from backend.app.services.models import (
    AllocationTarget, FinancialAssumptions, Goal, GoalCreate, GoalUpdate, GoalsSummary,
    AllocationPolicySummary, AnalyticsPoint, InsightAllocationRow, InsightFinding, InsightTaxLot, Insights,
    SnapshotAllocationShift, SnapshotComparison, SnapshotHoldingChange, TimeSeriesPoint, ScheduledExpense, ScheduledExpenseInput,
)
from backend.app.services.portfolio_service import list_positions
from backend.app.services.repositories import get_setting


ASSUMPTION_FIELDS = [
    "expected_annual_return", "annual_volatility", "inflation_rate", "monthly_household_contribution",
    "monthly_expenses", "current_age", "end_age", "short_term_tax_rate", "long_term_tax_rate", "long_term_holding_days",
]


def get_assumptions(conn: sqlite3.Connection) -> FinancialAssumptions:
    row = conn.execute("SELECT * FROM financial_assumptions WHERE id = 1").fetchone()
    return FinancialAssumptions(**dict(row)) if row else FinancialAssumptions()


def save_assumptions(conn: sqlite3.Connection, payload: FinancialAssumptions) -> FinancialAssumptions:
    if payload.current_age is not None and payload.end_age <= payload.current_age:
        raise ValueError("End age must be greater than current age.")
    values = [getattr(payload, field) for field in ASSUMPTION_FIELDS]
    conn.execute(
        f"INSERT INTO financial_assumptions (id, {', '.join(ASSUMPTION_FIELDS)}) VALUES (1, {', '.join(['?'] * len(ASSUMPTION_FIELDS))}) "
        f"ON CONFLICT(id) DO UPDATE SET {', '.join(f'{field}=excluded.{field}' for field in ASSUMPTION_FIELDS)}, updated_at=CURRENT_TIMESTAMP",
        values,
    )
    return get_assumptions(conn)


def _validate_scheduled_expense(payload: ScheduledExpenseInput) -> None:
    if not payload.name.strip():
        raise ValueError("Expense name is required.")
    if payload.expense_type not in {"one_time", "date_range"}:
        raise ValueError("Expense type must be one_time or date_range.")
    if payload.currency.upper() not in SUPPORTED_CURRENCIES:
        raise ValueError("Unsupported expense currency.")
    try:
        if payload.expense_type == "one_time":
            if not payload.expense_date:
                raise ValueError("A one-time expense requires a date.")
            datetime.strptime(payload.expense_date, "%Y-%m-%d")
        else:
            if not payload.start_date or not payload.end_date:
                raise ValueError("A date-range expense requires a start and end date.")
            start, end = datetime.strptime(payload.start_date, "%Y-%m-%d").date(), datetime.strptime(payload.end_date, "%Y-%m-%d").date()
            if end < start:
                raise ValueError("Expense end date must not be before its start date.")
    except ValueError as exc:
        if str(exc).startswith("Expense") or str(exc).startswith("A "):
            raise
        raise ValueError("Expense dates must use YYYY-MM-DD.") from exc


def list_scheduled_expenses(conn: sqlite3.Connection) -> list[ScheduledExpense]:
    return [ScheduledExpense(**dict(row)) for row in conn.execute("SELECT * FROM scheduled_expenses ORDER BY COALESCE(expense_date, start_date), id")]


def save_scheduled_expense(conn: sqlite3.Connection, payload: ScheduledExpenseInput, expense_id: int | None = None) -> ScheduledExpense:
    _validate_scheduled_expense(payload)
    values = (payload.name.strip(), payload.expense_type, payload.amount, payload.currency.upper(), payload.expense_date, payload.start_date, payload.end_date)
    if expense_id is None:
        expense_id = conn.execute("INSERT INTO scheduled_expenses(name, expense_type, amount, currency, expense_date, start_date, end_date) VALUES (?, ?, ?, ?, ?, ?, ?)", values).lastrowid
    else:
        if not conn.execute("SELECT 1 FROM scheduled_expenses WHERE id=?", (expense_id,)).fetchone():
            raise ValueError("Scheduled expense not found.")
        conn.execute("UPDATE scheduled_expenses SET name=?, expense_type=?, amount=?, currency=?, expense_date=?, start_date=?, end_date=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", values + (expense_id,))
    return next(item for item in list_scheduled_expenses(conn) if item.id == expense_id)


def delete_scheduled_expense(conn: sqlite3.Connection, expense_id: int) -> None:
    if not conn.execute("DELETE FROM scheduled_expenses WHERE id=?", (expense_id,)).rowcount:
        raise ValueError("Scheduled expense not found.")


def list_targets(conn: sqlite3.Connection, dimension: Optional[str] = None) -> list[AllocationTarget]:
    query = "SELECT id, dimension, label, target_percent, tolerance_percent FROM allocation_targets"
    rows = conn.execute(query + (" WHERE dimension = ?" if dimension else "") + " ORDER BY dimension, label", (dimension,) if dimension else ()).fetchall()
    return [AllocationTarget(**dict(row)) for row in rows]


def replace_targets(conn: sqlite3.Connection, dimension: str, targets: list[AllocationTarget]) -> list[AllocationTarget]:
    if dimension not in {"asset_category", "country", "currency"}:
        raise ValueError("Unsupported allocation target dimension.")
    if any(target.dimension != dimension for target in targets):
        raise ValueError("Target dimension must match the requested dimension.")
    if len({target.label.strip().lower() for target in targets}) != len(targets) or any(not target.label.strip() for target in targets):
        raise ValueError("Target labels must be unique and non-empty.")
    total = sum(target.target_percent for target in targets)
    if targets and not math.isclose(total, 100, abs_tol=0.01):
        raise ValueError("Configured allocation targets must total 100%.")
    conn.execute("DELETE FROM allocation_targets WHERE dimension = ?", (dimension,))
    conn.executemany(
        "INSERT INTO allocation_targets (dimension, label, target_percent, tolerance_percent) VALUES (?, ?, ?, ?)",
        [(dimension, target.label.strip(), target.target_percent, target.tolerance_percent) for target in targets],
    )
    return list_targets(conn, dimension)


def _validate_goal(payload: Union[GoalCreate, GoalUpdate]) -> None:
    try:
        datetime.strptime(payload.target_month, "%Y-%m")
    except ValueError as exc:
        raise ValueError("Target month must use YYYY-MM.") from exc
    for currency in (payload.target_currency, payload.allocated_currency, payload.contribution_currency):
        if currency.upper().strip() not in SUPPORTED_CURRENCIES:
            raise ValueError("Unsupported currency.")


def _months_until(target_month: str) -> int:
    target = datetime.strptime(target_month, "%Y-%m").date()
    today = date.today()
    return max(0, (target.year - today.year) * 12 + target.month - today.month)


def _goal_projection_ready(a: FinancialAssumptions) -> bool:
    return all(getattr(a, field) is not None for field in ("expected_annual_return", "annual_volatility"))


def _projection_ready(a: FinancialAssumptions) -> bool:
    return all(getattr(a, field) is not None for field in ("expected_annual_return", "annual_volatility", "inflation_rate", "monthly_household_contribution"))


def _lifetime_projection_ready(a: FinancialAssumptions) -> bool:
    return _projection_ready(a) and a.current_age is not None and a.end_age > a.current_age and a.monthly_expenses is not None


def _goal_from_row(conn: sqlite3.Connection, row, assumptions: FinancialAssumptions) -> Goal:
    display = get_display_currency(conn)
    result = dict(row)
    target = convert_amount(conn, row["target_amount"], row["target_currency"], display) or 0
    allocated = convert_amount(conn, row["allocated_amount"], row["allocated_currency"], display) or 0
    contribution = convert_amount(conn, row["monthly_contribution"], row["contribution_currency"], display) or 0
    result.update(target_amount_display=target, allocated_amount_display=allocated, monthly_contribution_display=contribution, display_currency=display)
    if _goal_projection_ready(assumptions):
        months = _months_until(row["target_month"])
        monthly_return = (1 + assumptions.expected_annual_return) ** (1 / 12) - 1
        projected = allocated * (1 + monthly_return) ** months + contribution * (((1 + monthly_return) ** months - 1) / monthly_return if monthly_return else months)
        result.update(
            projected_value=projected,
            projected_shortfall_surplus=projected - target,
        )
        factor = ((1 + monthly_return) ** months - 1) / monthly_return if monthly_return else months
        result["required_monthly_contribution"] = max(0, (target - allocated * (1 + monthly_return) ** months) / factor) if factor else max(0, target - allocated)
        result["probability_of_reaching"] = _goal_probability(allocated, contribution, target, months, assumptions)
    return Goal(**result)


def _goal_probability(start: float, monthly: float, target: float, months: int, a: FinancialAssumptions) -> float:
    if months == 0:
        return 100.0 if start >= target else 0.0
    rng = random.Random(20260804)
    mu = (1 + a.expected_annual_return) ** (1 / 12) - 1
    sigma = a.annual_volatility / math.sqrt(12)
    wins = 0
    for _ in range(10000):
        value = start
        for _ in range(months):
            value = value * (1 + rng.gauss(mu, sigma)) + monthly
        wins += value >= target
    return wins / 100


def list_goals_summary(conn: sqlite3.Connection) -> GoalsSummary:
    assumptions = get_assumptions(conn)
    goals = [_goal_from_row(conn, row, assumptions) for row in conn.execute("SELECT * FROM goals ORDER BY priority IS NULL, priority, target_month, id")]
    positions = list_positions(conn)
    static_rows = conn.execute("SELECT category, currency, amount FROM static_accounts WHERE category IN ('Bank Account', 'Retirement Account')").fetchall()
    investable = sum(p.total_fmv_display or 0 for p in positions) + sum(convert_amount(conn, r["amount"], r["currency"], get_display_currency(conn)) or 0 for r in static_rows)
    allocated = sum(goal.allocated_amount_display for goal in goals)
    return GoalsSummary(display_currency=get_display_currency(conn), investable_financial_assets=investable, total_allocated=allocated, unallocated_remainder=investable-allocated, over_allocated=allocated > investable, goals=goals)


def create_goal(conn: sqlite3.Connection, payload: GoalCreate) -> Goal:
    _validate_goal(payload)
    fields = ["name", "description", "target_amount", "target_currency", "target_month", "allocated_amount", "allocated_currency", "monthly_contribution", "contribution_currency", "priority"]
    conn.execute(f"INSERT INTO goals ({', '.join(fields)}) VALUES ({', '.join(['?'] * len(fields))})", [getattr(payload, f) if not isinstance(getattr(payload, f), str) else getattr(payload, f).strip() for f in fields])
    return _goal_from_row(conn, conn.execute("SELECT * FROM goals WHERE id = last_insert_rowid()").fetchone(), get_assumptions(conn))


def update_goal(conn: sqlite3.Connection, goal_id: int, payload: GoalUpdate) -> Goal:
    _validate_goal(payload)
    if not conn.execute("SELECT 1 FROM goals WHERE id = ?", (goal_id,)).fetchone():
        raise ValueError("Goal not found.")
    fields = ["name", "description", "target_amount", "target_currency", "target_month", "allocated_amount", "allocated_currency", "monthly_contribution", "contribution_currency", "priority"]
    conn.execute(f"UPDATE goals SET {', '.join(f'{f}=?' for f in fields)}, updated_at=CURRENT_TIMESTAMP WHERE id=?", [getattr(payload, f) for f in fields] + [goal_id])
    return _goal_from_row(conn, conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone(), get_assumptions(conn))


def delete_goal(conn: sqlite3.Connection, goal_id: int) -> None:
    if conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,)).rowcount == 0:
        raise ValueError("Goal not found.")


def insights(conn: sqlite3.Connection, *, include_forecast: bool = True) -> Insights:
    display, positions, a = get_display_currency(conn), list_positions(conn), get_assumptions(conn)
    values = [(p, p.total_fmv_display or 0) for p in positions]
    total = sum(v for _, v in values)
    security_totals: dict[str, AnalyticsPoint] = {}
    for position, value in values:
        key, label = company_identity(position.symbol, position.security_name)
        existing = security_totals.get(key)
        if existing:
            existing.value += value
        else:
            security_totals[key] = AnalyticsPoint(label=label, value=value)
    concentration = sorted(security_totals.values(), key=lambda point: point.value, reverse=True)
    aggregate = lambda key: [AnalyticsPoint(label=k, value=v) for k, v in sorted(_totals(values, key).items())]
    currency, country, exchange = aggregate(lambda p: p.currency), aggregate(lambda p: p.investment_country), aggregate(lambda p: p.exchange)
    drifts = {}
    dimensions = {"asset_category": lambda p: p.allocation_category, "country": lambda p: p.investment_country, "currency": lambda p: p.currency}
    for dimension, key in dimensions.items():
        actual = _totals(values, key)
        allocation_total = total
        if dimension == "asset_category":
            static_allocation = conn.execute("SELECT category, currency, amount FROM static_accounts WHERE category IN ('Bank Account','Retirement Account')").fetchall()
            for item in static_allocation:
                amount = convert_amount(conn, item["amount"], item["currency"], display) or 0
                label = "Cash" if item["category"] == "Bank Account" else "Retirement"
                actual[label] = actual.get(label, 0) + amount
                allocation_total += amount
        targets = list_targets(conn, dimension)
        rows = []
        for target in targets:
            actual_amount = actual.get(target.label, 0)
            actual_percent = actual_amount / allocation_total * 100 if allocation_total else 0
            minimum = max(0, target.target_percent - target.tolerance_percent)
            maximum = min(100, target.target_percent + target.tolerance_percent)
            outside = minimum - actual_percent if actual_percent < minimum else actual_percent - maximum if actual_percent > maximum else 0
            rows.append(InsightAllocationRow(
                label=target.label, actual_amount=actual_amount, actual_percent=actual_percent,
                target_percent=target.target_percent, tolerance_percent=target.tolerance_percent,
                minimum_percent=minimum, maximum_percent=maximum,
                drift_percent=actual_percent - target.target_percent,
                rebalance_amount=allocation_total * target.target_percent / 100 - actual_amount,
                compliant=outside == 0, outside_range_percent=outside, policy_gap_amount=allocation_total * outside / 100,
            ))
        drifts[dimension] = rows
    cash_brokerage = sum(v for p, v in values if p.security_type.lower() == "cash")
    static = conn.execute("SELECT category, currency, amount FROM static_accounts").fetchall()
    immediate = cash_brokerage + sum(convert_amount(conn, r["amount"], r["currency"], display) or 0 for r in static if r["category"] == "Bank Account")
    retirement = sum(convert_amount(conn, r["amount"], r["currency"], display) or 0 for r in static if r["category"] == "Retirement Account")
    real_estate = sum(convert_amount(conn, r["current_value"], r["currency"], display) or 0 for r in conn.execute("SELECT currency, current_value FROM real_estate_assets"))
    private_equity = sum(convert_amount(conn, r["value"], r["currency"], display) or 0 for r in conn.execute("SELECT currency, quantity * last_valuation_per_unit AS value FROM private_equity_assets"))
    tax_lots = []
    today = date.today()
    for p, value in values:
        gain = p.unrealized_gain_loss
        try: acquired = datetime.strptime(p.acquisition_date or "", "%Y-%m-%d").date()
        except ValueError: acquired = None
        days = (today-acquired).days if acquired else None
        kind = "Unknown holding period" if days is None else ("Long-term" if days >= (a.long_term_holding_days or 365) else "Short-term")
        rate = a.long_term_tax_rate if kind == "Long-term" else a.short_term_tax_rate if kind == "Short-term" else None
        tax_lots.append(InsightTaxLot(position_id=p.id, security_name=p.security_name, acquisition_date=p.acquisition_date, holding_days=days, classification=kind, gain=gain, indicative_tax=max(0, gain or 0)*rate if rate is not None else None))
    history = _history(conn, display)
    holding_change = _holding_change(conn, display)
    drawdown = _drawdown(history)
    rolling = {str(m): _growth(history, m) for m in (1, 3, 12)}
    financial_assets = total + sum(convert_amount(conn, r["amount"], r["currency"], display) or 0 for r in static if r["category"] in ("Bank Account", "Retirement Account"))
    # Monte Carlo is intentionally opt-in: the basic Insights page should not
    # make every analytics visit simulate thousands of lifetime paths.
    forecast = _forecast(financial_assets, a, list_scheduled_expenses(conn), conn, display) if include_forecast and _lifetime_projection_ready(a) else None
    runway = immediate/a.monthly_expenses if a.monthly_expenses else None
    comparison = snapshot_comparison(conn)
    policy_rows = [row for rows in drifts.values() for row in rows]
    breaches = [row for row in policy_rows if not row.compliant]
    policy = AllocationPolicySummary(
        configured_targets=len(policy_rows), compliant_targets=len(policy_rows) - len(breaches), breached_targets=len(breaches),
        unconfigured_dimensions=[dimension for dimension, rows in drifts.items() if not rows],
        largest_breach=max(breaches, key=lambda row: row.outside_range_percent, default=None),
    )
    findings = review_findings(conn, positions, total, concentration, drifts, immediate, runway)
    return Insights(display_currency=display, projection_setup_required=forecast is None, concentration=concentration, top_5_share=sum(x.value for x in concentration[:5])/total*100 if total else 0, top_10_share=sum(x.value for x in concentration[:10])/total*100 if total else 0, currency_exposure=currency, country_exposure=country, exchange_exposure=exchange, allocation_drift=drifts, allocation_policy=policy, liquidity=[AnalyticsPoint(label="Immediate cash / bank", value=immediate), AnalyticsPoint(label="Marketable securities", value=sum(v for p,v in values if p.security_type.lower() != "cash")), AnalyticsPoint(label="Retirement / restricted", value=retirement), AnalyticsPoint(label="Real estate", value=real_estate), AnalyticsPoint(label="Private equity (non-marketable / restricted)", value=private_equity)], cash_runway_months=runway, tax_lots=tax_lots, value_history=history, rolling_growth=rolling, drawdown=drawdown, holding_value_change=holding_change, forecast=forecast, findings=findings, snapshot_comparison=comparison)


_SEVERITY_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def review_findings(conn, positions, total, concentration, drifts, immediate, runway):
    """Build explainable, ranked observations from data the app actually has."""
    display = get_display_currency(conn)
    findings = []
    if total and concentration:
        for largest in concentration:
            share = largest.value / total * 100
            if share >= 20:
                severity = "critical" if share >= 50 else "high" if share >= 35 else "medium"
                excess = max(0, largest.value - total * .20)
                findings.append(InsightFinding(
                    id=f"concentration-{positions[0].snapshot_date if positions else 'none'}-{largest.label}", category="concentration",
                    severity=severity, title=f"{largest.label} is {share:.1f}% of the portfolio",
                    impact_amount=excess, impact_percent=share, impact_label="Value above 20% threshold", impact_percent_label="Portfolio share", confidence="high",
                    evidence=[f"Current value: {largest.value:,.2f} {display}", f"Portfolio value: {total:,.2f} {display}", "Review threshold: 20%"],
                    explanation="A single holding can dominate portfolio outcomes even when the rest of the portfolio is diversified.",
                    suggested_actions=["Review whether this concentration is intentional.", "Consider directing future contributions toward underweight allocations before considering sales."],
                    navigation={"page": "positions", "filters": (
                        {"any_of": [{"symbol": "GOOG"}, {"symbol": "GOOGL"}]}
                        if largest.label == ALPHABET_LABEL else {"security_name": largest.label}
                    )}
                ))
    for dimension, rows in drifts.items():
        for row in rows:
            if not row.compliant:
                direction = "over" if row.drift_percent > 0 else "under"
                findings.append(InsightFinding(
                    id=f"policy-{dimension}-{row.label}", category="allocation_policy",
                    severity="high" if row.outside_range_percent >= 10 else "medium",
                    title=f"{row.label} is outside its {row.minimum_percent:.1f}%–{row.maximum_percent:.1f}% policy range",
                    impact_amount=row.policy_gap_amount, impact_percent=row.outside_range_percent, impact_label="Approximate value outside policy range", impact_percent_label="Percentage points outside range", confidence="high",
                    evidence=[f"Actual: {row.actual_percent:.1f}%", f"Target: {row.target_percent:.1f}% ± {row.tolerance_percent:.1f} points", f"Allowed range: {row.minimum_percent:.1f}%–{row.maximum_percent:.1f}%", f"Approximate gap: {row.policy_gap_amount:,.2f} {display}"],
                    explanation="The current allocation is outside the range set by the household allocation policy.",
                    suggested_actions=["Review the target and confirm it still reflects your plan.", "Use available cash or new contributions to address underweights before evaluating sales."],
                    navigation={"page": "analytics", "section": "allocation_policy", "dimension": dimension, "label": row.label}
                ))
    cash_positions = sum((p.total_fmv_display or 0) for p in positions if p.security_type.lower() == "cash")
    if total and cash_positions / total >= .20:
        share = cash_positions / total * 100
        findings.append(InsightFinding(
            id="cash-drag", category="cash_drag", severity="medium", title=f"Brokerage cash is {share:.1f}% of invested assets",
            impact_amount=cash_positions, impact_percent=share, impact_label="Brokerage cash", impact_percent_label="Portfolio share", confidence="high",
            evidence=[f"Brokerage cash: {cash_positions:,.2f} {display}", f"Invested-asset base: {total:,.2f} {display}"],
            explanation="Cash can reduce volatility and fund near-term needs, but persistent excess cash may also reduce expected long-term growth.",
            suggested_actions=["Confirm how much cash is reserved for near-term spending.", "Review whether remaining cash should be assigned to a goal or allocation target."],
            navigation={"page": "positions", "filters": {"security_type": "Cash"}}
        ))
    base_currency = get_setting(conn, "decision_coach_base_currency")
    if not base_currency:
        base_currency = display
    currency_values = {}
    for position in positions:
        currency_values[position.currency] = currency_values.get(position.currency, 0) + (position.total_fmv_display or 0)
    foreign_currency, foreign_value = max(((currency, value) for currency, value in currency_values.items() if currency != base_currency), key=lambda item: item[1], default=(None, 0))
    if foreign_currency and total and foreign_value / total >= .30:
        share = foreign_value / total * 100
        findings.append(InsightFinding(
            id=f"currency-risk-{foreign_currency}", category="currency_risk", severity="high" if share >= 60 else "medium",
            title=f"{share:.1f}% of holdings are denominated in {foreign_currency}", impact_amount=foreign_value,
            impact_percent=share, impact_label=f"{foreign_currency}-denominated value", impact_percent_label="Portfolio share", confidence="medium",
            evidence=[f"Decision-coach base currency: {base_currency}", f"{foreign_currency}-denominated value: {foreign_value:,.2f} {display}", f"Portfolio share: {share:.1f}%"],
            explanation="Exchange-rate moves can materially change values in the display currency. Denomination is only a proxy and does not capture underlying company or fund exposures.",
            suggested_actions=["Check whether this currency exposure aligns with future spending and goals.", "Review underlying fund and company exposures before drawing a hedging conclusion."],
            navigation={"page": "positions", "filters": {"currency": foreign_currency}}
        ))
    if runway is not None and runway < 3:
        findings.append(InsightFinding(
            id="liquidity-runway", category="liquidity", severity="high" if runway < 1 else "medium",
            title=f"Immediate liquidity covers {runway:.1f} months of expenses", impact_amount=immediate, impact_percent=None, impact_label="Immediate liquidity", confidence="high",
            evidence=[f"Immediate cash and bank balances: {immediate:,.2f} {display}", f"Calculated runway: {runway:.1f} months", "Review threshold: 3 months"],
            explanation="A short liquidity runway can force asset sales during unfavorable markets or unexpected expenses.",
            suggested_actions=["Validate the monthly expense assumption.", "Review whether emergency reserves are adequate for your circumstances."]
        ))
    unclassified = [p for p in positions if p.allocation_category.lower() == "unclassified"]
    unresolved = [p for p in positions if p.exchange == "Unresolved" or p.investment_country == "Unresolved"]
    if unclassified or unresolved:
        affected = sum((p.total_fmv_display or 0) for p in {p.id: p for p in unclassified + unresolved}.values())
        findings.append(InsightFinding(
            id="missing-classification", category="data_quality", severity="medium", title="Some holdings have incomplete classifications",
            impact_amount=affected, impact_percent=affected / total * 100 if total else None, impact_label="Value with incomplete metadata", impact_percent_label="Portfolio share", confidence="high",
            evidence=[f"Unclassified positions: {len(unclassified)}", f"Unresolved location positions: {len(unresolved)}", f"Affected value: {affected:,.2f} {display}"],
            explanation="Incomplete metadata makes allocation, geography, and currency conclusions less reliable.",
            suggested_actions=["Review unresolved securities in Positions.", "Refresh or manually complete security classifications."],
            navigation={"page": "positions", "filters": {"any_of": [{"allocation_category": "Unclassified"}, {"exchange": "Unresolved"}, {"investment_country": "Unresolved"}]}, "actions": [
                {"label": f"Unclassified positions: {len(unclassified)}", "filters": {"allocation_category": "Unclassified"}},
                {"label": f"Unresolved location positions: {len(unresolved)}", "filters": {"any_of": [{"exchange": "Unresolved"}, {"investment_country": "Unresolved"}]}},
            ]}
        ))
    if positions:
        account_dates = {}
        account_values = {}
        account_rows = conn.execute("""
            SELECT p.account_id, p.snapshot_date, p.currency, SUM(COALESCE(p.total_fmv, 0)) AS value
            FROM positions p
            WHERE p.snapshot_date = (SELECT MAX(p2.snapshot_date) FROM positions p2 WHERE p2.account_id = p.account_id)
            GROUP BY p.account_id, p.snapshot_date, p.currency
        """).fetchall()
        for row in account_rows:
            account_id = row["account_id"]
            parsed = datetime.strptime(row["snapshot_date"], "%Y-%m-%d").date()
            account_dates[account_id] = max(account_dates.get(account_id, parsed), parsed)
            account_values[account_id] = account_values.get(account_id, 0) + (convert_amount(conn, row["value"], row["currency"], display) or 0)
        stale_accounts = [(key, snapshot_date, (date.today() - snapshot_date).days) for key, snapshot_date in account_dates.items() if (date.today() - snapshot_date).days > 45]
        if stale_accounts:
            oldest_age = max(item[2] for item in stale_accounts)
            oldest_date = min(item[1] for item in stale_accounts)
            affected = sum(account_values[item[0]] for item in stale_accounts)
            findings.append(InsightFinding(
                id="stale-snapshot", category="stale_data", severity="high" if oldest_age > 120 else "medium",
                title=f"{len(stale_accounts)} account snapshot{'s are' if len(stale_accounts) != 1 else ' is'} stale", impact_amount=affected, impact_percent=affected / total * 100 if total else None, impact_label="Value in stale accounts", impact_percent_label="Portfolio share", confidence="high",
                evidence=[f"Oldest account snapshot: {oldest_date.isoformat()}", f"Oldest age: {oldest_age} days", "Review threshold: 45 days"],
                explanation="Recommendations based on an old snapshot may not reflect the portfolio you own today.",
                suggested_actions=["Upload a newer holdings statement before making portfolio decisions."]
            ))
        stale_prices = []
        for position in positions:
            if position.security_type.lower() == "cash":
                continue
            raw_date = position.last_price_update or position.snapshot_date
            try:
                valuation_date = datetime.strptime(raw_date[:10], "%Y-%m-%d").date()
            except (TypeError, ValueError):
                stale_prices.append(position)
                continue
            if (date.today() - valuation_date).days > 14:
                stale_prices.append(position)
        if stale_prices:
            stale_ids = {position.security_id for position in stale_prices}
            affected = sum((position.total_fmv_display or 0) for position in stale_prices)
            findings.append(InsightFinding(
                id="stale-prices", category="stale_data", severity="medium",
                title=f"Valuations are stale for {len(stale_ids)} securities", impact_amount=affected,
                impact_percent=affected / total * 100 if total else None, impact_label="Value with stale prices", impact_percent_label="Portfolio share", confidence="high",
                evidence=[f"Securities beyond 14-day freshness threshold: {len(stale_ids)}", f"Affected value: {affected:,.2f} {display}"],
                explanation="Stale valuations can distort concentration, allocation drift, gains, and net-worth estimates.",
                suggested_actions=["Refresh supported market prices.", "For unsupported securities, verify and update the holding value manually."]
            ))
    return sorted(findings, key=lambda item: (_SEVERITY_ORDER[item.severity], item.impact_amount or 0), reverse=True)


def snapshot_comparison(conn: sqlite3.Connection) -> SnapshotComparison:
    dates = [row["snapshot_date"] for row in conn.execute("SELECT DISTINCT snapshot_date FROM positions ORDER BY snapshot_date DESC LIMIT 2")]
    disclosure = "Holdings snapshots do not identify trades, deposits, withdrawals, dividends, fees, or market movement. Activity labels are inferred and are not confirmed transactions; first-seen account coverage is labeled separately."
    if len(dates) < 2:
        return SnapshotComparison(available=False, latest_date=dates[0] if dates else None, disclosure=disclosure)
    latest_date, previous_date = dates
    display = get_display_currency(conn)
    snapshots = {latest_date: {}, previous_date: {}}
    for cutoff in (latest_date, previous_date):
        rows = conn.execute("""
            SELECT p.account_id, p.security_id, s.name, s.symbol, s.security_type, s.allocation_category,
                   p.currency, SUM(p.units) AS units, SUM(COALESCE(p.total_fmv, 0)) AS value
            FROM positions p JOIN securities s ON s.id = p.security_id
            WHERE p.snapshot_date = (
                SELECT MAX(p2.snapshot_date) FROM positions p2
                WHERE p2.account_id = p.account_id AND p2.snapshot_date <= ?
            )
            GROUP BY p.account_id, p.security_id, p.currency
        """, (cutoff,)).fetchall()
        for row in rows:
            value = convert_amount(conn, row["value"], row["currency"], display) or 0
            target = snapshots[cutoff]
            account_had_previous_coverage = conn.execute("SELECT 1 FROM positions WHERE account_id = ? AND snapshot_date <= ? LIMIT 1", (row["account_id"], previous_date)).fetchone() is not None
            item = target.setdefault(row["security_id"], {"name": row["name"], "symbol": row["symbol"], "type": row["security_type"], "category": row["allocation_category"], "units": 0.0, "value": 0.0, "coverage_only": True})
            item["units"] += row["units"] or 0
            item["value"] += value
            item["coverage_only"] = item["coverage_only"] and not account_had_previous_coverage
    previous, latest = snapshots[previous_date], snapshots[latest_date]
    changes = []
    for security_id in set(previous) | set(latest):
        old, new = previous.get(security_id), latest.get(security_id)
        before, after = old or new, new or old
        old_units, new_units = (old or {}).get("units", 0), (new or {}).get("units", 0)
        old_value, new_value = (old or {}).get("value", 0), (new or {}).get("value", 0)
        if old is None and new.get("coverage_only"): kind, label = "coverage_added", "First stored snapshot for this account; portfolio activity cannot be inferred"
        elif old is None: kind, label = "new", "Inferred addition; could be a purchase, transfer, or classification change"
        elif new is None: kind, label = "exited", "Inferred exit; could be a sale, transfer, or classification change"
        elif not math.isclose(old_units, new_units, abs_tol=1e-9): kind, label = "units_changed", "Units changed; trade versus transfer cannot be determined"
        else: kind, label = "valuation_only", "Units unchanged; value movement is consistent with price and/or FX movement"
        change = SnapshotHoldingChange(security_id=security_id, security_name=after["name"], symbol=after["symbol"], change_type=kind,
            previous_units=old_units, latest_units=new_units, units_change=new_units-old_units, previous_value=old_value, latest_value=new_value,
            value_change=new_value-old_value, value_change_percent=(new_value/old_value-1)*100 if old_value else None, activity_label=label)
        changes.append(change)
    new_holdings = sorted((c for c in changes if c.change_type == "new"), key=lambda c: c.latest_value, reverse=True)
    exited = sorted((c for c in changes if c.change_type == "exited"), key=lambda c: c.previous_value, reverse=True)
    changed = sorted((c for c in changes if c.change_type == "units_changed"), key=lambda c: abs(c.value_change), reverse=True)
    coverage = sorted((c for c in changes if c.change_type == "coverage_added"), key=lambda c: c.latest_value, reverse=True)
    unusual = sorted((c for c in changes if c.change_type == "valuation_only" and c.value_change_percent is not None and (abs(c.value_change_percent) >= 20 or math.isclose(abs(c.value_change_percent), 20, abs_tol=1e-9))), key=lambda c: abs(c.value_change), reverse=True)
    previous_total, latest_total = sum(x["value"] for x in previous.values()), sum(x["value"] for x in latest.values())
    def category_weights(snapshot, total):
        result = {}
        for item in snapshot.values(): result[item["category"]] = result.get(item["category"], 0) + item["value"]
        return {key: value / total * 100 if total else 0 for key, value in result.items()}
    old_weights, new_weights = category_weights(previous, previous_total), category_weights(latest, latest_total)
    shifts = [SnapshotAllocationShift(label=label, previous_percent=old_weights.get(label, 0), latest_percent=new_weights.get(label, 0), change_percent=new_weights.get(label, 0)-old_weights.get(label, 0)) for label in set(old_weights) | set(new_weights)]
    shifts = sorted((shift for shift in shifts if abs(shift.change_percent) >= 1), key=lambda shift: abs(shift.change_percent), reverse=True)
    old_cash = sum(x["value"] for x in previous.values() if x["type"].lower() == "cash")
    new_cash = sum(x["value"] for x in latest.values() if x["type"].lower() == "cash")
    return SnapshotComparison(available=True, latest_date=latest_date, previous_date=previous_date, latest_value=latest_total, previous_value=previous_total,
        total_value_change=latest_total-previous_total, total_value_change_percent=(latest_total/previous_total-1)*100 if previous_total else None,
        cash_change=new_cash-old_cash, new_holdings=new_holdings, exited_holdings=exited, position_changes=changed, coverage_changes=coverage,
        unusual_valuation_changes=unusual, allocation_shifts=shifts, disclosure=disclosure)


def _totals(values, key):
    result = {}
    for p, value in values: result[key(p)] = result.get(key(p), 0) + value
    return result

def _history(conn, display):
    totals = {}
    for r in conn.execute("SELECT snapshot_date, currency, SUM(COALESCE(total_fmv, 0)) value FROM positions GROUP BY snapshot_date, currency"):
        totals[r['snapshot_date']] = totals.get(r['snapshot_date'], 0) + (convert_amount(conn, r['value'], r['currency'], display) or 0)
    return [TimeSeriesPoint(date=k, value=v) for k,v in sorted(totals.items())]

def _drawdown(history):
    peak = 0
    result=[]
    for p in history:
        peak=max(peak,p.value); result.append(TimeSeriesPoint(date=p.date, value=(p.value/peak-1)*100 if peak else 0))
    return result

def _holding_change(conn, display):
    rows = conn.execute("""
        SELECT s.name, p.snapshot_date, p.currency, SUM(COALESCE(p.total_fmv, 0)) AS value
        FROM positions p JOIN securities s ON s.id = p.security_id
        GROUP BY s.id, p.snapshot_date, p.currency ORDER BY s.name, p.snapshot_date
    """).fetchall()
    values = {}
    for row in rows:
        value = convert_amount(conn, row["value"], row["currency"], display) or 0
        item = values.setdefault(row["name"], [None, 0])
        if item[0] is None: item[0] = value
        item[1] = value
    return sorted([AnalyticsPoint(label=name, value=latest - first) for name, (first, latest) in values.items()], key=lambda p: abs(p.value), reverse=True)

def _growth(history, months):
    if len(history) < 2: return None
    latest = datetime.strptime(history[-1].date, '%Y-%m-%d').date()
    candidates=[p for p in history[:-1] if (latest.year-datetime.strptime(p.date,'%Y-%m-%d').year)*12+latest.month-datetime.strptime(p.date,'%Y-%m-%d').month >= months]
    if not candidates or not candidates[-1].value: return None
    return (history[-1].value/candidates[-1].value-1)*100

def _month_index(value: date, origin: date) -> int:
    return (value.year - origin.year) * 12 + value.month - origin.month


def _scheduled_monthly_spend(expenses: list[ScheduledExpense], months: int, origin: date, inflation: float, conn, display: str) -> list[float]:
    result = [0.0] * (months + 1)
    for expense in expenses:
        amount = convert_amount(conn, expense.amount, expense.currency, display) or 0
        if expense.expense_type == "one_time" and expense.expense_date:
            index = _month_index(date.fromisoformat(expense.expense_date), origin)
            if 0 <= index <= months: result[index] += amount * (1 + inflation) ** (index / 12)
        elif expense.start_date and expense.end_date:
            start, end = _month_index(date.fromisoformat(expense.start_date), origin), _month_index(date.fromisoformat(expense.end_date), origin)
            duration = end - start + 1
            for index in range(max(0, start), min(months, end) + 1):
                result[index] += amount / duration * (1 + inflation) ** (index / 12)
    return result


def _forecast(start, a, expenses: list[ScheduledExpense], conn, display: str):
    months = (a.end_age - a.current_age) * 12
    mu=(1+a.expected_annual_return)**(1/12)-1; sigma=a.annual_volatility/math.sqrt(12); rng=random.Random(20260804)
    scheduled = _scheduled_monthly_spend(expenses, months, date.today(), a.inflation_rate, conn, display)
    # A dated item in the current calendar month is due in the opening period;
    # deduct it before recording the opening projection point rather than
    # silently dropping index zero from the monthly loop below.
    paths = [max(0, start - scheduled[0])] * 10000
    series=[]
    for month in range(months + 1):
        if month % 12 == 0 or month == months:
            ranked = sorted(paths)
            series.append({'month': month, 'age': a.current_age + month / 12, 'p10': ranked[999], 'p50': ranked[4999], 'p80': ranked[7999], 'p95': ranked[9499]})
        if month < months:
            spend = a.monthly_expenses * (1 + a.inflation_rate) ** (month / 12) + scheduled[month + 1]
            paths = [max(0, value * (1 + rng.gauss(mu, sigma)) + a.monthly_household_contribution - spend) for value in paths]
    terminal = series[-1]
    return {'series': series, 'months': months, 'current_age': a.current_age, 'end_age': a.end_age, 'monte_carlo_terminal': {key: terminal[key] for key in ('p10', 'p50', 'p80', 'p95')}, 'note':'Forecast includes planned spending, assumes constant FX rates, and is illustrative, not advice.'}
