import { describe, it, expect } from "vitest";
import {
  advance,
  confirmExit,
  stillHolding,
  autoConfirm,
  correctExit,
  reopen,
  effectiveConfig,
  rMultiple,
  atrExt50,
  severeBreakdown,
  recoverMaLevel,
  normalizeBar,
  parseEarningsToDays,
  ENGINE_CONFIG,
} from "../src/advance.js";

// ── Fixtures ──────────────────────────────────────────────────────────────────────────
// Base position: entry 100, initial stop 90 → R = 10. Fresh (open, no advance yet).
function pos(overrides = {}) {
  return {
    trade_id: "t1", user_id: "u1", ticker: "TEST", state: "open",
    entry_date: "2026-08-01", entry_price: 100, initial_stop: 90, stop_basis: "manual",
    initial_qty: 100, expected_exit_price: null, exit_signal_date: null, exit_reason: null,
    profit_floor: 90, current_stop: 90, trail_basis: "20ma", remaining_qty: 100,
    caution_flag: 0, highest_trim_atr: 0, days_to_earnings: null,
    opened_at: "2026-08-01T20:00:00Z", closed_at: null, exit_price: null,
    confirmation_status: "unconfirmed", last_advanced_date: null,
    meta: { source: "manual", widen_enabled: true },
    ...overrides,
  };
}
// A benign, mid-trade bar: price above 20/50MA, no exit, not extended. sma* are LEVELS.
function bar(overrides = {}) {
  return {
    trade_date: "2026-08-05", close: 105, high: 106, low: 104, open: 104.5, prev_close: 104,
    sma20: 100, sma50: 95, sma200: 80, atr: 2, days_to_earnings: null, ...overrides,
  };
}
const types = (r) => r.events.map((e) => e.event_type);

// ── Pure helpers ──────────────────────────────────────────────────────────
describe("pure helpers", () => {
  it("rMultiple = (price − entry)/R; NaN when R ≤ 0", () => {
    expect(rMultiple(pos(), 110)).toBeCloseTo(1.0);
    expect(rMultiple(pos(), 90)).toBeCloseTo(-1.0);
    expect(Number.isNaN(rMultiple(pos({ initial_stop: 100 }), 110))).toBe(true); // R=0
  });
  it("atrExt50 = (close − sma50)/atr", () => {
    expect(atrExt50(bar({ close: 120, sma50: 95, atr: 3 }))).toBeCloseTo(25 / 3);
    expect(Number.isNaN(atrExt50(bar({ atr: 0 })))).toBe(true);
  });
  it("severeBreakdown fires at ≥ SEVERE_BREAKDOWN_ATR one-day drop", () => {
    expect(severeBreakdown(bar({ prev_close: 110, close: 100, atr: 2 }), ENGINE_CONFIG)).toBe(true); // 5 ATR
    expect(severeBreakdown(bar({ prev_close: 104, close: 100, atr: 2 }), ENGINE_CONFIG)).toBe(false); // 2 ATR
  });
  it("recoverMaLevel inverts Finviz %-distance-from-MA", () => {
    expect(recoverMaLevel(105, 5)).toBeCloseTo(100); // 5% above → level 100
    expect(recoverMaLevel(105, -5)).toBeCloseTo(110.526, 2);
    expect(recoverMaLevel(105, null)).toBe(null);
  });
  it("normalizeBar recovers SMA levels from raw %-distance columns", () => {
    const b = normalizeBar({
      trade_date: "2026-08-05", close: 105, high: 106, low: 104, open: 104, prev_close: 104,
      atr: 2, raw: JSON.stringify({ SMA20: "5%", SMA50: "10.53%", SMA200: "-4.76%" }),
    });
    expect(b.sma20).toBeCloseTo(100, 4);
    expect(b.sma50).toBeCloseTo(95.0, 1);
    expect(b.sma200).toBeCloseTo(110.25, 1);
    expect(b.close).toBe(105);
  });
});

// ── effectiveConfig (§14) ────────────────────────────────────────────────────
describe("effectiveConfig", () => {
  it("no overrides → equals the globals", () => {
    expect(effectiveConfig(pos())).toEqual(ENGINE_CONFIG);
  });
  it("meta.config overrides layer on top, per-position only", () => {
    const cfg = effectiveConfig(pos({ meta: { config: { BREAKEVEN_R: 0.5 } } }));
    expect(cfg.BREAKEVEN_R).toBe(0.5);
    expect(cfg.TRIM_START_ATR).toBe(ENGINE_CONFIG.TRIM_START_ATR); // untouched
    expect(effectiveConfig(pos()).BREAKEVEN_R).toBe(1.0); // a sibling is unaffected
  });
});

// ── Exit checks (ordered; each SIGNALS → Closing, never Closed) ────────────────────────
describe("advance — exit signals land in Closing (never Closed)", () => {
  it("(a) stop hit → Closing at the stop level", () => {
    const r = advance(pos(), bar({ low: 89, open: 95 }));
    expect(r.position.state).toBe("closing");
    expect(r.position.exit_reason).toBe("stop_hit");
    expect(r.position.expected_exit_price).toBe(90);
    expect(r.position.exit_price).toBe(null); // never set on signal
    expect(r.position.exit_signal_date).toBe("2026-08-05");
    expect(types(r)).toEqual(["exit_signal"]);
  });
  it("(a) gap-down: open below stop → fill at the open, reported honestly", () => {
    const r = advance(pos(), bar({ open: 85, low: 84 }));
    expect(r.position.exit_reason).toBe("gap_down_below_stop");
    expect(r.position.expected_exit_price).toBe(85); // the worse-than-planned open, not 90
  });
  it("(b) close below 50MA → close_below_50ma (slow bleed)", () => {
    const r = advance(pos(), bar({ close: 94, sma50: 95, sma20: 96, low: 93 }));
    expect(r.position.exit_reason).toBe("close_below_50ma");
    expect(r.position.expected_exit_price).toBe(94);
  });
  it("(b) one-day crash → severe_breakdown, distinct from the 50MA bleed", () => {
    const r = advance(pos(), bar({ prev_close: 110, close: 100, atr: 2, sma50: 95, low: 99 }));
    expect(r.position.exit_reason).toBe("severe_breakdown");
  });
  it("(c) second consecutive close below 20MA → two_close_below_20ma", () => {
    const r = advance(pos({ caution_flag: 1 }), bar({ close: 99, sma20: 100, sma50: 95, low: 95, prev_close: 100 }));
    expect(r.position.exit_reason).toBe("two_close_below_20ma");
  });
  it("(b) HARD_EXIT_BASIS='20ma' override → close_below_20ma on the FIRST close, not two_close_below_20ma", () => {
    const cfg = effectiveConfig(pos({ meta: { config: { HARD_EXIT_BASIS: "20ma" } } }));
    const r = advance(pos({ meta: { config: { HARD_EXIT_BASIS: "20ma" } } }), bar({ close: 99, sma20: 100, sma50: 95, low: 98, prev_close: 100 }), cfg);
    expect(r.position.exit_reason).toBe("close_below_20ma");
    expect(r.position.caution_flag).toBe(0); // the stateful two-close counter never ran — this branch returns first
  });
  it("exit-before-advance: no trim/stop_moved event on the bar that signals an exit", () => {
    // Stop hit AND extended enough to trim — the exit must return first, emitting only exit_signal.
    const r = advance(pos(), bar({ low: 89, close: 120, sma50: 95, atr: 3 }));
    expect(types(r)).toEqual(["exit_signal"]);
  });
});

// ── Two-close soft exit: caution counter, reset, and the deliberate 50MA-basis case ───────────
describe("advance — two-close-below-20MA state", () => {
  it("first close below 20MA → caution (no exit), still advances the stop", () => {
    const r = advance(pos(), bar({ close: 99, sma20: 100, sma50: 95, low: 98, prev_close: 100 }));
    expect(r.position.state).toBe("managing");
    expect(r.position.caution_flag).toBe(1);
    expect(types(r)).toContain("caution");
    expect(types(r)).not.toContain("exit_signal");
  });
  it("close back at/above 20MA resets the caution counter", () => {
    const r = advance(pos({ caution_flag: 1 }), bar({ close: 101, sma20: 100 }));
    expect(r.position.caution_flag).toBe(0);
  });
  it("two closes below 20MA while ABOVE the 50MA stop still exits (deliberate, §7)", () => {
    const p = pos({ caution_flag: 1, trail_basis: "50ma", current_stop: 95, profit_floor: 95 });
    const r = advance(p, bar({ close: 98, sma20: 100, sma50: 95, low: 97, prev_close: 98 }));
    expect(r.position.exit_reason).toBe("two_close_below_20ma");
  });
  it("TWO_CLOSE_EXIT=0 override exits on the FIRST close below 20MA (falsy-zero must not fall back to the default 2)", () => {
    const p = pos({ meta: { config: { TWO_CLOSE_EXIT: 0 } } });
    const cfg = effectiveConfig(p);
    expect(cfg.TWO_CLOSE_EXIT).toBe(0);
    const r = advance(p, bar({ close: 99, sma20: 100, sma50: 95, low: 98, prev_close: 100 }), cfg);
    expect(r.position.state).toBe("closing");
    expect(r.position.exit_reason).toBe("two_close_below_20ma");
  });
});

// ── Stop advancement: breakeven floor, widen, within-basis ratchet ──────────────────────
describe("advance — stop advancement", () => {
  it("profit_floor ratchets to entry at +1R (BREAKEVEN_R), keyed on the intraday HIGH by default", () => {
    // high (110) tags +1R even though close (109) alone would not — proves the DEFAULT
    // BREAKEVEN_TRIGGER='high' basis, not a close-based coincidence (#335).
    const r = advance(pos(), bar({ close: 109, high: 110, sma20: 101, sma50: 95, low: 108 }));
    expect(r.position.profit_floor).toBe(100); // = entry
    expect(r.position.current_stop).toBeGreaterThanOrEqual(100);
  });
  it("BREAKEVEN_TRIGGER='close' override does NOT ratchet on a high-only tag", () => {
    const p = pos({ meta: { config: { BREAKEVEN_TRIGGER: "close" } } });
    const cfg = effectiveConfig(p);
    const r = advance(p, bar({ close: 109, high: 110, sma20: 101, sma50: 95, low: 108 }), cfg);
    expect(r.position.profit_floor).toBe(90); // unchanged: close (109) is still < entry+1R (110)
  });
  it("NVT tag-and-fade: high tags +1R, close does not — DEFAULT cfg still ratchets the floor", () => {
    // entry 100, initial_stop 95 → R = 5 → +1R = 105. High spikes to 105.5, closes back at 104.
    const p = pos({ initial_stop: 95, profit_floor: 95, current_stop: 95 });
    const r = advance(p, bar({ close: 104, high: 105.5, low: 103, sma20: 101, sma50: 95 }));
    expect(r.position.profit_floor).toBe(100); // = entry, protected despite the close-based fade
  });
  it("NVT tag-and-fade with BREAKEVEN_TRIGGER='close' does NOT ratchet (knob round-trip)", () => {
    const p = pos({
      initial_stop: 95, profit_floor: 95, current_stop: 95,
      meta: { config: { BREAKEVEN_TRIGGER: "close" } },
    });
    const cfg = effectiveConfig(p);
    const r = advance(p, bar({ close: 104, high: 105.5, low: 103, sma20: 101, sma50: 95 }), cfg);
    expect(r.position.profit_floor).toBe(95); // stays at initial — close (104) never reaches +1R (105)
  });
  it("20MA→50MA widen once 50MA > entry (may lower the stop, never below the floor)", () => {
    const p = pos({ profit_floor: 100, current_stop: 100 });
    const r = advance(p, bar({ close: 112, sma20: 108, sma50: 105, low: 110 }));
    expect(r.position.trail_basis).toBe("50ma");
    expect(r.position.current_stop).toBe(105); // max(floor 100, sma50 105), NOT the 108 the 20MA would give
    expect(types(r)).toContain("stop_moved");
  });
  it("meta.widen_enabled=false keeps the 20MA basis", () => {
    const p = pos({ profit_floor: 100, current_stop: 100, meta: { widen_enabled: false } });
    const r = advance(p, bar({ close: 112, sma20: 108, sma50: 105, low: 110 }));
    expect(r.position.trail_basis).toBe("20ma");
    expect(r.position.current_stop).toBe(108);
  });
  it("within a basis the stop ratchets UP only (never drops to a lower MA)", () => {
    const p = pos({ profit_floor: 100, current_stop: 100, trail_basis: "20ma" });
    const r = advance(p, bar({ close: 101, sma20: 98, sma50: 95, low: 100.5, prev_close: 101 }));
    expect(r.position.current_stop).toBe(100); // held, not lowered to 98
    expect(types(r)).not.toContain("stop_moved");
  });
});

// ── Scale-out trims (ATR extension from 50MA) ────────────────────────────────
describe("advance — trims", () => {
  it("trims 10% of remaining at the first whole ATR level (7)", () => {
    const r = advance(pos(), bar({ close: 116, sma50: 95, atr: 3, sma20: 100, low: 114 })); // ext = 7.0
    const trims = r.events.filter((e) => e.event_type === "partial_exit");
    expect(trims).toHaveLength(1);
    expect(trims[0].payload.at_atr).toBe(7);
    expect(trims[0].payload.qty).toBeCloseTo(10);
    expect(r.position.remaining_qty).toBeCloseTo(90);
    expect(r.position.highest_trim_atr).toBe(7);
  });
  it("catch-up: crossing 7 and 8 in one day trims once per level, compounding on remainder", () => {
    const r = advance(pos(), bar({ close: 120, sma50: 95, atr: 3, sma20: 100, low: 118 })); // ext ≈ 8.33
    const trims = r.events.filter((e) => e.event_type === "partial_exit");
    expect(trims.map((t) => t.payload.at_atr)).toEqual([7, 8]);
    expect(r.position.highest_trim_atr).toBe(8);
    expect(r.position.remaining_qty).toBeCloseTo(81); // 100 → 90 → 81
  });
  it("ledger guard: a later day at the same extension does not re-trim", () => {
    const p = pos({ highest_trim_atr: 7, remaining_qty: 90, last_advanced_date: "2026-08-05" });
    const r = advance(p, bar({ trade_date: "2026-08-06", close: 116.5, sma50: 95, atr: 3, sma20: 100, low: 114 })); // ext ≈ 7.17
    expect(r.events.filter((e) => e.event_type === "partial_exit")).toHaveLength(0);
    expect(r.position.remaining_qty).toBe(90);
  });
});

// ── Earnings guardrail: flag only ──────────────────────────────────────────
describe("advance — earnings guardrail", () => {
  it("flags (never exits) when days_to_earnings ≤ warn threshold; refreshes from the bar", () => {
    const r = advance(pos(), bar({ days_to_earnings: 3 }));
    expect(r.position.state).toBe("managing"); // not closed
    expect(r.position.days_to_earnings).toBe(3);
    const note = r.events.find((e) => e.event_type === "note" && e.payload.earnings_warning);
    expect(note).toBeTruthy();
  });
  it("no flag when earnings are far out", () => {
    const r = advance(pos(), bar({ days_to_earnings: 40 }));
    expect(r.events.find((e) => e.payload && e.payload.earnings_warning)).toBeFalsy();
  });
  it("no flag for a PAST earnings date (negative days_to_earnings) — regression for #335", () => {
    const r = advance(pos(), bar({ days_to_earnings: -5 }));
    expect(r.events.find((e) => e.event_type === "note" && e.payload.earnings_warning)).toBeFalsy();
  });
  it("boundary: days_to_earnings = 0 (earnings today) still warns", () => {
    const r = advance(pos(), bar({ days_to_earnings: 0 }));
    const note = r.events.find((e) => e.event_type === "note" && e.payload.earnings_warning);
    expect(note).toBeTruthy();
    expect(note.payload.days_to_earnings).toBe(0);
  });
});

// ── Lifecycle / idempotency / stale ──────────────────────────────────────────
describe("advance — lifecycle and guards", () => {
  it("Open → Managing on the first surviving advance", () => {
    const r = advance(pos(), bar());
    expect(r.position.state).toBe("managing");
    expect(r.position.last_advanced_date).toBe("2026-08-05");
  });
  it("Closed / Closing are no-ops (never re-advanced)", () => {
    expect(advance(pos({ state: "closed" }), bar()).events).toEqual([]);
    const c = advance(pos({ state: "closing" }), bar({ low: 1 }));
    expect(c.position.state).toBe("closing");
    expect(c.events).toEqual([]);
  });
  it("same-date re-run is a no-op (idempotency guard on last_advanced_date)", () => {
    const p = pos({ state: "managing", last_advanced_date: "2026-08-05", caution_flag: 1 });
    const r = advance(p, bar({ close: 99, sma20: 100 })); // would otherwise 2nd-close-exit
    expect(r.events).toEqual([]);
    expect(r.position).toBe(p);
  });
  it("stale/missing bar: flag + note, does not advance or stamp the date", () => {
    const r = advance(pos({ state: "managing" }), null);
    expect(r.stale).toBe(true);
    expect(types(r)).toEqual(["note"]);
    expect(r.position.last_advanced_date).toBe(null);
  });
});

// ── User-driven transitions ──────────────────────────────────────────────────
describe("confirmExit / stillHolding / autoConfirm / correctExit / reopen", () => {
  const closing = () =>
    pos({ state: "closing", expected_exit_price: 90, exit_signal_date: "2026-08-05", exit_reason: "stop_hit", caution_flag: 1 });

  it("confirmExit writes the USER's fill (≠ modeled) → Closed, confirmed", () => {
    const r = confirmExit(closing(), { exit_price: 88, now_iso: "2026-08-06T20:00:00Z" });
    expect(r.position.state).toBe("closed");
    expect(r.position.exit_price).toBe(88); // the actual fill, not the modeled 90
    expect(r.position.confirmation_status).toBe("confirmed");
    const ev = r.events[0];
    expect(ev.event_type).toBe("closed");
    expect(ev.payload.r_multiple).toBeCloseTo((88 - 100) / 10);
  });
  it("confirmExit with no price falls back to expected_exit_price", () => {
    expect(confirmExit(closing(), {}).position.exit_price).toBe(90);
  });
  it("stillHolding → Managing, clears expected fields, re-arms caution", () => {
    const r = stillHolding(closing());
    expect(r.position.state).toBe("managing");
    expect(r.position.expected_exit_price).toBe(null);
    expect(r.position.exit_reason).toBe(null);
    expect(r.position.caution_flag).toBe(0); // re-armed (CAUTION_REARM_ON_HOLD default)
  });
  it("stillHolding keeps caution when CAUTION_REARM_ON_HOLD=false", () => {
    const r = stillHolding(closing(), { ...ENGINE_CONFIG, CAUTION_REARM_ON_HOLD: false });
    expect(r.position.caution_flag).toBe(1);
  });
  it("autoConfirm closes at the SIGNAL-time price with status 'auto' only past the window", () => {
    expect(autoConfirm(closing(), ENGINE_CONFIG, { sessionsInClosing: 4 })).toBe(null);
    const r = autoConfirm(closing(), ENGINE_CONFIG, { sessionsInClosing: 5, now_iso: "x" });
    expect(r.position.state).toBe("closed");
    expect(r.position.exit_price).toBe(90); // frozen expected, not re-derived
    expect(r.position.confirmation_status).toBe("auto");
  });
  it("autoConfirm only applies to Closing positions", () => {
    expect(autoConfirm(pos({ state: "managing" }), ENGINE_CONFIG, { sessionsInClosing: 9 })).toBe(null);
  });
  it("correctExit is append-only: emits exit_corrected, recomputes R, updates the spine", () => {
    const closed = pos({ state: "closed", exit_price: 88, exit_reason: "stop_hit", confirmation_status: "auto" });
    const r = correctExit(closed, { exit_price: 90 });
    expect(r.position.exit_price).toBe(90);
    expect(r.events[0].event_type).toBe("exit_corrected");
    expect(r.events[0].payload.to).toBe(90);
    expect(r.events[0].payload.r_multiple).toBeCloseTo((90 - 100) / 10);
  });
  it("reopen returns Closed → Managing and emits reopened", () => {
    const closed = pos({ state: "closed", exit_price: 88, exit_reason: "stop_hit" });
    const r = reopen(closed);
    expect(r.position.state).toBe("managing");
    expect(r.position.exit_price).toBe(null);
    expect(r.position.exit_reason).toBe(null);
    expect(r.events[0].event_type).toBe("reopened");
  });
  it("reopen resets caution_flag so two-close-below-20MA needs two fresh closes", () => {
    const closed = pos({ state: "closed", exit_price: 88, exit_reason: "two_close_below_20ma", caution_flag: 2 });
    const r = reopen(closed);
    expect(r.position.caution_flag).toBe(0);
  });
});

// ── Property tests over random bar sequences (§9 invariants) ──────────────────────────
describe("advance — invariants over random bar sequences", () => {
  // Small deterministic LCG so the sequence is reproducible without a dependency.
  function makeRng(seed) {
    let s = seed >>> 0;
    return () => {
      s = (s * 1664525 + 1013904223) >>> 0;
      return s / 0xffffffff;
    };
  }
  it("profit_floor non-decreasing; current_stop ≥ profit_floor; remaining_qty ↓ and > 0", () => {
    for (let seed = 1; seed <= 40; seed++) {
      const rng = makeRng(seed);
      let p = pos();
      let price = 100;
      let prevFloor = p.profit_floor;
      let prevQty = p.remaining_qty;
      for (let day = 0; day < 60; day++) {
        price = Math.max(5, price * (1 + (rng() - 0.45) * 0.06)); // drifts up slightly, random walk
        const atr = 2 + rng() * 2;
        const b = {
          trade_date: `2026-09-${String(day + 1).padStart(2, "0")}`,
          close: price, high: price * 1.01, low: price * 0.98, open: price, prev_close: price / (1 + (rng() - 0.5) * 0.04),
          sma20: price * (1 - (rng() - 0.5) * 0.05), sma50: price * (1 - rng() * 0.1),
          sma200: price * 0.8, atr, days_to_earnings: null,
        };
        const r = advance(p, b, ENGINE_CONFIG);
        p = r.position;
        if (p.state !== "managing" && p.state !== "open") break; // exited → stop checking further bars
        expect(p.profit_floor).toBeGreaterThanOrEqual(prevFloor - 1e-9);
        expect(p.current_stop).toBeGreaterThanOrEqual(p.profit_floor - 1e-9);
        expect(p.remaining_qty).toBeGreaterThan(0);
        expect(p.remaining_qty).toBeLessThanOrEqual(prevQty + 1e-9);
        prevFloor = p.profit_floor;
        prevQty = p.remaining_qty;
      }
    }
  });
});

// ── Earnings parsing / wiring ────────────────────────────────────────────
describe("parseEarningsToDays / normalizeBar earnings", () => {
  it("counts calendar days ahead of asOf", () => {
    expect(parseEarningsToDays("Aug 20", "2026-08-13")).toBe(7);
  });
  it("/a and /b suffixes are ignored for the count", () => {
    expect(parseEarningsToDays("Aug 20/a", "2026-08-13")).toBe(7);
    expect(parseEarningsToDays("Aug 20/b", "2026-08-13")).toBe(7);
  });
  it("rolls forward a year when the date is >180 days in the past", () => {
    // asOf late in the year, earnings early-month → >180 days back this year, so next year.
    const days = parseEarningsToDays("Jan 05", "2026-11-01");
    expect(days).toBeGreaterThan(0);
    expect(days).toBe(65); // 2026-11-01 → 2027-01-05
  });
  it("returns null for '-', empty, null, and garbage", () => {
    expect(parseEarningsToDays("-", "2026-08-13")).toBe(null);
    expect(parseEarningsToDays("", "2026-08-13")).toBe(null);
    expect(parseEarningsToDays(null, "2026-08-13")).toBe(null);
    expect(parseEarningsToDays("Zzz 99", "2026-08-13")).toBe(null);
    expect(parseEarningsToDays("foo", "2026-08-13")).toBe(null);
  });
  it("normalizeBar derives days_to_earnings from raw.Earnings when the typed column is absent", () => {
    const b = normalizeBar({
      trade_date: "2026-08-13", close: 105, raw: JSON.stringify({ Earnings: "Aug 20" }),
    });
    expect(b.days_to_earnings).toBe(7);
  });
  it("normalizeBar prefers the typed days_to_earnings column when present", () => {
    const b = normalizeBar({
      trade_date: "2026-08-13", close: 105, days_to_earnings: 3,
      raw: JSON.stringify({ Earnings: "Aug 20" }),
    });
    expect(b.days_to_earnings).toBe(3);
  });
  it("normalizeBar stays pure when trade_date is missing: days_to_earnings is null, never wall-clock-derived", () => {
    const b = normalizeBar({
      trade_date: null, close: 105, raw: JSON.stringify({ Earnings: "Aug 20" }),
    });
    expect(b.days_to_earnings).toBe(null);
  });
});
