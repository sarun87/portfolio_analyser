# Contributing

Thanks for helping improve Portfolio Analyser. Contributions should preserve the app's local-first privacy model and keep calculations auditable.

## Development setup

Run `./init_portfolio_analyser` to create the Python environment, install backend and frontend dependencies, and build the UI. Run the test suite with `./run_tests`; run `cd frontend && npm run build` to verify the production frontend build.

The backend test suite is under `backend/tests/`; frontend tests are under `frontend/src/test/`. Tests and example statements must use synthetic data only.

## Change guidelines

- Include focused tests for behavior changes, especially portfolio math, imports, refresh/error paths, database compatibility, and security-sensitive behavior.
- Do not commit portfolio databases, statement exports, account identifiers, API credentials, certificates, logs, or backups. Never use real financial statements as test fixtures.
- Preserve existing migration and import compatibility; document any user-visible behavior change.
- Use the SPDX headers described in `README.md` for new first-party source files. Machine-generated and machine-readable files that cannot contain comments are exempt.
- Keep public-data provider calls user initiated and disclose any new provider or data-sharing behavior.

## Pull requests

Describe the problem and behavior change, list tests run, and call out any privacy, migration, dependency, or licensing impact. Do not include generated dependency directories or build output.
