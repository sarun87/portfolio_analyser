# Test Broker Statements

Synthetic CSV statement files for application and UI testing. These are not real account statements and do not contain real account data.

## Files

- `etrade_statement_2026-06-30.csv`
- `charles_schwab_statement_2026-06-30.csv`
- `morgan_stanley_statement_2026-06-30.csv`
- `fidelity_statement_2026-06-30.csv`
- `vanguard_statement_2026-06-30.csv`
- `multi_lot_fidelity_statement_2026-07-31.csv`
- `ibkr_statement_2026-06-30.csv`
- `hdfc_securities_statement_2026-06-30.csv`

## Suggested Test Flow

1. Start the app with `./run_portfolio_analyser`.
2. Unlock or create the app passphrase.
3. Go to Upload.
4. Pick the matching broker for each file.
5. Upload the CSV, preview the mapped columns, then commit.
6. Use the multi-lot Fidelity file to verify multiple lots for the same security.
7. Choose Interactive Brokers (IBKR) for the Open Positions-style CSV fixture, or HDFC Securities for the India holdings fixture.

The files include a mix of S&P 500 companies, broad market ETFs, international ETFs, bond funds, mutual funds, and cash rows.
