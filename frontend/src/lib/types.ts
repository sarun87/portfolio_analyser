export type AuthStatus = {
  configured: boolean;
  unlocked: boolean;
};

export type Broker = {
  id: number;
  name: string;
  default_currency?: string;
  notes?: string | null;
  locked_fields?: string[];
  configuration_version?: number;
  header_signature?: string[];
  mappings?: Record<string, string>;
};

export type BrokerDraft = {
  name: string;
  default_currency: string;
  notes?: string | null;
  locked_fields: string[];
  header_signature: string[];
  mappings: Record<string, string>;
};

export type BrokerConfigPreview = {
  header_signature: string[];
  detected_headers: string[];
  mappings: Record<string, string>;
  rows: PreviewRow[];
  invalid_rows: InvalidRow[];
  errors: string[];
  valid: boolean;
};

export type PreviewRow = {
  row_number: number;
  account_number?: string | null;
  security_name: string;
  symbol?: string | null;
  security_type: string;
  allocation_category: string;
  sector: string;
  acquisition_date?: string | null;
  lot_number?: string | null;
  units: number;
  per_unit_cost_basis?: number | null;
  total_cost_basis?: number | null;
  per_unit_fmv?: number | null;
  total_fmv?: number | null;
  currency: string;
  exchange: string;
  investment_country: string;
  location_status: string;
};

export type InvalidRow = { row_number: number; raw_values: Record<string, string | null>; field_errors: Record<string, string[]>; editable_values: Record<string, string | null>; csv_record: string };

export type ImportPreview = {
  broker_id: number;
  broker_name: string;
  configuration_version: number;
  statement_date: string;
  detected_columns: string[];
  suggested_mapping: Record<string, string>;
  rows: PreviewRow[];
  invalid_rows: InvalidRow[];
  ignored_rows: InvalidRow[];
  new_rows: PreviewRow[];
  modified_rows: ImportReconciliationRow[];
  deleted_rows: ImportReconciliationRow[];
  errors: string[];
  duplicate: boolean;
  fingerprint: string;
  locked_fields: string[];
};
export type ImportReconciliationRow = { row_number?: number | null; current_values: Record<string, unknown>; proposed_values: Record<string, unknown>; changed_fields: string[] };

export type PublicHtmlSource = "yahoo_html" | "google_finance_html" | "custom_url";

export type Position = {
  id: number;
  security_id: number;
  broker_name: string;
  account_mask: string;
  account_number?: string | null;
  security_name: string;
  symbol?: string | null;
  security_type: string;
  allocation_category: string;
  sector: string;
  exchange: string;
  investment_country: string;
  snapshot_date: string;
  acquisition_date?: string | null;
  lot_number?: string | null;
  units: number;
  per_unit_cost_basis?: number | null;
  total_cost_basis?: number | null;
  per_unit_fmv?: number | null;
  total_fmv?: number | null;
  per_unit_cost_basis_display?: number | null;
  total_cost_basis_display?: number | null;
  per_unit_fmv_display?: number | null;
  total_fmv_display?: number | null;
  unrealized_gain_loss?: number | null;
  unrealized_gain_loss_native?: number | null;
  unrealized_gain_loss_pct?: number | null;
  currency: string;
  display_currency: string;
  last_price_update?: string | null;
};

export type PositionUpdatePayload = {
  account_number?: string | null;
  security_name: string;
  symbol?: string | null;
  security_type: string;
  allocation_category: string;
  sector: string;
  exchange: string;
  investment_country: string;
  snapshot_date: string;
  acquisition_date?: string | null;
  lot_number?: string | null;
  units: number;
  per_unit_cost_basis?: number | null;
  total_cost_basis?: number | null;
  per_unit_fmv?: number | null;
  total_fmv?: number | null;
  currency: string;
};

export type PositionCreatePayload = PositionUpdatePayload & {
  broker_name: string;
  account_number?: string | null;
};

export type AnalyticsPoint = {
  label: string;
  value: number;
};

export type TimeSeriesPoint = {
  date: string;
  value: number;
};

export type DashboardAnalytics = {
  display_currency: string;
  brokerage_value: number;
  static_accounts_value: number;
  real_estate_value: number;
  total_net_worth: number;
  total_value: number;
  total_cost_basis: number;
  unrealized_gain_loss: number;
  unrealized_gain_loss_pct?: number | null;
  portfolio_growth: TimeSeriesPoint[];
  asset_allocation: AnalyticsPoint[];
  broker_allocation: AnalyticsPoint[];
  country_allocation: AnalyticsPoint[];
  exchange_allocation: AnalyticsPoint[];
  cash_vs_invested: AnalyticsPoint[];
  net_worth_allocation: AnalyticsPoint[];
  country_returns: Array<{ country:string; current_market_value:number; cost_basis:number; unrealized_return:number; unrealized_return_percent?:number|null; earliest_snapshot_value:number; latest_snapshot_value:number; snapshot_value_change_percent?:number|null }>;
  country_snapshot_disclosure?: string;
};

export type PriceRefreshResult = {
  security_id: number;
  symbol?: string | null;
  refreshed: boolean;
  price?: number | null;
  message: string;
};

export type ClassificationRefreshResult = {
  security_id: number;
  symbol?: string | null;
  refreshed: boolean;
  allocation_category: string;
  message: string;
};

export type CurrencySetting = {
  display_currency: string;
  supported_currencies: string[];
};

export type FxRate = {
  from_currency: string;
  to_currency: string;
  rate: number;
  source: string;
  updated_at: string;
};

export type StaticAccount = {
  id: number;
  category: "Bank Account" | "Retirement Account" | "Other";
  entity_name: string;
  account_type: string;
  account_holder: string;
  account_mask?: string | null;
  currency: string;
  amount: number;
  amount_display: number;
  display_currency: string;
  notes?: string | null;
  created_at: string;
  updated_at: string;
};

export type StaticAccountPayload = {
  category: StaticAccount["category"];
  entity_name: string;
  account_type: string;
  account_holder: string;
  account_number?: string | null;
  currency: string;
  amount: number;
  notes?: string | null;
};

export type RealEstateAsset = {
  id: number;
  property_info: string;
  entity_name?: string | null;
  purchase_date?: string | null;
  purchase_value: number;
  current_value: number;
  purchase_value_display: number;
  current_value_display: number;
  currency: string;
  display_currency: string;
  notes?: string | null;
  created_at: string;
  updated_at: string;
};

export type RealEstatePayload = {
  property_info: string;
  entity_name?: string | null;
  purchase_date?: string | null;
  purchase_value: number;
  current_value: number;
  currency: string;
  notes?: string | null;
};

export type PrivateEquityPayload = { company_name:string; stage:string; share_class:"Common"|"Preferred"; quantity:number; purchase_price_per_unit:number; investment_date?:string|null; last_valuation_per_unit:number; valuation_date?:string|null; ownership_percent?:number|null; valuation_source?:string|null; currency:string; notes?:string|null };
export type PrivateEquityAsset = PrivateEquityPayload & { id:number; purchase_value:number; current_value:number; unrealized_gain_loss:number; purchase_value_display:number; current_value_display:number; unrealized_gain_loss_display:number; display_currency:string; created_at:string; updated_at:string };

export type FinancialAssumptions = {
  expected_annual_return?: number | null;
  annual_volatility?: number | null;
  inflation_rate?: number | null;
  monthly_household_contribution?: number | null;
  monthly_expenses?: number | null;
  current_age?: number | null;
  end_age?: number | null;
  short_term_tax_rate?: number | null;
  long_term_tax_rate?: number | null;
  long_term_holding_days?: number | null;
};
export type ScheduledExpenseInput = { name:string; expense_type:"one_time"|"date_range"; amount:number; currency:string; expense_date?:string|null; start_date?:string|null; end_date?:string|null };
export type ScheduledExpense = ScheduledExpenseInput & { id:number };

export type AllocationTarget = { id?: number; dimension: string; label: string; target_percent: number; tolerance_percent: number };

export type Goal = {
  id: number; name: string; description?: string | null; target_amount: number; target_currency: string; target_month: string;
  allocated_amount: number; allocated_currency: string; monthly_contribution: number; contribution_currency: string; priority?: number | null;
  target_amount_display: number; allocated_amount_display: number; monthly_contribution_display: number; display_currency: string;
  projected_value?: number | null; projected_shortfall_surplus?: number | null;
  required_monthly_contribution?: number | null; probability_of_reaching?: number | null;
  created_at: string; updated_at: string;
};
export type GoalPayload = Omit<Goal, "id" | "target_amount_display" | "allocated_amount_display" | "monthly_contribution_display" | "display_currency" | "projected_value" | "projected_shortfall_surplus" | "required_monthly_contribution" | "probability_of_reaching" | "created_at" | "updated_at">;
export type GoalsSummary = { display_currency: string; investable_financial_assets: number; total_allocated: number; unallocated_remainder: number; over_allocated: boolean; goals: Goal[] };
export type InsightFinding = {
  id: string; category: string; severity: "critical" | "high" | "medium" | "low"; title: string;
  impact_amount?: number | null; impact_percent?: number | null; impact_label?: string | null; impact_percent_label?: string | null; confidence: "high" | "medium" | "low";
  evidence: string[]; explanation: string; suggested_actions: string[];
  navigation?: { page?: string; filters?: Record<string, unknown>; section?: string; dimension?: string; label?: string; actions?: Array<{label:string;filters:Record<string,unknown>}> } | null;
};
export type SnapshotHoldingChange = {
  security_id: number; security_name: string; symbol?: string | null; change_type: string;
  previous_units: number; latest_units: number; units_change: number; previous_value: number;
  latest_value: number; value_change: number; value_change_percent?: number | null; activity_label: string;
};
export type SnapshotComparison = {
  available: boolean; latest_date?: string | null; previous_date?: string | null; latest_value: number;
  previous_value: number; total_value_change: number; total_value_change_percent?: number | null; cash_change: number;
  new_holdings: SnapshotHoldingChange[]; exited_holdings: SnapshotHoldingChange[]; position_changes: SnapshotHoldingChange[];
  coverage_changes: SnapshotHoldingChange[];
  unusual_valuation_changes: SnapshotHoldingChange[];
  allocation_shifts: Array<{label:string;previous_percent:number;latest_percent:number;change_percent:number}>;
  disclosure: string;
};
export type Insights = {
  display_currency: string; projection_setup_required: boolean; concentration: AnalyticsPoint[]; top_5_share: number; top_10_share: number;
  currency_exposure: AnalyticsPoint[]; country_exposure: AnalyticsPoint[]; exchange_exposure: AnalyticsPoint[];
  allocation_drift: Record<string, Array<{ label: string; actual_amount: number; actual_percent: number; target_percent: number; tolerance_percent: number; minimum_percent: number; maximum_percent: number; drift_percent: number; rebalance_amount: number; compliant: boolean; outside_range_percent: number; policy_gap_amount: number }>>;
  allocation_policy: { configured_targets:number; compliant_targets:number; breached_targets:number; unconfigured_dimensions:string[]; largest_breach: { label:string; actual_percent:number; minimum_percent:number; maximum_percent:number; outside_range_percent:number } | null };
  liquidity: AnalyticsPoint[]; cash_runway_months?: number | null; tax_lots: Array<{ position_id: number; security_name: string; acquisition_date?: string | null; holding_days?: number | null; classification: string; gain?: number | null; indicative_tax?: number | null }>;
  value_history: TimeSeriesPoint[]; rolling_growth: Record<string, number | null>; drawdown: TimeSeriesPoint[]; holding_value_change: AnalyticsPoint[]; forecast?: { current_age?:number; end_age?:number; months?:number; series?:Array<{month:number;age:number;p10:number;p50:number;p80:number;p95:number}>; monte_carlo_terminal: {p10:number;p50:number;p80?:number;p95?:number;p90?:number} } | null;
  findings: InsightFinding[]; snapshot_comparison: SnapshotComparison;
};

export type FundConstituent = { constituent_key:string; identifier?:string|null; linked_security_id?:number|null; symbol?:string|null; name:string; weight_percent:number; sector:string; country:string; currency:string; asset_category:string };
export type FundCompositionInput = { source:string; source_url?:string|null; holdings_scope?:"full"|"top_10"; as_of_date?:string|null; constituents:FundConstituent[] };
export type FundComposition = FundCompositionInput & { security_id:number; security_name:string; reviewed_at:string; coverage_percent:number; stale:boolean };
export type PublicMetadataPreview = { security_id:number; provider:string; fetched_at:string; as_of_date?:string|null; composition?:FundCompositionInput|null; expense_ratio_percent?:number|null; facts:Record<string,unknown>; source_url?:string|null; warnings:string[]; holdings_count:number; holdings_scope:"full"|"top_10"; message:string };
export type PublicMetadataAcceptance = { metadata: FundMetadata; composition?: FundComposition|null };
export type FundMetadata = {security_id:number;provider:string;category?:string|null;thesis?:string|null;fund_family?:string|null;inception_date?:string|null;assets_under_management?:number|null;yield_percent?:number|null;turnover_percent?:number|null;beta?:number|null;expense_ratio_percent?:number|null;return_3y_percent?:number|null;return_5y_percent?:number|null;return_10y_percent?:number|null;return_since_inception_percent?:number|null;as_of_date?:string|null;fetched_at?:string|null;unavailable_fields:string[];reviewed_at:string};
export type PeerResearch = {security_id:number;retrieved_at:string;provider:string;candidates:Array<{symbol:string;name:string;category?:string|null;thesis?:string|null;expense_ratio_percent?:number|null;return_3y_percent?:number|null;return_5y_percent?:number|null;return_10y_percent?:number|null;matched_horizon?:string|null;matched_return_percent?:number|null;rank?:number|null}>;note:string;warnings:string[]};
export type ExposureRow = { key:string; label:string; value:number; percent:number; confidence:string; sources:string[] };
export type ExposureAnalysis = { display_currency:string; portfolio_value:number; composition_coverage_percent:number; company:ExposureRow[]; sector:ExposureRow[]; country:ExposureRow[]; currency:ExposureRow[]; asset_category:ExposureRow[]; overlaps:Array<{left_security_id:number;left_name:string;right_security_id:number;right_name:string;overlap_percent:number}>; compositions:FundComposition[]; policy_drift: Insights["allocation_drift"]; warnings:string[] };
export type MarketHistoryInput = { symbol:string; currency:string; observations:Array<{date:string;adjusted_close:number}> };
export type ManualMarketSeriesInput = MarketHistoryInput & { series_key:string; series_type:"benchmark"|"fx" };
export type HistoryRefreshResult = { series_key:string; symbol:string; refreshed:boolean; observation_count:number; message:string };
export type RiskSettings = { benchmark_symbol?:string|null; benchmark_currency?:string|null; minimum_observations:number };
export type RiskHolding = { security_id:number;name:string;symbol?:string|null;portfolio_weight_percent:number;observation_count:number;annualized_volatility_percent?:number|null;beta?:number|null;risk_contribution_percent?:number|null;max_drawdown_percent?:number|null;confidence:string;warning?:string|null };
export type RiskAnalysis = { display_currency:string;benchmark_symbol:string;history_years:number;coverage_percent:number;covered_portfolio_volatility_percent?:number|null;covered_portfolio_beta?:number|null;covered_portfolio_max_drawdown_percent?:number|null;holdings:RiskHolding[];correlations:Array<{left_security_id:number;right_security_id:number;correlation:number;observation_count:number}>;warnings:string[] };
export type SecurityFee = { security_id:number;security_name:string;expense_ratio_percent?:number|null;source:string;as_of_date?:string|null;reviewed_at:string;stale:boolean };
export type PortfolioFeeInput = { name:string;fee_type:"advisory_percent"|"fixed_account";annual_percent?:number|null;annual_amount?:number|null;currency:string;enabled:boolean };
export type PortfolioFee = PortfolioFeeInput & { id:number };
export type FeeSettings = { cash_reserve_months:number };
export type FeeAnalysis = { display_currency:string;portfolio_value:number;annual_fund_expenses:number;annual_advisory_fees:number;annual_fixed_fees:number;total_annual_fees:number;annual_fee_percent:number;cash_value:number;reserve_target?:number|null;potential_idle_cash?:number|null;potential_cash_drag?:number|null;holdings:Array<{security_id:number;name:string;value:number;expense_ratio_percent?:number|null;annual_cost?:number|null;confidence:string}>;portfolio_fees:PortfolioFee[];projections:Array<{years:number;cumulative_nominal_fees:number;ending_value_without_fees:number;ending_value_after_fees:number;opportunity_cost:number}>;warnings:string[] };

export type ScenarioPositionChange = { security_id: number; currency?: string | null; value_change: number; note?: string | null };
export type ScenarioInput = {
  name: string; description?: string | null; contribution: number; withdrawal: number; cash_reserve_change: number;
  position_changes: ScenarioPositionChange[]; goal_allocation_changes: Record<number, number>;
};
export type SavedScenario = ScenarioInput & { id: number; created_at: string; updated_at: string };
export type ScenarioMetrics = { portfolio_value:number; cash_value:number; cash_runway_months?:number|null; largest_holding?:string|null; largest_holding_percent:number; total_absolute_drift_percent?:number|null };
export type ScenarioAnalysis = {
  display_currency:string; current:ScenarioMetrics; proposed:ScenarioMetrics; estimated_realized_gain:number; estimated_tax?:number|null;
  goals:Array<{goal_id:number;name:string;current_allocated:number;proposed_allocated:number;current_probability?:number|null;proposed_probability?:number|null}>; warnings:string[];
};
export type StressTestInput = { preset?:string|null; market_shock_percent:number; interest_rate_change_bps:number; currency_shocks:Record<string,number>; category_shocks:Record<string,number>; sector_shocks:Record<string,number>; security_shocks:Record<number,number> };
export type StressTestResult = {
  display_currency:string; preset?:string|null; current_value:number; stressed_value:number; projected_loss:number; projected_loss_percent:number; cash_runway_months?:number|null;
  contributors:Array<{security_id:number;security_name:string;currency:string;current_value:number;shock_percent:number;projected_change:number}>;
  goals:Array<{goal_id:number;name:string;current_allocated:number;stressed_allocated:number;current_probability?:number|null;stressed_probability?:number|null}>; assumptions:string[];
};
