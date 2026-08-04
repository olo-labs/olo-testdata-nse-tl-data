# TL Dataset Quality and Validation

Run the exporter’s offline validation before consuming a generated database:

```powershell
.\scripts\run.ps1 -VerifyOnly
```

## Verify the schema

```sql
DESCRIBE SELECT * FROM read_parquet('database/r/RELIANCE/tl.parquet');
```

Compare the result with [DATA_DICTIONARY.md](DATA_DICTIONARY.md).

## Duplicate timestamps

```sql
SELECT candle_datetime, count(*) AS occurrences
FROM read_parquet('database/r/RELIANCE/tl.parquet')
GROUP BY candle_datetime
HAVING count(*) > 1;
```

## Invalid OHLC bounds

```sql
SELECT *
FROM read_parquet('database/r/RELIANCE/tl.parquet')
WHERE daily_high < greatest(daily_open, daily_low, daily_close)
   OR daily_low > least(daily_open, daily_high, daily_close);
```

## Null and non-finite audit

```sql
SELECT
  count(*) AS rows,
  count(daily_tl) AS daily_tl_rows,
  count(weekly_tl) AS weekly_tl_rows,
  count(monthly_tl) AS monthly_tl_rows,
  count(quarterly_tl) AS quarterly_tl_rows
FROM read_parquet('database/r/RELIANCE/tl.parquet');
```

## Known limitations

- The repository exports upstream TL values; it does not recompute or independently certify their formulas.
- Coverage and null patterns vary by symbol and upstream availability.
- Historical values may change after an upstream correction and later incremental/full export.
- Prices are not guaranteed to be adjusted for corporate actions.
- Symbol changes and security-master history are not normalized here.
- Higher-timeframe values are stored on daily rows; consumers must not mistake repetition/alignment for new weekly, monthly, or quarterly observations.
- A passing structural validation does not establish fitness for live trading or investment decisions.

Record the Git commit, source watermark/date, configuration, and export mode used by reproducible analyses.
