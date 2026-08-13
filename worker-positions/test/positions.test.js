import { describe, it, expect } from "vitest";
import { validateCreatePayload, buildPositionRow, STOP_BASES } from "../src/positions.js";

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
});
