# Session Notes

> **Future Claude:** read this immediately at session start. Summarize the current state for the user before doing anything else.
>
> **Format:** Append a new `---` delimited block per session. Header = date + workstream description. Keep the last 4 sessions here; a human will periodically move older entries to `.session/archive/session-notes-archive.md`. Do NOT replace existing entries — append only.

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

## 2026-06-25 — Picks cron dispatcher plan (PICKS-2-CRON)

**Status: PLAN COMPLETE. IMPLEMENTATION READY FOR NEXT SESSION.**

Plan written and docs committed to `claude/picks-cloudflare-cron-f0t7fz`. Extend `finviz-cron-dispatcher` with a 4th cron `31 22 * * 1-5` (22:31 UTC = 6:31 PM EDT). Routes by `event.cron` — picks cron dispatches `collect_picks.yml`. GitHub cron retired from `collect_picks.yml` (50-page scrape too expensive to misfire). Healthchecks.io dead-man's-switch planned.

**VP action item:** create healthchecks.io monitor (period=24h, grace=2h) and add `PICKS_HEALTHCHECK_URL` as repo secret before implementation merges.

**Safe to close.** Next session: implementation (worker-cron/ + collect_picks.yml).

---

## 2026-06-30 — Phase A: HoD price-basis toggle for Picks risk panel

**Status: PHASE A COMPLETE. SAFE TO CLOSE. PR #205 open.**

What landed (all in one commit on `claude/hod-price-basis-toggle-phase-a-8o28by`):
- `docs/index.html` — 4 edits:
  1. `deriveRiskMetrics(row, basis)` pure JS function + `window.__buildRiskBasisContent(rowData, basis)`
  2. `renderPickRow` if-expandable block: `data-row-json` attribute, `[ Last | HoD ]` toggle buttons, `risk-basis-content-{key}` wrapper
  3. `__togglePickRow` resets basis on collapse; new `__setPickBasis(key, basis)` function
  4. GUIDE `price_basis` entry (verbatim-synced with moaty-metrics.md)
- `docs/releases.json` — v2026.06.30 entry; `current` bumped
- `docs/sw.js` — CACHE finviz-v35 → finviz-v36
- `knowledge/moaty-metrics.md` — `price_basis` section added
- `planning/picks-hod-price-basis-toggle.md` — status line updated to Phase A shipped
- `tests/fixtures/picks_latest.csv` — TESTHOD row added (Price=100, High=200, ATR=5 for trim→extended test)
- `tests/test_pwa_picks_hod.py` — 5 new Playwright tests (require chromium)
- `.session/SPRINT.md` — PICKS-3E done; PICKS-3E-HOD-PHASE-B tracking task added

531 non-Playwright tests pass. Playwright HoD tests require `playwright install chromium` to run.

Next for this workstream:
- **Phase B** (PICKS-3E-HOD-PHASE-B): global tab-level [ Last | HoD ] toggle that re-ranks the entire Focus list on HoD metrics. Design complete in `planning/picks-hod-price-basis-toggle.md` §4. Prerequisite: validate Phase A in prod first.
- **PICKS-3D polish**: true inside-day H/L (schema bump), fundamental floor, search/filter, sort toggles.
