# Frequently Asked Questions About NSE TL Parquet Data

## What does this repository contain?

It contains one `tl.parquet` per qualifying NSE symbol with daily OHLCV plus Daily, Weekly, Monthly, and Quarterly TL and TL-OHLC values.

## Where is a symbol stored?

At `database/<lowercase-first-character>/<symbol>/tl.parquet`, for example `database/r/RELIANCE/tl.parquet`.

## What is TL data?

TL refers to the upstream technical-level series exported by this project. Both standard and OHLC-oriented forms are retained. See [DATA_DICTIONARY.md](DATA_DICTIONARY.md) and document the exact column used in research.

## Does the repository calculate TL values locally?

No. The exporter streams already-calculated columns from the configured Citus/PostgreSQL table into local Parquet files. The repository-local viewer reads only those generated files.

## How many timeframes are available?

Daily, Weekly, Monthly, and Quarterly TL values are stored on each daily row when available. The file also includes daily OHLCV.

## Is row order guaranteed?

No. Use `ORDER BY candle_datetime` or sort your DataFrame.

## How do I update the files?

Use `incremental.bat` to append rows newer than each symbol’s latest `candle_datetime`. Use `create.bat` for a complete recreation.

## Can I query every symbol together?

Yes. DuckDB can scan `database/*/*/tl.parquet` with `union_by_name = true` and optionally `filename = true`.

## Is this official NSE software or investment advice?

No. This is an independent community repository, is not affiliated with or endorsed by NSE, and does not provide investment advice.
