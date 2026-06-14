# Session Notes

> Future Claude: read this immediately at session start. Summarize the current state for the user before doing anything else.

---

## Current Status

**Status:** TICKER-1 (CF Worker) **merged and in CI** (PR #70 just merged — adds worker vitest tests to `tests.yml`). 28 vitest tests pass, bundles verified. TICKER-0 taxonomy map exists in **PR #66 (open/draft, session-notes.md conflict — needs resolution before merge)**.
**Safe to close:** Yes — all code changes complete, but user action required.
**Waiting on:** (1) **User must deploy the Worker manually** — `wrangler login` / `kv namespace create` / `secret put FMP_API_KEY` / `npm run deploy` cannot run from cloud (CF OAuth + secrets needed). See `worker/README.md`. (2) **PR #66 resolution** — merge TICKER-0 (taxonomy map) after conflict cleared.
**Next actions:** (1) Merge PR #66 (TICKER-0); (2) User deploys Worker, records `*.workers.dev` URL; (3) TICKER-2 (PWA Lookup tab using that URL); (4) TICKER-3 (Streamlit); (5) TICKER-4 ops endpoints (`/stats`, `/cache`, FMP counter).

---

## Session: 2026-06-13 — AI quota exhaustion fix (PR #58)

### What was done

**Root cause analysis** of RESOURCE_EXHAUSTED failures in `generate_ai.py`.

**Three compounding bugs identified and fixed:**

**Bug 1 — Incremental loading removed (commit `022d871`):** `existing_output = {}` was hardcoded. Every run regenerated all 7 fields from scratch even when a partial file existed. The `generate_for_group` skip-if-present logic was intact but never fired.

**Bug 2 — Retry loop retried daily quota exhaustion:** 429 with `GenerateRequestsPerDayPerProjectPerModel-FreeTier` was treated the same as per-minute rate limits. Each retry burned another quota unit and wasted 30+60+120s sleep per field. June 13 run: 7 first-attempts + 17 retries = 24 actual API requests, 20+ minutes elapsed.

**Bug 3 — `_generate_daily_delta` swallowed exceptions silently:** Every failure logged `{"status":"error"}` with no error field. `[]` from API failure was indistinguishable from `[]` from "model found no changes."

**Fixes committed (commit cb38d77):**
1. Restored partial-file incremental loading in `main()` — loads existing partial file, passes it as `existing=` to `generate_for_group`. Complete files still regenerate fresh (deliberate design).
2. Added `DailyQuotaExhaustedError` — detected in `_call_api` by `GenerateRequestsPerDayPerProjectPerModel` in error string, propagates to `main()` which saves partial output, logs `quota_exhausted`, exits 0.
3. `_generate_daily_delta` returns `(list, str)` tuple — `ok_empty` vs `error` with message are now distinguishable in run log.

**Tests:** 207 passing (was 126 in test_generate_ai.py, added 20 new tests covering all three fixes).

**PR #58:** Open (draft), awaiting CI.

**Plan file:** `planning/ai-quota-exhaustion-fix.md` committed and pushed.

### Key decisions

- Do NOT skip complete files (deliberate design from commit `022d871` + existing test `test_main_force_regenerates_complete_file`). Only partial files trigger incremental loading.
- `DailyQuotaExhaustedError` is non-retryable — quota can't reset mid-run.
- 20 RPD limit is real — Google cut from 250 → 20 for gemini-2.5-flash in late 2025. 7 calls/day is sufficient if not wasting calls on retries or full-regeneration of partial files.

### Next steps

1. Merge PR #58
2. Mark AI-3 done in SPRINT.md (this PR fully implements it)
3. Monitor `data/ai_run_log.jsonl` for 2+ days — expect `rate_limit_hits` ≤ 3, no `quota_exhausted` on normal days

---

## Session: 2026-06-14 — Post-merge documentation verification

### What was done

**Verified documentation after PR #70 merge** (TICKER-1 Cloudflare Worker code now in CI).

**Updated files:**
- `.session/session-notes.md` Current Status: TICKER-1 now marked as "merged and in CI"; noted that code is verified in tests but user must deploy manually.
- `.session/SPRINT.md` TICKER-1 entry: changed from "⏳ Code complete on branch" to "✅ Code merged & in CI"; clarified the vitest integration.

**Documentation accuracy verified:**
- `README.md` is current (covers current state, no changes needed)
- `CLAUDE.md` is current (covers project structure, no changes needed)
- `.claude/rules/` is current (no changes needed)

**Current blockers:**
1. TICKER-0 (taxonomy map, PR #66): conflict in session-notes.md prevents merge. Needs resolution.
2. User deployment of Worker: `wrangler` commands must be run locally (not in cloud session).

**Safe to close:** Yes — documentation is current, all code merged, next steps are well-documented.

---

## Session: 2026-06-14 — Ticker lookup feature design (plan written, PR #62)

### What was done

**Reviewed PR #57** (ticker → sector/industry lookup) and redesigned from scratch.

**PR #57 approach rejected** (yfinance + hardcoded sector dict + runtime difflib matching + Streamlit-only) for three reasons:
1. yfinance has a different taxonomy from Finviz; difflib is blind to semantic equivalence
2. The static PWA (GitHub Pages) cannot call a keyed API or run Python — needs a shared backend
3. Difflib is the wrong tool: the problem is a one-time 144-item semantic matching job, not a runtime problem

**New architecture designed and documented in `planning/PLAN_ticker_lookup.md`:**
- Source: FMP `/api/v3/profile` (GICS-based taxonomy ≈ Finviz's)
- Taxonomy translation: static LLM-generated map (Claude session, one-time) → `data/taxonomy_map.csv` committed
- Backend: Cloudflare Worker (free tier) — single normalization point, hides FMP key, serves both Streamlit + PWA
- KV cache TTL: 30 days (sector classifications are near-permanent)
- Cache full FMP profile payload (company name, description, logo, etc.)
- End-user result: trade context card — rank, momentum, perf, context signal (FAVORABLE/MIXED/CAUTION)
- PWA prioritized over Streamlit (used ~10× more)
- Future Phase 7: `/stocks?finviz_sector=&finviz_industry=` using FMP screener (returns all stocks in a group — confirmed FMP behavior)

**Files committed:**
- `planning/PLAN_ticker_lookup.md` — full implementation plan (Phases 0–7, code-level detail)
- `.session/SPRINT.md` — TICKER-0 through TICKER-5 added to backlog
- `.session/session-notes.md` — this entry

### Key decisions

- FMP over yfinance: GICS-based taxonomy, single JSON call, reliable free tier
- Claude session for taxonomy map (not a build script): ~144 rows, one-time semantic job
- CF Worker required (not optional): PWA is static — it cannot hold an API key
- 30-day KV TTL: sector classifications change at most once a year for most companies
- Phase 7 (screener) explicitly designed but not started: same Worker infrastructure extends cleanly

### Next steps

1. **User action required first (Phase 0):** FMP API key + Cloudflare account + Wrangler + KV namespace. See `planning/PLAN_ticker_lookup.md` Phase 0.
2. **TICKER-0:** New Claude session → taxonomy map generation. Follow Phase 1 in the plan exactly.
3. **TICKER-1:** CF Worker. New session; follow Phase 2.
4. **TICKER-2:** PWA Lookup tab. Follow Phase 3. (Do before TICKER-3.)
5. **AI Phase 2 still blocked** — waiting on 2+ weeks production data for smart regeneration skip logic.

---

## Session: 2026-06-13 — Phase 1 implementation: smart regeneration skip logic (PR #50)

### What was done

**Implemented Phase 1** per `planning/PLAN_smart_regeneration_pydantic.md` (Tasks 1.1, 1.2, 1.3).

**Task 1.1 + 1.2 (commit 540f32e):** Smart skip logic in `generate_ai.py`
- Added `_has_new_delta_data(date_str)` helper: reads `data/sectors/deltas.csv` and `data/industries/deltas.csv` with `dtype=str, usecols=["date"]`. Returns `True` if today's date appears in either; `False` if neither has data, CSVs are missing, or a read error occurs (prints WARNING on error).
- Added `argparse` with `--force-ai` flag and `FORCE_AI` env var; uses `parse_known_args()` so pytest args don't cause parse failures.
- Wired skip gate into `main()` after `today` is derived, before API key check: `if not force and not _has_new_delta_data(today): sys.exit(0)` with `outcome="skipped"` in artifacts.
- 8 new tests; 9 existing `main()` tests patched to monkeypatch `_has_new_delta_data=True`.

**Task 1.3 (commit ea874b0):** Workflow + README
- Added `force_ai` boolean input to `workflow_dispatch` in `collect.yml`. The AI step passes `--force-ai` only when input is `"true"`; scheduled cron always goes through the skip check.
- README updated with skip behaviour, `--force-ai` usage, and `FORCE_AI` env var.

**Tests:** 114 passing (was 106, +8 new).

**PR #50:** Merged (commit ff2be5b). All tests passing (114 tests).

### Key decisions

- `parse_known_args()` instead of `parse_args()` — prevents pytest args from causing parse failures when tests call `main()` directly.
- Skip gate fires before API key check — no side effects on skip (no log write until `_write_run_artifacts("skipped", ...)` which is cheap).
- WARNING printed on corrupt CSV read (per plan spec from PR #47 correction).

### Next steps

1. **Monitor production** — 2+ weeks of data collection to confirm skip logic fires correctly on no-delta days; force_ai checkbox works for manual overrides
2. **Phase 2** (schema descriptions + few-shot): unblock after production stability confirmed

---

## Session: 2026-06-13 — Plan review: Smart Regeneration + Schema Enrichment (PRs #46, #47)

### What was done

**Reviewed PR #44 plan** (`planning/PLAN_smart_regeneration_pydantic.md`) before implementation.

**PR #46 (merged):** Staff-engineer review pass on the plan. Key changes accepted:
- Removed Pydantic migration — plain dicts + `description` fields achieve the same semantic compliance, no new dependency
- Replaced status file inter-script coupling (`compute_deltas.py` → `data/deltas_run_status.json`) with direct delta CSV check in `generate_ai.py` (`_has_new_delta_data()`)
- Corrected stale reference: Task 1.2 described incremental loading logic that was already removed (`existing_output = {}` hardcoded)
- Caught pre-existing bug: `_normalize_phase()` drops `confidence` field despite `PHASE_SCHEMA` requiring it
- Clarified syntactic (structured output mode) vs. semantic (few-shot examples) compliance

**PR #47 (merged):** Two small follow-up fixes caught in review:
- Task 1.1/1.2 split: skip gate code referenced `force` variable not defined until Task 1.2. Fixed: Task 1.1 = helper function only; Task 1.2 = argparse + force + skip gate together
- Added WARNING print to `_has_new_delta_data`'s except branch so unexpected skips are visible in CI logs

### Key decisions

- Default-on-error for `_has_new_delta_data` → skip (not regenerate). Rationale: no delta data = nothing to analyze. generate_ai.py's job is not to diagnose compute_deltas failures. WARNING log gives visibility.
- Phase 2 blocked until 2+ weeks of production data confirms Phase 1 skip logic working correctly (see SPRINT.md gate)
- Recommend fresh session for Phase 1 implementation (context partially used; generate_ai.py is a large file requiring clean context)

### Next steps

1. **New session: implement Phase 1** — Tasks 1.1, 1.2, 1.3 per `planning/PLAN_smart_regeneration_pydantic.md`. All three tasks touch only `generate_ai.py`, `collect.yml`, and `README.md`.
2. After Phase 1 ships and runs in production 2+ weeks → evaluate Phase 2 (schema descriptions + few-shot)

---

## Session: 2026-06-12 — Force GenerateAI calls and fix AI data display corruption (PR #42, CI in progress)

### What was done

**Problem addressed:**
1. Stale AI insights: caching prevents regeneration when Finviz data updates
2. Dashboard display corruption: raw JSON like `{"key_signals": [...]}` showing instead of formatted text
3. Debug messages appearing: "Here is the JSON requested:" visible in UI
4. Fallback parsing mismatch: data shapes don't match frontend expectations

**Solution implemented (4 commits):**

1. **Force GenerateAI calls** (commit 022d871):
   - Removed cache check block that skipped if file already existed for the day
   - Always regenerate all fields from scratch on every workflow run
   - Eliminates stale insights; always ensures fresh data

2. **Normalize response shapes** (commit 022d871):
   - Added `_normalize_briefing()`: guarantees `{briefing: str, key_signals: list}` shape
   - Added `_normalize_phase()`: guarantees `{label: str, reasoning: str}` shape
   - Called after JSON parsing or fallback parsing to prevent malformed data from leaking into stored files
   - Handles all edge cases: null values, empty strings, type mismatches

3. **Defensive frontend parsing** (commit 705d35c):
   - Added validation in `renderAI()`: briefing might be string or object, handle both
   - Filter null/empty strings from key_signals before rendering
   - Graceful fallback if briefing accidentally stored as nested object
   - Ensures string type before splitting paragraphs

4. **Comprehensive test coverage** (commit 3640924):
   - 17 new unit tests for normalization functions
   - `_normalize_briefing`: 10 test cases (valid dict, null values, strings, invalid types)
   - `_normalize_phase`: 7 test cases (valid dict, whitespace, free-form labels)
   - All tests passing; existing tests remain passing

**Files changed:**
- `scripts/generate_ai.py`: Removed cache check, added 2 normalization helpers, updated generation logic
- `docs/index.html`: Added defensive parsing in `renderAI()` briefing section
- `tests/test_generate_ai.py`: 17 new test cases
- `PLAN.md`: Detailed implementation plan (committed separately)

**Test results:** All tests passing (106 tests in test_generate_ai.py, all generate_ai tests passing)

**PR #42 status:** Draft, CI in progress (2 test jobs running)

### Key decisions

- Always force regeneration (no caching); user's request to fix refresh issues took priority over API cost savings
- Normalization layer prevents both JSON parsing failures and fallback parsing mismatches from corrupting stored data
- Frontend defensive parsing handles incomplete/malformed data gracefully instead of crashing
- Test coverage focuses on robustness to edge cases that fallback parsing can produce

### Next steps

1. Monitor CI completion (watching PR #42)
2. Address any CI failures if they arise
3. Await user review/merge of PR #42

---

## Session: 2026-06-12 — AI workflow error resilience overhaul

### What was done

**Root cause analysis:**
- Initial diagnosis: 503 errors weren't being retried
- Deep dive on re-run logs: discovered `'NoneType' object has no attribute 'strip'` crash
- Root cause: Gemini API returns successful response with `response.text == None` on 503 errors

**Three layers of resilience implemented (PR #41):**

1. **Transient error retry logic** (commits 374c6e8, 738cf3d, 3fc91d8):
   - Extended retryable error detection from just "429" → now includes "503", "unavailable", "empty response", "preamble"
   - Applied exponential backoff: 30s, 60s, 120s (was only for quota errors)

2. **Robust preamble detection** (commit 3fc91d8):
   - New `_looks_like_preamble()` helper function (not Gemini-specific)
   - Detects 8 common LLM failure patterns: "here is", "below is", "json requested", etc.
   - Case-insensitive, excludes valid JSON (starts with `{`)
   - Prevents storing truncated responses like `"Here is the JSON requested:\n\`\`\`json"`

3. **Complete response validation** (commits 738cf3d, 3fc91d8):
   - Check `not response.text or not response.text.strip()` (catches None, empty string, whitespace-only)
   - Treat all incomplete responses as transient errors → trigger retry

**Test coverage** (commit 3fc91d8):
- Added 5 new unit tests for error paths
- Tests for preamble detection patterns, case-insensitivity, empty responses, whitespace, preamble retry
- Result: 89 tests passing (was 84) ✅

**Key decisions:**
- Pattern-match preambles, not API provider (future-proof)
- Whitespace-only responses treated same as empty (more conservative)
- All new error types feed into existing retry logic (no new code paths)

### Commits

1. `374c6e8` — fix: handle 503 errors and truncated responses (initial fixes)
2. `738cf3d` — fix: handle empty API responses (None response.text)
3. `c688c7f` — chore: update session notes with root cause analysis
4. `3fc91d8` — improve: robust error handling for transient API failures (5 tests added)

### PR #41

- Title: "fix: handle 503 errors and truncated responses"
- Status: Draft, ready for review
- Changes: 2 files, 4 commits, +114 lines, -6 lines
- Tests: All 89 passing

### Next steps

1. User merges PR #41
2. Trigger workflow re-run (manually or wait for next scheduled cron)
3. Workflow should retry the 3 failed fields: sectors.briefing, industries.watchlist, sectors.daily_delta
4. Complete the 2026-06-12 analysis with proper AI insights

---

## Session: 2026-06-11 — AI server-side architecture revamp (PR open, pending merge)

### What was done

6-phase refactor of `scripts/generate_ai.py`, `dashboard/app.py`, `docs/index.html`. Plan committed to `planning/ai-architecture-revamp.md` before any code changes.

**Phase 1 — JSON schema mode (`_call_api` update):**
- Added `PHASE_SCHEMA` and `WATCHLIST_SCHEMA` module-level dicts
- Extended `_call_api()` with `generation_config` and `response_schema` kwargs; lazily imports `google.genai.types` only when needed. Backward-compatible (no schema = no config kwarg sent).

**Phase 2 — Declarative `TASK_SPECS` pipeline:**
- Replaced the nested `if group_type == "sector"` if/else body of `generate_for_group()` with a loop over `TASK_SPECS` — a list of `{name, group_types, build_prompt, use_json_schema, response_schema, ...}` dicts.
- Added `_build_prompt()` helper to handle the `build_briefing_prompt` signature difference (`pass_group_type: True`).
- Added `_expected_fields()` so `_is_complete()` and `_missing_fields()` derive from `TASK_SPECS` — no hardcoded field names remain.
- Fixed a pre-existing bug: empty-snapshot path referenced `result` before it was assigned.
- New tasks (AI-1, AI-2, etc.) now require one dict entry in `TASK_SPECS` only; loop logic never changes.

**Phase 3 — `data/ai/index.json` master manifest:**
- `_update_index(date_str, status, output)` upserts an entry per run into `data/ai/index.json` (newest-first, capped at 90 entries, atomic write via `.tmp` swap).
- Called from `main()` after `_write_run_artifacts()` for both the "skipped" and "complete/partial" paths.

**Phase 4 — Dashboard + PWA consume index:**
- Dashboard AI Insights tab: reads `index.json` first, picks first `status="complete"` entry whose `.json` file exists; falls back to glob scan.
- PWA `loadAI()`: fetches `index.json` first, iterates entries; falls back to the snapshot-date URL if index is absent or empty.

**Phase 5 — Model upgrade:**
- `GEMINI_MODEL = "gemini-2.5-flash"` (was `"gemini-flash-latest"` unversioned alias).

**146 tests passing** (was 122 before this session; 24 new tests added).

### Next steps (prioritized)

1. Merge the open PR
2. **AI-1** (Anomaly Detection): now trivial to add — one `TASK_SPECS` entry + `build_anomaly_prompt()` + `ANOMALY_SCHEMA`. Gate on 14+ days of history.
3. **~2026-06-16**: 7d deltas arrive → INS-4 (Momentum Velocity), INS-5 (Daily Brief card), INS-6 (Heatmap) all unblock
4. **IDX-1**: 7-day rotation phase history strip in AI Insights tab using `index.json` entries (no need to load 7 full files). Effort: S.

### Key decisions

- `TASK_SPECS` is the single source of truth for "what to generate and for whom." `_expected_fields()` derives from it dynamically.
- JSON schema mode (`use_json_schema: True`) is on for `rotation_phase` and `watchlist` — API enforces valid JSON structure. Old text parsers kept as fallback.
- `index.json` uses status `"complete"` / `"partial"` / `"skipped"` — dashboard/PWA only load `"complete"` entries.
- Dashboard import check via `python3 -c "import dashboard.app"` doesn't work for Streamlit (top-level code runs on import). Use `python3 -m py_compile dashboard/app.py` instead.

---

## Session: 2026-06-11 — Workflow logging, monitoring, and AI partial completion fix (PR #35, merged)

### What was done

**Problem that triggered this session:**
`generate_ai.py` ran on 2026-06-11, generated `sectors.briefing`, then hit 429 rate-limiting and failed the remaining 3 calls. It wrote a partial `data/ai/2026-06-11.json`. On re-run, the old idempotency check (`output_path.exists()`) bailed immediately — partial content was locked in permanently.

**Three changes shipped:**

1. **AI partial completion fix (`scripts/generate_ai.py`):**
   - Idempotency check changed from "file exists" → "file is complete" (all 4 expected fields: `sectors.briefing`, `sectors.rotation_phase`, `sectors.watchlist`, `industries.briefing`)
   - `_is_complete(data)` and `_missing_fields(data)` added as pure functions
   - Incremental retry: loads existing partial file, passes per-group data to `generate_for_group` which skips already-present fields and regenerates only missing ones
   - Per-field outcomes tracked in module-level `_field_log` (reset at start of each `main()` call)

2. **Structured AI run log (`data/ai_run_log.jsonl` + `data/ai_run_summary.json`):**
   - Every run appends to `ai_run_log.jsonl`: timestamp, run_id, trigger, per-field status (`ok`/`error`/`skipped`/`no_data`), per-field elapsed seconds, rate-limit hit count, total API calls, full error text
   - `ai_run_summary.json` is a per-run sidecar (overwritten each run) consumed by collect.yml

3. **Workflow monitoring (`collect.yml` + `docs/index.html`):**
   - AI step gets `id: ai_gen`; outcome passed to Log fetch result step
   - `fetch_log.csv` gains `ai_outcome` and `ai_fields_missing` columns (schema migration runs automatically)
   - PWA pipeline history rows show ◆ green (complete), amber (partial with inline field names), grey (skipped)

**41 new tests; 122 total passing.**

Key CI fix: new `main()` tests mock both `sys.modules["google"]` AND `sys.modules["google.genai"]` — CI test env lacks google-genai, old test masked this because it accepted any `SystemExit(0)`.

5 reviewer findings addressed: `"step_skipped"` → `"skipped"` string fix (HIGH), `no_data` fields in `fields_missing` (MEDIUM), correct `skipped` vs `no_data` logging for existing fields, plus two dead-code removals.

### Next steps (prioritized)

1. **~2026-06-16**: 7d deltas arrive → INS-4 (Momentum Velocity), INS-5 (Daily Brief card), INS-6 (Momentum Score Heatmap) all unblock
2. **AI-1** (Anomaly Detection): flag rank deltas >2σ from 14-day rolling window. Gate on 14+ days of history.
3. **INS-7** (Sector Breadth): % of industries in a sector in top half. L effort (mostly mapping work).

### Key decisions

- Incremental retry (not reset) for partial AI files — preserves successful API calls, avoids quota waste
- "Complete" = all 4 fields non-empty (not just file presence)
- `ai_run_summary.json` in `data/` root (not `data/ai/`) so collect.yml's relative paths work

---

## Session: 2026-06-10 — AI integration pipeline (PR #25, merged)

### What was done

**Brainstormed 5 AI integration ideas** for the dashboard with the user. Agreed on server-side pre-computation via GitHub Actions (not runtime LLM calls from Streamlit) as the right architecture — API key lives only in Actions secrets, dashboard URL is safe to share publicly.

**Implemented ideas 1–3 (AI-0 in sprint board):**
- `scripts/generate_ai.py` — new script run nightly after `compute_deltas.py`. Calls Gemini 1.5 Flash (pinned `google-generativeai==0.8.6`) to generate: (1) daily briefing (3-paragraph narrative for sectors + industries), (2) rotation phase signal (Early/Mid/Late Cycle/Defensive + 1-sentence reasoning), (3) top-3 watchlist with thesis. Writes `data/ai/YYYY-MM-DD.json`, committed automatically by existing `git add data/` step.
- `.github/workflows/collect.yml` — added `Generate AI analysis` step after `Compute deltas`. Uses `secrets.GEMINI_API_KEY`. Exits 0 silently if key absent (workflow never fails on unconfigured envs).
- `dashboard/app.py` — added 7th tab "AI Insights". Reads pre-generated JSON, renders rotation phase badge, watchlist, and briefing. Zero LLM calls at dashboard runtime.
- `requirements.txt` — added `google-generativeai==0.8.6`.
- `tests/test_generate_ai.py` — 26 tests covering all pure functions + main() graceful exit + skip-trap (no file write on total API failure) + NaN rank_ytd guard.

**Review comments addressed (two rounds):**
1. Wrapped each `model.generate_content()` call in `try/except Exception` — transient API errors produce partial result, never fail the workflow.
2. Pinned `google-generativeai==0.8.6`; removed unused `python-dotenv`.
3. Removed misleading `rank_agreement` column from test fixture.
4. Fixed NaN `rank_ytd` not guarded in `serialize_top_movers()` (ValueError → `"N/A"`).
5. Fixed skip-trap: `main()` no longer writes the JSON if all API calls return `{}` — lets `workflow_dispatch` retry cleanly.

**64 tests passing** after all changes.

### Ideas still remaining (in sprint board as AI-1, AI-2)
- **AI-1** (Anomaly Detection): flag rank deltas >2σ from 14-day rolling window, add Gemini context per anomaly. Needs 14+ days of history.
- **AI-2** (Natural Language Q&A): real-time text input in dashboard — requires auth/cost-gate decision (key in `st.secrets` vs. local-only).

### User action needed
Add `GEMINI_API_KEY` to GitHub Actions secrets:
**Settings → Secrets and variables → Actions → New repository secret → Name: `GEMINI_API_KEY` → Value: your Gemini API key**

The next scheduled cron (weekdays 22:00 UTC) will generate the first `data/ai/YYYY-MM-DD.json` automatically.

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
- Created SPEC.md (later renamed to INITIAL_SPEC.md), all scripts, dashboard, GitHub Actions workflow, CLAUDE.md, .claude/rules/

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
