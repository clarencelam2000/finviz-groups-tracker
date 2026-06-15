# Rebuild the AI tab: a freeform daily note grounded in our computed signals

> Implementation plan. Status: approved, in progress.

## Context

The AI tab is unusable. Screenshots (Jun 12–14) confirm the failure: **raw JSON
leaks straight into the UI** — e.g. `{ "key_signals": [ "Energy leads YTD at
+28.3%...` truncated mid-word — "Rotation Phase: Unknown" with `{` bleeding
through, "Unkn" pills in the phase-history strip, and a "WHAT CHANGED" card full
of apology text ("7-day rank delta data is unavailable today."). The June 11 run
(`data/ai/2026-06-11.json`) is the quality bar: clean prose, a real rotation
phase, a 3-name watchlist.

Root cause: the pipeline was rebuilt around **forced JSON schema mode**
(`response_mime_type="application/json"` + `response_schema`) on
`gemini-2.5-flash` with a 1200-token cap. The model emits JSON-inside-JSON,
truncates, and the ~280 lines of schemas/parsers/normalizers/preamble-detection
fight it and lose.

Meanwhile the PWA already has **Today, Movers, Momentum, Strength** tabs showing
every raw metric (All-Green, Sustained-Strong, `momentum_score`,
`rank_agreement`, 7/14/30d movers). The old AI tab just re-displayed those in
fragile JSON cards. **Our computed signals are the moat** — the thing the plain
Finviz groups page can't do — so the AI tab should *narrate those signals* in
plain language, not re-tabulate raw percentages.

**Goal:** the AI tab becomes a **daily market note** — one freeform markdown
document per group (sectors / industries): a TL;DR headline, a short narrative,
then signal-driven sections beneath. Built **from our computed signals**, not
raw perf tables. No schema enforcement anywhere; text shown verbatim via a light
markdown renderer.

### Decisions confirmed with the user
- **Structure:** freeform daily note + signal-driven sections beneath, as one
  markdown blob.
- **One combined Gemini call per group** (not per-section) — sends the signals
  once (leanest input), most coherent, fewest requests. Sectors get one extra
  tiny phase call for the history strip.
- **Emphasis:** all-green & sustained strength · movers & momentum · divergence /
  early-warning. Feed **`rank_agreement`** explicitly (powers "fragile all-green").
- **Token cap removed** (no `max_output_tokens`; prompt asks for brevity).
- Keep a lightweight **rotation-phase label** (sectors only) for the 14-day
  history strip; everything else freeform.

### Input-bloat check (does not grow over time)
`load_latest_snapshot` / `load_latest_delta` already filter to the **latest date
only** — history never enters the prompt, so a prompt 6 months out is the same
size as today's. Inputs are bounded by group counts (~11 sectors, ~150
industries, roughly constant). One concrete trim: today's
`serialize_snapshot_summary` dumps **all ~150 industries** (~3k tokens). Replace
that with **curated, capped signal blocks** (top/bottom-N + the computed lists),
cutting input to ~1–1.5k tokens/call while leaning into the moat.

---

## Phase 0 — land this plan in the repo first (before any code)

1. Commit this document to `planning/ai-tab-daily-note.md` on branch
   `claude/exciting-brown-1pc93v`.
2. Push; open a PR into `claude/elegant-babbage-hlxnfy`; **merge it** before
   starting implementation. (Per user instruction — the plan is the contract.)

---

## New AI JSON shape (per group)

```jsonc
{
  "date": "...", "generated_at": "...", "model": "...",
  "sectors":    { "note": "<markdown>", "rotation_phase": {"label","reasoning"} },
  "industries": { "note": "<markdown>" }
}
```

`note` = one markdown doc: a `**TL;DR**` line, 1–2 narrative paragraphs, then
`## Strength`, `## Movers & Momentum`, `## Divergences`. Calls: **2 for sectors,
1 for industries** (down from 7).

## Backend — `scripts/generate_ai.py`

1. **Delete** all JSON schemas (34–107); `parse_briefing_response` /
   `_normalize_briefing` / `_normalize_phase` (456–510); `_looks_like_preamble`
   (603–619); the daily-delta feature (`build_daily_delta_prompt`,
   `_generate_daily_delta`, `_find_prior_ai_file`, 344–397) and its block in
   `main` (942–968).

2. **Add computed-signal serializers** (deterministic Python, same style as
   existing `serialize_top_movers` / `serialize_momentum_leaders`; each capped to
   N names so input stays lean):
   - `serialize_strength_signals(snap_df, delta_df)` — **all-green**
     (`perf_week/month/quarter/half/ytd` all > 0) + **sustained-strong** (top-N
     across `rank_month`, `rank_quarter`, `rank_half`) + a **breadth one-liner**
     ("8 of 11 sectors all-green"). Reuse the Strength-tab threshold logic.
   - Extend momentum serialization to include **laggards** (lowest
     `momentum_score`) alongside leaders.
   - `serialize_divergences(snap_df, delta_df)` — the additive, no-other-tab
     signal, explicitly using `rank_agreement`: **fading** (high `momentum_score`
     but `rank_ytd_delta_7d` < 0), **emerging** (large positive
     `rank_ytd_delta_7d` but below-median `momentum_score`), **fragile
     all-green** (all-green but low `rank_agreement`). Returns named groups + numbers.
   - All serializers no-op gracefully on empty/short history (no crash, return a
     "not enough history yet" line).

3. **Add `build_note_prompt(group_type, snap_df, delta_df, date_str)`**: ask for
   a markdown note — `**TL;DR**` one-liner, 1–2 short paragraphs, then
   `## Strength`, `## Movers & Momentum`, `## Divergences`; name specific groups,
   cite the numbers from the supplied blocks, **use ONLY the provided signals**,
   be concise, no disclaimers. Replace the full snapshot dump with the curated
   blocks from step 2.

4. **Lightweight phase (sectors only):** simple plain-text
   `parse_phase_response(text) -> {label, reasoning}` (read `Label:` / `Why:`;
   else first line = label, rest = reasoning). Sector prompt still suggests the
   four canonical labels (Early/Mid/Late/Defensive) so the PWA color map +
   history strip match.

5. **Simplify `_call_api`** (622–680): drop `response_schema`; build
   `types.GenerateContentConfig(temperature=...)` with **no `max_output_tokens`,
   no `response_mime_type`, no `response_schema`**; remove fence-stripping +
   preamble check. **Keep** rate-limit spacing, empty-response retry, backoff,
   `DailyQuotaExhaustedError`.

6. **Rewrite `TASK_SPECS` + `generate_for_group`** (523–746): two tasks — `note`
   (both groups) → `result["note"] = raw.strip()`; `rotation_phase` (sectors
   only) → `parse_phase_response(raw)`. Remove `use_json_schema` /
   `response_schema` / `fallback_parse`. Temps ~0.6 (note) / 0.2 (phase).

7. **Update `_expected_fields` / `_is_complete` / `_missing_fields`** to
   `sectors.note`, `sectors.rotation_phase`, `industries.note`.

8. **Leave unchanged:** `_update_index` (reads `sectors.rotation_phase.label`),
   run-artifact logging, backend/auth, snapshot-date logic. Model stays
   `gemini-2.5-flash` (note: June 11 used `gemini-flash-latest` — one-line pin
   swap if quality disappoints).

## Frontend — `docs/index.html`

1. **Add a small self-contained `renderMarkdown(text)`**: escape first, then
   `## headers`, `**bold**`, `-`/`*` bullets, blank-line paragraphs. Vanilla JS +
   Tailwind, matching existing style.

2. **Rewrite the briefing block** (1047–1104): render
   `renderMarkdown(activeGroup.note)` in one card. Backward-compat:
   `note = activeGroup.note || (typeof activeGroup.briefing === 'string'
   ? activeGroup.briefing : activeGroup.briefing?.briefing) || ''`, so the
   June 11 file still renders. Drop all `key_signals` + `<details>` logic.

3. **Remove** the "What changed" daily-delta card (983–997) and the **watchlist
   card** (1021–1045).

4. **Keep** the sector rotation-phase pill + 14-day history strip (1000–1019,
   `loadPhaseHistory`), but **handle "Unknown"/empty labels gracefully** — don't
   render "Unkn" pills (skip or show a neutral dot), and don't show the phase
   card at all if there's no real label.

5. **`shareAI`** (389–397): drop `key_signals`; share title + a `note` snippet.

## Tests — `tests/test_generate_ai.py`

Rewrite by pattern (~2200 lines):
- **Delete** tests for removed code: schema shape, `_normalize_*`,
  `_looks_like_preamble`, `_find_prior_ai_file`, daily-delta flows,
  watchlist-parse, `test_call_api_passes_response_schema_as_config`,
  briefing-key-signals extraction.
- **Add** tests for `serialize_strength_signals` + `serialize_divergences`
  (happy path + empty/short-history edges), `build_note_prompt` (asserts the
  `##` headers + that signal data is embedded), and a `generate_for_group` test
  (note is a plain string; sectors `rotation_phase` is `{label, reasoning}`).
- **Update** the `_call_api` config test to assert **no** `max_output_tokens` /
  `response_schema` passed; keep retry/quota tests.
- **Keep** serializer tests, `_update_index`, `_is_complete`/`_missing_fields`
  (new fields), `_has_new_delta_data`, `main` lifecycle.
- Per `.claude/rules/branch-commit-discipline.md`: tests land with code, green
  before each commit (`python3 -m pytest tests/ -q`).

## Commits (after Phase 0 merges)

1. `refactor: drop JSON schema mode and daily-delta from generate_ai`
2. `feat: add strength/divergence signal serializers`
3. `feat: generate freeform markdown daily note from computed signals`
4. `feat: render AI note as markdown in PWA, drop legacy cards`

Branch `claude/exciting-brown-1pc93v`; draft PR into
`claude/elegant-babbage-hlxnfy`. Update `.session/` notes per the handoff
checklist before the final PR merges.

## Verification

- `python3 -m pytest tests/ -q` green.
- **Regenerate locally to eyeball** (needs a backend — AI Studio `GEMINI_API_KEY`
  or Vertex per CLAUDE.md): `python scripts/generate_ai.py --force-ai`. Confirm
  `data/ai/<date>.json` has a clean markdown `note` per group (TL;DR + paragraphs
  + the three `##` sections, real names/numbers, no truncation), a sector
  `rotation_phase`, and no JSON-in-JSON / watchlist / daily_delta.
  - Likely **cannot run in the Claude Code cloud env** if the Gemini endpoint is
    blocked (same as Playwright per CLAUDE.md) — run locally or via the
    `generate_ai.yml` Action. I'll verify tests + static markdown rendering here.
- **Visual check:** open `docs/index.html` against a regenerated file (or the
  June 11 file via the back-compat path) — markdown note + sections render, the
  phase pill/strip show clean labels (no "Unkn"), and no stale watchlist /
  "What changed" cards remain.
