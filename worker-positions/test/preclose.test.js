import { describe, it, expect, beforeEach } from "vitest";
import { makeD1 } from "./helpers/d1.js";
import { handleRequest } from "../src/index.js";
import { mintToken } from "../src/auth.js";
import { computePreCloseAdvisory, readPreCloseAdvisory, PRECLOSE_SEVERITY } from "../src/preclose.js";
import { etDateStr } from "../src/time.js";

// ── Fixture helpers (mirrors test/sweep.test.js's quoteRow/pctForLevel conventions) ─────────────

// Inverse of advance.js's recoverMaLevel(close, pct) = close / (1 + pct/100).
function pctForLevel(close, level) {
  return `${((close / level - 1) * 100).toFixed(6)}%`;
}

// A single provisional bar in the SAME shape validateIngestBatch() produces per row — i.e. NO
// trade_date on the row itself (trade_date is a batch-level field; see src/preclose.js header for
// why computePreCloseAdvisory stamps it back on before calling normalizeBar()).
function quote({ ticker = "AAPL", close, sma20, sma50, low, high, open, prev_close, atr = 2 }) {
  const raw = { Ticker: ticker };
  if (sma20 != null && close != null) raw.SMA20 = pctForLevel(close, sma20);
  if (sma50 != null && close != null) raw.SMA50 = pctForLevel(close, sma50);
  return {
    ticker,
    prev_close: prev_close ?? close,
    open: open ?? close,
    high: high ?? close,
    low: low ?? close,
    close,
    atr,
    raw: JSON.stringify(raw),
  };
}

function seedPos(db, overrides = {}) {
  return db._seedPosition({
    ticker: "AAPL",
    user_id: "owner",
    state: "open",
    entry_date: "2026-08-01",
    entry_price: 100,
    initial_stop: 90,
    stop_basis: "manual",
    initial_qty: 100,
    profit_floor: 90,
    current_stop: 90,
    trail_basis: "20ma",
    remaining_qty: 100,
    caution_flag: 0,
    meta: "{}",
    ...overrides,
  });
}

describe("computePreCloseAdvisory", () => {
  let db;
  beforeEach(() => {
    db = makeD1();
  });

  it("1. act signal: a bar whose low is below the stop -> stop_hit, ref_level = current_stop", async () => {
    seedPos(db, { current_stop: 95 });
    const result = await computePreCloseAdvisory(db, {
      quotes: [quote({ close: 100, sma20: 90, sma50: 80, low: 94, open: 101 })],
      trade_date: "2026-08-20",
    });
    expect(result).toEqual({ trade_date: "2026-08-20", users: 1, checked: 1, flagged: 1 });

    const row = await readPreCloseAdvisory(db, "owner", "2026-08-20");
    expect(row.n_checked).toBe(1);
    expect(row.n_flagged).toBe(1);
    expect(row.items).toHaveLength(1);
    expect(row.items[0]).toMatchObject({
      ticker: "AAPL",
      category: "exit",
      severity: "act",
      signal: "stop_hit",
      ref_level: 95,
      price: 100,
    });
    expect(PRECLOSE_SEVERITY.stop_hit).toBe("act");
  });

  it("2. heads-up signal: close_below_50ma -> severity heads_up, correct ref_level (sma50)", async () => {
    // sma20 must stay ABOVE the close too, or the 20MA rule (checked after the 50MA rule but not
    // reached since 50MA returns first) would confuse the fixture's intent — keep both below close
    // so close_below_50ma (checked first) is the one that fires.
    seedPos(db, { current_stop: 70 }); // stop well below close/low so stop_hit doesn't pre-empt it
    const result = await computePreCloseAdvisory(db, {
      quotes: [quote({ close: 95, sma20: 100, sma50: 100, low: 94, open: 96 })],
      trade_date: "2026-08-20",
    });
    expect(result.flagged).toBe(1);
    const row = await readPreCloseAdvisory(db, "owner", "2026-08-20");
    expect(row.items[0].signal).toBe("close_below_50ma");
    expect(row.items[0].severity).toBe("heads_up");
    expect(row.items[0].ref_level).toBeCloseTo(100, 5);
  });

  it("3. all-clear: a bar that signals nothing still upserts a receipt row (n_checked>=1, n_flagged=0)", async () => {
    seedPos(db, { current_stop: 80 });
    const result = await computePreCloseAdvisory(db, {
      quotes: [quote({ close: 110, sma20: 95, sma50: 90, low: 108, open: 109 })],
      trade_date: "2026-08-20",
    });
    expect(result).toEqual({ trade_date: "2026-08-20", users: 1, checked: 1, flagged: 0 });
    const row = await readPreCloseAdvisory(db, "owner", "2026-08-20");
    expect(row.n_checked).toBeGreaterThanOrEqual(1);
    expect(row.n_flagged).toBe(0);
    expect(row.items).toEqual([]);
  });

  it("4. a `closing` position is not evaluated or reported", async () => {
    seedPos(db, { state: "closing", current_stop: 200 }); // would stop-hit at any price if evaluated
    const result = await computePreCloseAdvisory(db, {
      quotes: [quote({ close: 100, sma20: 90, sma50: 80, low: 99, open: 100 })],
      trade_date: "2026-08-20",
    });
    expect(result.users).toBe(0);
    expect(result.checked).toBe(0);
    const row = await readPreCloseAdvisory(db, "owner", "2026-08-20");
    expect(row).toBeNull();
  });

  it("5. DISJOINTNESS (critical): positions/ticker_quotes are untouched by the compute", async () => {
    seedPos(db, { current_stop: 95 });
    const positionsBefore = db._positions();
    const quotesBefore = db._quotes();
    expect(quotesBefore).toEqual([]); // nothing seeded into ticker_quotes at all

    await computePreCloseAdvisory(db, {
      quotes: [quote({ close: 100, sma20: 90, sma50: 80, low: 94, open: 101 })], // triggers stop_hit
      trade_date: "2026-08-20",
    });

    const positionsAfter = db._positions();
    const quotesAfter = db._quotes();
    expect(positionsAfter).toEqual(positionsBefore); // byte-identical: state, last_advanced_date, meta, etc.
    expect(positionsAfter[0].last_advanced_date).toBeNull();
    expect(positionsAfter[0].state).toBe("open");
    expect(quotesAfter).toEqual([]); // still zero rows in ticker_quotes — no bar was ever persisted
  });

  it("6. upsert/self-heal: a second run with different bars overwrites the first (last-write-wins)", async () => {
    seedPos(db, { current_stop: 80 });
    await computePreCloseAdvisory(db, {
      quotes: [quote({ close: 110, sma20: 95, sma50: 90, low: 108, open: 109 })], // all-clear
      trade_date: "2026-08-20",
    });
    let row = await readPreCloseAdvisory(db, "owner", "2026-08-20");
    expect(row.n_flagged).toBe(0);

    await computePreCloseAdvisory(db, {
      quotes: [quote({ close: 100, sma20: 90, sma50: 80, low: 79, open: 100 })], // stop_hit this time
      trade_date: "2026-08-20",
    });
    row = await readPreCloseAdvisory(db, "owner", "2026-08-20");
    expect(row.n_flagged).toBe(1);
    expect(row.items[0].signal).toBe("stop_hit");

    // Still exactly ONE row for (owner, 2026-08-20) — the upsert didn't create a duplicate.
    const raw = await db.prepare("SELECT COUNT(*) as n FROM preclose_advisory").first();
    expect(raw.n).toBe(1);
  });

  it("7. readPreCloseAdvisory: parsed shape; unknown user/date -> null", async () => {
    seedPos(db, { current_stop: 80 });
    await computePreCloseAdvisory(db, {
      quotes: [quote({ close: 110, sma20: 95, sma50: 90, low: 108, open: 109 })],
      trade_date: "2026-08-20",
    });
    const row = await readPreCloseAdvisory(db, "owner", "2026-08-20");
    expect(row).toMatchObject({ n_checked: 1, n_flagged: 0, items: [] });
    expect(typeof row.ran_at).toBe("string");

    expect(await readPreCloseAdvisory(db, "owner", "2099-01-01")).toBeNull();
    expect(await readPreCloseAdvisory(db, "someone-else", "2026-08-20")).toBeNull();
  });

  it("8. tenancy: the WHERE clause keys on user_id (single-user harness — see auth.js SINGLE_USER_ID)", async () => {
    // This worker is single-user at present (src/auth.js SINGLE_USER_ID = "owner"; makeD1()'s
    // _seedPosition also defaults user_id to "owner"), so seeding a genuinely second, independently
    // authenticated user isn't exercised elsewhere in this test suite either — flagged per the spec's
    // "comment + single-user test is acceptable" allowance. What IS asserted here: the read is scoped
    // by user_id, not just trade_date — a row for a different user_id does not leak into this read.
    seedPos(db, { current_stop: 95, user_id: "owner" });
    await computePreCloseAdvisory(db, {
      quotes: [quote({ close: 100, sma20: 90, sma50: 80, low: 94, open: 101 })],
      trade_date: "2026-08-20",
    });
    expect(await readPreCloseAdvisory(db, "owner", "2026-08-20")).not.toBeNull();
    expect(await readPreCloseAdvisory(db, "not-owner", "2026-08-20")).toBeNull();
  });
});

// ── Route-level auth-split tests (mirror the /advance and /ingest/quotes conventions) ────────────
describe("routes: POST /positions/preclose-advisory + GET /positions/preclose", () => {
  const SECRET = "test-secret-abc123-abc123-abc123";
  const PASSPHRASE = "correct horse";
  const INGEST_TOKEN = "ingest-token-super-secret-0123456789";
  let env;
  beforeEach(() => {
    env = {
      POSITIONS_SESSION_SECRET: SECRET,
      POSITIONS_AUTH_PASSPHRASE: PASSPHRASE,
      POSITIONS_INGEST_TOKEN: INGEST_TOKEN,
      ALLOWED_ORIGINS: "https://clarencelam2000.github.io",
      POSITIONS_DB: makeD1(),
    };
  });

  function req(path, { method = "GET", body, token } = {}) {
    const headers = {};
    if (token) headers.authorization = `Bearer ${token}`;
    if (body !== undefined) headers["content-type"] = "application/json";
    return new Request(`https://finviz-positions.workers.dev${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  }

  const batchBody = {
    trade_date: "2026-08-20",
    collected_at: "2026-08-20T19:40:00Z",
    quotes: [{ ticker: "AAPL", close: 100, high: 100, low: 99, open: 100, raw: { Ticker: "AAPL" } }],
  };

  it("service token can POST the advisory ingest and gets counts only", async () => {
    env.POSITIONS_DB._seedPosition({ ticker: "AAPL", state: "open", user_id: "owner", current_stop: 80 });
    const res = await handleRequest(req("/positions/preclose-advisory", { method: "POST", token: INGEST_TOKEN, body: batchBody }), env);
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toEqual({ trade_date: "2026-08-20", users: 1, checked: 1, flagged: 0 });
    expect(body.results).toBeUndefined();
  });

  it("service token cannot GET /positions/preclose", async () => {
    const res = await handleRequest(req("/positions/preclose", { token: INGEST_TOKEN }), env);
    expect(res.status).toBe(401);
  });

  it("owner bearer cannot POST the advisory ingest", async () => {
    const ownerToken = await mintToken(env, "owner");
    const res = await handleRequest(req("/positions/preclose-advisory", { method: "POST", token: ownerToken, body: batchBody }), env);
    expect(res.status).toBe(401);
  });

  it("owner bearer can GET /positions/preclose and gets a null-safe empty shape when nothing ran yet", async () => {
    const ownerToken = await mintToken(env, "owner");
    const res = await handleRequest(req("/positions/preclose", { token: ownerToken }), env);
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ran_at: null, n_checked: 0, n_flagged: 0, items: [] });
  });

  it("end-to-end: POST then GET returns the computed advisory for today's ET date", async () => {
    env.POSITIONS_DB._seedPosition({ ticker: "AAPL", state: "open", user_id: "owner", current_stop: 200 }); // guaranteed stop_hit
    // Use TODAY's ET date so the GET (which always reads today) finds the row the POST wrote.
    const today = etDateStr(new Date());
    const body = { ...batchBody, trade_date: today };
    const postRes = await handleRequest(req("/positions/preclose-advisory", { method: "POST", token: INGEST_TOKEN, body }), env);
    expect(postRes.status).toBe(200);

    const ownerToken = await mintToken(env, "owner");
    const getRes = await handleRequest(req("/positions/preclose", { token: ownerToken }), env);
    expect(getRes.status).toBe(200);
    const advisory = await getRes.json();
    expect(advisory.n_flagged).toBe(1);
    // batchBody's open (100) sits below the seeded current_stop (200), so this is the honest
    // gap-down variant of the stop-hit rule (advance.js signalExit), not the plain in-range one.
    expect(advisory.items[0].signal).toBe("gap_down_below_stop");
    expect(PRECLOSE_SEVERITY.gap_down_below_stop).toBe("act");
  });

  it("malformed batch 400s (reuses validateIngestBatch)", async () => {
    const res = await handleRequest(
      req("/positions/preclose-advisory", { method: "POST", token: INGEST_TOKEN, body: { trade_date: "bad", quotes: [] } }),
      env
    );
    expect(res.status).toBe(400);
  });
});
