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

**Each signal is a first-class metric that can stand alone AND may optionally feed a score —
never ONLY the score.** A blended black-box number is least trustworthy exactly when you most
want to trust it (right before a breakout). Layering:

- **Layer 1 — raw metrics, each individually visible.**
- **Layer 2 — chips/flags** (cheap wins; extend the existing "Coiled" chip family): e.g. Coil,
  Squeeze, NR7, Quiet pullback, Rule-of-Three, Expansion↑.
- **Layer 3 — optional composite "Compression score"** shown NEXT TO its components, tappable to
  decompose — never instead of them. May or may not fold into the existing Focus score (open).

Surfacing targets beyond the score: Picks cards, Lookup cards, Morning cards, Trade tickets.
A metric can also be a **filter/sort** and stand alone as a chip.

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
  - **Expansion / breakout confirmation:** **increased volume** on range expansion / breaking
    **above prior-day highs** (or N-day high). This is the resolution side — "the money event."
    Need exact def (close vs high; RelVol threshold; range-expansion threshold; gap handling).

### 5.6 Squeeze (TTM) — needs computed inputs
- TTM Squeeze fires when Bollinger Bands (SMA20 ± 2σ of price) contract **inside** Keltner
  Channels (SMA20 ± 1.5·ATR). We scrape SMA20 + ATR but **not** BB width / price σ — must compute
  σ from a price-close series. Needs ~20 consecutive closes → per-name data-sufficiency applies
  (§3 graceful degradation, not a population gate). Most "brand-name" compression flag; maps to a
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
5. **Squeeze** BB/σ computation + per-name data-sufficiency handling (§5.6/§3).
6. **52W-high proximity** as apex context — threshold.
7. **Scoring integration** — does the composite fold into Focus score or stay separate; weights;
   keep decomposable.
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
