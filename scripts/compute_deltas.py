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
    LOOKBACK_WINDOWS,
    MOMENTUM_COLS,
    PERF_DELTA_METRICS,
    PERF_RANK_METRICS,
    RANK_DELTA_METRICS,
    REGIME_LONG,
    REGIME_SHORT,
    SLOPE_WINDOW,
    WEIGHTS_FAST,
    WEIGHTS_MID,
    delta_columns,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"

SNAPSHOT_COLS = [
    "date", "collected_at", "group_type", "name", "stocks", "market_cap",
    "pe", "fwd_pe", "perf_day", "perf_week", "perf_month", "perf_quarter",
    "perf_half", "perf_year", "perf_ytd", "avg_volume", "rel_volume", "change",
]

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
    """Compute momentum_score: mean percentile across all 7 perf metrics."""
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
# Core computation
# ---------------------------------------------------------------------------

def compute_for_group(group_type: str, target_date_str: str = None,
                      snap_path: Path = None, delta_path: Path = None):
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

    for group_type in ("sector", "industry"):
        compute_for_group(group_type, args.date)

    print("\nDone.")


if __name__ == "__main__":
    main()
