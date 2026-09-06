# Evidence pack — schema design pass (AI-NEXT-P0)

**Status:** Design pass **reviewed and locked** (owner answers folded into §6; staff review pass
2026-09-06, log in §9). No code. Implementable as `AI-NEXT-P0a/b/c` in `.session/SPRINT.md`.
**Date:** 2026-09-05 · reviewed 2026-09-06
**Parent:** `planning/ai-llm-integration-proposal.md` (§2 architecture, §3.0 framing)
**Blocks:** every other AI-NEXT phase. P0 must land before P2/P1/P4.

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
  "meta":    { "pack_version": "1.0.0", "surface": "morning_card", "subject": "NVDA",
               "as_of": "2026-09-05", "session": "pre_close",
               "generated_at": "2026-09-05T19:35:11Z", "pack_hash": "sha256:…" },
  "fields":  { "<field_id>": { "v": <value>, "u": "<unit>", "l": "<human label>" } },
  "context": { "<block_id>": { "label": "...", "rows": [ ... ] } },
  "notes":   [ "free-text caveats the builder wants the model to know" ]
}
```

### 2.0 Granularity — one pack per *statement target*

The original draft's example was a single row, but the first surface (Morning) has ~115 rows a
day and the triage summary reasons *across* them. So a pack's scope has to be explicit:

| `meta.surface` | One pack per… | `meta.subject` | Statements it yields |
|---|---|---|---|
| `morning_card` | (session, ticker) row in scope | ticker | `read`, `catch` |
| `morning_triage` | session | `"*"` | `triage`, `pattern`, `catch` |
| `picks_card` | Focus row | ticker | `thesis`, `catch` |
| `brief_public` | trading day | `"*"` | `regime`, `action`, `non_action`, `uncertainty` |
| `position` (Tier B) | open position | position id | `hold_read`, `catch` |

Rules that follow:

- **`fields` is scoped to the subject.** In a `morning_card` pack, `row.*` means *this ticker's
  row*. No cross-row field ids like `NVDA.trigger` — that would make the namespace unbounded and
  the registry unenforceable.
- **Cross-row facts are `derived.*` aggregates**, computed by the builder into the triage pack —
  `derived.n_actionable`, `derived.n_invalidated`, `derived.invalidated_ext_atr_median`. If the
  triage summary wants to say "4 invalidated overnight, all >2.5 ATR extended", both numbers are
  builder-computed fields, per the deterministic-computation boundary in §2.1.
- **Triage may cite subjects.** A `morning_triage` statement may carry `subjects: ["NVDA","AMD"]`
  so the renderer can link the ranked names to their cards. Subjects are validated against the
  session's row set, not against `fields`.
- **The shared bulk goes in `context` once per run, not once per pack.** All ~115 rows and the
  144-industry deltas are identical across every `morning_card` pack in a session. The prompt
  assembler emits them as the **stable prefix** (see §2.5) and the per-card `fields` as the
  volatile tail. Physically each pack still carries its `context` (a pack must be self-describing
  for the provenance record), but the prompt is `[system + registry + shared context] + [fields]`.
- **`meta.pack_hash`** is `sha256` of the canonical serialization (§2.5) of `fields` + `context` +
  `notes`, excluding `meta`. It is the Tier B cache key component and the Tier A "did the input
  change since last run" check for incremental resume.

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
- `u` (unit) drives rendering — `usd`, `pct`, `pp`, `atr`, `x`, `rank`, `sessions`, `days`,
  `enum`, `text`, `ratio`, `int`. **The model never formats a number**; the renderer formats by
  unit, so `$184.20` and `2.1×` are consistent with the rest of the PWA for free. The unit table
  (id → formatter → plural rule) is part of the registry and lives in one place per runtime:
  `evidence_pack.UNITS` / `formatUnit()` in `docs/index.html`. `sessions` and `days` formatters own
  pluralisation (`1 session`, `6 sessions`) so templates never bake in a plural.
- `enum` fields carry a display string as well: `{ "v": "setting_up", "u": "enum", "l": "Status at
  10:05", "d": "Setting up" }`. The renderer shows `d`; the model reasons over `v`. `d` comes from
  the same label maps the PWA already uses for status chips, so the AI never invents a status name.
- `l` (label) is what the provenance drawer shows. Required — an unlabeled field can't be cited
  legibly.
- `v` may be `null` when the source is NaN/blank. A null field is still registered and citable, so
  the model can say "no earnings date on file"; the renderer shows `—` for a null slot. Builders
  add a `notes` entry whenever a field is null for a data-coverage reason (see §2.3).
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

**But a pattern found in `context` must still be citable, or breadth is pointless.** The whole
reason to feed broadly (#409) is that the model can find a relationship the builder did not
pre-compute. If validation rule 2 (every cite resolves in `fields`) were the only option, the model
would either cite nothing for such a statement — un-provenanced — or the prompt would push it back
to `fields` only, which is pre-chewing by another name. So:

- A citation may be a **block reference**: `"context:industries"` or a row reference
  `"context:industries#Semiconductors"` (block id + `#` + the row's key column value).
- The drawer renders a block cite as its `label` plus a row count ("All 144 industries · 2026-09-05
  deltas"), and a row cite as that single row, formatted. Never the whole block.
- Every `context` block therefore declares its `key` column: `{ "label": "...", "key": "name",
  "columns": [...], "rows": [...] }`. Row cites are validated against `key` values.
- **A `slots` value may never point into `context`.** Slots are numbers on screen; numbers on
  screen come from `fields`. If the model needs a context value in prose, the builder promotes it
  to a field in a follow-up PR — the forcing function stays.

Block `columns` are listed once and rows are positional arrays (not objects), which is roughly a
2× token saving over repeated keys across 115+144 rows and matters for the ≤10-min Morning budget.

### 2.3 `notes`

Builder-authored caveats the model should condition on but not repeat verbatim — e.g. "SPY row
missing for this date, RS columns are NaN", "fewer than 50 sessions of history, 50d deltas are NaN".
Prevents the model confidently narrating a NaN. Notes are also the trigger for a `low` confidence
(§3.3): a statement whose cites include a field a note flags as missing/short-history is thin by
construction.

### 2.4 A concrete Morning pack (the first surface — build against this, not the abstract shape)

Derived from the real `morning.csv` header (27 columns, `collect_morning.py:98-119`) and the status
enum in `pick_status.py:33-52`. `morning_card` for the `pre_close` session:

```json
{
  "meta": { "pack_version": "1.0.0", "surface": "morning_card", "subject": "NVDA",
            "as_of": "2026-09-04", "session": "pre_close",
            "generated_at": "2026-09-04T19:35:11Z", "pack_hash": "sha256:…" },
  "fields": {
    "row.ticker":          { "v": "NVDA", "u": "text", "l": "Ticker" },
    "row.group":           { "v": "Semiconductors", "u": "text", "l": "Industry group" },
    "row.list_category":   { "v": "leaders", "u": "enum", "l": "Pick bucket", "d": "Leaders" },
    "row.status":          { "v": "triggered", "u": "enum", "l": "Status at 15:30", "d": "Triggered" },
    "row.trigger":         { "v": 184.20, "u": "usd", "l": "Trigger" },
    "row.stop":            { "v": 176.50, "u": "usd", "l": "Planned stop" },
    "row.price":           { "v": 186.05, "u": "usd", "l": "Price at 15:30" },
    "row.open":            { "v": 183.10, "u": "usd", "l": "Open" },
    "row.high":            { "v": 187.40, "u": "usd", "l": "Session high" },
    "row.low":             { "v": 182.90, "u": "usd", "l": "Session low" },
    "row.change":          { "v": 1.62, "u": "pct", "l": "Change on day" },
    "row.atr":             { "v": 4.10, "u": "usd", "l": "ATR (14)" },
    "row.atr_from_lod":    { "v": 0.77, "u": "atr", "l": "ATR from low of day" },
    "row.rel_volume":      { "v": 2.10, "u": "x", "l": "Relative volume" },
    "row.rsi":             { "v": 61.3, "u": "ratio", "l": "RSI (14)" },
    "row.sma20_dist":      { "v": 3.4, "u": "pct", "l": "Distance to 20MA" },
    "row.sma50_dist":      { "v": 8.9, "u": "pct", "l": "Distance to 50MA" },
    "row.sma50_ext_atr":   { "v": 4.0, "u": "atr", "l": "ATR-extension from 50MA" },
    "row.pct_of_52w_high": { "v": -2.1, "u": "pct", "l": "From 52-week high" },
    "row.reclaim_ref":     { "v": null, "u": "enum", "l": "Reclaim reference", "d": null },
    "prior.status":        { "v": "setting_up", "u": "enum", "l": "Status at 10:05", "d": "Setting up" },
    "prior.price":         { "v": 183.40, "u": "usd", "l": "Price at 10:05" },
    "derived.stop_gap_pct":   { "v": 5.1, "u": "pct", "l": "Price to planned stop" },
    "derived.stop_gap_atr":   { "v": 2.3, "u": "atr", "l": "Price to planned stop (ATR)" },
    "derived.r_at_price":     { "v": 0.24, "u": "ratio", "l": "R already used vs plan" },
    "derived.status_changed": { "v": true, "u": "enum", "l": "Status changed since 10:05", "d": "Yes" },
    "group.rank_month":       { "v": 3, "u": "rank", "l": "Group 1-month rank" },
    "group.rank_month_delta_5d": { "v": 2, "u": "int", "l": "Group rank change, 5 sessions" },
    "group.rs_month":         { "v": 4.2, "u": "pp", "l": "Group RS vs S&P, 1 month" },
    "group.rs_new_high":      { "v": 1, "u": "enum", "l": "Group RS at 20-session high", "d": "Yes" }
  },
  "context": {
    "session_rows": { "label": "All Morning rows, pre-close 2026-09-04", "key": "ticker",
                      "columns": ["ticker","group","list_category","status","prior_status",
                                  "atr_from_lod","rel_volume","sma50_ext_atr"],
                      "rows": [["NVDA","Semiconductors","leaders","triggered","setting_up",0.77,2.1,4.0], "…"] },
    "prior_sessions": { "label": "This ticker's last 5 sessions (10:05 + 15:30)", "key": "date",
                        "columns": ["date","session","status","price","atr_from_lod"], "rows": ["…"] },
    "industries":  { "label": "All 144 industries · 2026-09-04 deltas", "key": "name",
                     "columns": ["name","rank_month","rank_month_delta_5d","rs_month","rs_score","momentum_score"],
                     "rows": ["…"] }
  },
  "notes": [ "days_to_earnings is not in the Morning scrape; earnings.* fields are absent from this pack." ]
}
```

Things this example settles for the implementer:

- `earnings.days_to` from the original draft is **not available** on Morning (the 27-column store
  has no earnings column). It exists on Picks (`picks_latest.csv`) and in D1 `ticker_quotes`.
  Do not fake it; the note tells the model why the catch can't mention earnings here.
- `sma20_dist` / `sma50_ext_atr` / `pct_of_52w_high` are pure single-row derivations from
  `Price`/`SMA20`/`SMA50`/`ATR`/`52W High` that the PWA already computes client-side (the
  `ATR_EXT_*` bands in `docs/CLAUDE.md` § PWA display thresholds are applied to exactly this
  ATR-extension value). The Python builder recomputes them with the **same formulas** —
  add a parity test against a fixture the PWA test also asserts, or the AI will say "4.0 ATR" next
  to a chip that says "3.9".

  > **Corrected 2026-09-06 during P0a implementation** — the bullet above was half wrong, and
  > getting it wrong silently produces numbers that disagree with the chip beside them:
  >
  > 1. **`sma20_dist` and `pct_of_52w_high` are not derived at all.** Finviz's `SMA20`, `SMA50`
  >    and `52W High` screener columns are already *percent-distance-from-live-price*, stored
  >    verbatim as strings (`"3.05%"`, `"-6.31%"` — see `collect_morning.py` `SETUP_COLUMNS`).
  >    The builder parses the `%` and that is the field. Only **`sma50_ext_atr` / `sma20_ext_atr`**
  >    are genuinely derived, via the PWA's reconstruction `ma$ = price / (1 + pct/100)` then
  >    `(price − ma$) / ATR` (`docs/index.html` `deriveRiskMetrics()`, ~line 4603).
  > 2. **There are two different ATRs in every Morning row and they disagree.** Lowercase `atr`
  >    is the status engine's quote-block scrape; capital `ATR` is the Finviz screener block.
  >    They differ on **224 of 234** rows carrying both. Each derivation must use the ATR from
  >    its own source: MA-extension uses capital `ATR` (parity with the PWA chip), while
  >    stop/trigger geometry (`stop_gap_atr`, `range_atr`) uses lowercase `atr` — the ATR the
  >    engine actually planned the stop with. Mixing them yields a plausible-looking wrong number.
  > 3. **Coverage cliff.** `RSI`/`Volatility`/`Rel Volume`/`52W High` exist only from
  >    **2026-09-01**, and `Price`/`SMA20`/`SMA50`/`ATR` only from **2026-09-03**. The builder
  >    *omits* these fields (rather than emitting them as null) when the block is absent, and
  >    adds a `notes` caveat: an omitted field means "never collected for this date", a `null`
  >    field means "collected and empty" — a distinction the model is prompted on.
  > 4. **`group` is null on exactly the watchlist rows** (225 of 2,408). Watch tickers are not
  >    screened picks and carry no industry group, so every `group.*` field is null for them and
  >    §3.3 forces those statements to `low` confidence. Expected, not a data bug.
- `derived.status_changed` is what selects the row into scope for the `pre_close` session (owner
  decision: actionable + changed only).

### 2.5 Canonical serialization (needed for hashing, caching, and prompt caching)

Both builders emit the pack with **sorted keys, UTF-8, no whitespace, floats rounded to 4 dp,
`null` for missing**. `pack_hash` is computed over that byte string. The prompt assembler places
`context` before `fields` so the shared bulk is a byte-identical prefix across every pack in a
run — that is what makes Vertex prompt caching bite across ~40 per-card calls.

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

- `slots` — every `{name}` in `text` must appear here, and every value must be a valid `field_id`
  (never a `context:` reference — §2.2).
- `cites` — a superset of the slot fields: what it *reasoned from*, including fields it didn't
  quote, plus any `context:` block/row references. Drives the provenance drawer.
- `confidence` — `high` / `medium` / `low`, per the rubric in §3.3.
- `kind` — from the per-surface set in §2.0, so the renderer places it. Unknown kinds are dropped.
- `subjects` — optional, triage packs only (§2.0).
- The response also carries `"contract_version": "1.0.0"` at the top level so a renderer can
  refuse output written against a contract it doesn't understand.

Per-surface caps, enforced by the validator not the prompt: `morning_card` = 1 `read` + 1 `catch`;
`morning_triage` ≤ 5 statements; `picks_card` = 1 `thesis` + 1 `catch`. Extra statements are
dropped, first-wins.

### 3.1 Validation (the whole gate, and it is now cheap)

1. Every `{slot}` in `text` has an entry in `slots`, and every `slots` key is used in `text`.
2. Every `slots` value resolves in `fields`; every `cites` entry resolves in `fields` or is a valid
   `context:` block/row reference (§2.2).
3. `text` contains **no bare digits** outside `{slots}` — *after* stripping a fixed lexicon of
   digit-bearing vocabulary the app already uses: `20MA`, `50MA`, `200MA`, `52W`, `RSI`, `10:05`,
   `15:30`, `S&P 500`. The lexicon is a registry entry (`pack_schema.json` → `digit_lexicon`),
   shared by both runtimes, and adding to it is a registry change like any field. Without this,
   "reclaimed the 20MA" fails the rule and the most useful sentences get suppressed.
4. A `catch` statement exists and is non-empty (the mandatory counter-evidence rule), for every
   surface whose kind set includes `catch`.

All four are mechanical. **No numeric-comparison heuristics, no fuzzy matching** — which is exactly
the brittleness the owner flagged in the earlier blocking-gate proposal. A failure here is a bug in
our prompt, not a judgement call about a model's arithmetic, so failing closed is safe.

### 3.2 What happens on failure (fail closed, but not silently)

- **Retry once** with the validator's error list appended to the prompt ("statement 2 cites
  `row.earnings_days` which is not in the pack; the pack has these fields: …"). This is cheap and
  is the standard fix for structured-output slips. No second retry.
- On second failure the **statement** is dropped, not the whole card, *unless* the dropped
  statement is the mandatory `catch` — then the card is dropped (a thesis with no catch is exactly
  the one-sided output §3.0 forbids).
- Every drop is recorded in the run's Tier-2 capture (`status: "rejected"`, `rule`, `raw`) and
  counted in `data/ai/index.json` per date as `rejected_statements` / `rejected_cards`, so
  `eval_ai.py` can trend it and a rising rate is visible without reading logs.
- **Rendering a dropped card:** the surface falls back to what it shows today (`_mNote()` on
  Morning; nothing on Picks). The user never sees an "AI failed" state — silence convention.
- **Spike outcome (`AI-NEXT-P0c`) — which of three designs, never whether to ship.** Over ≥50 real
  `morning_card` packs against `gemini-3.5-flash` with `response_schema` set, the measured
  drop-rate-after-retry selects the renderer design: **≤5%** → slot filling, batched calls;
  **5–15%** → slot filling, per-row calls only (slower, same product); **>15%** → the
  renderer-owned-templates design in the proposal §2, where the model returns `kind` + `cites`
  only and the renderer owns the sentence wording. All three ship an AI-selected, fully-cited
  read on the card; the third merely moves phrasing from the model to the app, which is strictly
  the *safer* product. Record the measured rate in the spike's knowledge note.

  > **Wording fixed 2026-09-06.** This bullet previously read "go/no-go", which wrongly implied
  > the spike could cancel the workstream. It cannot — there is no no-go branch. Renamed here and
  > in the SPRINT row so the next reader does not misread the risk.

  > **Corpus decision (owner, 2026-09-06).** Because the Finviz setup block only starts
  > 2026-09-03 (see §2.4), the spike runs on the **full history back to 2026-08-10** and reports
  > the drop rate **split into two cohorts**: full-field rows (2026-09-03 onward, the
  > production-shaped pack — this is the cohort the thresholds above are read against) and
  > thin-field rows (before, where the setup block is absent). The thin cohort separately
  > measures whether the model misbehaves around omitted fields, which is real information the
  > full-field cohort alone cannot give. Rejected: waiting ~2 weeks for depth (no reason to
  > block), and running on the 234 full-field rows alone (2 trading days is too narrow a sample
  > for a threshold decision, and it tests nothing about null handling).

### 3.3 Confidence — rubric and rendering

`confidence` is **not** the model's feeling. It is set by the model against a mechanical rubric
stated in the prompt, and the validator downgrades it when the rubric is provably violated:

- `low` if the statement's `cites` include any field with `v: null`, or any field named in a
  `notes` caveat, or fewer than 2 distinct fields.
- `medium` if it rests on 2–3 fields with none flagged.
- `high` otherwise.

The validator can check the first two bullets mechanically and forces `low` when either applies,
whatever the model said. It also attaches a `thin` list naming *why* it downgraded, so the marker's
tooltip is built from fact rather than from the model's self-report.

**Rendering — decided 2026-09-06 (owner): all three states render.** Staff had recommended the
`low`-only variant on the app's "no badge = no signal" convention; the owner chose full visibility
instead. `high` / `medium` / `low` each get a marker on the statement, and `low`'s tooltip lists
the flagged fields from `thin`. P0b builds it this way — the decision is baked in, not retrofitted.
All three remain logged in Tier-2 so calibration can be checked once ticker-level outcomes exist
(#404).

> Staff note, recorded rather than argued: three visible markers add chrome to an already-dense
> card, and a `medium` badge on most statements risks reading as noise the eye learns to skip. If
> that happens in real use, dropping to `low`-only is a pure render change — the contract carries
> all three states either way, so nothing downstream needs to move.

---

## 4. Versioning

`meta.pack_version` is semver. **Minor** = fields added (a renderer built on 1.0 keeps working).
**Major** = a field removed or its `u`/meaning changed, which can silently corrupt a cached
statement's rendering — so cached Tier B statements are invalidated on major bump.

Field ids are an API the model is prompted against. Renaming one is a breaking change; prefer
adding and deprecating.

---

## 5. Where it lives

- `scripts/evidence_pack.py` — builders + the field registry + the validator (Tier A, and the
  source of truth). Pure functions over DataFrames/dicts; no I/O, no API, so every rule is
  unit-testable with `io.StringIO` fixtures per `branch-commit-discipline.md`.
- `scripts/generate_ai.py` — new `TASK_SPECS` entries take a pack instead of `serialize_*()`
  output; existing entries untouched until #409.
- `worker-positions/src/evidencePack.js` — Tier B builder + the same validator (P4).
- `docs/index.html` — `renderStatements(statements, pack)` (slot fill + `formatUnit()`), the
  cited-subset "Behind this" drawer, and the `low`-confidence marker. Built once in P0, reused by
  every surface.
- **`data/ai/pack_schema.json`** — the shared registry: `fields` (id → unit → label, per surface),
  `units`, `digit_lexicon`, `kinds` per surface, `contract_version`. Generated from the Python
  registry by `python scripts/evidence_pack.py --emit-schema` and committed; a test asserts the
  committed file equals the generated one (same anti-drift pattern as
  `delta_config.delta_columns()` and `display_methodology.json`). The JS builder and the PWA
  renderer import it. **Registry drift is a hard build error (owner decision, §6).**
- **Output files** (Tier A): `data/ai/morning/YYYY-MM-DD.{morning,pre_close}.json` holding
  `{meta, cards: {ticker: {pack_hash, statements}}, triage: {statements}}`, plus the packs
  themselves in `data/ai/provenance/morning/…` (Tier 1) — the pack *is* the provenance record, so
  the drawer needs no second file. Tier 2 debug capture unchanged (ADR-006).
- **Service worker:** `sw.js` is cache-first and only bypasses the cache for
  `raw.githubusercontent.com` (`docs/sw.js:70-73`). The existing AI JSON is fetched through
  `BASE` = `https://raw.githubusercontent.com/${REPO}/${BRANCH}/data` (`docs/index.html:429`),
  so it is always network-fresh. The new files must go through `BASE` too — a relative
  `docs/`-path fetch would serve the 10:05 prose at 15:30. Verify in P2's Playwright test.

### 5.1 Parity between the two builders

The registry stops the two runtimes disagreeing about *ids*; it does not stop them disagreeing
about *values*. P4 adds a golden-fixture test: `tests/fixtures/evidence_pack/<case>/input.json` →
both builders → byte-equal canonical output, asserted from both pytest and vitest. Any derived
field formula (`derived.stop_gap_pct`, `row.sma50_ext_atr`) must be written once per runtime and
covered by that fixture.

No ground-truth CSV changes. Per `.claude/rules/data-pipeline.md`, nothing here becomes a column on
`picks.csv` or the session stores.

---

## 6. Owner decisions (2026-09-06 — locked)

1. **Registry enforcement → hard build error.** A field id absent from `pack_schema.json` fails
   the build and the test suite. Every new field touches the registry in the same PR.
2. **`context` budget → no cap for Tier A batch; soft cap on Tier B** with oldest-first truncation
   and a `notes` entry saying what was dropped. Cap value is a documented constant in
   `evidencePack.js` (three-places rule), initial value to be set in P4 from measured latency.
3. **`confidence` → render all three states.** ✅ **Closed 2026-09-06.** Owner chose full
   visibility over the staff-recommended `low`-only variant; `high`/`medium`/`low` each render a
   marker, `low`'s tooltip lists the validator's `thin` reasons. See §3.3.
4. **P0c corpus → mixed, cohort-split.** ✅ **Decided 2026-09-06**, forced by the setup-column
   coverage cliff found during P0a implementation. Full history, drop rate reported separately
   for full-field and thin-field rows. See §3.2.

## 7. Not in scope here

Prompt text and any surface-specific UI beyond the shared renderer. This pass defines the contract;
`AI-NEXT-P0a` builds the Tier A builder + registry + validator against it, `P0b` the shared
renderer, `P0c` the structured-output spike.

## 8. Test plan (the P0 PR is not done without these)

| Area | Test | File |
|---|---|---|
| Registry | committed `pack_schema.json` == generated; every builder-emitted id is registered; hard error on unknown id | `tests/test_evidence_pack.py` |
| Builder | `morning_card` from a 3-row `StringIO` morning + pre_close fixture: field set, derived formulas, `status_changed`, null handling, `notes` on missing SPY / short history | same |
| Builder | `morning_triage` aggregates match a hand-computed fixture | same |
| Canonical | same input → identical bytes and `pack_hash` across two calls; float rounding | same |
| Validator | one test per rule (4), plus: lexicon strips `20MA`; `slots` into `context:` rejected; unknown `kind` dropped; per-surface caps; `catch` missing → card dropped; retry-once wiring with a fake client | same |
| Confidence | null-cited field forces `low` regardless of model value | same |
| Renderer | `renderStatements()` fills slots by unit (`usd`, `pct`, `atr`, `x`, `sessions` plural), shows `d` for enums, `—` for null; drawer renders only cited fields + block labels, never full context; `low` marker present/absent | `tests/test_pwa_ai_statements.py` (Playwright — **add to the `tests.yml` ignore list in the same PR**) |
| Capture | rejected statements land in Tier 2 and `index.json` counters | `tests/test_generate_ai.py` |

## 9. Staff review log (2026-09-06)

- **§2.0 granularity added.** The draft's single-row example left "how does triage cite across 115
  rows" undefined; this is the first thing an implementer hits on Morning.
- **§2.2 context citation added.** Rule 2 as written made every insight from broad context
  un-provenanced, which quietly defeated the point of feeding broadly.
- **§2.4 concrete Morning example** from the real store header; found `earnings.days_to` is not
  available on Morning, and that three derived fields must match PWA client-side formulas.
- **§3.1 rule 3 digit lexicon.** Literal "no bare digits" rejects `20MA`, `52W`, `10:05`.
- **§3.2 failure behavior + spike go/no-go**, tied to the repo's prior failed JSON-mode attempt
  (`ai-tab-daily-note.md`).
- **§3.3 confidence rubric** so the value is derived, not felt; **§5 output/SW placement**;
  **§5.1 builder parity**; **§8 test plan**; **§6 questions → decisions**.
