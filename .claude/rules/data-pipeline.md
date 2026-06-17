# Data Pipeline Rules

## CSV deduplication
All append operations check for existing `(date, name)` before writing. The `date` column uses `YYYY-MM-DD` in US/Eastern timezone. `collected_at` is ISO 8601 UTC and is NOT part of the uniqueness key — re-running the scraper on the same day updates the timestamp but is treated as the same row.

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
`rank_X_delta_Nd = rank_prior - rank_today`
Positive = improved (e.g., was rank 18, now rank 12 → delta = +6).

## Lookback windows (trading-day based)
Lookback windows are defined once in `scripts/delta_config.py` (`LOOKBACK_WINDOWS`,
currently `[5, 10, 20, 50]`) and measured in **trading sessions**, not calendar days.
`find_trading_date_back()` indexes back by position in the sorted list of available
trading dates, so weekend/holiday gaps are skipped automatically. If fewer than N
sessions of history exist, the delta is NaN. (The legacy calendar-based
`find_nearest_date()` — scan up to 5 extra calendar days back — is retained for
reference but is no longer on the main delta path.)

To change windows, edit `LOOKBACK_WINDOWS`; every consumer derives its columns from
`delta_config.delta_columns()`. The PWA still hardcodes the window literals (minimal
renumber); making it read them from the CSV header is fast-follow LB-FF1.

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
