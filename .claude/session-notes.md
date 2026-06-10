# Session Notes

> Future Claude: read this immediately at session start. Summarize the current state for the user before doing anything else.

---

## Current Status

**Status:** Complete ✅
**Safe to close:** Yes — PRs #10–#13 all merged
**Waiting on:** Nothing
**Open threads:**
- Trigger `workflow_dispatch` on Daily Snapshot to confirm ubuntu-22.04 fix end-to-end: https://github.com/clarencelam2000/finviz-groups-tracker/actions/workflows/collect.yml
- Set up healthchecks.io: create check (26h period, 1h grace) → add ping URL as `HEALTHCHECK_URL` secret in repo Settings → Secrets → Actions

> Update this block at the end of every working block. Options: `Complete ✅` / `In Progress 🔄` / `Blocked 🔴` / `Needs User Input ⚠️`

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
