import { describe, it, expect, beforeEach } from "vitest";
import { handleRequest } from "../src/index.js";
import { mintToken } from "../src/auth.js";
import { makeD1 } from "./helpers/d1.js";

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
    POSITIONS_DB: makeD1(),
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
    expect(env.POSITIONS_DB._events().length).toBe(1);
    expect(env.POSITIONS_DB._events()[0].event_type).toBe("entered");

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
    expect(env.POSITIONS_DB._positions()).toHaveLength(2);
    const rows = env.POSITIONS_DB._positions();
    expect(rows[0].trade_id).not.toBe(rows[1].trade_id);
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

describe("WS5 phase 2 — held-tickers feed machine routes", () => {
  const ingestReq = (path, { method = "GET", body } = {}) => {
    const headers = { authorization: `Bearer ${INGEST_TOKEN}` };
    if (body !== undefined) headers["content-type"] = "application/json";
    return new Request(`https://finviz-positions.workers.dev${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  };

  it("GET /held-tickers returns the union of open/managing/closing tickers", async () => {
    env.POSITIONS_DB._seedPosition({ ticker: "AAPL", state: "open", user_id: "owner" });
    env.POSITIONS_DB._seedPosition({ ticker: "MSFT", state: "closing", user_id: "owner" });
    env.POSITIONS_DB._seedPosition({ ticker: "TSLA", state: "watching", user_id: "owner" });
    const res = await handleRequest(ingestReq("/held-tickers"), env);
    expect(res.status).toBe(200);
    expect((await res.json()).tickers).toEqual(["AAPL", "MSFT"]);
  });

  it("POST /ingest/quotes writes append-only bars and reports the count", async () => {
    const body = {
      trade_date: "2026-08-13",
      collected_at: "2026-08-13T21:05:00Z",
      quotes: [{ ticker: "AAPL", close: 231.5, raw: { Ticker: "AAPL", SMA50: "3.2%" } }],
    };
    const res = await handleRequest(ingestReq("/ingest/quotes", { method: "POST", body }), env);
    expect(res.status).toBe(200);
    expect((await res.json()).written).toBe(1);
    const q = env.POSITIONS_DB._quotes().find((r) => r.ticker === "AAPL" && r.trade_date === "2026-08-13");
    expect(q.close).toBe(231.5);
  });

  it("POST /ingest/quotes 400s a malformed batch", async () => {
    const res = await handleRequest(ingestReq("/ingest/quotes", { method: "POST", body: { trade_date: "bad", quotes: [] } }), env);
    expect(res.status).toBe(400);
  });

  // ── Cross-auth isolation: the two auth paths cannot substitute for each other ──────────────────
  it("machine routes reject a valid OWNER bearer token (not a service token)", async () => {
    const ownerToken = await mintToken(env, "owner");
    const withOwner = (path, method = "GET", body) =>
      new Request(`https://x${path}`, {
        method,
        headers: { authorization: `Bearer ${ownerToken}`, ...(body !== undefined ? { "content-type": "application/json" } : {}) },
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
    expect((await handleRequest(withOwner("/held-tickers"), env)).status).toBe(401);
    expect((await handleRequest(withOwner("/ingest/quotes", "POST", { trade_date: "2026-08-13", collected_at: "t", quotes: [{ ticker: "AAPL" }] }), env)).status).toBe(401);
  });

  it("owner routes reject the INGEST token (cannot read/create positions)", async () => {
    expect((await handleRequest(ingestReq("/positions"), env)).status).toBe(401);
    expect((await handleRequest(ingestReq("/positions", { method: "POST", body: { ticker: "AAPL", entry_price: 100, initial_stop: 95, qty: 1 } }), env)).status).toBe(401);
  });

  it("machine routes 401 when the ingest token is wrong", async () => {
    const bad = new Request("https://x/held-tickers", { headers: { authorization: "Bearer wrong" } });
    expect((await handleRequest(bad, env)).status).toBe(401);
  });
});
