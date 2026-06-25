# Work Log

> Gitignored. Track milestones, decisions, and discoveries as the project evolves.

---

## 2026-06-25 — Picks pipeline LIVE: first green collect_picks.yml run

First `collect_picks.yml` dispatch succeeded. 273 stock picks / 262 unique tickers / 19 industry
groups across all 4 buckets (leaders/emerging/accel/rs_new_high). 19/19 scraped slugs
validated. Dedup confirmed: Packaging & Containers appeared in both `emerging` and `accel`,
scraped once, tagged separately with independent `grp_category_rank` per bucket. `picks_latest.csv`
correct (= max-date slice). `picks.csv`: 108 cols per row (84 Finviz + 5 lead + 19 `grp_*`).
ADR-008 grp_* table reconciled to match the 19-col implemented spec. Phase 3 unblocked.

## 2026-06-25 — Picks pipeline Phase 2: collect_picks.py + selector + workflow

Stage-2 stock-picks data pipeline code-complete. New `scripts/collect_picks.py` (pure
`select_groups()` four-bucket priority-fill selector + paginated screener scrape + append/dedup +
`picks_latest.csv` + G4 `validated` flip + stale-read guard) and `scripts/picks_config.py` (schema +
triple-doc'd constants). Seeded `data/picks/selector_versions.json` v1 with immutable-registry tests.
New `.github/workflows/collect_picks.yml` with own EOD cron; added the shared
`concurrency: finviz-data-commit` block to BOTH it and the existing `collect.yml` (G1 gotcha).
30 new unit tests (selector buckets/floors/dedup/cap, pagination + global-cap, build/write/migration,
registry, golden-header sync) — 480 tests pass.

## 2026-06-24 — Sector hierarchy Phase 1: sidebar filter + breadth metric

TASK-6B and INS-7 both complete. Streamlit dashboard now has a sidebar Sector selectbox (Industries view) that narrows all tabs to a single sector's industries. New Sector Breadth table in Strength tab shows per-sector top-half industry counts against the full 144-industry universe. `compute_sector_breadth()` extracted as testable module with 10 tests. 337 total tests pass.

## 2026-06-22 — Movers tab improvements shipped (PRs #155, #156, #157)

Four improvements across three PRs: RS NH/↑cross market-context badges on Top Gainers; "Score" → "Mom" label rename; tap-any-card to open Lookup for that group; YTD/Month/Week rank dimension toggle. Review subagents caught two real bugs (scroll target + initUIFromState sync) fixed before merge. Release 2026.06.22.1, sw.js CACHE → finviz-v24.

---

## 2026-06-21 — CF Worker auto-deploy live (PR #152)

`.github/workflows/deploy-workers.yml` shipped. Both Cloudflare Workers (finviz-ticker-lookup, finviz-cron-dispatcher) now auto-deploy on push to default branch when their source changes. `build:taxonomy` runs before tests (validates ETF override names against snapshot CSVs). No more manual `npm run deploy`. Post-merge: trigger `workflow_dispatch` to smoke-test both deploy jobs.

---

## Data Collection Milestones

| Date | Milestone | Notes |
|------|-----------|-------|
| 2026-06-09 | First successful scrape | 11 sectors, 144 industries |
| 2026-06-09 | Pipeline verified end-to-end | collect → deltas → dashboard all working |
| | Confirmed Finviz update time | Probe intraday — TBD |
| 2026-06-09 | GitHub Actions cron enabled | Runners confirmed working |
| 2026-06-09 | Mobile PWA live on GitHub Pages | https://clarencelam2000.github.io/finviz-groups-tracker/ |
| 2026-06-13 | AI quota exhaustion root-caused and fixed (PR #58) | Three bugs: incremental loading removed, retry on daily quota, silent delta errors. Fixed with DailyQuotaExhaustedError + restored partial-file resume. 207 tests passing. |
| 2026-06-14 | TICKER-1: CF Worker code merged | PR #74 merged TICKER-1 worker to main branch. `/lookup` endpoint + KV cache complete, 28 vitest tests passing. Pending user deployment (`wrangler deploy`). |
| 2026-06-14 | TICKER-0: FMP→Finviz taxonomy map built | `data/taxonomy_map.csv` (133 rows) from 242 live FMP profiles. All Finviz names validated; 132/144 reachable. Discovered FMP migrated to `/stable/` API — plan's v3 endpoint dead (see `knowledge/fmp-api-findings.md`). |
| 2026-06-14–15 | AI-MIGRATION: Gemini AI Studio → Vertex AI (code merged, validation INCOMPLETE) | **Phase 1 (GCP):** User completed G1–G3 (project, SA, WIF, secrets). **Code Merged:** PR #79 includes Phases 2–4 + RETRY_BASE_DELAY optimization. **Validation:** Two runs completed; Run #1 (23:07 UTC) had preamble wrapping; Run #2 (23:56 UTC) still has JSON parse error on `sectors.daily_delta` ("Unterminated string" at column 99). PR #84's 900-token increase insufficient. **Blocker:** daily_delta response appears truncated or wrapped in additional formatting. Needs investigation + potential workaround (reduce scope or increase tokens further). |
| 2026-06-15 | AI tab rebuilt: freeform note over forced JSON | Replaced the brittle JSON-schema pipeline (root cause of JSON-in-JSON / truncation / "Unknown" phase / apology-text deltas) with one freeform markdown note per group, built from computed signals (all-green, sustained strength, movers, momentum leaders/laggards, divergences). Token cap removed; daily-delta + watchlist + key_signals dropped. PWA renders markdown via `renderMarkdown()`. Broken Jun 12–14 artifacts removed. 93 tests passing. Branch `claude/exciting-brown-1pc93v`. |
| 2026-06-20 | ETF-1: Curated ETF override layer complete | 31 ETFs (thematic/sector/diversified), build validation, worker runtime wiring, PWA ETF badges, ADR-005. COPX→Copper, ITA→A&D, SMH→Semis, etc. Post-deploy: bust KV cache for seed ETFs. 50 worker + 165 Python tests pass. |
| 2026-06-21 | RS-4: Tier 5 discrete RS flags complete | 9 new delta columns: beats_benchmark_{day..ytd} (7 booleans), rs_new_high (IBD-style 20-session high flag), rs_cross (neg→pos flip within 5 sessions). NH (amber) + ↑ cross (sky) badges surface in vs Market tab. beats N/7 tf sub-line. GUIDE, moaty-metrics, releases.json, sw.js all updated. 206 tests passing. |
| | First 7d deltas available | Need 7 days of data |
| | First 30d deltas available | Need 30 days of data |
| | First `notebooks/analysis.ipynb` | After 30+ days of data |

---

## Scraper / Pipeline Issues

| Date | Issue | Resolution | Status |
|------|-------|------------|--------|
| 2026-06-09 | CSS selector `.table-groups` wrong | Changed to `.groups_table` | Fixed |
| 2026-06-09 | `wait_until="load"` times out | Changed to `"domcontentloaded"` | Fixed |
| 2026-06-09 | `perf_day` always empty | Copy from `change` column (same value) | Fixed |
| 2026-06-09 | `pytz` + `plotly` missing from requirements.txt | Added | Fixed |
| 2026-06-09 | `na_option='bottom'` missing from rank() calls | Added per spec | Fixed |
| 2026-06-09 | `rel_volume` always NaN | Not served by Finviz for this URL — low priority | Known |

---

## Dashboard Updates

| Date | Feature Added | Notes |
|------|--------------|-------|
| 2026-06-12 | AI tab PWA improvements (all 8 items) | key signals bullets, collapsible briefing, conviction tags, industries rotation phase + watchlist, "what changed" delta card, relative timestamp, native share, phase history strip, historical date navigation |
| 2026-06-09 | Initial 4-tab dashboard | Snapshot, Top Movers, Time Series, Momentum |
| 2026-06-09 | Rank columns in Snapshot tab | rank_day/week/month/ytd joined from deltas |
| 2026-06-09 | CSV download buttons | Snapshot, Top Movers, Momentum tabs |
| 2026-06-09 | Multi-select Time Series | Up to 3 groups, color-coded |
| 2026-06-09 | Heatmap tab (5th tab) | RdYlGn colorscale, gated behind ≥7 days of data |

---

## Decisions Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-06-09 | CSV as source of truth; SQLite/Parquet derived | Binary files bloat Git history |
| 2026-06-09 | Rank computed from perf values, not scraped | Finviz display rank depends on sort order |
| 2026-06-09 | Playwright over Elite subscription | Elite not available; Playwright works at low frequency |
| 2026-06-09 | Positive rank delta = improvement | rank_prior - rank_today; lower rank = better |
| 2026-06-09 | session-notes.md + WORK_LOG.md tracked in Git | Cloud containers are ephemeral — gitignoring loses them |
| 2026-06-09 | `perf_day` sourced from `change` column | Finviz doesn't serve a separate Perf Day column for groups |

---

## Infrastructure Issues

| Date | Issue | Status | Fix |
|------|-------|--------|-----|
| 2026-06-09 | GitHub Actions runners not allocating | Fixed | Enabled in repo Settings → Actions → General |
| 2026-06-10 | `ubuntu-latest` → 24.04 broke playwright deps | Fixed | Pinned `ubuntu-22.04` in collect.yml (PR #?) |
| 2026-06-10 | Silent data loss on workflow_dispatch (no eviction) | Fixed | `collect.py` now raises if 0 rows written (PR #26) |
| 2026-06-10 | Verify step false positive on stale rows | Fixed | Added `collected_at` freshness check ≤30 min (PR #26) |

## 2026-06-09 — Mobile iPhone PWA dashboard shipped (PR #7, merged)

Three static files added to `docs/`: `index.html` (full PWA), `manifest.json`, `sw.js`. Hosted on GitHub Pages — no server required. Fetches CSVs live from `raw.githubusercontent.com` on every load. Three tabs: Today (color-coded perf cards), Movers (rank delta leaderboard, placeholder until ~June 16), Momentum (works immediately). Installable as a home screen app on iPhone via Safari → Add to Home Screen.

## 2026-06-10 — rank_agreement metric + Strength tab (Streamlit + PWA) shipped (PR #17, merged)

`rank_agreement` now accumulates in `deltas.csv` from today — measures how consistently rank_month, rank_quarter, and rank_half agree for each group (1.0 = all timeframes confirm same standing, 0.0 = maximum disagreement). New Strength tab in both Streamlit and PWA surfaces Sustained Strength (top-N in all three timeframes simultaneously) and All Green (all perf timeframes positive, emoji dot matrix). Works on day-1 data since perf_quarter/half are scraped live from Finviz.

## 2026-06-09 — Commit discipline rules and test scaffolding

`.claude/rules/commit-discipline.md` committed — covers small-commit sizing, per-change test requirements, and the session handoff checklist. PR #3 (merged) already delivered the comprehensive 57-test suite; this session contributed the written rules. PR #4 open as draft.

---

## 2026-06-10 — Server-side AI analysis pipeline shipped (PR #25, merged)

Nightly `generate_ai.py` runs after `compute_deltas.py` in GitHub Actions, calling Gemini 1.5 Flash to produce a daily briefing (3 paragraphs, sectors + industries), a rotation phase signal (Early/Mid/Late Cycle/Defensive), and a top-3 sector watchlist with thesis. Output committed to `data/ai/YYYY-MM-DD.json`. Streamlit dashboard has a new 7th "AI Insights" tab that reads the pre-generated JSON — no LLM calls at runtime. API key lives only in GitHub Actions secrets. Requires `GEMINI_API_KEY` secret to be added to the repo to activate. 64 tests passing.

---

Three detection gaps that caused total June 9 data loss are now closed:
- `collect.py` raises `RuntimeError` if 0 rows written after eviction (catches silent dedup no-ops)
- Verify step now checks `collected_at` freshness (≤30 min) in addition to row count, and uses correct pre-9 AM date logic
- PWA Today tab shows pipeline run history from `fetch_log.csv` (last 5 runs, outcome + row counts)

Also captured today's near-close data (4:00 PM ET, market close) via manual workflow_dispatch.

---

## 2026-06-11 — Workflow logging, monitoring, and AI partial completion fix (PR #35, merged)

Three interrelated problems solved in one PR:

**1. AI partial completion bug fixed.** `generate_ai.py` previously skipped re-running if any output file existed for today — even if it only had `sectors.briefing` (which is exactly what happened today: 429 rate-limit interrupted after the first of 4 API calls). The idempotency check now validates all 4 expected fields (`sectors.briefing`, `sectors.rotation_phase`, `sectors.watchlist`, `industries.briefing`). Incomplete files trigger incremental retry: only missing fields are regenerated, preserving what already succeeded.

**2. Structured AI run log.** Every `generate_ai.py` execution now appends to `data/ai_run_log.jsonl` with: per-field outcomes (`ok`/`error`/`skipped`/`no_data`), per-field wall time, rate-limit hit count, total API calls, full error text, and overall outcome. Analogous to CloudWatch structured logs.

**3. Workflow monitoring.** `fetch_log.csv` gains two new columns (`ai_outcome`, `ai_fields_missing`). Schema migration runs automatically on the first workflow execution after the update. The PWA pipeline history section now shows an AI status diamond (◆ green = complete, amber = partial, grey = skipped) per run row. `data/ai_run_summary.json` is a per-run sidecar that collect.yml reads to populate the new columns.

41 new tests added; 122 total passing.

---

## 2026-06-14 — Ticker lookup CF Worker built (TICKER-1, draft PR)

`worker/` Cloudflare Worker: `/lookup?t=SYM` → Finviz sector/industry + profile, 30d
KV cache, `/health`, CORS, structured logging. Corrected the plan's dead FMP endpoint
to `stable/profile` with migrated field names. 28 vitest tests pass; `wrangler deploy
--dry-run` bundles clean. Deploy is owner-gated (interactive `wrangler login` + FMP
secret) — code is ready, awaiting `npm run deploy`.

## 2026-06-17 — Configurable lookbacks + momentum variants

`compute_deltas.py` is now driven by `scripts/delta_config.py` (single source of
truth for the deltas schema). Lookbacks switched from calendar 7/14/30 to
trading-day 5/10/20/50 via position-based `find_trading_date_back` (gap-tolerant).
Added six momentum signals: `momentum_confirmed`, `momentum_weighted_mid`,
`momentum_weighted_fast`, `regime_short_long`, `momentum_accel`, `rank_trend_slope`.
Consumers updated: `export_db.py`/`dashboard/app.py` import `delta_columns()`
(export_db's copy was stale); `docs/index.html` renumbered (full-dynamic is
fast-follow LB-FF1); `generate_ai.py` repointed off the removed `rank_ytd_delta_7d`.
159 tests pass; end-to-end smoke on real sector data verified the 41-column output.
Plan PR #104; implementation on branch `claude/jolly-darwin-fjik54`.

---

## 2026-06-16 — Lookup tab improvements Phase 1 shipped (6 client-side slices)

The PWA Lookup tab now surfaces the derived "moaty" layer per ticker: a
weekly-rank sparkline, Rank Floor + Sustained/Consistent conviction chip, a
breadth dot strip (gating on mo/qtr/half/ytd), evidence-backed SIGNAL copy,
clarity touches (rank-basis label, 30d delta, loading skeleton), and a "Why this
matters" glossary + Finviz/TradingView deeplinks. All client-side in
`docs/index.html`, no pipeline change; SW cache → v4. Live visual pass pending
(Playwright blocked in cloud). PR #97.

---

## 2026-06-15 — Lookup tab improvements Phase 0 (knowledge + plan)

Scoped and documented a client-side uplift to the PWA Lookup tab to surface our
derived "moaty" metrics for a ticker's sector/industry. Landed the pickup-able
plan (`planning/lookup-tab-improvements.md`), a full metric inventory
(`knowledge/moaty-metrics.md`), three ADRs (client-side-first, Rank Floor,
breadth-excludes-week), a CF edge roadmap, and a README "What makes this
different" section. Phase 1 (6 client-side slices in `docs/index.html`) seeded in
SPRINT; no app behavior change yet.

---

## 2026-06-21 — Start Here onboarding intro shipped (3 commits on claude/dreamy-archimedes-3q6ag1)

5-slide first-run carousel + persistent "Start Here" hub section. WELCOME constant (mirrors GUIDE
pattern) drives both surfaces from one array. First-visit auto-opens carousel once via
`fvt_intro_seen_v1` localStorage key; re-openable anytime via ⓘ hub. Cites O'Neil/IBD 37%+12%
stat inline. "Replay intro" button in hub re-opens the carousel. Anti-drift tests guard tab IDs
and verbatim copy sync with `knowledge/product-intro-copy.md`. 212 non-Playwright tests pass.
ONBOARD-DL-UX (deep-link dismiss UX) tracked as a revisit candidate in SPRINT.md.

---

## Open Questions / Future Ideas

- [ ] Confirm Finviz data finalization time (probe intraday)
- [ ] Find historical Finviz-equivalent data for backfill (deferred)
- [ ] Add sub-industry level tracking
- [ ] Consider adding alert when momentum_score crosses threshold
- [ ] Cross-reference with SPY/QQQ volume on same day
- [ ] 6b: Sector → Industry drill-down in dashboard sidebar (L effort)

## 2026-06-19 — Guide & What's New hub (PWA + dashboard)
Implemented planning/whats-new-and-guide.md first pass on branch claude/epic-sagan-njeu84.
PWA gains a header ℹ️ hub (slide-up sheet) with What's New (docs/releases.json) and a Guide
(11-metric glossary copied verbatim from moaty-metrics.md, live-threshold legend, how-to,
search). Unseen-release dot + one-time banner via localStorage fvt_seen_release_v1 with
first-visit seeding. Contextual "why this matters →" deep-links on Today/Movers/Momentum/
Strength. Dashboard sidebar mirrors both (glossary parsed from moaty-metrics.md, What's New
from releases.json). sw.js CACHE v9→v10. New test_guide_releases.py (anti-drift + verbatim
sync + releases validity) and TestPWAHub Playwright class — all green. 3 pre-existing
TestPWALookbackWindows failures are unrelated (fail on base branch too).
