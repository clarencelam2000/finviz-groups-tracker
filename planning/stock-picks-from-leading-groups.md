# Plan: Top-stock picks from leading groups (Stage-2 screener pipeline)

> Status: **READY TO EXECUTE.** All major decisions VP-confirmed (2026-06-23 + 2026-06-24).
> Phase-1.5 spike COMPLETE (2026-06-24) — selector policy locked (see §Spike results).
> Completed tasks before Phase 2 starts: (1) DONE - Phase-1 probe run on GitHub Actions — validate 84-col
> anon fetch on one large industry (Semiconductors) + measure real daily fetch count;
> (2) DONE - VP sign-off on the real fetch number.

## Context & thesis

The existing pipeline tracks **group** rotation (sector/industry rank, momentum, RS vs SPY)
but stops at the group boundary. The product gap: a user sees "Aerospace & Defense is a
sustained-strength leader" and has no path to the *individual Stage-2 names inside it*.

**Thesis (Ariel Hernandez / O'Neil / Minervini):** a strong stock in a strong group, in a
confirmed Stage-2 uptrend, not over-extended from its 50SMA, with decent fundamentals and a
tight stop, is a high-expectancy swing setup. We already identify the strong *groups*. This
feature surfaces the strong *stocks* inside them, **tracks those lists daily**, and — later —
runs **attribution** to learn which group-selection methodology and which stock metrics
actually picked winners.

**Why now / why collection-first:** the daily picks list has *option value we can never
backfill*. Group membership on a given day and the point-in-time Finviz technicals (RSI,
%-from-50SMA, rel-vol that day) are gone if we don't log them. Forward price paths are far
less fragile: because the v=151 view includes the **Price** column (D5), every day a name is
in the screen we already capture its close, so in-screen forward returns are reconstructable
from our own log with no external dependency. Only names that have *exited* the screen need a
historical-close backfill, and free OHLC sources exist for that (Stooq, yfinance, Tiingo).
So the irreplaceable work is **starting the daily capture**, not the analysis — the analysis
is a later session.

> **Correction (staff review 2026-06-23):** an earlier draft said forward closes were
> "FMP historical, already wired." That is **not** true — the only FMP integration is the
> Worker's `/stable/profile` lookup, and `backfill.py` explicitly states automated historical
> backfill is unsupported (FMP's historical EOD endpoint is also paywalled for new free keys).
> Treat exited-name backfill as a **Phase-4 spike against a free OHLC provider**, not an
> existing capability.

## Decisions (VP-confirmed 2026-06-23)

| # | Decision | Choice |
|---|----------|--------|
| D1 | First slice | Build the **EOD scrape pipeline first** (irreplaceable data) + ship the deep-link button in the same effort. No phase-0 gate. |
| D2 | Group coverage | **Selected leading groups only**, not all 144. Categories below. Button still available for ALL 144. |
| D3 | List categories | **Leaders + emerging (core)**, **Accelerating momentum**, **RS-new-high confirmed** — with a baseline-strength floor on the latter two (see §Selectors). |
| D4 | Stock screen | **Wide net, filter in-house.** VP supplies canonical Finviz URL(s). Don't bake tight filters into the URL; store wide, tune filters in our pipeline. |
| D5 | Stored columns | **Full `v=151` custom view (~84 columns — VP-supplied `c=` list, see §VP URL handoff)** — maximally future-proofs attribution. **Pin the explicit ordered `c=` list in config, never rely on the bare saved view** — saved-view membership is account/cookie-bound and can drift, which would corrupt an append-only fixed-header CSV. |
| D6 | List size | **Store ALL qualifiers per group** (breadth = count of qualifiers is its own signal). Requires Finviz pagination (`&r=` offset; ~20 rows/page). |
| D7 | Scrape job | **Separate GitHub Actions workflow** (`collect_picks.yml`), **independent cron + concurrency guard** (VP-confirmed). Own EOD trigger scheduled *after* `collect.py`. Isolates failure domains; the concurrency group + rebase-before-push + a "deltas are today's" assertion prevent commit races / stale reads (see §Finviz scraping notes). |
| D8 | PWA surface | **Both:** standalone **"Picks" tab** (cross-group destination) + a per-group **"Stage-2 names →" section inside the Lookup tab** (contextual, when an industry is pulled up). No generic-card surface. |
| D9 | Attribution schema | **Membership-only, append-only event log** (`picks.csv`, one row per stock × list × day). Entry/exit/forward-returns are derived OFFLINE later (Option C hybrid view), never hand-maintained. |
| D10 | TwelveData / extended indicators | **Deferred.** Finviz's custom view already serves SMA distances, 52w-high distance, ATR, RSI. Optional spike later (§Deferred). |
| D11 | Stored-net breadth + fetch budget | **Store wide (generous superset, relaxed trend gates), tag Stage-2 in-house — bounded & explicitly NOT long-term** (VP accepted cautiously 2026-06-23). Keep `sh_avgvol_o100` liquidity floor, hard per-group + global fetch caps (~120/day), Phase-1 volume probe, Phase-4 sunset back toward the tight net. Honest volume ~60–120 fetches/day. See §Fetch-volume budget & guardrails. |

## Architecture

```
collect.py (existing, EOD)
   └─> data/industries/deltas.csv  ──┐
                                      │ (group selectors read this)
collect_picks.py (NEW, separate EOD workflow)
   1. select_groups()      reads latest deltas.csv → leading/emerging/accel/RS-NH groups
   2. for each selected group:
        build screener URL from screener_config.json (base f= + ind_<slug> + ordered c=)
        scrape ALL pages (Playwright, paginate &r=) → ~84-col rows
   3. append to data/picks/picks.csv  (one row per stock × list_category × day)
   4. rewrite data/picks/picks_latest.csv (max-date slice → PWA fetches this)

config:   data/picks/screener_config.json     (modular URL: f=, c=, v/o/ft — VP-editable)
slug map: data/picks/finviz_industry_slugs.csv  (144 rows, derived from snapshots.csv — no live Finviz validation)

PWA:
   - Picks tab: read picks_latest.csv grouped by list_category → group → stocks
   - Lookup tab: when an industry is shown, render its Stage-2 names + Finviz deep-link

(LATER, offline) eval_picks.py: membership log → positions view → forward returns vs SPY+group
```

### Data layout

```
data/picks/
  picks.csv                    # append-only; date, list_category, selector_version, group, ticker, <84 finviz cols>, <group-metric values at selection>
  picks_latest.csv             # latest trading date only — what the PWA fetches (see PWA note)
  finviz_industry_slugs.csv    # industry_name, ind_slug, validated (bool), note
  screener_config.json         # modular URL config (base f= filters, ordered c= columns, v/o/ft) — see §VP URL handoff
```

> **PWA fetch size (VP-confirmed: per-date latest artifact).** `picks.csv` is the full
> append-only log (~20 groups × ~40 names × 84 cols/day → multi-MB within weeks) and is for
> offline attribution only. `collect_picks.py` also writes a small **`picks_latest.csv`**
> (current trading date only) that the PWA fetches from `raw.githubusercontent`, so the app
> never downloads full history. Tracked as a non-blocking open question below (rotation/LFS for
> the growing log).

`picks.csv` uniqueness key: `(date, list_category, ticker)`. A stock can appear under
multiple categories on the same day (e.g. both `leaders` and `accel`) — that's intentional;
keep both rows so per-category attribution is clean. Dedup/last-write-wins per that key,
mirroring `collect.py`.

## Group selectors (D3) — with the anti-flash floor

Read the latest `data/industries/deltas.csv`. For each category, select groups and tag the
rows written to `picks.csv` with `list_category`:

| Category | Primary signal | **Baseline-strength floor (anti-flash)** |
|----------|----------------|------------------------------------------|
| `leaders` | **sustained strength top-N across 1mo+3mo+6mo** — membership pinned to the PWA `sustained strength` definition (top N in the three main mid-length timeframes, `docs/index.html`), possibly ranked / tiebroken by momentum_confirmed score. **Ranking metric has been discussed in the selector spike** - NOT `rs_confirmed` alone — that conflates RS-vs-SPY with absolute strength. | n/a — already an absolute-strength definition |
| `emerging` | `regime_short_long` > `REGIME_THRESHOLD` | `rs_score` > 0.5 (must already be net-positive vs SPY) |
| `accel` | `momentum_accel` > `ACCEL_STRONG` | **top 40% by `momentum_score` percentile** AND `rs_score` > 0.5 — reject bottom-of-pack dead-cat flashes |
| `rs_new_high` | `rs_new_high` = 1 | `rs_score` ≥ 0.6 AND **top 40% by `momentum_score` percentile** — IBD "true leadership", not a low-base RS pop |

> The floor on `accel`/`rs_new_high` is the VP's explicit concern: a group can post a
> momentum-accel spike or 20-day RS-new-high while still near the bottom of the pack. Gate
> both on absolute standing before they qualify. Exact thresholds to tune; start conservative.

### Daily cap & priority-fill mix (STARTING PROPOSAL — finalized in the selector spike)

**Cap = 20 unique groups/day** (conviction over breadth; also bounds ToS exposure). Fill by
priority, dedup groups, stop at 20. The gates/ranks below are a **starting proposal to react to
in the spike**, not a locked design:

| Priority | Category | Gate (existing `deltas.csv` cols) | Slots | Rank within by (TBD in spike) |
|----------|----------|-----------------------------------|-------|----------------|
| 1 | `leaders` | top-N (in the three main mid-length timeframes - 1mo/3mo/6mo) with bonus set freshness fills from momentum_confirmed rank | ≤ **10** | **8 by sustained_strength** (rank_month + rank_quarter + rank_half, lowest sum = best) **+ 2 freshness fills by momentum_confirmed** (not already in top-8). VP-locked 2026-06-24. |
| 2 | `emerging` | `regime_short_long > REGIME_THRESHOLD (0.15)` **AND** `rs_score > 0.5` | ≤ **4** | `regime_short_long` desc |
| 3 | `accel` | `momentum_accel > ACCEL_STRONG (0.08)` **AND** top-40% floor **AND** `rs_score > 0.5` | ≤ **3** | `momentum_accel` desc |
| 4 | `rs_new_high` | `rs_new_high == 1` **AND** `rs_score ≥ 0.6` **AND** top-40% floor | ≤ **3** | `rs_slope` desc |

Rationale & design properties:
- **Leaders gets half the cap** — highest-expectancy, most-sustained; earlier/riskier buckets get
  small allocations.
- **Dedup counts unique groups toward 20**, but a group qualifying in multiple categories still
  gets its stock rows **tagged per category** in `picks.csv` (clean per-methodology attribution);
  it is only **scraped once**.
- **Self-shrinks in a correction** — correct behavior, not a bug.

#### Anti-flash floor: express as a percentile, NOT an absolute cutoff (robustness)

The floor on `accel`/`rs_new_high` is the group's **cross-sectional percentile rank among
today's groups by `momentum_score`**, **not** an absolute `momentum_score ≥ 0.5`.
**VP-locked: top 40% (not top 50%)** — conservative starting point, can loosen toward
top-50% after 30+ days if the buckets yield too few qualifying groups.
Reason for percentile over absolute: `momentum_score` is config-driven by `PERF_RANK_METRICS`
in `delta_config.py` (currently 6 timeframes, day excluded). If that list changes — e.g. drop
weekly — the metric **rescales**, so an absolute `≥ 0.5` silently means something different,
while a *percentile* ("top 40% of today's groups") is invariant to rescaling.

> **Earlier overclaim corrected:** Claude said reusing `REGIME_THRESHOLD`/`ACCEL_STRONG` means "nothing
> can drift." That only avoids **duplicate-constant drift** (two copies of one threshold
> disagreeing). It does **not** address **metric-redefinition drift** (the underlying
> `momentum_score`/`rs_score` formula changing). The two mitigations below handle that.

#### Selector decoupling, versioning & replayability (makes the selector modular)

The selector is the *one* part of this pipeline that is cheap to change and **fully replayable**:
`deltas.csv` is a complete historical archive, so any group-selection policy can be re-run over
all past days at any time. To keep that property usable:
1. **Stamp each pick with `selector_version`** and record the group-level metric values used at
   selection time (sidecar or extra `picks.csv` cols). Then a later formula change doesn't strand
   past analysis — you re-select historically and compare versions head-to-head.
2. **Keep selection logic in one small module** (`select_groups`) reading named config constants,
   so swapping the leaders rank metric or a floor is a one-line, tested change.

This is also why the *stock filter* (not the group selector) is the irreplaceable axis: group
selection is replayable from `deltas.csv`; per-stock point-in-time technicals are not.

### COMPLETED - Spike (Phase 1.5) — selector design, live with VP

**Format:** VP is present for the entire spike. This is a live, interactive session — not a
pre-computed report. The engineer runs candidates in real time and VP calls the shots on the spot.
Runs entirely in cloud against `deltas.csv` (no Finviz access needed; 10 trading days of data,
144 industries).

**What to run:**
- For each candidate **`leaders` ranking metric** — `momentum_confirmed`, a sustained-strength
  rank (groups top-ranked across mid-timeframes, secondarily by `momentum_confirmed`), all-green
  ranked by `rs_score` — show *which groups would have been selected* on each historical date;
  eyeball stability, day-over-day turnover, and overlap between methods.
- Apply the priority-fill table (§Daily cap) with each candidate ranking, capping at ≤10 leaders.
  Show the resulting 20-group list per day, per method. VP picks the one that looks right.
- Test the `emerging` / `accel` / `rs_new_high` gate thresholds against the same history:
  how many groups qualify per day? Are the floors working (no bottom-quartile groups slipping in)?
- All-green definition: `perf_week > 0 AND perf_month > 0 AND perf_quarter > 0 AND perf_half > 0
  AND perf_ytd > 0` (5 timeframes; day excluded). Source: `docs/index.html` line 1636.

**Output (decisions locked by VP at end of session):**
- Leaders ranking metric (one of the candidates above, or VP's variant)
- Anti-flash floor expression for `accel` / `rs_new_high` (percentile cutoff value)
- Slot split confirmed or adjusted (≤10/4/3/3 is the starting proposal)
- Stage-2 stored-net filter question: any adjustments to the VP-supplied wide-net `f=` before
  Phase 2 starts, or ship as-is and revisit at Phase-4 attribution?

**Note:** the fetch-volume quantification (how many stock rows per group under various filters)
requires hitting the Finviz screener and is NOT part of this spike. That is the Phase-1
one-shot probe run on GitHub Actions.

### Spike results (VP decisions locked 2026-06-24)

**Data used:** 10 trading dates (2026-06-09 → 2026-06-23), 144 industries.
All analysis run in cloud against `data/industries/deltas.csv` + `data/industries/snapshots.csv`.

**Findings from the data:**
- All-green count per day: ranged 21–46 (self-shrinks during weakness — correct behavior).
  Jun 23 dropped to 21 as the market rotated (vs 31 the prior day); high turnover that day
  is a rotation signal, not a bug.
- `momentum_accel` was all NaN across all 10 dates (needs 11 sessions for a 10-session delta;
  unlocks on the 11th trading date, ~2026-06-25). The `accel` bucket will yield 0 groups
  until then — expected.
- `rs_score` available from Jun 18 (3 dates); `rs_new_high` from Jun 22 (2 dates).
- The `rs_score > 0.5` floor on the `emerging` bucket is **essential**: without it 39–50
  groups qualify (useless); with it, 3–4. Floor is working exactly as intended.
- `rs_new_high` raw: 13–19 qualifying → 3 after floors (`rs_score ≥ 0.6` + top-40%).

**Stability comparison (avg day-over-day Jaccard, Jun 15–23):**

| Metric | Jaccard | Character |
|--------|---------|-----------|
| sustained_strength | **0.691** (most stable) | Rewards durable mid-TF rank leaders; always includes Semiconductors |
| momentum_weighted_mid | 0.650 | Near-identical to SS; Jun 17→18 zero turnover |
| momentum_confirmed | 0.605 | More responsive; catches fresher movers earlier |
| rank_agreement | 0.578 (least stable) | Noisy; not recommended |

**Locked decisions:**

| Item | Decision |
|------|----------|
| **Leaders ranking metric** | **Approach 1: 8 slots by sustained_strength (sum of rank_month + rank_quarter + rank_half, lower = better) + 2 freshness-fill slots by momentum_confirmed (not already in top-8)**. Core 8 are durable mid-timeframe leaders; freshness slots catch fresh movers. Attributable in picks.csv: tag each row's ranking basis. |
| **Anti-flash floor** | **Top 40% cross-sectional percentile by `momentum_score`** (not absolute cutoff — invariant to formula rescaling per plan §anti-flash floor). Applied to `accel` and `rs_new_high` buckets. |
| **Slot split** | **≤10 leaders / ≤4 emerging / ≤3 accel / ≤3 rs_new_high (cap = 20)** — confirmed as-is. In practice totals 13–17 given current data coverage. |
| **Wide-net filter** | Ship VP-supplied URL as-is; revisit at Phase-4 attribution. |

**Sustained_strength vs momentum_confirmed divergence (where they differ):**
- SS consistently includes Semiconductors (strong mid-rank even when short-term wobbles).
- momentum_confirmed freshness fills add: Farm & Heavy Construction Machinery (Jun 17–18),
  Scientific & Technical Instruments + Engineering & Construction (Jun 22),
  Specialty Industrial Machinery (Jun 23).

### Fetch-volume budget & guardrails (VP concern — D11, 2026-06-23)

**Decision (D11): store wide (generous superset of signals, relaxed *trend* gates), tag Stage-2
in-house — BUT bounded and explicitly temporary.** The VP accepted the "store wide" recommendation
*cautiously*, on the record that it is **not a long-term solution** and that fetch volume is a real
concern. Honoring that requires honesty about the number and hard guardrails:

- **Honest volume estimate.** The VP's "~40 fetches/day" (20 groups × 2 pages) reflects the
  *tight* Stage-2 net. "Store wide" *loosens the row filter*, so big industries (Semis ≈ 100–200
  names) become 5–10 pages each. **Realistic generous-capture volume is ~60–120 fetches/day**, not
  40. Do not plan around 40.
- **Keep the liquidity floor as a volume ally.** Retain `sh_avgvol_o100` (avg vol > 100K) even in
  the "wide" net — it is defensible on its own merits (we want liquid, institutional-friendly
  names) AND it is the single biggest reducer of junk rows / pages. Relax only the *trend* gates
  (`ta_highlow52w_a30h`, `ta_sma200_sb50`, `ta_sma50_pa`) that cause survivorship; recompute strict
  Stage-2 as an in-house boolean column.
- **Measure before committing (Phase-1 probe).** Before turning on the daily job, do a **one-time
  probe scrape** that counts names/pages per selected group at the proposed breadth and reports the
  real projected daily fetch total. The spike's "row-count" step needs this probe — existing CSVs
  are group-level only, so stock counts must be measured, not estimated. **VP signs off on the
  actual number, not my estimate.**
- **Hard guardrails in `collect_picks.py`:** per-group page cap, global daily fetch cap (start
  ~120), polite inter-fetch delay, and **abort if projected fetches exceed the cap** rather than
  silently scraping more. Caps are configurable constants (triple-doc per house rules).
- **Sunset trigger (the "not LT" promise, in writing).** Once Phase-4 attribution identifies which
  signals actually predict winners, **narrow the stored net** to those — dropping back toward the
  tight Stage-2 volume. This is a tracked obligation, not an aspiration: revisit at the first
  attribution review.

## Finviz scraping notes (carry-over from collect.py + new)

- **Same Cloudflare block as collect.py** — must run on **Azure (GitHub Actions)**, not cloud
  Claude (Google Cloud IPs get `cf-mitigated: challenge`). Playwright headless Chromium.
- **Pagination (NEW):** `v=151` returns ~20 rows/page. Walk `&r=1`, `&r=21`, `&r=41`… until a
  page returns fewer than the page size (or repeats). A wide net on a big industry = 50+ names.
- **Politeness:** delay between page loads and between groups (the separate workflow per D7
  isolates this from the core EOD snapshot). ~20–30 groups × pages = real volume — keep it
  human-paced and consider a daily cap.
- **Volume is the #1 feasibility risk — see §Fetch-volume budget & guardrails (D11).** With the
  chosen "store wide" breadth, realistic load is **~60–120 screener page loads/day** from one
  Azure IP (NOT the ~40 a tight net implies) — a large escalation over today's 2 group page loads,
  against Finviz's *screener* (more bot-sensitive than the groups view). Mitigations are mandatory,
  not optional: liquidity floor, per-group + global fetch caps, polite delays, a Phase-1 volume
  probe to confirm the real number, and a Phase-4 sunset back toward the tight net. At a 3–5s
  delay this is a ~10–20 min Actions job.
- **"Wide net" = wide on COLUMNS, not on FILTERS (clarification).** Two orthogonal axes:
  *column breadth* (`c=`, 84 IDs — how many attributes per passing stock) vs *filter width*
  (`f=` tokens — how many stocks pass at all). D5 is the column axis; D4/D11 is the filter axis.
  We store all 84 columns regardless; the breadth choice (D11) is purely about *which names* get
  logged.
  **Consequence (survivorship):** only names *already* Stage-2 ever enter the log; names that
  drop out vanish, and pre-Stage-2 observations are never captured. Group selection is
  *replayable* from the archived `deltas.csv`; per-stock point-in-time technicals are **not**.
  So the stock-filter width is the one thing we can never widen retroactively — see the
  Stage-2-net open question (D4 tension) and the selector spike.
- **Concurrency / stale-read guard (D7).** `collect_picks.yml` and `collect.yml` both commit to
  `data/` on the same branch. Use a shared GitHub **`concurrency:` group** so they never push
  simultaneously, **rebase (or `git pull --rebase`) before push**, and **assert the deltas are
  current** before scraping: `deltas['date'].max() == trading_date()` — abort/skip otherwise so
  cron drift can't make picks scrape against yesterday's group rankings.
- **Slug derivation:** `ind_<slug>` where `slug` = `name.lower()` with all non-alphanumerics
  stripped. Verified: `Aerospace & Defense → aerospacedefense`, `Software - Application →
  softwareapplication`. **Build the 144 from `data/industries/snapshots.csv`, NOT
  `taxonomy_map.csv`** (the latter is the incomplete FMP→Finviz map — missing ~17 industries).
  No pre-flight live-dropdown validation against all 144 slugs — that's disproportionate effort.
  Instead: **fail loud at scrape time** — if a group returns 0 result rows, log a clear WARNING
  with the slug and group name, skip that group, and surface it in the run summary. **GOTCHA: a
  wrong slug does NOT 404** — Finviz returns HTTP 200 with an empty table. So the scraper must
  check row count > 0, not just HTTP status.
- **URL templates (VP-supplied 2026-06-23, decoded below).** Handling, validation, and
  modularity are specified in §VP URL handoff & modular screener config.

## VP URL handoff & modular screener config

**What the VP provides:** *one* full sample screener URL per template — the **wide-net (storage)**
URL and the **tight Stage-2 (button)** URL — for *any single* industry. The VP does **not**
hand-build 144 URLs; they paste two example URLs and the implementer parameterizes them.

### VP-supplied samples (2026-06-23) — decoded

**Button (tight Stage-2), view `v=311`:**
```
https://finviz.com/screener?v=311&f=cap_midover,ind_<slug>,ta_sma20_sa50,ta_sma50_pa&ft=4&o=sma50
  filters: cap_midover · ta_sma20_sa50 (20SMA > 50SMA) · ta_sma50_pa (price > 50SMA)
```

**Wide net (storage scrape), view `v=151`, 84 columns (revised URL, 2026-06-23):**
```
https://finviz.com/screener?v=151&f=cap_midover,ind_<slug>,sh_avgvol_o100,ta_highlow52w_a30h,ta_sma200_sb50,ta_sma50_pa&ft=4&o=-marketcap&c=1,2,4,5,6,7,67,65,66,68,79,8,9,10,13,145,146,33,32,34,37,38,149,16,77,17,18,142,19,20,143,21,23,22,132,133,39,40,41,27,29,42,43,44,45,47,46,138,49,51,48,52,53,54,59,63,64,81,86,87,88,62,69,135,137,136,150,3,12,144,35,36,82,78,28,139,50,57,58,60,61,148,127,128
  filters: cap_midover · sh_avgvol_o100 (avg vol > 100K — liquidity floor) · ta_highlow52w_a30h (within 30% of 52w high) · ta_sma200_sb50 (50SMA > 200SMA) · ta_sma50_pa (price > 50SMA)
  sort: o=-marketcap (biggest first — institutional-friendly leaders on top)
  84 columns (exceeds the original "~70" estimate — even better for attribution)
```
> Revision: the first paste had `o=wiimdailydigest` (accidental leftover sort) and no avg-vol
> floor. Revised URL **adds `sh_avgvol_o100`** (a real filter change — liquidity gate) and sorts
> `-marketcap`. Columns byte-identical (verified). Since we paginate **every** page, sort affects
> only the button's display order + scrape order, never *what* we store.
> `%2C` in the raw paste = `,` (URL-encoded comma) — decode before parsing.
> Semiconductors is a large group → doubles as the multi-page pagination validation case.

**Risks to retire in Phase-1 validation (verify on a HEADLESS, ANONYMOUS, Azure run):**
1. **Custom 84-col `c=` on a free / unauthenticated client — biggest schema risk.** VP sees all
   84 columns *in his logged-in browser*, but that is **necessary, not sufficient**: our scrape
   is headless + unauthenticated + on an Azure IP. Elite-gated columns can render for VP yet be
   blank/absent anonymously; the anonymous table shape may differ. We already use custom `c=` for
   the *groups* view (`v=152&c=…`) anonymously, so it's *likely* fine — but the only valid test
   is a headless anonymous Azure fetch returning all 84 columns **populated**.
2. **Sort token** — resolved to `o=-marketcap` (the accidental `wiimdailydigest` is dropped).
   Non-critical anyway since we paginate every page.
3. **Stage-2 filters baked into the stored net (D4 tension)** — see the "wide net = columns not
   filters" clarification in §Finviz scraping notes and the survivorship discussion. Decision
   parked for the selector spike + Open dependencies; default is to ship the VP net as-is to
   start the clock.

**How the implementer turns that into the pipeline:**

1. **Decompose, don't store monolithically.** Parse each sample URL into its parts and persist
   them in `data/picks/screener_config.json` (one block per template, `wide` and `button`):
   ```json
   {
     "wide": {
       "v": "151",
       "base_filters": ["cap_midover", "ta_highlow52w_a30h", "ta_sma200_sb50", "ta_sma50_pa"],
       "sort": "-marketcap", "ft": "4",
       "columns": [{"id": 1, "label": "Ticker"}, {"id": 65, "label": "RSI"}, ...]  // 84 ids, ordered
     },
     "button": {
       "v": "311",
       "base_filters": ["cap_midover", "ta_sma20_sa50", "ta_sma50_pa"],
       "sort": "sma50", "ft": "4"
     }
   }
   ```
   The scraper builds each request URL programmatically: `base_filters + ["ind_"+slug]` joined
   into `f=`, plus `v`/`o`/`ft`/`c`. **`ind_<slug>` is the only per-group variable.**

2. **Modular for the VP (answers "can the VP add columns later?").** Yes — by design. To add or
   reorder columns the VP edits the `columns` list in `screener_config.json` (or pastes a new
   sample URL and the implementer re-extracts). Nothing else changes; the request URL and the
   CSV header are both **derived from `columns`**. *Caveat:* `picks.csv` is append-only with a
   fixed header — adding a column mid-history requires a header migration (superset-rewrite,
   exactly like `ensure_deltas_csv()` adds new columns and backfills old rows blank). Document
   that adding a column is a schema bump, not a silent change. Removing/reordering columns is
   discouraged; prefer append-only column growth.

3. **The opaque integer `c=` IDs are NOT a problem (VP asked).** They never need hand-decoding.
   Finviz **renders the human column labels in the result table's header row**, in `c=` order.
   So on first run we scrape that header and map *position → label* (e.g. id `65` → "RS"), store
   it in `columns[].label`, and use the labels as the `picks.csv` header. The integers are just
   the request key; meaning comes from the scraped header. Assert `len(scraped header) == 84` so
   a view drift is caught immediately (the D5 header-drift guard).

4. **Validation recipe (Phase-1 probe).** One GitHub Actions run, one large industry
   (Semiconductors — many names, exercises pagination naturally):
   - **84-col anon check:** confirm all 84 columns return populated on a headless/anonymous/Azure
     client. VP seeing them in his logged-in browser is necessary but not sufficient.
   - **Page-count measurement:** record how many `&r=` pages Semiconductors produces under the
     VP-supplied wide-net filter. Extrapolate to the ~20-group daily cap → real fetch volume.
   - **Required-columns assertion:** verify the `c=` list contains the fields the PWA and
     attribution need — Price, %-from-50SMA, 52w-high distance, RSI, perf week/month, EPS/sales
     growth, Country. Fail loudly if any are missing.
   - **Golden-header snapshot:** commit the first validated 84-col header as a fixture; a test
     asserts future scrapes match it (drift tripwire).

5. **Mostly resolved by the VP samples.** URLs, filters, sort, and the 84-col `c=` list are now
   in hand (decoded above). The only residual VP confirmation is the **Stage-2-filter-in-wide-net**
   question (risk 3 above) — see Open dependencies.

## Deep-link button (folds into same effort)

On each industry context (Lookup tab card), a "Stage-2 stocks on Finviz →" button opens the
prefilled screener for that `ind_<slug>` in a new tab. Pure URL construction from the slug
map — zero backend. Use the *user-facing* (tighter Stage-2) filter template for the button so
the human lands on a clean list, even though our stored scrape uses the wide net.

## PWA (D8)

- **Picks tab (new):** top-level tab. Read **`picks_latest.csv`** (not the full log). Group by `list_category`
  → industry → stocks. Show per stock: ticker, %-from-50SMA (extension), 52w-high distance,
  RSI, perf week/month, EPS/sales growth (from the stored 84 cols). Sort least-extended
  first. Show breadth (count of qualifiers) per group as a health signal.
- **Lookup tab section:** when an industry is pulled up, render its Stage-2 names (from
  `picks.csv` if the group was selected that day) + the deep-link button. If the group wasn't
  in the selected universe, show just the button ("not currently a leading group — screen it
  yourself →").
- Release triplet per house rules (releases.json entry + `current` + `sw.js` CACHE bump).

## Attribution (D9) — LATER session, schema-locked NOW

Collection is **membership-only** (`picks.csv` append-only). Nothing stateful is maintained
day-to-day. The analysis phase (`eval_picks.py`, separate session) will:

1. Reconstruct positions from the log: `entry` = first date in a continuous run per
   `(ticker, list_category)`; `exit` = first gap.
2. Backfill daily closes for tracked tickers. **In-screen days need no backfill** — the v=151
   Price column is already logged in `picks.csv`. Only names that have *exited* the screen need
   a historical-close source: a free OHLC provider (Stooq / yfinance / Tiingo). **This is not
   yet integrated** — it is a Phase-4 spike (see correction in §Context). Pick the provider and
   validate coverage/quotas before relying on it.
3. Compute forward returns at **1w / 1mo / 3mo**, measured **absolute, vs SPY, and vs the
   stock's own group** — so we can answer both "did the list beat the market?" and "did
   stock-picking beat just buying the group?".
4. Compare **methodologies head-to-head** (leaders vs emerging vs accel vs RS-NH) and test
   which stored metrics (extension, RSI, EPS growth…) had predictive value.

This evolves the schema to the **hybrid (Option C)**: a regenerated `picks_positions` view
derived from the log — never hand-maintained.

## Phasing

1. **COMPLETED Phase 1 — slug map + probe run** (small, one GitHub Actions run): (a) generate
   `finviz_industry_slugs.csv` from `snapshots.csv` using the slugify function — pure math, no
   Finviz calls; (b) one-shot GitHub Actions run: scrape one large industry (Semiconductors) to
   confirm all 84 columns return populated on an anonymous/headless/Azure client AND count
   pages/rows to measure real daily fetch volume. VP signs off on the real fetch number before
   the daily job turns on.
1.5 **COMPLETED Spike — selector design, live with VP** (see §Spike): pick the leaders ranking metric, the
   floors/cap split, and the Stage-2-net decision by running candidates against historical
   `deltas.csv`. Runs in cloud (no scraping). Gates Phase 2's `select_groups`.
2. **Phase 2 — scraper + collection** (core, irreplaceable): `collect_picks.py` (selectors +
   paginated scrape + append), `collect_picks.yml` separate workflow, `data/picks/picks.csv` +
   `picks_latest.csv`. **Start the daily clock ASAP.** URL templates in hand; needs Phase-1
   validation + the spike's selector policy.
3. **Phase 3 — PWA surfaces:** Picks tab + Lookup-tab section + deep-link button + release.
4. **Phase 4 — attribution** (later, own session): `eval_picks.py`, OHLC backfill, methodology
   comparison.
5. **Spike (optional) — TwelveData/extended indicators** if Finviz columns prove insufficient.

## Open dependencies / questions parked for VP

- [x] **Canonical wide-net + button Finviz URLs** — VP supplied 2026-06-23 (decoded in §VP URL
      handoff). 84-col `c=` list, `cap_midover` + Stage-2 `ta_*` filters, `v=151`/`v=311`.
- [x] **Stored-net breadth (D11)** — VP chose **store wide + tag in-house**, *cautiously*, as an
      explicitly **non-LT** solution. Keep liquidity floor, relax trend gates, hard fetch caps,
      Phase-1 volume probe, Phase-4 sunset. Honest volume ~60–120 fetches/day (not 40). See
      §Fetch-volume budget.
- [x] **Selector spike COMPLETE (2026-06-24)** — leaders ranking metric + cap/floor split locked.
      See §Spike results. Metric: Approach 1 (8 SS + 2 MC freshness fills). Floor: top 40%
      by momentum_score percentile. Slot split: 10/4/3/3 confirmed. NOT `rs_confirmed` alone.
- [x] **Geography** — include foreign ADRs (VP confirmed 2026-06-24). `sh_avgvol_o100` liquidity
      floor handles quality screening. Store `Country` column; filter locally if needed later.
- [x] **Finviz ToS / Azure IP** — no evidence of GitHub Actions Azure IPs being blocked at the
      screener. Rate limiting is request-velocity-based, not IP-based. Mitigated by polite
      inter-fetch delays and a hard fetch cap. Existing `collect.py` already runs from Azure
      without issues (different endpoint, same IP pool).
- [x] **VP sign-off on the real fetch number** after the Phase-1 probe (gate before daily job on).
- [x] **Free-tier 84-col validation (engineer, Phase 1)** — one GitHub Actions run against one
      large industry (Semiconductors) confirms all 84 columns return populated anonymously.
      Also measures real page count / daily fetch volume for VP sign-off.
- [ ] **`picks.csv` log growth** (non-blocking) — full append-only log grows multi-MB within weeks;
      revisit rotation / git-LFS / yearly partition later. PWA insulated via `picks_latest.csv`.
- [ ] **Phase-4 OHLC provider** for exited-name backfill — Stooq / yfinance / Tiingo; validate
      coverage + quota. Not yet integrated (see §Context correction).

## Testing

- `collect_picks.py` pure functions: `slugify_industry`, `select_groups` (each category +
  floor), pagination loop (mock pages), append/dedup, **URL build from `screener_config.json`**
  (asserts `ind_<slug>` injection + ordered `c=`). Use `tmp_path`/`StringIO` per house rule.
- Slug-map anti-drift test: every industry in `snapshots.csv` has a row in
  `finviz_industry_slugs.csv` (mirrors taxonomy validation discipline).
- **Header / schema smoke tests (VP asked) — guard the discouraged behaviors explicitly:**
  - **Golden-header match:** the first validated 84-col header committed as a fixture; any drift
    (Finviz view change or config edit) fails.
  - **Reorder/removal guard:** assert a new header is a same-order **superset** of the committed
    one → column **removal or reorder fails the test**; a pure **append** is allowed and triggers
    the migration path (below).
  - **Migration test:** adding a column to `screener_config.json` backfills existing `picks.csv`
    rows with blanks and produces a superset header (mirrors `ensure_deltas_csv()`); old rows
    stay readable.
  - **Count + required-columns asserts:** `len(scraped) == len(config.columns) == 84`, and the
    needed fields are present (Price, %-from-50SMA, 52w-high, RSI, perf wk/mo, EPS/sales growth,
    Country).
- **`picks_latest.csv` test:** equals the max-date slice of `picks.csv` after a run.
- PWA: Playwright fixture-intercept tests for Picks tab + Lookup section (per CLAUDE.md
  pattern).
