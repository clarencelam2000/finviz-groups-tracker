// Positions domain logic for finviz-positions (WS5 phase 1).
// Validation is a PURE function (unit-tested without D1); the create/list helpers are the only
// DB-touching code. Design: planning/trade-lifecycle-engine.md § 3, § 4, § 8a; ADR-012.

import { etDateStr, isoUtc } from "./time.js";
import { distinctTradeDates, sessionsSince } from "./sweep.js";
import { effectiveConfig } from "./advance.js";

// Stop bases the WS4 ticket offers, plus 'manual' for the future free-entry form (§ 8a).
export const STOP_BASES = ["prior_day_low", "todays_low", "20ma", "50ma", "manual"];
const TICKER_RE = /^[A-Z][A-Z0-9.\-]{0,9}$/; // 1–10 chars, letters/digits/./-, starts with a letter.

// Every value the `state` column can hold. Kept separate from quotes.js's HELD_STATES (which
// happens to equal LIVE_STATES today but answers a different question — "should we poll a quote
// for it" — and will diverge once WS5-5's closed-position grace window ships).
export const ALL_STATES = ["open", "managing", "closing", "closed"];
export const LIVE_STATES = ["open", "managing", "closing"];

function isFiniteNumber(x) {
  return typeof x === "number" && Number.isFinite(x);
}

// PURE. Validate + normalize the ticker-generic "I took it" payload (§ 8a: the create path is a
// payload, not a picks-row identity — the WS4 ticket is just one caller; a future manual form is
// another). Returns { ok:true, value } or { ok:false, error }.
export function validateCreatePayload(body) {
  if (!body || typeof body !== "object") return { ok: false, error: "body must be a JSON object" };

  const ticker = typeof body.ticker === "string" ? body.ticker.trim().toUpperCase() : null;
  if (!ticker || !TICKER_RE.test(ticker)) return { ok: false, error: "ticker invalid (expect 1–10 alnum, e.g. AAPL)" };

  const entry_price = body.entry_price;
  const initial_stop = body.initial_stop;
  const qty = body.qty;
  if (!isFiniteNumber(entry_price) || entry_price <= 0) return { ok: false, error: "entry_price must be > 0" };
  if (!isFiniteNumber(initial_stop) || initial_stop <= 0) return { ok: false, error: "initial_stop must be > 0" };
  if (!isFiniteNumber(qty) || qty <= 0) return { ok: false, error: "qty must be > 0" };
  // Long-only swing setup: the stop sits BELOW entry, so R = entry - stop is strictly positive.
  // Guarding here keeps every downstream R-multiple from being computed off a non-positive risk.
  if (initial_stop >= entry_price) return { ok: false, error: "initial_stop must be < entry_price (R = entry - stop > 0)" };

  const stop_basis = typeof body.stop_basis === "string" ? body.stop_basis : "manual";
  if (!STOP_BASES.includes(stop_basis)) return { ok: false, error: `stop_basis must be one of ${STOP_BASES.join("|")}` };

  // meta is a client-supplied JSON bag but we control the reserved keys. source defaults to 'manual'
  // unless the caller (the WS4 picks ticket) says 'picks'. group_id (§ 3a) is reserved but optional.
  let meta = {};
  if (body.meta != null) {
    if (typeof body.meta !== "object" || Array.isArray(body.meta)) return { ok: false, error: "meta must be an object" };
    meta = { ...body.meta };
  }
  meta.source = meta.source === "picks" ? "picks" : "manual";
  if (meta.widen_enabled == null) meta.widen_enabled = true; // § 6 per-position widen toggle, default on.

  const days_to_earnings = isFiniteNumber(body.days_to_earnings) ? Math.trunc(body.days_to_earnings) : null;

  // entry_date (optional, § 8a manual entry): lets the owner log a trade taken on an earlier
  // date. Absent/null/'' -> null, so buildPositionRow falls back to today's ET date (unchanged
  // behavior). Present -> must be a YYYY-MM-DD calendar date, and not in the future (ET).
  let entry_date = null;
  if (body.entry_date != null && body.entry_date !== "") {
    // Format check, then a UTC round-trip so a well-formed but impossible date (e.g. 2026-02-30,
    // 2026-13-01) is rejected — entry_date becomes a NOT-NULL trade_date in the append-only
    // position_events ledger, so a garbage value must never be storable. (JS Date rolls invalid
    // days over, so the round-trip back to the same string is the real calendar check.)
    if (typeof body.entry_date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(body.entry_date)) {
      return { ok: false, error: "entry_date must be YYYY-MM-DD" };
    }
    const parsed = new Date(body.entry_date + "T00:00:00Z");
    if (isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== body.entry_date) {
      return { ok: false, error: "entry_date must be YYYY-MM-DD" };
    }
    if (body.entry_date > etDateStr(new Date())) {
      return { ok: false, error: "entry_date cannot be in the future" };
    }
    entry_date = body.entry_date;
  }

  return { ok: true, value: { ticker, entry_price, initial_stop, qty, stop_basis, meta, days_to_earnings, entry_date } };
}

// Build the initial positions row from a validated payload. PURE (takes trade_id/now as inputs).
// Initializes engine state so phase-3 advance() has sane starting values:
//   state = open (user has confirmed the fill; § 1 Watching -> Open)
//   current_stop = profit_floor = initial_stop  (invariant current_stop >= profit_floor holds; § 4)
//   trail_basis = 20ma  (default trailing basis before the first advance widens it; § 4)
//   remaining_qty = initial_qty = qty
export function buildPositionRow(v, { trade_id, user_id, now = new Date() }) {
  // entry_date may be an owner-supplied backdate (manual § 8a entry); opened_at stays the real
  // creation time. The engine advances forward from the next fed bar, so a backdate is only an
  // accurate trade-date label — never a retroactive replay.
  const entry_date = v.entry_date || etDateStr(now);
  return {
    trade_id,
    user_id,
    ticker: v.ticker,
    state: "open",
    entry_date,
    entry_price: v.entry_price,
    initial_stop: v.initial_stop,
    stop_basis: v.stop_basis,
    initial_qty: v.qty,
    expected_exit_price: null,
    exit_signal_date: null,
    exit_reason: null,
    profit_floor: v.initial_stop,
    current_stop: v.initial_stop,
    trail_basis: "20ma",
    remaining_qty: v.qty,
    caution_flag: 0,
    highest_trim_atr: 0,
    days_to_earnings: v.days_to_earnings,
    opened_at: isoUtc(now),
    closed_at: null,
    exit_price: null,
    confirmation_status: "unconfirmed",
    last_advanced_date: null,
    meta: JSON.stringify(v.meta),
  };
}

const POSITION_COLS = [
  "trade_id", "user_id", "ticker", "state", "entry_date", "entry_price", "initial_stop", "stop_basis",
  "initial_qty", "expected_exit_price", "exit_signal_date", "exit_reason", "profit_floor", "current_stop",
  "trail_basis", "remaining_qty", "caution_flag", "highest_trim_atr", "days_to_earnings", "opened_at",
  "closed_at", "exit_price", "confirmation_status", "last_advanced_date", "meta",
];

// Insert a position row + its first `entered` event in one D1 batch (atomic-ish; D1 batch is a
// single transaction). Each call creates an INDEPENDENT LOT — "I took it" twice on one ticker makes
// two rows on purpose (§ 3a scale-ins). We deliberately do NOT add a (user_id, ticker) uniqueness
// assumption.
export async function insertPosition(db, row) {
  const placeholders = POSITION_COLS.map(() => "?").join(", ");
  const values = POSITION_COLS.map((c) => row[c]);
  const enteredPayload = JSON.stringify({
    entry_price: row.entry_price,
    initial_stop: row.initial_stop,
    stop_basis: row.stop_basis,
    qty: row.initial_qty,
    source: JSON.parse(row.meta).source,
  });
  await db.batch([
    db.prepare(`INSERT INTO positions (${POSITION_COLS.join(", ")}) VALUES (${placeholders})`).bind(...values),
    db
      .prepare(
        `INSERT INTO position_events (trade_id, user_id, ts, trade_date, event_type, payload)
         VALUES (?, ?, ?, ?, 'entered', ?)`
      )
      .bind(row.trade_id, row.user_id, row.opened_at, row.entry_date, enteredPayload),
  ]);
  return row;
}

// EVENTS_DISPLAY_CAP: how many of a position's newest position_events ride inline in the
// GET /positions response's `events` array (WS5-7 managing-card overhaul). Purely a payload-size
// cap for the card's inline activity list — it does NOT bound what stop_ack_value is computed
// from (see attachEventsAndAck below, which reads the FULL per-trade event list before slicing).
// Raise it if the card ever wants a longer inline history; no schema impact either way.
const EVENTS_DISPLAY_CAP = 8;

// The latest-bar LEFT JOIN this module adds to every listPositions() query (both the no-state and
// state-filtered branches). `ticker_quotes` is user-less/public (migration 0002) so joining it
// inside the already user_id-scoped `positions` query leaks nothing across tenants — the row set
// is still fully bounded by `p.user_id = ?`. Null-safe by construction: a ticker with zero bars
// yields a LEFT JOIN miss, so every `last_*` column comes back NULL, never a throw.
const LATEST_BAR_JOIN = `
  LEFT JOIN ticker_quotes q
    ON q.ticker = p.ticker
   AND q.trade_date = (SELECT MAX(trade_date) FROM ticker_quotes q2 WHERE q2.ticker = p.ticker)
`;
const LATEST_BAR_COLS = `
  q.close AS last_close, q.trade_date AS last_bar_date,
  q.open AS last_open, q.high AS last_high, q.low AS last_low,
  q.change_pct AS last_change_pct, q.volume AS last_volume, q.raw AS last_raw
`;

// List a user's positions, newest first. `state` optionally filters — a single state string, an
// array of states (IN clause), or omitted/empty for all. ALWAYS scoped by user_id — the app-layer
// tenant boundary (D1 has no RLS; ADR-012). Callers are responsible for validating `state` values
// against ALL_STATES before calling (see index.js) — this function trusts its input.
//
// WS5-7: each row is additionally augmented with the latest ticker_quotes bar (last_*, null-safe),
// a bounded inline `events` array, and a computed `stop_ack_value` — see attachEventsAndAck().
//
// Session-calendar fields (this PR): each row also gets `auto_confirm_sessions`,
// `sessions_in_closing`, `sessions_since_close` — see attachSessionCounts() below. `opts.closedWithinSessions`
// (a positive integer, or omitted/undefined for no filtering) additionally bounds returned `closed`
// rows to those whose `sessions_since_close` is within that many sessions — see index.js's
// `?closed_within_sessions=` param, the only current caller.
//
// NOTE on unbounded closed history: we deliberately do NOT add a SQL LIMIT/hardcap on closed rows
// here. A cap correct for mixed-state queries (e.g. `?state=open,closed`) would need to apply only
// to the closed subset, which the single shared query shape can't express without either a second
// query or non-trivial SQL — and per the locked spec, correctness/simplicity wins over a clever SQL
// bound, with timezone-aware session math being SQL-hostile in the first place. The
// `closed_within_sessions` filter below is the actual bound on payload size for the closed-history
// use case (WS5-6); an operator-scale pathological history is a future concern, not this PR's.
export async function listPositions(db, user_id, state = null, opts = {}) {
  const states = state == null ? [] : Array.isArray(state) ? state : [state];
  let stmt;
  if (states.length === 0) {
    stmt = db
      .prepare(
        `SELECT p.*, ${LATEST_BAR_COLS}
         FROM positions p
         ${LATEST_BAR_JOIN}
         WHERE p.user_id = ?
         ORDER BY p.opened_at DESC`
      )
      .bind(user_id);
  } else {
    const marks = states.map(() => "?").join(", ");
    stmt = db
      .prepare(
        `SELECT p.*, ${LATEST_BAR_COLS}
         FROM positions p
         ${LATEST_BAR_JOIN}
         WHERE p.user_id = ? AND p.state IN (${marks})
         ORDER BY p.opened_at DESC`
      )
      .bind(user_id, ...states);
  }
  const { results } = await stmt.all();
  let positions = results.map((r) => ({ ...r, meta: safeParse(r.meta) }));
  positions = await attachEventsAndAck(db, user_id, positions);

  if (positions.length > 0) {
    const calendar = await distinctTradeDates(db);
    positions = attachSessionCounts(positions, calendar);
  }

  const { closedWithinSessions } = opts;
  if (closedWithinSessions != null) {
    positions = positions.filter(
      (p) => p.state !== "closed" || p.sessions_since_close <= closedWithinSessions
    );
  }

  return positions;
}

// Attach the three session-calendar derived fields (this PR) to every position. PURE given the
// already-fetched `calendar` (distinctTradeDates' ascending trade_date list) — no DB access here,
// mirroring attachEventsAndAck's shape but without its query. Reuses `sessionsSince` (sweep.js),
// the SAME clock `autoConfirm` uses to auto-close a stuck `closing` position — so the client's
// countdown/age display can never disagree with what the engine itself will do.
function attachSessionCounts(positions, calendar) {
  return positions.map((p) => {
    const sessions_in_closing = p.state === "closing" ? sessionsSince(calendar, p.exit_signal_date) : null;
    // The close's session anchor is when it SETTLED to closed (closed_at), not when the exit first
    // signalled (exit_signal_date) — a position can sit in `closing` for several sessions before
    // confirm/auto-close. closed_at is ISO-UTC; convert to its ET trade-date so it lines up with the
    // trade_date-keyed calendar. sessionsSince counts strictly-after, so a just-closed position reads
    // 0 (in grace) and ages up as sessions settle.
    const closeEtDate = p.state === "closed" && p.closed_at ? etDateStr(new Date(p.closed_at)) : null;
    const sessions_since_close = p.state === "closed" && closeEtDate ? sessionsSince(calendar, closeEtDate) : null;
    return {
      ...p,
      // effectiveConfig(p), not the bare global — a position with a meta.config.EXIT_AUTOCONFIRM_SESSIONS
      // override must report that override here too, or the countdown would disagree with autoConfirm.
      auto_confirm_sessions: effectiveConfig(p).EXIT_AUTOCONFIRM_SESSIONS,
      sessions_in_closing,
      sessions_since_close,
    };
  });
}

// Attach a bounded, newest-first `events` array and a computed `stop_ack_value` to each position,
// in ONE grouped query (no N+1 — a single `trade_id IN (...)` fetch for every position passed in).
async function attachEventsAndAck(db, user_id, positions) {
  if (positions.length === 0) return positions;

  const marks = positions.map(() => "?").join(", ");
  const { results: eventRows } = await db
    .prepare(
      `SELECT trade_id, ts, trade_date, event_type, payload
       FROM position_events
       WHERE user_id = ? AND trade_id IN (${marks})
       ORDER BY ts DESC`
    )
    .bind(user_id, ...positions.map((p) => p.trade_id))
    .all();

  // Group by trade_id. Rows already arrive newest-first (ORDER BY ts DESC), so both the display
  // slice and the stop_ack_value scan below can walk each group in order without re-sorting.
  const byTrade = new Map();
  for (const row of eventRows) {
    const parsed = { ...row, payload: safeParse(row.payload) };
    if (!byTrade.has(row.trade_id)) byTrade.set(row.trade_id, []);
    byTrade.get(row.trade_id).push(parsed);
  }

  return positions.map((p) => {
    const all = byTrade.get(p.trade_id) || [];
    // stop_ack_value is derived from the FULL ordered list, not the capped display slice below —
    // a trade with >8 non-ack events since the last ack must not hide/stale-ify the ack value.
    const latestAck = all.find((e) => e.event_type === "stop_ack");
    const stop_ack_value = latestAck && typeof latestAck.payload.value === "number" ? latestAck.payload.value : null;
    return { ...p, events: all.slice(0, EVENTS_DISPLAY_CAP), stop_ack_value };
  });
}

function safeParse(s) {
  try {
    return JSON.parse(s || "{}");
  } catch {
    return {};
  }
}
