# Implementation Plan: Force GenerateAI Calls & Fix AI Data Display

**Created**: 2026-06-12 | **Branch**: `claude/force-generateai-calls-fixes-edjqfd`

---

## Context & Problem Statement

The Finviz Tracker dashboard's AI Insights tab is experiencing data refresh issues and display corruption:

1. **Stale cache**: The `generate_ai.py` script skips regeneration if the day's file already exists and is complete (lines 794–805), causing stale AI insights even when Finviz data updates.
2. **Frontend parsing failures**: The AI tab shows raw JSON structures like `{"key_signals": ["Energy maintains..."` and debug messages ("Here is the JSON requested:") instead of formatted content (screenshots provided).
3. **Backend fallback degradation**: When the Gemini API returns preamble text instead of pure JSON (caught by `_looks_like_preamble`, line 538), the fallback parser returns data structures that don't match frontend expectations (e.g., `rotation_phase` label becomes "Unknown").

**Root causes:**
- Cache prevents daily refreshes even when snapshot data updates
- LLM sometimes violates JSON schema constraints; fallback parsing produces mismatched shapes
- Frontend assumes briefing is an object with `{"briefing": "...", "key_signals": [...]}` but receives raw strings or partial objects

**Solution scope:**
- Remove caching entirely; always regenerate AI on each workflow run
- Validate and normalize briefing/phase response shapes before storing
- Ensure frontend can handle both complete and degraded data gracefully

---

## Tasks

### Task 1: Force GenerateAI Calls (Backend)

**Purpose/Motivation:**  
Remove date-based caching to ensure AI insights refresh with each GitHub Actions run, avoiding stale analysis when market data changes.

**Detailed Description:**  
Modify `scripts/generate_ai.py` to skip the completeness check (lines 794–805) and always regenerate all fields from scratch. This ensures:
- No cached file is ever considered "done"
- Each workflow run produces fresh Gemini calls
- The `was_incremental` flag is always False

**Changes:**
1. Delete the cache check block (lines 794–805)
2. Simplify main() flow: always initialize `existing_output = {}`
3. Update status message to always say "Generating" not "Skipping"

**Acceptance Criteria:**
- GitHub Actions workflow always executes Gemini API calls (no "skipped" outcomes)
- `data/ai_run_summary.json` always reports `outcome` as "complete" or "partial" (never "skipped")
- No leftover completeness check logic

**Happy Path Success Case:**
- Workflow run at 22:05 UTC finishes with outcome "complete"
- Next workflow run 2h later regenerates all fields fresh
- Both runs' logs show API calls, not cached skips

**Edge Cases:**
- Missing snapshot data (existing logic at line 621–628 handles this)
- API quota exhaustion → outcome "partial"; next run retries
- Empty snapshot CSV → skips generation but doesn't crash

**Dependencies:**
- `.github/workflows/collect.yml` (calls generate_ai.py after compute_deltas succeeds)

**Error/Failure Cases:**
- Gemini API unavailable → records error fields in ai_run_summary.json; next run retries
- No API key → exits with outcome "no_key" (unchanged)

**Follow-up Tasks:**
- Monitor API usage (Gemini free tier: 5 req/min → ~15 req per run × 3 runs/day = 45/day)
- If quota issues arise, implement workflow input parameter for optional --skip-ai flag

---

### Task 2: Validate & Normalize Briefing Responses (Backend)

**Purpose/Motivation:**  
Ensure the LLM's response (whether pure JSON or fallback-parsed text) always normalizes to the shape frontend expects: `{"briefing": "...", "key_signals": [...]}`. Prevents raw JSON fragments from leaking into the data file.

**Detailed Description:**  
After each Gemini call, validate the parsed response and apply a normalization layer that guarantees the correct shape before storing. Update `generate_for_group()` (lines 653–659) to:
1. After JSON parse or fallback parse, check if `briefing` is a dict or string
2. If it's a dict but missing `key_signals`, add empty array
3. If it's a raw string (from fallback), wrap it: `{"briefing": raw_string, "key_signals": []}`
4. Validate no null/undefined fields

**Changes:**
1. Create a normalization helper function `_normalize_briefing(parsed)` that returns `{"briefing": str, "key_signals": list}`
2. Call it at line 653 after `json.loads()` or fallback parse
3. Same for phase responses: ensure `{"label": str, "reasoning": str, "confidence": float}` with fallback label = "Unknown"

**Acceptance Criteria:**
- All briefing entries in `data/ai/{date}.json` have shape `{"briefing": "...", "key_signals": [...]}`
- All phase entries have shape `{"label": str, "reasoning": str}`
- No raw JSON fragments or strings in the output file
- Fallback-parsed responses normalize correctly

**Happy Path Success Case:**
- Gemini returns pure JSON → parsed directly and stored
- Gemini returns preamble + JSON (caught by _looks_like_preamble) → rejected and retried
- If retry fails, fallback parse produces string → wrapped as `{"briefing": "...", "key_signals": []}`

**Edge Cases:**
- LLM returns JSON with missing `key_signals` key → add empty array
- LLM returns JSON with null/empty briefing → store empty string, not null
- Phase label contains non-enum value (e.g., "Mid-Early Hybrid") → store as-is in free-form field, frontend renders with neutral icon

**Dependencies:**
- BRIEFING_SCHEMA, PHASE_SCHEMA definitions (lines 71–96)
- Fallback parsers: `parse_briefing_response()`, `parse_phase_response()`

**Error/Failure Cases:**
- Parse produces non-dict, non-string result → use fallback or default empty structure
- Exception during normalization → log error, store error record, continue to next field

**Follow-up Tasks:**
- Add test for normalization with various malformed inputs (see testing section)
- Monitor ai_run_log.jsonl for "error" field entries and adjust schema if patterns emerge

---

### Task 3: Fix Frontend JSON Parsing & Display (Frontend)

**Purpose/Motivation:**  
The frontend is displaying raw JSON strings and debug preambles instead of formatted content. Implement robust parsing and fallback rendering to handle incomplete/malformed AI data gracefully.

**Detailed Description:**  
Update `docs/index.html` `renderAI()` function (lines 905–1077) to:
1. Validate `data.sectors.briefing` and `data.industries.briefing` exist and are strings, not nested objects
2. Parse raw JSON-string values if accidentally stored as strings (defensive parsing)
3. Gracefully render incomplete data: if phase is missing/null, show "—" instead of "Unknown"
4. Hide debug messages like "Here is the JSON requested:"

**Changes:**
1. **Lines 1029**: Add validation check; if briefing is object instead of string, extract `.briefing` property
2. **Lines 1044–1048**: When splitting by `\n\n+`, first check if briefing is actually a string; if it's an object, JSON.stringify + parse
3. **Line 980–981**: Check `phase && phase.label` exists; if not, skip phase card entirely instead of rendering "Unknown"
4. **Line 1030**: Safely extract key_signals; if missing/not-array, default to `[]`
5. **Add defensive parsing**: Before rendering, run `Object.keys(data)` check to ensure data structure is valid

**Acceptance Criteria:**
- AI tab displays formatted briefing text, not raw JSON
- No "Here is the JSON requested:" debug messages visible
- Missing or null `rotation_phase` doesn't render a card with "Unknown" label
- `key_signals` array displays as bullet points (or hidden if empty)
- All frontend rendering is fault-tolerant: missing fields don't crash the tab

**Happy Path Success Case:**
- Load `data/ai/2026-06-12.json` with valid structure → renders perfectly
- Brief shows 3–5 bullet points + expandable full briefing
- Rotation phase shows icon + label + reasoning

**Edge Cases:**
- `data.sectors.briefing` is a JSON string `"{...}"` instead of parsed object → parse it
- `data.industries.rotation_phase` is null → skip phase card, show only briefing
- `data.sectors.key_signals` is `[null, null, "Energy..."]` → filter out nulls before render
- Empty briefing string `""` → show "No briefing for this date"
- Old cached files before normalization (malformed) → gracefully degrade to empty state

**Dependencies:**
- `renderAI()` function (lines 905–1077)
- `escapeHtml()` helper (used throughout for XSS prevention)
- `state.aiData` object structure

**Error/Failure Cases:**
- JSON.parse() fails on accidentally-stringified data → catch error, default to `{}`
- Phase object missing `label` → don't render phase card
- key_signals is not an array → coerce to `[]` or `[item]` if single string

**Follow-up Tasks:**
- Add debug mode (URL param `?debug=ai`) to log raw `state.aiData` in console for troubleshooting
- Add test for rendering with various malformed/incomplete AI data structures

---

### Task 4: Update GitHub Actions Workflow (Workflow)

**Purpose/Motivation:**  
Ensure the workflow environment supports the new force-regeneration behavior and logs relevant diagnostics.

**Detailed Description:**  
Update `.github/workflows/collect.yml` to confirm the AI step (lines 90–95):
1. Always executes (no conditional skip)
2. Logs API call counts and rate-limit diagnostics
3. Records outcome to fetch_log.csv for dashboard pipeline visibility

**Changes:**
1. Verify AI step runs if `steps.deltas.outcome == 'success'` (unchanged)
2. Add `Continue-on-error: true` if desired (allows workflow to complete even if AI fails)
3. Ensure `ai_run_summary.json` is always written (already done in script)

**Acceptance Criteria:**
- Workflow runs generate AI data every time (not skipped)
- fetch_log.csv records AI outcome (complete/partial/error)
- No breaking changes to existing workflow step order

**Happy Path Success Case:**
- Scheduled run at 22:05 UTC completes; ai_run_summary.json shows `"outcome": "complete"`
- fetch_log.csv adds row with ai_outcome = "complete"

**Dependencies:**
- `scripts/generate_ai.py` (modified by Task 1)
- `.github/workflows/collect.yml`

---

### Task 5: Add Tests for New Normalization & Parsing Logic (Tests)

**Purpose/Motivation:**  
Ensure backend and frontend changes are robust to malformed inputs and don't regress existing functionality.

**Detailed Description:**  
Add test cases in `tests/test_generate_ai.py` for:
1. Normalization of briefing responses (various shapes)
2. Normalization of phase responses (valid enum, free-form)
3. Fallback parsing behavior (preamble rejection, string wrapping)
4. End-to-end generation flow (no-cache behavior)

**Changes:**
1. Create `_normalize_briefing()` test with inputs: raw string, dict missing key_signals, dict with null values
2. Create `_normalize_phase()` test with inputs: valid enums, free-form labels, missing confidence
3. Create fallback parser tests to verify preamble detection and string wrapping
4. Mock Gemini API to return both valid JSON and preamble-wrapped responses

**Acceptance Criteria:**
- All new normalization functions have >90% branch coverage
- Tests cover happy path + 3+ edge cases per function
- Existing compute_deltas tests still pass

**Happy Path Success Case:**
- Run `pytest tests/test_generate_ai.py -v` → all pass

**Dependencies:**
- `pytest` (in requirements-dev.txt)
- `unittest.mock.patch` for mocking Gemini client

---

## Implementation Checklist

### Phase 1: Backend Changes (generate_ai.py)

- [ ] Remove cache check block (lines 794–805)
- [ ] Simplify main() to always set `existing_output = {}`
- [ ] Create `_normalize_briefing(parsed)` helper function
- [ ] Create `_normalize_phase(parsed)` helper function
- [ ] Update line 653–659 to call normalization functions
- [ ] Test locally: `python scripts/generate_ai.py` (with GEMINI_API_KEY)
- [ ] Verify output file has correct normalized structure

### Phase 2: Frontend Changes (docs/index.html)

- [ ] Add validation checks in `renderAI()` (line ~1029)
- [ ] Add defensive JSON parsing for briefing
- [ ] Update phase rendering to skip if missing/null
- [ ] Test in browser: load old/malformed AI JSON files and verify graceful fallback
- [ ] Verify no debug text appears

### Phase 3: Tests

- [ ] Add `tests/test_generate_ai.py` test cases
- [ ] Run `pytest tests/ -q` → all pass
- [ ] Verify git hook runs (if configured)

### Phase 4: Verification & Commit

- [ ] Manual test: trigger GitHub Actions workflow
- [ ] Verify ai_run_summary.json outcome is "complete" (not "skipped")
- [ ] Load dashboard in browser, check AI tab displays correctly
- [ ] Commit changes with clear message: `fix: force GenerateAI calls and normalize responses`
- [ ] Push to `claude/force-generateai-calls-fixes-edjqfd`
- [ ] Create draft PR if one doesn't exist

---

## Verification Strategy

**Backend verification (generate_ai.py):**
1. Set `GEMINI_API_KEY` locally
2. Run `python scripts/generate_ai.py`
3. Verify output file `data/ai/{date}.json` has complete structure:
   - `sectors.briefing`: string (not object)
   - `sectors.rotation_phase.label`: enum or free-form (not "Unknown" unless genuinely unknown)
   - `industries.briefing`: string
   - `sectors.daily_delta`: array of strings (if generated)
4. Run `python3 -m pytest tests/test_generate_ai.py -v`

**Frontend verification (docs/index.html):**
1. Start local web server: `python -m http.server 8000 -d docs/`
2. Open browser to `http://localhost:8000`
3. Load different AI data files (valid, incomplete, malformed) via developer console
4. Verify:
   - Briefing text displays as formatted paragraphs (not raw JSON)
   - Key signals show as bullet points
   - Rotation phase renders with icon + label (or is hidden if missing)
   - No errors in browser console
5. Screenshot result for comparison

**Workflow verification:**
1. Push branch to `claude/force-generateai-calls-fixes-edjqfd`
2. Trigger workflow manually via GitHub Actions UI
3. Check workflow logs:
   - `Generating AI analysis...` message appears (not "Skipping")
   - API call count > 0
   - `ai_run_summary.json` outcome is "complete" or "partial" (never "skipped")
4. Load dashboard, verify AI tab updates

---

## Files to Modify

| File | Type | Changes |
|------|------|---------|
| `scripts/generate_ai.py` | Backend | Remove cache check; add normalization helpers |
| `docs/index.html` | Frontend | Add validation/parsing in `renderAI()` |
| `tests/test_generate_ai.py` | Test | Add normalization + parsing tests |
| `.github/workflows/collect.yml` | Config | (Verify, likely no changes needed) |

---

## Rollback Strategy

If issues arise:
1. **Revert commit**: `git revert <commit-hash>`
2. **Restore cache**: Add back lines 794–805 with minimal modifications
3. **Reduced regeneration**: Instead of always regenerating, regenerate only if `delta_df.modified_at > file.mtime()`

---

## Notes

- **API cost**: Force regeneration increases Gemini calls from ~6 per day (3 runs, skipped if cache hit) to ~15+ per day (3 runs × 5 fields). Monitor free-tier quota.
- **Performance**: Each AI generation takes ~60–90s (rate-limited). Dashboard may show "Loading..." for longer after workflow starts.
- **Incremental fallback**: If API quota is exhausted mid-run, the file is still incomplete; next run will complete it (incremental logic remains in `generate_for_group()`).
