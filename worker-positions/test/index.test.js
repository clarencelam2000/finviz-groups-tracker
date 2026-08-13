import { describe, it, expect, beforeEach } from "vitest";
import { handleRequest } from "../src/index.js";
import { mintToken } from "../src/auth.js";

// Minimal in-memory D1 mock: enough for insertPosition (batch of 2 INSERTs) and listPositions
// (SELECT ... WHERE user_id = ? [AND state = ?] ORDER BY opened_at DESC).
function makeDb() {
  const positions = [];
  const events = [];
  function prepare(sql) {
    return {
      sql,
      _binds: [],
      bind(...args) {
        this._binds = args;
        return this;
      },
      async all() {
        // list query: first bind is user_id; optional second is state
        const userId = this._binds[0];
        const state = /AND state = \?/.test(sql) ? this._binds[1] : null;
        let rows = positions.filter((p) => p.user_id === userId && (state == null || p.state === state));
        rows = rows.slice().sort((a, b) => (a.opened_at < b.opened_at ? 1 : -1));
        return { results: rows };
      },
      async run() {
        _apply(sql, this._binds);
        return { success: true };
      },
    };
  }
  function _apply(sql, binds) {
    if (sql.includes("INSERT INTO positions")) {
      const cols = sql.match(/\(([^)]+)\) VALUES/)[1].split(",").map((s) => s.trim());
      const row = {};
      cols.forEach((c, i) => (row[c] = binds[i]));
      positions.push(row);
    } else if (sql.includes("INSERT INTO position_events")) {
      events.push({ trade_id: binds[0], user_id: binds[1], ts: binds[2], trade_date: binds[3], event_type: "entered", payload: binds[4] });
    }
  }
  return {
    prepare,
    async batch(stmts) {
      for (const s of stmts) _apply(s.sql, s._binds);
      return stmts.map(() => ({ success: true }));
    },
    _positions: positions,
    _events: events,
  };
}

const SECRET = "test-secret-abc123-abc123-abc123";
const PASSPHRASE = "correct horse";
let env;
beforeEach(() => {
  env = {
    POSITIONS_SESSION_SECRET: SECRET,
    POSITIONS_AUTH_PASSPHRASE: PASSPHRASE,
    ALLOWED_ORIGINS: "https://clarencelam2000.github.io,http://localhost:8000",
    POSITIONS_DB: makeDb(),
  };
});

function req(path, { method = "GET", body, token, origin } = {}) {
  const headers = {};
  if (token) headers.authorization = `Bearer ${token}`;
  if (origin) headers.origin = origin;
  if (body !== undefined) headers["content-type"] = "application/json";
  return new Request(`https://finviz-positions.workers.dev${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

describe("routing + auth gating", () => {
  it("health is open", async () => {
    const res = await handleRequest(req("/health"), env);
    expect(res.status).toBe(200);
    expect((await res.json()).service).toBe("finviz-positions");
  });

  it("preflight returns CORS for an allowed origin", async () => {
    const res = await handleRequest(req("/positions", { method: "OPTIONS", origin: "https://clarencelam2000.github.io" }), env);
    expect(res.status).toBe(204);
    expect(res.headers.get("Access-Control-Allow-Origin")).toBe("https://clarencelam2000.github.io");
  });

  it("does not echo Allow-Origin for a disallowed origin", async () => {
    const res = await handleRequest(req("/positions", { method: "OPTIONS", origin: "https://evil.example" }), env);
    expect(res.headers.get("Access-Control-Allow-Origin")).toBeNull();
  });

  it("rejects unauthenticated writes/reads", async () => {
    expect((await handleRequest(req("/positions", { method: "POST", body: {} }), env)).status).toBe(401);
    expect((await handleRequest(req("/positions"), env)).status).toBe(401);
  });

  it("login with correct passphrase yields a working token", async () => {
    const res = await handleRequest(req("/auth/login", { method: "POST", body: { passphrase: PASSPHRASE } }), env);
    expect(res.status).toBe(200);
    const { token } = await res.json();
    const authed = await handleRequest(req("/positions", { token }), env);
    expect(authed.status).toBe(200);
  });

  it("login with wrong passphrase is 401", async () => {
    const res = await handleRequest(req("/auth/login", { method: "POST", body: { passphrase: "nope" } }), env);
    expect(res.status).toBe(401);
  });
});

describe("create + list", () => {
  it("creates a position and its entered event, then lists it", async () => {
    const token = await mintToken(env, "owner");
    const res = await handleRequest(
      req("/positions", { method: "POST", token, body: { ticker: "nvda", entry_price: 120, initial_stop: 110, qty: 5, stop_basis: "20ma", meta: { source: "picks" } } }),
      env
    );
    expect(res.status).toBe(201);
    const { position } = await res.json();
    expect(position.ticker).toBe("NVDA");
    expect(position.state).toBe("open");
    expect(env.POSITIONS_DB._events.length).toBe(1);
    expect(env.POSITIONS_DB._events[0].event_type).toBe("entered");

    const list = await handleRequest(req("/positions", { token }), env);
    const { positions } = await list.json();
    expect(positions).toHaveLength(1);
    expect(positions[0].meta.source).toBe("picks");
  });

  it("two 'I took it' on one ticker create two independent lots (§ 3a)", async () => {
    const token = await mintToken(env, "owner");
    const body = { ticker: "AXON", entry_price: 50, initial_stop: 47, qty: 3 };
    await handleRequest(req("/positions", { method: "POST", token, body }), env);
    await handleRequest(req("/positions", { method: "POST", token, body }), env);
    expect(env.POSITIONS_DB._positions).toHaveLength(2);
    expect(env.POSITIONS_DB._positions[0].trade_id).not.toBe(env.POSITIONS_DB._positions[1].trade_id);
  });

  it("rejects an invalid payload with 400", async () => {
    const token = await mintToken(env, "owner");
    const res = await handleRequest(req("/positions", { method: "POST", token, body: { ticker: "X", entry_price: 10, initial_stop: 12, qty: 1 } }), env);
    expect(res.status).toBe(400);
  });

  it("list is scoped by user_id (isolation)", async () => {
    const tokenOwner = await mintToken(env, "owner");
    const tokenOther = await mintToken(env, "someone_else");
    await handleRequest(req("/positions", { method: "POST", token: tokenOwner, body: { ticker: "AAPL", entry_price: 100, initial_stop: 95, qty: 1 } }), env);
    const otherList = await handleRequest(req("/positions", { token: tokenOther }), env);
    expect((await otherList.json()).positions).toHaveLength(0);
  });
});
