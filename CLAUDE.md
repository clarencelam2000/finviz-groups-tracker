# CLAUDE.md

## Project purpose

Finviz Groups Tracker — daily scraper and analysis pipeline for Finviz sector and industry group performance data. Uses Playwright (headless Chromium) because Finviz blocks plain HTTP requests. Data is stored in append-only CSVs and processed into rank/delta artifacts.

## Key scripts

| Script | What it does |
|--------|-------------|
| `scripts/collect.py` | Fetches sector and industry data from Finviz using Playwright; appends new rows to snapshot CSVs. Idempotent (deduplicates on date + name). |
| `scripts/compute_deltas.py` | Reads snapshot CSVs; computes rankings and lookback deltas (7d/14d/30d); appends to delta CSVs. Accepts `--date YYYY-MM-DD`. |
| `scripts/export_db.py` | Exports all CSVs to SQLite (`finviz_groups.db`) and Parquet files in `./exports/`. |
| `scripts/backfill.py` | Shows current date coverage and instructions for manual backfill. Accepts `--status`. |
| `dashboard/app.py` | Streamlit dashboard with Snapshot, Top Movers, Time Series, and Momentum tabs. |

## Data directory structure

```
data/
  sectors/
    snapshots.csv    # append-only; one row per (date, sector)
    deltas.csv       # append-only; one row per (date, sector)
  industries/
    snapshots.csv
    deltas.csv
```

## Running a manual collection

```bash
# Install dependencies (once)
pip install -r requirements.txt
playwright install chromium

# Collect today's snapshot
python scripts/collect.py

# Compute deltas for the latest date
python scripts/compute_deltas.py

# Check coverage
python scripts/backfill.py --status
```

## Important notes

- Playwright must be installed with `playwright install chromium` (or `playwright install chromium --with-deps` in CI). The scripts will fail without it.
- The `exports/` directory and `*.db` / `*.parquet` files are gitignored.
- GitHub Actions runs the pipeline automatically on weekdays at 22:00 UTC via `.github/workflows/collect.yml`.
- All Python scripts handle empty CSVs (headers-only) gracefully without crashing.
