// Pre-close advisory compute for finviz-positions (WS5-8 PR-1a, issue: file when this lands).
//
// At 15:40 ET a GitHub-Actions job scrapes near-final bars for held tickers and POSTs them to
// POST /positions/preclose-advisory. This module runs the PURE advance() engine against each held
// position's CURRENT persisted state + that provisional bar, classifies what the engine WOULD
// signal, and stores ONLY the computed result in preclose_advisory. It is deliberately DISJOINT
// from positions/ticker_quotes/position_events — the 17:30 settled sweep (src/sweep.js) stays the
// sole writer of those three. A 15:40 write to ticker_quotes or positions.last_advanced_date would
// make the 17:30 sweep a no-op (loadBarsAfter's window would already be past today's bar), which is
// exactly the bug this module must never introduce. See worker-positions/CLAUDE.md § pre-close
// advisory for the invariant in one place.
//
// Design: this spec (WS5-8 PR-1a, locked). Reuses advance()/normalizeBar()/effectiveConfig() from
// advance.js verbatim — no engine logic is re-implemented here.

import { advance, normalizeBar, effectiveConfig } from "./advance.js";
import { loadAdvanceablePositions, barWindowStart } from "./sweep.js";

// Severity classification of an exit reason (advance.js EXIT_REASONS) for the advisory's "act" vs
// "heads_up" split. "act" = a genuine intraday-real signal (stop hit, a gap, a one-day crash) —
// worth acting on before the close. "heads_up" = close-referenced rules (MA closes) that are only
// PROVISIONAL off a 15:40 bar and may still firm up or reverse by the real close — worth watching,
// not necessarily acting on yet. Deliberately covers only the 5 reasons the locked spec named;
// `close_below_20ma` (reachable only via a per-position HARD_EXIT_BASIS="20ma" override — no
// position uses one today) and `manual_close` (never emitted by advance() itself) fall through to
// the DEFAULT_SEVERITY fallback below rather than throwing, since a config override is data, not a
// code path this module should need to know about ahead of time.
export const PRECLOSE_SEVERITY = Object.freeze({
  stop_hit: "act",
  gap_down_below_stop: "act",
  severe_breakdown: "act",
  close_below_50ma: "heads_up",
  two_close_below_20ma: "heads_up",
});
const DEFAULT_SEVERITY = "heads_up"; // unmapped exit reason (e.g. an override-only path) — never throw.

// The only category v1 emits (WS5-8b will add "reclaim").
const CATEGORY_EXIT = "exit";

function refLevelFor(reason, pos, bar) {
  switch (reason) {
    case "stop_hit":
    case "gap_down_below_stop":
      return typeof pos.current_stop === "number" ? pos.current_stop : null;
    case "close_below_50ma":
      return typeof bar.sma50 === "number" ? bar.sma50 : null;
    case "two_close_below_20ma":
      return typeof bar.sma20 === "number" ? bar.sma20 : null;
    default:
      // severe_breakdown and any unmapped reason have no single natural reference level.
      return null;
  }
}

// computePreCloseAdvisory(db, { quotes, trade_date, now }) — the compute + upsert.
//
// `quotes` is the validated ingest batch's `rows` array (validateIngestBatch's output shape, the
// SAME rows ingestQuotes() consumes) — each has `ticker`, `close`, `high`, `low`, `open`, `raw`
// (JSON string of the wide scrape), etc. NOTE (spec deviation, see PR description): those rows do
// NOT carry `trade_date` per-row — validateIngestBatch keeps `trade_date` at the batch level and
// ingestQuotes() stamps it onto every row only at INSERT time. normalizeBar() requires
// row.trade_date to be a pure function of the row (advance.js comment), so this function stamps
// the batch's `trade_date` onto each row before normalizing — mirroring what ingestQuotes() does,
// without touching ticker_quotes itself.
export async function computePreCloseAdvisory(db, { quotes, trade_date, now = new Date() }) {
  const ran_at = now.toISOString();

  // Map<ticker, quoteRow>, upper-cased key; last wins on a duplicate ticker in the batch.
  const byTicker = new Map();
  for (const q of quotes || []) {
    if (!q || typeof q.ticker !== "string") continue;
    byTicker.set(q.ticker.trim().toUpperCase(), q);
  }

  // Same two-state set the 17:30 sweep advances (open/managing) — a `closing` position already
  // carries its signal in the red confirmation strip and must not be re-reported here.
  const positions = await loadAdvanceablePositions(db);

  // Per-user accumulation: { checked, items }.
  const byUser = new Map();

  for (const pos of positions) {
    const userId = pos.user_id;
    if (!byUser.has(userId)) byUser.set(userId, { checked: 0, items: [] });
    const bucket = byUser.get(userId);
    bucket.checked++; // every open/managing position counts toward "your book" (drives the receipt count)

    // Only FLAG positions the 17:30 settled sweep would actually advance on today's bar. The sweep
    // gates each position on the exclusive window barWindowStart(pos) < trade_date (sweep.js); a
    // position entered today (or backdated, or already advanced today) is deliberately NOT advanced
    // on this bar — its entry-day `low` is largely pre-purchase and would fire a FALSE stop_hit. If
    // the advisory ignored that guard it would surface an "act — stop hit" the settled engine then
    // never confirms, directly contradicting the 17:30 result. So mirror the same window here: still
    // count it in the book above, but never evaluate/flag it.
    const windowStart = barWindowStart(pos);
    if (!windowStart || !(trade_date > windowStart)) continue;

    const quoteRow = byTicker.get((pos.ticker || "").toUpperCase());
    if (!quoteRow) continue; // no matching bar this run — counted, not reported.

    const bar = normalizeBar({ ...quoteRow, trade_date });
    const cfg = effectiveConfig(pos);
    // PURE, in-memory only: ONE bar, no persistence, the returned `position` is discarded — the
    // advisory must never advance real position state (HARD INVARIANT #1).
    const { events } = advance(pos, bar, cfg);

    // An exit is emitted as a SINGLE event_type "exit_signal" event carrying the reason in
    // payload.reason (see advance.js signalExit()) — not a reason-named event_type. Confirmed by
    // reading advance.js directly: `{ event_type: "exit_signal", payload: { reason, ... } }`.
    const exitEvent = events.find((e) => e.event_type === "exit_signal");
    if (!exitEvent) continue; // no exit signal this bar — counted, not reported.

    const reason = exitEvent.payload && exitEvent.payload.reason;
    const severity = PRECLOSE_SEVERITY[reason] || DEFAULT_SEVERITY;
    bucket.items.push({
      trade_id: pos.trade_id,
      ticker: pos.ticker,
      category: CATEGORY_EXIT,
      severity,
      signal: reason,
      price: bar.close,
      ref_level: refLevelFor(reason, pos, bar),
    });
  }

  // Upsert one row per user_id present in the loaded set — even n_flagged=0 gets a row (the "we
  // checked, nothing to act on" receipt the PWA reads).
  for (const [userId, bucket] of byUser) {
    await db
      .prepare(
        `INSERT INTO preclose_advisory (user_id, trade_date, ran_at, n_checked, n_flagged, items)
         VALUES (?, ?, ?, ?, ?, ?)
         ON CONFLICT(user_id, trade_date) DO UPDATE SET
           ran_at=excluded.ran_at, n_checked=excluded.n_checked, n_flagged=excluded.n_flagged, items=excluded.items`
      )
      .bind(userId, trade_date, ran_at, bucket.checked, bucket.items.length, JSON.stringify(bucket.items))
      .run();
  }

  let checked = 0;
  let flagged = 0;
  for (const bucket of byUser.values()) {
    checked += bucket.checked;
    flagged += bucket.items.length;
  }

  // Counts-only return (mirrors /advance's counts-only ethos for a service-token caller) — no
  // private per-position data crosses back to the caller of this function.
  return { trade_date, users: byUser.size, checked, flagged };
}

// readPreCloseAdvisory(db, user_id, trade_date) — the owner-bearer GET's read path.
export async function readPreCloseAdvisory(db, user_id, trade_date) {
  const row = await db
    .prepare("SELECT * FROM preclose_advisory WHERE user_id = ? AND trade_date = ?")
    .bind(user_id, trade_date)
    .first();
  if (!row) return null;
  let items = [];
  try {
    items = JSON.parse(row.items || "[]");
  } catch {
    items = [];
  }
  return { ran_at: row.ran_at, n_checked: row.n_checked, n_flagged: row.n_flagged, items };
}
