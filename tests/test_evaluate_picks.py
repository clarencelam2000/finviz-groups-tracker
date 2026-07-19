"""Tests for scripts/evaluate_picks.py (PICKS-4 group scoreboard)."""

import numpy as np
import pandas as pd
import pytest

from scripts.evaluate_picks import (
    HORIZONS,
    SCORE_COLUMNS,
    _compound,
    compute_scores,
    load_selected_groups,
    print_report,
    write_scores,
)


def snap(rows):
    return pd.DataFrame(rows, columns=["date", "name", "perf_day"])


def picks_frame(rows):
    return pd.DataFrame(rows, columns=["pick_date", "group", "buckets", "selector_version"])


BENCH_EMPTY = pd.DataFrame(columns=["date", "perf_day"])


class TestCompound:
    def test_two_day_compounding(self):
        # +10% then -5% -> 1.1*0.95 = 1.045 -> +4.5%
        assert _compound(np.array([10.0, -5.0])) == pytest.approx(4.5)

    def test_nan_in_window_yields_nan(self):
        assert np.isnan(_compound(np.array([1.0, np.nan])))

    def test_empty_yields_nan(self):
        assert np.isnan(_compound(np.array([])))


class TestComputeScores:
    def make_snapshots(self, dates, perfs_by_name):
        rows = []
        for name, perfs in perfs_by_name.items():
            rows += [(d, name, p) for d, p in zip(dates, perfs)]
        return snap(rows)

    def test_forward_math_and_controls(self):
        # 4 sessions after the pick date; A selected, B/C control
        dates = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09"]
        snapshots = self.make_snapshots(dates, {
            "A": [0, 1, 1, 1, 1],
            "B": [0, 2, 2, 2, 2],
            "C": [0, -1, -1, -1, -1],
        })
        bench = pd.DataFrame({"date": dates, "perf_day": [0, 0.5, 0.5, 0.5, 0.5]})
        picks = picks_frame([("2026-01-05", "A", "leaders", "v2")])
        out = compute_scores(picks, snapshots, bench, horizons=[1, 3])

        h1 = out[out["horizon"] == 1].iloc[0]
        assert h1["fwd_ret"] == pytest.approx(1.0)
        assert h1["fwd_ret_spy"] == pytest.approx(0.5)
        # median over A(1), B(2), C(-1) = 1
        assert h1["fwd_ret_median"] == pytest.approx(1.0)
        # non-selected = B(2), C(-1) -> mean 0.5
        assert h1["n_nonsel"] == 2
        assert h1["fwd_ret_nonsel_mean"] == pytest.approx(0.5)
        assert h1["excess_nonsel"] == pytest.approx(0.5)

        h3 = out[out["horizon"] == 3].iloc[0]
        assert h3["fwd_ret"] == pytest.approx((1.01 ** 3 - 1) * 100)
        assert h3["excess_spy"] == pytest.approx(h3["fwd_ret"] - (1.005 ** 3 - 1) * 100)
        assert h3["n_sessions_avail"] == 3
        assert list(out.columns) == SCORE_COLUMNS

    def test_gap_dates_counted_positionally(self):
        # A weekend/holiday gap between sessions must not shrink the window:
        # horizons count trading sessions (positions), not calendar days.
        dates = ["2026-01-02", "2026-01-05", "2026-01-06"]  # gap over the weekend
        snapshots = self.make_snapshots(dates, {"A": [0, 3, 3], "B": [0, 1, 1]})
        picks = picks_frame([("2026-01-02", "A", "accel", "v2")])
        out = compute_scores(picks, snapshots, BENCH_EMPTY, horizons=[2])
        row = out.iloc[0]
        assert row["n_sessions_avail"] == 2
        assert row["fwd_ret"] == pytest.approx((1.03 ** 2 - 1) * 100)

    def test_partial_window_then_settles_on_rebuild(self):
        picks = picks_frame([("2026-01-05", "A", "leaders", "v2")])
        dates_short = ["2026-01-05", "2026-01-06"]
        short = self.make_snapshots(dates_short, {"A": [0, 1]})
        out1 = compute_scores(picks, short, BENCH_EMPTY, horizons=[3])
        assert out1.iloc[0]["n_sessions_avail"] == 1  # partial, unsettled

        dates_full = dates_short + ["2026-01-07", "2026-01-08"]
        full = self.make_snapshots(dates_full, {"A": [0, 1, 1, 1]})
        out2 = compute_scores(picks, full, BENCH_EMPTY, horizons=[3])
        row = out2.iloc[0]
        assert row["n_sessions_avail"] == 3  # settled after rebuild
        assert row["fwd_ret"] == pytest.approx((1.01 ** 3 - 1) * 100)

    def test_zero_forward_sessions_skipped(self):
        snapshots = snap([("2026-01-05", "A", 1.0)])
        picks = picks_frame([("2026-01-05", "A", "leaders", "v2")])
        out = compute_scores(picks, snapshots, BENCH_EMPTY)
        assert len(out) == 0

    def test_missing_spy_and_median_nan_handling(self):
        dates = ["2026-01-05", "2026-01-06"]
        snapshots = self.make_snapshots(dates, {"A": [0, 1], "B": [0, np.nan]})
        picks = picks_frame([("2026-01-05", "A", "leaders", "v2")])
        out = compute_scores(picks, snapshots, BENCH_EMPTY, horizons=[1])
        row = out.iloc[0]
        assert np.isnan(row["fwd_ret_spy"]) and np.isnan(row["excess_spy"])
        # B is NaN in-window -> excluded from median (median = A alone) and control
        assert row["fwd_ret_median"] == pytest.approx(1.0)
        assert row["n_nonsel"] == 0
        assert np.isnan(row["fwd_ret_nonsel_mean"])

    def test_empty_picks_yields_empty_frame(self):
        out = compute_scores(picks_frame([]), snap([("2026-01-05", "A", 1.0)]), BENCH_EMPTY)
        assert len(out) == 0
        assert list(out.columns) == SCORE_COLUMNS


class TestLoadSelectedGroups:
    def test_dedupes_and_pipe_joins_buckets(self, tmp_path):
        p = tmp_path / "picks.csv"
        p.write_text(
            "date,collected_at,list_category,selector_version,group,ticker\n"
            "2026-01-05,t,leaders,v2,Gold,AAA\n"
            "2026-01-05,t,leaders,v2,Gold,BBB\n"
            "2026-01-05,t,accel,v2,Gold,AAA\n"
            "2026-01-05,t,emerging,v2,Silver,CCC\n"
        )
        out = load_selected_groups(p)
        assert len(out) == 2
        gold = out[out["group"] == "Gold"].iloc[0]
        assert gold["buckets"] == "accel|leaders"
        assert gold["selector_version"] == "v2"

    def test_headers_only_no_crash(self, tmp_path):
        p = tmp_path / "picks.csv"
        p.write_text("date,collected_at,list_category,selector_version,group,ticker\n")
        out = load_selected_groups(p)
        assert len(out) == 0

    def test_missing_file(self, tmp_path):
        assert len(load_selected_groups(tmp_path / "nope.csv")) == 0


class TestWriteAndReport:
    def test_write_empty_scores_header_only(self, tmp_path):
        out_csv = tmp_path / "eval" / "group_scores.csv"
        write_scores(pd.DataFrame(columns=SCORE_COLUMNS), out_csv)
        df = pd.read_csv(out_csv)
        assert list(df.columns) == SCORE_COLUMNS and len(df) == 0

    def test_report_runs_and_flags_low_power(self, capsys):
        dates = ["2026-01-05", "2026-01-06", "2026-01-07"]
        snapshots = pd.concat([
            snap([(d, "A", p) for d, p in zip(dates, [0, 2, 2])]),
            snap([(d, "B", p) for d, p in zip(dates, [0, 1, 1])]),
        ])
        bench = pd.DataFrame({"date": dates, "perf_day": [0, 0.5, 0.5]})
        picks = picks_frame([("2026-01-05", "A", "leaders|accel", "v2")])
        scores = compute_scores(picks, snapshots, bench, horizons=HORIZONS)
        print_report(scores)
        text = capsys.readouterr().out
        assert "NOT YET POWERED" in text
        assert "leaders" in text and "accel" in text  # bucket explode
        assert "Paired per-date" in text

    def test_report_no_settled_rows(self, capsys):
        print_report(pd.DataFrame(columns=SCORE_COLUMNS))
        assert "No settled rows" in capsys.readouterr().out
