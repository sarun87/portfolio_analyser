import sqlite3


SCHEMA = """
CREATE TABLE IF NOT EXISTS app_settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS brokers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  default_currency TEXT NOT NULL DEFAULT 'USD',
  notes TEXT,
  locked_fields_json TEXT NOT NULL DEFAULT '[]',
  header_signature_json TEXT NOT NULL DEFAULT '[]',
  mappings_json TEXT NOT NULL DEFAULT '{}',
  configuration_version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  broker_id INTEGER NOT NULL REFERENCES brokers(id) ON DELETE CASCADE,
  account_number_enc TEXT NOT NULL,
  account_mask TEXT NOT NULL,
  account_fingerprint TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (broker_id, account_fingerprint)
);

CREATE TABLE IF NOT EXISTS statement_imports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  broker_id INTEGER NOT NULL REFERENCES brokers(id),
  account_id INTEGER REFERENCES accounts(id),
  statement_date TEXT NOT NULL,
  source_filename TEXT,
  row_count INTEGER NOT NULL,
  fingerprint TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL,
  detected_columns TEXT NOT NULL,
  errors_json TEXT NOT NULL DEFAULT '[]',
  locked_fields_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS securities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT,
  name TEXT NOT NULL,
  security_type TEXT NOT NULL,
  allocation_category TEXT NOT NULL DEFAULT 'Unclassified',
  sector TEXT NOT NULL DEFAULT 'Unclassified',
  classification_source TEXT,
  classified_at TEXT,
  price_refresh_supported INTEGER NOT NULL DEFAULT 1,
  exchange TEXT NOT NULL DEFAULT 'Unresolved',
  investment_country TEXT NOT NULL DEFAULT 'Unresolved',
  mfapi_scheme_code TEXT,
  location_source TEXT,
  location_resolved_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (symbol, exchange)
);

CREATE TABLE IF NOT EXISTS positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  import_id INTEGER NOT NULL REFERENCES statement_imports(id) ON DELETE CASCADE,
  account_id INTEGER NOT NULL REFERENCES accounts(id),
  security_id INTEGER NOT NULL REFERENCES securities(id),
  snapshot_date TEXT NOT NULL,
  acquisition_date TEXT,
  lot_number TEXT,
  units REAL NOT NULL DEFAULT 0,
  per_unit_cost_basis REAL,
  total_cost_basis REAL,
  per_unit_fmv REAL,
  total_fmv REAL,
  currency TEXT NOT NULL DEFAULT 'USD',
  row_notes TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS price_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  security_id INTEGER NOT NULL REFERENCES securities(id) ON DELETE CASCADE,
  price REAL NOT NULL,
  price_date TEXT NOT NULL,
  provider TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (security_id, price_date, provider)
);

CREATE TABLE IF NOT EXISTS fx_rates (
  from_currency TEXT NOT NULL,
  to_currency TEXT NOT NULL,
  rate REAL NOT NULL,
  source TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (from_currency, to_currency)
);

CREATE TABLE IF NOT EXISTS static_accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  category TEXT NOT NULL,
  entity_name TEXT NOT NULL,
  account_type TEXT NOT NULL,
  account_holder TEXT NOT NULL,
  account_number_enc TEXT,
  account_mask TEXT,
  account_fingerprint TEXT,
  currency TEXT NOT NULL DEFAULT 'USD',
  amount REAL NOT NULL DEFAULT 0,
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS real_estate_assets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  property_info TEXT NOT NULL,
  entity_name TEXT,
  purchase_date TEXT,
  purchase_value REAL NOT NULL DEFAULT 0,
  current_value REAL NOT NULL DEFAULT 0,
  currency TEXT NOT NULL DEFAULT 'USD',
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS financial_assumptions (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  expected_annual_return REAL,
  annual_volatility REAL,
  inflation_rate REAL,
  monthly_household_contribution REAL,
  monthly_expenses REAL,
  current_age INTEGER,
  end_age INTEGER NOT NULL DEFAULT 85,
  short_term_tax_rate REAL,
  long_term_tax_rate REAL,
  long_term_holding_days INTEGER,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scheduled_expenses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  expense_type TEXT NOT NULL CHECK (expense_type IN ('one_time', 'date_range')),
  amount REAL NOT NULL CHECK (amount >= 0),
  currency TEXT NOT NULL,
  expense_date TEXT,
  start_date TEXT,
  end_date TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS allocation_targets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dimension TEXT NOT NULL CHECK (dimension IN ('asset_category', 'country', 'currency')),
  label TEXT NOT NULL,
  target_percent REAL NOT NULL CHECK (target_percent >= 0 AND target_percent <= 100),
  tolerance_percent REAL NOT NULL DEFAULT 10 CHECK (tolerance_percent >= 0 AND tolerance_percent <= 100),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (dimension, label)
);

CREATE TABLE IF NOT EXISTS goals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  description TEXT,
  target_amount REAL NOT NULL CHECK (target_amount >= 0),
  target_currency TEXT NOT NULL DEFAULT 'USD',
  target_month TEXT NOT NULL,
  allocated_amount REAL NOT NULL DEFAULT 0 CHECK (allocated_amount >= 0),
  allocated_currency TEXT NOT NULL DEFAULT 'USD',
  monthly_contribution REAL NOT NULL DEFAULT 0 CHECK (monthly_contribution >= 0),
  contribution_currency TEXT NOT NULL DEFAULT 'USD',
  priority INTEGER,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS saved_scenarios (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  description TEXT,
  scenario_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fund_compositions (
  security_id INTEGER PRIMARY KEY REFERENCES securities(id) ON DELETE CASCADE,
  source TEXT NOT NULL DEFAULT 'manual',
  source_url TEXT,
  holdings_scope TEXT NOT NULL DEFAULT 'full',
  as_of_date TEXT,
  reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fund_constituents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fund_security_id INTEGER NOT NULL REFERENCES fund_compositions(security_id) ON DELETE CASCADE,
  constituent_key TEXT NOT NULL,
  identifier TEXT,
  linked_security_id INTEGER REFERENCES securities(id) ON DELETE SET NULL,
  symbol TEXT,
  name TEXT NOT NULL,
  weight_percent REAL NOT NULL CHECK (weight_percent > 0 AND weight_percent <= 100),
  sector TEXT NOT NULL DEFAULT 'Unclassified',
  country TEXT NOT NULL DEFAULT 'Unresolved',
  currency TEXT NOT NULL DEFAULT 'Unresolved',
  asset_category TEXT NOT NULL DEFAULT 'Unclassified',
  UNIQUE (fund_security_id, constituent_key)
);

CREATE TABLE IF NOT EXISTS fund_metadata (
  security_id INTEGER PRIMARY KEY REFERENCES securities(id) ON DELETE CASCADE,
  provider TEXT NOT NULL DEFAULT 'manual',
  category TEXT,
  thesis TEXT,
  fund_family TEXT,
  inception_date TEXT,
  assets_under_management REAL,
  yield_percent REAL,
  turnover_percent REAL,
  beta REAL,
  expense_ratio_percent REAL,
  return_3y_percent REAL,
  return_5y_percent REAL,
  return_10y_percent REAL,
  return_since_inception_percent REAL,
  as_of_date TEXT,
  fetched_at TEXT,
  unavailable_fields_json TEXT NOT NULL DEFAULT '[]',
  reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fund_sector_weights (
  fund_security_id INTEGER NOT NULL REFERENCES securities(id) ON DELETE CASCADE,
  sector TEXT NOT NULL,
  weight_percent REAL NOT NULL CHECK (weight_percent >= 0 AND weight_percent <= 100),
  PRIMARY KEY (fund_security_id, sector)
);

CREATE TABLE IF NOT EXISTS fund_ohlcv_history (
  fund_security_id INTEGER NOT NULL REFERENCES securities(id) ON DELETE CASCADE,
  price_date TEXT NOT NULL,
  open REAL,
  high REAL,
  low REAL,
  close REAL,
  adjusted_close REAL,
  volume REAL,
  PRIMARY KEY (fund_security_id, price_date)
);

CREATE TABLE IF NOT EXISTS fund_refresh_status (
  security_id INTEGER PRIMARY KEY REFERENCES securities(id) ON DELETE CASCADE,
  yahoo_symbol TEXT NOT NULL,
  refreshed_at TEXT NOT NULL,
  warnings_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS private_equity_assets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_name TEXT NOT NULL,
  stage TEXT NOT NULL,
  share_class TEXT NOT NULL CHECK (share_class IN ('Common', 'Preferred')),
  quantity REAL NOT NULL CHECK (quantity >= 0),
  purchase_price_per_unit REAL NOT NULL CHECK (purchase_price_per_unit >= 0),
  investment_date TEXT,
  last_valuation_per_unit REAL NOT NULL CHECK (last_valuation_per_unit >= 0),
  valuation_date TEXT,
  ownership_percent REAL,
  valuation_source TEXT,
  currency TEXT NOT NULL DEFAULT 'USD',
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reference_cache (
  cache_key TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at TEXT
);

CREATE TABLE IF NOT EXISTS market_series (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  series_key TEXT NOT NULL UNIQUE,
  series_type TEXT NOT NULL CHECK (series_type IN ('security', 'benchmark', 'fx')),
  security_id INTEGER REFERENCES securities(id) ON DELETE CASCADE,
  symbol TEXT NOT NULL,
  currency TEXT NOT NULL,
  source TEXT NOT NULL,
  refreshed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS market_series_points (
  series_id INTEGER NOT NULL REFERENCES market_series(id) ON DELETE CASCADE,
  observation_date TEXT NOT NULL,
  adjusted_close REAL NOT NULL CHECK (adjusted_close > 0),
  PRIMARY KEY (series_id, observation_date)
);

CREATE TABLE IF NOT EXISTS risk_settings (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  benchmark_symbol TEXT,
  benchmark_currency TEXT,
  minimum_observations INTEGER NOT NULL DEFAULT 60 CHECK (minimum_observations >= 20),
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS security_fee_metadata (
  security_id INTEGER PRIMARY KEY REFERENCES securities(id) ON DELETE CASCADE,
  expense_ratio_percent REAL CHECK (expense_ratio_percent >= 0 AND expense_ratio_percent <= 100),
  source TEXT NOT NULL DEFAULT 'manual',
  as_of_date TEXT,
  reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS portfolio_fees (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  fee_type TEXT NOT NULL CHECK (fee_type IN ('advisory_percent', 'fixed_account')),
  annual_percent REAL CHECK (annual_percent >= 0 AND annual_percent <= 100),
  annual_amount REAL CHECK (annual_amount >= 0),
  currency TEXT NOT NULL DEFAULT 'USD',
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fee_settings (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  cash_reserve_months REAL NOT NULL DEFAULT 6 CHECK (cash_reserve_months >= 0),
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_positions_snapshot ON positions(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_positions_security ON positions(security_id);
CREATE INDEX IF NOT EXISTS idx_positions_account ON positions(account_id);
CREATE INDEX IF NOT EXISTS idx_securities_location ON securities(investment_country, exchange);
CREATE INDEX IF NOT EXISTS idx_price_history_security ON price_history(security_id, price_date);
CREATE INDEX IF NOT EXISTS idx_static_accounts_category ON static_accounts(category);
CREATE INDEX IF NOT EXISTS idx_allocation_targets_dimension ON allocation_targets(dimension);
CREATE INDEX IF NOT EXISTS idx_goals_target_month ON goals(target_month);
CREATE INDEX IF NOT EXISTS idx_saved_scenarios_updated ON saved_scenarios(updated_at);
CREATE INDEX IF NOT EXISTS idx_fund_constituents_fund ON fund_constituents(fund_security_id);
CREATE INDEX IF NOT EXISTS idx_fund_ohlcv_date ON fund_ohlcv_history(fund_security_id, price_date);
CREATE INDEX IF NOT EXISTS idx_private_equity_company ON private_equity_assets(company_name);
CREATE INDEX IF NOT EXISTS idx_market_series_security ON market_series(security_id);
CREATE INDEX IF NOT EXISTS idx_market_points_date ON market_series_points(observation_date);
"""


def init_db(conn: sqlite3.Connection) -> None:
    # Migrations deliberately run on every unlock.  Older encrypted dumps did
    # not have a version ledger, so the first migration is an additive
    # baseline: it creates missing objects but never clears user records.
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
    for version, migration in MIGRATIONS:
        if not conn.execute("SELECT 1 FROM schema_migrations WHERE version = ?", (version,)).fetchone():
            migration(conn)
            conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
    ensure_fx_rates(conn)
    # This is a write-time default, not something Insights should create on a
    # read request (which would force an encrypted snapshot persistence).
    conn.execute("INSERT OR IGNORE INTO app_settings(key, value) VALUES ('decision_coach_base_currency', 'USD')")
    conn.commit()


def _baseline_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _ensure_column(conn, "securities", "sector", "TEXT NOT NULL DEFAULT 'Unclassified'")
    _ensure_column(conn, "brokers", "default_currency", "TEXT NOT NULL DEFAULT 'USD'")
    _ensure_column(conn, "brokers", "notes", "TEXT")
    _ensure_column(conn, "brokers", "locked_fields_json", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(conn, "brokers", "header_signature_json", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(conn, "brokers", "mappings_json", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(conn, "brokers", "configuration_version", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(conn, "allocation_targets", "tolerance_percent", "REAL NOT NULL DEFAULT 10")
    _ensure_column(conn, "fund_compositions", "source_url", "TEXT")
    _ensure_column(conn, "fund_compositions", "holdings_scope", "TEXT NOT NULL DEFAULT 'full'")
    _ensure_column(conn, "fund_constituents", "identifier", "TEXT")


def _allocation_categories(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS allocation_categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL COLLATE NOCASE UNIQUE,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    names = {"Unclassified", "Cash", "Equity", "Fixed Income", "Real Estate", "Alternatives", "Other"}
    for query, column in (
        ("SELECT DISTINCT allocation_category AS name FROM securities", "name"),
        ("SELECT DISTINCT asset_category AS name FROM fund_constituents", "name"),
        ("SELECT DISTINCT label AS name FROM allocation_targets WHERE dimension='asset_category'", "name"),
    ):
        try:
            names.update(row[column].strip() for row in conn.execute(query) if row[column] and row[column].strip())
        except sqlite3.OperationalError:
            pass
    for name in names:
        conn.execute("INSERT OR IGNORE INTO allocation_categories (name) VALUES (?)", (name,))


def _composition_provenance(conn: sqlite3.Connection) -> None:
    _ensure_column(conn, "fund_compositions", "source_url", "TEXT")
    _ensure_column(conn, "fund_compositions", "holdings_scope", "TEXT NOT NULL DEFAULT 'full'")
    _ensure_column(conn, "fund_constituents", "identifier", "TEXT")


def _projection_planning(conn: sqlite3.Connection) -> None:
    _ensure_column(conn, "financial_assumptions", "current_age", "INTEGER")
    _ensure_column(conn, "financial_assumptions", "end_age", "INTEGER NOT NULL DEFAULT 85")
    conn.execute("""CREATE TABLE IF NOT EXISTS scheduled_expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
        expense_type TEXT NOT NULL CHECK (expense_type IN ('one_time', 'date_range')),
        amount REAL NOT NULL CHECK (amount >= 0), currency TEXT NOT NULL,
        expense_date TEXT, start_date TEXT, end_date TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")


def _performance_indexes(conn: sqlite3.Connection) -> None:
    """Additive indexes for current-position and historical-series reads."""
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_positions_account_snapshot_date
            ON positions(account_id, snapshot_date DESC);
        CREATE INDEX IF NOT EXISTS idx_market_points_series_date
            ON market_series_points(series_id, observation_date);
        CREATE INDEX IF NOT EXISTS idx_price_history_security_latest
            ON price_history(security_id, price_date DESC, id DESC);
    """)


def _lot_identity_index(conn: sqlite3.Connection) -> None:
    """Index the additive lot identity without imposing a risky unique constraint.

    Existing databases can contain historically duplicated or incomplete lot
    data, so a unique index would make upgrading destructive.  The columns
    already exist in all supported schemas; this migration only adds an index.
    """
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_positions_lot_identity
        ON positions(account_id, security_id, lot_number, acquisition_date, per_unit_cost_basis)""")


def _report_branding(conn: sqlite3.Connection) -> None:
    """Persist report defaults inside the encrypted database."""
    conn.execute("""CREATE TABLE IF NOT EXISTS report_branding (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        title TEXT NOT NULL,
        subtitle TEXT,
        footer TEXT,
        logo_data BLOB,
        logo_mime_type TEXT,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("""INSERT OR IGNORE INTO report_branding (id, title)
        VALUES (1, 'Portfolio Analyser Net-Worth Report')""")


def _liabilities(conn: sqlite3.Connection) -> None:
    """Add liabilities without changing existing encrypted portfolio data."""
    conn.execute("""CREATE TABLE IF NOT EXISTS liabilities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_name TEXT NOT NULL,
        liability_type TEXT NOT NULL,
        custom_type TEXT,
        account_reference_enc TEXT,
        account_reference_mask TEXT,
        outstanding_balance REAL NOT NULL CHECK (outstanding_balance >= 0),
        currency TEXT NOT NULL DEFAULT 'USD',
        notes TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_liabilities_type ON liabilities(liability_type)")


def _yfinance_fund_data(conn: sqlite3.Connection) -> None:
    """The old fund editor is disposable; yfinance data is stored afresh."""
    conn.executescript("""
        DELETE FROM fund_constituents;
        DELETE FROM fund_compositions;
        DELETE FROM fund_metadata;
        CREATE TABLE IF NOT EXISTS fund_sector_weights (
          fund_security_id INTEGER NOT NULL REFERENCES securities(id) ON DELETE CASCADE,
          sector TEXT NOT NULL,
          weight_percent REAL NOT NULL CHECK (weight_percent >= 0 AND weight_percent <= 100),
          PRIMARY KEY (fund_security_id, sector));
        CREATE TABLE IF NOT EXISTS fund_ohlcv_history (
          fund_security_id INTEGER NOT NULL REFERENCES securities(id) ON DELETE CASCADE,
          price_date TEXT NOT NULL, open REAL, high REAL, low REAL, close REAL,
          adjusted_close REAL, volume REAL,
          PRIMARY KEY (fund_security_id, price_date));
        CREATE TABLE IF NOT EXISTS fund_refresh_status (
          security_id INTEGER PRIMARY KEY REFERENCES securities(id) ON DELETE CASCADE,
          yahoo_symbol TEXT NOT NULL, refreshed_at TEXT NOT NULL,
          warnings_json TEXT NOT NULL DEFAULT '[]');
        CREATE INDEX IF NOT EXISTS idx_fund_ohlcv_date ON fund_ohlcv_history(fund_security_id, price_date);
    """)


def _yfinance_expense_ratio_unit(conn: sqlite3.Connection) -> None:
    """Correct values written before yfinance ratios were treated as percentages."""
    conn.execute("""UPDATE fund_metadata
        SET expense_ratio_percent = expense_ratio_percent / 100.0
        WHERE provider = 'yfinance' AND expense_ratio_percent IS NOT NULL""")


def _mfapi_indian_mutual_funds(conn: sqlite3.Connection) -> None:
    _ensure_column(conn, "securities", "mfapi_scheme_code", "TEXT")
    _ensure_column(conn, "fund_refresh_status", "provider", "TEXT NOT NULL DEFAULT 'yfinance'")
    _ensure_column(conn, "fund_refresh_status", "provider_identifier", "TEXT")


MIGRATIONS = ((1, _baseline_schema), (2, _allocation_categories), (3, _composition_provenance), (4, _projection_planning), (5, _performance_indexes), (6, _lot_identity_index), (7, _report_branding), (8, _liabilities), (9, _yfinance_fund_data), (10, _yfinance_expense_ratio_unit), (11, _mfapi_indian_mutual_funds))


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    if column not in {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def ensure_fx_rates(conn: sqlite3.Connection) -> None:
    from backend.app.services.fx_service import ensure_default_fx_rates

    ensure_default_fx_rates(conn)
