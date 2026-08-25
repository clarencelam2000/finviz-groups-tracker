import { describe, it, expect } from "vitest";
import {
  LEVEL_TYPES,
  WATCHLIST_TTL_SESSIONS,
  WATCHLIST_PURGE_DAYS,
  validateAddPayload,
  validatePatchPayload,
  addWatch,
  listWatch,
  patchWatch,
  deleteWatch,
  watchlistTickers,
  watchlistTickerRefs,
  tickWatchlist,
} from "../src/watchlist.js";
import { heldTickers } from "../src/quotes.js";
import { makeD1 } from "./helpers/d1.js";

// ── validateAddPayload (PURE) ───────────────────────────────────────────────────────────────────
describe("validateAddPayload", () => {
  it("accepts above with a value", () => {
    const r = validateAddPayload({ ticker: "aapl", level_type: "above", level_value: 200 });
    expect(r.ok).toBe(true);
    expect(r.value).toEqual({ ticker: "AAPL", level_type: "above", level_value: 200 });
  });

  it("accepts below with a value", () => {
    const r = validateAddPayload({ ticker: "MSFT", level_type: "below", level_value: 300 });
    expect(r.ok).toBe(true);
    expect(r.value.level_value).toBe(300);
  });

  it("accepts reclaim_20ma / reclaim_50ma with no value", () => {
    for (const t of ["reclaim_20ma", "reclaim_50ma"]) {
      const r = validateAddPayload({ ticker: "NVDA", level_type: t });
      expect(r.ok).toBe(true);
      expect(r.value).toEqual({ ticker: "NVDA", level_type: t, level_value: null });
    }
  });

  it("accepts a no-level entry (level_type absent/null/empty)", () => {
    expect(validateAddPayload({ ticker: "TSLA" }).value).toEqual({ ticker: "TSLA", level_type: null, level_value: null });
    expect(validateAddPayload({ ticker: "TSLA", level_type: null }).ok).toBe(true);
    expect(validateAddPayload({ ticker: "TSLA", level_type: "" }).ok).toBe(true);
  });

  it("rejects a bad ticker", () => {
    expect(validateAddPayload({ ticker: "1BAD" }).ok).toBe(false);
    expect(validateAddPayload({ ticker: "" }).ok).toBe(false);
    expect(validateAddPayload({}).ok).toBe(false);
  });

  it("rejects above/below missing a value", () => {
    expect(validateAddPayload({ ticker: "AAPL", level_type: "above" }).ok).toBe(false);
    expect(validateAddPayload({ ticker: "AAPL", level_type: "below", level_value: -5 }).ok).toBe(false);
  });

  it("rejects a value supplied WITH a reclaim type", () => {
    const r = validateAddPayload({ ticker: "AAPL", level_type: "reclaim_20ma", level_value: 100 });
    expect(r.ok).toBe(false);
    expect(r.error).toContain("reclaim");
  });

  it("rejects an unknown level_type", () => {
    const r = validateAddPayload({ ticker: "AAPL", level_type: "moonshot" });
    expect(r.ok).toBe(false);
    expect(r.error).toContain(LEVEL_TYPES.join("|"));
  });
});

// ── validatePatchPayload (PURE) ─────────────────────────────────────────────────────────────────
describe("validatePatchPayload", () => {
  it("accepts the renew shape", () => {
    expect(validatePatchPayload({ renew: true })).toEqual({ ok: true, value: { renew: true } });
  });

  it("accepts an edit-level shape", () => {
    const r = validatePatchPayload({ level_type: "above", level_value: 150 });
    expect(r.ok).toBe(true);
    expect(r.value).toEqual({ level_type: "above", level_value: 150 });
  });

  it("accepts clearing the level via level_type: null", () => {
    const r = validatePatchPayload({ level_type: null });
    expect(r.ok).toBe(true);
    expect(r.value).toEqual({ level_type: null, level_value: null });
  });

  it("rejects an empty/no-op body", () => {
    expect(validatePatchPayload({}).ok).toBe(false);
    expect(validatePatchPayload(null).ok).toBe(false);
  });

  it("rejects an invalid edit-level payload the same way validateAddPayload would", () => {
    const r = validatePatchPayload({ level_type: "above" }); // missing value
    expect(r.ok).toBe(false);
  });
});

// ── addWatch (UPSERT) ───────────────────────────────────────────────────────────────────────────
describe("addWatch", () => {
  it("inserts a new row with sessions_remaining=TTL, status=active", async () => {
    const db = makeD1();
    const row = await addWatch(db, { user_id: "owner", ticker: "AAPL", level_type: "above", level_value: 200 });
    expect(row.sessions_remaining).toBe(WATCHLIST_TTL_SESSIONS);
    expect(row.status).toBe("active");
    expect(row.level_value).toBe(200);
    expect(db._watchlist()).toHaveLength(1);
  });

  it("re-adding the same (user,ticker) UPSERTs: renews TTL, updates level, does not duplicate, keeps created_at", async () => {
    const db = makeD1();
    const first = await addWatch(db, { user_id: "owner", ticker: "AAPL", level_type: "above", level_value: 200, now: new Date("2026-08-01T00:00:00Z") });
    // Simulate the entry having ticked down and drifted from the TTL default.
    await tickWatchlist(db, { date: "2026-08-05", now: new Date("2026-08-05T21:00:00Z") });
    const second = await addWatch(db, {
      user_id: "owner",
      ticker: "AAPL",
      level_type: "below",
      level_value: 150,
      now: new Date("2026-08-10T00:00:00Z"),
    });
    expect(db._watchlist()).toHaveLength(1); // no duplicate row
    expect(second.id).toBe(first.id);
    expect(second.level_type).toBe("below");
    expect(second.level_value).toBe(150);
    expect(second.sessions_remaining).toBe(WATCHLIST_TTL_SESSIONS);
    expect(second.status).toBe("active");
    expect(second.created_at).toBe(first.created_at); // unchanged on renew
  });
});

// ── listWatch ───────────────────────────────────────────────────────────────────────────────────
describe("listWatch", () => {
  it("joins the latest ticker_quotes bar and recovers prior_high/prior_low/atr/sma20/sma50", async () => {
    const db = makeD1();
    db._seedWatchlist({ user_id: "owner", ticker: "AAPL", id: undefined });
    // Older bar (should be superseded by the latest one below).
    db._seedQuote({ ticker: "AAPL", trade_date: "2026-08-10", close: 200, high: 205, low: 198, atr: 4, raw: JSON.stringify({ SMA20: "-50%" }) });
    // Latest bar: close=220, SMA20 %-distance = 2.0% above -> level = 220/1.02.
    db._seedQuote({
      ticker: "AAPL",
      trade_date: "2026-08-13",
      close: 220,
      high: 222,
      low: 218,
      atr: 5,
      raw: JSON.stringify({ SMA20: "2.0%", SMA50: "-4.0%" }),
    });
    const rows = await listWatch(db, "owner");
    expect(rows).toHaveLength(1);
    const r = rows[0];
    expect(r.prior_high).toBe(222);
    expect(r.prior_low).toBe(218);
    expect(r.atr).toBe(5);
    expect(r.sma20).toBeCloseTo(220 / 1.02, 6);
    expect(r.sma50).toBeCloseTo(220 / 0.96, 6);
  });

  it("returns null refs when no bar exists yet", async () => {
    const db = makeD1();
    db._seedWatchlist({ user_id: "owner", ticker: "FRESH" });
    const rows = await listWatch(db, "owner");
    expect(rows[0].prior_high).toBeNull();
    expect(rows[0].prior_low).toBeNull();
    expect(rows[0].atr).toBeNull();
    expect(rows[0].sma20).toBeNull();
    expect(rows[0].sma50).toBeNull();
  });

  it("is user-scoped (another user's rows not returned)", async () => {
    const db = makeD1();
    db._seedWatchlist({ user_id: "owner", ticker: "AAPL" });
    db._seedWatchlist({ user_id: "someone_else", ticker: "MSFT" });
    const rows = await listWatch(db, "owner");
    expect(rows).toHaveLength(1);
    expect(rows[0].ticker).toBe("AAPL");
  });

  it("parses meta and includes active+expired rows", async () => {
    const db = makeD1();
    db._seedWatchlist({ user_id: "owner", ticker: "AAPL", meta: JSON.stringify({ note: "x" }) });
    db._seedWatchlist({ user_id: "owner", ticker: "MSFT", status: "expired", expired_at: "2026-08-01T00:00:00Z" });
    const rows = await listWatch(db, "owner");
    expect(rows).toHaveLength(2);
    expect(rows.find((r) => r.ticker === "AAPL").meta).toEqual({ note: "x" });
  });
});

// ── patchWatch / deleteWatch ────────────────────────────────────────────────────────────────────
describe("patchWatch", () => {
  it("renew resets TTL and status, clears expired_at", async () => {
    const db = makeD1();
    const seeded = db._seedWatchlist({ user_id: "owner", ticker: "AAPL", sessions_remaining: 0, status: "expired", expired_at: "2026-08-01T00:00:00Z" });
    const row = db._watchlist()[0];
    const res = await patchWatch(db, { user_id: "owner", id: row.id, renew: true });
    expect(res.changed).toBe(true);
    const after = db._watchlist()[0];
    expect(after.sessions_remaining).toBe(WATCHLIST_TTL_SESSIONS);
    expect(after.status).toBe("active");
    expect(after.expired_at).toBeNull();
  });

  it("edits the level", async () => {
    const db = makeD1();
    db._seedWatchlist({ user_id: "owner", ticker: "AAPL" });
    const row = db._watchlist()[0];
    const res = await patchWatch(db, { user_id: "owner", id: row.id, level_type: "below", level_value: 100 });
    expect(res.changed).toBe(true);
    const after = db._watchlist()[0];
    expect(after.level_type).toBe("below");
    expect(after.level_value).toBe(100);
  });

  it("is user-scoped: wrong user -> not changed", async () => {
    const db = makeD1();
    db._seedWatchlist({ user_id: "owner", ticker: "AAPL" });
    const row = db._watchlist()[0];
    const res = await patchWatch(db, { user_id: "someone_else", id: row.id, renew: true });
    expect(res.changed).toBe(false);
  });

  it("unknown id -> not changed", async () => {
    const db = makeD1();
    const res = await patchWatch(db, { user_id: "owner", id: 9999, renew: true });
    expect(res.changed).toBe(false);
  });
});

describe("deleteWatch", () => {
  it("deletes an owned row", async () => {
    const db = makeD1();
    db._seedWatchlist({ user_id: "owner", ticker: "AAPL" });
    const row = db._watchlist()[0];
    const res = await deleteWatch(db, { user_id: "owner", id: row.id });
    expect(res.changed).toBe(true);
    expect(db._watchlist()).toHaveLength(0);
  });

  it("is user-scoped: wrong user -> not changed, row survives", async () => {
    const db = makeD1();
    db._seedWatchlist({ user_id: "owner", ticker: "AAPL" });
    const row = db._watchlist()[0];
    const res = await deleteWatch(db, { user_id: "someone_else", id: row.id });
    expect(res.changed).toBe(false);
    expect(db._watchlist()).toHaveLength(1);
  });
});

// ── watchlistTickers / watchlistTickerRefs ─────────────────────────────────────────────────────
describe("watchlistTickers", () => {
  it("returns only active tickers, DISTINCT, user-less", async () => {
    const db = makeD1();
    db._seedWatchlist({ user_id: "owner", ticker: "AAPL" });
    db._seedWatchlist({ user_id: "someone_else", ticker: "MSFT" });
    db._seedWatchlist({ user_id: "owner", ticker: "TSLA", status: "expired", expired_at: "2026-08-01T00:00:00Z" });
    const t = await watchlistTickers(db);
    expect(t).toEqual(["AAPL", "MSFT"]);
  });
});

describe("watchlistTickerRefs", () => {
  it("returns active-only refs WITHOUT level_value, with level_type", async () => {
    const db = makeD1();
    db._seedWatchlist({ user_id: "owner", ticker: "AAPL", level_type: "above", level_value: 200 });
    db._seedWatchlist({ user_id: "owner", ticker: "MSFT", status: "expired", expired_at: "2026-08-01T00:00:00Z" });
    db._seedQuote({ ticker: "AAPL", trade_date: "2026-08-13", close: 220, high: 222, low: 218, atr: 5, raw: "{}" });
    const refs = await watchlistTickerRefs(db);
    expect(refs).toHaveLength(1);
    expect(refs[0].ticker).toBe("AAPL");
    expect(refs[0].level_type).toBe("above");
    expect(refs[0]).not.toHaveProperty("level_value");
    expect(refs[0].prior_high).toBe(222);
    expect(refs[0].prior_low).toBe(218);
    expect(refs[0].has_history).toBe(true);
  });

  it("has_history is false for a ticker with no bar yet (WS-POSITIONS-STATUS)", async () => {
    const db = makeD1();
    db._seedWatchlist({ user_id: "owner", ticker: "SMCI" });
    const refs = await watchlistTickerRefs(db);
    expect(refs).toHaveLength(1);
    expect(refs[0].has_history).toBe(false);
    expect(refs[0].prior_high).toBeNull();
  });

  it("de-dupes by ticker when multiple users watch the same one", async () => {
    const db = makeD1();
    db._seedWatchlist({ user_id: "owner", ticker: "AAPL" });
    db._seedWatchlist({ user_id: "someone_else", ticker: "AAPL" });
    const refs = await watchlistTickerRefs(db);
    expect(refs).toHaveLength(1);
  });
});

// ── tickWatchlist ────────────────────────────────────────────────────────────────────────────────
describe("tickWatchlist", () => {
  it("decrements active rows and reports ticked:true", async () => {
    const db = makeD1();
    db._seedWatchlist({ user_id: "owner", ticker: "AAPL", sessions_remaining: 10 });
    db._seedWatchlist({ user_id: "owner", ticker: "MSFT", sessions_remaining: 3 });
    const res = await tickWatchlist(db, { date: "2026-08-13", now: new Date("2026-08-13T21:05:00Z") });
    expect(res).toEqual({ ticked: true, decremented: 2, expired: 0, purged: 0 });
    const rows = db._watchlist();
    expect(rows.find((r) => r.ticker === "AAPL").sessions_remaining).toBe(9);
    expect(rows.find((r) => r.ticker === "MSFT").sessions_remaining).toBe(2);
  });

  it("a second call on the SAME date is a no-op (ticked:false)", async () => {
    const db = makeD1();
    db._seedWatchlist({ user_id: "owner", ticker: "AAPL", sessions_remaining: 10 });
    await tickWatchlist(db, { date: "2026-08-13", now: new Date("2026-08-13T21:05:00Z") });
    const res2 = await tickWatchlist(db, { date: "2026-08-13", now: new Date("2026-08-13T23:00:00Z") });
    expect(res2).toEqual({ ticked: false, decremented: 0, expired: 0, purged: 0 });
    expect(db._watchlist()[0].sessions_remaining).toBe(9); // unchanged by the second call
  });

  it("a DIFFERENT date ticks again", async () => {
    const db = makeD1();
    db._seedWatchlist({ user_id: "owner", ticker: "AAPL", sessions_remaining: 10 });
    await tickWatchlist(db, { date: "2026-08-13", now: new Date("2026-08-13T21:05:00Z") });
    const res2 = await tickWatchlist(db, { date: "2026-08-14", now: new Date("2026-08-14T21:05:00Z") });
    expect(res2.ticked).toBe(true);
    expect(res2.decremented).toBe(1);
    expect(db._watchlist()[0].sessions_remaining).toBe(8);
  });

  it("expires rows that hit 0", async () => {
    const db = makeD1();
    db._seedWatchlist({ user_id: "owner", ticker: "AAPL", sessions_remaining: 1 });
    const res = await tickWatchlist(db, { date: "2026-08-13", now: new Date("2026-08-13T21:05:00Z") });
    expect(res.expired).toBe(1);
    const row = db._watchlist()[0];
    expect(row.status).toBe("expired");
    expect(row.sessions_remaining).toBe(0);
    expect(row.expired_at).toBeTruthy();
  });

  it("purges an expired row older than WATCHLIST_PURGE_DAYS but keeps a fresh one", async () => {
    const db = makeD1();
    const now = new Date("2026-08-15T12:00:00Z");
    const oldExpired = new Date(now.getTime() - (WATCHLIST_PURGE_DAYS + 1) * 86400000).toISOString();
    const freshExpired = new Date(now.getTime() - 1 * 86400000).toISOString();
    db._seedWatchlist({ user_id: "owner", ticker: "OLD", status: "expired", expired_at: oldExpired });
    db._seedWatchlist({ user_id: "owner", ticker: "FRESH", status: "expired", expired_at: freshExpired });
    const res = await tickWatchlist(db, { date: "2026-08-15", now });
    expect(res.purged).toBe(1);
    const tickers = db._watchlist().map((r) => r.ticker);
    expect(tickers).toEqual(["FRESH"]);
  });

  it("leaves non-active rows untouched by the decrement", async () => {
    const db = makeD1();
    db._seedWatchlist({ user_id: "owner", ticker: "EXP", status: "expired", sessions_remaining: 0, expired_at: "2026-08-14T00:00:00Z" });
    const res = await tickWatchlist(db, { date: "2026-08-15", now: new Date("2026-08-15T12:00:00Z") });
    expect(res.decremented).toBe(0);
    expect(db._watchlist()[0].sessions_remaining).toBe(0);
  });

  it("defaults `date` to the ET date derived from `now` when omitted", async () => {
    const db = makeD1();
    db._seedWatchlist({ user_id: "owner", ticker: "AAPL", sessions_remaining: 10 });
    const res = await tickWatchlist(db, { now: new Date("2026-08-13T15:00:00Z") }); // 11am ET
    expect(res.ticked).toBe(true);
    expect(res.decremented).toBe(1);
  });
});

// ── heldTickers union (WS5 §8b P1) ─────────────────────────────────────────────────────────────
describe("heldTickers union with active watchlist", () => {
  it("includes a watchlist-only ticker (no position) alongside held-position tickers, DISTINCT+sorted", async () => {
    const db = makeD1();
    db._seedPosition({ ticker: "AAPL", state: "open", user_id: "owner" });
    db._seedPosition({ ticker: "TSLA", state: "watching", user_id: "owner" }); // not held
    db._seedWatchlist({ user_id: "owner", ticker: "NVDA" }); // watchlist-only, no position
    db._seedWatchlist({ user_id: "owner", ticker: "AAPL" }); // overlaps a held position; must not duplicate
    db._seedWatchlist({ user_id: "owner", ticker: "ZOOM", status: "expired", expired_at: "2026-08-01T00:00:00Z" }); // excluded
    const t = await heldTickers(db);
    expect(t).toEqual(["AAPL", "NVDA"]);
  });
});
