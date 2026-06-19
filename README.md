# Finviz Groups Tracker

Daily tracker for Finviz sector and industry group performance. Scrapes the Finviz Groups page using Playwright (headless Chromium), stores raw performance snapshots in append-only CSVs, computes rank and delta artifacts for trend analysis, and generates nightly AI market briefings via Gemini.

## What it does

- Fetches sector and industry performance data from Finviz daily (weekdays at 22:00 UTC via GitHub Actions)
- Stores raw snapshots in `data/sectors/snapshots.csv` and `data/industries/snapshots.csv`
- Computes rankings, rank changes over configurable trading-day lookback windows (default: 5/10/20/50 sessions), and a suite of momentum scores
- Generates a nightly AI analysis (market briefing, rotation phase signal, sector watchlist) via Gemini and commits it to `data/ai/YYYY-MM-DD.json`
- Logs every workflow run with field-level detail to `data/ai_run_log.jsonl` and `data/fetch_log.csv`
- Exports to SQLite and Parquet via `scripts/export_db.py`
- Provides a Streamlit dashboard for local browsing and visualization

## What makes this different

Finviz shows you today's numbers. This project tracks how those numbers *change*
and how *consistent* the strength is — a daily derived layer that's the real
moat. Every metric is documented in
[`knowledge/moaty-metrics.md`](knowledge/moaty-metrics.md).

- **Momentum score** — broad strength across all 7 timeframes at once (0–100%).
- **Momentum confirmed** — `momentum_score × rank_agreement`: broad strength gated by cross-timeframe consistency. High only when the trend is corroborated across 1/3/6-month.
- **Momentum weighted** — two weighted variants: `momentum_weighted_mid` (heavier on 1mo/3mo trend) and `momentum_weighted_fast` (heavier on day/week) for different rotation detection speeds.
- **Momentum acceleration** — `momentum_accel`: change in `momentum_score` over the past 10 sessions. Positive = broad momentum is building.
- **Regime signal** — `regime_short_long`: short-horizon percentile minus long-horizon percentile (~[-1,1]). Positive = emerging leader (strong recently, weaker long-term); negative = fading.
- **Rank trend slope** — `rank_trend_slope`: least-squares slope of `rank_ytd` over the trailing 10 sessions. Positive = rank is improving.
- **Rank trajectory** — `rank_*_delta_Nd`: how many spots a group moved up/down over 5/10/20/50 trading sessions. Spots rotation before the headline numbers do.
- **Rank agreement** — how tightly the 1-, 3-, and 6-month rankings cluster:
  high means a confirmed trend, not a one-week pop.
- **Sustained Strength** — top-N across 1, 3, AND 6 months simultaneously.
- **Rank Floor** — the worst a group's ranking has dropped to across 1/3/6
  months: a conservative conviction read.
- **All Green / breadth** — positive across the major timeframes at a glance.

The PWA Lookup tab surfaces these for any ticker's sector/industry — answering
"is this stock's group a tailwind or a headwind?" See
[`planning/lookup-tab-improvements.md`](planning/lookup-tab-improvements.md).

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

AI analysis can run on either **Vertex AI** (preferred for scale) or **Gemini AI Studio** (free tier). See **CLAUDE.md** § "AI generation auth (Vertex AI)" for detailed setup instructions including local development and CI authentication.

**Vertex AI (via Workload Identity Federation — GCP + GitHub):**
Requires GCP project setup and three repo secrets. See CLAUDE.md for full instructions.

**Gemini AI Studio (free tier fallback):**
```bash
GEMINI_API_KEY=your_key python scripts/generate_ai.py
```

Calls Gemini to produce a daily briefing, rotation phase signal, and sector watchlist. Output is written to `data/ai/YYYY-MM-DD.json`. Exits silently (graceful skip) if no API key is set.

**Smart skip:** By default, `generate_ai.py` checks whether today's date appears in the delta CSVs before making any API calls. If `compute_deltas.py` hasn't run yet for today (e.g. a mid-day re-run), it exits 0 without consuming API quota.

**Force regeneration:** Use `--force-ai` to bypass the skip check:

```bash
python scripts/generate_ai.py --force-ai
```

Or set the `FORCE_AI=1` environment variable. The GitHub Actions manual trigger (`workflow_dispatch`) also exposes a **Force AI regeneration** checkbox.

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

Schema is generated by `scripts/delta_config.py` (`delta_columns()`) — the single source of truth. All consumers (`compute_deltas.py`, `export_db.py`, `dashboard/app.py`) import from there.

`date, name, rank_day, rank_week, rank_month, rank_quarter, rank_half, rank_year, rank_ytd`, then for each window W in `5/10/20/50` trading sessions: `rank_week_delta_Wd, rank_month_delta_Wd, rank_ytd_delta_Wd, perf_week_delta_Wd, perf_month_delta_Wd, perf_ytd_delta_Wd`, then the momentum columns: `momentum_score, momentum_confirmed, momentum_weighted_mid, momentum_weighted_fast, momentum_accel, regime_short_long, rank_trend_slope, rank_agreement`.

> **Note on `export_db.py`:** `load_csv` does not validate that the live CSV contains all expected columns — columns absent from a pre-migration CSV are silently missing until `compute_deltas.py` has been re-run for those dates.

### fetch_log.csv columns

`timestamp, run_date, trigger, run_id, outcome, sectors_rows, industries_rows, step_failed, ai_outcome, ai_fields_missing`

- `ai_outcome`: `complete` / `partial` / `skipped` / `no_key` / `no_data` / `failed`
- `ai_fields_missing`: comma-separated list of fields that errored or had no snapshot data

### AI output JSON structure

```json
{
  "date": "2026-06-11",
  "generated_at": "2026-06-11T22:05:00Z",
  "model": "gemini-2.5-flash",
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

## Cloudflare Worker API

The ticker lookup feature uses a Cloudflare Worker (`worker/`) as a shared backend. It's live at:

```
https://finviz-ticker-lookup.salmonbaby8.workers.dev
```

### Endpoints

- **`GET /health`** — Health check. Returns `{"status": "ok"}`.
- **`GET /lookup?t=TICKER`** — Look up a single ticker symbol. Returns the company's Finviz sector and industry classification with confidence score and company details. Uses KV cache (30-day TTL). Example: `/lookup?t=AAPL` → `{finviz_sector: "Technology", finviz_industry: "Consumer Electronics", confidence: 0.95, ...}`.
- **`GET /stats`** — Daily FMP API call counter. Returns `{date: "YYYY-MM-DD", fmp_calls_today: <count>}`. Useful for monitoring free-tier quota usage.
- **`DELETE /cache?t=TICKER`** — Manual cache bust for a single ticker. Deletes the cached profile from KV. Use when taxonomy updates are deployed.

The Worker is called by both the PWA (Lookup tab in `docs/index.html`) and the Streamlit dashboard (Tab 8, "Ticker Lookup").

---

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

**Today** — All sectors or industries as color-coded cards, sorted by Week % by default. Use the sort dropdown to switch between Week / YTD / Month / Qtr / 6-Month / 1-Year / Day. Each card shows the group's 6-Month rank badge (rank 1 = strongest 6-month performer), its name, and two secondary metrics. A small arrow (↑/↓) shows the 5-session YTD rank delta, and a slope glyph (↑↑/↑/~/↓/↓↓) beside it shows the 10-session least-squares trend of the YTD rank — more reliable than a single-window diff. Tap any card to expand it: shows Quarter / 6-Month / 1-Year %, P/E, stock count, and market cap. Once 20 sessions of history exist (~July 10), a "vs 20d ago" row also appears showing how much the weekly and YTD % have changed. Below the cards, a Pipeline section shows the last 5 workflow run outcomes including AI generation status (◆ green = complete, amber = partial, grey = skipped).

**Movers** — The biggest rank climbers and fallers over 5 / 10 / 20 / 50 trading sessions. A "data accumulating" placeholder is shown until enough history exists (5-session deltas arrive after the 6th trading day). Each row shows how many ranking spots the group gained or lost. Green left border = gainer, red = loser.

**Momentum** — Two sub-views selectable via a toggle at the top:
- **Momentum view** (default) — Composite breadth leaderboard sorted by `momentum_score`. Shows which groups are consistently strong across all 7 timeframes at once. Includes a mini progress bar and an acceleration badge (▲▲ building / ▼▼ fading) once 10 sessions of history exist (~June 23). Works from day one.
- **Rotation view** — Groups ranked by `regime_short_long`: how much recent short-term strength (week + month) is outpacing or lagging long-term strength (3-month + 6-month + year). Split into three sections: 🌱 Emerging (rotating in), → Established (balanced), 📉 Fading (rotating out). Each card shows the 0-centered regime bar, short vs. long % context, and momentum score. Works from day one.

**Strength** — Two sub-views: Sustained Strength (top-N across all three medium-term timeframes: month / quarter / half-year simultaneously, sorted by `momentum_confirmed` = `momentum_score × rank_agreement`, rewarding groups that are both strong and consistent) and All Green (all perf timeframes positive, shown as an emoji dot matrix). Each Sustained card shows "Confirmed X% · Agree X%" so you can see the raw conviction level at a glance.

**AI** — Nightly AI analysis from Gemini: rotation phase classification (Early / Mid / Late Cycle / Defensive), top-3 sector watchlist with thesis, and a 3-paragraph market briefing for both sectors and industries. Requires `GEMINI_API_KEY` in GitHub Actions secrets to generate. The dashboard reads pre-committed JSON — no LLM calls at runtime.

**Refresh button (top-right)** — Clears the in-memory cache and re-fetches all CSV data from GitHub. Use this after the daily Actions run (~22:00 UTC / 6pm ET) to see the latest data. The app does not auto-refresh.

---

## Ranking and scoring methodology

### How ranks are computed

Every day, each group (sector or industry) is ranked from **1 (best)** to **N (worst)** independently for each of 7 performance metrics: `perf_day`, `perf_week`, `perf_month`, `perf_quarter`, `perf_half`, `perf_year`, `perf_ytd`. Rank 1 = highest % gain that day. Groups with missing data are placed at the bottom. Ties share the lowest rank among them (min method). Ranks are computed fresh from the raw CSV data — never scraped from Finviz.

### How rank deltas work

Lookback windows are defined in `scripts/delta_config.py` (`LOOKBACK_WINDOWS`, default `[5, 10, 20, 50]`) and measured in **trading sessions**, not calendar days. `find_trading_date_back()` counts back by position in the sorted list of actual trading days — so weekends and holidays are skipped automatically, not approximated.

```
rank_delta = rank_on_prior_trading_date - rank_today
```

A **positive delta means improvement** — e.g., was rank 18 five sessions ago, now rank 12 → delta = +6. Negative = fell in the ranking. Delta columns remain NaN until enough sessions of history exist (e.g., 50-session deltas need 50+ trading days).

**Perf deltas** use the opposite arithmetic: `perf_delta = today_perf - prior_perf`. Positive means the raw % improved over the window. The sign directions differ because rank 1 = best (lower = better) while higher % = better performance.

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

## Configurable parameters

All pipeline parameters live in `scripts/delta_config.py`. Edit that file to change behavior — every consumer (`compute_deltas.py`, `export_db.py`, `dashboard/app.py`) derives its schema from there.

| Parameter | Default | What it controls |
|-----------|---------|-----------------|
| `LOOKBACK_WINDOWS` | `[5, 10, 20, 50]` | Trading-session lookback windows for rank/perf deltas. Edit to add/remove windows — column names update automatically everywhere. |
| `RANK_DELTA_METRICS` | `["rank_week", "rank_month", "rank_ytd"]` | Which rank metrics get a per-window delta column. |
| `PERF_DELTA_METRICS` | `["perf_week", "perf_month", "perf_ytd"]` | Which perf metrics get a per-window delta column. |
| `ACCEL_WINDOW` | `10` | Sessions lookback for `momentum_accel` (change in `momentum_score`). Best kept equal to a value already in `LOOKBACK_WINDOWS` (currently `LOOKBACK_WINDOWS[1]`) to avoid an extra `compute_ranks` pass. |
| `SLOPE_WINDOW` | `10` | Sessions window for `rank_trend_slope` least-squares fit. |
| `WEIGHTS_MID` / `WEIGHTS_FAST` | see file | Per-metric weights for `momentum_weighted_mid` / `_fast`. |
| `REGIME_SHORT` / `REGIME_LONG` | wk+month / 3mo+6mo+year | Buckets for the `regime_short_long` signal. Day was excluded (too volatile); `perf_ytd` excluded from long (double-counts `perf_year`). |

> **To change lookback windows:** edit `LOOKBACK_WINDOWS`, then re-run `compute_deltas.py --date <d>` for each existing date to populate the new columns. `ensure_deltas_csv()` auto-migrates the CSV header on the next run (old columns drop, new columns appear empty).

### PWA display thresholds (`docs/index.html`)

These constants control when visual indicators appear or change state. All are near the top of the `<script>` block.

| Constant | Default | What it controls |
|----------|---------|-----------------|
| `REGIME_THRESHOLD` | `0.15` | Boundary between Emerging/Established/Fading buckets in Rotation view. Groups with `\|regime\| > 0.15` get a colored section header and card color; within ±0.15 = Established. |
| `ACCEL_STRONG` | `0.08` | `momentum_accel` threshold for the double-arrow badge (▲▲ building / ▼▼ fading). |
| `ACCEL_SLIGHT` | `0.02` | `momentum_accel` threshold for the single-arrow badge (▲ / ▼). Values within ±0.02 show no badge. |
| `SLOPE_STRONG` | `0.05` | `rank_trend_slope` threshold for the double-arrow glyph (↑↑ / ↓↓) on Today cards. |
| `SLOPE_SLIGHT` | `0.01` | `rank_trend_slope` threshold for the single-arrow glyph (↑ / ↓). Values within ±0.01 show `~`. |

> The Guide's **legend** renders these thresholds live (read from JS scope), so the in-app explanation can never drift from the numbers above.

### Scrape schedule (`worker-cron/wrangler.toml`)

The daily scrape is scheduled by the Cloudflare Worker `finviz-cron-dispatcher` (`worker-cron/`),
which fires `workflow_dispatch` to launch `collect.yml`. A single GitHub cron in `collect.yml`
remains as a same-time redundancy backstop. See `planning/cloudflare-cron-scheduler.md`.

| Parameter | Default | What it controls / how to change |
|-----------|---------|----------------------------------|
| `[triggers] crons` (`worker-cron/wrangler.toml`) | `["49 13 * * 1-5", "51 14 * * 1-5", "48 19 * * 1-5"]` | The three weekday-only fire times (UTC; fixed-UTC, no DST). Edit here, then `wrangler deploy` from `worker-cron/`. The EOD entry (`48 19`) is mirrored by the backstop cron in `collect.yml` — change both together. |
| `DISPATCH_REF` (`worker-cron/wrangler.toml` `[vars]`) | `claude/elegant-babbage-hlxnfy` | The git ref `collect.yml` runs on. Change without touching Worker code; redeploy to apply. |
| `GITHUB_DISPATCH_TOKEN` (Worker secret) | — | GitHub fine-grained PAT (this repo, Actions: R/W). Set via `wrangler secret put`, never committed. |

### Releases / "What's New" (`docs/releases.json`)

The PWA's ℹ️ hub shows release notes from `docs/releases.json` and flags unseen updates with a dot.

| Item | Convention | Notes |
|------|-----------|-------|
| Version | `YYYY.MM.DD` | Human-scannable, monotonic, no semver. `current` must equal the newest entry's `version`. |
| `tag` | `feature` / `fix` / `data` / `improvement` | Colors the entry badge. |
| `tab` (optional) | a PWA tab id (e.g. `momentum`) | Adds an "Open {tab} →" deep-link to the entry. |
| Unseen tracking | `localStorage` key `fvt_seen_release_v1` | First visit seeds to `current` (no backlog nag); dot clears on opening the hub. |

> **Cutting a release = 3 steps, always together:** (1) prepend an entry to `releases.json`,
> (2) update `current`, (3) bump `CACHE` in `docs/sw.js`. See CLAUDE.md § Automation.
> The glossary copy in the `GUIDE` constant (`docs/index.html`) is kept verbatim-synced with the
> User one-liners in `knowledge/moaty-metrics.md`; `tests/test_guide_releases.py` enforces both.

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

See **CLAUDE.md** § "AI generation auth (Vertex AI)" for comprehensive setup instructions for both backends.

**Quick start (Gemini AI Studio):**
1. Go to repo **Settings → Secrets and variables → Actions → New repository secret**
2. Name: `GEMINI_API_KEY`, Value: your Gemini API key (free tier works — 5 req/min)
3. The next scheduled cron will generate `data/ai/YYYY-MM-DD.json` automatically

**Production setup (Vertex AI with Workload Identity Federation):**
Requires GCP project creation, service account, WIF pool/provider, and three repo secrets. Full gcloud commands in CLAUDE.md.

