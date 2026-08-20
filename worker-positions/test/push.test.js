import { describe, it, expect, beforeEach } from "vitest";
import { makeD1 } from "./helpers/d1.js";
import { handleRequest } from "../src/index.js";
import { mintToken } from "../src/auth.js";
import { sweep } from "../src/sweep.js";
import {
  buildVapidJwt,
  base64UrlToBytes,
  subscribePush,
  unsubscribePush,
  listSubscriptionsForUser,
  dispatchExitPushes,
} from "../src/push.js";

// Lead-generated, round-trip-verified test keypair (from the locked spec).
const TEST_VAPID = {
  publicKey: "BIlHEo6AR0obzj6aFUPsrRxCd_U473Q4EoCzaXPwPqLIH583hyFwiMXH1k8yBElGNwowiR8DKQ-nJ39vETP67yc",
  privateKey: "Wdvqewu8a05zRGq-0OQORLnyyztWd7Fx5TBvJc90yJk",
  contactEmail: "salmonbaby8@gmail.com",
};

function decodeJwtPart(b64url) {
  const bytes = base64UrlToBytes(b64url);
  return JSON.parse(new TextDecoder().decode(bytes));
}

let db;
beforeEach(() => {
  db = makeD1();
});

// ── 1. buildVapidJwt ──────────────────────────────────────────────────────────────────────────
describe("buildVapidJwt", () => {
  it("produces a 3-part JWT with the expected header/payload shape", async () => {
    const now = new Date("2026-08-20T12:00:00Z");
    const jwt = await buildVapidJwt("https://fcm.googleapis.com/fcm/send/abc123", TEST_VAPID.privateKey, TEST_VAPID.publicKey, TEST_VAPID.contactEmail, now);
    const parts = jwt.split(".");
    expect(parts).toHaveLength(3);

    const header = decodeJwtPart(parts[0]);
    expect(header).toEqual({ typ: "JWT", alg: "ES256" });

    const payload = decodeJwtPart(parts[1]);
    expect(payload.aud).toBe("https://fcm.googleapis.com");
    expect(payload.sub).toBe(`mailto:${TEST_VAPID.contactEmail}`);
    const expectedExp = Math.floor(now.getTime() / 1000) + 12 * 3600;
    expect(payload.exp).toBe(expectedExp);
  });
});

// ── 2. store fns ──────────────────────────────────────────────────────────────────────────────
describe("push subscription store", () => {
  it("subscribePush inserts; re-subscribe with same (user_id, endpoint) upserts keys, one row", async () => {
    await subscribePush(db, "owner", { endpoint: "https://push.example/a", p256dh: "p1", auth: "a1" });
    let rows = await listSubscriptionsForUser(db, "owner");
    expect(rows).toHaveLength(1);
    expect(rows[0].p256dh).toBe("p1");

    await subscribePush(db, "owner", { endpoint: "https://push.example/a", p256dh: "p2", auth: "a2" });
    rows = await listSubscriptionsForUser(db, "owner");
    expect(rows).toHaveLength(1);
    expect(rows[0].p256dh).toBe("p2");
    expect(rows[0].auth).toBe("a2");
  });

  it("unsubscribePush deletes; listSubscriptionsForUser scopes by user", async () => {
    await subscribePush(db, "owner", { endpoint: "https://push.example/a", p256dh: "p1", auth: "a1" });
    await subscribePush(db, "other-user", { endpoint: "https://push.example/b", p256dh: "p2", auth: "a2" });

    expect(await listSubscriptionsForUser(db, "owner")).toHaveLength(1);
    expect(await listSubscriptionsForUser(db, "other-user")).toHaveLength(1);

    await unsubscribePush(db, "owner", "https://push.example/a");
    expect(await listSubscriptionsForUser(db, "owner")).toHaveLength(0);
    expect(await listSubscriptionsForUser(db, "other-user")).toHaveLength(1);
  });
});

// ── 3-7. dispatchExitPushes ───────────────────────────────────────────────────────────────────
describe("dispatchExitPushes", () => {
  it("calls sendPushFn once per subscription and writes a push_sent event", async () => {
    await subscribePush(db, "owner", { endpoint: "https://push.example/a", p256dh: "p1", auth: "a1" });
    await subscribePush(db, "owner", { endpoint: "https://push.example/b", p256dh: "p2", auth: "a2" });
    let calls = 0;
    const mock = async () => {
      calls++;
      return { ok: true, status: 201, gone: false };
    };

    const result = await dispatchExitPushes(db, {
      intents: [{ user_id: "owner", trade_id: "t1", ticker: "AAPL" }],
      vapid: TEST_VAPID,
      sendPushFn: mock,
      now_iso: "2026-08-20T21:05:00Z",
      trade_date: "2026-08-20",
    });

    expect(calls).toBe(2);
    expect(result.sent).toBe(2);
    const events = db._events();
    expect(events.filter((e) => e.event_type === "push_sent")).toHaveLength(1);
    expect(events[0].trade_id).toBe("t1");
    expect(events[0].trade_date).toBe("2026-08-20");
  });

  it("idempotency: a second dispatch for the same (trade_id, trade_date) does not call sendPushFn again", async () => {
    await subscribePush(db, "owner", { endpoint: "https://push.example/a", p256dh: "p1", auth: "a1" });
    let calls = 0;
    const mock = async () => {
      calls++;
      return { ok: true, status: 201, gone: false };
    };
    const intents = [{ user_id: "owner", trade_id: "t1", ticker: "AAPL" }];

    await dispatchExitPushes(db, { intents, vapid: TEST_VAPID, sendPushFn: mock, now_iso: "2026-08-20T21:05:00Z", trade_date: "2026-08-20" });
    expect(calls).toBe(1);

    const result2 = await dispatchExitPushes(db, { intents, vapid: TEST_VAPID, sendPushFn: mock, now_iso: "2026-08-20T21:06:00Z", trade_date: "2026-08-20" });
    expect(calls).toBe(1); // not called again
    expect(result2.skipped).toBe(1);
    expect(result2.sent).toBe(0);
  });

  it("410 prune: a gone response deletes the subscription row and writes no push_sent event", async () => {
    const sub = await subscribePush(db, "owner", { endpoint: "https://push.example/a", p256dh: "p1", auth: "a1" });
    const mock = async () => ({ ok: false, status: 410, gone: true });

    const result = await dispatchExitPushes(db, {
      intents: [{ user_id: "owner", trade_id: "t1", ticker: "AAPL" }],
      vapid: TEST_VAPID,
      sendPushFn: mock,
      now_iso: "2026-08-20T21:05:00Z",
      trade_date: "2026-08-20",
    });

    expect(result.pruned).toBe(1);
    expect(result.sent).toBe(0);
    expect(await listSubscriptionsForUser(db, "owner")).toHaveLength(0);
    expect(db._events().filter((e) => e.event_type === "push_sent")).toHaveLength(0);
  });

  it("no subscriptions: no throw, no push_sent marker written", async () => {
    const result = await dispatchExitPushes(db, {
      intents: [{ user_id: "owner", trade_id: "t1", ticker: "AAPL" }],
      vapid: TEST_VAPID,
      sendPushFn: async () => ({ ok: true, status: 201, gone: false }),
      now_iso: "2026-08-20T21:05:00Z",
      trade_date: "2026-08-20",
    });
    expect(result.sent).toBe(0);
    expect(db._events()).toHaveLength(0);
  });

  it("best-effort: a throwing sendPushFn does not make dispatchExitPushes throw", async () => {
    await subscribePush(db, "owner", { endpoint: "https://push.example/a", p256dh: "p1", auth: "a1" });
    const throwing = async () => {
      throw new Error("network down");
    };
    await expect(
      dispatchExitPushes(db, {
        intents: [{ user_id: "owner", trade_id: "t1", ticker: "AAPL" }],
        vapid: TEST_VAPID,
        sendPushFn: throwing,
        now_iso: "2026-08-20T21:05:00Z",
        trade_date: "2026-08-20",
      })
    ).resolves.toEqual({ sent: 0, pruned: 0, skipped: 0 });
  });
});

// ── 8-9. sweep integration ────────────────────────────────────────────────────────────────────
// Reuses the exit fixture pattern from test/sweep.test.js: a position whose bar sequence trips a
// stop_hit, transitioning it into `closing` on the 17:30 sweep.
function pctForLevel(close, level) {
  return `${((close / level - 1) * 100).toFixed(6)}%`;
}
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
function seedExitPos(db, overrides = {}) {
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
function seedStopHitBars(db) {
  db._seedQuote(quoteRow({ trade_date: "2026-08-02", close: 101, sma20: 95, sma50: 80, low: 99 }));
  db._seedQuote(quoteRow({ trade_date: "2026-08-03", close: 103, sma20: 97, sma50: 80, low: 101, prev_close: 101 }));
  // bar3: low 95 <= current_stop 97, open 98 >= 97 (not a gap) -> stop_hit at 97
  db._seedQuote(quoteRow({ trade_date: "2026-08-04", close: 98, sma20: 97, sma50: 80, low: 95, open: 98, prev_close: 103 }));
}

describe("sweep — Tier-1 push dispatch", () => {
  it("fires one push on a fresh closing transition, pushed:1, push_sent event exists; a re-sweep with same trade_date does not re-dispatch", async () => {
    seedExitPos(db, { state: "managing" });
    seedStopHitBars(db);
    await subscribePush(db, "owner", { endpoint: "https://push.example/a", p256dh: "p1", auth: "a1" });

    let calls = 0;
    const mock = async () => {
      calls++;
      return { ok: true, status: 201, gone: false };
    };
    const now = new Date("2026-08-04T21:35:00Z"); // ET trade_date 2026-08-04

    const result = await sweep(db, { now, push: { vapid: TEST_VAPID, sendPushFn: mock } });
    expect(result.pushed).toBe(1);
    expect(calls).toBe(1);
    expect(db._positions()[0].state).toBe("closing");
    expect(db._events().filter((e) => e.event_type === "push_sent")).toHaveLength(1);

    // Same-day re-dispatch: no new bars, so the advance loop no-ops and produces no new intent
    // (last_advanced_date already == the exit bar). Even so, dispatchExitPushes' own idempotency
    // guard is what actually protects a re-fire, exercised directly above; here we confirm sweep()
    // as a whole does not call the mock again for this scenario.
    const result2 = await sweep(db, { now, push: { vapid: TEST_VAPID, sendPushFn: mock } });
    expect(calls).toBe(1);
    expect(result2.pushed).toBe(0);
  });

  it("dry_run dispatches nothing: pushed:0, mock not called", async () => {
    seedExitPos(db, { state: "managing" });
    seedStopHitBars(db);
    await subscribePush(db, "owner", { endpoint: "https://push.example/a", p256dh: "p1", auth: "a1" });

    let calls = 0;
    const mock = async () => {
      calls++;
      return { ok: true, status: 201, gone: false };
    };
    const now = new Date("2026-08-04T21:35:00Z");

    const result = await sweep(db, { now, dry_run: true, push: { vapid: TEST_VAPID, sendPushFn: mock } });
    expect(result.pushed).toBe(0);
    expect(calls).toBe(0);
    // dry_run never persists at all, so state is unchanged too.
    expect(db._positions()[0].state).toBe("managing");
  });
});

// ── route tests ───────────────────────────────────────────────────────────────────────────────
const SECRET = "test-secret-abc123-abc123-abc123";
const PASSPHRASE = "correct horse";
const INGEST_TOKEN = "ingest-token-super-secret-0123456789";

function makeEnv() {
  return {
    POSITIONS_SESSION_SECRET: SECRET,
    POSITIONS_AUTH_PASSPHRASE: PASSPHRASE,
    POSITIONS_INGEST_TOKEN: INGEST_TOKEN,
    ALLOWED_ORIGINS: "https://clarencelam2000.github.io,http://localhost:8000",
    POSITIONS_DB: makeD1(),
  };
}

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

describe("routes: POST /push/subscribe, /push/unsubscribe", () => {
  let env;
  beforeEach(() => {
    env = makeEnv();
  });

  it("subscribe happy path: 200, row present", async () => {
    const token = await mintToken(env, "owner");
    const res = await handleRequest(
      req("/push/subscribe", { method: "POST", token, body: { endpoint: "https://push.example/a", keys: { p256dh: "p1", auth: "a1" } } }),
      env
    );
    expect(res.status).toBe(200);
    expect((await res.json()).ok).toBe(true);
    const rows = await listSubscriptionsForUser(env.POSITIONS_DB, "owner");
    expect(rows).toHaveLength(1);
    expect(rows[0].endpoint).toBe("https://push.example/a");
  });

  it("subscribe bad shape: 400", async () => {
    const token = await mintToken(env, "owner");
    const res = await handleRequest(req("/push/subscribe", { method: "POST", token, body: { endpoint: "https://push.example/a" } }), env);
    expect(res.status).toBe(400);
  });

  it("subscribe unauthorized without bearer: 401", async () => {
    const res = await handleRequest(
      req("/push/subscribe", { method: "POST", body: { endpoint: "https://push.example/a", keys: { p256dh: "p1", auth: "a1" } } }),
      env
    );
    expect(res.status).toBe(401);
  });

  it("unsubscribe: 200, row gone", async () => {
    const token = await mintToken(env, "owner");
    await subscribePush(env.POSITIONS_DB, "owner", { endpoint: "https://push.example/a", p256dh: "p1", auth: "a1" });
    const res = await handleRequest(req("/push/unsubscribe", { method: "POST", token, body: { endpoint: "https://push.example/a" } }), env);
    expect(res.status).toBe(200);
    expect(await listSubscriptionsForUser(env.POSITIONS_DB, "owner")).toHaveLength(0);
  });
});
