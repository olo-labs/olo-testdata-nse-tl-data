# TL Parquet File Structure

Consumer files use this stable layout:

```text
database/<group>/<symbol>/tl.parquet
```

`<group>` is the lowercase first ASCII alphanumeric character of the symbol, or `_` for other leading characters. The symbol folder is filesystem-safe and URL-decoded by the viewer when displayed.

Examples:

```text
database/2/20MICRONS/tl.parquet
database/a/ABB/tl.parquet
database/r/RELIANCE/tl.parquet
database/t/TCS/tl.parquet
```

## File contract

- One file represents one symbol.
- One row represents one daily `candle_datetime` observation.
- The symbol is encoded by the directory and is not repeated as a Parquet column.
- All configured daily OHLCV and multi-timeframe TL fields are stored together.
- Consumers must order by `candle_datetime` when chronological order matters.

## Glob queries

All symbol files:

```text
database/*/*/tl.parquet
```

DuckDB inventory:

```sql
SELECT filename, count(*) AS rows,
       min(candle_datetime) AS first_date,
       max(candle_datetime) AS last_date
FROM read_parquet('database/*/*/tl.parquet', filename = true, union_by_name = true)
GROUP BY filename
ORDER BY filename;
```

## Temporary and local files

| Path | Role |
| --- | --- |
| `database/_temp/` | DuckDB spill space for bounded-memory exports |
| `scripts/config.json` | Ignored local connection/configuration file |
| `scripts/.python/` | Private Python runtime created by the launcher when needed |
| `scripts/.venv/` | Private exporter dependencies |
| `olo-db-viewer/.venv/` | Viewer-only dependencies |
| `olo-db-viewer/viewer_state.json` | Ignored local UI selections/colors |

Temporary export names such as `tl.tmp.parquet` and `tl.delta.parquet` must not be treated as completed consumer files.
