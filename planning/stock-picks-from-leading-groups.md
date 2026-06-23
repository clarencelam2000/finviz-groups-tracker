# Plan: Top-stock picks from leading groups (Stage-2 screener pipeline)

> Status: **FRAMEWORK / pre-implementation.** Decisions below are VP-confirmed (interview
> 2026-06-23). Two hard dependencies remain before coding the scraper: (1) the canonical
> wide-net Finviz screener URL(s) from the VP, (2) one-time validation of the 144-row
> industry→`ind_` slug map against Finviz's live filter dropdown.

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
%-from-50SMA, rel-vol that day) are gone if we don't log them. Plain forward price paths ARE
backfillable later (FMP historical closes, already wired). So the irreplaceable work is
**starting the daily capture**, not the analysis — the analysis is a later session.

## Decisions (VP-confirmed 2026-06-23)

| # | Decision | Choice |
|---|----------|--------|
| D1 | First slice | Build the **EOD scrape pipeline first** (irreplaceable data) + ship the deep-link button in the same effort. No phase-0 gate. |
| D2 | Group coverage | **Selected leading groups only**, not all 144. Categories below. Button still available for ALL 144. |
| D3 | List categories | **Leaders + emerging (core)**, **Accelerating momentum**, **RS-new-high confirmed** — with a baseline-strength floor on the latter two (see §Selectors). |
| D4 | Stock screen | **Wide net, filter in-house.** VP supplies canonical Finviz URL(s). Don't bake tight filters into the URL; store wide, tune filters in our pipeline. |
| D5 | Stored columns | **Full `v=151` custom view (~70 columns)** — maximally future-proofs attribution. |
| D6 | List size | **Store ALL qualifiers per group** (breadth = count of qualifiers is its own signal). Requires Finviz pagination (`&r=` offset; ~20 rows/page). |
| D7 | Scrape job | **Separate GitHub Actions workflow** (`collect_picks.yml`), own EOD trigger, after `collect.py` has the day's group rankings. Isolates failure domains. |
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
        build screener URL (wide-net template + ind_<slug>)
        scrape ALL pages (Playwright, paginate &r=) → ~70-col rows
   3. append to data/picks/picks.csv  (one row per stock × list_category × day)

slug map: data/picks/finviz_industry_slugs.csv  (144 rows, validated vs live dropdown)

PWA:
   - Picks tab: read picks.csv (latest date) grouped by list_category → group → stocks
   - Lookup tab: when an industry is shown, render its Stage-2 names + Finviz deep-link

(LATER, offline) eval_picks.py: membership log → positions view → forward returns vs SPY+group
```

### Data layout

```
data/picks/
  picks.csv                    # append-only; date, list_category, group, ticker, <~70 finviz cols>
  finviz_industry_slugs.csv    # industry_name, ind_slug, validated (bool), note
```

`picks.csv` uniqueness key: `(date, list_category, ticker)`. A stock can appear under
multiple categories on the same day (e.g. both `leaders` and `accel`) — that's intentional;
keep both rows so per-category attribution is clean. Dedup/last-write-wins per that key,
mirroring `collect.py`.

## Group selectors (D3) — with the anti-flash floor

Read the latest `data/industries/deltas.csv`. For each category, select groups and tag the
rows written to `picks.csv` with `list_category`:

| Category | Primary signal | **Baseline-strength floor (anti-flash)** |
|----------|----------------|------------------------------------------|
| `leaders` | high sustained strength (all-green / multi-tf rank + `rs_confirmed`) | n/a — already an absolute-strength definition |
| `emerging` | `regime_short_long` > `REGIME_THRESHOLD` | `rs_score` > 0.5 (must already be net-positive vs SPY) |
| `accel` | `momentum_accel` > `ACCEL_STRONG` | rank in **top half** of peers AND `rs_score` > 0.5 — reject bottom-of-pack dead-cat flashes |
| `rs_new_high` | `rs_new_high` = 1 | `rs_score` high AND rank top-half — IBD "true leadership", not a low-base RS pop |

> The floor on `accel`/`rs_new_high` is the VP's explicit concern: a group can post a
> momentum-accel spike or 20-day RS-new-high while still near the bottom of the pack. Gate
> both on absolute standing before they qualify. Exact thresholds to tune; start conservative.

Expected selected universe: ~20–30 groups/day (mostly leaders). Cap total selected groups
(e.g. 30) to bound scrape volume / ToS exposure.

## Finviz scraping notes (carry-over from collect.py + new)

- **Same Cloudflare block as collect.py** — must run on **Azure (GitHub Actions)**, not cloud
  Claude (Google Cloud IPs get `cf-mitigated: challenge`). Playwright headless Chromium.
- **Pagination (NEW):** `v=151` returns ~20 rows/page. Walk `&r=1`, `&r=21`, `&r=41`… until a
  page returns fewer than the page size (or repeats). A wide net on a big industry = 50+ names.
- **Politeness:** delay between page loads and between groups (the separate workflow per D7
  isolates this from the core EOD snapshot). ~20–30 groups × pages = real volume — keep it
  human-paced and consider a daily cap.
- **Slug derivation:** `ind_<slug>` where `slug` = `name.lower()` with all non-alphanumerics
  stripped. Verified: `Aerospace & Defense → aerospacedefense`, `Software - Application →
  softwareapplication`. **Must validate all 144** against Finviz's live filter dropdown once
  (some names may abbreviate) — emit `finviz_industry_slugs.csv` with a `validated` flag and
  fail loudly on any unmapped/404 slug. **Build the 144 from `data/industries/snapshots.csv`,
  NOT `taxonomy_map.csv`** (the latter is the incomplete FMP→Finviz map — missing ~17
  industries: Airlines, Gambling, Internet Retail, Semiconductor Equipment & Materials,
  "Furnishings, Fixtures & Appliances", Coking Coal, etc.).
- **URL template (PENDING VP):** wide-net version of e.g.
  `https://finviz.com/screener?v=151&f=cap_midover,ind_<slug>,...&ft=4&o=sma50&c=<col list>`
  — VP to supply the exact `f=` filter set and `c=` column list. The tight examples for
  reference (Stage-2 / Technical / Custom views) are in the task brief.

## Deep-link button (folds into same effort)

On each industry context (Lookup tab card), a "Stage-2 stocks on Finviz →" button opens the
prefilled screener for that `ind_<slug>` in a new tab. Pure URL construction from the slug
map — zero backend. Use the *user-facing* (tighter Stage-2) filter template for the button so
the human lands on a clean list, even though our stored scrape uses the wide net.

## PWA (D8)

- **Picks tab (new):** top-level tab. Read `picks.csv` latest date. Group by `list_category`
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
2. Backfill daily closes for every tracked ticker (incl. names that exited the screen) from
   **FMP historical** (already integrated) or yfinance/Stooq.
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
   paginated scrape + append), `collect_picks.yml` separate workflow, `data/picks/picks.csv`.
   **Start the daily clock ASAP.** Needs VP URL template (D4).
3. **Phase 3 — PWA surfaces:** Picks tab + Lookup-tab section + deep-link button + release.
4. **Phase 4 — attribution** (later, own session): `eval_picks.py`, FMP backfill, methodology
   comparison.
5. **Spike (optional) — TwelveData/extended indicators** if Finviz columns prove insufficient.

## Open dependencies / questions parked for VP

- [ ] **Canonical wide-net Finviz URL(s)** — VP to supply `f=` filters + `c=` column list (D4/D5).
- [ ] Selector thresholds (the anti-flash floors) — start conservative, tune after first weeks.
- [ ] Total selected-group cap per day (bounds scrape volume) — propose 30.
- [ ] Finviz ToS comfort level on ~20–30 paginated screener scrapes/day (escalation over the
      2 group-page scrapes today). Politeness + cap mitigate; flag if concern.
- [ ] Stock universe geography (Finviz `cap_midover` includes foreign listings) — keep all or
      US-only? Default: keep all, store country column, filter later.

## Testing

- `collect_picks.py` pure functions: `slugify_industry`, `select_groups` (each category +
  floor), pagination loop (mock pages), append/dedup. Use `tmp_path`/`StringIO` per house rule.
- Slug-map anti-drift test: every industry in `snapshots.csv` has a row in
  `finviz_industry_slugs.csv` (mirrors taxonomy validation discipline).
- PWA: Playwright fixture-intercept tests for Picks tab + Lookup section (per CLAUDE.md
  pattern).
