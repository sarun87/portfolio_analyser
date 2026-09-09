import type {
  AuthStatus,
  Broker,
  BrokerConfigPreview,
  BrokerDraft,
  ClassificationRefreshResult,
  CurrencySetting,
  ReportBranding, ReportBrandingPayload,
  DashboardAnalytics,
  FxRate,
  ImportPreview,
  Position,
  PositionCreatePayload,
  PositionUpdatePayload,
  PriceRefreshResult,
  RealEstateAsset,
  RealEstatePayload,
  PrivateEquityAsset, PrivateEquityPayload,
  StaticAccount,
  StaticAccountPayload
  , Liability, LiabilityPayload
  , FinancialAssumptions, AllocationTarget, Goal, GoalPayload, GoalsSummary, Insights, InsightFinding, SnapshotComparison,
  ScenarioInput, SavedScenario, ScenarioAnalysis, StressTestInput, StressTestResult,
  ExposureAnalysis, FundComposition, FundCompositionInput, PublicMetadataPreview, PublicMetadataAcceptance, FundMetadata, PeerResearch,
  HistoryRefreshResult, ManualMarketSeriesInput, MarketHistoryInput, RiskAnalysis, RiskSettings,
  FeeAnalysis, FeeSettings, SecurityFee, PortfolioFee, PortfolioFeeInput, ScheduledExpense, ScheduledExpenseInput
} from "./types";

const jsonHeaders = { "Content-Type": "application/json" };

function csrfToken(): string | null {
  const prefix = "portfolio_csrf=";
  return document.cookie.split(";").map(cookie => cookie.trim()).find(cookie => cookie.startsWith(prefix))?.slice(prefix.length) || null;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  const method = (init?.method || "GET").toUpperCase();
  if (["POST", "PUT", "PATCH", "DELETE"].includes(method) && !url.startsWith("/api/auth/setup") && !url.startsWith("/api/auth/unlock")) {
    const token = csrfToken();
    if (token) headers.set("X-CSRF-Token", token);
  }
  const response = await fetch(url, { ...init, headers, credentials: "same-origin" });
  if (!response.ok) {
    let message = response.statusText;
    try {
      const payload = await response.json();
      message = payload.detail || message;
    } catch {
      // Keep status text.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

async function download(url: string, payload: unknown): Promise<Blob> {
  const token = csrfToken();
  const response = await fetch(url, { method: "POST", headers: { ...jsonHeaders, ...(token ? { "X-CSRF-Token": token } : {}) }, credentials: "same-origin", body: JSON.stringify(payload) });
  if (!response.ok) {
    let message = response.statusText;
    try { message = (await response.json()).detail || message; } catch { /* retain status */ }
    throw new Error(message);
  }
  return response.blob();
}

export const api = {
  authStatus: () => request<AuthStatus>("/api/auth/status"),
  setup: async (passphrase: string) => {
    const status = await request<AuthStatus>("/api/auth/setup", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ passphrase })
    });
    return status;
  },
  unlock: async (passphrase: string) => {
    const status = await request<AuthStatus>("/api/auth/unlock", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ passphrase })
    });
    return status;
  },
  lock: async () => {
    return request<AuthStatus>("/api/auth/lock", { method: "POST" });
  },
  logout: async () => request<AuthStatus>("/api/auth/logout", { method: "POST" }),
  changePassphrase: (newPassphrase: string) =>
    request<AuthStatus>("/api/auth/change-passphrase", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ new_passphrase: newPassphrase })
    }),
  brokers: () => request<Broker[]>("/api/brokers"),
  previewBroker: (payload: { draft: BrokerDraft; csv_text: string; statement_currency?: string }) => request<BrokerConfigPreview>("/api/brokers/preview", { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  createBroker: (payload: { draft: BrokerDraft; sample_csv?: string; statement_currency?: string }) => request<Broker>("/api/brokers", { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  updateBroker: (id: number, payload: { draft: BrokerDraft; sample_csv?: string; statement_currency?: string }) => request<Broker>(`/api/brokers/${id}`, { method: "PUT", headers: jsonHeaders, body: JSON.stringify(payload) }),
  deleteBroker: (id: number) => request<{ deleted: boolean }>(`/api/brokers/${id}`, { method: "DELETE" }),
  previewImport: (payload: Record<string, unknown>) =>
    request<ImportPreview>("/api/imports/preview", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload)
    }),
  commitImport: (payload: Record<string, unknown>) =>
    request<{ import_id: number; imported_rows: number; duplicate: boolean; added_rows?: number; modified_rows?: number; deleted_rows?: number }>("/api/imports/commit", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload)
    }),
  positions: () => request<Position[]>("/api/positions"),
  createPosition: (payload: PositionCreatePayload) =>
    request<Position>("/api/positions", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload)
    }),
  updatePosition: (id: number, payload: PositionUpdatePayload) =>
    request<Position>(`/api/positions/${id}`, {
      method: "PUT",
      headers: jsonHeaders,
      body: JSON.stringify(payload)
    }),
  updatePositions: (updates: Array<{ position_id: number; payload: PositionUpdatePayload }>) =>
    request<Position[]>("/api/positions/bulk", {
      method: "PUT",
      headers: jsonHeaders,
      body: JSON.stringify(updates)
    }),
  deletePosition: (id: number) => request<{ deleted: boolean }>(`/api/positions/${id}`, { method: "DELETE" }),
  profitLoss: () => request<Position[]>("/api/profit-loss"),
  dashboard: () => request<DashboardAnalytics>("/api/analytics/dashboard"),
  reportBranding: () => request<ReportBranding>("/api/report-branding"),
  saveReportBranding: (payload: ReportBrandingPayload) => request<ReportBranding>("/api/report-branding", { method: "PUT", headers: jsonHeaders, body: JSON.stringify(payload) }),
  generateReport: (payload: ReportBrandingPayload & { report_type: "summary" | "detail" }) => download("/api/reports/generate", payload),
  insights: () => request<Insights>("/api/insights"),
  projectionInsights: () => request<Insights>("/api/insights/projection"),
  reviewInbox: () => request<InsightFinding[]>("/api/review-inbox"),
  snapshotComparison: () => request<SnapshotComparison>("/api/snapshot-comparison"),
  scenarios: () => request<SavedScenario[]>("/api/scenarios"),
  saveScenario: (payload: ScenarioInput) => request<SavedScenario>("/api/scenarios", { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  updateScenario: (id: number, payload: ScenarioInput) => request<SavedScenario>(`/api/scenarios/${id}`, { method: "PUT", headers: jsonHeaders, body: JSON.stringify(payload) }),
  deleteScenario: (id: number) => request<{deleted:boolean}>(`/api/scenarios/${id}`, { method: "DELETE" }),
  analyzeScenario: (payload: ScenarioInput) => request<ScenarioAnalysis>("/api/scenarios/analyze", { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  runStressTest: (payload: StressTestInput) => request<StressTestResult>("/api/stress-tests/run", { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  lookThrough: () => request<ExposureAnalysis>("/api/look-through"),
  saveFundComposition: (id:number,payload:FundCompositionInput) => request<FundComposition>(`/api/fund-compositions/${id}`,{method:"PUT",headers:jsonHeaders,body:JSON.stringify(payload)}),
  previewPublicMetadata: (id:number, payload: { source: "yahoo_html" | "google_finance_html" | "custom_url" | "ishares_csv" | "vanguard_csv"; url?: string } = {source:"yahoo_html"}) => request<PublicMetadataPreview>(`/api/public-metadata/${id}/preview`,{method:"POST",headers:jsonHeaders,body:JSON.stringify(payload)}),
  acceptPublicComposition: (id:number) => request<PublicMetadataAcceptance>(`/api/fund-compositions/${id}/accept-public`,{method:"POST"}),
  fundMetadata: (id:number) => request<FundMetadata|null>(`/api/fund-metadata/${id}`),
  researchPeers: (id:number) => request<PeerResearch>(`/api/fund-peers/${id}/research`,{method:"POST"}),
  cachedPeers: (id:number) => request<PeerResearch>(`/api/fund-peers/${id}`),
  riskSettings: () => request<RiskSettings>("/api/risk/settings"),
  saveRiskSettings: (payload:RiskSettings) => request<RiskSettings>("/api/risk/settings",{method:"PUT",headers:jsonHeaders,body:JSON.stringify(payload)}),
  refreshMarketHistory: () => request<HistoryRefreshResult[]>("/api/market-history/refresh",{method:"POST"}),
  importMarketHistory: (id:number,payload:MarketHistoryInput) => request<HistoryRefreshResult>(`/api/market-history/${id}`,{method:"PUT",headers:jsonHeaders,body:JSON.stringify(payload)}),
  importManualMarketSeries: (payload:ManualMarketSeriesInput) => request<HistoryRefreshResult>("/api/market-history/manual-series",{method:"POST",headers:jsonHeaders,body:JSON.stringify(payload)}),
  riskAnalysis: () => request<RiskAnalysis>("/api/risk-analysis"),
  securityFees: () => request<SecurityFee[]>("/api/security-fees"),
  saveSecurityFee: (id:number,expense_ratio_percent:number|null) => request<SecurityFee>(`/api/security-fees/${id}`,{method:"PUT",headers:jsonHeaders,body:JSON.stringify({expense_ratio_percent,source:"manual"})}),
  acceptPublicFee: (id:number) => request<SecurityFee>(`/api/security-fees/${id}/accept-public`,{method:"POST"}),
  portfolioFees: () => request<PortfolioFee[]>("/api/portfolio-fees"),
  createPortfolioFee: (payload:PortfolioFeeInput) => request<PortfolioFee>("/api/portfolio-fees",{method:"POST",headers:jsonHeaders,body:JSON.stringify(payload)}),
  updatePortfolioFee: (id:number,payload:PortfolioFeeInput) => request<PortfolioFee>(`/api/portfolio-fees/${id}`,{method:"PUT",headers:jsonHeaders,body:JSON.stringify(payload)}),
  deletePortfolioFee: (id:number) => request<{deleted:boolean}>(`/api/portfolio-fees/${id}`,{method:"DELETE"}),
  feeSettings: () => request<FeeSettings>("/api/fees/settings"),
  saveFeeSettings: (payload:FeeSettings) => request<FeeSettings>("/api/fees/settings",{method:"PUT",headers:jsonHeaders,body:JSON.stringify(payload)}),
  feeAnalysis: () => request<FeeAnalysis>("/api/fee-analysis"),
  assumptions: () => request<FinancialAssumptions>("/api/settings/assumptions"),
  saveAssumptions: (payload: FinancialAssumptions) => request<FinancialAssumptions>("/api/settings/assumptions", { method: "PUT", headers: jsonHeaders, body: JSON.stringify(payload) }),
  scheduledExpenses: () => request<ScheduledExpense[]>("/api/scheduled-expenses"),
  createScheduledExpense: (payload: ScheduledExpenseInput) => request<ScheduledExpense>("/api/scheduled-expenses", { method:"POST", headers:jsonHeaders, body:JSON.stringify(payload) }),
  updateScheduledExpense: (id:number, payload: ScheduledExpenseInput) => request<ScheduledExpense>(`/api/scheduled-expenses/${id}`, { method:"PUT", headers:jsonHeaders, body:JSON.stringify(payload) }),
  deleteScheduledExpense: (id:number) => request<{deleted:boolean}>(`/api/scheduled-expenses/${id}`, { method:"DELETE" }),
  allocationTargets: (dimension?: string) => request<AllocationTarget[]>(`/api/allocation-targets${dimension ? `?dimension=${dimension}` : ""}`),
  saveAllocationTargets: (dimension: string, targets: AllocationTarget[]) => request<AllocationTarget[]>(`/api/allocation-targets/${dimension}`, { method: "PUT", headers: jsonHeaders, body: JSON.stringify({ dimension, targets }) }),
  allocationCategories: () => request<string[]>("/api/allocation-categories"),
  createAllocationCategory: (name:string) => request<string>("/api/allocation-categories", {method:"POST",headers:jsonHeaders,body:JSON.stringify({name})}),
  deleteAllocationCategory: (name:string) => request<{deleted:boolean}>(`/api/allocation-categories/${encodeURIComponent(name)}`, {method:"DELETE"}),
  goals: () => request<GoalsSummary>("/api/goals"),
  createGoal: (payload: GoalPayload) => request<Goal>("/api/goals", { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }),
  updateGoal: (id: number, payload: GoalPayload) => request<Goal>(`/api/goals/${id}`, { method: "PUT", headers: jsonHeaders, body: JSON.stringify(payload) }),
  deleteGoal: (id: number) => request<{ deleted: boolean }>(`/api/goals/${id}`, { method: "DELETE" }),
  refreshSecurity: (securityId: number) =>
    request<PriceRefreshResult>(`/api/prices/refresh/${securityId}`, { method: "POST" }),
  refreshAll: () => request<PriceRefreshResult[]>("/api/prices/refresh-all", { method: "POST" }),
  classifySecurity: (securityId: number) =>
    request<ClassificationRefreshResult>(`/api/securities/classify/${securityId}`, { method: "POST" }),
  classifyAll: () => request<ClassificationRefreshResult[]>("/api/securities/classify-all", { method: "POST" }),
  currency: () => request<CurrencySetting>("/api/currency"),
  setCurrency: (currency: string) => request<CurrencySetting>(`/api/currency/${currency}`, { method: "POST" }),
  fxRates: () => request<FxRate[]>("/api/fx-rates"),
  setFxRate: (payload: { from_currency: string; to_currency: string; rate: number }) =>
    request<FxRate>("/api/fx-rates", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload)
    }),
  refreshFxRates: () => request<FxRate[]>("/api/fx-rates/refresh", { method: "POST" }),
  staticAccounts: () => request<StaticAccount[]>("/api/static-accounts"),
  createStaticAccount: (payload: StaticAccountPayload) =>
    request<StaticAccount>("/api/static-accounts", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload)
    }),
  updateStaticAccount: (id: number, payload: StaticAccountPayload) =>
    request<StaticAccount>(`/api/static-accounts/${id}`, {
      method: "PUT",
      headers: jsonHeaders,
      body: JSON.stringify(payload)
    }),
  deleteStaticAccount: (id: number) => request<{ deleted: boolean }>(`/api/static-accounts/${id}`, { method: "DELETE" }),
  realEstate: () => request<RealEstateAsset[]>("/api/real-estate"),
  createRealEstate: (payload: RealEstatePayload) =>
    request<RealEstateAsset>("/api/real-estate", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload)
    }),
  updateRealEstate: (id: number, payload: RealEstatePayload) =>
    request<RealEstateAsset>(`/api/real-estate/${id}`, {
      method: "PUT",
      headers: jsonHeaders,
      body: JSON.stringify(payload)
    }),
  deleteRealEstate: (id: number) => request<{ deleted: boolean }>(`/api/real-estate/${id}`, { method: "DELETE" }),
  privateEquity: () => request<PrivateEquityAsset[]>("/api/private-equity"),
  createPrivateEquity: (payload:PrivateEquityPayload) => request<PrivateEquityAsset>("/api/private-equity",{method:"POST",headers:jsonHeaders,body:JSON.stringify(payload)}),
  updatePrivateEquity: (id:number,payload:PrivateEquityPayload) => request<PrivateEquityAsset>(`/api/private-equity/${id}`,{method:"PUT",headers:jsonHeaders,body:JSON.stringify(payload)}),
  deletePrivateEquity: (id:number) => request<{deleted:boolean}>(`/api/private-equity/${id}`,{method:"DELETE"}),
  liabilities: () => request<Liability[]>("/api/liabilities"),
  createLiability: (payload: LiabilityPayload) => request<Liability>("/api/liabilities", { method:"POST", headers:jsonHeaders, body:JSON.stringify(payload) }),
  updateLiability: (id: number, payload: LiabilityPayload) => request<Liability>(`/api/liabilities/${id}`, { method:"PUT", headers:jsonHeaders, body:JSON.stringify(payload) }),
  deleteLiability: (id: number) => request<{deleted:boolean}>(`/api/liabilities/${id}`, { method:"DELETE"}),
  cleanDatabase: () =>
    request<{ cleaned: boolean; message: string; reset: boolean }>("/api/database/clean", {
      method: "POST"
    }),
  cleanDatabaseScope: (scope: "brokerage" | "static" | "real-estate" | "private-equity" | "liabilities" | "all") =>
    request<{ cleaned: boolean; message: string; reset: boolean }>(`/api/database/clean/${scope}`, {
      method: "POST"
    })
};
