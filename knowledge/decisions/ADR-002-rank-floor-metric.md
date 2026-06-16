# ADR-002: Rank Floor metric

**Date**: 2026-06-15
**Status**: Accepted

## Context

The Lookup tab needs a single, glanceable answer to "how reliably strong is this
group?" `momentum_score` captures broad strength but blends seven timeframes
including noisy day/week. We wanted a conservative "worst case over the medium
term" number that pairs with the existing Sustained Strength / `rank_agreement`
story.

## Decision

Introduce **Rank Floor** = the worst (numerically highest) rank across
`rank_month`, `rank_quarter`, `rank_half`. Interpreted as: "this group is never
worse than #N over 1, 3, and 6 months." Displayed as "Top {floor} across
1/3/6mo" (optional band "#{best}–#{floor}").

In Phase 1 it is computed client-side in `docs/index.html` from existing
`deltas.csv` columns — no pipeline or schema change.

## Alternatives considered

- **Include week/day** in the floor. Rejected: reintroduces the short-term noise
  we wanted to exclude, and breaks the coherence with `rank_agreement` and
  Sustained Strength, which use month/quarter/half.
- **Average rank instead of worst.** Rejected: "floor" is a stronger, more
  honest conviction framing than an average that can hide a bad timeframe.
- **Add the column to `compute_deltas.py` now.** Deferred: would trigger schema
  migration + tests for a value we can derive in the browser today.

## Consequences

- Month/quarter/half is now the canonical "sustained" timeframe set across
  Rank Floor, Sustained Strength, and `rank_agreement`.
- Backlog item: promote Rank Floor to a computed column in `compute_deltas.py`
  (with tests) and surface it in `dashboard/app.py` for product-wide
  consistency.
