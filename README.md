![Static Badge](https://img.shields.io/badge/Built%20with%20AI-blue)

# Portfolio Analyser

Local-first portfolio statement analyser for configurable CSV broker exports.

## What it does

- Broker definitions are editable: configure one or more CSV sections, their header signatures, mappings, and optional row filters, then import using the saved configuration. Fresh databases include editable Fidelity and IBKR entries only.
- Imports never accept one-off column mappings; refresh the preview if a broker configuration changes. Import-only lock overrides do not alter broker defaults.
- Stores normalized positions, lots, cost basis, FMV, and statement snapshots in local SQLite.
- Encrypts the complete portfolio database at rest with an app passphrase and masks accounts in the UI by default.
- Shows positions, unrealized profit/loss, allocation, portfolio growth, and net-worth trends.
- Provides a ranked portfolio review inbox with evidence, confidence, estimated impact, and non-prescriptive next steps.
- Turns asset-category, country, and currency targets into household allocation-policy ranges with configurable per-target tolerances and explainable breach alerts.
- Compares the two latest portfolio states for new/exited holdings, unit changes, cash movement, allocation shifts, and unusual valuation changes, with inferred activity clearly labeled.
- Saves non-destructive scenarios for contributions, withdrawals, reallocations, sales, cash reserves, and goal allocations, with current-versus-proposed comparisons.
- Runs preset and custom portfolio stress tests across market, rate, currency, allocation-category, and security-level shocks.
- Expands manually supplied or explicitly approved fund holdings into effective company, sector, geography, currency, and asset-class exposure, including fund overlap and unmapped coverage.
- Estimates volatility, drawdown, correlation, beta, and holding-level risk contribution from cached five-year adjusted histories, with manual security, benchmark, and FX imports for offline use.
- Records outbound Yahoo Finance, Google Finance, and Frankfurter calls in `logs/external_api.log`, including provider, status, and duration. Logs rotate at 10 MB with seven files retained; URLs are recorded without queries and no response data or headers are logged.
- Tracks fund expense ratios, advisory fees, named account fees, reserve-aware cash drag, and 1/10/20/30-year nominal and opportunity costs.
- Resolves each listed security's exchange and investment country at import, with manual correction when a ticker cannot be resolved.
- Supports per-import field locks to retain selected prior holding values such as cost basis.
- Refreshes market prices per security or globally through a Yahoo-style quote adapter.

Public fund metadata and historical market data are optional and token-free. Public fund holdings and expense ratios are saved only after review; manual metadata and manual price histories are authoritative and are not overwritten by refreshes. Coverage, freshness, and missing-data limitations are shown with the resulting analytics.

The encrypted in-memory database is a single-process design. Run one Uvicorn worker; multiple workers would have separate in-memory copies of the portfolio. Multiple browser sessions are supported by the one process while the portfolio remains unlocked. Use the global lock action to revoke every session.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

cd frontend
npm install
npm run build
cd ..

uvicorn backend.app.main:app --reload
```

Then open `http://127.0.0.1:8000`.

## Run with Docker

Docker runs the application as an unprivileged process and bind-mounts `data/` and `logs/` from this directory, so portfolio data and outbound-request logs persist across container replacements.

```bash
./run_in_docker --build
```

This makes the app available only on the local machine at `http://127.0.0.1:8000`. To allow access from the local LAN, explicitly opt into HTTP and name the exact URL opened in the browser:

```bash
PORTFOLIO_TRUSTED_ORIGINS=http://192.168.1.25:8000 ./run_in_docker --insecure
```

The Dockerfile builds natively on x86_64 and ARM64 hosts, including Apple Silicon and ARM Linux. To publish one image for both Linux architectures, use the `docker buildx` command documented at the top of `Dockerfile`.

For network-accessible production deployment with HTTPS, see [PRODUCTION_HTTPS.md](PRODUCTION_HTTPS.md).

Portfolio data exists as SQLite only in memory while the application is unlocked. Committed state is stored in `data/portfolio.db.encrypted` as a passphrase-encrypted container; no plaintext SQLite database or WAL is written to disk. `data/auth.json` contains only the random KDF salt and encrypted passphrase verifier.

During development, the frontend can also run separately:

```bash
cd frontend
npm install
npm run dev
```

The frontend dev server expects the API at `http://127.0.0.1:8000`.
