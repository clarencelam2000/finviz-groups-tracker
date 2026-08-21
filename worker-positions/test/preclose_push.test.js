// WS5-8 PR-2 (issue #349) — pre-close act-now push dispatch tests.
//
// New file (not appended to push.test.js) since this is a sibling dispatcher with its own seed
// shape (preclose_advisory rows, not sweep intents) — kept separate to avoid bloating the existing
// file further.

import { describe, it, expect, beforeEach } from "vitest";
import { makeD1 } from "./helpers/d1.js";
import { subscribePush, listSubscriptionsForUser, dispatchPreClosePushes, buildPreClosePushPayload } from "../src/push.js";

const TEST_VAPID = {
  publicKey: "BIlHEo6AR0obzj6aFUPsrRxCd_U473Q4EoCzaXPwPqLIH583hyFwiMXH1k8yBElGNwowiR8DKQ-nJ39vETP67yc",
  privateKey: "Wdvqewu8a05zRGq-0OQORLnyyztWd7Fx5TBvJc90yJk",
  contactEmail: "salmonbaby8@gmail.com",
};

let db;
beforeEach(() => {
  db = makeD1();
});

// preclose_advisory has no _seed helper in d1.js (test/helpers/d1.js only has _seedPosition/
// _seedQuote/_seedWatchlist) — insert directly, mirroring how those helpers build rows.
function seedAdvisory(db, { user_id = "owner", trade_date = "2026-08-21", items = [] } = {}) {
  return db
    .prepare(
      `INSERT INTO preclose_advisory (user_id, trade_date, ran_at, n_checked, n_flagged, items) VALUES (?, ?, ?, ?, ?, ?)`
    )
    .bind(user_id, trade_date, `${trade_date}T19:40:00Z`, items.length, items.length, JSON.stringify(items))
    .run();
}

describe("buildPreClosePushPayload", () => {
  it("act copy with a known reason and a price", () => {
    const payload = JSON.parse(buildPreClosePushPayload({ ticker: "NVT", signal: "stop_hit", price: 42.1 }));
    expect(payload.title).toBe("🚨 NVT — act now before the close");
    expect(payload.body).toBe("Stop hit at 42.1. Place your broker order before the bell.");
    expect(payload.ticker).toBe("NVT");
    expect(payload.tag).toBe("finviz-preclose");
    expect(payload.url).toBe("#positions");
  });

  it("known reason without a price omits the ' at X' clause", () => {
    const payload = JSON.parse(buildPreClosePushPayload({ ticker: "NVT", signal: "gap_down_below_stop" }));
    expect(payload.body).toBe("Gap-down through stop. Place your broker order before the bell.");
  });

  it("falls back to a generic body for an unknown/missing reason", () => {
    const payload = JSON.parse(buildPreClosePushPayload({ ticker: "OUST" }));
    expect(payload.body).toBe("A position hit an exit signal. Place your order before the bell.");
  });
});

describe("dispatchPreClosePushes", () => {
  it("sends for an act item, does NOT send for a heads_up item", async () => {
    await subscribePush(db, "owner", { endpoint: "https://push.example/a", p256dh: "p1", auth: "a1" });
    seedAdvisory(db, {
      trade_date: "2026-08-21",
      items: [
        { trade_id: "t-act", ticker: "NVT", category: "exit", severity: "act", signal: "stop_hit", price: 42.1, ref_level: 40 },
        { trade_id: "t-heads-up", ticker: "AAPL", category: "exit", severity: "heads_up", signal: "close_below_50ma", price: 190, ref_level: 191 },
      ],
    });

    const receivedTickers = [];
    const mock = async (sub, vapid, payload) => {
      receivedTickers.push(JSON.parse(payload).ticker);
      return { ok: true, status: 201, gone: false };
    };

    const result = await dispatchPreClosePushes(db, {
      trade_date: "2026-08-21",
      vapid: TEST_VAPID,
      sendPushFn: mock,
      now_iso: "2026-08-21T19:41:00Z",
    });

    expect(result.sent).toBe(1);
    expect(receivedTickers).toEqual(["NVT"]);
    const events = db._events();
    expect(events.filter((e) => e.event_type === "preclose_push_sent")).toHaveLength(1);
    expect(events[0].trade_id).toBe("t-act");
  });

  it("idempotency: a second dispatch for the same (trade_id, trade_date) does not re-send", async () => {
    await subscribePush(db, "owner", { endpoint: "https://push.example/a", p256dh: "p1", auth: "a1" });
    seedAdvisory(db, {
      trade_date: "2026-08-21",
      items: [{ trade_id: "t-act", ticker: "NVT", category: "exit", severity: "act", signal: "stop_hit", price: 42.1, ref_level: 40 }],
    });
    let calls = 0;
    const mock = async () => {
      calls++;
      return { ok: true, status: 201, gone: false };
    };

    await dispatchPreClosePushes(db, { trade_date: "2026-08-21", vapid: TEST_VAPID, sendPushFn: mock, now_iso: "2026-08-21T19:41:00Z" });
    expect(calls).toBe(1);

    const result2 = await dispatchPreClosePushes(db, { trade_date: "2026-08-21", vapid: TEST_VAPID, sendPushFn: mock, now_iso: "2026-08-21T19:42:00Z" });
    expect(calls).toBe(1);
    expect(result2.skipped).toBe(1);
    expect(result2.sent).toBe(0);
  });

  it("no subscriptions: no send, no marker written (retry semantics)", async () => {
    seedAdvisory(db, {
      trade_date: "2026-08-21",
      items: [{ trade_id: "t-act", ticker: "NVT", category: "exit", severity: "act", signal: "stop_hit", price: 42.1, ref_level: 40 }],
    });

    const result = await dispatchPreClosePushes(db, {
      trade_date: "2026-08-21",
      vapid: TEST_VAPID,
      sendPushFn: async () => ({ ok: true, status: 201, gone: false }),
      now_iso: "2026-08-21T19:41:00Z",
    });

    expect(result.sent).toBe(0);
    expect(db._events()).toHaveLength(0);

    // Retries once a device subscribes.
    await subscribePush(db, "owner", { endpoint: "https://push.example/a", p256dh: "p1", auth: "a1" });
    let calls = 0;
    const result2 = await dispatchPreClosePushes(db, {
      trade_date: "2026-08-21",
      vapid: TEST_VAPID,
      sendPushFn: async () => {
        calls++;
        return { ok: true, status: 201, gone: false };
      },
      now_iso: "2026-08-21T19:45:00Z",
    });
    expect(calls).toBe(1);
    expect(result2.sent).toBe(1);
  });

  it("never throws: a throwing sendPushFn on one item does not abort the rest", async () => {
    await subscribePush(db, "owner", { endpoint: "https://push.example/a", p256dh: "p1", auth: "a1" });
    seedAdvisory(db, {
      trade_date: "2026-08-21",
      items: [
        { trade_id: "t-fail", ticker: "FAIL", category: "exit", severity: "act", signal: "stop_hit", price: 10, ref_level: 9 },
        { trade_id: "t-ok", ticker: "OK", category: "exit", severity: "act", signal: "stop_hit", price: 20, ref_level: 19 },
      ],
    });

    const mock = async (sub, vapid, payload) => {
      if (JSON.parse(payload).ticker === "FAIL") throw new Error("network down");
      return { ok: true, status: 201, gone: false };
    };

    let result;
    await expect(
      (async () => {
        result = await dispatchPreClosePushes(db, { trade_date: "2026-08-21", vapid: TEST_VAPID, sendPushFn: mock, now_iso: "2026-08-21T19:41:00Z" });
      })()
    ).resolves.toBeUndefined();

    expect(result.sent).toBe(1); // only OK's send succeeded
    const events = db._events().filter((e) => e.event_type === "preclose_push_sent");
    expect(events).toHaveLength(1);
    expect(events[0].trade_id).toBe("t-ok");
  });

  it("no vapid config: returns zeroed counts, no D1 access", async () => {
    seedAdvisory(db, {
      trade_date: "2026-08-21",
      items: [{ trade_id: "t-act", ticker: "NVT", category: "exit", severity: "act", signal: "stop_hit", price: 42.1, ref_level: 40 }],
    });
    const result = await dispatchPreClosePushes(db, { trade_date: "2026-08-21", vapid: null, now_iso: "2026-08-21T19:41:00Z" });
    expect(result).toEqual({ sent: 0, pruned: 0, skipped: 0 });
  });

  it("410 prune: a gone response deletes the subscription row and writes no marker", async () => {
    await subscribePush(db, "owner", { endpoint: "https://push.example/a", p256dh: "p1", auth: "a1" });
    seedAdvisory(db, {
      trade_date: "2026-08-21",
      items: [{ trade_id: "t-act", ticker: "NVT", category: "exit", severity: "act", signal: "stop_hit", price: 42.1, ref_level: 40 }],
    });
    const mock = async () => ({ ok: false, status: 410, gone: true });

    const result = await dispatchPreClosePushes(db, { trade_date: "2026-08-21", vapid: TEST_VAPID, sendPushFn: mock, now_iso: "2026-08-21T19:41:00Z" });

    expect(result.pruned).toBe(1);
    expect(result.sent).toBe(0);
    expect(await listSubscriptionsForUser(db, "owner")).toHaveLength(0);
    expect(db._events().filter((e) => e.event_type === "preclose_push_sent")).toHaveLength(0);
  });

  it("distinct event_type from Tier-1: a pre-existing push_sent marker does not suppress the preclose push", async () => {
    await subscribePush(db, "owner", { endpoint: "https://push.example/a", p256dh: "p1", auth: "a1" });
    seedAdvisory(db, {
      trade_date: "2026-08-21",
      items: [{ trade_id: "t-act", ticker: "NVT", category: "exit", severity: "act", signal: "stop_hit", price: 42.1, ref_level: 40 }],
    });
    await db
      .prepare(`INSERT INTO position_events (trade_id, user_id, ts, trade_date, event_type, payload) VALUES (?, ?, ?, ?, ?, ?)`)
      .bind("t-act", "owner", "2026-08-21T21:35:00Z", "2026-08-21", "push_sent", "{}")
      .run();

    let calls = 0;
    const result = await dispatchPreClosePushes(db, {
      trade_date: "2026-08-21",
      vapid: TEST_VAPID,
      sendPushFn: async () => {
        calls++;
        return { ok: true, status: 201, gone: false };
      },
      now_iso: "2026-08-21T19:41:00Z",
    });
    expect(calls).toBe(1);
    expect(result.sent).toBe(1);
  });
});
