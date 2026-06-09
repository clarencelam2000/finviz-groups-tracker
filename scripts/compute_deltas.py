"""
compute_deltas.py — Read snapshot CSVs and compute rank/delta artifacts,
appending to deltas CSVs.
"""

import argparse
import csv
import math
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

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

DELTA_COLUMNS = [
    "date", "name",
    "rank_day", "rank_week", "rank_month", "rank_quarter", "rank_half", "rank_year", "rank_ytd",
    "rank_week_delta_7d", "rank_week_delta_14d", "rank_week_delta_30d",
    "rank_month_delta_7d", "rank_month_delta_14d", "rank_month_delta_30d",
    "rank_ytd_delta_7d", "rank_ytd_delta_14d", "rank_ytd_delta_30d",
    "perf_week_delta_7d", "perf_week_delta_14d", "perf_week_delta_30d",
    "perf_month_delta_7d",
    "perf_ytd_delta_7d", "perf_ytd_delta_30d",
    "momentum_score",
]

PERF_RANK_METRICS = [
    "perf_day", "perf_week", "perf_month", "perf_quarter",
    "perf_half", "perf_year", "perf_ytd",
]

LOOKBACK_WINDOWS = [7, 14, 30]
DATE_TOLERANCE = 5  # extra calendar days to search for nearest date

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


def load_existing_keys(csv_path: Path) -> set:
    keys = set()
    if not csv_path.exists():
        return keys
    df = pd.read_csv(csv_path, dtype=str)
    if df.empty or "date" not in df.columns or "name" not in df.columns:
        return keys
    for _, row in df.iterrows():
        keys.add((row["date"], row["name"]))
    return keys


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
    """Find the closest available date that is <= target_date within tolerance."""
    candidates = [d for d in available_dates if d <= target_date]
    if not candidates:
        return None
    best = max(candidates)
    if (target_date - best).days <= tolerance_days:
        return best
    return None


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
    existing_keys = load_existing_keys(delta_path)

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

    df_today = compute_ranks(df_today)
    df_today["momentum_score"] = compute_momentum(df_today)

    # Pre-load lookback snapshots
    lookback_frames = {}
    for n_days in LOOKBACK_WINDOWS:
        prior_target = target_date - timedelta(days=n_days)
        prior_date = find_nearest_date(available_dates, prior_target)
        if prior_date and prior_date != target_date:
            df_prior = df[df["date"] == prior_date].copy()
            df_prior = compute_ranks(df_prior)
            lookback_frames[n_days] = df_prior.set_index("name")
        else:
            lookback_frames[n_days] = None

    # Build output rows
    new_rows = []
    for _, row in df_today.iterrows():
        key = (str(target_date), row["name"])
        if key in existing_keys:
            continue

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

        for n_days in LOOKBACK_WINDOWS:
            prior_df = lookback_frames[n_days]
            name = row["name"]

            # Rank deltas: rank_prior - rank_today (positive = improved = moved up)
            for rank_col, perf_col in [
                ("rank_week", "perf_week"),
                ("rank_month", "perf_month"),
                ("rank_ytd", "perf_ytd"),
            ]:
                delta_col = f"{rank_col}_delta_{n_days}d"
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

            # Perf deltas
            for perf_col in ["perf_week", "perf_month", "perf_ytd"]:
                # Not all combos required — check list
                delta_col = f"{perf_col}_delta_{n_days}d"
                if delta_col not in DELTA_COLUMNS:
                    continue
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

        out["momentum_score"] = _fmt(row.get("momentum_score"))
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
