# Plan: AI Call Capture & Visibility

> Make the **(input data, prompt, raw output, parsed output)** of every Gemini call
> visible, testable, iterable, and — for users — auditable. Brainstorm origin: VP
> session 2026-06-22 ("can we make AI calls more visible/testable/interactive").

## Phase Status

| Phase | Item | Status | Commit |
|-------|------|--------|--------|
| 0 | This plan | 🟡 In review | `docs: add AI capture & visibility plan` |
| 1 | Tier-2 debug capture (`--capture`) | ⬜ Not started | |
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
   outside {High,Med,Low}, or a hallucinated group name absent from the input. The
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
- **Two retention tiers.** A slim, committed, user-facing tier and a heavy, gitignored,
  dev-only tier — produced by the same hook, governed by different rules.

---

## The keystone: two-tier capture

One hook in `generate_for_group()` (the loop at `generate_ai.py:1028-1059` already holds
`prompt`, `raw`, the parsed result, `generation_config`, and timing) writes to two tiers.

### Tier 1 — Provenance (committed, slim, user-facing)

Deterministic from the CSVs, tiny, safe to commit. Powers the PWA "Behind this" drawer.
Per call, only the **input data block** (the serializer output) — no prompt boilerplate,
no raw response.

```jsonc
// data/ai/provenance/2026-06-18.json   (committed, ~5-15 KB/day)
{
  "date": "2026-06-18",
  "sectors.pulse":        { "input_blocks": "MARKET STATE: All-green breadth 7/11 (64%)...\nTOP GAINERS...\nDIVERGENCES..." },
  "sectors.rotation_map": { "input_blocks": "ROTATION FLOW: ..." }
}
```

### Tier 2 — Debug capture (gitignored, full, dev-facing)

The complete forensic record. Powers preview/diff/eval. Behind `--capture` / `AI_CAPTURE=1`,
**off by default**, written to gitignored `data/ai/debug/` so the repo never bloats unless
we opt in.

```jsonc
// data/ai/debug/2026-06-18.json   (gitignored)
{
  "date": "2026-06-18", "model": "gemini-3.5-flash", "backend": "vertex_ai",
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
- **Token usage is a freebie.** `response.usage_metadata` (google-genai) yields
  prompt/output/total tokens — capturing it now gives a cost paper trail *before* the
  free credits expire, which is exactly when we'll want it.
- **Tier 1 is derivable without the API.** The input block is just the serializer output,
  so provenance can be written even on a dry/preview run (no creds needed).
- **PWA never reads Tier 2.** Users only ever see the slim, committed Tier-1 block —
  raw prompts/responses stay dev-only.

### Implementation surface (Phase 1)

- New module-level constant block (documented per the 3-places rule):
  - `CAPTURE_DIR = DATA_DIR / "ai" / "debug"` — gitignored Tier-2 output.
  - `PROVENANCE_DIR = DATA_DIR / "ai" / "provenance"` — committed Tier-1 output.
- `_record_capture(fkey, task, group_type, prompt, raw, parsed, cfg, usage, elapsed)`:
  accumulate into a run-level dict (mirrors `_field_log`).
- `_extract_usage(response) -> dict`: pull `usage_metadata` defensively (absent on some
  error/retry paths → `{}`).
- Write both tiers in `main()` after generation (alongside `_write_run_artifacts`).
- `.gitignore`: add `data/ai/debug/`.
- CLI: `--capture` flag; env `AI_CAPTURE=1` equivalent. Tier-1 provenance writes
  **always** (it's small and committed); Tier-2 writes only when capture is on.

---

## Phase 2 — `--preview` (no API, no creds)

`python scripts/generate_ai.py --preview [--date YYYY-MM-DD] [--task pulse] [--group sector]`

Renders the selected prompts from existing CSVs and prints them (and writes the Tier-1
provenance block) **without calling Gemini**. Preview is "capture minus the API call":
it reuses `_build_prompt()` and the same serializers. Instant iteration, runnable in this
cloud container with zero credentials.

Output: human-readable to stdout by default; `--json` for machine-readable; honors
`--task`/`--group` filters to focus on one call.

---

## Phase 3 — Prompt snapshot tests (item ③, re-added)

`tests/fixtures/ai/` holds frozen `(input CSV slice → rendered prompt)` snapshots, one
per task × group. A test builds the prompt from the fixture CSV and asserts it equals the
stored snapshot. A prompt edit then surfaces as a **reviewable diff in the PR** and fails
CI if unintended — same anti-drift discipline as `GUIDE` ↔ `moaty-metrics.md`.

- Update workflow: intentional prompt change ⇒ regenerate snapshot in the same commit
  (a `--update-snapshots` pytest flag or a tiny helper script).
- Pairs naturally with the existing pure-function tests in `tests/test_generate_ai.py`.

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

- Backward-compatible: if no provenance file for a date, the drawer is simply absent.
- Frontend-only render change (no test required per repo rules; note in commit).
- Ships with a "What's New" release entry + `sw.js` CACHE bump (CLAUDE.md 3-step rule).

---

## Phase 5 — `tools/ai-lab.html` offline viewer (item ⑤, de-Streamlit'd)

A single vanilla-JS file (same stack as `docs/index.html`, lives in `tools/` so it's not
served by GitHub Pages). Loads a Tier-2 debug JSON (drag-drop or `?file=`) and renders,
per call: **input block | prompt | raw response | parsed output** in columns. Features:

- Date / version A-B diff (compare the same task across two captures, or two prompt
  versions on the same data — the "iterate" loop, made visual).
- Token + latency readout per call (cost awareness).
- No build step, no server, no creds — pure static viewer over captured artifacts.

> Live re-run from the viewer (edit prompt → call Gemini → see result) is a deliberate
> *later* opt-in (`--serve` endpoint). v1 is read-only over captures.

---

## Phase 6 — `scripts/eval_ai.py` (item ④, quarantined)

A **separate** script so token spend is never on the nightly path. Two layers:

**Offline guards (no API, run in CI):**
- **Hallucination guard (highest value):** every group name in a call's output must
  appear in that call's input block. Catches invented sectors/industries.
- **Format adherence:** pulse has exactly Headline + Conviction; `Level ∈ {High,Medium,Low}`;
  watchlist ≤ 5 bullets; rotation_phase label ∈ the 4 enum values; no empty parsed sections.
- Runs over Tier-2 captures (or historical `data/ai/*.json`); zero creds, zero cost.

**LLM-judge (opt-in, flag-gated, uses free credits):**
- `--judge` grades groundedness ("is each claim supported by the input block?") on a
  batch of dates. Isolated, manual/optional-CI only; turn it off by not running it.

---

## Phase 7 — Vertex express-key auth path (item: VP's new API key)

The new **Vertex API key** sidesteps both AI Studio's 429s and the ADC problems in this
environment. Add a third client-init branch in `main()`:

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

- `_backend` gains a `"vertex_express"` value for the run log.
- **Key provisioning (never in chat/repo):**
  - *This env:* set `GOOGLE_API_KEY` as an environment variable in the Claude Code web
    environment config / setup script. Read via `os.getenv`, never printed.
  - *CI:* GitHub Actions repository secret, injected as env in `collect.yml`.
  - Restrict the key (API + referrer restrictions, quota cap) in the Cloud console; rotate
    on any suspected exposure. `.env` is already gitignored as a local fallback.
- Reachability verified 2026-06-22: `generativelanguage` + `aiplatform` endpoints return
  HTTP responses from this container (404 to unauthenticated root = reachable).

---

## Stretch / backlog (items ⑦, ⑧)

- **PWA `?debug=1`** — a hidden query param that reveals the full prompt + raw response
  per card for on-device dogfooding. Needs Tier-2 served somewhere non-public, so gated
  and off by default.
- **Interactive regenerate / Q&A (⑧)** — "regenerate this section with a different angle"
  and free-form Q&A over the day's input block. This is the AI-2 Q&A epic hinted in
  `planning/ai-architecture-revamp.md`; tracked separately, out of scope here.

---

## Testing plan

| Phase | Tests |
|-------|-------|
| 1 | `_record_capture` accumulation, `_extract_usage` (present/absent), two-tier write to `tmp_path`, capture-off writes nothing to debug/ |
| 2 | `--preview` builds expected prompt and makes zero API calls (assert `_api_call_count == 0`) |
| 3 | Snapshot equality per task×group; update-snapshot flow |
| 4 | Frontend-only (note in commit); optional Playwright assert drawer renders + absent-file fallback |
| 6 | Hallucination guard catches an injected fake group; format guards catch a dropped section / bad level |
| 7 | Client-init branch selection by env (mock `genai.Client`); `_backend` value |

Per repo rule: every `scripts/` change ships with a `tests/` change in the same commit.
Run `python3 -m pytest tests/ -q` before each commit.

---

## Configurable constants (document in all 3 places per CLAUDE.md)

- `CAPTURE_DIR`, `PROVENANCE_DIR` — output locations.
- `AI_CAPTURE` env / `--capture` flag — Tier-2 on/off (default off).
- `GOOGLE_API_KEY` — Vertex express key (new auth path).

Each gets: in-code comment + README § Configurable parameters row + a CLAUDE.md note.

---

## Open decisions for the VP

1. **Provenance granularity:** store the full input block verbatim (simplest, ~10 KB/day)
   vs. a structured per-signal dict (richer PWA rendering, more code). Recommend verbatim
   for v1.
2. **Tier-2 retention:** gitignored-only (dev runs locally/in-session) vs. also uploaded
   as a CI artifact on the nightly run for post-hoc inspection. Recommend gitignored-only
   first; CI artifact as a fast-follow if we want history.
3. **Eval cadence:** offline guards in CI on every PR touching `generate_ai.py` (cheap,
   recommended) vs. nightly. LLM-judge stays manual until we trust the offline guards.

---

## Execution order

1 → 2 → 7 (unblocks live capture in-session) → 3 → 4 → 5 → 6.

Rationale: Phase 1 is the keystone; 2 gives an instant no-creds loop; 7 makes live
capture work *here* (express key) rather than only in CI; 3/4/5/6 then fan out from the
captured artifacts.
