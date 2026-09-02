# Data Pipeline Rules

## CSV deduplication
All append operations check for existing `(date, name)` before writing. The `date` column uses `YYYY-MM-DD` in US/Eastern timezone. `collected_at` is ISO 8601 UTC and is NOT part of the uniqueness key — re-running the scraper on the same day updates the timestamp but is treated as the same row.

`data/picks/picks.csv` follows the same convention: its uniqueness key is `(date, list_category, ticker)`, and `collected_at` (added Phase 3e) is a single run-wide UTC timestamp stamped on every row, not part of that key — a same-day re-run of `collect_picks.py` just carries the newer timestamp forward.

## Value conventions
- `perf_*` columns: raw percentage floats (e.g., `2.34` means +2.34%). NOT stored as decimals.
- `market_cap`: billions as float (e.g., `1.23` = $1.23B, `0.456` = $456M).
- `avg_volume`: raw units (e.g., `1230000`). NOT abbreviated.
- `pe`, `fwd_pe`: float, empty string if N/A or `-`.
- Any missing/unparseable value: store as empty string in CSV (pandas reads as `NaN`).

## Rank computation
- Ranks are computed from `perf_*` values each day, never scraped from Finviz.
- Use `pandas.Series.rank(ascending=False, method='min', na_option='bottom')`.
- Rank 1 = best performer (highest % gain).
- Each `perf_*` metric gets its own independent rank column.

## Delta sign convention

**Rank deltas** (opposite arithmetic direction from perf — rank 1 = best, so
lower number = better):
```
rank_X_delta_Nd = rank_prior - rank_today
```
Positive = improved (e.g., was rank 18, now rank 12 → delta = +6).

**Perf deltas** (straightforward — higher % = better):
```
perf_X_delta_Nd = today_perf - prior_perf
```
Positive = performance improved over the window (e.g., week % is higher now than
N trading sessions ago). Note the arithmetic is the *opposite direction* from rank
deltas — this is intentional: rank 1 means highest gain, so improvement lowers the
rank number, while improvement in raw % raises the value.

## Lookback windows (trading-day based)
Lookback windows are defined once in `scripts/delta_config.py` (`LOOKBACK_WINDOWS`,
currently `[5, 10, 20, 50]`) and measured in **trading sessions**, not calendar days.
`find_trading_date_back()` indexes back by position in the sorted list of available
trading dates, so weekend/holiday gaps are skipped automatically. If fewer than N
sessions of history exist, the delta is NaN. (The legacy calendar-based
`find_nearest_date()` — scan up to 5 extra calendar days back — is retained for
reference but is no longer on the main delta path.)

To change windows, edit `LOOKBACK_WINDOWS`; every consumer derives its columns from
`delta_config.delta_columns()`. The PWA derives window buttons from the CSV header via
`extractWindowsFromHeader()` (LB-FF1, done 2026-06-18, PR #110). Residual: two hardcoded
`_20d` column literals remain in `docs/index.html` (~line 1741) — see SPRINT § LB-FF1-RESIDUAL.

## Momentum score formula
```python
momentum_score = mean([
    (n - rank_day) / (n - 1),
    (n - rank_week) / (n - 1),
    (n - rank_month) / (n - 1),
    (n - rank_quarter) / (n - 1),
    (n - rank_half) / (n - 1),
    (n - rank_year) / (n - 1),
    (n - rank_ytd) / (n - 1),
])
```
where `n` = number of groups with non-null values. Score range: 0.0 (worst) to 1.0 (best).

## Empty CSV handling
All scripts must handle header-only CSVs (0 data rows) without crashing. Check `len(df) == 0` before any groupby/rank/merge operation.

## File paths (relative to repo root)
- `data/sectors/snapshots.csv`
- `data/sectors/deltas.csv`
- `data/industries/snapshots.csv`
- `data/industries/deltas.csv`

## Schema changes to ground-truth CSVs — owner approval required, pure-function-first

Ground-truth CSVs (`data/**/snapshots.csv`, `data/**/deltas.csv`, `data/picks/picks.csv`,
`data/picks/picks_latest.csv`, `data/benchmark/snapshots.csv`, `data/picks/sessions/*.csv`) are
append-only historical records. Adding, removing, or renaming a column in one of these is a
**high-cost, hard-to-reverse action** — even an "additive, backfilled, two-way-door" migration
still means touching every historical row, permanently growing the file, and coupling every
downstream consumer (export_db, dashboard, PWA, evaluate_picks) to the new shape. Treat it with
the same care as a database schema migration, not as a normal code change.

**Before adding a column, ask: does this actually need to live in the pipeline?**

A derived value only belongs in the backend/CSV if it needs either:
- **Cross-row computation** — ranking or comparison against other rows (e.g. `rank_*`), which a
  single client-side row can't do on its own, or
- **Multi-day trailing computation** — a scan over several days of history that would be
  expensive or impractical to reconstruct at render/analysis time (e.g. `tight_range_7`).

If a value is a **pure, single-row function of columns that are already present in that row**
(no cross-row ranking, no trailing window), it does NOT need a backend column. Compute it where
it's consumed instead — client-side in the PWA (`docs/index.html`), or on the fly in whatever
analysis script needs it. The PWA already does this for several derived reads (SMA-distance %,
ATR-extension multiple) reconstructed straight from raw Finviz columns already in the row — new
derived facts of the same shape should follow that pattern, not add a column.

**A value that depends on a tunable config constant must never be persisted as if it were
observed ground truth.** If the constant changes later, every historical row's persisted value
silently stops matching what the current config would compute, and the only fix is a re-migration
every time the config changes. Config-dependent flags/scores belong computed at
render/analysis time from the constant + the already-stored raw inputs — same treatment as the
PWA's existing display-threshold constants (see `docs/CLAUDE.md` § PWA display thresholds).

**Concrete cautionary example:** PR #392 added a `power_of_3` column to `picks.csv` /
`picks_latest.csv` — a pure single-row function of `Price`/`ATR`/`SMA20`/`SMA50` (all already
present in every row) gated by a tunable ATR-multiple constant. It could have been a few lines of
client-side JS with zero migration. Instead it bumped the picks schema 118→119 columns, backfilled
13,395 historical rows, touched two pipeline files, and produced a merge-conflict-prone diff.

**Rule:** before implementing any schema change to a ground-truth CSV, write out — and get the
owner's explicit approval for, *before* implementing — why the value can't be a pure function
computed where it's consumed. This applies even to a migration that looks "safe" because it's
additive/superset/two-way-door. Build first, ask forgiveness later is not acceptable here; the
cost of undoing a shipped, backfilled schema change is far higher than the cost of asking first.
