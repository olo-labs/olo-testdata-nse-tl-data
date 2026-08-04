# Citus trade-log to Parquet exporter

This project uses DuckDB to discover every equity in a Citus/PostgreSQL table and stream that equity's rows into its own compressed Parquet file. Python never loads the result rows into memory.

The output follows the existing OLO symbol database layout:

```text
database/
  a/
    ABC/
      tl.parquet
  3/
    3MINDIA/
      tl.parquet
```

## Configure

Copy `scripts/config.example.json` to the ignored `scripts/config.json`, then set the actual schema, table, equity column, selected columns, and optional SQL filter. Column names in `columns` and `order_by` are validated identifiers. `where` is intended for a trusted, repository-owned filter such as `series = 'EQ'`.

Connection values can be stored directly in the ignored local `scripts/config.json`
for double-click operation, or supplied through environment variables as shown below
(use the Citus coordinator as the host):

```powershell
$env:CITUS_HOST = "citus-coordinator.example.com"
$env:CITUS_PORT = "5432"
$env:CITUS_DATABASE = "market_data"
$env:CITUS_USER = "readonly_exporter"
$env:CITUS_PASSWORD = "..."
```

The database user needs only `CONNECT`, `USAGE` on the configured schema, and
`SELECT` on the source table. The local `scripts/config.json` is excluded from Git,
and credentials are never printed in console logs.

## Run

First test one equity or a small number:

```powershell
Copy-Item .\scripts\config.example.json .\scripts\config.json
.\scripts\run.ps1 -Equity RELIANCE
.\scripts\run.ps1 -LimitEquities 5 -Refresh
```

Export all equities:

```powershell
.\scripts\run.ps1
```

One-click Windows commands:

```bat
create.bat
incremental.bat
```

`create.bat` first deletes the complete configured generated `database` directory,
then rebuilds every equity file from the source table. This also removes stale
symbols and abandoned temporary files. `incremental.bat`
reads the maximum configured `incremental_column` from each existing Parquet,
adds only newer source rows, and creates files for equities that do not exist
locally yet. For this dataset the incremental column is `candle_datetime`.

Both commands print detailed live progress to the console: startup settings,
connection/discovery phases, the current symbol and action, completed and total
symbols, overall percentage, elapsed time, estimated time remaining, incremental
watermarks, rows written, output paths, errors, and a final summary. Database
credentials are never included in these logs.

No preinstalled Python is required. On the first run, the launcher downloads the
official signed Python 3.12 installer from `python.org`, verifies its Windows
Authenticode signature, installs a private runtime under `scripts/.python`, creates
`scripts/.venv`, and installs DuckDB. Later runs reuse those local components.

Existing files are skipped, so an interrupted run can be restarted. Use `-Refresh` to atomically replace them. A file is first written as `tl.tmp.parquet`, checked for readable metadata, and then renamed to `tl.parquet`.

Validate every completed file without connecting to Citus:

```powershell
.\scripts\run.ps1 -VerifyOnly
```

## Large-data behavior

- DuckDB's PostgreSQL extension reads from the Citus coordinator and pushes the equality filter for each equity into PostgreSQL.
- Only one equity is exported at a time, bounding local memory and database concurrency.
- DuckDB spills to `database/_temp` after reaching `duckdb.memory_limit`.
- Zstandard compression and 122,880-row row groups are the defaults; both are configurable.
- Add the table's Citus distribution/partition key to `equity_column` when possible. An index on that column also helps the distinct-equity discovery query.
- Leave `order_by` empty for maximum throughput. Add a timestamp column only if consumers require physical chronological order; sorting very large equities requires additional temporary disk.

DuckDB installs its `postgres` extension on the first connected run, so that run requires internet access. Later runs use the cached extension.
