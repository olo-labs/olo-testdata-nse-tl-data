# Query NSE TL Data with DuckDB, pandas, and Polars

Run these examples from the repository root.

## DuckDB

Read one symbol chronologically:

```sql
SELECT *
FROM read_parquet('database/r/RELIANCE/tl.parquet')
ORDER BY candle_datetime;
```

Compare closing price with all standard TL timeframes:

```sql
SELECT candle_datetime, daily_close,
       daily_tl, weekly_tl, monthly_tl, quarterly_tl
FROM read_parquet('database/r/RELIANCE/tl.parquet')
WHERE candle_datetime >= DATE '2024-01-01'
ORDER BY candle_datetime;
```

Find daily closes above every populated standard TL value:

```sql
SELECT candle_datetime, daily_close,
       daily_tl, weekly_tl, monthly_tl, quarterly_tl
FROM read_parquet('database/r/RELIANCE/tl.parquet')
WHERE daily_close > daily_tl
  AND daily_close > weekly_tl
  AND daily_close > monthly_tl
  AND daily_close > quarterly_tl
ORDER BY candle_datetime DESC;
```

Inventory all files without loading them into Python memory:

```sql
SELECT filename, count(*) AS rows,
       min(candle_datetime) AS first_date,
       max(candle_datetime) AS last_date
FROM read_parquet('database/*/*/tl.parquet', filename = true, union_by_name = true)
GROUP BY filename
ORDER BY filename;
```

## Python with DuckDB

```python
import duckdb

frame = duckdb.execute("""
    SELECT candle_datetime, daily_close, daily_tl, daily_tl_ohlc
    FROM read_parquet(?)
    WHERE candle_datetime BETWEEN ? AND ?
    ORDER BY candle_datetime
""", [
    "database/r/RELIANCE/tl.parquet",
    "2024-01-01",
    "2024-12-31",
]).df()

print(frame.tail())
```

## pandas

```python
import pandas as pd

levels = pd.read_parquet("database/r/RELIANCE/tl.parquet")
levels = levels.sort_values("candle_datetime")
levels["close_minus_daily_tl"] = levels["daily_close"] - levels["daily_tl"]
print(levels.tail())
```

## Polars

```python
import polars as pl

levels = (
    pl.scan_parquet("database/r/RELIANCE/tl.parquet")
    .select("candle_datetime", "daily_close", "weekly_tl", "monthly_tl")
    .sort("candle_datetime")
    .collect()
)
print(levels.tail())
```

## Discover symbols

```python
from pathlib import Path
from urllib.parse import unquote

symbols = sorted(unquote(path.parent.name) for path in Path("database").glob("*/*/tl.parquet"))
print(len(symbols), symbols[:20])
```

## OLO DB Viewer

Double-click `olo-db-viewer.bat`. The viewer reads this repository's local `tl.parquet` files only and charts daily OHLCV together with stored TL/TL-OHLC overlays.

![Temporary OLO DB Viewer interface reference; replace with a TL-specific capture](assets/olo-db-viewer-snapshot.png)

The screenshot filename is stable. Overwrite `docs/assets/olo-db-viewer-snapshot.png` after capturing the TL-specific interface.
