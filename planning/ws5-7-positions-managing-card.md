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
else:                                       hero = unrealized P&L (green/red)                 [US-3]
                                            subline = "Open risk $O to stop"
```

Everything in the table §2 is available under **Details ▾** regardless of state (US-8).

**Rounding/format:** dollars `$X` (whole) for totals ≥ $100, `$X.XX` below; per-share always 2dp;
P&L carries sign and color (`text-emerald-400` / `text-red-400`); risk-free uses emerald.

---

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
│ Details ▾                                    │  ← collapsed by default
│  ├ Entry      $142.78    Qty      30         │
│  ├ Stop       $142.90    (trailed · 20MA)    │  ← true basis, not initial
│  ├ 1R (init)  $2.30/sh   Open risk  $174     │
│  ├ Today      148.70  ▲1.7%  (146.66–149.00) │  ← latest bar (US-5)
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
       q.high AS last_high, q.low AS last_low, q.change_pct AS last_change_pct
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
- Activity trail: either (a) return the last N `position_events` inline per position, or (b) a new
  `GET /positions/:id/events`. **Recommend (a)** with a bounded `LIMIT` (e.g. last 8) to avoid an
  N+1 fetch on tab load — the trail is short and always wanted when the card expands. Decide in the
  impl plan; (a) is the default unless payload size argues otherwise.
- Tests: extend `worker-positions/test/positions.test.js` — join returns latest bar, null when no
  bar, tenant scoping still holds on the joined query, events bounded.

---

## 6. Stop-moved acknowledgement (US-1) — where does the "✓ Updated" state live?

Three options; pick in impl plan:

- **(A) Client-only (localStorage), recommended for v1.** Key `posStopAck:<trade_id>:<curStop>`.
  Acknowledging writes the key; the banner shows only when no ack exists for the *current* stop
  value, so a new move (new `curStop`) re-raises it automatically. Zero backend/schema work, ships
  with the card. Downside: per-device (ack on phone doesn't clear on laptop) — acceptable for a
  single-user tool; the engine state is unaffected either way.
- **(B) Server field** `stop_ack_value` on `positions` — cross-device, but a schema migration +
  route + the sweep must never clobber it (mirror the persist-column-disjointness rule). Heavier.
- **(C) None — always show the banner while `current_stop != initial_stop`.** Simplest, but nags
  forever. Rejected.

**Recommendation: (A) for v1**, note (B) as a follow-up if cross-device ack is wanted. The banner
copy must name the action ("Update your broker's stop to $142.90"), not just state the fact.

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
- **WS5-8 (NEW — pre-close advisory read):** a **15:30 ET provisional** evaluation of held
  positions that *warns* on an intraday exit signal ("OUST trading below your stop, ~30 min left")
  **without mutating state**. Keeps the 17:30 settled run as source of truth (never reschedule it —
  `advance()` is defined on settled closes; a provisional bar reverses in the last 30 min). Reuses
  the existing `pre_close` session infra (WS3b/#268). Independent of WS5-7: the card renders
  whatever the worker returns, so this adds an advisory layer later with ~zero card rework. **File
  as its own issue when WS5-7 lands.**
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
