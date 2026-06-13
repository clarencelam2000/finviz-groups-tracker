# Implementation Plan: Smart Regeneration + Schema Enrichment

**Created:** 2026-06-12  
**Status:** Approved for Implementation  
**Scope:** Fix LLM schema violations and optimize API quota usage  
**Target Completion:** 3-4 weeks (Phase 1: 1 week, Phase 2: 2-3 weeks + monitoring)

---

## Context & Rationale

### Problem Statement

1. **API Waste:** Currently always regenerate AI analysis every workflow run, regardless of whether source data changed. ~15+ API calls/day vs optimal 6-10.

2. **LLM Schema Violations:** Gemini API sometimes violates schema constraints, returning preamble text or malformed JSON. Current code treats symptom (fallback parsing) not root cause. Proper structured output techniques can reduce violations dramatically.

3. **Maintenance Burden:** Manual JSON schemas (lines 23-96 in generate_ai.py) are error-prone and hard to evolve. Few-shot examples are minimal (1 per prompt). Prompts lack comprehensive guidance.

### Solution Approach

**Phase 1: Smart Regeneration with Force Flag**
- Detect if today's date appears in delta CSVs (checked directly in `generate_ai.py`)
- Skip AI regeneration if no changes detected (preserve API budget)
- Add `--force-ai` CLI flag to force regeneration when needed (manual testing, debugging)
- Maintain backward compatibility (default behavior safe)

**Phase 2: Schema Enrichment + Few-Shot Learning**
- Add `description` fields to all schemas and `additionalProperties: false` (guides LLM toward correct values, tightens contract)
- Add 2-3 few-shot examples per prompt to improve semantic quality and data specificity
- Add validation logging to track schema compliance over time
- Defer fallback parser removal until proven (2-4 weeks of 95%+ compliance monitoring)

### Why This Matters

- **API Cost:** Reduces unnecessary calls by ~40% on unchanged-data days (~2-3 days/week). On free tier, critical to avoid quota exhaustion.
- **Reliability:** Schema descriptions guide LLM toward correct values; few-shot examples improve data specificity. Current fallback approach loses information (phase label becomes "Unknown").
- **Maintainability:** Schema descriptions serve as inline documentation for the LLM and future implementers, easier to evolve than bare type constraints.
- **Observability:** Validation logging enables monitoring compliance trends and early detection of LLM degradation.

---

## Phase 1: Smart Regeneration with Force Flag

### Task 1.1: Add Skip Detection to generate_ai.py

**Purpose/Motivation:**  
Enable `generate_ai.py` to detect whether today's delta data exists before spending API quota. Checked directly in `generate_ai.py` by reading the delta CSVs — no changes to `compute_deltas.py` needed.

**Detailed Task Description:**

1. Add helper function to `scripts/generate_ai.py`:
   ```python
   def _has_new_delta_data(date_str: str) -> bool:
       """Return True if today's date appears in at least one delta CSV."""
       for subdir in ("sectors", "industries"):
           path = DATA_DIR / subdir / "deltas.csv"
           if not path.exists():
               continue
           try:
               df = pd.read_csv(path, dtype=str, usecols=["date"])
               if (df["date"] == date_str).any():
                   return True
           except Exception:
               pass
       return False
   ```

2. Call in `main()` after establishing `today` (before API key check):
   ```python
   if not force and not _has_new_delta_data(today):
       print(f"No new delta data for {today} — skipping AI regeneration.")
       _write_run_artifacts("skipped", False, time.monotonic() - run_start, today)
       sys.exit(0)
   ```

3. Missing or unreadable delta CSV → function returns `False` → skip (safe default; no data means nothing to analyze)

**Acceptance Criteria:**
- Returns `True` when today's date appears in sectors or industries delta CSV
- Returns `False` when neither CSV has today's date (including missing CSVs)
- CSV parse error → returns `False` → skip gracefully
- Function is unit-tested with `tmp_path` fixtures (no real file I/O)

**Happy Path:**
```
2026-06-12 run (post-close):
- compute_deltas has appended rows for 2026-06-12
- _has_new_delta_data("2026-06-12") → True
- AI generation proceeds
```

**Edge Cases:**
- Delta CSVs don't exist yet (first run) → returns `False` → skip; use `--force-ai` for first run
- CSV exists but only has prior-day rows → returns `False` → skip correctly
- Midday run before compute_deltas has run → returns `False` → skip (no data to analyze yet)

**Dependencies:** None (no changes to `compute_deltas.py`)

**Error/Failure Cases:**
- CSV missing columns or corrupt → caught by `except Exception` → returns `False` → skip

**Follow-up Tasks:**
- (Sprint) Add metric: track days skipped due to no changes
- (Backlog) Surface skip count in fetch_log.csv for trend monitoring

---

### Task 1.2: Implement Force Flag + Wire Skip Logic

**Purpose/Motivation:**  
Add `--force-ai` CLI flag and `FORCE_AI` env var override. Wire the skip check from Task 1.1 into `main()`.

**Detailed Task Description:**

1. Add argparse to `scripts/generate_ai.py` `main()`:
   ```python
   parser = argparse.ArgumentParser()
   parser.add_argument("--force-ai", action="store_true",
                       help="Force regeneration even if no new delta data")
   args = parser.parse_args()
   force = args.force_ai or bool(os.getenv("FORCE_AI"))
   ```

2. After establishing `today` (before API key check), add skip gate:
   ```python
   if not force and not _has_new_delta_data(today):
       print(f"No new delta data for {today} — skipping AI regeneration.")
       _write_run_artifacts("skipped", False, time.monotonic() - run_start, today)
       sys.exit(0)
   ```
   Placed before the API key check so no side-effects occur on skip.

3. When generating (force or changes present) → proceed with full generation from scratch (always regenerates; no partial-file loading).

4. Preserve artifacts (ai_run_summary.json, ai_run_log.jsonl) structure:
   - `outcome: "skipped"` when skip fires
   - Existing `outcome: "complete"` / `"partial"` / `"failed"` paths unchanged

**Acceptance Criteria:**
- CLI flag `--force-ai` bypasses skip
- `FORCE_AI=1` env var also bypasses skip
- No-change days: AI step exits 0 with `outcome: skipped`
- Change days: full regeneration proceeds
- Artifacts correctly show skip vs complete status

**Happy Path:**
```
Day 1 (new delta data for 2026-06-11):
  $ python scripts/generate_ai.py
  "Generating AI analysis for 2026-06-11..."
  [API calls made]
  outcome: complete

Day 2 (no new delta data — midday run):
  $ python scripts/generate_ai.py
  "No new delta data for 2026-06-12 — skipping AI regeneration."
  [No API calls]
  outcome: skipped

Day 2b (manual override):
  $ python scripts/generate_ai.py --force-ai
  "Generating AI analysis for 2026-06-12..."
  [API calls made]
  outcome: complete
```

**Edge Cases:**
- First run ever (no delta CSVs) → `_has_new_delta_data` returns False → skip; operator uses `--force-ai` for bootstrapping
- Snapshot date mismatch (rate-limit retry pushes past midnight): `today` is derived from snapshot date, not `date.today()` — existing logic unchanged

**Dependencies:** Task 1.1 must be complete

**Error/Failure Cases:**
- CSV unreadable → `_has_new_delta_data` returns False → skip (safe)
- CLI parse error → standard argparse error message

**Follow-up Tasks:**
- (Sprint) Update workflow to pass --force-ai from workflow_dispatch input
- (Backlog) Add dashboard UI toggle for force-regenerate

---

### Task 1.3: Update GitHub Actions Workflow

**Purpose/Motivation:**  
Enable manual workflow triggers with `force_ai` checkbox.

**Detailed Task Description:**

Modify `.github/workflows/collect.yml`:
1. Add workflow_dispatch input parameter:
   ```yaml
   on:
     schedule: [...]
     workflow_dispatch:
       inputs:
         force_ai:
           type: boolean
           default: false
           description: 'Force AI regeneration even if no changes detected'
   ```

2. Update "Generate AI analysis" step:
   ```yaml
   - name: Generate AI analysis
     if: steps.deltas.outcome == 'success'
     env:
       GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
     run: |
       FLAGS=""
       if [ "${{ github.event.inputs.force_ai }}" = "true" ]; then
         FLAGS="--force-ai"
       fi
       python scripts/generate_ai.py $FLAGS
   ```

3. Update README.md to document the flag and CLI usage

**Acceptance Criteria:**
- Workflow file is valid YAML
- Manual trigger UI shows force_ai checkbox
- Flag correctly passed to script
- README updated

**Dependencies:** Task 1.2 must be complete

**Error/Failure Cases:** None (standard workflow parameter syntax)

---

### Phase 1 Execution Summary

**Order:** 1.1 → 1.2 → 1.3  
**Estimated Time:** 4-7 hours  
**Testing:** Full workflow test on no-change day and force_ai trigger

---

## Phase 2: Schema Enrichment + Few-Shot Learning

### Task 2.1: Enrich Schema Descriptions + Add additionalProperties

**Purpose/Motivation:**  
All 5 schema dicts currently have zero `description` fields. Gemini uses `description` to understand what values are expected — adding them is the primary lever for improving semantic compliance (e.g., picking the right enum value, writing specific vs. vague content). `additionalProperties: false` tightens the contract and prevents silent extra fields. No new dependencies required.

Also fixes a pre-existing bug: `PHASE_SCHEMA` requires `confidence` but `_normalize_phase()` silently drops it.

**Detailed Task Description:**

1. Add `"description"` at the object level and to every property across all 5 schemas (`PHASE_SCHEMA`, `INDUSTRY_PHASE_SCHEMA`, `WATCHLIST_SCHEMA`, `BRIEFING_SCHEMA`, `DAILY_DELTA_SCHEMA`). Example for `PHASE_SCHEMA`:
   ```python
   PHASE_SCHEMA = {
       "type": "object",
       "description": "Market rotation phase classification for a given date.",
       "additionalProperties": False,
       "properties": {
           "label": {
               "type": "string",
               "description": "One of the four classic cycle phases. Choose based on which sector groups are leading.",
               "enum": ["Early Cycle", "Mid Cycle", "Late Cycle", "Defensive"],
           },
           "reasoning": {
               "type": "string",
               "description": "One sentence: which specific sectors are leading and why they indicate this phase.",
           },
           "confidence": {
               "type": "number",
               "description": "Confidence from 0.0 (uncertain) to 1.0 (very confident).",
           },
       },
       "required": ["label", "reasoning", "confidence"],
   }
   ```

2. Add `"additionalProperties": False` to all 5 schemas (supported by Gemini API as of Nov 2025).

3. Fix `_normalize_phase()` to preserve `confidence` instead of dropping it:
   ```python
   def _normalize_phase(parsed) -> dict:
       if isinstance(parsed, dict):
           return {
               "label": str(parsed.get("label") or "").strip(),
               "reasoning": str(parsed.get("reasoning") or "").strip(),
               "confidence": parsed.get("confidence"),  # None if absent; dashboard renders "N/A"
           }
   ```

4. No changes to `_call_api()`, `TASK_SPECS`, or `requirements.txt`.

**Acceptance Criteria:**
- All 5 schemas have `"description"` at the object level and on every property
- All 5 schemas have `"additionalProperties": False`
- `_normalize_phase()` passes `confidence` through to output
- Existing tests pass (no behavior change)
- No new dependencies added

**Happy Path:**
```
LLM receives schema with property descriptions
→ Selects correct enum label with high confidence
→ Writes specific reasoning citing sector names and metrics
→ JSON parsed successfully; confidence preserved in output
```

**Edge Cases:**
- `additionalProperties: false` rejected by a Gemini API version: remove only that field and log a warning; schemas still have descriptions
- `confidence` absent from LLM response: `_normalize_phase` returns `None` for field

**Dependencies:** None (independent of Phase 1)

**Error/Failure Cases:**
- Malformed schema dict (e.g., typo in key name) → caught at module import; existing tests catch this
- Validation still fails after enrichment → caught by existing fallback parsers (not removed until Task 2.4)

**Follow-up Tasks:**
- (Backlog) Add schema descriptions to `DAILY_DELTA_SCHEMA` nested array items once Task 2.3 confirms compliance baseline

---

### Task 2.2: Add Few-Shot Examples

**Purpose/Motivation:**  
Few-shot examples improve the *semantic quality* of LLM responses — helping the model write data-specific signals and choose correct values rather than generic statements. Note: syntactic JSON format is already guaranteed by structured output mode (`response_mime_type=application/json` + `response_schema`); few-shot examples address a different problem — the difference between "Energy is rising" and "Energy +12% YTD, rank improved 4 spots in 7 days."

**Detailed Task Description:**

1. **Phase Prompts** (sector and industry):
   Add few-shot section after phase definitions with 2 concrete examples showing format

2. **Watchlist Prompt** (already has format example; enhance):
   Add conviction rationale explaining when to use "strong", "moderate", "speculative"

3. **Briefing Prompt** (industry and sector):
   Add JSON-formatted example showing expected key_signals and briefing structure

4. **Industry Phase Prompt**:
   Similar to sector phase but with industry-specific examples

5. **Daily Delta Prompt** (if used):
   Add good vs bad examples showing specific metrics

**Acceptance Criteria:**
- Each prompt has 2-3 concrete few-shot examples
- Examples formatted identically to expected output
- Prompts remain <2000 tokens (readable)
- Tests pass (examples don't break parsing)

**Happy Path:**
```
LLM sees few-shot examples with format
→ Responds with identical format
→ Parser extracts data perfectly
```

**Edge Cases:**
- Examples too long → reduce to 2 per prompt
- Examples contain contradictions → align them
- LLM copies example numbers → parser handles gracefully

**Dependencies:** Task 2.1 (schema descriptions establish field guidance; examples build on that foundation)

**Error/Failure Cases:**
- Malformed examples → LLM learns incorrect format → fallback parser catches it
- Whitespace inconsistency → LLM output may not match expected format

**Follow-up Tasks:**
- (Sprint) A/B test: measure compliance improvement before/after
- (Backlog) Collect actual failures and create counter-examples

---

### Task 2.3: Add Validation Logging with Verbose Output

**Purpose/Motivation:**  
Track schema compliance over time with verbose real-time feedback during generation. Enable early detection of LLM degradation and monitoring for Task 2.4 (fallback parser removal decision).

**Detailed Task Description:**

1. Add validation tracking dict in module globals

2. Update `generate_for_group()` JSON parsing with verbose logging:
   - On success: print `"{fkey}: JSON OK"`
   - On fallback: print `"{fkey}: fallback ({error_msg})"`
   - Log status to _validation_log dict

3. Extend `ai_run_summary.json` to include validation metrics:
   - Add `validation` dict with per-field status (ok/fallback/error)
   - Add `compliance_rate` calculation (ok_count / total_count)

4. Keep fallback parsers unchanged (no removal until Task 2.4)

**Acceptance Criteria:**
- ai_run_summary.json includes validation dict
- Each field has status (ok/fallback/error)
- No crashes from logging itself
- Log entries are valid JSON
- Fallback behavior unchanged
- Verbose output to stdout during generation

**Happy Path:**
```
$ python scripts/generate_ai.py
Generating AI analysis for 2026-06-12...
  sectors.briefing: JSON OK
  sectors.rotation_phase: fallback (JSONDecodeError: ...)
  sectors.watchlist: JSON OK
  industries.briefing: JSON OK
  industries.rotation_phase: JSON OK
  industries.watchlist: JSON OK

Summary written to ai_run_summary.json:
  compliance_rate=0.83 (5 ok, 1 fallback)
```

**Edge Cases:**
- Logging JSON serialization fails → print warning, continue
- _validation_log grows large → won't happen (single daily run)

**Dependencies:** Task 2.1 and 2.2 should be done first

**Error/Failure Cases:**
- JSON serialization fails in summary write → don't crash, skip this field
- Validation dict is missing in output → add default empty dict

**Follow-up Tasks:**
- (Sprint) Dashboard graph: compliance rate over time
- (Backlog) Alerting: if compliance <90%, send notification
- (Sprint 2.4) Decide to remove fallback parsers based on 2-4 week monitoring

---

### Task 2.4: Remove Fallback Parsers (Deferred)

**Purpose/Motivation:**  
Once schema enrichment + few-shot examples have proven reliable (2-4 weeks at ≥95% compliance), remove the fallback parsers for simplicity.

**Detailed Task Description:**

This task is intentionally deferred until Phase 2.1-2.3 deployed and monitored in production. Proceed only if:
- 100+ runs with ≥95% JSON compliance
- No increase in fallback logs over 2 weeks
- No regression in AI output quality

When confident:
1. Remove `parse_briefing_response()`, `parse_watchlist_response()`, `parse_phase_response()` functions
2. Replace try/except fallback path with direct `_normalize_*()` on parsed JSON
3. Remove `fallback_parse` from TASK_SPECS
4. Update error handling to be graceful (field marked as error on JSON parse failure)

**Acceptance Criteria:**
- Fallback parsers removed
- Direct parse + normalize in place
- Tests updated (no fallback test cases)
- Error handling graceful
- No regressions after 1 week

**Happy Path:**
```
Response: Valid JSON (guaranteed by structured output mode)
→ json.loads() succeeds
→ _normalize_*() extracts fields
→ Stored in output file
```

**Dependencies:** Task 2.1-2.3 must be deployed and stable for 2-4 weeks

**Error/Failure Cases:**
- Malformed JSON despite structured output → `json.loads()` raises → caught by outer try/except, field marked as error
- No fallback parser to catch errors → errors logged, output file incomplete (acceptable; next run regenerates)

**Follow-up Tasks:**
- (Backlog) Investigate remaining errors (if any) and update prompts/schemas

---

### Phase 2 Execution Summary

**Order:** 2.1 & 2.2 (parallel) → 2.3 → (monitor 2-4 weeks) → 2.4  
**Estimated Time:** 7-11 hours (phases 1-3), 2-4 weeks monitoring  
**Testing:** Unit tests, integration tests, production monitoring

---

## Overall Execution Plan

### Week 1 (Phase 1)
- Mon: Task 1.1 (`_has_new_delta_data()` + skip in `main()`) + testing
- Tue: Task 1.2 (argparse + force flag) + testing
- Wed: Task 1.3 (workflow YAML + docs) + testing
- Thu-Fri: Full workflow testing (no-change day, force_ai trigger, normal day)
- Commit to branch, create PR

### Week 2-3 (Phase 2.1-2.3)
- Phase 2.1: Schema descriptions + `additionalProperties` + confidence fix
- Phase 2.2: Few-shot examples (parallel with 2.1)
- Phase 2.3: Validation logging
- Full testing and integration
- Commit to branch, create PR

### Week 4+ (Monitoring)
- Monitor compliance metrics from ai_run_summary.json
- Collect validation logs
- Evaluate fallback parser removal criteria for Task 2.4

---

## Files Modified

### Phase 1:
- `scripts/generate_ai.py` — Add `_has_new_delta_data()`, argparse, skip logic in `main()`
- `.github/workflows/collect.yml` — Add workflow input parameter
- `README.md` — Document --force-ai flag

### Phase 2:
- `scripts/generate_ai.py` — Schema descriptions, `additionalProperties`, `_normalize_phase` confidence fix, few-shot in prompts, validation logging
- `tests/test_generate_ai.py` — New tests for skip logic, schema descriptions, compliance_rate

---

## Verification Strategy

### Unit Tests
- Phase 1: `_has_new_delta_data()` with CSV fixtures, skip path in `main()`, force flag, env var
- Phase 2: schema descriptions present on all properties, `additionalProperties` constraints, `confidence` field preserved, few-shot examples in prompts, validation logging

### Integration Tests
- Full workflow: collect → compute (no changes) → generate → skip
- Full workflow: collect → compute (with changes) → generate → regenerate
- Manual trigger: force_ai=true → regenerates
- Compliance: few-shot examples in sent prompts
- Validation: artifacts include validation_failures

### Regression Tests
- Ensure no increase in average API calls per run
- Ensure no increase in error_field logs
- Spot-check output quality (subjective review of actual JSON)

### Production Monitoring (Phase 2)
- Track compliance_rate from ai_run_summary.json over 2+ weeks
- Alert if compliance <90%
- Collect any validation failures for analysis

---

## Rollback Strategy

**Phase 1 Rollback:**
- If skip logic fires incorrectly: set `FORCE_AI=1` in workflow env vars as a kill-switch while diagnosing
- If `_has_new_delta_data()` has a false-negative bug: remove the skip check from `main()` (2-line revert)
- Cost: Only extra API calls on no-change days

**Phase 2 Rollback:**
- If schema descriptions cause unexpected Gemini API behavior: remove description fields (backward-compatible change; descriptions are optional in JSON Schema)
- If `additionalProperties: false` causes API errors: remove that constraint only
- If few-shot examples don't help: remove examples from prompts
- Fallback parsers always in place (until Task 2.4 removes them)

---

## Success Criteria

### Phase 1 Complete When:
- [ ] `_has_new_delta_data()` exists in `generate_ai.py` and is unit-tested with CSV fixtures
- [ ] `generate_ai.py` skips when delta CSVs lack today's date
- [ ] `--force-ai` flag forces regeneration
- [ ] `FORCE_AI` env var also works
- [ ] Workflow accepts `force_ai` input parameter
- [ ] README updated
- [ ] 5+ test runs confirm skip and generate paths behave correctly

### Phase 2 Complete When:
- [ ] All 5 schemas have `"description"` on every property and `"additionalProperties": False`
- [ ] `_normalize_phase()` preserves `confidence` field in output
- [ ] Few-shot examples present in briefing and watchlist prompts
- [ ] Validation logging tracks failures with verbose output
- [ ] `ai_run_summary.json` includes `compliance_rate`
- [ ] Tests updated and passing
- [ ] 2+ weeks production data shows ≥95% compliance
- [ ] Decision made on Task 2.4 (fallback parser removal)

---

## Sources

Research on Gemini API capabilities was conducted via:
- [Structured outputs - generateContent API](https://ai.google.dev/gemini-api/docs/structured-output)
- [Prompt design strategies | Gemini API](https://ai.google.dev/gemini-api/docs/prompting-strategies)
- [Structured output | Gemini Enterprise Agent Platform](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/capabilities/control-generated-output)

Key findings:
- Gemini structured output (`response_mime_type=application/json` + `response_schema`) guarantees syntactic correctness but not semantic correctness
- `description` fields in the schema are the primary lever for improving semantic compliance (correct enum values, specific content)
- Few-shot examples improve semantic quality; they address a different problem than JSON format compliance
- `additionalProperties: false` is supported in Gemini API as of November 2025
- Gemini accepts both dict schemas and Pydantic BaseModels for `response_schema`; dict schemas require no new dependency
