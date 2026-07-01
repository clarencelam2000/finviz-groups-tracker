"""
Tests for scripts/replay_picks.py — see planning/picks-methodology-tracking.md
for the design spec these tests validate against.
"""
import math
from pathlib import Path

import pandas as pd
import pytest

from scripts import replay_picks as rp

ROOT = Path(__file__).parent.parent
FIXTURE_CSV = ROOT / "tests" / "fixtures" / "replay_picks_fixture.csv"


# ---------------------------------------------------------------------------
# normalize_inv unit tests
# ---------------------------------------------------------------------------

class TestNormalizeInv:
    def test_minmax_lower_is_better(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])  # n=5, min_pool=5 -> minmax path
        out = rp.normalize_inv(s, min_pool=5)
        assert out.iloc[0] == 1.0  # lowest raw -> best score
        assert out.iloc[-1] == 0.0  # highest raw -> worst score

    def test_all_equal_defaults_to_half(self):
        s = pd.Series([2.0, 2.0, 2.0, 2.0, 2.0])
        out = rp.normalize_inv(s, min_pool=5)
        assert (out == 0.5).all()

    def test_nan_defaults_to_half_in_minmax_path(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, float("nan")])
        out = rp.normalize_inv(s, min_pool=5)
        assert out.iloc[-1] == 0.5

    def test_all_nan_defaults_to_half(self):
        s = pd.Series([float("nan")] * 3)
        out = rp.normalize_inv(s, min_pool=5)
        assert (out == 0.5).all()

    def test_small_pool_uses_rank_based_percentile(self):
        s = pd.Series([1.0, 2.0, 3.0])  # n=3 < min_pool=5
        out = rp.normalize_inv(s, min_pool=5)
        assert out.iloc[0] == 1.0  # lowest raw -> best
        assert out.iloc[-1] == 0.0  # highest raw -> worst
        assert out.iloc[1] == 0.5

    def test_small_pool_single_valid_value_scores_one(self):
        s = pd.Series([5.0])  # n=1 < min_pool=5, single valid entry
        out = rp.normalize_inv(s, min_pool=5)
        assert out.iloc[0] == 1.0

    def test_small_pool_nan_stays_neutral_not_best(self):
        s = pd.Series([1.0, float("nan")])  # n=2 < min_pool=5
        out = rp.normalize_inv(s, min_pool=5)
        assert out.iloc[0] == 1.0
        assert out.iloc[1] == 0.5  # NaN never gets the m==1 shortcut


# ---------------------------------------------------------------------------
# load_methodology
# ---------------------------------------------------------------------------

class TestLoadMethodology:
    def test_loads_v1_for_pipeline_start_date(self):
        m = rp.load_methodology("2026-06-25")
        assert m["version"] == "v1"

    def test_loads_v1_for_later_date(self):
        m = rp.load_methodology("2026-07-01")
        assert m["version"] == "v1"

    def test_override_selects_specific_version(self):
        m = rp.load_methodology("2026-07-01", override="v1")
        assert m["version"] == "v1"

    def test_override_unknown_version_raises(self):
        with pytest.raises(ValueError, match="Unknown methodology version"):
            rp.load_methodology("2026-07-01", override="v99")


# ---------------------------------------------------------------------------
# Full replay pipeline against a small fixture CSV
# ---------------------------------------------------------------------------

class TestReplayFixture:
    def setup_method(self, monkeypatch=None):
        rp.PICKS_CSV = FIXTURE_CSV

    def test_base_filter_excludes_microcap_and_downtrend(self):
        out = rp.replay(date="2026-06-25", view="all")
        assert "MICROCAP" not in out["ticker"].values
        assert "DOWNTREND" not in out["ticker"].values

    def test_multi_category_ticker_preserved_as_separate_rows(self):
        out = rp.replay(date="2026-06-25", view="all")
        anet_rows = out[out["ticker"] == "ANET"]
        assert len(anet_rows) == 2
        assert set(anet_rows["list_category"]) == {"leaders", "rs_new_high"}

    def test_all_view_sort_order(self):
        out = rp.replay(date="2026-06-25", view="all")
        # leaders (Computer Hardware alpha before Semiconductors, least-extended
        # first within group) then rs_new_high.
        assert list(zip(out["ticker"], out["list_category"])) == [
            ("ANET", "leaders"),
            ("STX", "leaders"),
            ("DELL", "leaders"),
            ("ANET", "rs_new_high"),
        ]

    def test_focus_view_excludes_nothing_within_dq_band(self):
        out = rp.replay(date="2026-06-25", view="focus")
        # All 4 base-filtered rows have 0 < atr_ext_50 <= 4.0 -> all qualify.
        assert len(out) == 4
        assert "focus_score" in out.columns
        assert out["focus_score"].between(0, 1).all()

    def test_focus_view_sorted_score_desc(self):
        out = rp.replay(date="2026-06-25", view="focus")
        scores = out["focus_score"].tolist()
        assert scores == sorted(scores, reverse=True)

    def test_focus_score_independent_per_category_row(self):
        # ANET's two rows (leaders, rs_new_high) share identical raw data and
        # must get the identical focus_score (computed independently per row,
        # same as the JS ticker+'_'+list_category keying).
        out = rp.replay(date="2026-06-25", view="focus")
        anet_scores = out[out["ticker"] == "ANET"]["focus_score"].tolist()
        assert len(anet_scores) == 2
        assert math.isclose(anet_scores[0], anet_scores[1])

    def test_unknown_date_raises_clear_error(self):
        with pytest.raises(ValueError, match="No picks found for 2099-01-01"):
            rp.replay(date="2099-01-01", view="all")

    def test_pre_pipeline_date_raises_pipeline_start_error(self):
        with pytest.raises(ValueError, match="picks pipeline started"):
            rp.replay(date="2020-01-01", view="all")

    def test_invalid_view_raises(self):
        with pytest.raises(ValueError, match="view must be"):
            rp.replay(date="2026-06-25", view="bogus")

    def teardown_method(self):
        rp.PICKS_CSV = ROOT / "data" / "picks" / "picks.csv"
