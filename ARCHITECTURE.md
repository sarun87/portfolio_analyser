# Portfolio Analyser Architecture

This document captures enough application context for a future engineer or LLM agent to safely modify the codebase from a cold start.

## Purpose

Portfolio Analyser is a local-first web application for importing broker CSV statements, normalizing holdings into SQLite, and showing portfolio positions, unrealized profit/loss, allocation, growth, and net-worth analytics.

The app is designed for sensitive financial data:

- It runs locally.
- SQLite runs only in memory while unlocked; encrypted committed state is stored in `data/portfolio.db.encrypted`.
- Uploaded CSV files are parsed but not retained.
- The complete database is encrypted with an app passphrase.
- Account numbers are masked in the UI.

## Stack

- Backend: FastAPI, Python 3.9-compatible code.
- Database: in-memory SQLite with encrypted snapshot persistence.
- Encryption: `cryptography.Fernet`, key derived from passphrase with PBKDF2.
- Frontend: React, TypeScript, Vite.
- Charts: Recharts.
- Icons: `lucide-react`.
- External data:
  - Market prices: Yahoo Finance chart endpoint.
  - Security classification: Yahoo Finance quote summary endpoint with local fallback rules.
  - FX rates: Frankfurter API, with manual overrides in Settings.

## Important Scripts

- `./init_portfolio_analyser`
  - Creates `.venv`
  - Installs Python dependencies
  - Installs frontend npm dependencies
  - Builds the frontend

- `./run_portfolio_analyser`
  - Starts FastAPI on `http://127.0.0.1:8000`
  - Serves the built frontend from `frontend/dist`

- `./compress_application [--portable|--full]`
  - Creates copyable archives under `archives/`
  - Portable mode excludes `.venv`, `node_modules`, `.git`, caches, and generated archives
  - Includes encrypted application data if present

## Repository Layout

- `backend/app/main.py`
  - FastAPI app setup
  - CORS config for Vite dev server
  - Encrypted database lifecycle setup
  - Static frontend serving from `frontend/dist`

- `backend/app/api/routes.py`
  - HTTP API routes
  - Auth setup/unlock/lock
  - Import preview/commit
  - Positions, P/L, analytics
  - Price refresh
  - Classification refresh
  - FX/currency management
  - Database clean

- `backend/app/db/schema.py`
  - SQLite schema
  - Fresh database initialization
  - Broker seed data
  - FX default-rate seeding

- `backend/app/services/`
  - `csv_importer.py`: CSV header mapping, parsing, validation, preview fingerprints
  - `import_service.py`: Persists previewed imports into normalized tables
  - `portfolio_service.py`: Positions, P/L, dashboard analytics, currency conversion
- `price_service.py`: Yahoo-style price refresh
- `scenario_service.py`: Saved non-destructive scenarios, current/proposed comparisons, and portfolio stress tests
  - `classification_service.py`: Allocation category classification
  - `fx_service.py`: Display currency, FX rates, Frankfurter refresh, manual rates
  - `repositories.py`: Low-level DB write/read helpers
  - `models.py`: Pydantic API models

- `frontend/src/App.tsx`
  - Main React application
  - Auth gate
  - Navigation
  - Dashboard/charts
  - Positions and P/L tables
  - Upload flow
  - Settings, FX controls, clean database action

- `frontend/src/lib/api.ts`
  - Typed frontend API client

- `frontend/src/lib/types.ts`
  - TypeScript API/data types

- `frontend/src/styles/styles.css`
  - Light/dark UI styling
  - Table, chart, form, settings styles

- `backend/tests/`
  - Backend unit/integration tests for parsing, import persistence, analytics, duplicate detection, and database cleaning

- `test_data/`
  - Synthetic broker CSV statements for UI/manual testing

## Database Model

Core tables:

- `app_settings`
  - Key/value settings.
  - Stores application settings such as the selected display currency.

- `brokers`
  - Seeded broker names:
    - `ETRADE`
    - `Charles Schwab`
    - `Morgan Stanley`
    - `Fidelity`
  - `Vanguard`
  - `Interactive Brokers (IBKR)`
  - `HDFC Securities`

- `accounts`
  - Broker account records.
  - Full account number is additionally field-encrypted in `account_number_enc`.
  - UI-safe mask is stored in `account_mask`.
  - `account_fingerprint` supports duplicate/reconciliation without decrypting.

- `statement_imports`
  - Import audit metadata.
  - Stores broker, account, statement date, source filename, row count, detected columns, validation warnings, and fingerprint.
  - Does not store raw CSV content.

- `securities`
  - Normalized security master data.
  - Important columns:
    - `symbol`
    - `name`
    - `security_type`
    - `allocation_category`
    - `sector` (manual metadata used by sector stress tests; defaults to `Unclassified`)
    - `classification_source`
    - `classified_at`
  - `price_refresh_supported`
  - `exchange`, `investment_country`, and location lookup metadata

- `positions`
  - Statement snapshot holdings.
  - Important columns:
    - `snapshot_date`
    - `acquisition_date`
    - `lot_number`
    - `units`
    - `per_unit_cost_basis`
    - `total_cost_basis`
    - `per_unit_fmv`
    - `total_fmv`
  - `currency`

Import locks are selected per upload and are recorded with the statement import. Locked holding fields are copied from the latest matching broker/account/security/lot snapshot while the new snapshot date is retained.

- `price_history`
  - Refreshed security prices by date/provider.

- `fx_rates`
  - Stored currency conversion rates.
  - Supported currencies are currently `USD`, `INR`, `GBP`, `EUR`.
  - Identity rates are seeded for each currency.
  - Manual overrides and API-sourced rates share the same table.

## Auth and Encryption

Encryption is managed in `backend/app/core/encryption.py`.

Flow:

1. First launch calls `POST /api/auth/setup`.
2. A random salt is generated.
3. A Fernet key is derived from the passphrase with PBKDF2.
4. A verifier token is encrypted and stored with the salt in `data/auth.json`; neither value is portfolio data.
5. SQLite is opened only in memory, and committed SQL snapshots are Fernet-encrypted before atomic disk writes.
6. Later unlocks call `POST /api/auth/unlock`, derive the key again, decrypt the verifier and database, and issue a random in-memory session token.

The key, session token, CSRF token, and plaintext SQLite database are held only in process memory. The browser receives the session token only in an HttpOnly, browser-session cookie, so refreshing the UI preserves the unlocked session without exposing the token to JavaScript.

Important behavior:

- Every non-authentication API requires both an unlocked database and the current session cookie. State-changing requests also require a matching CSRF cookie/header pair and a trusted browser origin.
- Locking closes the in-memory SQLite database, clears the key and session state, and expires both browser cookies.
- Browser-session cookies survive refreshes but are cleared when the browser closes; backend restart also invalidates the in-memory session.
- Local development permits HTTP cookies for loopback use. Production requires `PORTFOLIO_SESSION_COOKIE_SECURE=true` and HTTPS `PORTFOLIO_TRUSTED_ORIGINS` (comma-separated); see [PRODUCTION_HTTPS.md](PRODUCTION_HTTPS.md) for deployment instructions.
- If `data/portfolio.db.encrypted` is copied to another device with `data/auth.json`, the same passphrase is required.

## Import Flow

Frontend:

1. User selects broker, statement date, and CSV file.
2. Browser reads file text.
3. Frontend sends CSV text to `/api/imports/preview`.
4. User reviews detected column mapping and preview rows.
5. Frontend sends the same CSV text plus final mapping to `/api/imports/commit`.

Backend:

1. `csv_importer.py` parses CSV headers with `csv.DictReader`.
2. Broker-specific aliases and global aliases map source columns to canonical fields.
3. Rows are normalized into `PreviewRow`.
4. A stable fingerprint detects duplicate imports.
5. `import_service.py` persists:
   - broker
   - encrypted/masked accounts inside the encrypted database
   - securities
   - positions
   - statement import metadata

Canonical import fields:

- `account_number`
- `security_name`
- `symbol`
- `security_type`
- `acquisition_date`
- `lot_number`
- `units`
- `per_unit_cost_basis`
- `total_cost_basis`
- `per_unit_fmv`
- `total_fmv`
- `currency`

Supported import currencies:

- `USD`
- `INR`
- `GBP`
- `EUR`

## Analytics and Currency

Analytics are snapshot-based, not transaction-based.

There is no transaction ledger, dividend model, realized gain/loss model, or time-weighted return calculation.

`portfolio_service.py`:

- Lists only the latest snapshot date for the Positions and P/L views.
- Converts monetary values into the selected display currency using `fx_service.py`.
- Builds:
  - total value
  - total cost basis
  - unrealized gain/loss
  - portfolio growth by snapshot date
  - allocation by `allocation_category`
  - broker allocation
  - cash vs invested

Display currency is stored in `app_settings.display_currency`.

FX behavior:

- `GET /api/currency` returns current display currency and supported currencies.
- `POST /api/currency/{currency}` changes display currency.
- `GET /api/fx-rates` lists all stored rates.
- `POST /api/fx-rates` manually updates a rate.
- `POST /api/fx-rates/refresh` refreshes rates from Frankfurter.

If no FX rate exists for a pair, the backend currently falls back to `1.0`. Future changes may want to surface missing-rate warnings instead.

## Market Prices

`price_service.py` refreshes prices from Yahoo Finance’s chart endpoint.

Endpoints:

- `POST /api/prices/refresh/{security_id}`
- `POST /api/prices/refresh-all`

Refresh behavior:

- Requires a symbol.
- Skips unsupported or symbol-less securities.
- Stores price in `price_history`.
- Keeps imported statement snapshots immutable.
- Overlays the latest cached price when current positions and analytics are read; historical snapshot comparisons continue to use statement-date values.

Current limitation:

- Price refresh assumes the returned price is in the same currency as stored statement values.
- For multi-currency precision, future work should store quote currency per price response and convert explicitly.

## Security Classification

Allocation charts use `securities.allocation_category`, not raw imported `security_type`.

Categories currently include:

- `Large Cap`
- `Mid Cap`
- `Small Cap`
- `Hybrid Fund`
- `Bonds`
- `Cash`
- `Unclassified`

Classification flow:

1. Imports assign a deterministic local fallback category using `fallback_category`.
2. Allocation page exposes `Refresh Classifications`.
3. Backend tries Yahoo Finance quote summary/profile data.
4. If remote data fails, local fallback remains in use.

Endpoints:

- `POST /api/securities/classify/{security_id}`
- `POST /api/securities/classify-all`

Known local mappings include:

- `QQQ`, `VOO`: Large Cap
- `VTI`, `SCHB`: Hybrid Fund
- `SCHC`: Small Cap
- `AGG`, `BND`, `SCHZ`, `VGIT`, `VCIT`, `MUB`, `TLT`, `VBTLX`, `VWIUX`: Bonds

## Frontend Behavior

Main views:

- Overview
- Positions
- Profit/Loss
- Growth
- Allocation
- Upload
- Settings

Important UI features:

- Dark mode toggle in the top bar.
- Dark mode is stored in `localStorage` as `portfolio-theme`.
- Security symbols link to Yahoo Finance.
- Positions and Profit/Loss tables are sortable.
- Positions has a monetary display toggle:
  - total values
  - per-stock/unit values
  - current/FMV price view
- Pie charts show percentages.
- Clicking an asset-allocation pie slice switches to Positions and applies a text filter.
- Settings includes:
  - privacy/encryption status
  - display currency
  - FX refresh
  - manual FX rate edits
  - clean database action

## Clean Database Behavior

Endpoint:

- `POST /api/database/clean`

Deletes:

- `price_history`
- `positions`
- `statement_imports`
- `securities`
- `accounts`

Preserves:

- `app_settings`
- `brokers`
- encryption setup
- display currency and FX rates

The UI requires typing `DELETE` before the clean action is enabled.

## Public API Summary

Auth:

- `GET /api/auth/status`
- `POST /api/auth/setup`
- `POST /api/auth/unlock`
- `POST /api/auth/lock`

Broker/import:

- `GET /api/brokers`
- `POST /api/imports/preview`
- `POST /api/imports/commit`

Portfolio:

- `GET /api/positions`
- `POST /api/positions`
- `PUT /api/positions/{position_id}`
- `GET /api/profit-loss`
- `GET /api/analytics/dashboard`

Prices/classification:

- `POST /api/prices/refresh/{security_id}`
- `POST /api/prices/refresh-all`
- `POST /api/securities/classify/{security_id}`
- `POST /api/securities/classify-all`

Currency/FX:

- `GET /api/currency`
- `POST /api/currency/{currency}`
- `GET /api/fx-rates`
- `POST /api/fx-rates`
- `POST /api/fx-rates/refresh`

Maintenance:

- `POST /api/database/clean`

## Testing

Run backend tests:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/portfolio_analyser_pycache .venv/bin/python -m pytest backend/tests
```

Run frontend build:

```bash
cd frontend
npm run build
```

Current test coverage focuses on:

- number parsing
- broker/header mapping
- import preview normalization
- import persistence
- dashboard analytics
- duplicate import detection
- clean database behavior

Manual UI test data lives in `test_data/`.

Recommended manual flow:

1. Start app with `./run_portfolio_analyser`.
2. Create or unlock passphrase.
3. Upload each CSV from `test_data/`.
4. Confirm preview mapping.
5. Commit imports.
6. Check Positions, P/L, Allocation, Growth.
7. Toggle dark mode.
8. Click allocation pie slices and verify Positions filter.
9. Change display currency in Settings.
10. Refresh or manually edit FX rates.
11. Use Clean Database after test completion.

## Design Constraints and Conventions

- Keep Python 3.9 compatibility.
  - Avoid PEP 604 runtime annotations in Pydantic models unless using `Optional[...]`.
  - Some modules use `from __future__ import annotations`, but Pydantic model fields should still be conservative.

- Use SQLite directly with `sqlite3`.
  - The shared in-memory connection and encrypted persistence are managed in `backend/app/db/database.py`.
  - Use `get_connection()` for serialized request-level transaction handling.

- This codebase currently assumes fresh deployments without database migrations.
  - If persistent upgrade support is needed later, introduce an explicit migration strategy instead of adding ad hoc compatibility code.

- Keep raw CSV files out of storage.
  - Do not add raw upload persistence unless product/security requirements change.

- Preserve full-database encryption and encrypted account-field handling.
  - Do not introduce plaintext database, dump, journal, or WAL files.

- Keep frontend API types aligned with Pydantic models.
  - Update both `backend/app/services/models.py` and `frontend/src/lib/types.ts` for response shape changes.

- Use `lucide-react` icons for UI controls.

- Avoid destructive operations without explicit confirmation in UI.

## Known Limitations and Future Work

- PDF statements are not supported.
- Analytics are holdings-snapshot based, not transaction based.
- No realized gain/loss, dividends, deposits, withdrawals, IRR, or TWR.
- FX conversion assumes stored position values are in the row currency and applies the selected display rate at view time.
- Price refresh does not yet store quote currency.
- Yahoo Finance endpoints are unofficial and may change.
- Frankfurter rates require internet access; manual rates are available as fallback.
- Security classification is best-effort and should not be treated as authoritative investment taxonomy.
- Frontend is mostly in one large `App.tsx`; future growth should split it into feature components.
