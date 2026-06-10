# Session Notes

> Future Claude: read this immediately at session start. Summarize the current state for the user before doing anything else.

---

## Current Status

**Status:** Complete ✅
**Safe to close:** Yes — PR #26 merged, session notes committed, no open threads
**Waiting on:** Tonight's scheduled cron (22:00 UTC = 6 PM ET) — will overwrite today's near-close data with EOD values
**Open threads:** None

---

## Session: 2026-06-10 — Retrospective + silent-failure gap fixes (PR #26)

### What happened (retrospective)

Three failures combined to lose June 9 EOD data:
1. **Scheduled cron failed** — `ubuntu-latest` was upgraded to 24.04, renaming `libasound2` → `libasound2t64`, breaking `playwright install --with-deps`. Fixed in prior session by pinning `ubuntu-22.04`.
2. **Manual dispatch silently skipped all rows** — The workflow_dispatch ran on commit `edf97817` which didn't yet have `evict_today_rows`. The 2 AM rows already in the CSV for June 9 caused all 155 freshly-scraped rows to deduplicate and write nothing. `collect.py` exited 0; git said "Everything up-to-date". Silent total loss.
3. **Verify step gave false positive** — Old verify only checked row count (`>= 8`). The stale 2 AM rows satisfied this check, so the workflow showed green despite no new data being written.

### What was done

- **Triggered workflow_dispatch at 3:58 PM ET** — captured near-close data at 4:00 PM ET (market close). Stored in `data/fetch_log.csv` and committed as `data: snapshot 2026-06-10`.

- **PR #26 merged** (3 commits — all gap fixes):
  1. `fix: raise RuntimeError in collect.py when 0 rows written after eviction` — `collect()` now raises if `append_records` returns 0 after eviction, so the silent no-op can never repeat.
  2. `fix: verify step uses trading_date logic and checks collected_at freshness` — verify now uses `now_et.hour < 9` date logic (mirrors `trading_date()`), and checks that `max(collected_at)` is within 30 minutes of workflow run time.
  3. `feat: show pipeline fetch history in PWA Today tab` — loads `data/fetch_log.csv` from GitHub, renders last 5 runs with green/red dot, timestamp (ET), trigger, row counts, and failed step.

- **81 tests passing** (1 new test: `test_collect_raises_when_eviction_skipped`)

### Key decisions

- 30-minute freshness limit in verify: scheduled cron runs at 22:00 UTC; Playwright scrape + commit takes <5 min. 30 min gives headroom for runner queueing.
- Pipeline history in PWA (not Streamlit): on-the-go visibility is the high-value case. Five rows is enough to see the last week of weekday runs.

### What's deferred

- **Healthchecks.io**: User still needs to add `HEALTHCHECK_URL` secret. Steps: healthchecks.io → New Check → period 26h → copy URL → repo Settings → Secrets → `HEALTHCHECK_URL`.
- **Pip/playwright CI caching**: explicitly deferred to a separate task per user.

### No open threads

---

## Session: 2026-06-10 — PWA UX polish + collect.py date-stamping fix

### What was done

- **PR #20**: Freshness label improvements — short date format (`Jun 9` not `2026-06-09`) across all cases; cross-midnight collection timestamp prefixed with `"collected"` to disambiguate two dates in the label.
- **PR #21**: 600ms minimum spinner duration on manual refresh (button + pull-to-refresh). Initial page load unaffected. Prevents spinner from flashing and disappearing on fast CDN responses.
- **PR #22**: Haptic feedback (40ms vibration) when pull-to-refresh crosses the release threshold; tap "Finviz Tracker" title scrolls smoothly to top.
- **PR #23**: `collect.py` date-stamping bug fix — `trading_date(now_et)` helper returns the previous calendar day if collection is before 9 AM ET. Prevents delayed GitHub Actions runners from labeling prior-session data with the next day's date. 5 new tests added; 80 total passing.

### Key insight discovered
The `collected_at` timestamp `2026-06-09T06:19:08Z` = 2:19 AM ET June 9 = 11:19 PM PT June 8. The cron ran unusually late (8+ hours past scheduled 22:00 UTC). This caused June 8's closing data to be stamped as `date = 2026-06-09` — now fixed.

### No open threads

---

## Next session — what to work on

Data dependency reminder:
- **Works today (day 1):** Sustained Strength, All Green, rank_agreement — all use Finviz-scraped perf values, no history needed
- **~June 16 (7d data):** INS-4 (Momentum Velocity), INS-5 (Daily Brief card), INS-6 (Momentum Score Heatmap)
- **Anytime (L effort):** INS-7 (Sector Breadth — needs static sector→industry mapping)

### INS-4: Momentum Velocity (~June 16)
`momentum_score` has been accumulating in `deltas.csv` since June 9. Once 7 days exist, add:
- `momentum_score_delta_7d` and `momentum_score_delta_14d` to `DELTA_COLUMNS` in `scripts/compute_deltas.py`
- Same lookback pattern as existing rank delta columns (lines ~257–294 in `compute_for_group()`)
- "Rising Stars" view in dashboard + PWA: positive velocity, currently top-half of momentum leaderboard

### INS-5: Daily Brief card (PWA) (~June 16)
Top-of-screen card in `docs/index.html` showing 2–3 sentences: biggest mover today, who's sustained strong, what's rolling over. Implement as `buildBrief(delta, snap)` → returns HTML string inserted above the tab bar content. Gate behind `hasMoversData` check.

### INS-6: Momentum Score Heatmap (~June 16)
Same structure as Heatmap tab in `dashboard/app.py` (tab 5, ~lines 400–445) but pivot on `momentum_score` instead of a rank delta. Cells = absolute composite score over time. Gate behind ≥7 days same as existing heatmap.

### INS-7: Sector Breadth (anytime)
For each sector: % of constituent industries in top half of full universe. Needs a hardcoded `SECTOR_INDUSTRY_MAP` dict in `dashboard/app.py`. Finviz groups URL at `?g=sector` vs `?g=industry` already has the data — can cross-reference by name. L effort (mostly cataloguing).

### D1 (user action still pending)
No `main` branch exists — default is `claude/elegant-babbage-hlxnfy`. Cron and PWA `BRANCH` constant both hardcode this name. Safe to leave as-is; but if user wants to rename, do D1 first then PWA-1.

---

## Session: 2026-06-10 — PWA bug fixes: timestamp timezone + refresh cache-bust

### What was done

Two user-reported bugs in `docs/index.html` fixed:

**Bug 1 — "Last updated" PT time showed 11pm when data collected at 5pm PT**
- Root cause: `collected_at` is stored UTC (`2026-06-09T06:19:08Z`). Converting to PT gives 11:19 PM PDT on June 8, but the label showed `"2026-06-09 · 11:19 PM PT"` which users read as "June 9 at 11pm" (confusing / seemingly future).
- Fix in `freshnessLabel()`: compare PT calendar date of `collected_at` against the trading date. If they differ (cross-midnight), prepend the PT date: shows `"Jun 8, 11:19 PM PT"` instead of just `"11:19 PM PT"`. Normal cron collections (22:00 UTC = 3pm PDT, same calendar day) are unaffected.

**Bug 2 — Refresh button only worked once then seemed frozen**
- Root cause: `fetchCSV` used PapaParse `download: true` (XHR) without cache-busting. raw.githubusercontent.com CDN caches responses; subsequent refreshes within the cache TTL returned identical data, making the UI appear unchanged. No re-entrancy guard either.
- Fix: added `force` parameter through `fetchCSV` → `loadGroup` → `loadAndRender`. When `force=true`, appends `?_=${Date.now()}` to bypass browser/CDN cache. Added `if (state.loading) return` guard to `window.__refresh` to prevent concurrent calls.

---



### What was done

- **Brainstormed 7 actionable insight features** (see plan file). Prioritized for immediate value vs. data dependency.
- **`rank_agreement` metric** added to `deltas.csv` and `compute_deltas.py`. Converts rank_month/quarter/half to percentiles, measures std of the three, normalizes by 1/√3. Score 1.0 = all timeframes confirm the same trend; 0.0 = maximum disagreement. Requires all 3 columns present (< 3 guard prevents misleading scores from wrong normalizer with 2 values). 75 tests passing.
- **Strength tab — Streamlit** (6th tab): Sustained Strength (top-N in all three timeframes, threshold slider with proper clamping for sectors) + All Green (dot matrix of perf timeframes). HTML escaping on group names.
- **Strength tab — PWA**: same two views via sub-toggle pill. effectiveN = min(topN, n//2) prevents Strong/Weak overlap when topN >= n (sectors, n=11).
- **PR review response**: fixed 4 bugs (slider crash, PWA overlap, 2-col normalization, HTML injection) + SPRINT.md stale formula.

### Key decisions
- `rank_agreement` requires all 3 of rank_month/quarter/half — returning NaN for 2-column fallback is safer than using the wrong _MAX_STD_3 normalizer.
- Slider min/max/default all derived from n_total to stay self-consistent regardless of sectors vs. industries.
- PWA uses effectiveN = floor(n/2) as a hard cap — labels show the actual effective N used.

### Deferred to backlog (INS-4 through INS-7 in SPRINT.md)
- Momentum Velocity (needs 7+ days of history)
- Daily Brief card
- Momentum Score Heatmap
- Sector Breadth (hardest — needs static sector→industry mapping)

---

## Session: 2026-06-10 — PWA small tasks: iOS icon, error display, dead code cleanup

### What was done

Three high-priority small tasks from the sprint backlog completed and merged into PR #14:

- **PWA-2**: Added `<link rel="apple-touch-icon">` in `<head>` with SVG data URI from manifest.json. iOS Safari will now show the icon when user adds app to home screen.
- **PWA-3**: Fixed `showError()` to display errors on the currently active tab instead of always on Today tab. Now network failures on Movers/Momentum tabs show feedback in the correct location.
- **PWA-4**: Dead code cleanup:
  - Removed unused `forceSign` parameter from `fmtPct()` that had unreachable ternary logic
  - Renamed shadowing `delta` variable to `spots` in `moverCard()` for clarity

### PR & CI status
- **PR #14** opened as draft: `claude/sprint-small-tasks-en5pkd` → `claude/elegant-babbage-hlxnfy`
- Changes: 8 additions, 7 deletions in `docs/index.html` only
- CI status: pending (no checks reported yet; should be clean — HTML-only changes)
- No review comments

### Session characteristics
- Focused, short session (3 small tasks from sprint backlog)
- All work committed and pushed
- Sprint board updated to mark PWA-2, PWA-3, PWA-4 as Done

---

## Session: 2026-06-09 — Mobile PWA dashboard

### What was done
- Built `docs/index.html` — full single-page PWA with Today / Movers / Momentum tabs
- Built `docs/manifest.json` + `docs/sw.js` — makes it installable as iPhone home screen app
- Fetches CSVs from `raw.githubusercontent.com` (base branch) on every load; no server needed
- PR #7 opened and merged into `claude/elegant-babbage-hlxnfy`
- README.md updated with tab guide, methodology, and install instructions
- WORK_LOG.md, SPRINT.md, session-notes.md all updated

### User actions still needed
1. **Enable GitHub Pages**: repo Settings → Pages → branch `claude/elegant-babbage-hlxnfy`, folder `/docs` → Save → live in ~2 min
2. **Install on iPhone**: open `https://clarencelam2000.github.io/finviz-groups-tracker/` in Safari → Share → Add to Home Screen

### Current data state
- 1 day of data (2026-06-09). Movers tab shows placeholder.
- Momentum tab works immediately.
- 7d deltas arrive ~2026-06-16; Movers tab lights up then.

---

## Session: 2026-06-09 — Initial build + first live scrape

### What was done
Built the full project from scratch, then validated and fixed the scraper in a second cloud session (with unrestricted network).

**Session 1 (this repo's setup):**
- Created SPEC.md, all scripts, dashboard, GitHub Actions workflow, CLAUDE.md, .claude/rules/

**Session 2 (first live run — another Claude agent):**
- Fixed CSS selector: `.table-groups` → `.groups_table` (the actual class on live Finviz)
- Fixed `wait_until="load"` → `"domcontentloaded"` (analytics scripts block full page load event)
- Added `ignore_https_errors=True` (needed for TLS-proxy in cloud env; harmless in Actions)
- Fixed `perf_day` always empty: Finviz's "Change" column = perf_day; added copy fallback
- Added `pytz` + `plotly` to requirements.txt (were missing, would break GitHub Actions)
- Added `na_option='bottom'` to all rank() calls per spec
- Added `COLLECT_RETRY_DELAY` env var to override retry delays for fast debugging
- Made session-notes.md and WORK_LOG.md tracked in Git (removed from .gitignore)

**First live data: 2026-06-09 — 11 sectors, 144 industries. Pipeline fully verified end-to-end.**

### Key technical discoveries
- `perf_day` and `change` are always identical (both come from Finviz's "Change" column)
- `rel_volume` is always NaN — not served for this custom group URL. Low priority.
- PEG and Volume columns exist on page but are intentionally skipped in HEADER_MAP
- `COLLECT_RETRY_DELAY=0` env var makes retries instant for debugging
- Dashboard all 4 tabs verified with Plotly charts rendering

### Current state
- **Data**: 1 day (2026-06-09). All 7d/14d/30d lookback deltas are NaN — expected, need more data.
- **Pipeline**: collect.py → compute_deltas.py → dashboard fully working.
- **Branch**: Everything on `claude/elegant-babbage-hlxnfy`. No `main` branch yet.
- **GitHub Actions cron**: NOT running — scheduled workflows only fire on the default branch.

### Blockers / user actions needed
1. **Create `main` branch or set `claude/elegant-babbage-hlxnfy` as default branch** — this is the only thing blocking automated daily collection. GitHub → Settings → Branches.
2. **Run collect.py intraday** on a trading day (10am, 1pm, 4pm, 6pm ET) to find when Finviz finalizes data.

### Next steps (prioritized)
1. [ ] Set default branch → cron activates automatically
2. [ ] Intraday probing to confirm 22:00 UTC cron is right timing
3. [ ] After ~7 days of data: first meaningful 7d deltas, start reviewing movers
4. [ ] After ~30 days: full delta set, build `notebooks/analysis.ipynb`
5. [ ] Dashboard polish: multi-select Time Series, rank_day in snapshot view, heatmap tab

---

## Session: 2026-06-09 — Sprint: robustness, tests, dashboard features

### What was done

All "Pre-Data Improvements" sprint tasks completed (see `.claude/SPRINT.md`):

- **Test infrastructure**: 56 pytest tests across 3 test files — all green locally
  - `tests/test_collect_parsing.py`: parse_perf, parse_market_cap, parse_avg_volume, parse_table, append_records, collect() row-count guard (T7)
  - `tests/test_compute_deltas.py`: find_nearest_date, compute_ranks, compute_for_group (integration), ensure_deltas_csv (T9)
  - `tests/test_momentum.py`: compute_momentum NaN edge cases
- **`rank_day` metric** added to `DELTA_COLUMNS` in `compute_deltas.py`; existing CSVs auto-migrated by extended `ensure_deltas_csv()`
- **Momentum score NaN fix**: all-NaN/missing perf columns excluded from mean instead of inserting full-column NaN
- **`compute_for_group()`** refactored with optional `snap_path`/`delta_path` kwargs for testability
- **`collect.py` hardening**: row-count guard (RuntimeError on 0 rows, warn below floor), unknown column summary logging, fetch timing
- **Dashboard**: rank columns in Snapshot tab, CSV download buttons, multi-select Time Series (up to 3, color-coded), new Heatmap tab (gated behind ≥7 day data guard)
- **GitHub Actions `collect.yml`**: timeout-minutes: 30, post-collect row-count verification step
- **`tests.yml`** CI workflow added (T8) — YAML is correct but see blocker below
- **`requirements-dev.txt`** (pytest==8.2.2, pytest-mock==3.14.0) and **`requirements-test.txt`** (minimal CI deps) added
- **`.claude/SPRINT.md`** sprint board committed to repo
- **PR #3 merged** into `claude/elegant-babbage-hlxnfy`

### Key technical discoveries
- `compute_for_group()` now accepts `snap_path`/`delta_path` kwargs — tests use `tmp_path`, no monkeypatching of DATA_DIR needed
- `ensure_deltas_csv()` detects header mismatch and rewrites the file in-place, preserving all existing rows
- `requirements-test.txt` exists to avoid Python 3.12 incompatibility with `notebook`/`ipykernel` packages in the main `requirements.txt`

### Current blockers

#### ⚠️ GitHub Actions runners not allocating — ALL CI fails instantly

**Symptom**: Every workflow run (push, pull_request, workflow_dispatch) completes in ~3-4 seconds with `runner_id: 0`, `runner_name: ""`, and logs 404. Zero `collect.yml` run history also exists — the data CSVs were populated locally, never via scheduled Actions.

**Root cause**: Almost certainly **GitHub Actions is disabled at the repository level**. `runner_id: 0` means GitHub rejects the job before even attempting to queue it — this is not a billing issue (billing failures still allocate runners).

**Fix (one click)**: Go to **GitHub → repo Settings → Actions → General** → change "Disable actions" to "Allow all actions and reusable workflows" → Save.

**What to do after fixing**:
1. Re-add `push` and `pull_request` triggers to `tests.yml` (they were removed to stop noise — see commit `0e1bc6e`)
2. Push a commit to confirm a real runner is allocated (run_id will have non-zero runner_id, logs will be available)
3. Verify the 57 tests pass in CI

---

## Session: 2026-06-09 — Commit discipline rules and test scaffolding

### What was done

- Wrote `.claude/rules/commit-discipline.md` — three sections:
  1. Keep commits small: sizing guide, "too large" signals, slice → commit → push workflow
  2. Testing requirements: coverage table by change type, testable pure functions, fixture pattern
  3. Session handoff checklist: what goes in session-notes vs WORK_LOG, 5-item end-of-session checklist
- **Draft PR #4** open: `claude/commit-testing-best-practices-nfxsmn` → `claude/elegant-babbage-hlxnfy`

### Rebase note
PR #3 landed mid-session with a comprehensive test suite (57 tests). When rebasing:
- Kept PR #3's `tests/test_compute_deltas.py` (more thorough — integration tests, rank_day coverage)
- Reverted `requirements.txt` pytest addition (pytest already in `requirements-dev.txt` from PR #3)
- Only net-new artifact from this session: `.claude/rules/commit-discipline.md`

### Current state
- 57 tests passing (`python3 -m pytest tests/ -q`)
- Two open draft PRs: PR #3 is merged; PR #4 (`commit-discipline.md`) awaiting review
- No CI running (GitHub Actions runner issue still open)

### Next steps (prioritized)
1. [ ] **Fix GitHub Actions**: repo Settings → Actions → General → enable. Then re-add push/PR triggers to `tests.yml`.
2. [ ] **Merge PR #4** (just the rules doc — trivial review)
3. [ ] **Confirm cron is running** after enabling Actions
4. [ ] **~2026-06-16**: 7d deltas arrive — Heatmap and Top Movers become useful
5. [ ] **6b (Sector → Industry drill-down)**: Backlog, L effort
