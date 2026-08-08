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
| `scripts/evaluate_picks.py` | Picks alpha scoreboard: rebuilds `data/picks/eval/group_scores.csv` (forward group returns vs SPY + cross-sectional median + non-selected control, per bucket, horizons 1/3/5/10 sessions). `--report` prints the alpha roll-up with a sample-size guard. Derived artifact — fully rebuilt each run, not append-only. Runs in `collect.yml` after `compute_deltas.py`. | ~150 |
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
  picks/
    display_methodology.json  # versioned display/scoring constants for Picks (All/Focus); see § Picks pipeline
    ariel_match_config.json   # documentation-only Ariel-match constants; no anti-drift guard (see § Picks pipeline)
    eval/group_scores.csv     # DERIVED (rebuilt daily, not append-only): picks alpha scoreboard; see scripts/evaluate_picks.py
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

### PWA display thresholds

The PWA (`docs/index.html`) has its own set of display/scoring constants (regime, momentum,
RS, Focus scoring, Ariel-match, etc.) — see **`docs/CLAUDE.md`** for the full table. Kept out
of this file since it only matters when touching `docs/`.

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

## ETF override layer, Picks pipeline, Playwright PWA/dashboard testing

Moved out of this always-loaded file since they only matter when touching that area:
- **ETF override layer** (`data/etf_overrides.csv`, worker build/runtime/cache-bust) → `worker/CLAUDE.md`
- **Picks pipeline** (`scripts/collect_picks.py`, selector buckets, `grp_*` columns, workflow guards) → `scripts/CLAUDE.md`
- **AI capture constants** (`scripts/generate_ai.py`) → `scripts/CLAUDE.md`
- **PWA functional testing with Playwright** (CSV route interception pattern) → `docs/CLAUDE.md`
- **Streamlit dashboard functional testing with Playwright** — same pattern as PWA testing but no interception needed (dashboard reads local CSVs directly); see `docs/CLAUDE.md` for the harness.
- **Scraping dev workflow** (iterating on `collect.py` against non-Cloudflare URLs) and **installing Playwright on demand** (don't add to `requirements.txt`) → `scripts/CLAUDE.md`

All Playwright-in-cloud work should first read
`knowledge/investigations/playwright-cloud-session-testing.md` for cloud-specific gotchas
(Chromium revision mismatch, CDN/raw.githubusercontent.com route-stubbing, glob boundary bug).

---

## Automation

- **Primary scheduler: the Cloudflare Worker `finviz-cron-dispatcher` (`worker-cron/`).** As of
  WS1 (`knowledge/decisions/ADR-010-single-trigger-cron-dispatch.md`,
  `planning/cron-consolidation-state-machine.md`) it runs on a **single** Cron Trigger,
  `*/5 * * * *` (`worker-cron/wrangler.toml`), firing `scheduled()` every 5 minutes around the
  clock. Which job (if any) actually dispatches on a given tick is decided entirely in code —
  `worker-cron/src/routing.js` `JOB_SCHEDULE` + `jobsForTick(etNow, dispatchedToday)` — gated on
  Eastern wall-clock time computed via `Intl.DateTimeFormat('en-US', { timeZone:
  'America/New_York' })`, which tracks EST/EDT automatically. **This removed the twice-yearly
  manual DST edit** that the old 3-cron-trigger design required across `wrangler.toml`,
  `src/index.js`, and `collect.yml` in lockstep.
  - **Self-healing dispatch, not exact-minute matching.** A job is due whenever the tick falls
    inside its `[target, target + DISPATCH_WINDOW_MINUTES)` ET window (default 30 min) **and**
    has no successful dispatch recorded for today's ET date yet (per-job KV key
    `last_dispatch_<jobName>`, e.g. `last_dispatch_collect_eod`). A delayed or skipped
    Cloudflare tick no longer silently drops that day's job — the next 5-minute tick still picks
    it up inside the window. No-op ticks (no job's window open) do zero I/O, keeping the
    ~288 ticks/day this design produces free of observability noise.
  - **Current jobs** (`worker-cron/src/routing.js` `JOB_SCHEDULE`, Mon–Fri): `collect_morning`
    at 09:45 ET (WS3 morning status, ADR-013, ungated — dispatches `collect_morning.yml`, KV key
    `last_dispatch_collect_morning`), `collect_preclose`
    at 15:50 ET (pre-close snapshot, shifted from legacy `:48`), `collect_eod` at 17:00 ET (EOD
    post-close snapshot, shifted from legacy `:01`), `picks` — also targets 17:00 ET, the same as
    `collect_eod`, not a fixed margin after it. The EOD collect run captures the day's final
    closing data.
  - **Session dimension (WS2, ADR-011 Option C):** `scripts/session_config.py` is the single
    source of truth for the "session" concept referenced above. The `eod` session is exactly
    this existing settled pipeline — `collect_eod`'s output files stay byte-identical, no
    migration. `morning` (09:45 ET, ADR-013 WS3, now writing
    `data/picks/sessions/morning{,_latest}.csv` via `collect_morning.yml`) and `pre_close`
    (15:50 ET, matching the `collect_preclose` cron above, not yet built — WS3b/WS5) are
    provisional sessions living in physically-separate, session-keyed stores that this settled
    pipeline never reads.
  - **Picks is dependency-gated, not fixed-time (issue #259, closing the last piece of ADR-010).**
    `worker-cron/src/picksGate.js` + `index.js`'s `runPicksGate` replace the old "EOD + 90min,
    hope collect.yml finished" margin with an actual state check: on every tick inside picks'
    `[17:00, 17:00 + PICKS_GATE_WINDOW_MINUTES)` ET window (120 min, i.e. 17:00–19:00 ET), the
    dispatcher reads its own `last_dispatch_collect_eod` KV record, then queries the GitHub
    Actions API (`GET .../collect.yml/runs`, reusing `GITHUB_DISPATCH_TOKEN`) for the run that
    corresponds to that EOD dispatch (matched by `created_at` at/after the dispatch timestamp,
    disambiguating from the earlier same-day pre-close run — a naive "most recent run" check can
    be satisfied by the wrong run). Picks dispatches the moment that run is confirmed
    `conclusion === 'success'`; if the window closes first, an explicit **miss** record is written
    to `last_gate_check_picks` KV (surfaced via `/last`) instead of the day silently going
    missing. This is the same self-heal/retry mechanism `jobsForTick` already provides for
    `collect_preclose`/`collect_eod` (not a second one-off) — the gate just adds the "was the
    underlying workflow actually successful" check on top, which a plain time-window check can't
    see. `collect.yml` running `collect.py → compute_deltas.py → evaluate_picks.py → git commit &&
    git push` all in one job (push last) means run-success is a sufficient "deltas landed" proxy —
    no separate commit-presence check is needed.
  - **`collect_picks.yml` also keeps its GitHub backstop:** an interim `schedule:` cron
    (`31 23 * * 1-5`, weekdays in GitHub's 0=Sunday convention) was added (issue #252,
    PICKS-FIX-C) after the old per-workflow Cloudflare picks trigger failed to deploy under the
    5-trigger account limit, leaving picks with no trigger and no data from 2026-07-17 onward. A
    healthchecks.io dead-man's-switch on `collect_picks.yml` still provides a before-bed alert if
    both flows fail silently. Per ADR-010, a single Cloudflare trigger is now a *stronger* single
    point of failure than the old 3 independent triggers were, so both GitHub `schedule:`
    backstops (`collect.yml` and `collect_picks.yml`) are kept, not removed, by this design.
  - **Why a separate scheduler:** GitHub's `schedule:` cron drifts hours and is dropped under
    load; `workflow_dispatch` is event-driven and prompt. See `planning/cloudflare-cron-scheduler.md`
    and `knowledge/decisions/` for the full rationale.
  - Config constants (tick interval, per-job ET target times, `DISPATCH_WINDOW_MINUTES`) are
    documented in-code in `worker-cron/src/routing.js` and in `worker-cron/README.md`
    § Configurable parameters, per this repo's 3-places rule.
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
- On failure: GitHub emails automatically. `collect.py` itself retries each fetch 3x with backoff (30s/60s/120s); there is **no workflow-level job retry** — a job that fails after script retries stays failed until the next scheduled trigger.
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

### Cutting a release ("What's New")

**Hard rule:** shipping a user-facing change requires updating `docs/releases.json` +
bumping `docs/sw.js`'s cache version **in the same PR** as the code change — never split
them. Full steps, the Guide-glossary sync, and the "Start Here" intro carousel: see
**`docs/CLAUDE.md`** (this only loads when touching `docs/`, where all three live).

---

## Session continuity (Claude Code web)

> These are instructions for future Claude instances, not the user. The user runs Claude Code on the web (code.claude.com), not the CLI.

### PR activity monitoring policy (token cost critical)

**DO NOT use `subscribe_pr_activity`, or `send_later` tools to monitor PRs or schedule check-ins UNLESS the owner explicitly requests it.** These tools waste tokens and money. Specifically:

- **Never** call `mcp__claude-code-remote__subscribe_pr_activity` to auto-monitor CI events or review comments
- **Never** call `mcp__claude-code-remote__send_later` to schedule hourly PR status re-checks
- **Never** call `mcp__claude-code-remote__fire_trigger` / `mcp__claude-code-remote__create_trigger` to set up recurring PR checks

Only use these if the owner explicitly asks you to watch a PR. If they do ask, acknowledge the request and set it up. 

---

- **Starting a session**: This `CLAUDE.md` auto-loads at session start. Also read `.session/session-notes.md` immediately — it holds the last 4 session entries with recent findings, blockers, and next steps. Start the session by summarizing what's in the notes so the user knows you're oriented. Older history is in `.session/archive/session-notes-archive.md` — only read it if the user asks or context demands it.
- **Sync first**: Run `git fetch origin && git log --oneline origin/claude/elegant-babbage-hlxnfy -5` before doing anything else — GitHub Actions may have pushed data overnight, and you need the latest base before branching or editing. See `.claude/rules/branch-commit-discipline.md` for the full session-start checklist.
- **Ending a session**: Before the user closes, **append** a new `---` delimited block to `.session/session-notes.md`. Header format: `## YYYY-MM-DD — <workstream description>` (date + what you worked on, not the branch name — branches are ephemeral). Include: status, what landed, any blockers, and next steps. Be specific — vague notes are useless next session. Do NOT replace existing entries; append only.
- **Session-notes window**: The file keeps the last 4 session entries. A human reviewer periodically moves older entries to `.session/archive/session-notes-archive.md`. You do not need to manage the archive.
- **Work log**: `.session/WORK_LOG.md` is retired — do not update it. Milestone context belongs in your session-notes entry.
- **Cannot run collect.py here**: Playwright installs fine in cloud, but Cloudflare blocks headless Chromium on Google Cloud IPs (AS396982). `collect.py` must run **locally** or via **GitHub Actions** (Azure IPs pass Cloudflare). Everything else — `compute_deltas.py`, tests, dashboard, PWA functional tests — runs fine in cloud. See § ETF override layer/Picks pipeline/Playwright testing above for pointers to `docs/CLAUDE.md` and `scripts/CLAUDE.md`.
- **Subagents for analysis**: Use subagents (Agent tool) for exploratory pandas/data work to avoid bloating the main context window.
- **Context pressure**: Use `/compact` when nearing limits. Prioritize keeping INITIAL_SPEC.md decisions and script logic in context; data rows are expendable.
- **Save research before it's lost**: If a session involved substantial research (API evaluation, debugging a non-obvious root cause, evaluating architectural trade-offs), write a summary to `knowledge/` before ending. A future Claude — or a human reading the code — should not have to rediscover it. Research logs go in `knowledge/` as free-form `.md` files; architectural decisions (and the alternatives rejected) go in `knowledge/decisions/` as ADRs. See `knowledge/README.md` for templates.
---

## Repository structure

| Directory | Purpose |
|-----------|---------|
| `scripts/` | Data collection and processing scripts. See `scripts/CLAUDE.md` for Picks pipeline and AI-capture detail. |
| `dashboard/` | Streamlit dashboard |
| `worker/` | Cloudflare Worker (ticker lookup + cache ops) — see `worker/README.md` and `worker/CLAUDE.md` (ETF override layer, ADR-009). |
| `docs/` | PWA (GitHub Pages) — `index.html`, `sw.js`, `manifest.json`. See `docs/CLAUDE.md` for display-threshold constants, release process, and PWA-specific testing. |
| `data/` | Append-only CSVs (sectors, industries) |
| `planning/` | Implementation plans and feature designs |
| `knowledge/` | Research logs, ADRs, debugging post-mortems |
| `.session/` | Session notes, sprint board, work log (committed, not gitignored) |
| `.claude/rules/` | Project rules files (branch discipline, data pipeline) |
| `.github/workflows/` | CI/CD — daily collect + compute_deltas |

> `docs/` is named per GitHub Pages convention: "Deploy from branch → /docs" only supports `/` or `/docs` as source. Do not rename it without switching to GitHub Actions deployment first.

> **Subdirectory `CLAUDE.md` files load only when Claude touches files in that directory.**
> If a task turns out to be cross-cutting (e.g. a scripts change that also affects PWA display),
> proactively `Read` the other directory's `CLAUDE.md` too — it won't auto-load otherwise.

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

## Respecting and Reducing Token Usage

- "For all (substantial) web research tasks or code exploration tasks or modular coding tasks use your judgement to decide an appropriate lower power model and run that in a subagent."
Why: cost/efficiency — research and implementation work rarely needs the top-tier model; judgment, review, and synthesis stay with the main loop.
How to apply: when a task in this project is primarily web research or exploring/writing/editing code, spawn an Agent with a model override (sonnet for substantive implementation, haiku for trivial/mechanical edits) and a self-contained prompt; review the result in the main loop before committing. Design, auditing, data synthesis, and anything judgment-heavy stays in the main model. 
