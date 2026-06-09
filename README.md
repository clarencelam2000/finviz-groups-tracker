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

## Mobile app (iPhone)

A lightweight Progressive Web App lives at `docs/` and is served via GitHub Pages at:

```
https://clarencelam2000.github.io/finviz-groups-tracker/
```

No server required — it fetches the latest CSVs directly from GitHub on every load.

**To install on iPhone:**
1. Open the URL in **Safari** (not Chrome)
2. Tap Share → **Add to Home Screen**
3. Launches full-screen, no browser chrome

### Tab guide

**Today** — All sectors or industries as color-coded cards, sorted by YTD % by default. Use the sort dropdown to switch to Week / Month / Day. Each card shows the group's YTD rank badge, its name, Day % and Week % as secondary metrics, and the selected metric as the big number on the right. Green = positive, red = negative.

**Movers** — The biggest rank climbers and fallers over 7 / 14 / 30 days. A "data accumulating" placeholder is shown until enough history exists (7-day deltas arrive ~7 trading days after first collection). Each row shows how many ranking spots the group gained or lost. Green left border = gainer, red = loser.

**Momentum** — A composite breadth leaderboard sorted by `momentum_score`. Shows which groups are consistently strong (or weak) across all 7 performance timeframes at once, not just one hot streak. Includes a mini progress bar. Works from day one (does not require delta history).

**Refresh button (top-right)** — Clears the in-memory cache and re-fetches all CSV data from GitHub. Use this after the daily Actions run (~22:00 UTC / 6pm ET) to see the latest data. The app does not auto-refresh.

---

## Ranking and scoring methodology

### How ranks are computed

Every day, each group (sector or industry) is ranked from **1 (best)** to **N (worst)** independently for each of 7 performance metrics: `perf_day`, `perf_week`, `perf_month`, `perf_quarter`, `perf_half`, `perf_year`, `perf_ytd`. Rank 1 = highest % gain that day. Groups with missing data are placed at the bottom. Ties share the lowest rank among them (min method). Ranks are computed fresh from the raw CSV data — never scraped from Finviz.

### How rank deltas work

For each lookback window (7d, 14d, 30d), the pipeline finds the nearest available trading day within 5 calendar days of the target date, then computes:

```
rank_delta = rank_on_prior_date - rank_today
```

A **positive delta means improvement** — e.g., was rank 18 seven days ago, now rank 12 → delta = +6. Negative = fell in the ranking. Delta columns remain NaN until enough history exists.

### Momentum score (0.0 – 1.0)

The momentum score is a composite breadth metric that answers: *how strong is this group across all timeframes simultaneously?*

For each of the 7 performance metrics, the group's rank is converted to a percentile:

```
percentile = (n - rank) / (n - 1)
```

where `n` = number of groups with non-null data. This gives 1.0 for rank 1 (best) and 0.0 for rank n (worst). The momentum score is the average of all 7 percentiles.

A score of **0.87** means the group is in roughly the 87th percentile on average across all timeframes. A score of **0.24** means it's near the bottom across the board. All-NaN columns (e.g. `perf_day` when only one day of data exists) are excluded from the average.

---

## GitHub Actions

The workflow in `.github/workflows/collect.yml` runs automatically on weekdays at 22:00 UTC (approximately 6 PM Eastern), collects a snapshot, computes deltas, and commits the updated CSVs back to the repository.

You can also trigger it manually from the GitHub Actions tab using "workflow_dispatch".
