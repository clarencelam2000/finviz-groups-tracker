# CLAUDE.md

## Project purpose

Finviz Groups Tracker — daily scraper and analysis pipeline for Finviz sector and industry group performance data. Uses Playwright (headless Chromium) because Finviz blocks plain HTTP requests. Data is stored in append-only CSVs and processed into rank/delta artifacts.

The core idea: track *changes* in sector/industry rankings over time (5/10/20/50 trading-day lookbacks) to identify where capital is rotating. See `INITIAL_SPEC.md` for full design rationale.

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
| `scripts/compute_deltas.py` | Computes ranks, trading-day deltas (5/10/20/50), and momentum variants; appends to delta CSVs. Accepts `--date YYYY-MM-DD` | ~300–400 |
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

> The schema is generated from `scripts/delta_config.py` (`delta_columns()`) — the single
> source of truth. `compute_deltas.py`, `export_db.py`, and `dashboard/app.py` all import it.
> Lookback windows are **trading sessions** `[5, 10, 20, 50]`, not calendar days.

`date, name, rank_day, rank_week, rank_month, rank_quarter, rank_half, rank_year, rank_ytd`,
then for each window `W` in `5/10/20/50`: `rank_week_delta_Wd, rank_month_delta_Wd, rank_ytd_delta_Wd, perf_week_delta_Wd, perf_month_delta_Wd, perf_ytd_delta_Wd`,
then the momentum columns: `momentum_score, momentum_confirmed, momentum_weighted_mid, momentum_weighted_fast, momentum_accel, regime_short_long, rank_trend_slope, rank_agreement`.

- `rank_*` values: rank 1 = best performer. Derived from `perf_*` values, never scraped.
- `rank_*_delta_Wd`: positive = improved (rose in ranking). E.g., `+6` means 6 spots better than W trading sessions ago.
- `momentum_score`: 0–1 float; average percentile rank across all 7 perf timeframes. Higher = stronger broad momentum.
- `momentum_confirmed`: `momentum_score × rank_agreement` (strength gated by cross-timeframe consistency).
- `momentum_weighted_mid` / `_fast`: percentile means weighted toward 1mo/3mo / day-week respectively.
- `momentum_accel`: change in `momentum_score` over `ACCEL_WINDOW` (10) sessions; positive = building.
- `regime_short_long`: short- minus long-horizon percentile (range ~[-1,1]); positive = emerging leader, negative = fading. Short bucket: `perf_week + perf_month`. Long bucket: `perf_quarter + perf_half + perf_year`. Configured in `scripts/delta_config.py` as `REGIME_SHORT` / `REGIME_LONG`.
- `rank_trend_slope`: negated least-squares slope of `rank_ytd` over the trailing window; positive = improving.
- Delta/momentum columns are `NaN` until enough history exists (e.g., 50d deltas need 50+ sessions; accel needs 10).

### PWA display thresholds (in `docs/index.html` near top of `<script>`)

These constants gate visual indicators in the PWA. Edit them directly in `index.html` — they are not derived from the CSV pipeline.

| Constant | Default | Controls |
|----------|---------|---------|
| `REGIME_THRESHOLD` | `0.15` | Boundary between Emerging / Established / Fading buckets in Rotation view. Also the card color cutoff — must stay consistent (uses `REGIME_THRESHOLD` in both places). |
| `ACCEL_STRONG` | `0.08` | `momentum_accel` threshold for double-arrow (▲▲/▼▼) badge on Momentum cards. |
| `ACCEL_SLIGHT` | `0.02` | `momentum_accel` threshold for single-arrow (▲/▼) badge. Within ±`ACCEL_SLIGHT` = no badge. |
| `SLOPE_STRONG` | `0.05` | `rank_trend_slope` threshold for double-arrow (↑↑/↓↓) glyph on Today cards. |
| `SLOPE_SLIGHT` | `0.01` | `rank_trend_slope` threshold for single-arrow (↑/↓) glyph. Within ±`SLOPE_SLIGHT` = `~`. |

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
print(latest.nlargest(10, 'rank_ytd_delta_5d')[['name', 'rank_ytd', 'rank_ytd_delta_5d', 'momentum_score']])
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

> Verified against live Finviz on 2026-06-16.

- **Playwright CDN works in Claude Code cloud** — Chromium downloads fine (~175MB). `playwright install chromium --with-deps` succeeds in the cloud container (verified 2026-06-16).
- **collect.py still cannot scrape Finviz from Claude Code cloud** — but the reason is Cloudflare bot detection, NOT a network block. Our outbound IP is on Google Cloud (AS396982, `136.113.40.206`); Cloudflare returns HTTP 403 with `cf-mitigated: challenge` and serves a Turnstile JS challenge that headless Chromium fails because `navigator.webdriver=true` is detectable. GitHub Actions runs on Microsoft Azure IPs which Cloudflare treats differently (lower bot-score baseline). Run `collect.py` locally or via GitHub Actions.
- **compute_deltas.py, export_db.py, dashboard, and tests all run fine in cloud** — no Finviz network dependency.
- Finviz blocks plain HTTP — Playwright (headless Chromium) is required.
- CSS selector: **`.groups_table`** (not `.table-groups` — verified live).
- `wait_until="domcontentloaded"` — analytics scripts block the `load` event; domcontentloaded works fine.
- `ignore_https_errors=True` — needed for TLS-intercepting proxy in cloud envs; harmless in GitHub Actions.
- `perf_day` is sourced from Finviz's `Change` column (they're identical; no separate Perf Day column).
- `rel_volume` is always NaN — not served for this custom group URL. Expected.
- Retry logic: 3 attempts, 30s / 60s / 120s backoff. Set `COLLECT_RETRY_DELAY=0` env var to skip waits during debugging.
- Finviz URL pattern: `https://finviz.com/groups?g={sector|industry}&v=152&o=name&c=0,1,2,3,4,5,15,16,17,18,19,20,22,24,25,26`

---

## What Playwright in cloud unlocks (verified 2026-06-16)

Playwright + Chromium install and run correctly in cloud sessions. This opens up capabilities that didn't exist before:

### PWA functional testing (`docs/index.html`)
The PWA fetches CSVs from `raw.githubusercontent.com`. Playwright can **intercept those requests** and return local fixture CSV data, so we can test the full UI without deploying to GitHub Pages and without live data:

```python
# Pattern: serve the PWA locally, intercept GitHub raw CSV fetches
import subprocess, time
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    server = subprocess.Popen(['python3', '-m', 'http.server', '8080', '--directory', 'docs'])
    time.sleep(1)
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    # Intercept CSV fetches and return local fixture data
    page.route('**/raw.githubusercontent.com/**snapshots.csv', lambda r: r.fulfill(
        body=open('tests/fixtures/sectors_snapshots.csv').read(), content_type='text/plain'
    ))
    page.route('**/raw.githubusercontent.com/**deltas.csv', lambda r: r.fulfill(
        body=open('tests/fixtures/sectors_deltas.csv').read(), content_type='text/plain'
    ))

    page.goto('http://localhost:8080/', wait_until='networkidle')
    # Now assert on rendered cards, tab switching, sort behavior, etc.
    server.terminate()
```

What this lets us test: tab switching, card rendering, sort/filter, movers gainers/losers, momentum scores, empty-data placeholders, pull-to-refresh state, search filtering — all of it, headlessly, in cloud.

### Streamlit dashboard functional testing (`dashboard/app.py`)
The dashboard reads local CSV files directly, so no interception needed:

```python
# Run streamlit, then drive with Playwright
subprocess.Popen(['streamlit', 'run', 'dashboard/app.py', '--server.headless', 'true', '--server.port', '8501'])
time.sleep(3)
page.goto('http://localhost:8501/')
# Assert on tab content, chart presence, data table rows, etc.
```

### Scraping code development
We can write, iterate, and debug `collect.py` scraping logic (selectors, parsing, retry behavior) against non-Cloudflare URLs without needing a local machine or burning GitHub Actions runs. Only the final Finviz target requires GitHub Actions due to Cloudflare.

### Installing Playwright — on demand, not in requirements
Do **not** add `playwright install chromium` to the default setup. It's 175MB and only needed for testing/dev tasks. Install it in-session when the task calls for it:
```bash
pip install playwright
python3 -m playwright install chromium --with-deps
```
There is no need for a conditional or auto-detection — just run it when you need it.

---

## Automation

- GitHub Actions runs **weekdays only**, three times a day: `13:49`, `14:51`, and `19:48` UTC
  (~9:49am / 10:51am / 3:48pm ET in summer; one hour earlier in ET during winter — GitHub cron
  is fixed-UTC and cannot follow DST). The last run is the EOD snapshot just before the close.
- **No weekend or holiday dates.** Markets are closed on weekends and NYSE holidays, so such a
  scrape only re-captures the prior session's stale close. `trading_date()` in `collect.py` rolls
  any weekend, Monday-pre-open, or NYSE-holiday collection (cron drift or manual dispatch) back to
  the most recent **trading day**, so **no row is ever stamped with a weekend or holiday date**.
  The holiday list (`NYSE_HOLIDAYS` in `collect.py`) is hardcoded through 2027 — extend it for
  future years; a year not in the table falls back to weekend-only handling.
- Workflow: `.github/workflows/collect.yml`
- Trigger: `workflow_dispatch` also available for manual runs.
- On failure: GitHub emails automatically. Retry 3x before failing.
- `collect.py` and `compute_deltas.py` are **last-write-wins** per `date`: a later run on the same
  trading day evicts and rewrites that date's snapshot *and* delta rows, so the EOD run's ranks win
  over an earlier intraday run's.
- Gaps in data: compute_deltas.py counts trading sessions by position (`find_trading_date_back`), so missing/holiday days don't break the 5/10/20/50-session deltas.

### Cutting a release ("What's New") — 3 steps, always together

The PWA's **What's New** hub reads `docs/releases.json`. Release versions use the
`YYYY.MM.DD` convention (human-scannable, monotonic, no semver to maintain). When you
ship a user-facing change, do **all three** of these in the same PR:

1. **Prepend** a new entry to `releases.json` `releases[]` (newest-first): `version`
   (`YYYY.MM.DD`), `date`, `title`, `tag` (`feature|fix|data|improvement`), optional
   `tab` (deep-links the entry to a tab), and a short user-facing `notes[]`.
2. **Update** the top-level `current` to the new `version` (this drives the unseen-update
   dot). `tests/test_guide_releases.py` asserts `current === releases[0].version`.
3. **Bump** `CACHE` in `docs/sw.js` (e.g. `finviz-v10` → `v11`) so the new shell +
   `releases.json` aren't served from a stale cache.

> The in-app **Guide** glossary copy lives in the `GUIDE` constant in `docs/index.html`,
> copied **verbatim** from the User one-liners in `knowledge/moaty-metrics.md`. The legend
> reads the live threshold constants (`REGIME_THRESHOLD`, `ACCEL_*`, `SLOPE_*`) so it can't
> drift. If you add a metric, add its `GUIDE` entry too — the anti-drift test enforces that
> every "why this matters" link targets a real `GUIDE` id.

## Session continuity (Claude Code web)

> These are instructions for future Claude instances, not the user. The user runs Claude Code on the web (code.claude.com), not the CLI.

- **Starting a session**: This `CLAUDE.md` auto-loads at session start. Also read `.session/session-notes.md` immediately — it has the last session's findings, blockers, and next steps. Start the session by summarizing what's in the notes so the user knows you're oriented.
- **Sync first**: Run `git fetch origin && git log --oneline origin/claude/elegant-babbage-hlxnfy -5` before doing anything else — GitHub Actions may have pushed data overnight, and you need the latest base before branching or editing. See `.claude/rules/branch-commit-discipline.md` for the full session-start checklist.
- **Ending a session**: Before the user closes, update `.session/session-notes.md` with: what was done, what was discovered, any blockers, and the prioritized next steps. Be specific — vague notes are useless next session.
- **Work log**: Update `.session/WORK_LOG.md` with any milestones hit (first successful scrape, first week of data, dashboard features added).
- **Cannot run collect.py here**: Playwright installs fine in cloud, but Cloudflare blocks headless Chromium on Google Cloud IPs (AS396982). `collect.py` must run **locally** or via **GitHub Actions** (Azure IPs pass Cloudflare). Everything else — `compute_deltas.py`, tests, dashboard, PWA functional tests — runs fine in cloud. See "What Playwright in cloud unlocks" section above.
- **Subagents for analysis**: Use subagents (Agent tool) for exploratory pandas/data work to avoid bloating the main context window.
- **Context pressure**: Use `/compact` when nearing limits. Prioritize keeping INITIAL_SPEC.md decisions and script logic in context; data rows are expendable.
- **Save research before it's lost**: If a session involved substantial research (API evaluation, debugging a non-obvious root cause, evaluating architectural trade-offs), write a summary to `knowledge/` before ending. A future Claude — or a human reading the code — should not have to rediscover it. Research logs go in `knowledge/` as free-form `.md` files; architectural decisions (and the alternatives rejected) go in `knowledge/decisions/` as ADRs. See `knowledge/README.md` for templates.

Note: there's no send_later tool in this session, so you can't auto-schedule the hourly re-check — webhooks won't tell you about CI success or merge-conflict transitions, so user will ping you if they would like me to re-check, or you can respond to any review-comment/CI-failure events as they arrive.
---

## Repository structure

| Directory | Purpose |
|-----------|---------|
| `scripts/` | Data collection and processing scripts |
| `dashboard/` | Streamlit dashboard |
| `worker/` | Cloudflare Worker (ticker lookup + cache ops) — see `worker/README.md` |
| `docs/` | PWA (GitHub Pages) — `index.html`, `sw.js`, `manifest.json` |
| `data/` | Append-only CSVs (sectors, industries) |
| `planning/` | Implementation plans and feature designs |
| `knowledge/` | Research logs, ADRs, debugging post-mortems |
| `.session/` | Session notes, sprint board, work log (committed, not gitignored) |
| `.claude/rules/` | Project rules files (branch discipline, data pipeline) |
| `.github/workflows/` | CI/CD — daily collect + compute_deltas |

> `docs/` is named per GitHub Pages convention: "Deploy from branch → /docs" only supports `/` or `/docs` as source. Do not rename it without switching to GitHub Actions deployment first.

---

## Code quality and documentation standards

### Configurable items — document everywhere they can be changed

Any constant that controls pipeline behavior (lookback windows, thresholds, model names,
window sizes, weights, etc.) **must** appear in **all three** of these places:

1. **In-code comment** on the constant itself — explain what it controls, valid range/effect,
   and any coupling constraints. Example from `scripts/delta_config.py`:
   ```python
   # ACCEL_WINDOW ideally stays equal to a value already in LOOKBACK_WINDOWS to avoid
   # a redundant compute_ranks pass. Currently equals LOOKBACK_WINDOWS[1] = 10.
   ACCEL_WINDOW = 10
   ```

2. **`README.md` § Configurable parameters** — the public-facing table anyone reads first.
   Every parameter gets a row: name, default value, what it controls, how to change it safely.

3. **`CLAUDE.md`** (this file) — note the constant in the relevant section (e.g., deltas.csv
   columns, momentum score formula) so future Claude instances see it in their initial context.

**Rule:** If you add or rename a configurable constant, update all three before committing.
If a constant is only used internally and has no meaningful user-facing effect, it still needs
an in-code comment but may skip the README table.

---

### Code comments — be liberal; tie TODOs to sprint tasks

The general Claude Code rule ("default to no comments") is **relaxed for this project** in
three specific situations:

**1. Configurable constants** — always comment (see above).

**2. Non-obvious behavior and known gotchas** — comment whenever a reader could waste time
   debugging something that was already investigated. Examples from this codebase:
   - `export_db.load_csv` silently ignores missing columns (documented in-code + README)
   - `ACCEL_WINDOW` coupling to `LOOKBACK_WINDOWS` (documented in delta_config.py)
   - Playwright Chromium install works in cloud but Finviz scraping is blocked by Cloudflare
     (documented in CLAUDE.md Playwright section)

   Format: one-line comment or a short NOTE/WARNING block. Keep it factual — what happens,
   not a re-statement of the code.

**3. TODOs — always reference a SPRINT.md task ID or a GitHub issue**

   Never write a bare `# TODO: fix this`. Always tie it to something trackable:
   ```python
   # TODO(LB-FF1): derive window buttons from CSV header; see SPRINT.md § LB-FF1
   # TODO(#123): handle the case where prior_date == target_date for same-day reruns
   ```
   If no SPRINT task exists yet, create one in `.session/SPRINT.md` first, then reference it.
   This ensures every known gap is visible in the sprint board and never silently buried.

**In documentation** (CLAUDE.md, README, data-pipeline.md): if a section describes behavior
that has a known limitation or a planned improvement, add a `> **Note:**` or `> **Known gap:**`
callout. See the export_db entry in README § Delta columns for an example.

You must include the necessary and sufficient info for anyone else on the team to pick it up later.

---



- Playwright must be installed with `playwright install chromium` (or `playwright install chromium --with-deps` in CI).
- The `exports/` directory and `*.db` / `*.parquet` files are gitignored.
- `.session/session-notes.md`, `.session/WORK_LOG.md`, and `.session/SPRINT.md` are tracked in Git (not gitignored) — cloud containers are ephemeral. They live in `.session/` (not `.claude/`) so Claude can edit them without permission prompts.
- `.claude/rules/` IS committed — see `.claude/rules/README.md` for an index of all rules files and when to consult each.
- All Python scripts handle empty CSVs (headers-only) gracefully without crashing.
