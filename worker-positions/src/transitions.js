// Owner-driven state-transition wiring for finviz-positions — WS5 phase 3b-ii (SPRINT WS5-3b-ii).
//
// advance.js (phase 3a) already contains the PURE transition functions — confirmExit, stillHolding,
// correctExit, reopen (and autoConfirm, wired into the sweep, not here). This module is their D1
// wiring: load one position (user-scoped), enforce the state precondition, call the pure function,
// and persist the result under a compare-and-set guard. Nothing here re-implements transition logic.
//
// These are the mirror image of sweep.js's engine path: the sweep NEVER writes exit_price/closed_at/
// confirmation_status (persistAdvance's UPDATE is deliberately narrow) precisely because THOSE
// columns are user-owned and written HERE. persistTransition() is the only place the engine's
// exit-signal (Closing) becomes a settled, user-confirmed close.
//
// Design: planning/trade-lifecycle-engine.md §4 (state machine), §7 (edit/undo/confirm edge cases),
// §11; ADR-012. worker-positions/CLAUDE.md § Phase 3b-ii.

import { confirmExit, stillHolding, correctExit, reopen, effectiveConfig } from "./advance.js";
import { etDateStr, isoUtc } from "./time.js";

function isNum(x) {
  return typeof x === "number" && Number.isFinite(x);
}

// ── The columns persistTransition() may write. Deliberately the COMPLEMENT of persistAdvance()'s
// set: state + the four exit-signal fields + the three settled-close fields + caution_flag. It
// NEVER writes the engine-managed columns (profit_floor, current_stop, trail_basis, remaining_qty,
// highest_trim_atr, days_to_earnings, last_advanced_date) — those are the sweep's, and keeping the
// two write paths' column lists disjoint (except caution_flag, legitimately re-armed by
// stillHolding/reopen) is what stops either path from clobbering the other's fields. caution_flag
// is the one shared column, and only ever while the position is in closing/closed — a state the
// sweep does not advance — so there is no live contention on it.
const TRANSITION_COLS = [
  "state",
  "expected_exit_price",
  "exit_signal_date",
  "exit_reason",
  "exit_price",
  "closed_at",
  "confirmation_status",
  "caution_flag",
];

// ── loadPosition(db, user_id, trade_id) — a single position, user-scoped, meta parsed to an object.
// User-scoped on purpose (the app-layer tenant boundary; D1 has no RLS): a trade_id belonging to
// another user returns null → the route 404s, never leaking existence. `meta` is a JSON TEXT column
// but effectiveConfig() reads it as an object, so parse it here at the load boundary (same rule as
// sweep.js's loadAdvanceablePositions — skip it and per-position config overrides silently vanish).
export async function loadPosition(db, user_id, trade_id) {
  const row = await db
    .prepare("SELECT * FROM positions WHERE trade_id = ? AND user_id = ?")
    .bind(trade_id, user_id)
    .first();
  if (!row) return null;
  let meta = {};
  try {
    meta = JSON.parse(row.meta || "{}");
  } catch {
    meta = {};
  }
  return { ...row, meta };
}

// ── persistTransition(db, {...}) — the ONLY DB-write path for the owner transitions. ─────────────
// Same compare-and-set idempotency shape as sweep.js's persistAdvance(), but the version column is
// `state` (not last_advanced_date): a transition is valid only from a known pre-state, and guarding
// on it makes a double-submit safe — two concurrent "confirm exit" requests both read `closing`,
// but only the first's UPDATE matches `state = 'closing'`; the second affects zero rows (and its
// guarded event INSERTs find nothing), so it no-ops instead of double-closing or double-logging.
//
// Ordering is load-bearing, identical to persistAdvance: guarded event INSERTs FIRST, the CAS UPDATE
// LAST. A transition that changes state (confirm/still-holding/reopen) would, if the UPDATE ran
// first, move `state` out from under every event statement's `WHERE EXISTS (... state = ?)` guard in
// the SAME batch and silently drop them. Events-first means the whole batch applies against one
// snapshot, or (on a lost CAS race) none of it does — never a partial apply.
//
// `state` is NOT NULL in the schema, so `state = ?` is a plain equality (unlike persistAdvance's
// nullable last_advanced_date, which needs `IS`). user_id is in every guard too — defense in depth
// on top of the user-scoped load, so no batch can ever touch another user's row.
export async function persistTransition(db, { trade_id, user_id, expectedState, position, events, now_iso }) {
  const stmts = [];

  for (const ev of events) {
    stmts.push(
      db
        .prepare(
          `INSERT INTO position_events (trade_id, user_id, ts, trade_date, event_type, payload)
           SELECT ?, ?, ?, ?, ?, ? WHERE EXISTS (
             SELECT 1 FROM positions WHERE trade_id = ? AND user_id = ? AND state = ?
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
          user_id,
          expectedState
        )
    );
  }

  stmts.push(
    db
      .prepare(
        `UPDATE positions SET
           state = ?, expected_exit_price = ?, exit_signal_date = ?, exit_reason = ?,
           exit_price = ?, closed_at = ?, confirmation_status = ?, caution_flag = ?
         WHERE trade_id = ? AND user_id = ? AND state = ?`
      )
      .bind(
        position.state,
        position.expected_exit_price,
        position.exit_signal_date,
        position.exit_reason,
        position.exit_price,
        position.closed_at,
        position.confirmation_status,
        position.caution_flag,
        trade_id,
        user_id,
        expectedState
      )
  );

  const results = await db.batch(stmts);
  const updateResult = results[results.length - 1];
  // Prefer the driver's change count; fall back to `true` if some driver omits meta.changes (matches
  // persistAdvance's reasoning — assume-applied beats a false negative on every write).
  const applied =
    updateResult && updateResult.meta && typeof updateResult.meta.changes === "number"
      ? updateResult.meta.changes === 1
      : true;
  return { applied };
}

// ── applyTransition(db, {...}) — the route handler's single entry point. ─────────────────────────
// Returns { position } on success (meta as an object, matching /positions), or { error, status } on
// a precondition failure (404 not found, 409 wrong state / lost CAS race, 400 bad input). PURE of
// the HTTP layer — index.js only maps this to a Response.
//
// State preconditions (§4 state machine): confirm-exit and still-holding require `closing` (there is
// an exit signal to resolve); correct-exit and reopen require `closed` (there is a settled close to
// amend). Any other current state is a 409, not a silent no-op — the caller asked for something the
// position can't do right now.
export async function applyTransition(db, { user_id, trade_id, action, body = {}, now = new Date() }) {
  const pos = await loadPosition(db, user_id, trade_id);
  if (!pos) return { error: "not found", status: 404 };

  const now_iso = isoUtc(now);
  const trade_date = etDateStr(now); // the ET session this owner action is stamped to in the ledger.
  const cfg = effectiveConfig(pos);

  let outcome;
  let expectedState;

  if (action === "confirm-exit") {
    if (pos.state !== "closing") return { error: `cannot confirm-exit from state '${pos.state}'`, status: 409 };
    // Editable actual fill (§7): body.exit_price overrides the modeled expected_exit_price, but only
    // if it is a real positive number — a client sending 0/negative/non-numeric must not record a
    // bogus fill (confirmExit()'s own isNum() would happily accept 0). Omitted → default to expected.
    let exit_price;
    if (body.exit_price === undefined || body.exit_price === null) {
      exit_price = pos.expected_exit_price;
      if (!isNum(exit_price)) return { error: "no exit_price given and no expected_exit_price on file", status: 400 };
    } else if (isNum(body.exit_price) && body.exit_price > 0) {
      exit_price = body.exit_price;
    } else {
      return { error: "exit_price must be a number > 0", status: 400 };
    }
    outcome = confirmExit(pos, { exit_price, trade_date, now_iso });
    expectedState = "closing";
  } else if (action === "still-holding") {
    if (pos.state !== "closing") return { error: `cannot still-holding from state '${pos.state}'`, status: 409 };
    outcome = stillHolding(pos, cfg, { trade_date });
    expectedState = "closing";
  } else if (action === "correct-exit") {
    if (pos.state !== "closed") return { error: `cannot correct-exit from state '${pos.state}'`, status: 409 };
    if (!isNum(body.exit_price) || body.exit_price <= 0) return { error: "exit_price must be a number > 0", status: 400 };
    outcome = correctExit(pos, { exit_price: body.exit_price, trade_date });
    expectedState = "closed";
  } else if (action === "reopen") {
    if (pos.state !== "closed") return { error: `cannot reopen from state '${pos.state}'`, status: 409 };
    outcome = reopen(pos, { trade_date });
    expectedState = "closed";
  } else {
    return { error: "unknown transition", status: 400 };
  }

  // The pure transition fns return trade_date as a SIBLING of events (not stamped per-event, the way
  // advanceThroughBars does for the fold). position_events.trade_date is NOT NULL, so stamp each
  // event with the transition's trade_date here before persisting.
  const events = outcome.events.map((ev) => ({ ...ev, trade_date: outcome.trade_date ?? trade_date }));
  const { applied } = await persistTransition(db, {
    trade_id,
    user_id,
    expectedState,
    position: outcome.position,
    events,
    now_iso,
  });
  // Lost the CAS race (another request/sweep changed the state between our load and our write): the
  // position is no longer in the pre-state we validated. Report a conflict rather than a stale 200.
  if (!applied) return { error: "position state changed concurrently, retry", status: 409 };

  // outcome.position.meta is already the parsed object (loadPosition parsed it, the pure fns spread
  // it through), so the response matches /positions' object-meta shape without re-parsing.
  return { position: outcome.position };
}
