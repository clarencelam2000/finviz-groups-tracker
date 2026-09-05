# AI/LLM integration across Picks, Morning, Positions — and at top level

**Status:** Proposal, awaiting owner direction. No code shipped.
**Date:** 2026-09-05
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
  `gemini-3.5-flash` on Vertex, ~3 runs/day cascading off `collect.yml`.
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

### The uncomfortable input to strategy

`scripts/evaluate_picks.py --report`, run live on 48 settled dates:

| horizon | exSPY mean | hit | exMEDIAN mean | hit | paired per-date |
|---|---|---|---|---|---|
| 1 | −0.25% | 44% | −0.17% | 46% | −0.18 (22/48 dates +) |
| 3 | −0.77% | 39% | −0.44% | 46% | −0.54 (20/46 +) |
| 5 | −1.15% | 41% | −0.64% | 44% | −0.79 (16/44 +) |
| 10 | −1.39% | 42% | −0.80% | 44% | −1.07 (17/39 +) |

Per bucket, `leaders` (the largest, 492 rows at h=1) is the worst at every horizon
(−0.34 → −2.13% exSPY). `emerging` is the only bucket with a positive read, and only at h=10
(+0.86 exSPY / +1.42 exMEDIAN, 53–59% hit, N=158).

**Scope this correctly — it is easy to overstate.** This measures forward returns of the *industry
groups* the selector chose. It does **not** measure the stock picks, and it does not measure the
Morning trigger/stop discipline or the position engine at all. Ticker-level scoring is deliberately
unbuilt (`evaluate_picks.py` docstring: the internal price chain is survivorship-biased, deferred as
PICKS-4B). With `ticker_quotes` now accumulating real OHLC for held and watched names, that
instrument is becoming buildable for the first time.

But the strategic implication holds regardless: **do not build an AI that hypes picks.** Build one
that filters, disqualifies, and grades. A skeptical second opinion is the honest posture, the
defensible product, and the safer one for a live trader.

---

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

**Tier B — on-demand / private / authenticated.** Positions and watchlist live in D1 behind bearer
auth. They can never be committed to git — not "shouldn't", *can't*. So Tier B requires an LLM call
originating **inside `worker-positions`**, authenticated as the owner, with the response cached in
D1 keyed by `(user_id, trade_date, surface, position_hash)` and never written to the repo.

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

### One grounding rule I want to change

`eval_ai.py` today checks that every group name in the output appears in the input, and it runs
**offline only** — ADR-006 deliberately quarantines token-spending paths off the nightly run. That
was right for commentary. It is not right for a card that talks about money the owner has at risk.

Proposal: extend the check to **numeric** grounding (every number in the output must appear in the
pack) and run it as a **blocking gate on the personal tiers** — if a card fails, suppress the card
rather than ship a wrong number. Broadcast commentary can stay non-blocking.

---

## 3. The features

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

**Plus the honesty chip.** Feed `evaluate_picks` output into the prompt so the model can cite the
scoreboard *against the app itself*: *"this bucket's measured 10-session excess is −2.1% over 48
dates — treat as a watch candidate, not a buy."* An AI that quotes your own negative backtest is a
trust asset no competitor will copy, and it is the correct response to §0's numbers.

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
- **Blocking numeric grounding on personal tiers** (§2). Suppress the card, don't ship the number.
- **Silence convention** — the app already uses "no badge = no signal". AI inherits it. No forced
  daily paragraph about a position where nothing happened.
- **Voice split** — imperative voice stays reserved for the deterministic engine ("Stop moved to
  X"). The LLM speaks descriptively and always surfaces its uncertainty line.
- **Cost** — today ~33 calls/day on flash. Picks thesis for 25 names batches into ~3 calls; morning
  triage ~2; positions on-demand is a handful. Same order of magnitude. Keep the incremental-resume
  and `DailyQuotaExhaustedError` fast-abort machinery — both already earned their keep.
- **Model choice** — `gemini-3.5-flash` is right for narration. The J3 critique/coach jobs are
  reasoning-heavy; consider a stronger model for the weekly review only (1 call/week).

---

## 5. Phasing

| Phase | Scope | Tier | Size |
|---|---|---|---|
| **P0** | Evidence-pack builder + versioned schema; `TASK_SPECS` takes a pack; wire `evaluate_picks` output into prompts. No new UI. | A | M |
| **P1** | Picks: thesis + the catch + honesty chip. Ships with "Behind this". | A | M |
| **P2** | Morning: per-card session read, cross-session delta narrative, triage summary. | A | M |
| **P3** | The Brief — top level, public half only. | A | S |
| **P4** | Tier B infra: `worker-positions` `POST /ai/ask` + D1 cache + blocking grounding gate + **ticker→industry group join**. | B | L |
| **P5** | Positions: hold/trim second opinion. The Brief's personal half lights up. | B | M |
| **P6** | Weekly review — the loop-closer. | B | M |
| **P7** | *(optional)* LLM-proposed `meta.config` overrides, owner-approved, never autonomous. | B | M |

P0–P3 need **no new infrastructure and no new secrets**. P4 is the one real infra step; everything
personal is gated behind it.

---

## 6. Open questions for the owner

1. **Private data → Vertex.** P4–P7 require position/watchlist data to leave D1 for the Gemini API
   (same GCP project already in use). Acceptable? If not, the roadmap ends at P3 — which is still
   most of the value of J2.
2. **Posture.** Skeptical critic (recommended, per §0), balanced analyst, or confident assistant?
   This sets prompt persona and, more importantly, whether the AI is allowed to argue against a pick
   the app itself surfaced.
3. **Starting point.** Picks (P1, safe, immediate, no infra) or Positions (P4+P5, higher value,
   needs the Tier B build)?
4. **On-demand vs. always-on** for the Positions read — a tap costs ~2s of latency and one call; a
   batch pre-generates for every open position each evening. Latency vs. freshness.

---

## 7. Tracking

Tracked in `.session/SPRINT.md` as `AI-NEXT-*`. Nothing here is implemented; this document is the
design gate. Per `.claude/rules/data-pipeline.md`, note that **none of P0–P7 requires a schema
change to any ground-truth CSV** — AI output lands in `data/ai/` (derived, already established) or
in a new D1 cache table, never as new columns on `picks.csv` or the session stores.
