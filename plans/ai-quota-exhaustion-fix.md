# AI Quota Exhaustion Fix Plan

**Branch:** `claude/ai-analysis-resource-exhausted-k5yjmo`  
**Status:** PLANNING  
**Last updated:** 2026-06-13  
**Tracking run:** https://github.com/clarencelam2000/finviz-groups-tracker/actions/runs/27460720241/job/8117385076

---

## Problem Statement

`generate_ai.py` is exhausting Gemini's free tier quota (20 requests/day for `gemini-2.5-flash`) every day, causing partial or failed AI analysis output. The 20 RPD limit is real — Google cut it from 250 RPD → 20 RPD in late 2025 — but 20 RPD is sufficient for normal operation (7 calls/day baseline). Two code bugs multiply actual usage by 10–20×.

### Evidence from `data/ai_run_log.jsonl`

- June 12: 4 runs burned 12 calls (`7+3+1+1`) — all for the same day's data.
- June 13 02:00Z scheduled run: `api_calls=7`, `rate_limit_hits=17`, `elapsed=1225s` (20 minutes of mostly sleeping between doomed retries).
- Actual API requests that run sent to Google: `7 first-attempts + 17 retries = 24` — over the 20/day cap.

### Root causes

| # | Bug | Location | Effect |
|---|---|---|---|
| 1 | Incremental loading removed in commit `022d871` | `main()` in `generate_ai.py` | Every run regenerates all 7 fields from scratch, even when a partial file exists |
| 2 | Retry logic retries daily quota exhaustion | `_call_api()` in `generate_ai.py` | When daily quota hits, retrying 3× per field burns 3 more quota units AND wastes 210s per field |
| 3 (minor) | `_generate_daily_delta()` swallows exceptions silently | `_generate_daily_delta()` | `sectors.daily_delta` always shows `{"status": "error"}` with no diagnostic info |

---

## Phased Checklist

### Phase 0 — Commit and push this plan file *(do first, before any code)*
- [ ] Write plan to `plans/ai-quota-exhaustion-fix.md`
- [ ] Commit: `docs: add AI quota exhaustion fix plan`
- [ ] Push to `claude/ai-analysis-resource-exhausted-k5yjmo`

### Phase 1 — Fix incremental loading (Bug 1)
- [ ] Restore the block in `main()` that loads an existing partial file from `output_path`
- [ ] Set `existing_output` from disk; set `was_incremental = True` when partial file found
- [ ] Verify skip logic in `generate_for_group` activates correctly
- [ ] Add/update tests in `tests/test_generate_ai.py`
- [ ] Run `python3 -m pytest tests/ -q` — all pass
- [ ] Commit: `fix: restore incremental loading of partial AI output files`

### Phase 2 — Abort cleanly on daily quota exhaustion (Bug 2)
- [ ] Add `DailyQuotaExhaustedError` exception class
- [ ] In `_call_api()`: detect `GenerateRequestsPerDayPerProjectPerModel` in error string, raise `DailyQuotaExhaustedError` instead of retrying
- [ ] In `generate_for_group()`: catch and re-raise `DailyQuotaExhaustedError` (with field logging)
- [ ] In `_generate_daily_delta()`: let `DailyQuotaExhaustedError` propagate (don't swallow it)
- [ ] In `main()`: wrap generation loop to catch `DailyQuotaExhaustedError`, save partial output, log `"quota_exhausted"` outcome, exit 0
- [ ] Add/update tests
- [ ] Run `python3 -m pytest tests/ -q` — all pass
- [ ] Commit: `fix: abort on daily quota exhaustion instead of retrying`

### Phase 3 — Fix daily_delta error tracking (Bug 3, minor)
- [ ] Change `_generate_daily_delta()` to return `None` on exception (instead of `[]`), capturing the error string
- [ ] In `main()`: distinguish `None` (error) from `[]` (empty result) in the `_record_field` call
- [ ] Update tests
- [ ] Run `python3 -m pytest tests/ -q` — all pass
- [ ] Commit: `fix: propagate daily_delta errors into run log`

### Phase 4 — Update session artifacts
- [ ] Mark this plan's phases complete in this file
- [ ] Update `.session/session-notes.md`
- [ ] Update `.session/WORK_LOG.md`
- [ ] Update `.session/SPRINT.md`
- [ ] Push all changes, open PR

---

## Fix 1: Restore Incremental Loading

### What was removed and why it matters
Commit `022d871` ("force GenerateAI calls and normalize response shapes") deleted this block from `main()`:

```python
if output_path.exists():
    try:
        with open(output_path, encoding="utf-8") as f:
            existing_output = json.load(f)
    except Exception:
        existing_output = {}
    if _is_complete(existing_output):
        print("AI analysis already complete — skipping.")
        _write_run_artifacts("skipped", ...)
        sys.exit(0)
    else:
        missing = _missing_fields(existing_output)
        was_incremental = True
```

Without this, `existing_output = {}` always, so `generate_for_group(existing={})` starts with an empty result dict and the skip-if-present check (`if spec["name"] in result: continue`) never fires. Every run regenerates all 7 fields, regardless of what's already written.

The infrastructure for incremental operation (`was_incremental`, `existing=` param, skip-if-present logic) is all intact — this block just needs to be re-inserted.

### Purpose / what it fixes
- Eliminates wasted re-generation of already-complete fields on incremental runs
- Enables quota-safe retry: a run that was cut short by quota exhaustion writes a partial file; the next day's run picks up only the missing fields
- Makes `was_incremental: true` in the run log accurate again

### Detailed task description
In `main()`, between `existing_output = {}` and `print(f"Generating AI analysis for {today}...")`, insert:

```python
if output_path.exists():
    try:
        with open(output_path, encoding="utf-8") as f:
            candidate = json.load(f)
        if not _is_complete(candidate):
            missing = _missing_fields(candidate)
            print(
                f"Partial file found ({len(missing)} field(s) missing: {', '.join(missing)})"
                f" — resuming incrementally."
            )
            existing_output = candidate
            was_incremental = True
        # Complete file: fall through and regenerate fresh (always produce up-to-date insights)
    except Exception:
        pass  # existing_output stays {}
```

**Important constraint**: Do NOT skip when file is complete. Commit `022d871` deliberately removed skip-on-complete, and `test_main_force_regenerates_complete_file` captures this intent. Incremental loading only applies to *partial* (incomplete) files from a prior run cut short by quota or error.

### Acceptance criteria
- [ ] If `data/ai/YYYY-MM-DD.json` exists and is COMPLETE: script regenerates all fields fresh; `was_incremental: false` in run log
- [ ] If partial file exists with 3/6 fields: script passes those 3 completed fields as `existing` to `generate_for_group`, only generates the 3 missing; run log shows `was_incremental: true` and skipped fields show `"status": "skipped", "was_new": false`
- [ ] If no file exists: behavior unchanged from current (all 7 fields generated)
- [ ] If file exists but is corrupt JSON: falls back to `existing_output = {}`, regenerates all fields

### Alternatives considered

**Alternative A: Keep `existing_output = {}`, rely on skip gate only**  
Add the file-load and skip check but don't call `generate_for_group` with the existing data — just re-run all fields every time but skip if all were already complete.  
*Assessment*: Only helps if the prior run was 100% complete. For partial runs (the common failure case), does nothing — still regenerates all fields.  
*Decision*: Rejected. Doesn't address the incremental partial-run case.

**Alternative B: Add a lock/completion flag file alongside the JSON**  
Write `data/ai/YYYY-MM-DD.complete` when all fields succeed. Check for this file at startup to skip.  
*Assessment*: Adds file system state that is hard to keep in sync. The existing `_is_complete()` function already solves this by inspecting the JSON itself.  
*Decision*: Rejected. Unnecessary complexity; `_is_complete()` is the right tool.

**Chosen approach: Restore the removed block verbatim (with minor message improvements)**  
*Rationale*: The code was working correctly before `022d871`. The reason it was removed (to force normalization) is now moot because `_normalize_briefing()` and `_normalize_phase()` were added in the same commit and handle old-shape data. Restoring the block is low-risk.

### Happy path success cases
- Partial file from previous run exists with 4/6 fields → generates 2 missing fields, updates file, logs `was_incremental: true`
- Complete file exists → immediate skip, 0 API calls consumed
- No file exists → normal full generation path

### Edge cases
- Partial file exists but `existing_output` lacks the top-level `sectors` or `industries` key → `existing_output.get(key, {})` returns `{}`, that group is fully regenerated (safe)
- `generated_at` timestamp: `existing_output.get("generated_at", datetime.now()...)` preserves the original creation time for partial files (already handled correctly by current code)
- File written mid-run by a concurrent workflow instance → both try to write; Git's `git pull --rebase` in the commit step will merge them; last writer wins (acceptable for this use case)

### Error / failure cases
- `output_path` exists but cannot be read (permissions): `except Exception` falls back to full regeneration — safe
- `output_path` contains valid JSON but with unexpected schema: `_is_complete()` and `_missing_fields()` will return that all fields are missing → full regeneration — safe

### Dependencies
- No new dependencies
- `_is_complete()`, `_missing_fields()`, `generate_for_group()` must remain unchanged in behavior

### Follow-up tasks (backlog)
- AI-3 (already in sprint backlog): "Restore per-field resumability" — this fix addresses AI-3 fully; it can be marked done after this lands

---

## Fix 2: Abort Cleanly on Daily Quota Exhaustion

### Purpose / what it fixes
When Google's daily quota is exhausted, the current retry loop (30s/60s/120s backoff, 3 retries) is useless. The quota cannot reset mid-run. Each retry attempt:
1. Wastes the backoff sleep time (~210s per failing field)
2. Burns another quota unit (making subsequent fields more likely to fail)
3. Contributes to run times exceeding 20 minutes

The fix distinguishes *daily quota exhausted* (unrecoverable today) from *per-minute rate limited* (transient, retrying makes sense).

The distinguishing signal is in the quota error's `quotaId` field: `GenerateRequestsPerDayPerProjectPerModel-FreeTier`.

### Detailed task description

**Step 1**: Add exception class after imports (near line 15):
```python
class DailyQuotaExhaustedError(Exception):
    """Gemini daily free-tier RPD quota is fully consumed. Cannot retry until reset."""
```

**Step 2**: In `_call_api()`, inside the `except Exception as e:` block, add before the `is_retryable` check:
```python
err_str = str(e)
if "GenerateRequestsPerDayPerProjectPerModel" in err_str:
    raise DailyQuotaExhaustedError(err_str) from e
```

**Step 3**: In `generate_for_group()`, in the per-field `except Exception as e:` block:
```python
except DailyQuotaExhaustedError:
    _record_field(fkey, "quota_exhausted", was_new=True, elapsed=time.monotonic() - t0)
    raise  # propagate to main()
except Exception as e:
    ...  # existing handler unchanged
```

**Step 4**: In `_generate_daily_delta()`:
```python
except DailyQuotaExhaustedError:
    raise  # don't swallow — let main() handle it
except Exception as e:
    print(f"  [daily_delta] API call failed: {e}")
    return []
```

**Step 5**: In `main()`, wrap the generation loop:
```python
try:
    for group_type in ("sector", "industry"):
        key = "sectors" if group_type == "sector" else "industries"
        output[key] = generate_for_group(
            client, group_type, today, existing=existing_output.get(key, {})
        )
    # ... daily_delta block ...
except DailyQuotaExhaustedError as e:
    print(
        f"Daily free-tier quota exhausted — saving partial output and aborting.\n"
        f"Next scheduled run will resume from this partial file.\n{e}"
    )
    has_partial = any(output.get(k) for k in ("sectors", "industries"))
    if has_partial:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        print(f"Partial output saved to {output_path}")
    _write_run_artifacts("quota_exhausted", was_incremental, time.monotonic() - run_start, today)
    sys.exit(0)
```

### Acceptance criteria
- [ ] When `DailyQuotaExhaustedError` is raised in `_call_api()`, no retries occur (exits the retry loop immediately)
- [ ] `rate_limit_hits` is NOT incremented for daily quota errors (only incremented for per-minute transient errors)
- [ ] Run log shows `"outcome": "quota_exhausted"` for a run that hit daily quota
- [ ] Fields completed before the quota hit are saved to `output_path` (partial output preserved)
- [ ] Workflow exits 0 (not a workflow failure; the commit step still runs and pushes the partial file)
- [ ] Per-minute rate limit errors (429 with a different `quotaId`) still retry normally

### Alternatives considered

**Alternative A: Check quota error in `is_retryable`, set `max_retries = 0` for daily quota**  
Instead of a new exception class, set the attempt to `max_retries` directly when daily quota is detected, forcing the outer `raise`.  
*Assessment*: This surfaces the error as a generic `Exception` from `_call_api()`. `generate_for_group()` catches it and moves to the next field, then the next field also hits quota and also fails, and so on. The run completes slowly (fields serially fail) rather than aborting immediately. Doesn't save partial output cleanly.  
*Decision*: Rejected. Too slow; doesn't abort the run.

**Alternative B: Module-level flag `_daily_quota_hit: bool`**  
Set a global flag in `_call_api()` when daily quota is detected. Check it at the top of the loop in `main()` to break early.  
*Assessment*: Achieves the same result as the exception approach but with less clean propagation. The flag could be missed if new callers are added. Exception propagation is the Pythonic pattern for exceptional conditions.  
*Decision*: Rejected. Exception is cleaner and harder to accidentally bypass.

**Alternative C: Upgrade to Gemini paid tier**  
Avoid the quota issue by using a billing-enabled API key.  
*Assessment*: Solves the quota problem permanently but costs money. Also doesn't fix the underlying waste (multiple runs generating duplicate work). Appropriate to revisit once the codebase is clean.  
*Decision*: Out of scope for this fix; noted as follow-up.

**Chosen approach: `DailyQuotaExhaustedError` exception class**  
*Rationale*: Clean propagation through the call stack, immediately aborts the run on first daily quota hit, preserves partial output, logs correct `outcome` in run log. Easy to test by mocking `_call_api`.

### Happy path success cases
- Script runs, hits daily quota on field 3/7, saves fields 1-2 as partial output, logs `quota_exhausted`, exits 0, workflow pushes the partial file
- Next day's scheduled run loads the partial file (Fix 1), generates only fields 3-7

### Edge cases
- Daily quota hit on the very first field (nothing to save): `has_partial` check is `False`, no partial file written — correct, run log shows `quota_exhausted` with `api_calls=1`
- Daily quota hit inside `_generate_daily_delta()`: propagates through the `DailyQuotaExhaustedError` re-raise and is caught in `main()`; whatever was generated before `daily_delta` is still saved
- Both per-minute AND per-day quota are exhausted simultaneously: per-day check fires first (added before `is_retryable`), so `DailyQuotaExhaustedError` is raised — correct, since per-day is the binding constraint
- Error string format changes (Google changes API error format): detection key `"GenerateRequestsPerDayPerProjectPerModel"` is a stable, specific quota metric name embedded in the quota violation struct, not a human-readable message. Less likely to change than the human message.

### Error / failure cases
- `DailyQuotaExhaustedError` raised before `output` dict is initialized in `main()`: The try-block wraps only the generation loop (after `output` is initialized); no risk of `NameError`
- `json.dump` fails when writing partial output: wrapped in `try/except` (same pattern as existing `_write_run_artifacts`)

### Dependencies
- Must be implemented after Fix 1 (or simultaneously), because the value of aborting early depends on the next run being able to resume incrementally
- No external dependencies

### Follow-up tasks (backlog)
- Consider upgrading to Gemini paid tier if 20 RPD proves insufficient even after these fixes
- Monitor `data/ai_run_log.jsonl` for `quota_exhausted` entries after deploy; if they persist, audit manual dispatches in GitHub Actions history

---

## Fix 3: Daily Delta Error Propagation

### Purpose / what it fixes
`_generate_daily_delta()` catches all exceptions and returns `[]`. This conflates two distinct cases:
1. API call failed (exception) → should log an error with the exception message
2. API returned valid response with empty changes list → should log as success (or at least "ok-empty")

Every run log since `sectors.daily_delta` was introduced shows `{"status": "error", "was_new": true}` with no `error` field — making it impossible to distinguish between "model returned no changes" and "API threw 503/429". Additionally, `DailyQuotaExhaustedError` must not be swallowed here (already handled in Fix 2).

### Detailed task description

**Step 1**: Change `_generate_daily_delta()` signature and return:
```python
def _generate_daily_delta(client, prior_briefing: str, date_str: str) -> "tuple[list, str]":
    """Returns (changes_list, error_message). error_message is '' on success."""
    snap_df = load_latest_snapshot("sector")
    delta_df = load_latest_delta("sector")
    prompt = build_daily_delta_prompt(prior_briefing, snap_df, delta_df, date_str)
    try:
        raw = _call_api(client, prompt,
                        generation_config={"temperature": 0.4, "max_output_tokens": 300},
                        response_schema=DAILY_DELTA_SCHEMA)
        parsed = json.loads(raw)
        changes = parsed.get("changes", []) if isinstance(parsed, dict) else []
        return changes, ""
    except DailyQuotaExhaustedError:
        raise  # propagate to main()
    except Exception as e:
        msg = str(e)
        print(f"  [daily_delta] API call failed: {msg}")
        return [], msg
```

**Step 2**: Update the caller in `main()`:
```python
changes, err_msg = _generate_daily_delta(client, prior_briefing, today)
t_elapsed = time.monotonic() - t0
if changes:
    output["sectors"]["daily_delta"] = changes
    _record_field("sectors.daily_delta", "ok", was_new=True, elapsed=t_elapsed)
elif err_msg:
    _record_field("sectors.daily_delta", "error", was_new=True,
                  elapsed=t_elapsed, error=err_msg)
else:
    # Model returned empty list — valid response, no notable changes
    _record_field("sectors.daily_delta", "ok_empty", was_new=True, elapsed=t_elapsed)
```

### Acceptance criteria
- [ ] When `_call_api()` raises an exception inside `_generate_daily_delta`, the error message appears in `data/ai_run_log.jsonl` under `fields["sectors.daily_delta"]["error"]`
- [ ] When `DailyQuotaExhaustedError` occurs in `_generate_daily_delta`, it propagates to `main()` (not silently consumed)
- [ ] When the model legitimately returns no changes (`[]`), the status is `ok_empty` not `error`

### Alternatives considered

**Alternative A: Leave `_generate_daily_delta` returning `[]`, add a separate error tracking dict**  
*Assessment*: More complex. The tuple return is the simplest way to surface the error message.  
*Decision*: Rejected.

**Alternative B: Raise the exception from `_generate_daily_delta` and handle it in `main()`**  
*Assessment*: Requires more changes to `main()` to distinguish this from `DailyQuotaExhaustedError`. The tuple approach is cleaner.  
*Decision*: Rejected.

### Dependencies
- Must be done after or alongside Fix 2 (depends on `DailyQuotaExhaustedError` existing)

### Follow-up tasks
- Monitor whether `ok_empty` ever appears in practice (model returning no daily changes); if it appears frequently, consider removing the `daily_delta` task when < 2 days of history exist

---

## Files Expected to Change

| File | Changes |
|---|---|
| `scripts/generate_ai.py` | Fixes 1, 2, 3 (incremental loading, quota abort, delta error) |
| `tests/test_generate_ai.py` | New/updated tests for all three fixes |
| `plans/ai-quota-exhaustion-fix.md` | This file (phase checkboxes updated as work completes) |
| `.session/session-notes.md` | Updated at end of session |
| `.session/WORK_LOG.md` | Milestone entry when fixes land |
| `.session/SPRINT.md` | AI-3 marked done; follow-up tasks added |

---

## Tests Required

### For Fix 1 (incremental loading)
- `test_main_skips_when_complete`: mock `output_path.exists() = True` with a complete JSON blob → assert `sys.exit(0)` called, 0 API calls, `_write_run_artifacts` called with `"skipped"`
- `test_main_resumes_partial`: mock partial JSON (missing one field) → assert only missing fields passed to `generate_for_group`, `was_incremental=True` in run log
- `test_main_regenerates_on_corrupt_file`: mock `output_path.exists() = True` with invalid JSON → assert falls back to full generation

### For Fix 2 (daily quota abort)
- `test_call_api_raises_on_daily_quota`: mock Gemini client to return `429` with `"GenerateRequestsPerDayPerProjectPerModel"` → assert `DailyQuotaExhaustedError` raised, `_rate_limit_hits` not incremented
- `test_call_api_retries_on_per_minute_quota`: mock Gemini client to return `429` with a different quota ID → assert retries occur normally
- `test_main_saves_partial_on_quota_exhaustion`: mock first field succeeds, second raises `DailyQuotaExhaustedError` → assert partial file written, `outcome = "quota_exhausted"` logged, `sys.exit(0)` called

### For Fix 3 (delta error propagation)
- `test_generate_daily_delta_returns_error_message`: mock `_call_api` to raise `Exception("503 error")` → assert return is `([], "503 error")`
- `test_generate_daily_delta_propagates_daily_quota`: mock `_call_api` to raise `DailyQuotaExhaustedError` → assert it propagates (not caught)
- `test_generate_daily_delta_ok_empty`: mock `_call_api` to return `{"changes": []}` → assert return is `([], "")` and main logs `ok_empty`

---

## Verification (Mandatory Observable Mechanisms)

### Unit tests (must pass before each commit)
```bash
python3 -m pytest tests/test_generate_ai.py -v
python3 -m pytest tests/ -q  # full suite
```

### Manual integration test (no API key needed)
1. Create a partial AI file to simulate a prior partial run:
   ```bash
   mkdir -p data/ai
   echo '{"date":"2026-06-13","sectors":{"briefing":"test"},"industries":{}}' > data/ai/2026-06-13.json
   ```
2. Run without API key:
   ```bash
   python scripts/generate_ai.py
   ```
3. Expected output: `"Partial file found (5 field(s) missing: ...)"`, then exits with `no_key` (not `skipped`)
4. Run again after removing the partial file:
   ```bash
   rm data/ai/2026-06-13.json && python scripts/generate_ai.py
   ```
5. Expected output: `"Generating AI analysis for ..."`, then exits with `no_key`

### Run log verification (after next GitHub Actions run)
Check `data/ai_run_log.jsonl` for:
- No more `rate_limit_hits > 3` on any single run
- If `outcome = "quota_exhausted"`: the *next* run should show `was_incremental: true` and `outcome = "complete"` or `"partial"` with fewer API calls

### Quota usage reduction (observable over 3 days)
Normal operation should use ≤7 API calls/day. With incremental loading active, a partial run uses even fewer. Track in `data/ai_run_log.jsonl`:
```bash
# Sum api_calls across all runs for a given date
python3 -c "
import json
from collections import defaultdict
calls = defaultdict(int)
for line in open('data/ai_run_log.jsonl'):
    r = json.loads(line)
    calls[r['date']] += r['api_calls']
for d, c in sorted(calls.items()):
    print(f'{d}: {c} calls')
"
```
Goal: max 7–10 calls per day per data date (not 24+).

---

## Rollback Strategy

If any fix causes regressions:
1. **Fix 1 rollback**: Set `existing_output = {}` and remove the file-load block. Side effect: back to burning all 7 calls per run. Acceptable temporarily.
2. **Fix 2 rollback**: Remove `DailyQuotaExhaustedError` and the early-exit check. Side effect: back to retrying daily quota errors. Acceptable temporarily (just slow and wasteful).
3. All fixes are isolated to `generate_ai.py`. Rollback is a single-file revert.
4. **Data safety**: No data is deleted. The `data/ai/` JSON files are append/overwrite only. Worst case is a partial or missing AI analysis file for one day.

---

## Sprint / Backlog Updates

### To close after this lands
- AI-3: "Restore per-field resumability" — Fix 1 fully addresses this

### New items to add to backlog
- **QUOTA-1**: Monitor daily API call counts in `ai_run_log.jsonl` for 2 weeks post-fix; if consistently hitting quota even with these fixes, evaluate paid tier upgrade
- **QUOTA-2**: Add a `workflow_dispatch` guard: if the `generate_ai.yml` workflow was already run successfully today (check `data/ai_run_summary.json`), make manual dispatches no-op by default (requires `--force-ai` to override)
- **QUOTA-3**: (Optional) Reduce number of scheduled collect.yml triggers that cascade into generate_ai.yml; `collect.yml` currently runs at 14:45 and 22:11 UTC weekdays — each success triggers `generate_ai.yml`. One successful trigger per day should be sufficient for normal operation.
