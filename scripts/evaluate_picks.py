#!/usr/bin/env python3
"""Picks alpha scoreboard — the measurement instrument for PICKS-4.

Computes forward returns for every group the Picks selector chose, versus SPY
and versus the same-window cross-sectional median of ALL tracked industries
(the honest alpha control), and writes them to
``data/picks/eval/group_scores.csv``. ``--report`` prints the roll-up
(per-bucket stats + the paired per-date selected-vs-non-selected test) so
every future alpha re-assessment is a command, not a hand analysis.

Design decisions (deviations from planning/picks-alpha-evaluation.md, made
deliberately — see knowledge/investigations/picks-alpha-assessment-2026-07-14.md
for the methodology this automates):

- group_scores.csv is a DERIVED artifact, fully rebuilt on every run from
  picks.csv + snapshots (deterministic, idempotent). Not append-only: a full
  rebuild makes partial-horizon rows self-correct for free and eliminates the
  last-write-wins partial-rewrite bug class. Rows with n_sessions_avail <
  horizon are "unsettled" and change on later runs by design.
- Each row also stores the non-selected control (fwd_ret_nonsel_mean /
  excess_nonsel) — without it the paired per-date test, the single most
  honest number, could not be computed from the scoreboard alone.
- No ticker_scores.csv yet: the internal price chain is survivorship-biased
  (spec Part 3.1); stock-level scoring waits for real OHLC (PICKS-4B).

Reads only committed CSVs; no network. Run daily after compute_deltas.py
(wired as a step in collect.yml — NOT a separate workflow, so it rides the
existing finviz-data-commit concurrency group instead of racing it).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PICKS_CSV = ROOT / "data" / "picks" / "picks.csv"
INDUSTRY_SNAPSHOTS_CSV = ROOT / "data" / "industries" / "snapshots.csv"
BENCHMARK_CSV = ROOT / "data" / "benchmark" / "snapshots.csv"
SCORES_CSV = ROOT / "data" / "picks" / "eval" / "group_scores.csv"

# Forward horizons in TRADING SESSIONS (positional in the snapshot date list,
# so weekends/holidays are skipped for free — same convention as
# find_trading_date_back in compute_deltas.py). Adding a horizon is safe (full
# rebuild); removing one silently drops its rows on the next run.
HORIZONS = [1, 3, 5, 10]

# Below this many distinct settled pick dates the report prints a
# "not yet powered" caveat — per the assessment's statistical-discipline rule
# (forward windows overlap heavily; rows are not independent, dates are the
# effective N). Don't tune the selector below this threshold.
MIN_POWERED_DATES = 40

SCORE_COLUMNS = [
    "pick_date", "group", "buckets", "selector_version", "horizon",
    "n_sessions_avail", "fwd_ret", "fwd_ret_spy", "fwd_ret_median",
    "n_nonsel", "fwd_ret_nonsel_mean",
    "excess_spy", "excess_median", "excess_nonsel",
]


def load_selected_groups(picks_csv: Path = PICKS_CSV) -> pd.DataFrame:
    """Unique (date, group) picks with pipe-joined bucket tags.

    Returns columns: pick_date, group, buckets, selector_version.
    Empty/headers-only picks.csv -> empty frame with those columns.
    """
    cols = ["pick_date", "group", "buckets", "selector_version"]
    if not picks_csv.exists():
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(
        picks_csv, usecols=["date", "list_category", "selector_version", "group"],
        dtype=str,
    )
    if len(df) == 0:
        return pd.DataFrame(columns=cols)
    grouped = (
        df.groupby(["date", "group"], sort=True)
        .agg(
            buckets=("list_category", lambda s: "|".join(sorted(set(s.dropna())))),
            selector_version=("selector_version", "first"),
        )
        .reset_index()
        .rename(columns={"date": "pick_date"})
    )
    return grouped[cols]


def _perf_matrix(snapshots: pd.DataFrame) -> pd.DataFrame:
    """date x name matrix of perf_day (raw %)."""
    snap = snapshots[["date", "name", "perf_day"]].copy()
    snap["perf_day"] = pd.to_numeric(snap["perf_day"], errors="coerce")
    # duplicate (date, name) shouldn't exist (dedup on write) — keep last if so
    snap = snap.drop_duplicates(subset=["date", "name"], keep="last")
    return snap.pivot(index="date", columns="name", values="perf_day").sort_index()


def _compound(values: np.ndarray) -> float:
    """Compound daily raw-% returns; NaN if any day is missing.

    Requiring a complete window (rather than skipping NaN days) keeps every
    group's forward return measured over the identical session set — skipping
    would silently compare unequal windows.
    """
    if len(values) == 0 or np.isnan(values).any():
        return float("nan")
    return float((np.prod(1.0 + values / 100.0) - 1.0) * 100.0)


def compute_scores(
    picks: pd.DataFrame,
    snapshots: pd.DataFrame,
    benchmark: pd.DataFrame,
    horizons: list[int] = HORIZONS,
) -> pd.DataFrame:
    """Build the full scoreboard frame (one row per pick_date x group x horizon).

    Rows with 0 available forward sessions are skipped (nothing to score);
    rows with 0 < n_sessions_avail < horizon carry the partial-window return
    and are naturally corrected on a later full rebuild.
    """
    if len(picks) == 0 or len(snapshots) == 0:
        return pd.DataFrame(columns=SCORE_COLUMNS)

    perf = _perf_matrix(snapshots)
    dates = list(perf.index)
    date_pos = {d: i for i, d in enumerate(dates)}

    bench = benchmark[["date", "perf_day"]].copy() if len(benchmark) else pd.DataFrame(columns=["date", "perf_day"])
    bench["perf_day"] = pd.to_numeric(bench.get("perf_day"), errors="coerce")
    spy = bench.drop_duplicates("date", keep="last").set_index("date")["perf_day"]

    rows = []
    for pick_date, day_picks in picks.groupby("pick_date", sort=True):
        if pick_date not in date_pos:
            continue  # picks stamped on a date with no snapshot — nothing to anchor to
        start = date_pos[pick_date] + 1  # forward window starts strictly after pick_date
        selected = set(day_picks["group"])
        for horizon in horizons:
            window = dates[start:start + horizon]
            n_avail = len(window)
            if n_avail == 0:
                continue
            sub = perf.loc[window]
            # per-industry forward return over the identical window
            fwd_all = sub.apply(lambda col: _compound(col.to_numpy()), axis=0)
            fwd_median = float(np.nanmedian(fwd_all)) if fwd_all.notna().any() else float("nan")
            nonsel = fwd_all[~fwd_all.index.isin(selected)].dropna()
            nonsel_mean = float(nonsel.mean()) if len(nonsel) else float("nan")
            fwd_spy = _compound(spy.reindex(window).to_numpy())
            for _, p in day_picks.iterrows():
                fwd = fwd_all.get(p["group"], float("nan"))
                rows.append({
                    "pick_date": pick_date,
                    "group": p["group"],
                    "buckets": p["buckets"],
                    "selector_version": p["selector_version"],
                    "horizon": horizon,
                    "n_sessions_avail": n_avail,
                    "fwd_ret": fwd,
                    "fwd_ret_spy": fwd_spy,
                    "fwd_ret_median": fwd_median,
                    "n_nonsel": len(nonsel),
                    "fwd_ret_nonsel_mean": nonsel_mean,
                    "excess_spy": fwd - fwd_spy,
                    "excess_median": fwd - fwd_median,
                    "excess_nonsel": fwd - nonsel_mean,
                })
    return pd.DataFrame(rows, columns=SCORE_COLUMNS)


def write_scores(scores: pd.DataFrame, out_csv: Path = SCORES_CSV) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out = scores.copy()
    for c in out.columns:
        if out[c].dtype == float:
            out[c] = out[c].round(4)
    out.to_csv(out_csv, index=False)


def _fmt(x: float) -> str:
    return "   NaN" if pd.isna(x) else f"{x:+6.2f}"


def print_report(scores: pd.DataFrame, min_powered: int = MIN_POWERED_DATES) -> None:
    """Roll-up over SETTLED rows only (n_sessions_avail == horizon)."""
    settled = scores[scores["n_sessions_avail"] == scores["horizon"]]
    if len(settled) == 0:
        print("No settled rows yet — nothing to report.")
        return

    n_dates = settled["pick_date"].nunique()
    print(f"Picks alpha scoreboard — {n_dates} distinct settled pick dates")
    if n_dates < min_powered:
        print(f"⚠  NOT YET POWERED (< {min_powered} dates) — treat every number as "
              "directional only; do not tune the selector on this.")

    print("\n== Overall (settled rows), by horizon ==")
    print("  h    N  dates | exSPY mean/med  hit | exMED mean/med  hit | exNONSEL mean")
    for h, g in settled.groupby("horizon"):
        v = g.dropna(subset=["excess_spy"])
        m = g.dropna(subset=["excess_median"])
        p = g.dropna(subset=["excess_nonsel"])
        hit_spy = (v["excess_spy"] > 0).mean() * 100 if len(v) else float("nan")
        hit_med = (m["excess_median"] > 0).mean() * 100 if len(m) else float("nan")
        print(f"  {h:>2} {len(g):>4} {g['pick_date'].nunique():>5} |"
              f" {_fmt(v['excess_spy'].mean())}/{_fmt(v['excess_spy'].median())} {hit_spy:3.0f}% |"
              f" {_fmt(m['excess_median'].mean())}/{_fmt(m['excess_median'].median())} {hit_med:3.0f}% |"
              f" {_fmt(p['excess_nonsel'].mean())}")

    print("\n== By bucket (a group can carry multiple tags), by horizon ==")
    exploded = settled.assign(bucket=settled["buckets"].str.split("|")).explode("bucket")
    print("  bucket        h    N | exSPY mean  hit | exMED mean  hit")
    for (b, h), g in exploded.groupby(["bucket", "horizon"]):
        v = g.dropna(subset=["excess_spy"])
        m = g.dropna(subset=["excess_median"])
        hit_spy = (v["excess_spy"] > 0).mean() * 100 if len(v) else float("nan")
        hit_med = (m["excess_median"] > 0).mean() * 100 if len(m) else float("nan")
        print(f"  {b:<12} {h:>2} {len(g):>4} | {_fmt(v['excess_spy'].mean())} {hit_spy:5.0f}% |"
              f" {_fmt(m['excess_median'].mean())} {hit_med:5.0f}%")

    print("\n== Paired per-date test (mean selected fwd_ret − mean non-selected, same window) ==")
    print("  The most honest number: cancels the market factor date by date.")
    for h, g in settled.groupby("horizon"):
        per_date = g.groupby("pick_date").apply(
            lambda d: d["fwd_ret"].mean() - d["fwd_ret_nonsel_mean"].iloc[0],
            include_groups=False,
        ).dropna()
        if len(per_date) == 0:
            continue
        pos = int((per_date > 0).sum())
        print(f"  h={h:>2}: mean {_fmt(per_date.mean())}  ({pos}/{len(per_date)} dates positive)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--report", action="store_true",
                    help="print the roll-up from the existing scoreboard (no rebuild)")
    ap.add_argument("--min-settled", type=int, default=MIN_POWERED_DATES,
                    help="settled-date count below which the report prints the low-power caveat")
    args = ap.parse_args()

    if args.report:
        if not SCORES_CSV.exists():
            print(f"{SCORES_CSV} not found — run without --report first to build it.")
            return
        print_report(pd.read_csv(SCORES_CSV, dtype={"pick_date": str}), args.min_settled)
        return

    picks = load_selected_groups()
    snapshots = pd.read_csv(INDUSTRY_SNAPSHOTS_CSV, dtype={"date": str})
    benchmark = pd.read_csv(BENCHMARK_CSV, dtype={"date": str}) if BENCHMARK_CSV.exists() \
        else pd.DataFrame(columns=["date", "perf_day"])
    scores = compute_scores(picks, snapshots, benchmark)
    write_scores(scores)
    settled = scores[scores["n_sessions_avail"] == scores["horizon"]] if len(scores) else scores
    print(f"Wrote {len(scores)} rows ({len(settled)} settled, "
          f"{scores['pick_date'].nunique() if len(scores) else 0} pick dates) -> {SCORES_CSV}")


if __name__ == "__main__":
    main()
