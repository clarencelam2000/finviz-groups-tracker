"""
replay_picks.py — deterministically reconstruct a historical Picks (All/Focus) view.

Given `data/picks/picks.csv` (raw scraped data, all columns needed for replay already
present) and `data/picks/display_methodology.json` (versioned filter/ranking constants),
reproduces exactly what the PWA would have shown for any past date under any
methodology version — enabling A/B testing across methodology changes.

Mirrors the JS logic in docs/index.html (renderPicks / computeFocusScores) closely
enough for the v1 methodology (see display_methodology.json's `known_gaps` block for
what v1 intentionally does not model: Phase 3d liquidity/earnings penalties and the
Phase 4 Ariel-match filter — tracked as PICKS-METH-V2 in .session/SPRINT.md).

See planning/picks-methodology-tracking.md for the full design spec this implements.
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).parent.parent
PICKS_CSV = BASE_DIR / "data" / "picks" / "picks.csv"
METHODOLOGY_PATH = BASE_DIR / "data" / "picks" / "display_methodology.json"

PICKS_PIPELINE_START_DATE = "2026-06-25"


def _parse_cap_b(series: pd.Series) -> pd.Series:
    """Parse 'Market Cap' strings like '345.79B', '456M', '1.2T' -> float billions.
    Mirrors JS _pCapB(). Returns NaN for '-' or unparseable values."""

    def _one(v):
        if not v or str(v).strip() in ("", "-"):
            return float("nan")
        s = str(v).strip()
        suffix_map = {"T": 1000, "B": 1, "M": 0.001, "K": 0.000001}
        last = s[-1].upper()
        if last in suffix_map:
            try:
                return float(s[:-1]) * suffix_map[last]
            except (ValueError, TypeError):
                return float("nan")
        try:
            return float(s)
        except (ValueError, TypeError):
            return float("nan")

    return series.apply(_one)


def _parse_pct(series: pd.Series) -> pd.Series:
    """Parse SMA* distance strings like '8.33%' or '8.33' -> float.
    Mirrors JS _pPct(): strips '%' suffix then parses. Returns NaN for '-'."""
    return pd.to_numeric(
        series.astype(str).str.replace("%", "", regex=False),
        errors="coerce",
    )


def load_methodology(date: str, override: str = None) -> dict:
    """Return the methodology version entry in effect on `date` (or `override`).

    Lookup: largest `effective_date` <= `date` among `versions[]` (assumed
    newest-first, per display_methodology.json's authoring convention).
    """
    registry = json.loads(METHODOLOGY_PATH.read_text())
    versions = registry["versions"]

    if override is not None:
        for v in versions:
            if v["version"] == override:
                return v
        raise ValueError(f"Unknown methodology version {override!r}")

    for v in versions:
        if v["effective_date"] <= date:
            return v
    raise ValueError(f"No methodology version effective on or before {date!r}")


def normalize_inv(series: pd.Series, min_pool: int) -> pd.Series:
    """Inverted normalization: lower raw -> higher score (1.0 = best).
    Mirrors JS computeFocusScores' normalizeInv() exactly.
    NaN always -> 0.5 (neutral). n=1 valid value -> 1.0.
    """
    valid = series.dropna()
    if len(valid) == 0:
        return pd.Series(0.5, index=series.index)
    n = len(series)
    if n < min_pool:
        # Rank-based percentile for small pools (avoids jumpy min-max).
        sorted_valid = sorted(valid.tolist())
        m = len(sorted_valid)

        def _rank_score(v):
            if pd.isna(v):
                return 0.5  # NaN -> neutral (not 1.0 even when m=1)
            rank = sorted_valid.index(v)  # 0 = lowest raw = best
            return 1.0 if m == 1 else 1.0 - rank / (m - 1)

        return series.map(_rank_score)
    mn, mx = valid.min(), valid.max()
    if mx == mn:
        return pd.Series(0.5, index=series.index)
    return ((mx - series) / (mx - mn)).fillna(0.5)


def _load_and_filter_to_date(target_date: str) -> pd.DataFrame:
    df = pd.read_csv(PICKS_CSV, dtype=str)
    df = df[df["date"] == target_date]
    if len(df) == 0:
        if target_date < PICKS_PIPELINE_START_DATE:
            raise ValueError(
                f"No picks for {target_date}: picks pipeline started "
                f"{PICKS_PIPELINE_START_DATE}."
            )
        raise ValueError(
            f"No picks found for {target_date}. The date is valid but no data was "
            "captured (possible causes: weekend/holiday, Cloudflare block that "
            "aborted the run before writing)."
        )
    return df.reset_index(drop=True)


def _apply_base_filter(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    cap_b = _parse_cap_b(df["Market Cap"])
    df = df[cap_b > p["base_filter"]["min_market_cap_b"]].copy()

    sma50 = _parse_pct(df["SMA50"])
    sma200 = _parse_pct(df["SMA200"])
    sma20 = _parse_pct(df["SMA20"])

    ma_pass = (sma50 > 0) | (sma200 > 0) | (sma50 > sma20)
    return df[ma_pass].copy()


def _replay_all(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    cat_order = p["all_view_sort"]["category_order"]

    atr_n = pd.to_numeric(df["atr_ext_50"], errors="coerce")
    cat_rank = (
        df["list_category"]
        .map({c: i for i, c in enumerate(cat_order)})
        .fillna(len(cat_order))
    )

    return (
        df.assign(_cat_rank=cat_rank, _atr_n=atr_n)
        .sort_values(
            ["_cat_rank", "group", "_atr_n"],
            ascending=[True, True, True],
            na_position="last",
        )
        .drop(columns=["_cat_rank", "_atr_n"])
        .reset_index(drop=True)
    )


def _replay_focus(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    atr = pd.to_numeric(df["atr_ext_50"], errors="coerce")
    focus_candidates = df[
        (atr > p["focus_dq"]["min_exclusive"]) & (atr <= p["focus_dq"]["max_inclusive"])
    ].copy()

    if len(focus_candidates) == 0:
        focus_candidates["focus_score"] = pd.Series(dtype=float)
        return focus_candidates

    if len(focus_candidates) == 1:
        focus_candidates["focus_score"] = 1.0
        return focus_candidates

    raw_group = pd.to_numeric(focus_candidates["grp_sum_mid_rank"], errors="coerce")

    r20 = pd.to_numeric(focus_candidates["risk_20ma_pct"], errors="coerce")
    r50 = pd.to_numeric(focus_candidates["risk_50ma_pct"], errors="coerce")
    raw_tight = pd.DataFrame({"r20": r20, "r50": r50}).apply(
        lambda row: min(
            (v for v in [row.r20, row.r50] if pd.notna(v) and v > 0),
            default=float("nan"),
        ),
        axis=1,
    )

    raw_quiet = pd.to_numeric(focus_candidates["range_atr"], errors="coerce")

    min_pool = p["focus_score"]["normalization"]["fallback_threshold"]
    w = p["focus_score"]["weights"]

    norm_group = normalize_inv(raw_group, min_pool)
    norm_tight = normalize_inv(raw_tight, min_pool)
    norm_quiet = normalize_inv(raw_quiet, min_pool)

    base = w["group"] * norm_group + w["tight"] * norm_tight + w["quiet"] * norm_quiet

    ep = p["focus_score"]["extension_penalty"]
    atr_focus = pd.to_numeric(focus_candidates["atr_ext_50"], errors="coerce")
    penalty_t = (
        ((atr_focus - ep["ramp_start"]) / (ep["ramp_end"] - ep["ramp_start"]))
        .clip(0, 1)
        .fillna(0)
    )
    penalty_frac = ep["max_fraction"] * penalty_t

    focus_candidates["focus_score"] = base * (1 - penalty_frac)
    return focus_candidates.sort_values("focus_score", ascending=False).reset_index(drop=True)


def replay(date: str = None, view: str = "all", methodology_version: str = None) -> pd.DataFrame:
    """Return picks in display order for the given date and view.

    Minimum output columns: ticker, group, list_category, atr_ext_50;
    Focus view adds focus_score.
    """
    if date is None:
        all_dates = pd.read_csv(PICKS_CSV, usecols=["date"], dtype=str)["date"]
        if len(all_dates) == 0:
            raise ValueError("picks.csv has no rows to replay.")
        date = all_dates.max()

    df = _load_and_filter_to_date(date)

    methodology = load_methodology(date, override=methodology_version)
    p = methodology["params"]

    df = _apply_base_filter(df, p)

    if view == "all":
        out = _replay_all(df, p)
        cols = ["ticker", "group", "list_category", "atr_ext_50"]
    elif view == "focus":
        out = _replay_focus(df, p)
        cols = ["ticker", "group", "list_category", "atr_ext_50", "focus_score"]
    else:
        raise ValueError(f"view must be 'all' or 'focus', got {view!r}")

    return out[[c for c in cols if c in out.columns]]


def main():
    parser = argparse.ArgumentParser(description="Replay a historical Picks view.")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD (default: max date in picks.csv)")
    parser.add_argument("--view", choices=["all", "focus"], default="all")
    parser.add_argument("--methodology-version", default=None, help="e.g. v1 (default: version effective on --date)")
    parser.add_argument("--pretty", action="store_true", help="styled terminal table (default: TSV)")
    args = parser.parse_args()

    try:
        out = replay(date=args.date, view=args.view, methodology_version=args.methodology_version)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.pretty:
        print(out.to_string(index=False))
    else:
        print(out.to_csv(index=False, sep="\t"), end="")


if __name__ == "__main__":
    main()
