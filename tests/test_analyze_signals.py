"""Tests for scripts/analyze_signals.py (SPRINT § EMRG-2/4/7/9).

Expected values are hand-computed from the fixtures below, never by calling the
module's own helpers — otherwise a sign or scaling bug would satisfy its own test.
"""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import analyze_signals as ae  # noqa: E402


# ---------------------------------------------------------------- compounding

def test_compound_matches_hand_arithmetic():
    # 1.01 * 1.02 = 1.0302 -> +3.02%
    assert ae.compound(np.array([1.0, 2.0])) == pytest.approx(3.02)


def test_compound_log_is_additive():
    a = ae.compound_log(np.array([1.0, 2.0]))
    assert a == pytest.approx(math.log(1.01) + math.log(1.02))


def test_log_round_trip_recovers_simple_return():
    vals = np.array([1.0, 2.0, -0.5])
    assert ae.log_to_pct(ae.compound_log(vals)) == pytest.approx(ae.compound(vals))


@pytest.mark.parametrize("vals", [np.array([]), np.array([1.0, np.nan])])
def test_compounders_reject_incomplete_windows(vals):
    assert math.isnan(ae.compound(vals))
    assert math.isnan(ae.compound_log(vals))


# ------------------------------------------------------------ efficiency ratio

def test_efficiency_ratio_one_when_perfectly_directional():
    # All same sign: |net| equals the path length, up to compounding.
    assert ae.efficiency_ratio(np.array([1.0, 1.0, 1.0])) == pytest.approx(
        abs(ae.compound(np.array([1.0, 1.0, 1.0]))) / 3.0)


def test_efficiency_ratio_near_zero_when_thrashing():
    # +1, -1, +1, -1 travels 4 units of path and ends ~flat.
    assert ae.efficiency_ratio(np.array([1.0, -1.0, 1.0, -1.0])) < 0.02


def test_efficiency_ratio_nan_on_flat_tape():
    # Zero path length is undefined, not "maximally choppy".
    assert math.isnan(ae.efficiency_ratio(np.array([0.0, 0.0])))


def test_efficiency_series_respects_warmup_and_has_no_lookahead():
    bench = pd.DataFrame({"date": [f"2026-01-{i:02d}" for i in range(1, 6)],
                          "perf_day": [1.0, -1.0, 1.0, -1.0, 1.0]})
    s = ae.efficiency_series(bench, window=3)
    # First two dates cannot have a 3-session trailing window.
    assert list(s.index) == ["2026-01-03", "2026-01-04", "2026-01-05"]
    # The value on day 3 uses days 1-3 only.
    assert s["2026-01-03"] == pytest.approx(
        ae.efficiency_ratio(np.array([1.0, -1.0, 1.0])))


# ------------------------------------------------------------------- the gate

def _deltas(rows):
    return pd.DataFrame(rows, columns=["date", "name", "regime_short_long", "rs_score"])


def test_gate_requires_both_floors_and_is_strict():
    d = _deltas([
        ("2026-01-02", "yes",        0.20, 0.60),
        ("2026-01-02", "regime_low", 0.10, 0.60),
        ("2026-01-02", "rs_low",     0.20, 0.40),
        ("2026-01-02", "on_edge",    0.15, 0.60),   # strict >, so excluded
        ("2026-01-02", "nan_row",    np.nan, 0.60),
    ])
    assert ae.gate_fires(d) == {"yes"}


def test_gate_empty_frame_is_empty_set():
    assert ae.gate_fires(_deltas([])) == set()


# ----------------------------------------------------------------- streaks

def test_firing_streaks_counts_consecutive_sessions_and_breaks_on_gap():
    d = _deltas([
        ("2026-01-02", "a", 0.5, 0.9),
        ("2026-01-03", "a", 0.5, 0.9),
        ("2026-01-03", "b", 0.5, 0.9),
        ("2026-01-04", "b", 0.5, 0.9),          # 'a' does not fire -> streak resets
        ("2026-01-05", "a", 0.5, 0.9),
    ])
    s = ae.firing_streaks(d)
    assert s["2026-01-02"] == {"a": 1}
    assert s["2026-01-03"] == {"a": 2, "b": 1}
    assert s["2026-01-04"] == {"b": 2}
    assert s["2026-01-05"] == {"a": 1}


def test_streak_bucket_edges_are_inclusive_and_open_ended():
    assert ae.streak_bucket(1) == "1"
    assert ae.streak_bucket(2) == "2-3" and ae.streak_bucket(3) == "2-3"
    assert ae.streak_bucket(5) == "4-5"
    assert ae.streak_bucket(6) == "6+" and ae.streak_bucket(99) == "6+"


def test_streak_bucket_returns_empty_for_unbucketed():
    assert ae.streak_bucket(0) == ""


def test_compute_streaks_labels_a_first_fire_as_bucket_one():
    deltas, snap = _fixture()
    out = ae.compute_streaks(deltas, snap, horizons=[1])
    assert list(out["cohort"]) == ["1"]
    # 'hot' is the only firing group and returns +2% on the single forward day.
    assert out.iloc[0]["fwd_mean"] == pytest.approx(2.0)


def test_compute_streaks_excess_matches_the_spread_convention():
    """Both must subtract the same-day full cross-section, or they cannot be compared."""
    deltas, snap = _fixture()
    stk = ae.compute_streaks(deltas, snap, horizons=[1])
    spr = ae.compute_spread(deltas, snap, pd.DataFrame(columns=["date", "perf_day"]),
                            horizons=[1])
    assert stk.iloc[0]["fwd_excess"] == pytest.approx(spr.iloc[0]["spread"])


# --------------------------------------------------------------- the spread

def _fixture():
    """3 groups x 4 sessions. Only 'hot' fires, and only on day 1.

    perf_day day2 = hot +2, mid 0, cold -2  -> cross-sectional mean 0.
    """
    dates = ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"]
    snap = pd.DataFrame([
        {"date": d, "name": n, "perf_day": p}
        for d, row in zip(dates, [(1.0, 1.0, 1.0), (2.0, 0.0, -2.0),
                                  (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)])
        for n, p in zip(["hot", "mid", "cold"], row)
    ])
    deltas = pd.DataFrame([
        {"date": "2026-01-02", "name": "hot",  "regime_short_long": 0.9, "rs_score": 0.9},
        {"date": "2026-01-02", "name": "mid",  "regime_short_long": 0.0, "rs_score": 0.9},
        {"date": "2026-01-02", "name": "cold", "regime_short_long": -0.9, "rs_score": 0.1},
    ])
    return deltas, snap


def test_spread_excludes_the_signal_day_itself():
    deltas, snap = _fixture()
    out = ae.compute_spread(deltas, snap, pd.DataFrame(columns=["date", "perf_day"]),
                            horizons=[1])
    row = out.iloc[0]
    # Forward window is day 2 only. hot = +2%; day-1's +1% must not appear.
    assert row["fwd_fire_mean"] == pytest.approx(2.0)


def test_spread_is_measured_against_the_full_cross_section():
    """The k-dependence fix: complement-subtraction would give a different number."""
    deltas, snap = _fixture()
    out = ae.compute_spread(deltas, snap, pd.DataFrame(columns=["date", "perf_day"]),
                            horizons=[1])
    row = out.iloc[0]
    xs_mean = ae.log_to_pct(np.mean([ae.compound_log(np.array([v]))
                                     for v in (2.0, 0.0, -2.0)]))
    assert row["spread"] == pytest.approx(2.0 - xs_mean)
    # The complement figure is retained but is NOT what `spread` reports.
    assert row["fwd_nonfire_mean"] == pytest.approx(
        ae.log_to_pct(np.mean([ae.compound_log(np.array([0.0])),
                               ae.compound_log(np.array([-2.0]))])))
    assert row["spread"] != pytest.approx(2.0 - row["fwd_nonfire_mean"])


def test_spread_drops_dates_without_a_full_forward_window():
    deltas, snap = _fixture()
    # Only 3 forward sessions exist after the signal date, so h=10 is unscoreable.
    assert len(ae.compute_spread(deltas, snap,
                                 pd.DataFrame(columns=["date", "perf_day"]),
                                 horizons=[10])) == 0


def test_control_matches_the_firing_count():
    deltas, snap = _fixture()
    out = ae.compute_spread(deltas, snap, pd.DataFrame(columns=["date", "perf_day"]),
                            horizons=[1])
    assert out.iloc[0]["n_fire"] == 1
    assert out.iloc[0]["n_universe"] == 3


# ------------------------------------------------------- empty-input handling

@pytest.mark.parametrize("fn,cols", [
    (ae.compute_gradient, ae.GRADIENT_COLUMNS),
    (ae.compute_streaks, ae.STREAK_COLUMNS),
])
def test_derived_frames_handle_empty_inputs(fn, cols):
    out = fn(pd.DataFrame(columns=["date", "name"]), pd.DataFrame(columns=["date", "name"]))
    assert len(out) == 0 and list(out.columns) == cols


def test_compute_spread_handles_empty_inputs():
    out = ae.compute_spread(pd.DataFrame(columns=["date", "name"]),
                            pd.DataFrame(columns=["date", "name"]),
                            pd.DataFrame(columns=["date", "perf_day"]))
    assert len(out) == 0 and list(out.columns) == ae.SPREAD_COLUMNS


def test_gradient_skips_days_thinner_than_the_bin_count():
    deltas, snap = _fixture()   # only 3 groups, GRADIENT_BINS = 5
    assert len(ae.compute_gradient(deltas, snap, horizons=[1])) == 0
