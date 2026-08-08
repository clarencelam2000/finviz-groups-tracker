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
    STATUS_NO_QUOTE,
    STATUS_INVALIDATED,
    STATUS_GAPPED_THROUGH,
    STATUS_TRIGGERED,
    STATUS_FAILED_BREAKOUT,
    STATUS_SETTING_UP,
    STATUS_PRECEDENCE,
    ACTIONABLE_STATUSES,
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
        STATUS_INVALIDATED,
        STATUS_GAPPED_THROUGH,
        STATUS_TRIGGERED,
        STATUS_FAILED_BREAKOUT,
        STATUS_SETTING_UP,
    ]


def test_actionable_statuses():
    assert ACTIONABLE_STATUSES == {STATUS_TRIGGERED, STATUS_GAPPED_THROUGH}


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
