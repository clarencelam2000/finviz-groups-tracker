# WS5-7 — Positions managing-card overhaul

> **Status:** spec locked, ready to build cold. High priority (ranked above WS5-4).
> **Issue:** #337 · **Epic:** #264 (WS5 trade lifecycle) · **SPRINT:** WS5-7
> **Design authority:** this file. **Owner sign-off:** pending mock approval (§9).
> **Sibling decisions:** #335 (breakeven ratchet), WS5-8 (pre-close advisory, §8 here).

---

## 0. Why this exists (the miss it fixes)

The Positions tab was built in WS5 phase 1 as a deliberately **frozen, read-only placeholder** —
its banner literally promises "daily stop management & alerts arrive with the lifecycle engine."
Phases 2–3 then shipped the held feed + the `advance()` engine **entirely in the worker**, each
with green vitest suites, and **no one looped back to upgrade the phase-1 card** once the engine
went live and started mutating position rows on the 17:30 ET sweep.

Result, observed live on 2026-08-18 (real positions OUST / NVT / EOG, D1 `finviz-positions`):

- **The card computes `risk = entry − current_stop`.** Once the engine trails the stop to or above
  entry, this goes to `$0.00` (OUST) or **negative** (EOG showed `Risk/sh −$0.12`, `Open risk
  −$3.55`). The "−$3.55" is literally the *locked-in gain* with its sign flipped and the wrong label.
- **The stop-basis label lies.** The card renders `current_stop` but labels it with the *initial*
  `stop_basis`. OUST showed `$45.13 (Manual)` — but 45.13 is the engine's 20MA breakeven ratchet,
  not the manual 45.00. EOG showed `$142.90 (Prior low)` — but the prior low was 140.48; it trailed
  via 20MA. **The user was never told the stop moved** → cannot update the resting order in their
  brokerage. For a trailing-stop engine, this is the whole value proposition leaking out.
- **Nothing the engine did is visible.** `stop_moved {from,to,basis}`, `exit_signal {reason,
  expected_exit_price, at_close}`, the current-day bar — all written to `position_events` /
  `ticker_quotes`, none surfaced. State silently changed between two screenshots 13 minutes apart
  (the 17:30 sweep ran between them) with zero explanation → reads as flakiness.
- **The banner is now false.** It says management "arrives with the engine" while the engine is
  actively managing.

None of this is a data bug — every engine decision verified correct against the bars. It is a
**presentation + missing-action-surface** gap. WS5-7 closes it.

**Scope boundary vs WS5-4 (Phase 4).** WS5-4 = push notifications + the exit-confirmation strip
for `closing` positions. WS5-4's strip **only renders for `closing`**; it never touches the
everyday `managing` card. WS5-7 is the everyday card. They share one small backend add (§5) and
are otherwise independent. WS5-7 needs **no VAPID**, which is why it ships first.

---

## 1. Work backwards: user stories

The user is a swing trader who checks the app on their phone, usually once in the evening after
the settled run, sometimes intraday. Every story below is a real state in today's live data.

**US-1 — "My stop moved up; I need to update my broker." (the table-stakes story)**
> EOG is winning. The engine trailed my stop 142.78 → 142.90 on the 20MA today. I open the app.
> The card must *tell me the stop moved*, show the old and new value, and prompt me to go update
> the resting stop order in my brokerage — because the engine only tracks; my broker holds the
> real order. I tap "✓ Updated" so it stops nagging me tomorrow.

Acceptance: a `managing` card whose `current_stop` changed on the latest sweep shows a distinct
"stop raised" affordance with `from → to` and basis, plus an acknowledge control. Un-acknowledged
state persists across reloads until the user marks it done or the stop moves again.

**US-2 — "Am I safe yet?" (the risk-free celebration)**
> OUST's stop is at my entry (45.13); EOG's is above entry. I want to instantly see that these
> trades can't lose money anymore. This is the best structural state a trade reaches and the app
> currently *buries it as `$0.00` / negative risk.*

Acceptance: when `current_stop ≥ entry_price`, the card leads with a `🔒 Risk-free` treatment and,
when `current_stop > entry`, the locked-in $ amount. Never shows negative risk.

**US-3 — "Where do I stand right now?"**
> I want unrealized P&L and how much is still at risk down to the stop, in dollars, at a glance —
> without doing mental math off entry/stop/qty.

Acceptance: hero line shows unrealized P&L (from last close) and open-risk-to-stop, color-coded,
for every card. Degrades gracefully to entry-time framing if no live bar exists yet (US-7).

**US-4 — "Why did this change / what did the engine do today?"**
> The card looked different than yesterday. I want a one-tap, plain-English record: "Stop raised
> to 142.90 (20MA) · Aug 18", "Exit signal: stop hit, modeled fill 167.44 · Aug 18".

Acceptance: an expandable per-card activity trail sourced from `position_events`, newest first,
human-readable, with dates.

**US-5 — "What did the market do today for this name?"**
> Show me today's bar — O/H/L/C and the % — so I can sanity-check the engine's read against what
> I saw happen.

Acceptance: the card (expanded) shows the latest `ticker_quotes` bar for the ticker.

**US-6 — "This one is exiting — what do I do?" (hand-off to WS5-4)**
> NVT/OUST are `closing`. WS5-7 does **not** build the confirm/still-holding actions (that's
> WS5-4), but the card must clearly say what happened (reason + modeled fill + at-close), so the
> state is legible even before the action surface exists.

Acceptance: `closing` cards show the exit reason, modeled fill, and the actual close in plain
English. No dead "exit pending" with no context. (Action buttons are explicitly WS5-4.)

**US-7 — "I just logged this; the engine hasn't run yet."**
> A brand-new position (or one with no `ticker_quotes` bar yet) has no last price. The card must
> not show `NaN`/`—` garbage or a fake $0 — it shows entry-time framing and an honest "first
> engine read after tonight's close" note.

Acceptance: null-safe. No live bar → show initial risk (entry − initial_stop) × qty as "planned
risk," omit P&L, note the pending first read.

**US-8 — "Don't make me think." (anti-story / what NOT to do)**
> Do not dump four dollar figures on the collapsed card. One hero answer + optional details.

---

## 2. The four numbers (model), and which one is the hero

Per-share, then × `remaining_qty` for the dollar figures. `last` = latest `ticker_quotes.close`
for the ticker (§5 backend add). `R = entry − initial_stop` (frozen).

| Concept | Formula | Meaning |
|---|---|---|
| **Initial risk (1R)** | `entry − initial_stop` | sizing unit; R-multiple denominator |
| **Open risk** | `max(last − current_stop, 0) × qty` | $ still at stake down to the stop |
| **Locked-in** | `max(current_stop − entry, 0) × qty` | guaranteed $ if stopped (only when stop ≥ entry) |
| **Unrealized P&L** | `(last − entry) × qty` | where the trade is now |

**Hero selection (collapsed card), by state:**

```
if state == 'closing':                      hero = exit summary (reason · modeled fill)      [US-6]
elif last is null:                          hero = "Planned risk $R×qty · first read tonight" [US-7]
elif current_stop >= entry:                 hero = "🔒 Risk-free" (+ "· locked +$L" if L>0)   [US-2]
                                            subline = unrealized P&L
                                            + PENDING-LOCK tag if stop-ack not yet done (below)
else:                                       hero = unrealized P&L (green/red)                 [US-3]
                                            subline = "Open risk $O to stop"
```

**PENDING-LOCK tag (owner ask).** The "locked +$L" claim is only *true if the user actually raises
their broker's resting stop* to `current_stop`. Until the stop-moved ack (§6) is recorded, the
risk-free hero shows a conditional treatment — e.g. `🔒 Risk-free · +$3.55 once you raise your stop`
or a small amber `Lock pending` chip — flipping to the plain `locked +$3.55` after ack. Same ack
state drives both this tag and the stop-moved banner: one acknowledgement, both resolve.

**Every number carries its per-share form and its formula.** Dollar totals show the per-share value
too where it fits (`Open risk $174 ($5.80/sh)`); unrealized P&L is **always** shown (hero subline
*and* a details row), never omitted on a live card. Under Details, a **"show formulas"** sub-toggle
(off by default) reveals the arithmetic inline per row — e.g. `Open risk = 148.70 − 142.90 = $5.80/sh
× 30 = $174`, `1R = 142.78 − 140.48 = $2.30/sh`. This is the audit/learn affordance (owner found the
literal `148.70 − 142.90 = $5.80/sh` line genuinely useful) and doubles as the "why is this
risk-free?" explainer, so no separate info button is needed — the stop-moved banner + the formula
reveal together carry the reasoning.

Everything in the table §2 is available under **Details ▾** regardless of state (US-8), and every
card's Details shows the **same full row set** (Entry, Stop + true basis, 1R, Open risk, Locked-in
*or* Unrealized P&L, Qty/remaining, Today's bar, Activity) — no thin/inconsistent Details per state.

**Rounding/format:** dollar totals show cents **only when non-zero** — `$174` but `+$177.60` —
thousands-separated (matches the owner-approved mock, where real P&L keeps its cents and round
figures drop the `.00`; supersedes an earlier "whole ≥ $100" draft that would have shown the real
`+$177.60` as `+$178`). Per-share always 2dp; P&L carries sign and color (`text-emerald-400` /
`text-red-400`); risk-free uses emerald.

---

## 2b. FULL state enumeration (owner asked to double-check — I'd missed three)

Two orthogonal axes: the worker **lifecycle state**, and **overlays** that can decorate a
`managing`/`open` card. Enumerating both so nothing is unhandled.

**Lifecycle state (worker `state` column):**

| State | On tab? | Card treatment |
|---|---|---|
| `open` | yes | Pre-first-sweep. Usually the US-7 "no bar yet → planned risk" path. |
| `managing` | yes | The everyday card; hero per §2 (risk-free / P&L / underwater). |
| `closing` | yes | Exit signaled, awaiting confirm (US-6). Reason variants below. |
| `closed` | **no** (except WS5-5 grace window) | Out of scope here; final outcome card is WS5-5. Enumerated so it's not forgotten. |

**Hero variants within `managing`/`open`** (the six the mock shows): (A) no-bar → planned risk;
(B) risk-free + locked (`stop > entry`); (C) risk-free at breakeven (`stop == entry`, locked $0 —
a sub-case of B, same 🔒, no "+$X", NOT a separate code path); (D) up, stop below entry; (E)
underwater (`last < entry`), stop below entry.

> Note on an impossible combo: **underwater + risk-free can't coexist.** If `stop ≥ entry` and
> `last < entry` then `last < stop`, which means the stop is already hit → the position is
> `closing`, not `managing`. So there is no "underwater but risk-free" card. Good invariant to state.

**`closing` reason variants** (all from `exit_reason`, render in plain English):
`stop_hit`, `gap_down_below_stop`, `close_below_50ma`, `severe_breakdown`, `two_close_below_20ma`.
Each shows: reason phrase · modeled fill (`expected_exit_price`) · actual close (`at_close`) · R.

**Overlays (decorate a `managing` card; can co-occur) — THE THREE I MISSED:**

| Overlay | Trigger (data) | Card cue |
|---|---|---|
| **Stop-moved (pending ack)** | `current_stop != initial_stop` AND no ack for current value | the §6 banner + pending-lock tag |
| **Partial trim** | `remaining_qty < initial_qty` | "20 of 30 sh · trimmed 10 @ 3× ATR" — the ATR-extension trim ledger (`advance.js`). Qty row must show remaining-of-initial, not a bare number, or the size looks wrong. P&L/risk all use `remaining_qty`. |
| **Caution (1 close < 20MA)** | `caution_flag >= 1` (counter, not bool — see #335-sibling note) | amber "⚠ 1 of 2 closes below 20MA — exits on the next close below" — a real actionable warning the engine already computes and we currently hide. |
| **Earnings approaching** | `days_to_earnings` within warn band | **NOT built in WS5-7 — deferred to #335.** "Earnings in N days" badge. **Why deferred:** the `earnings_warning` note currently fires on *negative* days-to-earnings (past dates) — see the event log; that latent engine bug (the negative-days guard) must be fixed before this overlay is surfaced, else it flags already-past earnings. Bundled with the #335 breakeven-ratchet taste call; also tracked in `.session/SPRINT.md`. |

The trim + caution overlays are the substantive additions from this review; both are already in the
`advance()` output and D1, just never surfaced. The mock (§9) now includes a trim example and a
caution example.

## 3. Card anatomy (managing state, expanded)

```
┌─────────────────────────────────────────────┐
│ EOG · picks · 2026-08-14        MANAGING     │  ← header (unchanged structure)
│                                              │
│ 🔒 Risk-free · locked +$3.55                 │  ← HERO (state-driven, §2)
│ +$177.60 unrealized                          │  ← subline
│                                              │
│ ⬆ Stop raised 142.78 → 142.90 (20MA)  Aug 18 │  ← STOP-MOVED banner (US-1), only when changed
│    Update your broker    [ ✓ Updated ]       │     + acknowledge control
│                                              │
│ Details ▾            [ show formulas ]        │  ← collapsed by default; formula sub-toggle
│  ├ Entry      $142.78    Qty     30 of 30    │  ← "N of M" when trimmed (§2b overlay)
│  ├ Stop       $142.90    (trailed · 20MA)    │  ← true basis, not initial
│  ├ 1R (init)  $2.30/sh   Open risk $174 ($5.80/sh) │
│  ├ Unrealized +$177.60   Locked-in +$3.55    │  ← P&L always shown
│  ├ Today  O148.04 H149.00 L146.66 C148.70 ▲1.7% │  ← full OHLC + %
│  ├         Vol 4.2M · avg 3.8M               │  ← volume + avg volume (US-5)
│  └ Activity                                  │  ← from position_events (US-4)
│     • Stop raised → 142.90 (20MA)   Aug 18   │
│     • Stop raised → 142.78 (20MA)   Aug 17   │
│     • Entered @ 142.78 · 30sh       Aug 14   │
└─────────────────────────────────────────────┘
```

`closing` card: hero = `⚠ Exit signal · stop hit · modeled fill $167.44 (closed 164.63)`, amber.
Details still available; no action buttons (WS5-4). The existing amber "exit pending" badge stays.

---

## 4. `posCardHtml` — concrete before/after

Current (`docs/index.html` ~5764–5786):

```js
function posCardHtml(p) {
  const ticker = escapeHtml(p.ticker || '');
  const source = escapeHtml((p.meta && p.meta.source) || p.source || 'manual');
  const entryDate = escapeHtml(p.entry_date || p.created_at || '');
  const stateBadge = POS_STATE_BADGE[p.state] || '';
  const entry = parseFloat(p.entry_price);
  const stop = parseFloat(p.current_stop != null ? p.current_stop : p.initial_stop);
  const qty = parseFloat(p.remaining_qty != null ? p.remaining_qty : p.initial_qty);
  const basisLabel = POS_STOP_BASIS_LABEL[p.stop_basis] || p.stop_basis || 'Manual';
  const riskShare = (!isNaN(entry) && !isNaN(stop)) ? entry - stop : NaN;      // ← BUG: labeled "risk"
  const openRisk = (!isNaN(riskShare) && !isNaN(qty)) ? riskShare * qty : NaN; // ← BUG: negative when stop>entry
  return `… _mKv('Risk/sh', …) … _mKv('Open risk', …) …`;
}
```

Target shape (pseudocode — mock in §9 is the visual authority; keep the helper style `_mKv`/`_mNote`):

```js
// Pure, unit-testable. Returns everything the template needs. No DOM, no escaping here.
function posDerive(p) {
  const entry       = parseFloat(p.entry_price);
  const initStop    = parseFloat(p.initial_stop);
  const curStop     = parseFloat(p.current_stop != null ? p.current_stop : p.initial_stop);
  const qty         = parseFloat(p.remaining_qty != null ? p.remaining_qty : p.initial_qty);
  const last        = (p.last_close != null) ? parseFloat(p.last_close) : NaN;   // §5 backend add
  const oneR        = (isFinite(entry) && isFinite(initStop)) ? entry - initStop : NaN;
  const stopMoved   = isFinite(curStop) && isFinite(initStop) && Math.abs(curStop - initStop) > 1e-9;
  const trueBasis   = stopMoved ? (p.trail_basis || 'trailed') : p.stop_basis;   // moved ⇒ engine basis
  const riskFree    = isFinite(entry) && isFinite(curStop) && curStop >= entry;
  const lockedIn    = riskFree ? Math.max(curStop - entry, 0) * qty : 0;
  const hasLast     = isFinite(last);
  const openRisk    = hasLast ? Math.max(last - curStop, 0) * qty : NaN;         // floored ≥ 0, never negative
  const unrealized  = hasLast ? (last - entry) * qty : NaN;
  const plannedRisk = (isFinite(oneR) && isFinite(qty)) ? oneR * qty : NaN;      // US-7 fallback
  return { entry, initStop, curStop, qty, last, oneR, stopMoved, trueBasis,
           riskFree, lockedIn, hasLast, openRisk, unrealized, plannedRisk };
}
```

- `posDerive` is the extraction target for tests (§7) — it's the whole bug surface, pure and
  synchronous. `posCardHtml` becomes a thin renderer over it + `posHeroHtml(state, d)`,
  `posStopMovedHtml(p, d)`, `posDetailsHtml(p, d)`, `posActivityHtml(p)`.
- **Basis map fix:** `POS_STOP_BASIS_LABEL` gains no new keys; the *selection* changes — when
  `stopMoved`, label from `trail_basis` (`'20ma'`/`'50ma'` → `20MA`/`50MA`), prefixed "trailed ·".
- **Never render negative risk anywhere.** `openRisk`/`lockedIn` are floored; the mislabeled
  `riskShare`/`openRisk` rows are deleted.

---

## 5. Backend change (small, shared with WS5-4)

`GET /positions` must return a **last price** per position so the card can compute P&L/open-risk.
Today `listPositions()` (`worker-positions/src/positions.js:157`) is `SELECT * FROM positions` —
no bar join.

**Add** `last_close` (+ `last_bar_date` for the "Today" row / staleness) via a correlated subquery
or LEFT JOIN to the latest `ticker_quotes` row per ticker:

```sql
SELECT p.*,
       q.close      AS last_close,
       q.trade_date AS last_bar_date,
       q.open AS last_open, q.high AS last_high, q.low AS last_low,
       q.close AS last_close, q.change_pct AS last_change_pct, q.volume AS last_volume, q.raw AS last_raw
FROM positions p
LEFT JOIN ticker_quotes q
  ON q.ticker = p.ticker
 AND q.trade_date = (SELECT MAX(trade_date) FROM ticker_quotes q2 WHERE q2.ticker = p.ticker)
WHERE p.user_id = ? AND p.state IN (...)
ORDER BY p.opened_at DESC
```

- `ticker_quotes` is public/user-less (migration 0002) — no tenant leak; join stays inside the
  user-scoped `positions` filter.
- Null-safe: a position with no bar yet → `last_close` NULL → US-7 path. Preserve exactly today's
  columns; only add fields (backward-compatible; the PWA reads new fields defensively).
- **Avg volume** for the "Vol 4.2M · avg 3.8M" row is not a typed column — pull it from the `raw`
  JSON (`Average Volume`, the 84-col held scrape has it). Either parse `raw` client-side (already
  returned) or add a typed `avg_volume` projection server-side. Client-side parse is fine (the field
  is already in the payload once `q.raw` is selected).
- Activity trail: either (a) return the last N `position_events` inline per position, or (b) a new
  `GET /positions/:id/events`. **Recommend (a)** with a bounded `LIMIT` (e.g. last 8) to avoid an
  N+1 fetch on tab load — the trail is short and always wanted when the card expands. Decide in the
  impl plan; (a) is the default unless payload size argues otherwise.
- Tests: extend `worker-positions/test/positions.test.js` — join returns latest bar, null when no
  bar, tenant scoping still holds on the joined query, events bounded.

---

## 6. Stop-moved acknowledgement (US-1) — where does the "✓ Updated" state live?

**Owner decision (2026-08-19): cross-device, server-side.** The owner trades on phone *and* laptop,
so a localStorage ack (per-device) is out — acking on the phone must clear the banner on the laptop.
So v1 is the server field, not the client shortcut:

- **`stop_ack_value REAL` on `positions`** (migration `0004_stop_ack.sql`, applied out-of-band like
  0001–0003). The stop-moved banner + pending-lock tag render whenever
  `current_stop != initial_stop` AND (`stop_ack_value IS NULL` OR `stop_ack_value != current_stop`).
  Acking = owner-bearer `POST /positions/<trade_id>/ack-stop` writing `stop_ack_value = current_stop`.
  A *new* engine stop-move (new `current_stop`) automatically re-raises the banner because the ack
  value no longer equals the current stop — no separate "unack" step.
- **Persist-disjointness (load-bearing, mirror the WS5-3b rule):** `stop_ack_value` is a
  **user-owned** column. The sweep's `persistAdvance()` UPDATE must **never** write it (same
  discipline as `exit_price`/`closed_at` — see `worker-positions/CLAUDE.md` § sweep). Only the
  `ack-stop` route writes it. This keeps the "engine trails the stop; user acks separately" loop
  from clobbering itself. Add a test asserting the sweep leaves `stop_ack_value` untouched.
- Route lives beside the other owner transitions in `src/transitions.js` (anchored regex, below the
  owner-auth gate). Tenant-scoped load → 404; CAS on `state` not needed (idempotent write of a value).

Banner copy names the action + the number: **"Update your broker's stop to $142.90"**, not just a
fact. Rejected alternative: always-show-while-moved (option C) — nags forever.

---

## 7. Testing

- **`tests/test_pwa_positions.py` (Playwright, in `tests.yml --ignore`)** — extend the existing
  mock. New fixtures for each hero state: risk-free+locked (EOG-like), risk-free-at-entry
  (OUST-like), up-stop-below-entry, underwater, closing, and no-last-bar (US-7). Assert: no
  negative risk text anywhere; risk-free chip present when stop≥entry; stop-moved banner + ack;
  true basis label; P&L sign/color; activity trail order.
- **Pure-function unit coverage for `posDerive`** — the mock server can't easily assert arithmetic;
  add a small Node test (or a Playwright `page.evaluate` block) pinning the four numbers for the
  six states, incl. the sign-flip regression (EOG: stop 142.90 > entry 142.78 ⇒ openRisk 0, not
  negative; lockedIn +3.55).
- **Worker:** `positions.test.js` join cases (§5).
- The mock's worker stub must return the new `last_close`/events fields (see docs/CLAUDE.md harness).

---

## 8. Explicitly out of scope → tracked follow-ups (do NOT lose)

- **WS5-4 (Phase 4):** confirm-fill / still-holding action buttons on `closing` cards + push.
  WS5-7 makes `closing` *legible*; WS5-4 makes it *actionable*.
- **WS5-8 (NEW — pre-close read so the owner can act before the bell).** Owner need: learning at
  17:30 (after close) that a stop was hit is useless — they want the read at **~15:30–15:45 ET**,
  with runway to place orders in-hours instead of eating after-hours spreads/slippage. This is a
  correct, owner-driven requirement; the design below is the honest version (an earlier draft of
  this section over-claimed "provisional bars reverse" with no data — retracted).

  **What's actually true, precisely:**
  - **Intraday exits are real at 15:30.** `stop_hit` and `gap_down_below_stop` are events that
    happened the moment price traded through the level — a 15:30 read of them is not "provisional,"
    it's a fact. The last 15 min ≈ the close for a swing trade.
  - **Only close-referenced rules need the final print:** `close_below_50ma` and
    `two_close_below_20ma` reference the *closing* price. At 15:30 they're a read on the
    current (near-final) price, which *may* differ slightly from the 16:00 print. Advisory copy
    should distinguish "your stop is hit right now" (act) from "on track to close below 50MA"
    (heads-up, may firm up at the bell). No claim about how often it flips — we haven't measured it.

  **The non-obvious engineering catch (this is the part worth remembering):**
  - **Idempotency collision.** The sweep guards on `last_advanced_date` — a same-day re-run is a
    no-op. So if a 15:30 run *advanced/mutated* a position, it would stamp today's date and the
    17:30 settled run would **skip it** → the provisional 15:30 state would stick and the settled
    close would never be applied. That is the real reason the 15:30 read must be **advisory-only —
    it computes signals and alerts, writes NO position state, does not stamp `last_advanced_date`.**
    The 17:30 settled run stays the single writer. (Alternative: teach the guard a provisional-vs-
    settled distinction so settled supersedes — more complex, not recommended for v1.)
  - **Held feed timing.** `collect_held.py` scrapes at 17:30. A 15:30 read needs the held tickers
    scraped at 15:30 too — a new held scrape (a `worker-cron` `JOB_SCHEDULE` entry, **not** a new
    Cloudflare trigger; the single-trigger dispatcher makes this cheap). The existing `pre_close`
    (15:30) job scrapes the *picks* universe, not held tickers, so it's a sibling job, not a free
    ride.
  - **Soft dependency on WS5-4 (push).** A 15:30 advisory only reaches the owner in-hours if it can
    *push* — otherwise it just sits in the app until they happen to open it. The in-app surface
    works without push; the "nudge me at 15:30" half wants VAPID (WS5-4). So WS5-8's full value
    lands after WS5-4, though the read/compute can be built independently.

  Independent of WS5-7 (the card renders whatever the worker returns → ~zero card rework to add the
  advisory layer later). **File as its own issue when WS5-7 lands.**
- **#335:** breakeven ratchet close-vs-high taste call.
- **Cross-device stop-ack (§6 option B)** — only if the localStorage v1 proves annoying.

---

## 9. Impl plan + mocks (approval gate)

Build order once the mock is owner-approved:
1. **Backend §5** (join + bounded events) — ships independently, backward-compatible, deployable
   before any PWA change (no user-visible effect until the card reads it).
2. **`posDerive` + renderers §4** behind the existing card — the core bug fix (risk math, true
   basis, hero states).
3. **Stop-moved banner + ack §6** (localStorage v1).
4. **Details / activity / today-bar §3.**
5. **Banner rewrite + release triplet** (`releases.json` + `sw.js` bump — user-facing) + docs
   (`docs/CLAUDE.md` Positions section, README constants if any) + tests §7.

**Mock:** `planning/mocks/ws5-7-positions-card.html` — all six hero states side by side, using the
real live values (EOG/OUST/NVT from 2026-08-18) so the owner reviews against known data. Published
as an Artifact for review (owner directive: mocks reviewed as Artifacts, source committed for
history). **No production code until the mock is approved.**
