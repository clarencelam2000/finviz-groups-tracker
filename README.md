# Finviz Groups Tracker

Daily tracker for Finviz sector and industry group performance. Scrapes the Finviz Groups page using Playwright (headless Chromium), stores raw performance snapshots in append-only CSVs, and computes rank and delta artifacts for trend analysis.

## What it does

- Fetches sector and industry performance data from Finviz daily (weekdays at 22:00 UTC via GitHub Actions)
- Stores raw snapshots in `data/sectors/snapshots.csv` and `data/industries/snapshots.csv`
- Computes rankings, rank changes over 7/14/30-day lookback windows, and a momentum score
- Exports to SQLite and Parquet via `scripts/export_db.py`
- Provides a Streamlit dashboard for local browsing and visualization

## How to run locally

### 1. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Collect a snapshot

```bash
python scripts/collect.py
```

This fetches current sector and industry data from Finviz and appends it to the snapshot CSVs. The script is idempotent — running it multiple times on the same day will not create duplicates.

### 3. Compute deltas

```bash
python scripts/compute_deltas.py
```

Reads the snapshot CSVs and appends rank/delta rows to the deltas CSVs.

### 4. Launch the dashboard

```bash
streamlit run dashboard/app.py
```

### 5. Export to SQLite / Parquet (optional)

```bash
python scripts/export_db.py
```

Outputs are written to `./exports/` (not committed to Git).

## Data structure

```
data/
  sectors/
    snapshots.csv   # raw daily snapshots, one row per (date, sector)
    deltas.csv      # computed ranks and deltas, one row per (date, sector)
  industries/
    snapshots.csv   # same structure, for industries
    deltas.csv
```

### Snapshot columns

`date, collected_at, group_type, name, stocks, market_cap, pe, fwd_pe, perf_day, perf_week, perf_month, perf_quarter, perf_half, perf_year, perf_ytd, avg_volume, rel_volume, change`

### Delta columns

`date, name, rank_week, rank_month, rank_quarter, rank_half, rank_year, rank_ytd` plus rank deltas and perf deltas for 7d/14d/30d windows, and `momentum_score`.

## GitHub Actions

The workflow in `.github/workflows/collect.yml` runs automatically on weekdays at 22:00 UTC (approximately 6 PM Eastern), collects a snapshot, computes deltas, and commits the updated CSVs back to the repository.

You can also trigger it manually from the GitHub Actions tab using "workflow_dispatch".
