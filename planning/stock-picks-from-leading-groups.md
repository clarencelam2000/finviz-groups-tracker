# Plan: Top-stock picks from leading groups (Stage-2 screener pipeline)

> Status: **FRAMEWORK / pre-implementation.** Decisions below are VP-confirmed (interviews
> 2026-06-23). The Finviz URL templates are now **in hand** (wide-net + button, decoded in
> §VP URL handoff). Remaining before/within Phase 1: (1) one-time validation of the 144-row
> industry→`ind_` slug map vs Finviz's live dropdown, (2) retire three free-tier risks (84-col
> custom `c=`, the `wiimdailydigest` sort token, Stage-2 filters baked into the stored net), and
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
  picks.csv                    # append-only; date, list_category, group, ticker, <~70 finviz cols>
  picks_latest.csv             # latest trading date only — what the PWA fetches (see PWA note)
  finviz_industry_slugs.csv    # industry_name, ind_slug, validated (bool), note
  screener_config.json         # modular URL config (base f= filters, ordered c= columns, v/o/ft) — see §VP URL handoff
```

> **PWA fetch size (VP-confirmed: per-date latest artifact).** `picks.csv` is the full
> append-only log (~25 groups × ~40 names × ~70 cols/day → multi-MB within weeks) and is for
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
| `leaders` | **all-green AND `rs_confirmed` ≥ floor.** Pin "all-green" to the existing PWA definition: positive in all 5 timeframes (Wk·Mo·Qtr·½yr·YTD), per `docs/index.html` `allGreen` (~line 1636). Name the `rs_confirmed` threshold explicitly in `delta_config` (start ~0.5). | n/a — already an absolute-strength definition |
| `emerging` | `regime_short_long` > `REGIME_THRESHOLD` | `rs_score` > 0.5 (must already be net-positive vs SPY) |
| `accel` | `momentum_accel` > `ACCEL_STRONG` | rank in **top half** of peers AND `rs_score` > 0.5 — reject bottom-of-pack dead-cat flashes |
| `rs_new_high` | `rs_new_high` = 1 | `rs_score` high AND rank top-half — IBD "true leadership", not a low-base RS pop |

> The floor on `accel`/`rs_new_high` is the VP's explicit concern: a group can post a
> momentum-accel spike or 20-day RS-new-high while still near the bottom of the pack. Gate
> both on absolute standing before they qualify. Exact thresholds to tune; start conservative.

### Daily cap & priority-fill mix (proposed — VP sign-off pending)

**Cap = 20 unique groups/day** (conviction over breadth; also bounds ToS exposure). Fill by
priority, dedup groups, stop at 20:

| Priority | Category | Gate (existing `deltas.csv` cols) | Slots | Rank within by |
|----------|----------|-----------------------------------|-------|----------------|
| 1 | `leaders` | all-green (5/5 timeframes +) **AND** `rs_confirmed ≥ 0.5` | ≤ **10** | `rs_confirmed` desc |
| 2 | `emerging` | `regime_short_long > REGIME_THRESHOLD (0.15)` **AND** `rs_score > 0.5` | ≤ **4** | `regime_short_long` desc |
| 3 | `accel` | `momentum_accel > ACCEL_STRONG (0.08)` **AND** `momentum_score ≥ 0.5` **AND** `rs_score > 0.5` | ≤ **3** | `momentum_accel` desc |
| 4 | `rs_new_high` | `rs_new_high == 1` **AND** `rs_score ≥ 0.6` **AND** `momentum_score ≥ 0.5` | ≤ **3** | `rs_slope` desc |

Rationale:
- **`momentum_score ≥ 0.5` is the "top-half" anti-flash floor** — it's already a 0–1 percentile
  across timeframes, so "top half" is unambiguous and self-adjusting (cleaner than a raw rank
  cutoff). This is the gate the VP wanted on `accel`/`rs_new_high`.
- **Leaders gets half the cap** — highest-expectancy, most-sustained; the earlier/riskier
  buckets get small allocations.
- **Dedup counts unique groups toward 20**, but a group qualifying in multiple categories still
  gets its stock rows **tagged per category** in `picks.csv` (clean per-methodology attribution);
  it is only **scraped once**.
- **Reuses existing PWA constants** (`REGIME_THRESHOLD`, `ACCEL_STRONG`) — one source of truth,
  no new magic numbers. New floors (`rs_confirmed ≥ 0.5`, `rs_score` cutoffs) go in
  `delta_config.py` with the configurable-constant triple-doc treatment.
- **Self-shrinks in a correction** (fewer all-green leaders) — correct behavior, not a bug.

Thresholds are deliberately conservative starting points; tune after the first few weeks of
captured data.

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
  treat the 20-group cap (§Selector thresholds) as a **hard ceiling**, not a suggestion.
  **NOTE:** the VP wide-net URL is itself Stage-2 pre-filtered (`ta_highlow52w_a30h`,
  `ta_sma200_sb50`, `ta_sma50_pa`), so per-group name counts are moderate, not raw-universe —
  the realistic load is ~tens of page loads/day, not hundreds.
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

**Wide net (storage scrape), view `v=151`, 84 columns:**
```
https://finviz.com/screener?v=151&f=cap_midover,ind_<slug>,ta_highlow52w_a30h,ta_sma200_sb50,ta_sma50_pa&ft=4&o=wiimdailydigest&c=1,2,4,5,6,7,67,65,66,68,79,8,9,10,13,145,146,33,32,34,37,38,149,16,77,17,18,142,19,20,143,21,23,22,132,133,39,40,41,27,29,42,43,44,45,47,46,138,49,51,48,52,53,54,59,63,64,81,86,87,88,62,69,135,137,136,150,3,12,144,35,36,82,78,28,139,50,57,58,60,61,148,127,128
  filters: cap_midover · ta_highlow52w_a30h (within 30% of 52w high) · ta_sma200_sb50 (50SMA > 200SMA) · ta_sma50_pa (price > 50SMA)
  84 columns (exceeds the original "~70" estimate — even better for attribution)
```
> `%2C` in the raw paste = `,` (URL-encoded comma) — decode before parsing.
> Semiconductors is a large group → doubles as the multi-page pagination validation case.

**Three risks to retire in Phase-1 validation (do NOT assume; verify on an Azure run):**
1. **Custom 84-col `c=` on a free (non-Elite) account.** We already use custom `c=` for the
   *groups* view (`v=152&c=…`) on free, so it's *likely* fine for the screener — but this is the
   single biggest schema risk; confirm all 84 columns render before trusting the header.
2. **`o=wiimdailydigest` sort** looks like a custom/Elite sort token. Low impact (we paginate
   every page, so sort order doesn't affect completeness) — fall back to `o=-change` if it errors.
3. **Stage-2 filters are baked into the "wide" net** (`ta_*` above). This *narrows* what we
   store: names that drop out of Stage-2 vanish from the log, so some counterfactual attribution
   ("did Stage-2 gating add value vs an unfiltered group?") is impossible later. VP confirmed
   wording pending — see Open dependencies. Mild tension with D4's "store wide, filter in-house."

**How the implementer turns that into the pipeline:**

1. **Decompose, don't store monolithically.** Parse each sample URL into its parts and persist
   them in `data/picks/screener_config.json` (one block per template, `wide` and `button`):
   ```json
   {
     "wide": {
       "v": "151",
       "base_filters": ["cap_midover", "ta_highlow52w_a30h", "ta_sma200_sb50", "ta_sma50_pa"],
       "sort": "wiimdailydigest", "ft": "4",
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
  RSI, perf week/month, EPS/sales growth (from the stored ~70 cols). Sort least-extended
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
   snapshots, validate vs live Finviz dropdown (one Actions run). De-risks everything.
2. **Phase 2 — scraper + collection** (core, irreplaceable): `collect_picks.py` (selectors +
   paginated scrape + append), `collect_picks.yml` separate workflow, `data/picks/picks.csv` +
   `picks_latest.csv`. **Start the daily clock ASAP.** URL templates now in hand (decoded
   above); Phase-1 must first retire the 3 free-tier risks (84-col `c=`, sort token, Stage-2-net).
3. **Phase 3 — PWA surfaces:** Picks tab + Lookup-tab section + deep-link button + release.
4. **Phase 4 — attribution** (later, own session): `eval_picks.py`, OHLC backfill, methodology
   comparison.
5. **Spike (optional) — TwelveData/extended indicators** if Finviz columns prove insufficient.

## Open dependencies / questions parked for VP

- [x] **Canonical wide-net + button Finviz URLs** — VP supplied 2026-06-23 (decoded in §VP URL
      handoff). 84-col `c=` list, `cap_midover` + Stage-2 `ta_*` filters, `v=151`/`v=311`.
- [ ] **CONFIRM: keep the Stage-2 `ta_*` filters in the *stored* wide net?** They narrow the log
      (names that exit Stage-2 disappear), foreclosing some counterfactual attribution. Default:
      keep as supplied. Flag if you want a truly unfiltered store for the comparison study.
- [x] Selector thresholds + cap — proposed in §Daily cap (20-group priority-fill, mix per
      category). **VP sign-off still wanted** on the exact numbers/slot split.
- [ ] **VP confirm geography:** `cap_midover` includes foreign listings — keep all (store Country,
      filter later) or restrict to US? Default: keep all.
- [ ] Finviz ToS comfort on ~20 groups × pages/day. Stage-2-filtered net keeps this to ~tens of
      page loads; politeness + cap mitigate. Flag if concern.
- [ ] **`picks.csv` log growth** (non-blocking, VP-noted) — the full append-only log grows
      multi-MB; revisit rotation / git-LFS / yearly partition later. PWA already insulated via
      `picks_latest.csv`, so this does not block collection.
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
