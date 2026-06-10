# CLAUDE.md

## Project purpose

Finviz Groups Tracker — daily scraper and analysis pipeline for Finviz sector and industry group performance data. Uses Playwright (headless Chromium) because Finviz blocks plain HTTP requests. Data is stored in append-only CSVs and processed into rank/delta artifacts.

The core idea: track *changes* in sector/industry rankings over time (7d/14d/30d lookbacks) to identify where capital is rotating. See `SPEC.md` for full design rationale.

---

## Quick start

```bash
# One-time setup
pip install -r requirements.txt
playwright install chromium

# Daily manual run
python scripts/collect.py          # ~2-4 min; appends to data/*/snapshots.csv
python scripts/compute_deltas.py   # ~5 sec; appends to data/*/deltas.csv

# Start dashboard locally
streamlit run dashboard/app.py

# Check data coverage
python scripts/backfill.py --status

# Export to SQLite + Parquet (local only, not committed)
python scripts/export_db.py
```

---

## Key scripts

| Script | What it does | Approx tokens |
|--------|-------------|----------------|
| `scripts/collect.py` | Playwright scraper; appends to snapshot CSVs; deduplicates on `(date, name)` | ~200–250 |
| `scripts/compute_deltas.py` | Computes ranks and 7d/14d/30d deltas; appends to delta CSVs. Accepts `--date YYYY-MM-DD` | ~300–400 |
| `scripts/export_db.py` | Exports CSVs → SQLite (`finviz_groups.db`) + Parquet in `./exports/` (not committed) | ~150 |
| `scripts/backfill.py` | Shows current date coverage; prints manual backfill instructions. Accepts `--status` | ~50 |
| `dashboard/app.py` | Streamlit dashboard: Snapshot, Top Movers, Time Series, Momentum tabs | ~100 |

> Token estimates are rough input-only counts for the script files themselves. Actual session costs depend on how much data context you load. Use `/context` to monitor live usage.

---

## Data directory structure

```
data/
  sectors/
    snapshots.csv    # append-only; one row per (date, sector)   ~11 rows/day
    deltas.csv       # append-only; one row per (date, sector)   ~11 rows/day
  industries/
    snapshots.csv    # append-only; one row per (date, industry) ~150 rows/day
    deltas.csv       # append-only; one row per (date, industry) ~150 rows/day
```

### snapshots.csv columns
`date, collected_at, group_type, name, stocks, market_cap, pe, fwd_pe, perf_day, perf_week, perf_month, perf_quarter, perf_half, perf_year, perf_ytd, avg_volume, rel_volume, change`

- `perf_*` values are raw percentages (e.g., `2.34` = +2.34%)
- `market_cap` is in billions (e.g., `1.23` = $1.23B)
- `avg_volume` is in raw units (e.g., `1230000`)
- Null values stored as empty string in CSV

### deltas.csv columns
`date, name, rank_week, rank_month, rank_quarter, rank_half, rank_year, rank_ytd, rank_week_delta_7d, rank_week_delta_14d, rank_week_delta_30d, rank_month_delta_7d, rank_month_delta_14d, rank_month_delta_30d, rank_ytd_delta_7d, rank_ytd_delta_14d, rank_ytd_delta_30d, perf_week_delta_7d, perf_week_delta_14d, perf_week_delta_30d, perf_month_delta_7d, perf_ytd_delta_7d, perf_ytd_delta_30d, momentum_score`

- `rank_*` values: rank 1 = best performer. Derived from `perf_*` values, never scraped.
- `rank_*_delta_*d`: positive = improved (rose in ranking). E.g., `+6` means 6 spots better than N days ago.
- `momentum_score`: 0–1 float; average percentile rank across all 7 perf timeframes. Higher = stronger broad momentum.
- Delta columns are `NaN` until enough history exists (e.g., 30d deltas need 30+ days of data).

---

## Common workflows

### Run manual backfill (first week probing)
```bash
# Run at multiple times on the same day to find when Finviz updates
python scripts/collect.py   # run at 10am, 1pm, 4pm, 5pm ET and compare collected_at vs values
```

### View top movers today
```python
import pandas as pd
df = pd.read_csv('data/industries/deltas.csv')
latest = df[df['date'] == df['date'].max()]
print(latest.nlargest(10, 'rank_ytd_delta_7d')[['name', 'rank_ytd', 'rank_ytd_delta_7d', 'momentum_score']])
```

### Reload dashboard after data update
Dashboard auto-reloads when CSV files change. Just refresh the browser.

### Export for analysis in Excel/SQL
```bash
python scripts/export_db.py
# Creates: finviz_groups.db, exports/sectors_snapshots.parquet, etc.
```

---

## Playwright / Finviz notes

> Verified against live Finviz on 2026-06-09.

- **Cannot run in Claude Code cloud** — Playwright CDN is blocked. Run `collect.py` locally or via GitHub Actions only. Use an environment with unrestricted outbound network for cloud testing.
- Finviz blocks plain HTTP — Playwright (headless Chromium) is required.
- CSS selector: **`.groups_table`** (not `.table-groups` — verified live).
- `wait_until="domcontentloaded"` — analytics scripts block the `load` event; domcontentloaded works fine.
- `ignore_https_errors=True` — needed for TLS-intercepting proxy in cloud envs; harmless in GitHub Actions.
- `perf_day` is sourced from Finviz's `Change` column (they're identical; no separate Perf Day column).
- `rel_volume` is always NaN — not served for this custom group URL. Expected.
- Retry logic: 3 attempts, 30s / 60s / 120s backoff. Set `COLLECT_RETRY_DELAY=0` env var to skip waits during debugging.
- Finviz URL pattern: `https://finviz.com/groups?g={sector|industry}&v=152&o=name&c=0,1,2,3,4,5,15,16,17,18,19,20,22,24,25,26`

---

## Automation

- GitHub Actions runs weekdays at **22:00 UTC** (5–6pm ET depending on DST).
- Workflow: `.github/workflows/collect.yml`
- Trigger: `workflow_dispatch` also available for manual runs.
- On failure: GitHub emails automatically. Retry 3x before failing.
- Gaps in data: compute_deltas.py uses nearest available date for lookbacks, so one missed day doesn't break 7d/14d/30d deltas.

---

## Session continuity (Claude Code web)

> These are instructions for future Claude instances, not the user. The user runs Claude Code on the web (code.claude.com), not the CLI.

- **Starting a session**: This `CLAUDE.md` auto-loads at session start. Also read `.claude/session-notes.md` immediately — it has the last session's findings, blockers, and next steps. Start the session by summarizing what's in the notes so the user knows you're oriented.
- **Sync first**: Run `git fetch origin && git log --oneline origin/claude/elegant-babbage-hlxnfy -5` before doing anything else — GitHub Actions may have pushed data overnight, and you need the latest base before branching or editing. See `.claude/rules/branch-commit-discipline.md` for the full session-start checklist.
- **Ending a session**: Before the user closes, update `.claude/session-notes.md` with: what was done, what was discovered, any blockers, and the prioritized next steps. Be specific — vague notes are useless next session.
- **Work log**: Update `.claude/WORK_LOG.md` with any milestones hit (first successful scrape, first week of data, dashboard features added).
- **Cannot run collect.py here**: The Claude Code cloud environment blocks Playwright's CDN and outbound access to finviz.com. `collect.py` must run **locally** on the user's machine or via **GitHub Actions**. Do not attempt `playwright install` or `python scripts/collect.py` in a cloud session — it will fail.
- **Subagents for analysis**: Use subagents (Agent tool) for exploratory pandas/data work to avoid bloating the main context window.
- **Context pressure**: Use `/compact` when nearing limits. Prioritize keeping SPEC.md decisions and script logic in context; data rows are expendable.

---

## Important notes

- Playwright must be installed with `playwright install chromium` (or `playwright install chromium --with-deps` in CI).
- The `exports/` directory and `*.db` / `*.parquet` files are gitignored.
- `.claude/session-notes.md`, `.claude/WORK_LOG.md`, and `.claude/SPRINT.md` are tracked in Git (not gitignored) — cloud containers are ephemeral.
- `.claude/settings.json` pre-approves edits to those three session files so Claude never prompts the user for permission when updating them. Rules files (`.claude/rules/`) remain protected and will still prompt.
- `.claude/rules/` IS committed — see `.claude/rules/README.md` for an index of all rules files and when to consult each.
- All Python scripts handle empty CSVs (headers-only) gracefully without crashing.
