# Plan: AI Server-Side Architecture Revamp

## Phase Status

| Phase | Status | Commit |
|-------|--------|--------|
| 0 | ✅ Done | `docs: add AI architecture revamp plan` |
| 1 | ✅ Done | `feat: add JSON schema mode for phase and watchlist` |
| 2 | ✅ Done | `refactor: replace hardcoded AI pipeline with TASK_SPECS` |
| 3 | ✅ Done | `feat: add data/ai/index.json master manifest` |
| 4 | ✅ Done | `feat: load AI data via index.json in dashboard and PWA` |
| 5 | ⬜ Pending | Model upgrade |
| 6 | ⬜ Pending | Update plan + session notes |

> **Resuming after a context reset**: read this table first to know where to start.
> Then run `python3 -m pytest tests/ -q` to confirm green baseline.

---

## Context

The nightly AI pipeline (`scripts/generate_ai.py`) works but has three structural problems that will compound as new features (AI-1 anomaly detection, AI-2 Q&A) are added:

1. **No master index** — dashboard/PWA must guess today's date to find the latest JSON; no coverage overview without a directory scan.
2. **Fragile text parsing** — `parse_phase_response()` and `parse_watchlist_response()` use brittle line-splitting that breaks if Gemini reformats output. Structured JSON output eliminates this.
3. **Hardcoded if/else pipeline** — `generate_for_group()` has nested `if group_type == "sector"` guards. Every new AI task adds another branch.

Secondary: `GEMINI_MODEL = "gemini-flash-latest"` is an unversioned alias.

---

## Phased Execution Overview

| Phase | Change | Files | Commit |
|-------|--------|-------|--------|
| 0 | Write PLAN.md to repo | `plans/ai-architecture-revamp.md` | `docs: add AI architecture revamp plan` |
| 1 | JSON schemas + `_call_api` update | `scripts/generate_ai.py`, `tests/test_generate_ai.py` | `feat: add JSON schema mode for phase and watchlist` |
| 2 | Declarative `TASK_SPECS` pipeline | `scripts/generate_ai.py`, `tests/test_generate_ai.py` | `refactor: replace hardcoded AI pipeline with TASK_SPECS` |
| 3 | `index.json` master manifest | `scripts/generate_ai.py`, `tests/test_generate_ai.py` | `feat: add data/ai/index.json master manifest` |
| 4 | Dashboard + PWA consume index | `dashboard/app.py`, `docs/index.html` | `feat: load AI data via index.json in dashboard and PWA` |
| 5 | Model upgrade | `scripts/generate_ai.py` | `chore: pin Gemini model to gemini-2.5-flash` |
| 6 | Update plan + session notes | `plans/ai-architecture-revamp.md`, `.session/` | `docs: mark AI architecture revamp complete` |

Each phase is committed separately. If a phase's tests fail, the commit is not made — fix first.

---

## Change 1: JSON Schema Mode for Structured Outputs

### Purpose / Motivation / What it fixes

`parse_phase_response()` parses text like:
```
PHASE: Late Cycle
REASONING: Energy leads.
```
If Gemini adds a preamble or reformats the response, the parser silently returns `label: "Unknown"`. `parse_watchlist_response()` has the same fragility — a model preamble or extra blank line can produce fewer than 3 picks.

Gemini's `response_mime_type="application/json"` mode with a schema guarantees syntactically valid JSON. The parser goes from "brittle text splitting" to `json.loads()`.

### Detailed Task Description

Define schemas as module-level dicts near top of `generate_ai.py` (after imports, before functions):

```python
PHASE_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {
            "type": "string",
            "enum": ["Early Cycle", "Mid Cycle", "Late Cycle", "Defensive"],
        },
        "reasoning": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["label", "reasoning", "confidence"],
}

WATCHLIST_SCHEMA = {
    "type": "object",
    "properties": {
        "picks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "thesis": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["name", "thesis"],
            },
            "minItems": 3,
            "maxItems": 3,
        }
    },
    "required": ["picks"],
}
```

Update `_call_api()` to accept `generation_config` and `response_schema` kwargs:

```python
from google.genai import types

def _call_api(client, prompt: str, max_retries: int = 3,
              generation_config: dict = None, response_schema: dict = None) -> str:
    ...
    extra = {}
    if generation_config or response_schema:
        extra["config"] = types.GenerateContentConfig(
            temperature=(generation_config or {}).get("temperature", 0.7),
            max_output_tokens=(generation_config or {}).get("max_output_tokens", 500),
            response_mime_type="application/json" if response_schema else None,
            response_schema=response_schema,
        )
    response = client.models.generate_content(
        model=GEMINI_MODEL, contents=prompt, **extra
    )
    return response.text.strip()
```

Keep existing text parsers (`parse_phase_response`, `parse_watchlist_response`) as fallback — they are dead paths in practice but guard against unexpected API changes.

The `confidence` field is new in the output JSON. The dashboard reads `label` and `reasoning` from phase, and `name`/`thesis` from picks — `confidence` is additive and ignored by existing dashboard code. No dashboard changes needed.

### Acceptance Criteria

- [ ] `_call_api()` accepts `generation_config` and `response_schema` kwargs
- [ ] When `response_schema` is passed, `GenerateContentConfig` is constructed with `response_mime_type="application/json"`
- [ ] Calling `_call_api()` without schema kwargs behaves identically to today (backward compat)
- [ ] `PHASE_SCHEMA` and `WATCHLIST_SCHEMA` are defined at module level and importable
- [ ] Existing text parsers are still present (not deleted)

### Verification Commands

```bash
# Unit tests — must all pass with no new failures
python3 -m pytest tests/test_generate_ai.py -v -k "phase or watchlist or call_api"

# New tests to write:
# test_call_api_passes_schema_to_config — mock client.models.generate_content,
#   assert GenerateContentConfig was constructed with response_mime_type="application/json"
# test_call_api_no_schema_no_config — assert no config kwarg passed when schema=None
# test_phase_schema_has_required_fields — assert PHASE_SCHEMA["required"] == ["label","reasoning","confidence"]
# test_watchlist_schema_has_picks_array — assert WATCHLIST_SCHEMA shape

# Full suite
python3 -m pytest tests/ -q
```

### Happy Path

1. `_call_api(client, prompt, response_schema=PHASE_SCHEMA)` called.
2. API returns `{"label": "Late Cycle", "reasoning": "Energy leads.", "confidence": 0.85}`.
3. Caller does `json.loads(raw)` → clean dict. No regex needed.

### Edge Cases

- **API returns valid JSON but missing optional field** (`confidence` absent): `json.loads()` still works; dashboard gracefully handles missing keys with `.get()`.
- **API returns plain text despite JSON mode**: `json.loads()` raises `JSONDecodeError`; caller catches it and falls back to text parser.
- **`response_schema` kwarg not passed**: `_call_api` behaves exactly as today — no `config` kwarg sent to `generate_content`.

### Error / Failure Cases

- **`GenerateContentConfig` construction fails** (e.g., SDK version doesn't support it): raises at call time; caught by outer try/except in `generate_for_group()`; field recorded as `error`; pipeline continues.
- **Schema rejected by API** (malformed dict): same — caught, recorded as `error`.

### Rollback

This change is isolated to `_call_api()` and the two schema dicts. Rollback = revert to the previous `_call_api()` signature (remove the two kwargs and the `extra` block). The schema dicts can stay — they're inert if not referenced.

### Follow-up Backlog Tasks

- **PIPE-2**: Add `confidence` rendering to dashboard (small badge next to rotation phase label). Effort: S.
- **PIPE-3**: Log `confidence` value in `ai_run_log.jsonl` per run for quality tracking. Effort: S.

---

## Change 2: Declarative `TASK_SPECS` Pipeline

### Purpose / Motivation / What it fixes

`generate_for_group()` currently hardcodes every AI task as nested if/else. Adding AI-1 (anomaly detection) means inserting another `if group_type == "sector"` block. The function grows unboundedly and understanding "what tasks exist and for which groups" requires reading the full body.

A declarative `TASK_SPECS` list separates **what to generate** (config) from **how to run it** (loop logic). Adding a new AI task becomes one dict entry. The loop logic never changes.

### Detailed Task Description

Define `TASK_SPECS` at module level in `generate_ai.py`, after all prompt builder functions are defined (they must exist before being referenced):

```python
TASK_SPECS = [
    {
        "name": "briefing",
        "group_types": ("sector", "industry"),
        "build_prompt": build_briefing_prompt,
        "use_json_schema": False,
        "generation_config": {"temperature": 0.7, "max_output_tokens": 500},
    },
    {
        "name": "rotation_phase",
        "group_types": ("sector",),
        "build_prompt": build_phase_prompt,
        "use_json_schema": True,
        "response_schema": PHASE_SCHEMA,
        "generation_config": {"temperature": 0.2, "max_output_tokens": 300},
    },
    {
        "name": "watchlist",
        "group_types": ("sector",),
        "build_prompt": build_watchlist_prompt,
        "use_json_schema": True,
        "response_schema": WATCHLIST_SCHEMA,
        "generation_config": {"temperature": 0.5, "max_output_tokens": 400},
    },
]
```

**Signature normalization**: `build_briefing_prompt` currently takes `(group_type, snap_df, delta_df, date_str)` while the others take `(snap_df, delta_df, date_str)`. Use a `functools.partial` in the TASK_SPECS dict to normalize — this avoids special-casing in the loop:

```python
{"build_prompt": functools.partial(build_briefing_prompt, group_type="sector"), ...}
```

Or alternatively, update the loop to pass `group_type` explicitly for specs that need it via a `"pass_group_type": True` flag. Pick whichever avoids the most churn — document in the commit body.

**Refactored `generate_for_group()`**:

```python
def generate_for_group(client, group_type, date_str, existing=None):
    result = dict(existing or {})
    key_prefix = "sectors" if group_type == "sector" else "industries"
    snap_df = load_latest_snapshot(group_type)
    delta_df = load_latest_delta(group_type)

    applicable = [s for s in TASK_SPECS if group_type in s["group_types"]]

    if snap_df.empty:
        for spec in applicable:
            fkey = f"{key_prefix}.{spec['name']}"
            if fkey not in _field_log:
                status = "skipped" if spec["name"] in result else "no_data"
                _record_field(fkey, status, was_new=False)
        return result

    for spec in applicable:
        fkey = f"{key_prefix}.{spec['name']}"
        if spec["name"] in result:
            _record_field(fkey, "skipped", was_new=False)
            continue
        print(f"  [{group_type}] Generating {spec['name']}...")
        t0 = time.monotonic()
        try:
            prompt = _build_prompt(spec, group_type, snap_df, delta_df, date_str)
            raw = _call_api(client, prompt,
                            generation_config=spec.get("generation_config"),
                            response_schema=spec.get("response_schema"))
            if spec["use_json_schema"]:
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    parsed = spec.get("fallback_parse", lambda t: t)(raw)
                if spec["name"] == "watchlist":
                    result["watchlist"] = parsed.get("picks", [])
                else:
                    result[spec["name"]] = parsed
            else:
                result[spec["name"]] = raw
            _record_field(fkey, "ok", was_new=True, elapsed=time.monotonic() - t0)
        except Exception as e:
            print(f"  [{group_type}] {spec['name']} failed: {e}")
            _record_field(fkey, "error", was_new=True, elapsed=time.monotonic() - t0, error=str(e))

    return result
```

**Update `_is_complete()` and `_missing_fields()`** to derive expected fields from `TASK_SPECS`:

```python
def _expected_fields() -> list:
    seen = {}
    for spec in TASK_SPECS:
        for gtype in spec["group_types"]:
            prefix = "sectors" if gtype == "sector" else "industries"
            key = f"{prefix}.{spec['name']}"
            seen[key] = True
    return list(seen)

def _is_complete(data: dict) -> bool:
    for field in _expected_fields():
        prefix, name = field.split(".", 1)
        val = data.get(prefix, {}).get(name)
        if not val:
            return False
    return True

def _missing_fields(data: dict) -> list:
    missing = []
    for field in _expected_fields():
        prefix, name = field.split(".", 1)
        val = data.get(prefix, {}).get(name)
        if not val:
            missing.append(field)
    return missing
```

### Acceptance Criteria

- [ ] `generate_for_group()` contains no hardcoded field names or `if group_type == "sector"` guards
- [ ] All 4 existing fields (briefing×2, rotation_phase, watchlist) are generated identically to before
- [ ] `_is_complete()` returns `True` for an output with all 4 fields and `False` with any missing
- [ ] `_missing_fields()` returns correct dotted field names for incomplete outputs
- [ ] Partial-completion re-run logic still works (skips existing fields, regenerates missing ones)
- [ ] `TASK_SPECS` is the single source of truth — `_expected_fields()` derives from it

### Verification Commands

```bash
# Full test suite — no regressions
python3 -m pytest tests/ -q

# New tests to write:
# test_task_specs_covers_all_expected_fields — assert set(_expected_fields()) == known set
# test_generate_for_group_skips_existing — pass existing dict with all fields, assert no API calls made
# test_generate_for_group_empty_snapshot — assert all fields get "no_data" or "skipped" status
# test_is_complete_true_when_all_fields_present
# test_is_complete_false_when_field_missing
# test_missing_fields_returns_correct_keys

# Smoke test (no API key needed — exercises data loading + no-op path):
GEMINI_API_KEY="" python3 scripts/generate_ai.py
# Expected: "GEMINI_API_KEY not set — skipping AI generation." then exits 0
```

### Happy Path

1. Pipeline runs for `group_type="sector"`. Loop finds 3 applicable specs. Each is generated, parsed, recorded.
2. Pipeline runs for `group_type="industry"`. Loop finds 1 applicable spec. One API call.

### Edge Cases

- **Partial existing file**: loop skips specs whose `name` is already in `result`; generates only missing ones.
- **New spec added to `TASK_SPECS`**: existing complete files will now have `_is_complete()` return False → triggers regeneration of the new field only. Correct behavior.
- **`build_prompt` raises**: caught by per-spec try/except, field recorded as `error`, loop continues.

### Dependencies

- Phase 1 (schemas + `_call_api` update) must be committed before this phase — `TASK_SPECS` references `PHASE_SCHEMA` and `WATCHLIST_SCHEMA`.

### Error / Failure Cases

- **All specs fail for a group**: `result` is empty or unchanged. `_is_complete()` returns False. File written with whatever partial content exists (preserves prior partial content). Same behavior as today.

### Rollback

Revert `generate_for_group()` to the previous if/else version. `TASK_SPECS` can stay — it's inert if the function doesn't use it. `_is_complete()`/`_missing_fields()` revert to hardcoded field lists.

### Follow-up Backlog Tasks

- **AI-1** (already in SPRINT.md): Implementation is now just adding one spec dict + `build_anomaly_prompt()` + `ANOMALY_SCHEMA`. No `generate_for_group()` changes.
- **PIPE-1**: Add `"system_instruction"` key to each spec for better prompt control. Effort: S.

---

## Change 3: `data/ai/index.json` Master Manifest

### Purpose / Motivation / What it fixes

The dashboard finds the latest AI JSON like this:
```python
candidate = ai_dir / f"{latest_date}.json"
if candidate.exists():
    ai_file = candidate
else:
    existing = sorted(ai_dir.glob("*.json"))
    ai_file = existing[-1] if existing else None
```

Problems:
- Assumes AI file date matches snapshot date — not guaranteed if pipeline ran late or partial.
- The PWA (static site) cannot do directory scans — it tries today's date and silently shows nothing if the file isn't there.
- No way to see historical AI coverage at a glance.

`data/ai/index.json` decouples "which entry is latest and complete" from "what date is today." It also enables future features like a 7-day rotation phase history strip without loading 7 full files.

### Detailed Task Description

**New function `_update_index(date_str, status, output)`** in `generate_ai.py`:

```python
def _update_index(date_str: str, status: str, output: dict) -> None:
    index_path = AI_DIR / "index.json"
    try:
        existing = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    except (json.JSONDecodeError, OSError):
        existing = {}

    entries = existing.get("entries", [])
    new_entry = {
        "date": date_str,
        "status": status,
        "model": GEMINI_MODEL,
        "generated_at": output.get("generated_at", ""),
        "rotation_phase": (
            output.get("sectors", {}).get("rotation_phase", {}).get("label", "")
            if isinstance(output.get("sectors", {}).get("rotation_phase"), dict)
            else ""
        ),
    }

    # Upsert: replace existing entry for this date, or prepend
    entries = [e for e in entries if e.get("date") != date_str]
    entries.insert(0, new_entry)
    entries.sort(key=lambda e: e.get("date", ""), reverse=True)
    entries = entries[:90]  # trim to last 90 trading days

    index = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "entries": entries,
    }
    try:
        tmp = index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(index_path)  # atomic on POSIX
    except Exception as e:
        print(f"  [index] Failed to write index.json: {e}")
```

Called in `main()` immediately after `_write_run_artifacts()`, passing `output` (the full dict written to the date file) and `outcome` as `status`.

**Dashboard changes (`dashboard/app.py`, AI Insights tab ~lines 623–634)**:

```python
index_path = ai_dir / "index.json"
ai_file = None
if index_path.exists():
    try:
        idx = json.loads(index_path.read_text(encoding="utf-8"))
        for entry in idx.get("entries", []):
            if entry.get("status") == "complete":
                candidate = ai_dir / f"{entry['date']}.json"
                if candidate.exists():
                    ai_file = candidate
                    break
    except (json.JSONDecodeError, OSError):
        pass  # fall through to glob fallback

if ai_file is None:
    # Existing glob fallback — unchanged
    existing = [p for p in sorted(ai_dir.glob("*.json")) if p.stem != "index"]
    if existing:
        ai_file = existing[-1]
```

**PWA changes (`docs/index.html`, AI tab)**:
- Replace the current "try today's date" fetch with: fetch `index.json` → find first `status == "complete"` entry → fetch that date's full file.
- If `index.json` fetch fails (404 on old repo), fall through to the existing today-date attempt.

### Acceptance Criteria

- [ ] `data/ai/index.json` is written after every successful `generate_ai.py` run
- [ ] Re-running on the same date upserts (updates existing entry, no duplicates)
- [ ] Index is sorted newest-first
- [ ] Index has ≤ 90 entries after many runs
- [ ] A corrupt/missing `index.json` does not crash the pipeline or dashboard
- [ ] Dashboard AI Insights tab finds the correct file via `index.json`
- [ ] PWA AI tab shows content without guessing today's date

### Verification Commands

```bash
# Unit tests
python3 -m pytest tests/test_generate_ai.py -v -k "index"

# New tests to write:
# test_update_index_creates_file_if_missing
# test_update_index_upserts_same_date
# test_update_index_trims_to_90
# test_update_index_corrupt_file_fallback
# test_update_index_newest_first
# test_update_index_rotation_phase_extracted

# Manual smoke test:
python3 -c "
import json; from pathlib import Path
idx = json.loads(Path('data/ai/index.json').read_text())
assert 'entries' in idx
assert 'updated_at' in idx
assert idx['entries'] == sorted(idx['entries'], key=lambda e: e['date'], reverse=True)
assert len(idx['entries']) <= 90
print('index.json OK:', len(idx['entries']), 'entries')
"

# Full suite
python3 -m pytest tests/ -q
```

### Happy Path

1. Nightly run completes → writes `2026-06-11.json` → `_update_index("2026-06-11", "complete", output)` prepends entry to `index.json` → dashboard loads index, finds first `status=="complete"` entry, loads full file → renders correctly.

### Edge Cases

- **First ever run** (no `index.json`): function creates it with a single entry.
- **Partial run** (some fields missing): entry gets `status: "partial"`. Next run upserts same date with `status: "complete"`.
- **Run skipped** (file already complete): dashboard lookup skips it (not `"complete"`) and finds the previous day's complete entry.
- **Gap in data** (missed trading day): index naturally skips that date. Dashboard finds the most recent complete entry.
- **`index.json` exists but date file is missing** (manual deletion): dashboard skips that entry and tries the next; eventually falls back to glob.
- **90-entry trim**: oldest entries drop off. The `YYYY-MM-DD.json` files themselves are never deleted.

### Dependencies

- Phase 0 (PLAN.md committed) and Phase 1+2 should be done first, but this phase is independently implementable.

### Error / Failure Cases

- **Write fails** (disk full, permissions): caught, warning printed, pipeline exits 0. The date JSON is already written — only the index is missing.
- **`tmp.replace()` not atomic on some filesystems** (rare): dashboard gets a partial read → `JSONDecodeError` → falls back to glob. Next successful run fixes the index.

### Rollback

Remove the `_update_index()` call from `main()`. Delete `data/ai/index.json`. Dashboard and PWA fall back to existing glob/today-date logic automatically (the fallback code is kept in place).

---

## Change 4: Model Upgrade

Update `GEMINI_MODEL = "gemini-2.5-flash"` (from `"gemini-flash-latest"` alias).

Pinning to a specific version prevents silent behavior changes if the alias is updated. Gemini 2.5 Flash supports structured output and is stable in production. No `requirements.txt` change needed (`google-genai>=2.8.0` already covers it).

**Verification**: Update the test that asserts the model constant, run `python3 -m pytest tests/ -q`. Done in a single-line commit.

---

## Files Modified (All Phases)

| File | Changes |
|------|---------|
| `plans/ai-architecture-revamp.md` | New — this plan file, committed to repo |
| `scripts/generate_ai.py` | Schemas, `TASK_SPECS`, `generate_for_group()` refactor, `_is_complete()`/`_missing_fields()`, `_update_index()`, `_call_api()` params, model string |
| `dashboard/app.py` | AI Insights tab: `index.json`-first file discovery, fallback to glob |
| `docs/index.html` | PWA AI tab: fetch `index.json` first, then latest complete date file |
| `tests/test_generate_ai.py` | New tests for schemas, `TASK_SPECS`, `_update_index()`, `_is_complete()`/`_missing_fields()` |

## What Does NOT Change

- `_write_run_artifacts()`, `ai_run_log.jsonl`, `ai_run_summary.json` — monitoring layer stays as-is
- `data/ai/YYYY-MM-DD.json` format — no breaking changes to individual day files
- All existing prompt builder and serializer functions (only `build_briefing_prompt` signature adjusted)
- Data loading functions (`load_latest_snapshot`, `load_latest_delta`)
- GitHub Actions workflow — `data/ai/` is already staged; `index.json` commits automatically

---

## Master Verification Checklist (End of All Phases)

```bash
# 1. All tests pass — no regressions
python3 -m pytest tests/ -q
# Expected: all green, count >= original + new tests

# 2. Smoke test — no API key path
GEMINI_API_KEY="" python3 scripts/generate_ai.py
# Expected output: "GEMINI_API_KEY not set — skipping AI generation."
# Expected: exit 0, no traceback

# 3. index.json structural validation
python3 -c "
import json; from pathlib import Path
idx = json.loads(Path('data/ai/index.json').read_text())
assert 'entries' in idx and 'updated_at' in idx
assert all('date' in e and 'status' in e for e in idx['entries'])
assert idx['entries'] == sorted(idx['entries'], key=lambda e: e['date'], reverse=True)
print('index.json structure OK')
"

# 4. Dashboard import check
python3 -c "import dashboard.app; print('dashboard.app imports OK')"

# 5. generate_ai.py import check
python3 -c "import scripts.generate_ai as g; print('TASK_SPECS count:', len(g.TASK_SPECS)); print('Model:', g.GEMINI_MODEL)"
# Expected: TASK_SPECS count: 3, Model: gemini-2.5-flash

# 6. _is_complete / _missing_fields self-consistency
python3 -c "
import scripts.generate_ai as g
complete = {'sectors': {'briefing': 'x', 'rotation_phase': {'label': 'Mid Cycle', 'reasoning': 'y', 'confidence': 0.8}, 'watchlist': [{'name': 'Tech', 'thesis': 'z'}]}, 'industries': {'briefing': 'x'}}
assert g._is_complete(complete), 'should be complete'
assert g._missing_fields(complete) == [], 'should have no missing fields'
partial = {'sectors': {}, 'industries': {}}
assert not g._is_complete(partial)
assert len(g._missing_fields(partial)) == 4
print('_is_complete/_missing_fields OK')
"
```

## Rollback Strategy (Full)

If any phase causes regressions:
1. `git revert <commit-sha>` for the offending phase commit
2. Run `python3 -m pytest tests/ -q` to confirm green
3. Update `plans/ai-architecture-revamp.md` to mark the phase as reverted with reason
4. Commit the revert + plan update

Each phase is committed independently so rollback is surgical.
