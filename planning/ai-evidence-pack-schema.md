# Evidence pack — schema design pass (AI-NEXT-P0)

**Status:** Design pass. Awaiting owner review. No code.
**Date:** 2026-09-05
**Parent:** `planning/ai-llm-integration-proposal.md` (§2 architecture, §3.0 framing)
**Blocks:** every other AI-NEXT phase. P0 must land before P1/P2/P4.

---

## 1. Why this needs a schema before code

Three decisions from the proposal review turned the evidence pack from "a dict we build in
`generate_ai.py`" into a contract with real obligations:

1. **Slot filling** — the model returns sentence templates plus *field references*, and the renderer
   resolves them. A field reference is only meaningful against a stable, addressable namespace. An
   ad-hoc dict has no addresses.
2. **Two runtimes** — Tier A builds packs in Python (`generate_ai.py`), Tier B in JS
   (`worker-positions`). They must be structurally identical or the same prompt behaves differently
   on the Positions tab than on Picks.
3. **Citation-driven provenance** — the "ⓘ Behind this" drawer renders *the subset of fields the
   model cited*. That requires resolving a citation back to a field and its human label at render
   time.

None of those work against an untyped bag. Hence a design pass rather than folding it into P0's
implementation PR.

---

## 2. Shape

A pack is one JSON object. Four top-level keys, and that shape never varies by surface:

```json
{
  "meta":    { "pack_version": "1.0.0", "surface": "morning", "as_of": "2026-09-05",
               "session": "morning", "generated_at": "2026-09-05T14:05:11Z" },
  "fields":  { "<field_id>": { "v": <value>, "u": "<unit>", "l": "<human label>" } },
  "context": { "<block_id>": { "label": "...", "rows": [ ... ] } },
  "notes":   [ "free-text caveats the builder wants the model to know" ]
}
```

### 2.1 `fields` — the addressable, citable layer

Flat. Dotted `field_id` keys, no nesting, because a flat namespace makes both slot resolution and
citation lookup a single dictionary access with no traversal code in two languages.

```json
"fields": {
  "row.ticker":            { "v": "NVDA",  "u": "text",    "l": "Ticker" },
  "row.trigger":           { "v": 184.20,  "u": "usd",     "l": "Trigger price" },
  "row.price":             { "v": 186.05,  "u": "usd",     "l": "Price now" },
  "row.atr_from_lod":      { "v": 0.42,    "u": "atr",     "l": "ATR from low of day" },
  "row.rel_volume":        { "v": 2.10,    "u": "x",       "l": "Relative volume" },
  "earnings.days_to":      { "v": 6,       "u": "sessions","l": "Sessions to earnings" },
  "group.rank_month":      { "v": 3,       "u": "rank",    "l": "Group 1-month rank" },
  "prior.status":          { "v": "setting_up", "u": "enum", "l": "Status at 10:05" }
}
```

Rules:

- **Every number the user will ever see is a field.** If prose needs a value, it is a field first.
- `u` (unit) drives rendering — `usd`, `pct`, `pp`, `atr`, `x`, `rank`, `sessions`, `enum`, `text`,
  `ratio`. **The model never formats a number**; the renderer formats by unit, so `$184.20` and
  `2.1×` are consistent with the rest of the PWA for free.
- `l` (label) is what the provenance drawer shows. Required — an unlabeled field can't be cited
  legibly.
- **Derived values are fields too.** If we want "your stop is 7% away," `derived.stop_gap_pct` is
  computed by the builder, not by the model. This is the deterministic-computation boundary: the
  model reasons about which fact matters; it never does arithmetic that reaches the screen.

### 2.2 `context` — the broad, non-citable layer

Per the proposal's "feed broadly" decision, this is where bulk goes: all 144 industries, the full
pick row, the whole `position_events` ledger, prior sessions. Row-oriented, compact, and explicitly
**not** individually addressable — promoting a value out of `context` into `fields` is the
deliberate act that makes it quotable.

That split is the whole guardrail: **breadth for the model's reasoning, a bounded set for the
reader's provenance.** Without it, "Behind this" degrades into a data dump and stops being read.

### 2.3 `notes`

Builder-authored caveats the model should condition on but not repeat verbatim — e.g. "SPY row
missing for this date, RS columns are NaN", "fewer than 50 sessions of history, 50d deltas are NaN".
Prevents the model confidently narrating a NaN.

---

## 3. Model output contract

```json
{
  "statements": [
    { "kind": "thesis",
      "text": "Group is #{rank} by 1-month rank and this triggered on {relvol} volume.",
      "slots": { "rank": "group.rank_month", "relvol": "row.rel_volume" },
      "cites": ["group.rank_month", "row.rel_volume", "prior.status"],
      "confidence": "high" },
    { "kind": "catch",
      "text": "Earnings in {days} sessions.",
      "slots": { "days": "earnings.days_to" },
      "cites": ["earnings.days_to"],
      "confidence": "high" }
  ]
}
```

- `slots` — every `{name}` in `text` must appear here, and every value must be a valid `field_id`.
- `cites` — a superset of the slot fields: what it *reasoned from*, including fields it didn't
  quote. Drives the provenance drawer.
- `confidence` — per §3.0 of the proposal, derived from evidence strength, not a persona setting.
- `kind` — `thesis` / `catch` / `triage` / `hold_read` etc., so the renderer places it.

### 3.1 Validation (the whole gate, and it is now cheap)

1. Every `{slot}` in `text` has an entry in `slots`. 2. Every `slots` value and every `cites` entry
resolves in `fields`. 3. `text` contains **no bare digits** outside `{slots}`. 4. A `catch` statement
exists and is non-empty (the mandatory counter-evidence rule).

All four are mechanical. **No numeric-comparison heuristics, no fuzzy matching** — which is exactly
the brittleness the owner flagged in the earlier blocking-gate proposal. A failure here is a bug in
our prompt, not a judgement call about a model's arithmetic, so failing closed is safe.

---

## 4. Versioning

`meta.pack_version` is semver. **Minor** = fields added (a renderer built on 1.0 keeps working).
**Major** = a field removed or its `u`/meaning changed, which can silently corrupt a cached
statement's rendering — so cached Tier B statements are invalidated on major bump.

Field ids are an API the model is prompted against. Renaming one is a breaking change; prefer
adding and deprecating.

---

## 5. Where it lives

- `scripts/evidence_pack.py` — builders + the field registry (Tier A, and the source of truth).
- `worker-positions/src/evidencePack.js` — Tier B builder for position/watchlist packs.
- **`data/ai/pack_schema.json`** — the shared field registry (id → unit → label), generated from
  the Python registry and committed, so the JS side and any test can assert against one artifact
  rather than duplicating a list in two languages. This is the same anti-drift pattern
  `delta_config.delta_columns()` already uses for the deltas schema, and the same one
  `display_methodology.json` uses for PWA constants.

No ground-truth CSV changes. Per `.claude/rules/data-pipeline.md`, nothing here becomes a column on
`picks.csv` or the session stores.

---

## 6. Open questions for the owner

1. **Registry enforcement.** Should a field id absent from `data/ai/pack_schema.json` be a hard
   build error, or a warning? Hard error is safer (catches drift in CI) but means every new field
   touches the registry in the same PR. *Recommend: hard error, consistent with the repo's existing
   anti-drift tests.*
2. **`context` budget.** "Feed broadly" needs a ceiling somewhere or a Positions pack with a
   200-event ledger and 60 bars gets slow on the on-demand tap. *Recommend: no cap for Tier A batch;
   a soft cap on Tier B with oldest-first truncation and a `notes` entry saying what was dropped.*
3. **Does `confidence` render?** It's in the contract either way. Showing it is honest but adds
   chrome to every card. *Recommend: don't render in v1; log it, and revisit once there's a sense of
   whether it varies meaningfully.*

---

## 7. Not in scope here

Prompt text, task registry changes, and any UI. This pass defines the contract only; P0's
implementation PR builds the Tier A builder and registry against it.
