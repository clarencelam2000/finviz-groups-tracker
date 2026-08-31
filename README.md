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

- **Momentum score** — broad strength across 6 timeframes (week → YTD) at once (0–100%).
- **Momentum confirmed** — `momentum_score × rank_agreement`: broad strength gated by cross-timeframe consistency. High only when the trend is corroborated across 1/3/6-month.
- **Momentum weighted** — two weighted variants: `momentum_weighted_mid` (heavier on 1mo/3mo trend) and `momentum_weighted_fast` (heavier on week) for different rotation detection speeds.
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
- **Momentum view** (default) — Composite breadth leaderboard sorted by `momentum_score`. Shows which groups are consistently strong across 6 timeframes (week → YTD) at once. Includes a mini progress bar and an acceleration badge (▲▲ building / ▼▼ fading) once 10 sessions of history exist (~June 23). Works from day one.
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
| `RS_SLOPE_COL` | `"rs_month"` | Canonical RS spread used for the `rs_slope` least-squares fit. `rs_month` chosen as the most informative mid-frequency RS signal. |
| `RS_AGREEMENT_COLS` | `["rs_month", "rs_quarter", "rs_half"]` | RS spread columns used to compute `rs_agreement`. Mirrors `rank_agreement` inputs for consistency. |
| `RS_REGIME_SHORT` / `RS_REGIME_LONG` | wk+month / qtr+half+year | Buckets for `rs_regime_short_long` (RS analog of `regime_short_long`). |
| `RS_BEAT_TIMEFRAMES` | `["day","week","month","quarter","half","year","ytd"]` | Timeframe suffixes that get a `beats_benchmark_X` boolean column. Changing this adds or removes columns from the delta schema; auto-migrated by `ensure_deltas_csv()`. |
| `RS_NEW_HIGH_WINDOW` | `20` | Trading sessions looked back for `rs_new_high`. 20 ≈ 1 trading month — classic IBD RS-new-high window. Must be ≥ 2. |
| `RS_CROSS_WINDOW` | `5` | Trading sessions looked back for `rs_cross`. 5 ≈ 1 trading week — tight window to catch fresh rotations and filter noise. Must be ≥ 2. |

> **To change lookback windows:** edit `LOOKBACK_WINDOWS`, then re-run `compute_deltas.py --date <d>` for each existing date to populate the new columns. `ensure_deltas_csv()` auto-migrates the CSV header on the next run (old columns drop, new columns appear empty).

### Picks pipeline (`scripts/picks_config.py`)

Constants for the Stage-2 stock-picks selector and scraper (`scripts/collect_picks.py`).
Any change to a constant that feeds selection requires bumping `SELECTOR_VERSION` **and**
prepending an entry to `data/picks/selector_versions.json` (enforced by tests — see ADR-007).

| Parameter | Default | What it controls |
|-----------|---------|-----------------|
| `SELECTOR_VERSION` | `"v3"` | Monotonic, immutable-once-published selector policy id stamped on every `picks.csv` row. Bump on any selection-logic/constant change. |
| `DAILY_GROUP_CAP` | `27` | Max **unique** groups scraped per day. A group qualifying in multiple buckets counts once toward this cap but is tagged once per bucket it naturally ranks in (attribution) — a lower-priority bucket backfills past its natural top-N with the next new candidate so dedup doesn't shrink its effective slot yield (v2). Raised 20 -> 27 (v3) to match the exact worst-case sum of all 5 buckets' slots (11+2+4+3+3+4) so a fully-packed day never truncates a bucket. |
| `LEADER_SS_SLOTS` | `11` | Leaders "core" slots ranked by sustained strength (lowest `rank_month+rank_quarter+rank_half`). Raised 8 -> 11 (v3). |
| `LEADER_MC_SLOTS` | `2` | Leaders "freshness" slots ranked by `momentum_confirmed` desc among groups not in the core. |
| `EMERGING_SLOTS` | `4` | Max emerging-bucket groups. |
| `ACCEL_SLOTS` | `3` | Max accel-bucket groups. |
| `RS_NH_SLOTS` | `3` | Max rs_new_high-bucket groups. |
| `ALL_GREEN_SLOTS` | `4` | Max all_green-bucket groups (v3, new). Lowest priority (5th) — fills last. |
| `ALL_GREEN_PERF_COLS` | `["perf_week","perf_month","perf_quarter","perf_half","perf_ytd"]` | Raw perf columns (from `snapshots.csv`, not `deltas.csv`) that must ALL be positive for a group to qualify for all_green. `select_groups()` requires the caller to have already merged these onto its input — `main()` does this from `snapshots.csv`; missing columns degrade to 0 all_green groups, not an error. |
| `ANTIFLASH_PCTILE` | `0.40` | Anti-flash floor for accel/rs_new_high as a cross-sectional `momentum_score` percentile (top 40%). Invariant to formula rescaling. |
| `EMERGING_REGIME_FLOOR` | `0.15` | Emerging primary gate on `regime_short_long` (mirrors PWA `REGIME_THRESHOLD`). |
| `ACCEL_THRESHOLD` | `0.08` | Accel primary gate on `momentum_accel` (mirrors PWA `ACCEL_STRONG`). |
| `EMERGING_RS_FLOOR` / `ACCEL_RS_FLOOR` | `0.5` | `rs_score` floors on emerging / accel buckets (must be net-positive vs SPY). |
| `RS_NH_RS_FLOOR` | `0.6` | `rs_score` floor on rs_new_high (IBD "true leadership"). |
| `PAGE_SIZE` | `20` | Rows per Finviz screener page (`v=151`); used to walk `&r=`. |
| `PAGE_CAP` | `2` | Per-group hard page cap (40 names). Lowered from 15 after historical data showed only Biotechnology (a structurally oversized Finviz industry, ~100 names/day) ever exceeded 40 names. Screener sorts `-marketcap` desc, so the cap keeps the biggest/most-liquid names in an oversized group. |
| `GLOBAL_FETCH_CAP` | `50` | **Hard global daily page cap (VP-set).** Job scrapes in priority order (leaders first) and stops at 50 pages. Revisit after live data. > **Known gap:** as of v3, `DAILY_GROUP_CAP` (27) x `PAGE_CAP` (2) = 54, which is 4 pages **over** this cap on a fully-packed day (owner decision 2026-08-24: raise `DAILY_GROUP_CAP` but not this one). On such a day the lowest-priority bucket reached (`all_green`) can be silently cut short by the page cap, not just its own slot cap. |
| `PAGE_DELAY_S` | `3` | Polite inter-fetch delay (s). `PICKS_PAGE_DELAY=0` to skip during debugging. |
| `TIGHT_RANGE_WINDOW` | `7` | Compression spine (B-2, `picks_config.py`): number of trailing **available** daily bars (incl. today) the `tight_range_7` fact is evaluated over — 1 when today's raw High−Low is the narrowest of them. picks.csv history is gappy per-ticker, so these are the last N sessions on file, not N guaranteed-consecutive days (the PWA labels it "last 7 bars", never "NR7"). A window, not a threshold — it selects which bars to compare, it doesn't gate a value. |
| `SPARK_WINDOW` | `10` | Max points in the `range_atr_spark` / `atr_spark` sparklines (trailing available bars, oldest→newest). Shown values, no cutoff. |
| `SPARK_MIN_BARS` | `3` | Minimum available bars before a sparkline series is emitted at all; below this the column is blank (per-name graceful degradation). A too-short line reads as noise. |
| `HEADER_MISSING_ABORT_FRAC` | `0.10` | Header-drift guard (`collect_picks.py`): if `Ticker` is missing from the scraped screener header, or more than this fraction of the config's 84 labels are missing, the run aborts **before** writing (parse untrustworthy). A smaller drift still writes the partial capture (affected columns blank) but exits 1 **after** the write so CI goes red and `screener_config.json` gets fixed before the next run. |
| `TICKER_DUP_RATE_MAX` | `0.25` | Ticker-corruption guard (`collect_picks.py`): aborts **before** writing if more than this fraction of scraped tickers have a duplicated leading character (e.g. `"HHSBC"`, `"CC"`) — the signature of the 2026-07-15 markup-corruption incident. Real baseline is ~1-4%. To change safely, re-measure the real baseline over a few weeks of clean runs first. |
| `TICKER_SHORT_RATE_MAX` | `0.30` | Single-char-ticker guard (`collect_picks.py`, issue #252): complements `TICKER_DUP_RATE_MAX` by aborting **before** writing if more than this fraction of scraped tickers are a single character — catches the 2026-07-16 corruption class (parser returning only the avatar's leading letter) that the pair-duplication check is blind to. Real baseline is ~1.3-1.4%. To change safely, re-measure the real baseline over a few weeks of clean runs first. |

> **Behavior note (not a constant) — empty-scrape guard:** if **no** selected group returns any
> rows (the signature of a Cloudflare block: HTTP 200 with an empty table), `collect_picks.py`
> aborts with `exit(1)` **before** writing, rather than letting the date's existing rows be evicted
> and silently wiping a same-day capture. The daily picks list is irreplaceable, so a blocked run
> is a loud no-op (CI red + debug-HTML artifact uploaded), not a destructive overwrite. Non-empty
> re-runs still follow last-write-wins per date.

### Session dimension (`scripts/session_config.py`)

Single source of truth for the "session" concept (WS2, ADR-011 Option C): `eod` is the
existing settled pipeline — the current files stay byte-identical, unchanged. `morning`
and `pre_close` are provisional sessions whose data will coexist in physically-separate,
session-keyed stores added later (not yet built).

| Session | Capture (ET) | Settled? | Notes |
|---------|--------------|----------|-------|
| `eod` | `17:00` | Yes | The existing settled pipeline; matches the `collect_eod` cron. |
| `morning` | `10:05` | No | Provisional (WS3, ADR-013); 10:05 ET leaves a full 30-min candle after the open so intraday High/Low are a real range. |
| `pre_close` | `15:30` | No | Provisional (WS3b, issue #268); last half-hour read, ~30 min before the close. **Not** the same as the existing settled `collect_preclose` backstop cron job, which stays at `15:50` and dispatches the unrelated #259 picks gate. |

`DEFAULT_SESSION` = `eod` — callers that don't yet think in terms of multiple sessions default here.

`WATCHLIST_TICK_SESSIONS` = `{morning}` — sessions whose writer decrements the personal
watchlist's TTL on a successful, non-dry-run write (WS5 §8b). `pre_close` is deliberately
excluded so a watch entry doesn't lose two "mornings remaining" for one calendar day; see
`scripts/collect_morning.py`'s `should_tick_watchlist()`.

### WS3 morning status (`scripts/collect_morning.py`)

First writer under the provisional-session store pattern (ADR-013). Pure status engine
lives in `scripts/pick_status.py`; see `scripts/CLAUDE.md` § WS3 morning status for the
full pipeline description.

| Parameter | Default | What it controls |
|-----------|---------|-----------------|
| `MORNING_FOCUS_TOP_N` | `100` | Issue #293 scrape-universe cap: the morning run scrapes only the Focus view's top-N tickers by `focus_score` (reconstructed via `replay_picks.replay(date, "focus")`), not the full picks list (75–375 names/day). Best-first, so a partial scrape keeps the strongest names. Raise/lower to trade coverage for request cost. |
| `MORNING_FOCUS_SCORE_FLOOR` | `0.3` | Drop Focus candidates below this `focus_score` even when under the cap, so thin days self-trim instead of padding down to low-conviction setups. With N=100 the sample universe becomes min 22 / median 95 / max 100 names/day. |
| `MORNING_BATCH_SIZE` | `50` | Max tickers per `t=`-filtered screener URL fetch (URL-length safety). Each batch paginates internally with `&r=` like `probe_picks`. **Keep off a multiple of `PAGE_SIZE` (20):** a multiple-of-20 batch ends on a full page and forces a wasted empty-probe goto, so 50 (=20+20+10) is more request-efficient than 40 or 60 — batch 50 = 6 gotos for ~100 tickers vs batch 60 = 7. |
| `MAX_STALE_SESSIONS` | `5` | Max trading sessions `picks_latest.csv` may lag behind today before `collect_morning.py` refuses to write (exits 1 loud). |
| `MORNING_STORE` | `data/picks/sessions/morning.csv` | Append-only provisional history, keyed `(date, ticker)`, last-write-wins (same convention as `picks.csv`). |
| `MORNING_LATEST` | `data/picks/sessions/morning_latest.csv` | Max-date slice of `MORNING_STORE` — the PWA fetch target (Phase C). |

### WS5 held-tickers feed (`scripts/collect_held.py`)

Settled-EOD quote feed for the *held* set (union of open/managing/closing positions,
`planning/trade-lifecycle-engine.md` §5/§5a). Shares `fetch_ticker_quotes`/`build_ticker_url`
with `collect_morning.py` (`block="held"`); see `scripts/CLAUDE.md` § WS5 held-tickers feed
for the full pipeline description. Unlike every other collector in this table, it writes to
**D1 over HTTP, not to a repo CSV** — there is no store path to configure here.

| Parameter | Default | What it controls |
|-----------|---------|-----------------|
| `POSITIONS_WORKER_URL` (env) | unset, required | Base URL of the `finviz-positions` Worker. Read from `GET {URL}/held-tickers` and posted to at `POST {URL}/ingest/quotes`. Set as a GitHub Actions secret; missing → `sys.exit(1)` loud. |
| `POSITIONS_INGEST_TOKEN` (env) | unset, required | Bearer token authenticating both calls above (`worker-positions/src/auth.js`). Set as a GitHub Actions secret; missing → `sys.exit(1)` loud. |

### Picks alpha scoreboard (`scripts/evaluate_picks.py`)

| Parameter | Default | What it controls |
|-----------|---------|-----------------|
| `HORIZONS` | `[1, 3, 5, 10]` | Forward horizons in **trading sessions** for the group scoreboard (`data/picks/eval/group_scores.csv`). Adding one is safe (the file is fully rebuilt each run); removing one drops its rows on the next rebuild. |
| `MIN_POWERED_DATES` | `40` | Distinct settled pick dates below which `--report` prints the "NOT YET POWERED" caveat. Dates (not rows) are the effective N — forward windows overlap heavily. Don't tune the selector below this. |

> `group_scores.csv` is a **derived artifact, fully rebuilt on every run** (not append-only):
> partial-horizon rows (`n_sessions_avail < horizon`) self-correct as new sessions arrive.
> Filter to `n_sessions_avail == horizon` for the settled scoreboard. Rebuilt daily by
> `collect.yml` right after `compute_deltas.py`. `python scripts/evaluate_picks.py --report`
> prints the alpha roll-up (per-bucket stats + paired per-date selected-vs-non-selected test).

### PWA display thresholds (`docs/index.html`)

These constants control when visual indicators appear or change state. All are near the top of the `<script>` block.

| Constant | Default | What it controls |
|----------|---------|-----------------|
| `REGIME_THRESHOLD` | `0.15` | Boundary between Emerging/Established/Fading buckets in Rotation view. Groups with `\|regime\| > 0.15` get a colored section header and card color; within ±0.15 = Established. |
| `ACCEL_STRONG` | `0.08` | `momentum_accel` threshold for the double-arrow badge (▲▲ building / ▼▼ fading). |
| `ACCEL_SLIGHT` | `0.02` | `momentum_accel` threshold for the single-arrow badge (▲ / ▼). Values within ±0.02 show no badge. |
| `SLOPE_STRONG` | `0.05` | `rank_trend_slope` threshold for the double-arrow glyph (↑↑ / ↓↓) on Today cards. |
| `SLOPE_SLIGHT` | `0.01` | `rank_trend_slope` threshold for the single-arrow glyph (↑ / ↓). Values within ±0.01 show `~`. |
| `RS_STRONG` | `2.0` | RS spread (pp vs S&P) threshold for the strong badge (deep green / deep red) in the vs Market tab and Today cards. |
| `RS_SLIGHT` | `0.5` | RS spread threshold for the mild badge (green / orange). Within ±0.5pp → neutral chip. |
| `BREADTH_GATE_TFS` | `{month, quarter, half, ytd}` | Lookup card "Raw Perf" dot row: which of the 6 displayed timeframes (`week, month, quarter, half, ytd, year`) count toward the "All green" verdict. Week and year render as dots but don't gate — see `knowledge/decisions/ADR-003-breadth-excludes-week.md`. |
| `SIGNAL_WEIGHTS` | see code | Lookup tab SIGNAL card (`groupSignal()`) per-factor weights: `momentumConfirmed 0.30`, `rsConfirmed 0.30`, `rankDeltaShort 0.15`, `regime 0.15`, `breadth 0.10`. A factor is skipped (weight renormalized away) when its source column is null, so missing data never fabricates a fake neutral score. |
| `SIGNAL_FAVORABLE` / `SIGNAL_CAUTION` | `0.65` / `0.35` | Lookup tab SIGNAL card verdict thresholds on the `groupSignal()` composite. `>=` favorable, `<=` caution, between = mixed, no data either side = no signal. |
| `BREADTH_TOP_HALF_FRACTION` | `0.5` | "Top half" cutoff shared by `computeSectorBreadth()` — powers both the Strength-tab sector breadth table and the Today-tab sector card breadth bar / drill-down (via the `computeSectorTopHalfCounts()` wrapper). A single threshold, two render targets. |
| `MIN_MARKET_CAP_B` | `5` | Picks tab C6 base display filter: hides rows whose Market Cap is ≤ 5B. Cuts noise from micro/nano-caps. |
| `ATR_EXT_ACTIONABLE` | `4.0` | ATR-extension emerald band cap (<4× = actionable / entry-zone). Also the Focus hard-DQ line (Phase 3b). |
| `ATR_EXT_TRIM` | `8.0` | ATR-extension red band start (≥8× = trim-10% candidate for held positions). Amber band is 4–8×. |
| `ATR_FROM_LOD_CLEAN` / `ATR_FROM_LOD_CHASE` | `0.8` / `1.0` | Morning tab (WS3) entry-quality bands on `atr_from_lod` = (price − session low) / ATR, actionable cards only. `≤0.8` clean entry, `>1.0` chasing, between = caution. Also in `docs/CLAUDE.md` threshold table. |
| `LAUNCH_NEAR_HIGH_PCT` | `8` | Launch-ready chip (Picks tab, Phase 1): `ohMag` (% below 52-week high) at or under this counts as "near the high" (little overhead supply). Also in `docs/CLAUDE.md` threshold table. |
| `LAUNCH_CALM_EXT_MAX` | `3` | Launch-ready chip: `atr_ext_50` at or under this (and `> 0`), combined with near-high, classifies the pick as `Coiled`; above this = `Extended`. Also in `docs/CLAUDE.md` threshold table. |
| `LAUNCH_OVERHEAD_PCT` | `20` | Launch-ready chip: `ohMag` above this classifies the pick as `Overhead` (deep below high, heavy overhead supply). Also in `docs/CLAUDE.md` threshold table. |
| `ATR_EXT_PENALTY_START` | `2.5` | ATR-extension at which the Focus-score extension penalty begins ramping. Zero penalty below this; full `PENALTY_MAX` at `ATR_EXT_ACTIONABLE` (4×). |
| `PENALTY_MAX` | `0.5` | Maximum Focus-score extension discount fraction (50% haircut at 5×). `score = base × (1 − penalty_fraction)`, always ∈ [0, 1]. |
| `FOCUS_W_GROUP` | `0.2` | Focus score weight for the sustained group-strength component (`grp_sum_mid_rank` inverted min-max). Lowered from `0.4` on 2026-07-16. |
| `FOCUS_W_TIGHT` | `0.4` | Focus score weight for the nearest-MA stop tightness component (`min(risk_20ma_pct, risk_50ma_pct)` where both > 0, inverted min-max). |
| `FOCUS_W_QUIET` | `0.4` | Focus score weight for the quiet-bar component (`range_atr`, inverted min-max — lower range = quieter = better). Raised from `0.2` on 2026-07-16. |
| `FOCUS_MIN_POOL` | `5` | Minimum Focus candidates before switching from min-max to rank-based normalization (avoids degenerate single-point scaling). |
| `BUTTON_V` | `'311'` | Finviz screener view number used by the Lookup deep-link button (tight Stage-2 layout). Must stay in sync with `data/picks/screener_config.json` `button.v`. |
| `BUTTON_BASE_FILTERS` | `['cap_midover','ta_sma20_sa50','ta_sma50_pa']` | Base Finviz screener filters prepended before the `ind_<slug>` / `sec_<slug>` token. Must stay in sync with `data/picks/screener_config.json` `button.base_filters`. |
| `BUTTON_SORT` | `'sma50'` | Sort order for the Lookup deep-link screener (ascending distance from 50MA). Must stay in sync with `data/picks/screener_config.json` `button.sort`. |
| `BUTTON_FT` | `'4'` | `ft` (filter type) parameter for the Lookup deep-link screener. Must stay in sync with `data/picks/screener_config.json` `button.ft`. Anti-drift guard: `tests/test_picks_button_config.py`. |
| `EARNINGS_IMMINENT_DAYS` | `3` | Picks tab expanded card: earnings-date badge turns red when the next known earnings date is within this many days. |
| `EARNINGS_CAUTION_DAYS` | `10` | Picks tab expanded card: earnings-date badge turns amber when within this many days (and beyond `EARNINGS_IMMINENT_DAYS`). Only upcoming (non-past) dates are colored. |
| `FOCUS_MIN_DOLLAR_VOL` | `30_000_000` | Focus scoring hard gate: avg $ volume (Price × Avg Volume) must be at or above this for a stock to be a Focus candidate. |
| `LIQUIDITY_PENALTY_START` | `60_000_000` | Above this avg $ volume, zero Focus-score liquidity penalty; ramps to `LIQUIDITY_PENALTY_MAX` at the `FOCUS_MIN_DOLLAR_VOL` floor. |
| `LIQUIDITY_PENALTY_MAX` | `0.3` | Max multiplicative Focus-score haircut for thin (but above-floor) liquidity. |
| `EARNINGS_PENALTY_MAX` | `0.7` | Max multiplicative Focus-score haircut for imminent earnings; ramps in from `EARNINGS_CAUTION_DAYS` to `EARNINGS_IMMINENT_DAYS`, holds through day 0. |
| `POST_EARNINGS_PENALTY_FRAC` | `0.25` | One-day carry-over penalty (fraction of `EARNINGS_PENALTY_MAX`) for a stock that reported exactly 1 day ago. 2+ days past is fully decayed. |
| `ARIEL_GROUP_TOP_N_FULL` | `40` | Ariel match (Phase 4): group must rank in the top N industries by `rank_month + rank_quarter` (ascending sum) to fully qualify. |
| `ARIEL_GROUP_TOP_N_SOFT` | `50` | Ariel match: soft-qualify extension for ranks 41–50 (near-miss on the group gate). |
| `ARIEL_DOLLAR_VOL_MIN` | `100_000_000` | Ariel match: hard floor on avg $ volume (Price × Avg Volume); no soft band. |
| `ARIEL_ATR_PCT_FLOOR_SOFT` | `3.0` | Ariel match: below this ATR/Price % the daily-move gate is excluded entirely (too quiet). |
| `ARIEL_ATR_PCT_FULL_LOW` / `ARIEL_ATR_PCT_FULL_HIGH` | `4.0` / `7.0` | Ariel match: full-qualify band for ATR/Price % (daily move). |
| `ARIEL_ATR_PCT_CEIL_SOFT` | `9.0` | Ariel match: above this ATR/Price % the daily-move gate is excluded entirely (too volatile). |
| `ARIEL_GROWTH_MIN_FULL` | `25` | Ariel match: EPS YoY TTM AND Sales YoY TTM must each be at or above this % for the growth gate to fully qualify. |
| `ARIEL_GROWTH_MIN_SOFT` | `15` | Ariel match: soft-qualify floor for EPS YoY TTM AND Sales YoY TTM — either metric below this fails the growth gate outright. |
| `WATCHLIST_TTL_SESSIONS` | `10` | Personal watchlist (WS5 §8b): display-only mirror of the worker's `WATCHLIST_TTL_SESSIONS` — drives the watch card's "N mornings left" readout. The worker (`worker-positions`) owns the real `sessions_remaining` counter; see its README for the source-of-truth constant. |
| `WATCHLIST_EXPIRING_AT` | `1` | Personal watchlist: `sessions_remaining <=` this shows the amber "expiring" cue on a watch card's footer. |
| `WATCHLIST_GAUGE_PAD` | `0.08` | Personal watchlist: fraction of the price domain padded on each end of a watch card's levels gauge, so end markers aren't clipped. |
| `POS_VISIBLE_STATES` | `{'open','managing','closing'}` | Positions tab: worker `state` values that always render as a live card. Since WS5-5 (#332) the live fetch also pulls `closed` rows bounded by `closed_within_sessions=POS_GRACE_SESSIONS`; the real client-side gate is `posIsLiveVisible(p)`, not a bare `POS_VISIBLE_STATES.has()` check. |
| `POS_STATE_BADGE` | see code | Positions tab: small uppercase badge shown on `managing` ("managing") and `closing` ("exit pending", amber) cards; `open` shows no badge (default/expected state). |
| `POS_GRACE_SESSIONS` | `2` | Positions tab (WS5-5, #332): trading sessions a `closed` position keeps showing in the live list (read-only "closed" badge) before it drops to the Closed section only. |
| `POS_CLOSED_HISTORY_SESSIONS` | `60` | Positions tab (WS5-5): how many trading sessions back the lazy-loaded Closed section fetches once expanded (~3 trading months). |

> The worker-side `WATCHLIST_TTL_SESSIONS` (source of truth for `sessions_remaining`) and
> `WATCHLIST_PURGE_DAYS` (expired-entry retention) are documented in
> `worker-positions/README.md` § Configurable parameters, not duplicated here.

> The Guide's **legend** renders these thresholds live (read from JS scope), so the in-app explanation can never drift from the numbers above.

### Display methodology versioning (`data/picks/display_methodology.json`)

Same versioning pattern as `selector_versions.json` (`current` pointer + newest-first
`versions[]`, looked up by largest `effective_date ≤ date`), but for the *client-side*
constants above that determine which Picks stocks are shown and how Focus scores are
ranked — base filter, All-view sort, Focus DQ/scoring/weights, ATR display bands.
Whenever any of those PWA constants changes, prepend a new version entry **in the same
PR** — there's no "wait until it's stable" grace period; the file's whole job is to
never lag live reality. Anti-drift guard (`tests/test_picks_methodology.py`) only
checks `current` (the newest entry) against live `docs/index.html`; older entries are
frozen historical snapshots and are expected to diverge once superseded. Full design:
`planning/picks-methodology-tracking.md`. Replay/A-B tool: `scripts/replay_picks.py`.

`v1` (effective 2026-06-25) covered the original Phase 3b base filter/sort/Focus-score
formula. `v2` (current, effective 2026-07-01) added the Phase 3d Focus liquidity
gate/penalty (`FOCUS_MIN_DOLLAR_VOL`/`LIQUIDITY_PENALTY_START`/`LIQUIDITY_PENALTY_MAX`)
and earnings-proximity penalty (`EARNINGS_IMMINENT_DAYS`/`EARNINGS_CAUTION_DAYS`/
`EARNINGS_PENALTY_MAX`/`POST_EARNINGS_PENALTY_FRAC`).

> **Known gap:** the Phase 4 Ariel-match filter (`ARIEL_*` constants) is not modeled in
> `display_methodology.json` at all, by design — it's an optional additive display
> layer independent of the core All/Focus ranking. It's versioned separately in
> `data/picks/ariel_match_config.json`, which has **no anti-drift guard/test** —
> enforcement there is manual code review only.
>
> **Known limitation (permanent, not a bug):** the earnings penalty depends on "days
> until next earnings," which `docs/index.html` always computes relative to the
> viewer's wall-clock date at render time. `scripts/replay_picks.py` instead uses the
> replay `--date` as that reference, reproducing what a viewer would have seen live on
> that date — re-running the replay for the same past date on a later day will not
> reproduce a value the live PWA never actually showed (there's no live value to match,
> since the PWA doesn't retroactively recompute this for past dates either).

### Scrape schedule (`worker-cron/wrangler.toml`)

The daily scrape is scheduled by the Cloudflare Worker `finviz-cron-dispatcher` (`worker-cron/`),
which fires `workflow_dispatch` to launch `collect.yml`. A single GitHub cron in `collect.yml`
remains as a same-time redundancy backstop. See `planning/cloudflare-cron-scheduler.md`.

| Parameter | Default | What it controls / how to change |
|-----------|---------|----------------------------------|
| `[triggers] crons` (`worker-cron/wrangler.toml`) | `["49 13 * * 1-5", "51 14 * * 1-5", "48 19 * * 1-5"]` | The three weekday-only fire times (UTC; fixed-UTC, no DST). Edit here, then `wrangler deploy` from `worker-cron/`. The EOD entry (`48 19`) is mirrored by the backstop cron in `collect.yml` — change both together. |
| `DISPATCH_REF` (`worker-cron/wrangler.toml` `[vars]`) | `claude/elegant-babbage-hlxnfy` | The git ref `collect.yml` runs on. Change without touching Worker code; redeploy to apply. |
| `GITHUB_DISPATCH_TOKEN` (Worker secret) | — | GitHub fine-grained PAT (this repo, Actions: R/W). Set via `wrangler secret put`, never committed. |

### AI analysis (`scripts/generate_ai.py`)

Controls Tier-1 (provenance) and Tier-2 (debug capture) output, auth, and retention.

| Parameter | Default | What it controls |
|-----------|---------|-----------------|
| `CAPTURE_DIR` | `data/ai/debug/` | Directory for Tier-2 debug JSON files (full prompt + raw + parsed + usage + latency). Written (and committed) only when `AI_CAPTURE=1`. Rolling 30-day window in HEAD; older files pruned from HEAD but fully recoverable from git history. Always on in CI. |
| `PROVENANCE_DIR` | `data/ai/provenance/` | Directory for Tier-1 provenance JSON files (input data blocks only — no instruction text). Always written on every successful run. Committed permanently. |
| `CAPTURE_RETENTION_DAYS` | `30` | How many days of Tier-2 debug files to keep in HEAD (older files are deleted from the working tree on the next run, but remain in git history). |
| `AI_CAPTURE` (env) | unset (off) | Set to `1` to enable Tier-2 debug capture. Always on in CI (`generate_ai.yml`). Off by default locally to avoid committing verbose debug blobs. |
| `GOOGLE_API_KEY` (env) | unset | Vertex AI express key (third auth path). Priority: express key > Vertex ADC > AI Studio. Enables Vertex without a full GCP project credential setup. |

**Auth priority for Vertex AI:** `GOOGLE_API_KEY` (express key) → `GOOGLE_CLOUD_PROJECT` + ADC → graceful-skip with a clear error message.

**Preview mode:** `python scripts/generate_ai.py --preview [--task TASK] [--group TYPE] [--json]` — builds prompts from CSVs, writes Tier-1 provenance, no API calls, no credentials required.

### Releases / "What's New" (`docs/releases.json`)

The PWA's ℹ️ hub shows release notes from `docs/releases.json` and flags unseen updates with a dot.

| Item | Convention | Notes |
|------|-----------|-------|
| Version | `YYYY.MM.DD` (or `YYYY.MM.DD.N` for same-day releases) | Human-scannable, monotonic, no semver. `current` must equal the newest entry's `version`. |
| `tag` | `feature` / `fix` / `data` / `improvement` | Colors the entry badge. |
| `tab` (optional) | a PWA tab id (e.g. `momentum`) | Adds an "Open {tab} →" deep-link to the entry. |
| Unseen tracking | `localStorage` key `fvt_seen_release_v1` | First visit seeds to `current` (no backlog nag); dot clears on opening the hub. |

> **Cutting a release = 3 steps, always together:** (1) prepend an entry to `releases.json`,
> (2) update `current`, (3) bump `CACHE` in `docs/sw.js`. See CLAUDE.md § Automation.
> The glossary copy in the `GUIDE` constant (`docs/index.html`) is kept verbatim-synced with the
> User one-liners in `knowledge/moaty-metrics.md`; `tests/test_guide_releases.py` enforces both.

### Start Here intro (`WELCOME` constant)

The "Start Here" hub section and first-run carousel draw from the `WELCOME` array in `docs/index.html` (near the `GUIDE` constant). Each entry is `{id, title, body, items?}`.

| Item | Notes |
|------|-------|
| Content source | `knowledge/product-intro-copy.md` — the canonical copy for all body/desc strings. Keep verbatim-synced with `WELCOME`. |
| First-run behavior | On first page load (no `fvt_intro_seen_v1` in `localStorage`), the 5-slide carousel auto-opens. Dismissing (Skip / Get started) sets the key. |
| Re-opening | Hub ⓘ → Start Here → "Replay intro" button; or call `showIntroOverlay()`. |
| `fvt_intro_seen_v1` | `localStorage` key that tracks carousel dismissal. Bump the suffix to `v2` only when content changes enough to re-show it to existing users (e.g. a new tab added). Minor copy edits do **not** warrant a bump. |
| Tab deep-links | Each item in the tabs-tour slide has a `tab` field — a `switchTab()` call. Add to `VALID_TAB_IDS` in `tests/test_pwa_intro.py` whenever a new tab is added. |
| Anti-drift tests | `tests/test_pwa_intro.py` — tab ID guard + body/desc verbatim-sync check (mirrors `test_guide_releases.py`). |

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

