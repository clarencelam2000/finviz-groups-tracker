#!/usr/bin/env python3
"""Emerging-signal alpha study — SPRINT § EMRG-2 / EMRG-7 / EMRG-1a.

Answers "is there alpha in the emerging signal?" by measuring the SIGNAL, not
the picks pipeline. Reads ``data/industries/deltas.csv`` directly and replays
the emerging gate over every group-day it fires on, so nothing here depends on
``picks.csv``'s 4-slot truncation or its selector-version breaks.

Why this exists alongside ``evaluate_picks.py`` rather than extending it:

- ``evaluate_picks.py`` scores rows and averages them. A day with 16 firing
  groups then contributes 16 rows and a day with 3 contributes 3, so the mean
  is dominated by broad-signal days — which are plausibly strong-market days.
  Part of the "edge" it reports could be market direction. This script
  collapses each date to ONE number (portfolio spread) so every date weighs the
  same, which is also the only shape that produces a readable equity curve.
- ``evaluate_picks.py`` grades the deployed selector (202 group-days). This
  grades the gate (393 group-days, starting a week earlier).

Both are legitimate; they answer different questions. Neither replaces the other.

Outputs (all under ``data/picks/eval/``, all DERIVED — rebuilt every run, never
append-only):

  emerging_spread.csv    one row per (date, horizon): the portfolio spread,
                         its components, the negative control, and that date's
                         market efficiency ratio.
  emerging_gradient.csv  one row per (date, horizon, quintile): the
                         dose-response sort over ``regime_short_long``.

Reads only committed CSVs; no network. Safe to run from a Claude Code cloud
session (no Finviz dependency).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from picks_config import EMERGING_REGIME_FLOOR, EMERGING_RS_FLOOR  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DELTAS_CSV = ROOT / "data" / "industries" / "deltas.csv"
SNAPSHOTS_CSV = ROOT / "data" / "industries" / "snapshots.csv"
BENCHMARK_CSV = ROOT / "data" / "benchmark" / "snapshots.csv"
SPREAD_CSV = ROOT / "data" / "picks" / "eval" / "emerging_spread.csv"
GRADIENT_CSV = ROOT / "data" / "picks" / "eval" / "emerging_gradient.csv"
STREAK_CSV = ROOT / "data" / "picks" / "eval" / "emerging_streak.csv"

# Forward horizons in TRADING SESSIONS, positional in the sorted date list so
# weekend/holiday gaps are skipped for free (same convention as
# find_trading_date_back in compute_deltas.py and HORIZONS in
# evaluate_picks.py). Keep these two lists aligned unless you have a reason not
# to — a horizon here that evaluate_picks.py lacks makes the two scoreboards
# incomparable at that horizon.
HORIZONS = [1, 3, 5, 10]

# EFFICIENCY_WINDOW — trailing sessions used for the market-regime measure
# (EMRG-1a). The efficiency ratio is abs(net move) / sum(abs(daily moves)) over
# this many SPY sessions: ~0 = thrashing sideways (chop), ~1 = clean directional
# move (trend).
#
# 10 is a deliberate compromise. It costs 9 warm-up days out of a 55-session
# benchmark history; a 20-day window (matching a 20SMA, the owner's original
# instinct) would cost 19 and leave too little to regress against. Raise it once
# #419 lands more SPY history and the warm-up stops being the binding constraint.
# Validated at 10 against the owner's hand-labelled thrust segment
# (2026-07-28..08-14): that segment scores 0.51 vs 0.14-0.22 elsewhere, and the
# 6 most-trending windows in the sample all fall inside it.
EFFICIENCY_WINDOW = 10

# GRADIENT_BINS — number of cross-sectional buckets for the dose-response sort
# (EMRG-4). 5 over ~144 groups gives ~29 groups/bin, enough that a bin mean is
# not one or two names. Going to 10 halves that and gets noisy fast at this
# sample size.
GRADIENT_BINS = 5

# CONTROL_SEED — fixed so the negative control (EMRG-7) is reproducible. The
# control draws the SAME NUMBER of groups the gate fired on that date, from the
# same daily universe, uniformly at random. Matching the count matters: an
# unmatched control would differ in diversification as well as in selection,
# and we would not know which caused the gap.
CONTROL_SEED = 20260908

SPREAD_COLUMNS = [
    "date", "horizon", "n_fire", "n_universe",
    "fwd_fire_mean", "fwd_nonfire_mean", "spread",
    "fwd_control_mean", "control_spread",
    "efficiency_ratio",
]
GRADIENT_COLUMNS = ["date", "horizon", "quintile", "n", "fwd_mean", "fwd_excess"]
STREAK_COLUMNS = ["date", "horizon", "cohort", "n", "fwd_mean", "fwd_excess"]

# FRESH_STREAK_MAX — a firing group-day counts as a "fresh" trigger when the
# gate has fired for at most this many consecutive sessions including today.
# 1 means strictly the first day of a new fire. This split exists because the
# owner acts on NEW signals: if the edge lives only in the stale cohort, the
# gate is confirming a move that already happened rather than anticipating one,
# which is a different (and much less useful) instrument.
FRESH_STREAK_MAX = 1


def compound(values: np.ndarray) -> float:
    """Compound a run of daily raw-% returns into a single raw-% figure.

    Returns NaN if ANY day in the window is missing. Requiring a complete
    window (rather than skipping NaN days) keeps every group measured over the
    identical session set — skipping would silently compare unequal windows and
    flatter whichever group had the most gaps. Same rule as
    evaluate_picks._compound; kept deliberately identical so the two
    scoreboards stay comparable.
    """
    if len(values) == 0 or np.isnan(values).any():
        return float("nan")
    return float((np.prod(1.0 + values / 100.0) - 1.0) * 100.0)


def compound_log(values: np.ndarray) -> float:
    """Compound a run of daily raw-% returns into a LOG return.

    Why log and not simple compounding: every comparison in this study is a
    difference of means across groups. Simple compounded returns do not
    decompose additively, so `mean(selected) - mean(rest)` leaves a
    market x spread cross term that does not cancel — it inflates the gap
    whenever the market rose over the window. That bias points the same way as
    the effect we are testing, and it is largest in exactly the trending
    stretch the regime analysis cares about. Log returns are additive, so the
    difference is clean; convert back with `log_to_pct` only for display.
    """
    if len(values) == 0 or np.isnan(values).any():
        return float("nan")
    return float(np.log1p(values / 100.0).sum())


def log_to_pct(x: float) -> float:
    """Convert a log return back to a raw % figure, for display only."""
    return float("nan") if pd.isna(x) else float((np.expm1(x)) * 100.0)


def perf_matrix(snapshots: pd.DataFrame) -> pd.DataFrame:
    """date x name matrix of perf_day (raw %), sorted by date."""
    snap = snapshots[["date", "name", "perf_day"]].copy()
    snap["perf_day"] = pd.to_numeric(snap["perf_day"], errors="coerce")
    snap = snap.drop_duplicates(subset=["date", "name"], keep="last")
    return snap.pivot(index="date", columns="name", values="perf_day").sort_index()


def forward_returns(perf: pd.DataFrame, dates: list, start: int, horizon: int) -> pd.Series:
    """Per-group compounded return over `horizon` sessions starting at index `start`.

    Values are LOG returns (see compound_log) so that downstream differences of
    means are unbiased.

    `start` is the index of the FIRST forward session — callers pass
    position_of(t) + 1, so the window never includes the signal date itself.
    That exclusion matters: the signal date's own return is already inside the
    gate's `perf_week` input, so including it would be direct leakage.
    Returns an empty Series when the window would run past the data.
    """
    window = dates[start:start + horizon]
    if len(window) < horizon:
        return pd.Series(dtype=float)
    sub = perf.loc[window]
    return sub.apply(lambda col: compound_log(col.to_numpy()), axis=0)


def gate_fires(deltas_today: pd.DataFrame,
               regime_floor: float = EMERGING_REGIME_FLOOR,
               rs_floor: float = EMERGING_RS_FLOOR) -> set:
    """Group names whose emerging gate fires on this date.

    Mirrors the Priority-2 filter in collect_picks.select_groups, minus the
    slot cap and priority ordering — deliberately, since the point is to see
    the whole firing population, not the 4 that survive selection. Floors are
    imported from picks_config so there is one source of truth; if the deployed
    gate changes, this study follows it automatically.
    """
    if len(deltas_today) == 0:
        return set()
    d = deltas_today.dropna(subset=["regime_short_long", "rs_score"])
    fired = d[(d["regime_short_long"] > regime_floor) & (d["rs_score"] > rs_floor)]
    return set(fired["name"])


def efficiency_ratio(daily_pct: np.ndarray) -> float:
    """abs(net compounded move) / sum(abs(daily moves)) over the given window.

    0 = pure chop (lots of motion, no progress); 1 = every session in the same
    direction. NaN if the window has any missing day, or if nothing moved at
    all (a zero denominator is undefined, not zero — a flat tape is not
    maximally choppy, it is uninformative).
    """
    if len(daily_pct) == 0 or np.isnan(daily_pct).any():
        return float("nan")
    path = float(np.abs(daily_pct).sum())
    if path == 0:
        return float("nan")
    return abs(compound(daily_pct)) / path


def efficiency_series(benchmark: pd.DataFrame,
                      window: int = EFFICIENCY_WINDOW) -> pd.Series:
    """Trailing efficiency ratio per benchmark date, indexed by date.

    The value at date t uses the `window` sessions ENDING at t (inclusive), so
    it is knowable on t and carries no lookahead into the forward window.
    """
    if len(benchmark) == 0:
        return pd.Series(dtype=float)
    b = benchmark[["date", "perf_day"]].copy()
    b["perf_day"] = pd.to_numeric(b["perf_day"], errors="coerce")
    b = b.drop_duplicates("date", keep="last").sort_values("date")
    vals, out = b["perf_day"].to_numpy(), {}
    for i, d in enumerate(b["date"]):
        if i + 1 < window:
            continue
        out[d] = efficiency_ratio(vals[i + 1 - window:i + 1])
    return pd.Series(out, dtype=float)


def compute_spread(deltas: pd.DataFrame, snapshots: pd.DataFrame,
                   benchmark: pd.DataFrame, horizons: list[int] = HORIZONS,
                   seed: int = CONTROL_SEED) -> pd.DataFrame:
    """One row per (date, horizon): the portfolio spread and its control.

    spread = mean forward log-return of gate-firing groups
           - mean forward log-return of the FULL cross-section that day.

    Subtracting the full cross-section rather than the non-firing complement is
    deliberate, and it is not cosmetic. Writing k for the number of firing
    groups and N for the universe:

        mean(fire) - mean(nonfire) = N/(N-k) * (mean(fire) - mean(all))

    so the complement version carries a 1/(1-k/N) gain that moves with k. Here
    k ranges 3..16 over N~144, i.e. a 1.02x..1.12x multiplier — and k is itself
    regime-correlated (more groups fire in a trending tape), so that multiplier
    would quietly amplify exactly the days the regime analysis is about.
    Subtracting the full cross-section has no such k-dependence.
    `fwd_nonfire_mean` is still recorded for reference and for anyone wanting
    to reproduce the old figure.

    The same-day subtraction is what cancels the market factor: if everything
    rose 3% that day, both terms rise with it. Only dates where the FULL
    horizon of forward sessions exists are emitted — a partial window would be
    a different measurement wearing the same column name.
    """
    if len(deltas) == 0 or len(snapshots) == 0:
        return pd.DataFrame(columns=SPREAD_COLUMNS)

    perf = perf_matrix(snapshots)
    dates = list(perf.index)
    pos = {d: i for i, d in enumerate(dates)}
    eff = efficiency_series(benchmark)
    rng = np.random.default_rng(seed)

    rows = []
    for date, day in deltas.groupby("date", sort=True):
        if date not in pos:
            continue
        fire = gate_fires(day)
        if not fire:
            continue
        start = pos[date] + 1
        for horizon in horizons:
            fwd = forward_returns(perf, dates, start, horizon).dropna()
            if len(fwd) == 0:
                continue
            in_fire = fwd[fwd.index.isin(fire)]
            out_fire = fwd[~fwd.index.isin(fire)]
            if len(in_fire) == 0 or len(out_fire) == 0:
                continue
            # Negative control: same count, same universe, drawn at random.
            n = len(in_fire)
            picks = rng.choice(fwd.index.to_numpy(), size=n, replace=False)
            ctrl = fwd[fwd.index.isin(picks)]
            all_mean = float(fwd.mean())
            rows.append({
                "date": date,
                "horizon": horizon,
                "n_fire": n,
                "n_universe": len(fwd),
                "fwd_fire_mean": log_to_pct(in_fire.mean()),
                "fwd_nonfire_mean": log_to_pct(out_fire.mean()),
                "spread": log_to_pct(in_fire.mean()) - log_to_pct(all_mean),
                "fwd_control_mean": log_to_pct(ctrl.mean()),
                "control_spread": log_to_pct(ctrl.mean()) - log_to_pct(all_mean),
                "efficiency_ratio": eff.get(date, float("nan")),
            })
    return pd.DataFrame(rows, columns=SPREAD_COLUMNS)


def compute_gradient(deltas: pd.DataFrame, snapshots: pd.DataFrame,
                     horizons: list[int] = HORIZONS,
                     bins: int = GRADIENT_BINS) -> pd.DataFrame:
    """Dose-response sort: forward return by regime_short_long quintile (EMRG-4).

    Every group is ranked each day and cut into `bins` equal-count buckets
    (quintile 1 = lowest regime_short_long, `bins` = highest). `fwd_excess` is
    the bin's mean forward return minus that day's cross-sectional mean, so the
    market move is removed the same way the spread removes it.

    This never touches the emerging bucket or any threshold — it measures the
    underlying variable across the whole universe, which is what makes it able
    to say whether 0.15 is a meaningful cut or an arbitrary one.
    """
    if len(deltas) == 0 or len(snapshots) == 0:
        return pd.DataFrame(columns=GRADIENT_COLUMNS)

    perf = perf_matrix(snapshots)
    dates = list(perf.index)
    pos = {d: i for i, d in enumerate(dates)}

    rows = []
    for date, day in deltas.groupby("date", sort=True):
        if date not in pos:
            continue
        d = day.dropna(subset=["regime_short_long"])
        # qcut needs more rows than bins to produce distinct edges; a thin day
        # (early history, heavy NaN) is skipped rather than silently binned wrong.
        if len(d) <= bins:
            continue
        try:
            q = pd.qcut(d["regime_short_long"].rank(method="first"), bins,
                        labels=range(1, bins + 1))
        except ValueError:
            continue
        bin_by_name = dict(zip(d["name"], q))
        start = pos[date] + 1
        for horizon in horizons:
            fwd = forward_returns(perf, dates, start, horizon).dropna()
            if len(fwd) == 0:
                continue
            day_mean = float(fwd.mean())
            for b in range(1, bins + 1):
                names = [n for n, bb in bin_by_name.items() if bb == b]
                vals = fwd[fwd.index.isin(names)]
                if len(vals) == 0:
                    continue
                rows.append({
                    "date": date, "horizon": horizon, "quintile": b,
                    "n": len(vals), "fwd_mean": log_to_pct(float(vals.mean())),
                    "fwd_excess": log_to_pct(float(vals.mean())) - log_to_pct(day_mean),
                })
    return pd.DataFrame(rows, columns=GRADIENT_COLUMNS)


def firing_streaks(deltas: pd.DataFrame) -> dict:
    """{date: {group: consecutive sessions the gate has fired, inclusive}}.

    Streak 1 = the gate fired today and did not fire on the previous session in
    the data. Gaps in the date list break a streak, which is the conservative
    reading: we cannot know a group kept firing on a day we did not collect.
    """
    out, prev_date, prev = {}, None, {}
    for date, day in deltas.groupby("date", sort=True):
        fire = gate_fires(day)
        cur = {g: (prev.get(g, 0) + 1 if prev_date is not None else 1) for g in fire}
        out[date], prev, prev_date = cur, cur, date
    return out


def compute_streaks(deltas: pd.DataFrame, snapshots: pd.DataFrame,
                    horizons: list[int] = HORIZONS,
                    fresh_max: int = FRESH_STREAK_MAX) -> pd.DataFrame:
    """Forward excess return split by fresh trigger vs stale streak (EMRG-9).

    `fwd_excess` is measured against the same day's full cross-sectional mean,
    identical to compute_spread, so the two are directly comparable.
    """
    if len(deltas) == 0 or len(snapshots) == 0:
        return pd.DataFrame(columns=STREAK_COLUMNS)
    perf = perf_matrix(snapshots)
    dates = list(perf.index)
    pos = {d: i for i, d in enumerate(dates)}
    streaks = firing_streaks(deltas)

    rows = []
    for date, by_group in streaks.items():
        if date not in pos or not by_group:
            continue
        start = pos[date] + 1
        for horizon in horizons:
            fwd = forward_returns(perf, dates, start, horizon).dropna()
            if len(fwd) == 0:
                continue
            day_mean = float(fwd.mean())
            for cohort, members in (
                ("fresh", [g for g, s in by_group.items() if s <= fresh_max]),
                ("stale", [g for g, s in by_group.items() if s > fresh_max]),
            ):
                vals = fwd[fwd.index.isin(members)]
                if len(vals) == 0:
                    continue
                rows.append({
                    "date": date, "horizon": horizon, "cohort": cohort,
                    "n": len(vals), "fwd_mean": log_to_pct(float(vals.mean())),
                    "fwd_excess": log_to_pct(float(vals.mean())) - log_to_pct(day_mean),
                })
    return pd.DataFrame(rows, columns=STREAK_COLUMNS)


def _fmt(x: float) -> str:
    return "   NaN" if pd.isna(x) else f"{x:+6.2f}"


def print_report(spread: pd.DataFrame, gradient: pd.DataFrame,
                 streak: pd.DataFrame | None = None) -> None:
    """Roll-up. Every number here is one-date-one-vote by construction."""
    if len(spread) == 0:
        print("No spread rows — nothing to report.")
        return

    print(f"Emerging signal study — {spread['date'].nunique()} dates, "
          f"gate = regime_short_long > {EMERGING_REGIME_FLOOR} "
          f"and rs_score > {EMERGING_RS_FLOOR}")

    print("\n== Portfolio spread (firing − full cross-section, one number per date) ==")
    print("   h dates | spread mean/med   pos% | control mean  pos%")
    for h, g in spread.groupby("horizon"):
        s, c = g["spread"].dropna(), g["control_spread"].dropna()
        print(f"  {h:>2} {len(g):>5} | {_fmt(s.mean())}/{_fmt(s.median())} "
              f"{100 * (s > 0).mean():5.0f}% | {_fmt(c.mean())} "
              f"{100 * (c > 0).mean():5.0f}%")
    print("  NOTE: the control column is the read-the-instrument check. If it "
          "also looks\n  positive, the harness manufactures an edge and the "
          "spread column means nothing.")

    print("\n== Spread vs market efficiency ratio (chop → trend) ==")
    for h, g in spread.groupby("horizon"):
        v = g.dropna(subset=["spread", "efficiency_ratio"])
        if len(v) < 3:
            continue
        r = v["spread"].corr(v["efficiency_ratio"])
        lo = v[v["efficiency_ratio"] <= v["efficiency_ratio"].median()]["spread"]
        hi = v[v["efficiency_ratio"] > v["efficiency_ratio"].median()]["spread"]
        print(f"  h={h:>2}  n={len(v):>3}  corr {r:+.2f} | "
              f"choppier half {_fmt(lo.mean())}  trendier half {_fmt(hi.mean())}")

    if streak is not None and len(streak):
        print("\n== Fresh trigger vs stale streak (excess vs same-day cross-section) ==")
        print("  The tradeable split: does the gate ANTICIPATE a move or CONFIRM one?")
        print("   h |  fresh exc   n |  stale exc   n")
        for h, g in streak.groupby("horizon"):
            f = g[g["cohort"] == "fresh"]
            s = g[g["cohort"] == "stale"]
            print(f"  {h:>2} | {_fmt(f['fwd_excess'].mean())} {int(f['n'].sum()):>5} |"
                  f" {_fmt(s['fwd_excess'].mean())} {int(s['n'].sum()):>5}")

    if len(gradient):
        print("\n== Gradient: forward excess return by regime_short_long quintile ==")
        print("  (1 = lowest regime, 5 = highest; monotone rise = real signal, "
              "not a threshold artifact)")
        piv = gradient.pivot_table(index="horizon", columns="quintile",
                                   values="fwd_excess", aggfunc="mean")
        print("   h |" + "".join(f"     q{c}" for c in piv.columns))
        for h, row in piv.iterrows():
            print(f"  {h:>2} |" + "".join(_fmt(row[c]) for c in piv.columns))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--report", action="store_true",
                    help="print the roll-up from existing CSVs (no rebuild)")
    args = ap.parse_args()

    if args.report:
        if not SPREAD_CSV.exists():
            print(f"{SPREAD_CSV} not found — run without --report first.")
            return
        grad = pd.read_csv(GRADIENT_CSV, dtype={"date": str}) if GRADIENT_CSV.exists() \
            else pd.DataFrame(columns=GRADIENT_COLUMNS)
        stk = pd.read_csv(STREAK_CSV, dtype={"date": str}) if STREAK_CSV.exists() \
            else pd.DataFrame(columns=STREAK_COLUMNS)
        print_report(pd.read_csv(SPREAD_CSV, dtype={"date": str}), grad, stk)
        return

    deltas = pd.read_csv(DELTAS_CSV, dtype={"date": str}, low_memory=False)
    snapshots = pd.read_csv(SNAPSHOTS_CSV, dtype={"date": str}, low_memory=False)
    benchmark = pd.read_csv(BENCHMARK_CSV, dtype={"date": str}) if BENCHMARK_CSV.exists() \
        else pd.DataFrame(columns=["date", "perf_day"])

    spread = compute_spread(deltas, snapshots, benchmark)
    gradient = compute_gradient(deltas, snapshots)
    streak = compute_streaks(deltas, snapshots)
    SPREAD_CSV.parent.mkdir(parents=True, exist_ok=True)
    spread.round(4).to_csv(SPREAD_CSV, index=False)
    gradient.round(4).to_csv(GRADIENT_CSV, index=False)
    streak.round(4).to_csv(STREAK_CSV, index=False)
    print(f"Wrote {len(spread)} spread / {len(gradient)} gradient / "
          f"{len(streak)} streak rows -> {SPREAD_CSV.parent}\n")
    print_report(spread, gradient, streak)


if __name__ == "__main__":
    main()
