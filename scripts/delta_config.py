"""
delta_config.py — Single source of truth for the deltas.csv schema.

Defines the lookback windows, which metrics get per-window deltas, and the
momentum/rank columns. compute_deltas.py, export_db.py, and dashboard/app.py
all import from here so the schema is defined exactly once.

To change the lookback windows (e.g. switch to 21/63 trading days), edit
LOOKBACK_WINDOWS — every consumer derives its columns from delta_columns().
"""

# Lookback windows, in *trading* days (sessions), not calendar days.
LOOKBACK_WINDOWS = [5, 10, 20, 50]
LOOKBACK_BASIS = "trading"  # "trading" sessions vs "calendar" days

# Which rank/perf metrics get a per-window delta column.
RANK_DELTA_METRICS = ["rank_week", "rank_month", "rank_ytd"]
PERF_DELTA_METRICS = ["perf_week", "perf_month", "perf_ytd"]

# Point-in-time rank columns (rank 1 = best performer for that timeframe).
RANK_COLS = [
    "rank_day", "rank_week", "rank_month", "rank_quarter",
    "rank_half", "rank_year", "rank_ytd",
]

# Momentum / composite columns appended after the per-window deltas.
MOMENTUM_COLS = [
    "momentum_score",
    "momentum_confirmed",
    "momentum_weighted_mid",
    "momentum_weighted_fast",
    "momentum_accel",
    "regime_short_long",
    "rank_trend_slope",
    "rank_agreement",
]

# Perf metrics ranked for momentum percentile scoring (best=1).
PERF_RANK_METRICS = [
    "perf_day", "perf_week", "perf_month", "perf_quarter",
    "perf_half", "perf_year", "perf_ytd",
]

# Weighted-momentum profiles. Keys are perf metrics; missing metrics default
# to weight 1.0. "mid" leans on the 1-month/3-month trend; "fast" leans on the
# day/week trend to catch fresh rotation.
WEIGHTS_MID = {
    "perf_day": 0.5, "perf_week": 1.0, "perf_month": 2.0, "perf_quarter": 2.0,
    "perf_half": 1.0, "perf_year": 1.0, "perf_ytd": 1.0,
}
WEIGHTS_FAST = {
    "perf_day": 2.0, "perf_week": 2.0, "perf_month": 1.0, "perf_quarter": 0.5,
    "perf_half": 0.5, "perf_year": 0.5, "perf_ytd": 0.5,
}

# Short- vs long-horizon buckets for the regime score.
# Short = wk + month (smoother than day, still captures recent rotation).
# Long = 3mo + 6mo + yr (excludes perf_ytd to avoid double-counting with yr).
REGIME_SHORT = ["perf_week", "perf_month"]
REGIME_LONG = ["perf_quarter", "perf_half", "perf_year"]

# Which trading-day window to use when measuring momentum acceleration and the
# rank-trend slope window length (in sessions).
#
# ACCEL_WINDOW ideally stays equal to a value already in LOOKBACK_WINDOWS so the
# prior-frame data is already loaded by the delta loop (avoiding a redundant
# compute_ranks pass). Currently both equal LOOKBACK_WINDOWS[1] = 10.
# If you change ACCEL_WINDOW to a value outside LOOKBACK_WINDOWS, momentum_accel
# will still be correct — it loads its own frame — but the extra compute_ranks call
# adds a small overhead.
ACCEL_WINDOW = 10
SLOPE_WINDOW = 10


def delta_columns() -> list[str]:
    """Return the full ordered list of deltas.csv columns.

    This is the ONLY definition of the deltas schema. All readers/writers
    derive their column list from here.
    """
    cols = ["date", "name", *RANK_COLS]
    for w in LOOKBACK_WINDOWS:
        for m in RANK_DELTA_METRICS:
            cols.append(f"{m}_delta_{w}d")
        for m in PERF_DELTA_METRICS:
            cols.append(f"{m}_delta_{w}d")
    cols += MOMENTUM_COLS
    return cols
