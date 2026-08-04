# OLO DB Viewer

Repository-local Windows desktop checker for this repository's NSE multi-timeframe TL Parquet database.

## Launch

Double-click `olo-db-viewer.bat` here or in the repository root. The first launch creates `olo-db-viewer/.venv` and installs pinned dependencies; later launches reuse that environment.

The app always reads `../database/*/*/tl.parquet` from this repository. It does not accept an external database override and does not read the OHLC/delivery repository.

## TL database checks

Select a symbol, aggregation timeframe, and cutoff to inspect daily OHLCV together with the stored TL series:

- Daily TL and Daily TL OHLC
- Weekly TL and Weekly TL OHLC
- Monthly TL and Monthly TL OHLC
- Quarterly TL and Quarterly TL OHLC

The Indicators menu also provides locally calculated EMA, AMA, Super Trend, RSI, and Anchored VWAP overlays for chart inspection. Visible-bars and end-time controls allow historical slices without later rows entering calculations. UI selections and colors are stored in ignored `viewer_state.json`.

For the authoritative file contract and queries, use the repository [data dictionary](../docs/DATA_DICTIONARY.md) and [quick start](../docs/QUICKSTART.md).
