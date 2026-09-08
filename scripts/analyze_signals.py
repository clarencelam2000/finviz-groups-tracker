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
from picks_config import (  # noqa: E402
    ACCEL_RS_FLOOR,
    ACCEL_THRESHOLD,
    ANTIFLASH_PCTILE,
    EMERGING_REGIME_FLOOR,
    EMERGING_RS_FLOOR,
    LEADER_SS_SLOTS,
    RS_NH_RS_FLOOR,
)

ROOT = Path(__file__).resolve().parent.parent
DELTAS_CSV = ROOT / "data" / "industries" / "deltas.csv"
SNAPSHOTS_CSV = ROOT / "data" / "industries" / "snapshots.csv"
BENCHMARK_CSV = ROOT / "data" / "benchmark" / "snapshots.csv"
SPREAD_CSV = ROOT / "data" / "picks" / "eval" / "emerging_spread.csv"
GRADIENT_CSV = ROOT / "data" / "picks" / "eval" / "emerging_gradient.csv"
STREAK_CSV = ROOT / "data" / "picks" / "eval" / "emerging_streak.csv"
COMPARE_CSV = ROOT / "data" / "picks" / "eval" / "rule_comparison.csv"

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
STREAK_COLUMNS = ["date", "horizon", "cohort", "n", "fwd_mean", "fwd_excess", "efficiency_ratio"]

# STREAK_BUCKETS — how firing group-days are grouped by consecutive-fire streak
# (inclusive of today). Bucket 1 is a brand-new fire; later buckets are
# continuations of an existing one. Edges are (label, lo, hi) with hi inclusive
# and None meaning open-ended.
#
# This is deliberately a DOSE-RESPONSE, not the binary fresh/stale split it
# replaced. The binary version answered "is the edge in new fires or old ones";
# the buckets answer the tradeable version of that question — HOW LONG after a
# first fire does the edge appear, i.e. when should an entry actually be placed.
# A monotone rise across buckets is also much harder to manufacture by chance
# than a two-way gap, so it doubles as a robustness check on the finding.
#
# Widening a bucket trades resolution for sample size; at ~390 firing group-days
# the current four already put only ~40-60 rows in the tail bucket, so do not
# split further without more history.
STREAK_BUCKETS = [("1", 1, 1), ("2-3", 2, 3), ("4-5", 4, 5), ("6+", 6, None)]


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


# ---------------------------------------------------------------------------
# SELECTION RULES — the thing being compared.
#
# Each rule takes one date's slice of deltas.csv and returns the set of group
# names it would pick that day. Every rule is scored identically downstream, so
# `--rules a,b,c` is a straight "which cut makes more money" leaderboard.
#
# Two families:
#   * DEPLOYED rules mirror scripts/collect_picks.py's selector, floors imported
#     from picks_config so they follow the live config rather than drifting.
#     Slot caps and cross-bucket priority are deliberately NOT applied — we are
#     scoring the rule, not the 27-name daily budget.
#   * SIMPLE rules are single-variable top-N cuts. They exist as the honest
#     baseline: a multi-condition screen has to beat "just rank on one column
#     and take the top N" to justify itself. On 2026-09-08 the emerging gate
#     did not (see knowledge/alpha-study-working-agreement.md).
#
# Adding a rule is one function plus one RULES entry. That is the intended way
# to answer "is Accel earning its place" or "should Leaders be top 11 or top 20"
# without writing a new study.
# ---------------------------------------------------------------------------

def _pctile(day: pd.DataFrame, col: str = "momentum_score") -> pd.Series:
    """Cross-sectional percentile (0-1) of `col` within this date."""
    return day[col].rank(pct=True, ascending=True)


def _top_n(day: pd.DataFrame, col: str, n: int, ascending: bool = False) -> set:
    d = day.dropna(subset=[col])
    if len(d) == 0:
        return set()
    d = d.sort_values(col, ascending=ascending)
    return set(d["name"].head(n))


def rule_emerging(day):
    """DEPLOYED emerging gate: regime floor AND rs_score floor."""
    return gate_fires(day)


def rule_emerging_regime_only(day):
    """The emerging gate with the rs_score floor removed — the ablation."""
    d = day.dropna(subset=["regime_short_long"])
    return set(d[d["regime_short_long"] > EMERGING_REGIME_FLOOR]["name"])


def rule_leaders(day):
    """DEPLOYED leaders core: best LEADER_SS_SLOTS by summed mid-horizon rank."""
    d = day.dropna(subset=["rank_month", "rank_quarter", "rank_half"]).copy()
    if len(d) == 0:
        return set()
    d["_sum_mid"] = d["rank_month"] + d["rank_quarter"] + d["rank_half"]
    return _top_n(d, "_sum_mid", LEADER_SS_SLOTS, ascending=True)


def rule_accel(day):
    """DEPLOYED accel gate: momentum_accel + anti-flash percentile + rs floor."""
    d = day.dropna(subset=["momentum_accel", "momentum_score", "rs_score"]).copy()
    if len(d) == 0:
        return set()
    d["_p"] = _pctile(d)
    return set(d[(d["momentum_accel"] > ACCEL_THRESHOLD)
                 & (d["_p"] >= ANTIFLASH_PCTILE)
                 & (d["rs_score"] > ACCEL_RS_FLOOR)]["name"])


def rule_rs_new_high(day):
    """DEPLOYED rs_new_high gate."""
    d = day.dropna(subset=["rs_new_high", "rs_score", "momentum_score"]).copy()
    if len(d) == 0:
        return set()
    d["_p"] = _pctile(d)
    return set(d[(d["rs_new_high"] == 1)
                 & (d["rs_score"] >= RS_NH_RS_FLOOR)
                 & (d["_p"] >= ANTIFLASH_PCTILE)]["name"])


def _mk_top(col, n):
    return lambda day, _c=col, _n=n: _top_n(day, _c, _n)


RULES = {
    # deployed selector buckets
    "emerging": rule_emerging,
    "leaders": rule_leaders,
    "accel": rule_accel,
    "rs_new_high": rule_rs_new_high,
    # ablation of the emerging gate
    "emerging_regime_only": rule_emerging_regime_only,
    # single-variable baselines (the bar a multi-condition screen must clear)
    **{f"top{n}_regime": _mk_top("regime_short_long", n) for n in (5, 10, 14, 20, 28)},
    **{f"top{n}_momentum": _mk_top("momentum_score", n) for n in (10, 14, 28)},
    **{f"top{n}_mom_confirmed": _mk_top("momentum_confirmed", n) for n in (10, 14, 28)},
    **{f"top{n}_rs_confirmed": _mk_top("rs_confirmed", n) for n in (10, 14, 28)},
}


def compare_rules(deltas: pd.DataFrame, snapshots: pd.DataFrame,
                  rule_names: list[str] | None = None,
                  horizons: list[int] = HORIZONS) -> pd.DataFrame:
    """Score every named rule on the same dates and horizons.

    Returns one row per (rule, horizon): average selection size, mean excess
    return vs the day's full cross-section, and the share of days the selection
    beat that cross-section. Every rule sees identical dates and identical
    forward windows, so the numbers are directly comparable.
    """
    names = rule_names or list(RULES)
    cols = ["rule", "horizon", "n_dates", "avg_picks", "excess_mean", "hit_rate"]
    if len(deltas) == 0 or len(snapshots) == 0:
        return pd.DataFrame(columns=cols)
    perf = perf_matrix(snapshots)
    dates = list(perf.index)
    pos = {d: i for i, d in enumerate(dates)}

    acc: dict = {(r, h): [] for r in names for h in horizons}
    for date, day in deltas.groupby("date", sort=True):
        if date not in pos:
            continue
        picks = {r: RULES[r](day) for r in names}
        start = pos[date] + 1
        for h in horizons:
            fwd = forward_returns(perf, dates, start, h).dropna()
            if len(fwd) == 0:
                continue
            day_mean = log_to_pct(float(fwd.mean()))
            for r in names:
                v = fwd[fwd.index.isin(picks[r])]
                if len(v) == 0:
                    continue
                acc[(r, h)].append((len(v), log_to_pct(float(v.mean())) - day_mean))

    rows = []
    for (r, h), vals in acc.items():
        if not vals:
            continue
        exc = [e for _, e in vals]
        rows.append({
            "rule": r, "horizon": h, "n_dates": len(vals),
            "avg_picks": float(np.mean([n for n, _ in vals])),
            "excess_mean": float(np.mean(exc)),
            "hit_rate": float(np.mean([e > 0 for e in exc])),
        })
    return pd.DataFrame(rows, columns=cols).sort_values(
        ["horizon", "excess_mean"], ascending=[True, False])


def print_rule_comparison(cmp_df: pd.DataFrame, horizons: list[int] | None = None) -> None:
    """Leaderboard: which cut made the most money, per horizon."""
    if len(cmp_df) == 0:
        print("No rule-comparison rows.")
        return
    print("\n== Which cut makes more money? (excess vs the day's average group) ==")
    print("  Every rule scored on identical dates and identical forward windows.")
    for h in (horizons or sorted(cmp_df["horizon"].unique())):
        g = cmp_df[cmp_df["horizon"] == h]
        if len(g) == 0:
            continue
        print(f"\n  --- {h} sessions forward ---")
        print(f"  {'rule':<22} {'picks/day':>9} {'excess':>8} {'hit':>6}  {'dates':>5}")
        for _, r in g.iterrows():
            print(f"  {r['rule']:<22} {r['avg_picks']:>9.1f} {r['excess_mean']:>+8.2f}"
                  f" {100 * r['hit_rate']:>5.0f}% {int(r['n_dates']):>6}")


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


def streak_bucket(streak: int, buckets: list = None) -> str:
    """Label a consecutive-fire streak. Returns "" if it falls in no bucket."""
    for label, lo, hi in (buckets or STREAK_BUCKETS):
        if streak >= lo and (hi is None or streak <= hi):
            return label
    return ""


def compute_streaks(deltas: pd.DataFrame, snapshots: pd.DataFrame,
                    benchmark: pd.DataFrame | None = None,
                    horizons: list[int] = HORIZONS,
                    buckets: list = None) -> pd.DataFrame:
    """Forward excess return by consecutive-fire streak bucket (EMRG-9).

    `fwd_excess` is measured against the same day's full cross-sectional mean,
    identical to compute_spread, so the two numbers are directly comparable.
    The efficiency ratio is carried on every row so the whole table can be
    re-cut by market regime without recomputing anything.
    """
    if len(deltas) == 0 or len(snapshots) == 0:
        return pd.DataFrame(columns=STREAK_COLUMNS)
    buckets = buckets or STREAK_BUCKETS
    perf = perf_matrix(snapshots)
    dates = list(perf.index)
    pos = {d: i for i, d in enumerate(dates)}
    streaks = firing_streaks(deltas)
    eff = efficiency_series(benchmark) if benchmark is not None and len(benchmark) \
        else pd.Series(dtype=float)

    rows = []
    for date, by_group in streaks.items():
        if date not in pos or not by_group:
            continue
        start = pos[date] + 1
        by_bucket: dict[str, list] = {}
        for g, s in by_group.items():
            by_bucket.setdefault(streak_bucket(s, buckets), []).append(g)
        for horizon in horizons:
            fwd = forward_returns(perf, dates, start, horizon).dropna()
            if len(fwd) == 0:
                continue
            day_mean = float(fwd.mean())
            for label, _, _ in buckets:
                vals = fwd[fwd.index.isin(by_bucket.get(label, []))]
                if len(vals) == 0:
                    continue
                rows.append({
                    "date": date, "horizon": horizon, "cohort": label,
                    "n": len(vals), "fwd_mean": log_to_pct(float(vals.mean())),
                    "fwd_excess": log_to_pct(float(vals.mean())) - log_to_pct(day_mean),
                    "efficiency_ratio": eff.get(date, float("nan")),
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
        labels = [b[0] for b in STREAK_BUCKETS]
        print("\n== Entry timing: excess return by consecutive-fire streak ==")
        print("  Bucket 1 = the gate fired TODAY for the first time. Later buckets are")
        print("  continuations. A rise left-to-right means waiting beats entering on day 1.")
        print("   h |" + "".join(f"    d{l:<4}" for l in labels))
        for h, g in streak.groupby("horizon"):
            cells = []
            for l in labels:
                s = g[g["cohort"] == l]
                cells.append(f"{_fmt(s['fwd_excess'].mean())}" if len(s) else "   ---")
            print(f"  {h:>2} |" + "".join(f" {c}" for c in cells))
        print("   n |" + "".join(
            f" {int(streak[(streak.cohort == l) & (streak.horizon == streak.horizon.min())]['n'].sum()):>6}"
            for l in labels))

        v = streak.dropna(subset=["efficiency_ratio"])
        if len(v):
            cut = v["efficiency_ratio"].median()
            print("\n  Same table split by market regime (h=10 only, "
                  f"efficiency ratio median {cut:.2f}):")
            print("   regime  |" + "".join(f"    d{l:<4}" for l in labels))
            for name, sub in (("choppier", v[v.efficiency_ratio <= cut]),
                              ("trendier", v[v.efficiency_ratio > cut])):
                sub = sub[sub["horizon"] == 10]
                cells = []
                for l in labels:
                    s = sub[sub["cohort"] == l]
                    cells.append(_fmt(s["fwd_excess"].mean()) if len(s) else "   ---")
                print(f"   {name:<8} |" + "".join(f" {c}" for c in cells))

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
    ap.add_argument("--compare", nargs="?", const="ALL", metavar="RULES",
                    help="score selection rules head-to-head instead of running the "
                         "emerging study. Comma-separated names, or omit for all. "
                         f"Available: {', '.join(RULES)}")
    ap.add_argument("--horizons", default=None,
                    help="comma-separated forward horizons in sessions "
                         f"(default {','.join(map(str, HORIZONS))})")
    args = ap.parse_args()

    horizons = [int(x) for x in args.horizons.split(",")] if args.horizons else HORIZONS

    if args.compare:
        deltas = pd.read_csv(DELTAS_CSV, dtype={"date": str}, low_memory=False)
        snapshots = pd.read_csv(SNAPSHOTS_CSV, dtype={"date": str}, low_memory=False)
        names = None if args.compare == "ALL" else [
            n.strip() for n in args.compare.split(",")]
        if names:
            unknown = [n for n in names if n not in RULES]
            if unknown:
                raise SystemExit(f"unknown rule(s): {', '.join(unknown)}. "
                                 f"Available: {', '.join(RULES)}")
        cmp_df = compare_rules(deltas, snapshots, names, horizons)
        cmp_df.round(4).to_csv(COMPARE_CSV, index=False)
        print(f"Wrote {len(cmp_df)} rows -> {COMPARE_CSV}")
        print_rule_comparison(cmp_df, horizons)
        return

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
    streak = compute_streaks(deltas, snapshots, benchmark)
    SPREAD_CSV.parent.mkdir(parents=True, exist_ok=True)
    spread.round(4).to_csv(SPREAD_CSV, index=False)
    gradient.round(4).to_csv(GRADIENT_CSV, index=False)
    streak.round(4).to_csv(STREAK_CSV, index=False)
    print(f"Wrote {len(spread)} spread / {len(gradient)} gradient / "
          f"{len(streak)} streak rows -> {SPREAD_CSV.parent}\n")
    print_report(spread, gradient, streak)


if __name__ == "__main__":
    main()
