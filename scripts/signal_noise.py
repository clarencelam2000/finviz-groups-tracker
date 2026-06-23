#!/usr/bin/env python3
"""
signal_noise.py — Rolling signal-to-noise check for momentum_score.

Computes mean |day-over-day Δmomentum_score| over a rolling window,
separately for sectors and industries. Lower = steadier signal.

Usage:
    python scripts/signal_noise.py                  # 20-session default window
    python scripts/signal_noise.py --window 10      # custom window
    python scripts/signal_noise.py --date 2026-06-18  # as-of a specific date

Output (per universe):
    - Mean and max rolling churn across all groups (lower = better)
    - Top 5 noisiest groups (candidates for closer inspection)

Suggested threshold once ≥20 sessions of data exist:
    mean |Δ| > 0.07 = signal may have regressed; investigate formula changes.
    (Baseline from Jun 9–18: sectors 0.058, industries 0.046 with 6-timeframe formula.)
"""

import argparse
from pathlib import Path

import pandas as pd

# Default rolling window, in trading sessions. 20 ≈ one calendar month.
# ACCEL_WINDOW in delta_config.py uses 10; 20 gives a more stable noise estimate.
DEFAULT_WINDOW = 20

DATA_PATHS = {
    "Sectors":    Path("data/sectors/deltas.csv"),
    "Industries": Path("data/industries/deltas.csv"),
}


def rolling_churn(
    df: pd.DataFrame,
    window: int = DEFAULT_WINDOW,
    as_of: str | None = None,
) -> pd.DataFrame:
    """Compute per-group rolling mean of |day-over-day Δmomentum_score|.

    Returns a DataFrame with columns [date, name, abs_delta, rolling_mean].
    Rows where abs_delta is NaN (first session per group, or NaN momentum)
    are dropped.

    Args:
        df: deltas CSV loaded as a DataFrame (must contain date/name/momentum_score).
        window: rolling window in trading sessions (min_periods=2 always).
        as_of: if given, truncate to dates ≤ this value before computing.
    """
    if "momentum_score" not in df.columns or df.empty:
        return pd.DataFrame(columns=["date", "name", "abs_delta", "rolling_mean"])

    df = df[["date", "name", "momentum_score"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["name", "date"])

    if as_of is not None:
        df = df[df["date"] <= pd.Timestamp(as_of)]

    # Day-over-day absolute delta per group (NaN on each group's first session)
    df["abs_delta"] = df.groupby("name")["momentum_score"].diff().abs()

    # Rolling mean over `window` sessions per group; min_periods=2 so early
    # sessions produce a meaningful (if narrow) estimate rather than NaN.
    df["rolling_mean"] = df.groupby("name")["abs_delta"].transform(
        lambda s: s.rolling(window, min_periods=2).mean()
    )

    result = df[["date", "name", "abs_delta", "rolling_mean"]].dropna(subset=["abs_delta"])
    return result.reset_index(drop=True)


def _summarize(label: str, path: Path, window: int, as_of: str | None) -> None:
    if not path.exists():
        print(f"\n{label}: data file not found ({path})")
        return

    df = pd.read_csv(path, low_memory=False)
    churn = rolling_churn(df, window=window, as_of=as_of)

    if churn.empty:
        print(f"\n{label}: no data (need ≥2 sessions with valid momentum_score)")
        return

    latest_date = churn["date"].max()
    latest = churn[churn["date"] == latest_date]

    mean_churn = latest["rolling_mean"].mean()
    max_churn = latest["rolling_mean"].max()
    n_groups = latest["name"].nunique()
    n_sessions = churn["date"].nunique()

    print(f"\n{label}  ({n_groups} groups · {n_sessions} sessions · "
          f"{window}-session window · as-of {latest_date.date()})")
    print(f"  Mean |Δmomentum_score|  {mean_churn:.4f}  (lower = steadier)")
    print(f"  Max  |Δmomentum_score|  {max_churn:.4f}  (worst single group)")

    top5 = latest.nlargest(5, "rolling_mean")[["name", "rolling_mean"]].reset_index(drop=True)
    if not top5.empty:
        print("  Top 5 noisiest groups:")
        for _, row in top5.iterrows():
            print(f"    {row['name']:<42} {row['rolling_mean']:.4f}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rolling momentum_score signal-to-noise report"
    )
    parser.add_argument(
        "--window", type=int, default=DEFAULT_WINDOW,
        help=f"Rolling window in trading sessions (default: {DEFAULT_WINDOW})"
    )
    parser.add_argument(
        "--date", default=None,
        help="As-of date YYYY-MM-DD (default: latest available)"
    )
    args = parser.parse_args()

    for label, path in DATA_PATHS.items():
        _summarize(label, path, window=args.window, as_of=args.date)
    print()


if __name__ == "__main__":
    main()
