# Sprint: Pre-Data Improvements
**Branch:** `claude/explore-plan-next-steps-3jlhmh`  
**Goal:** Build robustness, tests, and dashboard features while waiting for data to accumulate (7d deltas arrive ~2026-06-16; full 30d picture ~2026-07-09)

---

## Board

### 🔴 Backlog

#### Ticker Lookup Feature

Full plan: `planning/PLAN_ticker_lookup.md`

| # | Task | File(s) | Effort | Notes |
|---|------|---------|--------|-------|
| ~~TICKER-0~~ | ~~**Taxonomy map: FMP → Finviz (Claude session)**~~ | `data/taxonomy_map.csv`, `data/fmp_sample_profiles.json`, `knowledge/fmp-api-findings.md` | S | **Done 2026-06-14.** Sampled 242 live FMP profiles → 129 unique FMP industries; built 133-row map, all Finviz names validated, 132/144 Finviz industries reachable (FMP coarser in 12 — documented). 12 low-confidence rows flagged. Evidence + API findings committed. |
| ~~TICKER-1~~ | ~~**CF Worker: /lookup endpoint + KV cache**~~ | `worker/src/index.js`, `worker/wrangler.toml`, `worker/src/taxonomy_map.json`, `worker/package.json`, `worker/README.md`, `worker/test/index.test.js` | M | ✅ **Done — deployed live 2026-06-14:** `https://finviz-ticker-lookup.salmonbaby8.workers.dev`. Code merged PR #74; deployed headlessly via `CLOUDFLARE_API_TOKEN` from a Claude Code web session (KV namespace `3ae4430b…`, FMP key set as Worker secret). 28 vitest tests pass; `/health`, `/lookup?t=AAPL` (→ Technology / Consumer Electronics, conf 1.0, KV cache verified), `/lookup?t=FAKEXYZ` (→ ticker_not_found) all pass live. Headless deploy writeup: `knowledge/cloudflare-headless-deploy.md`. |
| ~~TICKER-2~~ | ~~**PWA Lookup tab**~~ | `docs/index.html` | M | ✅ **Done 2026-06-14.** New "Lookup" tab wired to live Worker (`WORKER_URL`). Ticker input → `/lookup` → company header (logo/exchange/mktcap/confidence) + industry perf card + sector perf card + FAVORABLE/MIXED/CAUTION signal. Joins to already-loaded `state.data.{sectors,industries}.{delta,snap}` by exact Finviz group name (verified match). sessionStorage cache; graceful error cards. |
| ~~TICKER-3~~ | ~~**Streamlit Lookup tab**~~ | `dashboard/app.py`, NEW `dashboard/worker_client.py`, `requirements.txt`, `requirements-test.txt`, NEW `tests/test_worker_client.py` | M | ✅ **Done 2026-06-14.** Tab 8 "Ticker Lookup": calls live Worker via pure `lookup_ticker()` (no st import → testable), renders company header + Finviz classification + industry/sector `_render_group_card` (rank/momentum/perf joined to latest CSV date). `WORKER_URL` from `st.secrets`/env with live default. `requests==2.33.1` pinned. 4 new tests in `test_worker_client.py` (168 passed total, ex-playwright). |
| ~~TICKER-4~~ | ~~**Operations setup**~~ | — | — | ✅ **Done 2026-06-15.** Added FMP call counter (daily KV key `fmp_calls_YYYY-MM-DD`, 7d TTL), `/stats` endpoint returning `{date, fmp_calls_today}`, `DELETE /cache?t=TICKER` for manual cache busting. Counter incremented only on FMP cache misses, never on errors. 34 vitest tests pass. PR #90 merged. |
| TICKER-5 | **[FUTURE] Sector/Industry → Stocks screener** | `worker/src/index.js` (add /stocks endpoint), `docs/index.html`, `dashboard/app.py` | M | New Worker endpoint `/stocks?finviz_sector=&finviz_industry=` calls FMP screener, returns top 25 by market cap, KV cache 7d. Both front-ends add "Show stocks" toggle on group cards. Do NOT start until TICKER-0 through TICKER-4 are validated in production. See Phase 7 in plan. |

> **Phase 0:** (1) FMP free account + API key ✅ done. (2) Cloudflare account + KV namespace ✅ done — Worker deployed 2026-06-14.

> **Monthly recurring:** CF analytics check, FMP quota check, taxonomy validity spot-check. See plan Phase 5.

---

#### Lookup Tab Improvements

Full plan: `planning/lookup-tab-improvements.md`. ADRs: `knowledge/decisions/ADR-001..003`. Metric inventory: `knowledge/moaty-metrics.md`. Develop on `claude/lookup-tab-improvements-h7nw9b`. All Phase 1 slices are client-side in `docs/index.html` (no pipeline change, HTML-only — note in commits).

| # | Task | File(s) | Effort | Notes |
|---|------|---------|--------|-------|
| ~~LOOK-0~~ | ~~**Phase 0: knowledge + plan + README moat**~~ | `planning/lookup-tab-improvements.md`, `knowledge/moaty-metrics.md`, `knowledge/decisions/ADR-001..003`, `knowledge/cloudflare-edge-roadmap.md`, `README.md`, `.session/SPRINT.md` | S | Pickup-able plan, metric inventory, 3 ADRs, CF roadmap, README "What makes this different" section. No behavior change. |
| ~~LOOK-1~~ | ~~**Slice 1: retain history + weekly-rank sparkline**~~ | `docs/index.html`, `docs/sw.js` | M | ✅ **Done 2026-06-16.** `loadGroup` now retains full delta history in `state.data[group].deltaAll` (latest-only `.snap`/`.delta` untouched). New `groupRankHistory()` + `rankSparkline()` render an inline SVG of `rank_week` over the last ~30d in each group card, y inverted (up = improving), green/red by net direction, labeled "Weekly rank · last Nd". Hidden when <2 points. SW cache → v4. |
| ~~LOOK-2~~ | ~~**Slice 2: conviction chip + Rank Floor**~~ | `docs/index.html` | M | ✅ **Done 2026-06-16.** New `convictionInfo(delta, n)`: Rank Floor = max(rank_month, rank_quarter, rank_half) → "Top #{floor} across 1/3/6mo" row. Chip = "Sustained" (floor ≤ top quartile, emerald) / "Consistent" (rank_agreement ≥ 0.85 AND floor ≤ top half, sky) / hidden. Returns null gracefully if the 3 ranks aren't all present. Chip shown top-right of each group card. |
| ~~LOOK-3~~ | ~~**Slice 3: breadth dot strip**~~ | `docs/index.html` | S | ✅ **Done 2026-06-16.** `breadthStrip(snap)` renders D·W·M·Q·6M·Y dots (green/red/grey per `perf_*` sign) + an "All green" badge or "k/4 green" count. Verdict gates on month/quarter/half/ytd only via `BREADTH_TFS[].gate`; day & week dots render but don't gate (ADR-003). |
| ~~LOOK-4~~ | ~~**Slice 4: evidence-backed SIGNAL copy**~~ | `docs/index.html` | S | ✅ **Done 2026-06-16.** New `groupReasons(name, gd, n)` extracts concrete signals (30d/7d rank trajectory, conviction+floor, momentum %, breadth k/4). `contextSignalCard` appends the 2–3 strongest (industry first) as an evidence line under the verdict. Scoring spine + thresholds unchanged. |
| ~~LOOK-5~~ | ~~**Slice 5: clarity wins**~~ | `docs/index.html` | S | ✅ **Done 2026-06-16.** Rank label now "Rank (wk)"; added a 30d rank-delta chip (`rank_week_delta_30d`, "▲N over 30d") beside the weekly arrow; replaced "Looking up…" text with `lookupSkeleton()` matching the result layout. |
| ~~LOOK-6~~ | ~~**Slice 6: QoL — glossary + info affordance + deeplinks**~~ | `docs/index.html` | M | ✅ **Done 2026-06-16.** `lookupGlossary()` = collapsed "Why this matters" `<details>` (copy from `knowledge/moaty-metrics.md`) covering rank/floor/sustained/momentum/breadth incl. the percentile basis (folds in the info affordance). Subtle Finviz (`quote.ashx?t=`) + **TradingView** (`/symbols/SYM/`) deeplinks in the company header. Deepvue dropped — no public per-ticker URL (behind login); owner chose TradingView. |
| LOOK-B1 | Sparkline rank-timeframe toggle (wk/mo/3mo/6mo) | `docs/index.html` | S | Deferred (Proposal A). |
| LOOK-B2 | Acceleration hint from `perf_*_delta_*` (▲▲/▼) | `docs/index.html` | S | Deferred (Proposal B7). |
| LOOK-B3 | Empty-state recent searches + example chips | `docs/index.html` | S | Deferred (Proposal D9). |
| LOOK-B4 | Tap group card → jump to group in Today/Momentum | `docs/index.html` | M | Deferred (Proposal D10). |
| LOOK-B5 | AI rotation-phase line on sector card | `docs/index.html` | S | Deferred. |
| LOOK-B6 | Promote Rank Floor to `compute_deltas.py` column (+ dashboard + tests) | `scripts/compute_deltas.py`, `dashboard/app.py`, `tests/` | M | Deferred. Product-wide consistency. |
| LOOK-B7 | Revisit All-Green week gating; align dashboard | `docs/index.html`, `dashboard/app.py` | S | Deferred. See ADR-003. |

---

#### AI Integration

| # | Task | File(s) | Effort | Notes |
|---|------|---------|--------|-------|
| AI-MIGRATION | **Migrate from Gemini AI Studio to Vertex AI (Phases 1–4)** | `scripts/generate_ai.py`, `.github/workflows/generate_ai.yml`, `tests/test_generate_ai.py`, `CLAUDE.md` | L | Plan in `planning/vertex-ai-migration.md` (PR #67). **Phases 2–4 merged in PR #79** (2026-06-14): dual-mode client, WIF workflow, PR #83+#84 fixes. **Phase 1 (GCP infra) = owner, done** — 3 secrets added; script confirmed on Vertex AI backend. **⚠️ BLOCKER: `sectors.daily_delta` field fails JSON parse** ("Unterminated string" error, column 99). PR #84's 900-token increase insufficient; response appears truncated or wrapped. 6/7 fields generating cleanly. **Next:** Debug actual response format from Vertex AI, increase tokens further or reduce daily_delta scope. |
| PLAN-2 | **Phase 2: Schema Enrichment + Few-Shot** | `scripts/generate_ai.py`, `tests/test_generate_ai.py` | M | Add `description` fields + `additionalProperties: false` to all 5 schemas; fix `_normalize_phase()` confidence bug; add few-shot examples to briefing/watchlist prompts; add validation logging. **BLOCKED** until Phase 1 is deployed and 2+ weeks of `fetch_log.csv` data shows skip logic firing correctly (`ai_outcome=skipped` on no-data days, `=complete` on data days). |
| AI-1 | **Anomaly Detection + LLM Explanation** | `scripts/generate_ai.py`, `dashboard/app.py` | M | Flag rank deltas >2σ from a 14-day rolling window using pandas, then send each flagged group to Gemini for a 1-sentence contextual note. See full spec below. |
| AI-2 | **Natural Language Q&A** | `dashboard/app.py` | M | Text input in AI Insights tab — user types a question, gets a plain-English answer backed by the actual data. Requires a real-time API call; needs an auth/cost-gate decision. See full spec below. |
| ~~AI-3~~ | ~~**Restore per-field resumability in `generate_ai.py`**~~ | — | — | **Done in PR #58** (2026-06-13). Restored incremental partial-file loading. Also fixed daily quota abort (`DailyQuotaExhaustedError`) and delta error tracking. |
| AI-4 | **AI Health widget in Streamlit dashboard** | `dashboard/app.py` | S | PR #53 decoupled AI generation, so `fetch_log.csv` no longer shows AI outcomes. Add a health widget to the AI Insights tab reading from `data/ai/index.json`. No pipeline changes needed. See full spec below. |

**AI-1 spec — Anomaly Detection + LLM Explanation**

_What it does:_ Nightly, detect statistically unusual rank moves and add plain-English context for each one.

_Implementation (all in `scripts/generate_ai.py`):_
1. Add `detect_anomalies(delta_df: pd.DataFrame, min_days: int = 14) -> list` — loads ALL rows of `deltas.csv` (not just latest day), computes per-group rolling 14-day mean and std of `rank_ytd_delta_7d`, then for the latest date flags any group where `|rank_ytd_delta_7d - rolling_mean| / rolling_std > 2`. Returns list of `{"name": str, "delta": float, "z_score": float}`. Return `[]` if fewer than `min_days` rows exist — don't guess.
2. In `generate_for_group()` (after watchlist), if anomalies detected, build a prompt: _"The following groups had unusually large rank moves today (vs. their 14-day baseline). For each, write one sentence explaining what this kind of move might indicate about capital rotation. [anomaly list]. Respond as NAME: [note] one per line."_ Catch exceptions same as the other 3 calls.
3. Parse the response into `result["anomalies"] = [{"name": ..., "delta": ..., "z_score": ..., "note": ...}]`.
4. JSON output already committed nightly alongside other AI content.
5. Dashboard: in `dashboard/app.py` tab 7 (AI Insights, end of file), add a `st.expander("Notable Moves")` after the briefing section. Iterate `ai_data.get(group_key, {}).get("anomalies", [])` and render each with delta + z_score + note. Show "None detected" if list is empty.

_Test additions (`tests/test_generate_ai.py`):_ `test_detect_anomalies_returns_empty_below_min_days`, `test_detect_anomalies_flags_high_z_score`, `test_detect_anomalies_no_false_positive_normal_move`.

_Data gate:_ needs 14+ days of delta history. Gate with `if len(all_dates) < min_days: return []`.

---

**AI-2 spec — Natural Language Q&A**

_What it does:_ A text input in the AI Insights tab — user asks "which industries have improved rank for 30 days straight?" or "show me everything with high momentum but weak recent move" and gets a direct answer.

_Architecture decision required (pick one before starting):_
- **Option A (recommended):** Gate on `GEMINI_API_KEY` in `st.secrets` — if present, show the Q&A widget; if absent, show a muted info message. Key stored in `.streamlit/secrets.toml` (gitignored) locally, or in Streamlit Cloud's secrets UI for deployment. This means the API key lives in the Streamlit environment — acceptable if the dashboard URL is not widely shared.
- **Option B (local-only):** Only enable Q&A when running locally (`os.getenv("GEMINI_API_KEY")` set). No key in Streamlit deployment; hosted dashboard stays key-free. Good for personal use only.

_Implementation (`dashboard/app.py`, tab 7, bottom of the file):_
1. Check `api_key = st.secrets.get("GEMINI_API_KEY", None) or os.getenv("GEMINI_API_KEY")`. If None, show `st.info("Configure GEMINI_API_KEY to enable Q&A.")` and stop.
2. `question = st.text_input("Ask a question about the data...")` + `st.button("Ask")`.
3. On submit: serialize the latest `delta_df` as a compact markdown table (top 30 rows by momentum_score, columns: name / rank_ytd / rank_ytd_delta_7d / momentum_score / rank_agreement). Pass with question to `gemini-1.5-flash`. Cache with `@st.cache_data(ttl=300, show_spinner=False)` keyed on `(question, str(latest_date), group_label)`.
4. Render response with `st.markdown(response)`.

_Token budget:_ 30 rows × 5 columns ≈ ~500 tokens of data context. Well within Flash's 1M limit. Log `len(prompt)` on first run to confirm.

_Test:_ mock `genai.GenerativeModel.generate_content`, verify prompt contains the question and data table, verify cache key includes the date.

---

**AI-3 spec — Restore per-field resumability in `generate_ai.py`**

_Background:_ PR #35 (2026-06-11) implemented field-level resumability — load the existing partial JSON for today, regenerate only missing fields. PR #42 (2026-06-12) removed it entirely: the "if today's file exists, skip everything" idempotency check was causing stale insights on days when Finviz updated after the initial run. The fix in PR #42 swung too far — it removed resumability as collateral damage. PR #50 (2026-06-13) added a run-level skip gate (`_has_new_delta_data`). As of now:

- `existing_output = {}` is hardcoded in `main()` — never populated from file
- The per-field skip logic in `generate_for_group` (`if spec["name"] in result: continue`) is orphaned dead code that never fires
- Every run makes all 7 API calls from scratch, even if 4 already succeeded before a rate-limit failure

_What to implement:_ Before starting generation, if `output_path` (`data/ai/YYYY-MM-DD.json`) already exists for today, load it into `existing_output` and set `was_incremental = True`. If the file is already complete (per `_is_complete()`), skip the whole run — unless `--force-ai` is set. The existing per-field skip logic in `generate_for_group` then fires correctly for any already-present fields.

_Critical constraint — don't restore the PR #42 stale data bug:_ The PR #42 bug was: file existed from an early cron run → second cron run (after Finviz updated) saw the file and skipped everything → stale data persisted all day. The fix: only load the existing file if it is **incomplete** (partial). A complete file skips the run (no stale risk since all fields are done). A partial file resumes only missing fields (correct). `--force-ai` always regenerates everything regardless.

_Decision table:_
| State | Behavior |
|-------|----------|
| No file for today | Generate all 7 fields |
| Partial file for today | Load it; generate only missing fields |
| Complete file for today | Skip (log `outcome=skipped`) |
| Any state + `--force-ai` | Generate all 7 fields from scratch |

_Files:_
- `scripts/generate_ai.py`: modify `main()` — add file-load block before the generation loop (8–10 lines)
- `tests/test_generate_ai.py`: add 2 tests — `test_main_resumes_partial_file` (partial file → only missing fields called), `test_main_skips_complete_file` (complete file, no force → zero API calls)

_Effort:_ S — the scaffolding is already there. The only missing piece is the 8-line block that reads the file into `existing_output`.

---

**AI-4 spec — AI Health widget in Streamlit dashboard**

_Motivation:_ PR #53 decoupled AI generation from `collect.yml` — `ai_outcome` in `fetch_log.csv` is now always `""` for snapshot rows. There is no single place to see "did AI run today, and did it succeed?" without digging into Actions logs or raw JSONL. This adds a lightweight visibility widget to the dashboard.

_Data source:_ `data/ai/index.json` — already committed nightly by `_update_index()` in `generate_ai.py`. Structure: `{"updated_at": "...", "entries": [{"date": "YYYY-MM-DD", "status": "complete|partial|skipped|failed", "model": "...", "generated_at": "...", "rotation_phase": "..."}, ...]}`. Capped at 90 entries. File is ~5KB — fast to read.

_Implementation (`dashboard/app.py`, AI Insights tab):_
1. After the existing AI content renders, add `st.expander("AI Run Health", expanded=False)`.
2. Inside: `index_path = DATA_DIR / "ai" / "index.json"`. If it doesn't exist, show `st.info("No AI run history yet.")`.
3. Load the JSON, take the first 7–10 entries (last 7–10 days). Render as a table or `st.metric` row:
   - Date | Status | Model | Generated at | Phase
   - Color-code `status` with emoji: `complete` → ✓, `partial` → ~, `skipped` → ○, `failed` → ✗ (or use `st.success/warning/info/error` per row)
4. For `partial` entries: the full field-level detail is in `data/ai_run_log.jsonl`. Optionally add a nested expander "Show field detail" that reads that entry from the JSONL (match on `date`). This is a nice-to-have — the outer widget is the priority.

_No test required_ — dashboard-only change. Note it in the commit message.

_Effort:_ S — `index.json` is already being written; this is a pure read.

_Dependency:_ None. Works today.

---

#### Data / Insight Features

| # | Task | File(s) | Effort | Notes |
|---|------|---------|--------|-------|
| D1 | **[USER ACTION] Create `main` branch, set as default** | GitHub UI | S | Blocks cron and PWA-1. Merge `claude/elegant-babbage-hlxnfy` → new `main`, then Settings → Branches → change default. |
| PWA-1 | Fix hardcoded `BRANCH` constant in PWA | `docs/index.html` line ~117 | S | Change `'claude/elegant-babbage-hlxnfy'` to `'main'` (or whichever branch receives daily cron data). Depends on D1. |
| INS-4 | **Momentum Velocity (`momentum_score_delta_7d/14d`)** | `scripts/compute_deltas.py` | M | Track momentum_score change over time. "Rising Stars" = positive velocity + currently top-half. Needs 7+ days of data. |
| INS-5 | **Daily Brief card (PWA top-of-screen)** | `docs/index.html` | M | Single card: today's breakout, sustained leaders, what's rolling over. Eliminates tab-hopping on mobile. Needs 7+ days for interesting content. |
| INS-6 | **Momentum Score Heatmap (time × industry)** | `dashboard/app.py` | S | Companion to existing rank-delta heatmap — cells = `momentum_score` over time. Absolute picture of sustained leaders. Needs 7+ days. |
| INS-7 | **Sector Breadth** | `dashboard/app.py` | L | % of industries in a sector that are top-half of full universe. Needs static sector→industry mapping (11 sectors × 144 industries). Hardest feature. |
| DEBT-1 | `evict_today_rows` concurrency race | `scripts/collect.py` | S | Two simultaneous `collect.py` processes could race on read-modify-write. Non-issue given single scheduled Action + ad-hoc manual runs. Fix would be a file lock (e.g. `fcntl.flock`). Table until concurrency is actually needed. |
| DEBT-2 | `evict_today_rows` I/O errors not caught | `scripts/collect.py` | S | Disk-full / permission errors bubble up as exceptions. Intentional — matches rest of codebase. Could add explicit error message if this causes confusion in prod logs. |
| 6b | Sector → Industry drill-down | `dashboard/app.py` | L | Hardcode `SECTOR_INDUSTRY_MAP` (11 sectors → 144 industries) in `app.py`. Sidebar selectbox filters all tabs. Effort is mostly cataloguing the mapping, not code. |

> **D1 note — the elegant-babbage debt**: `claude/elegant-babbage-hlxnfy` is currently the default branch (no `main` exists). GitHub Actions cron only fires on the default branch, and the PWA hardcodes this branch name. D1 is the root fix; PWA-1 is the code follow-up. Until D1 is done, the cron data will keep landing on `elegant-babbage` — so don't change the `BRANCH` constant before D1 is complete.

---

### 🟡 Ready

| # | Task | File(s) | Effort | Notes |
|---|------|---------|--------|-------|
| PLAN-1 | **Phase 1: Smart Regeneration + Force Flag** | `scripts/generate_ai.py`, `.github/workflows/collect.yml`, `README.md` | M | Add `_has_new_delta_data()` helper (Task 1.1), argparse + force flag + skip gate in `main()` (Task 1.2), workflow input param (Task 1.3). Full spec in `planning/PLAN_smart_regeneration_pydantic.md`. Start new session; generate_ai.py is large. |

---

### 🟢 In Progress

_(nothing)_

---

### ✅ Done

| # | Task | Date |
|---|------|------|
| AI-PWA | AI tab improvements (Items 1–8): key signals, delta card, conviction tags, industries structure, relative timestamp, native share, phase history strip, historical date navigation | 2026-06-12 |
| AI-ARCH | AI architecture revamp: `TASK_SPECS`, `index.json` manifest, `gemini-2.5-flash`, incremental completion (PR #38) | 2026-06-11 |
| MON-1 | Workflow logging + monitoring: AI partial completion fix, `ai_run_log.jsonl`, `fetch_log.csv` AI columns, PWA pipeline diamond (PR #35) | 2026-06-11 |
| AI-0 | Server-side AI pipeline: daily briefing + rotation phase + watchlist (PR #25) | 2026-06-10 |
| INS-1 | Sustained Strength / "Evergreen" list (Streamlit + PWA) | 2026-06-10 |
| INS-2 | `rank_agreement` metric in deltas.csv | 2026-06-10 |
| INS-3 | All Green filter + emoji dot matrix | 2026-06-10 |
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
