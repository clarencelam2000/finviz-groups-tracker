# AI-NEXT-P0c — structured-output spike: can `gemini-3.5-flash` hold the pack contract?

**Status:** ✅ **Run complete, 2026-09-06.** Result: **renderer-owned templates** (see §4). The
raw harness numbers say 90% dropped / 3.3% first-try; the true first-try count is **0/60, not
2/60** — see §4's correction, which also names a real validator bug this run surfaced and fixed
in the same PR.

**Task:** `.session/SPRINT.md` → `AI-NEXT-P0c` · **AC:** `planning/ai-next-user-stories.md` → US-P0c
**Contract under test:** `planning/ai-evidence-pack-schema.md` §3 (model output) and §3.1 (the four
validation rules) · **Harness:** `scripts/spike_structured_output.py` (shipped with P0a)

---

## 1. What this spike decides — and what it cannot

It selects **which of three renderer designs** we build. It has no cancel branch.

| Drop rate after retry-once (`full` cohort) | Design selected |
|---|---|
| ≤ 5% | Slot filling, **batched** calls — cheapest and fastest |
| 5–15% | Slot filling, **per-row** calls only — slower, identical product |
| > 15% | **Renderer-owned templates** — the model returns `kind` + `cites` only, and the app owns the sentence wording |

All three ship an AI-selected, fully-cited read on the Morning card. The third merely moves
phrasing from the model to the app, which is the *safer* product — less fluent, not less useful.

> This framing is a correction. The schema originally called it a "go/no-go", which reads as
> though a bad result kills the workstream. It does not, and the wording was fixed in schema §3.2
> and the SPRINT row on 2026-09-06 so nobody re-reads that risk into it.

**Why a spike at all:** this repo already tried forced-JSON mode once and backed it out
(`knowledge/.../ai-tab-daily-note.md`). Building a renderer on an unmeasured assumption that the
model holds a stricter contract than that one would repeat the mistake.

## 2. Corpus (US-P0c AC1)

Built by `_load_corpus()` from real `data/picks/sessions/{morning,pre_close}.csv` history.

- **Scope filter matches production** (US-P2a AC2): a row is sampled only if its status is
  actionable (`triggered` / `gapped_through` / `reclaim`) **or** its status changed vs the prior
  read. Measuring the drop rate on `setting_up` rows production never sends would flatter it.
- **Prior-row pairing matches production**: a `morning` row's prior is the *previous day's*
  `pre_close`; a `pre_close` row's prior is the *same day's* `morning`.
- **Deterministic** — `--seed` fixes the sample so a re-run measures the same corpus.
- **Shared `context` is included** (all rows for the latest sampled date + all 144 industries),
  because a spike run without it would measure a materially smaller prompt than production sends.

Verified with `--dry-run` on 2026-09-06 (no API spend):

```
corpus: 60 packs  cohorts={'full': 30, 'thin': 30}
statuses={triggered: 13, gapped_through: 13, reclaim: 12, failed_breakout: 9,
          invalidated: 7, setting_up: 6}
status_changed=37
shared prefix: 20,964 bytes (byte-identical across packs) · per-row tail: ~2,872 bytes
```

That clears US-P0c AC1 on every count: ≥50 packs (60), all actionable statuses present, and ≥10
status-changed rows (37).

### 2a. The cohort split, and why it exists

The Finviz setup block was only added to the session stores partway through the history:

| Columns | First date | Rows |
|---|---|---|
| `RSI`, `Volatility W/M`, `Rel Volume`, `52W High` | 2026-09-01 | 478 |
| `Price`, `SMA20`, `SMA50`, `ATR` | 2026-09-03 | 234 |
| everything else | 2026-08-10 | 2,408 |

So packs come in two shapes, and one blended rate would hide that:

- **`full`** — carries the setup block. This is the production-shaped pack, and **the cohort the
  thresholds in §1 are read against.**
- **`thin`** — setup block absent, those fields omitted from the pack with a `notes` caveat.
  Measures whether the model misbehaves around omitted fields (invents them, cites ids that
  aren't there) — real information the full cohort cannot give.

Owner decision, 2026-09-06. Rejected alternatives: waiting ~2 weeks for depth (no reason to block
the workstream), and running on the 234 full-field rows alone (2 trading days is too narrow a
sample to hang a threshold on, and it tests nothing about null handling).

### 2b. Known limitation — state it, don't bury it

The sampled rows span many dates, but the shared `context` block is built from a single date. So
the spike is a valid test of **contract adherence** (do slots resolve, do cites stay in the pack,
does the model keep digits out of `text`) and **not** a test of reasoning quality — for most rows
the broad context is not that row's own session. Do not quote this spike as evidence the prose is
*good*, only that it is *well-formed*. Judging quality needs the owner reading real output on the
Morning tab, which is P2b.

## 3. How to run it

Cannot run from a Claude Code cloud session (no Vertex creds; see `CLAUDE.md`). Locally or in
GitHub Actions, same auth ladder as `generate_ai.py`:

```bash
# Vertex express key (preferred)
GOOGLE_GENAI_USE_VERTEXAI=true GOOGLE_API_KEY=... \
    python3 scripts/spike_structured_output.py --limit 60

# or AI Studio
GEMINI_API_KEY=... python3 scripts/spike_structured_output.py --limit 60

# corpus/prompt inspection only, no API calls — this part DOES run anywhere
python3 scripts/spike_structured_output.py --dry-run --limit 60
```

Roughly 60–120 calls (retry-once on failures). It writes
`knowledge/investigations/ai-next-structured-output-spike.json` with per-call detail plus a
summary, and prints a markdown table ready to paste into §4 below.

`DailyQuotaExhaustedError` propagates rather than being swallowed — a truncated run must not be
mistaken for a measured result.

---

## 4. Results

Run 2026-09-06, `gemini-3.5-flash`, backend `vertex_express`, seed default, 60 packs. Raw
harness output (`knowledge/investigations/ai-next-structured-output-spike.json`):

| Cohort | n | validated 1st try | validated after retry | **dropped** | median latency |
|---|---|---|---|---|---|
| full (2026-09-03+) | 30 | 3.3% | 0 | 90.0% | 130.3s |
| thin (setup block absent) | 30 | 3.3% | 0 | 90.0% | 153.6s |
| **all** | 60 | 3.3% | 0 | 90.0% | 141.4s |

4 rows also hit an outright API error (both calls failed with an exception, not a validation
rejection) — `RBRK`, `ZM`, `SYRE`, `NVT`. Not investigated further; small n, didn't change the
cohort-level percentages meaningfully.

**Rejections by rule:** `rule1_slot_undeclared` × 53, `rule2_cite_unresolved` × 1 — i.e.
essentially every rejection is the *same* rule, which per this doc's own §4 note ("a
concentration in one rule is usually a prompt fix, not a model limit") was worth digging into
before taking the 90% number at face value. That dig found something worse than a prompt fix.

### 4.0 Correction — the true first-try count is 0/60, not 2/60, and the validator had a real gap

The two "first-try" successes (`RDNT`, `DHR`) were re-inspected against their raw model output
before this doc was finalized. Both wrote the field id **directly into `text`** as the
placeholder — e.g. `"...shift to an {row.status} status..."` — with `slots: {}` (empty), exactly
the same failure every dropped row made. They were not, in fact, well-formed.

**Root cause: `_SLOT_RE` (`scripts/evidence_pack.py`) only matched letters/digits/underscore —
`\{([A-Za-z_][A-Za-z0-9_]*)\}` — so a dot in the placeholder made it invisible to the regex
entirely.** `{row.status}` doesn't match that pattern (the `.` isn't in the character class), so
Rule 1's "does every `{placeholder}` have a matching `slots` entry" check found **zero**
placeholders in the text and had nothing to compare against `slots` — an empty set minus an
empty set is empty, so it passed clean. Rule 3 (no bare digit outside a slot) is the only other
check that could have caught it, and only by accident: it only fires if the un-recognized
placeholder's own text happens to contain a digit (e.g. `sma20_dist` would trip it; `status`
would not). `row.status`, `derived.price_change_since_prior`, `row.atr_from_lod`,
`row.reclaim_ref_value`, `row.reclaim_ref`, and `row.rel_volume` — every field name the model
used this way in this run — contain no digit, so nothing caught it. **Both "passing" statements
would have rendered the literal, unsubstituted string `"{row.status}"` to a real user on the
Morning card.** That is a worse failure than the 54 the validator did catch, since those at
least got correctly discarded.

**Fixed in the same PR as this doc's update:** `_SLOT_RE` now also matches dotted identifiers
(`\{([A-Za-z_][A-Za-z0-9_.]*)\}`), so a field id written directly into `text` is recognized as a
placeholder and correctly rejected under `rule1_slot_undeclared` for having no `slots` entry
(verified: re-running `validate()` against `RDNT`'s and `DHR`'s exact raw output post-fix now
rejects both). Regression test:
`tests/test_evidence_pack.py::test_rule1_catches_dotted_field_id_used_directly_as_placeholder`.

**Corrected headline: 0/60 clean passes.** Every single response the model returned in this run
used `slots: {}` — confirmed by inspecting all 60 raw responses, not just the 2 that superficially
looked clean. The model consistently reasons correctly (its `cites` arrays are real, valid field
ids every time) and consistently fails to also populate the separate `slots` mapping the schema
requires. `RESPONSE_SCHEMA` declares `slots` as `{"type": "object"}` with no `minProperties` or
other structural constraint — an empty object satisfies the JSON *shape* the schema enforces, so
Gemini's constrained decoding has no structural pressure to fill it in; only the prose system
prompt asks for it, and prose instructions lose to schema-shape pressure under
`response_schema`-constrained generation. This reads as a fixable schema/prompt design gap, not
proof the model cannot hold the contract at all — worth a cheap, small (~10-20 call) follow-up
after a schema change (e.g. `slots` as a list of `{name, field}` pairs — the same array shape as
`cites`, which the model *did* get right every time — or `minProperties: 1`) before concluding
this design is a dead end. Not run yet; needs owner sign-off given the API spend already used a
chunk of the available Google API credit.

**Selected renderer design, as measured (read against the `full` cohort, corrected count):**
**renderer-owned templates** — 0% clean first-try validated is far past the >15% cutoff either
way, corrected or not. This part of the conclusion does not change: don't let the model write
free sentences yet. What changes is *why* — not "the model can't do this," but "the model didn't
get pressured hard enough by our schema to do the one extra bookkeeping step this design needs,"
which is a narrower, more specific, and more fixable claim.

### 4a. Batching (US-P0c AC3)

Per-row vs 5-row vs 10-row calls, to set P2's ≤10-min budget from data rather than guesswork.

| Mode | calls for a 40-row session | drop rate | wall clock |
|---|---|---|---|
| per-row | 40 | — | — |
| batch-5 | 8 | — | — |
| batch-10 | 4 | — | — |

> **Not yet implemented in the harness.** The current script measures per-row only. Batching is a
> small addition to `run()` (group N packs into one call, one `statements` array per subject) and
> should be written *after* the per-row numbers land — if per-row already clears the 10-minute
> budget, batching is an optimisation nobody needs to build. Tracked as **AI-NEXT-P0c-BATCH** in
> `.session/SPRINT.md`.

### 4b. Projected wall clock for a 40-row session (US-P0c AC4)

Measured median latency was 141.4s per pack (nearly every pack made both the first call and the
one allowed retry, since almost nothing validated first-try) with a p90 of 288.8s — both far
above what a "flash" model is expected to take; this smells like the SDK silently retrying on
rate limits under the hood rather than genuine model think-time, but wasn't root-caused this
session. Run serially, 40 rows × ~141s median ≈ **94 minutes** — well past the "≤10-min budget"
this AC exists to check against. **This alone, independent of the drop-rate finding, means the
morning-triage feature cannot call this API once per row in a simple loop** — it needs either
batching (§4a, not yet built) or parallel/concurrent calls, or both, before it can run inside a
10-minute window. Flagging this as a separate, real constraint the eventual `AI-NEXT-P2a`
implementation must solve, not something the >15%-drop-rate finding already covers.

## 5. Three example outputs (US-P0c AC4)

**Retried (failed once, passed on retry):** none — `after_retry` was 0/60 across both cohorts.
Not one pack recovered on the one allowed retry, even with the exact validation errors handed
back to the model. Worth noting on its own: the retry-once mechanism bought nothing in this run.

**"Good" before the §4.0 correction, actually dropped once re-checked (`RDNT`, full cohort):**
```json
{"kind": "read",
 "text": "The shift to an {row.status} status after a {derived.price_change_since_prior} drop means the previous breakout attempt has officially failed.",
 "slots": {}, "cites": ["row.status", "derived.price_change_since_prior", "prior.status"],
 "confidence": "high"}
```
Would have rendered as the literal text above, `{row.status}` and all, to a real user.

**Dropped (typical — short custom placeholder name, `slots` still empty; `NTRA`, full cohort):**
```json
{"kind": "read",
 "text": "The stock's status has shifted from {prior_status} to {status}, indicating that the recent breakout attempt has failed to hold.",
 "slots": {}, "cites": ["prior.status", "row.status", "derived.status_changed"],
 "confidence": "high"}
```
Correctly caught by `rule1_slot_undeclared` even before the fix, since `prior_status`/`status`
have no dot in them and matched `_SLOT_RE` already. This is the more common of the two shapes the
model produced, but both shapes share the same underlying miss: `slots` never gets filled in
either way.

## 6. Decision

**Renderer-owned templates.** The model returns `kind` + `cites` only (which it produces
correctly and consistently); the app owns the sentence wording via pre-written templates keyed
by status/situation. This holds whether you read the raw 90%-dropped number or the corrected
0%-clean-first-try number — both are far past the >15% cutoff.

**Do not read this as "gemini-3.5-flash can't do structured output."** The specific, narrow thing
it failed at was populating a second, schema-unenforced `slots` object that's semantically
redundant with the `cites` array it *did* get right every time. That looks like a fixable
prompt/schema design issue (§4.0), not a hard capability wall — but re-testing that fix costs
another real, if smaller, API run, so it's raised here as an option for the owner to weigh, not
executed unilaterally given the API spend already used a chunk of the available credit for this
run alone.

**Also decided here, independent of the drop rate:** the ~90–290 second per-call latency this run
measured means a naive serial per-row loop cannot fit the ≤10-minute morning-triage budget for a
40-row session (§4b) — `AI-NEXT-P2a` will need batching, concurrency, or both regardless of which
renderer design ships.

## 7. Follow-through

- [x] Outcome written into the `AI-NEXT-P0c` SPRINT row (2026-09-06).
- [x] Validator bug found by this run (`_SLOT_RE` missed dotted field ids used as placeholders)
      fixed in `scripts/evidence_pack.py` in the same PR as this doc update, with a regression
      test (`tests/test_evidence_pack.py::test_rule1_catches_dotted_field_id_used_directly_as_placeholder`).
- [ ] Amend `planning/ai-evidence-pack-schema.md` §3 (US-P0c AC5) — the contract's `text`/`slots`
      fields become renderer-owned; the schema doc must say so. **Not done in this PR** — planning
      doc changes should get their own review pass, not ride along with an ops/bugfix PR.
- [ ] Owner decision needed: is a small follow-up run (~10-20 calls) worth trying against a fixed
      `slots` schema (§4.0) before committing to renderer-owned templates for good? The design
      decision doesn't have to wait on this — renderer-owned templates is correct either way — but
      it affects whether a future upgrade path to model-authored prose is realistic.
- [ ] Unblocks `AI-NEXT-P0b` (shared renderer) and `AI-NEXT-P2a` (Morning pipeline) — both can now
      proceed on the renderer-owned-templates design.
