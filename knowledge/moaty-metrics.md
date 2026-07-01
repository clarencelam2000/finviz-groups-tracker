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
| `momentum_score` | deltas.csv | 0–1; avg percentile rank across 6 perf timeframes (week → YTD) |
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
- **Source:** `compute_momentum` (`scripts/compute_deltas.py`).
- **Formula:** mean of `(n - rank_x) / (n - 1)` across week/month/quarter/
  half/year/ytd, where `n` = groups with non-null values. All-NaN columns
  excluded. Range 0.0 (worst) – 1.0 (best); single-row → NaN.
  Day excluded from scoring — too noisy (one session swings the score ~14%).
- **Signals:** broad strength across durable timeframes at once.
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

## rs_day / rs_week / rs_month / rs_quarter / rs_half / rs_year / rs_ytd
- **Source:** `compute_for_group` (`scripts/compute_deltas.py`). Raw RS spreads:
  `group_perf_X − SPY_perf_X` per matching timeframe. SPY data from
  `data/benchmark/snapshots.csv`. NaN when SPY data is absent for that date.
- **Signals:** positive = outperforming S&P 500 over that horizon; negative = lagging.
  Zero = matched the market. Combines with momentum ranks to distinguish leaders that
  beat peers AND beat the market from leaders that merely beat weaker peers.
- **User one-liner:** "How much this group beat or lagged the S&P 500 over each
  timeframe — positive means it outperformed the market."

## rs_score
- **Source:** `compute_rs_score` (`scripts/compute_deltas.py`). Fraction of 6
  timeframes (wk/mo/qtr/6mo/yr/ytd) where the group's RS spread (group perf −
  SPY perf) is positive. Day excluded from scoring — too noisy (stored and
  displayed separately for the "held up on a down day" read). Score 1.0 = beating
  SPY in every counted horizon; 0.0 = trailing in all. This is an absolute signal
  — a rising tide lifting all groups does not inflate the score (unlike
  `momentum_score`, which is a cross-sectional peer rank).
- **User one-liner:** "How broadly this group beats the S&P 500 across every
  timeframe at once, from 0 to 100%."

## rs_agreement
- **Source:** `compute_rs_agreement` (`scripts/compute_deltas.py`). Sign consistency
  of RS spreads across `rs_month`, `rs_quarter`, `rs_half`. Computed as |mean(sign)|
  where sign = +1 if rs > 0, −1 if rs < 0. Score 1.0 = all three medium-term horizons
  agree on direction (all positive or all negative); lower = mixed signals.
- **User one-liner:** "How much the 1-, 3-, and 6-month RS readings agree — high
  means consistently beating the market, not a one-timeframe fluke."

## rs_confirmed
- **Source:** `df_today["rs_confirmed"] = df_today["rs_score"] * df_today["rs_agreement"]`.
  Product of two 0–1 scores. High only when the group is *broadly* outperforming (high
  rs_score — many timeframes positive) AND the medium-term timeframes agree on direction
  (high rs_agreement). A group beating SPY in 5 of 6 timeframes but with mixed 1/3/6mo
  signals is discounted.
- **User one-liner:** "Market-beating strength filtered by consistency — high only
  when the group beats SPY across timeframes AND those timeframes agree."

## rs_slope
- **Source:** `compute_rs_slope` (`scripts/compute_deltas.py`). Least-squares slope
  of `rs_month` spread over the trailing `SLOPE_WINDOW = 10` sessions. Positive = the
  group is pulling further ahead of the market over time. Unlike `rank_trend_slope`,
  no negation is needed (higher RS = better). NaN if fewer than 2 sessions of SPY +
  group data overlap.
- **User one-liner:** "Whether this group's edge over the S&P 500 is widening (↑)
  or narrowing (↓) over the last 10 sessions."

## rs_accel
- **Source:** change in `rs_score` over `ACCEL_WINDOW = 10` sessions. Positive =
  more timeframes flipping to positive RS vs SPY (breadth of outperformance is growing).
  Earliest-warning RS rotation signal. NaN if fewer than 10 sessions of history exist.
- **User one-liner:** "How fast this group's advantage over the market is building (+)
  or fading (−) over the last 10 trading sessions."

## rs_regime_short_long
- **Source:** `compute_rs_regime` (`scripts/compute_deltas.py`). Short-horizon RS
  breadth (`rs_week`, `rs_month`: fraction > 0) minus long-horizon RS breadth
  (`rs_quarter`, `rs_half`, `rs_year`: fraction > 0). Positive = beating SPY recently
  but not historically (freshly emerging RS leader); negative = established RS leader
  (or a long-term laggard whose short-term RS has faded). Range [−1, 1].
  Configured via `RS_REGIME_SHORT` / `RS_REGIME_LONG` in `scripts/delta_config.py`.
- **User one-liner:** "Whether this group is a new market-beater (+) or a long-established one (−) — positive means relative strength is freshly emerging."

## beats_benchmark_X (beats_benchmark_day / _week / _month / … / _ytd)
- **Source:** `compute_beats_benchmark` (`scripts/compute_deltas.py`). Boolean per
  timeframe: 1 when `rs_X > 0` (the group beats SPY for that horizon), 0 otherwise.
  Blank when SPY data is absent. All 7 columns (including `beats_benchmark_day`) are
  stored; the PWA count excludes day — too noisy for a breadth read.
- **Signals:** the count of 1s across the 6 non-day timeframes ("beats N/6 tf") gives a
  quick breadth-of-outperformance read distinct from `rs_score`. 6/6 = outperforming
  across every tracked horizon. `rs_day` and `beats_benchmark_day` remain visible for
  the "held up on a down day" signal.
- **User one-liner:** "How many of the 6 standard timeframes (week → YTD) this group is currently outperforming the S&P 500 on — shown as "beats N/6 tf" on cards."

## rs_new_high
- **Source:** `compute_rs_new_high` (`scripts/compute_deltas.py`). 1 when today's
  `rs_month` (canonical RS line, `RS_SLOPE_COL`) equals or exceeds its maximum over
  the trailing `RS_NEW_HIGH_WINDOW = 20` trading sessions; 0 otherwise. NaN when fewer
  than 2 sessions of overlapping SPY + group data exist in the window.
- **Signals:** classic IBD-style RS-new-high flag. A group posting a new RS high while
  its absolute trend is still rising is among the strongest leadership signals.
- **User one-liner:** "The group's RS spread vs SPY is at its highest point in the last 20 sessions — a classic IBD-style leadership signal."

## rs_cross
- **Source:** `compute_rs_cross` (`scripts/compute_deltas.py`). 1 when `rs_month`
  crossed from ≤ 0 to > 0 within the last `RS_CROSS_WINDOW = 5` trading sessions
  (today must be > 0; at least one prior session in the window must be ≤ 0). 0 when
  today's RS is non-positive, or the group has been above 0 throughout the window.
  NaN when fewer than 2 sessions of overlapping data exist.
- **Signals:** discrete rotation trigger. A fresh cross above 0 means the group has
  only *just* begun beating the market — earlier-stage than a group posting RS new
  highs. The 5-session window keeps it tight so it doesn't fire on noise.
- **User one-liner:** "This group's RS spread just flipped from lagging to beating the market within the last 5 sessions — a rotation trigger."

## atr_ext_50 (ATR extension — picks pipeline, Phase 3a)
- **Source:** `compute_metrics_row` (`scripts/picks_metrics.py`). `(Price − sma50_price) / ATR`
  where `sma50_price = Price / (1 + SMA50/100)`. Finviz `SMA50` = "% above 50MA"; we reconstruct
  the MA price level. NaN when ATR or SMA50 is blank.
- **PWA thresholds:** `ATR_EXT_ACTIONABLE = 5.0` and `ATR_EXT_TRIM = 8.0` in `docs/index.html`.
  ≤5× = emerald (actionable); 5–8× = amber (caution); ≥8× = red with "trim" tag.
- **Signals:** the CEO "rubber-band stretch". Over-extension from the 50MA increases mean-reversion
  risk; entries above 5× carry a poor risk-reward profile even in strong groups.
- **User one-liner:** "How many ATR multiples above its 50-day MA the stock is — the rubber-band
  stretch: ≤5× is actionable, ≥8× is a trim candidate."

## risk_20ma_pct (risk to 20MA — picks pipeline, Phase 3a)
- **Source:** `compute_metrics_row` (`scripts/picks_metrics.py`). `(Price − sma20_price) / Price`
  where `sma20_price = Price / (1 + SMA20/100)`. Stored as a raw fraction (0.0115 = 1.15%).
  NaN when Price or SMA20 is blank.
- **PWA display:** rendered as a percentage. $-risk = fraction × price.
- **Signals:** the stop-risk to the near-term MA. Tight (<2%) = low per-share risk; >5% = requires
  wider position sizing to stay within standard risk limits.
- **User one-liner:** "What fraction of the current price you'd give back if stopped at the 20-day
  MA — shown as a % (e.g. 1.1% means a tight $1.82 stop on a $165 stock)."

## risk_50ma_pct (risk to 50MA — picks pipeline, Phase 3a)
- **Source:** `compute_metrics_row` (`scripts/picks_metrics.py`). `(Price − sma50_price) / Price`.
  Stored as a raw fraction. NaN when Price or SMA50 is blank.
- **PWA display:** rendered as a percentage. $-risk = fraction × price.
- **Signals:** wider-stop alternative. Use when a position needs more room to breathe through
  intraday volatility without getting shaken out.
- **User one-liner:** "What fraction of the current price you'd give back if stopped at the 50-day
  MA — the wider-stop alternative to the 20MA stop."

## range_atr (day range / ATR — picks pipeline, Phase 3a)
- **Source:** `compute_metrics_row` (`scripts/picks_metrics.py`). `(High − Low) / ATR`.
  NaN when ATR is blank.
- **Signals:** the C1 tightness proxy. <1× = a quiet constructive bar (stock is resting, not
  thrashing); >2× = a wide volatile day. Small values identify stocks that are still coiling inside
  a base rather than breaking out aggressively.
- **User one-liner:** "How much the stock moved today (High−Low) relative to its ATR — below 1×
  is a quiet constructive day; above 2× is a volatile day."

## stage2 (Stage-2 flag — picks pipeline, Phase 3a)
- **Source:** `compute_metrics_row` (`scripts/picks_metrics.py`).
  `1 if SMA50_pct > 0 AND SMA200_pct > SMA50_pct else 0`.
  Equivalence proof: `SMA200_pct > SMA50_pct` ↔ `sma50_price > sma200_price` ↔ 50MA > 200MA.
  NaN when SMA50 or SMA200 is blank.
- **Signals:** the William O'Neil / IBD Stage-2 base condition. The majority of big winning stocks
  spend their best run in Stage 2. Stocks below the 50MA or with an inverted MA stack are in
  Stage 1, 3, or 4 — outside the sweet spot.
- **User one-liner:** "Whether the stock is in Stage 2: price above the 50-day MA and the 50MA
  above the 200MA — the technical configuration where most big winning stocks reside."

## focus_score (Focus quality score — PWA Picks tab, Phase 3b)
- **Source:** PWA-computed (`docs/index.html` `computeFocusScores()`). Not stored in any CSV — derived
  cross-sectionally from today's Focus pool at render time.
- **Formula:** `score = base × (1 − extension_penalty_fraction)`.
  - `base = FOCUS_W_GROUP × group_n + FOCUS_W_TIGHT × tight_n + FOCUS_W_QUIET × quiet_n` (0.4/0.4/0.2 weights, sum to 1).
  - Each component uses the same inverted min–max ruler: `(max − x) / (max − min)` across Focus candidates.
  - Group strength = `grp_sum_mid_rank` (lower = stronger group). Stop tightness = nearest positive MA stop
    (`min(risk_20ma_pct, risk_50ma_pct)` keeping only positive values; 20MA dropped when price is below it).
    Quiet bar = `range_atr` (lower = tighter day).
  - Extension penalty ramps 0 → 0.5 from 3.5× to 5× (`ATR_EXT_PENALTY_START` → `ATR_EXT_ACTIONABLE`).
- **Range:** always [0, 1]; score × 100 displayed as integer in PWA.
- **Normalization edge cases:** all-equal component → 0.5; pool < 5 → rank-based percentile; n == 1 → 1.0.
- **Focus gate (hard gates before scoring):** `atr_ext_50 > 0` (price above 50MA) AND `atr_ext_50 ≤ 5.0`
  (not over-extended). No RSI gate; no Stage-2 gate (3b decision — revisit via PICKS-3B-FOCUSGATE).
- **User one-liner:** "A blended 0–100 quality score ranking Focus picks by group strength, how tight the nearest MA stop is, and how quiet today's bar was — then discounted for extension beyond 3.5×."

## price_basis (Price basis toggle — PWA Picks tab, Phase A)
- **Source:** PWA UI state only — not stored in any CSV. Per-card ephemeral state; resets to Last on collapse.
- **Two modes:**
  - **Last** (default): all stop-distance metrics use the closing price as the entry price.
  - **HoD** (High of Day): substitutes the prior session's High as the realistic breakout entry price.
    Breakout buyers don't fill at the close — they trigger above the prior day's high. HoD shows what
    the risk actually looks like from that realistic fill.
- **Which metrics re-base (stop-distance family):** `atr_ext_50`, `atr_ext_20`, `risk_20ma_pct`,
  `risk_50ma_pct`, $/sh risk per stop.
- **Which metrics stay fixed on close:** `range_atr`, ATR%, MA dollar levels (sma20_price, sma50_price).
  Bar properties describe the instrument, not the entry — they always come from the close-price session.
- **Label swap in HoD mode:** "trim" (position-management instruction) becomes "extended" (stretch
  description) when atrExt ≥ ATR_EXT_TRIM. Same red color ramp still applies.
- **Phase B (not yet built):** a global tab-level toggle that re-ranks the Focus list on HoD metrics.
  Phase A is display-only inside the expanded risk panel.
- **User one-liner:** "Switches the risk panel between two measurement bases: Last (closing price, the default) and HoD (High of Day — the realistic breakout entry price for the next session)."

## atr_ext_20 (ATR extension to 20MA — PWA Picks tab, Phase 3c)
- **Source:** PWA-computed (`deriveRiskMetrics` in `docs/index.html`). Not stored in `picks.csv` —
  the same client-side formula as `atr_ext_50`, just against the 20MA: `(Price − sma20_price) / ATR`
  where `sma20_price = Price / (1 + SMA20/100)`. NaN when ATR or SMA20 is blank.
- **Display:** a new row in the expanded risk panel — `ATR | 20MA stop (ATR) | 50MA stop (ATR)` —
  mirroring the HoD/20MA-stop/50MA-stop row above it, in ATR multiples instead of dollars/percent.
  Colored by sign (same sky/amber convention as the risk_20ma_pct / risk_50ma_pct cells above it),
  not the 3-tier emerald/amber/red extension bands (those stay on the separate "Ext (×50MA)" cell).
- **Signals:** replaces the old "Stop dist (ATR)" cell, which picked whichever of the 20MA/50MA
  distance was nearer without labeling which one — this shows both explicitly, always in the same
  position, so the reading never silently swaps meaning day to day.
- **User one-liner:** "How many ATR multiples above (or below) its 20-day MA the stock is — the same rubber-band read as the 50MA extension, but against the tighter near-term stop."

## avg_dollar_volume (Avg $ volume — PWA Picks tab, Phase 3c)
- **Source:** PWA-computed (`renderPickRow` in `docs/index.html`). `Price × Avg Volume`, where
  `Avg Volume` is Finviz's trailing average daily share volume (abbreviated string, e.g. `"9.24M"`,
  parsed by `_pVolRaw`). Not stored in `picks.csv` — display-only for now.
- **Signals:** a liquidity check independent of the raw share count. Two names can show the same
  Avg Volume in shares but very different $ liquidity at different price points; this normalizes
  for position-sizing purposes (can you actually fill the size you want without moving the tape).
- **Display-only today.** A follow-up PR is planned to add a liquidity floor (~$30M avg $ volume)
  and a gradual penalty into Focus scoring for thin names.
- **User one-liner:** "The average dollar amount traded per day — Last Price × Avg Volume — a liquidity check independent of the raw share count."

## earnings_proximity (Earnings proximity — PWA Picks tab, Phase 3c)
- **Source:** PWA-computed (`parseEarningsInfo` in `docs/index.html`) from Finviz's `Earnings`
  column: `"Mon DD"` optionally suffixed `/b` (before open) or `/a` (after close); `"-"` for none
  known. No year is given — inferred as the nearest occurrence (current year, rolled forward one
  year if that lands more than 180 days in the past, to handle Dec→Jan wraparound without
  misflagging an already-stale same-year date as upcoming).
- **PWA thresholds:** `EARNINGS_IMMINENT_DAYS = 3` (red) and `EARNINGS_CAUTION_DAYS = 10` (amber)
  in `docs/index.html`. Only upcoming dates (daysUntil ≥ 0) are colored — a past date is shown
  neutrally, since Finviz doesn't always refresh immediately after a name reports, so a stale date
  reflects missing data, not risk.
- **Signals:** earnings is a binary event — a good technical setup can gap through a stop on a bad
  print. Flagging proximity lets a trader choose to size down, wait, or skip a name reporting soon,
  independent of how clean the chart looks.
- **User one-liner:** "The stock's next known earnings date, color-flagged when it falls within the next 10 days — a binary event that adds risk regardless of the technical setup."

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
