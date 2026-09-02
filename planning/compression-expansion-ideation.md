# Compression / Expansion — Ideation & Alignment

> **Status:** Ideation (riffing). No code yet. This doc persists the design thinking and the
> owner's feedback from an ephemeral chat session so nothing is lost. Owner = the trader; when
> this doc records a trading-domain judgment, the owner is the authority (per CLAUDE.md
> § "Don't manufacture objections to the owner's idea").
>
> **Two tracked efforts** come out of this (deliberately separate, overlapping files):
> - **Effort A — Card standardization** (Picks/Focus ↔ Morning ↔ Trade ticket ↔ Watchlist)
> - **Effort B — Compression/Expansion metrics**
>
> See § "Two efforts & ordering" for why they're separate and how they interleave.
>
> **▶ Resuming this workstream? Go to §12 "Living task tracker" first** — it's the single source
> of truth for what's built vs. left, the ordering rule, and which subtask is next. §§1–11 are the
> design; §12 is the status board (kept current in the same PR as each subtask).

---

## 1. The idea

Surface **volatility compression** (a stock coiling — range tightening, volume drying up) and
its resolution, **expansion** (breakout / range expansion on volume), inside the product. The
raw material is largely already scraped for free from Finviz.

## 2. What we already scrape (grounded, verified)

Two Finviz scrapes exist; volatility lives only in the ticker-level one:

- **Group snapshots** (`data/{sectors,industries}/snapshots.csv`) — **no volatility columns.**
  Only `perf_*`, `market_cap`, `pe/fwd_pe`, `avg_volume`, `rel_volume`, `change`. A group-level
  vol-ratio would have to be a *synthetic* proxy built from the perf series. **Owner call: group
  vol-ratio is NOT a priority** — looks differentiating but unclear alpha. Deprioritized, not
  killed.
- **Picks "wide" screener** (`scripts/collect_picks.py`, `data/picks/screener_config.json`,
  84 Finviz columns → 114 total in `picks.csv`/`picks_latest.csv`). Already flowing daily:
  `ATR` (id 49), `Volatility W` (id 50), `Volatility M` (id 51), `SMA20/50/200` (52/53/54),
  `High`/`Low`/`Prev Close`/`Open`, `RSI` (59), `Beta` (48), `Gap` (61), `Change from Open` (60),
  `Rel Volume` (64), `Avg Volume` (63), `Volume` (67), `52W High`/`52W Low` (57/58).
- **Already-derived** (`scripts/picks_metrics.py`): `range_atr` = (High − Low)/ATR (single-day
  tightness vs the rolling ATR); `atr_ext_50` = (Price − SMA50)/ATR (rubber-band extension).

## 3. Data history — two stores, different density (verified)

| Store | Density (measured) | Vol columns? |
|---|---|---|
| `data/picks/picks.csv` | Gappy per-name — a ticker only gets a row on days its group was selected. 42 dates, **median 6 sessions/ticker**, 577 tickers ≥7 sessions, 130 ≥20. | Full wide set. |
| D1 `ticker_quotes` (worker-positions) | Dense — held + watchlist names scraped **every** session (17:30 held feed) + FMP seed on add. `raw` col = complete scrape JSON. | Full (via `raw`). |

**Owner correction (important, supersedes an earlier draft):** Do **NOT** restrict time-series
compression signals to held/watch names only. The owner cares about non-held/watch names too.
Many names in Leaders groups get scraped consistently across a 2–3 week span, so most names have
enough history over a two-week window. **Principle: do what we can with the data we have,
per-name — degrade gracefully, do not restrict the population.** Concretely: for a given name and
a given signal, if enough consecutive sessions exist → compute the time-series signal; if not →
fall back to the single-bar signal or hide just that one metric for that name. This is a
per-metric, per-name graceful-degradation rule, **not** a population gate. (The earlier
"single-bar everywhere / time-series only on D1 held-watch" framing was too quick a conclusion
and is explicitly rejected.)

## 4. Surfacing philosophy (owner-endorsed)

### 4.0 GOVERNING PRINCIPLE (owner, 2026-08-30) — facts→flags, judgments→shown values
**Do NOT invent thresholds. Do NOT gate continuous quantities into binary flags. Show the trader
the facts and the raw values; let the trader assess.** A cutoff (RelVol > 1.5, range_atr > 1.5)
throws away information and pre-decides for the trader — the owner explicitly does not want this.
Rule:
- **Factual / genuinely binary** (NR7 = literally the narrowest range of the last 7; higher low;
  price above both MAs; MAs bunched; broke prior-day high) → MAY be a flag, because it states a
  fact, not an opinion. No invented number.
- **Continuous / judgment** (Vol W vs M, RelVol, projected RVol, range_atr, ATR trend) → **SHOW the
  value or the sparkline. Never a cutoff.** The trader reads it and decides.

This dissolves the threshold problem and sets the asymmetry: **compression is the spine** (facts +
shown values, robust/repeatable/proven); **expansion is a lightweight, honest secondary** — surface
the raw break + shown volume/range, do NOT overpromise a "trigger," revisit later (§5.5a).

### 4.1 Layering
- **Layer 1 — raw metrics, each individually visible** (the primary surface; per §4.0 most
  continuous metrics stay HERE, shown, not thresholded).
- **Layer 2 — flags** ONLY for the factual/binary items in §4.0. Extends the existing "Coiled" chip
  family. NOT a home for thresholded judgment metrics.
- **Layer 3 — optional composite score** — LOW priority / maybe never. Only ever shown NEXT TO its
  decomposable components, never instead of them, never as a black box. Owner is wary of blended
  scores; do not lead with this.

Surfacing targets: Picks cards, Lookup cards, Morning cards, Trade tickets — as **shown values**,
plus **filter/sort**, plus flags only where §4.0 permits.

## 5. Signal set (current thinking + owner corrections)

### 5.1 Vol-ratio (Volatility W vs M)
- **Show BOTH raw numbers**, e.g. `Vol W 3.2% / Vol M 4.8%`, not just the ratio. Derive the
  contraction read (W < M = contracting) as a secondary tint/arrow. (Owner: don't hide behind a
  single ratio.)
- Cheap win: also viable as a standalone chip/flag.

### 5.2 VCP (contraction pattern)
- VCP = multi-week pattern: **progressively shallower pullbacks (contractions)**, **range
  tightening**, **volume drying up** into the apex, near highs. Owner's own def: higher lows,
  decreasing volume, range getting smaller, swing highs/lows compressing.
- **Owner correction: "lower highs" is NOT a VCP prerequisite** — that was wrongly added. Drop it.
  It's shallower/tightening pullbacks + volume dry-up, not descending highs.
- We can't detect textbook VCP (needs weeks of swing pivots we may not have per name), but can
  build a **VCP-style contraction proxy**: shrinking successive pullback depth + tightening range
  (rolling `range_atr` / Vol W) + **volume dry-up** (RelVol trending < 1 while price holds) +
  52W-high proximity. Label honestly as "Contraction (VCP-style)", not "VCP detected".
- **Volume dry-up** is the strongest, cheapest sub-signal (owner named it). Have Avg Vol + Vol +
  RelVol daily.

### 5.3 MA convergence — confirmer only, heavily qualified
- **Owner corrections (I had this wrong):**
  - "Converging because price falls into them = breakdown" is **wrong** — price can pull back
    *healthily* into MAs; convergence-into-MA ≠ breakdown.
  - "SMA20/50 converging below price in uptrend = healthy consolidation" is **not an iff** —
    skeptical it's a reliable standalone read. 20 running away from 50 = momentum increasing;
    unclear this cuts cleanly.
- **What we CAN use — "Rule of Three" heuristic:** MAs **bunched up**, still **sloping upward
  (not down)**, price **above both**, and **price/SMA20/SMA50 converging** → price can bounce off
  the bunched MAs as a launchpad. Flag as **potential "Rule of Three"**.
- **Confirmer, not a trigger** (owner agree). Weakest signal of the set; small confirming tick
  inside a setup section, never a headline metric, never scored alone.

**Owner spec locked (2026-09-02) — it's "Power of 3", not "Rule of Three".** Power of 3 is
normally price / 10 / 20 / 50 MAs bunched; **we don't scrape the 10MA, so drop it** (and drop the
200 — it's not the third line of this pattern). The build uses **price / 20MA / 50MA** only.
- **The chip is a fact the OWNER specified — dissolves the §4.0 threshold tension.** It fires when
  price, 20MA and 50MA all sit within a single **2×ATR** band:
  `max(price, 20MA$, 50MA$) − min(price, 20MA$, 50MA$) ≤ 2 × ATR`. The 2×ATR band is the owner's
  own number (the domain authority per §4.0), not an invented cutoff — so a binary chip is
  legitimate here (genuinely-binary fact). Constant `POWER_OF_3_ATR_MULT = 2.0`, triple-documented.
- **Shown alongside the chip:** price's distance to 20MA and to 50MA (Finviz `SMA20`/`SMA50` %),
  so the trader sees *why* it is/isn't bunched.
- **Compute site:** a 6th `METRICS_COLS` entry `power_of_3` in `picks_metrics.compute_pick_metrics`
  (single-bar; reuses the `sma20_price`/`sma50_price`/`ATR` that function already reconstructs,
  right next to `stage2`). NaN when price/either MA/ATR is missing.
- **Render:** a "Power of 3" sub-block in the shared `volSetupSectionHtml` (A-2 seam) → shows on
  Picks + Morning + Watchlist + inherited Ticket at once. On the Morning family it rides the
  picks_latest cross-ref (last night's EOD MA/ATR), same as B-2/B-3 — the morning store carries no
  SMA/ATR, and MAs barely move intraday. Fresh intraday Power-of-3 = a later follow-up (add
  SMA20/SMA50/ATR to the morning `SETUP_COLUMNS`), tracked under WIDE-SCRAPE-FASTFOLLOW (#385).

### 5.4 ATR trend — sparkline for eyes, slope for score
- **Mini sparkline** is the trustworthy human-facing surface (owner: yes). A human reads
  "tightening then popping" off a sparkline and rightly distrusts a lone slope number.
- **Two distinct series, both useful** (owner clarification, correct):
  - **ATR** (Finviz col 49) = 14-day rolling average true range (absolute $). Sparkline shows
    whether *average* range is contracting/expanding (multi-day vol trend).
  - **range_atr** = (High − Low)/ATR = single-day range as a multiple of the rolling avg.
    Sparkline shows day-by-day tightness (which days coiled vs which expanded).
- **LS (least-squares) best-fit slope** only if a *scalar* is needed for sort/score. Reuse the
  existing machinery (`delta_config.py` already computes `rank_trend_slope` / `rs_slope` this way)
  rather than a 2-point (A−B)/days difference, which is endpoint-dominated and lies on a noisy
  series. **Confidence: moderate, and honestly flagged as opaque to the owner.** Treat the slope
  as coarse (sign + magnitude bucket), NOT precise; the sparkline is the source of truth, the
  slope is a convenience scalar. Open question — owner is reasonably skeptical of the black box.

### 5.5 Volume-quality (pullback / expansion) — owner idea
- Not "compression" per se but adjacent and wanted:
  - **Quiet pullback:** down day on **below-average / lower volume** = generally benign (a down
    day is OK if volume is light). Need exact def (down day AND volume < avg? < prior day?
    magnitude threshold).
  - **Expansion / breakout confirmation:** see §5.5a — worked out in detail.

### 5.5a Expansion — SECONDARY, lower-confidence (owner, 2026-08-30)
**Owner posture: compression is the robust/proven half; expansion is more subjective and NOT
nailed down — and that's fine. Proceed cautiously, don't overpromise, revisit.** Do NOT force a
"trigger" or invent thresholds here (§4.0). Surface facts + shown values only.

**The one solid, factual piece already exists.** `scripts/pick_status.py`
`compute_pick_status(trigger=prior_high, stop=prior_low, price, open_, high, low)` is a pure,
tested engine already emitting `triggered` (price ≥ prior high), `gapped_through` (open > prior
high = chase risk), `failed_breakout`, `reclaim`, `invalidated`, `setting_up`. **Broke prior-day
high = a fact** → usable as a flag per §4.0. It has NO volume/range dimension.

**What to SHOW alongside the break (values, NOT thresholded flags):**
- **Volume / projected volume / projected RVol** — owner's idea: extrapolate full-day volume from
  volume-so-far + time-elapsed/time-left, show projected volume AND projected RVol as *values*.
  A shown projection, not a cutoff. (See §5.5b.)
- **range_atr** — SHOWN as a value if useful, NOT as an "expansion buy signal." Owner: a wide-range
  day is not something to act on (wouldn't enter >0.8 ATR off the LoD), so range_atr as a
  breakout-confirm was over-claimed and is dropped as a *signal*; it may still be a shown context
  value. (This corrects the earlier draft.)
- **gap context** — engine already separates `gapped_through`; show it as context (gap-up = higher
  chase-risk), not a disqualifier.

**OPEN, deliberately unresolved (owner uncomfortable forcing this):** what "the breakout" even is
(prior-day high vs N-day high vs pivot). Not simple; do not promise. Park it, revisit with data.

**Intraday vs EOD — the real fork (data consequence):**
- **Canonical = EOD derived signal.** On the wide picks/held scrape RelVol + range_atr +
  prior/N-day high are all clean. Compute as a derived column in the picks pipeline. Recommended.
- **Morning/intraday = provisional only.** The morning block scrapes **Volume but NOT Avg/Rel
  Volume** (9-col config) — so an intraday volume read means cross-ref'ing prior-day Avg Volume
  from `picks_latest`, AND intraday volume at 10:05 is *partial-day* so it understates vs a
  full-day avg. **⚠️ UNVERIFIED, must check before relying on it:** whether Finviz "Rel Volume" is
  time-of-day normalized. If yes, intraday RelVol is meaningful; if no, morning volume is noise.
  Do NOT build the morning volume signal on this assumption — verify against live intraday data
  first. Morning card can show the *price* break (existing engine) provisionally regardless.

**Composition** — a move IN ISOLATION is just a move; a break preceded by a coil (NR7 in the prior
few sessions) is more meaningful. Show "was compressed in the last N days, then broke" as context.
Do not oversell it as a single composite trigger (§4.0).

### 5.5b Projected volume / projected RVol (owner idea, 2026-08-30)
Intraday, extrapolate the full-day volume from volume-so-far, time-elapsed and time-left, and show
**projected volume AND projected RVol as VALUES** on the morning card. A shown projection, not a
threshold. Not claimed perfect — a display aid for the trader to assess. Fits §4.0 exactly.
- Data note: the 10:05 morning store carries raw `Volume` but **not** Finviz `Rel Volume`, so prior
  morning snapshots can't by themselves settle whether Finviz RVol is time-of-day normalized — check
  on a live trading day (Sunday when raised). Projected RVol would use prior-day Avg Volume from
  `picks_latest` as the denominator regardless.

### 5.6 Squeeze (TTM) — DROPPED (owner, 2026-08-30)
Owner asked to explain TTM/NR7 as concepts; Claude then over-promoted squeeze into the signal set
and kept carrying it = scope creep off the original plot. **Dropped.** NR7 (range_atr) already
captures "coiling" cheaply from columns we have; squeeze added a σ-computation dependency and a
20-session-history requirement for marginal gain. Not in scope. (Original detail, for reference
only, do not treat as planned work:)
- TTM Squeeze fires when Bollinger Bands (SMA20 ± 2σ of price) contract **inside** Keltner
  Channels (SMA20 ± 1.5·ATR). We scrape SMA20 + ATR but **not** BB width / price σ — must compute
  σ from a price-close series. Needs ~20 consecutive closes. Maps to a
  "Squeeze on / fired" chip.

### 5.7 NR7 / NRn
- NR7 = today's High−Low range is the narrowest of the last 7 sessions (NR4 = 4-day). Crudest
  single-bar-in-context coil flag; expansion trigger = next day breaks the NR7 bar's high/low.
  Open: which range definition (H−L absolute, true range incl. gaps, or `range_atr`).

## 6. Concept explainers (persisted for reference)

- **TTM Squeeze** — Bollinger-inside-Keltner compression detector (the "red dots"); fires on the
  pop back outside. See §5.6.
- **NR7** — Narrowest Range in 7 days. See §5.7.
- **VCP** — Volatility Contraction Pattern; shallower pullbacks + tightening range + volume
  dry-up near highs. NOT lower highs. See §5.2.

## 7. Card standardization (Effort A) — audit findings

**Five distinct per-ticker card schemas today** (not three), via subagent audit of
`docs/index.html`:

1. **Picks/Focus card** (`renderPickRow`, ~4538) — rich: ATR-ext, RSI, Perf W/M, %>50MA,
   Avg $ Vol, Earnings, Focus score, Ariel badge, launch chip. Also used in Lookup Stage-2.
2. **Morning card** (`morningCardBody`/`renderMorning`, ~5280/8202) — minimal: trigger, price,
   ATR-from-LoD, status pill, launch chip. **Missing** RSI, Perf W/M, %>50MA, Avg $ Vol,
   Earnings, Focus, Ariel.
3. **Trade ticket** (`ws4TicketHtml`, ~5580) — an **expansion of the morning card** (owner's
   framing); re-derives ATR-ext + earnings + focus via a THIRD code path (`ws4FocusScore`,
   `deriveRiskMetrics`).
4. **Watchlist card** (`watchCardHtml`, ~8012) — **lives in the Morning tab; owner considers it
   the same family as the morning card** (should share its schema + carry the trade ticket).
5. **Positions/managing card** (~6239) — different lifecycle vocabulary (R-multiple/P&L);
   arguably out of scope for "which pick am I looking at."

**Owner's grouping:** Morning card + Watchlist card + Trade ticket are one family (ticket =
morning-card expansion); Picks/Focus card is the other. Standardize so a field looks the same and
sits in the same place across them.

### 7.1 Root cause of the divergence (data, not just display) — VERIFIED
The Morning card is minimal because **`collect_morning.py` scrapes only the thin `morning`
screener config (9 columns: trigger/price/ATR/low), not the wide 84.** The morning session store
(`data/picks/sessions/morning_latest.csv`) physically lacks RSI/Perf/Vol/Ariel — so "just render
the picks fields" can't work off the morning store alone.

### 7.2 Cross-reference-at-render — tested, only PARTLY holds
Claim was: join the morning ticker back to the already-loaded `picks_latest.csv` row client-side
(the PWA already does this via `ws4FindPicksRow`). **Verified:** `picks_latest.csv` has all 114
cols, but **18 of 123 morning tickers are NOT in `picks_latest`** (~15%: AMD, ALAB, ARXS, BAX,
OSCR, TSEM, …) — watchlist adds / setting-up names not in last night's EOD picks run. So cross-ref
covers ~85% for free; ~15% render blank.

### 7.3a A-1 verification (2026-09-01) — findings + recommendation
Verification the doc §7.3 asked for, done. **Recommendation: scrape-wide (path a).**

**Cost of scrape-wide is near-zero (the doc's feared downside does not hold).**
`collect_morning.py::fetch_ticker_quotes` (`build_ticker_url`, lines ~138-211) scrapes a
`t=`-filtered ticker list, batched ≤50/URL (`MORNING_BATCH_SIZE=50`), paginated 20 rows/page.
The number of `page.goto()` calls — i.e. the Cloudflare surface — is driven **entirely by ticker
count, not column count**. Morning universe = Focus top-100 + watchlist union (min22/median95/
max100 names/day) → ≤2 batches. Switching the morning block from 9 cols to a wide 84-col block
changes only the `c=` URL param: **identical goto count, identical Cloudflare exposure**, only a
larger HTML payload per page. The 84-col `t=`-filtered scrape is already proven in prod —
`build_ticker_url(..., block="held")` does exactly this for the WS5 held feed.

**Cross-ref coverage is worse than the doc's ~15% estimate.** Measured on 2026-08-31 data:
morning **33.6% orphans** (42/125), pre-close **21%** (21/100). Orphans = watchlist adds +
setting-up names not in last night's EOD picks run. Cross-ref would leave ~⅓ of morning cards
blank on the volatility/setup section — disproportionately the pre-open action surface.

**What each B section needs (verified present in `picks_latest.csv`):**
- B-1 (raw scraped): `RSI`, `Volatility W`, `Volatility M`, `Rel Volume`, `52W High`. Scrape-wide
  provides these **fresh this-morning**; cross-ref provides last night's (fine for multi-day, staler
  for RSI/RelVol).
- B-2 (derived in the *picks* pipeline, NOT scraped): `tight_range_7`, `range_atr_spark`,
  `atr_spark`. These come via **cross-ref regardless** — they're trailing/multi-day, so last night's
  values are current enough; orphans have no picks history so they'd be blank under *any* path.

**Existing join is already built + loaded:** `ws4FindPicksRow(ticker)` (exact-string match on
`Ticker||ticker`), and `state.picksData` (picks_latest) is already resident on every render via
`loadPicks()` — no new fetch needed for the cross-ref half.

**Net recommendation:** scrape-wide the morning run for the B-1-family raw columns (100% coverage,
fresh, ~zero extra Cloudflare cost, reuses proven `held` machinery); keep cross-ref to picks_latest
for the B-2 derived sparkline columns (multi-day, no benefit from re-scraping). This matches the
owner's stated §7.3 preference ("wants full 84 cols … prefers (a) if no blocking downside") now that
"no blocking downside" is verified.

### 7.3 Owner decision on morning data
**Owner wants the full 84 columns available on morning cards.** Two ways, to be decided:
- **(a) Scrape the wide 84 in the morning run** — if no blocking downside, owner wants this.
  Downsides to weigh: slower morning scrape, more Cloudflare exposure, redundancy (EOD picks
  already has these; they barely move intraday except price). NOT yet confirmed there's no
  blocking downside — verify before committing.
- **(b) Seed from prior-day data** — cross-ref `picks_latest` for the ~85%, and backfill the
  ~15% orphans from D1 `ticker_quotes` / a prior picks snapshot.
- Likely hybrid: cross-ref where present, fill the gap for orphans; scrape-wide only if (a) proves
  free of blocking downside. **Open — do not champion one without verifying downsides.**

## 8. Two efforts & ordering

- **Effort A — Card standardization**: define ONE shared card component/schema (superset fields,
  consistent ordering/section grouping incl. a "Setup/Volatility" section) reused across the
  Picks-family and Morning-family cards. Mostly a client-side join + shared component + the §7.3
  data decision; NOT necessarily a pipeline change.
- **Effort B — Compression/Expansion metrics**: add the §5 signals to that shared component.
- **Soft ordering:** A's shared-component seam should exist before B's metrics land, or B
  hand-adds chips to 3+ diverging code paths and deepens the drift. Tracked separately (owner's
  choice) because B also touches the held/watch (Positions/Watchlist) card family and the D1 side,
  which A's picks↔morning work doesn't. Overlap in files, not in scope.

## 9. Its own tab/list?
Not a tab yet (a tab implies a scan population; ours is already defined). Prefer: a **filter/sort**
on existing lists + a **"Setup/Volatility" section within cards**. A future transient **"Triggers
today"** list (names where compression just fired / expansion event) is the one thing that might
justify its own small, time-sensitive list — phase 2.

## 10. Open riff threads (signal set not yet nailed)
1. **Expansion/trigger side** under-specified — exact breakout-confirmation def (close vs prior/
   N-day high, RelVol threshold, range-expansion threshold, gap handling).
2. **Quiet-pullback** exact definition (§5.5).
3. **Volume dry-up** metric definition for the VCP proxy (RelVol trend window/threshold).
4. **NR7 range definition** (§5.7).
5. ~~Squeeze~~ — DROPPED (§5.6).
6. **52W-high proximity** as apex context — SHOWN as distance-from-52W-high value, not a threshold.
7. **Scoring integration** — LOW priority / maybe never; owner wary of blended scores (§4.1 L3).
8. **Config constants** — every threshold triple-documented per repo rule (in-code + README +
   CLAUDE.md).
9. **Graceful degradation** mechanics per-metric/per-name (§3) — the concrete "enough sessions?"
   gate per signal.
10. **Eval** — do these signals predict forward returns? `evaluate_picks.py` scaffolding exists.

## 11. Owner feedback log (verbatim intent, persisted)
- Group vol-ratio: not a priority; differentiating but unclear alpha.
- **Do NOT restrict to held/watch names.** Cares about non-held/watch too; Leaders groups give
  ~2-3wk history for most names. Do what we can with the data; don't gate the population; don't
  make premature restrictive conclusions ("dangerous and restrictive").
- VCP: "lower highs" was wrongly added — not a prerequisite.
- MA convergence: my breakdown/consolidation framing was wrong; not iff; healthy pullbacks into
  MAs exist. Salvageable as "Rule of Three" (bunched, up-sloping, price above both, converging).
  Confirmer not trigger.
- Sparkline yes; ATR (rolling avg) and range_atr (single-day vs avg) are different, both useful.
- LS slope: acceptable but opaque to owner; low-moderate trust; keep the sparkline primary.
- Each signal should stand alone / be visible, not only a black-box score input.
- Chips/flags are cheap wins (extend the Coiled-chip family).
- Standardize Picks card ↔ Morning card; watchlist card = morning family; ticket = morning-card
  expansion.
- Wants full 84 cols on morning cards — scrape them or guarantee prior-day availability; verify
  before championing cross-ref.
- Verify assumptions and double-confirm before championing to the owner.

### 2026-08-30 (course-correction — owner frustrated/overwhelmed; recentered)
- **DO NOT invent thresholds / cutoffs.** Asking the owner to assign RelVol 1.5/2.0 or range_atr
  1.5 was the core frustration — those aren't knowable facts, and a binary cutoff is itself wrong
  (throws away info, pre-decides for the trader). SHOW the value, let the trader assess. → §4.0.
- **Facts→flags, judgments→shown values** is now the governing principle.
- **range_atr is NOT an expansion buy-signal** — owner wouldn't enter >0.8 ATR off the LoD, so a
  wide-range day isn't actionable; over-claimed. Demoted to a possible shown-context value only.
- **Squeeze DROPPED** — Claude introduced it (owner only asked to *explain* it) and kept carrying
  it = scope creep off the original plot. Out of scope. → §5.6.
- **Compression is the spine** (robust, repeatable, proven, facts-only). **Expansion is secondary
  and subjective — proceed cautiously, don't overpromise, revisit.** Owner explicitly less
  confident in expansion; the "what is the breakout" question is genuinely hard and is PARKED, not
  forced. → §5.5a.
- **Projected volume / projected RVol** (extrapolate full-day from time-of-day) is a wanted SHOWN
  value, not a threshold. → §5.5b.
- Owner asked Claude to summarize their thoughts/feelings to confirm understanding before
  proceeding — signal that the riff had drifted from first principles and added mental load.
- Owner may close the session anytime → keep everything committed at every step.

---

## 12. Living task tracker (single source of truth for progress)

> **Read this section FIRST when resuming the workstream in a new session.** It maps every part
> of the plan above to a status and the PR that moved it. The doc §§1–11 are the *design*; this
> section is *what's built vs. left*. Update it in the SAME PR as any subtask — never let progress
> live only in a PR description or chat (that's how work gets orphaned).
>
> **The A/B split is unchanged.** Effort A = card standardization (issue #378). Effort B =
> compression/expansion metrics (issue #379). We are NOT re-splitting; slices below are just the
> ordered pieces *inside* each effort.
>
> **Status key:** ✅ done · 🔨 in progress · ⏳ next up · ⬜ not started · 🅿️ parked (needs owner/verify) · ❌ dropped

### Ordering rule (why the next subtask is what it is)
1. **Compression before expansion** — compression is the spine (facts, proven); expansion is
   secondary/subjective and mostly 🅿️ parked (§5.5a). Don't build expansion "triggers."
2. **Effort A's shared-card seam should exist before Effort B metrics spread to 3+ cards** (§8).
   A single-card B slice (Picks only) is safe and does NOT trip this — that's why B-1 went first.
   The moment a B metric needs to appear on Picks AND Morning AND Lookup, the A seam must exist.
3. **No invented thresholds, ever** (§4.0). A slice that would need the owner to pick a cutoff is
   mis-scoped — show the value instead.
4. **Graceful degradation, not population gating** (§3). A time-series slice ships with a
   per-name "enough sessions?" fallback, never a held/watch-only restriction.

### Effort B — compression/expansion metrics (issue #379)
| ID | Slice | Doc ref | Status | PR / notes |
|----|-------|---------|--------|------------|
| B-1 | "Volatility & setup" section on Picks card — Vol W/M, RelVol, 52W-high dist (shown values) | §5.1, §10.6 | ✅ | **PR #380** (merged). Picks card only. Contracting/expanding tint = sign of (VolW−VolM), a fact. |
| B-2 | Tightest-range flag + range_atr/ATR sparkline (range tightening) — derived pipeline columns, per-name history w/ graceful degrade | §5.4, §5.7, §3 | ✅ | **PR #383**. 3 new `TRAILING_COLS` in the picks pipeline (`tight_range_7`, `range_atr_spark`, `atr_spark`), computed over trailing available bars, populated only on the picks_latest slice. Picks card "Range tightening" block: honest "Tightest range · last 7 bars" flag (owner 2026-08-31: NOT "NR7" — gappy history) + two mini sparklines. Graceful per-name degrade. |
| B-3 | Volume dry-up sub-signal for VCP proxy (RelVol trend while price holds) | §5.2, §10.3 | ✅ | **PR (this session).** New 4th `TRAILING_COLS` col `relvol_spark` (pipe-joined trailing Rel Volume series, same trailing-window/graceful-degrade machinery as B-2's sparks — window is `SPARK_WINDOW`, not a new constant). Picks card "Volume dry-up" sub-block under the B-1 "Volatility & setup" section renders it via the existing `volSpark()` helper (a SHOWN trend, doc §4.0 — no threshold, no flag). Migration backfilled 487/535 latest rows. Composes into B-4. |
| B-4 | VCP-style contraction proxy — shrinking pullback depth + tightening range + vol dry-up + 52W-high proximity. Label "Contraction (VCP-style)", never "VCP detected" | §5.2 | ⬜ | Composes B-2 + B-3. NOT "lower highs". |
| B-5 | **Power of 3** MA-bunching chip + shown MA distances — price/20MA/50MA within a 2×ATR band | §5.3 | 🔨 | **In progress (this session).** Owner-renamed "Power of 3" (not Rule of Three); price/20/50 only (no 10MA scraped, 200 dropped). Chip = single fact `spread(price,20MA$,50MA$) ≤ POWER_OF_3_ATR_MULT(2.0)×ATR` — owner-set band, §4.0-clean. New 6th `METRICS_COLS` col `power_of_3`; renders via shared `volSetupSectionHtml` (all card families). |
| B-6 | Propagate the "Volatility & setup" section (B-1 + B-2 + B-3) to Lookup + Morning + Ticket cards | §4.1, §8 | ✅ | **PR (this session).** Renders the shared `volSetupSectionHtml` (A-2 seam) on morning picks cards (`morningCardBody`, all live statuses) + watch cards (`watchCardHtml`), via `setupRowForCard(ticker, freshRow)` = picks_latest cross-ref (B-2/B-3 sparklines) + morning-store fresh B-1 override. Trade ticket inherits it from the morning card (no duplicate render). Lookup Stage-2 already had it (reuses `renderPickRow`). Owner-approved mock: `planning/mocks/b6-morning-volatility-setup.html`. 2 morning + 1 watch PWA tests. Release `2026.09.02` / sw.js v91. |
| B-7 | Optional composite score (decomposable, shown next to components) | §4.1 L3, §10.7 | 🅿️ | LOW priority / maybe never. Owner wary of blended scores. Do not lead with this. |
| B-8 | Forward-return eval of the signals (does compression predict?) | §10.10 | ⬜ | Reuse `evaluate_picks.py` scaffolding. Do after ≥1 signal has history. |
| B-X | Expansion side (projected vol/RVol §5.5b; break+coil context §5.5a) | §5.5, §5.5a, §5.5b | 🅿️ | Secondary/subjective per owner. Facts+shown-values only, no "trigger." Revisit later. |

### Effort A — card standardization (issue #378)
| ID | Slice | Doc ref | Status | PR / notes |
|----|-------|---------|--------|------------|
| A-1 | **Decide morning-card data path**: scrape-wide-84 vs cross-ref `picks_latest` (~85%) + D1 orphan backfill (~15%) | §7.3 | ✅ | **DECIDED 2026-09-01: scrape-wide (owner greenlit).** Verification in §7.3a. Cross-ref orphan rate worse than doc's ~15% (measured 2026-08-31: morning **33.6%**, pre-close **21%**). Scrape-wide cost is near-zero (`fetch_ticker_quotes` goto-count = ticker count, not column count; 84-col `t=` scrape already runs in prod as `block="held"`). Implementation = widen the morning/pre_close scrape to the wide column set + superset-additive session-store schema (next slice A-1-IMPL). B-2 derived sparkline cols still come via cross-ref (multi-day). |
| A-1-IMPL | **Widen the morning/pre_close scrape to the 84-col block + carry setup columns into the session store** (the pipeline realization of A-1) | §7.3a | ✅ | **PR (this session).** `collect_morning.py`: `WIDE_SCRAPE_BLOCK="held"` (84-col, reuses the proven held config), `SETUP_COLUMNS` (`RSI`, `Volatility W`, `Volatility M`, `Rel Volume`, `52W High`) carried through verbatim into `STORE_COLUMNS` (superset-additive). No PWA render yet (that's B-6). Live values land on the next Actions morning run; committed store CSVs stay old-schema until then (write_store backfills "" — no manual migration). |
| A-2 | Extract ONE shared card component/schema (superset fields + a "Setup/Volatility" section) reused across Picks-family and Morning-family | §7, §8 | ✅ | **PR (this session).** Extracted the "Volatility & setup" section (B-1 + B-2 + B-3) out of `renderPickRow` into one shared `volSetupSectionHtml(r)` in `docs/index.html`. **Pure refactor — Picks card renders byte-identically** (its 9 PWA tests green). Returns '' when a row has nothing to show (graceful degrade for morning orphans). This is the seam B-6 rides on. |
| A-3 | Apply the shared component to Morning card, Watchlist card, Trade ticket (the Morning family) | §7 | ✅ | **Realized by B-6** (same PR): `volSetupSectionHtml` now renders on the morning picks card, the watch card, and (inherited) the trade ticket. This is the "Setup/Volatility" section slice of A-3; the fuller card-schema superset (RSI/Perf/Avg$Vol/Earnings) is future Effort-A work, not required to unblock the compression spine. |

### Cross-cutting follow-ups (not scoped to a single effort)

| ID | Slice | Status | PR / notes |
|----|-------|--------|------------|
| WIDE-SCRAPE-FASTFOLLOW | **Scope which of the remaining 84 wide-scrape columns are worth storing** (SMA20/50/200, 52W Low, Beta, Gap, Change from Open, Earnings date, EPS/Revenue Surprise, Recom, Target Price, News) | ⬜ | Issue #385, PR #384 review finding, 2026-09-01. PR #384 made the morning/pre_close scrape wide (84 cols, `held` block) at ~zero extra `page.goto` cost, but only 5 columns (`SETUP_COLUMNS`) are carried into the store. **Deliberately NOT filed under Effort A** — card rendering (A-2/B-6) is one consumer, but Earnings/EPS/Revenue-Surprise and the SMA columns are equally relevant to WS4's trade-ticket earnings guardrail and WS5's `advance()` engine (earnings-approach overlay, reclaim-ref 50MA derivation), which have nothing to do with card display. Not a mandate to store all 84 — a scoping pass, low priority, no urgency. |

### Dropped / not in scope
| Item | Doc ref | Status |
|------|---------|--------|
| TTM Squeeze | §5.6 | ❌ Dropped (scope creep; NR7 covers coiling cheaply). |
| range_atr as an expansion buy-signal | §5.5a | ❌ Dropped as a signal (may remain a shown-context value only). |
| Group-level vol-ratio | §2 | 🅿️ Deprioritized (differentiating but unclear alpha). |
| "lower highs" as a VCP prerequisite | §5.2 | ❌ Wrong; removed from the design. |

### Progress log (newest first)
- **2026-09-02 — B-6 done (compression section on the Morning family) + A-3 realized.** Owner
  approved the mock and said "wire it into the morning family." Added `setupRowForCard(ticker,
  freshRow)` (picks_latest cross-ref for B-2/B-3 sparklines + fresh morning-store B-1 override) and
  rendered `volSetupSectionHtml` on `morningCardBody` (all live statuses, after the metric rows,
  before ticket/CTA) and `watchCardHtml` (after the body). The trade ticket inherits it from the
  morning card (no duplicate). Lookup Stage-2 already had it via `renderPickRow`. Graceful degrade:
  orphans with no picks history + no fresh scrape show no section. Tests: 2 new morning PWA
  (`test_volatility_setup_section_on_morning_card`, `..._hidden_for_orphan`) + 1 watch PWA
  (`test_watch_card_shows_volatility_setup_section`); also added a `pre_close_latest.csv` stub to
  `test_pwa_morning.py::_open_morning_tab` so that file runs in the cloud sandbox (was hanging on
  the unreachable domain). Release `2026.09.02` (feature, tab morning) / sw.js v90→v91. This closes
  A-2/A-3/B-6 — the compression spine now reaches the pre-open workflow. **Next: B-5 (MA bunching /
  Rule-of-Three, the last named spine item) or B-4 (compose the VCP-style proxy).**
- **2026-09-02 — A-2 done (shared card seam) + B-6 mock for owner review.** Owner chose the
  strategic A-2→B-6 lever over the contained Picks-only spine slices (B-4/B-5) for this fresh
  session. **A-2:** extracted the "Volatility & setup" section (B-1 Vol W/M·RelVol·52W + B-2 range
  tightening + B-3 volume dry-up) from `renderPickRow` into one shared `volSetupSectionHtml(r)` in
  `docs/index.html` — a pure refactor, Picks card byte-identical (9/9 PWA green). The function
  returns '' when a row has nothing to show, so a morning orphan self-hides (graceful degrade §3).
  **B-6 (pending owner green light):** built a real-data before/after mock of a Morning CAH card
  with the section (`planning/mocks/b6-morning-volatility-setup.html`, published as an Artifact).
  B-6 will render the identical section on Morning picks / Watchlist / Trade-ticket cards — B-1 raw
  cols fresh from the A-1 scrape-wide morning store, B-2/B-3 sparkline cols via `ws4FindPicksRow`
  cross-ref to picks_latest. **Next: on approval, wire B-6 into the Morning family + release triplet.**
- **2026-09-01 — B-3 done (volume dry-up).** Chose B-3 over A-2→B-6 this session: it moves the
  compression spine with an owner-named fact, is a contained single-card slice (ephemeral-session
  safe, no A dependency, doesn't trip ordering rule #2), and B-6 propagates the whole "Volatility &
  setup" section at once regardless of how many signals live in it — so landing B-3 first is free.
  Implementation mirrored B-2 exactly: 4th `TRAILING_COLS` col `relvol_spark` (trailing Rel Volume
  series via the same `compute_trailing_setup` machinery, reusing `SPARK_WINDOW`/`SPARK_MIN_BARS` —
  no new constant, nothing to threshold per §4.0), a "Volume dry-up" sub-block in `renderPickRow`
  via the existing `volSpark()` helper. Migration backfilled 487/535 picks_latest rows. 1 new unit
  test + extended the B-2 PWA test (3 polylines, "Volume dry-up" present); 737 non-PW green, PWA test
  green (chromium-1234). Release `2026.09.01` / sw.js v89→v90. **Next: A-2** (extract the shared card
  component from B-1's layout) → **B-6** (propagate B-1/B-2/B-3 to the Morning family). A-2 is the
  strategic next lever (cashes in A-1) but is a cross-card refactor better suited to a fresh session.
- **2026-09-01 — A-1 decided + A-1-IMPL done.** Verification (§7.3a) showed cross-ref orphan rate
  worse than the doc's ~15% (morning 33.6%, pre-close 21% on 2026-08-31) and that scrape-wide's
  feared cost is near-zero (goto count = ticker count, not column count; 84-col `t=` scrape already
  in prod as `block="held"`). **Owner greenlit scrape-wide.** Implemented: `collect_morning.py`
  scrapes the 84-col `held` block (`WIDE_SCRAPE_BLOCK`) for morning/pre_close and carries
  `SETUP_COLUMNS` (RSI, Vol W/M, Rel Volume, 52W High) into the session store (superset-additive).
  1 new unit test; 736 non-PW suite green. 3-places doc'd. **Next: A-2** (extract the shared card
  component from B-1's layout) → then **B-6** (render B-1/B-2 on the Morning family, B-1 from the
  fresh morning store, B-2 via cross-ref). B-3 (volume dry-up) remains the alternative Picks-only
  spine slice if the owner prefers to keep single-card momentum first.
- **2026-08-31 — B-2 done (PR #383).** Range tightening on the Picks card. Pipeline: 3 new
  `TRAILING_COLS` in `picks_config.py` (`tight_range_7`, `range_atr_spark`, `atr_spark`) +
  `picks_metrics.compute_trailing_setup()` (pure, trailing-window over a ticker's *available*
  bars, dedups same-date multi-bucket rows), wired into `collect_picks.write_picks` +
  `ensure_picks_csv` backfill; populated only on the max-date picks_latest slice (older rows "").
  PWA: "Range tightening" block in the B-1 "Volatility & setup" section — honest "Tightest range ·
  last 7 bars" flag (owner call: gappy history → NOT "NR7") + `volSpark()` mini sparklines for
  range/ATR and ATR $. Graceful per-name degrade (`SPARK_MIN_BARS`=3; flag needs 7 bars). New
  constants `TIGHT_RANGE_WINDOW`/`SPARK_WINDOW`/`SPARK_MIN_BARS` triple-documented. Release
  `2026.08.31.1` / `sw.js` v88→v89. Tests: 4 unit (`compute_trailing_setup`) + 1 PWA. Next: **B-3**
  (volume dry-up) — or reconsider A-1 if the owner wants to unblock the Morning-family propagation.
- **2026-08-31 — B-1 done (PR #380).** "Volatility & setup" section on the expanded Picks card:
  Vol W/M, RelVol, 52W-high distance, all shown values; contracting/expanding tint = sign of
  (VolW−VolM). No pipeline change, no new constant. Reference layout for A-2. Next: **B-2**.
