# Search and AI Discoverability Guide

This guide helps maintainers keep the NSE TL Parquet dataset understandable to GitHub visitors, search engines, dataset catalogues, and AI retrieval systems. Documentation can improve relevance and clarity, but cannot guarantee a top search ranking.

## Recommended GitHub description

```text
NSE India daily OHLCV with Daily, Weekly, Monthly and Quarterly TL/TL-OHLC data, stored as one query-ready Parquet file per symbol.
```

## Recommended GitHub topics

```text
nse  nse-india  indian-stock-market  ohlcv  parquet  duckdb
technical-analysis  market-data  historical-data  quantitative-finance
pandas  polars
```

These must be configured in GitHub; Markdown cannot set repository topics.

## Search phrases covered by the documentation

- NSE technical levels dataset
- NSE TL data download
- Indian stock market OHLCV Parquet
- NSE daily weekly monthly quarterly levels
- NSE support resistance historical data
- DuckDB NSE historical data
- pandas and Polars Indian equity data
- one Parquet file per NSE symbol

Use phrases naturally. Repetition without useful information harms readability and search quality.

## Machine-readable entry points

| File | Purpose |
| --- | --- |
| `metadata/dataset.jsonld` | Schema.org dataset metadata |
| `metadata/parquet-schema.json` | Ordered fields, nullability, and Parquet types |
| `llms.txt` | Compact AI/retrieval index |
| `CITATION.cff` | GitHub citation UI and research tools |
| `README.md` | Main human and crawler landing page |

## Facts that must remain synchronized

- Consumer path: `database/<group>/<symbol>/tl.parquet`.
- One file represents one symbol.
- The schema contains 14 ordered columns.
- Eight columns contain Daily/Weekly/Monthly/Quarterly TL and TL-OHLC values.
- Five columns contain daily OHLCV; `candle_datetime` is the timestamp.
- Consumers must order rows by `candle_datetime`.
- The exporter reads upstream calculated TL values and does not define their formula.
- This repository does not contain delivery quantity or delivery percentage.

## Public release checklist

1. Use a stable tag and descriptive release title.
2. Publish minimum/maximum `candle_datetime`, symbol count, file count, and row count.
3. Provide SHA-256 checksums for archives.
4. State the schema version and whether historical rows changed.
5. Link to the data dictionary, quality guide, license, and known limitations.
6. Keep versioned releases immutable when practical.

## Maintenance

- Validate internal links and JSON files after documentation changes.
- Update README, data dictionary, schema JSON, FAQ, and `llms.txt` together after contract changes.
- Avoid hard-coded coverage dates unless automation keeps them current.
- Use descriptive image alt text.
- Encourage research and downstream tools to link to the canonical repository URL.
