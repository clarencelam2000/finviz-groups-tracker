# Picks selector yield, group-cap headroom, and per-group sort — investigation

**Date**: 2026-08-23
**Author**: Claude (acting as SDE2), on request from the repo owner
**Status**: Investigation only — no code changed. For team/staff-eng prioritization discussion.
**Scope**: `scripts/collect_picks.py` (`select_groups`), `scripts/picks_config.py`,
`scripts/collect_morning.py`, `data/picks/screener_config.json`, `data/picks/picks.csv`

**Purpose of this document**: the owner asked why the Picks selector isn't filling all 22
bucket-slots into 20 unique groups, whether the 20-group cap and 40-ticker-per-group cap are
worth raising, and what other selector/display knobs exist. This doc separates verified facts
(§ Findings) from analysis/opinion (§ Opinions) per the owner's explicit request, so the facts
stand on their own for a team member picking this up cold, independent of whether they agree
with the recommendations.

**How to reproduce**: every number below was computed by reading `scripts/collect_picks.py`,
`scripts/picks_config.py`, `data/industries/deltas.csv`, and `data/picks/picks.csv` directly —
no external calls, no scraping. The exact queries are inlined in each section so a future
session (or a human with `pandas`) can re-run them against a later date. All numbers reference
the trading date **2026-08-21** (the latest date in `picks_latest.csv` at investigation time)
unless a date range is stated.

---

## 1. Findings (verified facts)

### 1.1 Why the selector yielded 18 unique groups, not 22, on 2026-08-21

`select_groups()` (`scripts/collect_picks.py:141`) is pure and runs entirely before any
scraping — it reads only `data/industries/deltas.csv`. Its cap logic
(`add_bucket_with_backfill`, line 201) is separate from and unrelated to `GLOBAL_FETCH_CAP`
(the scrape-page budget, applied after selection, `scripts/collect_picks.py:306`). **The 18-vs-22
gap is not caused by the global fetch cap.**

Stepping through the actual 2026-08-21 selection bucket by bucket:

| Bucket | Slots | Natural top-N | New (non-dup) added | Backfill outcome |
|---|---|---|---|---|
| leaders | 10 (8 SS + 2 freshness) | — | 10 | Always exactly 10 new — the freshness-fill pool (`~latest["name"].isin(core_names)`, line 232) structurally excludes the core 8, so this bucket cannot self-collide. |
| emerging | 4 | 10 qualifying candidates total | 4 | Natural top-4 by `regime_short_long` had zero overlap with leaders' 10 groups — full yield with no backfill needed. |
| accel | 3 | 19 qualifying candidates total | 3 | Natural top-3 was `[Coking Coal(dup), Oil & Gas E&P(new), Beverages - Non-Alcoholic(new)]` — 2 new. Backfill walked past rank 3, skipped one dup (`Drug Manufacturers - General`), found `Thermal Coal` (new) → reached 3/3. |
| rs_new_high | 3 | **only 7 qualifying candidates total** | **1** | Natural top-3 (`Coking Coal`, `Gold`, `Health Information Services`) were **all 3 already selected** by higher-priority buckets. Backfill continued through the remaining 4 candidates; 3 more were dups (`Other Precious Metals & Mining` via emerging, `Software - Application` via leaders, `Copper` via leaders), leaving exactly 1 new group (`Other Industrial Metals & Mining`). The candidate pool (7) was exhausted, not the group cap. |

Running total: 10 + 4 + 3 + 1 = **18 unique groups**, matching the observed `picks_latest.csv`
data for that date.

**Root cause**: `rs_new_high`'s qualifying pool is both small (7 candidates against a market of
143 tracked industries) and structurally correlated with the leaders/emerging buckets — a group
strong enough to hit a 20-session RS new high is usually already a leader or emerging name by
construction. This is what a bucket-level fill shortfall looks like when its own candidate pool
runs out, as distinct from a cap or fetch-budget shortfall.

### 1.2 Unique group count, past 10 trading sessions (≈2 weeks)

Computed directly from `data/picks/picks.csv` (`df.groupby('date')['group'].nunique()`):

| Date | Unique groups |
|---|---|
| 2026-08-10 | 17 |
| 2026-08-11 | 20 |
| 2026-08-12 | 18 |
| 2026-08-13 | 16 |
| 2026-08-14 | 20 |
| 2026-08-17 | 19 |
| 2026-08-18 | 16 |
| 2026-08-19 | 17 |
| 2026-08-20 | 17 |
| 2026-08-21 | 18 |

Range 16–20, median 17.5. The cap (20) was hit on only 2 of 10 sessions.

### 1.3 Day-over-day group overlap, same 10 sessions

Computed as `|today's groups ∩ yesterday's groups| / |today's groups|`:

| Date | Overlap w/ prior session |
|---|---|
| 2026-08-11 | 15/20 (75%) |
| 2026-08-12 | 14/18 (78%) |
| 2026-08-13 | 11/16 (69%) |
| 2026-08-14 | 14/20 (70%) |
| 2026-08-17 | 16/19 (84%) |
| 2026-08-18 | 11/16 (69%) |
| 2026-08-19 | 11/17 (65%) |
| 2026-08-20 | 16/17 (94%) |
| 2026-08-21 | 16/18 (89%) |

Overlap is consistently 65–94%. This traces to the `leaders` bucket's ranking metric
(`rank_month + rank_quarter + rank_half`, ascending) — a mid-timeframe composite that moves
slowly session to session by construction, and 10 of the daily 16–20 groups come from that
bucket.

### 1.4 Near-miss candidates if `rs_new_high`, `emerging`, or `accel` thresholds are loosened (2026-08-21 snapshot)

Gate constants: `RS_NH_RS_FLOOR=0.6`, `EMERGING_REGIME_FLOOR=0.15`, `EMERGING_RS_FLOOR=0.5`,
`ACCEL_THRESHOLD=0.08`, `ACCEL_RS_FLOOR=0.5`, `ANTIFLASH_PCTILE=0.40` (i.e. momentum
percentile ≥ 0.60) — all from `scripts/picks_config.py`.

**rs_new_high** — groups with `rs_new_high==1` (the binary IBD-style flag) that failed only the
`rs_score`/pctile gates:

| Group | rs_score (need ≥0.6) | momentum pctile (need ≥0.60) | Already selected elsewhere? |
|---|---|---|---|
| Medical Instruments & Supplies | 0.500 (gap 0.100) | 0.336 (gap 0.264) | no |
| Real Estate Services | 0.500 (gap 0.100) | 0.490 (gap 0.110) | no |
| Auto Manufacturers | 0.333 (gap 0.267) | 0.343 (gap 0.257) | no |
| Mortgage Finance | 0.167 (gap 0.433) | 0.042 (gap 0.558) | no |

Note: `rs_score` is `count(6 timeframes with positive RS spread) / 6`, so it only takes the
discrete values 0, 0.167, 0.333, 0.5, 0.667, 0.833, 1.0. There is no candidate between 0.5 and
0.6 — loosening `RS_NH_RS_FLOOR` from 0.6 to anywhere in (0.5, 0.667] has the identical effect
as setting it to 0.5.

**emerging** (`regime_short_long > 0.15 AND rs_score > 0.5`) — split by which gate is failing:

*Passes regime, fails only rs_score* (all currently sit at `rs_score = 0.500`, one timeframe
below the 0.667 needed): Confectioners, Chemicals, Beverages - Wineries & Distilleries, Real
Estate Services, Residential Construction, Uranium, Consulting Services,
Drug Manufacturers - Specialty & Generic, Financial Data & Stock Exchanges, Home Improvement
Retail. None are dedups.

*Passes rs_score, fails only regime* (closest to the 0.15 floor):

| Group | regime_short_long | gap | Already selected elsewhere? |
|---|---|---|---|
| Packaging & Containers | 0.147 | 0.003 | no |
| Coking Coal | 0.100 | 0.050 | yes (leaders) |
| Oil & Gas E&P | 0.097 | 0.053 | yes (accel) |
| Department Stores | 0.076 | 0.074 | no |
| Copper | 0.069 | 0.081 | yes (leaders) |

**accel** (`momentum_accel > 0.08 AND pctile ≥ 0.60 AND rs_score > 0.5`):

*Fails only `momentum_accel`* (closest to 0.08): Copper (gap 0.020, dedup via leaders), Software
- Application (gap 0.034, dedup via leaders), Shell Companies (gap 0.036, no dedup), Packaging &
Containers (gap 0.045, no dedup), Silver (gap 0.046, dedup via emerging).

*Fails only `rs_score`* (stuck at 0.500, same one-notch pattern as emerging): Agricultural
Inputs, Confectioners, Credit Services, Financial Data & Stock Exchanges, Lodging, Medical Care
Facilities, Real Estate - Development, REIT - Office, Uranium. None are dedups.

*Fails only pctile*: none — on this date, every group clearing accel+rs_score also cleared the
momentum-percentile floor.

### 1.5 Global fetch page usage, past 10 trading sessions

Computed as `sum over groups of ceil(rows_scraped_for_group / PAGE_SIZE)` from `picks.csv`
(`PAGE_SIZE = 20`), which reconstructs actual pages consumed since `picks.csv` reflects exactly
what was scraped:

| Date | Unique groups | Pages used | Headroom (of `GLOBAL_FETCH_CAP=50`) |
|---|---|---|---|
| 2026-08-10 | 17 | 20 | 30 |
| 2026-08-11 | 20 | 25 | 25 |
| 2026-08-12 | 18 | 21 | 29 |
| 2026-08-13 | 16 | 22 | 28 |
| 2026-08-14 | 20 | 26 | 24 |
| 2026-08-17 | 19 | 26 | 24 |
| 2026-08-18 | 16 | 19 | 31 |
| 2026-08-19 | 17 | 23 | 27 |
| 2026-08-20 | 17 | 22 | 28 |
| 2026-08-21 | 18 | 24 | 26 |

Maximum observed usage in this window: 26/50 pages (52%).

### 1.6 40-tickers-per-group sort order

`data/picks/screener_config.json`'s `wide` block sets `"sort": "-marketcap"`, and
`scripts/probe_picks.py::_build_url` (line 137) writes it verbatim into the Finviz URL as
`&o=-marketcap`. This means the ≤40 names kept per group under `PAGE_CAP=2` are the
**largest-market-cap names in that industry**, not sorted by 50-day-MA extension or any other
technical metric. `atr_ext_50` / `risk_50ma_pct` (the 50MA-extension metrics) are computed
*after* scraping, in `scripts/picks_metrics.py` — they play no role in which names Finviz
returns or which get cut off by the page cap.

### 1.7 Configurable/selector variables — Picks pipeline

All from `scripts/picks_config.py` (triple-documented there per repo convention: in-code
comment + README § Configurable parameters + `scripts/CLAUDE.md`):

| Constant | Value | Role |
|---|---|---|
| `DAILY_GROUP_CAP` | 20 | Max unique groups scraped/day |
| `LEADER_SS_SLOTS` / `LEADER_MC_SLOTS` | 8 / 2 | Leaders bucket split: sustained-strength core vs momentum-confirmed freshness fill |
| `EMERGING_SLOTS` / `ACCEL_SLOTS` / `RS_NH_SLOTS` | 4 / 3 / 3 | Per-bucket slot counts |
| `ANTIFLASH_PCTILE` | 0.40 | Cross-sectional momentum-score floor for accel/rs_new_high (top 40th percentile) |
| `EMERGING_REGIME_FLOOR` | 0.15 | Emerging bucket's `regime_short_long` gate |
| `ACCEL_THRESHOLD` | 0.08 | Accel bucket's `momentum_accel` gate |
| `EMERGING_RS_FLOOR` / `ACCEL_RS_FLOOR` / `RS_NH_RS_FLOOR` | 0.5 / 0.5 / 0.6 | Per-bucket `rs_score` (RS-vs-SPY breadth) floors |
| `PAGE_SIZE` / `PAGE_CAP` | 20 / 2 | Per-group scrape pagination (40 names/group ceiling) |
| `GLOBAL_FETCH_CAP` | 50 | Daily page budget across all selected groups |
| `PAGE_DELAY_S` | 3s (env-overridable via `PICKS_PAGE_DELAY`) | Inter-fetch delay |

Two adjacent config layers exist outside the selector itself: `data/picks/display_methodology.json`
(PWA-side All/Focus scoring/display constants, its own versioned registry with an anti-drift
test) and `data/picks/ariel_match_config.json` (Ariel-match filter constants — documentation
only, explicitly **no** anti-drift test per the file's own design).

**Any change to a selection-affecting constant requires a `SELECTOR_VERSION` bump plus a new
entry in `data/picks/selector_versions.json`** — this is enforced by existing tests (ADR-007).

### 1.8 Configurable variables — Morning tab

From `scripts/collect_morning.py` and `scripts/session_config.py`:

| Constant | Value | Role |
|---|---|---|
| `MORNING_BATCH_SIZE` | 50 | Ticker-quote scrape batch size (deliberately not a multiple of `PAGE_SIZE=20`, to avoid a wasted empty-probe page) |
| `MORNING_FOCUS_TOP_N` | 100 | Hard cap on tickers scraped in the morning run, best-first by `focus_score` |
| `MORNING_FOCUS_SCORE_FLOOR` | 0.3 | Drops low-conviction setups even under the cap |
| `MAX_STALE_SESSIONS` | 5 | How many trading sessions old `picks_latest.csv` may be before the morning run refuses to tag against it |
| `SESSIONS[...].capture_et` | 10:05 (morning), 15:30 (pre_close), 17:00 (eod) | Canonical per-session capture times (`session_config.py`) |
| `WATCHLIST_TICK_SESSIONS` | `{morning}` | Which sessions decrement the personal watchlist's daily TTL |

`scripts/pick_status.py` carries no numeric thresholds — trigger/stop levels come from
`picks_latest.csv` row data, not from constants in that module. Its only configurable surface
is `STATUS_PRECEDENCE` (evaluation order) and `ACTIONABLE_STATUSES` (which states get
ATR-from-LoD + "I took it" treatment in the PWA).

### 1.9 What the PWA currently surfaces about bucket membership, and what it doesn't

Confirmed by reading `docs/index.html`:

- Each pick row's `list_category` **is** surfaced — every pick's group chip shows
  `CATEGORY_LABEL[r.list_category]` (~line 4587), and the per-ticker detail view aggregates
  "every distinct `list_category` this ticker qualified under **today**" (~line 5266–5281,
  reading `list_category` straight from the row so it can't drift from the real selector).
- There is **no** cross-day concept anywhere in the codebase today: no "this group is new to
  leaders as of today," no "this group dropped out since yesterday," no streak/consecutive-days
  counter. Nothing in `picks.csv`'s schema, `picks_latest.csv`, or the PWA computes or stores
  this.
- `data/picks/eval/group_scores.csv` (written by `scripts/evaluate_picks.py`) is **never fetched
  by the PWA** — confirmed by grepping `docs/index.html` for `group_scores`, zero matches. It is
  a backend-only research artifact, read only via `evaluate_picks.py --report` or direct file
  access.

---

## 2. Opinions and recommendations (Claude, acting as SDE2 — not verified fact, for team discussion)

These are judgment calls, not measurements. Flagged explicitly so they can be weighed,
disputed, or discarded independently of § 1.

1. **The `rs_score` quantization (§1.4) is the more surgical lever than raising `DAILY_GROUP_CAP`.**
   A large fraction of the "near miss" groups in both `emerging` and `accel` are parked at
   exactly `rs_score = 0.500`, one flipped timeframe away from the 0.667 needed. Changing
   `EMERGING_RS_FLOOR`/`ACCEL_RS_FLOOR` from `> 0.5` to `>= 0.5` would admit this specific,
   already-identified cluster without touching the group cap or opening the door to a much more
   speculative set of names (which is what would happen if the floor dropped further, to ~0.33).
   I'd want the team to sanity-check this against `evaluate_picks.py`'s forward-return data
   before committing — I have not done that cross-check here.

2. **The fetch-budget headroom (§1.5, max 52% of `GLOBAL_FETCH_CAP` used in 2 weeks) means
   raising `DAILY_GROUP_CAP` is not currently constrained by the global page budget.** The
   binding constraint before hitting 50 pages would be `PAGE_CAP=2`/group for any newly-admitted
   large industry. This is a fact about current headroom; it is my opinion that this makes
   `DAILY_GROUP_CAP` a safer knob to raise than it might otherwise seem, not a recommendation to
   raise it — that's a separate question about signal quality, which this investigation didn't
   evaluate.

3. **The day-over-day overlap (§1.3) is a legitimate feature opportunity, not just noise.** Two
   distinct signals seem missing from the current pipeline:
   - **Streak length**: how many consecutive sessions a group has held its bucket membership.
     Currently the leaders bucket's slow-moving ranking metric produces exactly this kind of
     persistence, but nothing counts or surfaces it.
   - **Entry/exit events**: a group newly entering a bucket, or dropping out of one it had
     held, are each arguably a rotation signal in their own right — currently neither is
     recorded anywhere.

4. **On where the streak/entry/exit feature should live — I was wrong earlier in this
   conversation to suggest `evaluate_picks.py`, and want that corrected in writing.**
   `evaluate_picks.py` writes only to `data/picks/eval/group_scores.csv`, which §1.9 confirms
   the PWA never reads. Placing a feature the owner explicitly wants to see there would make it
   invisible in the app. My opinion on the better shape: a small script following this repo's
   existing `compute_deltas.py`/`delta_config.py` pattern that diffs consecutive trading dates'
   unique-group sets from `picks.csv` and writes streak/entry state into something the PWA
   already fetches — most naturally new `grp_*`-style columns on `picks_latest.csv` for streak
   count and a "new today" flag. A "dropped out" event has no natural row to attach to in
   today's `picks_latest.csv` (the group isn't present in today's data), so that specific piece
   likely needs its own small store, similar in shape to `display_methodology.json`. I have not
   scoped effort or written a design for this — that's follow-up work if the team wants it.

5. **§1.6 (market-cap sort) is presented here as fact only** — I do not have an opinion recorded
   in this doc on whether market-cap sort is the right choice for the 40-name cutoff, since the
   owner asked to defer that discussion.

---

## 3. Explicitly out of scope / not done

- No code changes were made — this is read-only investigation.
- No cross-check of the `rs_score >= 0.5` change (opinion #1 above) against
  `evaluate_picks.py`'s forward-return data.
- No sizing/effort estimate for the streak/entry/exit feature (opinion #3/#4).
- No investigation into whether the traders' missed picks the owner mentioned were a
  market-cap-sort exclusion vs. a threshold/bucket-membership miss — owner asked to hold off on
  this (see conversation).
