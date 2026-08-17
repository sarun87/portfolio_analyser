from __future__ import annotations

import json
import math
import sqlite3
from datetime import date, datetime

from backend.app.services.fx_service import get_display_currency
from backend.app.services.insight_service import (
    _goal_probability, _months_until, get_assumptions, list_goals_summary, list_targets,
)
from backend.app.services.models import (
    SavedScenario, ScenarioAnalysis, ScenarioGoalResult, ScenarioInput, ScenarioMetrics,
    StressContributor, StressGoalResult, StressTestRequest, StressTestResult,
)
from backend.app.services.portfolio_service import list_positions
from backend.app.services.repositories import get_setting


def list_scenarios(conn: sqlite3.Connection) -> list[SavedScenario]:
    return [_saved_from_row(row) for row in conn.execute("SELECT * FROM saved_scenarios ORDER BY updated_at DESC, id DESC")]


def save_scenario(conn: sqlite3.Connection, payload: ScenarioInput) -> SavedScenario:
    _validate_scenario(payload)
    cursor = conn.execute(
        "INSERT INTO saved_scenarios (name, description, scenario_json) VALUES (?, ?, ?)",
        (payload.name.strip(), payload.description, payload.model_dump_json()),
    )
    return _saved_from_row(conn.execute("SELECT * FROM saved_scenarios WHERE id = ?", (cursor.lastrowid,)).fetchone())


def update_scenario(conn: sqlite3.Connection, scenario_id: int, payload: ScenarioInput) -> SavedScenario:
    _validate_scenario(payload)
    if conn.execute(
        "UPDATE saved_scenarios SET name=?, description=?, scenario_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (payload.name.strip(), payload.description, payload.model_dump_json(), scenario_id),
    ).rowcount == 0:
        raise ValueError("Scenario not found.")
    return _saved_from_row(conn.execute("SELECT * FROM saved_scenarios WHERE id = ?", (scenario_id,)).fetchone())


def delete_scenario(conn: sqlite3.Connection, scenario_id: int) -> None:
    if conn.execute("DELETE FROM saved_scenarios WHERE id = ?", (scenario_id,)).rowcount == 0:
        raise ValueError("Scenario not found.")


def _saved_from_row(row) -> SavedScenario:
    payload = json.loads(row["scenario_json"])
    payload.update(id=row["id"], name=row["name"], description=row["description"], created_at=row["created_at"], updated_at=row["updated_at"])
    return SavedScenario(**payload)


def _validate_scenario(payload: ScenarioInput) -> None:
    ids = [(change.security_id, change.currency or "") for change in payload.position_changes]
    if len(ids) != len(set(ids)):
        raise ValueError("A scenario may contain only one change per security.")


def _holdings(conn: sqlite3.Connection):
    holdings = {}
    for position in list_positions(conn):
        key = (position.security_id, position.currency)
        item = holdings.setdefault(key, {
            "id": position.security_id, "name": position.security_name, "type": position.security_type,
            "category": position.allocation_category, "sector": position.sector, "country": position.investment_country,
            "currency": position.currency, "value": 0.0,
        })
        item["value"] += position.total_fmv_display or 0
    return holdings


def _metrics(conn: sqlite3.Connection, holdings) -> ScenarioMetrics:
    total = sum(item["value"] for item in holdings.values())
    cash = sum(item["value"] for item in holdings.values() if item["type"].lower() == "cash")
    ranked = sorted(holdings.values(), key=lambda item: item["value"], reverse=True)
    largest = ranked[0] if ranked else None
    drifts = []
    dimensions = {"asset_category": "category", "country": "country", "currency": "currency"}
    for dimension, key in dimensions.items():
        actual_values = {}
        for item in holdings.values():
            actual_values[item[key]] = actual_values.get(item[key], 0) + item["value"]
        dimension_drifts = []
        for target in list_targets(conn, dimension):
            actual = actual_values.get(target.label, 0) / total * 100 if total else 0
            dimension_drifts.append(abs(actual - target.target_percent))
        if dimension_drifts:
            drifts.append(sum(dimension_drifts) / 2)
    expenses = get_assumptions(conn).monthly_expenses
    return ScenarioMetrics(
        portfolio_value=total, cash_value=cash, cash_runway_months=max(0, cash) / expenses if expenses else None,
        largest_holding=largest["name"] if largest else None,
        largest_holding_percent=largest["value"] / total * 100 if largest and total else 0,
        total_absolute_drift_percent=sum(drifts) if drifts else None,
    )


def analyze_scenario(conn: sqlite3.Connection, payload: ScenarioInput) -> ScenarioAnalysis:
    _validate_scenario(payload)
    display = get_display_currency(conn)
    current = _holdings(conn)
    proposed = {key: dict(item) for key, item in current.items()}
    change_total = 0.0
    for change in payload.position_changes:
        matches = [key for key in proposed if key[0] == change.security_id and (change.currency is None or key[1] == change.currency)]
        if not matches:
            raise ValueError(f"Security {change.security_id} is not in the current portfolio.")
        if len(matches) > 1:
            raise ValueError(f"Security {change.security_id} is held in multiple currencies; select a currency.")
        key = matches[0]
        next_value = proposed[key]["value"] + change.value_change
        if next_value < -1e-6:
            raise ValueError(f"Change would make {proposed[key]['name']} negative.")
        proposed[key]["value"] = max(0, next_value)
        change_total += change.value_change
    cash_delta = payload.contribution - payload.withdrawal + payload.cash_reserve_change - change_total
    cash_items = [item for item in proposed.values() if item["type"].lower() == "cash"]
    if cash_items:
        if cash_delta < 0 and sum(max(0, item["value"]) for item in cash_items) + cash_delta < -1e-6:
            raise ValueError("Scenario requires more cash than the portfolio has available.")
        if cash_delta < 0:
            remaining = -cash_delta
            for item in sorted(cash_items, key=lambda row: row["value"], reverse=True):
                used = min(max(0, item["value"]), remaining)
                item["value"] -= used
                remaining -= used
                if remaining <= 1e-9:
                    break
        elif cash_delta > 0:
            preferred = next((item for item in cash_items if item["currency"] == display), cash_items[0])
            preferred["value"] += cash_delta
    elif cash_delta:
        if cash_delta < 0:
            raise ValueError("Scenario requires cash, but no cash holding is available.")
        proposed[(0, display)] = {"id": 0, "name": "Scenario cash", "type": "Cash", "category": "Cash", "sector": "Unclassified", "country": "Unresolved", "currency": display, "value": cash_delta}
    realized_gain, estimated_tax = _sale_tax_estimate(conn, payload)
    goals = _scenario_goals(conn, payload.goal_allocation_changes)
    warnings = [
        "Scenario results are hypothetical and do not modify stored positions.",
        "Security changes are modeled as value changes with offsetting cash; execution prices, fees, and lot selection are not known.",
        "Tax estimates use proportional unrealized gains and configured rates; they are informational, not tax advice.",
    ]
    proposed_metrics = _metrics(conn, proposed)
    if sum(goal.proposed_allocated for goal in goals) > proposed_metrics.portfolio_value:
        warnings.append("Proposed goal allocations exceed the proposed portfolio value.")
    return ScenarioAnalysis(
        display_currency=display, current=_metrics(conn, current), proposed=proposed_metrics,
        estimated_realized_gain=realized_gain, estimated_tax=estimated_tax, goals=goals,
        warnings=warnings,
    )


def _sale_tax_estimate(conn, payload):
    assumptions = get_assumptions(conn)
    positions = list_positions(conn)
    by_security = {}
    for position in positions:
        by_security.setdefault(position.security_id, []).append(position)
    gain_total = tax_total = 0.0
    tax_known = True
    for change in payload.position_changes:
        if change.value_change >= 0:
            continue
        lots = [position for position in by_security.get(change.security_id, []) if change.currency is None or position.currency == change.currency]
        security_value = sum(position.total_fmv_display or 0 for position in lots)
        sale_ratio = min(1, -change.value_change / security_value) if security_value else 0
        for position in lots:
            gain = (position.unrealized_gain_loss or 0) * sale_ratio
            gain_total += gain
            try:
                acquired = datetime.strptime(position.acquisition_date or "", "%Y-%m-%d").date()
            except ValueError:
                acquired = None
            if acquired is None:
                tax_known = False
                continue
            long_term = (date.today() - acquired).days >= (assumptions.long_term_holding_days or 365)
            rate = assumptions.long_term_tax_rate if long_term else assumptions.short_term_tax_rate
            if rate is None:
                tax_known = False
            else:
                tax_total += gain * rate
    return gain_total, tax_total if tax_known else None


def _projection_ready(assumptions) -> bool:
    return assumptions.expected_annual_return is not None and assumptions.annual_volatility is not None and assumptions.inflation_rate is not None and assumptions.monthly_household_contribution is not None


def _probability(allocated, goal, assumptions):
    if not _projection_ready(assumptions):
        return None
    months = _months_until(goal.target_month)
    target = goal.target_amount_display * (1 + assumptions.inflation_rate) ** (months / 12)
    return _goal_probability(allocated, goal.monthly_contribution_display, target, months, assumptions)


def _scenario_goals(conn, changes, stress_factor=1.0, stress=False):
    summary, assumptions = list_goals_summary(conn), get_assumptions(conn)
    results = []
    for goal in summary.goals:
        current = goal.allocated_amount_display
        proposed = max(0, current * stress_factor if stress else current + changes.get(goal.id, 0))
        results.append(ScenarioGoalResult(
            goal_id=goal.id, name=goal.name, current_allocated=current, proposed_allocated=proposed,
            current_probability=goal.probability_of_reaching, proposed_probability=_probability(proposed, goal, assumptions),
        ))
    return results


_PRESETS = {
    "market_crash": {"market": -30, "note": "Broad market crash: -30% to non-cash holdings."},
    "2008_style": {"types": {"Stock": -37, "ETF": -30, "Mutual Fund": -30, "Bond": 5, "Bond Fund": 5}, "note": "Historical-style 2008 proxy; not a replay of actual security returns."},
    "2020_style": {"types": {"Stock": -20, "ETF": -18, "Mutual Fund": -18, "Bond": 2, "Bond Fund": 2}, "note": "Historical-style 2020 shock proxy; recovery timing is not modeled."},
    "rate_shock": {"rate_bps": 200, "types": {"Stock": -5, "ETF": -5}, "note": "+200 bp rate shock with duration proxies for fixed income."},
}


def run_stress_test(conn: sqlite3.Connection, request: StressTestRequest) -> StressTestResult:
    if request.preset and request.preset not in _PRESETS:
        raise ValueError("Unknown stress-test preset.")
    for mapping in (request.currency_shocks, request.category_shocks, request.sector_shocks, request.security_shocks):
        if any(value < -100 or value > 100 for value in mapping.values()):
            raise ValueError("Custom shocks must be between -100% and 100%.")
    preset = _PRESETS.get(request.preset or "", {})
    holdings = _holdings(conn)
    base_currency = get_setting(conn, "decision_coach_base_currency") or get_display_currency(conn)
    if request.currency_shocks.get(base_currency, 0):
        raise ValueError(f"{base_currency} is the base currency; shock other currencies relative to it.")
    contributors = []
    current_total = stressed_total = stressed_cash = 0.0
    for item in holdings.values():
        current = item["value"]
        current_total += current
        currency_shock = request.currency_shocks.get(item["currency"], 0) if item["currency"] != base_currency else 0
        if item["type"].lower() == "cash":
            shock = currency_shock
        else:
            shock = request.market_shock_percent + preset.get("market", 0)
            preset_type = "Bond Fund" if _is_fixed_income(item) and item["type"] != "Bond" else "Bond" if _is_fixed_income(item) else item["type"]
            shock += preset.get("types", {}).get(preset_type, 0)
            rate_bps = request.interest_rate_change_bps + preset.get("rate_bps", 0)
            if _is_fixed_income(item):
                shock += -5 * rate_bps / 100
            shock += currency_shock
            shock += request.category_shocks.get(item["category"], 0)
            shock += request.sector_shocks.get(item["sector"], 0)
            shock += request.security_shocks.get(item["id"], 0)
            shock = max(-100, min(100, shock))
        change = current * shock / 100
        stressed_total += current + change
        if item["type"].lower() == "cash":
            stressed_cash += current + change
        contributors.append(StressContributor(security_id=item["id"], security_name=item["name"], currency=item["currency"], current_value=current, shock_percent=shock, projected_change=change))
    contributors.sort(key=lambda item: abs(item.projected_change), reverse=True)
    factor = stressed_total / current_total if current_total else 1
    scenario_goals = _scenario_goals(conn, {}, stress_factor=factor, stress=True)
    goals = [StressGoalResult(goal_id=g.goal_id, name=g.name, current_allocated=g.current_allocated, stressed_allocated=g.proposed_allocated, current_probability=g.current_probability, stressed_probability=g.proposed_probability) for g in scenario_goals]
    expenses = get_assumptions(conn).monthly_expenses
    assumptions = ["Shocks are instantaneous and additive, capped between -100% and +100%.", "Cash is not shocked.", "Allocation-category shocks can be used as sector proxies only when classifications represent sectors; otherwise use security-level shocks.", "Goal allocations are stressed proportionally because holdings are not yet linked to individual goals."]
    if preset.get("note"):
        assumptions.insert(0, preset["note"])
    loss = stressed_total - current_total
    return StressTestResult(display_currency=get_display_currency(conn), preset=request.preset, current_value=current_total, stressed_value=stressed_total,
        projected_loss=loss, projected_loss_percent=loss/current_total*100 if current_total else 0,
        cash_runway_months=max(0, stressed_cash)/expenses if expenses else None, contributors=contributors, goals=goals, assumptions=assumptions)


def _is_fixed_income(item) -> bool:
    return item["type"] in {"Bond", "Bond Fund"} or "bond" in item["category"].lower() or "fixed income" in item["category"].lower()
