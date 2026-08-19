import { describe, it, expect } from "vitest";
import { validateCreatePayload, buildPositionRow, STOP_BASES, listPositions } from "../src/positions.js";
import { etDateStr } from "../src/time.js";
import { ENGINE_CONFIG } from "../src/advance.js";
import { makeD1 } from "./helpers/d1.js";

const good = { ticker: "aapl", entry_price: 100, initial_stop: 95, qty: 10, stop_basis: "20ma" };

describe("validateCreatePayload", () => {
  it("accepts a valid payload and uppercases the ticker", () => {
    const r = validateCreatePayload(good);
    expect(r.ok).toBe(true);
    expect(r.value.ticker).toBe("AAPL");
    expect(r.value.meta.source).toBe("manual"); // default
    expect(r.value.meta.widen_enabled).toBe(true); // default
  });

  it("honors meta.source=picks and preserves group_id", () => {
    const r = validateCreatePayload({ ...good, meta: { source: "picks", group_id: "g1" } });
    expect(r.value.meta.source).toBe("picks");
    expect(r.value.meta.group_id).toBe("g1");
  });

  it("rejects a stop at or above entry (R must be > 0)", () => {
    expect(validateCreatePayload({ ...good, initial_stop: 100 }).ok).toBe(false);
    expect(validateCreatePayload({ ...good, initial_stop: 105 }).ok).toBe(false);
  });

  it("rejects non-positive numbers", () => {
    expect(validateCreatePayload({ ...good, entry_price: 0 }).ok).toBe(false);
    expect(validateCreatePayload({ ...good, qty: -1 }).ok).toBe(false);
    expect(validateCreatePayload({ ...good, initial_stop: 0 }).ok).toBe(false);
  });

  it("rejects a bad ticker", () => {
    expect(validateCreatePayload({ ...good, ticker: "" }).ok).toBe(false);
    expect(validateCreatePayload({ ...good, ticker: "TOOLONGTICKER" }).ok).toBe(false);
    expect(validateCreatePayload({ ...good, ticker: "1AB" }).ok).toBe(false); // must start with a letter
  });

  it("rejects a bad stop_basis but defaults to manual when omitted", () => {
    expect(validateCreatePayload({ ...good, stop_basis: "bogus" }).ok).toBe(false);
    const r = validateCreatePayload({ ticker: "AAPL", entry_price: 100, initial_stop: 95, qty: 10 });
    expect(r.ok).toBe(true);
    expect(r.value.stop_basis).toBe("manual");
    expect(STOP_BASES).toContain(r.value.stop_basis);
  });

  it("rejects non-object body/meta", () => {
    expect(validateCreatePayload(null).ok).toBe(false);
    expect(validateCreatePayload("x").ok).toBe(false);
    expect(validateCreatePayload({ ...good, meta: [1, 2] }).ok).toBe(false);
  });

  it("entry_date omitted defaults to null (falls back to today in buildPositionRow)", () => {
    const r = validateCreatePayload(good);
    expect(r.ok).toBe(true);
    expect(r.value.entry_date).toBe(null);
  });

  it("accepts a valid past entry_date", () => {
    const r = validateCreatePayload({ ...good, entry_date: "2026-08-01" });
    expect(r.ok).toBe(true);
    expect(r.value.entry_date).toBe("2026-08-01");
  });

  it("rejects a malformed entry_date", () => {
    // includes well-formed but impossible calendar dates (round-trip check)
    for (const bad of ["08/01/2026", "2026-8-1", "notadate", "2026-02-30", "2026-13-01", "2026-00-10"]) {
      const r = validateCreatePayload({ ...good, entry_date: bad });
      expect(r.ok).toBe(false);
      expect(r.error).toBe("entry_date must be YYYY-MM-DD");
    }
  });

  it("rejects a future entry_date", () => {
    // Compute "tomorrow" via the ET helper (not manual UTC math) so this isn't brittle around
    // the UTC/ET day boundary.
    const tomorrow = etDateStr(new Date(Date.now() + 2 * 24 * 60 * 60 * 1000));
    const r = validateCreatePayload({ ...good, entry_date: tomorrow });
    expect(r.ok).toBe(false);
    expect(r.error).toBe("entry_date cannot be in the future");
  });
});

describe("buildPositionRow", () => {
  it("initializes engine state per § 4 invariants", () => {
    const v = validateCreatePayload(good).value;
    const row = buildPositionRow(v, { trade_id: "t1", user_id: "owner", now: new Date("2026-08-13T18:00:00Z") });
    expect(row.state).toBe("open");
    expect(row.current_stop).toBe(95);
    expect(row.profit_floor).toBe(95); // current_stop >= profit_floor holds at creation
    expect(row.remaining_qty).toBe(10);
    expect(row.initial_qty).toBe(10);
    expect(row.trail_basis).toBe("20ma");
    expect(row.caution_flag).toBe(0);
    expect(row.highest_trim_atr).toBe(0);
    expect(row.confirmation_status).toBe("unconfirmed");
    expect(row.entry_date).toBe("2026-08-13"); // ET date of the instant
    expect(JSON.parse(row.meta).source).toBe("manual");
  });

  it("entry_date omitted -> row uses today's ET date (unchanged path)", () => {
    const v = validateCreatePayload(good).value;
    const row = buildPositionRow(v, { trade_id: "t1", user_id: "owner", now: new Date("2026-08-13T18:00:00Z") });
    expect(row.entry_date).toBe("2026-08-13");
  });

  it("entry_date supplied (backdate) -> row uses it verbatim; opened_at stays real-now", () => {
    const v = validateCreatePayload({ ...good, entry_date: "2026-08-01" }).value;
    const row = buildPositionRow(v, { trade_id: "t1", user_id: "owner", now: new Date("2026-08-13T18:00:00Z") });
    expect(row.entry_date).toBe("2026-08-01");
    expect(row.opened_at).toBe("2026-08-13T18:00:00.000Z"); // real creation time, NOT backdated
    expect(row.opened_at).not.toBe(row.entry_date);
  });
});

// ── listPositions — session-calendar fields + closed_within_sessions (this PR) ─────────────────
// The calendar is the global union of ticker_quotes.trade_date (distinctTradeDates, sweep.js), so
// any ticker's seeded bars advance it — tests below seed onto a shared "SPY"-style ticker for
// clarity, matching the "union across all held tickers" doc comment on distinctTradeDates.
describe("listPositions — session-calendar fields", () => {
  it("computes sessions_in_closing for a closing position via the seeded calendar; null otherwise", async () => {
    const db = makeD1();
    // Calendar: 02-10 (signal date, also the max date so far) plus two LATER sessions.
    db._seedQuote({ ticker: "AAPL", trade_date: "2026-02-10" });
    db._seedPosition({ trade_id: "t-signal-is-max", ticker: "VRT", state: "closing", exit_signal_date: "2026-02-10" });
    db._seedPosition({ trade_id: "t-open", ticker: "AAPL", state: "open" });

    let rows = await listPositions(db, "owner", null);
    const closingAtMax = rows.find((p) => p.trade_id === "t-signal-is-max");
    const openRow = rows.find((p) => p.trade_id === "t-open");
    expect(closingAtMax.sessions_in_closing).toBe(0); // signal date IS the max calendar date
    expect(openRow.sessions_in_closing).toBeNull(); // non-closing state

    // Add two later sessions -> sessions_in_closing should now read 2.
    db._seedQuote({ ticker: "AAPL", trade_date: "2026-02-11" });
    db._seedQuote({ ticker: "AAPL", trade_date: "2026-02-12" });
    rows = await listPositions(db, "owner", null);
    expect(rows.find((p) => p.trade_id === "t-signal-is-max").sessions_in_closing).toBe(2);
  });

  it("computes sessions_since_close off closed_at's ET date; null for non-closed; strictly-after (just-closed -> 0)", async () => {
    const db = makeD1();
    db._seedQuote({ ticker: "AAPL", trade_date: "2026-02-10" });
    // closed_at is ISO-UTC late in the day; its ET date is still 2026-02-10 (before 5pm ET rollover).
    db._seedPosition({ trade_id: "t-just-closed", ticker: "VRT", state: "closed", closed_at: "2026-02-10T18:00:00Z" });
    db._seedPosition({ trade_id: "t-open", ticker: "AAPL", state: "open" });

    let rows = await listPositions(db, "owner", null);
    expect(rows.find((p) => p.trade_id === "t-just-closed").sessions_since_close).toBe(0); // strictly-after: 0 on close day
    expect(rows.find((p) => p.trade_id === "t-open").sessions_since_close).toBeNull();

    db._seedQuote({ ticker: "AAPL", trade_date: "2026-02-11" });
    db._seedQuote({ ticker: "AAPL", trade_date: "2026-02-12" });
    rows = await listPositions(db, "owner", null);
    expect(rows.find((p) => p.trade_id === "t-just-closed").sessions_since_close).toBe(2);
  });

  it("sessions_since_close is null when closed_at is null even for a closed position", async () => {
    const db = makeD1();
    db._seedQuote({ ticker: "AAPL", trade_date: "2026-02-10" });
    db._seedPosition({ trade_id: "t-no-closed-at", ticker: "VRT", state: "closed", closed_at: null });
    const rows = await listPositions(db, "owner", null);
    expect(rows.find((p) => p.trade_id === "t-no-closed-at").sessions_since_close).toBeNull();
  });

  it("auto_confirm_sessions equals ENGINE_CONFIG.EXIT_AUTOCONFIRM_SESSIONS on every row regardless of state", async () => {
    const db = makeD1();
    db._seedQuote({ ticker: "AAPL", trade_date: "2026-02-10" });
    db._seedPosition({ trade_id: "t1", ticker: "AAPL", state: "open" });
    db._seedPosition({ trade_id: "t2", ticker: "AAPL", state: "closing", exit_signal_date: "2026-02-10" });
    db._seedPosition({ trade_id: "t3", ticker: "AAPL", state: "closed", closed_at: "2026-02-10T18:00:00Z" });
    const rows = await listPositions(db, "owner", null);
    expect(rows).toHaveLength(3);
    for (const p of rows) expect(p.auto_confirm_sessions).toBe(ENGINE_CONFIG.EXIT_AUTOCONFIRM_SESSIONS);
  });

  it("auto_confirm_sessions honors a per-position meta.config.EXIT_AUTOCONFIRM_SESSIONS override", async () => {
    const db = makeD1();
    db._seedQuote({ ticker: "AAPL", trade_date: "2026-02-10" });
    db._seedPosition({ trade_id: "t-override", ticker: "AAPL", state: "open", meta: JSON.stringify({ config: { EXIT_AUTOCONFIRM_SESSIONS: 2 } }) });
    db._seedPosition({ trade_id: "t-default", ticker: "AAPL", state: "open" });
    const rows = await listPositions(db, "owner", null);
    expect(rows.find((p) => p.trade_id === "t-override").auto_confirm_sessions).toBe(2);
    expect(rows.find((p) => p.trade_id === "t-default").auto_confirm_sessions).toBe(ENGINE_CONFIG.EXIT_AUTOCONFIRM_SESSIONS);
  });

  it("skips the calendar load entirely on an empty result (no crash on zero positions)", async () => {
    const db = makeD1();
    const rows = await listPositions(db, "owner", null);
    expect(rows).toEqual([]);
  });

  it("existing 3-arg callers (no opts) still work unchanged", async () => {
    const db = makeD1();
    db._seedQuote({ ticker: "AAPL", trade_date: "2026-02-10" });
    db._seedPosition({ trade_id: "t1", ticker: "AAPL", state: "open" });
    const rows = await listPositions(db, "owner", "open"); // no 4th arg at all
    expect(rows).toHaveLength(1);
    expect(rows[0].auto_confirm_sessions).toBe(ENGINE_CONFIG.EXIT_AUTOCONFIRM_SESSIONS);
  });
});

describe("listPositions — closed_within_sessions bound", () => {
  it("drops a closed position beyond the bound, keeps one within it, never touches non-closed states", async () => {
    const db = makeD1();
    // Calendar spans 02-01 .. 02-05, so a position closed on 02-01 has sessions_since_close = 4
    // (02-02..02-05) and one closed on 02-04 has sessions_since_close = 1 (02-05).
    for (const d of ["2026-02-01", "2026-02-02", "2026-02-03", "2026-02-04", "2026-02-05"]) {
      db._seedQuote({ ticker: "AAPL", trade_date: d });
    }
    db._seedPosition({ trade_id: "t-old", ticker: "VRT", state: "closed", closed_at: "2026-02-01T18:00:00Z" });
    db._seedPosition({ trade_id: "t-recent", ticker: "NVDA", state: "closed", closed_at: "2026-02-04T18:00:00Z" });
    db._seedPosition({ trade_id: "t-open", ticker: "AAPL", state: "open" });

    const rows = await listPositions(db, "owner", null, { closedWithinSessions: 2 });
    const ids = rows.map((p) => p.trade_id).sort();
    expect(ids).toEqual(["t-open", "t-recent"]); // t-old (4 sessions) dropped, t-open (non-closed) kept

    const unfiltered = await listPositions(db, "owner", null); // absent opts = no filtering
    expect(unfiltered).toHaveLength(3);
  });
});
