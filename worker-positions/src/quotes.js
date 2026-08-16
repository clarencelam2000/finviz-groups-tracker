// Held-tickers quote feed for finviz-positions (WS5 phase 2).
// Two machine-facing operations behind the service-token auth path (src/auth.js authenticateService):
//   * heldTickers(db)          — the union of currently-held symbols the GH-Actions job must scrape.
//   * ingestQuotes(db, batch)  — append-only write of a day's scraped bars into ticker_quotes.
// Validation of the ingest payload is a PURE function (unit-tested without D1). Design:
// planning/trade-lifecycle-engine.md § 5 / § 5a; ADR-012 § 10 / § 11; issues #312, #297.

import { watchlistTickers } from "./watchlist.js";

const TICKER_RE = /^[A-Z][A-Z0-9.\-]{0,9}$/; // 1–10 chars, letters/digits/./-, starts with a letter.
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/; // ET trading date YYYY-MM-DD.

// States whose positions count as "held" for feed membership (§ 5a: what you already own). `closing`
// is included on purpose — a position awaiting exit-confirmation must keep accruing bars so there is
// no gap in its series (§ 11a feed/catch-up decision). `watching`/`closed` are NOT held.
export const HELD_STATES = ["open", "managing", "closing"];

// Typed columns we persist besides ticker/trade_date/raw/collected_at. Everything scraped is ALSO
// kept verbatim in `raw` (#297), so this list is "what the engine reads directly", not "all we keep".
const QUOTE_NUMERIC_COLS = ["prev_close", "open", "high", "low", "close", "change_pct", "atr", "volume"];

function toNumOrNull(x) {
  if (x === null || x === undefined || x === "") return null;
  const n = typeof x === "number" ? x : Number(x);
  return Number.isFinite(n) ? n : null;
}
function toIntOrNull(x) {
  const n = toNumOrNull(x);
  return n === null ? null : Math.trunc(n);
}

// PURE. Validate + normalize an ingest batch: { trade_date, collected_at, quotes: [...] }.
// Returns { ok:true, value:{ trade_date, collected_at, rows:[...] } } or { ok:false, error }.
// A single bad ticker/trade_date fails the whole batch (the job re-runs idempotently, so partial
// junk is worse than a clean retry). Unknown/extra keys in a quote are preserved into `raw` by the
// caller — validation only pins down the typed columns + identity fields.
export function validateIngestBatch(body) {
  if (!body || typeof body !== "object") return { ok: false, error: "body must be a JSON object" };
  const trade_date = typeof body.trade_date === "string" ? body.trade_date.trim() : null;
  if (!trade_date || !DATE_RE.test(trade_date)) return { ok: false, error: "trade_date must be YYYY-MM-DD" };
  const collected_at = typeof body.collected_at === "string" && body.collected_at.trim()
    ? body.collected_at.trim()
    : null;
  if (!collected_at) return { ok: false, error: "collected_at (ISO-8601 UTC) required" };
  if (!Array.isArray(body.quotes)) return { ok: false, error: "quotes must be an array" };
  if (body.quotes.length === 0) return { ok: false, error: "quotes must be non-empty" };

  const rows = [];
  for (let i = 0; i < body.quotes.length; i++) {
    const q = body.quotes[i];
    if (!q || typeof q !== "object" || Array.isArray(q)) return { ok: false, error: `quotes[${i}] must be an object` };
    const ticker = typeof q.ticker === "string" ? q.ticker.trim().toUpperCase() : null;
    if (!ticker || !TICKER_RE.test(ticker)) return { ok: false, error: `quotes[${i}].ticker invalid: ${q.ticker}` };
    // `raw` is the full scrape map (#297). If the caller doesn't send one explicitly, fall back to
    // the whole quote object minus the identity/collected fields — never drop the wide capture.
    let raw = q.raw;
    if (raw == null) {
      raw = { ...q };
      delete raw.raw;
      delete raw.collected_at;
    }
    if (typeof raw !== "object" || Array.isArray(raw)) return { ok: false, error: `quotes[${i}].raw must be an object` };
    const row = { ticker, days_to_earnings: toIntOrNull(q.days_to_earnings), raw: JSON.stringify(raw) };
    for (const c of QUOTE_NUMERIC_COLS) row[c] = toNumOrNull(q[c]);
    rows.push(row);
  }
  return { ok: true, value: { trade_date, collected_at, rows } };
}

const INGEST_COLS = [
  "ticker", "trade_date", ...QUOTE_NUMERIC_COLS, "days_to_earnings", "raw", "collected_at",
];

// Append-only insert of a validated batch. One row per (ticker, trade_date); a same-day re-run
// is idempotent last-write-wins via ON CONFLICT DO UPDATE (see migration 0002 rationale). Chunked
// into D1 batches so a large held set stays under statement limits. Returns the row count written.
export async function ingestQuotes(db, value) {
  const { trade_date, collected_at, rows } = value;
  const placeholders = INGEST_COLS.map(() => "?").join(", ");
  const updates = INGEST_COLS.filter((c) => c !== "ticker" && c !== "trade_date")
    .map((c) => `${c}=excluded.${c}`)
    .join(", ");
  const sql =
    `INSERT INTO ticker_quotes (${INGEST_COLS.join(", ")}) VALUES (${placeholders}) ` +
    `ON CONFLICT(ticker, trade_date) DO UPDATE SET ${updates}`;
  const CHUNK = 50;
  let written = 0;
  for (let i = 0; i < rows.length; i += CHUNK) {
    const stmts = rows.slice(i, i + CHUNK).map((r) => {
      const full = { ...r, trade_date, collected_at };
      return db.prepare(sql).bind(...INGEST_COLS.map((c) => full[c]));
    });
    await db.batch(stmts);
    written += stmts.length;
  }
  return written;
}

// The feed set the held-tickers job must scrape: DISTINCT tickers across all users' held positions
// UNION the active personal watchlist (WS5 §8b, issue #319 — a watch item rides the EOD held feed
// to accumulate the prior-day High/Low/ATR/MAs a fresh watch has no bar history for yet, build
// brief § 3). Market data is user-less (§ 5), so we intentionally do NOT scope either half by
// user_id — the symbol list is shared.
export async function heldTickers(db) {
  const marks = HELD_STATES.map(() => "?").join(", ");
  const [{ results: posResults }, watchTickers] = await Promise.all([
    db.prepare(`SELECT DISTINCT ticker FROM positions WHERE state IN (${marks}) ORDER BY ticker`).bind(...HELD_STATES).all(),
    watchlistTickers(db),
  ]);
  const merged = new Set([...posResults.map((r) => r.ticker), ...watchTickers]);
  return [...merged].sort();
}
