# Implementation Plan: Smart Regeneration + Schema Improvement

**Created:** 2026-06-12  
**Revised:** 2026-06-12 (staff-engineer review pass)  
**Status:** Approved — revised before implementation  
**Scope:** Fix LLM schema violations and optimize API quota usage  
**Target Completion:** 2-3 weeks (Phase 1: 1 week, Phase 2: 1-2 weeks)

---

## Staff-Engineer Review Notes

The original plan was sound in intent but had several implementation issues caught before work began:

1. **Task 1.2 referenced removed logic.** The plan said "Keep existing incremental logic: load existing AI file, call `generate_for_group()` with existing data." That code was removed — `existing_output = {}` is hardcoded empty and `test_main_force_regenerates_complete_file` explicitly asserts always-regenerate. The plan described a feature that no longer exists.

2. **Status file creates unnecessary coupling.** Writing `data/deltas_run_status.json` from `compute_deltas.py` and reading it in `generate_ai.py` establishes an implicit inter-script contract. `generate_ai.py` can instead query the delta CSVs directly — same semantic, zero contract.

3. **Pydantic is over-engineered for this problem.** The 5 schema dicts (~70 lines) are simple. Gemini's `response_schema` already accepts dict schemas natively; adding Pydantic requires a new heavyweight dependency and an `isinstance` dispatch in `_call_api`. The actual compliance gains come from `description` fields in the schema properties and `additionalProperties: false` — both achievable in plain dicts with no new dep.

4. **Syntactic vs semantic compliance conflation.** `response_mime_type=application/json` + `response_schema` already guarantees syntactic JSON. If preambles appear despite structured output mode, that is an API configuration issue, not a few-shot problem. Few-shot examples *do* improve semantic quality (correct enum values, specific signals) — but that's a different benefit and should be stated separately.

5. **`confidence` field is silently dropped.** `PHASE_SCHEMA` requires `confidence` but `_normalize_phase()` discards it. Not a plan-breaking bug but should be resolved before Phase 2 touches those schemas.

6. **Validation logging already half-exists.** `_field_log` + `ai_run_log.jsonl` already track per-field status, elapsed time, and error strings. Task 2.3 is an extension of existing infrastructure, not new build.

---

## Context & Rationale

### Problem Statement

1. **API Waste:** The workflow runs 3× daily (14:00 UTC midday, 22:05 UTC post-close, 23:35 UTC nightly). All three currently call Gemini even when Finviz data has not changed — e.g., the 14:00 UTC midday run often scrapes data identical to yesterday's close. Actual useful calls: ~6-10/day. Current: ~15+.

2. **LLM Schema Violations:** Despite structured output mode (`response_mime_type=application/json` + `response_schema`), Gemini occasionally returns preamble text or malformed JSON. The code correctly retries on preambles (`_looks_like_preamble`) but the fallback parsers that catch JSON decode failures suggest schema guidance is insufficient. Adding `description` to schema properties is the correct lever — not few-shot examples (which would improve semantic quality for a different reason).

3. **Maintenance Burden:** Schema dicts at lines 23-96 lack field-level descriptions. This means the LLM has no guidance on *what* values are expected beyond type/enum. `additionalProperties` is not constrained. Improving descriptions and tightening the schema is lower-risk than a Pydantic migration.

### Why Pydantic Is Not in This Plan

The original plan proposed Pydantic v2 for "type safety and IDE support." After review:
- Gemini's `response_schema` accepts dict schemas natively (verified). No adapter needed.
- IDE support: Python `TypedDict` provides static typing with zero new dependencies and works with the existing dict schema pattern.
- Validation: the existing fallback parser + `_normalize_*` chain already handles malformed responses. Adding Pydantic validation would be a third layer, not a replacement.
- Adding `description` fields to the existing dict schemas is a targeted, low-risk change that directly addresses the compliance root cause.

**Decision: Keep dict schemas. Enrich them with `description` fields and `additionalProperties: false`.**

---

## Phase 1: Smart Regeneration with Force Flag

### Task 1.1: Add Skip Logic to generate_ai.py

**Purpose/Motivation:**  
Skip AI generation when today's delta rows don't exist yet (no new Finviz data). Preserve API quota on the 14:00 UTC midday run and any run where `collect.py` / `compute_deltas.py` found nothing new.

**Approach — check delta CSVs directly (no status file):**

`generate_ai.py` already loads delta CSVs via `load_latest_delta()`. The skip check reads the same files:

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
    return False  # missing or unreadable files treated as "no data"
```

Rationale: eliminates the inter-script file contract entirely. `generate_ai.py` is already the consumer of delta data — it is natural for it to check that data directly. If the delta CSV doesn't have today's rows, there is nothing new to analyze.

**Detailed Task Description:**

1. Add `_has_new_delta_data(date_str: str) -> bool` function (above).

2. Add argparse to `main()`:
   ```python
   parser = argparse.ArgumentParser()
   parser.add_argument("--force-ai", action="store_true",
                       help="Force regeneration even if no new delta data")
   args = parser.parse_args()
   force = args.force_ai or bool(os.getenv("FORCE_AI"))
   ```

3. After establishing `today` (snapshot-date logic), before the API key check:
   ```python
   if not force and not _has_new_delta_data(today):
       print(f"No new delta data for {today} — skipping AI regeneration.")
       _write_run_artifacts("skipped", False, time.monotonic() - run_start, today)
       sys.exit(0)
   ```
   Exit **before** checking the API key so no import side-effects occur on skip.

4. Remove `was_incremental` variable and the dead `existing_output = {}` / incremental completion code block in current `main()`. It is already dead code (always `{}`); removing it makes `main()` easier to read.

**Acceptance Criteria:**
- `python scripts/generate_ai.py` exits 0 silently when delta CSVs lack today's date
- `python scripts/generate_ai.py --force-ai` bypasses skip even when no delta data
- `FORCE_AI=1 python scripts/generate_ai.py` same result
- `ai_run_summary.json` has `outcome: "skipped"` on skip
- Missing or unreadable delta CSV → treated as "no data" → skip (safe default)
- Tests pass

**Edge Cases:**
- First-ever run (delta CSV doesn't exist) → skips correctly (no data to analyze)
- delta CSV exists but only has prior-day rows → skips correctly
- force flag set → always generates regardless of CSV state
- Rate-limit retry pushes run past midnight UTC: `today` is derived from snapshot date, not `date.today()` — existing logic handles this

**No status file is written. No changes to `compute_deltas.py`.**

**Dependencies:** None

**Error/Failure Cases:**
- CSV parse error → `_has_new_delta_data` returns `False` → skip (safe)
- `FORCE_AI` env var set to any truthy string → force regeneration

---

### Task 1.2: Update GitHub Actions Workflow

**Purpose/Motivation:**  
Add `force_ai` manual-dispatch input so operators can trigger full regeneration (debugging, model updates, reprocessing).

**Detailed Task Description:**

Modify `.github/workflows/collect.yml`:

1. Add `workflow_dispatch` inputs (merge with existing `workflow_dispatch` if present):
   ```yaml
   on:
     schedule: [...]  # unchanged
     workflow_dispatch:
       inputs:
         force_ai:
           type: boolean
           default: false
           description: 'Force AI regeneration even if no new delta data'
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

3. Update README.md: document `--force-ai` flag and when to use it.

**Acceptance Criteria:**
- Workflow YAML is valid (run `yamllint` or check Actions UI)
- Manual trigger shows `force_ai` checkbox
- Flag correctly passed through to script
- Scheduled runs do not set `FORCE_AI` (no regression)

**Dependencies:** Task 1.1 complete

---

### Phase 1 Execution Summary

**Order:** 1.1 → 1.2 (sequential; 1.2 depends on 1.1's CLI flag)  
**Estimated Time:** 3-5 hours  
**Changes to `compute_deltas.py`:** None  
**Testing:** Unit tests for `_has_new_delta_data`, skip-path in `main()`, force flag behavior

---

## Phase 2: Schema Enrichment + Semantic Quality

> **Scope change from original plan:** Pydantic migration removed. Schema enrichment via description fields is the correct lever for compliance. Few-shot examples are retained but repositioned as a semantic quality tool, not a JSON format tool.

### Task 2.1: Enrich Schema Descriptions + Add additionalProperties Constraints

**Purpose/Motivation:**  
Gemini uses `description` fields in the JSON schema to guide field values. Currently all 5 schemas have zero descriptions. This is the primary lever for improving semantic compliance (e.g., LLM picking the right enum value, writing specific vs. vague signals).

`additionalProperties: false` tightens the contract so Gemini doesn't return extra fields that silently get ignored.

**Detailed Task Description:**

1. For each schema dict, add `description` to the `properties` level and field level:

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
               "description": "One sentence explaining which sector groups are leading and why they indicate this phase.",
           },
           "confidence": {
               "type": "number",
               "description": "Confidence in this classification from 0.0 (uncertain) to 1.0 (very confident).",
           },
       },
       "required": ["label", "reasoning", "confidence"],
   }
   ```

2. Apply same treatment to `INDUSTRY_PHASE_SCHEMA`, `WATCHLIST_SCHEMA`, `BRIEFING_SCHEMA`, `DAILY_DELTA_SCHEMA`. Each property should have a `description` that gives the LLM concrete guidance on what to write.

3. Fix `_normalize_phase()` to preserve `confidence` instead of silently dropping it:
   ```python
   def _normalize_phase(parsed) -> dict:
       if isinstance(parsed, dict):
           return {
               "label": str(parsed.get("label") or "").strip(),
               "reasoning": str(parsed.get("reasoning") or "").strip(),
               "confidence": parsed.get("confidence"),  # None if absent
           }
       ...
   ```
   Update dashboard and tests to handle the optional `confidence` field.

4. Verify that `additionalProperties: False` is accepted by `google.genai` structured output. (Per the plan's own research notes: supported as of November 2025.)

**Acceptance Criteria:**
- All 5 schemas have `description` at the object level and every property
- All schemas have `additionalProperties: false`
- `_normalize_phase()` passes `confidence` through to output
- Existing tests pass
- No new dependencies added

**Dependencies:** None (independent of Phase 1)

**Error/Failure Cases:**
- `additionalProperties: false` rejected by Gemini API: fall back to removing it only from problematic schemas; log a warning
- `confidence` missing from LLM response: `_normalize_phase` returns `None` for the field, dashboard renders "N/A"

---

### Task 2.2: Add Few-Shot Examples for Semantic Quality

**Purpose/Motivation:**  
Few-shot examples improve the *semantic quality* of responses — getting the LLM to write specific, data-grounded signals rather than generic ones. This is distinct from JSON format compliance (which structured output handles). The watchlist and briefing prompts benefit most.

Note: few-shot examples belong in the prompt text, not the schema. JSON format is guaranteed by `response_mime_type="application/json"`.

**Detailed Task Description:**

1. **Briefing prompt** (`build_briefing_prompt`): Add a "good vs bad" example showing the expected specificity level:
   ```
   EXAMPLE OUTPUT (for illustration only — do not copy, use the real data above):
   {
     "key_signals": [
       "Energy +12.3% YTD, rank improved 4 spots in 7 days to #1",
       "Healthcare -2.1% month, rank dropped 3 spots vs 7 days ago"
     ],
     "briefing": "Energy leads broadly across all timeframes..."
   }
   ```

2. **Watchlist prompts** (sector and industry): Add 1 example pick showing the expected specificity for `thesis`:
   ```
   EXAMPLE FORMAT (illustrative):
   1. NAME: Energy | THESIS: YTD rank #1 with +4 spots 7d improvement; momentum 0.85 confirms trend | CONVICTION: strong
   ```
   Distinguish what makes a "strong" thesis: it references specific metrics from the data, not generic statements.

3. **Phase prompts**: The enum already constrains the label. Focus examples on `reasoning` quality:
   ```
   GOOD reasoning: "Energy (+12% YTD, rank #1) and Materials (+8% YTD) leading while Utilities (-3%) lags — classic Late Cycle pattern."
   BAD reasoning: "Energy is doing well which suggests Late Cycle."
   ```

4. Keep total prompt length under 2000 tokens — reduce example count if needed.

**Acceptance Criteria:**
- Each prompt has 1-2 concrete examples (not 3; 1 is sufficient for format, 2 max for quality)
- Examples show specific metrics, not generic statements
- Prompts remain under 2000 tokens
- No new API calls added (examples are static strings in prompts)
- Tests still pass (examples don't break parsers)

**Dependencies:** Task 2.1 (descriptions enrich schema; examples address prompt quality)

---

### Task 2.3: Extend Validation Logging

**Purpose/Motivation:**  
`_field_log` and `ai_run_log.jsonl` already track per-field status. Extend `ai_run_summary.json` to include a `compliance_rate` so the workflow's "Log fetch result" step and future dashboard work can surface trends.

This is an *extension* of existing infrastructure, not a new build.

**Detailed Task Description:**

1. Extend `_write_run_artifacts()` to compute and add compliance metrics to `ai_run_summary.json`:
   ```python
   ok_fields = [k for k, v in _field_log.items() if v.get("status") == "ok"]
   fallback_fields = [k for k, v in _field_log.items() if v.get("status") == "error"]
   total = len(_field_log)
   compliance_rate = round(len(ok_fields) / total, 3) if total else None

   summary = {
       "outcome": outcome,
       "fields_missing": ",".join(error_fields),
       "compliance_rate": compliance_rate,
       "fallback_fields": ",".join(fallback_fields),
   }
   ```

2. Add verbose per-field logging to stdout during generation (already logged via `print` on error; add explicit OK logging):
   ```python
   # In generate_for_group after _record_field:
   print(f"    {fkey}: {status}")
   ```

3. Extend `ai_run_log.jsonl` entries (already written) to include `compliance_rate` alongside existing fields. No schema change needed — it's append-only JSONL, backward compatible.

4. Do NOT remove fallback parsers yet (that is Task 2.4, deferred).

**Acceptance Criteria:**
- `ai_run_summary.json` includes `compliance_rate` (0.0–1.0) and `fallback_fields`
- Stdout shows per-field status during generation
- `ai_run_log.jsonl` entries include `compliance_rate`
- No behavior change in generation itself

**Dependencies:** Task 2.1 and 2.2 should be done first (get meaningful compliance data from improved schemas)

---

### Task 2.4: Remove Fallback Parsers (Deferred)

**Purpose/Motivation:**  
Once Tasks 2.1-2.3 are deployed and monitored, evaluate whether fallback parsers are still needed. If compliance_rate ≥ 0.95 over 20+ consecutive runs, they can be removed for simplicity.

**Proceed only when:**
- 20+ production runs with `compliance_rate ≥ 0.95` (from `ai_run_log.jsonl`)
- No increase in `error` status fields over the monitoring period
- No regression in output quality (spot-check a sample of AI JSON files)

**When removing:**
1. Remove `parse_briefing_response()`, `parse_watchlist_response()`, `parse_phase_response()`
2. Replace `try/except json.loads` with direct parse; let `_normalize_*` functions handle shape
3. Remove `fallback_parse` key from `TASK_SPECS`
4. Update affected tests (remove fallback test cases)

**Note on error handling post-removal:** A Gemini API misconfiguration that bypasses structured output would now leave a field empty rather than degrading gracefully. This is acceptable — the monitoring from 2.3 would catch it.

**Dependencies:** 2.1–2.3 deployed and stable for 2-4 weeks

---

### Phase 2 Execution Summary

**Order:** 2.1 (independent) → 2.2 (needs 2.1 descriptions) → 2.3 (extends 2.1/2.2 observations) → (monitor) → 2.4  
**Estimated Time:** 6-9 hours (tasks 2.1-2.3), 2-4 weeks monitoring for 2.4  
**New dependencies added:** None  
**Testing:** Unit tests for enriched schemas, few-shot presence in prompts, compliance_rate calculation

---

## Overall Execution Plan

### Week 1 (Phase 1)
- Mon: Task 1.1 (skip logic + force flag) — write tests first
- Tue: Task 1.2 (workflow YAML) — verify in GitHub Actions UI
- Wed-Fri: Monitor 2-3 live runs; confirm skip fires on 14:00 UTC midday run

### Week 2 (Phase 2.1-2.3)
- Phase 2.1: Schema enrichment + `confidence` fix (half day)
- Phase 2.2: Few-shot examples (half day)
- Phase 2.3: Validation logging extension (half day)
- Testing + PR

### Week 4+ (Monitoring → 2.4)
- Read `ai_run_log.jsonl` compliance_rate after each run
- Decide on Task 2.4 when criteria are met

---

## Files Modified

### Phase 1:
- `scripts/generate_ai.py` — add `_has_new_delta_data()`, argparse, skip logic, remove dead incremental code
- `.github/workflows/collect.yml` — add `force_ai` workflow_dispatch input
- `README.md` — document `--force-ai` flag
- `tests/test_generate_ai.py` — add skip logic tests

### Phase 2:
- `scripts/generate_ai.py` — schema descriptions, `additionalProperties`, `_normalize_phase` confidence fix, few-shot in prompts, compliance_rate in artifacts
- `tests/test_generate_ai.py` — schema description tests, compliance_rate tests

### Not modified:
- `scripts/compute_deltas.py` — no status file, no changes needed
- `requirements.txt` — no new dependencies

---

## Verification Strategy

### Unit Tests
- Phase 1: `_has_new_delta_data` with CSV fixtures (tmp_path), skip path in `main()`, force flag bypasses skip, `FORCE_AI` env var
- Phase 2: schema dicts have `description` at every property, `additionalProperties` present, `_normalize_phase` preserves confidence, compliance_rate calculation

### Integration Tests
- Workflow: compute_deltas runs → delta CSV has today's rows → generate_ai runs (no skip)
- Workflow: no new delta rows → generate_ai skips (exit 0, `outcome: skipped`)
- Force flag: `--force-ai` → generates regardless of delta CSV state

### Regression Tests
- Existing 140+ tests must pass unchanged (no test deleted, no behavior change to existing logic)
- Spot-check AI JSON output quality after few-shot examples added

### Production Monitoring (Phase 2)
- `ai_run_log.jsonl`: read `compliance_rate` after each run
- Alert threshold: if `compliance_rate < 0.90`, investigate schema or prompt issue before proceeding to 2.4

---

## Rollback Strategy

**Phase 1:**
- If skip logic has a false-negative bug (skips when it shouldn't): set `FORCE_AI=1` in workflow env vars to disable until patched
- Cost: extra API calls (original behavior)

**Phase 2:**
- If schema descriptions cause unexpected API errors: revert description fields (backward-compatible change)
- If `additionalProperties: false` breaks Gemini API: remove only that constraint
- Fallback parsers remain in place until Task 2.4 — no compliance regression

---

## Success Criteria

### Phase 1 Complete When:
- [ ] `_has_new_delta_data()` exists and is tested
- [ ] `generate_ai.py --force-ai` forces regeneration
- [ ] `FORCE_AI` env var also forces regeneration
- [ ] Midday (14:00 UTC) workflow run shows `outcome: skipped` when no new data
- [ ] Post-close (22:05 UTC) run shows `outcome: complete` when data is fresh
- [ ] `ai_run_summary.json` correctly records `skipped` vs `complete`
- [ ] README documents the flag

### Phase 2 Complete When:
- [ ] All 5 schemas have `description` on every property
- [ ] All 5 schemas have `additionalProperties: false`
- [ ] `_normalize_phase()` passes `confidence` through
- [ ] Few-shot examples present in briefing and watchlist prompts
- [ ] `ai_run_summary.json` includes `compliance_rate`
- [ ] Tests pass
- [ ] 20+ runs show `compliance_rate ≥ 0.95` (precondition for Task 2.4)
- [ ] Decision made on Task 2.4 (proceed or defer further)

---

## Sources

Research on Gemini API structured output:
- [Structured outputs - generateContent API](https://ai.google.dev/gemini-api/docs/structured-output)
- [Prompt design strategies | Gemini API](https://ai.google.dev/gemini-api/docs/prompting-strategies)
- [Structured output | Gemini Enterprise Agent Platform](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/capabilities/control-generated-output)

Key findings retained from original research:
- Gemini structured output guarantees **syntactic** correctness (valid JSON, correct types) but not **semantic** correctness (correct enum values, specific vs. vague content)
- `description` fields in the schema are the primary lever for semantic compliance
- `additionalProperties: false` is supported as of November 2025
- Few-shot examples improve semantic quality; they do not fix syntactic issues that structured output already handles
- Pydantic BaseModel is accepted by `response_schema` natively — but dict schemas are equally accepted and require no new dependency
