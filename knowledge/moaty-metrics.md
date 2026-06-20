# Moaty Metrics — Derived Layer Inventory

> What makes this project different from reading Finviz directly: a daily
> derived layer that tracks *change* and *consistency* in rankings over time.
> Plain Finviz shows today's numbers; we show trajectory, conviction, and
> breadth. This file is the source of truth for those metrics — and for the
> in-app "Why this matters" glossary copy.
>
> **Kept in sync with the in-app Guide.** The `GUIDE` constant in
> `docs/index.html` copies the **User one-liner** lines below *verbatim*, and the
> Streamlit dashboard (`dashboard/app.py`) parses them from this file at runtime.
> If you edit a one-liner here, edit the matching `GUIDE` entry too (and vice-versa).
> `tests/test_guide_releases.py::test_guide_one_liners_match_metrics_md` enforces it.

All derived metrics live in `data/*/deltas.csv` and are produced by
`scripts/compute_deltas.py`. `perf_*` raw values live in `data/*/snapshots.csv`.

| Metric | Where | What it is |
|--------|-------|-----------|
| `momentum_score` | deltas.csv | 0–1; avg percentile rank across all 7 perf timeframes |
| `momentum_confirmed` | deltas.csv | momentum_score × rank_agreement; strength gated by consistency |
| `momentum_accel` | deltas.csv | change in momentum_score over 10 sessions; positive = building |
| `regime_short_long` | deltas.csv | short-horizon minus long-horizon percentile; positive = emerging |
| `rank_trend_slope` | deltas.csv | negated LS slope of rank_ytd over 10 sessions; positive = improving |
| `rank_*` | deltas.csv | rank 1 = best performer per timeframe (week/month/…/ytd) |
| `rank_*_delta_Nd` | deltas.csv | rank change vs N sessions ago (N = 5, 10, 20, 50); positive = improved |
| `perf_*_delta_Nd` | deltas.csv | raw perf change vs N sessions ago (acceleration signal) |
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

## rank_*_delta_Nd (N = 5, 10, 20, 50)
- **Sign convention:** `rank_prior - rank_today`; positive = improved (rose in
  ranking). NaN until enough history exists. N is in **trading sessions**, not
  calendar days (defined in `scripts/delta_config.py` `LOOKBACK_WINDOWS`).
- **User one-liner:** "How many spots this group moved up (+) or down (−) over
  the last N trading sessions."

## perf_*_delta_Nd
- Raw performance change vs N trading sessions ago — basis for an acceleration
  hint (▲▲ accelerating / ▼ fading). Surfaced on the Today tab's expanded card
  as the "vs 20d ago" context row (wk and YTD perf change over ~1 month).
- **User one-liner:** "How much this group's own return has changed versus N
  trading sessions ago — positive means it's performing better than it was."

## rank_agreement
- **Source:** `compute_rank_agreement` (L183). Converts month/quarter/half
  ranks to percentiles and measures how tightly the three cluster. 1.0 = all
  three timeframes agree on standing; 0.0 = max disagreement. NaN if n ≤ 1.
- **Signals:** a high score *alongside* a high momentum_score = trend confirmed
  across timeframes, not a recent flash.
- **User one-liner:** "How much the 1-, 3-, and 6-month rankings agree — high
  means a consistent trend, not a one-week pop."

## momentum_confirmed
- **Source:** `df_today["momentum_confirmed"] = df_today["momentum_score"] * df_today["rank_agreement"]`
  (`scripts/compute_deltas.py`). Product of two 0–1 scores; range 0–1.
- **Signals:** high only when the group is *both* broadly strong (high momentum_score)
  *and* that strength is consistent across timeframes (high rank_agreement). A strong
  momentum_score with low rank_agreement (e.g. one outlier timeframe dragging up the
  average) will produce a low confirmed score.
- **User one-liner:** "Momentum filtered by consistency — high only when the group is
  strong across timeframes AND those timeframes agree."

## regime_short_long
- **Source:** `compute_regime()` (`scripts/compute_deltas.py` L249). Short-horizon
  percentile mean (`perf_week`, `perf_month`) minus long-horizon percentile mean
  (`perf_quarter`, `perf_half`, `perf_year`). Range roughly [−1, 1]. NaN if either
  bucket is unavailable.
- **PWA thresholds:** `REGIME_THRESHOLD = 0.15` in `docs/index.html`. Values above
  threshold → Emerging bucket (emerald); within ±threshold → Established; below
  negative threshold → Fading (red).
- **Signals:** positive = recently outperforming relative to its own long-term average
  (an emerging or re-accelerating leader); negative = recently underperforming relative
  to its own trend (a fading leader).
- **User one-liner:** "Whether this group is gaining (+) or losing (−) momentum
  relative to its longer-term trend — positive means recently accelerating."

## momentum_accel
- **Source:** `df_today["momentum_accel"] = momentum_score_today - momentum_score_prior`
  where prior is `ACCEL_WINDOW = 10` trading sessions ago (`scripts/compute_deltas.py`
  L379–391; `ACCEL_WINDOW` in `scripts/delta_config.py`). NaN if fewer than 10
  sessions of history exist.
- **PWA thresholds:** `ACCEL_STRONG = 0.08` and `ACCEL_SLIGHT = 0.02` in
  `docs/index.html`. |accel| > ACCEL_STRONG → double arrow (▲▲/▼▼); > ACCEL_SLIGHT →
  single arrow (▲/▼); within ±ACCEL_SLIGHT → no badge.
- **Signals:** positive = momentum is building over the last 10 sessions; negative =
  momentum is fading. Captures *rate of change*, not absolute level.
- **User one-liner:** "How fast this group's momentum is building (+) or fading (−)
  over the last 10 trading sessions."

## rank_trend_slope
- **Source:** `compute_rank_trend_slope()` (`scripts/compute_deltas.py` L266). Negated
  least-squares slope of `rank_ytd` over the trailing `SLOPE_WINDOW = 10` sessions.
  Negated because rank 1 = best: a falling rank number is improvement, so raw slope is
  negative when improving. NaN if fewer than 2 sessions of history exist.
- **PWA thresholds:** `SLOPE_STRONG = 0.05` and `SLOPE_SLIGHT = 0.01` in
  `docs/index.html`. |slope| > SLOPE_STRONG → double arrow (↑↑/↓↓); > SLOPE_SLIGHT →
  single arrow (↑/↓); within ±SLOPE_SLIGHT → `~` (flat).
- **Signals:** positive = rank_ytd has been trending upward (improving) consistently
  over 10 sessions; negative = trending downward. More reliable than a single-window
  delta because it fits a line to the full trailing window.
- **User one-liner:** "Whether this group's YTD ranking is on a consistent upward (↑)
  or downward (↓) trajectory over the last 10 sessions."

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

## Rotation Phase (AI — sectors only)
- **Definition:** an AI-generated read of where the broad market sits in its
  cycle, labeled Early Cycle, Mid Cycle, Late Cycle, or Defensive, with a short
  reasoning line. Generated nightly from the sector signals; shown on the AI tab
  and summarized in the Phase History strip.
- **User one-liner:** "An AI read of where the market is in its cycle — Early,
  Mid, or Late Cycle, or Defensive — based on which sectors are leading."

## AI Daily Note (AI)
- **Definition:** the freeform plain-English briefing the AI writes each day, one
  per group (sectors and industries). Built from the computed signals — sustained
  strength, notable movers, momentum leaders and laggards, and divergences.
- **User one-liner:** "A plain-English summary the AI writes each day for sectors
  and industries, highlighting strength, movers, and divergences."
