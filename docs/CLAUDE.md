# docs/ — PWA (GitHub Pages)

> Loads only when working in `docs/`. Root `CLAUDE.md` has the project-wide picture; this
> file holds detail specific to `index.html` / `sw.js` that doesn't need to load every session.

`docs/` is named per GitHub Pages convention: "Deploy from branch → /docs" only supports `/`
or `/docs` as source. Do not rename it without switching to GitHub Actions deployment first.

## PWA display thresholds (near top of `<script>` in `index.html`)

These constants gate visual indicators in the PWA. Edit them directly in `index.html` — they
are not derived from the CSV pipeline. Any change must also update `README.md` § Configurable
parameters and, if it's a scoring/display constant tracked by the anti-drift guard, bump
`data/picks/display_methodology.json` (see `scripts/CLAUDE.md` § Picks pipeline).

| Constant | Default | Controls |
|----------|---------|---------|
| `REGIME_THRESHOLD` | `0.15` | Boundary between Emerging / Established / Fading buckets in Rotation view. Also the card color cutoff — must stay consistent (uses `REGIME_THRESHOLD` in both places). |
| `ACCEL_STRONG` | `0.08` | `momentum_accel` threshold for double-arrow (▲▲/▼▼) badge on Momentum cards. |
| `ACCEL_SLIGHT` | `0.02` | `momentum_accel` threshold for single-arrow (▲/▼) badge. Within ±`ACCEL_SLIGHT` = neutral `~` glyph (steady); NaN/insufficient history = dimmed `—`. |
| `SLOPE_STRONG` | `0.05` | `rank_trend_slope` threshold for double-arrow (↑↑/↓↓) glyph on Today cards. |
| `SLOPE_SLIGHT` | `0.01` | `rank_trend_slope` threshold for single-arrow (↑/↓) glyph. Within ±`SLOPE_SLIGHT` = `~`. |
| `RS_STRONG` | `2.0` | RS spread (pp vs S&P) threshold for deep-color badge in vs Market tab and Today cards. |
| `RS_SLIGHT` | `0.5` | RS spread threshold for mild-color badge. Within ±`RS_SLIGHT` = neutral chip. |
| `BREADTH_GATE_TFS` | `{month, quarter, half, ytd}` | Lookup card "Raw Perf" dot row (`breadthStrip()`): which of the 6 displayed timeframes gate the "All green" verdict. Week and year render as dots but don't gate. Also shared as `DOT_ROW_TFS`'s tf/label/order source for the new `rsBreadthStrip()` vs-S&P dot row, so both rows line up dot-for-dot. |
| `RS_TF_LABEL` | see code | `rsChip(v, tf)`'s timeframe qualifier (e.g. "(1mo)" in "+9.8pp vs S&P (1mo)"). Derived from whichever `tf` the caller passes — not hardcoded — so a future caller passing `rs_week` gets "(1wk)" automatically instead of a silently wrong label. |
| `SIGNAL_WEIGHTS` | `{momentumConfirmed:0.30, rsConfirmed:0.30, rankDeltaShort:0.15, regime:0.15, breadth:0.10}` | Lookup tab SIGNAL card (`groupSignal()`): per-factor weight in the 0–1 composite. A factor with no source data is excluded and the remaining weights renormalized (same convention as `momentum_score`'s NaN handling), so missing data shrinks the average instead of injecting a fake neutral value. |
| `SIGNAL_FAVORABLE` / `SIGNAL_CAUTION` | `0.65` / `0.35` | Lookup tab SIGNAL card verdict thresholds on the `groupSignal()` composite score. `>= SIGNAL_FAVORABLE` → FAVORABLE, `<= SIGNAL_CAUTION` → CAUTION, between → MIXED, no data on either side → NO SIGNAL. |
| `BREADTH_TOP_HALF_FRACTION` | `0.5` | Sector-breadth "top half" cutoff, shared by `computeSectorBreadth()` (Strength-tab breadth table, week/month/quarter/half toggle) and `computeSectorTopHalfCounts()` (Today-tab sector card breadth bar + expand-in-place drill-down, YTD only). One threshold, two render targets — added when PR #178 (Today-tab breadth bar) was reconciled with the independently-shipped Strength-tab table (`122a4d1`). |
| `MIN_MARKET_CAP_B` | `5` | Picks tab base display filter (C6); rows below this market cap ($B) are hidden. |
| `ATR_EXT_ACTIONABLE` | `4.0` | ATR-extension emerald band cap; also the Focus hard-DQ line (Phase 3b). |
| `ATR_EXT_TRIM` | `8.0` | ATR-extension red band start; flags a held position as a trim-10% candidate. |
| `ATR_FROM_LOD_CLEAN` / `ATR_FROM_LOD_CHASE` | `0.8` / `1.0` | Morning tab (WS3, ADR-013) entry-quality bands on `atr_from_lod` = (price − session low) / ATR, shown on every Morning/Watch card status (owner decision 2026-09-02 dropped the original actionable-only gate — see below). `<= 0.8` clean entry (emerald "ok to act"), `> 1.0` chasing (red), between = caution (amber), same bands regardless of status. Owner-set 2026-08-08. |
| `LAUNCH_NEAR_HIGH_PCT` | `8` | Launch-ready chip (Picks tab, Phase 1, `computeLaunchReady()`): `ohMag` (% below 52-week high) `<=` this = "near the high" (little overhead supply). Display-only, no scoring effect. |
| `POWER_OF_3_ATR_MULT` | `2.0` | "Pre-Power of 3" MA-bunching chip (B-5, issue #379) in the Volatility & setup section (`volSetupSectionHtml`): fires when price, the 20MA and the 50MA all fit inside one band this many ATRs wide. Owner-set band (a fact, doc §4.0 — not an invented cutoff); larger = looser. **Computed client-side from the raw Price/ATR/SMA20/SMA50 columns — deliberately NOT a stored CSV column** (a config-dependent pure single-row value belongs at render time — see `.claude/rules/data-pipeline.md` § Schema changes to ground-truth CSVs). Real-time on Morning/Watch because those four are in `_SETUP_FRESH_COLS`. Not tracked by `display_methodology.json` (a display fact, not part of the All/Focus scoring). |
| `VOLATILITY_FLOOR_PCT` | `1.0` | Hard exclusion gate (2026-09-02, owner call after the APGE false-"coiled" case, `passesVolatilityFloor()`): a row is hidden from Picks (`passesPicksBaseFilter`), Focus (`isFocusEligible`), and the Morning picks-confirmation read (`renderMorning`) when its `Volatility W` % OR ATR/Price % is below this floor — provably near-dead (buyout-frozen, halted, or a perpetual preferred) rather than a genuine tight coil. NaN passes through (unknown ≠ low). The user's own **watchlist** and a direct **Lookup** ticker search are exempt (explicit intent) — Lookup instead shows an amber "Low volatility" chip (`tickerContextHtml`). Validated 2026-09-02 against the live picks pool: both `Volatility W` and `ATR/Price` have a real gap between ~0.5% and ~1.2% (the next names up are legitimate low-vol mega-caps starting at 1.2%+), so `1.0` sits in that gap rather than being an eyeballed cutoff. **Computed client-side from the already-scraped `Volatility W`/`ATR`/`Price` columns — not a stored CSV column** (a row-visibility decision, not a schema change; see `.claude/rules/data-pipeline.md` § Schema changes to ground-truth CSVs). Tracked by `display_methodology.json` under `base_filter`/`focus_dq` (`v6` entry) — the Focus *scoring formula* itself is unchanged, only the candidate pool. |
| `LAUNCH_CALM_EXT_MAX` | `3` | Launch-ready chip: `atr_ext_50` `<=` this (and `> 0`) alongside near-high = `Coiled`; `>` this = `Extended`. |
| `LAUNCH_OVERHEAD_PCT` | `20` | Launch-ready chip: `ohMag >` this = `Overhead` (deep below high, heavy overhead supply). |
| `ATR_EXT_PENALTY_START` | `2.5` | Focus-score extension penalty ramp start; 0 penalty below this, ramps to `PENALTY_MAX` at `ATR_EXT_ACTIONABLE`. |
| `PENALTY_MAX` | `0.5` | Max Focus extension-discount fraction (50% haircut at 4×). `score = base × (1 − penalty_fraction)`, always ∈ [0, 1]. |
| `FOCUS_W_GROUP` | `0.2` | Focus score weight for group sustained-strength component (`grp_sum_mid_rank`). Lowered from `0.4` on 2026-07-16 (`display_methodology.json` v3); freed weight moved to `FOCUS_W_QUIET`. |
| `FOCUS_W_TIGHT` | `0.4` | Focus score weight for nearest-MA stop tightness component. |
| `FOCUS_W_QUIET` | `0.4` | Focus score weight for quiet-bar component (`range_atr`). Raised from `0.2` on 2026-07-16 (`display_methodology.json` v3). |
| `FOCUS_MIN_POOL` | `5` | Min Focus candidates before falling back from min–max to rank-based normalization. |
| `BUTTON_V` | `'311'` | Lookup deep-link button: Finviz screener view number (tight Stage-2 layout). Mirror of `data/picks/screener_config.json` `button.v`. Anti-drift guard in `tests/test_picks_button_config.py`. |
| `BUTTON_BASE_FILTERS` | `['cap_midover','ta_sma20_sa50','ta_sma50_pa']` | Lookup deep-link button: base Finviz filters prepended before `ind_<slug>` / `sec_<slug>` token. Mirror of `screener_config.json` `button.base_filters`. |
| `BUTTON_SORT` | `'sma50'` | Lookup deep-link button: sort order (ascending distance from 50MA). Mirror of `screener_config.json` `button.sort`. |
| `BUTTON_FT` | `'4'` | Lookup deep-link button: `ft` (filter type) parameter. Mirror of `screener_config.json` `button.ft`. |
| `EARNINGS_IMMINENT_DAYS` | `3` | Picks tab expanded card: earnings-date badge turns red when the next known earnings date is within this many days. |
| `EARNINGS_CAUTION_DAYS` | `10` | Picks tab expanded card: earnings-date badge turns amber when within this many days (and beyond `EARNINGS_IMMINENT_DAYS`). Only upcoming dates are colored — a past/stale date (Finviz hasn't refreshed) shows neutrally. |
| `FOCUS_MIN_DOLLAR_VOL` | `30_000_000` | Focus scoring (Phase 3d): hard gate — a stock must have avg $ volume (Price × Avg Volume) at or above this to be a Focus candidate at all. |
| `LIQUIDITY_PENALTY_START` | `60_000_000` | Focus scoring: above this avg $ volume, zero liquidity penalty; ramps to `LIQUIDITY_PENALTY_MAX` right above the `FOCUS_MIN_DOLLAR_VOL` floor. |
| `LIQUIDITY_PENALTY_MAX` | `0.3` | Focus scoring: max multiplicative score haircut for a Focus candidate near the liquidity floor. |
| `EARNINGS_PENALTY_MAX` | `0.7` | Focus scoring: max multiplicative score haircut for earnings within `EARNINGS_IMMINENT_DAYS`; ramps in from 0 at `EARNINGS_CAUTION_DAYS`. |
| `POST_EARNINGS_PENALTY_FRAC` | `0.25` | Focus scoring: one-day carry-over penalty (this fraction of `EARNINGS_PENALTY_MAX`) for a stock that reported exactly 1 day ago; 2+ days past is fully decayed to 0. |
| `OVERHEAD_PENALTY_START` | `8` | Focus scoring (Phase 2): `ohMag` (% below 52-week high) at/below this gets 0 overhead-supply penalty. Aligns with `LAUNCH_NEAR_HIGH_PCT`'s near-high free zone. |
| `OVERHEAD_PENALTY_END` | `30` | Focus scoring: `ohMag` at/above this gets the full `OVERHEAD_PENALTY_MAX` haircut; ramp is linear between START and END. Calibrated to the live pool's ~p25 `ohMag` (~28.6%). |
| `OVERHEAD_PENALTY_MAX` | `0.20` | Focus scoring: max multiplicative score haircut for deep overhead supply (far below 52wk high). Kept below the extension (`0.5`) and earnings (`0.7`) penalty ceilings so overhead acts as a tiebreaker, not a veto. |
| `ARIEL_GROUP_TOP_N_FULL` | `40` | Ariel match (Phase 4): group must rank in the top N industries by `rank_month + rank_quarter` ascending sum to fully qualify. Computed from `state.data.industries.delta` (all ~144 industries), not limited to groups picks.csv has stock rows for. |
| `ARIEL_GROUP_TOP_N_SOFT` | `50` | Ariel match: soft-qualify extension for ranks 41–50 (near-miss on the group gate). |
| `ARIEL_DOLLAR_VOL_MIN` | `100_000_000` | Ariel match: hard floor on avg $ volume (Price × Avg Volume, same formula as `FOCUS_MIN_DOLLAR_VOL`); no soft band — a liquidity floor, not a strength signal. |
| `ARIEL_ATR_PCT_FLOOR_SOFT` / `ARIEL_ATR_PCT_CEIL_SOFT` | `3.0` / `9.0` | Ariel match: daily-move gate (ATR/Price %) is excluded entirely outside this range — too quiet below the floor, too volatile above the ceiling. |
| `ARIEL_ATR_PCT_FULL_LOW` / `ARIEL_ATR_PCT_FULL_HIGH` | `4.0` / `7.0` | Ariel match: full-qualify band for the daily-move gate; the two outer bands (floor–low, high–ceiling) are soft-qualify. |
| `ARIEL_GROWTH_MIN_FULL` | `25` | Ariel match: EPS YoY TTM AND Sales YoY TTM must each be ≥ this % for the growth gate to fully qualify (AND, not OR). |
| `ARIEL_GROWTH_MIN_SOFT` | `15` | Ariel match: soft-qualify floor for EPS YoY TTM AND Sales YoY TTM — either metric below this fails the growth gate outright. |
| `WATCHLIST_TTL_SESSIONS` | `10` | Watch card "N mornings left" — display-only mirror of the worker's `WATCHLIST_TTL_SESSIONS` (worker-positions), which owns the real `sessions_remaining` counter. |
| `WATCHLIST_EXPIRING_AT` | `1` | Watch card footer: `sessions_remaining <= this` shows the amber "expiring" cue (e.g. "1 morning left" in amber). |
| `WATCHLIST_GAUGE_PAD` | `0.08` | Fraction of the price domain padded on each end of a watch card's levels gauge so end markers (prior high/low, your level) aren't clipped at the track edges. |
| `POS_VISIBLE_STATES` | `{'open','managing','closing'}` | Positions tab: worker `state` values that always render as a live card. Since WS5-5 the live fetch is `?state=open,managing,closing,closed&closed_within_sessions=POS_GRACE_SESSIONS` — `posIsLiveVisible(p)` (not a bare `POS_VISIBLE_STATES.has()`) is the real client-side gate, additionally keeping `closed` rows within the grace window. |
| `POS_STATE_BADGE` | see code | Positions tab: small uppercase badge on `managing` cards; `open` gets no badge. `closing` no longer has an entry — WS5-4a hoists `closing` rows out of the card list into the confirmation strip, so they never reach this lookup. |
| `POS_GRACE_SESSIONS` | `2` | Positions tab (WS5-5, #332): trading sessions a `closed` position keeps showing in the live positions list (read-only "closed" badge card) before it drops to the Closed section only. Compared against the server's `sessions_since_close`. |
| `POS_CLOSED_HISTORY_SESSIONS` | `60` | Positions tab (WS5-5): how many trading sessions back the lazy-loaded Closed section fetches (`?closed_within_sessions=60`) once expanded — ~3 trading months. |
| `POS_EXIT_REASON_LABEL` | see code | Positions tab (WS5-7 / WS5-4a): maps `advance()`'s exit-check reason enum (`stop_hit`, `gap_down_below_stop`, `close_below_50ma`, `close_below_20ma`, `severe_breakdown`, `two_close_below_20ma`) to the plain-English phrase shown in the confirmation strip's expanded reason pill and the Activity trail. |
| `POS_EXIT_REASON_SHORT` | see code | Positions tab (WS5-4a): terse companion to `POS_EXIT_REASON_LABEL` for the confirmation strip's collapsed one-line summary (e.g. `stop_hit` → "stop hit", `gap_down_below_stop` → "gap-down"). |
| `POS_PRECLOSE_SEVERITY_META` | see code | Positions tab (WS5-8): pre-close advisory band item severity (`act`/`heads_up`) → pill label + Tailwind classes. Display strings/classes, not a numeric threshold — see § Pre-close read below. |

## Watchlist (Morning + Positions, WS5 §8b)

Personal per-ticker watch entries that ride the morning status-check pipeline for a limited
window, with an optional private "level of interest" overlay.

- **Two surfaces.** Morning tab: a "Your watchlist" section (`renderWatchlistSection()`), since
  morning-subtabs-watchlist rendered in its own subtab pane (`#morning-subtab-watchlist`) rather
  than stacked above the picks list — see § Morning tab below. Positions tab: an "＋ Add to
  watchlist" collapsible, a sibling to the §8a manual-entry expander (separate state, separate
  handlers — not merged with `manualEntry`).
- **Levels gauge defaults to hidden** (morning-subtabs-watchlist, owner request). `watchGaugeHtml()`'s
  "Show levels ▸ / Hide levels ▾" toggle (`__toggleWatchGauge`) is keyed by `state.watchGauge[ticker]`
  as a **SHOWN** flag — absent/false = hidden, the opposite polarity from the original "collapsed?"
  meaning the same map held before this change. The flip needed no per-ticker initialization: a
  ticker simply never added to the map now reads as hidden by construction.
- **Soft-remove, not delete (morning-subtabs-watchlist, migration 0007).** The watch card kebab's
  "Remove" (`window.watchRemove`) now sends `PATCH /watchlist/:id {remove:true}` — NOT the old
  `watchDeleteApi`/`DELETE` — so the row survives server-side as `status:'removed'` and drops into
  a collapsed **"Recently removed"** bin (`watchRemovedCardHtml`, mirrors the existing "Expired"
  bin) instead of vanishing. `worker-positions/src/watchlist.js::watchlistTickers()`'s
  `status = 'active'` filter (used by both `heldTickers()`'s scrape union and the public
  `GET /watchlist-tickers` feed) already excludes `removed` identically to `expired` — the ticker
  stops being scraped on the very next held-feed run with no separate filter needed. A removed
  card still renders a free TradingView chart (`watchChartAffordance` needs only the ticker
  symbol, independent of any backend feed) plus a **Restore** button
  (`window.watchRestore` → `PATCH {restore:true}`, same renew-with-fresh-TTL semantics as
  `watchRenew`). The hard `DELETE`/`watchDeleteApi` path still exists, reserved for graduation
  cleanup only (`watchGraduate`'s post-`POST /positions` cleanup) — a graduated ticker becoming a
  real position should vanish outright, not sit in a removed bin. Both terminal statuses purge
  after `WATCHLIST_PURGE_DAYS` (worker-side `tickWatchlist()`), symmetric.
- **Merge model, two sources joined client-side by ticker.** (1) The *public system read*:
  `morning_latest.csv` rows tagged `list_category === 'watchlist'` — the same server-computed
  status pipeline (`pick_status.py`) that scores picks, so watch tickers get a real
  triggered/gapped/reclaim/etc. status without any private data leaving the CSV. (2) The
  *private feed*: owner-bearer `GET /watchlist` on the `finviz-positions` worker, which returns
  `level_type`/`level_value`, `sessions_remaining`, `status`, and reference values
  (`prior_high`, `prior_low`, `atr`, `sma20`, `sma50`). The Morning-tab card
  (`watchCardHtml(entry, pub)`) merges the two by `ticker` at render time.
- **Three card states, not two (WS-POSITIONS-STATUS, 2026-08-25).** `entry.prior_high == null`
  (no `ticker_quotes` bar exists at all yet) → the true "Added — first morning check lands
  tomorrow AM" state. A bar can exist (live via `GET /watchlist`, which updates hours before the
  next `collect_morning.py` run) while `pub` is still null or `pub.status ===
  'awaiting_first_read'` (`pick_status.STATUS_AWAITING_FIRST_READ`) — that's a separate "Reference
  bar captured — first live read after the next scheduled check" state, distinct from both
  "Adding" and a genuine `no_quote` (an established ticker Finviz actually failed to quote today).
  Collapsing these into one `no_quote` copy is exactly what made a brand-new watch ticker show
  "Morning feed missed this ticker" when nothing was missed — see
  `planning/watchlist-status-honesty-and-seeding.md`.
- **Privacy — load-bearing:** `level_value` (the user's private price/MA threshold) never
  leaves the owner-bearer `/watchlist` path. There is no server-side "met/not-met" computation
  or storage of that comparison — the your-level read (`watchYourLevel()`) is computed entirely
  client-side from the already-fetched private entry plus the public price/low, so the level
  itself is never exposed through the public `morning_latest.csv` feed or any unauthenticated
  endpoint.
- **Graduation.** A watch card's "I took it →" reuses the §8a manual-entry ticket
  (`state.manualEntry`, prefilled ticker + `graduateWatchId`) rather than a separate trade-entry
  path. On a successful `POST /positions`, the client also `DELETE`s the watch entry
  (`watchDeleteApi`, best-effort) so a graduated ticker drops off the watchlist.
- **Reclaim status** (`pub.status === 'reclaim'`) uses the 50MA ref recovered from the private
  feed (`entry.sma50`) — the system reclaim signal is fixed to the 50MA per P2; if `sma50` is
  null (no EOD bar yet), the card falls back to the non-reclaim body rather than showing a ref
  it doesn't have.
- Constants: see the display-thresholds table above (`WATCHLIST_TTL_SESSIONS`,
  `WATCHLIST_EXPIRING_AT`, `WATCHLIST_GAUGE_PAD`). The worker's `WATCHLIST_TTL_SESSIONS` (source
  of truth for the real countdown) and `WATCHLIST_PURGE_DAYS` are documented in
  `worker-positions/README.md`.

## Morning tab (WS3, ADR-013)

**Subtabs (morning-subtabs-watchlist).** The tab has two panes, `#morning-subtab-picks`
(`renderMorning()`'s picks-confirmation cards) and `#morning-subtab-watchlist`
(`renderWatchlistSection()`'s "Your watchlist" — see § Watchlist above), switched by a
segmented-pill nav (`renderMorningSubtabs()` / `window.__setMorningSubtab`) that mirrors the
Picks All/Focus toggle's look. Both panes render unconditionally on every `state.tab === 'morning'`
pass (`render()` calls `renderMorningSubtabs(); renderWatchlistSection(); renderMorning();` every
time) — switching subtabs is a pure visibility toggle (`classList.toggle('hidden', ...)`), no
re-fetch or re-render. Default pane is `'picks'` (`state.morningSubtab`, session-only, resets on
reload) — the picks confirmation read is the tab's primary ADR-013 job; the watchlist is the
user's own opt-in radar, previously stacked above it in one scroll. The Watchlist subtab button
shows an active-entry count badge when non-zero.

The **Morning** tab (`renderMorning()` in `index.html`) reads the provisional store
`data/picks/sessions/morning_latest.csv` (fetched via `MORNING_URL`) and tags each of
yesterday's picks with a status computed server-side by `scripts/pick_status.py`. A missing
file (pre-first-run, or a non-trading day when `collect_morning.py` exits without writing) is
the empty state — a 404 is expected, never an error.

- **Provisional chrome is non-negotiable** (ADR-011): the amber banner + "provisional — not
  settled" timestamp must always render so a 10:05 ET read is never mistaken for settled EOD.
- **Actionability sort** (`MORNING_STATUS_META[*].order`): Triggered → Gapped-through / Reclaimed
  (both order 1) → Failed breakout → Setting up → Invalidated → No quote. This is the *display*
  order and is deliberately different from the engine's evaluation precedence
  (`pick_status.STATUS_PRECEDENCE`). **This grouping is a constant** — it applies under every
  sort mode below; the sort toggle only ever changes the tiebreak *within* a bucket (one
  exception, Rel volume's Global scope — see below).
- **Sort / launch-ready filter / bucket collapse + mini-nav (owner decision 2026-09-03).**
  `renderMorning()` enriches each row once (`sessionDisplayRow`, EOD cross-ref via
  `ws4FindPicksRow`, `computeLaunchReady`, Focus score, `atr_from_lod`, Rel Volume — see the
  `enriched` map at the top of the function) before filtering/sorting/grouping, so those steps
  never re-derive the same values per row.
  - **Sort pills** (`morningSortBarHtml()`, `state.morningSort`): `A–Z` (today's plain ticker
    order, kept as an explicit option, not removed), **`Focus score` (default)**, `ATR from LoD`
    (reuses the exact on-card label/metric — deliberately not a separate "entry quality" name),
    and `Rel volume`. `sortMorningEntries()` is the shared comparator: nulls (e.g. a ticker that
    isn't a Focus candidate today) always sort last within a bucket, then ticker A–Z — it never
    NaN-crashes on missing data.
  - **Rel volume's scope switch** (`state.morningSortScope`, only rendered when
    `morningSort==='rel_volume'` — a conditional control instead of a permanent 5th pill, given
    how much chrome already stacks above the first card on this tab): `In bucket` (default,
    same bucket-preserving behavior as the other three modes) or `Global`, which flattens ALL
    status buckets into one Rel-volume-ranked list — "what's most active right now" is a
    different question from "what's most active among my Triggered names," and doesn't make
    sense gated by status. In Global mode there are no bucket headers, no mini-nav, and no
    collapse — each card still shows its own status pill.
  - **Focus score chip + card sort share ONE computation.** `focusScoreMapForPool()` runs the
    same candidate derivation `ws4FocusScore()` has always used (C6 base filter +
    `isFocusEligible` over `state.picksData` — matches the Picks tab's own Focus badges) and
    `computeFocusScores()` pass. `renderMorning()` calls it once per render into module-level
    `_morningFocusMap`; the per-card chip, the `'focus'` sort branch, AND `ws4FocusScore()`'s
    trade-ticket footnote lookup (`ws4TicketHtml`, rendered later in the same synchronous render
    pass) all read that one map — never three separate `computeFocusScores()` passes that could
    disagree on a ticker's score within one render. A future change to the Focus formula or its
    candidate pool updates the chip, the sort, and the footnote for free.
  - **Launch-ready filter** (`morningLaunchFilterHtml()`, `state.morningLaunchFilter`): `All` /
    `Coiled` / `Extended` / `Overhead`, filtering on the SAME `computeLaunchReady()` label
    already shown as a card chip. Independent axis from sort — narrows the pool, then sort
    orders whatever's left. Pill counts are computed off the full (unfiltered) enriched pool so
    a pill always previews what selecting it would show. A filter that empties every bucket
    shows filter-specific "No `<X>` setups right now — try All" copy, not the generic
    no-picks-today empty state.
  - **Bucket collapse + sticky mini-nav** (`state.morningCollapsed`, a `Set` of status keys;
    `morningMiniNavHtml()`): each non-empty bucket header is a toggle button
    (`__toggleMorningBucket`) showing its label + count; `state.morningCollapsed` starts EMPTY
    (everything expanded, matching pre-2026-09-03 behavior) — the user collapses buckets
    manually rather than the tab defaulting to a denser/quieter look on its own. The sticky
    mini-nav (only rendered when there's more than one bucket) lists every non-empty bucket with
    its count; `__jumpToMorningBucket()` force-expands the target bucket before scrolling to it
    — landing on a collapsed header with nothing visible underneath would look like a broken
    jump, not a successful one.
  - All four pieces of state (`morningSort`, `morningSortScope`, `morningLaunchFilter`,
    `morningCollapsed`) are session-only, same convention as `morningView`/`morningSubtab` —
    they reset to their defaults on reload, never persisted.
- **`atr_from_lod` + Rel volume render on every status (owner decision 2026-09-02); the "I
  took it" button stays actionable-only.** Originally `atr_from_lod` was computed and shown
  only for Triggered / Gapped-through / **Reclaimed** (`MORNING_STATUS_META[*].actionable`,
  `reclaim.actionable:true` since 2026-08-27); the owner asked for real-time entry-quality
  context (ATR-from-LoD + Rel volume, both live scrape-wide values, unlike the B-2/B-3
  trailing cols below) on every card regardless of tradeability, so `compute_atr_from_lod`
  is now called unconditionally in `collect_morning.py` and both `morningCardBody` and
  `watchCardHtml` render the two rows on every status branch, same color bands throughout.
  `MORNING_STATUS_META[*].actionable` still gates the trade ticket / "I took it" CTA — that
  part of the actionable/non-actionable split is unchanged. Picks emit `reclaim` (against
  their prior low OR a derived 50MA); the `reclaim` case in `morningCardBody` names the
  reclaimed level from the `reclaim_ref`/`reclaim_ref_value` CSV columns (50MA prefixed `~`
  — a stale derived level). **`watchCardHtml`'s reclaim branch was a known inconsistency**
  (a separate hand-built body that predated the shared atrRow/rvolRow rows and never
  rendered them) — fixed here so all watch card states render the same rows; tracked as
  closed in `.session/SPRINT.md` (was open as a standardization gap).
- **Compression "Volatility & setup" section (B-6, issue #379).** Every morning picks card
  (`morningCardBody`, all live statuses) and every watch card (`watchCardHtml`) renders the shared
  `volSetupSectionHtml(r, {staleTrailing:true})` section (the A-2 seam, defined near `volSpark`)
  — the same one the Picks card uses (`renderPickRow` omits `staleTrailing`): B-1 Vol W/M (+
  contracting/expanding fact tint) · Rel volume · 52W-high dist, B-2 range tightening, B-3 volume
  dry-up, B-5 Pre-Power of 3 (MA-bunching COIL-PRECONDITION chip — price/20MA/50MA within a
  `POWER_OF_3_ATR_MULT`×ATR band, computed **client-side** in `volSetupSectionHtml` from raw
  Price/ATR/SMA20/SMA50 — NOT a stored CSV column, since it's a config-dependent pure single-row
  value; plus the two shown SMA % distances and the classic MA-to-MA cluster spread %; the full
  undercut→reclaim trigger is a later slice, B-5b). Because it's computed at render time and
  Price/SMA20/SMA50/ATR are in `_SETUP_FRESH_COLS`, the B-5 chip is **real-time** on Morning/Watch
  (fresh MA levels), unlike the B-2/B-3 trailing sparklines which stay last-close (see below). `staleTrailing:true` labels the B-2/B-3 sub-headers "Range/Volume over last
  10 sessions (as of last close M/D)" — those two sub-blocks alone come from the picks_latest
  cross-ref (last night's close), unlike the fresh B-1 row above them or the Picks tab (where the
  whole card is same-EOD-run, so no lag to caveat). It's inserted after the card's metric rows
  and before the trade ticket / CTA (context before action). The row it renders from is built by
  `setupRowForCard(ticker, freshRow)`: base = the `ws4FindPicksRow` cross-ref to `picks_latest`
  (carries the B-2/B-3 trailing sparkline cols, multi-day, plus its own `date` — the as-of date
  shown in the caveat), with the B-1 raw cols overridden by
  this-morning's fresh scrape-wide values from the morning store row (`r`) / watch public read
  (`pub`) — those columns are on the morning store since A-1-IMPL (scrape-wide). Self-hides (returns
  `''`) for an orphan with no picks history and no fresh scrape. The **trade ticket** deliberately
  does NOT render it separately — it lives inside the morning card, which already shows it above the
  ticket, so a second copy would duplicate.
- **"I took it" creates a real position (WS5 phase 1, #309).** It is login-gated: signed out, the
  tap shows a "Sign in on the Positions tab" note (no write); signed in, it opens an inline confirm
  (entry/stop/qty captured from the trade ticket's current state via `ws5BuildPayload`) → `POST
  /positions` to the `finviz-positions` worker (`POSITIONS_API`). The old `taken:<date>:<ticker>`
  localStorage marker is **kept, additively** — it still drives the card's "✓ Logged" state, but is
  now written only after a confirmed 201 (see `ws5ConfirmTakeIt`). `window.__morningTookIt` was
  removed; the writer is now `window.ws5TakeIt` → `ws5ConfirmTakeIt`.

## Positions tab (WS5-7 managing-card overhaul, issue #337)

Signed out → a passphrase sign-in card (`posLogin` → `POST /auth/login` → bearer token in
`localStorage['fv_pos_token']`). Signed in → `GET /positions?state=open,managing,closing` renders a
state-driven **managing card** (`posCardHtml` → `posDerive` + `posHeroHtml`/`posStopMovedHtml`/
`posOverlaysHtml`/`posDetailsHtml`/`posActivityHtml`) for `state` in `open`/`managing`/`closing`
(`POS_VISIBLE_STATES`, also re-checked client-side as defense-in-depth — only `closed` drops off).
Design authority: `planning/ws5-7-positions-managing-card.md`, mock
`planning/mocks/ws5-7-positions-card.html`.

This replaced the phase-1 read-only card (fixed 2026-08-19), whose `risk = entry − current_stop`
math went to `$0` or **negative** once the engine trailed the stop to/past entry — the negative
number was literally the locked-in gain with its sign flipped. `posDerive(p)` (pure, DOM-free,
unit-tested) is the whole fix: per-share first, then × `remaining_qty`, every $ figure floored at
zero. See `planning/ws5-7-positions-managing-card.md` §2 for the formula table.

- **Hero (collapsed card), priority order:** no `last_close` yet → neutral "Planned risk $X ·
  first read tonight" (US-7, null-safe, never NaN/fake $0); `current_stop >= entry_price` → 🔒
  Risk-free (locked `+$L` once acked, an amber "lock pending" chip + conditional copy until
  then, plain 🔒 alone at exact breakeven); else → P&L hero (`±$unrealized`, colored) + "Open
  risk $O ($/sh) to stop" subline. `closing` never reaches this hero — see the confirmation
  strip below.
- **Stop-moved banner + cross-device ack.** Renders whenever the position has a `stop_moved` event
  (sourced from that event's own `payload {from,to,basis}`, never `initial_stop`, so it can't
  misreport what happened). Un-acked → CTA + **✓ Updated** button → `posAckStop(tradeId)` →
  owner-bearer `POST /positions/<trade_id>/ack-stop` (`worker-positions/src/transitions.js::ackStop`,
  documented in `worker-positions/CLAUDE.md`). Acked → resolved "✓ Updated" text. The ack is
  **server-side by design** (`stop_ack_value` on the position row) — the owner trades on phone and
  laptop, so a localStorage ack (per-device) would desync between them. `posDerive`'s `acked` flag
  drives BOTH this banner's row2 AND the hero's pending-lock chip — one acknowledgement, both
  resolve together. A new engine stop-move automatically re-raises the banner (the acked value no
  longer matches `current_stop`) — no separate "unack" step.
- **Details ▾** (collapsed by default, same full row set on every card regardless of state — no
  thin/inconsistent Details): Entry, Stop (true basis — `trailed · <label>` when the stop has
  moved, not the stale initial `stop_basis`), 1R (initial), Open risk, Unrealized P&L (always shown
  on a live card), Locked-in (risk-free cards only), Qty (`N of M`, `(trimmed X)` when trimmed),
  today's O/H/L/C/%/volume bar (`avg` parsed defensively from `last_raw`'s `"Average Volume"` JSON
  field), and an Activity trail from `p.events` (newest-first, human-readable, dated). A **"show
  formulas"** checkbox in the summary reveals the arithmetic behind each row inline
  (`.pos-fx`/`.pos-formula`, CSS `:has()`-driven — see the `<style>` block; Tailwind's Play CDN
  can't express that selector as utility classes).
- **Overlays** (decorate a `managing`/`open` card, can co-occur): partial trim
  (`remaining_qty < initial_qty` — "✂ Trimmed N sh @ M× ATR · date — Q of I held") and caution
  (`caution_flag >= 1`, an integer counter, not a bool — "⚠ N of 2 closes below the 20MA — exits on
  the next close below"). Earnings (`days_to_earnings` within `EARNINGS_CAUTION_DAYS`=10, red within
  `EARNINGS_IMMINENT_DAYS`=3; its own `>= 0` client guard so a past-earnings date never shows even if
  the engine signal regresses — the engine-side negative-days guard fix is #335 / advance.js).
  Flag-only copy, mirroring the engine's never-auto-exit-on-earnings rule.
- **Confirmation strip (WS5-4a, issue #264/#268, design authority
  `planning/mocks/ws5-needs-confirmation-surface.html` States A/B/C,
  `planning/trade-lifecycle-engine.md` §8):** `closing` positions no longer render as cards at
  all — `renderPositions()` partitions the fetch into `closingRows`/`cardRows` and hoists
  `closingRows` into `posConfirmStripHtml()`, a collapsed-by-default red-accented strip above
  the (subtly dimmed) card list. Zero `closing` rows → zero pixels (State A). Collapsed (State
  B, default): one header line (`● Needs your confirmation` + count + `show ▾`) plus a terse
  one-line summary (`POS_EXIT_REASON_SHORT`, e.g. "NVT stop hit · OUST gap-down"). Expanded
  (State C, `posStripItemHtml()` per item, sorted oldest `exit_signal_date` first — "order =
  urgency"): reason pill (`POS_EXIT_REASON_LABEL`), modeled fill + R, an editable actual-fill
  input pre-filled with `expected_exit_price` (stashed to `state.posConfirmFill` on `oninput`,
  no re-render — focus-preserving, same discipline as `manualRecompute`), an auto-close
  countdown from `auto_confirm_sessions − sessions_in_closing` (omitted entirely, never "NaN",
  when either field is missing), and the two actions: **Confirm this fill →**
  (`window.posConfirmExit` → `POST /positions/<id>/confirm-exit`, sending `exit_price` only if
  the user edited the field — an unedited fill lets the server default to
  `expected_exit_price`) and **Still holding** (`window.posStillHolding` → `POST
  /positions/<id>/still-holding`). Both re-fetch via `posLoadPositions()` on success rather than
  hand-mutating state — the closed/reopened row simply drops out of (or changes state within)
  the next `open,managing,closing` fetch.
- **Recently-closed grace + Closed section (WS5-5, issue #332).** A `closed` position no longer
  vanishes from the tab the instant it settles. Two tiers: (1) it keeps rendering in the live
  list for `POS_GRACE_SESSIONS` (2) trading sessions — as a compact, **read-only**
  `posClosedCardHtml` card (no hero/stop-banner/overlays) under a muted "Recently closed"
  divider below the live cards, badge-marked "closed", showing exit price + realized $/R via
  `posDerive`; (2) a collapsible **Closed** section at the bottom of the tab, always rendered
  for a signed-in user, **lazy-loaded** — `posLoadClosed()` only fires `GET
  /positions?state=closed&closed_within_sessions=POS_CLOSED_HISTORY_SESSIONS` (60 sessions, ~3
  months) on first expand (`posToggleClosed()`), keeping the default tab payload light. The
  live fetch itself changed to `?state=open,managing,closing,closed&closed_within_sessions=
  POS_GRACE_SESSIONS` — `posIsLiveVisible(p)` gates what actually renders (open/managing/closing
  always; `closed` only while `sessions_since_close <= POS_GRACE_SESSIONS`), replacing the old
  bare `POS_VISIBLE_STATES.has()` check. The Closed section excludes rows already shown as grace
  cards (`sessions_since_close <= POS_GRACE_SESSIONS`) so nothing double-renders; a successful
  `posConfirmExit` invalidates `state.closedData` (set to `null`) so the next expand picks up
  the newly-closed trade. `posClosedCardHtml` is the single card renderer for both the grace
  block and the Closed section. **Out of scope (deferred, tracked separately):** the OS/app-icon
  push badge is WS5-4b. Hoisting an auto-closed-unconfirmed position into the confirmation strip
  with a `correct-exit` editor is a separate follow-up — WS5-5 renders it as a plain read-only
  closed card (with an amber "auto" cue from `confirmation_status === 'auto'`), no correction UI.
- Backend fields consumed (all null-safe, `worker-positions` GET `/positions`): `last_close`,
  `last_bar_date`, `last_open/high/low`, `last_change_pct`, `last_volume`, `last_raw` (JSON string),
  `events` (≤8, newest-first, `payload` pre-parsed to an object), `stop_ack_value` (server-computed
  from the full per-trade event history, robust to the 8-event display cap — use this for ack
  state, never re-derive it from the capped `events` array).
- Auth is a worker-native bearer token (not Cloudflare Access — the PWA is a cross-origin
  GitHub-Pages page); the whole auth surface is the swap seam `worker-positions/src/auth.js`.
  See `worker-positions/README.md` and ADR-012 for the backend contract.

### Pre-close read (WS5-8)

A ~15:40 ET advisory computed off a held scrape, so the owner can place broker orders
**in-hours** instead of learning at 17:30 that a stop was hit. Design authority:
`planning/mocks/ws5-8-preclose-read.html`. Source: owner-bearer `GET
/positions/preclose` on `finviz-positions`, returning `{ ran_at, n_checked, n_flagged,
items: [{ trade_id, ticker, category:"exit", severity:"act"|"heads_up", signal, price,
ref_level }] }`. `ran_at: null` means no read ran yet today (or the fetch failed/signed
out) — a null-safe empty shape.

- **Fetch:** `posLoadPreclose()` mirrors `posLoadPositions()` — fired alongside it from
  `renderPositions()`'s loading branch (`state.precloseData === null`), deduped by
  `state.precloseLoading`. Strictly best-effort: ANY failure (network, 401, 5xx) just
  leaves `state.precloseData = null`, never blocks or errors the positions render. Reset
  to `null` on sign-in/sign-out/retry (same convention as `positionsData`).
- **Render (`advisoryBandHtml`, pure function):** three states, mirroring
  `posConfirmStripHtml`'s collapsible shape but read-only (no confirm/still-holding
  buttons — those stay on the settled strip) —
  - `!ran_at` → renders nothing (zero pixels).
  - `ran_at` set, `items` empty → a single emerald-tinted receipt line: "✓ Pre-close
    checked at {time} · {n_checked} positions · nothing to act on before the close".
  - `items` non-empty → the **amber** band (`border-amber-500/40 bg-amber-500/5`,
    deliberately distinct from the **red** settled confirmation strip), collapsible via
    `state.precloseStripExpanded` / `window.posTogglePreclose()` (inline handlers go
    through `window.*`, not a bare `state.x=` attribute — see the `posSetConfirmFill`
    comment above `posStripItemHtml` for why). Items sort `act` before `heads_up`. Each
    row: ticker, severity pill (`POS_PRECLOSE_SEVERITY_META`), copy using
    `POS_EXIT_REASON_SHORT`/reason phrasing, and an aside — green "place your order
    before the close" for `act`, muted "may firm up at the bell" for `heads_up`.
    `price`/`ref_level` reuse `fmtPerSh`; a null `ref_level` omits the "· your stop
    $Y"/"vs $Y" clause rather than printing `$null`.
- **Slot order:** header → advisory band → the red confirm strip → cards (advisory sits
  above the settled strip — provisional first, settled second). Only wired into
  `renderPositions()`'s main loaded branch, not the empty-positions branch — a signed-in
  user with zero open/managing positions has nothing the compute could have flagged, so
  the band (or even the calm-day receipt) would be noise there.
- **Never writes position state** — no `POST`, no `last_advanced_date` stamp. The 17:30
  settled sweep (`advance()`) stays the sole writer; this is a read-only preview.

### Exit alerts — VAPID web push (WS5-4b)

A quiet, set-once footer affordance on the Positions tab (`#pos-alerts`, `posRenderAlerts()` /
`posEnableAlerts()` / `posDisableAlerts()`), rendered after the closed section in every signed-in,
non-transient branch of `renderPositions()` — never above the confirmation strip. **Ticker-named
payload (PR-1, issue #348):** the worker now encrypts an RFC 8291 `aes128gcm` JSON payload
(`{title, body, ticker, tag, url}`, built by `worker-positions/src/push.js`'s
`buildExitPushPayload()`) into the Tier-1 exit push, so the notification names the ticker and reason
(e.g. "🚨 NVT — exit signal" / "Stop hit at 42.10. Confirm your fill."). The service worker
(`docs/sw.js` `push` handler) reads it via `event.data.json()` — the browser's push service does the
RFC 8291 decryption before the event fires, so the handler only ever sees plaintext JSON. A
data-less push (no `event.data`) still falls back to today's generic "Exit signal" notification —
kept for backward compatibility, not otherwise used going forward. The in-app confirmation strip
remains the source of truth for full detail (modeled fill, R, auto-close countdown); the push is
still just a nudge. There is no Tier-2 rich-payload UI (decaying-cadence reminders, earnings-approach
push) — that's a separate later PR. Tapping the notification (`notificationclick`) focuses an existing window
and `postMessage`s `{type:'OPEN_POSITIONS'}` (handled by the SW-message listener next to
`SW_RELOAD`), or falls back to `self.clients.openWindow('...#positions')` on a cold start, which
`index.html`'s boot code picks up via a `location.hash === '#positions'` check and calls
`switchTab('positions')`.

Subscribe/unsubscribe reuse `posApi` (Bearer + 401 handling) against the backend routes `POST
/push/subscribe` / `POST /push/unsubscribe` on `finviz-positions` (`worker-positions/`, PR A of
this workstream — not touched here). `VAPID_PUBLIC_KEY` (near `POSITIONS_API`) must stay in sync
with the worker's `VAPID_PUBLIC_KEY` secret/var; it's safe to ship client-side (the private key
never leaves the worker).

**iOS requirement:** Safari supports web push only for a Home-Screen-installed PWA (iOS ≥16.4) —
in a plain browser tab `window.PushManager` is undefined. `posIsIOS()` + `posIsStandalone()` gate
the affordance to show "Add to Home Screen first" guidance instead of a dead-end "not supported"
message in that case.

### Manual entry: "log a position on any ticker" (WS5 §8a)

Signed-in Positions tab renders a collapsed-by-default expander ("＋ Log a position manually") above
the "Open positions" header (`manualEntryHtml()`, called from `renderPositions()` in every signed-in
branch — loading/error/empty/loaded — so it's always reachable regardless of fetch state). Expanded
form mirrors the ws4Ticket markup vocabulary (slate-900/slate-800 insets, sky-500 buttons, segmented
toggles) and freeze-confirms exactly like the Morning "I took it" flow (`manualConfirmHtml()` mirrors
`ws5ConfirmHtml()`), but is entirely standalone state (`state.manualEntry`) and payload builder
(`manualBuildPayload()`) — it does **not** touch `ws5BuildPayload`/the morning trade-ticket state.

- **Ticker resolve line**: typing debounces ~400ms (`manualTickerInput` → `manualResolveTicker`) then
  calls the existing `lookupTicker(sym)` (ticker-lookup worker, `WORKER_URL`). Success shows a green
  "✓ {company_name} · {finviz_sector}"; failure/unknown shows a muted "symbol not recognized — you can
  still log it" and **never blocks logging**. A sequence counter (`_manualLookupSeq`, module-level, not
  on `state`) guards against a stale earlier lookup overwriting a newer one.
- **Stop as** toggle: Price (direct stop input) or `% below` (computed `entry * (1 - pct/100)`).
- **Size by** toggle: `Risk $` (default `ws4RiskDefault()`, `qty = floor(risk / riskShare)`) or
  `Shares` (direct qty input, `risk = qty * riskShare`). Live "Risk / share" and "→ Position" readouts
  patch by id (`manual-riskshare`/`manual-position`) via `manualRecompute()` on every `oninput` — same
  focus-preserving discipline as `ws4Recompute` (never a full re-render on a keystroke; toggle clicks
  are the one case that does re-render, since a click doesn't lose input focus).
- **Optional fields**: `entry_date` (backdate — copy notes it's managed forward from the next bar, not
  replayed) and `days_to_earnings`. Both omitted from the payload (not sent as empty string/null-key)
  when left blank, except `days_to_earnings` which is explicitly `null` (matches `ws5BuildPayload`'s
  convention for the same field).
- **Payload shape** (`manualBuildPayload()`): `{ ticker, entry_price, initial_stop, qty,
  stop_basis: 'manual', meta: { source: 'manual' }, days_to_earnings, entry_date? }`. `stop_basis`
  is always the literal `'manual'` — already a valid `POS_STOP_BASIS_ENUM` fallback value, no worker
  change needed. Validates `entry>0`, `stop>0`, `stop<entry`, resulting `qty>=1`.
- **Lookup → Positions redirect**: the ticker-result view in `renderLookup()` shows "Open a position on
  {SYM} →" (`manualOpenFromLookup(sym)`), which prefills `state.manualEntry` (ticker + `resolved` from
  the already-fetched lookup data, no extra network call) and calls `switchTab('positions')`. If not
  signed in, the Positions tab's own sign-in gate handles it — the form only renders under the
  signed-in branch.
- Tests: `tests/test_pwa_manual_entry.py` (Playwright — in the CI `--ignore=` list, see
  `.claude/rules/branch-commit-discipline.md` § New Playwright test files).

## Cutting a release ("What's New") — 3 steps, always together

The PWA's **What's New** hub reads `docs/releases.json`. Release versions use the
`YYYY.MM.DD` convention (human-scannable, monotonic, no semver to maintain). For multiple
releases on the same calendar day, append `.N` (e.g. `2026.06.21.1`, `2026.06.21.2`).
When you ship a user-facing change, do **all three** of these in the same PR:

1. **Prepend** a new entry to `releases.json` `releases[]` (newest-first): `version`
   (`YYYY.MM.DD` or `YYYY.MM.DD.N` for same-day releases), `date`, `title`, `tag`
   (`feature|fix|data|improvement`), optional
   `tab` (deep-links the entry to a tab), and a short user-facing `notes[]`.
2. **Update** the top-level `current` to the new `version` (this drives the unseen-update
   dot). `tests/test_guide_releases.py` asserts `current === releases[0].version`.
3. **Bump** `CACHE` in `docs/sw.js` (e.g. `finviz-v10` → `v11`) so the new shell +
   `releases.json` aren't served from a stale cache.

> **Hard rule:** code change + `releases.json` entry + `sw.js` cache bump must all land in the
> same PR. Splitting them across PRs creates gaps where the feature ships with a stale cache,
> or the release dot fires before the code is live. If you catch yourself opening a separate PR
> for "just the cache bump", stop — that's the failure mode. The only exception: housekeeping
> PRs (typos, session notes, refactors) with no user-facing change skip the release surface
> entirely. Full checklist: `.claude/rules/branch-commit-discipline.md`.

**Pre-commit check**: if your diff touches `docs/index.html` with a user-facing change, confirm
`docs/releases.json` and `docs/sw.js` are also staged before committing.

> The in-app **Guide** glossary copy lives in the `GUIDE` constant in `docs/index.html`,
> copied **verbatim** from the User one-liners in `knowledge/moaty-metrics.md`. The legend
> reads the live threshold constants (`REGIME_THRESHOLD`, `ACCEL_*`, `SLOPE_*`) so it can't
> drift. If you add a metric, add its `GUIDE` entry too — the anti-drift test enforces that
> every "why this matters" link targets a real `GUIDE` id.

## "Start Here" intro — `WELCOME` constant and first-run carousel

The **Start Here** hub section and the first-run full-screen carousel both draw from the
`WELCOME` array constant in `docs/index.html` (defined near `GUIDE`). The two surfaces
share one content source; `renderWelcome(mode)` switches rendering between hub ('hub')
and carousel ('carousel') modes.

**Canonical copy source:** `knowledge/product-intro-copy.md` — all `body` and `desc`
strings in `WELCOME` must appear verbatim there. `tests/test_pwa_intro.py` enforces the
sync (same discipline as `moaty-metrics.md` ↔ `GUIDE`).

**First-run behavior:** on page boot, if `localStorage.getItem(INTRO_KEY)` is
not `'true'`, the carousel auto-opens. Dismissing (Skip / Get started) calls
`setIntroSeen()` which sets the key. Re-openable anytime: hub ⓘ → Start Here → Replay
intro.

**`INTRO_KEY` versioning (currently `fvt_intro_seen_v3`, `docs/index.html`):** bump the
suffix only when the intro content changes substantially enough that existing users
should see it again (e.g. a new tab added, a new slide, a major rewrite — v2 added the
Picks tab, v3 added the vs Mkt tab + the Focus-picks slide). Minor copy edits do **not**
warrant a bump — they don't justify re-nagging users who already dismissed it. Record
any bump as a `feat:` commit with an explicit rationale; do not bump silently. Keep this
note's version number current — it drifted out of sync with the code once already.

**Tab deep-links:** each item in the tabs-tour slide carries a `tab` field (one of the
real tab ids in `VALID_TAB_IDS`, `tests/test_pwa_intro.py`). Adding a new tab requires
updating `WELCOME` + `product-intro-copy.md` + `VALID_TAB_IDS` — the anti-drift test
will catch a mismatch.

## Functional testing with Playwright (headless, no deployment needed)

The PWA fetches CSVs from `raw.githubusercontent.com`. Playwright can **intercept those
requests** and return local fixture CSV data, so the full UI can be tested without deploying
to GitHub Pages and without live data. Before running this in a Claude Code cloud session,
read `knowledge/investigations/playwright-cloud-session-testing.md` for cloud-specific gotchas
(Chromium revision mismatch, CDN/raw.githubusercontent.com route-stubbing, glob boundary bug).

```python
# Pattern: serve the PWA locally, intercept GitHub raw CSV fetches
import subprocess, time
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    server = subprocess.Popen(['python3', '-m', 'http.server', '8080', '--directory', 'docs'])
    time.sleep(1)
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    # Intercept CSV fetches and return local fixture data. Use "**/filename.ext" (slash
    # immediately before the literal suffix) — "**domain**filename" silently never matches.
    page.route('**/snapshots.csv', lambda r: r.fulfill(
        body=open('tests/fixtures/sectors_snapshots.csv').read(), content_type='text/plain'
    ))
    page.route('**/deltas.csv', lambda r: r.fulfill(
        body=open('tests/fixtures/sectors_deltas.csv').read(), content_type='text/plain'
    ))

    page.goto('http://localhost:8080/', wait_until='networkidle')
    # Now assert on rendered cards, tab switching, sort behavior, etc.
    server.terminate()
```

What this lets us test: tab switching, card rendering, sort/filter, movers gainers/losers,
momentum scores, empty-data placeholders, pull-to-refresh state, search filtering — all of
it, headlessly, in cloud.
