# Session Notes Archive

> Older session entries moved here periodically by a human reviewer. Not auto-loaded.
> Newest entries at the top.

---

## 2026-06-28 — Phase 3c: Lookup Stage-2 section + Finviz deep-link button

**Status: PHASE 3c COMPLETE. PR OPEN. SAFE TO CLOSE.**

What landed:
- `docs/index.html` — `slugifyGroup()` + `buildScreenerUrl()` helpers; `renderLookupStage2()`; Stage-2 section hooked into BOTH `renderLookup()` branches (group-by-name + ticker→group); 4 BUTTON_* constants (BUTTON_V, BUTTON_BASE_FILTERS, BUTTON_SORT, BUTTON_FT) inlined near ATR_EXT_* constants block
- `docs/releases.json` — v2026.06.28 entry, tag "feature", tab "lookup"
- `docs/sw.js` — CACHE bumped to finviz-v33
- `tests/test_picks_button_config.py` — NEW: 9 tests (4 BUTTON_* anti-drift + 5 sector-slug tests)
- `CLAUDE.md` / `README.md` — 4 BUTTON_* constants triple-documented
- `planning/stock-picks-from-leading-groups.md` — Phase 3c marked COMPLETE
- `.session/SPRINT.md` — PICKS-3C marked Done

478 tests pass (9 new for Phase 3c).

**Phase 3d next:** inside-day polish, fundamental floor, Focus stacked-stop bonus, staleness banner.

---

## 2026-06-27 — Phase 3b: expandable risk panel + All/Focus toggle + Focus scoring

**Status: PHASE 3b COMPLETE. SAFE TO CLOSE.**

What landed:
- `docs/index.html` — `renderPickRow()` (module-level, 3b.0), expandable risk panel (3b.1), All/Focus toggle + `computeFocusScores()` (3b.2), 6 new constants (ATR_EXT_PENALTY_START, PENALTY_MAX, FOCUS_W_GROUP, FOCUS_W_TIGHT, FOCUS_W_QUIET, FOCUS_MIN_POOL), GUIDE entry for `focus_score`, `switchTab()` resets picksView='all' on tab entry (A4)
- `docs/releases.json` — v2026.06.27 entry, tag "feature", tab "picks"
- `docs/sw.js` — CACHE bumped to finviz-v32
- `knowledge/moaty-metrics.md` — `focus_score` entry
- `CLAUDE.md` / `README.md` — 6 Focus constants triple-documented
- `planning/stock-picks-from-leading-groups.md` — Phase 3b marked COMPLETE
- `tests/fixtures/picks_latest.csv` — 13th row: TESTAB20 (above50/below20 test case)
- `.session/SPRINT.md` — PICKS-3B marked Done

Playwright tests for 3b (`tests/test_pwa_picks.py`) written but deferred to separate branch `claude/pwa-picks-playwright-tests` pending cloud infra fix. Non-blocking.

---

## 2026-06-26 — Phase 3a: Picks tab MVP + backend derived metrics

**Status: PHASE 3a COMPLETE. SAFE TO CLOSE.**

What landed:
- `scripts/picks_metrics.py` — pure backend module: parsers + `compute_metrics_row()` for 5 METRICS_COLS
- `scripts/picks_config.py` — updated: METRICS_COLS added, `picks_columns()` now returns 113 cols
- `scripts/collect_picks.py` — updated: `ensure_picks_csv()` migration + `build_pick_rows()` computes metrics at scrape time
- `tests/test_picks_metrics.py` — 39 tests
- `tests/fixtures/picks_latest.csv` — 12-row 113-col EOD fixture
- `docs/index.html` — Picks tab button, section, loadPicks, renderPicks, C6 filter, C4 color bands, 5 GUIDE entries, WELCOME updated to 7 tabs, GUIDE_TAB_CHIPS updated, INTRO_KEY bumped to v2
- `docs/releases.json` — v2026.06.26 entry, tag "feature", tab "picks"
- `docs/sw.js` — CACHE bumped to finviz-v31
- `CLAUDE.md` / `README.md` — 3 new PWA constants triple-documented (MIN_MARKET_CAP_B, ATR_EXT_ACTIONABLE, ATR_EXT_TRIM)

522/522 non-Playwright tests pass. **Phase 3b next.**

---

## 2026-06-24 — Sector→industry hierarchy foundation complete

`data/finviz_sector_industry_map.json` merged (PR #171) — 11 sectors, 144 industries, 100% match against live snapshots. Full 22-feature hierarchy roadmap written to `planning/PLAN_sector_industry_hierarchy.md`. Sprint board updated with HIR-* tasks. Two items immediately unblocked: TASK-6B (Streamlit sidebar filter) and INS-7 (Sector Breadth).

---

## 2026-06-24 — Phase-1.5 spike: selector policy locked with VP

**Key findings:**
- All-green count: 21–46/day (self-shrinks on weakness — correct).
- `momentum_accel` is all NaN on all 10 dates (needs 11 sessions; unlocks ~Jun 25).
- `rs_score > 0.5` floor on `emerging` essential — drops qualifying count from 39–50 → 3–4 but removes noise.
- Sustained_strength most stable (Jaccard 0.691 avg); momentum_confirmed more responsive (0.605). Hybrid (8+2) captures both.

**Decisions locked (VP 2026-06-24):**
- Leaders metric: 8 by sustained_strength + 2 freshness fills by momentum_confirmed
- Anti-flash floor: Top 40% cross-sectional percentile by `momentum_score`
- Slot split: 10/4/3/3 (cap=20)

**Docs updated:** `planning/stock-picks-from-leading-groups.md` status block + Spike section.

**Not committed (Phase-1, paused per VP):** `scripts/probe_picks.py` + `.github/workflows/probe_picks.yml`.

---

## 2026-06-23 — Cron schedule adjustment for market hours

Updated `worker-cron/wrangler.toml` cron times to better align with US market hours. Key finding: Cloudflare Cron does NOT support timezone/DST. Manual adjustment required on Nov 2, 2026 (EDT→EST) and Mar 9, 2027 (EST→EDT). PR #168 opened.

---

## 2026-06-21 — Start Here onboarding intro

Implemented `planning/start-here-onboarding.md` in full. WELCOME constant (5-slide array), "Start Here" hub section, full-screen carousel, `fvt_intro_seen_v1` localStorage key. Anti-drift tests in `tests/test_pwa_intro.py`. `knowledge/product-intro-copy.md` canonical copy source. Release v2026.06.21, sw.js CACHE → v19.

---

## 2026-06-20 — ETF lookup overrides (ETF-1)

PR #137 merged. `data/etf_overrides.csv` — 31 curated ETFs. `build_taxonomy.js` extended to emit `etf_overrides.json`. `lookupEtf()` in `taxonomy.js`. PWA `renderLookup()` updated with thematic/sector/diversified card variants. ADR-005 written. releases.json 2026.06.20, SW cache v17→v18.

---

## 2026-06-20 — Lookup search enhancements (Ideas 1–7)

Ideas 1–4 (PR #131 merged): local group name search, typeahead dropdown, expanded group card, SW cache v15→v16.
Ideas 5–7 (PR #134): recent searches, pinned favorites, empty-state momentum chips, synonym map, fuzzy "did you mean". SW cache v17→v18, releases.json 2026.06.21.

---

## 2026-06-19 — Cloudflare Cron Scheduler live

PR #122 merged. Worker `finviz-cron-dispatcher` deployed. All three weekday cron triggers active. Live validation: end-to-end POST returned HTTP 204, `collect.yml` run #38 launched. KV namespace connected. Phase 3 (edge-scrape spike) deferred.

---

## 2026-06-19 — Guide & What's New hub

PWA header ℹ️ hub (slide-up sheet) with What's New (`docs/releases.json`) + Guide (11-metric glossary). Unseen dot + one-time banner. Contextual "why this matters →" deep-links. Dashboard sidebar mirrors both. SW cache v9→v10. `tests/test_guide_releases.py` + TestPWAHub Playwright class green.

---

## 2026-06-17 — Lookback config + momentum variants

`scripts/delta_config.py` single source of truth — `LOOKBACK_WINDOWS=[5,10,20,50]`. Trading-day lookbacks via `find_trading_date_back` (position-based, gap-tolerant). Six momentum variants added. PWA minimal window renumber. `generate_ai.py` repointed. 159 tests pass. LB-FF1 tracked in SPRINT (PWA full-dynamic windows).

---

## 2026-06-16 — Date/timezone hardening + stale-delta fix

Real bug: daily cron fired Sat/Sun, re-scraping stale close. `trading_date()` rolled Monday-pre-9am to Sunday. Stale-delta `existing_keys` guard locked first-run ranks. Fixes: `existing_keys` removed (last-write-wins), `trading_date()` rolls weekends + Monday-pre-open to preceding Friday, crons changed to weekday-only. Phantom weekend rows purged (Jun 13/14). CLAUDE.md Automation section updated.

---

## 2026-06-16 — Lookup tab improvements Phase 1

Six Phase 1 slices in `docs/index.html`: rank sparkline, conviction info (Rank Floor + Sustained/Consistent chip), breadth strip, RS spread chips, moat score, export button. Each its own commit with paired SPRINT + plan-doc updates.
