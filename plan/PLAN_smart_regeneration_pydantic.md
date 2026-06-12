# Implementation Plan: Smart Regeneration + Pydantic Migration

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
- Detect if `compute_deltas.py` found new data (write status file)
- Skip AI regeneration if no changes detected (preserve API budget)
- Add `--force-ai` CLI flag to force regeneration when needed (manual testing, debugging)
- Maintain backward compatibility (default behavior safe)

**Phase 2: Pydantic + Few-Shot Learning**
- Migrate manual JSON schemas → Pydantic BaseModels (type safety, better IDE support)
- Add 2-3 few-shot examples per prompt (research shows critical for format compliance)
- Enhance field descriptions to guide LLM toward compliance
- Add validation logging to track schema violations over time
- Defer fallback parser removal until proven (2-4 weeks of 95%+ compliance monitoring)

### Why This Matters

- **API Cost:** Reduces unnecessary calls by ~40% on unchanged-data days (~2-3 days/week). On free tier, critical to avoid quota exhaustion.
- **Reliability:** Pydantic + few-shot research shows 95%+ JSON compliance. Current fallback approach loses information (phase label becomes "Unknown").
- **Maintainability:** Pydantic models are self-documenting, easier to evolve as schema requirements change.
- **Observability:** Validation logging enables monitoring compliance trends and early detection of LLM degradation.

---

## Phase 1: Smart Regeneration with Force Flag

### Task 1.1: Write Delta Status File

**Purpose/Motivation:**  
Enable `generate_ai.py` to detect whether `compute_deltas.py` found new data. Skip regeneration on no-change days to conserve API quota.

**Detailed Task Description:**

1. Modify `scripts/compute_deltas.py` to write a status file after both group types are processed:
   - File: `data/deltas_run_status.json` (ephemeral, not committed)
   - Format (with timestamp for diagnostic purposes):
     ```json
     {
       "date": "YYYY-MM-DD",
       "completed_at": "2026-06-12T22:15:30.123456Z",
       "has_changes": true|false,
       "groups": {
         "sector": {"new_rows": 8},
         "industry": {"new_rows": 115}
       }
     }
     ```
   - `has_changes=true` if EITHER sector OR industry had new rows
   - Always overwrite (last run wins)

2. Write file at END of `main()`, after all `compute_for_group()` calls complete with `completed_at` timestamp
3. Only write if at least one group had rows (safe: missing file treated as "changes found")

**Acceptance Criteria:**
- File created every run with valid JSON
- Counts match actual delta rows appended
- If both groups have 0 new rows → `has_changes: false`
- File is readable and parseable
- Timestamp in ISO 8601 format

**Happy Path:**
```
2026-06-12 run:
- Finviz snapshots collected (8 sectors, 115 industries)
- compute_deltas appends 8 sector + 115 industry rows
- deltas_run_status.json written:
  {"date": "2026-06-12", "completed_at": "2026-06-12T22:15:30Z", "has_changes": true, 
   "groups": {"sector": {"new_rows": 8}, "industry": {"new_rows": 115}}}
```

**Edge Cases:**
- No snapshot data → 0 rows → has_changes=false
- compute_deltas crashes → status file not written (generate_ai defaults to regenerate, safe)
- Concurrent runs → last one wins (acceptable for daily cadence)

**Dependencies:** None

**Error/Failure Cases:**
- File write fails → print warning, don't crash (let generate_ai handle missing file)
- JSON corruption → log error, regenerate anyway

**Follow-up Tasks:**
- (Sprint) Add metric: track days skipped due to no changes
- (Backlog) Add `--no-skip` flag to compute_deltas for forcing full recomputation

---

### Task 1.2: Implement Skip Logic + CLI Flag

**Purpose/Motivation:**  
Check delta status and skip regeneration if no changes detected. Allow manual override via `--force-ai` flag.

**Detailed Task Description:**

1. Add argparse to `scripts/generate_ai.py` `main()`:
   ```python
   parser = argparse.ArgumentParser()
   parser.add_argument("--force-ai", action="store_true", 
                       help="Force regeneration even if no changes detected")
   args = parser.parse_args()
   ```

2. At start of `main()`, after API key check:
   - Try to read `data/deltas_run_status.json`
   - If file valid AND `has_changes==false` AND `not args.force_ai` AND `not os.getenv("FORCE_AI")`:
     - Print: `"No changes detected in deltas — skipping AI regeneration."`
     - Load most recent existing AI file (up to 5 days back)
     - Write artifacts with `outcome: "skipped"`
     - Exit with code 0
   - If file missing/invalid → regenerate (safe default)
   - If changes detected OR force flag set → proceed with full generation

3. Keep existing incremental logic:
   - Load existing AI file for today if it exists
   - Call `generate_for_group()` with existing data to fill partial fields
   - Write complete artifacts

4. Preserve artifacts (ai_run_summary.json, ai_run_log.jsonl) structure:
   - Add field: `was_skipped: true` when skipped
   - Record which prior file was reused

**Acceptance Criteria:**
- CLI flag `--force-ai` works
- Environment variable `FORCE_AI=true` also works
- No-change days: AI step skipped, prior file reused
- Change days: full regeneration proceeds
- Artifacts correctly show skip vs complete status
- Missing status file does NOT prevent regeneration

**Happy Path:**
```
Day 1 (changes detected):
  $ python scripts/generate_ai.py
  "Generating AI analysis for 2026-06-11..."
  [API calls made]
  outcome: complete

Day 2 (no changes):
  $ python scripts/generate_ai.py
  "No changes detected in deltas — skipping AI regeneration."
  [No API calls; reuse 2026-06-11.json]
  outcome: skipped

Day 2b (manual override):
  $ python scripts/generate_ai.py --force-ai
  "Generating AI analysis for 2026-06-12..."
  [API calls made]
  outcome: complete
```

**Edge Cases:**
- No prior AI file on first run → regenerate (expected)
- Prior file >5 days old → don't reuse (gap too large); generate new
- Status file says changes but snapshot empty → regenerate (safe)

**Dependencies:** Task 1.1 must be complete

**Error/Failure Cases:**
- Status file corrupt → log warning, regenerate
- No prior AI file available → generate new
- CLI parse fails → standard argparse error

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

## Phase 2: Pydantic + Few-Shot Learning

### Task 2.1: Convert Schemas to Pydantic

**Purpose/Motivation:**  
Replace error-prone manual JSON schemas with Pydantic BaseModels for type safety, better IDE support, and automatic schema generation.

**Detailed Task Description:**

1. Add `pydantic>=2.0` to `requirements.txt`

2. In `scripts/generate_ai.py`, replace lines 23-96 (manual JSON schemas) with Pydantic models:
   - `PhaseLabel`: Sector rotation phase (enum labels)
   - `IndustryPhaseLabel`: Industry micro-phase (free-form label)
   - `WatchlistPick`: Single setup with conviction
   - `WatchlistResponse`: Exactly 3 picks
   - `BriefingResponse`: Key signals + briefing text
   - `DailyDeltaResponse`: Changes vs yesterday

3. Update TASK_SPECS (lines 482-528) to reference Pydantic classes instead of dict schemas

4. Update `_call_api()` to handle Pydantic models:
   - Check if `response_schema` has `model_json_schema()` method
   - Convert to JSON schema dict for Gemini API

**Acceptance Criteria:**
- All 4 schema defs are Pydantic models
- Fields have comprehensive descriptions
- Pydantic validation works on sample responses
- Existing tests pass (no functionality change)
- No import errors

**Happy Path:**
```python
response_json = '{"label": "Late Cycle", "reasoning": "Energy leads...", "confidence": 0.85}'
phase = PhaseLabel.model_validate_json(response_json)
assert phase.label == "Late Cycle"
```

**Edge Cases:**
- Pydantic v1 vs v2 → lock to v2 in requirements.txt
- Schema generation adds extra fields → Gemini ignores them
- LLM returns partial model → validation fails, caught by fallback parser

**Dependencies:** Task 2.2 (prompts need updating in parallel)

**Error/Failure Cases:**
- Pydantic import missing → error at import time (caught at top of file)
- Validation fails → caught by existing try/except in `generate_for_group()`

**Follow-up Tasks:**
- (Backlog) Export Pydantic models to API output (type validation at write time)

---

### Task 2.2: Add Few-Shot Examples

**Purpose/Motivation:**  
Few-shot examples significantly improve LLM compliance with structured output formats. Current prompts have minimal examples; adding 2-3 per prompt improves format consistency and field adherence.

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

**Dependencies:** Task 2.1 (Pydantic models define expected structure)

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
Once Pydantic validation is proven reliable (2-4 weeks at ≥95% compliance), remove legacy code for simplicity.

**Detailed Task Description:**

This task is intentionally deferred until Phase 2.1-2.3 deployed and monitored in production. Proceed only if:
- 100+ runs with ≥95% JSON compliance
- No increase in fallback logs over 2 weeks
- No regression in AI output quality

When confident:
1. Remove `parse_briefing_response()`, `parse_watchlist_response()`, `parse_phase_response()` functions
2. Replace try/except with direct Pydantic validation
3. Remove `fallback_parse` from TASK_SPECS
4. Update error handling to be graceful

**Acceptance Criteria:**
- Fallback parsers removed
- Direct Pydantic validation in place
- Tests updated (no fallback test cases)
- Error handling graceful
- No regressions after 1 week

**Happy Path:**
```
Response: Valid JSON or Gemini structured output
→ Parse with Pydantic directly
→ Field validation succeeds
→ Stored in output file
```

**Dependencies:** Task 2.1-2.3 must be deployed and stable for 2-4 weeks

**Error/Failure Cases:**
- Schema-invalid response → raises ValidationError → caught by outer try/except, field marked as error
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
- Mon: Task 1.1 (compute_deltas status file) + testing
- Tue: Task 1.2 (generate_ai skip logic + CLI flag) + testing
- Wed: Task 1.3 (workflow YAML + docs) + testing
- Thu-Fri: Full workflow testing (no-change day, force_ai trigger, normal day)
- Commit to branch, create PR

### Week 2-3 (Phase 2.1-2.3)
- Phase 2.1: Pydantic model definitions
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
- `scripts/compute_deltas.py` — Write status file
- `scripts/generate_ai.py` — Read status, add CLI flag, skip logic
- `.github/workflows/collect.yml` — Add workflow input parameter
- `README.md` — Document --force-ai flag

### Phase 2:
- `requirements.txt` — Add pydantic
- `scripts/generate_ai.py` — Major refactoring (schemas, prompts, logging)
- `tests/test_generate_ai.py` — New tests

---

## Verification Strategy

### Unit Tests
- Phase 1: status file creation, skip logic, CLI flag, env var
- Phase 2: Pydantic validation, few-shot examples in prompts, validation logging

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
- If skip logic causes issues: remove status file check, always regenerate
- If deltas status file not written: defaults to regenerate (safe)
- Cost: Only extra API calls on no-change days

**Phase 2 Rollback:**
- If Pydantic validation too strict: revert to manual JSON schemas
- If few-shot examples don't help: remove examples from prompts
- Fallback parsers always in place (until Task 2.4 removes them)

---

## Success Criteria

### Phase 1 Complete When:
- [ ] compute_deltas.py writes correct deltas_run_status.json with timestamp
- [ ] generate_ai.py reads status and skips on no-change days
- [ ] --force-ai flag forces regeneration
- [ ] FORCE_AI env var also works
- [ ] Workflow accepts force_ai input parameter
- [ ] README updated
- [ ] 5+ test runs confirm behavior

### Phase 2 Complete When:
- [ ] All schemas converted to Pydantic models
- [ ] Few-shot examples present in all prompts
- [ ] Validation logging tracks failures with verbose output
- [ ] ai_run_summary.json includes validation metrics and compliance_rate
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
- Gemini supports Pydantic BaseModel for schema definitions with automatic JSON schema generation
- Few-shot examples with consistent formatting significantly improve LLM compliance
- Clear field descriptions in schemas guide the model toward compliance
- Structured output guarantees syntactic correctness but not semantic correctness (validation still needed)
- As of November 2025, additionalProperties keyword is now supported in Gemini API
