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
Watching ─(user confirms fill)─▶ Open ─(first advance)─▶ Managing ─(exit signal)─▶ Closing ─(user confirms fill)─▶ Closed
   │                                                          │                        │
   └─ (invalidated before entry) ─ discard/expire            └─ partial_exit events    └─ "still holding" ⇒ back to
                                                                do NOT change state         Managing (discretionary override)
                                                                (reducing qty)
```

- **Watching** — a WS4 ticket the user is tracking but has not entered. Optional; a user may create
  a position directly at Open.
- **Open** — user has confirmed a fill. Entry context is frozen (§ 3).
- **Managing** — the daily engine is advancing the position. Scale-out trims happen here and reduce
  `remaining_qty` **without leaving Managing**.
- **Closing** — the engine has detected an exit condition and recorded the **modeled** exit price as
  *expected*, but the position is **not yet closed**. Symmetric with entry: just as `entry_price` is
  the user's *actual* fill (not the computed trigger), the exit is the user's *actual* fill (not the
  modeled stop/close). The user confirms the real fill → **Closed**, or taps **"still holding"**
  (a discretionary override — e.g. they judge the break a fake-out) → back to **Managing**. This is
  the owner decision of 2026-08-07 (alignment § 10) and resolves the two staff findings on #264:
  (1) exits were asymmetric with entries on fill-truth, and (2) *signal-close vs execution-close* —
  the engine runs **after** the close, so the modeled exit is a **signal**; the real-world fill is
  next session's open at earliest. `Closing` makes the exit-signal date and the execution fill two
  distinct facts, which the honest R-multiple / expectancy record depends on.
- **Closed** — fully exited, at the user's **confirmed** exit fill (stop hit, two-close exit,
  hard-exit, or manual close). `exit_price` is the confirmed fill, never the modeled price.

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
should exit today is not first "advanced" and then signalled to exit.

**Exit semantics (owner decision, alignment § 10):** an exit check does **not** move the position
to `Closed`. It moves it to **`Closing`** with the modeled price recorded as the *expected* fill,
and emits an `exit_signal` event. The position only reaches `Closed` when the user confirms their
actual fill (or reverts to `Managing` via "still holding"). `signal_exit(pos, price, reason)` below
is that transition — it never writes `exit_price`; only the user's confirmation does. A position
already in `Closing` is not re-advanced (it is waiting on the user), same as `Closed`.

```
advance(pos, bar):
  if pos.state in (Closed, Closing): return (pos, [])   # terminal / awaiting user's confirmed fill
  if bar is missing/stale: flag stale, alert, DO NOT advance   # never act on stale data

  # ── EXIT CHECKS (ordered; first match SIGNALS the exit → Closing, not Closed) ──
  # On any exit signal we return immediately, so the stop/trim/earnings blocks below never run
  # on an exit day (a test pins this — no trim is emitted on the bar that signals the exit).

  # (a) Stop hit — including honest gap-through
  if bar.low <= pos.current_stop:
      exit_price = (bar.open < pos.current_stop) ? bar.open : pos.current_stop
      #   gap-through: opened below the stop → modeled fill at the open, worse than planned. Report it.
      return signal_exit(pos, exit_price, reason = gap? "gap_through_stop" : "stop_hit")

  # (b) Hard-exit override — "really breaks"
  if bar.close < bar.sma50 OR severe_breakdown(bar):        # close under 50MA, or a >SEVERE_BREAKDOWN_ATR
      return signal_exit(pos, bar.close, reason = "hard_exit")  #   single-day drop in ATRs

  # (c) Stateful two-close-below-20MA exit
  if bar.close < bar.sma20:
      if pos.caution_flag:                # yesterday's close was also below the 20MA → 2nd consecutive
          return signal_exit(pos, bar.close, reason = "two_close_below_20ma")
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
  state           TEXT NOT NULL,                 -- watching|open|managing|closing|closed
  entry_date      TEXT, entry_price REAL, initial_stop REAL, stop_basis TEXT, initial_qty REAL,
  expected_exit_price REAL, exit_signal_date TEXT, exit_reason TEXT,  -- set on Managing→Closing (modeled, awaiting confirm)
  profit_floor    REAL,                          -- monotonic non-decreasing
  current_stop    REAL, trail_basis TEXT,        -- 20ma|50ma
  remaining_qty   REAL,
  caution_flag    INTEGER DEFAULT 0,             -- 1 after a single close below 20MA
  highest_trim_atr INTEGER DEFAULT 0,            -- trim ledger
  days_to_earnings INTEGER,
  opened_at TEXT, closed_at TEXT, exit_price REAL,  -- exit_reason (above) carries the reason through to Closed
  last_advanced_date TEXT,                       -- idempotency guard for the daily run
  meta            TEXT DEFAULT '{}'              -- JSON bag: notes, tags, UI state, widen_enabled,
                                                 --   source ('picks'|'manual'), future fields
);
CREATE INDEX idx_positions_user_state ON positions(user_id, state);

CREATE TABLE position_events (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  trade_id   TEXT NOT NULL, user_id TEXT NOT NULL,
  ts         TEXT NOT NULL, trade_date TEXT NOT NULL,
  event_type TEXT NOT NULL,                      -- entered|stop_moved|partial_exit|caution|exit_signal|closed|note
  payload    TEXT DEFAULT '{}'                   -- JSON: qty, at_atr, price, reason, message, ...
);
CREATE INDEX idx_events_trade ON position_events(trade_id, ts);

-- Held-tickers quote feed — APPEND-ONLY (one row per ticker per trading date), NOT upsert-latest.
-- Rationale (owner Q, 2026-08-10): keeping the full bar series (a) gives advance() its 2-close
-- lookback naturally, and (b) preserves daily-bar history for OFF-PICKS held names — the one
-- market-data set the committed data/*.csv files don't already have (picks tickers already have
-- rich CSV history). Together with position_events (what happened) and closed positions (outcomes),
-- this makes D1 a complete substrate for BOTH trade-outcome backtesting and hypothetical rule-variant
-- replay. Tiny: open positions × trading days ≈ a few rows/day, well within D1 free-tier limits.
-- `wrangler d1 export` dumps it to SQLite for pandas, mirroring scripts/export_db.py for the CSVs.
CREATE TABLE ticker_quotes (
  ticker     TEXT NOT NULL, trade_date TEXT NOT NULL,
  close REAL, high REAL, low REAL, prev_close REAL,
  sma20 REAL, sma50 REAL, sma200 REAL, atr REAL, days_to_earnings INTEGER,
  collected_at TEXT,
  PRIMARY KEY (ticker, trade_date)               -- market data is not user-scoped; no user_id here
);
```

User-initiated partial stops (the owner sometimes runs several) are just `partial_exit` events —
they coexist in the ledger with engine-generated trims, so manual and automatic scale-outs share
one history. `ticker_quotes` carries **no `user_id`** deliberately: a daily bar for a symbol is
public market data, not private state — only *which* symbols are fetched (the union of open
positions) derives from private data, and that selection happens at query time, not in the row.

## 6. Config constants (triple-documented: in-code comment + README § Configurable parameters + CLAUDE.md)

| Constant | Default | Controls |
|---|---|---|
| `BREAKEVEN_R` | `1.0` | R-multiple at which `profit_floor` ratchets up to entry (breakeven) |
| `WIDEN_TRAIL_BASIS` | `true` | Whether to widen the trail from 20MA to 50MA once 50MA > entry |
| `TRIM_START_ATR` | `7` | First whole ATR-extension-from-50MA level that triggers a trim |
| `TRIM_PCT` | `0.10` | Fraction of **remaining** quantity trimmed at each new whole ATR level |
| `TWO_CLOSE_EXIT` | `2` | Consecutive closes below the 20MA that force a winner's exit |
| `HARD_EXIT_BASIS` | `50ma` | Close below this MA triggers immediate exit regardless of the two-close rule |
| `SEVERE_BREAKDOWN_ATR` | `3.0` | Single-day drop (in ATRs) that counts as "really breaks" for hard-exit. Owner-set 2026-08-07 (1 ATR = noise, ~2 = bad day, 3+ = "something broke"); recalibrate after real triggers. Phase 3 may ship relying on the close-below-50MA hard-exit alone and add this later. |
| `EARNINGS_WARN_SESSIONS` | reuse Focus `EARNINGS_IMMINENT_DAYS`/`EARNINGS_CAUTION_DAYS` | Days-to-earnings at which the guardrail flags/pushes |

**Widen policy (owner-confirmed 2026-08-07): automatic, with a per-position toggle.** `WIDEN_TRAIL_BASIS = true`
is the global default; each position carries a `widen_enabled` flag (default true, in the `meta` bag) so a user
can opt a single position out of the 20MA→50MA widen without a code change. **Breakeven trigger: `BREAKEVEN_R = 1.0`**
— the floor ratchets to entry at exactly +1R (owner-confirmed, not a price-buffer variant).

## 7. Edge cases (each gets a test)

- **Gap-through stop** — `open < current_stop`: **signal** exit at the open,
  `exit_reason = gap_through_stop`, record it as the *expected* fill and report the worse-than-planned
  price honestly (→ `Closing`); never pretend the stop level held. The user confirms the real fill.
- **"Still holding" override** — user rejects an exit signal from `Closing`: position returns to
  `Managing`, `expected_exit_price`/`exit_signal_date`/`exit_reason` cleared, a `note` event records
  the discretionary override. The next advance re-evaluates normally (and may re-signal).
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
advances it → on an exit signal the position enters **Closing** and the user is **pushed** to
**confirm the exit fill** (or "still holding") → **Closed** on confirmation. Earnings-approach also
pushes (VAPID; iOS needs install-to-home-screen).

## 8a. Extensibility: the position is the root entity (not the picks row)

Owner "think big" (2026-08-10): eventually let the user open a position on **any** ticker they type,
not only a pre-filtered pick. **The design already supports this** — and building phase 1 the right
way costs nothing extra:

- **The held-tickers feed is driven by the `positions` table, not the picks list** (ADR-012 § 3).
  The moment a position exists for a symbol, the feed fetches it — picks-origin or not. Finviz's
  `t=SYMBOL` screener filter (already used by `collect_morning.fetch_ticker_quotes`) works for any
  symbol, so the scrape generalizes for free.
- **The phase-1 "I took it" write path MUST be ticker-generic:** it accepts
  `{ticker, entry_price, initial_stop, stop_basis, qty}`. The WS4 picks ticket is just *one caller*
  that pre-fills that payload from a picks row; a future manual-entry form is a *second caller*
  filling the same payload. Do **not** key the create path on a picks-row identity — that would make
  arbitrary tickers a migration instead of a UI addition.
- Provenance is recorded as `meta.source = 'picks' | 'manual'` (JSON bag, no schema cost) so the UI
  can style/annotate origin without a column. A manual entry simply has no pre-computed stop menu
  until the feed lands its first bar (the 20MA/50MA stops then become available from `ticker_quotes`);
  it **degrades gracefully**, exactly like the WS4 ticket's existing no-EOD-match degrade path.

This future feature therefore needs **no ADR-012 storage change** — it is deferred UI work on top of
a phase-1 write path that is already ticker-generic. Tracked as a note here so it isn't proposed cold.

## 9. Testing plan

- **Pure `advance()` unit tests** — one fixture per rule: stop-hit, gap-through, hard-exit (both
  triggers), first-close-caution, second-close-exit, caution-reset, breakeven ratchet, 20→50 widen,
  within-basis ratchet, trim at 7, trim catch-up 7&8, earnings flag.
- **Exit-signal (`Closing`) tests** — every exit path lands in `Closing` with `expected_exit_price`
  set and `exit_price` **unset**; a position in `Closing` (or `Closed`) is a no-op on re-advance;
  **no trim/stop-move event is emitted on the bar that signals an exit** (pins the ordered-return
  guarantee); confirm-fill → `Closed` writes the user's price to `exit_price` (≠ modeled when they
  differ); "still holding" → back to `Managing` with the expected-exit fields cleared and re-signals
  on a later qualifying bar.
- **Property tests** — over random bar sequences: `profit_floor` monotonic non-decreasing;
  `current_stop >= profit_floor` always; `remaining_qty` monotonic non-increasing and > 0.
- **Idempotency test** — advance twice on the same date → identical state, no duplicate events.
- **Isolation test** — a query for user A never returns user B's rows (app-layer scoping).
- **Ticker-generic write-path test** — a `manual`-source position (no picks row) is created,
  advanced, and appears in the held-tickers feed selection, identical to a `picks`-source one.

## 10. Phasing (from ADR-012 — each independently useful)

1. D1 schema + "I took this" write path (spine + first `entered` event).
2. Held-tickers feed (trading-day job on the ADR-010 tick; shares mechanism with WS3 — build once).
3. `advance()` engine + the full test suite above.
4. Push notifications (VAPID; stop-hit + earnings-approach; subscription store in D1).

## 11. Decisions resolved (was "open questions") — owner sign-off 2026-08-07 / 2026-08-10

All four implementation questions are now closed; recorded here so they aren't re-litigated:

- **`SEVERE_BREAKDOWN_ATR` = 3.0** ✅ (owner, 2026-08-07). Recalibrate after real triggers; phase 3
  may ship on the close-below-50MA hard-exit alone and add this later.
- **Widen policy = automatic, per-position toggle** ✅ (owner, 2026-08-10). `WIDEN_TRAIL_BASIS = true`
  global default + `meta.widen_enabled` per position.
- **Breakeven trigger = +1R** ✅ (owner, 2026-08-10). `BREAKEVEN_R = 1.0`; not a price-buffer variant.
- **Ticker-quote store = D1, append-only** ✅ (stream-owner call, 2026-08-10; owner-endorsed; ADR-011
  § Coupling). `ticker_quotes(ticker, trade_date)` append-only (§ 5) — not the latest-bar-only shape
  ADR-012 originally implied. Chosen because the feed's only consumer is the D1-resident engine
  (reading a committed CSV *from a Worker* is the awkward path), the held set derives from D1
  positions, and append-only preserves off-picks bar history as a backtest substrate. Accepted cost:
  the GitHub-Actions scraper needs an **authenticated write path into D1** (Worker ingest endpoint or
  D1 HTTP API + a GH secret) instead of a `git commit` — paid once, and needed anyway for the
  "I took it" write and push-subscription store.

### 11a. New open items (design-review pass, 2026-08-10)

Surfaced reviewing this PR; not blockers for phase 1 (D1 schema + write path), but must be
resolved before phase 3 (`advance()` engine) is built — otherwise they get silently assumed away:

- **No reminder/nudge for a stuck `Closing` position.** Today's design sends exactly one push
  when the exit signal fires, then `advance()` goes inert for that position (§ 4: `Closing` is a
  terminal no-op like `Closed`). If the user misses that one push, the position sits unmonitored
  indefinitely while they believe the engine is still managing it — the confirmed-fill model only
  holds if confirmation actually happens promptly. `exit_signal_date` is already stored, so a
  reminder job (re-push if `state == Closing` for more than N days) costs nothing schema-wise to
  add — but needs to be decided and specced (cadence, N) before phase 4 (push notifications) ships.
- **Undefined feed/catch-up behavior during multi-day `Closing` limbo.** § 2 doesn't say which
  position states the held-tickers feed query includes. Two open questions this leaves unresolved:
  (1) does the feed keep appending bars to `ticker_quotes` for a ticker while its position sits in
  `Closing`, or does it stop — the latter opens a data gap in the backtest substrate right at the
  trade's most important moment; (2) when the user eventually taps "still holding," does
  `advance()` catch up over the bars from every skipped day, or jump straight to today's, silently
  skipping any trim/stop-move that should have fired in between? Needs a decision before § 4/§ 9
  are implemented.

## 12. Backtesting (owner Q, 2026-08-10)

D1 supports **both** backtest modes, provided the feed is append-only (§ 5):
- **Trade-outcome / expectancy** (win rate, R-distribution, MAE/MFE — the "honest record" of
  alignment § 8): the append-only `position_events` ledger + closed `positions` rows *are* this
  dataset, by construction.
- **Hypothetical rule-variant replay** (re-run `advance()` over historical bars with, say,
  `TRIM_START_ATR = 6`): needs a daily-bar time series. `ticker_quotes` provides it for held names;
  picks tickers already have rich history in `data/picks/`. Because `advance()` is a **pure
  function**, replaying it over stored bars is exactly the same code path as live advancement.
- **Export**: `wrangler d1 export` → SQLite for pandas, mirroring `scripts/export_db.py`. A
  `scripts/export_positions.py` (out of scope now) could formalize this when backtesting is picked up.
