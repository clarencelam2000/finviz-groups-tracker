"""
delta_config.py — Single source of truth for all CSV schemas and pipeline config.

Defines snapshot column lists, lookback windows, delta metrics, and composite
column groups. collect.py (writer), compute_deltas.py, export_db.py, and
dashboard/app.py all import from here so each schema is defined exactly once.

To change the lookback windows (e.g. switch to 21/63 trading days), edit
LOOKBACK_WINDOWS — every consumer derives its columns from delta_columns().
"""

# ---------------------------------------------------------------------------
# Snapshot CSV schemas
# ---------------------------------------------------------------------------

# data/sectors/snapshots.csv and data/industries/snapshots.csv columns.
# collect.py is the writer; compute_deltas.py and export_db.py are readers.
SNAPSHOT_COLS = [
    "date", "collected_at", "group_type", "name", "stocks", "market_cap",
    "pe", "fwd_pe", "perf_day", "perf_week", "perf_month", "perf_quarter",
    "perf_half", "perf_year", "perf_ytd", "avg_volume", "rel_volume", "change",
]

# data/benchmark/snapshots.csv columns (one SPY row per trading date).
# Raw perf_* values are stored here — never derived spreads. This is the
# two-way-door invariant: rs_ratio and RRG axes are retroactively derivable
# from raw perf_* without data loss. See ADR-005.
BENCH_CSV_COLUMNS = [
    "date", "collected_at", "ticker",
    "perf_day", "perf_week", "perf_month", "perf_quarter",
    "perf_half", "perf_year", "perf_ytd",
]

# The 7 performance columns within BENCH_CSV_COLUMNS. All 7 must parse
# successfully for a SPY scrape to be valid — SPY always has full perf history,
# so fewer than 7 means a Finviz label change or page-structure failure.
BENCH_PERF_COLS = [c for c in BENCH_CSV_COLUMNS if c.startswith("perf_")]

# ---------------------------------------------------------------------------
# Deltas pipeline config
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Relative-strength (RS vs SPY) columns
# ---------------------------------------------------------------------------

# Raw RS spreads: group_perf_X − SPY_perf_X per timeframe.
# Positive = beating the market over that horizon.
RS_TIMEFRAMES = [
    "rs_day", "rs_week", "rs_month", "rs_quarter", "rs_half", "rs_year", "rs_ytd",
]

# Canonical RS line used for rs_slope computation (least-squares slope of
# this spread over SLOPE_WINDOW sessions). rs_month is chosen because it is
# the most informative mid-frequency signal for detecting relative-strength
# trends, matching the 1-month window used by regime_short_long.
RS_SLOPE_COL = "rs_month"

# Medium-timeframe RS columns used to compute rs_agreement.
# Mirrors the rank_agreement inputs (rank_month/quarter/half) for consistency.
RS_AGREEMENT_COLS = ["rs_month", "rs_quarter", "rs_half"]

# Short/long RS horizon buckets for rs_regime_short_long.
# Short = week + month (fresh rotation signal without day noise).
# Long = quarter + half + year (durable trend baseline).
RS_REGIME_SHORT = ["rs_week", "rs_month"]
RS_REGIME_LONG = ["rs_quarter", "rs_half", "rs_year"]

# Window (trading sessions) for rs_new_high: is today's RS spread at its
# highest in the trailing RS_NEW_HIGH_WINDOW sessions? 20 sessions ≈ 1 trading
# month — classic "RS new high" leadership flag from the IBD methodology.
# Must be ≥ 2 to produce a meaningful signal; ideally matches a LOOKBACK_WINDOWS
# entry (currently LOOKBACK_WINDOWS[2] = 20) so no extra compute_ranks pass.
RS_NEW_HIGH_WINDOW = 20

# Window (trading sessions) for rs_cross: did rs_month flip from ≤ 0 to > 0
# within the last RS_CROSS_WINDOW sessions? 5 sessions ≈ 1 trading week — a
# tight window catches fresh rotations while filtering noise. Using
# LOOKBACK_WINDOWS[0] = 5 so history is already loaded by the delta loop.
RS_CROSS_WINDOW = 5

# Timeframe suffixes for beats_benchmark_X columns — aligned with RS_TIMEFRAMES
# so beats_benchmark_{suffix} is the boolean form of rs_{suffix} > 0.
RS_BEAT_TIMEFRAMES = ["day", "week", "month", "quarter", "half", "year", "ytd"]

# All RS-derived columns appended after MOMENTUM_COLS in the deltas schema.
RS_COLS = RS_TIMEFRAMES + [
    "rs_score",           # 0–1; fraction of 7 timeframes where group beats SPY (rs_X > 0)
    "rs_agreement",       # 0–1; sign consistency of rs_month/quarter/half (1.0 = all same direction)
    "rs_confirmed",       # rs_score × rs_agreement; breadth gated by directional consistency
    "rs_slope",           # LS slope of rs_month over SLOPE_WINDOW; positive = building
    "rs_accel",           # change in rs_score over ACCEL_WINDOW; positive = RS building
    "rs_regime_short_long",  # short-horizon RS breadth − long-horizon RS breadth; positive = emerging
] + [f"beats_benchmark_{tf}" for tf in RS_BEAT_TIMEFRAMES] + [
    "rs_new_high",   # 1 if rs_month is at its RS_NEW_HIGH_WINDOW-session high; 0 otherwise
    "rs_cross",      # 1 if rs_month crossed from ≤ 0 to > 0 within RS_CROSS_WINDOW sessions
]


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
    cols += RS_COLS
    return cols
