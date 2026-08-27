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

WS-POSITIONS-STATUS (2026-08-25, planning/watchlist-status-honesty-and-seeding.md) added
`STATUS_AWAITING_FIRST_READ` + an optional `has_history` param, same pattern as `ref`/
`STATUS_RECLAIM`: a brand-new watch ticker's first `collect_morning.py` run (10:05 ET) always
executes before that ticker's first `ticker_quotes` bar can exist (17:30 ET held feed), so the
missing-inputs gate below used to tag it `STATUS_NO_QUOTE` — copy "Morning feed missed this
ticker" — which is false; nothing was missed, the ticker has simply never had a bar. Picks
callers never pass `has_history`, so behavior for them is unchanged byte-for-byte.
"""

import math


# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------

STATUS_NO_QUOTE = "no_quote"
# STATUS_AWAITING_FIRST_READ (WS-POSITIONS-STATUS, 2026-08-25): the missing-inputs case, but for a
# watch ticker that has NEVER had a ticker_quotes bar (has_history=False) rather than one that had
# a quote request today and it came back empty. Mutually exclusive with STATUS_NO_QUOTE per
# evaluation — only ever the "no usable inputs" branch relabeled, never a fires-alongside case.
# Picks callers never pass has_history, so they only ever get STATUS_NO_QUOTE, unchanged.
STATUS_AWAITING_FIRST_READ = "awaiting_first_read"
STATUS_INVALIDATED = "invalidated"
STATUS_GAPPED_THROUGH = "gapped_through"
STATUS_TRIGGERED = "triggered"
STATUS_FAILED_BREAKOUT = "failed_breakout"
# STATUS_RECLAIM (P2, WS5 §8b watchlist build brief §3/§4c/§4d/§5): price is back above
# a reclaim reference level after a dip below it — the mirror of failed_breakout (which
# pokes above the prior High and falls back; reclaim dips below a level and recovers).
# Evaluated whenever a caller supplies a reclaim reference: watchlist callers pass a
# single `ref` (the 50-day MA); picks callers pass `reclaim_refs` (undercut-and-reclaim
# of EITHER the prior swing low OR the derived 50MA — owner decision 2026-08-27). A
# caller supplying neither never emits reclaim.
STATUS_RECLAIM = "reclaim"
STATUS_SETTING_UP = "setting_up"

# Ordered per ADR-013 Decision 3's precedence table (top-down, first match wins).
# Phase C's PWA actionability sort reuses this exact order — do not reorder without
# amending the ADR first (the mock's sort is: Triggered -> Gapped -> Failed ->
# Setting-up -> Invalidated -> No-quote, a DIFFERENT order than evaluation precedence;
# STATUS_PRECEDENCE below is the evaluation order, not the display order).
# STATUS_RECLAIM sits ABOVE failed_breakout and below the genuine-breakout states
# (owner decision 2026-08-27, applied uniformly to picks AND watchlist): a bar that
# both pokes its prior High (failed_breakout) AND undercuts-and-reclaims a reference
# level reads as reclaim — the recovered-off-the-lows signal wins over the
# rejected-at-highs one. It still never outranks a real triggered/gapped_through read
# (a full breakout dominates) or invalidated (below the invalidation floor = dead).
# Only ever fires when a caller supplies a reclaim ref (picks via `reclaim_refs`, watch
# via `ref`); a caller passing neither is byte-identical to a world without reclaim.
STATUS_PRECEDENCE = [
    STATUS_NO_QUOTE,
    STATUS_AWAITING_FIRST_READ,
    STATUS_INVALIDATED,
    STATUS_GAPPED_THROUGH,
    STATUS_TRIGGERED,
    STATUS_RECLAIM,
    STATUS_FAILED_BREAKOUT,
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


def matched_reclaim_ref(price, today_low, prior_low, candidates):
    """First `(label, value)` in `candidates` whose value yields a reclaim, else None.

    `candidates` is an ordered iterable of `(label, value)` pairs; iteration order IS
    the within-reclaim precedence (picks pass `prior_low` before `sma50`, so a name that
    reclaims both is attributed to the prior swing low). Each value is tested with
    `compute_reclaim` (same NaN/None guard), so a missing/derivable-as-None candidate
    just never matches. Returns None when nothing reclaims.

    Used in two places that must not diverge: `compute_pick_status` calls it to decide
    the reclaim state, and `collect_morning.build_status_rows` calls it again on a
    reclaim row to record WHICH level fired (for the PWA's "Reclaimed <level>" copy).
    """
    for label, value in candidates:
        if compute_reclaim(price, today_low, prior_low, value):
            return (label, value)
    return None


def compute_pick_status(trigger, stop, price, open_, high, low, ref=None, has_history=None,
                        reclaim_refs=None) -> str:
    """Evaluate a single ticker's morning status against ADR-013 Decision 3.

    Inputs: `trigger` (prior High), `stop` (prior Low), and today's quote fields
    `price`, `open_`, `high`, `low`. Evaluated TOP-DOWN, first match wins — the
    predicates deliberately overlap (a triggered name can also satisfy
    gapped_through or failed_breakout), so precedence is part of the spec:

      1. no_quote / awaiting_first_read — any of trigger/stop/price/open_/high/low
                             is None/NaN. Reported as awaiting_first_read when the
                             caller passes has_history=False (WS-POSITIONS-STATUS,
                             2026-08-25) — a watch ticker that has never had a bar,
                             as opposed to one Finviz genuinely failed to quote
                             today. Picks callers never pass has_history, so this
                             is always no_quote for them, unchanged.
      2. invalidated      — price <= stop
      3. gapped_through   — open_ > trigger
      4. triggered        — price >= trigger
      5. reclaim          — price is back above a reclaim reference after today's or the
                             prior low dipped below it. Evaluated whenever the caller
                             supplies a reference: `reclaim_refs` (picks — an ordered
                             list of (label, value), reclaim fires if ANY value matches)
                             takes precedence over the legacy scalar `ref` (watch — the
                             50MA). Sits ABOVE failed_breakout (owner decision
                             2026-08-27, uniform for picks + watch): a bar that both
                             pokes its High and reclaims a level reads as reclaim. Still
                             below triggered/gapped_through (a full breakout dominates)
                             and invalidated (below the floor = dead).
      6. failed_breakout  — high >= trigger  (price < trigger, open_ <= trigger, no
                             qualifying reclaim, by falling through 3/4/5)
      7. setting_up       — everything else

    `ref` (optional scalar, default None) / `reclaim_refs` (optional ordered
    [(label, value), ...]): the reclaim reference(s). With neither supplied, reclaim
    never fires — byte-identical to the pre-reclaim behavior for that caller.
    `low`/`stop` (today's low / prior low) are already validated non-missing by the
    no_quote gate above by the time reclaim is evaluated; `compute_reclaim` still
    guards each ref value (and re-checks the others defensively) since the refs are NOT
    part of the no_quote gate.

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
        return STATUS_AWAITING_FIRST_READ if has_history is False else STATUS_NO_QUOTE
    if price <= stop:
        return STATUS_INVALIDATED
    if open_ > trigger:
        return STATUS_GAPPED_THROUGH
    if price >= trigger:
        return STATUS_TRIGGERED
    # reclaim now sits ABOVE failed_breakout (owner decision 2026-08-27): a bar that both
    # pokes its prior High and reclaims a reference level reads as reclaim, uniformly for
    # picks and watchlist. `reclaim_refs` (picks: ordered [(label, value), ...]) takes
    # precedence over the legacy scalar `ref` (watch: the 50MA); a caller passing neither
    # yields no candidates and can never reclaim (byte-identical to no-reclaim for it).
    candidates = _reclaim_candidates(ref, reclaim_refs)
    if candidates and matched_reclaim_ref(price, low, stop, candidates):
        return STATUS_RECLAIM
    if high >= trigger:
        return STATUS_FAILED_BREAKOUT
    return STATUS_SETTING_UP


def _reclaim_candidates(ref, reclaim_refs):
    """Normalize the two reclaim-ref forms into one ordered `[(label, value), ...]`.

    `reclaim_refs` (picks) wins when supplied — even an empty list means "this caller
    opted in but has no usable level today", which correctly yields no reclaim. Falls
    back to the legacy scalar `ref` (watchlist's 50MA) as a single `("sma50", ref)`
    candidate, or an empty list when both are absent (every pre-2026-08-27 caller).
    """
    if reclaim_refs is not None:
        return list(reclaim_refs)
    if ref is not None:
        return [("sma50", ref)]
    return []


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
