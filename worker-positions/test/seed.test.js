// WS-POSITIONS-SEED (step 3) — tests for src/seed.js.
//
// Two things these tests exist to pin:
//   1. seedTickerBar uses INSERT OR IGNORE — it must NEVER overwrite a real Finviz bar or a prior
//      seed for the same (ticker, trade_date).
//   2. A seeded bar can never fold into a real position's advance: sweep.js's loadBarsAfter() reads
//      strictly `trade_date > floor`, so a position entered on/after the seed's date never sees it.
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { makeD1 } from "./helpers/d1.js";
import { mapFmpBar, seedTickerBar } from "../src/seed.js";
import { loadBarsAfter, barWindowStart } from "../src/sweep.js";

// A realistic FMP historical-price-eod/full payload: flat array, descending date order (verified
// live against the endpoint 2026-08-26). rows[0] is the newest completed session.
const FMP_ROWS = [
  { symbol: "AAPL", date: "2026-08-25", open: 310.9, high: 313.5, low: 308.2, close: 309.9, volume: 25666176, change: -1.04, changePercent: -0.3328, vwap: 310.56 },
  { symbol: "AAPL", date: "2026-08-24", open: 311.4, high: 313.3, low: 309.9, close: 310.34, volume: 34673600, change: -1.13, changePercent: -0.3628, vwap: 311.28 },
];

function fetchOk(rows) {
  return vi.fn(async () => ({ status: 200, ok: true, json: async () => rows }));
}

describe("mapFmpBar (pure)", () => {
  it("maps the newest row and takes prev_close from the second row", () => {
    const m = mapFmpBar(FMP_ROWS, "AAPL");
    expect(m).toEqual({
      ticker: "AAPL",
      trade_date: "2026-08-25",
      open: 310.9,
      high: 313.5,
      low: 308.2,
      close: 309.9,
      change_pct: -0.3328,
      volume: 25666176,
      prev_close: 310.34,
    });
  });

  it("single-row IPO edge → prev_close null", () => {
    const m = mapFmpBar([FMP_ROWS[0]], "AAPL");
    expect(m.trade_date).toBe("2026-08-25");
    expect(m.prev_close).toBeNull();
  });

  it("empty / non-array / missing bar → null", () => {
    expect(mapFmpBar([], "AAPL")).toBeNull();
    expect(mapFmpBar(null, "AAPL")).toBeNull();
    expect(mapFmpBar("nope", "AAPL")).toBeNull();
    expect(mapFmpBar([null], "AAPL")).toBeNull();
  });

  it("coerces non-finite / string-numeric fields", () => {
    const m = mapFmpBar([{ date: "2026-08-25", open: "12.5", high: undefined, low: null, close: "x", volume: "", changePercent: 1.2 }], "X");
    expect(m.open).toBe(12.5);   // numeric string coerced
    expect(m.high).toBeNull();   // undefined
    expect(m.low).toBeNull();    // null
    expect(m.close).toBeNull();  // NaN
    expect(m.volume).toBeNull(); // empty string
    expect(m.change_pct).toBe(1.2);
  });
});

describe("seedTickerBar", () => {
  let db;
  const env = { FMP_API_KEY: "test-key" };

  beforeEach(() => {
    db = makeD1();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("no FMP key → {seeded:false, no_api_key}, no fetch, no write", async () => {
    const spy = vi.spyOn(globalThis, "fetch");
    const r = await seedTickerBar(db, "AAPL", {});
    expect(r).toEqual({ seeded: false, reason: "no_api_key" });
    expect(spy).not.toHaveBeenCalled();
    expect(db._quotes()).toHaveLength(0);
  });

  it("happy path → inserts one fmp_seed bar", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(fetchOk(FMP_ROWS));
    const r = await seedTickerBar(db, "AAPL", env, { now: "2026-08-26T12:00:00Z" });
    expect(r).toEqual({ seeded: true, ticker: "AAPL", trade_date: "2026-08-25" });
    const rows = db._quotes();
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      ticker: "AAPL",
      trade_date: "2026-08-25",
      close: 309.9,
      prev_close: 310.34,
      source: "fmp_seed",
      collected_at: "2026-08-26T12:00:00Z",
    });
    // OHLC-only scope: atr/days_to_earnings left null, raw at its default.
    expect(rows[0].atr).toBeNull();
    expect(rows[0].raw).toBe("{}");
  });

  it("INSERT OR IGNORE never clobbers an existing real Finviz bar", async () => {
    // A real held-feed bar already exists for the same (ticker, trade_date).
    db._seedQuote({ ticker: "AAPL", trade_date: "2026-08-25", close: 999, atr: 4.2, source: "finviz", collected_at: "2026-08-25T21:30:00Z" });
    vi.spyOn(globalThis, "fetch").mockImplementation(fetchOk(FMP_ROWS));

    const r = await seedTickerBar(db, "AAPL", env);
    expect(r.seeded).toBe(true); // the call "succeeds" — a bar exists, which is the goal
    const rows = db._quotes();
    expect(rows).toHaveLength(1);
    // The Finviz bar is untouched: still its own values + source, NOT the seed's.
    expect(rows[0].close).toBe(999);
    expect(rows[0].atr).toBe(4.2);
    expect(rows[0].source).toBe("finviz");
  });

  it("network / status / json failures are swallowed as {seeded:false}", async () => {
    const cases = [
      [async () => { throw new Error("boom"); }, "fmp_timeout"],
      [async () => ({ status: 429, ok: false }), "rate_limited"],
      [async () => ({ status: 503, ok: false }), "fmp_unavailable"],
      [async () => ({ status: 200, ok: true, json: async () => { throw new Error("bad"); } }), "bad_json"],
      [async () => ({ status: 200, ok: true, json: async () => [] }), "no_data"],
    ];
    for (const [impl, reason] of cases) {
      vi.spyOn(globalThis, "fetch").mockImplementation(impl);
      const r = await seedTickerBar(db, "AAPL", env);
      expect(r).toEqual({ seeded: false, reason });
      expect(db._quotes()).toHaveLength(0);
      vi.restoreAllMocks();
    }
  });
});

describe("safety: a seed bar is excluded from a real position's advance window", () => {
  it("a position entered on the seed's date never sees the seed bar", async () => {
    const db = makeD1();
    vi.spyOn(globalThis, "fetch").mockImplementation(fetchOk(FMP_ROWS));
    await seedTickerBar(db, "AAPL", { FMP_API_KEY: "k" });
    vi.restoreAllMocks();

    // Position entered the same day the seed bar is dated. barWindowStart's floor includes
    // entry_date, and loadBarsAfter is strictly `> floor`, so the seed (trade_date == floor) is out.
    const pos = { entry_date: "2026-08-25", opened_at: "2026-08-25T14:00:00Z", last_advanced_date: null };
    const floor = barWindowStart(pos);
    const bars = await loadBarsAfter(db, "AAPL", floor, 100);
    expect(bars).toHaveLength(0);
  });
});
