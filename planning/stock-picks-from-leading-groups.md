# Plan: Top-stock picks from leading groups (Stage-2 screener pipeline)

> Status: **FRAMEWORK / pre-implementation.** Decisions below are VP-confirmed (interviews
> 2026-06-23). The Finviz URL templates are now **in hand** (wide-net + button, decoded in
> §VP URL handoff). Remaining before/within Phase 1: (1) one-time validation of the 144-row
> industry→`ind_` slug map vs Finviz's live dropdown, (2) retire three free-tier risks (84-col
> custom `c=` on a headless/anon/Azure client, and the Stage-2 filters baked into the stored net), and
> (3) VP sign-off on the proposed selector thresholds / 20-group cap mix.

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

## Architecture

```
collect.py (existing, EOD)
   └─> data/industries/deltas.csv  ──┐
                                      │ (group selectors read this)
collect_picks.py (NEW, separate EOD workflow)
   1. select_groups()      reads latest deltas.csv → leading/emerging/accel/RS-NH groups
   2. for each selected group:
        build screener URL from screener_config.json (base f= + ind_<slug> + ordered c=)
        scrape ALL pages (Playwright, paginate &r=) → ~70-col rows
   3. append to data/picks/picks.csv  (one row per stock × list_category × day)
   4. rewrite data/picks/picks_latest.csv (max-date slice → PWA fetches this)

config:   data/picks/screener_config.json     (modular URL: f=, c=, v/o/ft — VP-editable)
slug map: data/picks/finviz_industry_slugs.csv  (144 rows, validated vs live dropdown)

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
| `leaders` | **sustained strength** — membership pinned to the PWA `allGreen` definition (positive in all 5 timeframes, `docs/index.html` ~line 1636), possibly gated by a strength floor. **Ranking metric is OPEN — to be chosen in the selector spike** (candidates: `momentum_confirmed`, a sustained-strength rank, all-green ranked by RS). NOT `rs_confirmed` alone — that conflates RS-vs-SPY with absolute strength. | n/a — already an absolute-strength definition |
| `emerging` | `regime_short_long` > `REGIME_THRESHOLD` | `rs_score` > 0.5 (must already be net-positive vs SPY) |
| `accel` | `momentum_accel` > `ACCEL_STRONG` | rank in **top half** of peers AND `rs_score` > 0.5 — reject bottom-of-pack dead-cat flashes |
| `rs_new_high` | `rs_new_high` = 1 | `rs_score` high AND rank top-half — IBD "true leadership", not a low-base RS pop |

> The floor on `accel`/`rs_new_high` is the VP's explicit concern: a group can post a
> momentum-accel spike or 20-day RS-new-high while still near the bottom of the pack. Gate
> both on absolute standing before they qualify. Exact thresholds to tune; start conservative.

### Daily cap & priority-fill mix (STARTING PROPOSAL — finalized in the selector spike)

**Cap = 20 unique groups/day** (conviction over breadth; also bounds ToS exposure). Fill by
priority, dedup groups, stop at 20. The gates/ranks below are a **starting proposal to react to
in the spike**, not a locked design:

| Priority | Category | Gate (existing `deltas.csv` cols) | Slots | Rank within by (TBD in spike) |
|----------|----------|-----------------------------------|-------|----------------|
| 1 | `leaders` | all-green (5/5 timeframes +), optional strength floor | ≤ **10** | `momentum_confirmed` *or* sustained-strength rank *or* all-green-by-RS — **spike picks** |
| 2 | `emerging` | `regime_short_long > REGIME_THRESHOLD (0.15)` **AND** `rs_score > 0.5` | ≤ **4** | `regime_short_long` desc |
| 3 | `accel` | `momentum_accel > ACCEL_STRONG (0.08)` **AND** top-half floor **AND** `rs_score > 0.5` | ≤ **3** | `momentum_accel` desc |
| 4 | `rs_new_high` | `rs_new_high == 1` **AND** `rs_score ≥ 0.6` **AND** top-half floor | ≤ **3** | `rs_slope` desc |

Rationale & design properties:
- **Leaders gets half the cap** — highest-expectancy, most-sustained; earlier/riskier buckets get
  small allocations.
- **Dedup counts unique groups toward 20**, but a group qualifying in multiple categories still
  gets its stock rows **tagged per category** in `picks.csv` (clean per-methodology attribution);
  it is only **scraped once**.
- **Self-shrinks in a correction** (fewer all-green leaders) — correct behavior, not a bug.

#### Anti-flash floor: express as a percentile, NOT an absolute cutoff (robustness)

The "top-half" floor on `accel`/`rs_new_high` should be the group's **cross-sectional percentile
rank among today's groups** (e.g. top 50% by `momentum_score`), **not** an absolute `momentum_score
≥ 0.5`. Reason (VP's robustness concern): `momentum_score` is config-driven by `PERF_RANK_METRICS`
in `delta_config.py` (currently 6 timeframes, day excluded). If that list changes — e.g. drop
weekly — the metric **rescales**, so an absolute `≥ 0.5` silently means something different, while
a *percentile* ("top half of today's groups") is invariant to rescaling.

> **Earlier overclaim corrected:** I said reusing `REGIME_THRESHOLD`/`ACCEL_STRONG` means "nothing
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

### Spike (Phase 1.5) — selector design, live with VP

Before locking the selector, run a short analysis spike against the **existing** `deltas.csv`
history (no scraping needed — runs fine in cloud Claude):
- For each candidate **leaders ranking** (`momentum_confirmed`, sustained-strength rank,
  all-green-ranked-by-RS, others VP suggests) and each **floor/threshold**, show *which groups
  would have been selected* on real historical days; eyeball stability, overlap, turnover.
- Quantify the **Stage-2-filter tradeoff** (D4): pull row counts per group at a few filter
  loosenesses to put numbers on "how much extra volume would a looser stored net cost?" — so VP
  decides survivorship-vs-volume with data.
- Output: the locked selector policy (gates, ranks, slot split, cap) + the Stage-2-net decision.
  Do this **interactively with VP**; it's a judgment call best made over real selected lists.

## Finviz scraping notes (carry-over from collect.py + new)

- **Same Cloudflare block as collect.py** — must run on **Azure (GitHub Actions)**, not cloud
  Claude (Google Cloud IPs get `cf-mitigated: challenge`). Playwright headless Chromium.
- **Pagination (NEW):** `v=151` returns ~20 rows/page. Walk `&r=1`, `&r=21`, `&r=41`… until a
  page returns fewer than the page size (or repeats). A wide net on a big industry = 50+ names.
- **Politeness:** delay between page loads and between groups (the separate workflow per D7
  isolates this from the core EOD snapshot). ~20–30 groups × pages = real volume — keep it
  human-paced and consider a daily cap.
- **Volume is the #1 feasibility risk (understated until now).** Today's pipeline does ~2 group
  page loads; this is 20–30 groups × N pages ≈ **100–200 screener page loads/day** from one
  Azure IP — a 50–100× escalation, against Finviz's *screener* (more bot-sensitive than the
  groups view). Two compounding effects: (a) Cloudflare/ToS escalation risk, (b) Actions
  wall-clock — at a 3–5s polite delay this is a ~10–20 min job. State the runtime budget and
- **"Wide net" = wide on COLUMNS, not on FILTERS (clarification).** Two orthogonal axes:
  *column breadth* (`c=`, 84 IDs — how many attributes per passing stock) vs *filter width*
  (`f=` tokens — how many stocks pass at all). D5 is the column axis; D4 ("filter in-house")
  is the filter axis. The VP net is **wide on columns (84) but Stage-2-narrow on filters**, so
  per-group name counts are moderate, not raw-universe — realistic load ~tens of page loads/day.
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
  softwareapplication`. **Must validate all 144** against Finviz's live filter dropdown once
  (some names may abbreviate) — emit `finviz_industry_slugs.csv` with a `validated` flag and
  fail loudly on any unmapped slug. **GOTCHA: a wrong `ind_` slug does NOT 404** — Finviz
  returns HTTP 200 with an *empty result table*. So validation must parse the screener's
  industry-filter `<option value="ind_…">` set from the live dropdown HTML and assert each
  derived slug is a member; a URL-200 check is insufficient and will silently pass bad slugs.
  **Build the 144 from `data/industries/snapshots.csv`,
  NOT `taxonomy_map.csv`** (the latter is the incomplete FMP→Finviz map — missing ~17
  industries: Airlines, Gambling, Internet Retail, Semiconductor Equipment & Materials,
  "Furnishings, Fixtures & Appliances", Coking Coal, etc.).
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

4. **Validation recipe (extends the VP's "try one, check two" idea).** Don't just try the
   sample group — validate across the shape of the data:
   - **One large industry** (e.g. `Software - Application`, 100s of names) → exercises pagination
     to multiple `&r=` pages and the short-page terminator.
   - **One small industry** (single page, < page size) → confirms the loop stops at page 1.
   - **One special-char slug** (e.g. `Furnishings, Fixtures & Appliances`) → confirms slugify +
     dropdown-membership validation, not just the easy alphanumeric names.
   - **Required-columns assertion:** verify the VP's `c=` list actually contains the fields the
     PWA and attribution need — **Price, %-from-50SMA, 52w-high distance, RSI, perf week/month,
     EPS/sales growth, Country**. Fail loudly if any are missing, so we don't discover a hollow
     feature weeks into collection.
   - **Golden-header snapshot:** commit the first validated header as a fixture; a test asserts
     future scrapes match it (drift tripwire).

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

1. **Phase 1 — slug map + validation** (small): build `finviz_industry_slugs.csv` from
   snapshots, validate vs live Finviz dropdown (one Actions run). Also retire the headless-anon
   84-col `c=` check on Azure. De-risks everything.
1.5 **Spike — selector design, live with VP** (see §Spike): pick the leaders ranking metric, the
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
- [ ] **Stage-2 `ta_*` filters in the *stored* net (D4 tension)** — narrows the log to names
      already Stage-2 (survivorship). Note: this is a *filter/row* question, not a *column* one —
      we still store all 84 columns either way. **Deferred to the selector spike**, which will put
      row-count numbers on the volume cost of a looser net. Default: ship VP net as-is to start
      the clock.
- [ ] **Leaders ranking metric + cap/floor split — to the selector spike.** NOT `rs_confirmed`
      (conflates RS with absolute strength). Candidates: `momentum_confirmed`, sustained-strength
      rank, all-green-by-RS. Anti-flash floors expressed as **percentiles**, not absolute cutoffs.
- [ ] **VP confirm geography:** `cap_midover` includes foreign listings — keep all (store Country,
      filter later) or restrict to US? Default: keep all.
- [ ] Finviz ToS comfort on ~20 groups × pages/day. Stage-2-filtered net keeps this to ~tens of
      page loads; politeness + cap mitigate. Flag if concern.
- [ ] **`picks.csv` log growth** (non-blocking, VP-noted) — the full append-only log grows
      multi-MB; revisit rotation / git-LFS / yearly partition later. PWA already insulated via
      `picks_latest.csv`, so this does not block collection.
- [ ] **Free-tier 84-col validation (engineer, Phase 1)** — headless + anonymous + Azure fetch
      must return all 84 columns populated. VP seeing them in his logged-in browser is not
      sufficient evidence.
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
