# Contributing

Contributions that improve reproducibility, correctness, portability, or documentation are welcome.

## Useful contribution areas

- Reproducible validation reports and queries.
- DuckDB, pandas, Polars, R, Julia, or Spark usage recipes.
- Tests for incremental export and atomic replacement.
- Safer error handling that never exposes credentials.
- Cross-platform launchers and TL viewer improvements.
- Documentation corrections verified against actual Parquet files.

## Before submitting

1. Never commit `scripts/config.json`, passwords, connection strings, or private infrastructure details.
2. Keep the symbol paths and 14-column schema backward compatible unless proposing a documented version change.
3. Run `.\scripts\run.ps1 -VerifyOnly` when local files are available.
4. Compile Python changes and test a small symbol set before a complete export.
5. Update the README, data dictionary, schema JSON, FAQ, and `llms.txt` together when the contract changes.
6. Keep claims factual: this repository contains TL and daily OHLCV, not delivery quantity or delivery percentage.

## Reporting data issues

Include the symbol, `candle_datetime`, affected columns, repository commit/release, and a minimal query demonstrating the issue. Do not include credentials.

## Documentation style

- Define acronyms and exact columns.
- Prefer runnable examples over broad claims.
- Avoid promising search ranking, completeness, or trading performance.
- Link to the canonical repository and authoritative file contract.
