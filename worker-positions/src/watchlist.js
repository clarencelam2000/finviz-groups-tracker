// Personal watchlist domain logic for finviz-positions (WS5 §8b, issue #319, P1).
// Validation is a PURE function (unit-tested without D1); everything else is a thin DB helper.
// Design: planning/watchlist-build-brief-8b.md § 2 / § 4a / § 4b; worker-positions/CLAUDE.md.
//
// A watch item carries NO stop, NO size, ever — it is not a trade ticket (§1 of the brief). It
// carries a ticker and an OPTIONAL "carry your own" level of interest; the system read (breakout vs
// prior high, computed elsewhere by scripts/pick_status.py) always runs regardless of whether a
// level is set. Membership/level/TTL are PRIVATE and user-scoped here — the opposite privacy
// posture from ticker_quotes (migration 0002 header) — only an anonymous status row for the ticker
// rides the public morning store, built from watchlistTickerRefs()'s response, which OMITS
// level_value on purpose (see that function's comment).

import { etDateStr, isoUtc } from "./time.js";
import { normalizeBar } from "./advance.js";

const TICKER_RE = /^[A-Z][A-Z0-9.\-]{0,9}$/; // 1–10 chars, letters/digits/./-, starts with a letter. Same as positions.js/quotes.js.

export const LEVEL_TYPES = ["above", "below", "reclaim_20ma", "reclaim_50ma"];

// TTL (in TRADING MORNINGS, not calendar days) a watch entry starts/renews at. Decremented once per
// ET trading date on which the ticker HAS A BAR (skips "awaiting first read" mornings — see
// WS-POSITIONS-TTL-BURN in tickWatchlist()'s step 3 below). Owner-set (build brief § 6): 10 mornings
// is enough runway to see a setup develop without the list accumulating stale entries forever.
// Renewing (PATCH {renew:true}, or re-POSTing the same ticker via addWatch's upsert) resets the
// counter to this value.
export const WATCHLIST_TTL_SESSIONS = 10;

// Calendar days an `expired` entry lingers (collapsed bin in the UI) before tickWatchlist() purges
// it. Purge is keyed off expired_at (wall-clock ISO), NOT trading sessions — a short window keeps
// the table from growing unbounded while still giving the owner a few days to notice/renew before
// the row is gone for good.
export const WATCHLIST_PURGE_DAYS = 14;

function isFiniteNumber(x) {
  return typeof x === "number" && Number.isFinite(x);
}

// PURE. Shared level validation used by both validateAddPayload and validatePatchPayload's edit
// shape. body: { level_type?, level_value? }. Returns { ok:true, value:{level_type,level_value} } |
// { ok:false, error }.
function validateLevel(body) {
  const rawType = body.level_type;
  if (rawType === undefined || rawType === null || rawType === "") {
    // No-level entry: the level_value must also be absent — a value with no type is ambiguous, reject.
    if (body.level_value !== undefined && body.level_value !== null) {
      return { ok: false, error: "level_value requires a level_type" };
    }
    return { ok: true, value: { level_type: null, level_value: null } };
  }
  if (typeof rawType !== "string" || !LEVEL_TYPES.includes(rawType)) {
    return { ok: false, error: `level_type must be one of ${LEVEL_TYPES.join("|")}` };
  }
  if (rawType === "above" || rawType === "below") {
    const v = body.level_value;
    if (!isFiniteNumber(v) || v <= 0) return { ok: false, error: "level_value must be > 0 for above/below" };
    return { ok: true, value: { level_type: rawType, level_value: v } };
  }
  // reclaim_20ma / reclaim_50ma: the reference level IS the MA, never a user-supplied price.
  if (body.level_value !== undefined && body.level_value !== null) {
    return { ok: false, error: "level_value must be omitted for reclaim_20ma/reclaim_50ma" };
  }
  return { ok: true, value: { level_type: rawType, level_value: null } };
}

// PURE. Validate + normalize a POST /watchlist body: { ticker, level_type?, level_value? }.
export function validateAddPayload(body) {
  if (!body || typeof body !== "object") return { ok: false, error: "body must be a JSON object" };
  const ticker = typeof body.ticker === "string" ? body.ticker.trim().toUpperCase() : null;
  if (!ticker || !TICKER_RE.test(ticker)) return { ok: false, error: "ticker invalid (expect 1–10 alnum, e.g. AAPL)" };
  const lv = validateLevel(body);
  if (!lv.ok) return lv;
  return { ok: true, value: { ticker, ...lv.value } };
}

// PURE. Validate a PATCH /watchlist/:id body. Four shapes:
//   { renew: true }                     -> { ok:true, value:{ renew:true } }
//   { remove: true }                    -> { ok:true, value:{ remove:true } }  (soft-remove)
//   { restore: true }                   -> { ok:true, value:{ restore:true } } (undo a soft-remove)
//   { level_type?, level_value? }       -> { ok:true, value:{ level_type, level_value } } (edit)
// An empty/no-op body (none of the above present) is rejected — the caller must say what it wants
// changed. remove/restore mirror renew's shape exactly (a single boolean flag, no level payload) —
// see patchWatch for what each actually does to the row.
export function validatePatchPayload(body) {
  if (!body || typeof body !== "object") return { ok: false, error: "body must be a JSON object" };
  if (body.renew === true) return { ok: true, value: { renew: true } };
  if (body.remove === true) return { ok: true, value: { remove: true } };
  if (body.restore === true) return { ok: true, value: { restore: true } };
  const hasLevelKey = "level_type" in body || "level_value" in body;
  if (!hasLevelKey) return { ok: false, error: "body must set renew/remove/restore:true or a level_type/level_value edit" };
  const lv = validateLevel(body);
  if (!lv.ok) return lv;
  return { ok: true, value: lv.value };
}

const WATCH_COLS = [
  "user_id", "ticker", "level_type", "level_value", "sessions_remaining", "status",
  "created_at", "updated_at", "expired_at", "meta",
];

// UPSERT on (user_id, ticker): re-adding an existing watch RENEWS it (sessions_remaining reset to
// WATCHLIST_TTL_SESSIONS, status back to 'active', expired_at cleared) and updates the level — the
// intended UX per the build brief (§ 4b): "add" doubles as "renew + edit" for a ticker already on
// the list. created_at is set on insert only (ON CONFLICT's excluded.created_at is deliberately NOT
// referenced, so the original creation time survives every renew). Returns the resulting row.
export async function addWatch(db, { user_id, ticker, level_type, level_value, now = new Date() }) {
  const nowIso = isoUtc(now);
  const row = {
    user_id,
    ticker,
    level_type: level_type ?? null,
    level_value: level_value ?? null,
    sessions_remaining: WATCHLIST_TTL_SESSIONS,
    status: "active",
    created_at: nowIso,
    updated_at: nowIso,
    expired_at: null,
    meta: "{}",
  };
  const placeholders = WATCH_COLS.map(() => "?").join(", ");
  const sql =
    `INSERT INTO watchlist (${WATCH_COLS.join(", ")}) VALUES (${placeholders}) ` +
    `ON CONFLICT(user_id, ticker) DO UPDATE SET ` +
    `level_type=excluded.level_type, level_value=excluded.level_value, ` +
    `sessions_remaining=excluded.sessions_remaining, status=excluded.status, ` +
    `expired_at=excluded.expired_at, updated_at=excluded.updated_at`;
  await db.prepare(sql).bind(...WATCH_COLS.map((c) => row[c])).run();
  return db
    .prepare("SELECT * FROM watchlist WHERE user_id = ? AND ticker = ?")
    .bind(user_id, ticker)
    .first();
}

// Subquery joining each ticker to its LATEST ticker_quotes bar (max trade_date). Shared by listWatch
// and watchlistTickerRefs so the "latest bar" definition never drifts between the two callers.
const LATEST_BAR_JOIN = `
  LEFT JOIN (
    SELECT tq.* FROM ticker_quotes tq
    INNER JOIN (SELECT ticker, MAX(trade_date) AS trade_date FROM ticker_quotes GROUP BY ticker) lb
      ON tq.ticker = lb.ticker AND tq.trade_date = lb.trade_date
  ) q ON q.ticker = w.ticker
`;

function refsFromRow(q) {
  // No bar yet (freshly added ticker, first EOD hasn't landed) -> all-null refs, the "adding — first
  // check tomorrow AM" state the build brief § 3 describes. normalizeBar() itself tolerates a null
  // row, but we still guard explicitly here since the LEFT JOIN leaves every q_* column undefined.
  if (!q || q.q_trade_date == null) {
    return { prior_high: null, prior_low: null, atr: null, sma20: null, sma50: null };
  }
  const bar = normalizeBar({
    trade_date: q.q_trade_date,
    close: q.q_close,
    high: q.q_high,
    low: q.q_low,
    atr: q.q_atr,
    raw: q.q_raw,
  });
  return { prior_high: bar.high, prior_low: bar.low, atr: bar.atr, sma20: bar.sma20, sma50: bar.sma50 };
}

function safeParse(s) {
  try {
    return JSON.parse(s || "{}");
  } catch {
    return {};
  }
}

// List a user's watch rows (active + expired), newest active-first, each joined to its latest bar's
// recovered levels (prior_high/prior_low/atr/sma20/sma50 — null when no bar exists yet). ALWAYS
// scoped by user_id (app-layer tenant boundary; D1 has no RLS — ADR-012).
export async function listWatch(db, user_id) {
  const sql = `
    SELECT w.*, q.trade_date AS q_trade_date, q.close AS q_close, q.high AS q_high, q.low AS q_low,
           q.atr AS q_atr, q.raw AS q_raw
    FROM watchlist w
    ${LATEST_BAR_JOIN}
    WHERE w.user_id = ?
    ORDER BY (w.status = 'active') DESC, w.id DESC
  `;
  const { results } = await db.prepare(sql).bind(user_id).all();
  return results.map((r) => {
    const { q_trade_date, q_close, q_high, q_low, q_atr, q_raw, ...w } = r;
    return { ...w, meta: safeParse(w.meta), ...refsFromRow(r) };
  });
}

// User-scoped UPDATE by id. renew resets the TTL/status; remove soft-deletes (status='removed',
// stops heldTickers()'s scrape union on the next held-feed run, still visible to the owner in a
// collapsed "Recently removed" bin); restore undoes a remove back to 'active' with a fresh TTL
// (same renew semantics — a restored ticker gets a full run, not the TTL it happened to have left
// when removed); otherwise applies a level edit. Returns { changed:boolean } — false means not
// found OR not owned by this user (indistinguishable on purpose, matching listPositions/deleteWatch's
// tenant-scoping convention elsewhere in this worker).
export async function patchWatch(db, { user_id, id, renew, remove, restore, level_type, level_value, now = new Date() }) {
  const nowIso = isoUtc(now);
  let sql;
  let binds;
  if (renew || restore) {
    sql = `UPDATE watchlist SET sessions_remaining = ?, status = 'active', expired_at = NULL, removed_at = NULL, updated_at = ? WHERE user_id = ? AND id = ?`;
    binds = [WATCHLIST_TTL_SESSIONS, nowIso, user_id, id];
  } else if (remove) {
    sql = `UPDATE watchlist SET status = 'removed', removed_at = ?, updated_at = ? WHERE user_id = ? AND id = ?`;
    binds = [nowIso, nowIso, user_id, id];
  } else {
    sql = `UPDATE watchlist SET level_type = ?, level_value = ?, updated_at = ? WHERE user_id = ? AND id = ?`;
    binds = [level_type ?? null, level_value ?? null, nowIso, user_id, id];
  }
  const res = await db.prepare(sql).bind(...binds).run();
  return { changed: (res.meta && res.meta.changes) > 0 };
}

// User-scoped DELETE by id (also called on graduation — the PWA deletes the watch entry right after
// POST /positions succeeds, § build brief "GRADUATE").
export async function deleteWatch(db, { user_id, id }) {
  const res = await db.prepare("DELETE FROM watchlist WHERE user_id = ? AND id = ?").bind(user_id, id).run();
  return { changed: (res.meta && res.meta.changes) > 0 };
}

// The active-watch ticker set, for heldTickers()'s union (src/quotes.js). User-LESS on purpose —
// same rationale as heldTickers itself: this selects which symbols the market-data feed must fetch,
// not who owns them. status = 'active' excludes BOTH 'expired' and 'removed' rows — a soft-removed
// ticker (patchWatch's remove branch) drops out of the scrape union on the very next held-feed run
// with no separate filter needed here.
export async function watchlistTickers(db) {
  const { results } = await db
    .prepare("SELECT DISTINCT ticker FROM watchlist WHERE status = 'active' ORDER BY ticker")
    .all();
  return results.map((r) => r.ticker);
}

// For GET /watchlist-tickers (service token, scripts/collect_morning.py): every ACTIVE watch row
// joined to its latest bar, WITHOUT level_value. This is the privacy-load-bearing omission (build
// brief § "Locked design decisions" P1 spec item 1): the CI/service path never needs the user's
// price level — the your-level read happens client-side off the owner's own GET /watchlist. Only
// level_type rides here (needed to know WHICH reference the morning job's reclaim check should use).
// De-dupes by ticker if multiple users watch the same one (moot at user=1; GROUP BY picks the
// lowest id arbitrarily, which is fine — it's the same market-data refs either way).
//
// `has_history` (WS-POSITIONS-STATUS, 2026-08-25): true iff a bar exists at all for this ticker,
// i.e. the exact condition refsFromRow() itself gates on. Lets collect_morning.py/pick_status.py
// tell "never had a bar yet" (a brand-new watch ticker, expected) apart from "had a quote request
// today and it came back empty" (a genuine Finviz miss) — both used to collapse into the same
// no_quote status/copy, which is what let the 2026-08-20 union-outage incident go unnoticed and is
// what showed a misleading "feed missed this ticker" message on a ticker that had simply never had
// data. See planning/watchlist-status-honesty-and-seeding.md.
export async function watchlistTickerRefs(db) {
  const sql = `
    SELECT w.ticker, w.level_type, q.trade_date AS q_trade_date, q.close AS q_close, q.high AS q_high,
           q.low AS q_low, q.atr AS q_atr, q.raw AS q_raw
    FROM watchlist w
    ${LATEST_BAR_JOIN}
    WHERE w.status = 'active'
    GROUP BY w.ticker
    ORDER BY w.ticker
  `;
  const { results } = await db.prepare(sql).all();
  return results.map((r) => ({
    ticker: r.ticker,
    level_type: r.level_type,
    has_history: r.q_trade_date != null,
    ...refsFromRow(r),
  }));
}

// Idempotent-per-ET-date TTL decrement + expire + purge. Called by POST /watchlist/tick (service
// token) once per morning run, right after collect_morning.py's status write (build brief § 3).
//   1. Resolve the ET trading date to tick (explicit `date` wins, else derived from `now`).
//   2. INSERT OR IGNORE into watchlist_tick_log — if a row for this date already exists, the insert
//      changes 0 rows and we return early with ticked:false (double-run guard: a GitHub Actions
//      retry or the tests.yml/collect.yml backstop firing twice must not double-decrement).
//   3. Decrement sessions_remaining for every 'active' row WHOSE TICKER HAS AT LEAST ONE
//      ticker_quotes BAR (WS-POSITIONS-TTL-BURN). A brand-new watch ticker with no bar yet is in
//      the "awaiting_first_read" state — no real classification could have happened for it, so a
//      tick over a weekend/holiday gap before its first EOD read must not burn TTL. The "has a bar"
//      boundary matches has_history in watchlistTickerRefs() (q_trade_date != null) exactly.
//      Awaiting rows are left at full TTL, which is what keeps step 4 from expiring them early.
//   4. Expire rows that hit 0 (status='expired', expired_at=now).
//   5. Purge 'expired' AND 'removed' rows older than WATCHLIST_PURGE_DAYS calendar days (by
//      expired_at / removed_at respectively) — same lingering-collapsed-bin-then-gone lifecycle for
//      both terminal statuses, so a "Recently removed" bin doesn't grow unbounded either.
export async function tickWatchlist(db, { date, now = new Date() } = {}) {
  const tickDate = date || etDateStr(now);
  const nowIso = isoUtc(now);

  const ins = await db.prepare("INSERT OR IGNORE INTO watchlist_tick_log (tick_date) VALUES (?)").bind(tickDate).run();
  const inserted = (ins.meta && ins.meta.changes) > 0;
  if (!inserted) return { ticked: false, decremented: 0, expired: 0, purged: 0, skipped_no_history: 0 };

  const dec = await db
    .prepare(
      "UPDATE watchlist SET sessions_remaining = sessions_remaining - 1, updated_at = ? " +
        "WHERE status = 'active' AND ticker IN (SELECT ticker FROM ticker_quotes)"
    )
    .bind(nowIso)
    .run();
  const decremented = (dec.meta && dec.meta.changes) || 0;

  const skippedRow = await db
    .prepare(
      "SELECT COUNT(*) AS n FROM watchlist WHERE status = 'active' AND ticker NOT IN (SELECT ticker FROM ticker_quotes)"
    )
    .first();
  const skipped_no_history = (skippedRow && skippedRow.n) || 0;

  const exp = await db
    .prepare("UPDATE watchlist SET status = 'expired', expired_at = ? WHERE status = 'active' AND sessions_remaining <= 0")
    .bind(nowIso)
    .run();
  const expired = (exp.meta && exp.meta.changes) || 0;

  // Cutoff = now − WATCHLIST_PURGE_DAYS calendar days, as an ISO string — expired_at is also ISO, so
  // a plain string compare is correct (both are UTC, same fixed-width format).
  const cutoffMs = now.getTime() - WATCHLIST_PURGE_DAYS * 24 * 60 * 60 * 1000;
  const cutoffIso = new Date(cutoffMs).toISOString();
  const purgeExpired = await db
    .prepare("DELETE FROM watchlist WHERE status = 'expired' AND expired_at IS NOT NULL AND expired_at < ?")
    .bind(cutoffIso)
    .run();
  const purgeRemoved = await db
    .prepare("DELETE FROM watchlist WHERE status = 'removed' AND removed_at IS NOT NULL AND removed_at < ?")
    .bind(cutoffIso)
    .run();
  const purged = ((purgeExpired.meta && purgeExpired.meta.changes) || 0) + ((purgeRemoved.meta && purgeRemoved.meta.changes) || 0);

  return { ticked: true, decremented, expired, purged, skipped_no_history };
}
