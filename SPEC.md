# Finviz Groups Tracker — Project Specification

## 1. Overview

**Goal**: Build a data pipeline that snapshots Finviz's Groups page (sectors and industries) daily after market close, stores the raw performance data in a Git-committed append-only CSV, and computes derived delta/ranking artifacts to surface where money is flowing across sectors and industries over time.

**Core hypothesis**: A sector or industry steadily climbing in relative performance rank across multiple timeframes (e.g., Software ranked 18th by YTD 30 days ago, now ranked 12th) is a signal of capital rotation into that group. The inverse signals outflows.

**What existing tools don't do**: Finviz, Deepvue, and similar tools show single-point-in-time rankings. This project captures the time series of those rankings so you can track rank velocity and acceleration, not just position.

---

## 2. Data Source

**Source**: Finviz Groups page (`finviz.com/groups`)

**Group types**: Two separate datasets:
- **Sectors** — ~11 groups (e.g., Technology, Energy, Healthcare)
- **Industries** — ~150+ groups (e.g., Software, Oil & Gas E&P, Biotechnology)

Finviz also exposes sub-industries, but that is out of scope for now.

### Finviz URL Structure

| Parameter | Meaning |
|-----------|---------|
| `g=sector` / `g=industry` | Group type |
| `v=110` | Overview view (fundamental columns) |
| `v=140` | Performance view |
| `v=152` | Custom column view |
| `o=name` / `o=-perf26w` | Sort column (prefix `-` = descending) |
| `st=d1` | Stock type filter (all stocks) |
| `c=0,1,2,...` | Custom column IDs |

### Columns to Capture (All Available)

All columns exposed by Finviz Groups across views — captured in one combined snapshot per group type per day:

| Column | Description |
|--------|-------------|
| `name` | Industry or sector name |
| `stocks` | Number of stocks in group |
| `market_cap` | Total market cap |
| `pe` | P/E ratio |
| `fwd_pe` | Forward P/E ratio |
| `perf_day` | % change today |
| `perf_week` | % change trailing 5 trading days |
| `perf_month` | % change trailing ~21 trading days |
| `perf_quarter` | % change trailing ~63 trading days |
| `perf_half` | % change trailing ~126 trading days |
| `perf_year` | % change trailing ~252 trading days |
| `perf_ytd` | % change since Jan 1 |
| `avg_volume` | Average daily volume |
| `rel_volume` | Relative volume (vs average) |
| `change` | Current day's % change (same as perf_day during market hours) |
| `volume` | Today's volume |

> **Note**: All `perf_*` columns are rolling trailing windows, not calendar-fixed periods. `perf_week` captured on Monday and on Friday refer to different 5-day windows. This is a feature (it's always current) but affects interpretation of deltas.

---

## 3. Data Access Strategy

**Status**: TBD — to be finalized before implementation starts.

### Option A — Finviz Elite (Recommended)
- Elite accounts can export tables as CSV directly.
- Clean, stable, less likely to break.
- Avoids ToS scraping concerns.
- Cost: ~$40/month.

### Option B — Headless Browser (Playwright)
- Renders the page as a real browser; captures the rendered HTML table.
- No Elite subscription needed.
- Gray area with Finviz ToS; may require User-Agent rotation, rate limiting, and periodic maintenance if Finviz changes page structure.
- Preferred if Elite is not available.

### First-Week Probe
Before committing to a schedule, run collection at **multiple intraday times** (e.g., 10am, 1pm, 4pm, 5pm, 6pm ET) for the first ~5 trading days to determine:
- When does Finviz update its performance data for the day?
- Is data available intraday or only after close?
- Are there transient data quality issues near open/close?

This informs the final daily schedule for the GitHub Actions cron.

---

## 4. Storage Architecture

### Principles
- **Source of truth**: Human-readable, Git-diffable append-only CSV files, committed to the repository.
- **Derived artifacts**: SQLite and Parquet are **not** committed to Git. They are regenerated locally on demand from the master CSVs via a conversion script. Binary files in Git destroy diff history and eventually require Git LFS.
- **Delta CSVs**: Committed alongside snapshots as a convenience layer, but are fully regeneratable from the raw snapshots. They are not the source of truth.

### File Layout

```
finviz-groups-tracker/
├── data/
│   ├── sectors/
│   │   ├── snapshots.csv          # append-only; one row per sector per day
│   │   └── deltas.csv             # append-only; one row per sector per day (derived)
│   └── industries/
│       ├── snapshots.csv          # append-only; one row per industry per day
│       └── deltas.csv             # append-only; one row per industry per day (derived)
├── scripts/
│   ├── collect.py                 # scrape/fetch Finviz, append to snapshots.csv
│   ├── compute_deltas.py          # read snapshots.csv, compute/append deltas.csv
│   ├── backfill.py                # one-off manual backfill helper
│   └── export_db.py               # generate SQLite / Parquet from CSVs (not committed)
├── notebooks/
│   └── analysis.ipynb             # example queries: top movers, rank charts, momentum
├── dashboard/
│   └── app.py                     # Streamlit app for local browsing
├── .github/
│   └── workflows/
│       └── collect.yml            # GitHub Actions daily cron
├── SPEC.md
├── CLAUDE.md
└── README.md
```

---

## 5. Schema Design

### 5.1 Raw Snapshots (`snapshots.csv`)

One row per group per collection run.

```
date,collected_at,group_type,name,stocks,market_cap,pe,fwd_pe,
perf_day,perf_week,perf_month,perf_quarter,perf_half,perf_year,perf_ytd,
avg_volume,rel_volume,change,volume
```

| Column | Type | Notes |
|--------|------|-------|
| `date` | `YYYY-MM-DD` | Trading date (US ET) |
| `collected_at` | `ISO 8601 UTC` | Exact timestamp of collection |
| `group_type` | `sector` / `industry` | Redundant but useful for sanity checks |
| `name` | string | Finviz group name, normalized (trimmed, stable) |
| `stocks` | int | |
| `market_cap` | float (billions) | |
| `pe` | float | null if N/A |
| `fwd_pe` | float | null if N/A |
| `perf_day` | float | % as decimal (e.g., `2.34` not `0.0234`) |
| `perf_week` | float | |
| `perf_month` | float | |
| `perf_quarter` | float | |
| `perf_half` | float | |
| `perf_year` | float | |
| `perf_ytd` | float | |
| `avg_volume` | float | |
| `rel_volume` | float | |
| `change` | float | % |
| `volume` | int | |

**Uniqueness constraint**: `(date, name)` — one row per group per day. If collection runs multiple times in a day, the later run overwrites the earlier (or appends with a different `collected_at` — pipeline logic to handle dedup).

### 5.2 Computed Deltas (`deltas.csv`)

One row per group per day. Generated by `compute_deltas.py` after each snapshot.

**Rank computation**: Within each day's snapshot, groups are ranked by each `perf_*` metric (rank 1 = best performer). Ranks are computed separately for each metric. Rank is **not** scraped from Finviz — it is derived from the performance values.

```
date,name,
rank_week,rank_month,rank_quarter,rank_half,rank_year,rank_ytd,
rank_week_delta_7d,rank_week_delta_14d,rank_week_delta_30d,
rank_month_delta_7d,rank_month_delta_14d,rank_month_delta_30d,
rank_ytd_delta_7d,rank_ytd_delta_14d,rank_ytd_delta_30d,
perf_week_delta_7d,perf_week_delta_14d,perf_week_delta_30d,
perf_month_delta_7d,perf_ytd_delta_7d,perf_ytd_delta_30d,
momentum_score
```

**Delta sign convention**: Positive = improved rank (moved up). E.g., `rank_week_delta_7d = +6` means ranked 6 spots higher by `perf_week` than 7 days ago.

**Composite Momentum Score**: Computed as the average percentile rank across all 7 perf timeframes on that date. A score of 0.90 means the group is in the 90th percentile across all timeframes on average. This collapses multi-dimensional rank into a single signal.

```
momentum_score = mean(percentile_rank(perf_day), percentile_rank(perf_week), ..., percentile_rank(perf_ytd))
```

Where `percentile_rank(x)` = `(rank_among_peers - 1) / (total_peers - 1)` normalized to [0, 1].

**Null handling**: Delta columns are null until enough history exists (e.g., `rank_week_delta_30d` is null for the first 30 calendar days of data).

---

## 6. Pipeline Architecture

### Step-by-step per run

```
1. collect.py
   ├── Fetch Finviz Groups page for sectors (all columns)
   ├── Fetch Finviz Groups page for industries (all columns)
   ├── Parse and normalize data
   ├── Validate: expected row count, no blank name fields, key metrics non-null
   └── Append new rows to data/{sectors,industries}/snapshots.csv

2. compute_deltas.py
   ├── Load snapshots.csv
   ├── Compute ranks per metric for today's date
   ├── Look up snapshots from 7, 14, 30 calendar days prior (nearest available trading day)
   ├── Compute rank deltas and perf % point deltas
   ├── Compute momentum_score
   └── Append today's rows to data/{sectors,industries}/deltas.csv

3. Git commit and push
   └── Commit message: "data: snapshot YYYY-MM-DD"
```

### Idempotency
If a run executes twice for the same date, `collect.py` checks whether a row for that `(date, name)` already exists before appending. Duplicate detection uses the `date` column only (not `collected_at`), so re-runs after a partial failure safely overwrite.

---

## 7. Automation (GitHub Actions)

### Production schedule
- **Cadence**: Monday–Friday only
- **Time**: 22:00 UTC (5pm ET / 6pm ET depending on DST) — after US market close and after Finviz has updated
- **Holiday handling**: Run regardless; if market was closed, Finviz data is unchanged from prior day. Pipeline appends the row; delta computation handles the flat movement naturally.

### Retry logic
- On failure, retry up to **3 times** with exponential backoff: 30s, 60s, 120s.
- On all retries exhausted: mark the GitHub Actions run as failed.
- GitHub Actions sends a failure email automatically — no additional notification setup needed.
- Gaps in data are logged. Delta computation uses "nearest available trading day" lookups for the lookback windows, so a single missed day does not break the 7d/14d/30d deltas.

### Workflow file
```yaml
# .github/workflows/collect.yml
name: Daily Snapshot
on:
  schedule:
    - cron: '0 22 * * 1-5'
  workflow_dispatch:  # allows manual trigger for backfill
jobs:
  snapshot:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: pip install -r requirements.txt
      - run: python scripts/collect.py
      - run: python scripts/compute_deltas.py
      - run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/
          git commit -m "data: snapshot $(date +%Y-%m-%d)" || echo "No changes"
          git push
```

---

## 8. Manual Backfill Plan

Before automation goes live:

1. **Day 1**: Run `collect.py` manually several times during the trading day and after close to determine when Finviz data finalizes (probing the intraday update question).
2. **Days 2–5**: Continue probing at the identified update time. Also run `backfill.py` to record the initial seed data.
3. **After ~1 week**: Enable the GitHub Actions cron at the confirmed post-close time.
4. **Future task**: Research availability of historical Finviz-equivalent data (e.g., financial data vendors, Wayback Machine snapshots) to backfill months or years of history. This is tabled but the schema is designed to accept it without modification.

---

## 9. Analysis Layer

### Jupyter Notebook (`notebooks/analysis.ipynb`)
Example analyses to include:
- **Top movers**: Industries with largest `rank_ytd_delta_30d` (biggest rank climb or drop over 30 days).
- **Momentum leaderboard**: Sort by `momentum_score` for today; compare to 30 days ago.
- **Rotation heatmap**: Heatmap of `rank_week_delta_7d` across all industries over the last 60 days.
- **Individual group time series**: Plot `perf_ytd` and `rank_ytd` over all captured dates for a single industry.
- **Sector vs Industry**: Cross-reference sector momentum with constituent industry momentum.

### Streamlit Dashboard (`dashboard/app.py`)
Local-only interactive viewer:
- Date range selector
- Group type toggle (sectors / industries)
- Sortable table by any column
- Sparkline column showing rank trajectory over last 30 days
- "Top movers" panel (biggest rank gainers/losers in selected window)
- Filter by sector (so you can see all industries within, e.g., Technology)

---

## 10. Open Decisions

| Decision | Status | Notes |
|----------|--------|-------|
| Data access method | **TBD** | Finviz Elite CSV export (preferred) vs Playwright headless browser |
| Finviz update time | **TBD** | Probe during first week |
| Holiday calendar | Implementation detail | Use `pandas_market_calendars` or a static list of NYSE holidays |
| Backfill from historical source | Tabled | Research vendors after pipeline is live |
| Perf % deltas beyond 7d | Spec includes 14d and 30d for `perf_week` and `perf_ytd`; expand to all metrics if needed |

---

## 11. Non-Goals (for now)

- Real-time or intraday tracking
- Individual stock data (only group-level aggregates)
- Alerts/notifications beyond GitHub email on failure
- Public-facing dashboard (Streamlit is local-only)
- Sub-industry level data
- Any trading signal or recommendation engine
