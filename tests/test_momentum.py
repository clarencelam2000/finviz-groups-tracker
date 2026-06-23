import pandas as pd
import pytest

from scripts.compute_deltas import compute_momentum


class TestComputeMomentum:
    def test_all_metrics_present_top_scorer(self):
        # perf_day intentionally absent — no longer a momentum input (too noisy).
        df = pd.DataFrame({
            "name": ["A", "B", "C"],
            "perf_week":    [3.0, 2.0, 1.0],
            "perf_month":   [3.0, 2.0, 1.0],
            "perf_quarter": [3.0, 2.0, 1.0],
            "perf_half":    [3.0, 2.0, 1.0],
            "perf_year":    [3.0, 2.0, 1.0],
            "perf_ytd":     [3.0, 2.0, 1.0],
        })
        scores = compute_momentum(df)
        assert scores.iloc[0] == pytest.approx(1.0)   # A: top in all
        assert scores.iloc[2] == pytest.approx(0.0)   # C: bottom in all
        assert scores.iloc[0] > scores.iloc[1] > scores.iloc[2]

    def test_single_row_returns_nan(self):
        df = pd.DataFrame({"name": ["A"], "perf_ytd": [10.0]})
        scores = compute_momentum(df)
        assert scores.isna().all()

    def test_missing_metric_column_still_produces_scores(self):
        # perf_quarter absent — should compute from remaining 5 metrics (of 6 total)
        df = pd.DataFrame({
            "name": ["A", "B", "C"],
            "perf_week":  [3.0, 2.0, 1.0],
            "perf_month": [3.0, 2.0, 1.0],
            # perf_quarter intentionally absent
            "perf_half":  [3.0, 2.0, 1.0],
            "perf_year":  [3.0, 2.0, 1.0],
            "perf_ytd":   [3.0, 2.0, 1.0],
        })
        scores = compute_momentum(df)
        assert scores.notna().all()
        assert scores.iloc[0] == pytest.approx(1.0)

    def test_all_nan_metric_column_excluded_from_mean(self):
        # perf_quarter present but entirely NaN — should be excluded, not drag all scores to NaN
        df = pd.DataFrame({
            "name": ["A", "B", "C"],
            "perf_week":    [3.0, 2.0, 1.0],
            "perf_month":   [3.0, 2.0, 1.0],
            "perf_quarter": [float("nan"), float("nan"), float("nan")],
            "perf_half":    [3.0, 2.0, 1.0],
            "perf_year":    [3.0, 2.0, 1.0],
            "perf_ytd":     [3.0, 2.0, 1.0],
        })
        scores = compute_momentum(df)
        assert scores.notna().all()

    def test_row_with_nan_perf_gets_bottom_rank(self):
        # NaN values get na_option="bottom" rank → score 0.0 (not NaN)
        df = pd.DataFrame({
            "name": ["A", "B", "C"],
            "perf_ytd": [10.0, 5.0, float("nan")],
        })
        scores = compute_momentum(df)
        assert scores.notna().all()
        # C gets bottom rank → score 0.0
        assert scores.iloc[2] == pytest.approx(0.0)
        # A gets rank 1 → score 1.0
        assert scores.iloc[0] == pytest.approx(1.0)

    def test_scores_bounded_between_0_and_1(self):
        df = pd.DataFrame({
            "name": [f"G{i}" for i in range(10)],
            "perf_ytd": list(range(10, 0, -1)),
            "perf_week": list(range(1, 11)),
        })
        scores = compute_momentum(df)
        assert (scores >= 0.0).all()
        assert (scores <= 1.0).all()

    def test_perf_day_does_not_influence_score(self):
        # Day is excluded from momentum scoring (too noisy). A big red day for the
        # otherwise-strongest group must not change its score — it should still
        # lead on the 6 durable timeframes.
        base = {
            "name": ["A", "B", "C"],
            "perf_week":    [3.0, 2.0, 1.0],
            "perf_month":   [3.0, 2.0, 1.0],
            "perf_quarter": [3.0, 2.0, 1.0],
            "perf_half":    [3.0, 2.0, 1.0],
            "perf_year":    [3.0, 2.0, 1.0],
            "perf_ytd":     [3.0, 2.0, 1.0],
        }
        without_day = compute_momentum(pd.DataFrame(base))
        with_red_day = compute_momentum(pd.DataFrame({**base, "perf_day": [-99.0, 5.0, 5.0]}))
        # Adding perf_day (even a catastrophic one for A) leaves scores identical.
        assert list(without_day) == pytest.approx(list(with_red_day))
        assert with_red_day.iloc[0] == pytest.approx(1.0)  # A still tops the score
