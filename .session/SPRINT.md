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
| TICKER-1 | **CF Worker: /lookup endpoint + KV cache** | `worker/src/index.js`, `worker/wrangler.toml`, `worker/src/taxonomy_map.json`, `worker/package.json`, `worker/README.md`, `worker/test/index.test.js` | M | ✅ **Code merged** (PR #74, 2026-06-14). 28 vitest tests passing, code in `worker/` dir. Uses FMP `stable/profile` (legacy `/api/v3/profile/` is dead — see `knowledge/fmp-api-findings.md`). **Pending user deploy:** `wrangler login` → `kv namespace create` → `secret put FMP_API_KEY` → `npm run deploy` (see `worker/README.md`). Prerequisite: TICKER-0 (PR #66 — still needs its session-notes conflict resolved to merge). |
| TICKER-2 | **PWA Lookup tab** | `docs/index.html` | M | New "Lookup" tab. Text input → Worker call → trade context card: company header + industry perf card + sector perf card + FAVORABLE/MIXED/CAUTION signal. Joins to already-loaded state.data. See Phase 3 in plan. Prerequisite: TICKER-1 deployed. |
| TICKER-3 | **Streamlit Lookup tab** | `dashboard/app.py`, NEW `dashboard/worker_client.py`, `requirements.txt`, `requirements-test.txt`, NEW `tests/test_worker_client.py` | M | Tab 8. Same result as PWA. Pure `lookup_ticker()` in worker_client.py for testability. `_render_group_card` helper reused. See Phase 4 in plan. Prerequisite: TICKER-1 deployed. |
| TICKER-4 | **Operations setup** | `worker/src/index.js` (add /stats + cache-bust endpoints), `worker/README.md` | S | FMP call counter in KV, /stats endpoint, /health, /cache DELETE endpoint. Bookmark CF analytics dashboard. Monthly check task added to SPRINT.md. See Phase 5 in plan. |
| TICKER-5 | **[FUTURE] Sector/Industry → Stocks screener** | `worker/src/index.js` (add /stocks endpoint), `docs/index.html`, `dashboard/app.py` | M | New Worker endpoint `/stocks?finviz_sector=&finviz_industry=` calls FMP screener, returns top 25 by market cap, KV cache 7d. Both front-ends add "Show stocks" toggle on group cards. Do NOT start until TICKER-0 through TICKER-4 are validated in production. See Phase 7 in plan. |

> **Phase 0:** (1) FMP free account + API key ✅ done. (2) Cloudflare account + install Wrangler + create KV namespace — **still needed before TICKER-1.** See plan Phase 0.

> **Monthly recurring:** CF analytics check, FMP quota check, taxonomy validity spot-check. See plan Phase 5.

---

#### AI Integration

| # | Task | File(s) | Effort | Notes |
|---|------|---------|--------|-------|
| AI-MIGRATION | **Migrate from Gemini AI Studio to Vertex AI (Phases 1–4)** | `scripts/generate_ai.py`, `.github/workflows/generate_ai.yml`, `tests/test_generate_ai.py`, `CLAUDE.md` | L | Plan in `planning/vertex-ai-migration.md` (PR #67). **Phases 2–4 merged in PR #80** (2026-06-14): dual-mode client, WIF workflow, 6 tests, docs. **Phase 1 (GCP infra) = owner, still pending** — 3 secrets `WIF_PROVIDER`/`GCP_SA_EMAIL`/`GOOGLE_CLOUD_PROJECT` must be added to repo before AI runs activate. Script gracefully exits 0 if unconfigured. |
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
