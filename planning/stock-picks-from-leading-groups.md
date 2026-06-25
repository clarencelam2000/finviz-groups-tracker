# Plan: Top-stock picks from leading groups (Stage-2 screener pipeline)

> Status: **READY TO EXECUTE PHASE 2.** All major decisions VP-confirmed (2026-06-23 → 2026-06-25).
> Phase-1.5 spike COMPLETE (2026-06-24) — selector policy locked (see §Spike results).
> Phase-1 probe state: **84-col anonymous/headless/Azure validation DONE** — golden header
> committed (`tests/fixtures/probe_header_84col.txt`, 84 cols populated). **Fetch volume was NOT
> separately measured/recorded;** instead the VP set a **hard 50-page global cap** (2026-06-25,
> revisit after live data flows) — so the daily job is bounded by decision, not by a probe number.
> No remaining gate before Phase 2.

> Ensure you check the cross cutting docs section at the end of this plan for documentation requirements.
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
| D11 | Stored-net breadth + fetch budget | **Store wide (generous superset, relaxed trend gates), tag Stage-2 in-house — bounded & explicitly NOT long-term** (VP accepted cautiously 2026-06-23). Keep `sh_avgvol_o100` liquidity floor, hard per-group + global fetch caps. **Global cap = 50 pages/day (VP-set 2026-06-25; revisit after live data).** Phase-4 sunset back toward the tight net. See §Fetch-volume budget & guardrails. |

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
  picks.csv                    # append-only; date, list_category, selector_version, group, ticker,
                               #   <84 finviz cols>, <grp_* group-metric cols at selection — see spec>
  picks_latest.csv             # latest trading date only — what the PWA fetches (see PWA note)
  finviz_industry_slugs.csv    # industry_name, ind_slug, validated (bool), note  (144 rows; see G4/G5 below)
  screener_config.json         # modular URL config (base f= filters, ordered c= columns, v/o/ft) — see §VP URL handoff
  selector_versions.json       # append-only registry of every selector policy (see §selector_version scheme)
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
| `leaders` | **sum-of-ranks across 1mo+3mo+6mo, no hard gate** (VP-locked 2026-06-24/25): rank all groups by `sum(rank_month + rank_quarter + rank_half)` ascending (lowest sum = strongest mid-TF leader), take the top **8**; then **2 freshness fills** by `momentum_confirmed` desc among groups not already in the 8. **NOT** a top-N intersection gate, and **NOT** the PWA `sustained` view's logic — the PWA's "Sustained" tab gates on top-N in all three timeframes *then* sorts by `momentum_confirmed`; we deliberately do **not** replicate that here (sum-of-ranks degrades gracefully when fewer than 8 groups are top-N in all three). **NOT** `rs_confirmed` alone — that conflates RS-vs-SPY with absolute strength. | n/a — already an absolute-strength definition |
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
- **G2 — expected empty buckets early are NOT failures (Phase-2 executor):** `momentum_accel` is
  NaN until 11 sessions of history exist, so the `accel` bucket legitimately yields **0 groups** on
  the earliest runs (unlocked ~2026-06-25 per the spike). Likewise `rs_new_high`/`rs_score` floors
  need their own history. `select_groups` must treat a 0-group bucket as normal (fill from the next
  priority, total stays ≤ 20), never error, and the run summary should report per-bucket counts so
  an empty bucket is visibly *expected*, not a silent miss.

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
   selection time (the `grp_*` columns spec'd below). Then a later formula change doesn't strand
   past analysis — you re-select historically and compare versions head-to-head.
2. **Keep selection logic in one small module** (`select_groups`) reading named config constants,
   so swapping the leaders rank metric or a floor is a one-line, tested change.

This is also why the *stock filter* (not the group selector) is the irreplaceable axis: group
selection is replayable from `deltas.csv`; per-stock point-in-time technicals are not.

#### `selector_version` scheme (VP-confirmed direction 2026-06-25) — versioned registry

The VP's intent: **keep a permanent historical record of every selector policy ever used**, with
enforced version uniqueness, AWS-revision-style. Recommended implementation (decided here; mirrors
the repo's existing `releases.json` pattern rather than inventing a new convention):

- **`SELECTOR_VERSION`** is a single monotonic string constant in `collect_picks.py`, starting at
  **`"v1"`** (`v2`, `v3`, … — like AWS task-definition *revisions*: integers, immutable once
  published, never reused). It is stamped onto every `picks.csv` row as the `selector_version`
  column.
- **A committed append-only registry `data/picks/selector_versions.json`** records, newest-first,
  one entry per version: `version`, `effective_date`, `description` (prose: what changed and why),
  and a `params` block snapshotting **every** constant the selector used (slot split, floors,
  percentile cutoff, ranking-metric name, cap). This makes each version *self-describing* — a reader
  reconstructs the exact policy without `git blame`.
- **The rule (enforced by test):** any change to selection **logic OR any `params` value** ⇒ a new
  version id + a new prepended registry entry. **Published entries are immutable** — a test pins a
  hash of each non-active entry so an accidental edit to history fails CI; a second test asserts the
  active `SELECTOR_VERSION` has exactly one matching registry entry and that all versions are unique
  and monotonic.
- **Why a single registry file, not one config-file-per-version:** a JSON the implementer asked
  about (per-version files) gives the same immutability guarantee but adds directory ceremony and a
  loader that must pick the active file; the append-only registry is one diff-friendly file,
  consistent with how `docs/releases.json` already works here, and the immutability is enforced by
  the hash test either way. **Important caveat documented for both approaches:** the registry
  captures *constants*, not arbitrary *code* changes. If someone alters the ranking math in
  `select_groups` without bumping `SELECTOR_VERSION`, the stamp lies. The mitigation is the same
  bump rule above + code review — note it explicitly in ADR-007 so the obligation is visible.

#### Group-metric columns stamped onto `picks.csv` (`grp_*`) — exact spec

**Why these exist (VP-level):** when `select_groups` picks a group on a given day, the group
qualified *because* of specific group-level numbers from `deltas.csv` (its sum-of-mid-ranks, its
`momentum_confirmed`, its `regime_short_long`, its `rs_score`, etc.). Phase-4 attribution will ask
questions like *"did groups picked for high `momentum_confirmed` produce better stocks than groups
picked for high `regime_short_long`?"* — and we want to answer that **without re-deriving from
`deltas.csv`** (which is replayable but couples attribution to selector internals that may have
changed). So we **snapshot the qualifying group metrics onto every stock row** at selection time.

**Spec (fixed header, every category writes the same columns; blank where N/A for that category).**
Prefix all with **`grp_`** to avoid collision with the 84 Finviz stock columns:

| Column | Source (`deltas.csv` unless noted) | Purpose |
|--------|-------------------------------------|---------|
| `grp_rank_basis` | computed | `"sustained_strength"` (the 8) / `"freshness_fill"` (the 2) / category name for the other buckets — which rule won the slot |
| `grp_sum_mid_rank` | `rank_month + rank_quarter + rank_half` | the leaders ranking value |
| `grp_rank_month`, `grp_rank_quarter`, `grp_rank_half` | as named | transparency / re-derive sum |
| `grp_momentum_confirmed` | `momentum_confirmed` | leaders freshness-fill basis |
| `grp_momentum_score` | `momentum_score` | floor input |
| `grp_momentum_score_pctile` | computed cross-sectionally that day | the top-40% anti-flash floor value actually used |
| `grp_momentum_accel` | `momentum_accel` | `accel` bucket basis |
| `grp_regime_short_long` | `regime_short_long` | `emerging` bucket basis |
| `grp_rs_score` | `rs_score` | floor input for emerging/accel/rs_new_high |
| `grp_rs_new_high` | `rs_new_high` | `rs_new_high` bucket basis |
| `grp_rs_slope` | `rs_slope` | `rs_new_high` rank-within basis |

**Decisions baked in here:** (a) **inline columns, not a sidecar file** — a modest fixed set (~13),
and inline means attribution joins nothing and the row is self-contained; a sidecar would add a
second append-only file to keep consistent. (b) These `grp_*` columns are **append-only under the
same header-migration discipline** as the 84 stock columns (adding one later is a schema bump via
the `ensure_deltas_csv()`-style superset rewrite). (c) Storing `grp_momentum_score_pctile` (the
*computed percentile*, not just the raw score) is deliberate — it records the actual floor decision,
which is invariant to later `momentum_score` formula rescaling (the whole point of the percentile
floor per §anti-flash).

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
concern. Honoring that requires a hard cap and guardrails:

- **Volume is bounded by decision, not estimate.** "Store wide" *loosens the row filter*, so big
  industries (Semis ≈ 100–200 names) become several pages each. Rather than gate on a probe-measured
  number, **the VP set a hard global cap of 50 screener pages/day (2026-06-25)**. The job scrapes in
  priority order (leaders first) and **stops at 50 pages**, so the worst case is bounded regardless
  of how many names each group has. Revisit the cap once live data shows real daily page demand.
- **Keep the liquidity floor as a volume ally.** Retain `sh_avgvol_o100` (avg vol > 100K) even in
  the "wide" net — it is defensible on its own merits (we want liquid, institutional-friendly
  names) AND it is a large reducer of junk rows / pages. Relax only the *trend* gates that cause
  survivorship — `ta_sma200_sb50` (50SMA > 200SMA) and `ta_sma50_pa` (price > 50SMA), **both
  removed 2026-06-24** — and recompute strict Stage-2 as an in-house boolean column.
  **`ta_highlow52w_a20h` is KEPT** — and note its semantics: it means **more than 20% ABOVE the
  52-week LOW** (a bottom-of-the-barrel exclusion that filters out beaten-down names), *not* "within
  20% of the 52-week high." It is a floor-above-lows quality filter, not a near-high trend gate, so
  it does not create the same survivorship problem the SMA gates did. (Earlier drafts mislabeled
  this as `ta_highlow52w_a30h` "within 20% of high" — that was wrong on both the threshold and the
  direction.)
- **Hard guardrails in `collect_picks.py`:** per-group page cap (`PAGE_CAP`), **global daily page
  cap `GLOBAL_FETCH_CAP = 50`**, polite inter-fetch delay, and **stop scraping once the global cap
  is reached** (priority order ensures leaders are captured first) rather than silently exceeding
  it. Caps are configurable constants (triple-doc per house rules).
- **Sunset trigger (the "not LT" promise, in writing).** Once Phase-4 attribution identifies which
  signals actually predict winners, **narrow the stored net** to those — dropping back toward the
  tight Stage-2 volume. This is a tracked obligation, not an aspiration: revisit at the first
  attribution review, alongside the 50-page cap.

## Finviz scraping notes (carry-over from collect.py + new)

- **Same Cloudflare block as collect.py** — must run on **Azure (GitHub Actions)**, not cloud
  Claude (Google Cloud IPs get `cf-mitigated: challenge`). Playwright headless Chromium.
- **Pagination (NEW):** `v=151` returns ~20 rows/page. Walk `&r=1`, `&r=21`, `&r=41`… until a
  page returns fewer than the page size (or repeats). A wide net on a big industry = 50+ names.
- **Politeness:** delay between page loads and between groups (the separate workflow per D7
  isolates this from the core EOD snapshot). ~20–30 groups × pages = real volume — keep it
  human-paced and consider a daily cap.
- **Volume is the #1 feasibility risk — see §Fetch-volume budget & guardrails (D11).** With the
  chosen "store wide" breadth, load is a real escalation over today's 2 group page loads, against
  Finviz's *screener* (more bot-sensitive than the groups view). It is **bounded by the VP-set hard
  cap of 50 screener pages/day** (not estimated): the job scrapes in priority order and stops at 50.
  Mitigations are mandatory, not optional: liquidity floor, per-group + global page caps, polite
  delays, and a Phase-4 sunset back toward the tight net. At a 3–5s delay, 50 pages is a ~3–5 min
  Actions job.
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
  > **GOTCHA (verified 2026-06-25): `collect.yml` currently has NO `concurrency:` block** (only
  > `generate_ai.yml` does). A concurrency group only serializes workflows that *both* declare the
  > **same group name**. So Phase 2 must edit **both** files — add an identical
  > `concurrency: { group: finviz-data-commit, cancel-in-progress: false }` (use
  > `cancel-in-progress: false` so neither data job is killed mid-run) to `collect.yml` **and**
  > `collect_picks.yml`. Adding it to only the new workflow gives no protection. This is a required
  > edit to an existing file, not net-new code.
- **Slug derivation:** `ind_<slug>` where `slug` = `name.lower()` with all non-alphanumerics
  stripped. Verified: `Aerospace & Defense → aerospacedefense`, `Software - Application →
  softwareapplication`. **Build the 144 from `data/industries/snapshots.csv`, NOT
  `taxonomy_map.csv`** (the latter is the incomplete FMP→Finviz map — missing ~17 industries).
  No pre-flight live-dropdown validation against all 144 slugs — that's disproportionate effort.
  Instead: **fail loud at scrape time** — if a group returns 0 result rows, log a clear WARNING
  with the slug and group name, skip that group, and surface it in the run summary. **GOTCHA: a
  wrong slug does NOT 404** — Finviz returns HTTP 200 with an empty table. So the scraper must
  check row count > 0, not just HTTP status.
  - **G4 — `validated` column lifecycle (VP-confirmed 2026-06-25):** the slug map ships with
    `validated=false` for all rows (it's derived math, never live-checked). **Phase 2 flips a
    row's `validated` to `true` the first time that group is actually scraped and returns
    row-count > 0** — i.e. validation is a side effect of a successful live scrape, written back to
    `finviz_industry_slugs.csv` (committed on the same run). A row that scrapes 0 rows stays
    `validated=false` and is surfaced in the run summary as a suspect slug. This gives a
    self-building, evidence-backed validation record without a separate pre-flight pass.
  - **G5 — count is 144, not 145; `Infrastructure Operations` excluded (VP-confirmed 2026-06-25):**
    Finviz no longer carries an `Infrastructure Operations` industry. The slug map is built from
    `data/industries/snapshots.csv` (144 industries) which already excludes it, so no action is
    needed *here*. (Separate, out-of-scope cleanup: stale `Infrastructure Operations` references
    still live in `data/finviz_sector_industry_map.{json,csv}`, `tests/test_seed_taxonomy.py`, and
    `CLAUDE.md` — track as its own follow-up PR since it touches `seed_taxonomy` validation.)
- **URL templates (VP-supplied 2026-06-23, decoded below).** Handling, validation, and
  modularity are specified in §VP URL handoff & modular screener config.

## VP URL handoff & modular screener config

**What the VP provides:** *one* full sample screener URL per template — the **wide-net (storage)**
URL and the **tight Stage-2 (button)** URL — for *any single* industry. The VP does **not**
hand-build 144 URLs; they paste two example URLs and the implementer parameterizes them.

6/24/2026 VP provided a less restrictive URL, removing some technical filters: https://finviz.com/screener?v=151&f=cap_midover,ind_semiconductors,sh_avgvol_o100,ta_highlow52w_a20h&ft=4&o=-marketcap&c=1,2,4,5,6,7,67,65,66,68,79,8,9,10,13,145,146,33,32,34,37,38,149,16,77,17,18,142,19,20,143,21,23,22,132,133,39,40,41,27,29,42,43,44,45,47,46,138,49,51,48,52,53,54,59,63,64,81,86,87,88,62,69,135,137,136,150,3,12,144,35,36,82,78,28,139,50,57,58,60,61,148,127,128 

### VP-supplied samples (2026-06-23) — decoded

**Button (tight Stage-2), view `v=311`:**
```
https://finviz.com/screener?v=311&f=cap_midover,ind_<slug>,ta_sma20_sa50,ta_sma50_pa&ft=4&o=sma50
  filters: cap_midover · ta_sma20_sa50 (20SMA > 50SMA) · ta_sma50_pa (price > 50SMA)
```

**Wide net (storage scrape), view `v=151`, 84 columns (revised URL, 2026-06-24):**
```
https://finviz.com/screener?v=151&f=cap_midover,ind_<slug>,sh_avgvol_o100,ta_highlow52w_a20h&ft=4&o=-marketcap&c=1,2,4,5,6,7,67,65,66,68,79,8,9,10,13,145,146,33,32,34,37,38,149,16,77,17,18,142,19,20,143,21,23,22,132,133,39,40,41,27,29,42,43,44,45,47,46,138,49,51,48,52,53,54,59,63,64,81,86,87,88,62,69,135,137,136,150,3,12,144,35,36,82,78,28,139,50,57,58,60,61,148,127,128
  filters: cap_midover · sh_avgvol_o100 (avg vol > 100K — liquidity floor) · ta_highlow52w_a20h
           (more than 20% ABOVE the 52-week LOW — a bottom-of-barrel exclusion, NOT "near the
            52w high"; VP-clarified 2026-06-25)
  sort: o=-marketcap (biggest first — institutional-friendly leaders on top)
  84 columns (exceeds the original "~70" estimate — even better for attribution)
  Note: ta_sma200_sb50 (50SMA > 200SMA) and ta_sma50_pa (price > 50SMA) removed 2026-06-24 per VP —
  those SMA trend gates cause survivorship bias; Stage-2 qualification recomputed in-house from
  stored columns. ta_highlow52w_a20h is KEPT: as a floor-above-the-low it screens out beaten-down
  names without the near-high survivorship problem the SMA gates had.
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
   filters" clarification in §Finviz scraping notes and the survivorship discussion. 

**How the implementer turns that into the pipeline:**

1. **Decompose, don't store monolithically.** Parse each sample URL into its parts and persist
   them in `data/picks/screener_config.json` (one block per template, `wide` and `button`):
   ```json
   {
     "wide": {
       "v": "151",
       "base_filters": ["cap_midover", "sh_avgvol_o100", "ta_highlow52w_a20h"],
       "sort": "-marketcap", "ft": "4",
       "columns": [{"id": 1, "label": "Ticker"}, {"id": 65, "label": "Price"}, ...]  // 84 ids, ordered
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
2. **Phase 2 — scraper + collection** (core, irreplaceable). **No blockers remain — all inputs are
   in hand.** Executable checklist:
   - `select_groups(deltas_df)` → leaders (8 sum-of-ranks + 2 momentum_confirmed fills), emerging,
     accel, rs_new_high with top-40% floors; dedup to ≤ 20 unique groups; emit `grp_*` snapshot +
     `selector_version`. (No Finviz access; fully unit-testable against `deltas.csv`.)
   - `collect_picks.py` paginated scrape (`&r=` walk, stop at empty/short page or `PAGE_CAP`),
     header→label map, **stop at `GLOBAL_FETCH_CAP = 50` pages** in priority order, append to
     `picks.csv` (dedup key `(date, list_category, ticker)`), rewrite `picks_latest.csv` (max-date
     slice), flip `validated=true` on groups that returned rows (G4). Assert
     `deltas['date'].max() == trading_date()` before scraping.
   - `collect_picks.yml` separate workflow, own EOD cron after `collect.py`, **shared
     `concurrency: { group: finviz-data-commit, cancel-in-progress: false }` added to BOTH this
     file and `collect.yml`** (G1), rebase-before-push.
   - Seed `selector_versions.json` `v1`; add all tests above; triple-doc the constants; write
     ADR-007 + ADR-008.
   - **Start the daily clock ASAP** — the daily capture is the irreplaceable work.
3. **Phase 3 — PWA surfaces:** Picks tab + Lookup-tab section + deep-link button + release.
4. **Phase 4 — attribution** (later, own session): `eval_picks.py`, OHLC backfill, methodology
   comparison.
5. **Spike (optional) — TwelveData/extended indicators** if Finviz columns prove insufficient.

## Open dependencies / questions parked for VP

- [x] **Canonical wide-net + button Finviz URLs** — VP supplied 2026-06-23 (decoded in §VP URL
      handoff). 84-col `c=` list, `cap_midover` + Stage-2 `ta_*` filters, `v=151`/`v=311`.
- [x] **Stored-net breadth (D11)** — VP chose **store wide + tag in-house**, *cautiously*, as an
      explicitly **non-LT** solution. Keep liquidity floor, relax trend gates, hard fetch caps,
      Phase-4 sunset. Volume bounded by a **hard 50-page/day cap** (VP-set 2026-06-25), not a
      probe estimate. See §Fetch-volume budget.
- [x] **Selector spike COMPLETE (2026-06-24)** — leaders ranking metric + cap/floor split locked.
      See §Spike results. Metric: Approach 1 (8 SS + 2 MC freshness fills). Floor: top 40%
      by momentum_score percentile. Slot split: 10/4/3/3 confirmed. NOT `rs_confirmed` alone.
- [x] **Geography** — include foreign ADRs (VP confirmed 2026-06-24). `sh_avgvol_o100` liquidity
      floor handles quality screening. Store `Country` column; filter locally if needed later.
- [x] **Finviz ToS / Azure IP** — no evidence of GitHub Actions Azure IPs being blocked at the
      screener. Rate limiting is request-velocity-based, not IP-based. Mitigated by polite
      inter-fetch delays and a hard fetch cap. Existing `collect.py` already runs from Azure
      without issues (different endpoint, same IP pool).
- [x] **Fetch volume bound** — superseded: rather than gate on a probe-measured number, the VP set
      a **hard 50-page/day global cap** (2026-06-25). `GLOBAL_FETCH_CAP = 50`; revisit after live
      data shows real daily page demand. No probe sign-off blocks Phase 2.
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
  - **`select_groups` leaders test must assert sum-of-ranks ordering** (8 by lowest
    `rank_month+rank_quarter+rank_half`, then 2 by `momentum_confirmed` not already chosen) — and a
    regression case where **fewer than 8 groups are top-N in all three timeframes**, proving we do
    NOT use a hard intersection gate (degrades gracefully, still fills 8).
  - **Global-cap test:** with many qualifying groups, scrape stops at `GLOBAL_FETCH_CAP = 50` pages
    in priority order (leaders first); assert no 51st page is requested.
  - **`grp_*` snapshot test:** a selected leader's row carries the correct `grp_rank_basis`,
    `grp_sum_mid_rank`, and floor `grp_momentum_score_pctile` for that day.
  - **Empty-bucket test (G2):** all-NaN `momentum_accel` ⇒ `accel` bucket = 0 groups, no error,
    total still ≤ 20 by filling next priority.
- **`selector_version` registry tests:** (a) active `SELECTOR_VERSION` has exactly one matching
  entry in `selector_versions.json`; (b) versions are unique + monotonic; (c) immutability — a
  committed hash of each non-active entry fails CI if history is edited.
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

## Documentation ATTENTION: Cross-cutting docs — picks pipeline (you must update alongside the phase that introduces the feature)

Phase 2 (collect_picks.py + workflow):
  knowledge/decisions/ADR-007-picks-selector-policy.md — document the leaders **sum-of-ranks (8) +
    momentum_confirmed freshness-fill (2)** decision and why it deliberately does NOT reuse the PWA
    `sustained` intersection-gate logic; why rs_confirmed was rejected; anti-flash floor (top-40%
    percentile) rationale; `selector_version` bump rule + the "registry captures constants not code"
    caveat; fetch-budget trade-offs.
  knowledge/decisions/ADR-008-picks-collection-architecture.md (NEW — VP asked, 2026-06-25) — this
    is a heavy workstream with many structural decisions that don't belong in the selector ADR:
    separate `collect_picks.yml` workflow + shared concurrency group (D7); store-wide-columns vs
    tight-filters axis (D5/D11) and the 50-page hard cap; membership-only append-only log + derive
    positions offline (D9); `picks_latest.csv` PWA-fetch split; `grp_*` snapshot-at-selection
    columns; survivorship trade-off (only in-screen names are ever logged). Cross-link ADR-007.
  README.md § Configurable parameters — rows for every cap/slot/delay constant:
    DAILY_GROUP_CAP (20), LEADER_SS_SLOTS (8), LEADER_MC_SLOTS (2), EMERGING_SLOTS (4),
    ACCEL_SLOTS (3), RS_NH_SLOTS (3), ANTIFLASH_PCTILE (0.40), per-group PAGE_CAP,
    GLOBAL_FETCH_CAP (50), PAGE_DELAY_S, SELECTOR_VERSION ("v1").
  CLAUDE.md — add § Picks pipeline: key scripts, data layout (picks.csv / picks_latest.csv /
    selector_versions.json), workflow trigger and **shared concurrency guard (note collect.yml must
    gain the group too)**, selector categories, `grp_*` columns, 50-page fetch cap.
  data/picks/screener_config.json labels — must stay verbatim-synced to
    tests/fixtures/probe_header_84col.txt; re-run probe if Finviz view changes.
  data/picks/selector_versions.json — seed the `v1` entry in the same PR that lands select_groups;
    add the immutability + uniqueness tests (see §selector_version scheme).

Phase 3 (PWA surfaces):
  docs/releases.json + docs/sw.js CACHE bump (house rule: every user-facing change).
  knowledge/moaty-metrics.md — one-liner for any new metric surfaced in the Picks tab
    (extension from 50SMA, 52w-high distance, etc.).
  planning/stock-picks-from-leading-groups.md — update Phase 3 status to COMPLETE.

Per-phase (always):
  .session/SPRINT.md — move completed tasks, add new backlog items.
  .session/WORK_LOG.md — milestone entry when each phase lands end-to-end.
  planning/stock-picks-from-leading-groups.md — update phase status at top of file and mark phases complete as you go.
