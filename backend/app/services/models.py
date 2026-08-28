from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class AuthStatus(BaseModel):
    configured: bool
    unlocked: bool


class SetupRequest(BaseModel):
    passphrase: str = Field(min_length=8)


class UnlockRequest(BaseModel):
    passphrase: str = Field(min_length=1)


class ChangePassphraseRequest(BaseModel):
    new_passphrase: str = Field(min_length=8)


class Broker(BaseModel):
    id: int
    name: str
    default_currency: str = "USD"
    notes: Optional[str] = None
    locked_fields: list[str] = Field(default_factory=list)
    configuration_version: int = 1
    header_signature: list[str] = Field(default_factory=list)
    mappings: dict[str, str] = Field(default_factory=dict)


class BrokerDraft(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    default_currency: str = "USD"
    notes: Optional[str] = None
    locked_fields: list[str] = Field(default_factory=list)
    header_signature: list[str] = Field(default_factory=list)
    mappings: dict[str, str] = Field(default_factory=dict)


class BrokerConfigPreviewRequest(BaseModel):
    draft: BrokerDraft
    csv_text: str
    statement_currency: Optional[str] = None


class BrokerSaveRequest(BaseModel):
    draft: BrokerDraft
    sample_csv: Optional[str] = None
    statement_currency: Optional[str] = None


class BrokerConfigPreview(BaseModel):
    header_signature: list[str]
    detected_headers: list[str]
    mappings: dict[str, str]
    rows: list["PreviewRow"]
    invalid_rows: list["InvalidRow"] = Field(default_factory=list)
    errors: list[str]
    valid: bool


class ImportPreviewRequest(BaseModel):
    broker_id: int
    filename: Optional[str] = None
    csv_text: str
    statement_date: Optional[str] = None
    statement_currency: Optional[str] = None
    locked_fields: Optional[list[str]] = None
    expected_configuration_version: Optional[int] = None
    row_overrides: dict[int, dict[str, Optional[str]]] = Field(default_factory=dict)
    ignored_row_numbers: list[int] = Field(default_factory=list)


class ImportCommitRequest(ImportPreviewRequest):
    pass


class PreviewRow(BaseModel):
    row_number: int
    account_number: Optional[str] = None
    security_name: str
    symbol: Optional[str] = None
    security_type: str
    allocation_category: str = "Unclassified"
    sector: str = "Unclassified"
    acquisition_date: Optional[str] = None
    lot_number: Optional[str] = None
    units: float
    per_unit_cost_basis: Optional[float] = None
    total_cost_basis: Optional[float] = None
    per_unit_fmv: Optional[float] = None
    total_fmv: Optional[float] = None
    currency: str = "USD"
    exchange: str = "Unresolved"
    investment_country: str = "Unresolved"
    location_status: str = "unresolved"


class InvalidRow(BaseModel):
    row_number: int
    raw_values: dict[str, Optional[str]] = Field(default_factory=dict)
    field_errors: dict[str, list[str]] = Field(default_factory=dict)
    editable_values: dict[str, Optional[str]] = Field(default_factory=dict)
    csv_record: str = ""


class ImportPreview(BaseModel):
    broker_id: int
    broker_name: str
    configuration_version: int
    statement_date: str
    detected_columns: list[str]
    suggested_mapping: dict[str, str]
    rows: list[PreviewRow]
    invalid_rows: list[InvalidRow] = Field(default_factory=list)
    ignored_rows: list[InvalidRow] = Field(default_factory=list)
    errors: list[str]
    duplicate: bool
    fingerprint: str
    locked_fields: list[str] = Field(default_factory=list)
    new_rows: list[PreviewRow] = Field(default_factory=list)
    modified_rows: list["ImportReconciliationRow"] = Field(default_factory=list)
    deleted_rows: list["ImportReconciliationRow"] = Field(default_factory=list)


class ImportReconciliationRow(BaseModel):
    row_number: Optional[int] = None
    current_values: dict[str, object] = Field(default_factory=dict)
    proposed_values: dict[str, object] = Field(default_factory=dict)
    changed_fields: list[str] = Field(default_factory=list)


class ImportResult(BaseModel):
    import_id: int
    imported_rows: int
    duplicate: bool
    added_rows: int = 0
    modified_rows: int = 0
    deleted_rows: int = 0


class Position(BaseModel):
    id: int
    security_id: int
    broker_name: str
    account_mask: str
    account_number: Optional[str] = None
    security_name: str
    symbol: Optional[str] = None
    security_type: str
    allocation_category: str
    sector: str
    exchange: str
    investment_country: str
    snapshot_date: str
    acquisition_date: Optional[str] = None
    lot_number: Optional[str] = None
    units: float
    per_unit_cost_basis: Optional[float] = None
    total_cost_basis: Optional[float] = None
    per_unit_fmv: Optional[float] = None
    total_fmv: Optional[float] = None
    per_unit_cost_basis_display: Optional[float] = None
    total_cost_basis_display: Optional[float] = None
    per_unit_fmv_display: Optional[float] = None
    total_fmv_display: Optional[float] = None
    unrealized_gain_loss: Optional[float] = None
    unrealized_gain_loss_native: Optional[float] = None
    unrealized_gain_loss_pct: Optional[float] = None
    currency: str
    display_currency: str
    last_price_update: Optional[str] = None


class PositionUpdate(BaseModel):
    account_number: Optional[str] = None
    security_name: str
    symbol: Optional[str] = None
    security_type: str
    allocation_category: str
    sector: str = "Unclassified"
    exchange: str = "Unresolved"
    investment_country: str = "Unresolved"
    snapshot_date: str
    acquisition_date: Optional[str] = None
    lot_number: Optional[str] = None
    units: float = Field(ge=0)
    per_unit_cost_basis: Optional[float] = None
    total_cost_basis: Optional[float] = None
    per_unit_fmv: Optional[float] = None
    total_fmv: Optional[float] = None
    currency: str = "USD"


class PositionCreate(PositionUpdate):
    broker_name: str
    account_number: Optional[str] = None


class PositionBulkUpdateItem(BaseModel):
    position_id: int
    payload: PositionUpdate


class PriceRefreshResult(BaseModel):
    security_id: int
    symbol: Optional[str]
    refreshed: bool
    price: Optional[float] = None
    message: str


class CleanDatabaseResult(BaseModel):
    cleaned: bool
    message: str
    reset: bool = False


class ClassificationRefreshResult(BaseModel):
    security_id: int
    symbol: Optional[str]
    refreshed: bool
    allocation_category: str
    message: str


class CurrencySetting(BaseModel):
    display_currency: str
    supported_currencies: list[str]


class FxRate(BaseModel):
    from_currency: str
    to_currency: str
    rate: float
    source: str
    updated_at: str


class FxRateUpdate(BaseModel):
    from_currency: str
    to_currency: str
    rate: float


class StaticAccountBase(BaseModel):
    category: str
    entity_name: str
    account_type: str
    account_holder: str
    account_number: Optional[str] = None
    currency: str = "USD"
    amount: float
    notes: Optional[str] = None


class StaticAccountCreate(StaticAccountBase):
    pass


class StaticAccountUpdate(StaticAccountBase):
    pass


class StaticAccount(BaseModel):
    id: int
    category: str
    entity_name: str
    account_type: str
    account_holder: str
    account_mask: Optional[str] = None
    currency: str
    amount: float
    amount_display: float
    display_currency: str
    notes: Optional[str] = None
    created_at: str
    updated_at: str


class RealEstateAssetBase(BaseModel):
    property_info: str
    entity_name: Optional[str] = None
    purchase_date: Optional[str] = None
    purchase_value: float
    current_value: float
    currency: str = "USD"
    notes: Optional[str] = None


class RealEstateAssetCreate(RealEstateAssetBase):
    pass


class RealEstateAssetUpdate(RealEstateAssetBase):
    pass


class RealEstateAsset(BaseModel):
    id: int
    property_info: str
    entity_name: Optional[str] = None
    purchase_date: Optional[str] = None
    purchase_value: float
    current_value: float
    purchase_value_display: float
    current_value_display: float
    currency: str
    display_currency: str
    notes: Optional[str] = None
    created_at: str
    updated_at: str


class AnalyticsPoint(BaseModel):
    label: str
    value: float


class TimeSeriesPoint(BaseModel):
    date: str
    value: float


class CountryReturn(BaseModel):
    country: str
    current_market_value: float
    cost_basis: float
    unrealized_return: float
    unrealized_return_percent: Optional[float] = None
    earliest_snapshot_value: float
    latest_snapshot_value: float
    snapshot_value_change_percent: Optional[float] = None


class DashboardAnalytics(BaseModel):
    display_currency: str
    brokerage_value: float
    static_accounts_value: float
    real_estate_value: float
    private_equity_value: float = 0
    total_net_worth: float
    total_value: float
    total_cost_basis: float
    unrealized_gain_loss: float
    unrealized_gain_loss_pct: Optional[float]
    portfolio_growth: list[TimeSeriesPoint]
    asset_allocation: list[AnalyticsPoint]
    broker_allocation: list[AnalyticsPoint]
    country_allocation: list[AnalyticsPoint]
    exchange_allocation: list[AnalyticsPoint]
    cash_vs_invested: list[AnalyticsPoint]
    net_worth_allocation: list[AnalyticsPoint]
    country_returns: list[CountryReturn] = Field(default_factory=list)
    country_snapshot_disclosure: str = "Snapshot value change is a holdings-value proxy, not investment performance; imports do not model deposits, withdrawals, dividends, or trades."


class FinancialAssumptions(BaseModel):
    expected_annual_return: Optional[float] = Field(default=None, ge=-1, le=10)
    annual_volatility: Optional[float] = Field(default=None, ge=0, le=10)
    inflation_rate: Optional[float] = Field(default=None, ge=-1, le=10)
    monthly_household_contribution: Optional[float] = Field(default=None, ge=0)
    monthly_expenses: Optional[float] = Field(default=None, ge=0)
    current_age: Optional[int] = Field(default=None, ge=0, le=120)
    end_age: int = Field(default=85, ge=1, le=130)
    short_term_tax_rate: Optional[float] = Field(default=None, ge=0, le=1)
    long_term_tax_rate: Optional[float] = Field(default=None, ge=0, le=1)
    long_term_holding_days: Optional[int] = Field(default=365, ge=1, le=36500)


class ScheduledExpenseInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    expense_type: str
    amount: float = Field(ge=0)
    currency: str
    expense_date: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class ScheduledExpense(ScheduledExpenseInput):
    id: int


class AllocationTarget(BaseModel):
    id: Optional[int] = None
    dimension: str
    label: str
    target_percent: float = Field(ge=0, le=100)
    tolerance_percent: float = Field(default=10, ge=0, le=100)


class AllocationTargetSet(BaseModel):
    dimension: str
    targets: list[AllocationTarget]


class AllocationCategoryCreate(BaseModel):
    name: str


class GoalBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    target_amount: float = Field(ge=0)
    target_currency: str = "USD"
    target_month: str
    allocated_amount: float = Field(default=0, ge=0)
    allocated_currency: str = "USD"
    monthly_contribution: float = Field(default=0, ge=0)
    contribution_currency: str = "USD"
    priority: Optional[int] = Field(default=None, ge=1, le=100)


class GoalCreate(GoalBase):
    pass


class GoalUpdate(GoalBase):
    pass


class Goal(GoalBase):
    id: int
    target_amount_display: float
    allocated_amount_display: float
    monthly_contribution_display: float
    display_currency: str
    projected_value: Optional[float] = None
    projected_shortfall_surplus: Optional[float] = None
    required_monthly_contribution: Optional[float] = None
    probability_of_reaching: Optional[float] = None
    created_at: str
    updated_at: str


class GoalsSummary(BaseModel):
    display_currency: str
    investable_financial_assets: float
    total_allocated: float
    unallocated_remainder: float
    over_allocated: bool
    goals: list[Goal]


class InsightAllocationRow(BaseModel):
    label: str
    actual_amount: float
    actual_percent: float
    target_percent: float
    tolerance_percent: float
    minimum_percent: float
    maximum_percent: float
    drift_percent: float
    rebalance_amount: float
    compliant: bool
    outside_range_percent: float = 0
    policy_gap_amount: float = 0


class AllocationPolicySummary(BaseModel):
    configured_targets: int = 0
    compliant_targets: int = 0
    breached_targets: int = 0
    unconfigured_dimensions: list[str] = Field(default_factory=list)
    largest_breach: Optional[InsightAllocationRow] = None


class InsightTaxLot(BaseModel):
    position_id: int
    security_name: str
    acquisition_date: Optional[str]
    holding_days: Optional[int]
    classification: str
    gain: Optional[float]
    indicative_tax: Optional[float]


class InsightFinding(BaseModel):
    id: str
    category: str
    severity: str
    title: str
    impact_amount: Optional[float] = None
    impact_percent: Optional[float] = None
    impact_label: Optional[str] = None
    impact_percent_label: Optional[str] = None
    confidence: str
    evidence: list[str]
    explanation: str
    suggested_actions: list[str]
    navigation: Optional[dict[str, object]] = None


class SnapshotHoldingChange(BaseModel):
    security_id: int
    security_name: str
    symbol: Optional[str] = None
    change_type: str
    previous_units: float
    latest_units: float
    units_change: float
    previous_value: float
    latest_value: float
    value_change: float
    value_change_percent: Optional[float] = None
    activity_label: str


class SnapshotAllocationShift(BaseModel):
    label: str
    previous_percent: float
    latest_percent: float
    change_percent: float


class SnapshotComparison(BaseModel):
    available: bool
    latest_date: Optional[str] = None
    previous_date: Optional[str] = None
    latest_value: float = 0
    previous_value: float = 0
    total_value_change: float = 0
    total_value_change_percent: Optional[float] = None
    cash_change: float = 0
    new_holdings: list[SnapshotHoldingChange] = Field(default_factory=list)
    exited_holdings: list[SnapshotHoldingChange] = Field(default_factory=list)
    position_changes: list[SnapshotHoldingChange] = Field(default_factory=list)
    coverage_changes: list[SnapshotHoldingChange] = Field(default_factory=list)
    unusual_valuation_changes: list[SnapshotHoldingChange] = Field(default_factory=list)
    allocation_shifts: list[SnapshotAllocationShift] = Field(default_factory=list)
    disclosure: str


class Insights(BaseModel):
    display_currency: str
    projection_setup_required: bool
    concentration: list[AnalyticsPoint]
    top_5_share: float
    top_10_share: float
    currency_exposure: list[AnalyticsPoint]
    country_exposure: list[AnalyticsPoint]
    exchange_exposure: list[AnalyticsPoint]
    allocation_drift: dict[str, list[InsightAllocationRow]]
    allocation_policy: AllocationPolicySummary
    liquidity: list[AnalyticsPoint]
    cash_runway_months: Optional[float]
    tax_lots: list[InsightTaxLot]
    value_history: list[TimeSeriesPoint]
    rolling_growth: dict[str, Optional[float]]
    drawdown: list[TimeSeriesPoint]
    holding_value_change: list[AnalyticsPoint]
    forecast: Optional[dict]
    findings: list[InsightFinding]
    snapshot_comparison: SnapshotComparison


class ScenarioPositionChange(BaseModel):
    security_id: int
    currency: Optional[str] = None
    value_change: float
    note: Optional[str] = None


class ScenarioInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    contribution: float = Field(default=0, ge=0)
    withdrawal: float = Field(default=0, ge=0)
    cash_reserve_change: float = 0
    position_changes: list[ScenarioPositionChange] = Field(default_factory=list)
    goal_allocation_changes: dict[int, float] = Field(default_factory=dict)


class SavedScenario(ScenarioInput):
    id: int
    created_at: str
    updated_at: str


class ScenarioMetrics(BaseModel):
    portfolio_value: float
    cash_value: float
    cash_runway_months: Optional[float] = None
    largest_holding: Optional[str] = None
    largest_holding_percent: float = 0
    total_absolute_drift_percent: Optional[float] = None


class ScenarioGoalResult(BaseModel):
    goal_id: int
    name: str
    current_allocated: float
    proposed_allocated: float
    current_probability: Optional[float] = None
    proposed_probability: Optional[float] = None


class ScenarioAnalysis(BaseModel):
    display_currency: str
    current: ScenarioMetrics
    proposed: ScenarioMetrics
    estimated_realized_gain: float
    estimated_tax: Optional[float] = None
    goals: list[ScenarioGoalResult]
    warnings: list[str]


class StressTestRequest(BaseModel):
    preset: Optional[str] = None
    market_shock_percent: float = Field(default=0, ge=-100, le=100)
    interest_rate_change_bps: float = Field(default=0, ge=-5000, le=5000)
    currency_shocks: dict[str, float] = Field(default_factory=dict)
    category_shocks: dict[str, float] = Field(default_factory=dict)
    sector_shocks: dict[str, float] = Field(default_factory=dict)
    security_shocks: dict[int, float] = Field(default_factory=dict)


class StressContributor(BaseModel):
    security_id: int
    security_name: str
    currency: str
    current_value: float
    shock_percent: float
    projected_change: float


class StressGoalResult(BaseModel):
    goal_id: int
    name: str
    current_allocated: float
    stressed_allocated: float
    current_probability: Optional[float] = None
    stressed_probability: Optional[float] = None


class StressTestResult(BaseModel):
    display_currency: str
    preset: Optional[str] = None
    current_value: float
    stressed_value: float
    projected_loss: float
    projected_loss_percent: float
    cash_runway_months: Optional[float] = None
    contributors: list[StressContributor]
    goals: list[StressGoalResult]
    assumptions: list[str]


class FundConstituentInput(BaseModel):
    constituent_key: str = Field(min_length=1, max_length=200)
    identifier: Optional[str] = Field(default=None, max_length=100)
    linked_security_id: Optional[int] = None
    symbol: Optional[str] = None
    name: str = Field(min_length=1, max_length=300)
    weight_percent: float = Field(gt=0, le=100)
    sector: str = "Unclassified"
    country: str = "Unresolved"
    currency: str = "Unresolved"
    asset_category: str = "Unclassified"


class FundCompositionInput(BaseModel):
    source: str = "manual"
    source_url: Optional[str] = None
    holdings_scope: str = "full"
    as_of_date: Optional[str] = None
    constituents: list[FundConstituentInput] = Field(default_factory=list)


class FundComposition(FundCompositionInput):
    security_id: int
    security_name: str
    reviewed_at: str
    coverage_percent: float
    stale: bool


class PublicMetadataPreview(BaseModel):
    security_id: int
    provider: str
    fetched_at: str
    as_of_date: Optional[str] = None
    composition: Optional[FundCompositionInput] = None
    expense_ratio_percent: Optional[float] = None
    facts: dict = Field(default_factory=dict)
    source_url: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    holdings_count: int = 0
    holdings_scope: str = "top_10"
    message: str


class FundHtmlSyncRequest(BaseModel):
    source: str = "yahoo_html"
    url: Optional[str] = None


class PublicMetadataAcceptance(BaseModel):
    metadata: "FundMetadata"
    composition: Optional[FundComposition] = None


class FundMetadata(BaseModel):
    security_id: int
    provider: str
    category: Optional[str] = None
    thesis: Optional[str] = None
    fund_family: Optional[str] = None
    inception_date: Optional[str] = None
    assets_under_management: Optional[float] = None
    yield_percent: Optional[float] = None
    turnover_percent: Optional[float] = None
    beta: Optional[float] = None
    expense_ratio_percent: Optional[float] = None
    return_3y_percent: Optional[float] = None
    return_5y_percent: Optional[float] = None
    return_10y_percent: Optional[float] = None
    return_since_inception_percent: Optional[float] = None
    as_of_date: Optional[str] = None
    fetched_at: Optional[str] = None
    unavailable_fields: list[str] = Field(default_factory=list)
    reviewed_at: str


class PeerCandidate(BaseModel):
    symbol: str
    name: str
    category: Optional[str] = None
    thesis: Optional[str] = None
    expense_ratio_percent: Optional[float] = None
    return_3y_percent: Optional[float] = None
    return_5y_percent: Optional[float] = None
    return_10y_percent: Optional[float] = None
    matched_horizon: Optional[str] = None
    matched_return_percent: Optional[float] = None
    rank: Optional[int] = None


class PeerResearch(BaseModel):
    security_id: int
    retrieved_at: str
    provider: str
    candidates: list[PeerCandidate] = Field(default_factory=list)
    note: str
    warnings: list[str] = Field(default_factory=list)


class PrivateEquityAssetBase(BaseModel):
    company_name: str = Field(min_length=1, max_length=300)
    stage: str = Field(min_length=1, max_length=80)
    share_class: str
    quantity: float = Field(ge=0)
    purchase_price_per_unit: float = Field(ge=0)
    investment_date: Optional[str] = None
    last_valuation_per_unit: float = Field(ge=0)
    valuation_date: Optional[str] = None
    ownership_percent: Optional[float] = Field(default=None, ge=0, le=100)
    valuation_source: Optional[str] = None
    currency: str = "USD"
    notes: Optional[str] = None


class PrivateEquityAssetCreate(PrivateEquityAssetBase):
    pass


class PrivateEquityAssetUpdate(PrivateEquityAssetBase):
    pass


class PrivateEquityAsset(PrivateEquityAssetBase):
    id: int
    purchase_value: float
    current_value: float
    unrealized_gain_loss: float
    purchase_value_display: float
    current_value_display: float
    unrealized_gain_loss_display: float
    display_currency: str
    created_at: str
    updated_at: str


class ExposureRow(BaseModel):
    key: str
    label: str
    value: float
    percent: float
    confidence: str
    sources: list[str] = Field(default_factory=list)


class FundOverlap(BaseModel):
    left_security_id: int
    left_name: str
    right_security_id: int
    right_name: str
    overlap_percent: float


class ExposureAnalysis(BaseModel):
    display_currency: str
    portfolio_value: float
    composition_coverage_percent: float
    company: list[ExposureRow]
    sector: list[ExposureRow]
    country: list[ExposureRow]
    currency: list[ExposureRow]
    asset_category: list[ExposureRow]
    overlaps: list[FundOverlap]
    compositions: list[FundComposition]
    policy_drift: dict[str, list[InsightAllocationRow]] = Field(default_factory=dict)
    warnings: list[str]


class MarketObservation(BaseModel):
    date: str
    adjusted_close: float = Field(gt=0)


class MarketHistoryInput(BaseModel):
    symbol: str = Field(min_length=1)
    currency: str
    observations: list[MarketObservation] = Field(min_length=2)


class ManualMarketSeriesInput(MarketHistoryInput):
    series_key: str = Field(min_length=3, max_length=300)
    series_type: str


class HistoryRefreshResult(BaseModel):
    series_key: str
    symbol: str
    refreshed: bool
    observation_count: int = 0
    message: str


class RiskSettings(BaseModel):
    benchmark_symbol: Optional[str] = None
    benchmark_currency: Optional[str] = None
    minimum_observations: int = Field(default=60, ge=20, le=1000)


class RiskHolding(BaseModel):
    security_id: int
    name: str
    symbol: Optional[str] = None
    portfolio_weight_percent: float
    observation_count: int
    annualized_volatility_percent: Optional[float] = None
    beta: Optional[float] = None
    risk_contribution_percent: Optional[float] = None
    max_drawdown_percent: Optional[float] = None
    confidence: str
    warning: Optional[str] = None


class CorrelationRow(BaseModel):
    left_security_id: int
    right_security_id: int
    correlation: float
    observation_count: int


class RiskAnalysis(BaseModel):
    display_currency: str
    benchmark_symbol: str
    history_years: int = 5
    coverage_percent: float
    covered_portfolio_volatility_percent: Optional[float] = None
    covered_portfolio_beta: Optional[float] = None
    covered_portfolio_max_drawdown_percent: Optional[float] = None
    holdings: list[RiskHolding]
    correlations: list[CorrelationRow]
    warnings: list[str]


class SecurityFeeInput(BaseModel):
    expense_ratio_percent: Optional[float] = Field(default=None, ge=0, le=100)
    source: str = "manual"
    as_of_date: Optional[str] = None


class SecurityFee(SecurityFeeInput):
    security_id: int
    security_name: str
    reviewed_at: str
    stale: bool


class PortfolioFeeInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    fee_type: str
    annual_percent: Optional[float] = Field(default=None, ge=0, le=100)
    annual_amount: Optional[float] = Field(default=None, ge=0)
    currency: str = "USD"
    enabled: bool = True


class PortfolioFee(PortfolioFeeInput):
    id: int


class FeeSettings(BaseModel):
    cash_reserve_months: float = Field(default=6, ge=0, le=120)


class FeeHoldingCost(BaseModel):
    security_id: int
    name: str
    value: float
    expense_ratio_percent: Optional[float] = None
    annual_cost: Optional[float] = None
    confidence: str


class FeeProjection(BaseModel):
    years: int
    cumulative_nominal_fees: float
    ending_value_without_fees: float
    ending_value_after_fees: float
    opportunity_cost: float


class FeeAnalysis(BaseModel):
    display_currency: str
    portfolio_value: float
    annual_fund_expenses: float
    annual_advisory_fees: float
    annual_fixed_fees: float
    total_annual_fees: float
    annual_fee_percent: float
    cash_value: float
    reserve_target: Optional[float] = None
    potential_idle_cash: Optional[float] = None
    potential_cash_drag: Optional[float] = None
    holdings: list[FeeHoldingCost]
    portfolio_fees: list[PortfolioFee]
    projections: list[FeeProjection]
    warnings: list[str]
