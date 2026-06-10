# Sprint: Pre-Data Improvements
**Branch:** `claude/explore-plan-next-steps-3jlhmh`  
**Goal:** Build robustness, tests, and dashboard features while waiting for data to accumulate (7d deltas arrive ~2026-06-16; full 30d picture ~2026-07-09)

---

## Board

### 🔴 Backlog

| # | Task | File(s) | Effort | Notes |
|---|------|---------|--------|-------|
| D1 | **[USER ACTION] Create `main` branch, set as default** | GitHub UI | S | Blocks cron and PWA-1. Merge `claude/elegant-babbage-hlxnfy` → new `main`, then Settings → Branches → change default. |
| PWA-1 | Fix hardcoded `BRANCH` constant in PWA | `docs/index.html` line ~117 | S | Change `'claude/elegant-babbage-hlxnfy'` to `'main'` (or whichever branch receives daily cron data). Depends on D1. |
| INS-1 | **Sustained Strength / "Evergreen" list** | `dashboard/app.py`, `docs/index.html` | M | Filter: rank_month AND rank_quarter AND rank_half all ≤ threshold (slider). Works on day 1 — perf_quarter/half scraped live from Finviz. Flip side: Consistently Weak list. Days-on-list counter needs rolling history. |
| INS-2 | **`rank_agreement` metric in deltas.csv** | `scripts/compute_deltas.py`, `tests/` | M | `1 - std([rank_month, rank_quarter, rank_half]) / max_rank`. Near 1 = all timeframes confirm trend; near 0 = conflicting signals. Start accumulating now. |
| INS-3 | **All Green filter + dot matrix visual** | `dashboard/app.py` | S | Industries where perf_week, perf_month, perf_quarter, perf_half, perf_ytd all positive. Works day 1. Dot matrix: green/red per timeframe per row. |
| INS-4 | **Momentum Velocity (`momentum_score_delta_7d/14d`)** | `scripts/compute_deltas.py` | M | Track momentum_score change over time. "Rising Stars" = positive velocity + currently top-half. Needs 7+ days of data. |
| INS-5 | **Daily Brief card (PWA top-of-screen)** | `docs/index.html` | M | Single card: today's breakout, sustained leaders, what's rolling over. Eliminates tab-hopping on mobile. Needs 7+ days for interesting content. |
| INS-6 | **Momentum Score Heatmap (time × industry)** | `dashboard/app.py` | S | Companion to existing rank-delta heatmap — cells = `momentum_score` over time. Absolute picture of sustained leaders. Needs 7+ days. |
| INS-7 | **Sector Breadth** | `dashboard/app.py` | L | % of industries in a sector that are top-half of full universe. Needs static sector→industry mapping (11 sectors × 144 industries). Hardest feature. |
| PWA-2 | Add `<link rel="apple-touch-icon">` for iOS homescreen icon | `docs/index.html` `<head>` | S | Safari ignores web manifest icons for Add-to-Home-Screen; needs explicit `apple-touch-icon` tag. Can reuse the SVG data URI from `manifest.json`. |
| PWA-3 | Show error on active tab (not just Today) | `docs/index.html` `showError()` | S | Network failures on Movers/Momentum tabs show empty containers with no feedback. Display error in whichever tab is active. |
| PWA-4 | Dead code cleanup: `fmtPct` forceSign + `moverCard` delta shadowing | `docs/index.html` | S | `forceSign` param is never passed `true`; inner ternary always resolves to `''`. `delta` variable in `moverCard` shadows outer array — rename to `spots`. |
| DEBT-1 | `evict_today_rows` concurrency race | `scripts/collect.py` | S | Two simultaneous `collect.py` processes could race on read-modify-write. Non-issue given single scheduled Action + ad-hoc manual runs. Fix would be a file lock (e.g. `fcntl.flock`). Table until concurrency is actually needed. |
| DEBT-2 | `evict_today_rows` I/O errors not caught | `scripts/collect.py` | S | Disk-full / permission errors bubble up as exceptions. Intentional — matches rest of codebase. Could add explicit error message if this causes confusion in prod logs. |
| 6b | Sector → Industry drill-down | `dashboard/app.py` | L | Hardcode `SECTOR_INDUSTRY_MAP` (11 sectors → 144 industries) in `app.py`. Sidebar selectbox filters all tabs. Effort is mostly cataloguing the mapping, not code. |

> **D1 note — the elegant-babbage debt**: `claude/elegant-babbage-hlxnfy` is currently the default branch (no `main` exists). GitHub Actions cron only fires on the default branch, and the PWA hardcodes this branch name. D1 is the root fix; PWA-1 is the code follow-up. Until D1 is done, the cron data will keep landing on `elegant-babbage` — so don't change the `BRANCH` constant before D1 is complete.

---

### 🟡 Ready

_(nothing)_

---

### 🟢 In Progress

_(nothing)_

---

### ✅ Done

| # | Task | Date |
|---|------|------|
| PWA-2 | Add `<link rel="apple-touch-icon">` for iOS homescreen icon | 2026-06-10 |
| PWA-3 | Show error on active tab (not just Today) | 2026-06-10 |
| PWA-4 | Dead code cleanup: `fmtPct` forceSign + `moverCard` delta shadowing | 2026-06-10 |
| — | First live scrape: 11 sectors, 144 industries | 2026-06-09 |
| — | End-to-end pipeline verified (collect → deltas → dashboard) | 2026-06-09 |
| — | GitHub Actions cron wired (weekdays 22:00 UTC) | 2026-06-09 |
| — | Scraper fixes: CSS selector, domcontentloaded, TLS, perf_day | 2026-06-09 |
| 1 | Test infrastructure: 50 tests, all green (`pytest tests/ -v`) | 2026-06-09 |
| 2a | `rank_day` metric added to delta schema; existing CSVs auto-migrated | 2026-06-09 |
| 2b | Momentum score NaN fix: all-NaN columns excluded from mean | 2026-06-09 |
| 3a | Rank columns (rank_day/week/month/ytd) in Snapshot tab | 2026-06-09 |
| 3b | CSV export buttons on Snapshot, Top Movers, Momentum tables | 2026-06-09 |
| 3c | Multi-select Time Series (up to 3 groups, color-coded) | 2026-06-09 |
| 4a | `collect()` post-parse row-count guard (RuntimeError on 0 rows) | 2026-06-09 |
| 4b | Unknown Finviz column names logged as summary line to stderr | 2026-06-09 |
| 4c | `fetch_html()` runtime timing logged | 2026-06-09 |
| 5a | GitHub Actions job timeout: `timeout-minutes: 30` | 2026-06-09 |
| 5b | GitHub Actions post-collect row-count verification step | 2026-06-09 |
| 6a | Heatmap tab (RdYlGn; gated behind ≥7 day data guard) | 2026-06-09 |
| T7 | Test: `collect()` row-count guard — 56 tests, all green | 2026-06-09 |
| T8 | GitHub Actions CI workflow (`tests.yml`) — YAML correct; see note below | 2026-06-09 |
| T9 | Test: `ensure_deltas_csv` all 3 paths | 2026-06-09 |
| R1 | `.claude/rules/commit-discipline.md` — commit sizing, test requirements, handoff checklist | 2026-06-09 |
| M1 | Mobile iPhone PWA (`docs/`): Today / Movers / Momentum tabs; GitHub Pages; Add to Home Screen | 2026-06-09 |

---

## Known Issue: GitHub Actions Runners

Every workflow run in this repo fails instantly (`runner_id: 0`, completes in ~4s, logs 404). This affects **all** trigger types: `push`, `pull_request`, and `workflow_dispatch`. Zero `collect.yml` runs exist in the Actions history either — confirming the data CSVs were all populated locally, not via CI.

**Root cause:** GitHub Actions runners are not being allocated for this account/repo. This is likely a billing or account-level restriction, not a YAML issue. The `tests.yml` and `collect.yml` YAML files are structurally correct and will work on any standard GitHub account with Actions enabled.

**To fix:** Check GitHub account → Settings → Billing → Actions usage, or enable Actions under repo Settings → Actions → General.

---

## Effort Key
| Label | Time |
|-------|------|
| S | < 1h |
| M | 1–2h |
| L | 2–4h |

---

## Next Milestones

| Date | Event |
|------|-------|
| ~2026-06-16 | 7d deltas available — Heatmap + Top Movers light up |
| ~2026-06-23 | 14d deltas available |
| ~2026-07-09 | 30d deltas available — full picture |

After 7d data arrives: consider adding `rank_day_delta_7d` to the delta schema (same pattern as `rank_week_delta_7d`).

---

## Verification Checklist

- [x] `pytest tests/ -v` — 56 tests pass
- [x] `python scripts/compute_deltas.py` — migrates existing CSVs, `rank_day` in output
- [x] Dashboard: rank cols in Snapshot, download buttons, Time Series multiselect, Heatmap "need 7 days" message
- [x] GH Actions `collect.yml` — timeout + row-count step present
- [x] Push branch; draft PR #3 created
- [x] T7: `collect()` guard tests added (TestCollectRowCountGuard)
- [x] T8: `tests.yml` CI workflow YAML added and correct (runner allocation issue is account-level)
- [x] T9: `ensure_deltas_csv` path tests added (TestEnsureDeltasCsv)
