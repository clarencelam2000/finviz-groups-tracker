"""
Tests for scripts/replay_picks.py — see planning/picks-methodology-tracking.md
for the design spec these tests validate against.
"""
import datetime as dt
import math
from pathlib import Path

import pandas as pd
import pytest

from scripts import replay_picks as rp

ROOT = Path(__file__).parent.parent
FIXTURE_CSV = ROOT / "tests" / "fixtures" / "replay_picks_fixture.csv"
FIXTURE_V2_CSV = ROOT / "tests" / "fixtures" / "replay_picks_v2_fixture.csv"
FIXTURE_V4_CSV = ROOT / "tests" / "fixtures" / "replay_picks_v4_fixture.csv"


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

    def test_loads_v2_for_pipeline_start_of_liquidity_earnings(self):
        m = rp.load_methodology("2026-07-01")
        assert m["version"] == "v2"

    def test_loads_v2_for_date_just_before_v3_effective(self):
        m = rp.load_methodology("2026-07-15")
        assert m["version"] == "v2"

    def test_loads_v3_for_pipeline_start_of_weight_rebalance(self):
        m = rp.load_methodology("2026-07-16")
        assert m["version"] == "v3"

    def test_loads_v3_for_date_just_before_v4_effective(self):
        m = rp.load_methodology("2026-08-11")
        assert m["version"] == "v3"

    def test_loads_v4_for_pipeline_start_of_overhead_penalty(self):
        m = rp.load_methodology("2026-08-12")
        assert m["version"] == "v4"

    def test_loads_v4_for_date_just_before_v5_effective(self):
        m = rp.load_methodology("2026-08-24")
        assert m["version"] == "v4"

    def test_loads_v5_for_pipeline_start_of_all_green_category_order(self):
        m = rp.load_methodology("2026-08-25")
        assert m["version"] == "v5"

    def test_loads_v5_for_later_date(self):
        m = rp.load_methodology("2026-09-01")
        assert m["version"] == "v5"

    def test_loads_v1_for_date_before_v2_effective(self):
        m = rp.load_methodology("2026-06-30")
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


# ---------------------------------------------------------------------------
# Pure-function tests: liquidity/earnings penalties (v2, Phase 3d)
# ---------------------------------------------------------------------------

V2_LIQ_PARAMS = {"ramp_start": 60_000_000, "floor": 30_000_000, "max_fraction": 0.3}
V2_EARN_PARAMS = {
    "caution_days": 10,
    "imminent_days": 3,
    "max_fraction": 0.7,
    "post_earnings_carryover_days": 1,
    "post_earnings_carryover_fraction": 0.25,
}


class TestLiquidityPenaltyFrac:
    def test_no_penalty_at_or_above_ramp_start(self):
        assert rp.liquidity_penalty_frac(60_000_000, V2_LIQ_PARAMS) == 0.0
        assert rp.liquidity_penalty_frac(100_000_000, V2_LIQ_PARAMS) == 0.0

    def test_max_penalty_at_floor(self):
        assert math.isclose(rp.liquidity_penalty_frac(30_000_000, V2_LIQ_PARAMS), 0.3)

    def test_midpoint_penalty(self):
        # $45M is exactly halfway between the $30M floor and $60M ramp start.
        assert math.isclose(rp.liquidity_penalty_frac(45_000_000, V2_LIQ_PARAMS), 0.15)

    def test_nan_dollar_volume_is_zero_penalty(self):
        assert rp.liquidity_penalty_frac(float("nan"), V2_LIQ_PARAMS) == 0.0


V4_OVERHEAD_PARAMS = {"ramp_start": 8, "ramp_end": 30, "max_fraction": 0.20}


class TestOverheadPenaltyFrac:
    def test_no_penalty_at_or_below_ramp_start(self):
        assert rp.overhead_penalty_frac("-8.0%", V4_OVERHEAD_PARAMS) == 0.0
        assert rp.overhead_penalty_frac("-3.0%", V4_OVERHEAD_PARAMS) == 0.0

    def test_max_penalty_at_or_beyond_ramp_end(self):
        assert math.isclose(rp.overhead_penalty_frac("-30.0%", V4_OVERHEAD_PARAMS), 0.20)
        # Beyond ramp_end the clamp holds it at max_fraction, it does not extrapolate past it.
        assert math.isclose(rp.overhead_penalty_frac("-50.0%", V4_OVERHEAD_PARAMS), 0.20)

    def test_midpoint_penalty(self):
        # -19% is exactly halfway between ramp_start=8 and ramp_end=30 (ohMag=19).
        assert math.isclose(rp.overhead_penalty_frac("-19.0%", V4_OVERHEAD_PARAMS), 0.10)

    def test_dash_returns_zero_penalty(self):
        assert rp.overhead_penalty_frac("-", V4_OVERHEAD_PARAMS) == 0.0

    def test_none_returns_zero_penalty(self):
        assert rp.overhead_penalty_frac(None, V4_OVERHEAD_PARAMS) == 0.0

    def test_nan_returns_zero_penalty(self):
        assert rp.overhead_penalty_frac(float("nan"), V4_OVERHEAD_PARAMS) == 0.0

    def test_positive_value_from_stale_finviz_data_is_zero_not_negative(self):
        # Finviz's '52W High' distance is normally <= 0 (price at/below the 52wk high), but a
        # documented real-world data lag can report a *positive* value when a stock has already
        # broken to a new high before Finviz's stored 52W High catches up. ohMag = -parsed then
        # goes negative -- must clamp to 0 (same as an ordinary near-high row), not go negative
        # or otherwise misbehave.
        frac = rp.overhead_penalty_frac("+2.0%", V4_OVERHEAD_PARAMS)
        assert frac == 0.0

    def test_deeply_positive_value_still_zero_penalty(self):
        frac = rp.overhead_penalty_frac("+15.0%", V4_OVERHEAD_PARAMS)
        assert frac == 0.0


class TestParseEarningsDaysUntil:
    def test_future_date_same_year(self):
        d = rp.parse_earnings_days_until("Jul 03", dt.date(2026, 7, 1))
        assert d == 2

    def test_past_date_negative(self):
        d = rp.parse_earnings_days_until("Jun 30", dt.date(2026, 7, 1))
        assert d == -1

    def test_dash_returns_none(self):
        assert rp.parse_earnings_days_until("-", dt.date(2026, 7, 1)) is None

    def test_after_close_suffix_parses(self):
        d = rp.parse_earnings_days_until("Jul 03/a", dt.date(2026, 7, 1))
        assert d == 2

    def test_wraps_to_next_year_when_far_in_past(self):
        # "Jan 05" viewed from "Dec 20" of the same year is >180 days in the past
        # under the same-year assumption, so it should roll to next Jan 05.
        d = rp.parse_earnings_days_until("Jan 05", dt.date(2026, 12, 20))
        assert d == 16


class TestEarningsPenaltyFrac:
    def test_no_earnings_data_is_zero_penalty(self):
        assert rp.earnings_penalty_frac("-", dt.date(2026, 7, 1), V2_EARN_PARAMS) == 0.0

    def test_imminent_is_max_penalty(self):
        frac = rp.earnings_penalty_frac("Jul 03", dt.date(2026, 7, 1), V2_EARN_PARAMS)
        assert frac == 0.7

    def test_carryover_one_day_after(self):
        frac = rp.earnings_penalty_frac("Jun 30", dt.date(2026, 7, 1), V2_EARN_PARAMS)
        assert math.isclose(frac, 0.7 * 0.25)

    def test_two_days_past_is_fully_decayed(self):
        frac = rp.earnings_penalty_frac("Jun 29", dt.date(2026, 7, 1), V2_EARN_PARAMS)
        assert frac == 0.0

    def test_far_future_is_zero_penalty(self):
        frac = rp.earnings_penalty_frac("Aug 01", dt.date(2026, 7, 1), V2_EARN_PARAMS)
        assert frac == 0.0

    def test_ramp_midpoint(self):
        # 6 days out is halfway between imminent_days=3 and caution_days=10... check exact ramp math.
        frac = rp.earnings_penalty_frac("Jul 07", dt.date(2026, 7, 1), V2_EARN_PARAMS)
        expected = 0.7 * (10 - 6) / (10 - 3)
        assert math.isclose(frac, expected)


# ---------------------------------------------------------------------------
# Full v2 replay pipeline: liquidity gate/penalty + earnings penalty
# ---------------------------------------------------------------------------

class TestReplayV2Fixture:
    def setup_method(self):
        rp.PICKS_CSV = FIXTURE_V2_CSV

    def test_v2_methodology_selected_for_date(self):
        out = rp.replay(date="2026-07-01", view="focus")
        assert "focus_score" in out.columns

    def test_thin_liquidity_excluded_by_dq_gate(self):
        # TOOTHIN: Price 10 * Avg Volume 2.00M = $20M avg $ volume, below the $30M floor.
        out = rp.replay(date="2026-07-01", view="focus")
        assert "TOOTHIN" not in out["ticker"].values

    def test_thin_but_eligible_liquidity_gets_penalized_not_excluded(self):
        # THINBUT: Price 50 * Avg Volume 900K = $45M, inside [$30M, $60M) -> penalized, not excluded.
        out = rp.replay(date="2026-07-01", view="focus")
        assert "THINBUT" in out["ticker"].values

    def test_imminent_earnings_scores_lower_than_just_reported(self):
        # IMMINENT and JUSTREPORTED are identical on every field except 'Earnings':
        # IMMINENT is 2 days out (max 0.7 penalty), JUSTREPORTED reported yesterday
        # (0.7*0.25 carryover penalty) -- JUSTREPORTED's multiplier is larger, so its
        # focus_score should be proportionally higher, all else being equal.
        out = rp.replay(date="2026-07-01", view="focus")
        imminent = out[out["ticker"] == "IMMINENT"]["focus_score"].iloc[0]
        just_reported = out[out["ticker"] == "JUSTREPORTED"]["focus_score"].iloc[0]
        ratio = just_reported / imminent
        expected_ratio = (1 - 0.7 * 0.25) / (1 - 0.7)
        assert math.isclose(ratio, expected_ratio, rel_tol=1e-6)

    def teardown_method(self):
        rp.PICKS_CSV = ROOT / "data" / "picks" / "picks.csv"


# ---------------------------------------------------------------------------
# Full v4 replay pipeline: overhead-supply penalty (Phase 2)
# ---------------------------------------------------------------------------

class TestReplayV4Fixture:
    def setup_method(self):
        rp.PICKS_CSV = FIXTURE_V4_CSV

    def test_v4_methodology_selected_for_date(self):
        out = rp.replay(date="2026-08-12", view="focus")
        assert "focus_score" in out.columns

    def test_deep_overhead_scores_lower_than_near_high(self):
        # NEARHIGH and DEEPOH are identical on every field except '52W High', so the
        # entire score difference between them is the overhead penalty: NEARHIGH gets 0
        # (ohMag=3 <= ramp_start=8), DEEPOH gets the full 0.20 haircut (ohMag=35 >= ramp_end=30).
        out = rp.replay(date="2026-08-12", view="focus")
        near = out[out["ticker"] == "NEARHIGH"]["focus_score"].iloc[0]
        deep = out[out["ticker"] == "DEEPOH"]["focus_score"].iloc[0]
        ratio = near / deep
        assert math.isclose(ratio, 1 / (1 - 0.20), rel_tol=1e-6)

    def test_stale_finviz_high_treated_as_near_high_not_penalized(self):
        # STALEHIGH's '52W High' is a positive '+2.0%' -- the data-lag edge case where Finviz
        # hasn't caught up to a fresh breakout yet. It must score identically to NEARHIGH (both
        # 0 overhead penalty), not lower, and the replay must not raise.
        out = rp.replay(date="2026-08-12", view="focus")
        near = out[out["ticker"] == "NEARHIGH"]["focus_score"].iloc[0]
        stale = out[out["ticker"] == "STALEHIGH"]["focus_score"].iloc[0]
        assert math.isclose(near, stale, rel_tol=1e-9)

    def teardown_method(self):
        rp.PICKS_CSV = ROOT / "data" / "picks" / "picks.csv"
