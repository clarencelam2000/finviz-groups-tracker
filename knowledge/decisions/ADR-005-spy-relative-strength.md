# ADR-005: SPY relative-strength signals — source, spread vs ratio, forward accumulation

**Date**: 2026-06-20
**Status**: Accepted

## Context

The tracker's existing signals compare sectors/industries against *each other*
(peer rankings). A user requested a second axis: is each group outperforming the
S&P 500 itself? This ADR records the key decisions made during the RS integration
design, so future contributors understand why the implementation is shaped the way
it is.

---

## Decision 1: Data source — Finviz SPY quote page, not a market-data API

**Chosen:** Scrape `https://finviz.com/stock?t=SPY&p=d` using the same Playwright
+ retry path that already works for group data.

**Rejected alternatives:**

| Alternative | Rejection reason |
|-------------|-----------------|
| Alpha Vantage / Polygon / Yahoo Finance API | New API secret, new trust model, new timezone/holiday handling; potential window-definition mismatch with group `perf_*` (rolling 1-week vs calendar week, for instance). |
| Compute SPY from S&P 500 constituent data | Expensive and unnecessary; Finviz already publishes SPY's timeframe-aligned `perf_*` values. |
| Use an existing free JSON endpoint | All reliable ones require API keys or have rate limits that make daily automation fragile. |

**Rationale:** Finviz's SPY quote page exposes the same `perf_week/month/quarter/
half/year/ytd` columns used for groups, aligned to the same timezone and settlement
conventions. RS is an **aligned subtraction on matching timeframes** — using the same
source guarantees window definitions match exactly. The cost is one extra Playwright
page load per daily run (same Cloudflare/Azure path as groups; no new secrets).

---

## Decision 2: RS spread (absolute difference), not RS ratio

**Chosen:** `rs_X = group_perf_X − SPY_perf_X` (in percentage points).

**Rejected alternative:** RS ratio `(1 + group_perf) / (1 + SPY_perf)` (the RRG
standard).

**Rationale:**
- Spread is additive with existing `perf_*` percentage columns — no unit change.
- Symmetric around 0: positive = beating, negative = lagging. Easy to reason about.
- Handles negative tapes cleanly (SPY −5%, group −2% → RS = +3pp outperformance).
- Ratio can be derived from the stored spread algebraically at any time; the reverse
  is not true. Storing spread is the less-lossy choice.
- For display purposes the difference between spread and ratio is negligible at the
  small returns common to week/month timeframes.

**Ratio remains available:** `rs_ratio = (1 + g/100) / (1 + s/100)` can be derived
from stored `perf_*` columns whenever the RRG view ships. See Decision 3.

---

## Decision 3: Forward accumulation only — no historical SPY backfill

**Chosen:** RS history starts accumulating from the first day `collect.py` runs with
SPY support. No backfill attempt.

**Rejected alternative:** Backfill SPY history via API to get deeper RS series.

**Rationale:** RS is pairwise — `group_perf(D) − SPY_perf(D)` requires *both* sides
on date D. Group data exists only from project start (a few weeks). A 5-year SPY
series is useless on dates with no group data. The RS series is bounded by the
*shorter* history (groups), so an API backfill would extend SPY standalone but not
RS. The NaN-until-enough-history convention already in the pipeline handles this
cleanly.

---

## Decision 4: Raw SPY `perf_*` persisted in benchmark CSV (two-way-door invariant)

**Chosen:** Store raw SPY `perf_day/week/month/quarter/half/year/ytd` in
`data/benchmark/snapshots.csv`. Never store only the derived spread.

**Invariant:** As long as raw SPY `perf_*` per date is retained, every downstream
form — RS spread, RS ratio `(1+gp)/(1+sp)`, and full RRG axes — is derivable
retroactively over the entire stored history with zero data loss versus building it
today. Storing only the spread would make RRG impossible without a backfill.

**Effect:** The benchmark CSV mirrors the snapshot CSV structure (append-only,
`date`-keyed, last-write-wins per date). Adding fields to the benchmark CSV later
requires only a `ensure_csv`-style migration; no reprocessing of group data.

---

## Decision 5: RS columns go in `deltas.csv`, not `snapshots.csv`

**Chosen:** RS signals are computed columns that live in `data/{group}/deltas.csv`
alongside `momentum_score`, `rank_agreement`, etc.

**Rationale:**
- `snapshots.csv` is raw scraped data only (immutable source-of-truth convention).
- RS is derived (requires a join with benchmark data); placing it in `deltas.csv`
  mirrors how all other derived signals are handled.
- The `delta_columns()` single-source-of-truth in `delta_config.py` already governs
  this schema; adding RS there means `export_db.py` and `dashboard/app.py` pick up
  the columns automatically.
- `ensure_deltas_csv()` auto-migrates existing CSVs when RS columns are added.

---

## Decision 6: `bench_df` loaded once in `main()`, passed to `compute_for_group`

**Chosen:** Load benchmark CSV once before the sector/industry loop, pass the
resulting `pd.DataFrame` as `bench_df=` to `compute_for_group`.

**Rejected alternative:** Load inside `compute_for_group`.

**Rationale:** With ~150 industries, loading the CSV inside the function would read
the same file ~150 times. Loading once and passing it keeps I/O cost constant
regardless of group count.

---

## Signal catalog (Tiers 1–4, shipped in Phase 2)

| Column | Definition |
|--------|-----------|
| `rs_day/week/month/quarter/half/year/ytd` | Raw spread: `group_perf_X − SPY_perf_X` |
| `rs_score` | Mean percentile of RS spreads across all 7 timeframes (0–1) |
| `rs_agreement` | Cross-timeframe consistency of RS spreads on mo/qtr/half (0–1) |
| `rs_confirmed` | `rs_score × rs_agreement` |
| `rs_slope` | LS slope of `rs_month` spread over `SLOPE_WINDOW = 10` sessions |
| `rs_accel` | Change in `rs_score` over `ACCEL_WINDOW = 10` sessions |
| `rs_regime_short_long` | Short-horizon RS percentile mean minus long-horizon RS |

Tier 5 flags (`beats_benchmark_X`, `rs_new_high`, `rs_cross`) and Tier 6 depth
signals (`rs_volatility`, `rs_rank`, `rs_drawdown`) are deferred to Phases 3/5.
RRG / `rs_ratio_*` deferred to Phase 4.
