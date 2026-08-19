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

describe("GET /positions state filtering", () => {
  it("no ?state= returns every state, matching pre-filter behavior", async () => {
    const token = await mintToken(env, "owner");
    env.POSITIONS_DB._seedPosition({ ticker: "AAPL", state: "open" });
    env.POSITIONS_DB._seedPosition({ ticker: "MSFT", state: "managing" });
    env.POSITIONS_DB._seedPosition({ ticker: "TSLA", state: "closing" });
    env.POSITIONS_DB._seedPosition({ ticker: "NVDA", state: "closed" });
    const res = await handleRequest(req("/positions", { token }), env);
    expect((await res.json()).positions).toHaveLength(4);
  });

  it("a single state filters exactly like before (?state=open)", async () => {
    const token = await mintToken(env, "owner");
    env.POSITIONS_DB._seedPosition({ ticker: "AAPL", state: "open" });
    env.POSITIONS_DB._seedPosition({ ticker: "MSFT", state: "closed" });
    const res = await handleRequest(req("/positions?state=open", { token }), env);
    const { positions } = await res.json();
    expect(positions).toHaveLength(1);
    expect(positions[0].ticker).toBe("AAPL");
  });

  it("comma-separated states return the union, excluding closed", async () => {
    const token = await mintToken(env, "owner");
    env.POSITIONS_DB._seedPosition({ ticker: "AAPL", state: "open" });
    env.POSITIONS_DB._seedPosition({ ticker: "MSFT", state: "managing" });
    env.POSITIONS_DB._seedPosition({ ticker: "TSLA", state: "closing" });
    env.POSITIONS_DB._seedPosition({ ticker: "NVDA", state: "closed" });
    const res = await handleRequest(req("/positions?state=open,managing,closing", { token }), env);
    const tickers = (await res.json()).positions.map((p) => p.ticker).sort();
    expect(tickers).toEqual(["AAPL", "MSFT", "TSLA"]);
  });

  it("repeated ?state= params are equivalent to comma-separated", async () => {
    const token = await mintToken(env, "owner");
    env.POSITIONS_DB._seedPosition({ ticker: "AAPL", state: "open" });
    env.POSITIONS_DB._seedPosition({ ticker: "MSFT", state: "managing" });
    const res = await handleRequest(req("/positions?state=open&state=managing", { token }), env);
    const tickers = (await res.json()).positions.map((p) => p.ticker).sort();
    expect(tickers).toEqual(["AAPL", "MSFT"]);
  });

  it("dedupes repeated/comma-duplicated values", async () => {
    const token = await mintToken(env, "owner");
    env.POSITIONS_DB._seedPosition({ ticker: "AAPL", state: "open" });
    const res = await handleRequest(req("/positions?state=open,open&state=open", { token }), env);
    expect((await res.json()).positions).toHaveLength(1);
  });

  it("an unknown state value is a 400, not an empty result", async () => {
    const token = await mintToken(env, "owner");
    env.POSITIONS_DB._seedPosition({ ticker: "AAPL", state: "open" });
    const res = await handleRequest(req("/positions?state=bogus", { token }), env);
    expect(res.status).toBe(400);
    const badMixed = await handleRequest(req("/positions?state=open,bogus", { token }), env);
    expect(badMixed.status).toBe(400);
  });

  it("multi-state filtering still respects the user_id tenant boundary", async () => {
    const tokenOwner = await mintToken(env, "owner");
    const tokenOther = await mintToken(env, "someone_else");
    env.POSITIONS_DB._seedPosition({ user_id: "owner", ticker: "AAPL", state: "open" });
    env.POSITIONS_DB._seedPosition({ user_id: "someone_else", ticker: "MSFT", state: "open" });
    const res = await handleRequest(req("/positions?state=open,managing,closing", { token: tokenOther }), env);
    const { positions } = await res.json();
    expect(positions).toHaveLength(1);
    expect(positions[0].ticker).toBe("MSFT");
  });
});

describe("GET /positions ?closed_within_sessions= validation", () => {
  it("rejects a non-integer, zero, and a negative value with 400", async () => {
    const token = await mintToken(env, "owner");
    for (const bad of ["abc", "0", "-1", "1.5"]) {
      const res = await handleRequest(req(`/positions?closed_within_sessions=${bad}`, { token }), env);
      expect(res.status).toBe(400);
    }
  });

  it("a valid positive integer passes through (200) and bounds returned closed rows", async () => {
    const token = await mintToken(env, "owner");
    for (const d of ["2026-02-01", "2026-02-02", "2026-02-03", "2026-02-04", "2026-02-05"]) {
      env.POSITIONS_DB._seedQuote({ ticker: "AAPL", trade_date: d });
    }
    env.POSITIONS_DB._seedPosition({ ticker: "VRT", state: "closed", closed_at: "2026-02-01T18:00:00Z" }); // sessions_since_close = 4
    env.POSITIONS_DB._seedPosition({ ticker: "NVDA", state: "closed", closed_at: "2026-02-04T18:00:00Z" }); // sessions_since_close = 1
    const res = await handleRequest(req("/positions?state=closed&closed_within_sessions=2", { token }), env);
    expect(res.status).toBe(200);
    const { positions } = await res.json();
    expect(positions.map((p) => p.ticker)).toEqual(["NVDA"]);
  });

  it("absent param applies no filter (unchanged behavior)", async () => {
    const token = await mintToken(env, "owner");
    env.POSITIONS_DB._seedQuote({ ticker: "AAPL", trade_date: "2026-02-01" });
    env.POSITIONS_DB._seedPosition({ ticker: "VRT", state: "closed", closed_at: "2026-02-01T18:00:00Z" });
    const res = await handleRequest(req("/positions?state=closed", { token }), env);
    expect((await res.json()).positions).toHaveLength(1);
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

describe("WS5-7 — GET /positions latest-bar join", () => {
  it("returns the LATEST bar's fields when multiple bars exist for the ticker", async () => {
    const token = await mintToken(env, "owner");
    env.POSITIONS_DB._seedPosition({ ticker: "AAPL", state: "managing" });
    env.POSITIONS_DB._seedQuote({
      ticker: "AAPL", trade_date: "2026-08-10", close: 220, open: 218, high: 221, low: 217,
      change_pct: 1.1, volume: 900000, raw: JSON.stringify({ "Average Volume": "50M" }),
    });
    env.POSITIONS_DB._seedQuote({
      ticker: "AAPL", trade_date: "2026-08-11", close: 225, open: 221, high: 226, low: 220,
      change_pct: 2.3, volume: 950000, raw: JSON.stringify({ "Average Volume": "51M" }),
    });
    const res = await handleRequest(req("/positions", { token }), env);
    const { positions } = await res.json();
    expect(positions).toHaveLength(1);
    const p = positions[0];
    expect(p.last_bar_date).toBe("2026-08-11"); // the later of the two seeded bars
    expect(p.last_close).toBe(225);
    expect(p.last_open).toBe(221);
    expect(p.last_high).toBe(226);
    expect(p.last_low).toBe(220);
    expect(p.last_change_pct).toBe(2.3);
    expect(p.last_volume).toBe(950000);
    expect(JSON.parse(p.last_raw)["Average Volume"]).toBe("51M");
  });

  it("a position with no bar returns null last_* fields, no throw", async () => {
    const token = await mintToken(env, "owner");
    env.POSITIONS_DB._seedPosition({ ticker: "ZZZZ", state: "open" });
    const res = await handleRequest(req("/positions", { token }), env);
    expect(res.status).toBe(200);
    const { positions } = await res.json();
    expect(positions).toHaveLength(1);
    for (const f of ["last_close", "last_bar_date", "last_open", "last_high", "last_low", "last_change_pct", "last_volume", "last_raw"]) {
      expect(positions[0][f]).toBeNull();
    }
  });

  it("tenant scoping holds on the joined query; a shared ticker's bar is not a cross-tenant leak", async () => {
    const tokenOwner = await mintToken(env, "owner");
    const tokenOther = await mintToken(env, "someone_else");
    env.POSITIONS_DB._seedPosition({ user_id: "owner", ticker: "AAPL", state: "open" });
    env.POSITIONS_DB._seedQuote({ ticker: "AAPL", trade_date: "2026-08-11", close: 225 });
    const otherList = await handleRequest(req("/positions", { token: tokenOther }), env);
    expect((await otherList.json()).positions).toHaveLength(0);
    const ownerList = await handleRequest(req("/positions", { token: tokenOwner }), env);
    const { positions } = await ownerList.json();
    expect(positions).toHaveLength(1);
    expect(positions[0].last_close).toBe(225); // the public bar still joins for the row's actual owner
  });
});

describe("WS5-7 — GET /positions inline events + stop_ack_value", () => {
  it("attaches a newest-first events array capped at 8, payloads parsed", async () => {
    const token = await mintToken(env, "owner");
    const p = env.POSITIONS_DB._seedPosition({ ticker: "AAPL", state: "managing" });
    // Seed 10 stop_moved events with increasing ts so newest-first + cap-at-8 is observable.
    for (let i = 0; i < 10; i++) {
      await env.POSITIONS_DB
        .prepare(
          `INSERT INTO position_events (trade_id, user_id, ts, trade_date, event_type, payload)
           VALUES (?, ?, ?, ?, 'stop_moved', ?)`
        )
        .bind(p.trade_id, "owner", `2026-08-${String(i + 1).padStart(2, "0")}T12:00:00Z`, "2026-08-11", JSON.stringify({ to: 90 + i }))
        .run();
    }
    const res = await handleRequest(req("/positions", { token }), env);
    const { positions } = await res.json();
    expect(positions[0].events).toHaveLength(8);
    expect(positions[0].events[0].payload.to).toBe(99); // newest (i=9) first
    expect(positions[0].events[7].payload.to).toBe(92); // 8th newest (i=2)
  });

  it("zero positions skips the events query and does not throw", async () => {
    const token = await mintToken(env, "owner");
    const res = await handleRequest(req("/positions", { token }), env);
    expect(res.status).toBe(200);
    expect((await res.json()).positions).toEqual([]);
  });

  it("stop_ack_value is null when no stop_ack event exists", async () => {
    const token = await mintToken(env, "owner");
    env.POSITIONS_DB._seedPosition({ ticker: "AAPL", state: "managing", current_stop: 100 });
    const res = await handleRequest(req("/positions", { token }), env);
    const { positions } = await res.json();
    expect(positions[0].stop_ack_value).toBeNull();
  });
});

describe("WS5-7 — POST /positions/:id/ack-stop", () => {
  it("acks a managing position with current_stop set -> 200, one stop_ack event, reflected in GET /positions", async () => {
    const token = await mintToken(env, "owner");
    const p = env.POSITIONS_DB._seedPosition({ ticker: "AAPL", state: "managing", current_stop: 105 });
    const res = await handleRequest(req(`/positions/${p.trade_id}/ack-stop`, { method: "POST", token, body: {} }), env);
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.ok).toBe(true);
    expect(body.stop_ack_value).toBe(105);
    const events = env.POSITIONS_DB._events().filter((e) => e.event_type === "stop_ack");
    expect(events).toHaveLength(1);
    expect(JSON.parse(events[0].payload).value).toBe(105);

    const list = await handleRequest(req("/positions", { token }), env);
    const { positions } = await list.json();
    expect(positions[0].stop_ack_value).toBe(105);
  });

  it("idempotent: two acks at the same current_stop produce exactly ONE stop_ack event", async () => {
    const token = await mintToken(env, "owner");
    const p = env.POSITIONS_DB._seedPosition({ ticker: "AAPL", state: "managing", current_stop: 105 });
    await handleRequest(req(`/positions/${p.trade_id}/ack-stop`, { method: "POST", token, body: {} }), env);
    await handleRequest(req(`/positions/${p.trade_id}/ack-stop`, { method: "POST", token, body: {} }), env);
    const events = env.POSITIONS_DB._events().filter((e) => e.event_type === "stop_ack");
    expect(events).toHaveLength(1);
  });

  it("after the stop changes, acking again appends a NEW stop_ack event with the new value", async () => {
    const token = await mintToken(env, "owner");
    const p = env.POSITIONS_DB._seedPosition({ ticker: "AAPL", state: "managing", current_stop: 105 });
    await handleRequest(req(`/positions/${p.trade_id}/ack-stop`, { method: "POST", token, body: {} }), env);
    // Simulate the engine/owner moving the stop.
    await env.POSITIONS_DB.prepare("UPDATE positions SET current_stop = ? WHERE trade_id = ?").bind(110, p.trade_id).run();
    const res = await handleRequest(req(`/positions/${p.trade_id}/ack-stop`, { method: "POST", token, body: {} }), env);
    expect((await res.json()).stop_ack_value).toBe(110);
    const events = env.POSITIONS_DB._events().filter((e) => e.event_type === "stop_ack");
    expect(events).toHaveLength(2);

    const list = await handleRequest(req("/positions", { token }), env);
    const { positions } = await list.json();
    expect(positions[0].stop_ack_value).toBe(110); // reflects the newest
  });

  it("404s on a non-existent / other-user trade_id", async () => {
    const tokenOwner = await mintToken(env, "owner");
    const tokenOther = await mintToken(env, "someone_else");
    const ghost = await handleRequest(req(`/positions/nope/ack-stop`, { method: "POST", token: tokenOwner, body: {} }), env);
    expect(ghost.status).toBe(404);

    const p = env.POSITIONS_DB._seedPosition({ user_id: "owner", ticker: "AAPL", state: "managing", current_stop: 105 });
    const wrongUser = await handleRequest(req(`/positions/${p.trade_id}/ack-stop`, { method: "POST", token: tokenOther, body: {} }), env);
    expect(wrongUser.status).toBe(404);
  });

  it("401s without an owner bearer (below the auth gate)", async () => {
    const p = env.POSITIONS_DB._seedPosition({ ticker: "AAPL", state: "managing", current_stop: 105 });
    const res = await handleRequest(req(`/positions/${p.trade_id}/ack-stop`, { method: "POST", body: {} }), env);
    expect(res.status).toBe(401);
  });
});

describe("WS5 §8b P1 — personal watchlist routes (issue #319)", () => {
  const ingestReq = (path, { method = "GET", body } = {}) => {
    const headers = { authorization: `Bearer ${INGEST_TOKEN}` };
    if (body !== undefined) headers["content-type"] = "application/json";
    return new Request(`https://finviz-positions.workers.dev${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  };

  it("happy-path round-trip: add -> list -> patch(renew) -> delete with an owner token", async () => {
    const token = await mintToken(env, "owner");
    const add = await handleRequest(
      req("/watchlist", { method: "POST", token, body: { ticker: "nvda", level_type: "above", level_value: 200 } }),
      env
    );
    expect(add.status).toBe(201);
    const { watch } = await add.json();
    expect(watch.ticker).toBe("NVDA");
    expect(watch.sessions_remaining).toBe(10);

    const list = await handleRequest(req("/watchlist", { token }), env);
    expect(list.status).toBe(200);
    const { watchlist } = await list.json();
    expect(watchlist).toHaveLength(1);
    expect(watchlist[0].prior_high).toBeNull(); // no bar yet

    const patch = await handleRequest(req(`/watchlist/${watch.id}`, { method: "PATCH", token, body: { renew: true } }), env);
    expect(patch.status).toBe(200);
    expect((await patch.json()).ok).toBe(true);

    const del = await handleRequest(req(`/watchlist/${watch.id}`, { method: "DELETE", token }), env);
    expect(del.status).toBe(200);
    expect((await del.json()).ok).toBe(true);

    const listAfter = await handleRequest(req("/watchlist", { token }), env);
    expect((await listAfter.json()).watchlist).toHaveLength(0);
  });

  it("POST /watchlist rejects an invalid payload with 400", async () => {
    const token = await mintToken(env, "owner");
    const res = await handleRequest(req("/watchlist", { method: "POST", token, body: { ticker: "1BAD" } }), env);
    expect(res.status).toBe(400);
  });

  it("PATCH/DELETE /watchlist/:id 404 on an unowned or unknown id", async () => {
    const token = await mintToken(env, "owner");
    const patch = await handleRequest(req("/watchlist/9999", { method: "PATCH", token, body: { renew: true } }), env);
    expect(patch.status).toBe(404);
    const del = await handleRequest(req("/watchlist/9999", { method: "DELETE", token }), env);
    expect(del.status).toBe(404);
  });

  it("service token: GET /watchlist-tickers + POST /watchlist/tick", async () => {
    const token = await mintToken(env, "owner");
    await handleRequest(req("/watchlist", { method: "POST", token, body: { ticker: "AAPL", level_type: "above", level_value: 200 } }), env);

    const refs = await handleRequest(ingestReq("/watchlist-tickers"), env);
    expect(refs.status).toBe(200);
    const { tickers } = await refs.json();
    expect(tickers).toHaveLength(1);
    expect(tickers[0].ticker).toBe("AAPL");
    expect(tickers[0]).not.toHaveProperty("level_value");

    const tick = await handleRequest(ingestReq("/watchlist/tick", { method: "POST", body: { date: "2026-08-13" } }), env);
    expect(tick.status).toBe(200);
    const tickBody = await tick.json();
    expect(tickBody.ticked).toBe(true);
    expect(tickBody.decremented).toBe(1);
  });

  // ── Cross-auth isolation ──────────────────────────────────────────────────────────────────────
  it("owner token is REJECTED on the service watchlist routes", async () => {
    const ownerToken = await mintToken(env, "owner");
    const withOwner = (path, method = "GET", body) =>
      new Request(`https://x${path}`, {
        method,
        headers: { authorization: `Bearer ${ownerToken}`, ...(body !== undefined ? { "content-type": "application/json" } : {}) },
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
    expect((await handleRequest(withOwner("/watchlist-tickers"), env)).status).toBe(401);
    expect((await handleRequest(withOwner("/watchlist/tick", "POST", {}), env)).status).toBe(401);
  });

  it("service token is REJECTED on all owner watchlist routes", async () => {
    expect((await handleRequest(ingestReq("/watchlist"), env)).status).toBe(401);
    expect((await handleRequest(ingestReq("/watchlist", { method: "POST", body: { ticker: "AAPL" } }), env)).status).toBe(401);
    expect((await handleRequest(ingestReq("/watchlist/1", { method: "PATCH", body: { renew: true } }), env)).status).toBe(401);
    expect((await handleRequest(ingestReq("/watchlist/1", { method: "DELETE" }), env)).status).toBe(401);
  });
});
