"""Tests for scripts/pick_status.py — ADR-013 Decision 3 state machine.

No I/O, no playwright import — safe to run everywhere including CI's default
`pytest tests/` invocation (not on the Playwright ignore list).
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from pick_status import (  # noqa: E402
    compute_pick_status,
    compute_atr_from_lod,
    compute_reclaim,
    STATUS_NO_QUOTE,
    STATUS_AWAITING_FIRST_READ,
    STATUS_INVALIDATED,
    STATUS_GAPPED_THROUGH,
    STATUS_TRIGGERED,
    STATUS_FAILED_BREAKOUT,
    STATUS_RECLAIM,
    STATUS_SETTING_UP,
    STATUS_PRECEDENCE,
    ACTIONABLE_STATUSES,
    matched_reclaim_ref,
)

NAN = float("nan")


# ---------------------------------------------------------------------------
# One test per state
# ---------------------------------------------------------------------------


def test_triggered():
    # trigger=10, stop=8; price >= trigger, open <= trigger
    assert compute_pick_status(10, 8, 10.5, 9.5, 10.6, 9.4) == STATUS_TRIGGERED


def test_setting_up():
    # nothing tagged: price/open/high all below trigger, price above stop
    assert compute_pick_status(10, 8, 9.0, 8.5, 9.2, 8.4) == STATUS_SETTING_UP


def test_gapped_through():
    assert compute_pick_status(10, 8, 11.0, 10.5, 11.2, 10.4) == STATUS_GAPPED_THROUGH


def test_failed_breakout():
    # high tagged trigger intraday but price pulled back below it; open didn't gap
    assert compute_pick_status(10, 8, 9.8, 9.5, 10.1, 9.4) == STATUS_FAILED_BREAKOUT


def test_invalidated():
    assert compute_pick_status(10, 8, 7.5, 8.5, 9.0, 7.4) == STATUS_INVALIDATED


def test_no_quote_missing_field():
    for missing_idx in range(6):
        args = [10, 8, 9.0, 8.5, 9.2, 8.4]
        args[missing_idx] = None
        assert compute_pick_status(*args) == STATUS_NO_QUOTE

    for missing_idx in range(6):
        args = [10, 8, 9.0, 8.5, 9.2, 8.4]
        args[missing_idx] = NAN
        assert compute_pick_status(*args) == STATUS_NO_QUOTE


# ---------------------------------------------------------------------------
# STATUS_AWAITING_FIRST_READ (WS-POSITIONS-STATUS)
# ---------------------------------------------------------------------------


def test_awaiting_first_read_when_has_history_false():
    # Missing trigger/stop (no bar yet) + has_history=False -> awaiting_first_read, not no_quote.
    assert (
        compute_pick_status(None, None, 9.0, 8.5, 9.2, 8.4, has_history=False)
        == STATUS_AWAITING_FIRST_READ
    )


def test_no_quote_when_has_history_true_despite_missing_field():
    # An established ticker Finviz genuinely failed to quote today stays no_quote.
    assert (
        compute_pick_status(10, 8, None, 8.5, 9.2, 8.4, has_history=True) == STATUS_NO_QUOTE
    )


def test_has_history_none_default_is_byte_identical_to_no_quote():
    # Every picks caller omits has_history -> default None must behave exactly like before.
    assert compute_pick_status(None, 8, 9.0, 8.5, 9.2, 8.4) == STATUS_NO_QUOTE


def test_has_history_false_does_not_fire_when_inputs_are_present():
    # has_history is only consulted inside the missing-inputs gate -- a complete quote still
    # evaluates normally even if has_history happens to be False (defensive, shouldn't occur
    # in practice since a real quote implies a bar exists).
    assert (
        compute_pick_status(10, 8, 10.5, 9.5, 10.6, 9.4, has_history=False) == STATUS_TRIGGERED
    )


# ---------------------------------------------------------------------------
# Precedence-collision cases
# ---------------------------------------------------------------------------


def test_invalidated_outranks_triggered():
    # price <= stop AND high >= trigger (tagged trigger earlier, now below stop)
    assert compute_pick_status(10, 8, 7.9, 9.0, 10.5, 7.8) == STATUS_INVALIDATED


def test_gapped_outranks_triggered():
    # open > trigger AND price >= trigger
    assert compute_pick_status(10, 8, 11.0, 10.5, 11.5, 10.4) == STATUS_GAPPED_THROUGH


# ---------------------------------------------------------------------------
# Boundary equality
# ---------------------------------------------------------------------------


def test_boundary_price_equals_stop_is_invalidated():
    assert compute_pick_status(10, 8, 8.0, 8.5, 9.0, 7.9) == STATUS_INVALIDATED


def test_boundary_price_equals_trigger_is_triggered():
    assert compute_pick_status(10, 8, 10.0, 9.5, 10.1, 9.4) == STATUS_TRIGGERED


def test_boundary_open_equals_trigger_is_not_gapped():
    # open == trigger must NOT trip gapped_through (predicate is strict >)
    assert compute_pick_status(10, 8, 10.0, 10.0, 10.2, 9.9) == STATUS_TRIGGERED


# ---------------------------------------------------------------------------
# Precedence list / actionable set sanity
# ---------------------------------------------------------------------------


def test_status_precedence_order():
    assert STATUS_PRECEDENCE == [
        STATUS_NO_QUOTE,
        STATUS_AWAITING_FIRST_READ,
        STATUS_INVALIDATED,
        STATUS_GAPPED_THROUGH,
        STATUS_TRIGGERED,
        STATUS_RECLAIM,
        STATUS_FAILED_BREAKOUT,
        STATUS_SETTING_UP,
    ]


def test_actionable_statuses():
    assert ACTIONABLE_STATUSES == {STATUS_TRIGGERED, STATUS_GAPPED_THROUGH, STATUS_RECLAIM}


# ---------------------------------------------------------------------------
# compute_reclaim (P2, watchlist build brief §3/§4c)
# ---------------------------------------------------------------------------


def test_compute_reclaim_true_today_low_dipped():
    # price > ref, today_low < ref (prior_low stays >= ref)
    assert compute_reclaim(price=51, today_low=49, prior_low=50.5, ref=50) is True


def test_compute_reclaim_true_prior_low_dipped():
    # price > ref, prior_low < ref, today_low >= ref
    assert compute_reclaim(price=51, today_low=50.5, prior_low=49, ref=50) is True


def test_compute_reclaim_false_price_not_above_ref():
    assert compute_reclaim(price=49, today_low=49, prior_low=49, ref=50) is False


def test_compute_reclaim_false_neither_low_dipped():
    assert compute_reclaim(price=51, today_low=50.5, prior_low=50.2, ref=50) is False


def test_compute_reclaim_false_on_missing_input():
    assert compute_reclaim(None, 49, 50.5, 50) is False
    assert compute_reclaim(51, None, 50.5, 50) is False
    assert compute_reclaim(51, 49, None, 50) is False
    assert compute_reclaim(51, 49, 50.5, None) is False
    assert compute_reclaim(51, NAN, 50.5, 50) is False


def test_compute_reclaim_boundary_price_equals_ref_is_false():
    assert compute_reclaim(price=50, today_low=49, prior_low=50.5, ref=50) is False


def test_compute_reclaim_boundary_low_equals_ref_is_not_below():
    # today_low == ref is not "< ref"; prior_low == ref is also not "< ref" -> False
    assert compute_reclaim(price=51, today_low=50, prior_low=50, ref=50) is False


# ---------------------------------------------------------------------------
# compute_pick_status with ref (P2)
# ---------------------------------------------------------------------------


def test_compute_pick_status_fires_reclaim():
    # trigger=10, stop=8 (prior_low); low(today)=7.5 < ref=8.5; price=9 > ref=8.5;
    # price < trigger, high < trigger, open <= trigger -> falls through to reclaim.
    assert compute_pick_status(10, 8, 9.0, 8.0, 9.1, 7.5, ref=8.5) == STATUS_RECLAIM


def test_compute_pick_status_ref_none_never_reclaims_regression():
    # Same inputs as the reclaim-firing case above, but ref=None (default) must
    # be byte-identical to pre-P2 behavior: setting_up, never reclaim.
    assert compute_pick_status(10, 8, 9.0, 8.0, 9.1, 7.5) == STATUS_SETTING_UP


def test_compute_pick_status_reclaim_does_not_outrank_triggered():
    # price >= trigger -> triggered wins even though a ref is supplied and would
    # also qualify as reclaim in isolation.
    assert compute_pick_status(10, 8, 10.5, 9.5, 10.6, 9.4, ref=9.0) == STATUS_TRIGGERED


def test_compute_pick_status_reclaim_does_not_outrank_gapped():
    assert compute_pick_status(10, 8, 11.0, 10.5, 11.2, 10.4, ref=9.0) == STATUS_GAPPED_THROUGH


def test_compute_pick_status_reclaim_outranks_failed_breakout():
    # Owner decision 2026-08-27: reclaim now sits ABOVE failed_breakout. Same inputs as
    # the old "does not outrank" test (high 10.1 >= trigger 10 AND a qualifying ref) now
    # read as reclaim — uniform for picks and watch. The recovered-off-the-lows signal
    # wins over the rejected-at-highs one.
    assert compute_pick_status(10, 8, 9.8, 9.5, 10.1, 7.5, ref=8.5) == STATUS_RECLAIM


def test_compute_pick_status_reclaim_still_below_invalidated():
    # price <= stop (prior_low) -> invalidated still wins even with a qualifying ref.
    assert compute_pick_status(10, 8, 7.9, 9.0, 10.5, 7.5, ref=8.5) == STATUS_INVALIDATED


# ---------------------------------------------------------------------------
# reclaim_refs (picks multi-ref, 2026-08-27)
# ---------------------------------------------------------------------------


def test_reclaim_refs_prior_low_fires():
    # reclaim_refs with only prior_low (=8, the stop); today_low 7.5 < 8, price 9 > 8.
    assert (
        compute_pick_status(10, 8, 9.0, 8.0, 9.1, 7.5, reclaim_refs=[("prior_low", 8)])
        == STATUS_RECLAIM
    )


def test_reclaim_refs_sma50_fires_when_prior_low_does_not():
    # prior_low 8 does NOT reclaim (today_low 8.5 >= 8, prior_low 8 not < 8), but the
    # 50MA at 8.7 does: price 9 > 8.7 and today_low 8.5 < 8.7.
    assert (
        compute_pick_status(10, 8, 9.0, 8.0, 9.1, 8.5,
                            reclaim_refs=[("prior_low", 8), ("sma50", 8.7)])
        == STATUS_RECLAIM
    )


def test_reclaim_refs_empty_list_never_reclaims():
    # A picks caller that opted in but has no usable level today: no reclaim, falls to
    # failed_breakout here (high 10.1 >= trigger 10).
    assert (
        compute_pick_status(10, 8, 9.8, 9.5, 10.1, 7.5, reclaim_refs=[])
        == STATUS_FAILED_BREAKOUT
    )


def test_reclaim_refs_takes_precedence_over_scalar_ref():
    # When both are passed, reclaim_refs wins: prior_low 8 fires, ignoring ref.
    assert (
        compute_pick_status(10, 8, 9.0, 8.0, 9.1, 7.5, ref=99, reclaim_refs=[("prior_low", 8)])
        == STATUS_RECLAIM
    )


def test_matched_reclaim_ref_returns_first_match_in_order():
    # both prior_low (8) and sma50 (8.5) qualify (today_low 7.5 < both); prior_low is
    # first in the ordered candidate list, so it is the attributed level.
    assert matched_reclaim_ref(9.0, 7.5, 8, [("prior_low", 8), ("sma50", 8.5)]) == ("prior_low", 8)


def test_matched_reclaim_ref_skips_non_matching_first_candidate():
    # prior_low 8 does not reclaim (today_low 8.5 >= 8); sma50 8.7 does -> attributed to sma50.
    assert matched_reclaim_ref(9.0, 8.5, 8, [("prior_low", 8), ("sma50", 8.7)]) == ("sma50", 8.7)


def test_matched_reclaim_ref_none_when_nothing_matches():
    assert matched_reclaim_ref(9.0, 8.5, 8, [("prior_low", 8)]) is None
    assert matched_reclaim_ref(9.0, 7.5, 8, []) is None


def test_compute_pick_status_reclaim_outranks_setting_up():
    # Without ref this would be setting_up (see regression test above); with a
    # qualifying ref it must promote to reclaim.
    assert compute_pick_status(10, 8, 9.0, 8.0, 9.1, 7.5, ref=8.5) == STATUS_RECLAIM


# ---------------------------------------------------------------------------
# compute_atr_from_lod
# ---------------------------------------------------------------------------


def test_atr_from_lod_basic():
    assert compute_atr_from_lod(10.5, 9.5, 2.0) == 0.5


def test_atr_from_lod_atr_zero():
    assert compute_atr_from_lod(10.5, 9.5, 0) is None


def test_atr_from_lod_atr_none():
    assert compute_atr_from_lod(10.5, 9.5, None) is None


def test_atr_from_lod_atr_nan():
    assert compute_atr_from_lod(10.5, 9.5, NAN) is None


def test_atr_from_lod_missing_price_or_low():
    assert compute_atr_from_lod(None, 9.5, 2.0) is None
    assert compute_atr_from_lod(10.5, None, 2.0) is None
    assert compute_atr_from_lod(NAN, 9.5, 2.0) is None
