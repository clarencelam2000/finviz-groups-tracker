# AI/LLM integration across Picks, Morning, Positions — and at top level

**Status:** Design gate **passed** — owner decisions locked (§6). No code shipped. Ready for pickup:
start at `AI-NEXT-P0` in `.session/SPRINT.md`; user stories and acceptance criteria are in
`planning/ai-next-user-stories.md`.
**Date:** 2026-09-05 · staff review pass 2026-09-06 (see §8)
**Author:** staff-eng/product review, session `ai-llm-new-tabs-integration`
**Related:** ADR-006 (AI call capture) · ADR-012 §11 / `planning/trade-lifecycle-engine.md` §14
(extensibility door: per-position rules + a future LLM layer) · ADR-007 (picks selector) ·
`planning/ai-tab-daily-note.md` (the current freeform-note architecture)

---

## 0. Where the AI layer actually stands today

Verified by reading the code, not the docs:

- **`generate_ai.py` sees exactly two things:** `data/{sectors,industries}/snapshots.csv` and
  `.../deltas.csv`. Grep confirms **zero** references to picks, morning/session stores,
  positions, watchlist, or any ticker-level data. (`generate_ai.py:98-122`)
- **6 task types × 2 group types = 11 Gemini calls per run**, ~2 min wall clock,
  `gemini-3.5-flash` on Vertex, 2 cascaded runs/day off `collect.yml` (pre-close + EOD; `generate_ai.yml` follows "Daily Snapshot" only).
  (`TASK_SPECS`, `generate_ai.py:991-1056`; confirmed against `data/ai_run_log.jsonl`)
- **The prompt discipline is already good.** The model never sees raw CSVs — pure
  `serialize_*()` functions pre-compute breadth, divergence, rotation and RS blocks in pandas
  and hand the model a narrated evidence block with "Use ONLY the data below."
  (`generate_ai.py:209-624`) This is the single most reusable asset in the AI layer.
- **Two-tier capture + the "ⓘ Behind this" drawer** (ADR-006) is, product-wise, the best trust
  feature in the app. Every AI card can already show the exact input block it was given.
- **Everything the AI produces is broadcast:** identical for every viewer, committed to git as
  a static JSON, served free and offline by the service worker.

**The gap, stated plainly:** the AI layer is a market-commentary generator bolted to the side of
what has since become a personal trading system. It does not know what you own, what you are
watching, what triggered this morning, or what you did about it. It is also — by some distance —
the least differentiated surface in the app. Rotation commentary is a commodity; every newsletter
has one.

### What is *not* a commodity

Three assets have accumulated since the AI tab was built, and no competitor (Finviz included) has
the combination:

1. **Frozen causal attribution.** Every pick row carries 19 `grp_*` columns — the selecting
   group's `deltas.csv` metrics *at selection time* (`picks_config.py:196-216`). The reason a name
   was chosen is preserved, not re-derived later.
2. **A decision log, not a price log.** `data/picks/sessions/morning.csv` — 2,408 rows over 20
   sessions and growing — records, per ticker per session, what the plan said (trigger, stop) and
   what the market did to it (`triggered` / `gapped_through` / `reclaim` / `failed_breakout` /
   `invalidated` / `setting_up`), at both 10:05 and 15:30 ET.
3. **A typed, append-only trade ledger.** `position_events` per trade: `entered`, `stop_moved`,
   `caution`, `partial_exit`, `exit_signal`, `closed`, with typed payloads — plus `ticker_quotes`
   holding real daily OHLC **and** the full 84-column Finviz scrape per bar.

Joined on one trader's actual behaviour, (1)+(2)+(3) is the substrate. That is where the LLM
belongs — not in a fourth paragraph about sector rotation.

### The measurement question (corrected 2026-09-05 after owner review)

An earlier draft of this section asserted the picks selector is "negative at every horizon" and
hung the product posture on it. **That was overstated.** Full audit:
`knowledge/investigations/picks-alpha-2026-09-05-significance-audit.md`. The corrected version:

**What `evaluate_picks.py` measures** (`compute_scores`, `:112-175`): buy the whole *industry
group index* at the pick-day close, hold 1/3/5/10 sessions, **no entry condition and no stop**.
It is a test of the group selector as a standalone index strategy. It does not measure the stock
picks, the Morning trigger/stop logic, or the position engine.

Three corrections to the raw `--report` table:

1. **`excess_spy` is contaminated.** Over the sample, SPY returned +3.93% and the median tracked
   industry +1.48% — cap-weighted mega-cap leadership. Much of `excess_spy` is that weighting
   difference, not selector skill. `excess_median` / `excess_nonsel` are the fair controls and are
   about half as negative.
2. **There is no significance test, and forward windows overlap.** 39 h=10 dates over 62 sessions
   is ~6 *independent* windows. Under a moving-block bootstrap (block = horizon) vs the median
   control, three of four horizons **straddle zero**: h=1 −0.15% [−0.38,+0.08], h=3 −0.40%
   [−0.90,+0.04], h=5 −0.59% [−1.21,+0.20], h=10 −0.71% [−1.90,+0.22].
3. **It flips sign within the sample.** First half −1.25% at h=10, second half +0.16%.

**What survives:** the opposite gradient between buckets — `leaders` monotonically worse with
horizon (−0.28 → −1.00 → −1.58 vs median at h=1/5/10, CI excluding zero at h=10) and `emerging`
monotonically better (−0.03 → +0.50 → +1.48). `leaders` holds 13 of ≤27 daily slots. That is a
**selector-tuning question for ADR-007, not an AI question**, and it is not yet actionable — one
regime, ~6 independent windows, no out-of-sample period.

**What this explicitly does not say:** it is not a short signal, and it does not say the system
doesn't work. The part that does the work — trigger, stop, trailing management — is unmeasured.
The honest statement is **"we do not yet know whether the traded system has an edge,"** not "it
doesn't."

**The consequence for this proposal** is therefore weaker than the earlier draft claimed, and
narrower: an AI layer should not assert conviction the underlying measurement cannot support, and
several proposed features (the honesty chip, the weekly review) *depend on* a ticker-level
instrument that does not exist yet. See §5 — PICKS-4B is now a sequencing input, not a side note.

## 1. Three jobs, ranked by defensibility

| | Job | What it is | Value | Risk | Verdict |
|---|---|---|---|---|---|
| **J1** | **Narrate** | Turn numbers into prose (today's AI tab) | Low — commodity | Highest (hallucination, false confidence) | Keep, stop investing |
| **J2** | **Synthesize & prioritize** | Fuse rotation + today's picks + your watchlist + your positions into one ranked "next 30 minutes" list | High | Medium | **Build — this is the top-level feature** |
| **J3** | **Critique & coach against your own record** | "Your last four `leaders` entries above 2.5 ATR-ext all stopped inside 3 sessions; this one is 2.9" | Highest — no competitor can | Low (retrospective, fully grounded) | **Build — this is the moat** |

J2 is only possible for us because only we hold all four inputs. J3 is only possible because we
kept (1), (2) and (3) above. Both are strictly downstream of data the app already writes to disk
every day.

---

## 2. Architecture: the public/private fork

This is the one decision that constrains everything else.

**Tier A — batch / public / free.** Groups, Picks, and Morning are committed CSVs, identical for
every viewer. Generate in GitHub Actions → commit a JSON artifact → the PWA fetches a static file.
Zero new infra, zero runtime cost, offline-capable through the existing service worker, and it
reuses `generate_ai.py` end-to-end. **Everything on the Picks and Morning tabs can be Tier A.**

**Tier B — on-demand / private / authenticated.** Positions and watchlist *levels* live in D1 behind
bearer auth. They can never be committed to git — not "shouldn't", *can't*. So Tier B requires an
LLM call originating **inside `worker-positions`**, authenticated as the owner, with the response
cached in D1 keyed by `(user_id, trade_date, surface, pack_version, pack_hash)` and never written
to the repo. (`pack_version` in the key is what makes the schema doc's "major bump invalidates
cached statements" rule automatic rather than a migration.)

> **Boundary nuance, verified 2026-09-06:** watchlist *tickers* are already public. The Morning
> scrape pulls them from `GET /watchlist-tickers` and writes them into the committed
> `data/picks/sessions/morning.csv` with `list_category = "watchlist"` (14 of 114 rows on
> 2026-09-04; `collect_morning.py:286-320`). Only the *level* (`level_value`) is withheld. So the
> Morning per-card read (P2) covers watchlist rows as Tier A for free; the "your 'above 322' level
> is still 4% away" recall in §3.5 is the part that needs Tier B.

Concretely, Tier B is small: one authenticated route (`POST /ai/ask`), one cache table, one secret,
one grounding gate. It is new infra but not much of it — and `worker-positions` already has the
auth seam (`src/auth.js`), the dual-auth pattern, and a migrations discipline.

### The shared seam: the evidence pack

Both tiers build a **typed evidence pack** — a deterministic, serialized bundle of pre-computed
facts — and the model is instructed to use nothing else. This generalizes the `serialize_*()`
pattern that already works (`generate_ai.py:209-624`) into a first-class, versioned object with a
schema, so:

- the Python (Tier A) and JS (Tier B) builders produce structurally identical packs;
- **every sentence the model emits is traceable to a line in its pack** — which makes the existing
  "ⓘ Behind this" provenance drawer work unchanged for every new surface;
- the grounding checker (`scripts/eval_ai.py`) has a machine-readable target.

**Ship "Behind this" with every new AI surface from day one.** It is what separates this from a
chatbot guessing at your portfolio.

### Numbers: correctness by construction, not by checking

An earlier draft proposed a blocking gate that rejected a card if any number in its prose failed to
appear in the evidence pack. **Owner review flagged this as brittle, and that is right** — a model
legitimately produces derived values (a difference, a ratio, a rounding), so a literal
every-number-must-match check either false-positives constantly or gets loosened until it means
nothing. A gate that suppresses good cards is worse than no gate.

**Better design: the model never writes a number at all.**

The model returns a sentence *template with named slots* plus the pack fields that fill them:

```json
{
  "text": "Earnings in {days} sessions, and your {basis} stop is {gap} away.",
  "slots": { "days": "pack.earnings.days_to", "basis": "pack.position.stop_basis",
             "gap": "pack.derived.stop_gap_pct" }
}
```

The renderer fills the slots from the pack. Every number the user sees is then **the same value the
rest of the UI computed**, guaranteed — not a value that happened to survive a checker. The
validation reduces to "does every referenced field exist in the pack", which is a precise,
non-negotiable, non-brittle check, and a failure is a bug in our prompt rather than a judgement call
about a model's arithmetic.

This is the same principle as the 2026-08-24 `rsChip()` lesson in `CLAUDE.md`: when a fix's
correctness depends on a coincidence holding, add a parameter instead of an assumption. Here the
coincidence would be "the model did the arithmetic right this time."

The model still *reasons over* numbers — it decides which fact matters and what to say about it. It
just doesn't get to transcribe them. Prose that genuinely needs a computed value we don't already
have becomes a new deterministic pack field, which is a good forcing function.

### How much context to feed it

Owner's steer, and I agree: **don't over-curate.** The existing `serialize_*()` functions pre-chew
hard — they hand the model a short narrated summary because that was the right call for a 2023-era
context window. That constraint is gone, and heavy pre-chewing now actively costs us: it decides in
advance which patterns are findable, so the model can only re-describe our own analytics back to us.

Proposed split — **breadth for the model, traceability for the reader**:

- **Feed broadly.** All 144 industries, not just the leaders. The full pick row, not 6 selected
  columns. The whole `position_events` ledger. Prior sessions, so cross-day patterns are visible.
- **Require citation.** The model must name which pack fields it actually used for each statement.
  The "ⓘ Behind this" drawer then renders **the cited subset**, not the whole payload — otherwise
  provenance degrades into a data dump nobody reads, which would quietly destroy the app's best
  trust feature.

Two practical constraints worth stating up front: input tokens scale with breadth across ~3 runs a
day, so structure the payload as a **stable prefix + a small volatile tail** to make prompt caching
effective; and breadth raises latency, which matters for the on-demand Positions read but not for
anything batch.

### The structured-output risk this design carries (staff review, 2026-09-06)

Slot filling means the model must return **strict JSON** (`statements[] → text/slots/cites`). The
repo has been here before and retreated: `planning/ai-tab-daily-note.md` records that the first AI
tab was rebuilt around forced JSON schema mode (`response_mime_type` + `response_schema`,
`gemini-2.5-flash`) and failed — JSON-inside-JSON, truncation, ~280 lines of parser/normalizer code
"fighting it and losing." The fix was to remove JSON mode entirely; today's `_call_api` sets
*only* `temperature` (`generate_ai.py:1093-1094`, "No JSON mode, no response schema").

That history is two model generations old and the output here is far smaller and flatter than the
old nested schema, so it is probably fine now — **but "probably" is not a basis for building the
renderer.** P0 therefore carries a mandatory spike (`AI-NEXT-P0c` in SPRINT) that runs the real
Morning per-card contract against `gemini-3.5-flash` on ~50 real rows with `response_schema` set,
and measures the validation-failure rate under the four mechanical rules. The go/no-go threshold
and the fallbacks (retry-once with the validator's error fed back; per-row calls instead of
batched calls) are in the schema doc §3.2. If the spike fails, the fallback design is the model
returning **only** `cites` + `kind` with the *renderer* owning fixed sentence templates per kind —
less expressive, still fully grounded.

## 3. The features

### 3.0 A framing correction: "posture" was the wrong axis

An earlier draft asked the owner to choose an AI *persona* — "skeptical critic" vs "balanced
analyst" vs "confident assistant" — and justified the critic partly with the (since corrected)
claim that "every existing surface in the app tells you what's good."

**Both were wrong, per owner review.** The app already surfaces plenty of negative facts: a low
Focus score, an `invalidated` status, a failed-breakout, an ATR-extension warning band, an
earnings-imminent badge, a below-floor volatility chip. It is not a one-sided cheerleader.

And the deeper objection is the right one: **the LLM's job is to surface what our facts say, not to
adopt a stance toward them.** A persona dial is a way of pre-deciding the conclusion, which is
exactly what a grounded system should not do.

So the choice collapses. What that fuzzy "posture" question was actually asking about is two
concrete, separable properties:

1. **Evidence completeness** — is the strongest counter-evidence a *required* field, or an optional
   one? **Decision: required** (owner-confirmed). An optional criticism field silently empties out
   on precisely the names you are most excited about, which is when you need it most.
2. **Confidence calibration** — how strongly may it phrase a conclusion? **This should be derived
   from the strength of the underlying evidence, not set by a persona.** Where a claim rests on a
   thin or noisy basis, the model says so; where the data is unambiguous, it says that plainly. §0
   is the cautionary case: a weak result stated with confidence.

Net effect on the build: identical to what "skeptical critic" would have produced, but for a reason
that survives scrutiny. The correct label is **evidence-complete**, not skeptical. Nothing in the
prompt tells it to be negative.

### 3.1 Top level — **The Brief**

One card at the top of the app (or the AI tab reframed), generated after the 10:05 read. Five lines,
hard cap:

1. **Regime** — from the existing `rotation_phase` field. Already built, just relocated.
2. **What changed for you** — N triggered from your Focus list · M positions need a decision ·
   K watch levels hit.
3. **The one action** — highest-priority thing, with its reason.
4. **The one non-action** — the disqualifier. What *not* to do today.
5. **What I'm not sure about** — an explicit uncertainty line.

Composed client-side from two fetches: the public half (Tier A) renders signed-out; the personal
half (Tier B) lights up on sign-in. This is what makes AI feel like it is *in* the app rather than a
tab you visit.

### 3.2 Picks tab — **"Why this" + "The catch"**

Two batch-generated sentences per pick, top ~25 Focus names only (cost control), Tier A:

- **Thesis** — grounded on the frozen `grp_*` attribution plus the stock's own setup metrics.
  *"Semiconductors is #3 by mid-rank with RS at a 20-day high; this name is 1.2 ATR from its 50MA
  in its tightest 7-day range."*
- **The catch** — mandatory, **never empty**, the strongest argument against. Extension, earnings in
  6 days, thin dollar volume, group already 8 sessions extended.

A pick card that argues with itself is the differentiator. The existing Focus and Ariel breakdowns
are value-vs-threshold tables; this is the synthesis layer above them, and today *every* explanatory
string on this tab is a hardcoded per-status lookup (`_mNote()`), so there is no prose to displace.

**The honesty chip — dropped from the AI roadmap (owner decision, 2026-09-06).** An earlier draft
proposed feeding `evaluate_picks` output into the prompt so the model could quote the bucket's
measured excess against the app itself. Three reasons it is out:

1. The number is not trustworthy yet (§0): a point estimate over ~6 independent windows that flips
   sign across sample halves, with no interval until #401/#403 land. Quoting it on every pick card
   invites exactly the misreading that produced the methodology audit.
2. Even fixed, it grades the *group index*, not the pick, the trigger, or the stop. It says nothing
   about what is actually traded until #404 exists.
3. A backtest number has no reasoning for a model to add. When #404 lands, the right form is a
   **deterministic chip** rendered from `ticker_scores.csv`, not an LLM statement — same rule as
   every other computed value in the app.

The mandatory "catch" is the per-pick honesty mechanism, and it needs no backtest. Tracked as a
note on #404 so the deterministic chip is not forgotten.

### 3.3 Morning tab — **session read + triage**

The status engine already classifies correctly. What it can't do is *reason about this row's
numbers*:

- **Per-card synthesis** using trigger vs price vs stop, ATR-from-LoD, rel volume — and critically
  the **cross-session delta** (`setting_up` at 10:05 → `triggered` at 15:30 on 2.1× rel volume).
  The pre-close session is where this pays: "confirming into the close vs fading" is precisely a
  judgment call the deterministic engine can't express and an LLM can, from two reads plus a bar.
- **Triage summary** at the top: *"3 actionable, ranked. 4 invalidated overnight — all four were
  extended >2.5 ATR from the 50MA at yesterday's close."* Pattern-finding across today's rows is a
  job LLMs are genuinely good at and no fixed lookup table can do.

### 3.4 Positions tab — **the hold/trim/exit second opinion** (Tier B)

One tap per position: *"Should I still be holding this?"* Grounded on:

- the position row (entry, current stop, `profit_floor`, `trail_basis`, `caution_flag`, R multiple,
  `days_to_earnings`);
- the **full** `position_events` ledger — not the 8-event cap the UI renders;
- the last N `ticker_quotes` bars including the raw Finviz block (RSI, 52W range, `perf_*`);
- **the ticker's group deltas** — currently *not* connected to `worker-positions` at all. This join
  is the one genuinely new piece of plumbing worth building, and it is the app's entire thesis: you
  bought the stock because its group was rotating in. Has the group rolled over?

**Hard constraint: the engine decides, the LLM explains.** `advance()` is deterministic, tested
(155 vitest), and owns stops and exits. The LLM never writes `current_stop`, never closes a
position, never fires a transition. At most (a later phase) it *proposes* a per-position config
override into `meta.config` — the extensibility seam already documented in
`trade-lifecycle-engine.md` §14 — as a suggestion the owner taps to accept.

### 3.5 Watchlist — **level suggestion + why-you-watched recall**

*"You added this 9 days ago on a 20MA reclaim. It has since qualified in the `accel` bucket and sits
1.1 ATR from the 50MA. Your 'above 322' level is still 4% away."* Small, cheap, high delight — and it
uses history the app already has and currently throws away at render time.

### 3.6 The loop-closer — **Weekly review** (Tier B)

Sunday. Joins picks history + morning statuses + position events + closed trades into a coaching
note: what you took, what you *skipped that worked*, what your losing entries had in common. One
call per week, so it can afford a stronger model than the daily flash tier.

This is the feature that makes the app compound rather than just report. It is also, given §0, the
most honest thing we could build.

---

## 4. Guardrails

- **Traceability** — every generated sentence must map to a pack line; "Behind this" ships with
  every surface.
- **Numbers are slot-filled, never model-written** (§2). The only gate is the schema doc's four
  mechanical validation rules, applied identically on both tiers; a statement that fails them is
  dropped and logged, never rendered. (An earlier draft had a "blocking numeric-grounding gate" on
  Tier B — superseded by slot filling; the old wording survived here and in the P4 SPRINT row
  until the 2026-09-06 review.)
- **Silence convention** — the app already uses "no badge = no signal". AI inherits it. No forced
  daily paragraph about a position where nothing happened.
- **Voice split** — imperative voice stays reserved for the deterministic engine ("Stop moved to
  X"). The LLM speaks descriptively and always surfaces its uncertainty line.
- **Cost** — today 11 calls/run × 2 cascaded runs/day (pre-close + EOD; `generate_ai.yml` fires
  off "Daily Snapshot"). Morning per-card prose on the owner-scoped rows (actionable + changed,
  ~30–45/day, two sessions) is ~60–90 small calls/day if done per row, or ~4–6 if batched — the P0c
  spike decides which. Positions on-demand is a handful. Keep the incremental-resume and
  `DailyQuotaExhaustedError` fast-abort machinery — both already earned their keep.
- **Latency to screen** — owner-confirmed 2026-09-06: Morning prose must land **≤10 min after each
  read** (10:05 and 15:30 ET). That is achievable as Tier A only by cascading a new AI job off the
  `Morning Status` and `Pre-close Status` workflows (today `generate_ai.yml` only follows "Daily
  Snapshot"), and it puts a hard budget on the P2 run: scrape+commit (~3 min) + AI run + commit +
  PWA fetch. Measure it in the P0c spike; if it can't fit, per-row calls are the first thing to cut.
- **Model choice** — `gemini-3.5-flash` is right for narration. The J3 critique/coach jobs are
  reasoning-heavy; consider a stronger model for the weekly review only (1 call/week).

---

## 5. Phasing

Order reflects the owner's **Morning-first** decision. Each phase is decomposed into pick-up-able
sub-tasks with acceptance criteria in `.session/SPRINT.md` and `planning/ai-next-user-stories.md`.

| Phase | Scope | Tier | Size |
|---|---|---|---|
| **P0** | Evidence-pack builder + registry + validator (`scripts/evidence_pack.py`, `data/ai/pack_schema.json`), the structured-output spike, and the shared slot renderer in the PWA. No user-facing UI. | A | M |
| **P2** | Morning: per-card session read on actionable + changed rows, 10:05→15:30 delta narrative, triage summary; new AI cascade off the Morning/Pre-close workflows. Ships with "Behind this". | A | M |
| **P1** | Picks: thesis + the catch (top ~25 Focus names). Ships with "Behind this". | A | M |
| **P3** | The Brief — top level, public half only. | A | S |
| **P4** | Tier B infra: `worker-positions` `POST /ai/ask` + D1 cache + JS pack builder with parity tests + **ticker→industry group join**. | B | L |
| **P5** | Positions: hold/trim second opinion. The Brief's personal half lights up. | B | M |
| **P6** | Weekly review — the loop-closer. | B | M |
| **P7** | *(optional)* LLM-proposed `meta.config` overrides, owner-approved, never autonomous. Directions catalogue already exists in #299. | B | M |

P0–P3 need **no new infrastructure and no new secrets**. P4 is the one real infra step; everything
personal is gated behind it. Related retrofit of the *existing* AI tab onto the pack: #409 — it
rides on P0's builder and is sequenced after P2 so the new surface, not the old one, drives the
builder's shape.

---

## 6. Owner decisions (locked — do not re-ask)

| # | Question | Decision | When |
|---|---|---|---|
| 1 | Private position/watchlist data may leave D1 for the Gemini API (same GCP project)? | **Yes.** | 2026-09-05 |
| 2 | AI posture (critic / analyst / assistant)? | **Wrong axis — replaced** by *evidence-complete*: counter-evidence is a required field, confidence derives from evidence strength. See §3.0. | 2026-09-05 |
| 3 | Starting point? | **Morning tab** (P0 → P2). It is the tab the owner opens first. | 2026-09-05 |
| 4 | Positions read: on-demand or batch? | **On-demand tap.** | 2026-09-05 |
| 5 | Numeric grounding? | **Slot filling**, model never writes a number; no fuzzy numeric gate. See §2. | 2026-09-05 |
| 6 | How much context? | **Feed broadly**, require citation, drawer renders the cited subset. See §2. | 2026-09-05 |
| 7 | Morning latency to screen? | **≤10 min after each read** → new Tier A cascade off the Morning / Pre-close workflows. | 2026-09-06 |
| 8 | Which Morning rows get per-card prose? | **Actionable (`triggered`/`gapped_through`/`reclaim`) + rows whose status changed 10:05→15:30.** `setting_up`/`invalidated` keep the `_mNote()` strings. | 2026-09-06 |
| 9 | Honesty chip? | **Dropped** from the AI roadmap; becomes a deterministic chip once #404 exists. See §3.2. | 2026-09-06 |
| 10 | Schema §6 Q1 registry drift | **Hard build error.** | 2026-09-06 |
| 11 | Schema §6 Q2 context budget | **No cap for Tier A batch; soft cap + truncation note for Tier B.** | 2026-09-06 |
| 12 | Schema §6 Q3 confidence | **Leaning: render.** Staff recommendation is *render only the `low` state* (see schema doc §3.3); owner to confirm that variant or ask for all three states. | 2026-09-06, open on variant |

## 7. Tracking

Tracked in `.session/SPRINT.md` as `AI-NEXT-*` (decomposed per phase, with acceptance criteria in
`planning/ai-next-user-stories.md`). Nothing here is implemented; this document is the design gate. Per `.claude/rules/data-pipeline.md`, note that **none of P0–P7 requires a schema
change to any ground-truth CSV** — AI output lands in `data/ai/` (derived, already established) or
in a new D1 cache table, never as new columns on `picks.csv` or the session stores.

---

## 8. Staff review log (2026-09-06)

What changed in this document and why, so the SDE2 who wrote it can see the delta rather than
re-read the whole thing:

- **§6 rewritten** from "open questions" to a locked-decisions table. The old list still asked
  about "posture" (which §3.0 had already retired) and "starting point" (decided). A cold reader
  would have re-asked all four.
- **§4 guardrail contradiction fixed.** It still said "blocking numeric grounding on personal
  tiers" one section after §2 replaced that gate with slot filling.
- **§5 phasing reordered** to match Morning-first; P0 no longer wires `evaluate_picks` into
  prompts (that was the honesty-chip input); P1 no longer carries the chip; P4's "blocking
  grounding gate" replaced by the shared validator + JS parity tests.
- **§2 structured-output risk added.** Neither doc mentioned that the repo already tried JSON
  schema mode on the AI tab and backed it out (`ai-tab-daily-note.md`). It is the single biggest
  implementation risk in the design and now has a spike with a go/no-go.
- **§2 Tier boundary corrected** for watchlist tickers (already public via `morning.csv`).
- **§4 cost/latency** rewritten with the verified call count (11 × 2 runs, not "~33/day") and the
  new ≤10-min Morning budget, which forces a new workflow cascade the original doc did not mention.
- **#299 linked** from P7 — the position-management LLM directions catalogue already existed and
  the proposal did not reference it.

---
