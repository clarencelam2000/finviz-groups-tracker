# Plan: Top-stock picks from leading groups (Stage-2 screener pipeline)

> Status: **PHASE 3a COMPLETE (2026-06-26)** — Picks tab MVP shipped. Backend metrics
> (`atr_ext_50`, `risk_20ma_pct`, `risk_50ma_pct`, `range_atr`, `stage2`) in picks.csv/picks_latest.csv;
> one historical date backfilled via `ensure_picks_csv`. PWA Picks tab renders grouped by
> category→industry, sorted least-extended first, C4 color bands, C6 base filter. All acceptance
> criteria met; 80 tests pass. Release triplet present (v2026.06.26). Phase 3b (risk panel + Focus
> List) is next.
>
> Status: **PHASE 3b/3c SPEC REFINED & LOCKED (2026-06-27, staff review + CEO).** §3b/§3c rewritten:
> `renderPickRow()` refactor (3b.0); expandable risk panel + 3 tightness lines (Range/ATR, Volatility
> (ATR %), Stop distance (ATR)); Focus score now **one min–max ruler for all components** +
> **multiplicative extension discount** (`score = base × (1 − penalty)`, always ∈ [0,1]) +
> **nearest-MA stop tightness** (`min(positive risk_20, risk_50)` — fixes the below-20MA bug, gives the
> "either MA" reward); 3c button **inlined + anti-drift test** (no fetch), inline slugify, **both
> `renderLookup()` branches**, **sector `sec_<slug>` button**. New tracked tasks: PICKS-3B-FOCUSGATE,
> PICKS-3B-FOCUSTEST, PICKS-3D-STACKEDSTOP. **Ready for an implementer — no open blockers.**
>
> Status: **PHASE 2 LIVE (2026-06-25)** — first `collect_picks.yml` dispatch GREEN. Daily capture
> started. 273 stock picks / 262 unique tickers / 19 industry groups across all 4 buckets.
> 19/19 scraped slugs validated. Dedup logic confirmed (Packaging & Containers tagged in both
> `emerging` + `accel`, scraped once). `picks_latest.csv` correct. **Phase 3 (PWA surfaces) is
> unblocked — gate cleared.** Phase 3 is now **SPEC LOCKED (CEO-aligned 2026-06-26)** — see the
> detailed §"Phase 3 — PWA surfaces (DETAILED SPEC)" below; ready for an implementer (subphases
> 3a→3d, with acceptance criteria + tests). Phase 3a COMPLETE.
> Fast-follows still open: PICKS-2-ADR8 (ADR-008 grp_* reconciliation), PICKS-2-HDR (live
> header drift detection), PICKS-2-CRON (Cloudflare cron dispatcher for picks). See SPRINT.
>
> Status: **PHASE 2 CODE COMPLETE (2026-06-25)** — all checklist items landed: `collect_picks.py`,
> `picks_config.py`, `select_groups`, pagination/append, `collect_picks.yml` (shared concurrency on
> BOTH workflows), `selector_versions.json` v1, 30 unit tests, triple-doc'd constants, ADR-007/008.


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

**One-way/two-way door analysis:**
- *Adding `grp_*` columns later:* **two-way door** — superset migration (same as
  `ensure_deltas_csv()`) adds columns with blank backfill for old rows.
- *Renaming/removing existing columns:* **effectively one-way** once data flows — historical
  rows carry the old name, attribution queries referencing it break or silently get blanks.
  The column names chosen below are sticky. Pick them carefully before Phase 2 starts.
- *Column semantics changing:* acceptable if the value genuinely changes (e.g.
  `grp_momentum_score_pctile` records the actual computed percentile per day — it can shift
  if the formula or floor changes, and that's correct). Document any semantic shift with a
  `selector_version` bump.

**Spec (fixed header, every category writes all columns; blank where N/A for that category).**
Prefix all with **`grp_`** to avoid collision with the 84 Finviz stock columns:

| Column | Source (`deltas.csv` unless noted) | Purpose |
|--------|-------------------------------------|---------|
| `grp_rank_basis` | computed | `"sustained_strength"` (the 8) / `"freshness_fill"` (the 2) for leaders rows; **category name for the other buckets** - which rule won the slot, i.e `list_category` for non-leaders. Captures the within-leaders sub-rule for attribution — "did freshness fills underperform core slots?" |
| `grp_category_rank` | computed | **Integer: within-bucket rank among all qualifying candidates for that bucket**, sorted by the bucket's rank-within criterion (sum-of-ranks asc for leaders SS; `momentum_confirmed` desc for leaders freshness-fill; `regime_short_long` desc for emerging; `momentum_accel` desc for accel; `rs_slope` desc for rs_new_high). Rank 1 = strongest qualifying candidate in that category that day. For dedup groups appearing in multiple categories, each category row independently assigns the counterfactual within-bucket rank — meaningful for per-category attribution even though the slot was already claimed by a higher-priority bucket. Cannot be added retroactively — requires the full daily candidate pool, not stored in `deltas.csv`. |
| `grp_sum_mid_rank` | `rank_month + rank_quarter + rank_half` | the leaders sustained_strength ranking value; pre-computed convenience (derivable from the three component columns below) |
| `grp_rank_month`, `grp_rank_quarter`, `grp_rank_half` | as named | components of sum; re-derive sum or diagnose which timeframe drove the ranking |
| `grp_momentum_confirmed` | `momentum_confirmed` | leaders freshness-fill basis; strength × agreement |
| `grp_momentum_score` | `momentum_score` | floor input for accel/rs_new_high anti-flash; also cross-sectional peer-rank momentum signal |
| `grp_momentum_score_pctile` | computed cross-sectionally that day | the top-40% anti-flash floor value actually used; invariant to formula rescaling (see §anti-flash floor) |
| `grp_momentum_accel` | `momentum_accel` | `accel` bucket basis; NaN until 11 sessions of history |
| `grp_momentum_weighted_mid` | `momentum_weighted_mid` | explicit spike runner-up (Jaccard 0.650 vs sustained_strength 0.691); stored so Phase-4 can test head-to-head whether it would have selected better groups (same rationale as `grp_rs_confirmed`) |
| `grp_rank_agreement` | `rank_agreement` | cross-timeframe rank sign agreement; explicitly tested in spike (Jaccard 0.578, rejected as primary); stored for Phase-4 head-to-head comparison |
| `grp_regime_short_long` | `regime_short_long` | `emerging` bucket basis |
| `grp_rs_score` | `rs_score` | floor input for emerging/accel/rs_new_high; already a stable 0–1 fraction (fraction of timeframes beating SPY) — no `_pctile` variant needed (see note (e) below) |
| `grp_rs_agreement` | `rs_agreement` | RS directional consistency across mo/qtr/half; needed to independently re-derive `rs_confirmed` |
| `grp_rs_confirmed` | `rs_confirmed` | rs_score × rs_agreement; **explicitly rejected as the leaders metric** (see ADR-007) but stored so Phase-4 can test head-to-head whether it would have selected better groups |
| `grp_rs_accel` | `rs_accel` | RS-score acceleration over ACCEL_WINDOW sessions; RS-domain analog of `grp_momentum_accel`; measures whether outperformance vs SPY is building at selection time |
| `grp_rs_new_high` | `rs_new_high` | `rs_new_high` bucket basis |
| `grp_rs_slope` | `rs_slope` | `rs_new_high` rank-within basis; LS slope of `rs_month` over trailing window |

**Decisions baked in here:**

(a) **Inline columns, not a sidecar file** — 19 columns is manageable, and inline means attribution joins nothing and the row is self-contained.

(b) These `grp_*` columns are **append-only under the same header-migration discipline** as the 84 stock columns (adding one later is a schema bump via superset rewrite).

(c) **`grp_momentum_score_pctile`** (the *computed percentile*, not just the raw score) records the actual floor decision, invariant to `momentum_score` formula rescaling.

(d) **No `grp_rs_score_pctile`** — `rs_score` is already an absolute cross-sectionally stable fraction (fraction of timeframes where the group beats SPY). Unlike `momentum_score` which is a peer-rank metric that rescales if timeframes are added/removed, `rs_score` has a fixed denominator tied to market behavior. A percentile-of-a-fraction would lose the economic meaning. The raw value is the right thing to store.

(e) **`grp_category_rank` for dedup groups**: when a group qualifies in multiple buckets (e.g. Semis as both `leaders` and `accel`), each category row gets its own independently-computed within-bucket rank. The `accel` row's `grp_category_rank` is the counterfactual rank — "where would this group rank if only considering accel candidates?" The slot was already claimed by the leaders bucket, but the rank is still meaningful for per-category attribution ("did the #1-ranked accel candidate, even if it was also a leader, have better picks than the #3-ranked accel candidate?").

(f) **Rejected-alternative storage policy**: `grp_rs_confirmed`, `grp_momentum_weighted_mid`, and `grp_rank_agreement` are all stored despite not being active gates — they are the explicitly-measured alternatives from the selector spike. Phase-4 head-to-head comparison is the payoff.

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

---

# Phase 3 — PWA surfaces (DETAILED SPEC, CEO-aligned 2026-06-26)

> Status: **SPEC LOCKED, NOT STARTED.** This section supersedes the terse §PWA (D8) bullets above
> for implementation. Read it top-to-bottom before touching code. The §PWA (D8) bullets remain as
> the original D8 intent; where they differ, **this section wins** (CEO refinements 2026-06-26).
>
> **The product, in one line:** *every trading day, the strongest individual stocks inside the
> strongest groups — with a "Focus/Ready" highlights list of A++ actionable setups that are not
> over-extended, carry tight logical-stop risk, and sit in the leading groups.* This is the new
> crown-jewel feature.

## CEO decisions locked (2026-06-26)

| # | Decision | Choice |
|---|----------|--------|
| C1 | Inside-day / tightness fidelity | **Range/ATR proxy now** (`(High−Low)/ATR`, single-row). True inside-day deferred to 3d. |
| C2 | Focus List placement | **Toggle inside the Picks tab** (`All / Focus` segment), not a separate tab. |
| C3 | Logical-stop default | **20MA tight stop is the default; 50MA shown as the wider alternative.** |
| C4 | ATR-extension bands | **`atr_ext_50 ≤ 5` actionable; `5–8` caution; `≥ 8` trim-candidate.** |
| C5 | Where the math lives | **Raw derived metrics → backend columns** (single source of truth, pytest-testable, reused by Phase-4 attribution). **Decision thresholds + Focus weights → PWA constants** (tuned frequently; one-line edit + cache bump). See §C5 rationale. |
| C6 | Picks-tab base display filter | **`market_cap > 5B` AND (`price>50MA` OR `price>200MA` OR `20MA>50MA`).** Cuts the daily list from ~273 rows to ~165 (verified on 2026-06-25 data). |
| C7 | Focus scoring philosophy | **Blended multi-factor quality rank** (not a single-axis sort). Proximity-to-50MA is NOT a positive factor. See §Focus List. |
| C8 | RSI gate | **None.** RSI is display-only. |
| C9 | Fundamental floor | **Deferred to 3d**, and when applied, **show an "Honorable mentions" sub-list** of names the floor removed (so we can eyeball whether the floor is too aggressive — it's an un-calibrated judgment call at first). |

### §C5 rationale — backend vs PWA split (answers CEO's "does it matter?")

It matters, and here is the principled line:

- **Backend (new columns in `picks.csv` + `picks_latest.csv`, computed at write time in
  `collect_picks.py` using helpers in `picks_config.py`):** the *raw derived metrics* —
  `atr_ext_50`, `risk_20ma_pct`, `risk_50ma_pct`, `range_atr`, `stage2`. Why backend: (1) **single
  source of truth** — the extension number a trader sees on the card is byte-identical to the one
  Phase-4 attribution analyses; (2) **pytest-testable** — our test suite covers Python, not the
  PWA's inline JS; (3) keeps PWA rendering thin; (4) **the migration is free right now** — history
  is a single day (2026-06-25), so the append-only schema bump backfills exactly one date. This is
  the cheapest this change will ever be. These columns are deterministic functions of already-stored
  Finviz columns, so they need **no `selector_version` bump** — document them as a plain schema
  addition (superset append, same discipline as `ensure_deltas_csv()`).
- **PWA constants (`index.html`, alongside the existing `REGIME_THRESHOLD` / `ACCEL_*` / `SLOPE_*`
  family):** the *decision thresholds and Focus scoring weights* — `ATR_EXT_ACTIONABLE` (5),
  `ATR_EXT_TRIM` (8), `ATR_EXT_PENALTY_START` (3.5), `MIN_MARKET_CAP_B` (5), and the Focus weight
  set. Why PWA: these are the knobs we will tune frequently ("we're just starting off, we'll adjust
  over time" — CEO), and the repo's established pattern is that PWA display/decision thresholds live
  in `index.html`. Tuning one = a one-line edit + a `sw.js` CACHE bump, with **no scraper re-run and
  no data migration**.

> **Note for the implementer:** adding the backend derived columns is a small post-scrape transform
> — it does **not** change *what we fetch from Finviz* (the `c=`/`f=` URL is untouched). It runs on
> the already-scraped rows. Do not confuse this with a scrape change.

## Phase 3a — Picks tab MVP (the crown-jewel list)

**Goal:** a new top-level **Picks** tab that renders the daily list, grouped and sorted, with the
ATR-extension metric as the headline number. Shippable on its own.

### 3a.0 — Backend derived metrics (do this first; it's the data foundation)

Add a pure helper module **`scripts/picks_metrics.py`** (mirrors the `compute_deltas.py` /
`delta_config.py` split: schema/constants in config, computation logic in a dedicated script)
computing, per row, from the already-stored Finviz columns. **All Finviz percent columns are strings
like `"51.84%"`; market cap like `"336.47B"` / `"850.00M"`; ATR/Price/High/Low are plain floats.**
Provide robust parsers (`_pct()`, `_cap_b()` handling `T/B/M/K`, empty→NaN).

Derivations (note: Finviz `SMA20/SMA50/SMA200` columns are **percent of price above that MA**):

```
sma50_price   = Price / (1 + SMA50/100)          # reconstruct the MA level in dollars
sma20_price   = Price / (1 + SMA20/100)
dist_to_50ma  = Price - sma50_price              # dollars; negative if price below 50MA
atr_ext_50    = dist_to_50ma / ATR               # CEO's "rubber-band" stretch, in ATR multiples
risk_20ma_pct = (price - sma20_price) / price     # current price to 20MA stop; fraction
risk_50ma_pct = (price - sma50_price) / price    # wider stop alternative
range_atr     = (High - Low) / ATR               # tightness proxy (C1); small = quiet/narrow bar
stage2        = (SMA50 > 0) AND (sma50_price > sma200_price)   # price>50MA AND 50MA>200MA, in-house
```

`stage2` uses `sma200_price = Price/(1+SMA200/100)`; `sma50_price > sma200_price` ⟺ `SMA50 < SMA200`
in percent terms (lower %-above means the higher MA level). Implement via the dollar levels to avoid
sign confusion.

- New columns appended to **both** `picks.csv` and `picks_latest.csv`:
  `atr_ext_50, risk_20ma_pct, risk_50ma_pct, range_atr, stage2`.
- **Migration: use the `ensure_picks_csv()` pattern** (analogue to `ensure_deltas_csv()` in
  `compute_deltas.py`). At the top of `collect_picks.py main()`, call `ensure_picks_csv(PICKS_CSV)`
  which: (a) checks if the header already contains the new columns; if so, no-op; (b) if not,
  recomputes the derived values row-by-row from the already-stored Finviz columns and rewrites the
  file in-place (atomic tmp-rename). Then slice `picks_latest.csv` from the updated `picks.csv`.
  This is a one-time auto-migration — after day 1 it is a pure no-op. Do **not** write a one-off
  migration script; the `ensure_picks_csv()` in-main pattern is self-documenting and survives
  future column additions the same way.
- NaN-safe: any missing input (blank ATR, blank SMA) → NaN for that derived field; the PWA renders a
  dim `—` and the row is never crashed or silently zeroed.
- Place these **after** the `grp_*` block to preserve the existing golden-header superset guard
  (append-only; reorder/removal still fails the header test).

### 3a.1 — Tab + data load

- Add a `Picks` tab button (`data-tab="picks"`) to `#tab-bar` and a `<section id="tab-picks">`
  (mirror the existing 7-tab pattern at `docs/index.html:82-90` / `:96+`). Wire into `switchTab`.
- Fetch `${BASE}/picks/picks_latest.csv` (same `RAW_BASE` pattern as the other CSVs, `docs/index.html:306`).
- Empty/headers-only CSV → friendly placeholder ("No picks captured yet — the daily job runs after
  the close."). Never crash on a blocked-scrape day.
- **Adding a tab triggers anti-drift test requirements — do ALL of the following in the same PR:**
  1. Add `"picks"` entry to the `tabs-tour` slide in the `WELCOME` constant (`docs/index.html` near
     the `id: 'tabs-tour'` block — the slide currently says "Your 6 tabs"; update to "Your 7 tabs"
     and add a Picks item). Add matching verbatim copy to `knowledge/product-intro-copy.md`.
  2. Add `"picks"` to `VALID_TAB_IDS` in `tests/test_pwa_intro.py:25`.
  3. Add `"picks"` to `VALID_GUIDE_TABS` in `tests/test_guide_releases.py:26`.
  4. Add a `"picks"` chip to `GUIDE_TAB_CHIPS` in `docs/index.html` (near the `GUIDE_TAB_CHIPS`
     constant ~line 530) so Guide tab-filter works for Picks metrics.
  5. **Also fix the pre-existing `vsmarket` gap in the same commit:** `VALID_TAB_IDS` currently
     lists only 6 tabs and is missing `"vsmarket"` (the 7th real tab). Add it so the guard actually
     covers all tabs. `WELCOME` does not currently reference `vsmarket` in its tour items; that is
     intentional (vs-Mkt was added after the carousel was written and is not in the tour). Confirm
     the test allows a tab to exist without a WELCOME entry — if not, add a stub tour entry.
  6. Decide whether to bump `fvt_intro_seen_v1` to `v2` (CLAUDE.md rule: bump only when existing
     users should see the intro again — a new tab qualifies). If bumping, update `setIntroSeen()` and
     the `localStorage` key in `docs/index.html` and note the rationale in the commit message.

### 3a.2 — Base display filter (C6)

Render only rows where `cap_b(Market Cap) > MIN_MARKET_CAP_B` **AND**
(`SMA50 > 0` OR `SMA200 > 0` OR `sma20_price > sma50_price`). Document `MIN_MARKET_CAP_B = 5` as a
PWA constant. (Verified on 2026-06-25 **EOD** data: **141 rows / 134 unique tickers**. An earlier
10:30am intraday snapshot showed ~165 rows — ATR and Price shift through the trading day, changing
which rows pass. Tests must use a fixture derived from EOD data.)

### 3a.3 — Grouping, sort, layout

- Group **`list_category` → group (industry) → stocks** (D8). Category order: `leaders`, `emerging`,
  `accel`, `rs_new_high`. Within each industry, **sort least-extended first** (`atr_ext_50` asc;
  NaN last).
- Per-group header shows **breadth** = count of qualifying names (health signal, D8).
- Per-stock row (compact, mobile-first — match existing card density):
  - Ticker + Company (truncate)
  - **Extension** `atr_ext_50` formatted `4.3×` — **color-banded** by C4 (≤5 emerald, 5–8 amber,
    ≥8 red + a small "trim" tag). This is the visual headline.
  - `%>50MA` (raw `SMA50`), 52W-high distance (`52W High`), RSI (plain, no gate per C8)
  - Perf Week / Perf Month
  - EPS Q/Q (growth signal)
- A one-line legend at the top of the tab linking the extension bands to the Guide entry.

### 3a.4 — Release triplet

`releases.json` entry (tag `feature`, `tab: "picks"`) + bump `current` + bump `sw.js` CACHE. Per
house rule, all three in the same PR.

## Phase 3b — Extension & risk engine + Focus List

Builds on 3a's rendered rows. Adds the Ariel/Minervini decision layer.

> **Depends on 3a; do 3b before 3c.** 3c (Lookup section) reuses 3b's per-row renderer **with**
> the risk panel, so 3b lands first. Run the phases in order.

### 3b.0 — Refactor: extract `renderPickRow(r)` (do this first) — **B4**

Today `renderPicks()` (`docs/index.html:~3171–3219`) builds each stock row's HTML **inline inside
nested loops** — there is no callable "render one row" function. 3b adds the risk panel and 3c
renders the same rows inside the Lookup tab; without a shared helper that's ~30 lines of row HTML
copy-pasted into two places that will drift.

**Action:** extract a single **`renderPickRow(r, opts)`** helper that returns the row HTML
(ticker/company/extension band/`%>50`/RSI/perf + the 3b risk panel). `renderPicks()` calls it in
its loop; 3c's Lookup section calls the same function. One row layout, one place to change.
`opts` carries per-surface flags (e.g. `opts.expandable` for the risk panel). Add/extend the
Playwright test so both surfaces assert against the same rendered structure.

### 3b.1 — Per-row risk panel (expandable — **A1**)

The risk panel is an **expandable** secondary block per row (a subtle chevron toggles it open;
track open rows in a JS `Set` of tickers). Always-inline would roughly double every row's height on
mobile — rejected. Surface, when open:

- **High of day (next buy trigger):** the stored `High` (EOD scrape ⇒ today's high = next session's prev day high 
  breakout trigger). Label it **"HoD (next buy trigger)"**.
  > **Known gap (TODO PICKS-3D-STALE):** our cron runs EOD (after close), so intraday captures
  > show a partial-day `High`. No stale-data warning is shown in 3b MVP. Track in SPRINT as a
  > follow-up task (PICKS-3D-STALE): add a `run_at` timestamp column to `picks.csv` (stamped from
  > the workflow run time) and surface a banner in the PWA when the picks data is from an intraday
  > capture (run_at time < 16:00 ET on the data date).
- **Stop (20MA, default per C3):** show the **stop level** `sma20_price` and **Risk** =
  `risk_20ma_pct` as % **and** as $/share.
  - **Reconstruct the stop level** in JS from stored columns: `sma20_price = Price / (1 + SMA20/100)`
    (use the same parser pattern already in `renderPicks()`). `SMA20` is the Finviz "% of price above
    the 20MA" column.
  - **$/share risk is simpler — do NOT reconstruct for the dollar figure:** `$risk = Price ×
    risk_20ma_pct`. (`risk_20ma_pct` is stored as a fraction; e.g. ANET EOD 2026-06-25:
    `165.45 × 0.0115 = $1.90/share`, stop level `165.45/(1+1.16/100) ≈ $163.55`. Verified.)
  - Risk is measured from current `Price` (the stored value), **not** from `High`. `High` is only the
    breakout trigger.
- **Wider stop (50MA):** `sma50_price = Price/(1+SMA50/100)` + `risk_50ma_pct`, shown as the
  secondary alternative.
- **Extension:** `atr_ext_50` (same color band as 3a). Trim tag at `≥ ATR_EXT_TRIM`.
- **Tightness metrics (display-only; PWA-computed from stored `ATR`/`Price`/`High`/`Low` — no backend
  column, they are trivial functions attribution can recompute offline).** Label each so a trader
  reads it without a glossary:
  - **"Range/ATR" (`range_atr`, already a 3a backend column):** today's high–low range ÷ ATR.
    `< 1` = an inside-its-normal-swing, quiet day. Self-normalizes for the stock's own volatility and
    price level (a $500 and a $20 name are comparable), so it directly answers *"tight for THIS
    stock today?"*.
  - **"Volatility (ATR %)" (`atrp = ATR / Price`):** average daily move as a % of price. Lower = a
    structurally calmer name. Price-level-independent baseline volatility.
  - **"Stop distance (ATR)" (`nearest_stop$ / ATR`):** how many ATRs sit between price and the
    nearest logical MA stop below it (`nearest_stop$ = min` of the *positive* of `Price−sma20_price`,
    `Price−sma50_price`). Smaller = a tighter stop in volatility terms. Uses the same nearest-stop
    definition as the Focus tightness component (§3b.2) for consistency.

### 3b.2 — Focus List (C2, C7) — `All / Focus` toggle inside the Picks tab

A segmented control at the top of the Picks tab toggles between **All** (the 3a grouped list) and
**Focus** (a flat, ranked highlights list — A++ actionable setups).

**Focus membership (hard gates):**
- Passes the 3a base filter (C6), **and**
- `atr_ext_50` is a real positive value with `0 < atr_ext_50 ≤ ATR_EXT_ACTIONABLE (5)` — i.e. above
  the 50MA (extension is meaningful) and not over-extended. **`> 5` auto-DQs** (CEO explicit).
- No RSI gate (C8). No fundamental gate in 3b (that's 3d).
  > **Gate is `price > 50MA`, NOT full Stage-2 (`stage2 == 1`).** A Focus name only needs price above
  > its 50MA (positive extension); it does **not** need 50MA > 200MA. So a stock emerging from a base
  > (rising above its 50MA while the 50MA is still below the 200MA) is admitted. This looser gate is a
  > **judgment call, not a settled decision** — track **PICKS-3B-FOCUSGATE** (SPRINT): after live
  > data, decide whether to tighten Focus to require `stage2 == 1`.

**Focus rank — blended quality score (higher = better), all weights PWA constants, tunable.**
Compute each component, **normalize all of them cross-sectionally with the SAME min–max recipe**
across the day's Focus candidates, weight, then apply the extension as a **multiplicative discount**
(never a subtraction):

```
base   = w_group·group_strength + w_tight·stop_tightness + w_quiet·quiet_bar      # base ∈ [0, 1]
score  = base × (1 − extension_penalty_fraction)                                   # score ∈ [0, 1]
```

**Why one normalization recipe + a multiplicative discount (design decisions locked 2026-06-27):**
- **One ruler for all three components (min–max), not a mix.** The earlier draft normalized group
  strength with `(max−x)/(max−min)` (full 0→1 span) but tightness/quiet with `1−(x/max)` (compressed
  0→<1 span). Mixed rulers silently re-weight: a component on a compressed span contributes less than
  its stated weight. With one ruler, `w=0.4` genuinely means 0.4. `1−(x/max)` also breaks on the
  negative-`risk_20ma_pct` case (price below the 20MA → score `> 1`, wrongly topping the ranking).
- **Multiplicative discount keeps `score ∈ [0, 1]`.** The old `base − penalty` could go negative
  (`base` near 0, penalty up to 0.5 ⇒ −0.39). `base × (1 − penalty_fraction)` with `base ∈ [0,1]` and
  `(1−penalty) ∈ [0.5, 1]` is always non-negative, and the haircut scales with how good the setup
  otherwise is — "A++ but stretched, dock it up to 50%."

| Component | Dir | Source | Min–max normalization (across Focus candidates) |
|-----------|-----|--------|--------------------------------------------------|
| Group strength | **+** | `grp_sum_mid_rank` (lower sum-of-ranks = stronger group) | inverted: `(max − x) / (max − min)`. Same basis as the leaders bucket; consistent with selection. If you change this metric, write an ADR. Do **not** use `grp_momentum_score_pctile` — that is a percentile across ALL groups at selection time, not across today's Focus pool. |
| Stop tightness (nearest MA) | **+** | `min(positive of risk_20ma_pct, risk_50ma_pct)` | inverted: `(max − x) / (max − min)`. Smaller nearest-stop = tighter logical stop = better. **Either MA earns the points (the "OR"):** a logical stop must be an MA *below* price, so consider only positive risks; the nearer one is the stop. `risk_50ma_pct` is always positive for a Focus member (Focus requires `atr_ext_50 > 0 ⇔ price > 50MA`), so a valid stop always exists; `risk_20ma_pct` is dropped from the min when price is below the 20MA. This replaces the old "20MA tightness" component and fixes the negative-risk bug. |
| Quiet bar | **+ (mild)** | `range_atr` (3a backend col) | inverted: `(max − x) / (max − min)`. C1 tightness proxy. Already self-normalizes per stock (range ÷ its own ATR), so an expensive high-ATR name and a cheap low-ATR name are comparable — exactly "tight for THIS stock today". No change needed beyond switching to the min–max ruler. |

**Extension penalty (multiplicative, applied to `base`):**
```
extension_penalty_fraction = PENALTY_MAX × clamp( (atr_ext_50 − ATR_EXT_PENALTY_START)
                                                  / (ATR_EXT_ACTIONABLE − ATR_EXT_PENALTY_START), 0, 1 )
```
`0` below `ATR_EXT_PENALTY_START (3.5)`; ramps linearly to `PENALTY_MAX (0.5)` at
`ATR_EXT_ACTIONABLE (5.0)`. The denominator is derived from the two constants (`= 1.5`), never
hardcoded — retuning either constant keeps the ramp correct.

> **Optional 50MA double-support bonus → deferred to 3d (PICKS-3D-STACKEDSTOP).** The v1
> nearest-stop component already gives the "either MA" reward. A stock where BOTH MAs are tight AND
> close together (`|sma20_price − sma50_price| / price` small) has two stacked supports and deserves a
> small extra bump. Defer the bonus to 3d to keep v1 simple.

**Normalization edge cases (implement all three):**
- **All-equal component (`max == min`, denominator 0):** assign every candidate `0.5` for that
  component (neutral) — never divide by zero.
- **Small pool (`< FOCUS_MIN_POOL = 5`):** min–max is too jumpy; fall back to **rank-based
  normalization** (percentile rank 0–1 across the pool).
- **Single candidate (`n == 1`):** score `= 1.0` (sole candidate is by definition the best); show it,
  never an empty Focus.

> **Explicitly NOT a positive factor: proximity to the 50MA.** Being close to the 50MA does not make
> a setup good (CEO 2026-06-26). The 50MA appears only as the *extension penalty* (a discount beyond
> 3.5×) and as the wider-stop risk line — never as a reward for being near it.

Sort Focus descending by `score`. Render each row with the shared `renderPickRow()` (§3b.0) + risk
panel, plus a small score badge.

> **Show the score math while tuning (A2).** In the early weeks, inside the row's expandable, show
> the component breakdown so we can calibrate the weights, e.g.:
> ```
> Group   0.82 × 0.40 = 0.33
> Tight   1.00 × 0.40 = 0.40
> Quiet   0.50 × 0.20 = 0.10   → base 0.83
> Ext     4.1× → ×0.85         → score 0.71
> ```
> This is a tuning aid, removable later by flipping one flag.

> **Freshness-fill leaders are basis-blind in the Focus score (M3).** The group-strength component
> reads `grp_sum_mid_rank` and ignores `grp_rank_basis`, so SS leaders and freshness-fill leaders run
> through the identical formula. Consequence: freshness fills (selected by `momentum_confirmed`, often
> *because* their sum-of-ranks was too weak for the top-8) will tend to score lower on group strength
> and get **no credit for the freshness that selected them**. Acceptable for v1; revisit if freshness
> names systematically sink (note it alongside PICKS-3B-FOCUSGATE).

> **Deterministic Focus-order test → fast-follow (PICKS-3B-FOCUSTEST), NOT a 3b blocker.** Because the
> score is cross-sectionally normalized, you cannot pin one stock's score in isolation — but you *can*
> freeze a small fixture pool and assert the whole-pool ordering + scores within ±0.01. Tabled as a
> fast-follow per CEO (2026-06-27): the feature is heuristic/judgment anyway; do not block on it. The
> 3b acceptance test asserts the qualitative properties below (penalty observable, below-MA names
> excluded) rather than exact scores.

### 3b.3 — Release triplet (as 3a.4).

## Phase 3c — Lookup-tab Stage-2 section + deep-link button

> Reuses the **3b** `renderPickRow()` helper (rows + risk panel) — land 3b first.

**Hook into BOTH `renderLookup()` code paths (B3).** `renderLookup()` (`docs/index.html:~2896`) has
two branches that resolve a group, and the Stage-2 section must be added to **both** (missing one is
the easy bug):
1. **`if (groupResult)` branch (`~:2917`)** — a group looked up *by name*. The industry name is
   `groupResult.name` (only when `groupResult.groupKey === 'industries'`).
2. **Ticker branch (`else`, `~:3004`)** — a ticker resolved to a group. The industry name is
   `data.finviz_industry`; the sector is `data.finviz_sector`.

For the resolved **industry**, render a **"Stage-2 names"** section:
- If the industry is present in today's `picks_latest.csv` (already loaded in `state.picksData`),
  list its names with the shared `renderPickRow()` (rows + risk panel).
- Otherwise show the button alone ("not currently a leading group — screen it yourself →").

**Deep-link button — inline template + anti-drift test (B1/B2), NO runtime fetch:**
- **Button params live as PWA constants** in `index.html` (alongside `ATR_EXT_*`), mirroring the
  `button` block of `screener_config.json` (the tight `v=311` template: `cap_midover`,
  `ta_sma20_sa50`, `ta_sma50_pa`, `o=sma50`, `ft=4`). **Single source of truth stays
  `screener_config.json`** — add **`tests/test_picks_button_config.py`** asserting the inlined PWA
  constants equal the config's `button` block, so a future button change in the config reddens CI
  until `index.html` is updated. This matches the repo's existing anti-drift idiom (GUIDE ↔
  moaty-metrics, screener labels ↔ probe fixture). Runtime-fetching the 84-col `screener_config.json`
  just to build a URL is rejected; there is no server-side inject point (GitHub Pages branch-deploy).
- **Slug is computed inline, no CSV fetch (B2):** the JS equivalent of `slugify_industry` —
  `name.toLowerCase().replace(/[^a-z0-9]/g, '')` — builds `ind_<slug>`. The `finviz_industry_slugs.csv`
  `validated` column is a backend concern, irrelevant to URL construction; do not fetch it.
- **Industry button** available for **all 144** industries (selected or not): `ind_<slug>`.
- **Sector button (A3):** when a *sector* is the resolved group (sector-name lookup, or the ticker
  branch's `data.finviz_sector`), render the same button with **`sec_<slug>`** instead of `ind_<slug>`.
  All 11 sector names slugify cleanly to Finviz sector tokens (`Real Estate → sec_realestate`,
  `Communication Services → sec_communicationservices`, `Healthcare → sec_healthcare`, …); a unit test
  asserts the 11 mappings. (No Stage-2 *names* list for sectors — `picks_latest.csv` is industry-keyed
  — only the button.)
- Pure URL construction; no backend.
- Release triplet.

## Phase 3d — Polish & refinements (optional, post-MVP)

- **50MA double-support bonus (PICKS-3D-STACKEDSTOP):** add the "AND" reward to the Focus score — a
  small bump (or second multiplier) when BOTH MA stops are tight AND the 20MA and 50MA sit close
  together (`|sma20_price − sma50_price| / price` below a threshold), i.e. two stacked supports under
  price. The v1 nearest-stop component (§3b.2) already covers the "either MA" reward; this adds the
  "both, and close" case.
- **True inside-day / NR7** (upgrade from the C1 proxy): have `collect_picks.py` self-join the prior
  session from `picks.csv` to stamp `prev_high`/`prev_low`, enabling a real inside-day flag. Schema
  bump + migration; only worth it if the proxy proves too noisy.
- **Loose fundamental floor on Focus (C9):** e.g. `EPS Q/Q > 0 AND Sales Q/Q > 0`. **When it removes
  a name, surface it under an "Honorable mentions (failed fundamental floor)" sub-list** so we can
  judge whether the floor is mis-calibrated. The floor + the honorable-mention behavior are tunable
  PWA constants.
- Search/filter, sort toggles, target/R-multiple framing (distance to 52W high as rough upside),
  Guide glossary entries for any newly surfaced metric.

> **AI integration is explicitly OUT of Phase 3** — separate future task (CEO 2026-06-26).

## Configurable constants introduced in Phase 3 (triple-doc per house rules)

PWA constants (`docs/index.html`, near the `REGIME_THRESHOLD` block; also document in README
§Configurable parameters and CLAUDE.md §PWA display thresholds):

| Constant | Default | Controls |
|----------|---------|----------|
| `MIN_MARKET_CAP_B` | `5` | Picks-tab base display filter (C6); min market cap in $B. |
| `ATR_EXT_ACTIONABLE` | `5.0` | Extension band cutoff: ≤ is actionable (emerald); also the Focus hard-DQ line. |
| `ATR_EXT_TRIM` | `8.0` | ≥ flags a held position as a trim-10% candidate (red). |
| `ATR_EXT_PENALTY_START` | `3.5` | Focus-score extension penalty ramp start (0 below, ramps to PENALTY_MAX at ATR_EXT_ACTIONABLE). |
| `PENALTY_MAX` | `0.5` | Max extension-discount fraction at `ATR_EXT_ACTIONABLE (5×)`. Applied multiplicatively: `score = base × (1 − penalty_fraction)`, so 0.5 = up to a 50% haircut, `score` always ∈ [0,1]. Tune after first few weeks of live Focus data. |
| Focus weights | `w_group = 0.4`, `w_tight = 0.4`, `w_quiet = 0.2` | Blended Focus quality score weights (§3b.2): group strength, nearest-MA stop tightness, quiet bar. Starting allocation; all three are PWA constants, tunable with a one-line edit + cache bump. (Sensible starting split — two-way door; do not over-optimize.) |
| `FOCUS_MIN_POOL` | `5` | Minimum Focus candidates before falling back from min–max to rank-based normalization (§3b.2 edge cases). Not displayed to the user. |
| Button template (`BUTTON_*`) | mirrors `screener_config.json` `button` block | The `v=311` deep-link params inlined for the 3c button (B1). Single source of truth = `screener_config.json`; `tests/test_picks_button_config.py` asserts they match. |

> **`All / Focus` toggle is NOT persisted (A4):** the segment **resets to `All` on every Picks-tab
> entry / data reload.** Avoids stale-Focus confusion when the underlying pool reloads. No constant —
> just reset `state` on `switchTab('picks')`.

Backend columns (deterministic; document in README §Delta/Picks columns, CLAUDE.md §Picks pipeline,
and `knowledge/moaty-metrics.md`): `atr_ext_50`, `risk_20ma_pct`, `risk_50ma_pct`, `range_atr`,
`stage2`. The 3b tightness display metrics (`atrp = ATR/Price`, stop-distance-in-ATR) are
**PWA-computed display-only** — trivial functions of stored `ATR`/`Price`/`risk_*`, no backend column
(attribution can recompute them offline).

## Acceptance criteria (Phase 3, by subphase)

**3a** ✅ COMPLETE (2026-06-26)
- [x] Backend: `atr_ext_50, risk_20ma_pct, risk_50ma_pct, range_atr, stage2` present in
      `picks_latest.csv` and `picks.csv`; the one historical date is backfilled; golden-header
      superset test still passes.
- [x] `atr_ext_50` matches the worked examples within ±0.1×: **ANET ≈ 0.67×, STX ≈ 3.16×,
      DELL ≈ 3.64×, SNDK ≈ 4.55×** (2026-06-25 **EOD** data). Values at 10:30am intraday were
      ANET≈0.96×/STX≈3.2×/DELL≈3.5×/SNDK≈4.3× — the test fixture must use EOD data only.
- [x] `risk_20ma_pct` and `risk_50ma_pct` for ANET within ±0.3%: **risk_20ma_pct ≈ 1.15%,
      risk_50ma_pct ≈ 3.40%** (ANET EOD 2026-06-25: price=165.45, sma20≈163.55, sma50≈159.82;
      formula is `(price − smaX_price) / price`, NOT High-based). ANET is the canonical worked
      example — both risks <4% confirm it as actionable; SNDK's ~20% 20MA stop makes it a poor
      example. `risk_*` values are stored as fractions (0.0115, 0.0340); display as % in the PWA.
- [x] Picks tab renders, grouped category→industry→stock, base filter applied (≈141 rows on the
      2026-06-25 EOD fixture), least-extended-first within each industry, breadth count per group.
- [x] Extension color bands render per C4; `≥8×` shows the trim tag.
- [x] Empty/blocked-day CSV → placeholder, no crash.
- [x] Release triplet present; `tests/test_guide_releases.py` passes (`current === releases[0].version`).

**3b**
- [ ] `renderPickRow()` helper extracted (§3b.0); `renderPicks()` uses it; Playwright asserts the
      shared structure.
- [ ] Risk panel is **expandable**; shows prev-day high (buy trigger), 20MA stop level + risk $/%,
      50MA wider-stop alternative, extension, and the three tightness lines (Range/ATR, Volatility
      (ATR %), Stop distance (ATR)).
- [ ] `All / Focus` toggle works and **resets to All on tab entry/reload**; Focus excludes every
      `atr_ext_50 > 5` and every row at/below the 50MA (`atr_ext_50 ≤ 0`).
- [ ] Focus uses **one min–max ruler for all three components** and the **multiplicative** extension
      discount (`score = base × (1 − penalty)`); **all scores ∈ [0,1], never negative**.
- [ ] Stop-tightness component uses the **nearest positive MA stop** (`min(positive risk_20, risk_50)`),
      so a below-20MA Focus name is scored on its 50MA stop, not rewarded for a negative risk.
- [ ] Proximity-to-50MA contributes **no** positive weight; the 3.5×→5× extension discount is
      observable in ordering (qualitative assert; exact-score test is PICKS-3B-FOCUSTEST fast-follow).
- [ ] Normalization edge cases handled: all-equal → 0.5; pool `< 5` → rank-based; `n == 1` → 1.0.
- [ ] Release triplet present.

**3c**
- [ ] Stage-2 section added to **both** `renderLookup()` branches (group-by-name AND ticker→group).
- [ ] Lookup shows the Stage-2 names list (via `renderPickRow()`) for a selected industry, and the
      `v=311` deep-link button for any of the 144 industries; **sector** lookups get a `sec_<slug>`
      button. Button URL is well-formed (correct `ind_`/`sec_` slug, tight filters).
- [ ] `tests/test_picks_button_config.py` asserts inlined button constants == `screener_config.json`
      `button` block; sector-slug unit test covers all 11 sectors.
- [ ] Release triplet present.

## Validation & testing steps

- **Backend metrics (pytest, `tests/test_picks_metrics.py`):** parsers (`%`, `B/M/K/T`, empty→NaN);
  each derivation on the worked examples; NaN-safety when ATR/SMA blank; `stage2` truth table;
  migration test (old `picks.csv` row gains the new columns, backfilled, header is a superset).
- **PWA (Playwright fixture-intercept, per CLAUDE.md pattern).** The Picks PWA test file does
  **NOT exist yet** — 3b/3c must create `tests/test_pwa_picks.py` from scratch (http.server +
  route-intercept setup per the CLAUDE.md recipe; run `pip install playwright &&
  python3 -m playwright install chromium --with-deps` in-session). Route
  `**/raw.githubusercontent.com/**picks_latest.csv` to the existing committed fixture
  `tests/fixtures/picks_latest.csv` (EOD 2026-06-25 data); extend it to contain at minimum:
  - ANET, STX, DELL, SNDK (the four worked-example tickers; real EOD values)
  - One row with `ATR` blank (NaN-safety: NaN derived cols, no crash)
  - One row with `atr_ext_50 > 8` (trim candidate — verify the red trim tag renders)
  - One row with `atr_ext_50 > 5` (Focus DQ — excluded from Focus view)
  - One row with price **at/below the 50MA** (`SMA50 ≤ 0` ⇒ `atr_ext_50 ≤ 0`; Focus DQ — verify exclusion)
  - One row **above 50MA but below the 20MA** (`SMA20 < 0`, `SMA50 > 0`): a Focus member whose
    nearest stop must fall back to the 50MA — verify the stop-tightness component uses the 50MA and the
    score stays in [0,1] (the negative-`risk_20` regression).
  - At least one row with `Market Cap < 5B` (base-filter exclusion check)
  - Rows across at least 2 `list_category` values (`leaders`, `emerging`) to exercise grouping
  Assert: tab appears; base-filter row count matches fixture-visible rows; grouping + least-extended
  order; extension band colors; trim tag at ≥8×; risk panel expands and shows the stop level + $/%
  risk + tightness lines; `All/Focus` toggle filters out >5× and at/below-50MA names and resets to All
  on tab re-entry; **every Focus score is in [0,1]** and the extension discount is observable in
  ordering; Lookup Stage-2 section appears in both branches; deep-link URL format (`ind_`/`sec_`);
  empty-CSV placeholder (separate headers-only fixture).
- **Run before every commit:** `python3 -m pytest tests/ -q`.
- **Manual smoke (cloud OK — no Finviz needed):** serve `docs/` on `http.server`, intercept the CSV,
  eyeball the three subphase surfaces (the CLAUDE.md "PWA functional testing" recipe).

## Implementer hand-off obligations (CEO 2026-06-26 — do ALL of these)

1. **Write a "Notes to VP" hand-off** (append to `.session/session-notes.md`, and a milestone in
   `.session/WORK_LOG.md`) covering: **what to test**, **how to use the new surfaces** (what the
   Picks tab / Focus toggle / Lookup deep-link do and how a trader reads them), and any caveats
   (e.g. the trigger is next-session-only; the C1 tightness is a proxy until 3d).
2. **For every user-facing change, give VP-level context** in the PR description and session notes:
   the **user experience** (what the trader now sees/does) and the **implications** (what it changes
   about how they act, what it does *not* yet do).
3. **Update all non-code docs alongside the code** (do not defer): README §Configurable parameters
   (new constants + backend columns), CLAUDE.md (§Picks pipeline data layout + new columns + §PWA
   display thresholds), `knowledge/moaty-metrics.md` (one-liner for `atr_ext_50`, `range_atr`,
   `stage2`, risk metrics), the in-app **Guide** glossary (`GUIDE` constant — verbatim-synced to
   moaty-metrics per the anti-drift test), `docs/releases.json` + `docs/sw.js`, `.session/SPRINT.md`,
   and this plan's Phase-3 status. If any of these don't yet have a home for the new content,
   **create it.**
4. **ADR if a non-obvious design call is made** during build (e.g. the canonical `grp_` metric for
   Focus group-strength) → `knowledge/decisions/`.

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
2. **COMPLETED Phase 2 — scraper + collection** (core, irreplaceable). **LIVE 2026-06-25** — first
   dispatch green: 273 picks / 262 tickers / 19 groups (all 4 buckets). 19/19 slugs validated.
   Dedup confirmed. Code: `collect_picks.py`, `picks_config.py`, `collect_picks.yml` + shared
   concurrency on both workflows, `selector_versions.json` v1, 30 unit tests, triple-doc'd
   constants. Fast-follows open: PICKS-2-ADR8, PICKS-2-HDR, PICKS-2-CRON (see SPRINT). Checklist:
   - `select_groups(deltas_df)` → leaders (8 sum-of-ranks + 2 momentum_confirmed fills), emerging,
     accel, rs_new_high with top-40% floors; dedup to ≤ 20 unique groups; emit `grp_*` snapshot
     (19 columns, see §grp_* spec) including `grp_category_rank` (within-bucket rank among all
     qualifying candidates, independently computed per category for dedup groups) + `selector_version`.
     (No Finviz access; fully unit-testable against `deltas.csv`.)
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
- [ ] **PICKS-2-HDR — validate scraped header against `finviz_cols` at scrape time** (fast-follow,
      non-blocking). `build_pick_rows` maps each scraped cell by the config's 84 `label`s
      (`stock.get(col, "")`). If Finviz renames/reorders a header so it stops matching
      `screener_config.json`, the affected columns write **blank silently** — no error, lost data
      on the irreplaceable capture. The live header IS captured (`paginate_group` returns it) but
      unused for validation. Fix: in `main()`, WARN (and list mismatched labels) when a group's
      scraped header isn't a superset of `finviz_cols(config)`; consider exit 1 below a coverage
      threshold so CI reddens and the debug-HTML artifact uploads. The golden-header test pins the
      *config*, not the *live* response.
- [ ] **PICKS-2-CRON — promote `collect_picks.yml` to the Cloudflare-cron dispatcher** (fast-follow,
      non-blocking). Currently a **single** GitHub `schedule:` cron (`8 20 * * 1-5`). GitHub cron
      drifts/drops under load (§Automation in CLAUDE.md — the reason the Cloudflare dispatcher
      exists), and the shared `concurrency` group prevents overlap but does **not** order the two
      workflows: if deltas aren't pushed before picks runs, the stale-read guard aborts safely but
      yields **no picks capture that day** (unrecoverable). Fix: add a Cloudflare cron that POSTs a
      `workflow_dispatch` to `collect_picks.yml` ~20–30 min after the EOD `collect.yml` dispatch;
      keep the GitHub `schedule:` as a backstop. Tune the margin after live timing data.
- [ ] **PICKS-3B-FOCUSGATE — revisit the Focus gate (`price>50MA` vs full `stage2`)** (post-live,
      non-blocking). 3b admits any Focus name above its 50MA; it does NOT require 50MA>200MA. After a
      few weeks of live Focus data, decide whether sub-Stage-2 names pollute the list and the gate
      should tighten to `stage2 == 1`. Tracked per CEO 2026-06-27. Also revisit whether freshness-fill
      leaders should get credit for `momentum_confirmed` in the Focus group-strength component (M3).
- [ ] **PICKS-3B-FOCUSTEST — deterministic Focus-order regression test** (fast-follow, non-blocking).
      Freeze a small fixture pool and assert whole-pool ordering + scores within ±0.01 (a single
      stock's score can't be pinned in isolation because the score is cross-sectionally normalized).
      Tabled per CEO 2026-06-27 — the 3b acceptance test asserts qualitative properties (scores in
      [0,1], discount observable, below-MA names excluded) instead.
- [ ] **PICKS-3D-STACKEDSTOP — 50MA double-support bonus on the Focus score** (3d polish). Add the
      "both MAs tight AND close together" reward on top of the v1 nearest-stop component. See §3d.

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
    `grp_category_rank`, `grp_sum_mid_rank`, and floor `grp_momentum_score_pctile` for that day.
    A dedup row (group selected as both `leaders` and `accel`) independently carries the correct
    within-bucket `grp_category_rank` for each category row.
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
  knowledge/decisions/ADR-007-picks-selector-policy.md — ✅ WRITTEN (2026-06-25). Covers:
    leaders sum-of-ranks decision; why not PWA intersection gate; why not rs_confirmed alone;
    anti-flash floor rationale; selector_version registry scheme + constants-not-code caveat;
    alternatives considered. **Implementer reads this; does not need to write it.**
  knowledge/decisions/ADR-008-picks-collection-architecture.md — ✅ WRITTEN (2026-06-25). Covers:
    separate workflow + shared concurrency (D7); store-wide vs tight-filters (D5/D11) + 50-page
    cap; ta_highlow52w_a20h semantics; membership-only log (D9); picks_latest.csv split; grp_*
    column spec + one-way/two-way door analysis. **Implementer reads this; does not need to write it.**
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

