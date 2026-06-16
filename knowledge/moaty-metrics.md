# Moaty Metrics — Derived Layer Inventory

> What makes this project different from reading Finviz directly: a daily
> derived layer that tracks *change* and *consistency* in rankings over time.
> Plain Finviz shows today's numbers; we show trajectory, conviction, and
> breadth. This file is the source of truth for those metrics — and for the
> in-app "Why this matters" glossary copy.

All derived metrics live in `data/*/deltas.csv` and are produced by
`scripts/compute_deltas.py`. `perf_*` raw values live in `data/*/snapshots.csv`.

| Metric | Where | What it is |
|--------|-------|-----------|
| `momentum_score` | deltas.csv | 0–1; avg percentile rank across all 7 perf timeframes |
| `rank_*` | deltas.csv | rank 1 = best performer per timeframe (week/month/…/ytd) |
| `rank_*_delta_Nd` | deltas.csv | rank change vs N days ago; positive = improved |
| `perf_*_delta_Nd` | deltas.csv | raw perf change vs N days ago (acceleration signal) |
| `rank_agreement` | deltas.csv | 0–1; how tightly month/quarter/half ranks cluster |
| Sustained Strength | derived view | top-N in rank_month AND rank_quarter AND rank_half |
| All Green / Breadth | derived view | perf positive across the checked timeframes |
| **Rank Floor** | client-side (Phase 1) | worst rank across month/quarter/half |

---

## momentum_score
- **Source:** `compute_momentum` (`scripts/compute_deltas.py` L163).
- **Formula:** mean of `(n - rank_x) / (n - 1)` across day/week/month/quarter/
  half/year/ytd, where `n` = groups with non-null values. All-NaN columns
  excluded. Range 0.0 (worst) – 1.0 (best); single-row → NaN.
- **Signals:** broad strength across *every* timeframe at once.
- **User one-liner:** "How strong this group is across every timeframe at once,
  from 0 to 100%."

## rank_* (rank_week, rank_month, rank_quarter, rank_half, rank_year, rank_ytd)
- **Source:** `compute_ranks` (L143); `rank(ascending=False, method='min',
  na_option='bottom')`. Rank 1 = highest % gain. Derived, never scraped.
- **User one-liner:** "Where this group places among all groups for a given
  timeframe — #1 is the best performer."

## rank_*_delta_Nd (N = 7, 14, 30)
- **Sign convention:** `rank_prior - rank_today`; positive = improved (rose in
  ranking). NaN until enough history exists.
- **User one-liner:** "How many spots this group moved up (+) or down (−) over
  the last N days."

## perf_*_delta_Nd
- Raw performance change vs N days ago — basis for an acceleration hint
  (▲▲ accelerating / ▼ fading). Currently unused in the Lookup tab (backlog).

## rank_agreement
- **Source:** `compute_rank_agreement` (L183). Converts month/quarter/half
  ranks to percentiles and measures how tightly the three cluster. 1.0 = all
  three timeframes agree on standing; 0.0 = max disagreement. NaN if n ≤ 1.
- **Signals:** a high score *alongside* a high momentum_score = trend confirmed
  across timeframes, not a recent flash.
- **User one-liner:** "How much the 1-, 3-, and 6-month rankings agree — high
  means a consistent trend, not a one-week pop."

## Sustained Strength
- **Source:** dashboard view (`dashboard/app.py` L552). A group is
  "Consistently Strong" when it is top-N in `rank_month` AND `rank_quarter` AND
  `rank_half` simultaneously (weak = bottom-N in all three).
- **User one-liner:** "Strong across 1, 3, and 6 months at the same time — not
  just a recent flash."

## All Green / Breadth
- **Source:** dashboard view (`dashboard/app.py` L628). A group is "all green"
  when perf is positive across every checked timeframe. The dashboard currently
  checks `perf_week, perf_month, perf_quarter, perf_half, perf_ytd`.
- **PWA divergence (Phase 1):** the Lookup tab's green/All-Green signal gates on
  **month/quarter/half/ytd only** — week and day dots render but do not gate the
  green verdict (less intraday noise). See
  `knowledge/decisions/ADR-003-breadth-excludes-week.md`. This divergence is
  intentional and flagged for possible reconciliation.
- **User one-liner:** "Whether the group is positive across the major
  timeframes — all green means everything's trending up."

## Rank Floor (new — Phase 1, client-side)
- **Definition:** worst (numerically highest) rank across `rank_month`,
  `rank_quarter`, `rank_half`. "This group is never worse than #N over 1/3/6
  months."
- **Display:** "Top {floor} across 1/3/6mo"; optional band "#{best}–#{floor}".
- **Why month/quarter/half:** matches `rank_agreement` / Sustained Strength
  inputs for one coherent "sustained" story; avoids weekly/daily noise.
- **Status:** computed client-side in `docs/index.html` from existing columns;
  candidate for promotion to a `compute_deltas.py` column later. See
  `knowledge/decisions/ADR-002-rank-floor-metric.md`.
- **User one-liner:** "The lowest this group's ranking has dropped to across 1,
  3, and 6 months — its floor."
