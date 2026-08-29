import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  previewImport: vi.fn(), commitImport: vi.fn(), previewBroker: vi.fn(), createBroker: vi.fn(), updateBroker: vi.fn(), deleteBroker: vi.fn(),
  updatePosition: vi.fn(), updatePositions: vi.fn(),
  lookThrough: vi.fn(), saveFundComposition: vi.fn(), previewPublicMetadata: vi.fn(), acceptPublicComposition: vi.fn(),
  riskAnalysis: vi.fn(), riskSettings: vi.fn(), refreshMarketHistory: vi.fn(), saveRiskSettings: vi.fn(),
  importMarketHistory: vi.fn(), importManualMarketSeries: vi.fn(), feeAnalysis: vi.fn(), securityFees: vi.fn(),
  feeSettings: vi.fn(), saveSecurityFee: vi.fn(), previewPublicMetadataForFee: vi.fn(), acceptPublicFee: vi.fn(),
  portfolioFees: vi.fn(), createPortfolioFee: vi.fn(), updatePortfolioFee: vi.fn(), deletePortfolioFee: vi.fn(),
  saveFeeSettings: vi.fn()
}));

vi.mock("../lib/api", () => ({ api: apiMock }));

import { AllocationPolicyPage, BrokerSettings, ExposureInsights, ExposurePage, FeesPage, GoalsPage, InsightsPage, MobilePositionCard, PositionsTable, ProfitLossTable, ProjectionSettings, RiskPage, ScenarioLab, UploadPage, ValueMetricsPage } from "../App";
import type { GoalsSummary, Insights, Position } from "../lib/types";

const fund = {
  id: 1, security_id: 10, broker_name: "HDFC", account_mask: "****1", security_name: "Index Fund", symbol: "FUND",
  security_type: "ETF", allocation_category: "Large Cap", sector: "Diversified", exchange: "NSE",
  investment_country: "India", snapshot_date: "2026-08-01", units: 1, total_cost_basis: 7500, total_fmv: 8350,
  total_cost_basis_display: 90, total_fmv_display: 100, currency: "INR", display_currency: "USD"
} as Position;

const insights = {
  display_currency:"USD", projection_setup_required:false, concentration:[{label:"FUND",value:100}], top_5_share:100, top_10_share:100,
  currency_exposure:[{label:"USD",value:100}], country_exposure:[{label:"United States",value:100}], exchange_exposure:[{label:"NYSE",value:100}],
  allocation_drift:{category:[{label:"Large Cap",actual_amount:100,actual_percent:100,target_percent:80,tolerance_percent:10,minimum_percent:70,maximum_percent:90,drift_percent:20,rebalance_amount:-20,compliant:false,outside_range_percent:10,policy_gap_amount:10}]}, allocation_policy:{configured_targets:1,compliant_targets:0,breached_targets:1,unconfigured_dimensions:["country","currency"],largest_breach:{label:"Large Cap",actual_percent:100,minimum_percent:70,maximum_percent:90,outside_range_percent:10}}, liquidity:[{label:"Liquid",value:100}], cash_runway_months:6,
  tax_lots:[{position_id:1,security_name:"Index Fund",classification:"Long term",gain:10,indicative_tax:2}], value_history:[], rolling_growth:{"1":1,"3":2,"12":3}, drawdown:[], holding_value_change:[{label:"FUND",value:10}], forecast:{monte_carlo_terminal:{p10:90,p50:110,p90:130}}, findings:[],
  snapshot_comparison:{available:false,latest_value:0,previous_value:0,total_value_change:0,total_value_change_percent:0,cash_change:0,new_holdings:[],exited_holdings:[],position_changes:[],coverage_changes:[],unusual_valuation_changes:[],allocation_shifts:[],disclosure:"Need another snapshot"}
} as Insights;

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.lookThrough.mockResolvedValue({display_currency:"USD",portfolio_value:100,composition_coverage_percent:0,
    company:[],sector:[],country:[],currency:[],asset_category:[],overlaps:[],compositions:[],warnings:["No composition"]});
  apiMock.riskSettings.mockResolvedValue({benchmark_symbol:"^GSPC",benchmark_currency:"USD",minimum_observations:60});
  apiMock.riskAnalysis.mockResolvedValue({display_currency:"USD",benchmark_symbol:"^GSPC",history_years:5,coverage_percent:0,
    covered_portfolio_volatility_percent:null,covered_portfolio_beta:null,covered_portfolio_max_drawdown_percent:null,
    holdings:[],correlations:[],warnings:["History unavailable"]});
  apiMock.refreshMarketHistory.mockResolvedValue([{series_key:"security:10",symbol:"FUND",refreshed:false,observation_count:0,message:"offline"}]);
  apiMock.saveRiskSettings.mockResolvedValue({benchmark_symbol:"^GSPC",benchmark_currency:"USD",minimum_observations:60});
  apiMock.importManualMarketSeries.mockResolvedValue({series_key:"benchmark:^GSPC",symbol:"^GSPC",refreshed:true,observation_count:2,message:"saved"});
  apiMock.securityFees.mockResolvedValue([{security_id:10,security_name:"Index Fund",expense_ratio_percent:null,source:"unset",as_of_date:null,reviewed_at:"",stale:true}]);
  apiMock.feeSettings.mockResolvedValue({cash_reserve_months:6});
  apiMock.feeAnalysis.mockResolvedValue({display_currency:"USD",portfolio_value:100,annual_fund_expenses:0,annual_advisory_fees:0,
    annual_fixed_fees:0,total_annual_fees:0,annual_fee_percent:0,cash_value:0,reserve_target:null,potential_idle_cash:null,
    potential_cash_drag:null,holdings:[],portfolio_fees:[],projections:[],warnings:["Set assumptions"]});
  apiMock.createPortfolioFee.mockResolvedValue({id:1,name:"Advice",fee_type:"advisory_percent",annual_percent:1,currency:"USD",enabled:true});
  apiMock.previewPublicMetadata.mockResolvedValue({security_id:10,provider:"public",fetched_at:"2026-08-01",composition:null,expense_ratio_percent:.25,message:"draft"});
  apiMock.acceptPublicFee.mockResolvedValue({security_id:10,security_name:"Index Fund",expense_ratio_percent:.25,source:"public",reviewed_at:"2026-08-01",stale:false});
  apiMock.previewImport.mockResolvedValue({
    broker_id:1, broker_name:"Fidelity", configuration_version:3, statement_date:"2026-08-01", detected_columns:["Symbol"],
    suggested_mapping:{symbol:"Symbol"}, errors:[], duplicate:false, fingerprint:"preview", locked_fields:[],
    rows:[{row_number:2,account_number:"FID-1",security_name:"Index Fund",symbol:"FUND",security_type:"ETF",
      allocation_category:"Large Cap",sector:"Diversified",exchange:"NSE",investment_country:"India",
      location_status:"statement",acquisition_date:"2024-01-15",lot_number:"LOT-1",units:2,
      per_unit_cost_basis:75,total_cost_basis:150,per_unit_fmv:100,total_fmv:200,currency:"INR"}]
  });
  apiMock.updatePosition.mockImplementation((_id, payload) => Promise.resolve({...fund, ...payload}));
  apiMock.updatePositions.mockResolvedValue([]);
});

afterEach(cleanup);

describe("decision coach workspaces", () => {
  it("places analytics content in its focused workspaces and defers phone charts", () => {
    Object.defineProperty(window, "innerWidth", {configurable:true, value:375});
    vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
    render(<ExposureInsights insights={insights}/>);
    expect(screen.getAllByText("Top 5 concentration")).toHaveLength(2);
    expect(screen.getAllByRole("button", {name:"Show chart"})).toHaveLength(2);
    fireEvent.click(screen.getAllByRole("button", {name:"Show chart"})[0]);
    expect(screen.getByRole("button", {name:"Hide chart"})).toBeInTheDocument();
    cleanup();
    render(<InsightsPage insights={insights}/>);
    expect(screen.queryByText("Configured allocation drift")).not.toBeInTheDocument();
    expect(screen.getByText("Portfolio review inbox")).toBeInTheDocument();
    cleanup();
    render(<AllocationPolicyPage insights={insights}/>);
    expect(screen.getByText("Allocation policy and drift")).toBeInTheDocument();
    expect(screen.getByText("10.00% outside")).toBeInTheDocument();
    cleanup();
    render(<ValueMetricsPage insights={insights}/>);
    expect(screen.getByText("Unrealized tax view")).toBeInTheDocument();
    Object.defineProperty(window, "innerWidth", {configurable:true, value:1024});
    vi.unstubAllGlobals();
  });

  it("shows projection guidance before planning inputs and uses the stated goal target", () => {
    render(<ProjectionSettings insights={{...insights, projection_setup_required:true, forecast:null} as Insights} assumptions={null} scheduledExpenses={[]} currency="USD" onChanged={vi.fn()}/>);
    const guidance = screen.getByText(/Set Expenses & Projections assumptions/i);
    const inputs = screen.getByRole("heading", {name:"Expenses & Projections"});
    expect(guidance.compareDocumentPosition(inputs) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    cleanup();

    const summary = {
      display_currency:"USD", investable_financial_assets:200, total_allocated:200, unallocated_remainder:0, over_allocated:false,
      goals:[
        {id:1,name:"Short goal",description:null,target_amount:100,target_currency:"USD",target_month:"2030-01",allocated_amount:50,allocated_currency:"USD",monthly_contribution:0,contribution_currency:"USD",priority:null,target_amount_display:100,allocated_amount_display:50,monthly_contribution_display:0,display_currency:"USD",projected_value:80,projected_shortfall_surplus:-20,required_monthly_contribution:10,probability_of_reaching:0,created_at:"",updated_at:""},
        {id:2,name:"Surplus goal",description:null,target_amount:100,target_currency:"USD",target_month:"2030-01",allocated_amount:150,allocated_currency:"USD",monthly_contribution:0,contribution_currency:"USD",priority:null,target_amount_display:100,allocated_amount_display:150,monthly_contribution_display:0,display_currency:"USD",projected_value:140,projected_shortfall_surplus:40,required_monthly_contribution:0,probability_of_reaching:100,created_at:"",updated_at:""}
      ]
    } as GoalsSummary;
    render(<GoalsPage summary={summary} currency={{display_currency:"USD",supported_currencies:["USD"]}} onChanged={vi.fn()}/>);
    expect(screen.queryByRole("columnheader", {name:"Progress"})).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", {name:"Inflation-adjusted target"})).not.toBeInTheDocument();
    expect(screen.getByText("-$20.00")).toHaveClass("bad");
    expect(screen.getByText("$40.00")).toHaveClass("good");
  });

  it("expands mobile cards from the card, hides the security name, and isolates refresh", () => {
    const refresh = vi.fn();
    render(<MobilePositionCard position={fund} canRefresh onRefresh={refresh}/>);
    const card = screen.getByRole("button", {name:"FUND details"});
    expect(card).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Index Fund")).not.toBeInTheDocument();
    fireEvent.keyDown(card, {key:"Enter"});
    expect(card).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(screen.getByRole("button", {name:/refresh price/i}));
    expect(refresh).toHaveBeenCalledOnce();
    expect(card).toHaveAttribute("aria-expanded", "true");
  });

  it("uses per-unit values in mobile position cards", () => {
    render(<MobilePositionCard position={{...fund, per_unit_fmv: 25, per_unit_cost_basis: 20, per_unit_fmv_display: 25, per_unit_cost_basis_display: 20, display_currency: "INR"}} moneyMode="per-unit" canRefresh onRefresh={vi.fn()} />);
    expect(screen.getByText("₹25.00")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", {name:"FUND details"}));
    expect(screen.getByText("Value / unit")).toBeInTheDocument();
    expect(screen.getByText("₹20.00")).toBeInTheDocument();
  });

  it("uses Indian digit grouping for INR amounts", () => {
    render(<MobilePositionCard position={{...fund, per_unit_fmv: 1_000_000, per_unit_cost_basis: 20, per_unit_fmv_display: 1_000_000, per_unit_cost_basis_display: 20, display_currency: "INR"}} moneyMode="per-unit" canRefresh onRefresh={vi.fn()} />);
    expect(screen.getByText("₹10,00,000.00")).toBeInTheDocument();
  });

  it("uses global display-currency amounts in portfolio and profit/loss tables", () => {
    const convertedPosition = {
      ...fund,
      total_cost_basis: 83_000,
      total_fmv: 166_000,
      total_cost_basis_display: 1_000,
      total_fmv_display: 2_000,
      unrealized_gain_loss_native: 83_000,
      unrealized_gain_loss: 1_000
    };
    render(<PositionsTable positions={[convertedPosition]} brokers={[]} categories={[]} onRefresh={async () => {}} externalFilter="" structuredFilter={{}} onExternalFilterChange={() => {}} onStructuredFilterChange={() => {}} currencyMode="display" />);
    expect(screen.getByRole("columnheader", {name:"Total Cost Basis (USD)"})).toBeInTheDocument();
    expect(screen.getByText("$1,000.00")).toBeInTheDocument();
    expect(screen.getAllByText("$2,000.00")).toHaveLength(2);
    cleanup();
    render(<ProfitLossTable positions={[convertedPosition]} currencyMode="display" />);
    expect(screen.getByRole("columnheader", {name:/^P\/L \(USD\)/})).toBeInTheDocument();
    expect(screen.getAllByText("$1,000.00")).toHaveLength(3);
    expect(screen.getByText("$2,000.00")).toBeInTheDocument();
  });

  it("defaults portfolio tables to each position's source currency", () => {
    const convertedPosition = {...fund, total_cost_basis: 83_000, total_fmv: 166_000, total_cost_basis_display: 1_000, total_fmv_display: 2_000, unrealized_gain_loss_native: 83_000, unrealized_gain_loss: 1_000};
    render(<PositionsTable positions={[convertedPosition]} brokers={[]} categories={[]} onRefresh={async () => {}} externalFilter="" structuredFilter={{}} onExternalFilterChange={() => {}} onStructuredFilterChange={() => {}} />);
    expect(screen.getByRole("columnheader", {name:"Total FMV (Position currency)"})).toBeInTheDocument();
    expect(screen.getAllByText("₹1,66,000.00")).toHaveLength(2);
    cleanup();
    render(<ProfitLossTable positions={[convertedPosition]} />);
    expect(screen.getByRole("columnheader", {name:/^P\/L \(Position currency\)/})).toBeInTheDocument();
    expect(screen.getAllByText("₹83,000.00")).toHaveLength(3);
  });

  it("lets table pages opt into the global currency through their checkbox", () => {
    const onCurrencyModeChange = vi.fn();
    render(<PositionsTable positions={[fund]} brokers={[]} categories={[]} onRefresh={async () => {}} externalFilter="" structuredFilter={{}} onExternalFilterChange={() => {}} onStructuredFilterChange={() => {}} currencyMode="position" onCurrencyModeChange={onCurrencyModeChange} />);
    fireEvent.click(screen.getByLabelText("Use position currency"));
    expect(onCurrencyModeChange).toHaveBeenCalledWith("display");
  });

  it("keeps edited per-unit and total cost and FMV values in sync", async () => {
    const position = {...fund, units:10, per_unit_cost_basis:100, total_cost_basis:1_000, per_unit_fmv:200, total_fmv:2_000};
    render(<PositionsTable positions={[position]} brokers={[]} categories={[]} onRefresh={async () => {}} externalFilter="" structuredFilter={{}} onExternalFilterChange={() => {}} onStructuredFilterChange={() => {}} />);
    fireEvent.click(screen.getByRole("button", {name:/edit mode/i}));
    const perUnitCost = screen.getByLabelText("Per Unit Cost Basis for Index Fund");
    const totalCost = screen.getByLabelText("Total Cost Basis for Index Fund");
    const perUnitFmv = screen.getByLabelText("Per Unit FMV for Index Fund");
    const totalFmv = screen.getByLabelText("Total FMV for Index Fund");
    fireEvent.change(perUnitCost, {target:{value:"120"}});
    expect(totalCost).toHaveValue(1_200);
    fireEvent.change(totalCost, {target:{value:"1500"}});
    expect(perUnitCost).toHaveValue(150);
    fireEvent.change(perUnitFmv, {target:{value:"250"}});
    expect(totalFmv).toHaveValue(2_500);
    fireEvent.change(totalFmv, {target:{value:"3000"}});
    expect(perUnitFmv).toHaveValue(300);
    fireEvent.click(screen.getByTitle("Save position"));
    await waitFor(() => expect(apiMock.updatePosition).toHaveBeenCalledWith(1, expect.objectContaining({per_unit_cost_basis:150, total_cost_basis:1_500, per_unit_fmv:300, total_fmv:3_000})));
    const saveAll = screen.getByRole("button", {name:/save all/i});
    await waitFor(() => expect(saveAll).toBeEnabled());
    fireEvent.click(saveAll);
    await waitFor(() => expect(apiMock.updatePositions).toHaveBeenCalledWith([expect.objectContaining({position_id:1, payload:expect.objectContaining({per_unit_cost_basis:150, total_cost_basis:1_500, per_unit_fmv:300, total_fmv:3_000})})]));
  });

  it("routes each data-quality action with its structured filter", () => {
    const onNavigate = vi.fn();
    const finding = {id:"quality",category:"data_quality",severity:"medium",title:"Incomplete",confidence:"high",evidence:[],explanation:"",suggested_actions:[],navigation:{page:"positions",actions:[{label:"Unclassified positions: 2",filters:{allocation_category:"Unclassified"}},{label:"Unresolved location positions: 1",filters:{exchange:"Unresolved"}}]}} as Insights["findings"][number];
    render(<InsightsPage insights={{...insights,findings:[finding]}} onNavigate={onNavigate}/>);
    fireEvent.click(screen.getByRole("button", {name:"Unclassified positions: 2"}));
    expect(onNavigate).toHaveBeenCalledWith(expect.objectContaining({filters:{allocation_category:"Unclassified"}}));
  });

  it("loads exposure and opens the manual fund editor", async () => {
    const {rerender}=render(<ExposurePage positions={[fund]}/>);
    expect(await screen.findByText("Effective companies")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Fund"), {target:{value:"10"}});
    fireEvent.click(screen.getByRole("button", {name:/add row/i}));
    expect(screen.getByDisplayValue("new-1")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Fund"), {target:{value:""}});
    expect(screen.queryByRole("button", {name:/add row/i})).not.toBeInTheDocument();
    rerender(<ExposurePage positions={[{...fund,total_fmv_display:110}]}/>);
    await waitFor(()=>expect(apiMock.lookThrough).toHaveBeenCalledTimes(2));
  });

  it("refreshes historical risk without hiding an offline result", async () => {
    render(<RiskPage positions={[fund]} currency="USD"/>);
    expect(await screen.findByText("Holding risk decomposition")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", {name:/refresh all histories/i}));
    await waitFor(() => expect(apiMock.refreshMarketHistory).toHaveBeenCalledOnce());
    expect(await screen.findByText("0 of 1 series refreshed.")).toBeInTheDocument();
  });

  it("saves an edited benchmark before importing its manual history", async () => {
    render(<RiskPage positions={[fund]} currency="USD"/>);
    await screen.findByText("Holding risk decomposition");
    fireEvent.change(screen.getByLabelText("Benchmark symbol"), {target:{value:"^NSEI"}});
    fireEvent.change(screen.getByLabelText("Series"), {target:{value:"benchmark"}});
    fireEvent.change(screen.getByLabelText("CSV: date,adjusted_close"), {target:{value:"2026-01-01,100\n2026-01-02,101"}});
    fireEvent.click(screen.getByRole("button", {name:/import history/i}));
    await waitFor(()=>expect(apiMock.importManualMarketSeries).toHaveBeenCalledOnce());
    expect(apiMock.saveRiskSettings.mock.invocationCallOrder[0]).toBeLessThan(apiMock.importManualMarketSeries.mock.invocationCallOrder[0]);
    expect(apiMock.importManualMarketSeries).toHaveBeenCalledWith(expect.objectContaining({series_key:"benchmark:^NSEI"}));
  });

  it("creates a portfolio advisory fee from the fees workspace", async () => {
    render(<FeesPage positions={[fund]} currency="USD"/>);
    expect(await screen.findByText("Security expense ratios")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Name"), {target:{value:"Advice"}});
    fireEvent.change(screen.getByLabelText("Annual %"), {target:{value:"1"}});
    fireEvent.click(screen.getByRole("button", {name:/add fee/i}));
    await waitFor(() => expect(apiMock.createPortfolioFee).toHaveBeenCalledWith(expect.objectContaining({name:"Advice",annual_percent:1})));
  });

  it("requires a visible public fee draft before acceptance", async () => {
    render(<FeesPage positions={[fund]} currency="USD"/>);
    await screen.findByText("Security expense ratios");
    const accept=screen.getByRole("button",{name:"Accept public"});
    expect(accept).toBeDisabled();
    fireEvent.click(screen.getByRole("button",{name:"Public draft"}));
    await waitFor(()=>expect(accept).toBeEnabled());
    fireEvent.click(accept);
    await waitFor(()=>expect(apiMock.acceptPublicFee).toHaveBeenCalledWith(10));
  });

  it("explains Scenario Lab inputs as display-currency amounts", () => {
    render(<ScenarioLab scenarios={[]} positions={[]} goals={{display_currency:"INR",investable_financial_assets:0,total_allocated:0,unallocated_remainder:0,over_allocated:false,goals:[]}} currency={{display_currency:"INR",supported_currencies:["INR","USD"]}} onChanged={vi.fn()}/>);
    expect(screen.getByText("All values below are amounts in INR, not percentages. This model does not change stored positions.")).toBeInTheDocument();
    expect(screen.getByLabelText(/Contribution \/ deposit/)).toBeInTheDocument();
    expect(screen.getByText("External cash added to the portfolio in INR.")).toBeInTheDocument();
    expect(screen.getByLabelText(/Withdrawal \/ distribution/)).toBeInTheDocument();
    expect(screen.getByText(/positive adds cash, negative removes it/i)).toBeInTheDocument();
  });

  it("uses saved broker mappings while exposing import-only locks and normalized preview fields", async () => {
    render(<UploadPage brokers={[{id:1,name:"Fidelity"}]} onImported={vi.fn()}/>);
    const file = {name:"positions.csv",text:vi.fn().mockResolvedValue("Symbol\nFUND")};
    fireEvent.change(screen.getByLabelText("CSV File"), {target:{files:[file]}});
    await waitFor(()=>expect(screen.getByRole("button",{name:/preview import/i})).toBeEnabled());
    fireEvent.click(screen.getByRole("button",{name:/preview import/i}));
    await waitFor(()=>expect(apiMock.previewImport).toHaveBeenCalledOnce());
    expect(apiMock.previewImport).toHaveBeenCalledWith(expect.objectContaining({broker_id:1}));

    for (const label of ["Allocation Category","Sector","Exchange","Investment Country"]) {
      expect(screen.getByRole("checkbox",{name:label})).toBeInTheDocument();
    }
    expect(screen.getByText(/Column mappings are saved with this broker/)).toBeInTheDocument();
    for (const heading of ["Account","Allocation","Location","Acquisition Date","Lot","Currency"]) {
      expect(screen.getByRole("columnheader",{name:heading})).toBeInTheDocument();
    }
    expect(screen.getByText("Diversified")).toBeInTheDocument();
    expect(screen.getByText("India")).toBeInTheDocument();
    expect(screen.getByText("statement")).toBeInTheDocument();
    expect(screen.getByText("LOT-1")).toBeInTheDocument();
  });

  it("opens the broker editor and supports the advanced JSON configuration mode", () => {
    render(<BrokerSettings brokers={[{id:1,name:"Fidelity",default_currency:"USD",locked_fields:[],configuration_version:1,header_signature:[],mappings:{}}]} onChanged={vi.fn()}/>);
    fireEvent.click(screen.getByRole("button", {name:/add broker/i}));
    expect(screen.getByRole("heading", {name:"New broker"})).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", {name:"Advanced JSON"}));
    expect(screen.getByLabelText("Broker configuration JSON")).toBeInTheDocument();
    expect(screen.getByRole("button", {name:"Save broker"})).toBeEnabled();
  });

  it("uses comma-separated headers for mappings and preview", async () => {
    apiMock.previewBroker.mockResolvedValue({header_signature:["Account","Ticker","Qty"],detected_headers:["Account","Ticker","Qty"],mappings:{symbol:"Ticker",units:"Qty"},rows:[],invalid_rows:[],errors:[],valid:false});
    render(<BrokerSettings brokers={[]} onChanged={vi.fn()}/>);
    fireEvent.click(screen.getByRole("button", {name:/add broker/i}));
    fireEvent.change(screen.getByLabelText("Header names (comma-separated)"), {target:{value:"Account, Ticker, Qty"}});
    expect(screen.getAllByRole("option", {name:"Ticker"}).length).toBeGreaterThan(0);
    fireEvent.change(screen.getByLabelText("Sample CSV text"), {target:{value:"Account,Ticker,Qty\nA,AAA,2"}});
    fireEvent.click(screen.getByRole("button", {name:/preview configuration/i}));
    await waitFor(() => expect(apiMock.previewBroker).toHaveBeenCalled());
    expect(apiMock.previewBroker.mock.calls[0][0].draft.header_signature).toEqual(["Account", "Ticker", "Qty"]);
  });

  it("keeps detected CSV columns available while a broker mapping is edited", async () => {
    apiMock.previewBroker.mockResolvedValue({
      header_signature:["Account","Symbol","Name","Quantity"], detected_headers:["Account","Symbol","Name","Quantity"],
      mappings:{account_number:"Account",symbol:"Symbol",security_name:"Name",units:"Quantity"}, rows:[{row_number:2,security_name:"Alpha",symbol:"AAA",security_type:"Other",units:2}], invalid_rows:[], errors:[], valid:true
    });
    render(<BrokerSettings brokers={[]} onChanged={vi.fn()}/>);
    fireEvent.click(screen.getByRole("button", {name:/add broker/i}));
    fireEvent.change(screen.getByLabelText("Name"), {target:{value:"Test broker"}});
    fireEvent.change(screen.getByLabelText("Sample CSV text"), {target:{value:"Account,Symbol,Name,Quantity\nA,AAA,Alpha,2"}});
    fireEvent.click(screen.getByRole("button", {name:/preview configuration/i}));
    await waitFor(() => expect(apiMock.previewBroker).toHaveBeenCalledOnce());
    fireEvent.change(screen.getAllByLabelText("Symbol")[1], {target:{value:"Name"}});
    expect(screen.getByLabelText("Account Number")).toHaveValue("Account");
    expect(screen.getAllByLabelText("Security Name")[1]).toHaveValue("Name");
    expect(screen.getAllByLabelText("Units")[1]).toHaveValue("Quantity");
  });
});
