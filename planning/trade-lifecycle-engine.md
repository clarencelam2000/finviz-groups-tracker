# Design: Trade Lifecycle Engine (WS5)

Implementation design for the per-position daily state machine that manages a swing trade **after
entry**. Decision record: `knowledge/decisions/ADR-012-trade-lifecycle-engine.md`. Owner-intent
source of truth: `knowledge/cron-lifecycle-ideation-and-alignment.md` § 6. Storage keystone
coupling: `knowledge/decisions/ADR-011-session-dimension.md` § Coupling.

**Framing (do not lose):** swing trader, multi-day holds, daily bars, **no profit targets** —
exits are governed entirely by trailing risk rules and price action. Every rule below is a tunable
config constant, triple-documented per `CLAUDE.md` § "Configurable items."

---

## 1. State machine

```
Watching ──(user confirms fill)──▶ Open ──(first daily advance)──▶ Managing ──(exit rule)──▶ Closed
   │                                                                   │
   └── (setup invalidated before entry) ── discard/expire             └── partial_exit events do NOT
                                                                            change state (reducing qty)
```

- **Watching** — a WS4 ticket the user is tracking but has not entered. Optional; a user may create
  a position directly at Open.
- **Open** — user has confirmed a fill. Entry context is frozen (§ 3).
- **Managing** — the daily engine is advancing the position. Scale-out trims happen here and reduce
  `remaining_qty` **without leaving Managing**.
- **Closed** — fully exited (stop hit, two-close exit, hard-exit, or user manual close).

## 2. Daily inputs (per position, from the held-tickers feed)

Today's daily bar for the ticker: `close, high, low, prev_close, sma20, sma50, sma200, atr`,
plus `days_to_earnings` (reuse of the Focus-scoring `Earnings` parse). All are settled EOD values
from the held-tickers feed (a trading-day-only job on the ADR-010 tick). Morning/provisional
quotes are **not** used to advance a position — only the settled close is (swing framing).

## 3. Frozen-at-entry context (immutable after Open)

| Field | Meaning |
|---|---|
| `entry_price` | the user's **actual fill** (may differ from the computed trigger — the UI must accept it, or all R-math is wrong) |
| `entry_date` | fill date |
| `initial_stop` | the stop chosen at entry (prior-day low / today's low / 20MA / 50MA) |
| `stop_basis` | which of the above `initial_stop` came from |
| `initial_qty` | size at entry (for R and trim math) |

Derived constant for the life of the trade: **`R = entry_price − initial_stop`** (risk per share).
All R-multiples are `(price − entry_price) / R`.

## 4. The daily-advancement algorithm (the heart)

A **pure function** `advance(position, todays_bar) → (new_position, [events])`. Evaluated once per
trading date; **idempotent** per `(trade_id, date)` — re-running the same day with the same bar
produces the same state and emits no duplicate trims (guaranteed by the ledger guards below).
Rules are checked in this order; **exit checks come before stop/trim updates** so a position that
should close today is not first "advanced" and then closed.

```
advance(pos, bar):
  if pos.state == Closed: return (pos, [])            # terminal
  if bar is missing/stale: flag stale, alert, DO NOT advance   # never act on stale data

  # ── EXIT CHECKS (ordered; first match closes the position) ──

  # (a) Stop hit — including honest gap-through
  if bar.low <= pos.current_stop:
      exit_price = (bar.open < pos.current_stop) ? bar.open : pos.current_stop
      #   gap-through: opened below the stop → filled at the open, worse than planned. Report it.
      return close(pos, exit_price, reason = gap? "gap_through_stop" : "stop_hit")

  # (b) Hard-exit override — "really breaks"
  if bar.close < pos.sma50 OR severe_breakdown(bar):     # close under 50MA, or a >SEVERE_BREAKDOWN_ATR
      return close(pos, bar.close, reason = "hard_exit")  #   single-day drop in ATRs

  # (c) Stateful two-close-below-20MA exit
  if bar.close < bar.sma20:
      if pos.caution_flag:                # yesterday's close was also below the 20MA → 2nd consecutive
          return close(pos, bar.close, reason = "two_close_below_20ma")
      else:
          pos.caution_flag = true         # 1st close below → caution, watch next close
          emit caution event
  else:
      pos.caution_flag = false            # any close back at/above 20MA resets the counter

  # ── still Managing: STOP ADVANCEMENT ──

  # profit floor (monotonic non-decreasing) — enforces "once past breakeven, never red again"
  if r_multiple(pos, bar.close) >= BREAKEVEN_R:         # default BREAKEVEN_R = 1.0
      pos.profit_floor = max(pos.profit_floor, pos.entry_price)

  # trailing basis: default 20MA; WIDEN to 50MA once the 50MA has risen above entry
  new_basis = (bar.sma50 > pos.entry_price) ? "50ma" : "20ma"    # policy WIDEN_TRAIL_BASIS
  trail_level = (new_basis == "50ma") ? bar.sma50 : bar.sma20

  if new_basis != pos.trail_basis:        # deliberate one-time widen (may lower the stop, but never below floor)
      pos.current_stop = max(pos.profit_floor, trail_level)
      pos.trail_basis  = new_basis
  else:                                   # within a basis, the stop RATCHETS UP only
      pos.current_stop = max(pos.current_stop, trail_level, pos.profit_floor)

  if pos.current_stop changed: emit stop_moved event

  # ── SCALE-OUT trims (ATR extension from the 50MA) ──
  ext = (bar.close - bar.sma50) / bar.atr          # == atr_ext_50 from picks_metrics.py
  for M in (TRIM_START_ATR .. floor(ext)):         # TRIM_START_ATR = 7 → whole levels 7,8,9,...
      if M > pos.highest_trim_atr:                 # ledger guard → idempotent, never re-trims a level
          trim_qty = pos.remaining_qty * TRIM_PCT  # TRIM_PCT = 0.10 of REMAINING (asymptotic, never 0)
          pos.remaining_qty -= trim_qty
          pos.highest_trim_atr = M
          emit partial_exit event (qty = trim_qty, at_atr = M, price = bar.close)

  # ── EARNINGS guardrail (flag, do not auto-exit) ──
  if pos.days_to_earnings <= EARNINGS_WARN_SESSIONS:
      emit note event "earnings in N sessions — hold-or-exit decision"; push alert
      # engine does NOT auto-close on earnings; the user decides (owner integrates earnings manually)

  return (pos, events)
```

### Why the ordering and the two invariants matter

- **Exit-before-advance** avoids the bug where a position that gapped below its stop still gets its
  stop "trailed up" for the day before being recognized as closed.
- **`profit_floor` is the only monotonic quantity.** `current_stop` intentionally is not — the
  20MA→50MA widen lowers it on purpose. Modeling monotonicity on the *floor* (not the stop) is the
  exact correction the owner made (alignment record § 5.3); a property test should assert
  `profit_floor` never decreases across any bar sequence, and that `current_stop >= profit_floor`
  always.
- **The trim ledger (`highest_trim_atr`)** makes trims idempotent and catch-up-correct: if
  extension jumps from 6.5 to 8.2 ATR in one day, the loop trims once for 7 and once for 8; a
  same-day re-run trims nothing (both levels already ≤ `highest_trim_atr`).

## 5. D1 schema (sketch — field types finalized at implementation)

```sql
CREATE TABLE positions (
  trade_id        TEXT PRIMARY KEY,
  user_id         TEXT NOT NULL,                 -- scoped on EVERY query; app-layer isolation
  ticker          TEXT NOT NULL,
  state           TEXT NOT NULL,                 -- watching|open|managing|closed
  entry_date      TEXT, entry_price REAL, initial_stop REAL, stop_basis TEXT, initial_qty REAL,
  profit_floor    REAL,                          -- monotonic non-decreasing
  current_stop    REAL, trail_basis TEXT,        -- 20ma|50ma
  remaining_qty   REAL,
  caution_flag    INTEGER DEFAULT 0,             -- 1 after a single close below 20MA
  highest_trim_atr INTEGER DEFAULT 0,            -- trim ledger
  days_to_earnings INTEGER,
  opened_at TEXT, closed_at TEXT, exit_price REAL, close_reason TEXT,
  last_advanced_date TEXT,                       -- idempotency guard for the daily run
  meta            TEXT DEFAULT '{}'              -- JSON bag: notes, tags, UI state, future fields
);
CREATE INDEX idx_positions_user_state ON positions(user_id, state);

CREATE TABLE position_events (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  trade_id   TEXT NOT NULL, user_id TEXT NOT NULL,
  ts         TEXT NOT NULL, trade_date TEXT NOT NULL,
  event_type TEXT NOT NULL,                      -- entered|stop_moved|partial_exit|caution|closed|note
  payload    TEXT DEFAULT '{}'                   -- JSON: qty, at_atr, price, reason, message, ...
);
CREATE INDEX idx_events_trade ON position_events(trade_id, ts);
```

User-initiated partial stops (the owner sometimes runs several) are just `partial_exit` events —
they coexist in the ledger with engine-generated trims, so manual and automatic scale-outs share
one history.

## 6. Config constants (triple-documented: in-code comment + README § Configurable parameters + CLAUDE.md)

| Constant | Default | Controls |
|---|---|---|
| `BREAKEVEN_R` | `1.0` | R-multiple at which `profit_floor` ratchets up to entry (breakeven) |
| `WIDEN_TRAIL_BASIS` | `true` | Whether to widen the trail from 20MA to 50MA once 50MA > entry |
| `TRIM_START_ATR` | `7` | First whole ATR-extension-from-50MA level that triggers a trim |
| `TRIM_PCT` | `0.10` | Fraction of **remaining** quantity trimmed at each new whole ATR level |
| `TWO_CLOSE_EXIT` | `2` | Consecutive closes below the 20MA that force a winner's exit |
| `HARD_EXIT_BASIS` | `50ma` | Close below this MA triggers immediate exit regardless of the two-close rule |
| `SEVERE_BREAKDOWN_ATR` | **TBD — owner calibration** | Single-day drop (in ATRs) that counts as "really breaks" for hard-exit |
| `EARNINGS_WARN_SESSIONS` | reuse Focus value | Days-to-earnings at which the guardrail flags/pushes |

## 7. Edge cases (each gets a test)

- **Gap-through stop** — `open < current_stop`: exit at the open, `close_reason = gap_through_stop`,
  report the worse-than-planned fill honestly; never pretend the stop level held.
- **Stale / missing quote** (delisted, feed miss): flag, alert, do **not** advance on stale data.
- **Same-day re-run idempotency**: `last_advanced_date` + the trim ledger + deterministic
  recompute → a second run on the same date is a no-op.
- **Fill ≠ trigger**: R and all downstream math use `entry_price` (the actual fill), never the
  computed trigger.
- **Trim catch-up**: multiple whole ATR levels crossed in one day → one trim per newly crossed
  level; none on re-observation.
- **Deliberate give-back on widen**: after the 20MA→50MA widen, an unrealized +2R can pull back
  toward breakeven if price falls to the 50MA. This is the owner's intended "give proven trades
  room" behavior — **document it visibly**; if the owner later wants tighter profit protection,
  it's a one-constant change (ratchet the floor to a trailing level), not a redesign.
- **Weekend/holiday**: the feed is a trading-day-only job (ADR-010 gating) → no spurious advance.

## 8. UX loop

WS3 confirmation surface shows "TICKER triggered" → user taps **"I took it"**, enters **actual
fill** + chosen **stop** → creates the position (Open, first `entered` event) → the daily engine
advances it → **push** on stop-hit and earnings-approach (VAPID; iOS needs install-to-home-screen).

## 9. Testing plan

- **Pure `advance()` unit tests** — one fixture per rule: stop-hit, gap-through, hard-exit (both
  triggers), first-close-caution, second-close-exit, caution-reset, breakeven ratchet, 20→50 widen,
  within-basis ratchet, trim at 7, trim catch-up 7&8, earnings flag.
- **Property tests** — over random bar sequences: `profit_floor` monotonic non-decreasing;
  `current_stop >= profit_floor` always; `remaining_qty` monotonic non-increasing and > 0.
- **Idempotency test** — advance twice on the same date → identical state, no duplicate events.
- **Isolation test** — a query for user A never returns user B's rows (app-layer scoping).

## 10. Phasing (from ADR-012 — each independently useful)

1. D1 schema + "I took this" write path (spine + first `entered` event).
2. Held-tickers feed (trading-day job on the ADR-010 tick; shares mechanism with WS3 — build once).
3. `advance()` engine + the full test suite above.
4. Push notifications (VAPID; stop-hit + earnings-approach; subscription store in D1).

## 11. Open questions (for the owner / at implementation)

- **`SEVERE_BREAKDOWN_ATR`** needs owner calibration — what single-day drop counts as "really
  breaks" for the discretionary hard-exit? (Or drop it and rely on the close-below-50MA trigger
  alone.)
- **Widen policy** — is the 20MA→50MA widen automatic (as modeled) or a per-position user opt-in?
  Owner said "can widen" — modeled as automatic-with-toggle; confirm.
- **Ticker-quote store location** (CSV vs D1) — the WS2/WS5 shared decision from ADR-011 § Coupling.
- **Breakeven trigger** — ratchet the floor to breakeven at `+1R` (modeled) or at a price close
  above entry by some buffer? Confirm which matches the owner's actual habit.
