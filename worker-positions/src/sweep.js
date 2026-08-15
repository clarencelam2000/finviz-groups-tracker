// The D1-touching CALLER of the pure engine in advance.js — WS5 phase 3b (SPRINT WS5-3b).
//
// advance.js (phase 3a) is deliberately pure: no D1, no network, no clock. Everything in THIS file
// is the wiring that makes it run for real — load a position + its trailing ticker_quotes bars,
// fold advance() over them, and persist the result with a DB-layer idempotency guard. Nothing here
// re-implements engine logic; every rule decision still lives in advance.js.
//
// Design: planning/trade-lifecycle-engine.md §4 (algorithm), §5 (schema), §7 (edge cases),
// ADR-012, SPRINT WS5-3b.

import { advance, autoConfirm, normalizeBar, effectiveConfig, ENGINE_CONFIG } from "./advance.js";
import { persistTransition } from "./transitions.js";
import { etDateStr, isoUtc } from "./time.js";

// ── Configurable constants (triple-documented: here + README § Configurable parameters +
// worker-positions/CLAUDE.md — see this repo's 3-places rule, CLAUDE.md § Code quality).
export const SWEEP_CONFIG = Object.freeze({
  // The most bars ONE position may advance through in a single sweep() call. The sweep is a
  // catch-up FOLD over every bar since last_advanced_date, so a long feed outage (or the very
  // first sweep after bars have been quietly accumulating with no caller) could otherwise replay
  // months of history in a single request — unbounded work per invocation, unbounded D1 batch
  // size, unbounded time inside one Worker request. Capping it bounds the work; the position's
  // last_advanced_date simply lands wherever the cap left off, and the NEXT sweep continues from
  // there (barWindowStart reads last_advanced_date fresh each call). Raise this only for a
  // deliberate one-off backfill, then lower it back — it is not meant to be a permanent dial.
  MAX_CATCHUP_BARS: 30,

  // States loadAdvanceablePositions() will pick up. `closing` and `closed` are deliberately
  // EXCLUDED: `closing` is awaiting the user's confirmed fill (confirmExit) or a "still holding"
  // revert (stillHolding) — advance() itself already no-ops on it (NON_ADVANCING_STATES in
  // advance.js), so including it here would just mean loading bars for a position we then throw
  // away. Scoping the query to only advanceable states keeps the sweep's D1 read volume
  // proportional to what can actually move, not to the full historical position count.
  ADVANCEABLE_STATES: ["open", "managing"],
});

// ── barWindowStart(pos) — PURE. The exclusive lower bound on trade_date this position may
// advance through this sweep. ──────────────────────────────────────────────────────────────────
//
// The bound is the lexicographic MAX of last_advanced_date, entry_date, and opened_at's ET trading
// date. All three are (or reduce to) 'YYYY-MM-DD' strings, and that format sorts identically under
// string comparison and date comparison, so a plain string max() is correct without parsing any of
// them into a Date.
//
// WIRING-LAYER RULES, not in the design doc (lead decisions, 2026-08-13): entry_date and opened_at
// are included in the floor ON PURPOSE.
//
// (1) entry_date: a position must never be advanced on its own entry-day bar, because that day's
// `low` (and often `open`) is largely PRE-PURCHASE — the low can easily sit below the entry fill's
// initial stop for reasons that have nothing to do with the trade (e.g. the stock dipped before the
// entry print that afternoon). Advancing on the entry-day bar would risk firing a false `stop_hit`
// on the very day the user bought, before the engine has any business judging the trade.
//
// (2) opened_at (ET trading date): closes a gap the §8a backdated-entry feature (positions.js
// buildPositionRow) opened. entry_date can now be an owner-supplied date in the past, but
// ticker_quotes is a GLOBAL, un-scoped-by-position feed (quotes.js heldTickers) — if the ticker was
// already being fed (held by any other position, this user's or, in a multi-user future, another's)
// during the backdated window, bars already sit in ticker_quotes for dates the position never
// actually lived through. Without this floor, the very first sweep after a backdated create would
// fold advance() over that pre-existing history in one shot — a genuine retroactive replay (false
// stop-hits/trims off historical closes) — contradicting the explicit design promise that "a
// backdate is a label, not a replay" (planning/trade-lifecycle-engine.md §8a). For an ordinary
// (non-backdated) position entry_date already equals opened_at's ET date, so this floor is a no-op
// there; it only ever binds when entry_date is backdated behind the position's real creation time.
//
// The bound is strictly EXCLUSIVE (bar.trade_date > start, not >=), so the first bar the engine
// ever sees for a position is the session strictly AFTER all three floors.
//
// Returns null only when BOTH last_advanced_date and entry_date are absent — a position with no
// entry_date at all is a data-integrity gap the sweep orchestrator skips outright (see sweep()).
export function barWindowStart(pos) {
  const a = pos && pos.last_advanced_date;
  const b = pos && pos.entry_date;
  if (!a && !b) return null;
  let start = !a ? b : !b ? a : a > b ? a : b;
  const opened = pos && pos.opened_at ? etDateStr(new Date(pos.opened_at)) : null;
  if (opened && opened > start) start = opened;
  return start;
}

// ── advanceThroughBars(pos, rows, cfg) — PURE, no I/O. ────────────────────────────────────────
// Folds advance() over `rows` (raw ticker_quotes rows, ASCENDING trade_date order), normalizing
// each row to a bar first. Returns everything the wiring layer needs to decide whether/what to
// persist, without itself touching D1.
export function advanceThroughBars(pos, rows, cfg = ENGINE_CONFIG) {
  let current = pos;
  const events = [];
  let barsAdvanced = 0;
  let staleBars = 0;

  for (const row of rows) {
    const bar = normalizeBar(row);
    const result = advance(current, bar, cfg);
    current = result.position;

    // Stamp trade_date on every emitted event HERE, not inside advance.js — advance() is a pure
    // function of (pos, bar, cfg) and doesn't know which bar produced which event once folded
    // over a sequence; the ledger column position_events.trade_date is NOT NULL, so every event
    // needs a date, and the correct one is the date of the bar that produced it (not "today").
    for (const ev of result.events) {
      events.push({ ...ev, trade_date: bar.trade_date });
    }

    if (result.stale) {
      // A stale/missing bar never stamps last_advanced_date (see advance.js) — so it must not
      // count toward barsAdvanced either, and the loop simply moves on to the next bar. A later
      // good bar in this same sweep still advances normally from wherever last_advanced_date was
      // before the stale bar (i.e. unmoved by it).
      staleBars++;
      continue;
    }

    barsAdvanced++;

    // An exit signal moved the position out of the advanceable states (open/managing → closing).
    // Every later bar in `rows` would be a no-op against advance()'s own NON_ADVANCING_STATES
    // guard, so breaking here just makes that explicit instead of silently iterating do-nothing
    // calls — and it's what keeps events from a bar strictly after the exit-signal bar out of the
    // ledger (pinned by a sweep.test.js case: no event carries a later bar's trade_date).
    if (!SWEEP_CONFIG.ADVANCEABLE_STATES.includes(current.state)) break;
  }

  return {
    position: current,
    events,
    barsAdvanced,
    staleBars,
    advancedTo: current.last_advanced_date,
  };
}

// ── loadAdvanceablePositions(db) ──────────────────────────────────────────────────────────────
// A SYSTEM sweep, not a per-user query: every advanceable position across every user is loaded in
// one pass (each row carries its own user_id, which flows through to the events persistAdvance()
// writes — the isolation boundary is still enforced, just at the row level rather than the query).
// ORDER BY entry_date, trade_id gives sweep() (and its logs/tests) a stable, reproducible order —
// with no ordering at all, D1 makes no promises about row order across runs.
export async function loadAdvanceablePositions(db) {
  const states = SWEEP_CONFIG.ADVANCEABLE_STATES;
  const placeholders = states.map(() => "?").join(", ");
  const { results } = await db
    .prepare(`SELECT * FROM positions WHERE state IN (${placeholders}) ORDER BY entry_date ASC, trade_id ASC`)
    .bind(...states)
    .all();
  // EASY BUG TO MISS: `meta` is stored as a JSON TEXT column in D1, but advance()/effectiveConfig()
  // read pos.meta.widen_enabled and pos.meta.config as an OBJECT (see advance.js effectiveConfig
  // and the WIDEN_TRAIL_BASIS rule). Parse it HERE, once, at the load boundary, so every downstream
  // consumer in this module can treat pos.meta as already-an-object. Defensive try/catch: a
  // corrupt/legacy meta string degrades to {} (== globals-only config) rather than throwing and
  // failing the whole sweep over one bad row.
  return results.map((row) => {
    let meta = {};
    try {
      meta = JSON.parse(row.meta || "{}");
    } catch {
      meta = {};
    }
    return { ...row, meta };
  });
}

// ── loadClosingPositions(db) — every position awaiting an exit confirmation, across all users. ──
// The auto-confirm pass (§7) operates on exactly the states the main advance loop EXCLUDES: a
// `closing` position is not advanceable (advance() no-ops it), but it can still time out. meta is
// parsed here too so effectiveConfig() sees per-position EXIT_AUTOCONFIRM_SESSIONS overrides.
export async function loadClosingPositions(db) {
  const { results } = await db
    .prepare("SELECT * FROM positions WHERE state = 'closing' ORDER BY exit_signal_date ASC, trade_id ASC")
    .all();
  return results.map((row) => {
    let meta = {};
    try {
      meta = JSON.parse(row.meta || "{}");
    } catch {
      meta = {};
    }
    return { ...row, meta };
  });
}

// ── distinctTradeDates(db) — the session calendar, ascending. ───────────────────────────────────
// The natural trading-session calendar is the set of dates on which the held feed captured ANY bar
// (the union across all held tickers). Using the GLOBAL union — not one ticker's own bars — makes
// the session count robust to a single symbol missing a day: a market session that produced bars
// for other held names still counts, so a feed gap for one ticker can't understate how long its
// position has actually sat in Closing. Ascending order lets sessionsSince() do a cheap filter.
export async function distinctTradeDates(db) {
  const { results } = await db
    .prepare("SELECT DISTINCT trade_date FROM ticker_quotes ORDER BY trade_date ASC")
    .all();
  return results.map((r) => r.trade_date);
}

// ── sessionsSince(dates, exitSignalDate) — PURE. Trading sessions STRICTLY AFTER the exit signal. ─
// dates is the ascending session calendar (distinctTradeDates). The signal fires ON a session that
// itself has a bar; the clock we care about is how many sessions have settled SINCE — so the count
// is dates strictly greater than exitSignalDate. All are 'YYYY-MM-DD' strings, which sort
// identically as strings and as dates, so a string comparison is correct without parsing.
// With EXIT_AUTOCONFIRM_SESSIONS=5 this reaches the threshold on the 5th session after the signal.
export function sessionsSince(dates, exitSignalDate) {
  if (!exitSignalDate) return 0;
  let n = 0;
  for (const d of dates) if (d > exitSignalDate) n++;
  return n;
}

// ── loadBarsAfter(db, ticker, afterDate, limit) ───────────────────────────────────────────────
// afterDate is EXCLUSIVE (matches barWindowStart's exclusive floor). When afterDate is null (a
// position with no last_advanced_date AND no entry_date would hit this, though sweep() actually
// skips those before calling here — see skipped_no_entry_date), '' is used as the bound instead of
// branching the SQL into a with/without-date variant: every real 'YYYY-MM-DD' string sorts after
// the empty string lexicographically, so `trade_date > ''` is equivalent to "no lower bound" and
// keeps this function to one query shape.
export async function loadBarsAfter(db, ticker, afterDate, limit) {
  const bound = afterDate == null ? "" : afterDate;
  const { results } = await db
    .prepare("SELECT * FROM ticker_quotes WHERE ticker = ? AND trade_date > ? ORDER BY trade_date ASC LIMIT ?")
    .bind(ticker, bound, limit)
    .all();
  return results;
}

// ── persistAdvance(db, {...}) — the ONLY DB-write path for the engine. ───────────────────────────
// Idempotency is enforced AT THE DB LAYER via compare-and-set on last_advanced_date, not just by
// the caller checking-then-writing: two concurrent sweeps (a retried HTTP request racing a cron
// tick, say) reading the same pre-state cannot both apply — the second one's CAS UPDATE affects
// zero rows because the first already moved last_advanced_date out from under it. This is the same
// idea as an optimistic-lock version column, using last_advanced_date itself as the version.
export async function persistAdvance(db, { trade_id, user_id, expectedLastAdvancedDate, position, events, now_iso }) {
  const stmts = [];

  // (a) One guarded INSERT per event. Guarded on the SAME pre-state (last_advanced_date IS
  // expected) as the UPDATE below — see the ordering comment further down for why that matters.
  // `IS` (not `=`) is required here because expectedLastAdvancedDate is frequently NULL (a
  // position's first-ever advance): in SQL, `NULL = NULL` is NULL (falsy), never true, so a plain
  // `=` would make the WHERE EXISTS guard fail for every never-yet-advanced position. `IS`
  // correctly treats NULL as a comparable value equal to itself.
  for (const ev of events) {
    stmts.push(
      db
        .prepare(
          `INSERT INTO position_events (trade_id, user_id, ts, trade_date, event_type, payload)
           SELECT ?, ?, ?, ?, ?, ? WHERE EXISTS (
             SELECT 1 FROM positions WHERE trade_id = ? AND last_advanced_date IS ?
           )`
        )
        .bind(
          trade_id,
          user_id,
          now_iso,
          ev.trade_date,
          ev.event_type,
          JSON.stringify(ev.payload || {}),
          trade_id,
          expectedLastAdvancedDate
        )
    );
  }

  // (b) The CAS UPDATE, LAST. Deliberately narrow: only the columns advance() can actually change.
  // meta, exit_price, closed_at, and confirmation_status are NEVER written here — advance() never
  // touches them (they're owned by the user-driven transitions in advance.js: confirmExit,
  // stillHolding, correctExit, reopen), and narrowing the UPDATE's column list is what keeps a
  // sweep from ever clobbering a user-owned field it has no business writing, even accidentally.
  stmts.push(
    db
      .prepare(
        `UPDATE positions SET
           state = ?, expected_exit_price = ?, exit_signal_date = ?, exit_reason = ?,
           profit_floor = ?, current_stop = ?, trail_basis = ?, remaining_qty = ?,
           caution_flag = ?, highest_trim_atr = ?, days_to_earnings = ?, last_advanced_date = ?
         WHERE trade_id = ? AND last_advanced_date IS ?`
      )
      .bind(
        position.state,
        position.expected_exit_price,
        position.exit_signal_date,
        position.exit_reason,
        position.profit_floor,
        position.current_stop,
        position.trail_basis,
        position.remaining_qty,
        position.caution_flag,
        position.highest_trim_atr,
        position.days_to_earnings,
        position.last_advanced_date,
        trade_id,
        expectedLastAdvancedDate
      )
  );

  // WHY events go first: both statement groups guard on the IDENTICAL pre-state
  // (last_advanced_date IS expectedLastAdvancedDate). If the UPDATE ran first, it would advance
  // last_advanced_date and invalidate that guard for every event statement that follows it in the
  // SAME batch — they would silently no-op (their WHERE EXISTS would find nothing) and the events
  // would be dropped even though the position row moved. Events first means either everything in
  // this batch applies against the SAME snapshot, or (on a lost CAS race — another sweep/request
  // already advanced this position) NOTHING in the batch applies. No partial-apply state is
  // possible from this ordering.
  const results = await db.batch(stmts);

  const updateResult = results[results.length - 1];
  // Prefer the driver's own miss/change count; D1 (and our node:sqlite test shim) report
  // meta.changes, but fall back to `true` if a driver in some environment doesn't report it at
  // all — better to assume the write applied (matching D1's documented behavior) than to report a
  // false negative on every persisted advance because of a missing diagnostic field.
  const applied = updateResult && updateResult.meta && typeof updateResult.meta.changes === "number"
    ? updateResult.meta.changes === 1
    : true;

  // eventsWritten counts ACTUAL rows inserted (each event statement's own meta.changes), not
  // events.length — under a lost CAS race every event statement's WHERE EXISTS guard also fails
  // (same pre-state check as the UPDATE), so this correctly reports 0 even though `events` was
  // non-empty going in. The event results are every batch entry except the trailing UPDATE.
  const eventResults = results.slice(0, results.length - 1);
  const eventsWritten = eventResults.reduce((sum, r) => sum + (r && r.meta && typeof r.meta.changes === "number" ? r.meta.changes : (applied ? 1 : 0)), 0);

  return { applied, eventsWritten };
}

// ── sweep(db, opts) — the orchestrator. ───────────────────────────────────────────────────────
export async function sweep(db, { dry_run = false, now = new Date(), cfg } = {}) {
  const now_iso = isoUtc(now);
  const globals = cfg || ENGINE_CONFIG;
  const positions = await loadAdvanceablePositions(db);

  const results = [];
  let advanced = 0;
  let signalled = 0;
  let unchanged = 0;
  let staleCount = 0;

  for (const pos of positions) {
    // Defensive: a position with no entry_date at all is a data-integrity gap (every position
    // created via buildPositionRow gets one — see src/positions.js — so this should only happen
    // from a hand-edited or pre-phase-1-migration row). barWindowStart() would return null for it,
    // which would make loadBarsAfter() use '' as the bound and potentially advance through the
    // position's ENTIRE bar history at once, including its own entry-day bar's false-positive risk
    // (see barWindowStart's header comment) — skip rather than risk that.
    if (!pos.entry_date) {
      results.push({
        trade_id: pos.trade_id,
        ticker: pos.ticker,
        user_id: pos.user_id,
        from_state: pos.state,
        to_state: pos.state,
        bars_advanced: 0,
        advanced_to: pos.last_advanced_date,
        events: [],
        applied: false,
        skipped: "skipped_no_entry_date",
      });
      unchanged++;
      continue;
    }

    const windowStart = barWindowStart(pos);
    const bars = await loadBarsAfter(db, pos.ticker, windowStart, SWEEP_CONFIG.MAX_CATCHUP_BARS);

    const effCfg = effectiveConfig(pos, globals);
    const outcome = advanceThroughBars(pos, bars, effCfg);

    const fromState = pos.state;
    const toState = outcome.position.state;
    const moved = outcome.advancedTo !== pos.last_advanced_date;

    // Persist IF AND ONLY IF last_advanced_date moved. The tempting weaker gate — "persist whenever
    // there are events" — is a bug: a stale bar emits a `note` but deliberately does NOT stamp
    // last_advanced_date (advance.js, so a real bar arriving later that day still advances), which
    // means that bar stays inside loadBarsAfter()'s window on EVERY subsequent sweep. Persisting on
    // events alone would therefore re-append the same note daily and forever, and since each
    // earlier stale date also stays in the window, the duplication compounds across a run of stale
    // sessions. position_events is append-only with no dedupe, so the gate is the right place to
    // fix it. Nothing is lost: staleness is reported through this function's `stale` counter (which
    // /advance returns and the held-feed CI job logs), which is the correct channel for a condition
    // that repeats every session — the permanent ledger is not.
    //
    // Safe because events imply (moved OR stale): every non-stale, non-no-op path in advance()
    // stamps last_advanced_date, and the no-op paths emit no events. So the only events this gate
    // can drop are stale notes — and only for a batch that advanced nothing at all. Pinned by
    // "a trailing stale bar does not re-append its note on every later sweep" in sweep.test.js.
    let applied = false;
    if (moved) {
      if (!dry_run) {
        const persisted = await persistAdvance(db, {
          trade_id: pos.trade_id,
          user_id: pos.user_id,
          expectedLastAdvancedDate: pos.last_advanced_date,
          position: outcome.position,
          events: outcome.events,
          now_iso,
        });
        applied = persisted.applied;
      } else {
        // dry_run: report what WOULD have applied without writing — same shape either way so
        // callers (and the /advance route) don't need to special-case dry runs.
        applied = true;
      }
    }

    if (moved) {
      advanced++;
    } else {
      unchanged++;
    }
    if (fromState !== "closing" && toState === "closing") signalled++;
    if (outcome.staleBars > 0) staleCount++;

    results.push({
      trade_id: pos.trade_id,
      ticker: pos.ticker,
      user_id: pos.user_id,
      from_state: fromState,
      to_state: toState,
      bars_advanced: outcome.barsAdvanced,
      advanced_to: outcome.advancedTo,
      events: outcome.events.map((e) => e.event_type),
      applied,
    });
  }

  // ── AUTO-CONFIRM pass (§7): close out positions parked in `closing` past EXIT_AUTOCONFIRM_SESSIONS.
  // Runs AFTER the advance loop and over a DIFFERENT population (closing positions, which the advance
  // loop excludes). The price is the one frozen AT SIGNAL time (autoConfirm() reads
  // expected_exit_price — never re-derived from a later bar), labeled confirmation_status='auto' so
  // expectancy queries can filter it out and the owner can still correct/reopen it. It writes the
  // settled-close columns (exit_price/closed_at/confirmation_status) via persistTransition — the same
  // user-owned write path the manual confirm-exit route uses — NOT persistAdvance, whose UPDATE
  // deliberately never touches those columns. Skipped entirely in dry_run (report, don't write).
  let autoConfirmed = 0;
  const closing = await loadClosingPositions(db);
  if (closing.length) {
    const calendar = await distinctTradeDates(db);
    const trade_date = etDateStr(now);
    for (const pos of closing) {
      const effCfg = effectiveConfig(pos, globals);
      const sessionsInClosing = sessionsSince(calendar, pos.exit_signal_date);
      const outcome = autoConfirm(pos, effCfg, { sessionsInClosing, trade_date, now_iso });
      if (!outcome) continue; // not yet time — leave it parked, awaiting the owner.

      let applied = false;
      if (!dry_run) {
        // autoConfirm() returns trade_date as a sibling of events (like the other pure transitions);
        // position_events.trade_date is NOT NULL, so stamp each event before persisting.
        const events = outcome.events.map((ev) => ({ ...ev, trade_date: outcome.trade_date ?? trade_date }));
        const persisted = await persistTransition(db, {
          trade_id: pos.trade_id,
          user_id: pos.user_id,
          expectedState: "closing",
          position: outcome.position,
          events,
          now_iso,
        });
        applied = persisted.applied;
      } else {
        applied = true;
      }

      autoConfirmed++;
      results.push({
        trade_id: pos.trade_id,
        ticker: pos.ticker,
        user_id: pos.user_id,
        from_state: "closing",
        to_state: outcome.position.state,
        bars_advanced: 0,
        advanced_to: pos.last_advanced_date,
        events: outcome.events.map((e) => e.event_type),
        applied,
        action: "auto_confirm",
      });
    }
  }

  return {
    dry_run,
    positions: positions.length,
    advanced,
    signalled,
    unchanged,
    stale: staleCount,
    auto_confirmed: autoConfirmed,
    results,
  };
}
