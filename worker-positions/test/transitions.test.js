import { describe, it, expect, beforeEach } from "vitest";
import { makeD1 } from "./helpers/d1.js";
import { handleRequest } from "../src/index.js";
import { mintToken } from "../src/auth.js";
import { applyTransition, persistTransition, loadPosition } from "../src/transitions.js";

// ── Fixture helpers ──────────────────────────────────────────────────────────────────────────

// A position sitting in `closing` with an exit signal awaiting confirmation — the state
// confirm-exit / still-holding act on. entry/stop give rMultiple() something real to compute.
function seedClosing(db, partial = {}) {
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

// A settled `closed` position — the state correct-exit / reopen act on.
function seedClosed(db, partial = {}) {
  return db._seedPosition({
    ticker: "VRT",
    state: "closed",
    entry_date: "2026-01-02",
    entry_price: 100,
    initial_stop: 90,
    profit_floor: 90,
    current_stop: 96,
    remaining_qty: 100,
    expected_exit_price: 96,
    exit_signal_date: "2026-02-10",
    exit_reason: "stop_hit",
    exit_price: 96,
    closed_at: "2026-02-11T22:00:00Z",
    confirmation_status: "confirmed",
    last_advanced_date: "2026-02-10",
    ...partial,
  });
}

let db;
beforeEach(() => {
  db = makeD1();
});

// ── confirm-exit ─────────────────────────────────────────────────────────────────────────────
describe("applyTransition — confirm-exit", () => {
  it("closes at expected_exit_price when no fill is given", async () => {
    const p = seedClosing(db);
    const res = await applyTransition(db, { user_id: "owner", trade_id: p.trade_id, action: "confirm-exit", body: {} });
    expect(res.error).toBeUndefined();
    expect(res.position.state).toBe("closed");
    expect(res.position.exit_price).toBe(96);
    expect(res.position.confirmation_status).toBe("confirmed");

    const row = db._positions()[0];
    expect(row.state).toBe("closed");
    expect(row.exit_price).toBe(96);
    expect(row.confirmation_status).toBe("confirmed");
    const closed = db._events().find((e) => e.event_type === "closed");
    expect(closed).toBeTruthy();
    expect(JSON.parse(closed.payload).confirmation_status).toBe("confirmed");
    // R = (96 - 100) / (100 - 90) = -0.4
    expect(JSON.parse(closed.payload).r_multiple).toBeCloseTo(-0.4, 6);
  });

  it("records an edited actual fill that differs from the modeled price", async () => {
    const p = seedClosing(db);
    const res = await applyTransition(db, {
      user_id: "owner",
      trade_id: p.trade_id,
      action: "confirm-exit",
      body: { exit_price: 95.4 },
    });
    expect(res.position.exit_price).toBe(95.4);
    expect(db._positions()[0].exit_price).toBe(95.4);
  });

  it("rejects a non-positive or non-numeric fill (400) without a bogus close", async () => {
    for (const bad of [0, -1, "94", NaN]) {
      const p = seedClosing(db, { trade_id: `t-${bad}` });
      const res = await applyTransition(db, { user_id: "owner", trade_id: p.trade_id, action: "confirm-exit", body: { exit_price: bad } });
      expect(res.status).toBe(400);
      expect(db._positions().find((r) => r.trade_id === p.trade_id).state).toBe("closing");
    }
  });

  it("400s when no fill given and there is no expected_exit_price on file", async () => {
    const p = seedClosing(db, { expected_exit_price: null });
    const res = await applyTransition(db, { user_id: "owner", trade_id: p.trade_id, action: "confirm-exit", body: {} });
    expect(res.status).toBe(400);
  });

  it("409s from a non-closing state", async () => {
    const p = db._seedPosition({ state: "managing" });
    const res = await applyTransition(db, { user_id: "owner", trade_id: p.trade_id, action: "confirm-exit", body: {} });
    expect(res.status).toBe(409);
  });
});

// ── still-holding ────────────────────────────────────────────────────────────────────────────
describe("applyTransition — still-holding", () => {
  it("reverts closing → managing, clears exit fields, re-arms caution, logs a note", async () => {
    const p = seedClosing(db, { caution_flag: 1 });
    const res = await applyTransition(db, { user_id: "owner", trade_id: p.trade_id, action: "still-holding", body: {} });
    expect(res.position.state).toBe("managing");
    const row = db._positions()[0];
    expect(row.state).toBe("managing");
    expect(row.expected_exit_price).toBeNull();
    expect(row.exit_signal_date).toBeNull();
    expect(row.exit_reason).toBeNull();
    expect(row.caution_flag).toBe(0); // re-armed (CAUTION_REARM_ON_HOLD default)
    // engine columns are untouched by this write path
    expect(row.current_stop).toBe(96);
    expect(row.last_advanced_date).toBe("2026-02-10");
    const note = db._events().find((e) => e.event_type === "note");
    expect(JSON.parse(note.payload).still_holding).toBe(true);
  });

  it("409s from closed", async () => {
    const p = seedClosed(db);
    const res = await applyTransition(db, { user_id: "owner", trade_id: p.trade_id, action: "still-holding", body: {} });
    expect(res.status).toBe(409);
  });
});

// ── correct-exit ─────────────────────────────────────────────────────────────────────────────
describe("applyTransition — correct-exit", () => {
  it("appends exit_corrected, updates price + R, keeps state closed", async () => {
    const p = seedClosed(db);
    const res = await applyTransition(db, { user_id: "owner", trade_id: p.trade_id, action: "correct-exit", body: { exit_price: 97 } });
    expect(res.position.state).toBe("closed");
    expect(res.position.exit_price).toBe(97);
    const row = db._positions()[0];
    expect(row.exit_price).toBe(97);
    expect(row.confirmation_status).toBe("confirmed");
    const corrected = db._events().find((e) => e.event_type === "exit_corrected");
    expect(JSON.parse(corrected.payload).from).toBe(96);
    expect(JSON.parse(corrected.payload).to).toBe(97);
  });

  it("400s without a valid exit_price", async () => {
    const p = seedClosed(db);
    for (const bad of [undefined, 0, -5]) {
      const res = await applyTransition(db, { user_id: "owner", trade_id: p.trade_id, action: "correct-exit", body: { exit_price: bad } });
      expect(res.status).toBe(400);
    }
  });

  it("409s from a non-closed state", async () => {
    const p = seedClosing(db);
    const res = await applyTransition(db, { user_id: "owner", trade_id: p.trade_id, action: "correct-exit", body: { exit_price: 97 } });
    expect(res.status).toBe(409);
  });
});

// ── reopen ───────────────────────────────────────────────────────────────────────────────────
describe("applyTransition — reopen", () => {
  it("closed → managing, clears exit fields, re-arms caution, logs reopened", async () => {
    const p = seedClosed(db, { caution_flag: 1, confirmation_status: "auto" });
    const res = await applyTransition(db, { user_id: "owner", trade_id: p.trade_id, action: "reopen", body: {} });
    expect(res.position.state).toBe("managing");
    const row = db._positions()[0];
    expect(row.state).toBe("managing");
    expect(row.exit_price).toBeNull();
    expect(row.closed_at).toBeNull();
    expect(row.expected_exit_price).toBeNull();
    expect(row.exit_signal_date).toBeNull();
    expect(row.exit_reason).toBeNull();
    expect(row.confirmation_status).toBe("unconfirmed");
    expect(row.caution_flag).toBe(0);
    const reopened = db._events().find((e) => e.event_type === "reopened");
    expect(JSON.parse(reopened.payload).prior_exit_price).toBe(96);
  });

  it("409s from open/managing", async () => {
    const p = db._seedPosition({ state: "open" });
    const res = await applyTransition(db, { user_id: "owner", trade_id: p.trade_id, action: "reopen", body: {} });
    expect(res.status).toBe(409);
  });
});

// ── tenant scoping + not-found ─────────────────────────────────────────────────────────────────
describe("applyTransition — scoping and errors", () => {
  it("404s on an unknown trade_id", async () => {
    const res = await applyTransition(db, { user_id: "owner", trade_id: "nope", action: "confirm-exit", body: {} });
    expect(res.status).toBe(404);
  });

  it("404s on another user's position (no cross-tenant leak)", async () => {
    const p = seedClosing(db, { user_id: "someone-else" });
    const res = await applyTransition(db, { user_id: "owner", trade_id: p.trade_id, action: "confirm-exit", body: {} });
    expect(res.status).toBe(404);
    expect(db._positions()[0].state).toBe("closing"); // untouched
  });

  it("400s on an unknown action", async () => {
    const p = seedClosing(db);
    const res = await applyTransition(db, { user_id: "owner", trade_id: p.trade_id, action: "delete", body: {} });
    expect(res.status).toBe(400);
  });

  it("a second confirm-exit sees the closed state and 409s (double-submit safe)", async () => {
    const p = seedClosing(db);
    const first = await applyTransition(db, { user_id: "owner", trade_id: p.trade_id, action: "confirm-exit", body: {} });
    expect(first.position.state).toBe("closed");
    const second = await applyTransition(db, { user_id: "owner", trade_id: p.trade_id, action: "confirm-exit", body: {} });
    expect(second.status).toBe(409);
    // exactly one closed event — no duplicate ledger row from the retry
    expect(db._events().filter((e) => e.event_type === "closed").length).toBe(1);
  });
});

// ── persistTransition CAS ──────────────────────────────────────────────────────────────────────
describe("persistTransition — compare-and-set on state", () => {
  it("no-ops (applied=false, no event) when the pre-state guard fails", async () => {
    const p = seedClosed(db); // actual state is 'closed'
    const { applied } = await persistTransition(db, {
      trade_id: p.trade_id,
      user_id: "owner",
      expectedState: "closing", // stale expectation — lost the race
      position: { ...p, state: "closed", exit_price: 1, closed_at: "x", confirmation_status: "auto", caution_flag: 0 },
      events: [{ event_type: "closed", trade_date: "2026-02-12", payload: {} }],
      now_iso: "2026-02-12T22:00:00Z",
    });
    expect(applied).toBe(false);
    expect(db._events().length).toBe(0); // guarded INSERT dropped too
  });
});

// ── HTTP route surface ─────────────────────────────────────────────────────────────────────────
const SECRET = "test-secret-abc123-abc123-abc123";
const INGEST_TOKEN = "ingest-token-super-secret-0123456789";

function txReq(path, { method = "POST", body, token } = {}) {
  const headers = {};
  if (token) headers.authorization = `Bearer ${token}`;
  if (body !== undefined) headers["content-type"] = "application/json";
  return new Request(`https://finviz-positions.workers.dev${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

describe("transition routes via handleRequest", () => {
  let env;
  beforeEach(() => {
    env = {
      POSITIONS_SESSION_SECRET: SECRET,
      POSITIONS_AUTH_PASSPHRASE: "correct horse",
      POSITIONS_INGEST_TOKEN: INGEST_TOKEN,
      ALLOWED_ORIGINS: "https://clarencelam2000.github.io",
      POSITIONS_DB: makeD1(),
    };
  });

  it("401s without an owner token", async () => {
    const p = seedClosing(env.POSITIONS_DB);
    const res = await handleRequest(txReq(`/positions/${p.trade_id}/confirm-exit`, { body: {} }), env);
    expect(res.status).toBe(401);
  });

  it("rejects the service (ingest) token — owner-only route", async () => {
    const p = seedClosing(env.POSITIONS_DB);
    const res = await handleRequest(txReq(`/positions/${p.trade_id}/confirm-exit`, { body: {}, token: INGEST_TOKEN }), env);
    expect(res.status).toBe(401);
    expect(env.POSITIONS_DB._positions()[0].state).toBe("closing");
  });

  it("confirms an exit end-to-end with an owner token", async () => {
    const p = seedClosing(env.POSITIONS_DB);
    const token = await mintToken(env);
    const res = await handleRequest(txReq(`/positions/${p.trade_id}/confirm-exit`, { body: { exit_price: 95.5 }, token }), env);
    expect(res.status).toBe(200);
    const { position } = await res.json();
    expect(position.state).toBe("closed");
    expect(position.exit_price).toBe(95.5);
  });

  it("404s an unknown trade_id through the route", async () => {
    const token = await mintToken(env);
    const res = await handleRequest(txReq(`/positions/ghost/reopen`, { body: {}, token }), env);
    expect(res.status).toBe(404);
  });

  it("400s on malformed JSON body", async () => {
    const p = seedClosing(env.POSITIONS_DB);
    const token = await mintToken(env);
    const bad = new Request(`https://finviz-positions.workers.dev/positions/${p.trade_id}/confirm-exit`, {
      method: "POST",
      headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
      body: "{not json",
    });
    const res = await handleRequest(bad, env);
    expect(res.status).toBe(400);
  });

  it("does not shadow the /positions collection route", async () => {
    const token = await mintToken(env);
    const res = await handleRequest(txReq(`/positions`, { method: "GET", token }), env);
    expect(res.status).toBe(200); // list, not a transition 404
  });

  it("400s (not an uncaught URIError) on a malformed percent-encoded trade_id", async () => {
    const token = await mintToken(env);
    const bad = new Request(`https://finviz-positions.workers.dev/positions/%E0%A4%A/confirm-exit`, {
      method: "POST",
      headers: { authorization: `Bearer ${token}`, origin: "https://clarencelam2000.github.io" },
    });
    const res = await handleRequest(bad, env);
    expect(res.status).toBe(400);
    // Must still be a proper CORS'd json() response, not a raw thrown error.
    expect(res.headers.get("access-control-allow-origin")).toBeTruthy();
  });
});
