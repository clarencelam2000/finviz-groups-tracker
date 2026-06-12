# Finviz Groups Tracker

Daily tracker for Finviz sector and industry group performance. Scrapes the Finviz Groups page using Playwright (headless Chromium), stores raw performance snapshots in append-only CSVs, computes rank and delta artifacts for trend analysis, and generates nightly AI market briefings via Gemini.

## What it does

- Fetches sector and industry performance data from Finviz daily (weekdays at 22:00 UTC via GitHub Actions)
- Stores raw snapshots in `data/sectors/snapshots.csv` and `data/industries/snapshots.csv`
- Computes rankings, rank changes over 7/14/30-day lookback windows, and a momentum score
- Generates a nightly AI analysis (market briefing, rotation phase signal, sector watchlist) via Gemini and commits it to `data/ai/YYYY-MM-DD.json`
- Logs every workflow run with field-level detail to `data/ai_run_log.jsonl` and `data/fetch_log.csv`
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

This fetches current sector and industry data from Finviz and appends it to the snapshot CSVs. The script is idempotent — running it multiple times on the same day overwrites rather than duplicates (last-write-wins).

### 3. Compute deltas

```bash
python scripts/compute_deltas.py
```

Reads the snapshot CSVs and appends rank/delta rows to the deltas CSVs.

### 4. Generate AI analysis (optional)

```bash
GEMINI_API_KEY=your_key python scripts/generate_ai.py
```

Calls Gemini to produce a daily briefing, rotation phase signal, and sector watchlist. Output is written to `data/ai/YYYY-MM-DD.json`. Re-running on the same day fills in any fields that failed in a previous partial run (incremental retry). Exits silently if no API key is set.

### 5. Launch the dashboard

```bash
streamlit run dashboard/app.py
```

### 6. Export to SQLite / Parquet (optional)

```bash
python scripts/export_db.py
```

Outputs are written to `./exports/` (not committed to Git).

## Data structure

```
data/
  sectors/
    snapshots.csv      # raw daily snapshots, one row per (date, sector)
    deltas.csv         # computed ranks and deltas, one row per (date, sector)
  industries/
    snapshots.csv      # same structure, for industries
    deltas.csv
  ai/
    YYYY-MM-DD.json    # nightly AI analysis output (one file per trading day)
  fetch_log.csv        # workflow run history: outcome, row counts, AI status
  ai_run_log.jsonl     # structured per-run AI generation log (append-only)
```

### Snapshot columns

`date, collected_at, group_type, name, stocks, market_cap, pe, fwd_pe, perf_day, perf_week, perf_month, perf_quarter, perf_half, perf_year, perf_ytd, avg_volume, rel_volume, change`

### Delta columns

`date, name, rank_week, rank_month, rank_quarter, rank_half, rank_year, rank_ytd` plus rank deltas and perf deltas for 7d/14d/30d windows, `momentum_score`, and `rank_agreement`.

### fetch_log.csv columns

`timestamp, run_date, trigger, run_id, outcome, sectors_rows, industries_rows, step_failed, ai_outcome, ai_fields_missing`

- `ai_outcome`: `complete` / `partial` / `skipped` / `no_key` / `no_data` / `failed`
- `ai_fields_missing`: comma-separated list of fields that errored or had no snapshot data

### AI output JSON structure

```json
{
  "date": "2026-06-11",
  "generated_at": "2026-06-11T22:05:00Z",
  "model": "gemini-flash-latest",
  "sectors": {
    "briefing": "...",
    "rotation_phase": { "label": "Defensive", "reasoning": "..." },
    "watchlist": [ { "name": "...", "thesis": "..." } ]
  },
  "industries": {
    "briefing": "..."
  }
}
```

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

**Today** — All sectors or industries as color-coded cards, sorted by Week % by default. Use the sort dropdown to switch between Week / YTD / Month / Qtr / 6-Month / 1-Year / Day. Each card shows the group's 6-Month rank badge (rank 1 = strongest 6-month performer), its name, and two secondary metrics, with the selected metric as the big number on the right. Green = positive, red = negative. Below the cards, a Pipeline section shows the last 5 workflow run outcomes including AI generation status (◆ green = complete, amber = partial, grey = skipped).

**Movers** — The biggest rank climbers and fallers over 7 / 14 / 30 days. A "data accumulating" placeholder is shown until enough history exists (7-day deltas arrive ~7 trading days after first collection). Each row shows how many ranking spots the group gained or lost. Green left border = gainer, red = loser.

**Momentum** — A composite breadth leaderboard sorted by `momentum_score`. Shows which groups are consistently strong (or weak) across all 7 performance timeframes at once, not just one hot streak. Includes a mini progress bar. Works from day one (does not require delta history).

**Strength** — Two sub-views: Sustained Strength (top-N across all three medium-term timeframes: month / quarter / half-year simultaneously) and All Green (all perf timeframes positive, shown as an emoji dot matrix). Uses `rank_agreement` to measure multi-timeframe consensus.

**AI** — Nightly AI analysis from Gemini: rotation phase classification (Early / Mid / Late Cycle / Defensive), top-3 sector watchlist with thesis, and a 3-paragraph market briefing for both sectors and industries. Requires `GEMINI_API_KEY` in GitHub Actions secrets to generate. The dashboard reads pre-committed JSON — no LLM calls at runtime.

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

### rank_agreement (0.0 – 1.0)

Measures how consistently the medium-term timeframes (month, quarter, half-year) agree on a group's standing. Computed as `1 - (std of percentile ranks / max_possible_std)`. A score of 1.0 means all three timeframes rank the group identically; 0.0 means maximum disagreement. Requires all three columns to be non-null.

---

## GitHub Actions

The workflow in `.github/workflows/collect.yml` runs automatically on weekdays at 22:00 UTC (approximately 6 PM Eastern), collects a snapshot, computes deltas, generates AI analysis (if `GEMINI_API_KEY` secret is configured), and commits the updated data back to the repository.

You can also trigger it manually from the GitHub Actions tab using "workflow_dispatch".

### Workflow monitoring

Every run appends a row to `data/fetch_log.csv` with:
- `outcome`: `success` / `failure`
- `step_failed`: which step(s) failed (collect / verify / deltas)
- `ai_outcome`: AI generation result (`complete` / `partial` / `skipped` / `no_key`)
- `ai_fields_missing`: which AI fields failed or had no data

Every `generate_ai.py` execution also appends a structured JSON entry to `data/ai_run_log.jsonl` with per-field outcomes, per-field wall time, rate-limit hit count, and full error text. This is useful for diagnosing partial AI runs (e.g., 429 rate-limit mid-run).

### Partial AI completion and retry

If a run is interrupted (e.g., 429 rate-limit) after generating some but not all AI fields, the output JSON is written with the partial content. On the next run, `generate_ai.py` detects the incomplete file, logs which fields are missing, and regenerates only those — preserving what already succeeded. A file is considered complete only when all four expected fields are present and non-empty.

### Setting up AI generation

1. Go to repo **Settings → Secrets and variables → Actions → New repository secret**
2. Name: `GEMINI_API_KEY`, Value: your Gemini API key (free tier works — 5 req/min)
3. The next scheduled cron will generate `data/ai/YYYY-MM-DD.json` automatically

