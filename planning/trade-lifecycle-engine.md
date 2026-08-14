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

### 3a. Scale-ins / add-on buys = independent lots, grouped for display (owner ruleset, 2026-08-11)

The owner's real style: **each add-on buy is its own independent trade, not an averaging-in.** A
pyramid-add on a fresh breakout gets **its own entry, its own stop under *that* breakout, its own R,
and its own trim ledger** — distinct from the original lot. Blending everything into one
volume-weighted position (single averaged stop that matches neither tranche) is explicitly **not**
what we do; it destroys the per-tranche risk the owner actually manages.

Consequences for this design (deliberately light — the model above already supports it):

- **A "position" row stays exactly as specified** — single entry, single stop, single R, frozen
  per § 3. **Each lot is one `positions` row.** The frozen-at-entry immutability is *correct* here,
  not a limitation: a lot never mutates its entry.
- **`advance()` is unchanged.** It already runs per position; N lots on one ticker are just N
  `advance()` calls sharing that ticker's one daily bar (the feed is keyed `(ticker, trade_date)`,
  so one fetch serves every lot on that symbol — no extra scrape).
- **Nothing may assume one-position-per-ticker.** "I took it" twice on the same symbol already
  creates two independent lots today; phase 1 must simply not add a uniqueness assumption on
  `(user_id, ticker)`.
- **Grouping is a thin display layer:** lots on the same ticker/thesis share a `meta.group_id`
  (JSON bag, no schema cost). The UI packages them into one group showing a **share-weighted average
  entry, summed remaining qty, and summed open risk/heat** — presentation only; every lot keeps its
  own R and stop in the engine. See § 8b for the grouped-position UX and § 13 for the retrace-heat
  view that this grouping feeds.

This is a **UI/aggregation feature on top of an already-correct storage model** — no change to § 3's
invariant, no change to `advance()`. Phase 1 needs only: (a) don't assume one-position-per-ticker;
(b) reserve `meta.group_id`. Tracked as its own issue so the grouping/aggregation UI isn't proposed
cold.

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

**Effective config, not raw globals (LLM/per-position door, § 14).** `advance()` reads its tunables
from an **effective config** = the global constants (§ 6) with any per-position overrides in
`meta` layered on top — passed **in as a parameter**, never read from a global inside the function.
Today every position's overrides are empty, so effective config == the globals. But wiring it this
way from the start keeps `advance()` a pure function of `(position, bar, effective_config)`, so a
future per-position rule ("exit this one below its 30MA") — whether set in the UI or by a later LLM
layer — is a data change, not an engine rewrite. Do **not** hard-code a global lookup in the body.

```
advance(pos, bar, cfg):                                  # cfg = merge(GLOBAL_CONSTANTS, pos.meta overrides)
  if pos.state in (Closed, Closing): return (pos, [])   # terminal / awaiting user's confirmed fill
  if bar is missing/stale: flag stale, alert, DO NOT advance   # never act on stale data

  # ── EXIT CHECKS (ordered; first match SIGNALS the exit → Closing, not Closed) ──
  # On any exit signal we return immediately, so the stop/trim/earnings blocks below never run
  # on an exit day (a test pins this — no trim is emitted on the bar that signals the exit).

  # (a) Stop hit — including honest gap-down
  if bar.low <= pos.current_stop:
      exit_price = (bar.open < pos.current_stop) ? bar.open : pos.current_stop
      #   gap-down: opened below the stop → modeled fill at the open, worse than planned. Report it.
      return signal_exit(pos, exit_price, reason = gap? "gap_down_below_stop" : "stop_hit")

  # (b) Hard-exit override — "really breaks" — TWO distinct reasons, reported separately
  if bar.close < bar.sma50:
      return signal_exit(pos, bar.close, reason = "close_below_50ma")   # slow bleed under the 50MA
  if severe_breakdown(bar):                                             # ≥ SEVERE_BREAKDOWN_ATR one-day drop
      return signal_exit(pos, bar.close, reason = "severe_breakdown")   # a one-day crash

  # (c) Stateful two-close-below-20MA exit
  #   NOTE: this fires even after the trail has WIDENED to the 50MA (price can close below the 20MA
  #   while still above the 50MA stop). That is deliberate: losing the 20MA is a real weakening
  #   signal worth surfacing even on 50MA basis. It signals → Closing → the user taps "still holding"
  #   if they are intentionally giving the trade 50MA room. See § 7 "two-close above the 50MA".
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
  confirmation_status TEXT DEFAULT 'unconfirmed', -- unconfirmed | confirmed | auto (see § 6 auto-confirm)
  last_advanced_date TEXT,                       -- idempotency guard for the daily run
  meta            TEXT DEFAULT '{}'              -- JSON bag: notes, tags, UI state, widen_enabled,
                                                 --   source ('picks'|'manual'), group_id (scale-in
                                                 --   lots, § 3a), per-position rule overrides (§ 14)
);
CREATE INDEX idx_positions_user_state ON positions(user_id, state);

CREATE TABLE position_events (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  trade_id   TEXT NOT NULL, user_id TEXT NOT NULL,
  ts         TEXT NOT NULL, trade_date TEXT NOT NULL,
  -- append-only: corrections are NEW events, never destructive edits (see § 7 "edit/undo a closed position")
  event_type TEXT NOT NULL,                      -- entered|stop_moved|partial_exit|caution|exit_signal|
                                                 --   closed|exit_corrected|reopened|note
  payload    TEXT DEFAULT '{}'                   -- JSON: qty, at_atr, price, reason, message, ...
);
CREATE INDEX idx_events_trade ON position_events(trade_id, ts);

-- Held-tickers quote feed — APPEND-ONLY (one row per ticker per trading date), NOT upsert-latest.
-- Rationale (owner Q, 2026-08-10): keeping the full bar series (a) gives advance() its 2-close
-- lookback naturally, and (b) preserves daily-bar history for OFF-PICKS held names — the one
-- market-data set the committed data/*.csv files don't already have.
-- STORE THE FULL SCRAPE COLUMN SET, not just the fields advance() reads today (owner call,
-- 2026-08-11): the extra columns cost almost nothing (held positions × trading days is a tiny table)
-- and un-stored bar history is the ONE thing you can never backfill — you cannot re-capture a bar you
-- didn't save. Storing wide now is cheap insurance so a future rule variant that needs, say, volume
-- or sma100 can be backtested over real history instead of only going forward. Columns below are the
-- advance() core; widen to the full Finviz/picks scrape set at implementation (see § 12).
CREATE TABLE ticker_quotes (
  ticker     TEXT NOT NULL, trade_date TEXT NOT NULL,
  close REAL, high REAL, low REAL, prev_close REAL,
  sma20 REAL, sma50 REAL, sma200 REAL, atr REAL, days_to_earnings INTEGER,
  -- + the remaining Finviz scrape columns (volume, rel_volume, perf_*, etc.) — full set, cheap
  collected_at TEXT,
  PRIMARY KEY (ticker, trade_date)               -- market data is not user-scoped; no user_id here
);
```

User-initiated partial stops (the owner sometimes runs several) are just `partial_exit` events —
they coexist in the ledger with engine-generated trims, so manual and automatic scale-outs share
one history. `ticker_quotes` carries **no `user_id`** deliberately: a daily bar for a symbol is
public market data, not private state — only *which* symbols are fetched (the union of open
positions) derives from private data, and that selection happens at query time, not in the row.

### 5a. Two separate feeds — the morning picks feed and the held feed

These are **distinct jobs with distinct membership**, and the design must keep them separate:

- **Morning picks feed** (WS3, provisional ~10:05 ET) — *what to consider entering*. Its membership
  is the picks/watch set: yesterday's picks plus **any ticker the user (or, later, an LLM) adds to
  watch**. Example: Monday night the owner adds `AVGO` to watch for a Tuesday-morning entry — it
  joins the morning feed's fetch set even though it was never a screener pick.
- **Held feed** (WS5, settled EOD) — *what you already own*. Its membership is the union of **open
  `positions`** (§ 3), picks-origin or not; it advances trades after entry.

Both feeds are **freely add-able** — a symbol can be pushed into the watch set (morning feed) or
become a held position (held feed) by the user today and by an LLM layer later (§ 14), through the
same ticker-generic paths (§ 8a). A ticker can be in one, both, or neither. The held feed never
depends on the picks list; the morning feed is not limited to screener output. Keep the two
membership queries independent so neither silently constrains the other.

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
| `EXIT_AUTOCONFIRM_SESSIONS` | `5` | Trading sessions a position may sit in `Closing` before it auto-closes at `expected_exit_price` with `confirmation_status = 'auto'` (§ 7 auto-confirm). Long enough that a real "still holding" holder will have interacted; short enough the expectancy record doesn't rot. |
| `AUTO_CLOSE_STRIP_SESSIONS` | `3` | Sessions an *auto*-closed-unconfirmed position keeps showing in the "needs your confirmation" strip (correctable) before it drops to closed history (owner, 2026-08-11). |
| `CAUTION_REARM_ON_HOLD` | `true` | On "still holding," reset `caution_flag` so the two-close rule re-arms (needs two fresh closes), rather than re-signalling on the next single close (owner, 2026-08-11). Two-way door, per-position boolean — flip freely. |

**Widen policy (owner-confirmed 2026-08-07): automatic, with a per-position toggle.** `WIDEN_TRAIL_BASIS = true`
is the global default; each position carries a `widen_enabled` flag (default true, in the `meta` bag) so a user
can opt a single position out of the 20MA→50MA widen without a code change. **Breakeven trigger: `BREAKEVEN_R = 1.0`**
— the floor ratchets to entry at exactly +1R (owner-confirmed, not a price-buffer variant).

**Exit reasons (canonical enum).** `stop_hit`, `gap_down_below_stop`, `close_below_50ma`,
`close_below_20ma`, `severe_breakdown`, `two_close_below_20ma`, `manual_close`. The old bundled
`hard_exit` is **split** into `close_below_50ma` (slow bleed under the 50MA) and `severe_breakdown`
(≥ `SEVERE_BREAKDOWN_ATR` one-day drop) so the honest record and the UI can say *why* (owner,
2026-08-11). `close_below_20ma` is the `HARD_EXIT_BASIS="20ma"` per-position override's immediate
single-close counterpart to `close_below_50ma` — kept distinct from `two_close_below_20ma` (§4c's
stateful two-consecutive-close rule) so the record never claims two closes happened when the
override fired on the first one. Earnings is **not** an exit reason — it only flags/pushes; the
user decides.

## 7. Edge cases (each gets a test)

- **Gap-down below stop** — `open < current_stop`: **signal** exit at the open,
  `exit_reason = gap_down_below_stop`, record it as the *expected* fill and report the
  worse-than-planned price honestly (→ `Closing`); never pretend the stop level held. The user
  confirms the real fill.
- **Editable actual fill on confirm** — "Confirm fill" opens a price field **pre-filled with
  `expected_exit_price`, editable**; the user overwrites it if their real fill differed, then commits
  → `Closed` writes their price to `exit_price` and `confirmation_status = 'confirmed'`. Symmetric
  with entry's "I took it" fill entry. The modeled price is a default, never the recorded truth when
  they differ.
- **"Still holding" override** — user rejects an exit signal from `Closing`: position returns to
  `Managing`; `expected_exit_price`/`exit_signal_date`/`exit_reason` cleared; **`caution_flag` reset
  to `false`** when `CAUTION_REARM_ON_HOLD` (default), so the two-close rule re-arms rather than
  re-signalling on the next single close; a `note` event records the discretionary override. The
  next advance re-evaluates normally (and may re-signal). (For a `stop_hit` override, note the
  position can still re-signal the very next day because `current_stop` is unchanged and price is
  below it — that daily nag is intended, delivered as the *de-escalated* Tier-2 reminder of § 8, not
  a fresh alarm.)
- **Two-close above the 50MA** — after the trail has widened to the 50MA, a close below the 20MA can
  still trigger the two-close exit even though price is above the 50MA stop. **This is deliberate**,
  not a bug: losing the 20MA is a genuine weakening signal. It signals → `Closing`; a user who is
  intentionally giving the trade 50MA room taps "still holding." The `Closing`/"still holding" loop
  absorbs the interaction — we do **not** suppress the soft exit on 50MA basis.
- **Auto-confirm a stuck `Closing`** — a position left in `Closing` for more than
  `EXIT_AUTOCONFIRM_SESSIONS` (5) auto-closes at `expected_exit_price` with
  `confirmation_status = 'auto'`. Never silently wrong: every closed row is labeled, expectancy
  queries can filter `confirmed`-only, and the row stays correctable (below). Price is the one frozen
  at signal time — do **not** re-derive from later bars.
  - *Impl (WS5-3b-ii):* the "sessions in `Closing`" clock is the **global** trading-session
    calendar — `SELECT DISTINCT trade_date FROM ticker_quotes` (the union across every held ticker),
    counted strictly after `exit_signal_date` — not the position's own ticker's bars. Global is
    robust to a one-symbol feed gap understating how long a position has actually been parked. Lead
    reading of "natural session calendar"; owner-ratification item in SPRINT § WS5-3b-OWNER.
- **Edit / undo a closed position** — corrections are **append-only events**, never destructive:
  fixing the exit price on a closed trade emits `exit_corrected` (recompute R from the new price);
  reopening a wrongly-closed trade emits `reopened` (`Closed → Managing`). The original record stays
  in the ledger, auditable. Any closed position is editable — for `AUTO_CLOSE_STRIP_SESSIONS` (3)
  sessions inline in the confirmation strip, and after that from the closed-history view.
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

**In-app "needs your confirmation" pull surface (resolves the missed-push single point of failure).**
The exit loop must not depend on one push landing. If that push is missed (iOS not
installed-to-home, DND, offline), the position would otherwise sit in `Closing` unmanaged. So push is
the **nudge**; the **source of truth** is an in-app surface: whenever the user opens the PWA, every
`Closing` position (plus `auto`-closed-unconfirmed ones for `AUTO_CLOSE_STRIP_SESSIONS` sessions)
shows in a collapsed strip at the top of Positions, with a header/app-icon badge count. Zero items →
not rendered (zero space). Collapsed by default (~64px strip); expand-on-tap reveals each item's
modeled fill, the editable **Confirm fill** / **Still holding** actions, and the auto-confirm
countdown. A close-watching swing trader opens the app daily, so nothing stays invisible longer than
one session. Mock: `planning/mocks/ws5-needs-confirmation-surface.html`.

**Two-tier exit notifications (avoids alert fatigue / cry-wolf).** The initial signal and the
follow-up reminders are **different notification classes** so the high-salience class stays rare and
therefore trusted:

- **Tier 1 — exit signal** (fires once, when `advance()` first signals). High salience, sound/vibrate,
  actionable. *"🚨 Exit signal — VRT. Stop hit at 96.40 (gapped below 98.20). Confirm your fill or
  tap 'still holding'."* Action buttons where the platform supports them.
- **Tier 2 — reminder** (any later day still in `Closing`, and after a "still holding" that keeps
  re-qualifying). Low priority, silent, digest tone, distinct OS channel/tag so it groups separately
  and collapses. *"VRT still below your stop · day 3. 94.10 vs stop 98.20 (−0.9R). No action needed
  if you're holding on purpose. Auto-closes in 2 sessions."* **Decaying cadence** (day 1–2, then
  every other day), ends at auto-confirm; a collapse key so multiple reminders become one digest.

This is what makes the "still holding" daily re-signal a *feature* (it refuses to let a violated stop
go quiet) instead of a nag that trains the user to ignore all exit pushes.

## 8b. Grouped scale-in lots (UX for § 3a)

Independent lots on one ticker (§ 3a) are **packaged into one group card** sharing `meta.group_id`:

- **Header shows the aggregation** — share-weighted average entry, summed remaining qty, and summed
  **open risk/heat** across the group's lots. This is **presentation only**; each lot keeps its own
  R, stop, and trim ledger in the engine.
- **Each lot is expandable** to its own entry/stop/R/state — a user can see and act on tranches
  independently (e.g. one lot in `Closing` while others keep `Managing`).
- **Close actions at two levels** — a **group action** ("close all lots") *and* **per-lot close**.
  The weighted-average line is labeled as a display figure so it's never mistaken for a single
  managed stop.
- **Feeds the retrace-heat view (§ 13)** — the group's summed heat is exactly what the
  "what a pullback to the 20MA/50MA would cost" view reads from.

Detailed layout is **deferred to the eng building this phase** (a mock is not blocking — the storage
and engine are already correct per § 3a); this section is the spec they build to.

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
- **Exit-reason split** — a close under the 50MA reports `close_below_50ma`; a ≥ `SEVERE_BREAKDOWN_ATR`
  one-day drop reports `severe_breakdown`; a gap-down open below the stop reports `gap_down_below_stop`.
- **Caution re-arm** — after "still holding" with `CAUTION_REARM_ON_HOLD`, `caution_flag` is `false`
  and it takes two fresh closes below the 20MA to re-signal (one close alone does not).
- **Two-close above 50MA** — on 50MA basis, two closes below the 20MA while above the 50MA still
  signal `two_close_below_20ma` (the deliberate behavior, not suppressed).
- **Auto-confirm** — a position in `Closing` past `EXIT_AUTOCONFIRM_SESSIONS` closes at
  `expected_exit_price` with `confirmation_status = 'auto'`; earlier it stays `Closing`.
- **Append-only correction** — `exit_corrected` recomputes R without mutating the original event;
  `reopened` returns `Closed → Managing` and the ledger retains both.
- **Independent lots** — two lots on one ticker advance independently off the same daily bar; one
  can be in `Closing` while the other stays `Managing`; group aggregation (avg entry, summed qty,
  summed heat) matches the per-lot sum.
- **Effective config** — a per-position `meta` override (e.g. a different hard-exit MA) changes only
  that position's `advance()` outcome; positions without overrides are unaffected.

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

### 11a. Design-review items (2026-08-10) — resolved 2026-08-11

- **Reminder/nudge for a stuck `Closing` position — RESOLVED.** Covered by the in-app pull surface +
  two-tier notifications (§ 8) and auto-confirm after `EXIT_AUTOCONFIRM_SESSIONS` (§ 6/§ 7): a missed
  push no longer strands a position, and one that's never confirmed auto-closes (labeled, correctable).
- **Feed/catch-up behavior during `Closing` limbo — DECISION.** (1) The held feed **keeps appending**
  bars to `ticker_quotes` for a ticker while its position is in `Closing` — the row is keyed on the
  ticker, not the position state, so there is no data gap. (2) On "still holding," `advance()` **does
  not silently jump to today** — because a position in `Closing` is not advanced, no trim/stop-move is
  skipped in the meantime (nothing fired); on revert it resumes from the current bar. If a future
  design ever advances *through* `Closing`, this must be revisited — flagged in the § 9 tests.

## 12. Backtesting — a NICE-TO-HAVE, not a phase (owner, 2026-08-11)

**Backtesting the *feature* is explicitly deferred. What is *not* deferred is the cheap data
capture that keeps it possible** — because that capture is the only irreversible part:

- **Two decisions are one-way doors** (lose data you can't recover): the feed is **append-only** (not
  latest-bar-only) and stores the **full scrape column set** (not just the 8 fields `advance()` reads,
  § 5). Both are nearly free on a tiny table. **Keep both regardless of whether a backtester is ever
  built** — you can add compute later; you can never re-capture a bar you didn't store.
- **Everything else is deferrable compute** with zero data loss: the replay harness,
  `scripts/export_positions.py` (`wrangler d1 export` → SQLite for pandas), any UI.

**Honest scope of what `ticker_quotes` can back**, when built (do not oversell it):
- ✅ **Trade-outcome / expectancy** (win rate, R-distribution, MAE/MFE — the "honest record" of
  alignment § 8): the append-only `position_events` ledger + closed `positions` rows *are* this
  dataset, by construction.
- ✅ **Exit-rule-variant replay over trades you actually took** (e.g. re-run with `TRIM_START_ATR = 6`),
  within each trade's real holding window, using the stored bar's fields. `advance()` being a **pure
  function** makes replay the same code path as live advancement.
- ❌ **NOT a general strategy backtester.** `ticker_quotes` holds bars only for tickers you held, only
  while held. So it cannot do counterfactual *entries*, the *unentered universe*, or *post-exit
  continuation* (a variant that would exit later than reality has no bars past your actual exit).
  Entry price is a single realized fill, so entry-logic variants aren't testable either.

**Selection-bias mitigation is DEFERRED** (owner, 2026-08-11): widening the held feed to store bars
for *un-taken picks* was considered and **rejected for now** — there are many picks per day and
per-ticker `t=SYMBOL` scraping across all of them would multiply Finviz/Cloudflare load for data we
may never use. If a true strategy backtester is ever wanted, pull history from a **bulk OHLCV provider
(e.g. Alpaca)** rather than fattening the live scraper, and read it through a **pluggable bar source**
so the engine's live truth stays on `ticker_quotes` (Alpaca free = IEX, won't perfectly match
Finviz SMAs/ATR — backtest-only, never the live engine). Keeping backtest data capture and the live
scraper decoupled is the point.

## 13. Retrace-to-MA risk awareness (owner, 2026-08-11)

Owner's hard-won lesson: **unrealized profit is exposure, not safety.** Real losses came from
(a) sizing add-on buys too large, (b) not seeing that the more extended a position is above its 50MA,
the more a normal retrace *to* that MA costs, and (c) add-ons at higher prices dragging the
group's cost basis up so a pullback that "should" have been fine turns a green trade red. Trader
framing to encode: *"your unrealized profits belong to the market"*; *"your real equity is where
you'd be if stopped out at your MA"*; *"a pullback to the 20MA/50MA is normal, even healthy — your
sizing should survive it."*

**The engine already has every number to make this visible — it's a display, not new logic.** For
any position or group, given today's bar:

- **Retrace-to-MA give-back** = `(close − sma20) × remaining_qty` and `(close − sma50) × remaining_qty`
  — the dollars handed back if price fell to the 20MA / 50MA today. Show per lot and summed per group.
- **Extension gauge** = `atr_ext_50 = (close − sma50) / atr` (the same value the trim rule uses). The
  larger it is, the bigger the 50MA-retrace give-back — surface it as the "how exposed am I to a
  normal pullback" reading, not just a trim trigger.
- **Equity-at-MA** = mark the position's value *as if* stopped at the 20MA/50MA, next to the mark at
  today's close — makes "profits belong to the market" literal.
- **Heat** (already in the aggregate footer) = `Σ(entry − current_stop) × qty` — the realized-risk
  floor. Pair it with the retrace-to-MA figures so the user sees both "risk if stopped" and
  "give-back if it just breathes back to its average."

**Mitigations this enables (information, never forced):**
1. **Size-aware add-on check** — when adding a lot, show the *new group* retrace-to-50MA give-back
   and extension so an oversized add at a stretched price is visible *before* the buy.
2. **Extended-position flag** — when `atr_ext_50` is high (near/into trim territory), badge the
   position "extended — a 50MA retrace gives back \$X"; this is the same signal the trim rule acts on,
   surfaced for the human.
3. **Group cost-basis drift** — show how each add-on moved the group's weighted-avg entry up, so the
   "higher adds make a pullback worse" effect is explicit.

All three read from existing fields (`close, sma20, sma50, atr, entry, current_stop, qty`) — no new
storage, no new engine rule. Framed as **information, never "diversify"/"trim now"** advice, matching
the aggregate-exposure footer's tone (alignment § 10). A mock and exact thresholds are deferred to the
phase that builds the position/group card; captured here so it's specced, not proposed cold.

## 14. Extensibility door: per-position rules and a future LLM layer

The write path is already ticker-generic and payload-based (§ 8a), so a natural-language "I bought X
at Y, stop Z, manage it and ping me on …" layer is just a **third caller** of the same create path
(picks ticket, manual form, LLM — one door). Two cheap disciplines keep the door open, both free now:

- **`advance()` reads *effective config*, passed in** (§ 4): global constants merged with per-position
  `meta` overrides. Empty for every position today, but wiring it this way means a per-position rule
  ("exit this one below its 30MA") — set in the UI or by an LLM — is a **data change, not an engine
  rewrite**. Never hard-code a global lookup inside `advance()`.
- **Lots are independent positions** (§ 3a): the engine already handles N positions per ticker, so an
  LLM adding a tranche is the same additive path as a manual add — no single-entry assumption to undo.

The append-only `position_events` ledger is also an ideal LLM **read** substrate (summarize a trade,
explain a stop move, portfolio Q&A). Broader LLM directions are captured in a tracking issue, not
specced here. The only forward-looking traps to avoid are the two above — both cost nothing today and
are expensive to retrofit.
