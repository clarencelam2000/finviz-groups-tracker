"""
pick_status.py — WS3 morning status engine (ADR-013 Decision 3). PURE module.

No I/O, no clock reads, no file reads — `compute_pick_status` is session-agnostic by
contract: it takes reference levels + a single quote snapshot and returns a state string.
WS3 (09:45 ET) and WS3b (15:30 ET, issue #268) both call this verbatim against different
inputs; the function itself never knows which session invoked it.

Mirrors the pure/impure split used by `worker-cron/src/picksGate.js` (pure state-machine core,
impure caller does clock/file/network).
"""

import math


# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------

STATUS_NO_QUOTE = "no_quote"
STATUS_INVALIDATED = "invalidated"
STATUS_GAPPED_THROUGH = "gapped_through"
STATUS_TRIGGERED = "triggered"
STATUS_FAILED_BREAKOUT = "failed_breakout"
STATUS_SETTING_UP = "setting_up"

# Ordered per ADR-013 Decision 3's precedence table (top-down, first match wins).
# Phase C's PWA actionability sort reuses this exact order — do not reorder without
# amending the ADR first (the mock's sort is: Triggered -> Gapped -> Failed ->
# Setting-up -> Invalidated -> No-quote, a DIFFERENT order than evaluation precedence;
# STATUS_PRECEDENCE below is the evaluation order, not the display order).
STATUS_PRECEDENCE = [
    STATUS_NO_QUOTE,
    STATUS_INVALIDATED,
    STATUS_GAPPED_THROUGH,
    STATUS_TRIGGERED,
    STATUS_FAILED_BREAKOUT,
    STATUS_SETTING_UP,
]

# States considered "actionable" — Phase C shows ATR-from-LoD only for these, and
# Decision 5's "I took it" button only appears for these two states.
ACTIONABLE_STATUSES = {STATUS_TRIGGERED, STATUS_GAPPED_THROUGH}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_missing(x) -> bool:
    """True if x is None or NaN (float). Non-float values are never 'missing'."""
    if x is None:
        return True
    if isinstance(x, float) and math.isnan(x):
        return True
    return False


def compute_pick_status(trigger, stop, price, open_, high, low) -> str:
    """Evaluate a single ticker's morning status against ADR-013 Decision 3.

    Inputs: `trigger` (prior High), `stop` (prior Low), and today's quote fields
    `price`, `open_`, `high`, `low`. Evaluated TOP-DOWN, first match wins — the
    predicates deliberately overlap (a triggered name can also satisfy
    gapped_through or failed_breakout), so precedence is part of the spec:

      1. no_quote        — any of trigger/stop/price/open_/high/low is None/NaN
      2. invalidated      — price <= stop
      3. gapped_through   — open_ > trigger
      4. triggered        — price >= trigger
      5. failed_breakout  — high >= trigger  (price < trigger, open_ <= trigger, by
                             falling through 3 and 4)
      6. setting_up       — everything else

    Notes (see ADR-013 Decision 3 for full rationale — do not "improve" these):
    - invalidated outranks triggered/gapped_through: a name below its planned stop
      is dead even if it tagged the trigger earlier in the session. The whipsaw
      distinction (recovered after a stop-touch) is explicitly deferred to a future
      version; v1's conservative read is to show Invalidated.
    - invalidated checks `price` (current), not `low` (intraday low) — checking
      `low <= stop` would catch the whipsaw case, which is exactly what's deferred.
    - gapped_through outranks triggered: open_ > trigger means there was no entry
      near the trigger level at all (chase-risk), even though price >= trigger also
      holds. Reaching "triggered" therefore implies open_ <= trigger <= price — a
      genuine intraday break of the level, not a pre-existing gap.
    """
    if any(_is_missing(x) for x in (trigger, stop, price, open_, high, low)):
        return STATUS_NO_QUOTE
    if price <= stop:
        return STATUS_INVALIDATED
    if open_ > trigger:
        return STATUS_GAPPED_THROUGH
    if price >= trigger:
        return STATUS_TRIGGERED
    if high >= trigger:
        return STATUS_FAILED_BREAKOUT
    return STATUS_SETTING_UP


def compute_atr_from_lod(price, low, atr):
    """Return (price - low) / atr, or None if atr is missing/zero or an input is missing.

    Per ADR-013 Decision 3 this metric is only *meaningful* for actionable states
    (triggered / gapped_through) — an entry-quality gate (display thresholds:
    <=1.0 ok-to-act, >1.5 chase-risk, live in docs/index.html + docs/CLAUDE.md).
    Kept pure and unconditional here; the caller decides when to compute/display it.
    """
    if _is_missing(price) or _is_missing(low) or _is_missing(atr):
        return None
    if atr == 0:
        return None
    return (price - low) / atr
