# NSE TL Parquet Data Dictionary

The generated `tl.parquet` schema mirrors the configured database projection,
normally `SELECT *`. The exporter verifies exact column names and order for
every symbol. The fields below are common known columns, not a closed list;
new database columns appear automatically.

| Column | Type | Meaning |
| --- | --- | --- |
| `daily_tl` | `DOUBLE` | Stored daily TL value from the configured upstream calculation. |
| `daily_tl_ohlc` | `DOUBLE` | Stored daily TL value from the upstream OHLC-oriented calculation. |
| `weekly_tl` | `DOUBLE` | Stored weekly TL value aligned to the daily observation. |
| `weekly_tl_ohlc` | `DOUBLE` | Stored weekly OHLC-oriented TL value aligned to the daily observation. |
| `monthly_tl` | `DOUBLE` | Stored monthly TL value aligned to the daily observation. |
| `monthly_tl_ohlc` | `DOUBLE` | Stored monthly OHLC-oriented TL value aligned to the daily observation. |
| `quarterly_tl` | `DOUBLE` | Stored quarterly TL value aligned to the daily observation. |
| `quarterly_tl_ohlc` | `DOUBLE` | Stored quarterly OHLC-oriented TL value aligned to the daily observation. |
| `candle_datetime` | `TIMESTAMP` | Trading-date timestamp and incremental-export watermark. |
| `daily_open` | `DOUBLE` | Daily opening price. |
| `daily_high` | `DOUBLE` | Daily highest price. |
| `daily_low` | `DOUBLE` | Daily lowest price. |
| `daily_close` | `DOUBLE` | Daily closing price. |
| `daily_volume` | `DOUBLE` | Daily traded volume as supplied upstream. |

## Important interpretation note

“TL” is the stored upstream technical-level series. This repository exports the values faithfully but does not claim that every external tool uses the same formula or naming convention. Consumers should document which column they use and avoid silently treating `daily_tl` and `daily_tl_ohlc` as interchangeable.

## Eligibility and nulls

The configured symbol universe includes a symbol when at least one upstream row has `daily_tl > 0`. Once eligible, all configured rows are exported, including rows where individual TL values are zero or null.

Higher-timeframe fields are aligned to daily observations by the source. Null/zero handling should be chosen explicitly by the consumer; forward-filling can change indicator meaning and should not be applied without a documented reason.

## Expected OHLC invariants

- `daily_high >= daily_open`, `daily_close`, and `daily_low` for ordinary candles.
- `daily_low <= daily_open`, `daily_close`, and `daily_high`.
- `daily_volume` should not be negative.
- `candle_datetime` should be unique within a symbol file after a correct incremental export.
