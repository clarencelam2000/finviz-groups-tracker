# Plan: AI Call Capture & Visibility

> Make the **(input data, prompt, raw output, parsed output)** of every Gemini call
> visible, testable, iterable, and — for users — auditable. Brainstorm origin: VP
> session 2026-06-22 ("can we make AI calls more visible/testable/interactive").
>
> **Status:** plan approved for merge; **implementation on hold** pending VP go-ahead.
> Review by `code-review` bot (PR #154) resolved — see "Review resolutions" below.

## Phase Status

| Phase | Item | Status | Commit |
|-------|------|--------|--------|
| 0 | This plan + ADR-006 | 🟢 Approved (impl on hold) | `docs: revise AI capture plan per review` |
| 1 | Tier-2 debug capture (`CallResult` + `--capture`) | ⬜ Not started | |
| 2 | `--preview` (build prompts, no API) | ⬜ Not started | |
| 3 | Prompt snapshot tests | ⬜ Not started | |
| 4 | Tier-1 provenance + PWA "Behind this" drawer | ⬜ Not started | |
| 5 | `tools/ai-lab.html` offline viewer | ⬜ Not started | |
| 6 | `scripts/eval_ai.py` (offline guards; opt-in LLM-judge) | ⬜ Not started | |
| 7 | Vertex express-key auth path | ⬜ Not started | |
| S | Stretch: PWA `?debug=1`, interactive regenerate/Q&A | ⬜ Backlog | |

> Resuming after a context reset: read this table, then `python3 -m pytest tests/ -q`
> for a green baseline before touching `generate_ai.py`.

---

## Context — the five gaps this closes

The nightly pipeline (`scripts/generate_ai.py`) makes ~11 Gemini calls/run. For each,
pure `serialize_*()` functions turn snapshot/delta CSV rows into text blocks, pure
`build_*_prompt()` functions wrap them in instructions, and `_call_api()` returns raw
markdown that a tolerant parser converts into `data/ai/{date}.json`.

What's missing today:

1. **Prompt + raw response are never persisted.** `ai_run_log.jsonl` records status,
   latency, and `api_calls` — but not one character of what we sent or what the model
   returned. Debugging a bad briefing means re-running locally with `print()` + creds.
2. **Prompt changes are invisible in PRs.** A reviewer editing `build_pulse_prompt`
   sees the f-string, not the *rendered* prompt. No snapshot, no diff.
3. **No quality gate.** Nothing catches a dropped `## Conviction` section, a `Level:`
   outside {High,Medium,Low}, or a hallucinated group name absent from the input. The
   tolerant parsers degrade silently instead of failing loudly.
4. **Slow iteration loop.** Testing one prompt tweak needs creds + a full run. No
   "render this prompt on last Tuesday's data in two seconds."
5. **Zero provenance for users.** The PWA shows conclusions ("Energy rotating in") with
   no way to see the computed signals that justified them — a trust gap for a markets tool.

**Leverage note:** `serialize_*()` and `build_*_prompt()` are already pure,
side-effect-free functions. Almost everything below is additive plumbing around an
existing clean seam — no refactor of the generation logic.

---

## Design principles (constraints from the VP)

- **No one-way doors.** Everything additive. Free Google Cloud credits make live calls
  cheap *now*, but the design must scale down cleanly when the trial expires (~months).
  All token-spending paths are flag-gated and isolated in their own script — never on
  the nightly critical path.
- **No Streamlit.** The interactive layer is a single static HTML file reusing the
  existing vanilla-JS PWA stack, not a new framework/dependency.
- **Never lose run info (revised 2026-06-22).** Ephemeral CI/cloud runners reclaim any
  file that isn't committed. Therefore capture artifacts are **committed**, not
  gitignored — see "Persistence & retention" below. Only local secrets (`.env`) stay
  gitignored.

---

## Persistence & retention (revised per VP — the gitignore question)

> **VP flag:** "we will lose data and run infos if we gitignore???" — correct. The
> original draft gitignored Tier-2; that would discard it with the CI runner. Fixed.

What is **already committed today** (so already safe): `data/ai/*.json` (outputs),
`data/ai/index.json`, `data/ai_run_log.jsonl`, `data/ai_run_summary.json`. Run metadata
is **not** at risk. The only new at-risk artifact was the Tier-2 debug capture.

Revised rules:

| Artifact | Location | Committed? | Retention |
|----------|----------|-----------|-----------|
| Tier-1 provenance | `data/ai/provenance/{date}.json` | ✅ Yes | Permanent (small, user-facing) |
| Tier-2 debug capture | `data/ai/debug/{date}.json` | ✅ Yes | **Rolling 30 days in `HEAD`**; older pruned but **recoverable from git history** |
| Run log (existing) | `data/ai_run_log.jsonl` | ✅ Yes (unchanged) | Append-only |
| Local `.env` | repo root | ❌ gitignored (unchanged) | n/a — secrets |

Key points that answer the VP's concern:
- **Nothing is destroyed.** Rolling retention removes Tier-2 files from `HEAD` only; every
  version remains in git history (`git log -- data/ai/debug/<date>.json` recovers it).
- **`--capture` is ON in CI** (set in `collect.yml`) so the nightly run persists Tier-2.
  Off by default for ad-hoc local runs that don't want the churn.
- **Size is bounded and tiny:** ~11 calls/day × ~3 KB ≈ 33 KB/day; a 30-day window ≈ 1 MB.
- **Optional (Open Decision #2):** also upload the full Tier-2 dir as a GitHub Actions
  artifact for ergonomic long-term access without `git log` spelunking. Lean "add later".
- **`.gitignore` change:** none required for capture (we are *not* ignoring `debug/`).
  The earlier draft's "add `data/ai/debug/`" line is **removed**.

---

## Review resolutions (PR #154, 2026-06-22)

| # | Reviewer flag | Resolution |
|---|---------------|------------|
| 🔴1 | `_call_api()` returns bare string; can't surface usage/latency | **VP decision: `CallResult` dataclass** (`text`, `usage`, `latency`). Phase 1 introduces it; `test_generate_ai.py` updates to unpack `.text`. See Phase 1. |
| 🔴2 | Phase 3 snapshot tests assume prompt determinism | **Audited:** every `build_*_prompt()` injects exactly one non-CSV value, `date_str` (plus `group_name`, derived from `group_type`). Deterministic given fixed `date_str` + group_type + CSVs. Fixtures pin `date_str`. Gate closed. |
| 🔴3 | Committed Tier-1 provenance has no CI owner | **Resolved:** `collect.yml:174` already runs `git add data/` (the whole tree), so `data/ai/provenance/` is staged automatically and committed Tier-2 too. Phase 1 adds a checklist item to confirm the AI step runs **before** that `git add`, and that `--capture` is enabled in CI. |
| 🟡4 | Verify SDK exposes `usage_metadata` | **Confirmed:** `requirements.txt` pins `google-genai>=2.8.0,<3.0.0` — exposes `usage_metadata`. |
| 🟡5 | `?debug=1` understates scope (Pages is public) | Agreed; stays in backlog. Serving Tier-2 publicly needs an authenticated endpoint — explicitly **not** in Phase 5 scope. |
| 🟡6 | Open Decision #2 (CI artifact vs gitignored) | Superseded — Tier-2 is now committed with rolling retention; CI artifact is an optional add-on, not the persistence mechanism. |
| 🔑 | `GOOGLE_API_KEY` env note | **Confirmed present in this env** (presence verified, value never printed). CI repo secret still TODO for the nightly path (tracked in Phase 7). |

---

## The keystone: two-tier capture

One hook in `generate_for_group()` (the loop at `generate_ai.py:1028-1059` already holds
`prompt`, the parsed result, `generation_config`, and timing) writes to two tiers.

### Tier 1 — Provenance (committed, slim, user-facing)

Deterministic from the CSVs, tiny, safe to commit permanently. Powers the PWA "Behind
this" drawer. Per call, only the **input data block** (the serializer output) — no prompt
boilerplate, no raw response.

```jsonc
// data/ai/provenance/2026-06-18.json   (committed, ~5-15 KB/day, permanent)
{
  "date": "2026-06-18",
  "sectors.pulse":        { "input_blocks": "MARKET STATE: All-green breadth 7/11 (64%)...\nTOP GAINERS...\nDIVERGENCES..." },
  "sectors.rotation_map": { "input_blocks": "ROTATION FLOW: ..." }
}
```

### Tier 2 — Debug capture (committed, full, dev-facing, rolling 30d)

The complete forensic record. Powers preview/diff/eval. Written when `--capture` /
`AI_CAPTURE=1` is on (ON in CI). Committed with a rolling 30-day window in `HEAD`.

```jsonc
// data/ai/debug/2026-06-18.json   (committed; pruned from HEAD after 30d, kept in history)
{
  "date": "2026-06-18", "model": "gemini-3.5-flash", "backend": "vertex_express",
  "captured_at": "2026-06-18T22:01:14Z",
  "calls": {
    "sectors.pulse": {
      "task": "pulse", "group_type": "sector",
      "prompt": "<the full string sent to Gemini>",
      "generation_config": { "temperature": 0.4 },
      "raw_response": "## Headline\n...",
      "parsed_output": { "headline": "...", "conviction": { "level": "High", "why": "..." } },
      "latency_seconds": 12.3,
      "usage": { "prompt_tokens": 1840, "output_tokens": 95, "total_tokens": 1935 },
      "status": "ok"
    }
  }
}
```

### Why this shape

- **One hook, two writers.** Add `_record_capture(fkey, ...)` beside the existing
  `_record_field(...)` call. No change to the pure builders/serializers.
- **Token usage paper trail.** Capturing `usage_metadata` now — while credits are free —
  gives the cost history we'll want exactly when credits expire.
- **Tier 1 is derivable without the API** (it's just the serializer output), so it's
  written even on a `--preview`/dry run.
- **PWA never reads Tier 2.** Users only see the slim, committed Tier-1 block.

---

## Phase 1 — Tier-2 capture + `CallResult` (keystone)

- **`CallResult` dataclass** (VP decision): `_call_api()` returns
  `CallResult(text: str, usage: dict, latency: float)` instead of a bare string.
  - Update the two call sites in `generate_for_group()` to use `.text`.
  - Update `test_generate_ai.py`: any test asserting `_call_api` returns a string now
    asserts on `.text`; add a test that `usage`/`latency` are populated (mocked client).
- `_extract_usage(response) -> dict`: pull `usage_metadata` defensively (absent on some
  error/retry paths → `{}`).
- `_record_capture(...)`: accumulate per-call Tier-2 entries into a run-level dict
  (mirrors `_field_log`).
- Write both tiers in `main()` after generation; **prune Tier-2 to the last 30 dates**
  (mirror the `entries[:90]` pattern in `_update_index`).
- New constants (documented in all 3 places — see Config constants): `CAPTURE_DIR`,
  `PROVENANCE_DIR`, `CAPTURE_RETENTION_DAYS = 30`.
- CLI `--capture` flag + `AI_CAPTURE` env; Tier-1 always writes, Tier-2 only when on.
- **CI wiring checklist (resolves 🔴3):** confirm in `collect.yml` that (a) the
  `generate_ai.py` step runs before `git add data/`, and (b) it passes `--capture` (or
  sets `AI_CAPTURE=1`).

---

## Phase 2 — `--preview` (no API, no creds)

`python scripts/generate_ai.py --preview [--date YYYY-MM-DD] [--task pulse] [--group sector]`

Renders the selected prompts from existing CSVs and prints them (and writes Tier-1
provenance) **without calling Gemini**. Preview is "capture minus the API call": reuses
`_build_prompt()` and the same serializers. Instant iteration, runnable here with zero
credentials. `--json` for machine-readable output; `--task`/`--group` to focus one call.

---

## Phase 3 — Prompt snapshot tests (item ③)

`tests/fixtures/ai/` holds frozen `(input CSV slice + fixed date_str → rendered prompt)`
snapshots, one per task × group. A test rebuilds the prompt and asserts equality, so a
prompt edit surfaces as a **reviewable diff in the PR** and fails CI if unintended.

- **Determinism confirmed** (resolution 🔴2): fixtures pin `date_str`; `group_type` is the
  only other prompt-shaping input. No hidden non-determinism.
- Intentional prompt change ⇒ regenerate the snapshot in the same commit
  (`--update-snapshots` pytest flag or a tiny helper).

---

## Phase 4 — Tier-1 provenance → PWA "Behind this" drawer (item ⑥)

`docs/index.html` fetches `data/ai/provenance/{date}.json` alongside the AI JSON. Each AI
card gets a small ⓘ "Behind this" expander revealing the exact input block:

```
## Conviction    Level: High
Why: 64% all-green breadth, agreement 0.71, 2 divergences.
└─ ⓘ Behind this ▼
   MARKET STATE: All-green breadth 7/11 (64%)...
   Mean rank agreement: 0.71
   Momentum accel: 5 building, 1 fading
```

- Backward-compatible: no provenance file ⇒ drawer absent.
- Frontend-only render change (note in commit; optional Playwright assertion).
- Ships with a "What's New" release entry + `sw.js` CACHE bump (CLAUDE.md 3-step rule).

---

## Phase 5 — `tools/ai-lab.html` offline viewer (item ⑤, de-Streamlit'd)

A single vanilla-JS file (same stack as `docs/index.html`; lives in `tools/` so GitHub
Pages doesn't serve it). Loads a Tier-2 debug JSON (drag-drop or `?file=`) and renders per
call: **input block | prompt | raw response | parsed output** in columns. Features:

- Date / version A-B diff (same task across two captures, or two prompt versions on the
  same data — the iterate loop made visual).
- Token + latency readout per call.
- No build step, no server, no creds. Live re-run from the viewer is a deliberate later
  opt-in (`--serve`); v1 is read-only over captures.

---

## Phase 6 — `scripts/eval_ai.py` (item ④, quarantined)

A **separate** script so token spend is never on the nightly path.

**Offline guards (no API, run in CI):**
- **Hallucination guard (highest value):** every group name in a call's output must appear
  in that call's input block. Catches invented sectors/industries.
- **Format adherence:** pulse has Headline + Conviction; `Level ∈ {High,Medium,Low}`;
  watchlist ≤ 5 bullets; rotation_phase label ∈ the 4 enum values; no empty parsed sections.
- Runs over Tier-2 captures / historical `data/ai/*.json`; zero creds, zero cost.

**LLM-judge (opt-in, flag-gated, uses free credits):**
- `--judge` grades groundedness on a batch of dates. Isolated; manual/optional-CI only.

---

## Phase 7 — Vertex express-key auth path

The new **Vertex API key** sidesteps both AI Studio's 429s and ADC. Add a third
client-init branch in `main()`:

```python
# Priority: Vertex express key > Vertex ADC > AI Studio key
vertex_api_key = os.getenv("GOOGLE_API_KEY")          # Vertex express mode
if use_vertexai and vertex_api_key:
    client = genai.Client(vertexai=True, api_key=vertex_api_key)   # no ADC needed
elif use_vertexai:
    client = genai.Client(vertexai=True, project=..., location=...)  # ADC (CI)
else:
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))       # AI Studio
```

- `_backend` gains `"vertex_express"`.
- **Key provisioning (never in chat/repo):**
  - *This env:* `GOOGLE_API_KEY` already set (confirmed 2026-06-22). Read via `os.getenv`.
  - *CI:* add a GitHub Actions repository secret, inject as env in `collect.yml`. **TODO.**
  - Restrict the key + quota cap in the Cloud console; rotate on suspected exposure.
- Reachability verified 2026-06-22: `generativelanguage` + `aiplatform` endpoints return
  HTTP responses from this container.

---

## Stretch / backlog (items ⑦, ⑧)

- **PWA `?debug=1`** — reveal full prompt + raw response per card for on-device
  dogfooding. GitHub Pages is public, so this needs an **authenticated** endpoint to serve
  Tier-2 — not a mere flag. Stays backlog; must not creep into Phase 5.
- **Interactive regenerate / Q&A (⑧)** — "regenerate with a different angle" + free-form
  Q&A over the day's input block. This is the AI-2 Q&A epic hinted in
  `planning/ai-architecture-revamp.md`; tracked separately, out of scope here.

---

## Files touched (at implementation time — not now)

| Phase | Files |
|-------|-------|
| 1 | `scripts/generate_ai.py`, `tests/test_generate_ai.py`, `.github/workflows/collect.yml` (capture flag + step order), `README.md` + `CLAUDE.md` (config constants) |
| 2 | `scripts/generate_ai.py`, `tests/test_generate_ai.py` |
| 3 | `tests/test_generate_ai.py`, `tests/fixtures/ai/*` |
| 4 | `docs/index.html`, `docs/sw.js`, `docs/releases.json` |
| 5 | `tools/ai-lab.html` (new) |
| 6 | `scripts/eval_ai.py` (new), `tests/test_eval_ai.py` (new), optionally `.github/workflows/tests.yml` |
| 7 | `scripts/generate_ai.py`, `tests/test_generate_ai.py`, `.github/workflows/collect.yml` (CI secret) |

Cross-cutting docs: `knowledge/decisions/ADR-006-ai-call-capture.md` (this session),
`.session/` notes, and the README § Configurable parameters table.

---

## Testing plan

| Phase | Tests |
|-------|-------|
| 1 | `CallResult` unpack at call sites; `_extract_usage` (present/absent); `_record_capture` accumulation; two-tier write + 30-day prune to `tmp_path`; capture-off writes no debug file |
| 2 | `--preview` builds expected prompt and makes zero API calls (`_api_call_count == 0`) |
| 3 | Snapshot equality per task×group with pinned `date_str`; update-snapshot flow |
| 4 | Frontend-only (note in commit); optional Playwright drawer render + absent-file fallback |
| 6 | Hallucination guard catches an injected fake group; format guards catch a dropped section / bad level |
| 7 | Client-init branch selection by env (mock `genai.Client`); `_backend` value |

Per repo rule: every `scripts/` change ships with a `tests/` change in the same commit.
Run `python3 -m pytest tests/ -q` before each commit.

---

## Configurable constants (document in all 3 places per CLAUDE.md)

- `CAPTURE_DIR` / `PROVENANCE_DIR` — output locations.
- `CAPTURE_RETENTION_DAYS = 30` — rolling Tier-2 window in `HEAD` (older pruned, kept in
  git history). Tune up for more in-repo history, down to shrink the working tree.
- `AI_CAPTURE` env / `--capture` flag — Tier-2 on/off (default off; ON in CI).
- `GOOGLE_API_KEY` — Vertex express key (new auth path).

Each gets: in-code comment + README § Configurable parameters row + a CLAUDE.md note.

---

## Open decisions for the VP (remaining)

1. **Provenance granularity:** verbatim input block (simplest, ~10 KB/day) vs. structured
   per-signal dict (richer PWA rendering, more code). Recommend verbatim for v1.
2. **Tier-2 long-term archive:** rolling-30d-in-HEAD is the baseline (history always
   recoverable). Optionally *also* upload the full dir as a CI artifact for easy access.
   Recommend adding the CI artifact once Phase 6 eval is live.
3. **Eval cadence:** offline guards in CI on every PR touching `generate_ai.py` (cheap,
   recommended) vs. nightly. LLM-judge stays manual until the offline guards are trusted.

---

## Execution order

1 → 2 → 7 (unblocks live capture in-session) → 3 → 4 → 5 → 6.

Phase 1 is the keystone; 2 gives an instant no-creds loop; 7 makes live capture work
*here* (express key) rather than only in CI; 3/4/5/6 then fan out from the artifacts.
