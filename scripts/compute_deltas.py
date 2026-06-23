"""
compute_deltas.py — Read snapshot CSVs and compute rank/delta artifacts,
appending to deltas CSVs.
"""

import argparse
import csv
import math
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from delta_config import (
    ACCEL_WINDOW,
    BENCH_CSV_COLUMNS,
    LOOKBACK_WINDOWS,
    MOMENTUM_COLS,
    PERF_DELTA_METRICS,
    PERF_RANK_METRICS,
    RANK_DELTA_METRICS,
    REGIME_LONG,
    REGIME_SHORT,
    RS_AGREEMENT_COLS,
    RS_BEAT_TIMEFRAMES,
    RS_COLS,
    RS_CROSS_WINDOW,
    RS_NEW_HIGH_WINDOW,
    RS_REGIME_LONG,
    RS_REGIME_SHORT,
    RS_SCORE_TIMEFRAMES,
    RS_SLOPE_COL,
    RS_TIMEFRAMES,
    SLOPE_WINDOW,
    SNAPSHOT_COLS,
    WEIGHTS_FAST,
    WEIGHTS_MID,
    delta_columns,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"

DELTA_COLUMNS = delta_columns()

# LOOKBACK_WINDOWS are trading sessions (not calendar days), resolved by
# position in the sorted list of available trading dates.
DATE_TOLERANCE = 5  # extra calendar days to search for nearest date (legacy helper)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ensure_deltas_csv(csv_path: Path) -> bool:
    """Create or migrate the deltas CSV to match DELTA_COLUMNS.

    Returns True if a schema migration was performed (existing rows were rewritten),
    False if the file was created fresh or was already up-to-date.
    """
    if not csv_path.exists():
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=DELTA_COLUMNS)
            writer.writeheader()
        print(f"  Created {csv_path}")
        return False

    # Migrate schema if DELTA_COLUMNS has changed since the file was created
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        existing_cols = list(reader.fieldnames) if reader.fieldnames else []
        if existing_cols == DELTA_COLUMNS:
            return False
        rows = list(reader)

    print(f"  [migrate] Schema change detected in {csv_path} — rewriting with updated columns.")
    tmp = csv_path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DELTA_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in DELTA_COLUMNS})
    tmp.replace(csv_path)
    print(f"  [migrate] Migrated {len(rows)} rows.")
    return True


def _evict_date_rows(csv_path: Path, date_str: str):
    """Remove all rows for date_str from the deltas CSV (atomic rewrite)."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        kept = [r for r in reader if r.get("date") != date_str]
    tmp = csv_path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DELTA_COLUMNS)
        writer.writeheader()
        for row in kept:
            writer.writerow({col: row.get(col, "") for col in DELTA_COLUMNS})
    tmp.replace(csv_path)


def load_snapshots(csv_path: Path) -> pd.DataFrame:
    """Load snapshots CSV; return empty DataFrame if no data rows."""
    if not csv_path.exists():
        return pd.DataFrame(columns=SNAPSHOT_COLS)

    df = pd.read_csv(csv_path)
    if df.empty:
        return pd.DataFrame(columns=SNAPSHOT_COLS)

    # Parse numeric columns
    for col in ["perf_day", "perf_week", "perf_month", "perf_quarter",
                "perf_half", "perf_year", "perf_ytd", "change",
                "market_cap", "pe", "fwd_pe", "rel_volume", "stocks", "avg_volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    return df


def find_nearest_date(available_dates: list, target_date, tolerance_days: int = DATE_TOLERANCE):
    """Find the closest available date that is <= target_date within tolerance.

    Calendar-day helper retained for reference/tests; the main delta path now
    uses find_trading_date_back for trading-session lookbacks.
    """
    candidates = [d for d in available_dates if d <= target_date]
    if not candidates:
        return None
    best = max(candidates)
    if (target_date - best).days <= tolerance_days:
        return best
    return None


def find_trading_date_back(available_dates: list, target_date, n_sessions: int):
    """Return the date n_sessions trading days before target_date.

    available_dates must be sorted ascending and contain only actual trading
    days present in the snapshot. Returns None if target_date isn't present or
    there aren't n_sessions of prior history (NaN deltas during early history).
    """
    if target_date not in available_dates:
        return None
    i = available_dates.index(target_date)
    j = i - n_sessions
    if j < 0:
        return None
    return available_dates[j]


def compute_ranks(df_day: pd.DataFrame) -> pd.DataFrame:
    """Add rank columns to a single-day snapshot DataFrame."""
    df = df_day.copy()
    rank_metrics = {
        "rank_day": "perf_day",
        "rank_week": "perf_week",
        "rank_month": "perf_month",
        "rank_quarter": "perf_quarter",
        "rank_half": "perf_half",
        "rank_year": "perf_year",
        "rank_ytd": "perf_ytd",
    }
    for rank_col, perf_col in rank_metrics.items():
        if perf_col in df.columns:
            df[rank_col] = df[perf_col].rank(ascending=False, method="min", na_option="bottom")
        else:
            df[rank_col] = float("nan")
    return df


def compute_momentum(df_day: pd.DataFrame) -> pd.Series:
    """Compute momentum_score: mean percentile across 6 perf metrics (week → YTD)."""
    n = len(df_day)
    if n <= 1:
        return pd.Series([float("nan")] * n, index=df_day.index)

    scores = pd.DataFrame(index=df_day.index)
    for col in PERF_RANK_METRICS:
        if col in df_day.columns and df_day[col].notna().any():
            ranks = df_day[col].rank(ascending=False, method="min", na_option="bottom")
            # rank 1 → percentile 1.0, rank n → percentile 0.0
            scores[col] = (n - ranks) / (n - 1)
        # missing or all-NaN columns are omitted; mean(skipna=True) handles partial coverage

    return scores.mean(axis=1)


_MAX_STD_3 = 1.0 / math.sqrt(3)  # max sample std of 3 values drawn from [0, 1]


def compute_rank_agreement(df_day: pd.DataFrame) -> pd.Series:
    """Compute rank_agreement: how consistently month/quarter/half ranks align.

    Converts each rank to a percentile [0=worst, 1=best], then measures how
    tightly the three percentiles cluster. Score 1.0 = all three timeframes
    give the same relative standing; 0.0 = maximum disagreement.

    A high score alongside a high momentum_score means the trend is confirmed
    across timeframes, not just a recent flash.
    """
    n = len(df_day)
    if n <= 1:
        return pd.Series([float("nan")] * n, index=df_day.index)

    pct_df = pd.DataFrame(index=df_day.index)
    for rank_col in ["rank_month", "rank_quarter", "rank_half"]:
        if rank_col in df_day.columns and df_day[rank_col].notna().any():
            pct_df[rank_col] = (n - df_day[rank_col]) / (n - 1)

    if pct_df.shape[1] < 3:
        return pd.Series([float("nan")] * n, index=df_day.index)

    row_std = pct_df.std(axis=1, ddof=1)
    return (1 - row_std / _MAX_STD_3).clip(lower=0.0, upper=1.0)


def _perf_percentiles(df_day: pd.DataFrame) -> pd.DataFrame:
    """Per-metric percentile [0=worst, 1=best] for each available perf metric."""
    n = len(df_day)
    pct = pd.DataFrame(index=df_day.index)
    for col in PERF_RANK_METRICS:
        if col in df_day.columns and df_day[col].notna().any():
            ranks = df_day[col].rank(ascending=False, method="min", na_option="bottom")
            pct[col] = (n - ranks) / (n - 1)
    return pct


def weighted_momentum(df_day: pd.DataFrame, weights: dict) -> pd.Series:
    """Weighted mean of perf percentiles. Metrics absent from `weights` get 1.0.

    Returns NaN for single-row frames (percentile undefined).
    """
    n = len(df_day)
    if n <= 1:
        return pd.Series([float("nan")] * n, index=df_day.index)
    pct = _perf_percentiles(df_day)
    if pct.shape[1] == 0:
        return pd.Series([float("nan")] * n, index=df_day.index)
    w = pd.Series({c: weights.get(c, 1.0) for c in pct.columns})
    # row-wise weighted mean, skipping NaN cells (their weight drops out)
    mask = pct.notna()
    weighted_sum = (pct.fillna(0.0) * w).sum(axis=1)
    weight_total = (mask * w).sum(axis=1)
    return weighted_sum / weight_total.replace(0.0, float("nan"))


def compute_regime(df_day: pd.DataFrame) -> pd.Series:
    """Short-horizon percentile mean minus long-horizon percentile mean.

    Positive = emerging leader (strong recently, weaker long-term); negative =
    fading leader. Range roughly [-1, 1]. NaN if either bucket is unavailable.
    """
    n = len(df_day)
    if n <= 1:
        return pd.Series([float("nan")] * n, index=df_day.index)
    pct = _perf_percentiles(df_day)
    short_cols = [c for c in REGIME_SHORT if c in pct.columns]
    long_cols = [c for c in REGIME_LONG if c in pct.columns]
    if not short_cols or not long_cols:
        return pd.Series([float("nan")] * n, index=df_day.index)
    return pct[short_cols].mean(axis=1) - pct[long_cols].mean(axis=1)


def compute_rank_trend_slope(df_hist: pd.DataFrame, available_dates: list,
                             target_date, window: int = SLOPE_WINDOW) -> pd.Series:
    """Least-squares slope of each group's rank_ytd over the last `window` sessions.

    df_hist is the full multi-date snapshot. x = session index (0..k-1), y =
    rank_ytd. Raw slope is negative when rank improves (rank 1 = best), so we
    negate: positive = improving, matching the delta sign convention. Returns a
    Series indexed by name; NaN when fewer than 2 sessions of history exist.
    """
    # Sessions from oldest to newest, ending at target_date.
    if target_date not in available_dates:
        return pd.Series(dtype=float)
    end = available_dates.index(target_date)
    start = max(0, end - window + 1)
    sessions = available_dates[start:end + 1]
    if len(sessions) < 2:
        return pd.Series(dtype=float)

    # Build name -> [(x, rank_ytd), ...] across the window, ranking each day.
    per_name = {}
    for x, d in enumerate(sessions):
        day = compute_ranks(df_hist[df_hist["date"] == d])
        for _, r in day.iterrows():
            ry = r.get("rank_ytd")
            if ry is not None and not (isinstance(ry, float) and math.isnan(ry)):
                per_name.setdefault(r["name"], []).append((x, float(ry)))

    slopes = {}
    for name, pts in per_name.items():
        if len(pts) < 2:
            slopes[name] = float("nan")
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        mx = sum(xs) / len(xs)
        my = sum(ys) / len(ys)
        denom = sum((x - mx) ** 2 for x in xs)
        if denom == 0:
            slopes[name] = float("nan")
            continue
        raw = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom
        slopes[name] = -raw  # negate so positive = improving rank
    return pd.Series(slopes)


# ---------------------------------------------------------------------------
# Benchmark helpers
# ---------------------------------------------------------------------------

def load_benchmark(csv_path: Path) -> pd.DataFrame:
    """Load benchmark (SPY) snapshots CSV. Returns empty DataFrame if missing."""
    if not csv_path.exists():
        return pd.DataFrame(columns=BENCH_CSV_COLUMNS)
    df = pd.read_csv(csv_path)
    if df.empty:
        return pd.DataFrame(columns=BENCH_CSV_COLUMNS)
    for col in ["perf_day", "perf_week", "perf_month", "perf_quarter",
                "perf_half", "perf_year", "perf_ytd"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    return df


# ---------------------------------------------------------------------------
# RS (relative-strength vs SPY) pure functions
# ---------------------------------------------------------------------------

def compute_rs_score(df_day: pd.DataFrame) -> pd.Series:
    """RS score: fraction of 6 timeframes (week → YTD) where the group beats SPY.

    Day excluded from the score — a single session's spread is too noisy.
    rs_day is still stored and surfaced for context (the 'held up on a down day'
    signal), but does not count toward the breadth score.
    Score 1.0 = outperforming S&P 500 in every counted timeframe; 0.0 = trailing.
    Unlike momentum_score (cross-sectional peer rank), this is an absolute signal
    — a rising tide lifting all groups does not inflate the score.
    NaN when no RS spread columns have valid data.
    """
    n = len(df_day)
    if n == 0:
        return pd.Series([], dtype=float)

    scores = pd.DataFrame(index=df_day.index)
    for col in RS_SCORE_TIMEFRAMES:
        if col in df_day.columns and df_day[col].notna().any():
            # 1.0 where rs > 0, 0.0 where rs <= 0, NaN preserved for mean(skipna)
            scores[col] = (df_day[col] > 0).astype(float).where(df_day[col].notna())

    if scores.empty:
        return pd.Series([float("nan")] * n, index=df_day.index)

    return scores.mean(axis=1)


def compute_rs_agreement(df_day: pd.DataFrame) -> pd.Series:
    """RS agreement: sign consistency of RS spreads across medium timeframes.

    Uses rs_month, rs_quarter, rs_half. Score 1.0 = all three agree on direction
    (consistently beating or consistently lagging SPY); lower = mixed signals.
    Computed as |mean(sign)| where sign = +1 if rs > 0, −1 if rs < 0, 0 if exact zero.
    Returns NaN when fewer than 3 RS agreement columns have valid data.
    """
    n = len(df_day)
    if n == 0:
        return pd.Series([], dtype=float)

    sign_df = pd.DataFrame(index=df_day.index)
    for col in RS_AGREEMENT_COLS:
        if col in df_day.columns and df_day[col].notna().any():
            # +1 if > 0, -1 if < 0, 0 if exactly zero; NaN preserved
            sign_df[col] = df_day[col].apply(
                lambda x: float("nan") if (isinstance(x, float) and math.isnan(x))
                else (1.0 if x > 0 else (-1.0 if x < 0 else 0.0))
            )

    if sign_df.shape[1] < 3:
        return pd.Series([float("nan")] * n, index=df_day.index)

    return sign_df.mean(axis=1).abs()


def compute_rs_slope(df_hist: pd.DataFrame, bench_df: pd.DataFrame,
                     available_dates: list, target_date,
                     window: int = SLOPE_WINDOW) -> pd.Series:
    """Slope of RS_SLOPE_COL (rs_month) spread over the last `window` sessions.

    Positive = group's relative strength vs SPY is building (pulling further
    ahead of the market). Unlike rank_trend_slope, no negation is needed:
    higher rs_month = better RS.

    Returns empty Series if target_date not in available_dates or
    fewer than 2 sessions of SPY + group data overlap.
    """
    if target_date not in available_dates or bench_df is None or bench_df.empty:
        return pd.Series(dtype=float)
    end = available_dates.index(target_date)
    start = max(0, end - window + 1)
    sessions = available_dates[start:end + 1]
    if len(sessions) < 2:
        return pd.Series(dtype=float)

    # perf column underlying RS_SLOPE_COL (e.g. rs_month → perf_month)
    group_col = "perf_" + RS_SLOPE_COL[3:]

    per_name: dict = {}
    for x, d in enumerate(sessions):
        day_groups = df_hist[df_hist["date"] == d]
        spy_rows = bench_df[bench_df["date"] == d]
        if spy_rows.empty:
            continue
        spy_val = spy_rows[group_col].iloc[0] if group_col in spy_rows.columns else float("nan")
        if pd.isna(spy_val):
            continue
        for _, r in day_groups.iterrows():
            g_val = r.get(group_col)
            if pd.isna(g_val):
                continue
            per_name.setdefault(r["name"], []).append((x, float(g_val) - float(spy_val)))

    slopes: dict = {}
    for name, pts in per_name.items():
        if len(pts) < 2:
            slopes[name] = float("nan")
            continue
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        denom = sum((xi - mx) ** 2 for xi in xs)
        if denom == 0:
            slopes[name] = float("nan")
            continue
        slopes[name] = sum((xi - mx) * (yi - my) for xi, yi in zip(xs, ys)) / denom
    return pd.Series(slopes)


def compute_rs_regime(df_day: pd.DataFrame) -> pd.Series:
    """Short-horizon RS breadth minus long-horizon RS breadth.

    Short bucket (rs_week, rs_month): fraction of timeframes where the group beats SPY.
    Long bucket (rs_quarter, rs_half, rs_year): same.
    Result = short_breadth − long_breadth. Range [−1, 1].

    Positive = emerging RS leader: beating the market recently, not historically.
    Negative = established RS leader (or its reverse, a long-term laggard now fading).
    NaN if either bucket has no valid RS columns.
    """
    n = len(df_day)
    if n == 0:
        return pd.Series([], dtype=float)

    def _breadth(cols: list) -> pd.Series:
        vals = pd.DataFrame(index=df_day.index)
        for col in cols:
            if col in df_day.columns and df_day[col].notna().any():
                vals[col] = (df_day[col] > 0).astype(float).where(df_day[col].notna())
        if vals.empty:
            return pd.Series([float("nan")] * n, index=df_day.index)
        return vals.mean(axis=1)

    short = _breadth(RS_REGIME_SHORT)
    long_ = _breadth(RS_REGIME_LONG)
    result = short - long_
    return result.where(short.notna() & long_.notna())


# ---------------------------------------------------------------------------
# RS discrete flag pure functions (Tier 5)
# ---------------------------------------------------------------------------

def compute_beats_benchmark(df_today: pd.DataFrame) -> pd.DataFrame:
    """Boolean columns: does each group beat SPY for each timeframe?

    beats_benchmark_X = 1 when rs_X > 0, 0 when rs_X ≤ 0, NaN when rs_X is NaN.
    The 7 columns parallel RS_BEAT_TIMEFRAMES; their presence in df_today is
    gated upstream (rs_* are NaN when no SPY data exists for the date).
    """
    out = pd.DataFrame(index=df_today.index)
    for tf in RS_BEAT_TIMEFRAMES:
        rs_col = "rs_" + tf
        bb_col = "beats_benchmark_" + tf
        if rs_col in df_today.columns:
            out[bb_col] = df_today[rs_col].apply(
                lambda v: float("nan") if pd.isna(v) else (1 if v > 0 else 0)
            )
        else:
            out[bb_col] = float("nan")
    return out


def _build_rs_history(df_hist: pd.DataFrame, bench_df: pd.DataFrame,
                      available_dates: list, target_date,
                      window: int) -> dict:
    """Shared helper: build {name: [(session_x, rs_month_val), ...]} for the window.

    Returns a dict of (session_index, rs_month_spread) pairs per group name.
    Sessions where SPY data is absent are skipped; names with no data are absent.
    The session index (x) ranges 0..len(sessions)-1 with target_date at the end.
    """
    if target_date not in available_dates or bench_df is None or bench_df.empty:
        return {}
    end = available_dates.index(target_date)
    start = max(0, end - window + 1)
    sessions = available_dates[start:end + 1]
    if len(sessions) < 2:
        return {}

    group_col = "perf_" + RS_SLOPE_COL[3:]  # perf_month for RS_SLOPE_COL = "rs_month"
    per_name: dict = {}
    for x, d in enumerate(sessions):
        day_groups = df_hist[df_hist["date"] == d]
        spy_rows = bench_df[bench_df["date"] == d]
        if spy_rows.empty:
            continue
        spy_val = spy_rows[group_col].iloc[0] if group_col in spy_rows.columns else float("nan")
        if pd.isna(spy_val):
            continue
        for _, r in day_groups.iterrows():
            g_val = r.get(group_col)
            if not pd.isna(g_val):
                per_name.setdefault(r["name"], []).append((x, float(g_val) - float(spy_val)))
    return per_name


def compute_rs_new_high(df_hist: pd.DataFrame, bench_df: pd.DataFrame,
                        available_dates: list, target_date,
                        window: int = RS_NEW_HIGH_WINDOW) -> pd.Series:
    """1 if today's rs_month is at its RS_NEW_HIGH_WINDOW-session high; 0 otherwise.

    Uses RS_SLOPE_COL (rs_month) as the canonical RS line — consistent with
    rs_slope and rs_accel. NaN when fewer than 2 sessions of overlapping
    group + SPY data exist in the window.
    """
    per_name = _build_rs_history(df_hist, bench_df, available_dates, target_date, window)
    if not per_name:
        return pd.Series(dtype=float)

    end = available_dates.index(target_date)
    start = max(0, end - window + 1)
    last_x = len(available_dates[start:end + 1]) - 1

    result = {}
    for name, pts in per_name.items():
        today_vals = [v for x, v in pts if x == last_x]
        # Need today's point AND at least one prior overlapping session: a "new
        # high" is meaningless with a single observation. A group with only one
        # SPY-overlapping session in the window (e.g. sparse benchmark history)
        # would otherwise trivially satisfy today_rs >= window_max and flag 1.
        if not today_vals or len(pts) < 2:
            result[name] = float("nan")
            continue
        today_rs = today_vals[0]
        # pts includes today, so window_max >= today_rs always; >= is equivalent to == window_max
        window_max = max(v for _, v in pts)
        result[name] = 1 if today_rs >= window_max else 0
    return pd.Series(result)


def compute_rs_cross(df_hist: pd.DataFrame, bench_df: pd.DataFrame,
                     available_dates: list, target_date,
                     window: int = RS_CROSS_WINDOW) -> pd.Series:
    """1 if rs_month crossed from ≤ 0 to > 0 within the last RS_CROSS_WINDOW sessions.

    Classic rotation-trigger signal: the group just flipped from lagging to
    beating the market. Requires today's rs_month > 0 AND at least one prior
    session in the window where rs_month ≤ 0. Returns 0 when today's RS is
    non-positive, or when the group has been above 0 throughout the window.
    NaN when fewer than 2 sessions of overlapping data exist.
    """
    per_name = _build_rs_history(df_hist, bench_df, available_dates, target_date, window)
    if not per_name:
        return pd.Series(dtype=float)

    end = available_dates.index(target_date)
    start = max(0, end - window + 1)
    last_x = len(available_dates[start:end + 1]) - 1

    result = {}
    for name, pts in per_name.items():
        sorted_pts = sorted(pts, key=lambda p: p[0])
        today_vals = [v for x, v in sorted_pts if x == last_x]
        # A cross requires today plus at least one prior overlapping session to
        # compare against; a single observation cannot have "crossed" anything.
        if not today_vals or len(sorted_pts) < 2:
            result[name] = float("nan")
            continue
        today_rs = today_vals[0]
        if today_rs > 0:
            prior_values = [v for x, v in sorted_pts if x < last_x]
            result[name] = 1 if any(v <= 0 for v in prior_values) else 0
        else:
            result[name] = 0
    return pd.Series(result)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_for_group(group_type: str, target_date_str: str = None,
                      snap_path: Path = None, delta_path: Path = None,
                      bench_df: pd.DataFrame = None):
    subdir = "sectors" if group_type == "sector" else "industries"
    if snap_path is None:
        snap_path = DATA_DIR / subdir / "snapshots.csv"
    if delta_path is None:
        delta_path = DATA_DIR / subdir / "deltas.csv"

    ensure_deltas_csv(delta_path)

    df = load_snapshots(snap_path)
    if df.empty or "date" not in df.columns:
        print(f"  [{group_type}] No snapshot data available. Skipping.")
        return

    available_dates = sorted(df["date"].dropna().unique())
    if not available_dates:
        print(f"  [{group_type}] No valid dates in snapshot. Skipping.")
        return

    # Determine target date
    if target_date_str:
        target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    else:
        target_date = available_dates[-1]

    print(f"  [{group_type}] Computing deltas for date={target_date}")

    df_today = df[df["date"] == target_date].copy()
    if df_today.empty:
        print(f"  [{group_type}] No data for {target_date}. Skipping.")
        return

    # Last-write-wins: evict any existing rows for the target date so a later
    # (e.g. end-of-day) run recomputes them from the freshest snapshot instead
    # of locking in the first run's intraday ranks. Done after the emptiness
    # check above so we never wipe good rows when today's snapshot is missing.
    _evict_date_rows(delta_path, str(target_date))

    df_today = compute_ranks(df_today)
    df_today["momentum_score"] = compute_momentum(df_today)
    df_today["rank_agreement"] = compute_rank_agreement(df_today)
    # Confirmed momentum: broad strength (momentum_score) gated by cross-timeframe
    # consistency (rank_agreement). High only when the trend is corroborated.
    df_today["momentum_confirmed"] = df_today["momentum_score"] * df_today["rank_agreement"]
    df_today["momentum_weighted_mid"] = weighted_momentum(df_today, WEIGHTS_MID)
    df_today["momentum_weighted_fast"] = weighted_momentum(df_today, WEIGHTS_FAST)
    df_today["regime_short_long"] = compute_regime(df_today)

    # Rank-trend slope over the trailing SLOPE_WINDOW sessions.
    slope = compute_rank_trend_slope(df, available_dates, target_date)
    df_today["rank_trend_slope"] = df_today["name"].map(slope)

    # Pre-load lookback snapshots, indexed by trading-session offset.
    lookback_frames = {}
    for n_sessions in LOOKBACK_WINDOWS:
        prior_date = find_trading_date_back(available_dates, target_date, n_sessions)
        if prior_date and prior_date != target_date:
            df_prior = df[df["date"] == prior_date].copy()
            df_prior = compute_ranks(df_prior)
            lookback_frames[n_sessions] = df_prior.set_index("name")
        else:
            lookback_frames[n_sessions] = None

    # Momentum acceleration: today's momentum_score minus its value ACCEL_WINDOW
    # sessions ago. Positive = broad momentum is building.
    accel_date = find_trading_date_back(available_dates, target_date, ACCEL_WINDOW)
    if accel_date and accel_date != target_date:
        df_accel = compute_ranks(df[df["date"] == accel_date].copy())
        prior_mom = compute_momentum(df_accel)
        prior_mom.index = df_accel["name"].values
        df_today["momentum_accel"] = (
            df_today["momentum_score"].values
            - df_today["name"].map(prior_mom).values
        )
    else:
        df_today["momentum_accel"] = float("nan")

    # RS signals: require SPY benchmark data for the target date.
    # All RS columns are NaN when benchmark data is absent or missing for this date.
    spy_rows = (
        bench_df[bench_df["date"] == target_date]
        if bench_df is not None and not bench_df.empty
        else pd.DataFrame()
    )

    if not spy_rows.empty:
        spy_row = spy_rows.iloc[0]

        # Tier 1: raw RS spreads — group_perf_X − SPY_perf_X per timeframe.
        for tf in RS_TIMEFRAMES:
            group_col = "perf_" + tf[3:]  # e.g. rs_week → perf_week
            spy_val = spy_row.get(group_col, float("nan"))
            if not pd.isna(spy_val) and group_col in df_today.columns:
                df_today[tf] = df_today[group_col] - float(spy_val)
            else:
                df_today[tf] = float("nan")

        # Tier 2: aggregate RS — breadth and consistency of RS spreads.
        df_today["rs_score"] = compute_rs_score(df_today)
        df_today["rs_agreement"] = compute_rs_agreement(df_today)
        df_today["rs_confirmed"] = df_today["rs_score"] * df_today["rs_agreement"]

        # Tier 3: RS trend and acceleration.
        rs_slope_s = compute_rs_slope(df, bench_df, available_dates, target_date)
        df_today["rs_slope"] = df_today["name"].map(rs_slope_s)

        rs_accel_date = find_trading_date_back(available_dates, target_date, ACCEL_WINDOW)
        if rs_accel_date and rs_accel_date != target_date:
            df_accel_groups = df[df["date"] == rs_accel_date].copy()
            spy_accel = bench_df[bench_df["date"] == rs_accel_date]
            if not df_accel_groups.empty and not spy_accel.empty:
                spy_accel_row = spy_accel.iloc[0]
                for tf in RS_TIMEFRAMES:
                    group_col = "perf_" + tf[3:]
                    a_val = spy_accel_row.get(group_col, float("nan"))
                    if not pd.isna(a_val) and group_col in df_accel_groups.columns:
                        df_accel_groups[tf] = df_accel_groups[group_col] - float(a_val)
                    else:
                        df_accel_groups[tf] = float("nan")
                prior_rs = compute_rs_score(df_accel_groups)
                prior_rs.index = df_accel_groups["name"].values
                df_today["rs_accel"] = (
                    df_today["rs_score"].values
                    - df_today["name"].map(prior_rs).values
                )
            else:
                df_today["rs_accel"] = float("nan")
        else:
            df_today["rs_accel"] = float("nan")

        # Tier 4: RS regime — short-horizon vs long-horizon RS.
        df_today["rs_regime_short_long"] = compute_rs_regime(df_today)

        # Tier 5: discrete flags — beats_benchmark_X, rs_new_high, rs_cross.
        bb_df = compute_beats_benchmark(df_today)
        for bb_col in bb_df.columns:
            df_today[bb_col] = bb_df[bb_col]

        new_high_s = compute_rs_new_high(df, bench_df, available_dates, target_date)
        df_today["rs_new_high"] = df_today["name"].map(new_high_s)

        cross_s = compute_rs_cross(df, bench_df, available_dates, target_date)
        df_today["rs_cross"] = df_today["name"].map(cross_s)

    else:
        # No SPY data for this date → all RS columns NaN.
        for col in RS_COLS:
            df_today[col] = float("nan")

    # Build output rows
    new_rows = []
    for _, row in df_today.iterrows():
        out = {
            "date": str(target_date),
            "name": row["name"],
            "rank_day": _fmt(row.get("rank_day")),
            "rank_week": _fmt(row.get("rank_week")),
            "rank_month": _fmt(row.get("rank_month")),
            "rank_quarter": _fmt(row.get("rank_quarter")),
            "rank_half": _fmt(row.get("rank_half")),
            "rank_year": _fmt(row.get("rank_year")),
            "rank_ytd": _fmt(row.get("rank_ytd")),
        }

        for n_sessions in LOOKBACK_WINDOWS:
            prior_df = lookback_frames[n_sessions]
            name = row["name"]

            # Rank deltas: rank_prior - rank_today (positive = improved = moved up)
            for rank_col in RANK_DELTA_METRICS:
                delta_col = f"{rank_col}_delta_{n_sessions}d"
                if prior_df is not None and name in prior_df.index:
                    prior_rank = prior_df.loc[name, rank_col] if rank_col in prior_df.columns else float("nan")
                    today_rank = row.get(rank_col, float("nan"))
                    try:
                        val = float(prior_rank) - float(today_rank)
                    except (TypeError, ValueError):
                        val = float("nan")
                else:
                    val = float("nan")
                out[delta_col] = _fmt(val)

            # Perf deltas: today - prior (positive = perf improved over window)
            for perf_col in PERF_DELTA_METRICS:
                delta_col = f"{perf_col}_delta_{n_sessions}d"
                if prior_df is not None and name in prior_df.index and perf_col in prior_df.columns:
                    prior_val = prior_df.loc[name, perf_col]
                    today_val = row.get(perf_col, float("nan"))
                    try:
                        val = float(today_val) - float(prior_val)
                    except (TypeError, ValueError):
                        val = float("nan")
                else:
                    val = float("nan")
                out[delta_col] = _fmt(val)

        for mcol in MOMENTUM_COLS:
            out[mcol] = _fmt(row.get(mcol))
        for rs_col in RS_COLS:
            out[rs_col] = _fmt(row.get(rs_col))
        new_rows.append(out)

    if not new_rows:
        print(f"  [{group_type}] No new delta rows to append.")
        return

    with open(delta_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DELTA_COLUMNS)
        for row in new_rows:
            writer.writerow({col: row.get(col, "") for col in DELTA_COLUMNS})

    print(f"  [{group_type}] Appended {len(new_rows)} delta rows to {delta_path}")


def _fmt(val):
    """Format a numeric value for CSV: empty string if NaN/None."""
    if val is None:
        return ""
    try:
        if math.isnan(float(val)):
            return ""
        return val
    except (TypeError, ValueError):
        return ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Compute rank/delta artifacts from snapshots.")
    parser.add_argument("--date", default=None, help="Target date YYYY-MM-DD (default: latest in snapshot)")
    args = parser.parse_args()

    bench_path = DATA_DIR / "benchmark" / "snapshots.csv"
    bench_df = load_benchmark(bench_path)
    if bench_df.empty:
        print("  [info] No benchmark data found — RS columns will be NaN.")

    for group_type in ("sector", "industry"):
        compute_for_group(group_type, args.date, bench_df=bench_df)

    print("\nDone.")


if __name__ == "__main__":
    main()
