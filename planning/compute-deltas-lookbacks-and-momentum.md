# Plan: Config-driven lookback windows + momentum variants for compute_deltas

## Context

`scripts/compute_deltas.py` computes rank/delta artifacts into `data/*/deltas.csv`. Two
problems motivate this change:

1. **Lookback windows are baked into the schema.** Windows are `[7, 14, 30]` *calendar* days.
   We want `5/10/20/50` **trading** days, and want future window changes to be cheap.
   Today the delta column names encode the window value (`rank_ytd_delta_7d`), so changing
   windows renames every column and breaks every consumer that hardcodes a literal name.
2. **The output schema is defined in 3 places that already disagree.** `DELTA_COLUMNS` is
   duplicated in `compute_deltas.py`, `dashboard/app.py`, and `export_db.py` — and the
   `export_db.py` copy is already stale (missing `rank_day`, `rank_agreement`). The generation
   loop and `DELTA_COLUMNS` also disagree, forcing the `if delta_col not in DELTA_COLUMNS:
   continue` guard at line 297.

Goal: make windows + which-metrics-get-deltas a **single config**, switch to **trading-day**
lookbacks, renumber to `5/10/20/50`, and add several **momentum variants**. Keep the wide CSV
format (config-driven wide), not long/tidy — dynamic-wide gives ~80% of the flexibility at
~20% of the blast radius, and the PWA isn't being reworked here.

### Why config-driven wide and not long/tidy

The fully-general version is a long/tidy schema (`date, name, metric, lookback, value`), which
makes adding a window a zero-schema-change operation (emit more rows, no renamed columns):

```
date,        name,    metric,    lookback, value
2026-06-17,  Energy,  rank_ytd,  5,        +6
2026-06-17,  Energy,  rank_ytd,  10,       +3
```

But it forces every consumer that does a direct column lookup today
(`row["rank_ytd_delta_5d"]`, the PWA's `rank_ytd_delta_${win}`, the Streamlit table,
`export_db`) to switch to filter-and-pivot logic. That's a rewrite of all read paths.
Config-driven wide keeps the familiar wide format but makes the *next* window change a
one-line edit — the right trade-off unless/until the PWA is being reworked.

## Decisions (confirmed)

- **Config-driven wide** format (not long/tidy).
- **Trading-day** windows: `5, 10, 20, 50`.
- Momentum variants to add: rank-trend slope, acceleration, confirmed, weighted-mid
  (toward 1mo/3mo), weighted-fast (toward short timeframes), short-vs-long regime.
- PWA scope: **minimal renumber now**, with **full-dynamic windows as a tracked fast-follow**.

## Design

### 1. Single source of truth for delta schema (`scripts/delta_config.py`, new)

A small module both scripts and the dashboard import:

```python
LOOKBACK_WINDOWS = [5, 10, 20, 50]          # trading days
LOOKBACK_BASIS = "trading"                   # vs "calendar"

# which rank/perf metrics get per-window deltas
RANK_DELTA_METRICS = ["rank_week", "rank_month", "rank_ytd"]
PERF_DELTA_METRICS = ["perf_week", "perf_month", "perf_ytd"]

RANK_COLS = ["rank_day","rank_week","rank_month","rank_quarter",
             "rank_half","rank_year","rank_ytd"]
MOMENTUM_COLS = ["momentum_score","momentum_confirmed","momentum_weighted_mid",
                 "momentum_weighted_fast","momentum_accel","regime_short_long",
                 "rank_trend_slope","rank_agreement"]

def delta_columns() -> list[str]:
    cols = ["date","name", *RANK_COLS]
    for w in LOOKBACK_WINDOWS:
        for m in RANK_DELTA_METRICS: cols.append(f"{m}_delta_{w}d")
        for m in PERF_DELTA_METRICS: cols.append(f"{m}_delta_{w}d")
    cols += MOMENTUM_COLS
    return cols
```

`delta_columns()` becomes the **only** definition. This kills the loop/`DELTA_COLUMNS`
asymmetry and the line-297 guard — every generated combo is now intentional.

> Note: this drops the current "only some perf-deltas" quirk (e.g. `perf_month` only at 7d).
> Going forward every `PERF_DELTA_METRIC` gets every window. Column count:
> 4 windows × (3 rank + 3 perf) = 24 delta cols + 7 rank + 8 momentum ≈ 39 cols. Fine for CSV.

### 2. Trading-day lookbacks (`compute_deltas.py`)

`available_dates` is already the sorted list of actual trading days in the snapshot. Replace
calendar subtraction with **position-based** lookup — naturally gap-tolerant:

```python
def find_trading_date_back(available_dates, target_date, n_sessions):
    if target_date not in available_dates: return None
    i = available_dates.index(target_date)
    j = i - n_sessions
    return available_dates[j] if j >= 0 else None
```

Replace the `prior_target = target_date - timedelta(days=n)` / `find_nearest_date` block
(lines 246–254) with this. Keep `find_nearest_date` (still useful / tested) but it's no longer
on the main path. Early history (fewer than N sessions) → `None` → NaN deltas, same as today.

### 3. Momentum variants (new pure functions next to `compute_momentum`)

All take a single-day ranked frame (and, where noted, prior frames). All return a `pd.Series`,
NaN for `n<=1`, following the existing percentile convention `(n - rank) / (n - 1)`.

- **`momentum_confirmed`** = `momentum_score * rank_agreement` (both already computed). Free.
- **`momentum_weighted_mid`** = weighted mean of the 7 perf percentiles, heavier weight on
  `perf_month` and `perf_quarter` (e.g. weights day .5, week 1, month 2, quarter 2, half 1,
  year 1, ytd 1). Weights live in `delta_config.py`.
- **`momentum_weighted_fast`** = same machinery, weights toward `perf_day`/`perf_week`.
  Implement one `weighted_momentum(df, weights)` helper; the two variants are just weight dicts.
- **`regime_short_long`** = mean(short percentiles: day, week) − mean(long percentiles:
  half, year, ytd). Range ~[-1,1]; positive = emerging leader, negative = fading.
- **`momentum_accel`** = today's `momentum_score` − `momentum_score` computed on the snapshot
  ~N trading days back. Recompute momentum on a chosen lookback frame (reuse the loaded
  lookback frame for, say, the 10-session window). NaN before history exists.
- **`rank_trend_slope`** = least-squares slope of a group's `rank_ytd` over the last K
  snapshots (e.g. K=10 sessions), x = session index. Negative slope = rank improving (rank 1
  is best), so **negate** so positive = improving, matching the delta sign convention. Needs
  K prior ranked frames loaded by name.

### 4. Update consumers

- `dashboard/app.py`: delete local `DELTA_COLUMNS`, import `delta_columns()`. Replace the
  `["7d","14d","30d"]` selectbox (line 156) with `[f"{w}d" for w in LOOKBACK_WINDOWS]`.
- `export_db.py`: delete local (stale) `DELTA_COLUMNS`, import `delta_columns()`.
- `docs/index.html` (PWA): **minimal renumber now** — change the three hardcoded buttons /
  validation list / literal column refs from `7d/14d/30d` to the new windows. Add the 4th
  window (`50d`) button manually. Default moves from `rank_ytd_delta_7d` → smallest new window
  (`5d`); `_30d` references → largest (`50d`). **Full-dynamic (read windows from CSV header)
  is a tracked fast-follow** — see Fast-follow section.

## Migration

No data backfill script needed: `ensure_deltas_csv()` already auto-migrates on header
mismatch — it rewrites existing rows against the new header, filling absent columns with "".
Old `_7d/_14d/_30d` columns simply drop; new `_5d/_10d/_20d/_50d` + momentum columns appear
empty until `compute_deltas.py` reruns per date. Recommend regenerating history:
`for d in <each date>: python scripts/compute_deltas.py --date d` (or a small loop), since
trading-day deltas + new momentum cols need recomputation from snapshots.

## Critical files

- `scripts/delta_config.py` — NEW, single source of truth
- `scripts/compute_deltas.py` — import config, trading-day lookback, new momentum fns
- `scripts/export_db.py` — import config (removes stale duplicate)
- `dashboard/app.py` — import config, dynamic lookback selectbox
- `docs/index.html` — minimal window renumber (full-dynamic is fast-follow)
- `tests/test_compute_deltas.py` — see below
- `tests/test_generate_ai.py` — update fixtures off hardcoded `rank_ytd_delta_7d`

## Tests (required per repo rules)

- `find_trading_date_back`: exact, N back, beyond start → None, gap tolerance.
- `delta_columns()`: shape, no dupes, all expected names present.
- Each new momentum fn: range bounds, `n<=1` → NaN, best/worst sanity, all-NaN column handling.
- `rank_trend_slope`: monotonic-improving series → positive slope; flat → ~0; insufficient
  history → NaN. Sign convention (improving rank → positive).
- `momentum_accel`: improving → positive; no prior frame → NaN.
- Update `compute_for_group` tests for new column set + trading-day windows.
- Run `python3 -m pytest tests/ -q` before each commit.

## Fast-follow (tracked, separate PR)

**PWA full-dynamic windows.** Replace the minimal-renumber hardcoding in `docs/index.html`
with windows derived from the CSV header at load time (no literal window values in JS). Record
in: (a) this plan, (b) `.session/SPRINT.md` backlog, (c) `.session/session-notes.md`
next-steps, and (d) the implementation PR description as a known follow-up.

## Commit slicing (keep small, per branch-commit-discipline.md)

0. `docs: add plan for lookback config + momentum variants` (this doc — merge before coding)
1. `feat: add delta_config single source of truth` (+ wire compute_deltas/export_db/dashboard, tests)
2. `feat: switch lookbacks to trading-day basis` (find_trading_date_back, 5/10/20/50, tests)
3. `feat: add momentum variants` (one commit, tightly coupled, + tests)
4. `feat: renumber PWA lookback windows to 5/10/20/50` (docs/index.html minimal)
5. session notes / WORK_LOG / SPRINT update (incl. PWA full-dynamic fast-follow)

## Verification

- `python3 -m pytest tests/ -q` green.
- `python scripts/compute_deltas.py --date <recent>` on existing snapshots; inspect
  `data/*/deltas.csv` header == `delta_columns()`, spot-check new momentum cols.
- `python scripts/export_db.py` runs, exports include new columns.
- Streamlit + PWA functional test (Playwright per CLAUDE.md) with fixtures: lookback selector
  shows 5/10/20/50, movers render off the new default window.
