from __future__ import annotations

import queue
import json
import math
import colorsys
import threading
import tkinter as tk
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import colorchooser, messagebox, ttk
from urllib.parse import unquote

import duckdb
import matplotlib.ticker as mticker
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from PIL import Image, ImageTk
from tkcalendar import DateEntry


APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parent
DATABASE = REPO_ROOT / "database"
INDICATOR_CONFIG = APP_DIR / "indicators.json"
VIEWER_STATE = APP_DIR / "viewer_state.json"
LOGO_PATH = APP_DIR / "olo-logo.png"
MAX_VISIBLE_BARS = 5000
MIN_VISIBLE_BARS = 10
DEFAULT_VISIBLE_BARS = 280
HIGHER_TIMEFRAME_BARS = {
    "Day": DEFAULT_VISIBLE_BARS,
    "Week": DEFAULT_VISIBLE_BARS,
    "Month": DEFAULT_VISIBLE_BARS,
    "Quarter": DEFAULT_VISIBLE_BARS,
    "Year": DEFAULT_VISIBLE_BARS,
}

INTERVALS = {
    "Day": ("tl", "date_trunc('day', candle_datetime)"),
    "Week": ("tl", "date_trunc('week', candle_datetime)"),
    "Month": ("tl", "date_trunc('month', candle_datetime)"),
    "Quarter": ("tl", "date_trunc('quarter', candle_datetime)"),
    "Year": ("tl", "date_trunc('year', candle_datetime)"),
}

TIMEFRAME_PREFIX = {"15m": "15m", "Day": "D", "Week": "W", "Month": "M", "Quarter": "Q"}
TIMEFRAME_RANK = {"1m": 0, "5m": 1, "15m": 2, "Day": 3, "Week": 4, "Month": 5, "Quarter": 6}
INDICATOR_COLORS = ["#38bdf8", "#fbbf24", "#f97316", "#e879f9", "#a3e635", "#fb7185", "#2dd4bf"]
CONTRAST_COLORS = [
    "#e6194b", "#3cb44b", "#ffe119", "#4363d8", "#f58231", "#911eb4", "#42d4f4",
    "#f032e6", "#bfef45", "#fabed4", "#469990", "#dcbeff", "#9a6324", "#fffac8",
    "#800000", "#aaffc3", "#808000", "#ffd8b1", "#000075", "#a9a9a9",
]
for color_index in range(40):
    hue = (color_index * 0.61803398875) % 1.0
    red, green, blue = colorsys.hsv_to_rgb(hue, .72, .95)
    CONTRAST_COLORS.append(f"#{round(red * 255):02x}{round(green * 255):02x}{round(blue * 255):02x}")


def load_indicator_config(path: Path = INDICATOR_CONFIG) -> tuple[list[dict], int]:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Unable to read indicator configuration {path.name}: {error}") from error
    expanded = []
    for group in config.get("indicators", []):
        kind = str(group.get("type", "")).upper()
        if kind == "EMA":
            for color_index, value in enumerate(group.get("periods", [])):
                period = int(value)
                if period > 0:
                    expanded.append({"type": "EMA", "timeframe": "chart", "period": period,
                                     "label": f"EMA({period})",
                                     "color": INDICATOR_COLORS[color_index % len(INDICATOR_COLORS)]})
        elif kind == "SUPERTREND":
            period = int(group.get("period", 10))
            multiplier = float(group.get("multiplier", 3))
            expanded.append({"type": "SUPERTREND", "timeframe": "chart", "period": period,
                             "multiplier": multiplier, "label": f"Super Trend({period},{multiplier:g})",
                             "color": INDICATOR_COLORS[-1]})
        elif kind == "AMA":
            efficiency_period = int(group.get("efficiency_period", 10))
            fast_period = int(group.get("fast_period", 2))
            slow_period = int(group.get("slow_period", 30))
            if efficiency_period > 0 and 0 < fast_period < slow_period:
                expanded.append({"type": "AMA", "timeframe": "chart",
                                 "efficiency_period": efficiency_period,
                                 "fast_period": fast_period, "slow_period": slow_period,
                                 "label": f"AMA({efficiency_period},{fast_period},{slow_period}) OHLC/4",
                                 "color": "#60a5fa"})
    vwap_colors = {"Year": "#f43f5e", "Quarter": "#f97316", "Month": "#eab308",
                   "Week": "#14b8a6", "Day": "#0ea5e9"}
    for anchor in config.get("anchored_vwap", {}).get("anchors", []):
        if anchor in vwap_colors:
            expanded.append({"type": "ANCHORED_VWAP", "timeframe": anchor, "anchor": anchor,
                             "label": f"{anchor[0]} Anchored VWAP", "color": vwap_colors[anchor]})
    relative_colors = {"nifty": "#22d3ee", "sector": "#f59e0b"}
    for series in config.get("relative_close", {}).get("series", []):
        source = series.get("source")
        if source in relative_colors:
            expanded.append({"type": "COMPARISON_CLOSE", "timeframe": "Relative", "source": source,
                             "label": series.get("label", f"{source.title()} Close %"),
                             "color": relative_colors[source]})
    for index, column in enumerate((
        "daily_tl", "daily_tl_ohlc", "weekly_tl", "weekly_tl_ohlc",
        "monthly_tl", "monthly_tl_ohlc", "quarterly_tl", "quarterly_tl_ohlc",
    ), start=8):
        expanded.append({"type": "STORED_TL", "timeframe": "chart", "column_index": index,
                         "label": column.replace("_", " ").upper(),
                         "color": CONTRAST_COLORS[index - 8]})
    return expanded, max(1, int(config.get("rsi", {}).get("period", 14)))


def load_rsi_definitions(path: Path = INDICATOR_CONFIG) -> list[dict]:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rsi_config = config.get("rsi", {})
    period = max(1, int(rsi_config.get("period", 14)))
    return [{"timeframe": "chart", "period": period, "label": f"RSI({period})",
             "color": "#22d3ee", "source": "chart"}]


def load_market_config(path: Path = INDICATOR_CONFIG) -> dict:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"nifty_symbol": "NIFTY 50", "sector_symbol_filter": "NIFTY",
                "default_sector_symbol": "NIFTY BANK"}
    return config.get("market_symbols", {})


def ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (period + 1)
    result = [float(values[0])]
    for value in values[1:]:
        result.append(alpha * float(value) + (1 - alpha) * result[-1])
    return result


def latest_finite(values) -> float | None:
    for value in reversed(list(values)):
        if value is not None and math.isfinite(float(value)):
            return float(value)
    return None


def anchored_vwap(rows: list[tuple], anchor: str) -> list[float]:
    result = []
    current_bucket = None
    price_volume = volume_total = 0.0
    for row in rows:
        bucket = _bucket_start(row[0], anchor)
        if bucket != current_bucket:
            current_bucket, price_volume, volume_total = bucket, 0.0, 0.0
        typical_price = (float(row[2]) + float(row[3]) + float(row[4])) / 3.0
        volume = float(row[5] or 0)
        if volume:
            price_volume += typical_price * volume
            volume_total += volume
        result.append(price_volume / volume_total if volume_total else typical_price)
    return result


def adaptive_moving_average(rows: list[tuple], efficiency_period: int = 10,
                            fast_period: int = 2, slow_period: int = 30) -> list[float]:
    """NautilusTrader AMA fed with each bar's OHLC/4 price."""
    prices = [sum(float(row[index]) for index in (1, 2, 3, 4)) / 4.0 for row in rows]
    if not prices:
        return []
    alpha_fast = 2.0 / (fast_period + 1)
    alpha_slow = 2.0 / (slow_period + 1)
    inputs: list[float] = []
    deltas: list[float] = []
    result = []
    current = prices[0]
    for price in prices:
        inputs.append(price)
        if len(inputs) > efficiency_period:
            inputs.pop(0)
        efficiency_ratio = 0.0
        if len(inputs) >= 2:
            deltas.append(abs(inputs[-1] - inputs[-2]))
            if len(deltas) > efficiency_period:
                deltas.pop(0)
            volatility = abs(sum(deltas))
            efficiency_ratio = 0.0 if volatility == 0 else abs(inputs[-1] - inputs[0]) / volatility
        if result:
            smoothing = (efficiency_ratio * (alpha_fast - alpha_slow) + alpha_slow) ** 2
            current = smoothing * (price - current) + current
        else:
            current = price
        result.append(current)
    return result


def align_series(target_rows: list[tuple], source_rows: list[tuple], values: list[float]) -> list[float]:
    value_by_stamp = {row[0]: value for row, value in zip(source_rows, values)}
    return [value_by_stamp.get(row[0], math.nan) for row in target_rows]


def rsi(values: list[float], period: int = 14) -> list[float]:
    """Exponentially smoothed RSI on the conventional 0..100 scale."""
    if not values:
        return []
    result = []
    alpha = 2.0 / (period + 1)
    average_gain = average_loss = 0.0
    last_value = float(values[0])
    for raw_value in values:
        value = float(raw_value)
        change = value - last_value
        gain, loss = max(change, 0.0), max(-change, 0.0)
        if not result:
            average_gain, average_loss = gain, loss
        else:
            average_gain = alpha * gain + (1 - alpha) * average_gain
            average_loss = alpha * loss + (1 - alpha) * average_loss
        normalized = 1.0 if average_loss == 0 else 1.0 - 1.0 / (1.0 + average_gain / average_loss)
        result.append(normalized * 100.0)
        last_value = value
    return result


def _bucket_start(stamp: date | datetime, timeframe: str) -> date:
    if timeframe == "15m":
        value = stamp if isinstance(stamp, datetime) else datetime.combine(stamp, datetime.min.time())
        return value.replace(minute=(value.minute // 15) * 15, second=0, microsecond=0)
    value = stamp.date() if isinstance(stamp, datetime) else stamp
    if timeframe == "Week":
        return value - timedelta(days=value.weekday())
    if timeframe == "Month":
        return value.replace(day=1)
    if timeframe == "Quarter":
        return value.replace(month=((value.month - 1) // 3) * 3 + 1, day=1)
    if timeframe == "Year":
        return value.replace(month=1, day=1)
    return value


def indicator_applies(chart_interval: str, indicator_timeframe: str) -> bool:
    if indicator_timeframe == "chart":
        return True
    if chart_interval in {"1m", "5m", "15m"}:
        return TIMEFRAME_RANK.get(indicator_timeframe, -1) >= TIMEFRAME_RANK[chart_interval]
    if chart_interval == "Day":
        return indicator_timeframe in {"Day", "Week", "Month", "Quarter"}
    return indicator_timeframe == chart_interval


def _next_bucket_start(bucket: date, timeframe: str) -> date:
    if timeframe == "Week":
        return bucket + timedelta(days=7)
    if timeframe == "Month":
        return (bucket.replace(day=28) + timedelta(days=4)).replace(day=1)
    if timeframe == "Quarter":
        month = bucket.month + 3
        return date(bucket.year + (month - 1) // 12, (month - 1) % 12 + 1, 1)
    if timeframe == "Year":
        return date(bucket.year + 1, 1, 1)
    return bucket + timedelta(days=1)


def aggregate_candles(rows: list[tuple], timeframe: str) -> list[tuple]:
    """Aggregate daily rows using the same period boundaries as DuckDB date_trunc."""
    result = []
    for row in rows:
        bucket = _bucket_start(row[0], timeframe)
        if not result or result[-1][0] != bucket:
            result.append([bucket, row[1], row[2], row[3], row[4], row[5] or 0,
                           row[6], row[6] or 0, row[5] or 0])
            continue
        bar = result[-1]
        bar[2], bar[3], bar[4] = max(bar[2], row[2]), min(bar[3], row[3]), row[4]
        bar[5] += row[5] or 0
        if row[6] is not None:
            bar[6] = (bar[6] or 0) + row[6]
            bar[7] += row[6]
        bar[8] += row[5] or 0
    return [tuple(bar[:7] + [bar[7] * 100.0 / bar[8] if bar[8] and bar[6] is not None else None])
            for bar in result]


def expand_completed_values(daily_rows: list[tuple], timeframe: str,
                            period_rows: list[tuple], values: list[float]) -> list[float]:
    """Repeat each as-of higher-timeframe value across its matching daily period."""
    period_values = {row[0]: value for row, value in zip(period_rows, values)}
    return [period_values.get(_bucket_start(row[0], timeframe), math.nan) for row in daily_rows]


def supertrend(rows: list[tuple], period: int = 10, multiplier: float = 3) -> list[float]:
    result = [math.nan] * len(rows)
    if len(rows) < period:
        return result
    ranges = []
    for i, row in enumerate(rows):
        high, low = float(row[2]), float(row[3])
        previous_close = float(rows[i - 1][4]) if i else float(row[4])
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    # NautilusTrader AverageTrueRange defaults to a partial-window SIMPLE MA.
    atr = []
    rolling_sum = 0.0
    for i, value in enumerate(ranges):
        rolling_sum += value
        if i >= period:
            rolling_sum -= ranges[i - period]
        atr.append(rolling_sum / min(i + 1, period))
    upper = lower = math.nan
    rising = True
    for i in range(len(rows)):
        high, low, close = map(float, (rows[i][2], rows[i][3], rows[i][4]))
        middle = (high + low) / 2
        basic_upper, basic_lower = middle + multiplier * atr[i], middle - multiplier * atr[i]
        previous_close = float(rows[i - 1][4]) if i else close
        if i == 0:
            upper, lower = basic_upper, basic_lower
        else:
            upper = basic_upper if basic_upper < upper or previous_close > upper else upper
            lower = basic_lower if basic_lower > lower or previous_close < lower else lower
        if rising and close < lower:
            rising = False
        elif not rising and close > upper:
            rising = True
        result[i] = lower if rising else upper
    return result


def available_symbols() -> list[str]:
    symbols = []
    if DATABASE.is_dir():
        for group in DATABASE.iterdir():
            if group.is_dir() and not group.name.startswith("_"):
                for folder in group.iterdir():
                    if folder.is_dir() and (folder / "tl.parquet").exists():
                        symbols.append(unquote(folder.name))
    return sorted(set(symbols))


def symbol_file(symbol: str, timeframe: str) -> Path:
    first = symbol[:1].lower()
    group = first if first.isascii() and first.isalnum() else "_"
    # Generated NSE symbols use filesystem-safe names. Locate by decoded folder
    # name as a fallback so symbols containing escaped characters also work.
    direct = DATABASE / group / symbol / "tl.parquet"
    if direct.exists():
        return direct
    for folder in (DATABASE / group).iterdir():
        if unquote(folder.name) == symbol:
            return folder / "tl.parquet"
    return direct


def load_candles(symbol: str, interval: str, as_of: datetime | None = None) -> list[tuple]:
    timeframe, bucket = INTERVALS[interval]
    path = symbol_file(symbol, timeframe)
    if not path.exists():
        raise FileNotFoundError(f"No {timeframe} data is available for {symbol}.")
    parameters: list = [str(path)]
    source_sql = "SELECT * FROM read_parquet(?)"
    if as_of is not None:
        source_sql += " WHERE candle_datetime <= ?"
        parameters.append(as_of)
    query = f"""
        WITH source AS ({source_sql}),
        bars AS (
            SELECT {bucket} AS bucket,
                   arg_min(daily_open, candle_datetime) AS open,
                   max(daily_high) AS high,
                   min(daily_low) AS low,
                   arg_max(daily_close, candle_datetime) AS close,
                   sum(daily_volume) AS volume,
                   arg_max(daily_tl, candle_datetime) AS daily_tl,
                   arg_max(daily_tl_ohlc, candle_datetime) AS daily_tl_ohlc,
                   arg_max(weekly_tl, candle_datetime) AS weekly_tl,
                   arg_max(weekly_tl_ohlc, candle_datetime) AS weekly_tl_ohlc,
                   arg_max(monthly_tl, candle_datetime) AS monthly_tl,
                   arg_max(monthly_tl_ohlc, candle_datetime) AS monthly_tl_ohlc,
                   arg_max(quarterly_tl, candle_datetime) AS quarterly_tl,
                   arg_max(quarterly_tl_ohlc, candle_datetime) AS quarterly_tl_ohlc
            FROM source
            GROUP BY 1
        )
        SELECT bucket, open, high, low, close, volume, NULL::BIGINT, NULL::DOUBLE,
               daily_tl, daily_tl_ohlc, weekly_tl, weekly_tl_ohlc,
               monthly_tl, monthly_tl_ohlc, quarterly_tl, quarterly_tl_ohlc
        FROM bars ORDER BY bucket
    """
    connection = duckdb.connect()
    try:
        rows = connection.execute(query, parameters).fetchall()
    finally:
        connection.close()
    return rows


def load_comparison_candles(symbol: str, interval: str, as_of: datetime) -> list[tuple]:
    return load_candles(symbol, interval, as_of)


class OloDbViewer(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("OLO DB Viewer")
        self.geometry("1380x850")
        self.minsize(900, 600)
        self.configure(bg="#0b1118")
        logo = Image.open(LOGO_PATH).convert("RGBA")
        self.logo_icon = ImageTk.PhotoImage(logo.resize((64, 48), Image.Resampling.LANCZOS))
        header_logo = Image.new("RGBA", logo.size, "#f4f7fb")
        header_logo.putalpha(logo.getchannel("A"))
        self.logo_header = ImageTk.PhotoImage(header_logo.resize((56, 42), Image.Resampling.LANCZOS))
        self.iconphoto(True, self.logo_icon)
        self.results: queue.Queue = queue.Queue()
        self.symbol = tk.StringVar()
        self.interval = tk.StringVar(value="Day")
        self.market_config = load_market_config()
        self.nifty_symbol = self.market_config.get("nifty_symbol", "NIFTY 50")
        self.sector_symbol = tk.StringVar(value=self.market_config.get("default_sector_symbol", "NIFTY BANK"))
        now = datetime.now()
        self.as_of_date_text = tk.StringVar(value=now.strftime("%Y-%m-%d"))
        self.as_of_hour = tk.StringVar(value=now.strftime("%H"))
        self.as_of_minute = tk.StringVar(value=now.strftime("%M"))
        self.show_volume = tk.BooleanVar(value=True)
        self.show_delivery = tk.BooleanVar(value=False)
        self.show_percent = tk.BooleanVar(value=False)
        try:
            self.indicator_definitions, self.rsi_period = load_indicator_config()
            self.rsi_definitions = load_rsi_definitions()
            indicator_error = ""
        except ValueError as error:
            self.indicator_definitions, self.rsi_period = [], 14
            self.rsi_definitions = []
            indicator_error = str(error)
        self.indicator_vars = {
            definition["label"]: tk.BooleanVar(value=False)
            for definition in self.indicator_definitions
        }
        self.rsi_vars = {definition["label"]: tk.BooleanVar(value=False)
                         for definition in self.rsi_definitions}
        self._load_ui_state()
        self._ensure_unique_active_colors("price")
        self._ensure_unique_active_colors("bottom")
        self.bar_count = tk.IntVar(value=DEFAULT_VISIBLE_BARS)
        self.bar_count_label = tk.StringVar(value=f"{DEFAULT_VISIBLE_BARS} bars")
        self.end_index = tk.IntVar(value=0)
        self.range_label = tk.StringVar(value="Oldest  —  Newest")
        self.status = tk.StringVar(value=indicator_error or "Loading symbols…")
        self.current_chart: tuple[str, str, list[tuple]] | None = None
        self.loaded_as_of: datetime | None = None
        self.comparison_rows: dict[str, list[tuple]] = {"nifty": [], "sector": []}
        self.panel_mode = "split"
        self.zoom_job: str | None = None
        self.visible_rows: list[tuple] = []
        self.visible_start = 0
        self.price_axis = None
        self.price_axes = []
        self.metric_axis = None
        self.bottom_axes = []
        self.tooltip = None
        self.bottom_tooltip = None
        self.tooltip_index: int | None = None
        self.bottom_tooltip_index: int | None = None
        self.price_indicator_series: dict[str, list] = {}
        self.bottom_series: dict[str, list] = {}
        self.all_symbols: list[str] = []
        self.symbol_popdown_list = None
        self.symbol_popdown_command = None
        self._build_style()
        self._build_ui()
        self.after(50, self._load_symbols)

    def _build_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        self.option_add("*TCombobox*Listbox.background", "#16212d")
        self.option_add("*TCombobox*Listbox.foreground", "#e8eef5")
        self.option_add("*TCombobox*Listbox.selectBackground", "#1677b8")
        self.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
        self.option_add("*TCombobox*Listbox.font", ("Segoe UI", 10))
        style.configure("TFrame", background="#0b1118")
        style.configure("Panel.TFrame", background="#111a24")
        style.configure("TLabel", background="#0b1118", foreground="#c7d2df", font=("Segoe UI", 10))
        style.configure("Title.TLabel", foreground="#f4f7fb", font=("Segoe UI Semibold", 18))
        style.configure("Logo.TLabel", background="#0b1118")
        style.configure("Muted.TLabel", foreground="#7f91a5", font=("Segoe UI", 9))
        style.configure("TCheckbutton", background="#111a24", foreground="#b9c7d6", font=("Segoe UI", 9))
        style.map("TCheckbutton", background=[("active", "#111a24")])
        style.configure("Symbol.TCombobox", fieldbackground="#142735", background="#142735",
                        foreground="#68d5c0", arrowcolor="#68d5c0", bordercolor="#245567",
                        lightcolor="#245567", darkcolor="#245567", padding=7)
        style.map("Symbol.TCombobox",
                  fieldbackground=[("readonly", "#142735")],
                  foreground=[("readonly", "#d9fff8")],
                  selectbackground=[("readonly", "#142735")],
                  selectforeground=[("readonly", "#d9fff8")],
                  bordercolor=[("focus", "#2dd4bf")])
        style.configure("Interval.TCombobox", fieldbackground="#211d37", background="#211d37",
                        foreground="#c4b5fd", arrowcolor="#c4b5fd", bordercolor="#51448a",
                        lightcolor="#51448a", darkcolor="#51448a", padding=7)
        style.map("Interval.TCombobox",
                  fieldbackground=[("readonly", "#211d37")],
                  foreground=[("readonly", "#eeeaff")],
                  selectbackground=[("readonly", "#211d37")],
                  selectforeground=[("readonly", "#eeeaff")],
                  bordercolor=[("focus", "#a78bfa")])
        style.configure("Accent.TButton", background="#1d9bf0", foreground="white", padding=(16, 8), font=("Segoe UI Semibold", 10))
        style.map("Accent.TButton", background=[("active", "#3aacf4"), ("disabled", "#33404d")])
        style.configure("Zoom.Horizontal.TScale", background="#111a24", troughcolor="#253647",
                        bordercolor="#111a24", lightcolor="#1d9bf0", darkcolor="#1d9bf0")

    def _build_ui(self) -> None:
        header = ttk.Frame(self, padding=(22, 16))
        header.pack(fill="x")
        ttk.Label(header, image=self.logo_header, style="Logo.TLabel").pack(side="left")
        ttk.Label(header, text="OLO DB Viewer", style="Title.TLabel").pack(side="left", padx=(12, 0))
        ttk.Label(header, text="Repository-local TL Parquet explorer", style="Muted.TLabel").pack(side="left", padx=(14, 0), pady=(7, 0))

        controls = ttk.Frame(self, style="Panel.TFrame", padding=(18, 14))
        controls.pack(fill="x", padx=22, pady=(0, 12))
        ttk.Label(controls, text="SYMBOL · TYPE TO SEARCH", style="Muted.TLabel", background="#111a24").grid(row=0, column=0, sticky="w")
        ttk.Label(controls, text="TIMEFRAME", style="Muted.TLabel", background="#111a24").grid(row=0, column=1, sticky="w", padx=(14, 0))
        ttk.Label(controls, text="SHOW CANDLES UP TO", style="Muted.TLabel", background="#111a24").grid(row=0, column=2, sticky="w", padx=(14, 0))
        ttk.Label(controls, text="SECTOR SYMBOL", style="Muted.TLabel", background="#111a24").grid(row=0, column=3, sticky="w", padx=(14, 0))
        self.symbol_box = ttk.Combobox(controls, textvariable=self.symbol, state="normal", width=28,
                                       style="Symbol.TCombobox")
        self.symbol_box.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        self.interval_box = ttk.Combobox(controls, textvariable=self.interval, state="readonly", width=16,
                                         values=list(INTERVALS), style="Interval.TCombobox")
        self.interval_box.grid(row=1, column=1, padx=(14, 0), sticky="ew", pady=(5, 0))
        as_of = ttk.Frame(controls, style="Panel.TFrame")
        as_of.grid(row=1, column=2, padx=(14, 0), pady=(5, 0), sticky="w")
        self.as_of_date = DateEntry(as_of, textvariable=self.as_of_date_text, width=11,
                                    date_pattern="yyyy-mm-dd", background="#1677b8",
                                    foreground="white", borderwidth=1)
        self.as_of_date.pack(side="left")
        self.as_of_date.bind("<<DateEntrySelected>>", lambda _event: self.refresh_chart())
        self.as_of_hour_box = ttk.Spinbox(as_of, from_=0, to=23, width=2, wrap=True,
                                          format="%02.0f", textvariable=self.as_of_hour)
        self.as_of_hour_box.pack(side="left", padx=(6, 0))
        ttk.Label(as_of, text=":", background="#111a24").pack(side="left")
        self.as_of_minute_box = ttk.Spinbox(as_of, from_=0, to=59, width=2, wrap=True,
                                            increment=1, format="%02.0f", textvariable=self.as_of_minute)
        self.as_of_minute_box.pack(side="left")
        self.as_of_hour_box.bind("<Return>", lambda _event: self.refresh_chart())
        self.as_of_minute_box.bind("<Return>", lambda _event: self.refresh_chart())
        ttk.Button(as_of, text="Apply", command=self.refresh_chart).pack(side="left", padx=(5, 0))
        ttk.Button(as_of, text="Now", command=self._use_current_time).pack(side="left", padx=(5, 0))
        self.sector_box = ttk.Combobox(controls, textvariable=self.sector_symbol, state="readonly", width=22,
                                      style="Symbol.TCombobox")
        self.sector_box.grid(row=1, column=3, padx=(14, 0), sticky="ew", pady=(5, 0))
        self.sector_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_chart())
        metrics = ttk.Frame(controls, style="Panel.TFrame")
        metrics.grid(row=1, column=4, padx=20, pady=(5, 0))
        bottom_count = sum(variable.get() for variable in (
            self.show_volume, self.show_delivery, self.show_percent
        )) + sum(variable.get() for variable in self.rsi_vars.values())
        self.bottom_button = ttk.Menubutton(metrics, text=f"Bottom graph ({bottom_count}) ▾")
        self.bottom_menu = tk.Menu(self.bottom_button, tearoff=False, background="#16212d",
                                   foreground="#e8eef5", activebackground="#1677b8",
                                   activeforeground="#ffffff")
        bottom_menu = self.bottom_menu
        self.bottom_button.configure(menu=self.bottom_menu)
        self.bottom_button.pack(side="left")
        for label, variable, color in (
            ("Volume", self.show_volume, "#21c58b"),
        ):
            bottom_menu.add_checkbutton(label=label, variable=variable, indicatoron=True, selectcolor=color,
                                        command=self._bottom_metrics_changed)
        bottom_menu.add_separator()
        for definition in self.rsi_definitions:
            bottom_menu.add_checkbutton(label=definition["label"],
                                        variable=self.rsi_vars[definition["label"]],
                                        indicatoron=True, selectcolor=definition["color"],
                                        command=self._bottom_metrics_changed)
        bottom_menu.add_separator()
        bottom_menu.add_command(label="Customize selected colors…",
                                command=lambda: self._open_color_editor("bottom"))
        bottom_menu.add_command(label="Clear bottom graph", command=self._clear_bottom_metrics)
        indicator_count = sum(variable.get() for variable in self.indicator_vars.values())
        self.indicator_button = ttk.Menubutton(metrics, text=f"Indicators ({indicator_count}) ▾")
        self.indicator_menu = tk.Menu(self.indicator_button, tearoff=False, background="#16212d",
                                      foreground="#e8eef5", activebackground="#1677b8",
                                      activeforeground="#ffffff")
        indicator_menu = self.indicator_menu
        self.indicator_button.configure(menu=self.indicator_menu)
        self.indicator_button.pack(side="left", padx=(12, 0))
        previous_timeframe = None
        for definition in self.indicator_definitions:
            if previous_timeframe is not None and definition["timeframe"] != previous_timeframe:
                indicator_menu.add_separator()
            indicator_menu.add_checkbutton(label=definition["label"],
                                           variable=self.indicator_vars[definition["label"]],
                                           indicatoron=True, selectcolor=definition["color"],
                                           command=self._indicators_changed)
            previous_timeframe = definition["timeframe"]
        if self.indicator_definitions:
            indicator_menu.add_separator()
            indicator_menu.add_command(label="Customize selected colors…",
                                       command=lambda: self._open_color_editor("price"))
            indicator_menu.add_command(label="Clear all indicators", command=self._clear_indicators)
        self.load_button = ttk.Button(controls, text="Load chart", style="Accent.TButton", command=self.refresh_chart)
        self.load_button.grid(row=1, column=5, padx=(12, 0), pady=(5, 0))
        zoom = ttk.Frame(controls, style="Panel.TFrame")
        zoom.grid(row=2, column=0, columnspan=6, sticky="ew", pady=(14, 0))
        ttk.Label(zoom, text="VISIBLE BARS", style="Muted.TLabel", background="#111a24").pack(side="left")
        ttk.Label(zoom, text=str(MIN_VISIBLE_BARS), style="Muted.TLabel", background="#111a24").pack(side="left", padx=(14, 6))
        self.zoom_scale = ttk.Scale(zoom, from_=MIN_VISIBLE_BARS, to=MAX_VISIBLE_BARS, variable=self.bar_count,
                                    orient="horizontal", style="Zoom.Horizontal.TScale",
                                    command=self._zoom_changed)
        self.zoom_scale.pack(side="left", fill="x", expand=True)
        ttk.Label(zoom, text=f"{MAX_VISIBLE_BARS:,}", style="Muted.TLabel", background="#111a24").pack(side="left", padx=(6, 14))
        ttk.Label(zoom, textvariable=self.bar_count_label, foreground="#66c7ff",
                  background="#111a24", font=("Segoe UI Semibold", 9), width=10, anchor="e").pack(side="left")
        timeline = ttk.Frame(controls, style="Panel.TFrame")
        timeline.grid(row=3, column=0, columnspan=6, sticky="ew", pady=(10, 0))
        ttk.Label(timeline, text="END TIME", style="Muted.TLabel", background="#111a24").pack(side="left")
        self.timeline_scale = ttk.Scale(timeline, from_=0, to=0, variable=self.end_index,
                                        orient="horizontal", style="Zoom.Horizontal.TScale",
                                        command=self._timeline_changed)
        self.timeline_scale.pack(side="left", fill="x", expand=True, padx=(14, 14))
        ttk.Label(timeline, textvariable=self.range_label, foreground="#8fa1b4",
                  background="#111a24", font=("Segoe UI", 9), width=46, anchor="e").pack(side="left")
        controls.columnconfigure(0, weight=1)
        self.symbol_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_chart())
        self.symbol_box.bind("<Button-1>", self._prepare_symbol_typing)
        self.symbol_box.bind("<Control-a>", self._select_symbol_text)
        self.symbol_box.bind("<KeyRelease>", self._filter_symbols)
        self.symbol_box.bind("<Return>", self._load_first_symbol_match)
        self.symbol_box.bind("<Escape>", self._restore_symbols)
        self.interval_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_chart())

        self.figure = Figure(facecolor="#0b1118", constrained_layout=True)
        self.canvas = FigureCanvasTkAgg(self.figure, master=self)
        self.canvas.mpl_connect("motion_notify_event", self._show_candle_tooltip)
        self.canvas.mpl_connect("button_press_event", self._select_candle_cutoff)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=18)
        toolbar_frame = ttk.Frame(self)
        toolbar_frame.pack(fill="x", padx=18)
        toolbar = NavigationToolbar2Tk(self.canvas, toolbar_frame, pack_toolbar=False)
        toolbar.pack(side="left", fill="x", expand=True)
        toolbar.update()
        chart_tools = ttk.Frame(toolbar_frame)
        chart_tools.pack(side="right", padx=(12, 0))
        ttk.Button(chart_tools, text="＋ Zoom In", command=lambda: self._zoom_button(.65)).pack(side="left")
        ttk.Button(chart_tools, text="− Zoom Out", command=lambda: self._zoom_button(1.55)).pack(side="left", padx=5)
        ttk.Button(chart_tools, text=f"1 Day · {DEFAULT_VISIBLE_BARS}", command=self._focus_day).pack(side="left")
        ttk.Separator(chart_tools, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(chart_tools, text="Price ⛶", command=lambda: self._set_panel_mode("price")).pack(side="left")
        ttk.Button(chart_tools, text="Bottom ⛶", command=lambda: self._set_panel_mode("bottom")).pack(side="left", padx=5)
        ttk.Button(chart_tools, text="Split", command=lambda: self._set_panel_mode("split")).pack(side="left")
        ttk.Label(self, textvariable=self.status, style="Muted.TLabel", anchor="w").pack(fill="x", padx=24, pady=(5, 12))

    def _load_symbols(self) -> None:
        symbols = available_symbols()
        self.all_symbols = symbols
        sector_filter = self.market_config.get("sector_symbol_filter", "NIFTY").upper()
        sector_symbols = [symbol for symbol in symbols if sector_filter in symbol.upper()]
        self.sector_box["values"] = sector_symbols
        if self.sector_symbol.get() not in sector_symbols and sector_symbols:
            self.sector_symbol.set(sector_symbols[0])
        self.symbol_box["values"] = symbols
        self.symbol_box.configure(state="normal", takefocus=True)
        self.after_idle(self._install_popdown_typing)
        if not symbols:
            self.status.set("No completed symbol files found. Wait for database creation to finish, then reopen the viewer.")
            return
        self.symbol.set(symbols[0])
        self.after(100, self._focus_symbol_search)
        self.status.set(f"{len(symbols):,} symbols available")
        self.refresh_chart()

    def _focus_symbol_search(self) -> None:
        self.symbol_box.focus_set()
        self.symbol_box.selection_range(0, tk.END)

    def _prepare_symbol_typing(self, _event=None) -> None:
        self.symbol_box.configure(state="normal")
        self.symbol_box.focus_set()
        self.after_idle(lambda: self.symbol_box.selection_range(0, tk.END))

    def _select_symbol_text(self, _event=None) -> str:
        self.symbol_box.selection_range(0, tk.END)
        return "break"

    def _filter_symbols(self, event) -> None:
        if event.keysym in {"Return", "Escape", "Up", "Down", "Left", "Right", "Tab"}:
            return
        self._apply_symbol_filter()

    def _apply_symbol_filter(self) -> list[str]:
        typed = self.symbol.get().strip().upper()
        matches = [symbol for symbol in self.all_symbols if typed in symbol.upper()]
        self.symbol_box["values"] = matches
        self.status.set(f"{len(matches):,} matching symbols" if typed else f"{len(self.all_symbols):,} symbols available")
        return matches

    def _install_popdown_typing(self) -> None:
        popdown = self.tk.call("ttk::combobox::PopdownWindow", str(self.symbol_box))
        self.symbol_popdown_list = f"{popdown}.f.l"
        self.symbol_popdown_command = self.register(self._type_in_open_symbol_list)
        script = f'if {{[{self.symbol_popdown_command} %A %K] eq "break"}} {{break}}'
        self.tk.call("bind", self.symbol_popdown_list, "<KeyPress>", script)

    def _type_in_open_symbol_list(self, character: str, keysym: str) -> str:
        if keysym == "BackSpace":
            try:
                first = self.symbol_box.index("sel.first")
                last = self.symbol_box.index("sel.last")
                self.symbol_box.delete(first, last)
            except tk.TclError:
                position = self.symbol_box.index(tk.INSERT)
                if position > 0:
                    self.symbol_box.delete(position - 1)
        elif character and character.isprintable():
            try:
                first = self.symbol_box.index("sel.first")
                last = self.symbol_box.index("sel.last")
                self.symbol_box.delete(first, last)
            except tk.TclError:
                pass
            self.symbol_box.insert(tk.INSERT, character.upper())
        else:
            return ""
        matches = self._apply_symbol_filter()
        if self.symbol_popdown_list:
            self.tk.call(self.symbol_popdown_list, "delete", 0, "end")
            for symbol in matches:
                self.tk.call(self.symbol_popdown_list, "insert", "end", symbol)
            if matches:
                self.tk.call(self.symbol_popdown_list, "selection", "set", 0)
                self.tk.call(self.symbol_popdown_list, "see", 0)
        return "break"

    def _load_first_symbol_match(self, _event=None) -> None:
        matches = list(self.symbol_box["values"])
        typed = self.symbol.get().strip()
        if typed in self.all_symbols:
            selected = typed
        elif matches:
            selected = matches[0]
        else:
            return
        self.symbol.set(selected)
        self.symbol_box["values"] = self.all_symbols
        self.symbol_box.icursor(tk.END)
        self.refresh_chart()

    def _restore_symbols(self, _event=None) -> None:
        self.symbol_box["values"] = self.all_symbols
        self.symbol.set("")
        self.status.set(f"{len(self.all_symbols):,} symbols available")

    def _selected_as_of(self) -> datetime:
        try:
            selected_date = self.as_of_date.get_date()
            hour, minute = int(self.as_of_hour.get()), int(self.as_of_minute.get())
            if not 0 <= hour <= 23 or not 0 <= minute <= 59:
                raise ValueError
            return datetime.combine(selected_date, datetime.min.time()).replace(
                hour=hour, minute=minute, second=59
            )
        except (TypeError, ValueError, tk.TclError) as error:
            raise ValueError("Select a valid date and a time between 00:00 and 23:59.") from error

    def _use_current_time(self) -> None:
        now = datetime.now()
        self.as_of_date.set_date(now.date())
        self.as_of_hour.set(now.strftime("%H"))
        self.as_of_minute.set(now.strftime("%M"))
        self.refresh_chart()

    def refresh_chart(self) -> None:
        symbol, interval = self.symbol.get(), self.interval.get()
        if not symbol or interval not in INTERVALS:
            return
        try:
            as_of = self._selected_as_of()
        except ValueError as error:
            self.status.set(str(error))
            messagebox.showerror("Invalid date/time", str(error), parent=self)
            return
        if interval in HIGHER_TIMEFRAME_BARS and (
            not self.current_chart or self.current_chart[1] != interval
        ):
            count = HIGHER_TIMEFRAME_BARS[interval]
            self.bar_count.set(count)
            self.bar_count_label.set(f"{count:,} bars")
        self.load_button.state(["disabled"])
        self.status.set(f"Loading {symbol} · {interval} through {as_of:%d %b %Y %H:%M}…")
        comparison_sources = {
            definition["source"] for definition in self.rsi_definitions
            if definition["source"] != "chart" and self.rsi_vars[definition["label"]].get()
        }
        comparison_sources.update(
            definition["source"] for definition in self.indicator_definitions
            if definition["type"] == "COMPARISON_CLOSE"
            and self.indicator_vars[definition["label"]].get()
        )
        threading.Thread(target=self._query_worker,
                         args=(symbol, interval, as_of, self.sector_symbol.get(), comparison_sources),
                         daemon=True).start()
        self.after(60, self._poll_result)

    def _zoom_changed(self, value: str) -> None:
        count = max(MIN_VISIBLE_BARS, min(MAX_VISIBLE_BARS, int(round(float(value) / 10) * 10)))
        self.bar_count.set(count)
        self.bar_count_label.set(f"{count:,} bars")
        if self.zoom_job:
            self.after_cancel(self.zoom_job)
        self.zoom_job = self.after(160, self._redraw_zoom)

    def _timeline_changed(self, value: str) -> None:
        self.end_index.set(max(0, int(round(float(value)))))
        if self.zoom_job:
            self.after_cancel(self.zoom_job)
        self.zoom_job = self.after(120, self._redraw_zoom)

    def _zoom_button(self, factor: float) -> None:
        old_count = self.bar_count.get()
        new_count = max(MIN_VISIBLE_BARS, min(MAX_VISIBLE_BARS, int(round(old_count * factor / 10) * 10)))
        self.bar_count.set(new_count)
        self.bar_count_label.set(f"{new_count:,} bars")
        self._redraw_zoom()

    def _focus_day(self) -> None:
        self.bar_count.set(DEFAULT_VISIBLE_BARS)
        self.bar_count_label.set(f"{DEFAULT_VISIBLE_BARS} bars")
        self._redraw_zoom()

    def _set_panel_mode(self, mode: str) -> None:
        if mode not in {"split", "price", "bottom"}:
            return
        self.panel_mode = mode
        self._redraw_zoom()

    def _redraw_zoom(self) -> None:
        self.zoom_job = None
        if self.current_chart:
            self._draw(*self.current_chart)

    def _indicators_changed(self) -> None:
        self._ensure_unique_active_colors("price")
        selected = sum(variable.get() for variable in self.indicator_vars.values())
        self.indicator_button.configure(text=f"Indicators ({selected}) ▾")
        self._save_ui_state()
        missing_comparison = any(
            definition["type"] == "COMPARISON_CLOSE"
            and self.indicator_vars[definition["label"]].get()
            and not self.comparison_rows.get(definition["source"])
            for definition in self.indicator_definitions
        )
        if missing_comparison:
            self.refresh_chart()
        else:
            self._redraw_zoom()

    def _clear_indicators(self) -> None:
        for variable in self.indicator_vars.values():
            variable.set(False)
        self._indicators_changed()

    def _bottom_metrics_changed(self) -> None:
        self._ensure_unique_active_colors("bottom")
        selected = sum(variable.get() for variable in (
            self.show_volume, self.show_delivery, self.show_percent
        )) + sum(variable.get() for variable in self.rsi_vars.values())
        self.bottom_button.configure(text=f"Bottom graph ({selected}) ▾")
        self._save_ui_state()
        missing_comparison = any(
            definition["source"] != "chart"
            and self.rsi_vars[definition["label"]].get()
            and not self.comparison_rows.get(definition["source"])
            for definition in self.rsi_definitions
        )
        if missing_comparison:
            self.refresh_chart()
        else:
            self._redraw_zoom()

    def _clear_bottom_metrics(self) -> None:
        for variable in (self.show_volume, self.show_delivery, self.show_percent):
            variable.set(False)
        for variable in self.rsi_vars.values():
            variable.set(False)
        self._bottom_metrics_changed()

    def _load_ui_state(self) -> None:
        try:
            state = json.loads(VIEWER_STATE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        selected_indicators = set(state.get("price_indicators", []))
        for label, variable in self.indicator_vars.items():
            variable.set(label in selected_indicators)
        bottom = set(state.get("bottom_graph", []))
        self.show_volume.set("Volume" in bottom)
        self.show_delivery.set("Delivery" in bottom)
        self.show_percent.set("Delivery %" in bottom)
        for label, variable in self.rsi_vars.items():
            variable.set(label in bottom)
        saved_colors = state.get("indicator_colors", {})
        for definition in (*self.indicator_definitions, *self.rsi_definitions):
            color = saved_colors.get(definition["label"])
            if isinstance(color, str) and len(color) == 7 and color.startswith("#"):
                definition["color"] = color

    def _save_ui_state(self) -> None:
        state = {
            "price_indicators": [label for label, variable in self.indicator_vars.items() if variable.get()],
            "bottom_graph": [
                *(["Volume"] if self.show_volume.get() else []),
                *(["Delivery"] if self.show_delivery.get() else []),
                *(["Delivery %"] if self.show_percent.get() else []),
                *(label for label, variable in self.rsi_vars.items() if variable.get()),
            ],
            "indicator_colors": {
                definition["label"]: definition["color"]
                for definition in (*self.indicator_definitions, *self.rsi_definitions)
            },
        }
        try:
            temporary = VIEWER_STATE.with_suffix(".tmp")
            temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
            temporary.replace(VIEWER_STATE)
        except OSError:
            pass

    def _active_color_definitions(self, panel: str) -> list[dict]:
        definitions = self.indicator_definitions if panel == "price" else self.rsi_definitions
        variables = self.indicator_vars if panel == "price" else self.rsi_vars
        return [definition for definition in definitions if variables[definition["label"]].get()]

    def _ensure_unique_active_colors(self, panel: str) -> None:
        used = set()
        menu = getattr(self, "indicator_menu" if panel == "price" else "bottom_menu", None)
        for definition in self._active_color_definitions(panel):
            color = definition["color"].lower()
            if color in used:
                color = next(candidate for candidate in CONTRAST_COLORS if candidate.lower() not in used)
                definition["color"] = color
                if menu is not None:
                    try:
                        menu.entryconfigure(definition["label"], selectcolor=color)
                    except tk.TclError:
                        pass
            used.add(color.lower())

    def _open_color_editor(self, panel: str) -> None:
        definitions = self._active_color_definitions(panel)
        if not definitions:
            messagebox.showinfo("Indicator colors", "Select at least one indicator first.", parent=self)
            return
        window = tk.Toplevel(self)
        window.title("Price indicator colors" if panel == "price" else "Bottom indicator colors")
        window.configure(bg="#111a24")
        window.resizable(False, False)
        ttk.Label(window, text="Choose distinct high-contrast colors", style="Title.TLabel").pack(
            anchor="w", padx=16, pady=(14, 10)
        )
        body = ttk.Frame(window, style="Panel.TFrame", padding=(16, 8, 16, 16))
        body.pack(fill="both", expand=True)
        for row, definition in enumerate(definitions):
            ttk.Label(body, text=definition["label"], background="#111a24").grid(
                row=row, column=0, sticky="w", pady=3
            )
            button = tk.Button(body, text=definition["color"], width=10,
                               bg=definition["color"], fg="#ffffff", relief="flat")
            button.configure(command=lambda item=definition, control=button:
                             self._choose_indicator_color(panel, item, control))
            button.grid(row=row, column=1, padx=(18, 0), pady=3)

    def _choose_indicator_color(self, panel: str, definition: dict, button: tk.Button) -> None:
        _, color = colorchooser.askcolor(color=definition["color"], parent=button.winfo_toplevel(),
                                         title=f"Color for {definition['label']}")
        if not color:
            return
        used = {item["color"].lower() for item in self._active_color_definitions(panel)
                if item is not definition}
        if color.lower() in used:
            messagebox.showwarning("Color already active",
                                   "Choose a different color so active indicators remain distinct.",
                                   parent=button.winfo_toplevel())
            return
        definition["color"] = color
        button.configure(text=color, bg=color)
        menu = self.indicator_menu if panel == "price" else self.bottom_menu
        try:
            menu.entryconfigure(definition["label"], selectcolor=color)
        except tk.TclError:
            pass
        self._save_ui_state()
        self._redraw_zoom()

    def _query_worker(self, symbol: str, interval: str, as_of: datetime, sector_symbol: str,
                      comparison_sources: set[str]) -> None:
        try:
            comparisons = {}
            for source, comparison_symbol in (("nifty", self.nifty_symbol), ("sector", sector_symbol)):
                if source not in comparison_sources:
                    comparisons[source] = []
                    continue
                try:
                    comparisons[source] = load_comparison_candles(comparison_symbol, interval, as_of)
                except (FileNotFoundError, OSError, duckdb.Error):
                    comparisons[source] = []
            self.results.put((symbol, interval, as_of, comparisons,
                              load_candles(symbol, interval, as_of), None))
        except Exception as error:
            self.results.put((symbol, interval, as_of, {}, None, error))

    def _poll_result(self) -> None:
        try:
            symbol, interval, as_of, comparisons, rows, error = self.results.get_nowait()
        except queue.Empty:
            self.after(60, self._poll_result)
            return
        self.load_button.state(["!disabled"])
        if error:
            self.status.set(str(error))
            messagebox.showerror("Unable to load chart", str(error), parent=self)
            return
        self.loaded_as_of = as_of
        self.comparison_rows = comparisons
        self.timeline_scale.configure(from_=min(len(rows), max(1, self.bar_count.get())), to=max(1, len(rows)))
        self.end_index.set(len(rows))
        try:
            self._draw(symbol, interval, rows)
        except Exception as error:
            self.status.set(f"Chart rendering failed: {error}")
            messagebox.showerror("Unable to draw chart", str(error), parent=self)

    def _draw(self, symbol: str, interval: str, rows: list[tuple]) -> None:
        self.current_chart = (symbol, interval, rows)
        count = min(self.bar_count.get(), len(rows))
        total_rows = len(rows)
        self.timeline_scale.configure(from_=max(1, count), to=max(1, total_rows))
        end = max(count, min(self.end_index.get() or total_rows, total_rows))
        self.end_index.set(end)
        start = end - count
        analysis_rows = rows[:end]
        rows = analysis_rows[start:end]
        self.visible_rows = rows
        self.visible_start = start
        self.tooltip_index = None
        self.figure.clear()
        if not rows:
            self.status.set(f"No {interval} data found for {symbol}")
            self.canvas.draw_idle()
            return
        if self.panel_mode == "split":
            layout = self.figure.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.04)
            price_spec, metric_spec = layout[0], layout[1]
        else:
            layout = self.figure.add_gridspec(1, 1)
            price_spec = metric_spec = layout[0]
        price = self.figure.add_subplot(price_spec)
        self.price_axis = price
        self.price_axes = [price]
        metric = self.figure.add_subplot(metric_spec, sharex=price)
        self.metric_axis = metric
        self.bottom_axes = [metric]
        self.price_indicator_series = {}
        self.bottom_series = {}
        self.bottom_tooltip_index = None
        for axis in (price, metric):
            axis.set_facecolor("#0f1720")
            axis.grid(True, color="#22303e", alpha=.55, linewidth=.6)
            axis.tick_params(colors="#8fa1b4", labelsize=8)
            for spine in axis.spines.values():
                spine.set_color("#263544")
        dates = list(range(len(rows)))
        width = .68
        colors = []
        for x, row in zip(dates, rows):
            _, open_, high, low, close, *_ = row
            color = "#21c58b" if close >= open_ else "#f05268"
            colors.append(color)
            price.vlines(x, low, high, color=color, linewidth=.8)
            bottom, height = min(open_, close), abs(close - open_)
            price.add_patch(Rectangle((x - width / 2, bottom), width, max(height, 1e-9),
                                      facecolor=color, edgecolor=color, linewidth=.6))
        active_indicators = [
            definition for definition in self.indicator_definitions
            if (definition["type"] in {"ANCHORED_VWAP", "COMPARISON_CLOSE", "STORED_TL"}
                or indicator_applies(interval, definition["timeframe"]))
            and self.indicator_vars[definition["label"]].get()
        ]
        # Indicator calculations must stop at the selected End time, not at the
        # later database cutoff, otherwise a partial W/M/Q value can see future bars.
        all_rows = analysis_rows
        all_closes = [float(row[4]) for row in all_rows]
        relative_axis = None
        for definition in active_indicators:
            if definition["type"] == "STORED_TL":
                visible_values = [row[definition["column_index"]] for row in rows]
                self.price_indicator_series[definition["label"]] = visible_values
                latest = latest_finite(visible_values)
                label = definition["label"] if latest is None else f"{definition['label']}  {latest:,.2f}"
                price.plot(dates, visible_values, color=definition["color"], linewidth=1.15,
                           linestyle="--" if definition["label"].endswith("OHLC") else "-", label=label)
                continue
            if definition["type"] == "COMPARISON_CLOSE":
                source_rows = self.comparison_rows.get(definition["source"], [])
                if all_rows:
                    source_rows = [row for row in source_rows if row[0] <= all_rows[-1][0]]
                aligned_closes = align_series(all_rows, source_rows, [float(row[4]) for row in source_rows])
                visible_raw = aligned_closes[start:start + count]
                base = next((value for value in visible_raw if math.isfinite(value) and value != 0), None)
                visible_values = [math.nan if base is None or not math.isfinite(value)
                                  else (value / base - 1.0) * 100.0 for value in visible_raw]
                if relative_axis is None:
                    relative_axis = price.twinx()
                    self.price_axes.append(relative_axis)
                    relative_axis.tick_params(colors="#94a3b8", labelsize=8)
                    relative_axis.set_ylabel("Relative move %", color="#94a3b8")
                    relative_axis.grid(False)
                self.price_indicator_series[definition["label"]] = visible_values
                latest = latest_finite(visible_values)
                label = definition["label"] if latest is None else f"{definition['label']}  {latest:+.2f}%"
                relative_axis.plot(dates, visible_values, color=definition["color"],
                                   linewidth=1.2, label=label)
                continue
            indicator_rows = all_rows
            if (definition["type"] != "ANCHORED_VWAP"
                    and definition["timeframe"] not in {"chart", interval}):
                indicator_rows = aggregate_candles(all_rows, definition["timeframe"])
            indicator_closes = [float(row[4]) for row in indicator_rows]
            if definition["type"] == "EMA":
                values = ema(indicator_closes, definition["period"])
            elif definition["type"] == "SUPERTREND":
                values = supertrend(indicator_rows, definition["period"], definition["multiplier"])
            elif definition["type"] == "AMA":
                values = adaptive_moving_average(
                    indicator_rows, definition["efficiency_period"],
                    definition["fast_period"], definition["slow_period"]
                )
            else:
                values = anchored_vwap(indicator_rows, definition["anchor"])
            if indicator_rows is not all_rows:
                values = expand_completed_values(all_rows, definition["timeframe"], indicator_rows, values)
            visible_values = values[start:start + count]
            self.price_indicator_series[definition["label"]] = visible_values
            latest = latest_finite(visible_values)
            label = definition["label"] if latest is None else f"{definition['label']}  {latest:,.2f}"
            price.plot(dates, visible_values, color=definition["color"], linewidth=1.15, label=label)
        price_handles, price_labels = [], []
        for axis in self.price_axes:
            axis_handles, axis_labels = axis.get_legend_handles_labels()
            price_handles.extend(axis_handles)
            price_labels.extend(axis_labels)
        if price_handles:
            price.legend(price_handles, price_labels, loc="upper left", frameon=False,
                         labelcolor="#cbd5e1", fontsize=8, ncol=min(3, len(price_handles)))
        cutoff = f"  ·  through {self.loaded_as_of:%d %b %Y %H:%M}" if self.loaded_as_of else ""
        price.set_title(f"{symbol}  ·  {interval}{cutoff}", loc="left", color="#f2f6fa", fontsize=13, fontweight="bold")
        price.set_ylabel("Price", color="#8fa1b4")
        self.tooltip = price.annotate(
            "", xy=(0, 0), xytext=(14, 14), textcoords="offset points",
            color="#f4f7fb", fontsize=9, linespacing=1.35, zorder=20,
            bbox={"boxstyle": "round,pad=0.55", "facecolor": "#172431",
                  "edgecolor": "#4b647a", "alpha": .97},
            arrowprops={"arrowstyle": "->", "color": "#7f9bb2", "linewidth": .8},
        )
        self.tooltip.set_in_layout(False)
        self.tooltip.set_visible(False)
        if self.show_volume.get():
            volumes = [row[5] or 0 for row in rows]
            self.bottom_series["Volume"] = volumes
            metric.bar(dates, volumes, width=width, color=colors, alpha=.42, label=f"Volume  {volumes[-1]:,.0f}")
        if self.show_delivery.get() and any(row[6] is not None for row in rows):
            deliveries = [row[6] for row in rows]
            self.bottom_series["Delivery"] = deliveries
            latest = latest_finite(deliveries)
            metric.plot(dates, deliveries, color="#f7b955", linewidth=1,
                        label=f"Delivery  {latest:,.0f}" if latest is not None else "Delivery")
        if self.show_percent.get() and any(row[7] is not None for row in rows):
            percent_axis = metric.twinx()
            self.bottom_axes.append(percent_axis)
            percentages = [row[7] for row in rows]
            self.bottom_series["Delivery %"] = percentages
            latest = latest_finite(percentages)
            percent_axis.plot(dates, percentages, color="#a78bfa", linewidth=1.1,
                              label=f"Delivery %  {latest:.2f}%" if latest is not None else "Delivery %")
            percent_axis.tick_params(colors="#a78bfa", labelsize=8)
            percent_axis.set_ylabel("Delivery %", color="#a78bfa")
        active_rsi = [
            definition for definition in self.rsi_definitions
            if indicator_applies(interval, definition["timeframe"])
            and self.rsi_vars[definition["label"]].get()
        ]
        if active_rsi:
            rsi_axis = metric.twinx()
            self.bottom_axes.append(rsi_axis)
            if self.show_percent.get():
                rsi_axis.spines["right"].set_position(("outward", 52))
            for definition in active_rsi:
                source_rows = (all_rows if definition["source"] == "chart"
                               else self.comparison_rows.get(definition["source"], []))
                if source_rows is not all_rows and all_rows:
                    analysis_end = all_rows[-1][0]
                    source_rows = [row for row in source_rows if row[0] <= analysis_end]
                if not source_rows:
                    continue
                indicator_rows = source_rows
                if definition["timeframe"] not in {"chart", interval}:
                    indicator_rows = aggregate_candles(source_rows, definition["timeframe"])
                indicator_closes = [float(row[4]) for row in indicator_rows]
                rsi_values = rsi(indicator_closes, definition["period"])
                if indicator_rows is not source_rows:
                    rsi_values = expand_completed_values(
                        source_rows, definition["timeframe"], indicator_rows, rsi_values
                    )
                if source_rows is not all_rows:
                    rsi_values = align_series(all_rows, source_rows, rsi_values)
                visible_rsi = rsi_values[start:start + count]
                self.bottom_series[definition["label"]] = visible_rsi
                latest = latest_finite(visible_rsi)
                label = definition["label"] if latest is None else f"{definition['label']}  {latest:.2f}"
                rsi_axis.plot(dates, visible_rsi, color=definition["color"], linewidth=1.1, label=label)
            rsi_axis.axhline(70, color="#f05268", alpha=.45, linewidth=.7, linestyle="--")
            rsi_axis.axhline(30, color="#21c58b", alpha=.45, linewidth=.7, linestyle="--")
            rsi_axis.set_ylim(0, 100)
            rsi_axis.tick_params(colors="#22d3ee", labelsize=8)
            rsi_axis.set_ylabel("RSI", color="#22d3ee")
        self.bottom_tooltip = metric.annotate(
            "", xy=(0, 0), xytext=(14, 14), textcoords="offset points",
            color="#f4f7fb", fontsize=9, linespacing=1.35, zorder=30,
            bbox={"boxstyle": "round,pad=0.55", "facecolor": "#172431",
                  "edgecolor": "#4b647a", "alpha": .97},
            arrowprops={"arrowstyle": "->", "color": "#7f9bb2", "linewidth": .8},
        )
        self.bottom_tooltip.set_in_layout(False)
        self.bottom_tooltip.set_visible(False)
        metric.set_ylabel("Activity", color="#8fa1b4")
        metric.xaxis.set_major_locator(mticker.MaxNLocator(nbins=9, integer=True))
        def format_bar(value: float, _position: int) -> str:
            index = int(round(value))
            if 0 <= index < len(rows):
                stamp = rows[index][0]
                return stamp.strftime("%d %b\n%H:%M") if interval in ("1m", "5m", "15m") else stamp.strftime("%d %b\n%Y")
            return ""
        metric.xaxis.set_major_formatter(mticker.FuncFormatter(format_bar))
        price.set_xlim(-1, len(rows))
        handles, labels = [], []
        for axis in self.bottom_axes:
            axis_handles, axis_labels = axis.get_legend_handles_labels()
            handles.extend(axis_handles)
            labels.extend(axis_labels)
        if handles:
            metric.legend(handles, labels, loc="upper left", frameon=False,
                          labelcolor="#cbd5e1", fontsize=8, ncol=min(3, len(handles)))
        if self.panel_mode == "price":
            for axis in self.bottom_axes:
                axis.set_visible(False)
            price.tick_params(labelbottom=True)
        elif self.panel_mode == "bottom":
            for axis in self.price_axes:
                axis.set_visible(False)
        self.canvas.draw_idle()
        end_stamp = self.loaded_as_of if end == total_rows and self.loaded_as_of else rows[-1][0]
        self.range_label.set(f"End: {end_stamp:%d %b %Y %H:%M}  ·  {len(rows):,} visible bars")
        total = len(self.current_chart[2])
        history_note = "full available history" if len(rows) == total else "loaded history"
        self.status.set(
            f"Showing {len(rows):,} of {total:,} {interval} bars ({history_note}) · "
            f"{rows[0][0]:%d %b %Y} to {rows[-1][0]:%d %b %Y} · "
            f"cutoff {self.loaded_as_of:%d %b %Y %H:%M}"
        )

    def _show_candle_tooltip(self, event) -> None:
        if event.inaxes in self.bottom_axes:
            self._show_bottom_tooltip(event)
            if self.tooltip and self.tooltip.get_visible():
                self.tooltip.set_visible(False)
                self.tooltip_index = None
            return
        if self.bottom_tooltip and self.bottom_tooltip.get_visible():
            self.bottom_tooltip.set_visible(False)
            self.bottom_tooltip_index = None
        if not self.tooltip or not self.tooltip.get_visible() and event.inaxes not in self.price_axes:
            return
        if event.inaxes not in self.price_axes or event.xdata is None:
            if self.tooltip.get_visible():
                self.tooltip.set_visible(False)
                self.tooltip_index = None
                self.canvas.draw_idle()
            return
        index = int(round(event.xdata))
        if index < 0 or index >= len(self.visible_rows) or abs(event.xdata - index) > .7:
            if self.tooltip.get_visible():
                self.tooltip.set_visible(False)
                self.tooltip_index = None
                self.canvas.draw_idle()
            return
        if index == self.tooltip_index and self.tooltip.get_visible():
            return
        stamp, open_, high, low, close, volume = self.visible_rows[index][:6]
        self.tooltip.xy = (index, high)
        self.tooltip.set_text(
            f"{stamp:%d %b %Y  %H:%M}\n"
            f"Open     {open_:,.2f}\nHigh      {high:,.2f}\n"
            f"Low       {low:,.2f}\nClose     {close:,.2f}\n"
            f"Volume    {volume:,.0f}"
            + self._indicator_tooltip_text(index)
        )
        self._position_tooltip(self.tooltip, self.price_axis, index, high)
        self.tooltip.set_visible(True)
        self.tooltip_index = index
        self.canvas.draw_idle()

    def _show_bottom_tooltip(self, event) -> None:
        if not self.bottom_tooltip or event.xdata is None:
            return
        index = int(round(event.xdata))
        if index < 0 or index >= len(self.visible_rows) or abs(event.xdata - index) > .7:
            if self.bottom_tooltip.get_visible():
                self.bottom_tooltip.set_visible(False)
                self.bottom_tooltip_index = None
                self.canvas.draw_idle()
            return
        if index == self.bottom_tooltip_index and self.bottom_tooltip.get_visible():
            return
        stamp, _, _, _, _, volume = self.visible_rows[index][:6]
        lines = [f"{stamp:%d %b %Y  %H:%M}", f"Volume       {volume:,.0f}"]
        indicator_text = self._indicator_tooltip_text(index)
        if indicator_text:
            lines.extend(indicator_text.lstrip("\n").splitlines())
        top = self.metric_axis.get_ylim()[1]
        self.bottom_tooltip.xy = (index, top * .82)
        self.bottom_tooltip.set_text("\n".join(lines))
        self._position_tooltip(self.bottom_tooltip, self.metric_axis, index, top * .82)
        self.bottom_tooltip.set_visible(True)
        self.bottom_tooltip_index = index
        self.canvas.draw_idle()

    def _indicator_tooltip_text(self, index: int) -> str:
        lines = []
        for label, values in self.price_indicator_series.items():
            if index < len(values):
                value = values[index]
                if value is None or not math.isfinite(float(value)):
                    text = "—"
                elif label.endswith("%"):
                    text = f"{value:+.2f}%"
                else:
                    text = f"{value:,.2f}"
                lines.append(f"{label:<20} {text}")
        for definition in self.rsi_definitions:
            label = definition["label"]
            values = self.bottom_series.get(label)
            if values is not None and index < len(values):
                value = values[index]
                text = "—" if value is None or not math.isfinite(float(value)) else f"{value:.2f}"
                lines.append(f"{label:<20} {text}")
        return "\n" + "\n".join(lines) if lines else ""

    @staticmethod
    def _position_tooltip(annotation, axis, x: float, y: float) -> None:
        """Flip a tooltip around its anchor to keep it inside the plot area."""
        display_x, display_y = axis.transData.transform((x, y))
        bounds = axis.get_window_extent()
        open_left = display_x > bounds.x0 + bounds.width * .58
        open_down = display_y > bounds.y0 + bounds.height * .58
        annotation.set_position((-14 if open_left else 14, -14 if open_down else 14))
        annotation.set_horizontalalignment("right" if open_left else "left")
        annotation.set_verticalalignment("top" if open_down else "bottom")

    def _select_candle_cutoff(self, event) -> None:
        """Use a clicked price candle as the point-in-time chart cutoff."""
        if event.inaxes not in self.price_axes or event.xdata is None or not self.current_chart:
            return
        index = int(round(event.xdata))
        if index < 0 or index >= len(self.visible_rows) or abs(event.xdata - index) > .7:
            return
        interval = self.current_chart[1]
        global_index = self.visible_start + index
        all_rows = self.current_chart[2]
        if interval in {"Day", "Week", "Month", "Quarter", "Year"}:
            if global_index + 1 < len(all_rows):
                period_end = all_rows[global_index + 1][0]
            else:
                period_start = _bucket_start(all_rows[global_index][0], interval)
                period_end = _next_bucket_start(period_start, interval)
            if not isinstance(period_end, datetime):
                period_end = datetime.combine(period_end, datetime.min.time())
            cutoff = period_end - timedelta(minutes=1)
        else:
            stamp = self.visible_rows[index][0]
            cutoff = stamp if isinstance(stamp, datetime) else datetime.combine(stamp, datetime.min.time())
        self.as_of_date.set_date(cutoff.date())
        self.as_of_hour.set(f"{cutoff.hour:02d}")
        self.as_of_minute.set(f"{cutoff.minute:02d}")
        self.refresh_chart()


if __name__ == "__main__":
    OloDbViewer().mainloop()
