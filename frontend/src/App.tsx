import {
  BarChart3,
  Building2,
  Database,
  FileUp,
  FlaskConical,
  Home,
  Landmark,
  LineChart as LineIcon,
  Lock,
  Moon,
  Menu,
  Pencil,
  Plus,
  PieChart as PieIcon,
  RefreshCw,
  Save,
  Shield,
  Sun,
  Table2,
  Trash2,
  TrendingUp,
  Target,
  Lightbulb,
  Layers,
  Activity,
  BadgeDollarSign,
  Unlock,
  X
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import { api } from "./lib/api";
import type {
  AuthStatus,
  Broker,
  BrokerConfigPreview,
  BrokerDraft,
  CurrencySetting,
  DashboardAnalytics,
  FxRate,
  ImportPreview,
  Position,
  PositionCreatePayload,
  PositionUpdatePayload,
  RealEstateAsset,
  RealEstatePayload, PrivateEquityAsset, PrivateEquityPayload,
  StaticAccount,
  StaticAccountPayload,
  FinancialAssumptions,
  AllocationTarget,
  GoalPayload,
  GoalsSummary,
  Insights
  , SavedScenario, ScenarioInput, ScenarioAnalysis, StressTestInput, StressTestResult,
  ExposureAnalysis, FundCompositionInput, FundConstituent, PublicMetadataPreview, FundMetadata, PeerResearch,
  RiskAnalysis, RiskSettings, FeeAnalysis, SecurityFee, PortfolioFeeInput
} from "./lib/types";

type View = "overview" | "assets" | "portfolio" | "analytics" | "planning" | "upload" | "settings";

const fieldLabels: Record<string, string> = {
  account_number: "Account Number",
  security_name: "Security Name",
  symbol: "Symbol",
  security_type: "Security Type",
  allocation_category: "Allocation Category",
  sector: "Sector",
  exchange: "Exchange",
  investment_country: "Investment Country",
  acquisition_date: "Acquisition Date",
  lot_number: "Lot Number",
  units: "Units",
  per_unit_cost_basis: "Per Unit Cost Basis",
  total_cost_basis: "Total Cost Basis",
  per_unit_fmv: "Per Unit FMV",
  total_fmv: "Total FMV",
  currency: "Currency"
};
const lockableFields = ["security_name", "symbol", "security_type", "allocation_category", "sector", "exchange", "investment_country", "acquisition_date", "lot_number", "units", "per_unit_cost_basis", "total_cost_basis", "per_unit_fmv", "total_fmv", "currency"];

const navItems: Array<{ view: View; label: string; icon: typeof Table2 }> = [
  { view: "overview", label: "Overview", icon: BarChart3 },
  { view: "assets", label: "Bank/RE/PE", icon: Landmark },
  { view: "portfolio", label: "Portfolio", icon: PieIcon },
  { view: "analytics", label: "Analytics & Insights", icon: Lightbulb },
  { view: "planning", label: "Planning", icon: Target },
  { view: "upload", label: "Upload", icon: FileUp },
  { view: "settings", label: "Settings", icon: Shield }
];

const colors = ["#2563eb", "#16a34a", "#f59e0b", "#dc2626", "#7c3aed", "#0891b2", "#4b5563"];
const supportedCurrencies = ["USD", "INR", "GBP", "EUR"];
const securityTypes = ["Stock", "ETF", "Mutual Fund", "Bond", "Bond Fund", "Cash", "Other"];
const allocationCategories = ["Large Cap", "Mid Cap", "Small Cap", "Hybrid Fund", "Bonds", "International", "Cash", "Unclassified", "Other"];
const sectors = ["Communication Services", "Consumer Discretionary", "Consumer Staples", "Energy", "Financials", "Health Care", "Industrials", "Information Technology", "Materials", "Real Estate", "Utilities", "Diversified", "Unclassified"];

type PositionColumn = "broker" | "account" | "security" | "type" | "allocation" | "sector" | "country" | "exchange" | "snapshot" | "acquired" | "lot" | "units" | "cost_basis" | "fmv" | "currency";
const positionColumns: Array<{ key: PositionColumn; label: string }> = [
  { key: "broker", label: "Broker" }, { key: "account", label: "Account" }, { key: "security", label: "Security" },
  { key: "type", label: "Type" }, { key: "allocation", label: "Allocation" }, { key: "country", label: "Country" },
  { key: "sector", label: "Sector" },
  { key: "exchange", label: "Exchange" }, { key: "snapshot", label: "Snapshot" }, { key: "acquired", label: "Acquired" },
  { key: "lot", label: "Lot" }, { key: "units", label: "Units" }, { key: "cost_basis", label: "Cost Basis" },
  { key: "fmv", label: "FMV" }, { key: "currency", label: "Currency" }
];
const defaultPositionColumns = positionColumns.map((column) => column.key);

function WorkspaceTabs({ tabs, active, onChange }: { tabs: Array<{ id: string; label: string }>; active: string; onChange: (id: string) => void }) {
  return <div className="settingsTabs workspaceTabs" role="tablist">{tabs.map(tab => <button key={tab.id} role="tab" aria-selected={active === tab.id} className={active === tab.id ? "active" : "secondary"} onClick={() => onChange(tab.id)}>{tab.label}</button>)}</div>;
}
const positionColumnsStorageKey = "portfolio-position-columns";

function storedPositionColumns(): PositionColumn[] {
  try {
    const stored = JSON.parse(window.localStorage.getItem(positionColumnsStorageKey) || "null");
    if (Array.isArray(stored)) {
      const valid = stored.filter((key): key is PositionColumn => positionColumns.some((column) => column.key === key));
      if (valid.length || stored.length === 0) return valid;
    }
  } catch {
    // Ignore invalid browser preferences and restore defaults.
  }
  return defaultPositionColumns;
}

function money(value?: number | null, currency = "USD") {
  return new Intl.NumberFormat("en-US", { style: "currency", currency, maximumFractionDigits: 2 }).format(
    value || 0
  );
}

function number(value?: number | null) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 }).format(value || 0);
}

function pct(value?: number | null) {
  if (value === null || value === undefined) return "-";
  return `${value.toFixed(2)}%`;
}

type SortDirection = "asc" | "desc";
type SortState<T> = { key: keyof T | "security"; direction: SortDirection };

function compareValues(a: unknown, b: unknown) {
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a ?? "").localeCompare(String(b ?? ""), undefined, { numeric: true, sensitivity: "base" });
}

function nextSort<T>(current: SortState<T>, key: SortState<T>["key"]): SortState<T> {
  return { key, direction: current.key === key && current.direction === "asc" ? "desc" : "asc" };
}

function yahooFinanceUrl(symbol?: string | null) {
  return symbol ? `https://finance.yahoo.com/quote/${encodeURIComponent(symbol)}` : "";
}

function SymbolLink({ position }: { position: Position }) {
  if (!position.symbol) {
    return <strong>-</strong>;
  }
  return (
    <a className="symbolLink" href={yahooFinanceUrl(position.symbol)} target="_blank" rel="noreferrer">
      {position.symbol}
    </a>
  );
}

export function App() {
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [brokers, setBrokers] = useState<Broker[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [profitLoss, setProfitLoss] = useState<Position[]>([]);
  const [analytics, setAnalytics] = useState<DashboardAnalytics | null>(null);
  const [currency, setCurrency] = useState<CurrencySetting | null>(null);
  const [fxRates, setFxRates] = useState<FxRate[]>([]);
  const [staticAccounts, setStaticAccounts] = useState<StaticAccount[]>([]);
  const [realEstate, setRealEstate] = useState<RealEstateAsset[]>([]);
  const [privateEquity, setPrivateEquity] = useState<PrivateEquityAsset[]>([]);
  const [insights, setInsights] = useState<Insights | null>(null);
  const [goals, setGoals] = useState<GoalsSummary | null>(null);
  const [assumptions, setAssumptions] = useState<FinancialAssumptions | null>(null);
  const [allocationTargets, setAllocationTargets] = useState<AllocationTarget[]>([]);
  const [scenarios, setScenarios] = useState<SavedScenario[]>([]);
  const [view, setView] = useState<View>("overview");
  const [assetSection, setAssetSection] = useState<"banking" | "real-estate" | "private-equity">("banking");
  const [portfolioSection, setPortfolioSection] = useState<"growth" | "allocation" | "profit-loss" | "positions">("positions");
  const [analyticsSection, setAnalyticsSection] = useState<"insights" | "exposure" | "value-metrics" | "risk" | "scenario-lab">("insights");
  const [planningSection, setPlanningSection] = useState<"goals">("goals");
  const [positionFilter, setPositionFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    const stored = window.localStorage.getItem("portfolio-theme");
    return stored === "dark" ? "dark" : "light";
  });
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    if (!mobileMenuOpen) return;
    const dismiss = (event: KeyboardEvent) => { if (event.key === "Escape") setMobileMenuOpen(false); };
    document.body.classList.add("drawerOpen");
    window.addEventListener("keydown", dismiss);
    return () => { document.body.classList.remove("drawerOpen"); window.removeEventListener("keydown", dismiss); };
  }, [mobileMenuOpen]);

  async function loadAuth() {
    setAuth(await api.authStatus());
  }

  async function loadData() {
    const [brokerRows, positionRows, plRows, dashboard, currencySetting, rates, accountRows, realEstateRows, privateEquityRows, goalRows, assumptionRows, targetRows, scenarioRows] = await Promise.all([
      api.brokers(),
      api.positions(),
      api.profitLoss(),
      api.dashboard(),
      api.currency(),
      api.fxRates(),
      api.staticAccounts(),
      api.realEstate(), api.privateEquity(), api.goals(), api.assumptions(), api.allocationTargets(), api.scenarios()
    ]);
    setBrokers(brokerRows);
    setPositions(positionRows);
    setProfitLoss(plRows);
    setAnalytics(dashboard);
    setCurrency(currencySetting);
    setFxRates(rates);
    setStaticAccounts(accountRows);
    setRealEstate(realEstateRows);
    setPrivateEquity(privateEquityRows);
    setGoals(goalRows); setAssumptions(assumptionRows); setAllocationTargets(targetRows);
    setScenarios(scenarioRows);
  }

  useEffect(() => {
    loadAuth().catch((error) => setMessage(error.message));
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("portfolio-theme", theme);
  }, [theme]);

  useEffect(() => {
    if (auth?.unlocked) {
      loadData().catch((error) => setMessage(error.message));
    }
  }, [auth?.unlocked]);

  useEffect(() => {
    if (auth?.unlocked && view === "analytics" && analyticsSection === "insights") {
      api.insights().then(setInsights).catch((error) => setMessage(error.message));
    }
  }, [auth?.unlocked, view, analyticsSection, positions]);

  async function refreshAllPrices() {
    setBusy(true);
    setMessage(null);
    try {
      const result = await api.refreshAll();
      const refreshed = result.filter((item) => item.refreshed).length;
      setMessage(`Refreshed ${refreshed} of ${result.length} securities.`);
      await loadData();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Price refresh failed.");
    } finally {
      setBusy(false);
    }
  }

  async function changeDisplayCurrency(nextCurrency: string) {
    setBusy(true);
    setMessage(null);
    try {
      const next = await api.setCurrency(nextCurrency);
      setCurrency(next);
      await loadData();
      setMessage(`Display currency changed to ${next.display_currency}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Currency update failed.");
    } finally {
      setBusy(false);
    }
  }

  if (!auth) {
    return <div className="boot">Loading portfolio analyser...</div>;
  }

  if (!auth.unlocked) {
    return (
      <AuthGate
        auth={auth}
        onAuthenticated={(next) => {
          setAuth(next);
          setMessage(null);
        }}
      />
    );
  }

  return (
    <div className="appShell">
      <aside className="sidebar">
        <div className="brand">
          <Database size={24} />
          <div>
            <strong>Portfolio</strong>
            <span>Local analyser</span>
          </div>
        </div>
        <nav>
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button className={view === item.view ? "active" : ""} key={item.view} onClick={() => setView(item.view)}>
                <Icon size={18} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
      </aside>

      {mobileMenuOpen && <div className="mobileDrawerBackdrop" onClick={() => setMobileMenuOpen(false)}><aside className="mobileDrawer" onClick={event => event.stopPropagation()} aria-label="Main navigation"><div className="panelHeader"><strong>Navigate</strong><button className="iconOnly" aria-label="Close menu" onClick={() => setMobileMenuOpen(false)}><X size={18}/></button></div>{navItems.map(item => { const Icon = item.icon; return <button className={view === item.view ? "active" : ""} key={item.view} onClick={() => { setView(item.view); setMobileMenuOpen(false); }}><Icon size={18}/>{item.label}</button>; })}</aside></div>}

      <main className="content">
        <header className="topbar">
          <div>
            <p className="eyebrow">Multi-asset net worth</p>
            <h1>{navItems.find((item) => item.view === view)?.label}</h1>
          </div>
          <div className="actions">
            <button className="mobileMenuButton iconOnly" aria-label="Open menu" onClick={() => setMobileMenuOpen(true)}><Menu size={19}/></button>
            {currency && (
              <label className="topbarSelect" title="Display currency">
                <span>Currency</span>
                <select
                  value={currency.display_currency}
                  disabled={busy}
                  onChange={(event) => changeDisplayCurrency(event.target.value)}
                >
                  {currency.supported_currencies.map((item) => (
                    <option key={item}>{item}</option>
                  ))}
                </select>
              </label>
            )}
            <button className="secondary" disabled={busy} onClick={refreshAllPrices}>
              <RefreshCw size={16} />
              Refresh Prices
            </button>
            <button
              className="iconOnly"
              title={theme === "dark" ? "Use light mode" : "Use dark mode"}
              onClick={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
            >
              {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
            </button>
            <button
              className="iconOnly"
              title="Lock portfolio"
              onClick={async () => {
                const next = await api.lock();
                setAuth(next);
              }}
            >
              <Lock size={17} />
            </button>
          </div>
        </header>

        {message && <div className="notice">{message}</div>}

        {view === "overview" && analytics && (
          <Overview
            analytics={analytics}
            positions={positions}
            onAllocationClick={(label) => {
              setPositionFilter(label);
              setView("portfolio");
              setPortfolioSection("positions");
            }}
          />
        )}
        {view === "portfolio" && <WorkspaceTabs tabs={[{id:"positions",label:"Positions"},{id:"profit-loss",label:"Profit/Loss"},{id:"allocation",label:"Allocation"},{id:"growth",label:"Growth"}]} active={portfolioSection} onChange={id => setPortfolioSection(id as typeof portfolioSection)} />}
        {view === "portfolio" && portfolioSection === "profit-loss" && <ProfitLossTable positions={profitLoss} />}
        {view === "portfolio" && portfolioSection === "growth" && analytics && <GrowthView analytics={analytics} />}
        {view === "portfolio" && portfolioSection === "positions" && <PositionsTable positions={positions} brokers={brokers} onRefresh={loadData} externalFilter={positionFilter} onExternalFilterChange={setPositionFilter} />}
        {view === "portfolio" && portfolioSection === "allocation" && analytics && (
          <AllocationView
            analytics={analytics}
            onAllocationClick={(label) => {
              setPositionFilter(label);
              setView("portfolio");
              setPortfolioSection("positions");
            }}
            onClassified={async (text) => {
              setMessage(text);
              await loadData();
            }}
          />
        )}
        {view === "analytics" && <WorkspaceTabs tabs={[{id:"insights",label:"Insights"},{id:"exposure",label:"Exposure"},{id:"value-metrics",label:"Value metrics"},{id:"risk",label:"Risk"},{id:"scenario-lab",label:"Scenario Lab"}]} active={analyticsSection} onChange={id => setAnalyticsSection(id as typeof analyticsSection)} />}
        {view === "analytics" && analyticsSection === "insights" && insights && <InsightsPage insights={insights} />}
        {view === "analytics" && analyticsSection === "exposure" && <ExposurePage positions={positions} insights={insights} />}
        {view === "analytics" && analyticsSection === "value-metrics" && insights && <ValueMetricsPage insights={insights} />}
        {view === "analytics" && analyticsSection === "risk" && currency && <RiskPage positions={positions} currency={currency.display_currency} />}
        {view === "analytics" && analyticsSection === "scenario-lab" && goals && currency && <ScenarioLab scenarios={scenarios} positions={positions} goals={goals} currency={currency} onChanged={loadData} />}
        {view === "planning" && <WorkspaceTabs tabs={[{id:"goals",label:"Goals"}]} active={planningSection} onChange={id => setPlanningSection(id as typeof planningSection)} />}
        {view === "planning" && planningSection === "goals" && goals && currency && <GoalsPage summary={goals} currency={currency} onChanged={loadData} />}
        {view === "assets" && <WorkspaceTabs tabs={[{id:"banking",label:"Banking"},{id:"real-estate",label:"Real Estate"},{id:"private-equity",label:"Private Equity"}]} active={assetSection} onChange={id => setAssetSection(id as typeof assetSection)} />}
        {view === "assets" && assetSection === "banking" && (
          <BankingPage
            accounts={staticAccounts}
            currency={currency}
            onChanged={async (text) => {
              setMessage(text);
              await loadData();
            }}
          />
        )}
        {view === "assets" && assetSection === "real-estate" && (
          <RealEstatePage
            assets={realEstate}
            currency={currency}
            onChanged={async (text) => {
              setMessage(text);
              await loadData();
            }}
          />
        )}
        {view === "assets" && assetSection === "private-equity" && <PrivateEquityPage assets={privateEquity} currency={currency} onChanged={async text=>{setMessage(text);await loadData();}} />}
        {view === "upload" && (
          <UploadPage
            brokers={brokers}
            onImported={async (text) => {
              setMessage(text);
              await loadData();
              setView("portfolio");
              setPortfolioSection("positions");
            }}
          />
        )}
        {view === "settings" && (
          <Settings
            auth={auth}
            positionCount={positions.length}
            currency={currency}
            fxRates={fxRates}
            assumptions={assumptions}
            allocationTargets={allocationTargets}
            brokers={brokers}
            positions={positions}
            onSettingsChanged={loadData}
            onCleaned={async (text) => {
              setMessage(text);
              await loadData();
            }}
          />
        )}
      </main>
    </div>
  );
}

function AuthGate({ auth, onAuthenticated }: { auth: AuthStatus; onAuthenticated: (status: AuthStatus) => void }) {
  const [passphrase, setPassphrase] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const configured = auth.configured;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const next = configured ? await api.unlock(passphrase) : await api.setup(passphrase);
      onAuthenticated(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="authScreen">
      <form className="authPanel" onSubmit={submit}>
        <div className="authIcon">{configured ? <Lock size={28} /> : <Shield size={28} />}</div>
        <h1>{configured ? "Unlock portfolio" : "Create app passphrase"}</h1>
        <p>
          {configured
            ? "Enter the local app passphrase to decrypt sensitive account fields."
            : "Create a passphrase for encrypted local account data. Keep it somewhere safe."}
        </p>
        <input
          autoFocus
          minLength={configured ? 1 : 8}
          type="password"
          value={passphrase}
          onChange={(event) => setPassphrase(event.target.value)}
          placeholder={configured ? "Passphrase" : "Minimum 8 characters"}
        />
        {error && <div className="error">{error}</div>}
        <button disabled={busy || !passphrase}>
          <Unlock size={16} />
          {configured ? "Unlock" : "Set Passphrase"}
        </button>
      </form>
    </div>
  );
}

function Overview({
  analytics,
  positions,
  onAllocationClick
}: {
  analytics: DashboardAnalytics;
  positions: Position[];
  onAllocationClick: (label: string) => void;
}) {
  return (
    <section className="stack">
      <div className="metricGrid">
        <Metric label="Total Net Worth" value={money(analytics.total_net_worth, analytics.display_currency)} />
        <Metric label="Brokerage" value={money(analytics.brokerage_value, analytics.display_currency)} />
        <Metric label="Static Accounts" value={money(analytics.static_accounts_value, analytics.display_currency)} />
        <Metric label="Real Estate" value={money(analytics.real_estate_value, analytics.display_currency)} />
        <Metric label="Cost Basis" value={money(analytics.total_cost_basis, analytics.display_currency)} />
        <Metric
          label="Unrealized P/L"
          value={money(analytics.unrealized_gain_loss, analytics.display_currency)}
          tone={analytics.unrealized_gain_loss >= 0 ? "good" : "bad"}
        />
        <Metric label="Positions" value={positions.length.toString()} />
      </div>
      <div className="chartGrid">
        <ChartPanel title="Net Worth Allocation">
          <AllocationPie data={analytics.net_worth_allocation} currency={analytics.display_currency} />
        </ChartPanel>
        <ChartPanel title="Portfolio Growth">
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={analytics.portfolio_growth}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" />
              <YAxis tickFormatter={(value) => `$${Math.round(value / 1000)}k`} />
              <Tooltip formatter={(value) => money(Number(value), analytics.display_currency)} />
              <Area type="monotone" dataKey="value" stroke="#2563eb" fill="#bfdbfe" />
            </AreaChart>
          </ResponsiveContainer>
        </ChartPanel>
        <ChartPanel title="Asset Allocation">
          <AllocationPie data={analytics.asset_allocation} currency={analytics.display_currency} onSliceClick={onAllocationClick} />
        </ChartPanel>
      </div>
    </section>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: "good" | "bad" }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong className={tone || ""}>{value}</strong>
    </div>
  );
}

function ChartPanel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="panel">
      <h2>{title}</h2>
      {children}
    </section>
  );
}

type PositionDraft = {
  security_name: string;
  symbol: string;
  security_type: string;
  allocation_category: string;
  sector: string;
  exchange: string;
  investment_country: string;
  snapshot_date: string;
  acquisition_date: string;
  lot_number: string;
  units: string;
  per_unit_cost_basis: string;
  total_cost_basis: string;
  per_unit_fmv: string;
  total_fmv: string;
  currency: string;
};

type ManualPositionDraft = PositionDraft & {
  broker_name: string;
  account_number: string;
};

function emptyManualPosition(brokers: Broker[]): ManualPositionDraft {
  return {
    broker_name: brokers[0]?.name || "",
    account_number: "",
    security_name: "",
    symbol: "",
    security_type: "Stock",
    allocation_category: "Unclassified",
    sector: "Unclassified",
    exchange: "Unresolved",
    investment_country: "Unresolved",
    snapshot_date: new Date().toISOString().slice(0, 10),
    acquisition_date: "",
    lot_number: "",
    units: "",
    per_unit_cost_basis: "",
    total_cost_basis: "",
    per_unit_fmv: "",
    total_fmv: "",
    currency: "USD"
  };
}

function draftFromPosition(position: Position): PositionDraft {
  return {
    security_name: position.security_name || "",
    symbol: position.symbol || "",
    security_type: position.security_type || "Other",
    allocation_category: position.allocation_category || "Unclassified",
    sector: position.sector || "Unclassified",
    exchange: position.exchange || "Unresolved",
    investment_country: position.investment_country || "Unresolved",
    snapshot_date: position.snapshot_date || "",
    acquisition_date: position.acquisition_date || "",
    lot_number: position.lot_number || "",
    units: String(position.units ?? 0),
    per_unit_cost_basis: position.per_unit_cost_basis === null || position.per_unit_cost_basis === undefined ? "" : String(position.per_unit_cost_basis),
    total_cost_basis: position.total_cost_basis === null || position.total_cost_basis === undefined ? "" : String(position.total_cost_basis),
    per_unit_fmv: position.per_unit_fmv === null || position.per_unit_fmv === undefined ? "" : String(position.per_unit_fmv),
    total_fmv: position.total_fmv === null || position.total_fmv === undefined ? "" : String(position.total_fmv),
    currency: position.currency || "USD"
  };
}

function optionalText(value: string) {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function optionalNumber(value: string, label: string) {
  if (value.trim() === "") return null;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    throw new Error(`${label} must be a valid number.`);
  }
  return parsed;
}

function payloadFromDraft(draft: PositionDraft): PositionUpdatePayload {
  const units = optionalNumber(draft.units, "Units");
  if (units === null) {
    throw new Error("Units is required.");
  }
  if (!draft.security_name.trim()) {
    throw new Error("Security name is required.");
  }
  if (!draft.security_type.trim()) {
    throw new Error("Security type is required.");
  }
  if (!draft.allocation_category.trim()) {
    throw new Error("Allocation category is required.");
  }
  if (!draft.snapshot_date.trim()) {
    throw new Error("Snapshot date is required.");
  }
  return {
    security_name: draft.security_name.trim(),
    symbol: optionalText(draft.symbol),
    security_type: draft.security_type.trim(),
    allocation_category: draft.allocation_category.trim(),
    sector: draft.sector.trim() || "Unclassified",
    exchange: draft.exchange.trim() || "Unresolved",
    investment_country: draft.investment_country.trim() || "Unresolved",
    snapshot_date: draft.snapshot_date,
    acquisition_date: optionalText(draft.acquisition_date),
    lot_number: optionalText(draft.lot_number),
    units,
    per_unit_cost_basis: optionalNumber(draft.per_unit_cost_basis, "Per unit cost basis"),
    total_cost_basis: optionalNumber(draft.total_cost_basis, "Total cost basis"),
    per_unit_fmv: optionalNumber(draft.per_unit_fmv, "Per unit FMV"),
    total_fmv: optionalNumber(draft.total_fmv, "Total FMV"),
    currency: draft.currency
  };
}

function optionsWithCurrent(options: string[], current: string) {
  return options.includes(current) ? options : [current, ...options].filter(Boolean);
}

function PositionsTable({
  positions,
  brokers,
  onRefresh,
  externalFilter,
  onExternalFilterChange
}: {
  positions: Position[];
  brokers: Broker[];
  onRefresh: () => Promise<void>;
  externalFilter: string;
  onExternalFilterChange: (value: string) => void;
}) {
  const [query, setQuery] = useState(externalFilter);
  const [refreshing, setRefreshing] = useState<number | null>(null);
  const [moneyMode, setMoneyMode] = useState<"total" | "per-unit">("total");
  const [sort, setSort] = useState<SortState<Position>>({ key: "broker_name", direction: "asc" });
  const [editMode, setEditMode] = useState(false);
  const [showAddPosition, setShowAddPosition] = useState(false);
  const [manualDraft, setManualDraft] = useState<ManualPositionDraft>(() => emptyManualPosition(brokers));
  const [addingPosition, setAddingPosition] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<number, PositionDraft>>({});
  const [saving, setSaving] = useState<number | null>(null);
  const [savingAll, setSavingAll] = useState(false);
  const [showExitPrompt, setShowExitPrompt] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [visibleColumns, setVisibleColumns] = useState<PositionColumn[]>(storedPositionColumns);

  useEffect(() => {
    window.localStorage.setItem(positionColumnsStorageKey, JSON.stringify(visibleColumns));
  }, [visibleColumns]);

  const columnVisible = (column: PositionColumn) => visibleColumns.includes(column);

  function toggleColumn(column: PositionColumn) {
    setVisibleColumns((current) => current.includes(column) ? current.filter((key) => key !== column) : [...current, column]);
  }

  useEffect(() => {
    setQuery(externalFilter);
  }, [externalFilter]);

  const filtered = useMemo(() => {
    const needle = query.toLowerCase();
    const rows = positions.filter((position) =>
      [
        position.broker_name,
        position.account_mask,
        position.security_name,
        position.symbol,
        position.security_type,
        position.allocation_category,
        position.exchange,
        position.investment_country
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(needle))
    );
    return [...rows].sort((left, right) => {
      const leftValue = sort.key === "security" ? left.symbol || left.security_name : left[sort.key as keyof Position];
      const rightValue = sort.key === "security" ? right.symbol || right.security_name : right[sort.key as keyof Position];
      const result = compareValues(leftValue, rightValue);
      return sort.direction === "asc" ? result : -result;
    });
  }, [positions, query, sort]);

  async function refresh(position: Position) {
    setRefreshing(position.security_id);
    setEditError(null);
    try {
      const result = await api.refreshSecurity(position.security_id);
      if (!result.refreshed) setEditError(result.message);
      else await onRefresh();
    } catch (error) {
      setEditError(error instanceof Error ? error.message : "Price refresh failed.");
    } finally {
      setRefreshing(null);
    }
  }

  function canRefreshPrice(position: Position) {
    return Boolean(position.symbol?.trim()) && position.security_type.trim().toLowerCase() !== "cash";
  }

  function updateManualDraft(patch: Partial<ManualPositionDraft>) {
    setManualDraft((current) => ({ ...current, ...patch }));
  }

  async function addManualPosition() {
    setAddingPosition(true);
    setAddError(null);
    try {
      if (!manualDraft.broker_name.trim()) throw new Error("Broker is required.");
      const payload: PositionCreatePayload = {
        ...payloadFromDraft(manualDraft),
        broker_name: manualDraft.broker_name,
        account_number: optionalText(manualDraft.account_number)
      };
      await api.createPosition(payload);
      await onRefresh();
      setManualDraft(emptyManualPosition(brokers));
      setShowAddPosition(false);
    } catch (error) {
      setAddError(error instanceof Error ? error.message : "Could not add position.");
    } finally {
      setAddingPosition(false);
    }
  }

  function enterEditMode() {
    setEditError(null);
    setDrafts(Object.fromEntries(positions.map((position) => [position.id, draftFromPosition(position)])));
    setEditMode(true);
  }

  function draftFor(position: Position) {
    return drafts[position.id] || draftFromPosition(position);
  }

  function updateDraft(position: Position, patch: Partial<PositionDraft>) {
    setDrafts((current) => ({
      ...current,
      [position.id]: {
        ...(current[position.id] || draftFromPosition(position)),
        ...patch
      }
    }));
  }

  function changedFields(position: Position) {
    const draft = draftFor(position);
    const original = draftFromPosition(position);
    return (Object.keys(original) as Array<keyof PositionDraft>).filter((key) => draft[key] !== original[key]);
  }

  function inputClass(position: Position, field: keyof PositionDraft) {
    return changedFields(position).includes(field) ? "changedInput" : undefined;
  }

  const changedPositions = positions.filter((position) => changedFields(position).length > 0);

  function requestExitEditMode() {
    setEditError(null);
    if (changedPositions.length === 0) {
      setDrafts({});
      setEditMode(false);
      return;
    }
    setShowExitPrompt(true);
  }

  function discardAllEdits() {
    setShowExitPrompt(false);
    setDrafts({});
    setEditMode(false);
  }

  function cancelEdit(position: Position) {
    setEditError(null);
    setDrafts((current) => ({ ...current, [position.id]: draftFromPosition(position) }));
  }

  async function saveEdit(position: Position) {
    setSaving(position.id);
    setEditError(null);
    try {
      const updated = await api.updatePosition(position.id, payloadFromDraft(draftFor(position)));
      setDrafts((current) => ({ ...current, [position.id]: draftFromPosition(updated) }));
      await onRefresh();
    } catch (error) {
      setEditError(error instanceof Error ? error.message : "Position update failed.");
    } finally {
      setSaving(null);
    }
  }

  async function saveAllEdits() {
    setSavingAll(true);
    setEditError(null);
    try {
      const updates = changedPositions.map((position) => ({
        position,
        payload: payloadFromDraft(draftFor(position))
      }));
      for (const update of updates) {
        await api.updatePosition(update.position.id, update.payload);
      }
      await onRefresh();
      setShowExitPrompt(false);
      setDrafts({});
      setEditMode(false);
    } catch (error) {
      setShowExitPrompt(false);
      setEditError(error instanceof Error ? error.message : "Could not save all position edits.");
    } finally {
      setSavingAll(false);
    }
  }

  return (
    <section className="panel">
      <div className="panelHeader">
        <h2>All Positions</h2>
        <div className="tableTools">
          <details className="columnPicker">
            <summary>Columns ({visibleColumns.length}/{positionColumns.length})</summary>
            <div className="columnPickerMenu">
              {positionColumns.map((column) => <label key={column.key}><input type="checkbox" checked={columnVisible(column.key)} onChange={() => toggleColumn(column.key)} />{column.label}</label>)}
              <div className="columnPickerActions">
                <button className="secondary" onClick={() => setVisibleColumns(defaultPositionColumns)}>Select All</button>
                <button className="secondary" onClick={() => setVisibleColumns(defaultPositionColumns)}>Reset Defaults</button>
              </div>
            </div>
          </details>
          <button className="secondary" disabled={editMode || addingPosition} onClick={() => { setShowAddPosition((current) => !current); setAddError(null); }}>
            {showAddPosition ? <X size={15} /> : <Plus size={15} />}
            {showAddPosition ? "Cancel Add" : "Add Position"}
          </button>
          <button className={editMode ? "" : "secondary"} disabled={savingAll} onClick={editMode ? requestExitEditMode : enterEditMode}>
            {editMode ? <X size={15} /> : <Pencil size={15} />}
            {editMode ? "Exit Edit" : "Edit Mode"}
          </button>
          {editMode && changedPositions.length > 0 && (
            <button disabled={savingAll || saving !== null} onClick={saveAllEdits}>
              <Save size={15} />
              {savingAll ? "Saving..." : `Save All (${changedPositions.length})`}
            </button>
          )}
          <div className="segmented">
            <button className={moneyMode === "total" ? "active" : ""} onClick={() => setMoneyMode("total")}>Total</button>
            <button className={moneyMode === "per-unit" ? "active" : ""} onClick={() => setMoneyMode("per-unit")}>Per Unit</button>
          </div>
          <input
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              onExternalFilterChange(event.target.value);
            }}
            placeholder="Filter broker, symbol, allocation..."
          />
        </div>
      </div>
      {showAddPosition && (
        <div className="manualPositionForm">
          <h3>Add a security position</h3>
          <div className="formGrid">
            <label>Broker<select value={manualDraft.broker_name} onChange={(event) => updateManualDraft({ broker_name: event.target.value })}>{brokers.map((broker) => <option key={broker.id} value={broker.name}>{broker.name}</option>)}</select></label>
            <label>Account number <small>Optional; encrypted at rest</small><input value={manualDraft.account_number} onChange={(event) => updateManualDraft({ account_number: event.target.value })} /></label>
            <label>Symbol<input value={manualDraft.symbol} onChange={(event) => updateManualDraft({ symbol: event.target.value })} /></label>
            <label>Security name<input value={manualDraft.security_name} onChange={(event) => updateManualDraft({ security_name: event.target.value })} /></label>
            <label>Security type<select value={manualDraft.security_type} onChange={(event) => updateManualDraft({ security_type: event.target.value })}>{securityTypes.map((type) => <option key={type}>{type}</option>)}</select></label>
            <label>Allocation<select value={manualDraft.allocation_category} onChange={(event) => updateManualDraft({ allocation_category: event.target.value })}>{allocationCategories.map((category) => <option key={category}>{category}</option>)}</select></label>
            <label>Sector<select value={manualDraft.sector} onChange={(event) => updateManualDraft({ sector: event.target.value })}>{sectors.map((sector) => <option key={sector}>{sector}</option>)}</select></label>
            <label>Units<input type="number" min="0" step="0.0001" value={manualDraft.units} onChange={(event) => updateManualDraft({ units: event.target.value })} /></label>
            <label>Cost per unit<input type="number" min="0" step="0.0001" value={manualDraft.per_unit_cost_basis} onChange={(event) => updateManualDraft({ per_unit_cost_basis: event.target.value, total_cost_basis: "" })} /></label>
            <label>Market value per unit<input type="number" min="0" step="0.0001" value={manualDraft.per_unit_fmv} onChange={(event) => updateManualDraft({ per_unit_fmv: event.target.value, total_fmv: "" })} /></label>
            <label>Currency<select value={manualDraft.currency} onChange={(event) => updateManualDraft({ currency: event.target.value })}>{supportedCurrencies.map((currency) => <option key={currency}>{currency}</option>)}</select></label>
            <label>Snapshot date<input type="date" value={manualDraft.snapshot_date} onChange={(event) => updateManualDraft({ snapshot_date: event.target.value })} /></label>
            <label>Acquisition date<input type="date" value={manualDraft.acquisition_date} onChange={(event) => updateManualDraft({ acquisition_date: event.target.value })} /></label>
            <label>Lot number<input value={manualDraft.lot_number} onChange={(event) => updateManualDraft({ lot_number: event.target.value })} /></label>
            <label>Exchange<input value={manualDraft.exchange} onChange={(event) => updateManualDraft({ exchange: event.target.value })} /></label>
            <label>Investment country<input value={manualDraft.investment_country} onChange={(event) => updateManualDraft({ investment_country: event.target.value })} /></label>
          </div>
          {addError && <p className="inlineError">{addError}</p>}
          <div className="buttonRow left"><button disabled={addingPosition} onClick={addManualPosition}><Save size={15} />{addingPosition ? "Adding..." : "Add position"}</button></div>
        </div>
      )}
      {editError && <p className="inlineError">{editError}</p>}
      <div className="tableWrap desktopDataTable">
        <table>
          <thead>
            <tr>
              {columnVisible("broker") && <SortableTh label="Broker" sortKey="broker_name" sort={sort} onSort={setSort} />}
              {columnVisible("account") && <SortableTh label="Account" sortKey="account_mask" sort={sort} onSort={setSort} />}
              {columnVisible("security") && <SortableTh label="Security" sortKey="security" sort={sort} onSort={setSort} />}
              {columnVisible("type") && <SortableTh label="Type" sortKey="security_type" sort={sort} onSort={setSort} />}
              {columnVisible("allocation") && <SortableTh label="Allocation" sortKey="allocation_category" sort={sort} onSort={setSort} />}
              {columnVisible("sector") && <SortableTh label="Sector" sortKey="sector" sort={sort} onSort={setSort} />}
              {columnVisible("country") && <SortableTh label="Country" sortKey="investment_country" sort={sort} onSort={setSort} />}
              {columnVisible("exchange") && <SortableTh label="Exchange" sortKey="exchange" sort={sort} onSort={setSort} />}
              {columnVisible("snapshot") && <SortableTh label="Snapshot" sortKey="snapshot_date" sort={sort} onSort={setSort} />}
              {columnVisible("acquired") && <SortableTh label="Acquired" sortKey="acquisition_date" sort={sort} onSort={setSort} />}
              {columnVisible("lot") && <SortableTh label="Lot" sortKey="lot_number" sort={sort} onSort={setSort} />}
              {columnVisible("units") && <SortableTh label="Units" sortKey="units" sort={sort} onSort={setSort} numeric />}
              {columnVisible("cost_basis") && (editMode ? (
                <>
                  <SortableTh label="Per Unit Cost Basis" sortKey="per_unit_cost_basis" sort={sort} onSort={setSort} numeric />
                  <SortableTh label="Total Cost Basis" sortKey="total_cost_basis" sort={sort} onSort={setSort} numeric />
                </>
              ) : (
                <SortableTh label={moneyMode === "total" ? "Total Cost Basis" : "Per Unit Cost Basis"} sortKey={moneyMode === "total" ? "total_cost_basis" : "per_unit_cost_basis"} sort={sort} onSort={setSort} numeric />
              ))}
              {columnVisible("fmv") && (editMode ? <><SortableTh label="Per Unit FMV" sortKey="per_unit_fmv" sort={sort} onSort={setSort} numeric /><SortableTh label="Total FMV" sortKey="total_fmv" sort={sort} onSort={setSort} numeric /></> : <SortableTh label={moneyMode === "total" ? "Total FMV" : "Per Unit FMV"} sortKey={moneyMode === "total" ? "total_fmv" : "per_unit_fmv"} sort={sort} onSort={setSort} numeric />)}
              {columnVisible("currency") && <SortableTh label="Currency" sortKey="currency" sort={sort} onSort={setSort} />}
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((position) => {
              const draft = draftFor(position);
              return (
                <tr key={position.id} className={editMode ? "editingRow" : ""}>
                  {columnVisible("broker") && <td>{position.broker_name}</td>}
                  {columnVisible("account") && <td>{position.account_mask}</td>}
                  {columnVisible("security") && <td className="securityCell">
                    {editMode ? (
                      <div className="stackedInputs">
                        <input className={inputClass(position, "symbol")} aria-label="Symbol" value={draft.symbol} onChange={(event) => updateDraft(position, { symbol: event.target.value })} placeholder="Symbol" />
                        <input className={inputClass(position, "security_name")} aria-label="Security name" value={draft.security_name} onChange={(event) => updateDraft(position, { security_name: event.target.value })} placeholder="Security name" />
                      </div>
                    ) : (
                      <>
                        <SymbolLink position={position} />
                        <span>{position.security_name}</span>
                      </>
                    )}
                  </td>}
                  {columnVisible("type") && <td>
                    {editMode ? (
                      <select className={inputClass(position, "security_type")} value={draft.security_type} onChange={(event) => updateDraft(position, { security_type: event.target.value })}>
                        {optionsWithCurrent(securityTypes, draft.security_type).map((type) => (
                          <option key={type} value={type}>{type}</option>
                        ))}
                      </select>
                    ) : position.security_type}
                  </td>}
                  {columnVisible("allocation") && <td>
                    {editMode ? (
                      <select className={inputClass(position, "allocation_category")} value={draft.allocation_category} onChange={(event) => updateDraft(position, { allocation_category: event.target.value })}>
                        {optionsWithCurrent(allocationCategories, draft.allocation_category).map((category) => (
                          <option key={category} value={category}>{category}</option>
                        ))}
                      </select>
                    ) : position.allocation_category}
                  </td>}
                  {columnVisible("sector") && <td>
                    {editMode ? <select className={inputClass(position, "sector")} value={draft.sector} onChange={(event) => updateDraft(position, { sector: event.target.value })}>{optionsWithCurrent(sectors, draft.sector).map(sector => <option key={sector}>{sector}</option>)}</select> : position.sector}
                  </td>}
                  {columnVisible("country") && <td>
                    {editMode ? <input className={inputClass(position, "investment_country")} value={draft.investment_country} onChange={(event) => updateDraft(position, { investment_country: event.target.value })} /> : position.investment_country}
                  </td>}
                  {columnVisible("exchange") && <td>
                    {editMode ? <input className={inputClass(position, "exchange")} value={draft.exchange} onChange={(event) => updateDraft(position, { exchange: event.target.value })} /> : position.exchange}
                  </td>}
                  {columnVisible("snapshot") && <td>
                    {editMode ? (
                      <input className={inputClass(position, "snapshot_date")} type="date" value={draft.snapshot_date} onChange={(event) => updateDraft(position, { snapshot_date: event.target.value })} />
                    ) : position.snapshot_date}
                  </td>}
                  {columnVisible("acquired") && <td>
                    {editMode ? (
                      <input className={inputClass(position, "acquisition_date")} type="date" value={draft.acquisition_date} onChange={(event) => updateDraft(position, { acquisition_date: event.target.value })} />
                    ) : position.acquisition_date || "-"}
                  </td>}
                  {columnVisible("lot") && <td>
                    {editMode ? (
                      <input className={inputClass(position, "lot_number")} value={draft.lot_number} onChange={(event) => updateDraft(position, { lot_number: event.target.value })} />
                    ) : position.lot_number || "-"}
                  </td>}
                  {columnVisible("units") && <td className="num">
                    {editMode ? (
                      <input className={inputClass(position, "units")} type="number" min="0" step="0.0001" value={draft.units} onChange={(event) => updateDraft(position, { units: event.target.value })} />
                    ) : number(position.units)}
                  </td>}
                  {columnVisible("cost_basis") && (editMode ? (
                    <>
                      <td className="num"><input className={inputClass(position, "per_unit_cost_basis")} type="number" step="0.0001" value={draft.per_unit_cost_basis} onChange={(event) => updateDraft(position, { per_unit_cost_basis: event.target.value })} /></td>
                      <td className="num"><input className={inputClass(position, "total_cost_basis")} type="number" step="0.01" value={draft.total_cost_basis} onChange={(event) => updateDraft(position, { total_cost_basis: event.target.value })} /></td>
                    </>
                  ) : (
                    <td className="num">{money(moneyMode === "total" ? position.total_cost_basis : position.per_unit_cost_basis, position.currency)}</td>
                  ))}
                  {columnVisible("fmv") && (editMode ? <><td className="num"><input className={inputClass(position, "per_unit_fmv")} type="number" step="0.0001" value={draft.per_unit_fmv} onChange={(event) => updateDraft(position, { per_unit_fmv: event.target.value })} /></td><td className="num"><input className={inputClass(position, "total_fmv")} type="number" step="0.01" value={draft.total_fmv} onChange={(event) => updateDraft(position, { total_fmv: event.target.value })} /></td></> : <td className="num">{money(moneyMode === "total" ? position.total_fmv : position.per_unit_fmv, position.currency)}</td>)}
                  {columnVisible("currency") && <td>
                    {editMode ? (
                      <select className={inputClass(position, "currency")} value={draft.currency} onChange={(event) => updateDraft(position, { currency: event.target.value })}>
                        {supportedCurrencies.map((currency) => (
                          <option key={currency} value={currency}>{currency}</option>
                        ))}
                      </select>
                    ) : position.currency}
                  </td>}
                  <td>
                    {editMode ? (
                      <div className="rowActions">
                        <button className="iconOnly" title="Save position" disabled={saving === position.id} onClick={() => saveEdit(position)}>
                          <Save size={15} />
                        </button>
                        <button className="iconOnly" title="Cancel row edits" disabled={saving === position.id} onClick={() => cancelEdit(position)}>
                          <X size={15} />
                        </button>
                      </div>
                    ) : (
                      <button className="iconOnly" title={canRefreshPrice(position) ? "Refresh security price" : "No market-price refresh for this security"} disabled={refreshing === position.security_id || !canRefreshPrice(position)} onClick={() => refresh(position)}>
                        <RefreshCw size={15} />
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {!editMode && <div className="mobilePositionCards">{filtered.map(position => <MobilePositionCard key={position.id} position={position} refreshing={refreshing === position.security_id} canRefresh={canRefreshPrice(position)} onRefresh={() => refresh(position)} />)}</div>}
      {showExitPrompt && (
        <div className="modalBackdrop" role="presentation">
          <div className="confirmDialog" role="dialog" aria-modal="true" aria-labelledby="save-edits-title">
            <h3 id="save-edits-title">Save all position edits?</h3>
            <p>{changedPositions.length} position{changedPositions.length === 1 ? " has" : "s have"} unsaved changes.</p>
            <div className="buttonRow">
              <button disabled={savingAll} onClick={saveAllEdits}><Save size={15} />Save all edits</button>
              <button className="dangerButton" disabled={savingAll} onClick={discardAllEdits}>Discard changes</button>
              <button className="secondary" disabled={savingAll} onClick={() => setShowExitPrompt(false)}>Continue editing</button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function SortableTh<T>({
  label,
  sortKey,
  sort,
  onSort,
  numeric
}: {
  label: string;
  sortKey: SortState<T>["key"];
  sort: SortState<T>;
  onSort: (next: SortState<T>) => void;
  numeric?: boolean;
}) {
  const active = sort.key === sortKey;
  return (
    <th className={numeric ? "num" : ""}>
      <button className="sortButton" onClick={() => onSort(nextSort(sort, sortKey))}>
        {label}
        <span>{active ? (sort.direction === "asc" ? "▲" : "▼") : ""}</span>
      </button>
    </th>
  );
}

export function MobilePositionCard({ position, refreshing, canRefresh, onRefresh }: { position: Position; refreshing?: boolean; canRefresh?: boolean; onRefresh?: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const toggle = () => setExpanded(current => !current);
  const onKeyDown = (event: React.KeyboardEvent<HTMLElement>) => {
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); toggle(); }
  };
  const isProfitLoss = !onRefresh;
  return <article className="mobileDataCard" role="button" tabIndex={0} aria-expanded={expanded} aria-label={`${position.symbol || position.security_name} details`} onClick={toggle} onKeyDown={onKeyDown}>
    <div className="mobileCardSummary"><strong onClick={event => event.stopPropagation()}><SymbolLink position={position}/></strong><strong className={isProfitLoss ? ((position.unrealized_gain_loss_native || 0) >= 0 ? "good" : "bad") : ""}>{isProfitLoss ? money(position.unrealized_gain_loss_native, position.currency) : money(position.total_fmv, position.currency)}</strong></div>
    <small>{isProfitLoss ? `${pct(position.unrealized_gain_loss_pct)} · ${position.broker_name}` : `${position.broker_name} · ${position.account_mask} · ${number(position.units)} units`}</small>
    {expanded && <div className="mobileCardDetails"><dl>{isProfitLoss ? <><div><dt>Cost basis</dt><dd>{money(position.total_cost_basis, position.currency)}</dd></div><div><dt>Market value</dt><dd>{money(position.total_fmv, position.currency)}</dd></div><div><dt>Account</dt><dd>{position.account_mask}</dd></div></> : <><div><dt>Cost basis</dt><dd>{money(position.total_cost_basis, position.currency)}</dd></div><div><dt>Allocation</dt><dd>{position.allocation_category}</dd></div><div><dt>Snapshot</dt><dd>{position.snapshot_date}</dd></div></>}<div><dt>Lot</dt><dd>{position.lot_number || "-"}</dd></div></dl>{onRefresh && <button className="secondary" title={canRefresh ? "Refresh security price" : "No market-price refresh for this security"} disabled={refreshing || !canRefresh} onClick={event => { event.stopPropagation(); onRefresh(); }}><RefreshCw size={15}/>Refresh price</button>}</div>}
  </article>;
}

function ProfitLossTable({ positions }: { positions: Position[] }) {
  const [sort, setSort] = useState<SortState<Position>>({ key: "unrealized_gain_loss_native", direction: "desc" });
  const sorted = useMemo(
    () =>
      [...positions].sort((left, right) => {
        const leftValue = sort.key === "security" ? left.symbol || left.security_name : left[sort.key as keyof Position];
        const rightValue = sort.key === "security" ? right.symbol || right.security_name : right[sort.key as keyof Position];
        const result = compareValues(leftValue, rightValue);
        return sort.direction === "asc" ? result : -result;
      }),
    [positions, sort]
  );
  return (
    <section className="panel">
      <h2>Unrealized Profit/Loss</h2>
      <div className="tableWrap desktopDataTable">
        <table>
          <thead>
            <tr>
              <SortableTh label="Security" sortKey="security" sort={sort} onSort={setSort} />
              <SortableTh label="Broker" sortKey="broker_name" sort={sort} onSort={setSort} />
              <SortableTh label="Account" sortKey="account_mask" sort={sort} onSort={setSort} />
              <SortableTh label="Lot" sortKey="lot_number" sort={sort} onSort={setSort} />
              <SortableTh label="Total Cost Basis" sortKey="total_cost_basis" sort={sort} onSort={setSort} numeric />
              <SortableTh label="Total FMV" sortKey="total_fmv" sort={sort} onSort={setSort} numeric />
              <SortableTh label="P/L" sortKey="unrealized_gain_loss_native" sort={sort} onSort={setSort} numeric />
              <SortableTh label="P/L %" sortKey="unrealized_gain_loss_pct" sort={sort} onSort={setSort} numeric />
            </tr>
          </thead>
          <tbody>
            {sorted.map((position) => (
              <tr key={position.id}>
                <td>
                  <SymbolLink position={position} />
                  <span>{position.security_name}</span>
                </td>
                <td>{position.broker_name}</td>
                <td>{position.account_mask}</td>
                <td>{position.lot_number || "-"}</td>
                <td className="num">{money(position.total_cost_basis, position.currency)}</td>
                <td className="num">{money(position.total_fmv, position.currency)}</td>
                <td className={`num ${(position.unrealized_gain_loss_native || 0) >= 0 ? "good" : "bad"}`}>
                  {money(position.unrealized_gain_loss_native, position.currency)}
                </td>
                <td className="num">{pct(position.unrealized_gain_loss_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mobilePositionCards">{sorted.map(position => <MobilePositionCard key={position.id} position={position} />)}</div>
    </section>
  );
}

function GrowthView({ analytics }: { analytics: DashboardAnalytics }) {
  return (
    <section className="panel tall">
      <h2>Portfolio Growth</h2>
      <ResponsiveContainer width="100%" height={420}>
        <AreaChart data={analytics.portfolio_growth}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" />
          <YAxis tickFormatter={(value) => `$${Math.round(value / 1000)}k`} />
          <Tooltip formatter={(value) => money(Number(value), analytics.display_currency)} />
          <Area type="monotone" dataKey="value" stroke="#2563eb" fill="#bfdbfe" />
        </AreaChart>
      </ResponsiveContainer>
    </section>
  );
}

function AllocationView({
  analytics,
  onClassified,
  onAllocationClick
}: {
  analytics: DashboardAnalytics;
  onClassified: (message: string) => Promise<void>;
  onAllocationClick: (label: string) => void;
}) {
  const [busy, setBusy] = useState(false);

  async function refreshClassifications() {
    setBusy(true);
    try {
      const result = await api.classifyAll();
      const refreshed = result.filter((item) => item.refreshed).length;
      await onClassified(`Classified ${refreshed} of ${result.length} securities.`);
    } catch (err) {
      await onClassified(err instanceof Error ? err.message : "Classification refresh failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="stack">
      <div className="panelHeader inlineHeader">
        <div>
          <h2>Allocation Categories</h2>
          <p>Stored classifications group holdings as Large Cap, Mid Cap, Small Cap, Hybrid Fund, Bonds, Cash, or Unclassified.</p>
        </div>
        <button className="secondary" disabled={busy} onClick={refreshClassifications}>
          <RefreshCw size={16} />
          Refresh Classifications
        </button>
      </div>
      <div className="chartGrid">
        <ChartPanel title="Asset Allocation">
          <AllocationPie data={analytics.asset_allocation} currency={analytics.display_currency} onSliceClick={onAllocationClick} />
        </ChartPanel>
        <ChartPanel title="Broker Allocation">
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={analytics.broker_allocation}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="label" />
              <YAxis tickFormatter={(value) => `$${Math.round(value / 1000)}k`} />
              <Tooltip formatter={(value) => money(Number(value), analytics.display_currency)} />
              <Bar dataKey="value" fill="#16a34a" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartPanel>
        <ChartPanel title="Investment Country">
          <AllocationPie data={analytics.country_allocation} currency={analytics.display_currency} onSliceClick={onAllocationClick} />
        </ChartPanel>
        <ChartPanel title="Stock Exchange">
          <AllocationPie data={analytics.exchange_allocation} currency={analytics.display_currency} onSliceClick={onAllocationClick} />
        </ChartPanel>
        <ChartPanel title="Cash vs Invested">
          <AllocationPie data={analytics.cash_vs_invested} currency={analytics.display_currency} />
        </ChartPanel>
      </div>
    </section>
  );
}

function AllocationPie({
  data,
  currency,
  onSliceClick
}: {
  data: Array<{ label: string; value: number }>;
  currency: string;
  onSliceClick?: (label: string) => void;
}) {
  const total = data.reduce((sum, item) => sum + item.value, 0);
  return (
    <ResponsiveContainer width="100%" height={300}>
      <PieChart>
        <Pie
          data={data}
          dataKey="value"
          nameKey="label"
          outerRadius={105}
          label={({ label, value }) => `${label} ${total ? ((Number(value) / total) * 100).toFixed(1) : "0.0"}%`}
          onClick={(entry) => onSliceClick?.(entry.label)}
        >
          {data.map((_, index) => (
            <Cell key={index} fill={colors[index % colors.length]} />
          ))}
        </Pie>
        <Tooltip formatter={(value, name) => [`${money(Number(value), currency)} (${total ? ((Number(value) / total) * 100).toFixed(1) : "0.0"}%)`, name]} />
        <Legend />
      </PieChart>
    </ResponsiveContainer>
  );
}

export function UploadPage({ brokers, onImported }: { brokers: Broker[]; onImported: (message: string) => Promise<void> }) {
  const [brokerId, setBrokerId] = useState<number | null>(null);
  const [statementDate, setStatementDate] = useState("");
  const [statementCurrency, setStatementCurrency] = useState("USD");
  const [filename, setFilename] = useState<string | null>(null);
  const [csvText, setCsvText] = useState("");
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [lockedFields, setLockedFields] = useState<string[]>([]);
  const [previewStale, setPreviewStale] = useState(false);
  const [rowOverrides, setRowOverrides] = useState<Record<number, Record<string, string | null>>>({});
  const [ignoredRowNumbers, setIgnoredRowNumbers] = useState<number[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onFile(file: File | undefined) {
    if (!file) return;
    setFilename(file.name);
    setCsvText(await file.text());
    setPreview(null);
    setPreviewStale(false);
    setRowOverrides({});
    setIgnoredRowNumbers([]);
  }

  async function previewImport() {
    setBusy(true);
    setError(null);
    try {
      const result = await api.previewImport({
        broker_id: brokerId ?? brokers[0]?.id,
        filename,
        csv_text: csvText,
        statement_date: statementDate || undefined,
        statement_currency: statementCurrency,
        locked_fields: lockedFields,
        row_overrides: rowOverrides,
        ignored_row_numbers: ignoredRowNumbers
      });
      setPreview(result);
      setStatementDate(result.statement_date);
      setPreviewStale(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Preview failed.");
    } finally {
      setBusy(false);
    }
  }

  async function commitImport() {
    setBusy(true);
    setError(null);
    try {
      const result = await api.commitImport({
        broker_id: brokerId ?? brokers[0]?.id,
        filename,
        csv_text: csvText,
        statement_date: statementDate || preview?.statement_date,
        statement_currency: statementCurrency,
        locked_fields: lockedFields,
        expected_configuration_version: preview?.configuration_version,
        row_overrides: rowOverrides,
        ignored_row_numbers: ignoredRowNumbers
      });
      await onImported(result.duplicate ? "Duplicate import skipped." : `Imported ${result.imported_rows} rows: ${result.added_rows || 0} added, ${result.modified_rows || 0} updated, ${result.deleted_rows || 0} deleted.`);
      setPreview(null);
      setCsvText("");
      setFilename(null);
      setRowOverrides({});
      setIgnoredRowNumbers([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed.");
    } finally {
      setBusy(false);
    }
  }

  const visibleInvalidRows = preview ? (preview.invalid_rows || []).filter(row => !ignoredRowNumbers.includes(row.row_number)) : [];
  const visibleIgnoredRows = preview ? [
    ...(preview.ignored_rows || []),
    ...(preview.invalid_rows || []).filter(row => ignoredRowNumbers.includes(row.row_number))
  ].filter((row, index, rows) => rows.findIndex(item => item.row_number === row.row_number) === index) : [];

  return (
    <section className="stack">
      <div className="panel">
        <h2>Upload Statement CSV</h2>
        <div className="formGrid">
          <label>
            Broker
            <select value={brokerId ?? brokers[0]?.id ?? ""} onChange={(event) => { const chosen = brokers.find(b => b.id === Number(event.target.value)); setBrokerId(Number(event.target.value)); setStatementCurrency(chosen?.default_currency || "USD"); setLockedFields(chosen?.locked_fields || []); setPreview(null); setPreviewStale(false); setRowOverrides({}); setIgnoredRowNumbers([]); }}>
              {brokers.map((broker) => (
                <option key={broker.id} value={broker.id}>{broker.name}</option>
              ))}
            </select>
          </label>
          <label>
            Statement Date
            <input type="date" value={statementDate} onChange={(event) => { setStatementDate(event.target.value); setPreviewStale(Boolean(preview)); }} />
          </label>
          <label>
            Statement Currency
            <select value={statementCurrency} onChange={(event) => { setStatementCurrency(event.target.value); setPreviewStale(Boolean(preview)); }}>
              <option>USD</option>
              <option>INR</option>
              <option>GBP</option>
              <option>EUR</option>
            </select>
          </label>
          <label>
            CSV File
            <input type="file" accept=".csv,text/csv" onChange={(event) => onFile(event.target.files?.[0])} />
          </label>
        </div>
        {!brokers.length && <div className="notice">Create and validate a broker in Settings → Brokers before importing a statement.</div>}
        {filename && <div className="fileLine">{filename}</div>}
        {error && <div className="error">{error}</div>}
        <div className="buttonRow">
          <button disabled={!csvText || !brokers.length || busy} onClick={previewImport}>
            <FileUp size={16} />
            Preview Import
          </button>
          <button className="secondary" disabled={!preview || previewStale || busy || preview.duplicate || preview.rows.length === 0 || visibleInvalidRows.length > 0 || preview.errors.length > 0} onClick={commitImport}>
            Commit Import
          </button>
        </div>
      </div>

      {preview && (
        <div className="panel">
          <div className="panelHeader">
            <h2>Preview</h2>
            <div className="buttonRow compact">
              {previewStale && <span className="pill warn">Refresh required</span>}
              <span className={preview.duplicate ? "pill warn" : "pill"}>{preview.duplicate ? "Duplicate" : `${preview.rows.length} rows`}</span>
              <button className="secondary" disabled={busy} onClick={previewImport}><RefreshCw size={15} />Refresh Preview</button>
            </div>
          </div>
          {preview.errors.length > 0 && (
            <div className="errorList">
              {preview.errors.map((item) => (
                <div key={item}>{item}</div>
              ))}
            </div>
          )}
          <div className="notice">Column mappings are saved with this broker. Edit them in Settings → Brokers, then refresh this preview.</div>
          {visibleInvalidRows.length > 0 && <div className="stack"><div className="errorList">{visibleInvalidRows.length} row{visibleInvalidRows.length === 1 ? "" : "s"} need attention. Correct the values below or ignore them.</div><div className="tableWrap"><table><thead><tr><th>CSV row</th><th>Issues</th><th>Symbol</th><th>Units</th><th>Cost / Unit</th><th>Total Cost</th><th></th></tr></thead><tbody>{visibleInvalidRows.map(row => <tr key={row.row_number}><td>{row.row_number}</td><td>{Object.entries(row.field_errors).map(([field, issues]) => <div key={field}>{fieldLabels[field] || field}: {issues.join(" ")}</div>)}</td>{["symbol", "units", "per_unit_cost_basis", "total_cost_basis"].map(field => <td key={field}>{(field in row.editable_values || field in row.raw_values) ? <input value={rowOverrides[row.row_number]?.[field] ?? row.editable_values[field] ?? ""} onChange={e => setRowOverrides(current => ({...current, [row.row_number]: {...current[row.row_number], [field]: e.target.value}}))}/> : "—"}</td>)}<td><button className="secondary" onClick={() => { setRowOverrides(current => { const next = {...current}; delete next[row.row_number]; return next; }); setIgnoredRowNumbers(current => current.includes(row.row_number) ? current : [...current, row.row_number]); }}>Ignore row</button></td></tr>)}</tbody></table></div></div>}
          {visibleIgnoredRows.length > 0 && <div className="stack"><h3>Ignored rows</h3><div className="tableWrap"><table><thead><tr><th>CSV row</th><th>Raw values</th><th></th></tr></thead><tbody>{visibleIgnoredRows.map(row => <tr key={row.row_number}><td>{row.row_number}</td><td>{Object.entries(row.raw_values).map(([field, value]) => <div key={field}>{fieldLabels[field] || field}: {value || "—"}</div>)}</td><td><button className="secondary" onClick={() => setIgnoredRowNumbers(current => current.filter(number => number !== row.row_number))}>Restore to repair</button></td></tr>)}</tbody></table></div></div>}
          {((preview.new_rows || []).length > 0 || (preview.modified_rows || []).length > 0 || (preview.deleted_rows || []).length > 0) && <div className="stack"><h3>Import changes</h3>{(preview.new_rows || []).length > 0 && <div className="tableWrap"><h4>New securities</h4><table><tbody>{preview.new_rows.map(row => <tr key={row.row_number}><td>{row.symbol}</td><td>{row.security_name}</td><td>{row.units}</td></tr>)}</tbody></table></div>}{(preview.modified_rows || []).length > 0 && <div className="tableWrap"><h4>Modified securities</h4><table><tbody>{preview.modified_rows.map(row => <tr key={row.row_number}>{row.changed_fields.map(field => <td key={field}><strong>{fieldLabels[field] || field}</strong><br/><s>{String(row.current_values[field] ?? "—")}</s> → <mark>{String(row.proposed_values[field] ?? "—")}</mark></td>)}</tr>)}</tbody></table></div>}{(preview.deleted_rows || []).length > 0 && <div className="tableWrap"><h4>Deleted securities</h4><table><tbody>{preview.deleted_rows.map((row,index) => <tr key={index}><td>{String(row.current_values.symbol || "—")}</td><td>{String(row.current_values.security_name || "—")}</td><td>{String(row.current_values.units || "—")}</td></tr>)}</tbody></table></div>}</div>}
          <div className="lockGrid">
            <strong>Keep existing values for this import</strong>
            <span>Locked fields use the latest matching broker/account/security/lot value while the statement date still advances.</span>
            {lockableFields.map((field) => (
              <label key={field}>
                <input
                  type="checkbox"
                  checked={lockedFields.includes(field)}
                  onChange={(event) => { setLockedFields((current) => event.target.checked ? [...current, field] : current.filter((item) => item !== field)); setPreviewStale(true); }}
                />
                {fieldLabels[field]}
              </label>
            ))}
          </div>
          <div className="tableWrap">
            <table>
              <thead>
                <tr>
                  <th>Account</th>
                  <th>Security</th>
                  <th>Type</th>
                  <th>Allocation</th>
                  <th>Sector</th>
                  <th>Exchange</th>
                  <th>Investment Country</th>
                  <th>Location</th>
                  <th>Acquisition Date</th>
                  <th>Lot</th>
                  <th className="num">Units</th>
                  <th className="num">Cost / Unit</th>
                  <th className="num">Total Cost Basis</th>
                  <th className="num">Market Price / Unit</th>
                  <th className="num">Total FMV</th>
                  <th>Currency</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.slice(0, 25).map((row) => (
                  <tr key={row.row_number}>
                    <td>{row.account_number || "-"}</td>
                    <td>
                      <strong>{row.symbol || "-"}</strong>
                      <span>{row.security_name}</span>
                    </td>
                    <td>{row.security_type}</td>
                    <td>{row.allocation_category}</td>
                    <td>{row.sector}</td>
                    <td>{row.exchange}</td>
                    <td>{row.investment_country}</td>
                    <td>{row.location_status}</td>
                    <td>{row.acquisition_date || "-"}</td>
                    <td>{row.lot_number || "-"}</td>
                    <td className="num">{number(row.units)}</td>
                    <td className="num">{money(row.per_unit_cost_basis, row.currency)}</td>
                    <td className="num">{money(row.total_cost_basis, row.currency)}</td>
                    <td className="num">{money(row.per_unit_fmv, row.currency)}</td>
                    <td className="num">{money(row.total_fmv, row.currency)}</td>
                    <td>{row.currency}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}

const emptyStaticAccount: StaticAccountPayload = {
  category: "Bank Account",
  entity_name: "",
  account_type: "",
  account_holder: "",
  account_number: "",
  currency: "USD",
  amount: 0,
  notes: ""
};

function BankingPage({
  accounts,
  currency,
  onChanged
}: {
  accounts: StaticAccount[];
  currency: CurrencySetting | null;
  onChanged: (message: string) => Promise<void>;
}) {
  const [form, setForm] = useState<StaticAccountPayload>(emptyStaticAccount);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [sort, setSort] = useState<SortState<StaticAccount>>({ key: "entity_name", direction: "asc" });
  const [error, setError] = useState<string | null>(null);
  const supported = currency?.supported_currencies || ["USD", "INR", "GBP", "EUR"];

  const sorted = useMemo(
    () =>
      [...accounts].sort((left, right) => {
        const result = compareValues(left[sort.key as keyof StaticAccount], right[sort.key as keyof StaticAccount]);
        return sort.direction === "asc" ? result : -result;
      }),
    [accounts, sort]
  );

  async function saveAccount(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      if (editingId) {
        await api.updateStaticAccount(editingId, form);
        await onChanged("Account updated.");
      } else {
        await api.createStaticAccount(form);
        await onChanged("Account added.");
      }
      setForm(emptyStaticAccount);
      setEditingId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save account.");
    }
  }

  function editAccount(account: StaticAccount) {
    setEditingId(account.id);
    setForm({
      category: account.category,
      entity_name: account.entity_name,
      account_type: account.account_type,
      account_holder: account.account_holder,
      account_number: "",
      currency: account.currency,
      amount: account.amount,
      notes: account.notes || ""
    });
  }

  async function deleteAccount(id: number) {
    await api.deleteStaticAccount(id);
    await onChanged("Account deleted.");
  }

  return (
    <section className="stack">
      <div className="panel">
        <h2>{editingId ? "Edit Account" : "Add Account"}</h2>
        <form className="assetForm" onSubmit={saveAccount}>
          <label>
            Category
            <select value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value as StaticAccountPayload["category"] })}>
              <option>Bank Account</option>
              <option>Retirement Account</option>
              <option>Other</option>
            </select>
          </label>
          <label>
            Entity
            <input required value={form.entity_name} onChange={(event) => setForm({ ...form, entity_name: event.target.value })} />
          </label>
          <label>
            Account Type
            <input required value={form.account_type} onChange={(event) => setForm({ ...form, account_type: event.target.value })} />
          </label>
          <label>
            Account Holder
            <input required value={form.account_holder} onChange={(event) => setForm({ ...form, account_holder: event.target.value })} />
          </label>
          <label>
            Account Number
            <input value={form.account_number || ""} onChange={(event) => setForm({ ...form, account_number: event.target.value })} />
          </label>
          <label>
            Currency
            <select value={form.currency} onChange={(event) => setForm({ ...form, currency: event.target.value })}>
              {supported.map((item) => (
                <option key={item}>{item}</option>
              ))}
            </select>
          </label>
          <label>
            Amount
            <input required type="number" step="0.01" value={form.amount} onChange={(event) => setForm({ ...form, amount: Number(event.target.value) })} />
          </label>
          <label className="wideField">
            Notes
            <textarea value={form.notes || ""} onChange={(event) => setForm({ ...form, notes: event.target.value })} />
          </label>
          <div className="buttonRow left wideField">
            <button>
              <Save size={16} />
              {editingId ? "Update" : "Add"}
            </button>
            {editingId && (
              <button
                className="secondary"
                type="button"
                onClick={() => {
                  setEditingId(null);
                  setForm(emptyStaticAccount);
                }}
              >
                <X size={16} />
                Cancel
              </button>
            )}
          </div>
        </form>
        {error && <div className="error">{error}</div>}
      </div>
      {(["Bank Account", "Retirement Account", "Other"] as const).map((category) => (
        <StaticAccountTable
          key={category}
          title={`${category}s`}
          accounts={sorted.filter((account) => account.category === category)}
          sort={sort}
          onSort={setSort}
          onEdit={editAccount}
          onDelete={deleteAccount}
        />
      ))}
    </section>
  );
}

function StaticAccountTable({
  title,
  accounts,
  sort,
  onSort,
  onEdit,
  onDelete
}: {
  title: string;
  accounts: StaticAccount[];
  sort: SortState<StaticAccount>;
  onSort: (next: SortState<StaticAccount>) => void;
  onEdit: (account: StaticAccount) => void;
  onDelete: (id: number) => Promise<void>;
}) {
  const total = accounts.reduce((sum, account) => sum + account.amount_display, 0);
  const displayCurrency = accounts[0]?.display_currency || "USD";
  return (
    <section className="panel">
      <div className="panelHeader">
        <h2>{title}</h2>
        <strong>{money(total, displayCurrency)}</strong>
      </div>
      <div className="tableWrap">
        <table>
          <thead>
            <tr>
              <SortableTh label="Entity" sortKey="entity_name" sort={sort} onSort={onSort} />
              <SortableTh label="Type" sortKey="account_type" sort={sort} onSort={onSort} />
              <SortableTh label="Holder" sortKey="account_holder" sort={sort} onSort={onSort} />
              <SortableTh label="Account" sortKey="account_mask" sort={sort} onSort={onSort} />
              <SortableTh label="Currency" sortKey="currency" sort={sort} onSort={onSort} />
              <SortableTh label="Amount" sortKey="amount" sort={sort} onSort={onSort} numeric />
              <th>Notes</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {accounts.map((account) => (
              <tr key={account.id}>
                <td>{account.entity_name}</td>
                <td>{account.account_type}</td>
                <td>{account.account_holder}</td>
                <td>{account.account_mask || "-"}</td>
                <td>{account.currency}</td>
                <td className="num">{money(account.amount, account.currency)}</td>
                <td>{account.notes || "-"}</td>
                <td>
                  <div className="rowActions">
                    <button className="iconOnly" title="Edit" onClick={() => onEdit(account)}>
                      <Pencil size={15} />
                    </button>
                    <button className="iconOnly" title="Delete" onClick={() => onDelete(account.id)}>
                      <Trash2 size={15} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

const emptyRealEstate: RealEstatePayload = {
  property_info: "",
  entity_name: "",
  purchase_date: "",
  purchase_value: 0,
  current_value: 0,
  currency: "USD",
  notes: ""
};

function RealEstatePage({
  assets,
  currency,
  onChanged
}: {
  assets: RealEstateAsset[];
  currency: CurrencySetting | null;
  onChanged: (message: string) => Promise<void>;
}) {
  const [form, setForm] = useState<RealEstatePayload>(emptyRealEstate);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [sort, setSort] = useState<SortState<RealEstateAsset>>({ key: "property_info", direction: "asc" });
  const [error, setError] = useState<string | null>(null);
  const supported = currency?.supported_currencies || ["USD", "INR", "GBP", "EUR"];
  const sorted = useMemo(
    () =>
      [...assets].sort((left, right) => {
        const result = compareValues(left[sort.key as keyof RealEstateAsset], right[sort.key as keyof RealEstateAsset]);
        return sort.direction === "asc" ? result : -result;
      }),
    [assets, sort]
  );
  const total = assets.reduce((sum, asset) => sum + asset.current_value_display, 0);
  const displayCurrency = assets[0]?.display_currency || currency?.display_currency || "USD";

  async function saveAsset(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      if (editingId) {
        await api.updateRealEstate(editingId, form);
        await onChanged("Real estate asset updated.");
      } else {
        await api.createRealEstate(form);
        await onChanged("Real estate asset added.");
      }
      setEditingId(null);
      setForm(emptyRealEstate);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save real estate asset.");
    }
  }

  function editAsset(asset: RealEstateAsset) {
    setEditingId(asset.id);
    setForm({
      property_info: asset.property_info,
      entity_name: asset.entity_name || "",
      purchase_date: asset.purchase_date || "",
      purchase_value: asset.purchase_value,
      current_value: asset.current_value,
      currency: asset.currency,
      notes: asset.notes || ""
    });
  }

  async function deleteAsset(id: number) {
    await api.deleteRealEstate(id);
    await onChanged("Real estate asset deleted.");
  }

  return (
    <section className="stack">
      <div className="panel">
        <h2>{editingId ? "Edit Real Estate" : "Add Real Estate"}</h2>
        <form className="assetForm" onSubmit={saveAsset}>
          <label className="wideField">
            Property Information
            <input required value={form.property_info} onChange={(event) => setForm({ ...form, property_info: event.target.value })} />
          </label>
          <label>
            Entity / Holder
            <input value={form.entity_name || ""} onChange={(event) => setForm({ ...form, entity_name: event.target.value })} />
          </label>
          <label>
            Purchase Date
            <input type="date" value={form.purchase_date || ""} onChange={(event) => setForm({ ...form, purchase_date: event.target.value })} />
          </label>
          <label>
            Purchase Value
            <input required type="number" step="0.01" value={form.purchase_value} onChange={(event) => setForm({ ...form, purchase_value: Number(event.target.value) })} />
          </label>
          <label>
            Current Value
            <input required type="number" step="0.01" value={form.current_value} onChange={(event) => setForm({ ...form, current_value: Number(event.target.value) })} />
          </label>
          <label>
            Currency
            <select value={form.currency} onChange={(event) => setForm({ ...form, currency: event.target.value })}>
              {supported.map((item) => (
                <option key={item}>{item}</option>
              ))}
            </select>
          </label>
          <label className="wideField">
            Notes
            <textarea value={form.notes || ""} onChange={(event) => setForm({ ...form, notes: event.target.value })} />
          </label>
          <div className="buttonRow left wideField">
            <button>
              <Save size={16} />
              {editingId ? "Update" : "Add"}
            </button>
            {editingId && (
              <button className="secondary" type="button" onClick={() => { setEditingId(null); setForm(emptyRealEstate); }}>
                <X size={16} />
                Cancel
              </button>
            )}
          </div>
        </form>
        {error && <div className="error">{error}</div>}
      </div>
      <section className="panel">
        <div className="panelHeader">
          <h2>Properties</h2>
          <strong>{money(total, displayCurrency)}</strong>
        </div>
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <SortableTh label="Property" sortKey="property_info" sort={sort} onSort={setSort} />
                <SortableTh label="Entity" sortKey="entity_name" sort={sort} onSort={setSort} />
                <SortableTh label="Purchase Date" sortKey="purchase_date" sort={sort} onSort={setSort} />
                <SortableTh label="Purchase Value" sortKey="purchase_value" sort={sort} onSort={setSort} numeric />
                <SortableTh label="Current Value" sortKey="current_value" sort={sort} onSort={setSort} numeric />
                <SortableTh label="Currency" sortKey="currency" sort={sort} onSort={setSort} />
                <th>Notes</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((asset) => (
                <tr key={asset.id}>
                  <td>{asset.property_info}</td>
                  <td>{asset.entity_name || "-"}</td>
                  <td>{asset.purchase_date || "-"}</td>
                  <td className="num">{money(asset.purchase_value, asset.currency)}</td>
                  <td className="num">{money(asset.current_value, asset.currency)}</td>
                  <td>{asset.currency}</td>
                  <td>{asset.notes || "-"}</td>
                  <td>
                    <div className="rowActions">
                      <button className="iconOnly" title="Edit" onClick={() => editAsset(asset)}>
                        <Pencil size={15} />
                      </button>
                      <button className="iconOnly" title="Delete" onClick={() => deleteAsset(asset.id)}>
                        <Trash2 size={15} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </section>
  );
}

function PrivateEquityPage({assets,currency,onChanged}:{assets:PrivateEquityAsset[];currency:CurrencySetting|null;onChanged:(message:string)=>Promise<void>}) {
  const blank:PrivateEquityPayload={company_name:"",stage:"Seed",share_class:"Preferred",quantity:0,purchase_price_per_unit:0,investment_date:"",last_valuation_per_unit:0,valuation_date:"",ownership_percent:null,valuation_source:"",currency:currency?.display_currency||"USD",notes:""};
  const [form,setForm]=useState<PrivateEquityPayload>(blank); const [editing,setEditing]=useState<number|null>(null); const [error,setError]=useState<string|null>(null);
  const total=assets.reduce((sum,a)=>sum+a.current_value_display,0); const display=assets[0]?.display_currency||currency?.display_currency||"USD";
  async function save(e:React.FormEvent){e.preventDefault();try{if(editing)await api.updatePrivateEquity(editing,form);else await api.createPrivateEquity(form);await onChanged(editing?"Private equity valuation updated.":"Private equity investment added.");setEditing(null);setForm(blank);}catch(err){setError(err instanceof Error?err.message:"Could not save private equity.");}}
  function edit(a:PrivateEquityAsset){setEditing(a.id);setForm({company_name:a.company_name,stage:a.stage,share_class:a.share_class,quantity:a.quantity,purchase_price_per_unit:a.purchase_price_per_unit,investment_date:a.investment_date||"",last_valuation_per_unit:a.last_valuation_per_unit,valuation_date:a.valuation_date||"",ownership_percent:a.ownership_percent??null,valuation_source:a.valuation_source||"",currency:a.currency,notes:a.notes||""});}
  return <section className="stack"><section className="panel"><p className="eyebrow">No automated pricing or market-risk refresh</p><h2>{editing?"Update private equity":"Add private equity"}</h2><form className="assetForm" onSubmit={save}><label><span>Company</span><input required value={form.company_name} onChange={e=>setForm({...form,company_name:e.target.value})}/></label><label>Stage<select value={form.stage} onChange={e=>setForm({...form,stage:e.target.value})}>{["Pre-seed","Seed","Series A","Series B","Series C+","Growth","Secondary","Other"].map(x=><option key={x}>{x}</option>)}</select></label><label>Share class<select value={form.share_class} onChange={e=>setForm({...form,share_class:e.target.value as "Common"|"Preferred"})}><option>Common</option><option>Preferred</option></select></label><label>Quantity<input required type="number" min="0" step="any" value={form.quantity} onChange={e=>setForm({...form,quantity:Number(e.target.value)})}/></label><label>Purchase price / unit<input required type="number" min="0" step="any" value={form.purchase_price_per_unit} onChange={e=>setForm({...form,purchase_price_per_unit:Number(e.target.value)})}/></label><label>Investment date<input type="date" value={form.investment_date||""} onChange={e=>setForm({...form,investment_date:e.target.value})}/></label><label>Last valuation / unit<input required type="number" min="0" step="any" value={form.last_valuation_per_unit} onChange={e=>setForm({...form,last_valuation_per_unit:Number(e.target.value)})}/></label><label>Valuation date<input type="date" value={form.valuation_date||""} onChange={e=>setForm({...form,valuation_date:e.target.value})}/></label><label>Ownership %<input type="number" min="0" max="100" step="any" value={form.ownership_percent??""} onChange={e=>setForm({...form,ownership_percent:e.target.value===""?null:Number(e.target.value)})}/></label><label>Valuation source<input value={form.valuation_source||""} onChange={e=>setForm({...form,valuation_source:e.target.value})}/></label><label>Currency<select value={form.currency} onChange={e=>setForm({...form,currency:e.target.value})}>{(currency?.supported_currencies||supportedCurrencies).map(x=><option key={x}>{x}</option>)}</select></label><label className="wideField">Notes<textarea value={form.notes||""} onChange={e=>setForm({...form,notes:e.target.value})}/></label><div className="buttonRow left wideField"><button><Save size={16}/>{editing?"Update valuation":"Add"}</button>{editing&&<button type="button" className="secondary" onClick={()=>{setEditing(null);setForm(blank)}}>Cancel</button>}</div></form>{error&&<div className="error">{error}</div>}</section><section className="panel"><div className="panelHeader"><h2>Restricted, non-marketable holdings</h2><strong>{money(total,display)}</strong></div><div className="tableWrap"><table><thead><tr><th>Company</th><th>Stage</th><th>Class</th><th>Current value</th><th>Gain / loss</th><th>Valuation date</th><th>Source</th><th></th></tr></thead><tbody>{assets.map(a=><tr key={a.id}><td>{a.company_name}</td><td>{a.stage}</td><td>{a.share_class}</td><td>{money(a.current_value,a.currency)}</td><td>{money(a.unrealized_gain_loss,a.currency)}</td><td>{a.valuation_date||"-"}</td><td>{a.valuation_source||"-"}</td><td><button className="iconOnly" onClick={()=>edit(a)}><Pencil size={15}/></button><button className="iconOnly" onClick={async()=>{await api.deletePrivateEquity(a.id);await onChanged("Private equity investment deleted.")}}><Trash2 size={15}/></button></td></tr>)}</tbody></table></div></section></section>;
}

export function InsightsPage({ insights }: { insights: Insights }) {
  const c = insights.display_currency;
  return <section className="stack"><ReviewInbox findings={insights.findings} currency={c} /><SnapshotChanges comparison={insights.snapshot_comparison} currency={c} /><AllocationPolicySummary policy={insights.allocation_policy} />
    {insights.projection_setup_required && <div className="notice">Set Expenses & Projections assumptions in Settings to enable deterministic and Monte Carlo forecasts.</div>}
    <section className="panel"><h2>Projection guidance</h2><div className="metricGrid"><MetricCard label="Cash runway" value={insights.cash_runway_months == null ? "Set expenses" : `${insights.cash_runway_months.toFixed(1)} months`} /></div></section>
    {insights.forecast && <section className="panel"><h2>10-year forecast</h2><p>10,000 simulated monthly paths, with constant FX assumptions.</p><div className="metricGrid"><MetricCard label="P10 terminal" value={money(insights.forecast.monte_carlo_terminal.p10,c)} /><MetricCard label="P50 terminal" value={money(insights.forecast.monte_carlo_terminal.p50,c)} /><MetricCard label="P90 terminal" value={money(insights.forecast.monte_carlo_terminal.p90,c)} /></div></section>}
  </section>;
}

export function ExposureInsights({ insights }: { insights: Insights }) {
  const c = insights.display_currency; const [limit, setLimit] = useState<5 | 10>(5); const total = insights.concentration.reduce((sum, row) => sum + row.value, 0);
  return <section className="stack"><div className="metricGrid"><MetricCard label="Top 5 concentration" value={pct(insights.top_5_share)} active={limit === 5} onClick={() => setLimit(5)} /><MetricCard label="Top 10 concentration" value={pct(insights.top_10_share)} active={limit === 10} onClick={() => setLimit(10)} /></div>
    <div className="chartGrid"><ConcentrationPie title="Top 5 concentration" rows={insights.concentration} limit={5} total={total} currency={c} /><ConcentrationPie title="Top 10 concentration" rows={insights.concentration} limit={10} total={total} currency={c} /></div>
    <ConcentrationTable title={`Top ${limit} securities`} rows={insights.concentration.slice(0, limit)} currency={c} total={total} />
    <div className="chartGrid"><InsightTable title="Currency exposure" rows={insights.currency_exposure} currency={c} /><InsightTable title="Country exposure" rows={insights.country_exposure} currency={c} /><InsightTable title="Exchange exposure" rows={insights.exchange_exposure} currency={c} /></div>
  </section>;
}

export function ValueMetricsPage({ insights }: { insights: Insights }) {
  const c = insights.display_currency;
  return <section className="stack"><InsightTable title="Liquidity tiers" rows={insights.liquidity} currency={c} />
    <section className="panel"><h2>Allocation policy and drift</h2><p>Policy ranges are guardrails, not trade instructions. Rebalance amounts remain indicative.</p>{Object.entries(insights.allocation_drift).map(([dimension, rows]) => <div key={dimension}><h3>{dimension.replace("_", " ")}</h3>{rows.length === 0 ? <p className="disclosure">No policy targets configured.</p> : <div className="tableWrap"><table><thead><tr><th>Target</th><th>Actual</th><th>Policy range</th><th>Drift</th><th>Status</th><th>Over / under</th></tr></thead><tbody>{rows.map(r => <tr key={r.label}><td>{r.label}</td><td>{money(r.actual_amount,c)}<br/><small>{pct(r.actual_percent)}</small></td><td>{pct(r.minimum_percent)} – {pct(r.maximum_percent)}<br/><small>Target {pct(r.target_percent)} ± {pct(r.tolerance_percent)}</small></td><td>{pct(r.drift_percent)}</td><td><span className={`pill ${r.compliant ? "" : "warn"}`}>{r.compliant ? "Within range" : `${pct(r.outside_range_percent)} outside`}</span></td><td>{money(r.rebalance_amount,c)}</td></tr>)}</tbody></table></div>}</div>)}</section>
    <section className="panel"><h2>Unrealized tax view</h2><p>Indicative unrealized-gain estimates only; this excludes realized gains and is not tax advice.</p><div className="tableWrap"><table><thead><tr><th>Security</th><th>Holding period</th><th>Gain</th><th>Indicative tax</th></tr></thead><tbody>{insights.tax_lots.map(l => <tr key={l.position_id}><td>{l.security_name}</td><td>{l.classification}{l.holding_days != null ? ` (${l.holding_days}d)` : ""}</td><td>{l.gain == null ? "-" : money(l.gain,c)}</td><td>{l.indicative_tax == null ? "-" : money(l.indicative_tax,c)}</td></tr>)}</tbody></table></div></section>
    <section className="panel"><h2>Value-change proxy</h2><p>Snapshot value changes are cash-flow-sensitive proxies, not investment returns.</p><div className="metricGrid"><MetricCard label="1-month growth" value={pct(insights.rolling_growth["1"])} /><MetricCard label="3-month growth" value={pct(insights.rolling_growth["3"])} /><MetricCard label="12-month growth" value={pct(insights.rolling_growth["12"])} /></div></section><InsightTable title="Holding contribution to value change" rows={insights.holding_value_change} currency={c} />
  </section>;
}

function ReviewInbox({ findings, currency }: { findings: Insights["findings"]; currency: string }) {
  return <section className="panel reviewInbox">
    <div className="panelHeader"><div><p className="eyebrow">Decision coach</p><h2>Portfolio review inbox</h2></div><span className="pill">{findings.length} finding{findings.length === 1 ? "" : "s"}</span></div>
    <p className="sectionIntro">Ranked observations based on the latest stored snapshot. These are review prompts, not trade instructions.</p>
    {findings.length === 0 ? <div className="emptyState">No threshold-based findings. This does not mean the portfolio is risk-free.</div> :
      <div className="findingList">{findings.map(finding => <article className={`findingCard severity-${finding.severity}`} key={finding.id}>
        <div className="findingHeader"><div><span className={`severityBadge ${finding.severity}`}>{finding.severity}</span><span className="categoryLabel">{finding.category.replace(/_/g, " ")}</span><h3>{finding.title}</h3></div><div className="findingImpact">{finding.impact_amount == null ? "" : money(finding.impact_amount, currency)}<small>{finding.impact_label || "Estimated impact"}</small>{finding.impact_percent != null && <small>{finding.impact_percent_label || "Portfolio share"}: {pct(finding.impact_percent)}</small>}</div></div>
        <p>{finding.explanation}</p>
        <div className="findingDetails"><div><strong>Evidence</strong><ul>{finding.evidence.map(item => <li key={item}>{item}</li>)}</ul></div><div><strong>Suggested review</strong><ul>{finding.suggested_actions.map(item => <li key={item}>{item}</li>)}</ul></div></div>
        <small className="confidence">Confidence: {finding.confidence}</small>
      </article>)}</div>}
  </section>;
}

function AllocationPolicySummary({ policy }: { policy: Insights["allocation_policy"] }) {
  if (policy.configured_targets === 0) return <section className="panel"><p className="eyebrow">Allocation policy</p><h2>Policy not configured</h2><p>Set asset-category, country, or currency targets and tolerances in Settings to evaluate portfolio guardrails.</p></section>;
  const largest = policy.largest_breach;
  return <section className="panel"><div className="panelHeader"><div><p className="eyebrow">Allocation policy</p><h2>{policy.breached_targets ? `${policy.breached_targets} policy breach${policy.breached_targets === 1 ? "" : "es"}` : "Within configured policy ranges"}</h2></div><span className={`pill ${policy.breached_targets ? "warn" : ""}`}>{policy.compliant_targets}/{policy.configured_targets} within range</span></div>{largest && <p><strong>Largest variance:</strong> {largest.label} is {pct(largest.outside_range_percent)} outside its {pct(largest.minimum_percent)}–{pct(largest.maximum_percent)} range.</p>}{policy.unconfigured_dimensions.length > 0 && <p className="disclosure">Not configured: {policy.unconfigured_dimensions.map(item => item.replace("_", " ")).join(", ")}.</p>}</section>;
}

function SnapshotChanges({ comparison, currency }: { comparison: Insights["snapshot_comparison"]; currency: string }) {
  if (!comparison.available) return <section className="panel"><p className="eyebrow">What changed?</p><h2>Snapshot comparison</h2><div className="emptyState">Upload a second dated holdings snapshot to compare portfolio changes.</div><p className="disclosure">{comparison.disclosure}</p></section>;
  const changes = [...comparison.coverage_changes, ...comparison.new_holdings, ...comparison.exited_holdings, ...comparison.position_changes, ...comparison.unusual_valuation_changes];
  return <section className="panel snapshotChanges">
    <div className="panelHeader"><div><p className="eyebrow">What changed?</p><h2>{comparison.previous_date} to {comparison.latest_date}</h2></div><span className="pill warn">{comparison.coverage_changes.length ? "Inferences + data coverage" : "Inferred activity"}</span></div>
    <div className="metricGrid snapshotMetrics"><MetricCard label={comparison.coverage_changes.length ? "Recorded value change" : "Portfolio value change"} value={money(comparison.total_value_change, currency)} /><MetricCard label={comparison.coverage_changes.length ? "Relative change incl. coverage" : "Relative change"} value={pct(comparison.total_value_change_percent)} /><MetricCard label={comparison.coverage_changes.length ? "Recorded cash change" : "Cash movement"} value={money(comparison.cash_change, currency)} /><MetricCard label="Holdings flagged" value={String(changes.length)} /></div>
    {comparison.coverage_changes.length > 0 && <div className="notice coverageNotice">Some changes below come from accounts appearing for the first time in stored data. They are not treated as inferred trades.</div>}
    {changes.length > 0 && <div className="tableWrap"><table><thead><tr><th>Holding</th><th>Change</th><th className="num">Units</th><th className="num">Value change</th><th>Interpretation</th></tr></thead><tbody>{changes.map(change => <tr key={`${change.change_type}-${change.security_id}`}><td><strong>{change.symbol || change.security_name}</strong><span>{change.security_name}</span></td><td>{change.change_type.replace(/_/g, " ")}</td><td className="num">{number(change.previous_units)} → {number(change.latest_units)}</td><td className={change.change_type === "coverage_added" ? "num" : change.value_change >= 0 ? "num good" : "num bad"}>{money(change.value_change, currency)}{change.value_change_percent != null && <span>{pct(change.value_change_percent)}</span>}</td><td>{change.activity_label}</td></tr>)}</tbody></table></div>}
    {comparison.allocation_shifts.length > 0 && <div className="allocationShift"><h3>Largest allocation shifts</h3>{comparison.allocation_shifts.slice(0, 6).map(shift => <div key={shift.label}><strong>{shift.label}</strong><span>{pct(shift.previous_percent)} → {pct(shift.latest_percent)}</span><b className={shift.change_percent >= 0 ? "good" : "bad"}>{shift.change_percent >= 0 ? "+" : ""}{pct(shift.change_percent)}</b></div>)}</div>}
    <p className="disclosure">{comparison.disclosure}</p>
  </section>;
}

function MetricCard({ label, value, active = false, onClick }: { label: string; value: string; active?: boolean; onClick?: () => void }) {
  const content = <><span>{label}</span><strong>{value}</strong></>;
  return onClick ? <button className={`metric metricButton${active ? " active" : ""}`} onClick={onClick}>{content}</button> : <div className="metric">{content}</div>;
}
function InsightTable({ title, rows, currency }: { title: string; rows: {label:string;value:number}[]; currency: string }) { return <section className="panel"><h2>{title}</h2><div className="tableWrap"><table><tbody>{rows.map(row => <tr key={row.label}><td>{row.label}</td><td>{money(row.value,currency)}</td></tr>)}</tbody></table></div></section>; }

function useIsPhone() {
  const [isPhone, setIsPhone] = useState(() => window.innerWidth <= 640);
  useEffect(() => { const update = () => setIsPhone(window.innerWidth <= 640); window.addEventListener("resize", update); return () => window.removeEventListener("resize", update); }, []);
  return isPhone;
}

function OnDemandChart({ children }: { children: React.ReactNode }) {
  const isPhone = useIsPhone(); const [shown, setShown] = useState(false);
  if (!isPhone) return <>{children}</>;
  return <div className="onDemandChart"><button className="secondary" aria-expanded={shown} onClick={() => setShown(value => !value)}>{shown ? "Hide chart" : "Show chart"}</button>{shown && children}</div>;
}

function concentrationChartRows(rows: Array<{ label: string; value: number }>, limit: number, total: number) {
  const ranked = rows.slice(0, limit).map((row) => ({ ...row, value: Math.max(0, row.value) }));
  const other = Math.max(0, total - rows.slice(0, limit).reduce((sum, row) => sum + row.value, 0));
  return other > 0 ? [...ranked, { label: "Other", value: other }] : ranked;
}

function ConcentrationPie({ title, rows, limit, total, currency }: { title: string; rows: Array<{ label: string; value: number }>; limit: number; total: number; currency: string }) {
  const data = concentrationChartRows(rows, limit, total);
  return <section className="panel concentrationChart"><h2>{title}</h2><OnDemandChart><ResponsiveContainer width="100%" height={300}><PieChart><Pie data={data} dataKey="value" nameKey="label" outerRadius={100} label={({ name, value }) => `${name} ${total ? pct(Number(value) / total * 100) : "0.00%"}`}>{data.map((row, index) => <Cell key={row.label} fill={colors[index % colors.length]} />)}</Pie><Tooltip formatter={(value) => money(Number(value), currency)} /><Legend /></PieChart></ResponsiveContainer></OnDemandChart></section>;
}

function ConcentrationTable({ title, rows, currency, total }: { title: string; rows: Array<{ label: string; value: number }>; currency: string; total: number }) {
  return <section className="panel"><h2>{title}</h2><div className="tableWrap"><table><thead><tr><th>Security</th><th className="num">Amount</th><th className="num">Portfolio</th></tr></thead><tbody>{rows.map((row) => <tr key={row.label}><td>{row.label}</td><td className="num">{money(row.value, currency)}</td><td className="num">{pct(total ? row.value / total * 100 : 0)}</td></tr>)}</tbody></table></div></section>;
}

export function ScenarioLab({ scenarios, positions, goals, currency, onChanged }: { scenarios: SavedScenario[]; positions: Position[]; goals: GoalsSummary; currency: CurrencySetting; onChanged: () => Promise<void> }) {
  const blank = (): ScenarioInput => ({name:"Untitled scenario",description:"",contribution:0,withdrawal:0,cash_reserve_change:0,position_changes:[],goal_allocation_changes:{}});
  const [mode,setMode]=useState<"scenario"|"stress">("scenario");
  const [form,setForm]=useState<ScenarioInput>(blank()); const [editing,setEditing]=useState<number|null>(null); const [analysis,setAnalysis]=useState<ScenarioAnalysis|null>(null);
  const [analysisStale,setAnalysisStale]=useState(false); const [stressStale,setStressStale]=useState(false);
  const [selectedSecurity,setSelectedSecurity]=useState(""); const [error,setError]=useState<string|null>(null); const [busy,setBusy]=useState(false);
  const securities=useMemo(()=>Array.from(new Map(positions.filter(p=>p.security_type.toLowerCase()!=="cash").map(p=>[`${p.security_id}|${p.currency}`,{id:p.security_id,name:p.security_name,symbol:p.symbol,currency:p.currency,sector:p.sector,category:p.allocation_category}])).values()),[positions]);
  const stressSecurities=useMemo(()=>Array.from(new Map(securities.map(s=>[s.id,s])).values()),[securities]);
  const stressCategories=useMemo(()=>Array.from(new Set(positions.map(p=>p.allocation_category))).sort(),[positions]);
  const stressSectors=useMemo(()=>Array.from(new Set(positions.map(p=>p.sector).filter(s=>s&&s!=="Unclassified"))).sort(),[positions]);
  const scenarioPayload=(saved:SavedScenario):ScenarioInput=>({name:saved.name,description:saved.description,contribution:saved.contribution,withdrawal:saved.withdrawal,cash_reserve_change:saved.cash_reserve_change,position_changes:saved.position_changes,goal_allocation_changes:saved.goal_allocation_changes});
  function addSecurity(){const [rawId,selectedCurrency]=selectedSecurity.split("|");const id=Number(rawId); if(!id||form.position_changes.some(c=>c.security_id===id&&c.currency===selectedCurrency))return; setForm({...form,position_changes:[...form.position_changes,{security_id:id,currency:selectedCurrency,value_change:0}]});}
  async function analyze(){setBusy(true);setError(null);try{setAnalysis(await api.analyzeScenario(form));setAnalysisStale(false);}catch(e){setError(e instanceof Error?e.message:"Scenario analysis failed.");}finally{setBusy(false);}}
  async function save(){setBusy(true);setError(null);try{editing?await api.updateScenario(editing,form):await api.saveScenario(form);await onChanged();setEditing(null);}catch(e){setError(e instanceof Error?e.message:"Could not save scenario.");}finally{setBusy(false);}}
  const [stress,setStress]=useState<StressTestInput>({preset:"market_crash",market_shock_percent:0,interest_rate_change_bps:0,currency_shocks:{},category_shocks:{},sector_shocks:{},security_shocks:{}});
  const [stressResult,setStressResult]=useState<StressTestResult|null>(null);
  useEffect(()=>{if(analysis)setAnalysisStale(true);},[form]);
  useEffect(()=>{if(stressResult)setStressStale(true);},[stress]);
  async function runStress(){setBusy(true);setError(null);try{setStressResult(await api.runStressTest(stress));setStressStale(false);}catch(e){setError(e instanceof Error?e.message:"Stress test failed.");}finally{setBusy(false);}}
  return <section className="stack">
    <div className="segmented labTabs"><button className={mode==="scenario"?"active":""} onClick={()=>setMode("scenario")}>Scenario Lab</button><button className={mode==="stress"?"active":""} onClick={()=>setMode("stress")}>Stress Testing</button></div>
    {error&&<div className="error">{error}</div>}
    {mode==="scenario"?<>
      <section className="panel"><div className="panelHeader"><div><p className="eyebrow">Non-destructive model</p><h2>Proposed portfolio</h2></div><div className="buttonRow compact"><button className="secondary" onClick={()=>{setForm(blank());setEditing(null);setAnalysis(null);}}>New</button><button className="secondary" disabled={busy} onClick={analyze}>Compare</button><button disabled={busy} onClick={save}><Save size={16}/>Save scenario</button></div></div>
        <p className="fieldHelpIntro">All values below are amounts in {currency.display_currency}, not percentages. This model does not change stored positions.</p>
        <div className="formGrid"><label>Name<input value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/><small className="fieldHelp">A label used to save and compare this scenario.</small></label><label>Contribution / deposit<input type="number" value={form.contribution} onChange={e=>setForm({...form,contribution:Number(e.target.value)})}/><small className="fieldHelp">External cash added to the portfolio in {currency.display_currency}.</small></label><label>Withdrawal / distribution<input type="number" value={form.withdrawal} onChange={e=>setForm({...form,withdrawal:Number(e.target.value)})}/><small className="fieldHelp">Cash removed from the portfolio in {currency.display_currency}; available cash must cover it.</small></label><label>Additional cash-reserve change<input type="number" value={form.cash_reserve_change} onChange={e=>setForm({...form,cash_reserve_change:Number(e.target.value)})}/><small className="fieldHelp">A signed cash adjustment in {currency.display_currency}: positive adds cash, negative removes it.</small></label><label className="wideField">Description<textarea value={form.description||""} onChange={e=>setForm({...form,description:e.target.value})}/><small className="fieldHelp">Optional notes about the purpose or assumptions of this scenario.</small></label></div>
        <div className="panelHeader subHeader"><div><h3>Security value changes</h3><p>Positive values buy; negative values sell. Amounts use {currency.display_currency}; cash is adjusted automatically.</p></div><div className="addChange"><select value={selectedSecurity} onChange={e=>setSelectedSecurity(e.target.value)}><option value="">Choose holding</option>{securities.map(s=><option key={`${s.id}|${s.currency}`} value={`${s.id}|${s.currency}`}>{s.symbol||s.name} — {s.name} ({s.currency})</option>)}</select><button className="secondary" onClick={addSecurity}><Plus size={15}/>Add</button></div></div>
        <div className="changeGrid">{form.position_changes.map(change=><div className="changeRow" key={`${change.security_id}|${change.currency||""}`}><strong>{securities.find(s=>s.id===change.security_id&&(!change.currency||s.currency===change.currency))?.name||change.security_id} ({change.currency||"select currency"})</strong><input aria-label="Value change" type="number" value={change.value_change} onChange={e=>setForm({...form,position_changes:form.position_changes.map(c=>c.security_id===change.security_id&&c.currency===change.currency?{...c,value_change:Number(e.target.value)}:c)})}/><button className="iconOnly" onClick={()=>setForm({...form,position_changes:form.position_changes.filter(c=>!(c.security_id===change.security_id&&c.currency===change.currency))})}><X size={15}/></button></div>)}</div>
        {goals.goals.length>0&&<><h3>Goal allocation changes</h3><p className="fieldHelpIntro">Signed amounts in {currency.display_currency} assigned to each goal for comparison only; these do not move holdings.</p><div className="changeGrid">{goals.goals.map(goal=><label key={goal.id}>{goal.name}<input type="number" value={form.goal_allocation_changes[goal.id]||0} onChange={e=>setForm({...form,goal_allocation_changes:{...form.goal_allocation_changes,[goal.id]:Number(e.target.value)}})}/></label>)}</div></>}
      </section>
      {analysisStale&&<div className="notice">Scenario inputs changed. Run Compare again to refresh these results.</div>}{analysis&&<ScenarioComparison result={analysis}/>} 
      <section className="panel"><h2>Saved scenarios</h2>{scenarios.length===0?<div className="emptyState">No saved scenarios yet.</div>:<div className="savedScenarioGrid">{scenarios.map(saved=><article key={saved.id}><div><strong>{saved.name}</strong><span>{saved.description||"No description"}</span></div><div className="buttonRow compact"><button className="secondary" onClick={()=>{setForm(scenarioPayload(saved));setEditing(saved.id);setAnalysis(null);}}>Load</button><button className="iconOnly" onClick={async()=>{if(confirm(`Delete ${saved.name}?`)){await api.deleteScenario(saved.id);await onChanged();}}}><Trash2 size={15}/></button></div></article>)}</div>}</section>
    </>:<>
      <section className="panel"><div className="panelHeader"><div><p className="eyebrow">Instantaneous shocks</p><h2>Portfolio stress test</h2></div><button disabled={busy} onClick={runStress}><FlaskConical size={16}/>Run stress test</button></div>
        <div className="formGrid"><label>Preset<select value={stress.preset||""} onChange={e=>setStress({...stress,preset:e.target.value||null})}><option value="">Custom only</option><option value="market_crash">Market crash</option><option value="2008_style">2008-style</option><option value="2020_style">2020-style</option><option value="rate_shock">Rate shock</option></select></label><label>Additional market shock %<input type="number" min="-100" max="100" value={stress.market_shock_percent} onChange={e=>setStress({...stress,market_shock_percent:Number(e.target.value)})}/></label><label>Interest-rate change (bps)<input type="number" value={stress.interest_rate_change_bps} onChange={e=>setStress({...stress,interest_rate_change_bps:Number(e.target.value)})}/></label></div>
        <ShockEditor title="Currency moves" rows={currency.supported_currencies} values={stress.currency_shocks} onChange={values=>setStress({...stress,currency_shocks:values})}/><ShockEditor title="Allocation-category shocks" rows={stressCategories} values={stress.category_shocks} onChange={values=>setStress({...stress,category_shocks:values})}/><ShockEditor title="Sector shocks" rows={stressSectors} values={stress.sector_shocks} onChange={values=>setStress({...stress,sector_shocks:values})}/><ShockEditor title="Security shocks" rows={stressSecurities.map(s=>String(s.id))} labels={Object.fromEntries(stressSecurities.map(s=>[String(s.id),s.symbol||s.name]))} values={Object.fromEntries(Object.entries(stress.security_shocks).map(([k,v])=>[String(k),v]))} onChange={values=>setStress({...stress,security_shocks:Object.fromEntries(Object.entries(values).map(([k,v])=>[Number(k),v]))})}/>
      </section>{stressStale&&<div className="notice">Stress inputs changed. Run the stress test again to refresh these results.</div>}{stressResult&&<StressResults result={stressResult}/>}</>}
  </section>;
}

function ShockEditor({title,rows,labels={},values,onChange}:{title:string;rows:string[];labels?:Record<string,string>;values:Record<string,number>;onChange:(values:Record<string,number>)=>void}){
  if(!rows.length)return null;
  return <div className="shockEditor"><h3>{title}</h3><div>{rows.map(row=><label key={row}>{labels[row]||row}<input type="number" min="-100" max="100" value={values[row]||0} onChange={e=>{const value=Number(e.target.value);const next={...values};if(value)next[row]=value;else delete next[row];onChange(next);}}/><small>% change</small></label>)}</div></div>;
}

function ScenarioComparison({result}:{result:ScenarioAnalysis}){const c=result.display_currency;return <section className="stack"><div className="comparisonGrid"><MetricCard label="Current value" value={money(result.current.portfolio_value,c)}/><MetricCard label="Proposed value" value={money(result.proposed.portfolio_value,c)}/><MetricCard label="Current cash runway" value={result.current.cash_runway_months==null?"Set expenses":`${result.current.cash_runway_months.toFixed(1)} months`}/><MetricCard label="Proposed cash runway" value={result.proposed.cash_runway_months==null?"Set expenses":`${result.proposed.cash_runway_months.toFixed(1)} months`}/><MetricCard label={`Largest: ${result.current.largest_holding||"-"}`} value={pct(result.current.largest_holding_percent)}/><MetricCard label={`Largest: ${result.proposed.largest_holding||"-"}`} value={pct(result.proposed.largest_holding_percent)}/><MetricCard label="Allocation drift: current" value={pct(result.current.total_absolute_drift_percent)}/><MetricCard label="Allocation drift: proposed" value={pct(result.proposed.total_absolute_drift_percent)}/></div><section className="panel"><h2>Tax and goals</h2><p>Estimated realized gain: {money(result.estimated_realized_gain,c)} · Estimated tax: {result.estimated_tax==null?"Set tax assumptions":money(result.estimated_tax,c)}</p>{result.goals.length>0&&<div className="tableWrap"><table><thead><tr><th>Goal</th><th>Current allocation</th><th>Proposed allocation</th><th>Current probability</th><th>Proposed probability</th></tr></thead><tbody>{result.goals.map(g=><tr key={g.goal_id}><td>{g.name}</td><td>{money(g.current_allocated,c)}</td><td>{money(g.proposed_allocated,c)}</td><td>{pct(g.current_probability)}</td><td>{pct(g.proposed_probability)}</td></tr>)}</tbody></table></div>}<ul className="assumptionList">{result.warnings.map(w=><li key={w}>{w}</li>)}</ul></section></section>}

function StressResults({result}:{result:StressTestResult}){const c=result.display_currency;return <section className="stack"><div className="comparisonGrid"><MetricCard label="Current value" value={money(result.current_value,c)}/><MetricCard label="Stressed value" value={money(result.stressed_value,c)}/><MetricCard label="Projected change" value={money(result.projected_loss,c)}/><MetricCard label="Projected change %" value={pct(result.projected_loss_percent)}/><MetricCard label="Cash runway" value={result.cash_runway_months==null?"Set expenses":`${result.cash_runway_months.toFixed(1)} months`}/></div><section className="panel"><h2>Largest contributors</h2><div className="tableWrap"><table><thead><tr><th>Holding</th><th>Currency</th><th>Current value</th><th>Shock</th><th>Projected change</th></tr></thead><tbody>{result.contributors.slice(0,10).map(row=><tr key={`${row.security_id}|${row.currency}`}><td>{row.security_name}</td><td>{row.currency}</td><td>{money(row.current_value,c)}</td><td>{pct(row.shock_percent)}</td><td className={row.projected_change<0?"bad":"good"}>{money(row.projected_change,c)}</td></tr>)}</tbody></table></div></section>{result.goals.length>0&&<section className="panel"><h2>Affected goals</h2><div className="tableWrap"><table><thead><tr><th>Goal</th><th>Current allocation</th><th>Stressed allocation</th><th>Current probability</th><th>Stressed probability</th></tr></thead><tbody>{result.goals.map(g=><tr key={g.goal_id}><td>{g.name}</td><td>{money(g.current_allocated,c)}</td><td>{money(g.stressed_allocated,c)}</td><td>{pct(g.current_probability)}</td><td>{pct(g.stressed_probability)}</td></tr>)}</tbody></table></div></section>}<section className="panel"><h2>Assumptions and limitations</h2><ul className="assumptionList">{result.assumptions.map(a=><li key={a}>{a}</li>)}</ul></section></section>}

function GoalsPage({ summary, currency, onChanged }: { summary: GoalsSummary; currency: CurrencySetting; onChanged: () => Promise<void> }) {
  const blank = (): GoalPayload => ({name:"",description:"",target_amount:0,target_currency:currency.display_currency,target_month:"",allocated_amount:0,allocated_currency:currency.display_currency,monthly_contribution:0,contribution_currency:currency.display_currency,priority:null});
  const [form, setForm] = useState<GoalPayload | null>(null); const [editing, setEditing] = useState<number | null>(null); const [error,setError]=useState<string|null>(null);
  const edit = (goal?: GoalsSummary["goals"][number]) => { setEditing(goal?.id ?? null); setForm(goal ? {name:goal.name,description:goal.description,target_amount:goal.target_amount,target_currency:goal.target_currency,target_month:goal.target_month,allocated_amount:goal.allocated_amount,allocated_currency:goal.allocated_currency,monthly_contribution:goal.monthly_contribution,contribution_currency:goal.contribution_currency,priority:goal.priority} : blank()); };
  async function save() { if (!form) return; try { setError(null); editing ? await api.updateGoal(editing,form) : await api.createGoal(form); setForm(null); await onChanged(); } catch(e) {setError(e instanceof Error?e.message:"Could not save goal.");} }
  return <section className="stack"><div className="metricGrid"><MetricCard label="Investable financial assets" value={money(summary.investable_financial_assets,summary.display_currency)} /><MetricCard label="Allocated to goals" value={money(summary.total_allocated,summary.display_currency)} /><MetricCard label="Unallocated remainder" value={money(summary.unallocated_remainder,summary.display_currency)} /></div>{summary.over_allocated && <div className="error">Goal allocations exceed investable financial assets. This is a warning only; allocations are not blocked.</div>}<div className="panelHeader"><h2>Goals</h2><button onClick={() => edit()}><Target size={16}/> Add goal</button></div>
  {form && <section className="panel"><h2>{editing ? "Edit goal" : "New goal"}</h2><div className="formGrid"><label>Name<input value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/></label><label>Target month<input type="month" value={form.target_month} onChange={e=>setForm({...form,target_month:e.target.value})}/></label><label>Target amount<input type="number" value={form.target_amount} onChange={e=>setForm({...form,target_amount:Number(e.target.value)})}/></label><label>Target currency<CurrencyInput value={form.target_currency} onChange={v=>setForm({...form,target_currency:v})} currencies={currency.supported_currencies}/></label><label>Manual allocation<input type="number" value={form.allocated_amount} onChange={e=>setForm({...form,allocated_amount:Number(e.target.value)})}/></label><label>Allocation currency<CurrencyInput value={form.allocated_currency} onChange={v=>setForm({...form,allocated_currency:v})} currencies={currency.supported_currencies}/></label><label>Monthly contribution<input type="number" value={form.monthly_contribution} onChange={e=>setForm({...form,monthly_contribution:Number(e.target.value)})}/></label><label>Contribution currency<CurrencyInput value={form.contribution_currency} onChange={v=>setForm({...form,contribution_currency:v})} currencies={currency.supported_currencies}/></label><label>Priority<input type="number" value={form.priority ?? ""} onChange={e=>setForm({...form,priority:e.target.value ? Number(e.target.value) : null})}/></label><label>Description<input value={form.description ?? ""} onChange={e=>setForm({...form,description:e.target.value})}/></label></div><div className="buttonRow left"><button onClick={save}>Save goal</button><button className="secondary" onClick={()=>setForm(null)}>Cancel</button></div>{error&&<div className="error">{error}</div>}</section>}
  <section className="panel"><div className="tableWrap"><table><thead><tr><th>Goal</th><th>Progress</th><th>Target</th><th>Projected value</th><th>Shortfall / surplus</th><th>Required monthly</th><th>Reach probability</th><th></th></tr></thead><tbody>{summary.goals.map(g=><tr key={g.id}><td><strong>{g.name}</strong><br/><small>{g.target_month}</small></td><td>{pct(g.funding_progress)}</td><td>{money(g.target_amount_display,g.display_currency)}</td><td>{g.projected_value == null ? "Set assumptions" : money(g.projected_value,g.display_currency)}</td><td>{g.projected_shortfall_surplus == null ? "-" : money(g.projected_shortfall_surplus,g.display_currency)}</td><td>{g.required_monthly_contribution == null ? "-" : money(g.required_monthly_contribution,g.display_currency)}</td><td>{g.probability_of_reaching == null ? "-" : pct(g.probability_of_reaching)}</td><td><button className="iconOnly" onClick={()=>edit(g)}><Pencil size={15}/></button><button className="iconOnly" onClick={async()=>{if(confirm(`Delete ${g.name}?`)){await api.deleteGoal(g.id); await onChanged();}}}><Trash2 size={15}/></button></td></tr>)}</tbody></table></div></section></section>;
}
function CurrencyInput({value,onChange,currencies}:{value:string;onChange:(v:string)=>void;currencies:string[]}) { return <select value={value} onChange={e=>onChange(e.target.value)}>{currencies.map(c=><option key={c}>{c}</option>)}</select>; }

function Settings({
  auth,
  positionCount,
  currency,
  fxRates,
  assumptions,
  allocationTargets,
  brokers,
  positions,
  onSettingsChanged,
  onCleaned
}: {
  auth: AuthStatus;
  positionCount: number;
  currency: CurrencySetting | null;
  fxRates: FxRate[];
  assumptions: FinancialAssumptions | null;
  allocationTargets: AllocationTarget[];
  brokers: Broker[];
  positions: Position[];
  onSettingsChanged: () => Promise<void>;
  onCleaned: (text: string) => Promise<void>;
}) {
  const [settingsPage, setSettingsPage] = useState<"general" | "brokers" | "fx" | "projections" | "fees">("general");
  return (
    <section className="stack">
      <WorkspaceTabs tabs={[{id:"general",label:"General"},{id:"brokers",label:"Brokers"},{id:"fx",label:"FX"},{id:"projections",label:"Expenses & Projections"},{id:"fees",label:"Fees"}]} active={settingsPage} onChange={id => setSettingsPage(id as typeof settingsPage)} />
      {settingsPage === "brokers" && <BrokerSettings brokers={brokers} onChanged={onSettingsChanged} />}
      {settingsPage === "fx" && <FxSettings currency={currency} fxRates={fxRates} onChanged={onSettingsChanged} />}
      {settingsPage === "projections" && <ProjectionSettings assumptions={assumptions} targets={allocationTargets} onChanged={onSettingsChanged} />}
      {settingsPage === "fees" && currency && <FeesPage positions={positions} currency={currency.display_currency} />}
      {settingsPage === "general" && <>
      <div className="panel settings">
        <h2>Local Privacy</h2>
        <div className="settingsGrid">
          <div>
            <strong>Encryption</strong>
            <span>{auth.configured ? "Configured" : "Not configured"}</span>
          </div>
          <div>
            <strong>Unlock State</strong>
            <span>{auth.unlocked ? "Unlocked" : "Locked"}</span>
          </div>
          <div>
            <strong>Stored Positions</strong>
            <span>{positionCount}</span>
          </div>
          <div>
            <strong>Raw Upload Retention</strong>
            <span>Disabled</span>
          </div>
        </div>
      </div>
      <DatabaseTools onCleaned={onCleaned} />
      </>}
    </section>
  );
}

const emptyBrokerDraft = (): BrokerDraft => ({ name: "", default_currency: "USD", notes: "", locked_fields: [], header_signature: [], mappings: {} });

export function BrokerSettings({ brokers, onChanged }: { brokers: Broker[]; onChanged: () => Promise<void> }) {
  const [draft, setDraft] = useState<BrokerDraft | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [sampleCsv, setSampleCsv] = useState("");
  const [preview, setPreview] = useState<BrokerConfigPreview | null>(null);
  const [detectedHeaders, setDetectedHeaders] = useState<string[]>([]);
  const [jsonMode, setJsonMode] = useState(false);
  const [jsonText, setJsonText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function begin(broker?: Broker) {
    const next = broker ? { name: broker.name, default_currency: broker.default_currency || "USD", notes: broker.notes || "", locked_fields: broker.locked_fields || [], header_signature: broker.header_signature || [], mappings: broker.mappings || {} } : emptyBrokerDraft();
    setDraft(next); setEditingId(broker?.id || null); setSampleCsv(""); setPreview(null); setDetectedHeaders([]); setError(null); setJsonMode(false); setJsonText(JSON.stringify(next, null, 2));
  }
  function applyJson() { try { const next = JSON.parse(jsonText) as BrokerDraft; if (!next.name || !Array.isArray(next.header_signature) || !next.mappings) throw new Error("JSON must contain a broker name, header_signature, and mappings."); setDraft({ ...next, locked_fields: next.locked_fields || [] }); setPreview(null); setError(null); } catch (e) { setError(e instanceof Error ? `Invalid configuration JSON: ${e.message}` : "Invalid configuration JSON."); } }
  async function loadSample(file?: File) { if (!file) return; setSampleCsv(await file.text()); setPreview(null); setDetectedHeaders([]); }
  async function runPreview() { if (!draft || !sampleCsv) return; setBusy(true); setError(null); try { const result = await api.previewBroker({ draft, csv_text: sampleCsv, statement_currency: draft.default_currency }); setPreview(result); setDetectedHeaders(result.detected_headers); const next = { ...draft, header_signature: result.header_signature, mappings: result.mappings }; setDraft(next); setJsonText(JSON.stringify(next, null, 2)); } catch (e) { setError(e instanceof Error ? e.message : "Could not preview this broker configuration."); } finally { setBusy(false); } }
  async function save() { if (!draft || (!editingId && (!preview?.valid || !sampleCsv))) return; setBusy(true); setError(null); try { const payload = { draft, sample_csv: sampleCsv || undefined, statement_currency: draft.default_currency }; if (editingId) await api.updateBroker(editingId, payload); else await api.createBroker(payload); setDraft(null); await onChanged(); } catch (e) { setError(e instanceof Error ? e.message : "Could not save broker."); } finally { setBusy(false); } }
  async function remove(broker: Broker) { if (!confirm(`Delete ${broker.name}? This removes its broker-owned accounts and import history when permitted.`)) return; setBusy(true); setError(null); try { await api.deleteBroker(broker.id); await onChanged(); } catch (e) { setError(e instanceof Error ? e.message : "Could not delete broker."); } finally { setBusy(false); } }

  if (!draft) return <section className="stack"><section className="panel"><div className="panelHeader"><div><h2>Brokers</h2><p>Saved CSV layouts are used for every import. Configure and validate layouts here.</p></div><button onClick={() => begin()}><Plus size={16}/> Add broker</button></div>{error && <div className="error">{error}</div>}<div className="tableWrap"><table><thead><tr><th>Name</th><th>Default currency</th><th>Mapped fields</th><th>Version</th><th></th></tr></thead><tbody>{brokers.map(broker => <tr key={broker.id}><td><strong>{broker.name}</strong>{broker.notes && <><br/><small>{broker.notes}</small></>}</td><td>{broker.default_currency || "USD"}</td><td>{Object.keys(broker.mappings || {}).length} {broker.mappings?.symbol && broker.mappings?.units ? "ready" : "incomplete"}</td><td>{broker.configuration_version || 1}</td><td><button className="iconOnly" title="Edit broker" onClick={() => begin(broker)}><Pencil size={15}/></button><button className="iconOnly" title="Delete broker" disabled={busy} onClick={() => remove(broker)}><Trash2 size={15}/></button></td></tr>)}</tbody></table></div></section></section>;

  const headers = detectedHeaders.length ? detectedHeaders : draft.header_signature;
  return <section className="stack"><section className="panel"><div className="panelHeader"><div><h2>{editingId ? "Edit broker" : "New broker"}</h2><p>Save only after validating this configuration against a sample CSV.</p></div><button className="secondary" disabled={busy} onClick={() => setDraft(null)}>Cancel</button></div>
    <div className="formGrid"><label>Name<input value={draft.name} onChange={e => { setDraft({ ...draft, name: e.target.value }); setPreview(null); }} /></label><label>Default currency<select value={draft.default_currency} onChange={e => { setDraft({ ...draft, default_currency: e.target.value }); setPreview(null); }}><option>USD</option><option>INR</option><option>GBP</option><option>EUR</option></select></label><label>Notes<input value={draft.notes || ""} onChange={e => setDraft({ ...draft, notes: e.target.value })} /></label><label>Sample CSV<input type="file" accept=".csv,text/csv" onChange={e => loadSample(e.target.files?.[0])}/></label></div>
    <label>Sample CSV text<textarea value={sampleCsv} onChange={e => { setSampleCsv(e.target.value); setPreview(null); setDetectedHeaders([]); }} placeholder="Paste a representative CSV export" /></label>
    <div className="lockGrid"><strong>Default locked fields</strong><span>Imports inherit these locks; users can override them for one import.</span>{lockableFields.map(field => <label key={field}><input type="checkbox" checked={draft.locked_fields.includes(field)} onChange={e => setDraft({ ...draft, locked_fields: e.target.checked ? [...draft.locked_fields, field] : draft.locked_fields.filter(item => item !== field) })}/>{fieldLabels[field]}</label>)}</div>
    <div className="buttonRow left"><button className={jsonMode ? "secondary" : ""} onClick={() => { setJsonMode(false); setJsonText(JSON.stringify(draft, null, 2)); }}>Visual editor</button><button className={jsonMode ? "" : "secondary"} onClick={() => { setJsonMode(true); setJsonText(JSON.stringify(draft, null, 2)); }}>Advanced JSON</button></div>
    {jsonMode ? <><label>Broker configuration JSON<textarea className="jsonEditor" value={jsonText} onChange={e => setJsonText(e.target.value)} /></label><div className="buttonRow left"><button className="secondary" onClick={applyJson}>Apply JSON</button></div></> : <div className="stack"><div className="formGrid"><label>Header signature (comma-separated)<input value={draft.header_signature.join(", ")} onChange={e => { setDraft({...draft, header_signature: e.target.value.split(",").map(x => x.trim()).filter(Boolean)}); setPreview(null); }}/></label></div><div className="mappingGrid">{Object.entries(fieldLabels).map(([field, label]) => <label key={field}>{label}<select value={draft.mappings[field] || ""} onChange={e => { const mappings = e.target.value ? {...draft.mappings, [field]: e.target.value} : Object.fromEntries(Object.entries(draft.mappings).filter(([key]) => key !== field)); setDraft({...draft, mappings}); setPreview(null); }}><option value="">Not mapped</option>{headers.map(header => <option key={header}>{header}</option>)}</select></label>)}</div></div>}
    <div className="buttonRow left"><button disabled={!sampleCsv || busy} onClick={runPreview}><RefreshCw size={16}/> Preview configuration</button><button className="secondary" disabled={busy || (!editingId && !preview?.valid)} onClick={save}><Save size={16}/> Save broker</button></div>{error && <div className="error">{error}</div>}{preview && <div className={preview.valid ? "notice" : "errorList"}>{preview.valid ? `${preview.rows.length} normalized security rows are valid.` : preview.errors.map(item => <div key={item}>{item}</div>)}</div>}</section></section>;
}

function ProjectionSettings({ assumptions, targets, onChanged }: { assumptions: FinancialAssumptions | null; targets: AllocationTarget[]; onChanged: () => Promise<void> }) {
  const [form, setForm] = useState<FinancialAssumptions>(assumptions || {});
  const [error, setError] = useState<string | null>(null);
  useEffect(() => setForm(assumptions || {}), [assumptions]);
  async function save() { try { setError(null); await api.saveAssumptions(form); await onChanged(); } catch (e) { setError(e instanceof Error ? e.message : "Could not save assumptions."); } }
  const fields: Array<[keyof FinancialAssumptions, string, string]> = [
    ["monthly_expenses", "Monthly household expenses", "amount"], ["monthly_household_contribution", "Monthly investment contribution", "amount"],
    ["expected_annual_return", "Expected annual return", "percent"], ["annual_volatility", "Annual volatility", "percent"], ["inflation_rate", "Inflation", "percent"],
    ["short_term_tax_rate", "Short-term indicative tax", "percent"], ["long_term_tax_rate", "Long-term indicative tax", "percent"], ["long_term_holding_days", "Long-term holding days", "days"]
  ];
  return <section className="panel"><h2>Expenses & Projections</h2><p>Forecasts become available after return, volatility, inflation, and monthly contribution are completed. Values are assumptions, not advice.</p>
    <div className="formGrid">{fields.map(([key, label, kind]) => <label key={key}>{label}<input type="number" min="0" step="0.01" value={form[key] == null ? "" : kind === "percent" ? Number((Number(form[key]) * 100).toPrecision(12)) : form[key]} onChange={e => setForm({...form, [key]: e.target.value === "" ? null : (kind === "percent" ? Number(e.target.value) / 100 : Number(e.target.value))})} />{kind === "percent" && <small>Enter percentage, e.g. 7 for 7%</small>}</label>)}</div>
    <div className="buttonRow left"><button onClick={save}><Save size={16}/> Save assumptions</button></div>{error && <div className="error">{error}</div>}
    <AllocationTargetSettings targets={targets} onChanged={onChanged} />
  </section>;
}

function AllocationTargetSettings({ targets, onChanged }: { targets: AllocationTarget[]; onChanged: () => Promise<void> }) {
  const [dimension, setDimension] = useState("asset_category");
  const [rows, setRows] = useState<AllocationTarget[]>([]); const [error, setError] = useState<string | null>(null);
  useEffect(() => setRows(targets.filter(t => t.dimension === dimension)), [targets, dimension]);
  async function save() { try { setError(null); await api.saveAllocationTargets(dimension, rows.map(r => ({...r, dimension}))); await onChanged(); } catch (e) { setError(e instanceof Error ? e.message : "Targets must total 100%."); } }
  return <div className="stack"><div className="panelHeader"><h3>Allocation policy</h3><select value={dimension} onChange={e => setDimension(e.target.value)}><option value="asset_category">Asset category</option><option value="country">Country</option><option value="currency">Currency</option></select></div><p>Each target set totals 100%. The allowed range is target ± tolerance; policy guardrails do not create trade orders.</p>
  {rows.map((row, i) => <div className="formGrid" key={`${row.label}-${i}`}><label>Label<input value={row.label} onChange={e => setRows(rows.map((r, n) => n === i ? {...r, label:e.target.value} : r))}/></label><label>Target %<input type="number" min="0" max="100" value={row.target_percent} onChange={e => setRows(rows.map((r,n) => n === i ? {...r,target_percent:Number(e.target.value)} : r))}/></label><label>Tolerance (± points)<input type="number" min="0" max="100" value={row.tolerance_percent} onChange={e => setRows(rows.map((r,n) => n === i ? {...r,tolerance_percent:Number(e.target.value)} : r))}/></label><button className="secondary" onClick={() => setRows(rows.filter((_,n) => n !== i))}>Remove</button></div>)}
  <div className="buttonRow left"><button className="secondary" onClick={() => setRows([...rows, {dimension,label:"",target_percent:0,tolerance_percent:10}])}>Add target</button><button onClick={save}>Save policy</button></div>{error && <div className="error">{error}</div>}</div>;
}

function FxSettings({
  currency,
  fxRates,
  onChanged
}: {
  currency: CurrencySetting | null;
  fxRates: FxRate[];
  onChanged: () => Promise<void>;
}) {
  const [fromCurrency, setFromCurrency] = useState("USD");
  const [toCurrency, setToCurrency] = useState("INR");
  const [rate, setRate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const supported = currency?.supported_currencies || ["USD", "INR", "GBP", "EUR"];
  const sortedRates = useMemo(
    () => [...fxRates].sort((left, right) => `${left.from_currency}${left.to_currency}`.localeCompare(`${right.from_currency}${right.to_currency}`)),
    [fxRates]
  );

  async function refreshRates() {
    setBusy(true);
    setError(null);
    try {
      await api.refreshFxRates();
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "FX refresh failed.");
    } finally {
      setBusy(false);
    }
  }

  async function saveRate() {
    setBusy(true);
    setError(null);
    try {
      await api.setFxRate({ from_currency: fromCurrency, to_currency: toCurrency, rate: Number(rate) });
      setRate("");
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save FX rate.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <div className="panelHeader">
        <h2>Currency & FX</h2>
        <button className="secondary" disabled={busy} onClick={refreshRates}>
          <RefreshCw size={16} />
          Refresh FX Rates
        </button>
      </div>
      <div className="formGrid currencyGrid">
        <label>
          Display Currency
          <select
            value={currency?.display_currency || "USD"}
            onChange={async (event) => {
              await api.setCurrency(event.target.value);
              await onChanged();
            }}
          >
            {supported.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </label>
        <label>
          From
          <select value={fromCurrency} onChange={(event) => setFromCurrency(event.target.value)}>
            {supported.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </label>
        <label>
          To
          <select value={toCurrency} onChange={(event) => setToCurrency(event.target.value)}>
            {supported.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </label>
        <label>
          Manual Rate
          <input type="number" min="0" step="0.000001" value={rate} onChange={(event) => setRate(event.target.value)} placeholder="Example: 83.25" />
        </label>
      </div>
      <div className="buttonRow left">
        <button className="secondary" disabled={busy || !rate || Number(rate) <= 0} onClick={saveRate}>
          Save Manual FX Rate
        </button>
      </div>
      {error && <div className="error">{error}</div>}
      <div className="rateGrid">
        {sortedRates.map((item) => (
          <div key={`${item.from_currency}-${item.to_currency}`}>
            <strong>
              {item.from_currency} → {item.to_currency}
            </strong>
            <span>{item.rate.toFixed(6)}</span>
            <small>{item.source}</small>
          </div>
        ))}
      </div>
    </section>
  );
}

function DatabaseTools({ onCleaned }: { onCleaned: (message: string) => Promise<void> }) {
  const [confirmations, setConfirmations] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const options: Array<{
    scope: "brokerage" | "static" | "real-estate" | "private-equity" | "all";
    title: string;
    description: string;
    phrase: string;
  }> = [
    {
      scope: "brokerage",
      title: "Clear Brokerage Data",
      description: "Deletes imported statements, brokerage accounts, securities, positions, and price history.",
      phrase: "BROKERAGE"
    },
    {
      scope: "static",
      title: "Clear Static Banking Data",
      description: "Deletes Bank Accounts, Retirement Accounts, and Other static account records.",
      phrase: "BANKING"
    },
    {
      scope: "real-estate",
      title: "Clear Real Estate Data",
      description: "Deletes all tracked property records.",
      phrase: "REAL ESTATE"
    },
    {
      scope: "private-equity",
      title: "Clear Private Equity",
      description: "Delete private equity investments and their last-known valuations.",
      phrase: "CLEAR PRIVATE EQUITY"
    },
    {
      scope: "all",
      title: "Clear All Data",
      description: "Deletes brokerage, static banking, real estate, and private equity data. Settings, FX rates, and encryption setup remain.",
      phrase: "ALL DATA"
    }
  ];

  async function cleanDatabase(scope: "brokerage" | "static" | "real-estate" | "private-equity" | "all") {
    setBusy(true);
    setError(null);
    try {
      const result = await api.cleanDatabaseScope(scope);
      setConfirmations({});
      await onCleaned(result.message);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Database clean failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel dangerPanel">
      <h2>Clean Database</h2>
      <p>
        Delete selected data sets. Broker definitions, encryption settings, display currency, and FX rates remain available.
      </p>
      <div className="cleanGrid">
        {options.map((option) => {
          const value = confirmations[option.scope] || "";
          const canClean = value.trim().toUpperCase() === option.phrase;
          return (
            <div className="cleanOption" key={option.scope}>
              <strong>{option.title}</strong>
              <span>{option.description}</span>
              <input
                value={value}
                onChange={(event) => setConfirmations((current) => ({ ...current, [option.scope]: event.target.value }))}
                placeholder={`Type ${option.phrase} to confirm`}
              />
              <button className="dangerButton" disabled={!canClean || busy} onClick={() => cleanDatabase(option.scope)}>
                {option.title}
              </button>
            </div>
          );
        })}
      </div>
      {error && <div className="error">{error}</div>}
    </section>
  );
}

function ExposureTable({title,rows,currency}:{title:string;rows:ExposureAnalysis["company"];currency:string}) {
  return <section className="panel"><h2>{title}</h2><div className="tableWrap"><table><thead><tr><th>Exposure</th><th>Value</th><th>Share</th><th>Confidence</th><th>Sources</th></tr></thead><tbody>{rows.slice(0,15).map(row=><tr key={row.key}><td>{row.label}</td><td>{money(row.value,currency)}</td><td>{pct(row.percent)}</td><td>{row.confidence}</td><td>{row.sources.join(", ")}</td></tr>)}</tbody></table></div></section>;
}

export function ExposurePage({positions, insights}:{positions:Position[]; insights?: Insights | null}) {
  const funds=useMemo(()=>Array.from(new Map(positions.filter(p=>/fund|etf/i.test(p.security_type)).map(p=>[p.security_id,p])).values()),[positions]);
  const [analysis,setAnalysis]=useState<ExposureAnalysis|null>(null); const [selected,setSelected]=useState<number|null>(null);
  const [draft,setDraft]=useState<FundCompositionInput>({source:"manual",as_of_date:new Date().toISOString().slice(0,10),constituents:[]});
  const [preview,setPreview]=useState<PublicMetadataPreview|null>(null); const [metadata,setMetadata]=useState<FundMetadata|null>(null); const [peers,setPeers]=useState<PeerResearch|null>(null); const [csv,setCsv]=useState(""); const [htmlSource,setHtmlSource]=useState<"yahoo_html"|"google_finance_html"|"custom_url">("yahoo_html"); const [customUrl,setCustomUrl]=useState(""); const [busy,setBusy]=useState(false); const [error,setError]=useState<string|null>(null);
  async function load(){setAnalysis(await api.lookThrough());}
  useEffect(()=>{load().catch(e=>setError(e.message));},[positions]);
  function choose(id:number|null){setSelected(id);setPreview(null);setMetadata(null);setPeers(null);if(id&&typeof api.fundMetadata==="function")api.fundMetadata(id).then(setMetadata).catch(()=>{});const current=id==null?null:analysis?.compositions.find(c=>c.security_id===id);setDraft(current?{source:current.source,as_of_date:current.as_of_date,constituents:current.constituents}:{source:"manual",as_of_date:new Date().toISOString().slice(0,10),constituents:[]});}
  function updateRow(index:number,patch:Partial<FundConstituent>){setDraft({...draft,constituents:draft.constituents.map((row,i)=>i===index?{...row,...patch}:row)});}
  function importCsv(){try{const lines=csv.trim().split(/\r?\n/).filter(Boolean);if(lines.length<2)throw new Error("CSV needs a header and at least one row.");const header=lines[0].split(",").map(x=>x.trim().toLowerCase());const value=(cells:string[],key:string)=>cells[header.indexOf(key)]?.trim()||"";const rows=lines.slice(1).map(line=>{const cells=line.split(",");const name=value(cells,"name");const symbol=value(cells,"symbol");const weight=Number(value(cells,"weight_percent"));if(!name||!Number.isFinite(weight)||weight<=0)throw new Error("Each CSV row needs name and positive weight_percent.");return {constituent_key:value(cells,"constituent_key")||symbol||name.toLowerCase(),symbol:symbol||null,name,weight_percent:weight,sector:value(cells,"sector")||"Unclassified",country:value(cells,"country")||"Unresolved",currency:(value(cells,"currency")||"Unresolved").toUpperCase(),asset_category:value(cells,"asset_category")||"Unclassified"};});setDraft({...draft,source:"manual",constituents:rows});setError(null);}catch(e){setError(e instanceof Error?e.message:"Could not parse CSV.");}}
  async function save(){if(selected==null)return;setBusy(true);setError(null);try{await api.saveFundComposition(selected,{...draft,source:"manual"});await load();}catch(e){setError(e instanceof Error?e.message:"Could not save composition.");}finally{setBusy(false);}}
  async function publicDraft(){if(selected==null)return;setBusy(true);setError(null);try{setPreview(await api.previewPublicMetadata(selected,{source:htmlSource,url:htmlSource==="custom_url"?customUrl||undefined:undefined}));}catch(e){setError(e instanceof Error?e.message:"Public HTML sync unavailable.");}finally{setBusy(false);}}
  async function accept(){if(selected==null)return;setBusy(true);try{const accepted=await api.acceptPublicComposition(selected);setMetadata(accepted.metadata);setPreview(null);await load();}catch(e){setError(e instanceof Error?e.message:"Could not accept public composition.");}finally{setBusy(false);}}
  async function research(){if(selected==null)return;setBusy(true);setError(null);try{setPeers(await api.researchPeers(selected));}catch(e){setError(e instanceof Error?e.message:"Peer research unavailable.");}finally{setBusy(false);}}
  if(!analysis)return <section className="panel"><h2>Look-through exposure</h2><p>{error||"Loading exposure analysis…"}</p></section>;
  return <section className="stack">{insights && <ExposureInsights insights={insights} />}<section className="stack"><div className="metricGrid"><MetricCard label="Portfolio value" value={money(analysis.portfolio_value,analysis.display_currency)}/><MetricCard label="Fund composition coverage" value={pct(analysis.composition_coverage_percent)}/><MetricCard label="Fund pairs with overlap" value={String(analysis.overlaps.length)}/></div>
    <section className="panel"><div className="panelHeader"><div><p className="eyebrow">Manual data is authoritative</p><h2>Fund composition editor</h2></div></div><div className="formGrid"><label>Fund<select value={selected??""} onChange={e=>choose(e.target.value?Number(e.target.value):null)}><option value="">Select a fund</option>{funds.map(f=><option key={f.security_id} value={f.security_id}>{f.security_name} ({f.symbol||"no symbol"})</option>)}</select></label><label>As-of date<input type="date" value={draft.as_of_date||""} onChange={e=>setDraft({...draft,as_of_date:e.target.value})}/></label></div>
      {selected!=null&&<><div className="formGrid"><label>HTML source<select value={htmlSource} onChange={e=>setHtmlSource(e.target.value as typeof htmlSource)}><option value="yahoo_html">Yahoo Finance page</option><option value="google_finance_html">Google Finance page</option><option value="custom_url">Custom public URL</option></select></label>{htmlSource==="custom_url"&&<label>Public fund/issuer URL<input type="url" value={customUrl} placeholder="https://..." onChange={e=>setCustomUrl(e.target.value)}/></label>}</div><div className="buttonRow left"><button disabled={busy} onClick={()=>setDraft({...draft,constituents:[...draft.constituents,{constituent_key:`new-${draft.constituents.length+1}`,name:"",symbol:null,weight_percent:1,sector:"Unclassified",country:"Unresolved",currency:"Unresolved",asset_category:"Unclassified"}]})}><Plus size={15}/>Add row</button><button className="secondary" disabled={busy||(htmlSource==="custom_url"&&!customUrl)} onClick={publicDraft}><RefreshCw size={15}/>Sync public HTML draft</button><button disabled={busy} onClick={save}><Save size={15}/>Save manual data</button>{preview&&<button onClick={accept}>Accept reviewed public draft</button>}</div>
      {preview&&<div className="notice">{preview.message} Source: {preview.source_url||preview.provider}. Expense ratio draft: {preview.expense_ratio_percent==null?"not available":pct(preview.expense_ratio_percent)}. Review: {preview.holdings_count} top holdings are ready to accept; your manual editor remains unchanged.{preview.warnings.length>0&&<ul>{preview.warnings.map(w=><li key={w}>{w}</li>)}</ul>}</div>}
      <section className="panel"><div className="panelHeader"><div><h3>Fund research</h3><p>Stored provider facts and top-10 public holdings. Public data is best effort.</p></div><button className="secondary" disabled={busy} onClick={research}>Find comparable funds</button></div>{metadata?<div className="metricGrid"><MetricCard label="Category" value={metadata.category||"-"}/><MetricCard label="Expense ratio" value={metadata.expense_ratio_percent==null?"-":pct(metadata.expense_ratio_percent)}/><MetricCard label="5-year CAGR" value={metadata.return_5y_percent==null?"-":pct(metadata.return_5y_percent)}/><MetricCard label="Freshness" value={metadata.fetched_at?.slice(0,10)||"-"}/></div>:<p>Accept a reviewed public draft to store fund facts.</p>}{peers&&<><p className="notice">{peers.note}</p><div className="tableWrap"><table><thead><tr><th>Rank</th><th>Fund</th><th>Fee</th><th>Matched return</th><th>Horizon</th></tr></thead><tbody>{peers.candidates.map(p=><tr key={p.symbol}><td>{p.rank||"-"}</td><td>{p.name} ({p.symbol})</td><td>{p.expense_ratio_percent==null?"-":pct(p.expense_ratio_percent)}</td><td>{p.matched_return_percent==null?"-":pct(p.matched_return_percent)}</td><td>{p.matched_horizon||"-"}</td></tr>)}</tbody></table></div><ul className="assumptionList">{peers.warnings.map(w=><li key={w}>{w}</li>)}</ul></>}</section>
      <div className="tableWrap"><table><thead><tr><th>Key</th><th>Name</th><th>Symbol</th><th>Linked fund</th><th>Weight %</th><th>Sector</th><th>Country</th><th>Currency</th><th>Asset class</th><th></th></tr></thead><tbody>{draft.constituents.map((row,i)=><tr key={`${row.constituent_key}-${i}`}><td><input value={row.constituent_key} onChange={e=>updateRow(i,{constituent_key:e.target.value})}/></td><td><input value={row.name} onChange={e=>updateRow(i,{name:e.target.value})}/></td><td><input value={row.symbol||""} onChange={e=>updateRow(i,{symbol:e.target.value||null})}/></td><td><select value={row.linked_security_id||""} onChange={e=>updateRow(i,{linked_security_id:e.target.value?Number(e.target.value):null})}><option value="">None</option>{funds.filter(f=>f.security_id!==selected).map(f=><option key={f.security_id} value={f.security_id}>{f.security_name}</option>)}</select></td><td><input type="number" min="0" max="100" value={row.weight_percent} onChange={e=>updateRow(i,{weight_percent:Number(e.target.value)})}/></td><td><input value={row.sector} onChange={e=>updateRow(i,{sector:e.target.value})}/></td><td><input value={row.country} onChange={e=>updateRow(i,{country:e.target.value})}/></td><td><input value={row.currency} onChange={e=>updateRow(i,{currency:e.target.value})}/></td><td><input value={row.asset_category} onChange={e=>updateRow(i,{asset_category:e.target.value})}/></td><td><button className="iconOnly" onClick={()=>setDraft({...draft,constituents:draft.constituents.filter((_,j)=>j!==i)})}><Trash2 size={14}/></button></td></tr>)}</tbody></table></div>
      <label>Import CSV<textarea value={csv} onChange={e=>setCsv(e.target.value)} placeholder="constituent_key,name,symbol,weight_percent,sector,country,currency,asset_category"/></label><button className="secondary" onClick={importCsv}>Load CSV into editor</button></>}{error&&<div className="error">{error}</div>}</section>
    <div className="chartGrid"><ExposureTable title="Effective companies" rows={analysis.company} currency={analysis.display_currency}/><ExposureTable title="Effective sectors" rows={analysis.sector} currency={analysis.display_currency}/><ExposureTable title="Effective geography" rows={analysis.country} currency={analysis.display_currency}/><ExposureTable title="Effective currencies" rows={analysis.currency} currency={analysis.display_currency}/><ExposureTable title="Effective asset classes" rows={analysis.asset_category} currency={analysis.display_currency}/></div>
    <section className="panel"><h2>Fund overlap</h2><div className="tableWrap"><table><thead><tr><th>Fund</th><th>Fund</th><th>Shared constituent weight</th></tr></thead><tbody>{analysis.overlaps.map(row=><tr key={`${row.left_security_id}-${row.right_security_id}`}><td>{row.left_name}</td><td>{row.right_name}</td><td>{pct(row.overlap_percent)}</td></tr>)}</tbody></table></div></section><section className="panel"><h2>Limitations</h2><ul className="assumptionList">{analysis.warnings.map(w=><li key={w}>{w}</li>)}</ul></section></section></section>;
}

export function RiskPage({positions,currency}:{positions:Position[];currency:string}) {
  const securities=useMemo(()=>Array.from(new Map(positions.filter(p=>p.security_type.toLowerCase()!=="cash").map(p=>[p.security_id,p])).values()),[positions]);
  const [analysis,setAnalysis]=useState<RiskAnalysis|null>(null);const [settings,setSettings]=useState<RiskSettings>({benchmark_symbol:"",benchmark_currency:currency,minimum_observations:60});const [selected,setSelected]=useState("");const [csv,setCsv]=useState("");const [busy,setBusy]=useState(false);const [message,setMessage]=useState<string|null>(null);const [error,setError]=useState<string|null>(null);
  async function load(){const [a,s]=await Promise.all([api.riskAnalysis(),api.riskSettings()]);setAnalysis(a);setSettings(s);}
  useEffect(()=>{load().catch(e=>setError(e.message));},[positions,currency]);
  async function refresh(){setBusy(true);setError(null);try{const rows=await api.refreshMarketHistory();setMessage(`${rows.filter(r=>r.refreshed).length} of ${rows.length} series refreshed.`);await load();}catch(e){setError(e instanceof Error?e.message:"Refresh failed.");}finally{setBusy(false);}}
  async function saveSettings(){setBusy(true);try{await api.saveRiskSettings(settings);await load();}catch(e){setError(e instanceof Error?e.message:"Could not save settings.");}finally{setBusy(false);}}
  async function importCsv(){if(!selected)return;try{const lines=csv.trim().split(/\r?\n/).filter(Boolean);const start=lines[0]?.toLowerCase().includes("date")?1:0;const observations=lines.slice(start).map(line=>{const [date,raw]=line.split(",").map(x=>x.trim());return {date,adjusted_close:Number(raw)};});if(observations.length<2||observations.some(o=>!o.date||!Number.isFinite(o.adjusted_close)||o.adjusted_close<=0))throw new Error("Use CSV rows: date,adjusted_close.");if(selected.startsWith("security:")){const id=Number(selected.split(":")[1]);const security=securities.find(s=>s.security_id===id);await api.importMarketHistory(id,{symbol:security?.symbol||security?.security_name||"MANUAL",currency:security?.currency||currency,observations});}else if(selected==="benchmark"){await api.saveRiskSettings(settings);const symbol=settings.benchmark_symbol||analysis?.benchmark_symbol||"^GSPC";await api.importManualMarketSeries({series_key:`benchmark:${symbol}`,series_type:"benchmark",symbol,currency:settings.benchmark_currency||currency,observations});}else{const fxCurrency=selected.split(":")[1];await api.importManualMarketSeries({series_key:`fx:USD:${fxCurrency}`,series_type:"fx",symbol:`USD${fxCurrency}=X`,currency:fxCurrency,observations});}setMessage(`${observations.length} manual observations saved.`);await load();}catch(e){setError(e instanceof Error?e.message:"History import failed.");}}
  const names=Object.fromEntries(securities.map(s=>[s.security_id,s.security_name]));
  return <section className="stack"><section className="panel"><div className="panelHeader"><div><p className="eyebrow">Five-year adjusted daily history</p><h2>Risk settings and data</h2></div><button disabled={busy} onClick={refresh}><RefreshCw size={15}/>Refresh all histories</button></div><div className="formGrid"><label>Benchmark symbol<input value={settings.benchmark_symbol||""} onChange={e=>setSettings({...settings,benchmark_symbol:e.target.value})}/></label><label>Benchmark currency<select value={settings.benchmark_currency||currency} onChange={e=>setSettings({...settings,benchmark_currency:e.target.value})}>{supportedCurrencies.map(c=><option key={c}>{c}</option>)}</select></label><label>Minimum observations<input type="number" min="20" value={settings.minimum_observations} onChange={e=>setSettings({...settings,minimum_observations:Number(e.target.value)})}/></label></div><button onClick={saveSettings}>Save settings</button><h3>Offline adjusted-price import</h3><div className="formGrid"><label>Series<select value={selected} onChange={e=>setSelected(e.target.value)}><option value="">Select series</option>{securities.map(s=><option key={s.security_id} value={`security:${s.security_id}`}>{s.security_name}</option>)}<option value="benchmark">Benchmark: {settings.benchmark_symbol}</option>{supportedCurrencies.filter(c=>c!=="USD").map(c=><option key={c} value={`fx:${c}`}>FX: USD/{c}</option>)}</select></label><label>CSV: date,adjusted_close<textarea value={csv} onChange={e=>setCsv(e.target.value)}/></label></div><button className="secondary" disabled={!selected} onClick={importCsv}>Import history</button>{message&&<div className="notice">{message}</div>}{error&&<div className="error">{error}</div>}</section>
    {analysis&&<><div className="metricGrid"><MetricCard label="History coverage" value={pct(analysis.coverage_percent)}/><MetricCard label="Covered volatility" value={pct(analysis.covered_portfolio_volatility_percent)}/><MetricCard label={`Beta vs ${analysis.benchmark_symbol}`} value={analysis.covered_portfolio_beta?.toFixed(2)||"-"}/><MetricCard label="Covered max drawdown" value={pct(analysis.covered_portfolio_max_drawdown_percent)}/></div><section className="panel"><h2>Holding risk decomposition</h2><div className="tableWrap"><table><thead><tr><th>Holding</th><th>Weight</th><th>Volatility</th><th>Beta</th><th>Risk contribution</th><th>Drawdown</th><th>History</th><th>Confidence</th></tr></thead><tbody>{analysis.holdings.map(row=><tr key={row.security_id}><td>{row.name}</td><td>{pct(row.portfolio_weight_percent)}</td><td>{pct(row.annualized_volatility_percent)}</td><td>{row.beta?.toFixed(2)||"-"}</td><td>{pct(row.risk_contribution_percent)}</td><td>{pct(row.max_drawdown_percent)}</td><td title={row.warning||""}>{row.observation_count}</td><td>{row.confidence}</td></tr>)}</tbody></table></div></section><section className="panel"><h2>Largest correlations</h2><div className="tableWrap"><table><thead><tr><th>Holding</th><th>Holding</th><th>Correlation</th><th>Observations</th></tr></thead><tbody>{analysis.correlations.slice(0,20).map(row=><tr key={`${row.left_security_id}-${row.right_security_id}`}><td>{names[row.left_security_id]||row.left_security_id}</td><td>{names[row.right_security_id]||row.right_security_id}</td><td>{row.correlation.toFixed(3)}</td><td>{row.observation_count}</td></tr>)}</tbody></table></div></section><section className="panel"><h2>Assumptions and limitations</h2><ul className="assumptionList">{analysis.warnings.map(w=><li key={w}>{w}</li>)}</ul></section></>}</section>;
}

export function FeesPage({positions,currency}:{positions:Position[];currency:string}) {
  const blank:PortfolioFeeInput={name:"",fee_type:"advisory_percent",annual_percent:0,annual_amount:null,currency,enabled:true};
  const [analysis,setAnalysis]=useState<FeeAnalysis|null>(null);const [securityFees,setSecurityFees]=useState<SecurityFee[]>([]);const [ratios,setRatios]=useState<Record<number,string>>({});const [publicDrafts,setPublicDrafts]=useState<Set<number>>(new Set());const [reserveMonths,setReserveMonths]=useState(6);const [form,setForm]=useState<PortfolioFeeInput>(blank);const [busy,setBusy]=useState(false);const [message,setMessage]=useState<string|null>(null);const [error,setError]=useState<string|null>(null);
  async function load(){const [a,s,settings]=await Promise.all([api.feeAnalysis(),api.securityFees(),api.feeSettings()]);setAnalysis(a);setSecurityFees(s);setRatios(Object.fromEntries(s.map(x=>[x.security_id,x.expense_ratio_percent==null?"":String(x.expense_ratio_percent)])));setReserveMonths(settings.cash_reserve_months);}
  useEffect(()=>{load().catch(e=>setError(e.message));},[positions,currency]);
  async function saveRatio(id:number){setBusy(true);try{const raw=ratios[id];await api.saveSecurityFee(id,raw===""?null:Number(raw));await load();}catch(e){setError(e instanceof Error?e.message:"Could not save expense ratio.");}finally{setBusy(false);}}
  async function publicRatio(id:number){setBusy(true);setError(null);try{const preview=await api.previewPublicMetadata(id);if(preview.expense_ratio_percent==null)throw new Error("Public metadata did not include an expense ratio.");setRatios({...ratios,[id]:String(preview.expense_ratio_percent)});setPublicDrafts(current=>new Set(current).add(id));setMessage(`Draft expense ratio ${preview.expense_ratio_percent.toFixed(3)}% loaded. Use Accept public to persist it.`);}catch(e){setPublicDrafts(current=>{const next=new Set(current);next.delete(id);return next;});setError(e instanceof Error?e.message:"Public metadata unavailable.");}finally{setBusy(false);}}
  async function acceptRatio(id:number){if(!publicDrafts.has(id))return;setBusy(true);try{await api.acceptPublicFee(id);setPublicDrafts(current=>{const next=new Set(current);next.delete(id);return next;});await load();}catch(e){setError(e instanceof Error?e.message:"Could not accept public fee.");}finally{setBusy(false);}}
  async function addFee(){setBusy(true);try{await api.createPortfolioFee(form);setForm(blank);await load();}catch(e){setError(e instanceof Error?e.message:"Could not save portfolio fee.");}finally{setBusy(false);}}
  async function saveReserve(){await api.saveFeeSettings({cash_reserve_months:reserveMonths});await load();}
  return <section className="stack"><section className="panel"><div className="panelHeader"><div><p className="eyebrow">Manual values are authoritative</p><h2>Security expense ratios</h2></div></div><div className="tableWrap"><table><thead><tr><th>Holding</th><th>Expense ratio %</th><th>Source</th><th>Freshness</th><th></th></tr></thead><tbody>{securityFees.map(row=><tr key={row.security_id}><td>{row.security_name}</td><td><input type="number" min="0" step="0.001" value={ratios[row.security_id]??""} onChange={e=>setRatios({...ratios,[row.security_id]:e.target.value})}/></td><td>{row.source}</td><td>{row.stale?"Stale / missing":"Current"}</td><td><div className="buttonRow compact"><button disabled={busy} onClick={()=>saveRatio(row.security_id)}>Save manual</button><button className="secondary" disabled={busy} onClick={()=>publicRatio(row.security_id)}>Public draft</button><button className="secondary" disabled={busy||!publicDrafts.has(row.security_id)} onClick={()=>acceptRatio(row.security_id)}>Accept public</button></div></td></tr>)}</tbody></table></div>{message&&<div className="notice">{message}</div>}{error&&<div className="error">{error}</div>}</section>
    <section className="panel"><h2>Advisory and account fees</h2><div className="formGrid"><label>Name<input value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/></label><label>Type<select value={form.fee_type} onChange={e=>setForm({...form,fee_type:e.target.value as PortfolioFeeInput["fee_type"]})}><option value="advisory_percent">Advisory percentage</option><option value="fixed_account">Fixed account fee</option></select></label>{form.fee_type==="advisory_percent"?<label>Annual %<input type="number" min="0" step="0.01" value={form.annual_percent??""} onChange={e=>setForm({...form,annual_percent:Number(e.target.value),annual_amount:null})}/></label>:<><label>Annual amount<input type="number" min="0" value={form.annual_amount??""} onChange={e=>setForm({...form,annual_amount:Number(e.target.value),annual_percent:null})}/></label><label>Currency<select value={form.currency} onChange={e=>setForm({...form,currency:e.target.value})}>{supportedCurrencies.map(c=><option key={c}>{c}</option>)}</select></label></>}</div><button disabled={busy||!form.name.trim()} onClick={addFee}><Plus size={15}/>Add fee</button>{analysis&&<div className="tableWrap"><table><thead><tr><th>Name</th><th>Type</th><th>Annual charge</th><th>Status</th><th></th></tr></thead><tbody>{analysis.portfolio_fees.map(fee=><tr key={fee.id}><td>{fee.name}</td><td>{fee.fee_type.replace("_"," ")}</td><td>{fee.fee_type==="advisory_percent"?pct(fee.annual_percent):money(fee.annual_amount,fee.currency)}</td><td>{fee.enabled?"Active":"Paused"}</td><td><div className="buttonRow compact"><button className="secondary" onClick={async()=>{await api.updatePortfolioFee(fee.id,{name:fee.name,fee_type:fee.fee_type,annual_percent:fee.annual_percent,annual_amount:fee.annual_amount,currency:fee.currency,enabled:!fee.enabled});await load();}}>{fee.enabled?"Pause":"Enable"}</button><button className="iconOnly" onClick={async()=>{await api.deletePortfolioFee(fee.id);await load();}}><Trash2 size={14}/></button></div></td></tr>)}</tbody></table></div>}</section>
    <section className="panel"><h2>Cash reserve</h2><div className="formGrid"><label>Reserve target (months of expenses)<input type="number" min="0" value={reserveMonths} onChange={e=>setReserveMonths(Number(e.target.value))}/></label></div><button onClick={saveReserve}>Save reserve target</button></section>
    {analysis&&<><div className="metricGrid"><MetricCard label="Estimated annual fees" value={money(analysis.total_annual_fees,analysis.display_currency)}/><MetricCard label="Annual fee share" value={pct(analysis.annual_fee_percent)}/><MetricCard label="Fund expenses" value={money(analysis.annual_fund_expenses,analysis.display_currency)}/><MetricCard label="Advisory + fixed" value={money(analysis.annual_advisory_fees+analysis.annual_fixed_fees,analysis.display_currency)}/><MetricCard label="Potential idle cash" value={analysis.potential_idle_cash==null?"Set expenses":money(analysis.potential_idle_cash,analysis.display_currency)}/><MetricCard label="Potential annual cash drag" value={analysis.potential_cash_drag==null?"Set return":money(analysis.potential_cash_drag,analysis.display_currency)}/></div><section className="panel"><h2>Long-term cost projection</h2><div className="tableWrap"><table><thead><tr><th>Horizon</th><th>Nominal fees paid</th><th>Ending value before fees</th><th>Ending value after fees</th><th>Opportunity cost</th></tr></thead><tbody>{analysis.projections.map(row=><tr key={row.years}><td>{row.years} years</td><td>{money(row.cumulative_nominal_fees,analysis.display_currency)}</td><td>{money(row.ending_value_without_fees,analysis.display_currency)}</td><td>{money(row.ending_value_after_fees,analysis.display_currency)}</td><td>{money(row.opportunity_cost,analysis.display_currency)}</td></tr>)}</tbody></table></div></section><section className="panel"><h2>Assumptions and limitations</h2><ul className="assumptionList">{analysis.warnings.map(w=><li key={w}>{w}</li>)}</ul></section></>}</section>;
}
