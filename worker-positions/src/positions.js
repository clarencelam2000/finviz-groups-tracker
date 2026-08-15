// Positions domain logic for finviz-positions (WS5 phase 1).
// Validation is a PURE function (unit-tested without D1); the create/list helpers are the only
// DB-touching code. Design: planning/trade-lifecycle-engine.md § 3, § 4, § 8a; ADR-012.

import { etDateStr, isoUtc } from "./time.js";

// Stop bases the WS4 ticket offers, plus 'manual' for the future free-entry form (§ 8a).
export const STOP_BASES = ["prior_day_low", "todays_low", "20ma", "50ma", "manual"];
const TICKER_RE = /^[A-Z][A-Z0-9.\-]{0,9}$/; // 1–10 chars, letters/digits/./-, starts with a letter.

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

// List a user's positions, newest first. `state` optionally filters (e.g. 'open'); omitted = all.
// ALWAYS scoped by user_id — the app-layer tenant boundary (D1 has no RLS; ADR-012).
export async function listPositions(db, user_id, state = null) {
  const stmt = state
    ? db.prepare("SELECT * FROM positions WHERE user_id = ? AND state = ? ORDER BY opened_at DESC").bind(user_id, state)
    : db.prepare("SELECT * FROM positions WHERE user_id = ? ORDER BY opened_at DESC").bind(user_id);
  const { results } = await stmt.all();
  return results.map((r) => ({ ...r, meta: safeParse(r.meta) }));
}

function safeParse(s) {
  try {
    return JSON.parse(s || "{}");
  } catch {
    return {};
  }
}
