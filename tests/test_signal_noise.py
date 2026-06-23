import pandas as pd
import pytest

from scripts.signal_noise import rolling_churn, DEFAULT_WINDOW


def _df(dates, scores_a, scores_b=None):
    rows = [{"date": d, "name": "A", "momentum_score": s} for d, s in zip(dates, scores_a)]
    if scores_b is not None:
        rows += [{"date": d, "name": "B", "momentum_score": s} for d, s in zip(dates, scores_b)]
    return pd.DataFrame(rows)


class TestRollingChurn:
    def test_empty_df_returns_empty(self):
        df = pd.DataFrame(columns=["date", "name", "momentum_score"])
        result = rolling_churn(df)
        assert result.empty

    def test_missing_momentum_score_column_returns_empty(self):
        df = pd.DataFrame({"date": ["2026-06-09"], "name": ["A"]})
        result = rolling_churn(df)
        assert result.empty

    def test_single_session_per_group_returns_empty(self):
        # diff() needs ≥2 rows per group to produce a non-NaN abs_delta
        df = _df(["2026-06-09"], [0.5])
        result = rolling_churn(df)
        assert result.empty

    def test_abs_delta_computed_correctly(self):
        df = _df(["2026-06-09", "2026-06-10"], [0.6, 0.4])
        result = rolling_churn(df)
        assert len(result) == 1
        assert result["abs_delta"].iloc[0] == pytest.approx(0.2)

    def test_abs_delta_is_always_positive(self):
        # Whether score went up or down, abs_delta must be non-negative
        df = _df(["2026-06-09", "2026-06-10", "2026-06-11"], [0.3, 0.7, 0.5])
        result = rolling_churn(df)
        assert (result["abs_delta"] >= 0).all()

    def test_rolling_mean_correct_over_window(self):
        # 5 sessions, window=3 → last rolling_mean = mean of last 3 abs_deltas
        dates = [f"2026-06-{9 + i:02d}" for i in range(5)]
        # scores:    0.5, 0.6, 0.4, 0.7, 0.3
        # abs_delta:      0.1, 0.2, 0.3, 0.4
        # rolling(3):          mean(0.1,0.2,0.3)=0.2  mean(0.2,0.3,0.4)=0.3
        df = _df(dates, [0.5, 0.6, 0.4, 0.7, 0.3])
        result = rolling_churn(df, window=3)
        last_row = result[result["date"] == pd.Timestamp("2026-06-13")]
        assert last_row["rolling_mean"].iloc[0] == pytest.approx(0.3)

    def test_rolling_mean_min_periods_2_fills_early_rows(self):
        # With min_periods=2, the rolling_mean requires ≥2 non-NaN abs_deltas
        # in the window. The first abs_delta row is the 2nd session; it has only
        # 1 non-NaN abs_delta → rolling_mean is NaN. The 3rd session has 2 →
        # rolling_mean populates. Use 4 sessions so the later rows can be checked.
        df = _df(["2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12"],
                 [0.5, 0.6, 0.4, 0.7])
        result = rolling_churn(df, window=20)  # window larger than data
        # 3 abs_delta rows; last 2 should have rolling_mean populated
        assert result["rolling_mean"].iloc[-1] != float("nan")
        assert result["rolling_mean"].iloc[-1] == pytest.approx(
            result["abs_delta"].iloc[-3:].mean()  # mean of all 3 non-NaN abs_deltas
        )

    def test_as_of_filter_truncates_dates(self):
        dates = [f"2026-06-{9 + i:02d}" for i in range(5)]
        df = _df(dates, [0.5, 0.6, 0.4, 0.7, 0.3])
        result = rolling_churn(df, as_of="2026-06-11")
        assert result["date"].max() == pd.Timestamp("2026-06-11")

    def test_two_groups_computed_independently(self):
        # Group A: monotonically increasing → large deltas
        # Group B: flat → near-zero deltas
        dates = [f"2026-06-{9 + i:02d}" for i in range(4)]
        df = _df(dates, scores_a=[0.1, 0.4, 0.7, 1.0], scores_b=[0.5, 0.5, 0.5, 0.5])
        result = rolling_churn(df, window=5)
        latest = result[result["date"] == result["date"].max()]
        churn_a = latest[latest["name"] == "A"]["rolling_mean"].iloc[0]
        churn_b = latest[latest["name"] == "B"]["rolling_mean"].iloc[0]
        assert churn_a > churn_b
        assert churn_b == pytest.approx(0.0)

    def test_nan_momentum_score_rows_excluded(self):
        # NaN momentum_score on one date should not propagate to adjacent deltas
        dates = ["2026-06-09", "2026-06-10", "2026-06-11"]
        df = pd.DataFrame([
            {"date": "2026-06-09", "name": "A", "momentum_score": 0.5},
            {"date": "2026-06-10", "name": "A", "momentum_score": float("nan")},
            {"date": "2026-06-11", "name": "A", "momentum_score": 0.7},
        ])
        result = rolling_churn(df)
        # The only non-NaN abs_delta is 0.2 (0.7 - 0.5, with the NaN row
        # propagating NaN into both its own delta and the next).
        # After dropna(subset=["abs_delta"]) we should have no NaN abs_delta rows.
        assert (result["abs_delta"].notna()).all()

    def test_default_window_is_20(self):
        assert DEFAULT_WINDOW == 20
