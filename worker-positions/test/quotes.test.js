import { describe, it, expect } from "vitest";
import { validateIngestBatch, ingestQuotes, heldTickers, HELD_STATES } from "../src/quotes.js";
import { authenticateService } from "../src/auth.js";

// ── validateIngestBatch (PURE) ──────────────────────────────────────────────────────────────────
describe("validateIngestBatch", () => {
  const good = {
    trade_date: "2026-08-13",
    collected_at: "2026-08-13T21:05:00Z",
    quotes: [{ ticker: "aapl", close: "231.5", high: 232, low: 230, atr: "3.1", raw: { Ticker: "AAPL", SMA20: "2.1%" } }],
  };

  it("accepts a well-formed batch and normalizes ticker + numerics", () => {
    const r = validateIngestBatch(good);
    expect(r.ok).toBe(true);
    expect(r.value.trade_date).toBe("2026-08-13");
    const row = r.value.rows[0];
    expect(row.ticker).toBe("AAPL"); // upper-cased
    expect(row.close).toBe(231.5); // string coerced to number
    expect(row.atr).toBe(3.1);
    expect(JSON.parse(row.raw).SMA20).toBe("2.1%"); // full scrape preserved verbatim
  });

  it("falls back to the whole quote as raw when no explicit raw given (#297 never drop capture)", () => {
    const r = validateIngestBatch({
      trade_date: "2026-08-13",
      collected_at: "t",
      quotes: [{ ticker: "MSFT", close: 400, RSI: "61" }],
    });
    expect(r.ok).toBe(true);
    const raw = JSON.parse(r.value.rows[0].raw);
    expect(raw.RSI).toBe("61");
    expect(raw.close).toBe(400);
  });

  it("coerces unparseable / blank numerics to null, not NaN", () => {
    const r = validateIngestBatch({
      trade_date: "2026-08-13",
      collected_at: "t",
      quotes: [{ ticker: "NVDA", close: "-", volume: "", atr: "n/a" }],
    });
    expect(r.value.rows[0].close).toBeNull();
    expect(r.value.rows[0].volume).toBeNull();
    expect(r.value.rows[0].atr).toBeNull();
  });

  it("truncates days_to_earnings to an int", () => {
    const r = validateIngestBatch({ trade_date: "2026-08-13", collected_at: "t", quotes: [{ ticker: "AMD", days_to_earnings: 12.9 }] });
    expect(r.value.rows[0].days_to_earnings).toBe(12);
  });

  it.each([
    [null, "JSON object"],
    [{ collected_at: "t", quotes: [] }, "trade_date"],
    [{ trade_date: "8/13/2026", collected_at: "t", quotes: [{ ticker: "A" }] }, "trade_date"],
    [{ trade_date: "2026-08-13", quotes: [{ ticker: "A" }] }, "collected_at"],
    [{ trade_date: "2026-08-13", collected_at: "t", quotes: [] }, "non-empty"],
    [{ trade_date: "2026-08-13", collected_at: "t", quotes: "x" }, "array"],
    [{ trade_date: "2026-08-13", collected_at: "t", quotes: [{ ticker: "1BAD" }] }, "ticker invalid"],
    [{ trade_date: "2026-08-13", collected_at: "t", quotes: [{ ticker: "AAPL", raw: [1, 2] }] }, "raw must be an object"],
  ])("rejects malformed batch %#", (body, needle) => {
    const r = validateIngestBatch(body);
    expect(r.ok).toBe(false);
    expect(r.error).toContain(needle);
  });
});

// ── ingestQuotes / heldTickers against a tiny D1 mock ───────────────────────────────────────────
function makeQuoteDb(seedPositions = []) {
  const quotes = new Map(); // key `${ticker}|${trade_date}` -> row (last-write-wins == ON CONFLICT)
  const positions = seedPositions.slice();
  function prepare(sql) {
    return {
      sql,
      _binds: [],
      bind(...args) {
        this._binds = args;
        return this;
      },
      async all() {
        // heldTickers: SELECT DISTINCT ticker FROM positions WHERE state IN (...)
        const states = this._binds;
        const set = [...new Set(positions.filter((p) => states.includes(p.state)).map((p) => p.ticker))].sort();
        return { results: set.map((t) => ({ ticker: t })) };
      },
    };
  }
  function _apply(sql, binds) {
    // INSERT INTO ticker_quotes (col,...) VALUES (?...) ON CONFLICT DO UPDATE
    const cols = sql.match(/\(([^)]+)\) VALUES/)[1].split(",").map((s) => s.trim());
    const row = {};
    cols.forEach((c, i) => (row[c] = binds[i]));
    quotes.set(`${row.ticker}|${row.trade_date}`, row); // upsert
  }
  return {
    prepare,
    async batch(stmts) {
      for (const s of stmts) _apply(s.sql, s._binds);
      return stmts.map(() => ({ success: true }));
    },
    _quotes: quotes,
  };
}

describe("ingestQuotes", () => {
  it("writes one row per (ticker, trade_date) with typed cols + raw + collected_at", async () => {
    const db = makeQuoteDb();
    const v = validateIngestBatch({
      trade_date: "2026-08-13",
      collected_at: "2026-08-13T21:05:00Z",
      quotes: [{ ticker: "AAPL", close: 231.5, raw: { Ticker: "AAPL" } }],
    }).value;
    const n = await ingestQuotes(db, v);
    expect(n).toBe(1);
    const row = db._quotes.get("AAPL|2026-08-13");
    expect(row.close).toBe(231.5);
    expect(row.collected_at).toBe("2026-08-13T21:05:00Z");
    expect(JSON.parse(row.raw).Ticker).toBe("AAPL");
  });

  it("is idempotent last-write-wins on a same-day re-run", async () => {
    const db = makeQuoteDb();
    const mk = (close) => validateIngestBatch({ trade_date: "2026-08-13", collected_at: "t", quotes: [{ ticker: "AAPL", close }] }).value;
    await ingestQuotes(db, mk(100));
    await ingestQuotes(db, mk(105)); // EOD correction of an intraday capture
    expect(db._quotes.size).toBe(1);
    expect(db._quotes.get("AAPL|2026-08-13").close).toBe(105);
  });

  it("chunks a large batch (>50) without dropping rows", async () => {
    const db = makeQuoteDb();
    const quotes = Array.from({ length: 137 }, (_, i) => ({ ticker: `T${i}`.replace(/(\d)/, "A$1").toUpperCase(), close: i }));
    const v = validateIngestBatch({ trade_date: "2026-08-13", collected_at: "t", quotes }).value;
    const n = await ingestQuotes(db, v);
    expect(n).toBe(137);
    expect(db._quotes.size).toBe(137);
  });
});

// NOTE: heldTickers() now also unions in the active watchlist (WS5 §8b, issue #319). That coverage
// lives in test/watchlist.test.js's "heldTickers union with active watchlist" describe block, using
// the real makeD1() shim from helpers/d1.js instead of this file's hand-rolled makeQuoteDb() mock —
// the watchlist table is real D1 schema, so a hand-rolled mock can't exercise its join/query.
describe("heldTickers", () => {
  it("returns DISTINCT open/managing/closing tickers, excludes watching/closed, user-agnostic", async () => {
    const db = makeQuoteDb([
      { ticker: "AAPL", state: "open", user_id: "owner" },
      { ticker: "AAPL", state: "managing", user_id: "owner" }, // dup ticker, still one
      { ticker: "MSFT", state: "closing", user_id: "someone-else" }, // no user scoping on market data
      { ticker: "TSLA", state: "watching", user_id: "owner" }, // excluded
      { ticker: "NVDA", state: "closed", user_id: "owner" }, // excluded
    ]);
    const t = await heldTickers(db);
    expect(t).toEqual(["AAPL", "MSFT"]);
  });

  it("HELD_STATES is exactly open/managing/closing", () => {
    expect(HELD_STATES).toEqual(["open", "managing", "closing"]);
  });
});

// ── authenticateService (service token) ─────────────────────────────────────────────────────────
describe("authenticateService", () => {
  const TOKEN = "ingest-token-super-secret-0123456789";
  const env = { POSITIONS_INGEST_TOKEN: TOKEN };
  const withAuth = (h) => new Request("https://x/ingest/quotes", { method: "POST", headers: h });

  it("accepts the exact bearer token", () => {
    expect(authenticateService(withAuth({ authorization: `Bearer ${TOKEN}` }), env)).toBe(true);
  });
  it("rejects a wrong token", () => {
    expect(authenticateService(withAuth({ authorization: "Bearer nope" }), env)).toBe(false);
  });
  it("rejects a missing header", () => {
    expect(authenticateService(withAuth({}), env)).toBe(false);
  });
  it("fails closed when POSITIONS_INGEST_TOKEN is unset", () => {
    expect(authenticateService(withAuth({ authorization: `Bearer ${TOKEN}` }), {})).toBe(false);
  });
});
