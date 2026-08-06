# Cron Consolidation → Trade Lifecycle — Ideation & Alignment Record

**Date:** 2026-08-06
**Participants:** Repo owner (swing trader) + Claude (acting staff eng / staff product advisor)
**Purpose:** A durable, faithful record of the whole ideation conversation behind the
cron-consolidation initiative and everything it unlocked — what was proposed, what the owner
**approved / modified / rejected**, the owner's **actual trading ruleset**, and the corrections
the owner made to Claude's thinking. Written so that a future Claude session, or the owner, or a
teammate, does not have to re-derive any of this from scratch. This is the *why and how we
aligned*; the ADRs and planning docs are the *what*.

> **Read this first** if you are picking up any of WS1–WS5. It is the single source of truth for
> intent. If an ADR or planning doc ever contradicts this record on a point of owner intent,
> this record wins and the doc should be corrected.

---

## 0. Artifacts this conversation produced

| Artifact | What it is |
|---|---|
| `knowledge/decisions/ADR-010-single-trigger-cron-dispatch.md` | Decision record for the cron consolidation |
| `planning/cron-consolidation-state-machine.md` | Implementation-ready WS1 design |
| `planning/roadmap-cron-lifecycle.md` | Sequenced WS1–WS5 roadmap + cheap wins + parked/rejected |
| `knowledge/cron-lifecycle-ideation-and-alignment.md` | **This file** — the alignment/memory record |
| PR #257 | Ships the three docs above |
| Issues #258–#266 | Tracked work (WS1×3, WS2, WS3, WS4, WS5 epic, taxonomy check, parked tracker) |
| WS2 ADR, WS5 ADR + design doc, WS3/WS4 design docs | **Not yet written** — to be authored by main-model Claude (see § 7) |

---

## 1. Originating problem

- The Cloudflare account is shared with an unrelated project (`distil-*` workers) and has a
  **hard 5-cron-trigger limit**. `finviz-cron-dispatcher` was burning 3 of them.
- Hitting the limit already caused a real outage (issue #252): the picks cron failed to deploy,
  and picks had no trigger / no data from 2026-07-17. An intraday collect trigger had to be
  removed just to free a slot.
- **The felt pain point:** no morning market-open workflow — the owner has no actionable data
  until near market close. This was the emotional driver of the whole conversation.
- A senior eng on the sibling project shared a doctrine (see § 2).

## 2. The doctrine adopted (owner approved)

**One Cron Trigger per project.** Ride a single tick; gate multiple logical jobs inside
`scheduled()` by time-of-day / day-of-week computed **in code**, never by adding a new trigger.
Scales to effectively unlimited logical jobs on one trigger.

Claude's refinement on top (owner approved): because our jobs run at `:48/:01/:31` (not top of
hour), use a **`*/5 * * * *` tick** (every 5 min) — owner explicitly said *"aligned with every 5
min as the period. Don't need every minute."* — and compute **Eastern wall-clock in code** so
**DST becomes automatic** and the twice-yearly manual UTC edit disappears. Owner: *"The cheap win
on DST is a great point — and we should take this win yes."* and *"Definitely bundle in auto-DST
— I don't see any reason not to."*

## 3. The reframe that unlocked everything (owner aligned)

Two observations of the same trading day (morning + EOD), plus a session dimension to keep both,
turns the product from *"here's a ranked list, you figure out what to do and whether it's still
valid"* into *"here's what to do, how much, and what's changed since you last looked."* Guiding
philosophy, owner-endorsed: **the app holds the user's state so the user doesn't have to.**

**Hard constraint stated repeatedly by the owner: this is SWING trading, NOT day trading.**
React to price over days; **no pre-set profit targets** — *"Remove target — I don't trade with
targets - I just react to price action without some bias target."* Any idea that drifts toward
intraday reaction speed or fixed targets is out of scope by design.

## 4. Idea-by-idea decision log

Legend: ✅ approved · ✏️ approved with owner modification · ⏸️ deferred (not rejected) · ❌ rejected

| Idea | Disposition | Owner's reasoning (captured) |
|---|---|---|
| Consolidate 3 crons → 1 `*/5` tick | ✅ | Frees slots, unbounded jobs |
| Auto-DST via in-code ET | ✅ | "Take this win" |
| Dependency-driven picks dispatch (state machine, not 90-min margin) | ✅ | "Picks stops being 90 min later fingers crossed and becomes when deltas actually landed" |
| Self-heal + retry-on-miss; retire healthchecks.io / GH-email | ✅ | "We should do this. Removes need for these other hacky healthchecks" |
| Weekly taxonomy drift check | ✅ | "Yes. We can really make us much more robust. Deserves some good thought" |
| Session dimension (keystone) | ✅ | "Session dimension is the keystone" |
| Trade tickets: 20MA/50MA stops | ✏️ | Add stops at **20MA and 50MA**; **remove profit targets** |
| ATR-distance-from-LoD gate | ✅ | "Cheap win with high signal" — if a stock has run 1 ATR from LoD, the day's expected move is theoretically already done → don't chase |
| Earnings guardrail on tickets | ✅ | Already dinged in Focus/Picks scoring when earnings near; reuse the parsed date |
| Morning **confirmation/invalidation** surface | ✅ | "Good stuff" — sequenced ahead of morning picks |
| Trade **lifecycle engine** (WS5) | ✅ | "Impressed... addresses one of my gaps in my own trading" |
| Honest backtest entries (score the actual ticket, R-multiples, MAE/MFE) | ✅ | "This is good. Maybe we can add even more onto this idea" |
| PWA push (VAPID) | ✅ | Sibling project already gets VAPID pushes on same account |
| User-scoped storage in D1, user=1 now | ✅ | Sibling project already uses D1 on the same account |
| Light sizing/crowding **information** (not diversification) | ✏️ | Keep it light; add "pick the best horse in the firing group, not the laggards" |
| Morning **picks** (net-new opening list) | ⏸️ | "Maybe isn't that actionable for me actually... defer. But don't orphan or forget this" |
| Rotation-narrative digest | ⏸️ | "Sounds good yes, but not sure how it'll land. Might need to polish and refine" |
| Persistence / intraday decay tracking | ❌ | "Not to me. I would question if we are going into day trading territory" — Claude agreed, it is |
| Gap surface / opening-breadth gauge | ❌ | "A bit ticky tacky... how to treat gaps is quite dependent on market conditions. Not so simple." Breadth thin for swing |

## 5. Owner corrections to Claude's thinking (do NOT repeat these mistakes)

These are the moments the owner corrected staff Claude. Preserved verbatim-in-spirit so future
sessions inherit the correction, not the original error.

1. **collect ≠ picks; they are separate workflows.** Claude wrongly implied the morning job was a
   picks job. The owner: *"collect snapshots and picks are separate jobs - and we can separate
   them."* A morning collect (e.g. 9:45 ET) and a morning picks (e.g. 10:15) can be scheduled
   independently, with a 10:00 fallback check.

2. **"Deltas computed against yesterday's close" was flat wrong.** `compute_deltas` ranks whatever
   the latest snapshot is; picks run off that. The real nuance is that a morning snapshot's
   `perf_*` are Finviz **provisional mid-session** values, and because collect is last-write-wins
   per `(date, name)`, a morning row stamped today is **overwritten** by the EOD row. That
   overwrite — not any "vs yesterday's close" framing — is the *only* reason the session dimension
   is needed (to keep the morning artifact).

3. **The stop invariant is NOT "ratchet up only" — it's a profit floor.** This is the single most
   important correction in the conversation. See § 6 for the corrected rule. Claude's initial
   "stops only ratchet up, never loosen" would have *forbidden the owner's real strategy* of
   widening the trail from 20MA to 50MA.

4. **"Diversification" is a category error for this trader.** Claude imported modern-portfolio-
   theory / long-term-investor framing ("don't concentrate"). The owner is a **rotation trader who
   deliberately presses the leading group** — a whole group moving together is the *signal firing*,
   not undiversified risk. The only salvageable kernel: as *information* (not prescription),
   several positions in one group move as one bet, so know your true aggregate exposure for
   sizing. Never frame as "you should diversify."

5. **Scaling out is core to the process, not a v2 nicety.** Claude filed partial exits as "later";
   the owner's ruleset (§ 6) trims on a schedule, so the position model must be a *reducing
   quantity with a trim history* from v1.

## 6. The owner's ACTUAL trading ruleset (verbatim intent — this is precious, capture exactly)

This is what the WS4 tickets and the WS5 lifecycle engine must encode. These become tunable,
triple-documented config constants.

**Entry / tickets (WS4):**
- Buy trigger: **break above the prior day's high.**
- Stop options: **prior day's low**, or **current day's low**, or **20MA**, or **50MA**.
- **No profit targets.** Exit is governed by trailing risk rules and price action, not a target.
- Don't-chase gate: if price has already run **> 1 ATR from the low of day (LoD)**, the day's
  expected move is theoretically already done → poor entry.

**Position management / lifecycle (WS5):**
- **Profit-floor invariant:** once past breakeven, never let the trade go red again. The *active*
  stop may **widen** (20MA → 50MA) as long as it stays at/above that floor.
- **Widen the trail to the 50MA once the 50MA moves above entry** — safe precisely because by then
  even the looser 50MA stop still locks in green. (This is why "ratchet up only" is wrong: the
  50MA level can sit numerically *below* the current 20MA stop while both remain above breakeven.)
- **Exit rule (stateful):** cut a winning position **only if it closes below the 20MA twice** —
  *"usually I only cut a winning position if it closes twice under the 20MA, not on the first day
  unless it's really not looking good. First close under 20 is caution and watch the next
  close."* So: 1st close < 20MA = `caution`/watch; 2nd consecutive close < 20MA = exit;
  discretionary hard-exit override if it "really breaks."
- **Scale-out / trimming:** *"For trimming extension, every whole multiple ATR extension from 50
  above 7atr (eg 7atr, 8atr, 9atr) - trim 10% of remaining position."* Needs a trim ledger of the
  highest ATR-multiple already trimmed so a level isn't re-trimmed.
- Owner sometimes runs **several partial stops** across a position's life.

## 7. Storage & architecture decisions (owner aligned)

- **Not append-only CSV** for positions — they mutate daily and are personal financial data not
  fit for a public repo. Use **Cloudflare D1** (sibling project already runs D1 + VAPID on the
  same account → proven, and push comes for free).
- **Shape:** typed relational **spine** (`positions`) + JSON `meta` bag + append-only
  **`position_events`** ledger. Owner asked explicitly about SQL-vs-NoSQL / "spine + flexible
  bag" — this is the answer: spine where queried, JSON bag where not, event log for
  extensibility + audit + replay.
- **Multi-tenancy from day one even at user=1** (owner raised RLS / one-way-door concern):
  `user_id` on every row, every query scoped to it. **D1/SQLite has no row-level security** —
  isolation is **app-layer**; the Worker derives `user_id` from the auth token and never trusts a
  client-supplied one. user=1 auth = a single shared token for now.
- **Non-obvious consequence (owner aligned):** a held position needs a **daily quote even after it
  falls off the picks list** → a **held-tickers feed** is required, which is another gated job on
  the WS1 tick. The owner noted this is "good to hear our cron redesign is paying off many ways."

## 8. What Claude is less than fully confident about (honest flags)

- **Session-dimension key shape (WS2) is genuinely unresolved** — it's a design spike. The exact
  widening of `(date, name)` and `(date, list_category, ticker)` needs its own ADR.
- **ATR-from-LoD semantics differ intraday vs EOD** — at EOD "Low" is the full-day low (clean);
  from a *morning* snapshot "Low" is range-so-far. The gate is well-defined for EOD tickets;
  intraday use needs care.
- **Cloudflare Workers ICU/timezone data** — high confidence V8 in Workers ships full ICU
  (`Intl.DateTimeFormat` with `America/New_York` works), but verify at implementation.
- **The WS1 "parallel run" rollout validation is partial** — while the 3 old triggers are still
  active, the new routing function only *executes* at those 3 fire times, so you can't fully
  validate the new schedule's other target times until after the trigger cutover. Mitigate with
  thorough unit tests of `jobsForTick` rather than relying on prod-shadow comparison alone.
- **Backtest / MAE-MFE idea (WS4/eval)** is promising but under-specified — flagged as "add even
  more onto this" by the owner; not yet designed.

## 9. Process notes (for the owner and future Claude)

- **Design docs are main-model work, not subagent work.** In this session the three planning docs
  were drafted by a Sonnet subagent and reviewed/corrected by main-model Claude. The owner flagged
  (correctly) that judgment-heavy synthesis of a conversation only the main model was in should be
  authored by the main model. Per `CLAUDE.md`: *"Design, auditing, data synthesis, and anything
  judgment-heavy stays in the main model."* Remaining deep docs (WS2 ADR, WS5 ADR + design,
  WS3/WS4 docs) are to be authored by main-model Claude directly.
- **Nothing is implemented.** All work to date is docs + tracking. No code, workflow, or
  `wrangler.toml` change. Implementation waits on the owner's explicit go-word, starting with WS1.
- WS2 and WS5 each require their **own ADR before implementation** (tracked in #261, #264).
