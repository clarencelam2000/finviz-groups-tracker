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
| `scripts/generate_ai.py` | Gemini AI analysis from latest deltas; writes `data/ai/YYYY-MM-DD.json`. Auth: Vertex express key (GOOGLE_API_KEY) > Vertex ADC > AI Studio (GEMINI_API_KEY). Supports `--preview` (no API), `--capture` (Tier-2 debug). | ~1300 |
| `scripts/export_db.py` | Exports CSVs → SQLite (`finviz_groups.db`) + Parquet in `./exports/` (not committed) | ~150 |
| `scripts/backfill.py` | Shows current date coverage; prints manual backfill instructions. Accepts `--status` | ~50 |
| `scripts/seed_taxonomy.py` | Seeds `data/finviz_sector_industry_map.{json,csv}` by parsing fasiha/finviz-git-scraper's `map-sec_all.json` (plain HTTP — no Playwright, no Cloudflare). Run once; re-run only after Finviz restructures taxonomy. Validates against snapshot CSVs automatically. | ~80 |
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
  benchmark/
    snapshots.csv    # append-only; one SPY row per trading date; raw perf_* (never spread-only)
  finviz_sector_industry_map.json  # static; sector→industry containment tree; re-seed if Finviz restructures
  finviz_sector_industry_map.csv   # flat (finviz_sector, finviz_industry) pairs; for pandas joins
```

### finviz_sector_industry_map files

Seeded by `scripts/seed_taxonomy.py` from [fasiha/finviz-git-scraper](https://github.com/fasiha/finviz-git-scraper/blob/main/map-sec_all.json) — a nightly-updated Finviz treemap archive. No Playwright or Cloudflare involved; plain HTTP from raw.githubusercontent.com.

- **Coverage:** 11 sectors, 145 industries (144 match our tracked industries; 1 extra `Infrastructure Operations` not yet in our data)
- **Accuracy:** 100% match against `data/industries/snapshots.csv` as of 2026-06-24
- **Freshness:** Re-run `seed_taxonomy.py` if Finviz restructures taxonomy (rare, ~once/year). The script cross-validates and reports any mismatches.
- **Usage:** Load with `json.loads(Path("data/finviz_sector_industry_map.json").read_text())["sectors"]` → dict of `{sector: [industry, ...]}`. Enables INS-7 sector breadth and Task 6b sidebar filter.

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
then the momentum columns: `momentum_score, momentum_confirmed, momentum_weighted_mid, momentum_weighted_fast, momentum_accel, regime_short_long, rank_trend_slope, rank_agreement`,
then the RS (relative-strength vs SPY) columns: `rs_day, rs_week, rs_month, rs_quarter, rs_half, rs_year, rs_ytd, rs_score, rs_agreement, rs_confirmed, rs_slope, rs_accel, rs_regime_short_long`,
then the RS discrete flags: `beats_benchmark_day, beats_benchmark_week, beats_benchmark_month, beats_benchmark_quarter, beats_benchmark_half, beats_benchmark_year, beats_benchmark_ytd, rs_new_high, rs_cross`.

- `rank_*` values: rank 1 = best performer. Derived from `perf_*` values, never scraped.
- `rank_*_delta_Wd`: positive = improved (rose in ranking). E.g., `+6` means 6 spots better than W trading sessions ago.
- `momentum_score`: 0–1 float; average percentile rank across 6 perf timeframes (week → YTD; day excluded as too noisy). Higher = stronger broad momentum.
- `momentum_confirmed`: `momentum_score × rank_agreement` (strength gated by cross-timeframe consistency).
- `momentum_weighted_mid` / `_fast`: percentile means weighted toward 1mo/3mo / week respectively (day excluded from both; `_fast` leans on week to catch fresh rotation).
- `momentum_accel`: change in `momentum_score` over `ACCEL_WINDOW` (10) sessions; positive = building.
- `regime_short_long`: short- minus long-horizon percentile (range ~[-1,1]); positive = emerging leader, negative = fading. Short bucket: `perf_week + perf_month`. Long bucket: `perf_quarter + perf_half + perf_year`. Configured in `scripts/delta_config.py` as `REGIME_SHORT` / `REGIME_LONG`.
- `rank_trend_slope`: negated least-squares slope of `rank_ytd` over the trailing window; positive = improving.
- `rs_day/week/month/…/ytd`: RS spread = `group_perf_X − SPY_perf_X`; positive = beating the market. NaN when `data/benchmark/snapshots.csv` has no row for that date.
- `rs_score`: 0–1; fraction of 6 timeframes (week → YTD; day excluded as too noisy) where the group's RS spread (group_perf_X − SPY_perf_X) is positive. Unlike `momentum_score` (cross-sectional peer rank), this is an absolute signal — a rising tide does not inflate it. `RS_SLOPE_COL = "rs_month"` is the canonical RS line for `rs_slope`. `RS_AGREEMENT_COLS = ["rs_month","rs_quarter","rs_half"]` drive `rs_agreement`.
- `rs_agreement`: 0–1; sign consistency of RS spreads across mo/qtr/half. Computed as |mean(sign)| where sign = +1 if rs > 0, −1 if rs < 0. 1.0 = all three same direction.
- `rs_confirmed`: `rs_score × rs_agreement` (breadth of outperformance gated by directional consistency).
- `rs_slope`: LS slope of `rs_month` over `SLOPE_WINDOW` sessions; positive = outperformance building. `RS_REGIME_SHORT/LONG` configure `rs_regime_short_long` buckets.
- `rs_accel`: change in `rs_score` over `ACCEL_WINDOW` sessions; positive = more timeframes flipping positive vs SPY.
- `rs_regime_short_long`: short-horizon RS breadth (fraction of rs_week/rs_month > 0) minus long-horizon breadth (rs_quarter/rs_half/rs_year). Range [−1, 1]; positive = emerging RS leader.
- `beats_benchmark_{day,week,month,quarter,half,year,ytd}`: 1 when `rs_X > 0`, 0 when `rs_X ≤ 0`, blank when SPY absent. `RS_BEAT_TIMEFRAMES` lists the suffixes.
- `rs_new_high`: 1 when `rs_month` equals or exceeds its trailing `RS_NEW_HIGH_WINDOW = 20` session maximum (IBD-style RS-new-high flag). NaN if < 2 sessions of overlapping data.
- `rs_cross`: 1 when `rs_month` crossed from ≤ 0 to > 0 within the last `RS_CROSS_WINDOW = 5` sessions (rotation trigger). 0 if today's RS is non-positive or group was already above 0 throughout window.
- Delta/momentum/RS columns are `NaN` until enough history exists (e.g., 50d deltas need 50+ sessions; accel/slope need 10).

### PWA display thresholds (in `docs/index.html` near top of `<script>`)

These constants gate visual indicators in the PWA. Edit them directly in `index.html` — they are not derived from the CSV pipeline.

| Constant | Default | Controls |
|----------|---------|---------|
| `REGIME_THRESHOLD` | `0.15` | Boundary between Emerging / Established / Fading buckets in Rotation view. Also the card color cutoff — must stay consistent (uses `REGIME_THRESHOLD` in both places). |
| `ACCEL_STRONG` | `0.08` | `momentum_accel` threshold for double-arrow (▲▲/▼▼) badge on Momentum cards. |
| `ACCEL_SLIGHT` | `0.02` | `momentum_accel` threshold for single-arrow (▲/▼) badge. Within ±`ACCEL_SLIGHT` = neutral `~` glyph (steady); NaN/insufficient history = dimmed `—`. |
| `SLOPE_STRONG` | `0.05` | `rank_trend_slope` threshold for double-arrow (↑↑/↓↓) glyph on Today cards. |
| `SLOPE_SLIGHT` | `0.01` | `rank_trend_slope` threshold for single-arrow (↑/↓) glyph. Within ±`SLOPE_SLIGHT` = `~`. |
| `RS_STRONG` | `2.0` | RS spread (pp vs S&P) threshold for deep-color badge in vs Market tab and Today cards. |
| `RS_SLIGHT` | `0.5` | RS spread threshold for mild-color badge. Within ±`RS_SLIGHT` = neutral chip. |

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

## ETF override layer (worker/)

ETF lookups use a curated override file (`data/etf_overrides.csv`) to correct FMP's
legal-entity classification ("Asset Management") with the actual thematic exposure.

**Source of truth:** `data/etf_overrides.csv` — columns `ticker, finviz_industry,
finviz_sector, etf_name, kind, note`. Three `kind` values:
- `thematic` — single industry (COPX→Copper, ITA→Aerospace & Defense, SMH→Semiconductors…)
- `sector` — sector only, no single industry (XLE→Energy, XLK→Technology… all 11 SPDRs)
- `diversified` — no group (SPY, QQQ, VTI, DIA, IWM; PWA shows an informational card)

**Build step:** `npm run build:taxonomy` (in `worker/`) reads both `taxonomy_map.csv`
and `etf_overrides.csv`, validates all Finviz names against live snapshot CSVs, and
emits `worker/src/taxonomy_map.json` + `worker/src/etf_overrides.json`. Exits non-zero
with a clear message on any unknown group name.

**Runtime:** `lookupEtf(symbol)` in `taxonomy.js` checks `etf_overrides.json`. Applied
in `index.js` when `isEtf: true`. Response adds `classification_source` ("etf_override"
| "fmp_taxonomy") and `etf_kind` ("thematic" | "sector" | "diversified" | null).

**Post-deploy cache bust:** existing KV entries don't have the new fields until TTL
(30d). Bust manually with `DELETE /cache?t=TICKER` for each seed ETF — see
`worker/README.md` for the one-liner.

**ADR:** `knowledge/decisions/ADR-005-etf-classification-curated-first.md`

---

## Picks pipeline (`scripts/collect_picks.py`)

Daily Stage-2 stock-picks scraper: selects leading industry groups from
`data/industries/deltas.csv`, then scrapes the individual stocks inside them from the Finviz
screener and logs them to an append-only event log. **Phase 2 of
`planning/stock-picks-from-leading-groups.md`.** Required reading before editing:
**ADR-007** (selector policy) + **ADR-008** (collection architecture) in `knowledge/decisions/`.

> Like `collect.py`, the scrape MUST run on GitHub Actions (Azure IPs) — Cloudflare blocks the
> headless screener scrape from Google Cloud IPs. `select_groups` and all row-building/pagination
> helpers are **pure and fully unit-tested in cloud** (no Finviz access).

**Key scripts/config:**
| File | Role |
|------|------|
| `scripts/collect_picks.py` | `select_groups()` (pure selector) + paginated scrape + append. Inherits `slugify_industry`/`_build_url`/`_parse_table` from `probe_picks.py`. |
| `scripts/picks_config.py` | Single source of truth: schema (`picks_columns()`, 19 `grp_*` cols) + all tunable constants. |
| `data/picks/picks.csv` | Append-only log; one row per `(date, list_category, ticker)`. Lead cols + 84 Finviz cols + 19 `grp_*`. **Offline attribution only — never fetched by the PWA.** |
| `data/picks/picks_latest.csv` | Max-date slice of `picks.csv` — **this is what the PWA fetches.** |
| `data/picks/screener_config.json` | Modular URL config (`wide` net + `button`); 84-col `c=` list. Labels stay verbatim-synced to `tests/fixtures/probe_header_84col.txt`. |
| `data/picks/finviz_industry_slugs.csv` | 144 industry→slug rows. `validated` flips to `true` the first time a group scrapes >0 rows (G4). |
| `data/picks/selector_versions.json` | Append-only registry of every selector policy; newest-first. `current` must equal `SELECTOR_VERSION` and `versions[0].version` (test-enforced; published entries immutable). |

**Selector (ADR-007, VP-locked):** four buckets filled in priority order to ≤ `DAILY_GROUP_CAP`
(20) unique groups; a group qualifying in multiple buckets is **scraped once but tagged per
bucket**. A 0-group bucket is normal (e.g. `momentum_accel` is NaN until 11 sessions) — fill from
the next priority, never error.
1. **leaders** ≤10 — 8 by sustained strength (`rank_month+rank_quarter+rank_half` asc) + 2 freshness fills (`momentum_confirmed` desc).
2. **emerging** ≤4 — `regime_short_long > 0.15` AND `rs_score > 0.5`.
3. **accel** ≤3 — `momentum_accel > 0.08` AND top-40% by `momentum_score` AND `rs_score > 0.5`.
4. **rs_new_high** ≤3 — `rs_new_high == 1` AND `rs_score ≥ 0.6` AND top-40% by `momentum_score`.

The anti-flash floor is a **cross-sectional `momentum_score` percentile** (`ANTIFLASH_PCTILE = 0.40`),
not an absolute cutoff — invariant to `PERF_RANK_METRICS` rescaling.

**`grp_*` columns (19):** each pick row snapshots the selecting group's `deltas.csv` metrics at
selection time (so Phase-4 attribution never re-derives them). Includes `grp_rank_basis`,
`grp_category_rank` (within-bucket rank among qualifying candidates, independent per category for
dedup groups), `grp_momentum_score_pctile` (the floor value actually used), and stored
rejected-alternatives (`grp_rs_confirmed`, `grp_momentum_weighted_mid`, `grp_rank_agreement`) for
head-to-head Phase-4 comparison. Renaming/removing one is one-way once data flows; **adding** one is
a two-way-door superset migration (`ensure_deltas_csv()` pattern).

**Workflow & guards:**
- `.github/workflows/collect_picks.yml` — separate workflow, own EOD cron (`8 20 * * 1-5`, ~20 min
  after `collect.yml`). `workflow_dispatch` for manual runs.
- **Shared concurrency guard (G1):** both `collect_picks.yml` AND `collect.yml` declare
  `concurrency: { group: finviz-data-commit, cancel-in-progress: false }` — a group only serializes
  workflows sharing the name, so **both files must have it.** Rebase-before-push.
- **Stale-read guard:** `collect_picks.py` asserts `deltas['date'].max() == trading_date()` before
  scraping — a too-early run is a safe no-op, never a wrong-day scrape.
- **Fetch caps:** per-group `PAGE_CAP` and **hard global `GLOBAL_FETCH_CAP = 50` pages/day** (VP-set
  2026-06-25). Scrapes in priority order (leaders first) and stops at 50. A wrong slug returns HTTP
  200 with an empty table (NOT a 404) — the scraper checks row count, not status.

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

- **Primary scheduler: the Cloudflare Worker `finviz-cron-dispatcher` (`worker-cron/`).** Its
  Cron Triggers fire **weekdays only**, three times a day: `13:49`, `14:51`, and `19:48` UTC
  (~9:49am / 10:51am / 3:48pm ET in summer; one hour earlier in ET during winter — Cloudflare
  cron is fixed-UTC and cannot follow DST). Each trigger POSTs a GitHub `workflow_dispatch` to
  launch `collect.yml` on Azure runners. The cron expressions live in `worker-cron/wrangler.toml`
  `[triggers] crons`. The last run is the EOD snapshot just before the close. **Why a separate
  scheduler:** GitHub's `schedule:` cron drifts hours and is dropped under load;
  `workflow_dispatch` is event-driven and prompt. See `planning/cloudflare-cron-scheduler.md`
  and `knowledge/decisions/` for the full rationale.
- **Backstop: one GitHub cron** (`48 19 * * 1-5`) remains in `collect.yml` as redundancy. It
  fires at the *same time* as the Cloudflare EOD trigger (not a delayed fallback — GitHub cron is
  too timing-unreliable for that). The expected double-run is harmless: last-write-wins per date.
- **No weekend or holiday dates.** Markets are closed on weekends and NYSE holidays, so such a
  scrape only re-captures the prior session's stale close. `trading_date()` in `collect.py` rolls
  any weekend, Monday-pre-open, or NYSE-holiday collection (cron drift or manual dispatch) back to
  the most recent **trading day**, so **no row is ever stamped with a weekend or holiday date**.
  The holiday list (`NYSE_HOLIDAYS` in `collect.py`) is hardcoded through 2027 — extend it for
  future years; a year not in the table falls back to weekend-only handling.
- Workflow: `.github/workflows/collect.yml`
- Trigger: `workflow_dispatch` also available for manual runs.
- On failure: GitHub emails automatically. Retry 3x before failing.
- **Worker auto-deploy: `.github/workflows/deploy-workers.yml`** — triggers on push to the
  default branch when `worker/**` or `worker-cron/**` change. Runs `build:taxonomy` + tests
  before deploying; two independent jobs (one per worker). Also triggerable manually via
  `workflow_dispatch`. **No manual `npm run deploy` needed after merging worker changes.**
  - If the `Build taxonomy` step fails in CI: it is a **data validation error**, not a code
    error. An entry in `data/etf_overrides.csv` references a Finviz group name that doesn't
    exist in the snapshot CSVs. Fix: correct the name in `etf_overrides.csv` and re-push.
  - `wrangler deploy` does **not** touch secrets (FMP_API_KEY, GITHUB_DISPATCH_TOKEN), KV
    data, or cron expressions unless `wrangler.toml` changes.
  - TODO(D1): update `branches:` in the workflow to `[main]` when the default branch is
    renamed; also update `DISPATCH_REF` in `worker-cron/wrangler.toml` at the same time.
- `collect.py` and `compute_deltas.py` are **last-write-wins** per `date`: a later run on the same
  trading day evicts and rewrites that date's snapshot *and* delta rows, so the EOD run's ranks win
  over an earlier intraday run's.
- Gaps in data: compute_deltas.py counts trading sessions by position (`find_trading_date_back`), so missing/holiday days don't break the 5/10/20/50-session deltas.

### Cutting a release ("What's New") — 3 steps, always together

The PWA's **What's New** hub reads `docs/releases.json`. Release versions use the
`YYYY.MM.DD` convention (human-scannable, monotonic, no semver to maintain). For multiple
releases on the same calendar day, append `.N` (e.g. `2026.06.21.1`, `2026.06.21.2`).
When you ship a user-facing change, do **all three** of these in the same PR:

1. **Prepend** a new entry to `releases.json` `releases[]` (newest-first): `version`
   (`YYYY.MM.DD` or `YYYY.MM.DD.N` for same-day releases), `date`, `title`, `tag`
   (`feature|fix|data|improvement`), optional
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

### "Start Here" intro — `WELCOME` constant and first-run carousel

The **Start Here** hub section and the first-run full-screen carousel both draw from the
`WELCOME` array constant in `docs/index.html` (defined near `GUIDE`). The two surfaces
share one content source; `renderWelcome(mode)` switches rendering between hub ('hub')
and carousel ('carousel') modes.

**Canonical copy source:** `knowledge/product-intro-copy.md` — all `body` and `desc`
strings in `WELCOME` must appear verbatim there. `tests/test_pwa_intro.py` enforces the
sync (same discipline as `moaty-metrics.md` ↔ `GUIDE`).

**First-run behavior:** on page boot, if `localStorage.getItem('fvt_intro_seen_v1')` is
not `'true'`, the carousel auto-opens. Dismissing (Skip / Get started) calls
`setIntroSeen()` which sets the key. Re-openable anytime: hub ⓘ → Start Here → Replay
intro.

**`fvt_intro_seen_v1` key versioning:** bump the suffix to `v2` only when the intro
content changes substantially enough that existing users should see it again (e.g. a new
tab added, a major rewrite). Minor copy edits do **not** warrant a bump — they don't
justify re-nagging users who already dismissed it. Record any bump as a `feat:` commit
with an explicit rationale; do not bump silently.

**Tab deep-links:** each item in the tabs-tour slide carries a `tab` field (one of the
6 real tab ids). Adding a 7th tab requires updating `WELCOME` + `product-intro-copy.md`
+ `VALID_TAB_IDS` in `tests/test_pwa_intro.py` — the anti-drift test will catch the
mismatch.

## AI capture constants (`scripts/generate_ai.py`)

> Added in Phase 1 of the AI capture plan (ADR-006). Document changes to these in all three places per the configurable-constants rule above.

| Constant | Default | Controls |
|----------|---------|---------|
| `CAPTURE_DIR` | `data/ai/debug/` | Where Tier-2 debug captures are written (one file per date, committed, rolling window) |
| `PROVENANCE_DIR` | `data/ai/provenance/` | Where Tier-1 provenance files are written (one per date, committed permanently, user-facing) |
| `CAPTURE_RETENTION_DAYS` | `30` | Number of Tier-2 debug files kept in HEAD; older files are pruned from HEAD on each run but stay recoverable in git history. ~1 MB total at 30 days. |
| `AI_CAPTURE` env / `--capture` flag | off (on in CI) | Controls whether Tier-2 debug file is written. Set `AI_CAPTURE=1` or pass `--capture` to enable locally. Always enabled in `generate_ai.yml`. |
| `GOOGLE_API_KEY` | (set in env) | Vertex express key — sidesteps ADC and AI Studio 429s. Takes priority over Vertex ADC (`GOOGLE_CLOUD_PROJECT`) when `GOOGLE_GENAI_USE_VERTEXAI=true`. Sets `_backend="vertex_express"`. |

**Auth priority:** `GOOGLE_API_KEY` (Vertex express) > `GOOGLE_CLOUD_PROJECT` (Vertex ADC) > `GEMINI_API_KEY` (AI Studio).

**Preview mode (no creds needed):**
```bash
python scripts/generate_ai.py --preview [--task pulse] [--group sector] [--json]
```
Builds prompts from existing CSVs and writes Tier-1 provenance — no API call, no credentials required. Add `--date YYYY-MM-DD` to use a specific date (defaults to latest snapshot date).

---

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
| `worker/` | Cloudflare Worker (ticker lookup + cache ops) — see `worker/README.md`. ETF lookups apply a curated override layer (`data/etf_overrides.csv`) when `isEtf: true` — see ADR-005 and §ETF override layer below. |
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
