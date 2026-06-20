# Plan: Relative Strength vs S&P 500 (SPY) Benchmark Integration

## Context

**Why this is being built.** The tracker's core asset today is the *relative ranking of
groups against each other* — a sector can be #1 of 11 and still be lagging the market in a
rip-roaring tape, or #6 and beating it. A VP requested a second axis: **strength versus a
benchmark (S&P 500 / SPY)**, i.e. is each sector/industry out- or under-performing the
market itself. This is genuinely additive to the existing peer-rank signal and maps directly
onto the rotation thesis ("where is capital rotating *relative to the market*").

**Outcome.** Each sector and industry gets relative-strength (RS) signals versus SPY across
the existing perf timeframes, with trend/acceleration variants that surface groups *starting*
to pull away from the market. Raw SPY data is captured from day one so that richer views
(RRG / RS-ratio) remain a pure-derivation fast-follow — never blocked.

**This document is itself the Phase 0 deliverable** (see below): the full, self-contained
plan is committed to the repo so any teammate can pick it up.

---

## Key decisions (resolved during brainstorm)

| Question | Decision | Rationale |
|----------|----------|-----------|
| **Data source** | **Scrape Finviz SPY quote page** (`finviz.com/stock?t=SPY&p=d`) | Same source/trust model/timezone/Cloudflare-on-Azure path as groups. Zero new API secrets. SPY's `perf_week/month/quarter/...` line up 1:1 with group `perf_*` — apples-to-apples subtraction, no window-definition reconciliation. |
| **Index vs ETF** | **Don't care** (use SPY ETF) | Tracking error is immaterial for RS. User confirmed. |
| **Storage** | **New `data/benchmark/snapshots.csv`** (raw), derived RS columns go in `deltas.csv` | Clean separation; mirrors existing append-only structure; does NOT pollute the 11-sector / ~150-industry rank invariants or momentum `n`. |
| **RS spread vs ratio** | **Store the spread** (`group_perf − SPY_perf`) as canonical | Additive with existing `perf_*` percentage columns, zero new units, symmetric around 0 (>0 = beating market), handles negative tapes cleanly. Ratio derived for display only if/when RRG ships. |
| **Backfill via API** | **No — accumulate forward** | RS depth is gated by *group* history (binding constraint), not SPY history. An API can't seed RS earlier than group data exists. NaN-until-enough-history is the pipeline's existing convention. |
| **RRG / RS-ratio now?** | **Defer — but keep the door open** | NOT a one-way door *iff* raw SPY `perf_*` is persisted. See invariant below. |

### Two-way-door invariant (critical)

> **As long as `data/benchmark/snapshots.csv` stores SPY's raw `perf_*` per date, every
> downstream form — RS-spread, RS-ratio `(1+gp)/(1+sp)`, and full RRG axes (ratio +
> its slope) — is derivable retroactively over the entire stored history with zero data
> loss versus building it today.** The one-way-door failure mode is storing only the derived
> spread and discarding raw SPY. We explicitly persist raw SPY, so deferring RRG costs nothing
> but calendar time — and since group-data depth is the binding constraint, that cost is zero.

**Why deep SPY history doesn't help (corrects an earlier overstatement):** RS is pairwise —
`group_perf(D) − SPY_perf(D)` needs *both* sides on date D. We only have group data back to
project start (a few weeks). A 5-year SPY series is useless on dates with no group data, so
the RS series is only as deep as the *shorter* (group) history. An API backfill would only
give SPY's *standalone* trend early (for a regime overlay) — not earlier RS.

### How the benchmark equivalent is computed for sectors/industries

No constituent aggregation needed. Finviz already publishes each sector's and each industry's
own cap-weighted `perf_*`; SPY's quote page gives the same timeframe columns for the market.
RS is an **aligned subtraction on matching timeframes**, broadcasting the one SPY row for date
D against every group row for date D:

```
rs_week(group, D)  = group.perf_week(D)  − SPY.perf_week(D)
rs_month(group, D) = group.perf_month(D) − SPY.perf_month(D)   # ...etc for all 7 timeframes
```

11 subtractions/timeframe/day for sectors, ~150 for industries — trivial. Requires a clean
`date` join: one SPY row per `YYYY-MM-DD` (US/Eastern), same `trading_date()` rolling. If SPY
scrape fails on a day groups succeeded (or vice versa), that date's RS is NaN (existing
graceful-degradation pattern).

---

## Full derived-signal catalog (for the planning doc + future phases)

All live behind `scripts/delta_config.py` per the single-source-of-truth rule, NaN-until-
enough-history. Tiers indicate sequencing, not all ship at once.

**Tier 1 — raw RS spreads (foundation)**
- `rs_day, rs_week, rs_month, rs_quarter, rs_half, rs_year, rs_ytd` — `group_perf_X − SPY_perf_X`. Everything derives from these. Positive = beating market over that horizon.

**Tier 2 — aggregate / breadth of RS** (mirror existing momentum machinery)
- `rs_score` — analog of `momentum_score`: percentile-rank RS spreads across all 7 timeframes, averaged. One number for "broadly beats the market."
- `rs_agreement` — analog of `rank_agreement`: do the 7 RS timeframes agree in sign/direction? Durable vs one-timeframe fluke.
- `rs_confirmed` — `rs_score × rs_agreement` (mirrors `momentum_confirmed`).

**Tier 3 — RS trend & acceleration (headline signals)**
- `rs_slope` — signed least-squares slope of the canonical RS line (likely `rs_month` or a blend) over the trailing window. Positive = outperformance *building*. Reuses `compute_rank_trend_slope` machinery.
- `rs_accel` — change in `rs_slope` (or `rs_score`) over `ACCEL_WINDOW` sessions. Earliest-warning rotation signal.

**Tier 4 — regime / context overlays**
- `spy_perf_X` (carried from benchmark CSV) + derived `spy_regime` — is the market itself up/down over the window. Distinguishes *offensive* leadership (group up, SPY up, group more) from *defensive* (SPY down, group down less) — same RS number, very different meaning.
- `rs_regime_short_long` — analog of `regime_short_long` on RS: short-horizon RS minus long-horizon RS. Positive = *newly* beating the market (emerging RS leader) vs a year-long leader that may be late.

**Tier 5 — discrete flags (cheap UI wins)**
- `beats_benchmark_X` — boolean per timeframe.
- `rs_new_high` — RS line at its highest in the available window (classic RS-new-high leadership flag).
- `rs_cross` — flipped from lagging to leading (RS spread crossed 0) within last N sessions — discrete rotation trigger.

**Tier 6 — second-order / nice-to-have**
- `rs_volatility` — stdev of RS spread over window (persistent vs choppy outperformance; quality filter).
- `rs_rank` — rank groups *by* RS spread (RS leaderboard, distinct from perf-vs-peers `rank_*`).
- `rs_drawdown` — distance of current RS line below its trailing peak (flags fading leaders early).

**If only three beyond raw spreads:** `rs_score` (breadth), `rs_slope` (building outperformance),
`rs_regime_short_long` (emerging vs late leaders) — these carry the rotation thesis and reuse
existing machinery.

**Deferred (door kept open by the invariant):** `rs_ratio_*` and the **RRG view** (x = RS-ratio,
y = RS-momentum; quadrants Leading / Weakening / Lagging / Improving). Pure derivation from
stored raw SPY + group perf whenever greenlit.

---

## Implementation phases

### Phase 0 — Commit & merge THIS plan, then PAUSE for approval  ⟵ gate

1. Add this plan to the repo as `planning/PLAN_relative-strength-benchmark.md` (house style:
   `planning/PLAN_<slug>.md`; register in `planning/README.md` table with branch ref). It must
   be complete and self-contained — the decision table, the two-way-door invariant, the signal
   catalog, the phase breakdown, and the verification approach all travel with it.
2. Open a **draft PR** on branch `claude/wonderful-hypatia-qeemic`, mark ready for review.
3. **Stop. Await user approval before any Phase 1+ code.** No scraper or schema changes land
   in the plan PR.

### Phase 1 — Capture & store raw SPY (the door-keeping move; no UI, no RS yet)

- **`scripts/collect.py`**: add a SPY quote-page fetch + parse. Reuse `fetch_html()` (Playwright
  + retry), `trading_date()` (NYSE rolling — share verbatim, no fork), the perf parsers
  (`parse_perf`), and the dedup/evict/append helpers (`load_existing_keys`, `evict_today_rows`,
  `append_records`, `ensure_csv`). New selector for the quote page (NOT `.groups_table` — the
  quote page DOM differs; identify it during impl). Write to **`data/benchmark/snapshots.csv`**
  with `date, collected_at, ticker, perf_day, perf_week, perf_month, perf_quarter, perf_half,
  perf_year, perf_ytd` (+ price if cheaply available — harmless extra, supports future price-RS).
- Same last-write-wins per `date` semantics as groups.
- **Tests** (`tests/test_collect_parsing.py` or new `test_collect_benchmark.py`): quote-page parse
  → expected perf dict; empty/`-`/`N/A` handling; StringIO/`tmp_path`, no network.
- **Automation**: the existing `collect.yml` run scrapes SPY in the same job (one extra page load).
- Outcome: SPY history starts accumulating immediately. No deltas.csv change yet.

### Phase 2 — RS signals (Tier 1 + the chosen Tier 2/3)

- **`scripts/delta_config.py`**: add `RS_COLS` (the 7 `rs_*`) and the chosen aggregate/trend cols
  to the schema generated by `delta_columns()`. Comment every new constant (in-code + README
  table + CLAUDE.md, per the three-places rule). Decide the canonical RS line for `rs_slope`.
- **`scripts/compute_deltas.py`**: in `compute_for_group`, load the matching benchmark row per
  date (join on `date`), compute spreads, and reuse `compute_momentum`/`compute_rank_agreement`/
  `compute_regime`/`compute_rank_trend_slope` adapted to RS inputs. NaN when SPY row or history
  missing. `_fmt` for output.
- **Tests** (`test_delta_config.py` for schema; `test_compute_deltas.py` for each new pure fn:
  happy path + NaN/empty/single-row edges). Update `ensure_deltas_csv` auto-migration is exercised.
- **`dashboard/app.py`** + **`docs/index.html`** pick up new columns automatically via
  `delta_columns()` / `extractWindowsFromHeader`; no UI yet beyond data availability.

### Phase 3 — Surface in PWA

- RS badge/chip on existing cards ("+2.3% vs SPY", green/red) — cheapest visible win.
- New **"vs Market"** view sorted by `rs_score` / `rs_slope` (the "pulling away from the market"
  board), following the existing tab pattern (`docs/index.html` `#tab-bar`, `renderCard`).
- New threshold constants (`RS_STRONG`, `RS_SLIGHT`) beside `ACCEL_*`/`SLOPE_*`, documented in
  all three places.
- **`GUIDE`** entries for each new metric (verbatim-synced with `knowledge/moaty-metrics.md`);
  `tests/test_guide_releases.py` enforces sync + `current === releases[0].version`.
- **Release triplet** (same PR): prepend `docs/releases.json` entry, bump `current`, bump `CACHE`
  in `docs/sw.js`.

### Phase 4 (optional, deferred) — RRG / RS-ratio

- Pure derivation from stored raw SPY + group perf: `rs_ratio_*` + RRG quadrant view (x=ratio,
  y=ratio-momentum). No new data capture required — the invariant guarantees full history.

### Cross-cutting docs (with whichever phase introduces the metric)

- `knowledge/decisions/ADR-005-spy-relative-strength.md` — source choice, spread-vs-ratio,
  forward-accumulation, the two-way-door invariant, alternatives rejected (API, pseudo-group row).
- `knowledge/moaty-metrics.md` one-liners for each shipped RS metric.
- README § Configurable parameters + CLAUDE.md updates for every new constant/column.

---

## Critical files & reusable anchors

| File | Reuse |
|------|-------|
| `scripts/collect.py` | `fetch_html`, `trading_date`/`_is_trading_day`/`NYSE_HOLIDAYS`, `parse_perf`, `load_existing_keys`, `evict_today_rows`, `append_records`, `ensure_csv` |
| `scripts/delta_config.py` | `delta_columns()` single-source pattern; mirror `RANK_COLS`/`MOMENTUM_COLS` + `LOOKBACK_WINDOWS`/`ACCEL_WINDOW`/`SLOPE_WINDOW`/`REGIME_SHORT`/`REGIME_LONG` |
| `scripts/compute_deltas.py` | `compute_for_group`, `find_trading_date_back`, `compute_momentum`, `compute_rank_agreement`, `compute_regime`, `compute_rank_trend_slope`, `_fmt`, `ensure_deltas_csv`, `_evict_date_rows` |
| `docs/index.html` | threshold constants block (~L289), `fetchCSV`/`loadGroup`, `extractWindowsFromHeader`, `GUIDE`, `#tab-bar`, `renderCard` |
| `docs/releases.json`, `docs/sw.js` | release triplet (`current`, `releases[]`, `CACHE`) |
| `tests/` | `conftest.py` fixtures; `test_delta_config.py`, `test_compute_deltas.py`, `test_collect_parsing.py`, `test_guide_releases.py`; StringIO/`tmp_path` pattern |
| `planning/`, `knowledge/decisions/` | doc house style + ADR template |

---

## Verification

- **Phase 0**: planning doc renders; PR open & ready; registered in `planning/README.md`. No code.
- **Phase 1**: `python3 -m pytest tests/ -q` green; run `collect.py` locally/Actions (Cloudflare
  blocks cloud) → `data/benchmark/snapshots.csv` gets one SPY row/day, correct `date`, last-write-
  wins on rerun. Playwright-intercept harness (per CLAUDE.md) can feed a fixture quote page for the
  parser test without live Finviz.
- **Phase 2**: unit tests for each RS pure fn (happy + NaN/empty/single-row); run `compute_deltas.py`
  on fixture data → `rs_*` columns populate where history exists, NaN otherwise; `ensure_deltas_csv`
  auto-migrates an old header.
- **Phase 3**: PWA Playwright functional test (intercept `raw.githubusercontent` CSVs with fixtures
  per CLAUDE.md) → RS badge renders, "vs Market" view sorts correctly, GUIDE links resolve;
  `test_guide_releases.py` green; cache bump verified.
- Every phase: `python3 -m pytest tests/ -q` before each commit; one logical slice per commit;
  session logs (`.session/`) updated; PR per branch.
