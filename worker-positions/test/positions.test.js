import { describe, it, expect } from "vitest";
import { validateCreatePayload, buildPositionRow, STOP_BASES } from "../src/positions.js";
import { etDateStr } from "../src/time.js";

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
