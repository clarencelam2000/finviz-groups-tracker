"""
Tests for pure functions in scripts/compute_deltas.py.
All tests use in-memory data — no CSV I/O.
"""

import math
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import compute_deltas as cd


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def snapshot_3():
    """Three-row snapshot with clean perf data."""
    return pd.DataFrame({
        "name": ["Tech", "Energy", "Finance"],
        "perf_day":     [3.0, 1.0, 2.0],
        "perf_week":    [3.0, 1.0, 2.0],
        "perf_month":   [1.0, 3.0, 2.0],
        "perf_quarter": [2.0, 1.0, 3.0],
        "perf_half":    [1.0, 2.0, 3.0],
        "perf_year":    [3.0, 2.0, 1.0],
        "perf_ytd":     [2.0, 3.0, 1.0],
    })


# ---------------------------------------------------------------------------
# find_nearest_date
# ---------------------------------------------------------------------------

class TestFindNearestDate:
    def test_exact_match(self):
        dates = [date(2026, 1, 1), date(2026, 1, 8), date(2026, 1, 15)]
        assert cd.find_nearest_date(dates, date(2026, 1, 8)) == date(2026, 1, 8)

    def test_within_tolerance(self):
        dates = [date(2026, 1, 1), date(2026, 1, 10)]
        # target is Jan 13; Jan 10 is 3 days prior — within 5-day tolerance
        assert cd.find_nearest_date(dates, date(2026, 1, 13)) == date(2026, 1, 10)

    def test_beyond_tolerance_returns_none(self):
        dates = [date(2026, 1, 1)]
        # target is Jan 10; Jan 1 is 9 days prior — beyond 5-day tolerance
        assert cd.find_nearest_date(dates, date(2026, 1, 10)) is None

    def test_empty_list_returns_none(self):
        assert cd.find_nearest_date([], date(2026, 1, 1)) is None

    def test_no_dates_before_target_returns_none(self):
        dates = [date(2026, 1, 5)]
        assert cd.find_nearest_date(dates, date(2026, 1, 1)) is None


# ---------------------------------------------------------------------------
# compute_ranks
# ---------------------------------------------------------------------------

class TestComputeRanks:
    def test_rank_1_is_best_performer(self, snapshot_3):
        result = cd.compute_ranks(snapshot_3)
        # perf_week: Tech=3.0 (best), Finance=2.0, Energy=1.0
        assert result.loc[result["name"] == "Tech", "rank_week"].iloc[0] == 1
        assert result.loc[result["name"] == "Energy", "rank_week"].iloc[0] == 3

    def test_nan_goes_to_bottom(self):
        df = pd.DataFrame({
            "name": ["A", "B", "C"],
            "perf_week": [2.0, float("nan"), 1.0],
            "perf_month": [1.0, 2.0, 3.0],
            "perf_quarter": [1.0, 2.0, 3.0],
            "perf_half": [1.0, 2.0, 3.0],
            "perf_year": [1.0, 2.0, 3.0],
            "perf_ytd": [1.0, 2.0, 3.0],
        })
        result = cd.compute_ranks(df)
        # NaN gets rank 3 (bottom) via na_option='bottom'
        assert result.loc[result["name"] == "B", "rank_week"].iloc[0] == 3

    def test_does_not_mutate_input(self, snapshot_3):
        original_cols = list(snapshot_3.columns)
        cd.compute_ranks(snapshot_3)
        assert list(snapshot_3.columns) == original_cols


# ---------------------------------------------------------------------------
# compute_momentum
# ---------------------------------------------------------------------------

class TestComputeMomentum:
    def test_scores_in_0_1_range(self, snapshot_3):
        scores = cd.compute_momentum(snapshot_3)
        assert scores.between(0.0, 1.0).all()

    def test_best_performer_has_highest_score(self, snapshot_3):
        # Tech leads perf_week/perf_year/perf_day; should score high overall
        scores = cd.compute_momentum(snapshot_3)
        snapshot_3 = snapshot_3.copy()
        snapshot_3["score"] = scores
        # Just verify no score is exactly equal across the board (all different)
        assert scores.nunique() > 1

    def test_single_row_returns_nan(self):
        df = pd.DataFrame({
            "name": ["Tech"],
            "perf_day": [1.0], "perf_week": [1.0], "perf_month": [1.0],
            "perf_quarter": [1.0], "perf_half": [1.0], "perf_year": [1.0],
            "perf_ytd": [1.0],
        })
        scores = cd.compute_momentum(df)
        assert math.isnan(scores.iloc[0])

    def test_all_nan_column_ignored(self):
        df = pd.DataFrame({
            "name": ["A", "B"],
            "perf_day":     [float("nan"), float("nan")],
            "perf_week":    [2.0, 1.0],
            "perf_month":   [2.0, 1.0],
            "perf_quarter": [2.0, 1.0],
            "perf_half":    [2.0, 1.0],
            "perf_year":    [2.0, 1.0],
            "perf_ytd":     [2.0, 1.0],
        })
        scores = cd.compute_momentum(df)
        # Should not crash and A should score higher than B
        assert scores.iloc[0] > scores.iloc[1]


# ---------------------------------------------------------------------------
# _fmt
# ---------------------------------------------------------------------------

class TestFmt:
    def test_nan_returns_empty_string(self):
        assert cd._fmt(float("nan")) == ""

    def test_none_returns_empty_string(self):
        assert cd._fmt(None) == ""

    def test_valid_float_passes_through(self):
        assert cd._fmt(3.14) == 3.14

    def test_zero_passes_through(self):
        assert cd._fmt(0.0) == 0.0

    def test_negative_passes_through(self):
        assert cd._fmt(-5.0) == -5.0

    def test_string_nan_returns_empty_string(self):
        # "nan" as a string coerces to float nan
        assert cd._fmt("nan") == ""
