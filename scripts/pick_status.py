"""
pick_status.py — WS3 morning status engine (ADR-013 Decision 3). PURE module.

No I/O, no clock reads, no file reads — `compute_pick_status` is session-agnostic by
contract: it takes reference levels + a single quote snapshot and returns a state string.
WS3 (10:05 ET) and WS3b (15:30 ET, issue #268) both call this verbatim against different
inputs; the function itself never knows which session invoked it.

Mirrors the pure/impure split used by `worker-cron/src/picksGate.js` (pure state-machine core,
impure caller does clock/file/network).

P2 (WS5 §8b watchlist build brief) added `STATUS_RECLAIM` + `compute_reclaim` — an optional
`ref` param on `compute_pick_status` lets a caller (collect_morning.py's watchlist union) ask
for the reclaim read against a structural level (system default: the ticker's 50-day MA). Picks
callers never pass `ref`, so `compute_pick_status`'s behavior for them is unchanged byte-for-byte.
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
# STATUS_RECLAIM (P2, WS5 §8b watchlist build brief §3/§4c/§4d/§5): a watch ticker's
# price is back above its reclaim `ref` after a dip below it — the mirror of
# failed_breakout (which pokes above the prior High and falls back; reclaim dips
# below a level and recovers). Only ever evaluated when a caller passes `ref` (picks
# callers never do, so this is zero-impact on the existing picks pipeline).
STATUS_RECLAIM = "reclaim"
STATUS_SETTING_UP = "setting_up"

# Ordered per ADR-013 Decision 3's precedence table (top-down, first match wins).
# Phase C's PWA actionability sort reuses this exact order — do not reorder without
# amending the ADR first (the mock's sort is: Triggered -> Gapped -> Failed ->
# Setting-up -> Invalidated -> No-quote, a DIFFERENT order than evaluation precedence;
# STATUS_PRECEDENCE below is the evaluation order, not the display order).
# STATUS_RECLAIM sits between failed_breakout and setting_up (watchlist build brief
# §4c: "above setting_up, below the breakout states") — it never outranks a genuine
# triggered/gapped_through/failed_breakout read of the same quote, but a name that
# would otherwise be a flat setting_up gets flagged reclaim if it dipped below its
# reclaim ref and recovered.
STATUS_PRECEDENCE = [
    STATUS_NO_QUOTE,
    STATUS_INVALIDATED,
    STATUS_GAPPED_THROUGH,
    STATUS_TRIGGERED,
    STATUS_FAILED_BREAKOUT,
    STATUS_RECLAIM,
    STATUS_SETTING_UP,
]

# States considered "actionable" — Phase C shows ATR-from-LoD only for these, and
# Decision 5's "I took it" button only appears for these states. STATUS_RECLAIM was
# added here in P2 (lead decision 2) so a reclaimed watch ticker gets atr_from_lod
# computed and the PWA's "I took it" affordance — picks callers never pass `ref`, so
# they never produce STATUS_RECLAIM and this addition is zero-impact for them.
ACTIONABLE_STATUSES = {STATUS_TRIGGERED, STATUS_GAPPED_THROUGH, STATUS_RECLAIM}


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


def compute_reclaim(price, today_low, prior_low, ref) -> bool:
    """price back above `ref` after today's OR yesterday's low dipped below it.

    Mirror of failed_breakout (which pokes above the prior High and falls back) —
    reclaim instead dips below a structural level and recovers. `ref` is the
    system-read reclaim level: P2's lead decision fixes this to the ticker's 50-day
    MA (`sma50`), independent of the watchlist user's chosen level_type, because
    `ref` must be a level that CAN differ from `prior_low` (the caller's `stop`) —
    if ref==prior_low, the `prior_low < ref` branch degenerates to always-false. The
    user's own reclaim_20ma/reclaim_50ma overlay is a separate client-side read
    (P3), not this system read.

    Returns False if any input is missing/NaN (never raises) — this mirrors
    `_is_missing`'s NaN/None handling used by `compute_pick_status` itself, so a
    watch ticker with no MA bar yet (or a bad quote) just never reads as reclaim.
    """
    if any(_is_missing(x) for x in (price, today_low, prior_low, ref)):
        return False
    return price > ref and (today_low < ref or prior_low < ref)


def compute_pick_status(trigger, stop, price, open_, high, low, ref=None) -> str:
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
      6. reclaim          — (P2, watchlist build brief §4c) only evaluated when the
                             caller passes `ref` (picks callers never do); price is
                             back above `ref` after today's or the prior low dipped
                             below it. Sits between failed_breakout and setting_up —
                             it never outranks a genuine breakout-family read of the
                             same quote, but promotes an otherwise-flat setting_up
                             name that reclaimed a level worth watching.
      7. setting_up       — everything else

    `ref` (optional, default None — reclaim never fires, byte-identical to the
    pre-P2 behavior): the reclaim level. `low`/`stop` (today's low / prior low) are
    already validated non-missing by the no_quote gate above by the time reclaim is
    evaluated; `compute_reclaim` itself still guards `ref` (and re-checks the others
    defensively) since `ref` is NOT part of the no_quote gate — see below.

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
    - `ref` is deliberately NOT part of the no_quote gate: a watch ticker with a
      valid quote but no MA bar yet (ref missing) must still get a real
      breakout/setting_up read against trigger/stop, just never STATUS_RECLAIM.
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
    if ref is not None and compute_reclaim(price, low, stop, ref):
        return STATUS_RECLAIM
    return STATUS_SETTING_UP


def compute_atr_from_lod(price, low, atr):
    """Return (price - low) / atr, or None if atr is missing/zero or an input is missing.

    Per ADR-013 Decision 3 this metric is only *meaningful* for actionable states
    (triggered / gapped_through) — an entry-quality gate (display thresholds,
    owner-set 2026-08-08: <=0.8 clean entry, >1.0 chasing, 0.8<x<=1.0 caution;
    live in docs/index.html + docs/CLAUDE.md). Kept pure and unconditional here;
    the caller decides when to compute/display it.
    """
    if _is_missing(price) or _is_missing(low) or _is_missing(atr):
        return None
    if atr == 0:
        return None
    return (price - low) / atr
