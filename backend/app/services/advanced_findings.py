# SPDX-FileCopyrightText: Copyright (C) Arun Sriraman
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import sqlite3

from backend.app.services.exposure_service import exposure_analysis
from backend.app.services.fee_service import fee_analysis
from backend.app.services.models import InsightFinding
from backend.app.services.risk_service import risk_analysis


def advanced_findings(conn: sqlite3.Connection) -> list[InsightFinding]:
    findings: list[InsightFinding] = []
    exposure = exposure_analysis(conn)
    for row in exposure.company:
        if row.percent >= 20 and row.label.lower() != "cash" and not row.key.startswith("unmapped:"):
            findings.append(InsightFinding(
                id=f"look-through-{row.key}", category="look_through", severity="high" if row.percent >= 35 else "medium",
                title=f"{row.label} is {row.percent:.1f}% after look-through",
                impact_amount=row.value, impact_percent=row.percent, impact_label="Effective exposure",
                impact_percent_label="Portfolio share", confidence=row.confidence,
                evidence=[f"Exposure paths: {', '.join(row.sources)}", f"Effective value: {row.value:,.2f} {exposure.display_currency}"],
                explanation="Underlying company exposure can be materially larger than position-level allocation shows.",
                suggested_actions=["Review whether this effective concentration is intentional.", "Verify fund metadata before acting on the estimate."],
            ))
    if exposure.overlaps and exposure.overlaps[0].overlap_percent >= 20:
        overlap = exposure.overlaps[0]
        findings.append(InsightFinding(
            id=f"fund-overlap-{overlap.left_security_id}-{overlap.right_security_id}", category="look_through", severity="medium",
            title=f"{overlap.left_name} and {overlap.right_name} overlap by {overlap.overlap_percent:.1f}%",
            impact_percent=overlap.overlap_percent, impact_percent_label="Shared constituent weight", confidence="medium",
            evidence=["Overlap is the sum of the smaller shared constituent weights.", "Partial public compositions can understate overlap."],
            explanation="Funds with similar constituents may provide less diversification than their number suggests.",
            suggested_actions=["Compare the funds' roles, fees, and uncovered composition weight."],
        ))
    risk = risk_analysis(conn)
    covered = [item for item in risk.holdings if item.risk_contribution_percent is not None]
    if covered:
        largest = max(covered, key=lambda item: item.risk_contribution_percent or 0)
        if (largest.risk_contribution_percent or 0) >= 40:
            findings.append(InsightFinding(
                id=f"risk-contribution-{largest.security_id}", category="risk", severity="high" if (largest.risk_contribution_percent or 0) >= 60 else "medium",
                title=f"{largest.name} contributes {largest.risk_contribution_percent:.1f}% of covered portfolio risk",
                impact_percent=largest.risk_contribution_percent, impact_percent_label="Component risk share", confidence=largest.confidence,
                evidence=[f"Position weight: {largest.portfolio_weight_percent:.1f}%", f"Historical observations: {largest.observation_count}", f"History coverage: {risk.coverage_percent:.1f}%"],
                explanation="A holding can contribute more or less risk than its portfolio weight because volatility and correlations differ.",
                suggested_actions=["Review the holding's intended risk role and the analysis coverage before changing the portfolio."],
            ))
    if risk.coverage_percent < 80:
        findings.append(InsightFinding(
            id="risk-history-coverage", category="data_quality", severity="medium",
            title=f"Risk history covers only {risk.coverage_percent:.1f}% of non-cash assets",
            impact_percent=risk.coverage_percent, impact_percent_label="Covered market value", confidence="high",
            evidence=["At least 60 aligned daily returns are required per holding."],
            explanation="Incomplete history prevents a complete portfolio risk estimate.",
            suggested_actions=["Refresh historical data or import adjusted prices for unsupported holdings."],
        ))
    fees = fee_analysis(conn)
    if fees.annual_fee_percent >= 1:
        findings.append(InsightFinding(
            id="portfolio-fee-drag", category="fees", severity="high" if fees.annual_fee_percent >= 2 else "medium",
            title=f"Estimated annual fees are {fees.annual_fee_percent:.2f}% of the portfolio",
            impact_amount=fees.total_annual_fees, impact_percent=fees.annual_fee_percent,
            impact_label="Estimated annual fees", impact_percent_label="Portfolio share", confidence="medium",
            evidence=[f"Fund expenses: {fees.annual_fund_expenses:,.2f} {fees.display_currency}", f"Advisory and fixed fees: {fees.annual_advisory_fees + fees.annual_fixed_fees:,.2f} {fees.display_currency}"],
            explanation="Recurring costs compound over time and reduce the return retained by the portfolio.",
            suggested_actions=["Verify fee metadata and compare costs with the services or exposures received."],
        ))
    if fees.potential_cash_drag and fees.potential_cash_drag > 0:
        findings.append(InsightFinding(
            id="potential-idle-cash-drag", category="fees", severity="low",
            title="Cash above the configured reserve may create portfolio drag",
            impact_amount=fees.potential_cash_drag, impact_label="One-year estimated opportunity cost", confidence="low",
            evidence=[f"Potential idle cash: {fees.potential_idle_cash:,.2f} {fees.display_currency}", "This estimate uses the configured expected return."],
            explanation="The estimate is hypothetical and does not establish that the cash is unnecessary.",
            suggested_actions=["Confirm the reserve target and near-term spending needs."],
        ))
    return findings
