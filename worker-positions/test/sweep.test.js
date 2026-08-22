import { describe, it, expect, beforeEach } from "vitest";
import { makeD1 } from "./helpers/d1.js";
import { handleRequest } from "../src/index.js";
import { mintToken } from "../src/auth.js";
import {
  sweep,
  barWindowStart,
  advanceThroughBars,
  loadAdvanceablePositions,
  loadBarsAfter,
  persistAdvance,
  SWEEP_CONFIG,
  sessionsSince,
  distinctTradeDates,
  loadClosingPositions,
} from "../src/sweep.js";
import { ackStop } from "../src/transitions.js";
import { subscribePush } from "../src/push.js";

// ── Fixture helpers ──────────────────────────────────────────────────────────────────────────

// Inverse of advance.js's recoverMaLevel(close, pct) = close / (1 + pct/100). Given the LEVEL we
// actually want an MA to sit at, back-compute the %-distance string Finviz would have reported —
// so fixtures read as "sma20 sits at 95" rather than an opaque "-4.7619%" nobody can sanity-check.
function pctForLevel(close, level) {
  return `${((close / level - 1) * 100).toFixed(6)}%`;
}

// Build a raw ticker_quotes row (the shape loadBarsAfter() hands to normalizeBar()). sma20/sma50
// are LEVELS in the test's terms; this helper converts them to the %-distance strings the real
// column stores, via pctForLevel above.
function quoteRow({ ticker = "AAPL", trade_date, close, sma20, sma50, low, high, open, prev_close, atr = 2, daysToEarnings = null }) {
  const raw = { Ticker: ticker };
  if (sma20 != null && close != null) raw.SMA20 = pctForLevel(close, sma20);
  if (sma50 != null && close != null) raw.SMA50 = pctForLevel(close, sma50);
  return {
    ticker,
    trade_date,
    prev_close: prev_close ?? close,
    open: open ?? close,
    high: high ?? close,
    low: low ?? close,
    close,
    change_pct: null,
    atr,
    volume: 1000000,
    days_to_earnings: daysToEarnings,
    raw: JSON.stringify(raw),
    collected_at: `${trade_date}T21:00:00Z`,
  };
}

// Add `n` calendar days to a 'YYYY-MM-DD' string (UTC, no trading-calendar awareness needed —
// sweep.js only ever compares trade_date strings lexicographically, never counts sessions).
function addDays(dateStr, n) {
  const dt = new Date(`${dateStr}T00:00:00Z`);
  dt.setUTCDate(dt.getUTCDate() + n);
  return dt.toISOString().slice(0, 10);
}

// A fresh "just entered" position row, mirroring buildPositionRow()'s initial-state convention
// (src/positions.js): entry 100, initial_stop 90 → R = 10. profit_floor == current_stop ==
// initial_stop, trail_basis 20ma, state 'open'.
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
    meta: "{}",
    ...overrides,
  });
}

let db;
beforeEach(() => {
  db = makeD1();
});

// ── barWindowStart (pure) ────────────────────────────────────────────────────────────────────
describe("barWindowStart", () => {
  it("is the lexicographic max of last_advanced_date and entry_date", () => {
    expect(barWindowStart({ entry_date: "2026-08-01", last_advanced_date: "2026-08-05" })).toBe("2026-08-05");
    expect(barWindowStart({ entry_date: "2026-08-05", last_advanced_date: "2026-08-01" })).toBe("2026-08-05");
    expect(barWindowStart({ entry_date: "2026-08-05", last_advanced_date: null })).toBe("2026-08-05");
  });
  it("returns null only when BOTH dates are absent", () => {
    expect(barWindowStart({ entry_date: null, last_advanced_date: null })).toBe(null);
  });
  it("is also floored by opened_at's ET trading date (§8a backdate guard)", () => {
    // Backdated entry_date, but the position was really created 9 days later — opened_at wins.
    expect(barWindowStart({
      entry_date: "2026-08-01",
      last_advanced_date: null,
      opened_at: "2026-08-10T15:00:00Z", // ET trading date 2026-08-10 (EDT, UTC-4)
    })).toBe("2026-08-10");
  });
  it("opened_at is a no-op for a non-backdated position (entry_date == opened_at's ET date)", () => {
    expect(barWindowStart({
      entry_date: "2026-08-10",
      last_advanced_date: null,
      opened_at: "2026-08-10T15:00:00Z",
    })).toBe("2026-08-10");
  });
  it("last_advanced_date can still exceed opened_at once the position has advanced for real", () => {
    expect(barWindowStart({
      entry_date: "2026-08-01",
      last_advanced_date: "2026-08-15",
      opened_at: "2026-08-10T15:00:00Z",
    })).toBe("2026-08-15");
  });
});

// ── 1. Happy path: managing position + 3 consecutive bars ──────────────────────────────────────
describe("sweep — happy path", () => {
  it("advances through all 3 bars; last_advanced_date lands on the last bar; events carry per-bar dates", async () => {
    seedPos(db, { state: "managing", last_advanced_date: null });
    db._seedQuote(quoteRow({ trade_date: "2026-08-02", close: 101, sma20: 95, sma50: 80, low: 99 }));
    db._seedQuote(quoteRow({ trade_date: "2026-08-03", close: 103, sma20: 97, sma50: 80, low: 101, prev_close: 101 }));
    db._seedQuote(quoteRow({ trade_date: "2026-08-04", close: 105, sma20: 99, sma50: 80, low: 103, prev_close: 103 }));

    const result = await sweep(db);
    expect(result.positions).toBe(1);
    expect(result.advanced).toBe(1);
    expect(result.unchanged).toBe(0);

    const [row] = db._positions();
    expect(row.last_advanced_date).toBe("2026-08-04");
    expect(row.state).toBe("managing");

    const events = db._events();
    // At least one stop_moved per bar (20MA ratchets each day) — every event's trade_date must be
    // one of the 3 bar dates, and all 3 dates must be represented (nothing skipped or misdated).
    const dates = new Set(events.map((e) => e.trade_date));
    expect(dates).toEqual(new Set(["2026-08-02", "2026-08-03", "2026-08-04"]));
  });
});

// ── 2. open -> managing on first advance ────────────────────────────────────────────────────────
describe("sweep — state transitions", () => {
  it("open -> managing on first advance", async () => {
    seedPos(db, { state: "open" });
    db._seedQuote(quoteRow({ trade_date: "2026-08-02", close: 101, sma20: 95, sma50: 80, low: 99 }));
    await sweep(db);
    expect(db._positions()[0].state).toBe("managing");
  });
});

// ── 3. Entry-day bar is NOT advanced ────────────────────────────────────────────────────────────
describe("sweep — entry-day exclusion (wiring-layer rule)", () => {
  it("a bar dated == entry_date is not advanced (barWindowStart is exclusive)", async () => {
    seedPos(db, { entry_date: "2026-08-01" });
    db._seedQuote(quoteRow({ trade_date: "2026-08-01", close: 50, sma20: 95, sma50: 80, low: 1 })); // would stop-hit if read
    const result = await sweep(db);
    expect(result.results[0].bars_advanced).toBe(0);
    const [row] = db._positions();
    expect(row.last_advanced_date).toBe(null);
    expect(row.state).toBe("open");
  });
});

// ── 4. Bars strictly before entry_date are ignored ──────────────────────────────────────────────
describe("sweep — pre-entry bars ignored", () => {
  it("a bar dated before entry_date is never loaded", async () => {
    seedPos(db, { entry_date: "2026-08-05" });
    db._seedQuote(quoteRow({ trade_date: "2026-08-01", close: 50, sma20: 95, sma50: 80, low: 1 }));
    const result = await sweep(db);
    expect(result.results[0].bars_advanced).toBe(0);
    expect(db._positions()[0].last_advanced_date).toBe(null);
  });
});

// ── 4b. Backdated entry_date must not replay pre-existing bars (opened_at floor, §8a guard) ─────
describe("sweep — backdated entry_date does not replay pre-existing bars", () => {
  it("a bar dated between the backdated entry_date and the position's real creation is never loaded", async () => {
    seedPos(db, {
      entry_date: "2026-08-01", // owner-supplied backdate
      opened_at: "2026-08-10T15:00:00Z", // position actually created 9 days later
      last_advanced_date: null,
      state: "open",
    });
    // A bar already sitting in the (global, un-scoped) ticker_quotes feed from before this
    // position existed — e.g. left over from a prior/concurrent position on the same ticker.
    // Would fire a false stop_hit if the fold ever reached it.
    db._seedQuote(quoteRow({ trade_date: "2026-08-05", close: 50, sma20: 95, sma50: 80, low: 1 }));
    const result = await sweep(db);
    expect(result.results[0].bars_advanced).toBe(0);
    const [row] = db._positions();
    expect(row.last_advanced_date).toBe(null);
    expect(row.state).toBe("open");
    expect(db._events().length).toBe(0);
  });

  it("a bar dated after the position's real creation IS advanced normally", async () => {
    seedPos(db, {
      entry_date: "2026-08-01",
      opened_at: "2026-08-10T15:00:00Z",
      last_advanced_date: null,
      state: "managing",
    });
    db._seedQuote(quoteRow({ trade_date: "2026-08-11", close: 101, sma20: 95, sma50: 80, low: 99 }));
    const result = await sweep(db);
    expect(result.results[0].bars_advanced).toBe(1);
    expect(db._positions()[0].last_advanced_date).toBe("2026-08-11");
  });
});

// ── 5. Idempotency: running sweep() twice over the same data is a no-op the 2nd time ────────────
describe("sweep — idempotency", () => {
  it("a second sweep with no new bars changes nothing", async () => {
    seedPos(db, { state: "managing" });
    db._seedQuote(quoteRow({ trade_date: "2026-08-02", close: 101, sma20: 95, sma50: 80, low: 99 }));
    await sweep(db);
    const afterFirst = db._positions()[0];
    const eventsAfterFirst = db._events().length;

    await sweep(db); // second run: no new bars past last_advanced_date
    expect(db._positions()[0]).toEqual(afterFirst);
    expect(db._events().length).toBe(eventsAfterFirst);
  });
});

// ── 6. Exit signal mid-sequence: the fold breaks, no event carries a later bar's date ───────────
describe("sweep — exit signal breaks the fold", () => {
  it("stop_hit on bar 3 of 4: closing, exit_signal_date/last_advanced_date == bar 3, bar 4 never touched", async () => {
    seedPos(db, { state: "managing" });
    // bar1: sma20=95 -> current_stop ratchets 90->95 (no exit; low 99 > 90 pre-bar stop)
    db._seedQuote(quoteRow({ trade_date: "2026-08-02", close: 101, sma20: 95, sma50: 80, low: 99 }));
    // bar2: sma20=97 -> current_stop ratchets 95->97 (low 101 > 95)
    db._seedQuote(quoteRow({ trade_date: "2026-08-03", close: 103, sma20: 97, sma50: 80, low: 101, prev_close: 101 }));
    // bar3: low 95 <= current_stop 97, open 98 >= 97 (not a gap) -> stop_hit at 97
    db._seedQuote(quoteRow({ trade_date: "2026-08-04", close: 98, sma20: 97, sma50: 80, low: 95, open: 98, prev_close: 103 }));
    // bar4: would be a no-op even if read — must NOT appear in the ledger at all
    db._seedQuote(quoteRow({ trade_date: "2026-08-05", close: 200, sma20: 97, sma50: 80, low: 199, prev_close: 98 }));

    await sweep(db);
    const [row] = db._positions();
    expect(row.state).toBe("closing");
    expect(row.exit_reason).toBe("stop_hit");
    expect(row.exit_signal_date).toBe("2026-08-04");
    expect(row.last_advanced_date).toBe("2026-08-04");
    expect(row.expected_exit_price).toBeCloseTo(97, 4); // recovered from a rounded %-distance string

    const dates = db._events().map((e) => e.trade_date);
    expect(dates).not.toContain("2026-08-05");
  });
});

// ── 7. closing / closed positions are not picked up by the sweep at all ─────────────────────────
describe("sweep — advanceable-states scoping", () => {
  it("closing and closed positions are excluded entirely", async () => {
    seedPos(db, { ticker: "CLOSING1", state: "closing", last_advanced_date: "2026-08-01" });
    seedPos(db, { ticker: "CLOSED1", state: "closed", last_advanced_date: "2026-08-01" });
    db._seedQuote(quoteRow({ ticker: "CLOSING1", trade_date: "2026-08-02", close: 101, sma20: 95, sma50: 80, low: 99 }));
    db._seedQuote(quoteRow({ ticker: "CLOSED1", trade_date: "2026-08-02", close: 101, sma20: 95, sma50: 80, low: 99 }));

    const result = await sweep(db);
    expect(result.positions).toBe(0);
    expect(result.results).toEqual([]);
    // untouched — no advance means no last_advanced_date change
    for (const row of db._positions()) expect(row.last_advanced_date).toBe("2026-08-01");
  });
});

// ── 8. A stale bar mid-sequence emits a note, does not stamp the date, next good bar still works ─
describe("sweep — stale bar handling", () => {
  it("null-close bar mid-sequence: note event, no date stamp; the following good bar still advances", async () => {
    seedPos(db, { state: "managing" });
    db._seedQuote(quoteRow({ trade_date: "2026-08-02", close: 101, sma20: 95, sma50: 80, low: 99 }));
    db._seedQuote(quoteRow({ trade_date: "2026-08-03", close: null, sma20: null, sma50: null, low: null })); // stale
    db._seedQuote(quoteRow({ trade_date: "2026-08-04", close: 103, sma20: 97, sma50: 80, low: 101, prev_close: 101 }));

    const result = await sweep(db);
    expect(result.stale).toBe(1);
    const [row] = db._positions();
    expect(row.last_advanced_date).toBe("2026-08-04"); // stale bar never stamped, good bars did
    const events = db._events();
    const staleNote = events.find((e) => e.trade_date === "2026-08-03");
    expect(staleNote).toBeTruthy();
    expect(staleNote.event_type).toBe("note");
    expect(JSON.parse(staleNote.payload).stale).toBe(true);
  });

  // Regression (lead, 2026-08-13): a stale bar deliberately does NOT stamp last_advanced_date, so
  // it stays inside the query window on every subsequent sweep. If a sweep persisted purely on
  // "there were events", a TRAILING stale bar would re-append its note event every single day,
  // forever — and because every earlier stale date also stays in the window, the duplication grows
  // quadratically over a run of stale sessions (a delisted ticker, or a scrape returning no close).
  // The append-only ledger has no dedupe, so the fix is at the persistence gate: only write when
  // last_advanced_date actually MOVED. Staleness is still surfaced — via the sweep's `stale` count,
  // which the /advance response returns and the CI job logs — just not into the permanent ledger.
  it("a trailing stale bar does not re-append its note on every later sweep", async () => {
    seedPos(db, { state: "managing" });
    db._seedQuote(quoteRow({ trade_date: "2026-08-02", close: 101, sma20: 95, sma50: 80, low: 99 }));
    db._seedQuote(quoteRow({ trade_date: "2026-08-03", close: null, sma20: null, sma50: null, low: null }));

    await sweep(db);
    const afterFirst = db._events().length;
    const r2 = await sweep(db);
    await sweep(db);

    // The stale bar is still seen and still counted every sweep — that is the alert channel.
    expect(r2.stale).toBe(1);
    // But the ledger must not grow: no new rows from re-observing the same stale bar.
    expect(db._events().length).toBe(afterFirst);
  });
});

// ── 9. MAX_CATCHUP_BARS caps one sweep; a second sweep continues and finishes ────────────────────
describe("sweep — MAX_CATCHUP_BARS cap and continuation", () => {
  it("caps bars_advanced at MAX_CATCHUP_BARS; the next sweep picks up where it left off", async () => {
    seedPos(db, { state: "managing" });
    const TOTAL = SWEEP_CONFIG.MAX_CATCHUP_BARS + 5;
    // Flat, benign bars — price/MA levels never move, so nothing ever exits or trims across all 35.
    for (let i = 1; i <= TOTAL; i++) {
      db._seedQuote(quoteRow({ trade_date: addDays("2026-08-01", i), close: 101, sma20: 95, sma50: 80, low: 99, prev_close: 101 }));
    }

    const first = await sweep(db);
    expect(first.results[0].bars_advanced).toBe(SWEEP_CONFIG.MAX_CATCHUP_BARS);
    const afterFirst = db._positions()[0].last_advanced_date;
    expect(afterFirst).toBe(addDays("2026-08-01", SWEEP_CONFIG.MAX_CATCHUP_BARS));

    const second = await sweep(db);
    expect(second.results[0].bars_advanced).toBe(5); // the remaining bars
    expect(db._positions()[0].last_advanced_date).toBe(addDays("2026-08-01", TOTAL));
  });
});

// ── 10. meta stored as a JSON string is parsed; widen_enabled:false actually suppresses the widen ─
describe("sweep — meta JSON parsing feeds effectiveConfig/widen correctly", () => {
  it("widen_enabled:false keeps 20ma even when sma50 > entry; a true sibling widens to 50ma", async () => {
    seedPos(db, { ticker: "WIDENOFF", state: "managing", meta: JSON.stringify({ widen_enabled: false }) });
    seedPos(db, { ticker: "WIDENON", state: "managing", meta: JSON.stringify({ widen_enabled: true }) });
    // sma50 (105) > entry_price (100) is the widen trigger; sma20 (100) is lower still.
    db._seedQuote(quoteRow({ ticker: "WIDENOFF", trade_date: "2026-08-02", close: 112, sma20: 100, sma50: 105, low: 110 }));
    db._seedQuote(quoteRow({ ticker: "WIDENON", trade_date: "2026-08-02", close: 112, sma20: 100, sma50: 105, low: 110 }));

    await sweep(db);
    const rows = Object.fromEntries(db._positions().map((r) => [r.ticker, r]));
    expect(rows.WIDENOFF.trail_basis).toBe("20ma");
    expect(rows.WIDENON.trail_basis).toBe("50ma");
  });
});

// ── 11. dry_run computes the same shape but writes nothing ───────────────────────────────────────
describe("sweep — dry_run", () => {
  it("dry_run:true returns computed counts/results but persists no row or event changes", async () => {
    seedPos(db, { state: "managing" });
    db._seedQuote(quoteRow({ trade_date: "2026-08-02", close: 101, sma20: 95, sma50: 80, low: 99 }));
    const before = db._positions()[0];
    const eventsBefore = db._events().length;

    const result = await sweep(db, { dry_run: true });
    expect(result.dry_run).toBe(true);
    expect(result.advanced).toBe(1); // computed as if it would apply

    expect(db._positions()[0]).toEqual(before); // untouched
    expect(db._events().length).toBe(eventsBefore); // untouched
  });
});

// ── 12. CAS: a concurrent writer invalidates a stale expectedLastAdvancedDate ────────────────────
describe("persistAdvance — compare-and-set", () => {
  it("a stale expectedLastAdvancedDate applies nothing (lost race)", async () => {
    const seeded = seedPos(db, { state: "managing", last_advanced_date: null });
    // Simulate a concurrent writer advancing the position between our load and our persist.
    await db.prepare("UPDATE positions SET last_advanced_date = ? WHERE trade_id = ?").bind("2026-08-09", seeded.trade_id).run();
    const before = db._positions()[0];

    const outcome = await persistAdvance(db, {
      trade_id: seeded.trade_id,
      user_id: "owner",
      expectedLastAdvancedDate: null, // stale — the row is now "2026-08-09"
      position: { ...before, state: "managing", current_stop: 999, last_advanced_date: "2026-08-10" },
      events: [{ event_type: "note", trade_date: "2026-08-10", payload: { would_be: "dropped" } }],
      now_iso: "2026-08-10T00:00:00Z",
    });

    expect(outcome.applied).toBe(false);
    expect(outcome.eventsWritten).toBe(0);
    expect(db._positions()[0]).toEqual(before); // row untouched by the failed CAS
    expect(db._events()).toEqual([]);
  });
});

// ── 13. /advance route: dual auth + response shaping ──────────────────────────────────────────
describe("POST /advance route", () => {
  const SECRET = "test-secret-abc123-abc123-abc123";
  const PASSPHRASE = "correct horse";
  const INGEST_TOKEN = "ingest-token-super-secret-0123456789";
  let env;
  beforeEach(() => {
    env = {
      POSITIONS_SESSION_SECRET: SECRET,
      POSITIONS_AUTH_PASSPHRASE: PASSPHRASE,
      POSITIONS_INGEST_TOKEN: INGEST_TOKEN,
      ALLOWED_ORIGINS: "https://clarencelam2000.github.io,http://localhost:8000",
      POSITIONS_DB: db,
    };
    seedPos(db, { state: "managing" });
    db._seedQuote(quoteRow({ trade_date: "2026-08-02", close: 101, sma20: 95, sma50: 80, low: 99 }));
  });

  function advReq({ token, dry_run } = {}) {
    const headers = {};
    if (token) headers.authorization = `Bearer ${token}`;
    const qs = dry_run ? "?dry_run=1" : "";
    return new Request(`https://x/advance${qs}`, { method: "POST", headers });
  }

  it("service token -> 200 with counts only, no results key", async () => {
    const res = await handleRequest(advReq({ token: INGEST_TOKEN }), env);
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.advanced).toBe(1);
    expect("results" in body).toBe(false);
  });

  it("owner bearer -> 200 with results included", async () => {
    const token = await mintToken(env, "owner");
    const res = await handleRequest(advReq({ token }), env);
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(Array.isArray(body.results)).toBe(true);
    expect(body.results[0].ticker).toBe("AAPL");
  });

  it("no token -> 401", async () => {
    const res = await handleRequest(advReq({}), env);
    expect(res.status).toBe(401);
  });

  it("garbage token -> 401", async () => {
    const res = await handleRequest(advReq({ token: "not-a-real-token" }), env);
    expect(res.status).toBe(401);
  });
});

// ── Auto-confirm pass (WS5 phase 3b-ii) ────────────────────────────────────────────────────────

describe("sessionsSince — pure session counter", () => {
  const cal = ["2026-02-09", "2026-02-10", "2026-02-11", "2026-02-12", "2026-02-13"];
  it("counts only sessions strictly after the signal date", () => {
    expect(sessionsSince(cal, "2026-02-10")).toBe(3); // 11,12,13
  });
  it("is 0 on the signal date itself with no later sessions", () => {
    expect(sessionsSince(["2026-02-10"], "2026-02-10")).toBe(0);
  });
  it("returns 0 for a missing signal date", () => {
    expect(sessionsSince(cal, null)).toBe(0);
  });
});

describe("sweep — auto-confirm of stuck closing positions", () => {
  // A closing position awaiting confirmation, signalled on `signalDate`.
  function seedClosingPos(db, partial = {}) {
    return db._seedPosition({
      ticker: "VRT",
      state: "closing",
      entry_date: "2026-01-02",
      entry_price: 100,
      initial_stop: 90,
      profit_floor: 90,
      current_stop: 96,
      remaining_qty: 100,
      expected_exit_price: 96,
      exit_signal_date: "2026-02-10",
      exit_reason: "stop_hit",
      last_advanced_date: "2026-02-10",
      ...partial,
    });
  }
  // Seed a bare calendar of sessions (any ticker; the calendar is global).
  function seedCalendar(db, dates, ticker = "SPY") {
    for (const d of dates) db._seedQuote({ ticker, trade_date: d, close: 100 });
  }

  const NOW = new Date("2026-02-18T22:00:00Z");

  it("auto-closes at expected_exit_price after EXIT_AUTOCONFIRM_SESSIONS sessions", async () => {
    const db = makeD1();
    const p = seedClosingPos(db);
    seedCalendar(db, ["2026-02-11", "2026-02-12", "2026-02-13", "2026-02-16", "2026-02-17"]); // 5 > signal
    const out = await sweep(db, { now: NOW });
    expect(out.auto_confirmed).toBe(1);

    const row = db._positions().find((r) => r.trade_id === p.trade_id);
    expect(row.state).toBe("closed");
    expect(row.exit_price).toBe(96); // frozen expected price, not re-derived
    expect(row.confirmation_status).toBe("auto");
    const closed = db._events().find((e) => e.event_type === "closed");
    expect(JSON.parse(closed.payload).confirmation_status).toBe("auto");
    // engine columns untouched by the auto-confirm write path
    expect(row.current_stop).toBe(96);
  });

  it("leaves a position parked when fewer than EXIT_AUTOCONFIRM_SESSIONS have elapsed", async () => {
    const db = makeD1();
    const p = seedClosingPos(db);
    seedCalendar(db, ["2026-02-11", "2026-02-12", "2026-02-13", "2026-02-16"]); // 4 < 5
    const out = await sweep(db, { now: NOW });
    expect(out.auto_confirmed).toBe(0);
    expect(db._positions().find((r) => r.trade_id === p.trade_id).state).toBe("closing");
  });

  it("dry_run reports the auto-close without writing", async () => {
    const db = makeD1();
    const p = seedClosingPos(db);
    seedCalendar(db, ["2026-02-11", "2026-02-12", "2026-02-13", "2026-02-16", "2026-02-17"]);
    const out = await sweep(db, { now: NOW, dry_run: true });
    expect(out.auto_confirmed).toBe(1);
    expect(db._positions().find((r) => r.trade_id === p.trade_id).state).toBe("closing"); // unchanged
    expect(db._events().length).toBe(0);
  });

  it("honors a per-position EXIT_AUTOCONFIRM_SESSIONS override in meta.config", async () => {
    const db = makeD1();
    const p = seedClosingPos(db, { meta: JSON.stringify({ config: { EXIT_AUTOCONFIRM_SESSIONS: 2 } }) });
    seedCalendar(db, ["2026-02-11", "2026-02-12"]); // 2 sessions
    const out = await sweep(db, { now: NOW });
    expect(out.auto_confirmed).toBe(1);
    expect(db._positions().find((r) => r.trade_id === p.trade_id).state).toBe("closed");
  });

  it("uses the GLOBAL session calendar (a gap in the position's own ticker doesn't understate it)", async () => {
    const db = makeD1();
    const p = seedClosingPos(db, { ticker: "VRT" });
    // No VRT quotes at all — the sessions come entirely from other held names.
    seedCalendar(db, ["2026-02-11", "2026-02-12", "2026-02-13", "2026-02-16", "2026-02-17"], "AAPL");
    const out = await sweep(db, { now: NOW });
    expect(out.auto_confirmed).toBe(1);
    expect(db._positions().find((r) => r.trade_id === p.trade_id).state).toBe("closed");
  });

  it("loadClosingPositions parses meta and excludes non-closing states", async () => {
    const db = makeD1();
    seedClosingPos(db, { trade_id: "c1", meta: JSON.stringify({ config: { EXIT_AUTOCONFIRM_SESSIONS: 3 } }) });
    db._seedPosition({ trade_id: "m1", state: "managing" });
    db._seedPosition({ trade_id: "x1", state: "closed" });
    const rows = await loadClosingPositions(db);
    expect(rows.map((r) => r.trade_id)).toEqual(["c1"]);
    expect(rows[0].meta.config.EXIT_AUTOCONFIRM_SESSIONS).toBe(3);
  });

  it("distinctTradeDates returns the ascending union across tickers", async () => {
    const db = makeD1();
    db._seedQuote({ ticker: "AAPL", trade_date: "2026-02-12", close: 1 });
    db._seedQuote({ ticker: "VRT", trade_date: "2026-02-12", close: 1 }); // same date, dedup
    db._seedQuote({ ticker: "AAPL", trade_date: "2026-02-11", close: 1 });
    expect(await distinctTradeDates(db)).toEqual(["2026-02-11", "2026-02-12"]);
  });
});

// ── WS5-4b PR-A: Tier-2 decaying-cadence exit reminders (issue #348 tail) ────────────────────────
describe("sweep — Tier-2 reminder push cadence", () => {
  function seedClosingPos(db, partial = {}) {
    return db._seedPosition({
      ticker: "VRT",
      user_id: "owner",
      state: "closing",
      entry_date: "2026-01-02",
      entry_price: 100,
      initial_stop: 90,
      profit_floor: 90,
      current_stop: 96,
      remaining_qty: 100,
      expected_exit_price: 96,
      exit_signal_date: "2026-02-10",
      exit_reason: "stop_hit",
      last_advanced_date: "2026-02-10",
      ...partial,
    });
  }
  function seedCalendar(db, dates, ticker = "AAPL") {
    for (const d of dates) db._seedQuote({ ticker, trade_date: d, close: 100 });
  }

  const CAL_ALL = ["2026-02-11", "2026-02-12", "2026-02-13", "2026-02-16", "2026-02-17"]; // sessions 1..5 after signal 02-10

  async function runAt(db, sessionsInClosing, mock) {
    // seedCalendar with exactly `sessionsInClosing` sessions strictly after 2026-02-10.
    seedCalendar(db, CAL_ALL.slice(0, sessionsInClosing));
    await subscribePush(db, "owner", { endpoint: "https://push.example/a", p256dh: "p1", auth: "a1" });
    const now = new Date("2026-02-20T22:00:00Z");
    return sweep(db, { now, push: { vapid: { publicKey: "x", privateKey: "y", contactEmail: "z@z.com" }, sendPushFn: mock } });
  }

  for (const n of [1, 2, 4]) {
    it(`sessions_in_closing=${n} queues a reminder`, async () => {
      const db = makeD1();
      seedClosingPos(db);
      let calls = 0;
      const mock = async () => {
        calls++;
        return { ok: true, status: 201, gone: false };
      };
      await runAt(db, n, mock);
      expect(calls).toBe(1);
      expect(db._events().filter((e) => e.event_type === "reminder_push_sent")).toHaveLength(1);
    });
  }

  it("sessions_in_closing=3 does NOT queue a reminder", async () => {
    const db = makeD1();
    seedClosingPos(db);
    let calls = 0;
    const mock = async () => {
      calls++;
      return { ok: true, status: 201, gone: false };
    };
    await runAt(db, 3, mock);
    expect(calls).toBe(0);
    expect(db._events().filter((e) => e.event_type === "reminder_push_sent")).toHaveLength(0);
  });

  it("sessions_in_closing=0 (just entered closing this sweep) does NOT queue a Tier-2 reminder", async () => {
    const db = makeD1();
    // exit_signal_date == last_advanced_date == today's trade_date -> sessionsSince returns 0
    // with no calendar entries strictly after it.
    seedClosingPos(db, { exit_signal_date: "2026-02-20", last_advanced_date: "2026-02-20" });
    let calls = 0;
    const mock = async () => {
      calls++;
      return { ok: true, status: 201, gone: false };
    };
    await subscribePush(db, "owner", { endpoint: "https://push.example/a", p256dh: "p1", auth: "a1" });
    const now = new Date("2026-02-20T22:00:00Z");
    const out = await sweep(db, { now, push: { vapid: { publicKey: "x", privateKey: "y", contactEmail: "z@z.com" }, sendPushFn: mock } });
    expect(calls).toBe(0);
    expect(out.auto_confirmed).toBe(0);
    expect(db._events().filter((e) => e.event_type === "reminder_push_sent")).toHaveLength(0);
  });

  it("sessions_in_closing=5 auto-confirms and gets no reminder", async () => {
    const db = makeD1();
    seedClosingPos(db);
    let calls = 0;
    const mock = async () => {
      calls++;
      return { ok: true, status: 201, gone: false };
    };
    const out = await runAt(db, 5, mock);
    expect(out.auto_confirmed).toBe(1);
    expect(calls).toBe(0);
    expect(db._events().filter((e) => e.event_type === "reminder_push_sent")).toHaveLength(0);
  });
});

// ── WS5-7 persist-disjointness guard: the engine (sweep) path and the ack-stop event path must
// never touch each other's writes. ackStop() writes NO `positions` column (see its comment in
// transitions.js); a sweep run must never create, alter, or remove a stop_ack event. ─────────────
describe("persist-disjointness — sweep vs. ackStop", () => {
  it("a sweep run leaves an existing stop_ack event untouched and appends none of its own", async () => {
    const db = makeD1();
    const p = seedPos(db, { state: "managing", current_stop: 90, last_advanced_date: null });
    await ackStop(db, { user_id: "owner", trade_id: p.trade_id, now: new Date("2026-08-01T20:00:00Z") });
    const ackBefore = db._events().filter((e) => e.event_type === "stop_ack");
    expect(ackBefore).toHaveLength(1);

    // Advance the position through a real bar — this ratchets current_stop, appending its own
    // (non-ack) events, and updates last_advanced_date.
    db._seedQuote(quoteRow({ trade_date: "2026-08-02", close: 101, sma20: 95, sma50: 80, low: 99 }));
    await sweep(db);
    expect(db._positions()[0].last_advanced_date).toBe("2026-08-02"); // the engine path did run

    const ackAfter = db._events().filter((e) => e.event_type === "stop_ack");
    expect(ackAfter).toEqual(ackBefore); // byte-identical: sweep touched no stop_ack row
  });

  it("ackStop writes only position_events — the positions row (all engine + transition columns) is bit-for-bit unchanged", async () => {
    const db = makeD1();
    const p = seedPos(db, { state: "managing", current_stop: 90 });
    const before = db._positions()[0];
    await ackStop(db, { user_id: "owner", trade_id: p.trade_id, now: new Date("2026-08-01T20:00:00Z") });
    const after = db._positions()[0];
    expect(after).toEqual(before); // ackStop appended an event but wrote zero positions columns
  });
});
