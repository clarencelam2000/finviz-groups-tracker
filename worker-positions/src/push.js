// WS5-4b Web Push (Tier-1 exit-signal push, backend half). Design: the epic issue (#264) + the lead's
// locked spec for this PR. Ported from the sibling `distil` worker's proven `src/cron/webpush.ts` /
// `src/store/push.ts` (Phase 3 plan §6-D3 there) — see the header comment on buildVapidJwt/sendPush
// below for why it's a small vendored implementation, not a Node-shimmed `web-push` dependency.
//
// SCOPE, v1 (PR-1, issue #348 core): Tier-1 push, now WITH an RFC 8291 `aes128gcm` payload — the
// 17:30 sweep's first transition of a position to `closing` sends a ticker-named notification
// ("🚨 NVT — stop hit. Confirm your fill.") instead of a generic one. RFC 8292 VAPID auth (JWT +
// `Authorization: vapid ...`) is unchanged. Tier-2 decaying-cadence reminders and earnings-approach
// push are still OUT OF SCOPE for this file — those are a separate later PR; only the Tier-1
// exit-signal payload is built here.
//
// Push is a NUDGE, never load-bearing: dispatchExitPushes() below must never throw, and every call
// site in sweep.js wraps it in its own try/catch besides. A push failure must never fail the sweep,
// block a D1 write, or surface to the caller as an error.

import { isoUtc } from "./time.js";

// ── VAPID JWT signer + send (ported VERBATIM from distil/src/cron/webpush.ts) ───────────────────

export function base64UrlToBytes(b64url) {
  const b64 = b64url.replace(/-/g, "+").replace(/_/g, "/");
  const padded = b64 + "===".slice((b64.length + 3) % 4);
  const bin = atob(padded);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

export function bytesToBase64Url(bytes) {
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function textToBase64Url(text) {
  return bytesToBase64Url(new TextEncoder().encode(text));
}

/** Import the VAPID keypair (raw base64url, the `web-push generate-vapid-keys` / `npx web-push`
 * format already used by the deployed secrets) as a Web Crypto ECDSA P-256 signing key. Only the
 * private key is needed for signing; `k=` in the Authorization header carries the public key raw,
 * unparsed. */
async function importVapidPrivateKey(publicKeyB64, privateKeyB64) {
  const rawPublic = base64UrlToBytes(publicKeyB64); // 65 bytes: 0x04 || x(32) || y(32)
  const x = rawPublic.slice(1, 33);
  const y = rawPublic.slice(33, 65);
  const d = base64UrlToBytes(privateKeyB64); // 32-byte scalar
  const jwk = { kty: "EC", crv: "P-256", x: bytesToBase64Url(x), y: bytesToBase64Url(y), d: bytesToBase64Url(d), ext: true };
  return crypto.subtle.importKey("jwk", jwk, { name: "ECDSA", namedCurve: "P-256" }, false, ["sign"]);
}

/**
 * A VAPID JWT (RFC 8292): `{ aud, exp, sub }`, ES256-signed over Web Crypto. Web Crypto's ECDSA
 * output is already the raw `r || s` JOSE signature format (unlike Node's default DER encoding), so
 * no re-encoding step is needed.
 */
export async function buildVapidJwt(endpoint, privateKeyB64, publicKeyB64, contactEmail, now = new Date()) {
  const aud = new URL(endpoint).origin;
  const exp = Math.floor(now.getTime() / 1000) + 12 * 3600; // 12h — comfortably under the 24h RFC 8292 cap
  const header = { typ: "JWT", alg: "ES256" };
  const payload = { aud, exp, sub: `mailto:${contactEmail}` };
  const signingInput = `${textToBase64Url(JSON.stringify(header))}.${textToBase64Url(JSON.stringify(payload))}`;

  const privateKey = await importVapidPrivateKey(publicKeyB64, privateKeyB64);
  const sig = await crypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, privateKey, new TextEncoder().encode(signingInput));
  return `${signingInput}.${bytesToBase64Url(new Uint8Array(sig))}`;
}

// ── RFC 8291 aes128gcm payload encryption ────────────────────────────────────────────────────────
// Encrypts a UTF-8 payload string to one subscription's {p256dh, auth} keys. Single-record only (the
// push payload is always small — a JSON notification body, nowhere near the 4096-byte record size),
// so RFC 8188's multi-record chaining is out of scope; the record-size field is still emitted (fixed
// at RS below) because the header format requires it regardless of record count.
const RS = 4096; // RFC 8188 §2.1 record size — fixed; our single-record payload is always << 4096B.

async function importP256Raw(rawBytes, usages, extractable = false) {
  return crypto.subtle.importKey("raw", rawBytes, { name: "ECDH", namedCurve: "P-256" }, extractable, usages);
}

async function exportRawPublic(key) {
  return new Uint8Array(await crypto.subtle.exportKey("raw", key));
}

function concatBytes(...arrs) {
  const len = arrs.reduce((n, a) => n + a.length, 0);
  const out = new Uint8Array(len);
  let off = 0;
  for (const a of arrs) {
    out.set(a, off);
    off += a.length;
  }
  return out;
}

/** HKDF-SHA256 (RFC 5869) via Web Crypto, returning raw derived bytes (not an unextractable key) so
 * callers can feed the output straight into HKDF-Extract for the next step or into AES-GCM. */
async function hkdf(saltBytes, ikmBytes, infoBytes, lengthBytes) {
  const ikmKey = await crypto.subtle.importKey("raw", ikmBytes, "HKDF", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits(
    { name: "HKDF", hash: "SHA-256", salt: saltBytes, info: infoBytes },
    ikmKey,
    lengthBytes * 8
  );
  return new Uint8Array(bits);
}

/**
 * RFC 8291 §3.4 encryption of `payloadText` to one subscription's raw ECDH public key (`p256dhB64`,
 * base64url 65-byte 0x04||x||y) and auth secret (`authB64`, base64url 16 bytes). Returns the full
 * aes128gcm request body: RFC 8188 §2.1 header (salt(16) || rs(4, BE uint32) || idlen(1)=65 ||
 * keyid(65)) followed by ciphertext+tag. Exported so tests can call it directly (A4).
 */
export async function encryptAes128Gcm(payloadText, p256dhB64, authB64) {
  const uaPublic = base64UrlToBytes(p256dhB64); // client's raw EC public key, 65B
  const authSecret = base64UrlToBytes(authB64); // 16B

  // Ephemeral server P-256 keypair — a fresh one per message, per RFC 8291.
  const serverKeyPair = await crypto.subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, true, ["deriveBits"]);
  const asPublic = await exportRawPublic(serverKeyPair.publicKey); // 65B

  // ECDH shared secret between our ephemeral key and the client's public key.
  const uaPublicKey = await importP256Raw(uaPublic, []);
  const ecdhSecretBits = await crypto.subtle.deriveBits({ name: "ECDH", public: uaPublicKey }, serverKeyPair.privateKey, 256);
  const ecdhSecret = new Uint8Array(ecdhSecretBits);

  // PRK_key = HKDF-Extract-and-Expand(salt=auth_secret, ikm=ecdh_secret,
  //   info="WebPush: info\0" || ua_public || as_public, L=32)  — RFC 8291 §3.4.
  const webpushInfo = concatBytes(new TextEncoder().encode("WebPush: info\0"), uaPublic, asPublic);
  const prkKey = await hkdf(authSecret, ecdhSecret, webpushInfo, 32);

  // Per-message random salt for the content-encoding step (RFC 8188 §2.1).
  const salt = crypto.getRandomValues(new Uint8Array(16));

  // CEK = HKDF(salt, PRK_key, info="Content-Encoding: aes128gcm\0", L=16)
  const cek = await hkdf(salt, prkKey, new TextEncoder().encode("Content-Encoding: aes128gcm\0"), 16);
  // NONCE = HKDF(salt, PRK_key, info="Content-Encoding: nonce\0", L=12)
  const nonce = await hkdf(salt, prkKey, new TextEncoder().encode("Content-Encoding: nonce\0"), 12);

  // Record padding: plaintext || 0x02 (last-record delimiter, RFC 8188 §2) || zero padding. No extra
  // padding beyond the delimiter — our payloads are small and padding-for-size-obscurity isn't a goal
  // here (the ticker/reason is visible in the notification either way).
  const plaintext = new TextEncoder().encode(payloadText);
  const padded = concatBytes(plaintext, new Uint8Array([0x02]));

  const aesKey = await crypto.subtle.importKey("raw", cek, { name: "AES-GCM" }, false, ["encrypt"]);
  const ciphertext = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv: nonce, tagLength: 128 }, aesKey, padded));

  // RFC 8188 §2.1 header: salt(16) || rs(4, big-endian uint32) || idlen(1) || keyid(idlen).
  const header = new Uint8Array(16 + 4 + 1 + asPublic.length);
  header.set(salt, 0);
  new DataView(header.buffer).setUint32(16, RS, false);
  header[20] = asPublic.length; // 65
  header.set(asPublic, 21);

  return { body: concatBytes(header, ciphertext), salt, asPublic };
}

/** Send a VAPID-authenticated push to one subscription. `sub = {endpoint, p256dh, auth}`.
 * `payload === null` (default) sends today's exact data-less request (Content-Length:0, no
 * Content-Encoding) — unchanged from before RFC 8291 support. `payload` as a string encrypts it
 * per RFC 8291 against `sub`'s keys and sends it as the aes128gcm-encoded body. */
export async function sendPush(sub, vapid, payload = null) {
  const jwt = await buildVapidJwt(sub.endpoint, vapid.privateKey, vapid.publicKey, vapid.contactEmail);
  const headers = {
    Authorization: `vapid t=${jwt}, k=${vapid.publicKey}`,
    TTL: "86400",
  };
  let body;
  if (payload === null || payload === undefined) {
    headers["Content-Length"] = "0";
    body = undefined;
  } else {
    const encrypted = await encryptAes128Gcm(payload, sub.p256dh, sub.auth);
    headers["Content-Encoding"] = "aes128gcm";
    headers["Content-Type"] = "application/octet-stream";
    body = encrypted.body;
  }
  const res = await fetch(sub.endpoint, { method: "POST", headers, body });
  return {
    ok: res.ok,
    status: res.status,
    gone: res.status === 404 || res.status === 410,
    error: res.ok ? undefined : await res.text().catch(() => undefined),
  };
}

// ── Env plumbing ──────────────────────────────────────────────────────────────────────────────
// VAPID_PUBLIC_KEY/VAPID_SUBJECT are public [vars] in wrangler.toml; VAPID_PRIVATE_KEY is a Worker
// secret (never in wrangler.toml — set out-of-band via `wrangler secret put`). Returns null if any
// of the three is missing/empty, so callers (sweep.js, index.js) can no-op push cleanly without a
// separate "is push configured" check.
export function readVapidConfig(env) {
  const publicKey = env && env.VAPID_PUBLIC_KEY;
  const privateKey = env && env.VAPID_PRIVATE_KEY;
  const subject = env && env.VAPID_SUBJECT;
  if (!publicKey || !privateKey || !subject) return null;
  // VAPID_SUBJECT is the full RFC 8292 `mailto:you@x.com` contact; buildVapidJwt re-adds the
  // `mailto:` prefix itself, so strip it here if present. Kept robust to either form (a bare email
  // or an already-prefixed one) since this is a hand-set env var, not machine-generated.
  const contactEmail = subject.replace(/^mailto:/i, "");
  return { publicKey, privateKey, contactEmail };
}

// ── Store (port/adapt from distil/src/store/push.ts) ─────────────────────────────────────────────
// user_id is kept even though this is a single-owner app — tenant-safety parity with the rest of
// this worker (every other table here is scoped the same way).

export async function subscribePush(db, userId, { endpoint, p256dh, auth }) {
  const id = crypto.randomUUID();
  const ts = isoUtc();
  await db
    .prepare(
      `INSERT INTO push_subscriptions (id, user_id, endpoint, p256dh, auth, created_at, last_seen_at)
       VALUES (?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(user_id, endpoint) DO UPDATE SET
         p256dh = excluded.p256dh, auth = excluded.auth, last_seen_at = excluded.last_seen_at`
    )
    .bind(id, userId, endpoint, p256dh, auth, ts, ts)
    .run();
  return db.prepare(`SELECT * FROM push_subscriptions WHERE user_id = ? AND endpoint = ?`).bind(userId, endpoint).first();
}

export async function unsubscribePush(db, userId, endpoint) {
  await db.prepare(`DELETE FROM push_subscriptions WHERE user_id = ? AND endpoint = ?`).bind(userId, endpoint).run();
}

/** Prune a subscription the push service reports gone (404/410) — the dispatch cleanup path; no
 * user session is available there, so this prunes by row id, not (user_id, endpoint). */
export async function pruneSubscriptionById(db, id) {
  await db.prepare(`DELETE FROM push_subscriptions WHERE id = ?`).bind(id).run();
}

export async function listSubscriptionsForUser(db, userId) {
  const { results } = await db.prepare(`SELECT * FROM push_subscriptions WHERE user_id = ? ORDER BY created_at`).bind(userId).all();
  return results ?? [];
}

// Reason -> terse phrase, mirroring the PWA's POS_EXIT_REASON_SHORT (docs/index.html) so the push
// notification body reads consistently with the in-app confirmation strip. Kept as a small local map
// (not imported — this is a Worker, the PWA is a separate deployable) rather than a shared constant.
const EXIT_REASON_PHRASE = {
  stop_hit: "Stop hit",
  gap_down_below_stop: "Gap-down through stop",
  close_below_50ma: "Closed below the 50MA",
  close_below_20ma: "Closed below the 20MA",
  severe_breakdown: "Severe breakdown",
  two_close_below_20ma: "2 closes below the 20MA",
};

/** Build the Tier-1 exit-push JSON payload string for one intent. `reason`/`price` are optional —
 * an intent that only has `ticker` (reason/price unavailable) falls back to a generic body, per the
 * locked spec. */
export function buildExitPushPayload({ ticker, reason, price }) {
  const title = `🚨 ${ticker} — exit signal`;
  const phrase = reason && EXIT_REASON_PHRASE[reason];
  let body;
  if (phrase) {
    body = `${phrase}${typeof price === "number" ? ` at ${price}` : ""}. Confirm your fill.`;
  } else {
    body = "An exit signal fired. Open to confirm your fill.";
  }
  return JSON.stringify({ title, body, ticker, tag: "finviz-exit", url: "#positions" });
}

/** Build the Tier-2 decaying-cadence reminder push JSON payload string for one intent (WS5-4b PR-A,
 * issue #348 tail). MIRRORS `buildExitPushPayload` line-for-line — differences are ONLY: no 🚨 in
 * the title (this is the quiet tier), a "Day N..." countdown body, `tag: 'finviz-exit-reminder'`
 * (distinct from Tier-1's 'finviz-exit' so reminders collapse into their OWN lockscreen entry, never
 * replacing or being replaced by a Tier-1 notification), and `silent: true` (read by docs/sw.js's
 * push handler — the OS should not buzz/light up for these, just update quietly). See the locked
 * spec (`scratchpad/pr-A-tier2-reminders-spec.md`) for the full cadence rationale. */
export function buildReminderPushPayload({ ticker, sessions_in_closing, auto_confirm_sessions, reason, price }) {
  const title = `${ticker} — still closing`;
  const phrase = (reason && EXIT_REASON_PHRASE[reason]) || "Still below your exit level";
  const remaining = auto_confirm_sessions - sessions_in_closing;
  const body = `Day ${sessions_in_closing}. ${phrase}${typeof price === "number" ? ` at ${price}` : ""}. Auto-closes in ${remaining} session${remaining === 1 ? "" : "s"}.`;
  return JSON.stringify({ title, body, ticker, tag: "finviz-exit-reminder", silent: true, url: "#positions" });
}

/** Build the pre-close act-now push JSON payload string for one advisory item. Distinct copy from
 * `buildExitPushPayload` — different moment (15:40 provisional, not 17:30 settled) and different
 * call to action (place the order before the bell, not confirm an already-closed fill). Reuses the
 * SAME `EXIT_REASON_PHRASE` map so the reason wording stays consistent across both push tiers.
 * `tag: 'finviz-preclose'` is deliberately DISTINCT from Tier-1's `'finviz-exit'` so a later 17:30
 * push doesn't replace this one on the lockscreen (and vice versa) — see locked spec § A1. */
export function buildPreClosePushPayload({ ticker, signal, price }) {
  const title = `🚨 ${ticker} — act now before the close`;
  const phrase = signal && EXIT_REASON_PHRASE[signal];
  let body;
  if (phrase) {
    body = `${phrase}${typeof price === "number" ? ` at ${price}` : ""}. Place your broker order before the bell.`;
  } else {
    body = "A position hit an exit signal. Place your order before the bell.";
  }
  return JSON.stringify({ title, body, ticker, tag: "finviz-preclose", url: "#positions" });
}

// ── Pre-close act-now push dispatch (WS5-8 PR-2, issue #349) ─────────────────────────────────────
// Sibling dispatcher to dispatchExitPushes below, reading the already-upserted preclose_advisory
// rows (src/preclose.js) instead of collecting sweep-time intents. Same NEVER-THROWS contract, same
// "marker written only after a real successful send" idempotency discipline — but a DISTINCT
// event_type ('preclose_push_sent' vs 'push_sent') so the two push channels (15:40 advisory vs
// 17:30 settled exit) never suppress each other for the same trade_id/trade_date.
//
// HARD INVARIANT: this function must NEVER call ingestQuotes()/persistAdvance() or stamp
// positions.last_advanced_date — it only reads preclose_advisory and position_events/
// push_subscriptions. See worker-positions/CLAUDE.md § pre-close advisory for why that disjointness
// is load-bearing.
export async function dispatchPreClosePushes(db, { trade_date, vapid, sendPushFn = sendPush, now_iso }) {
  let sent = 0;
  let pruned = 0;
  let skipped = 0;

  if (!vapid) return { sent, pruned, skipped };

  let rows;
  try {
    const res = await db.prepare(`SELECT user_id, items FROM preclose_advisory WHERE trade_date = ?`).bind(trade_date).all();
    rows = res.results ?? [];
  } catch {
    return { sent, pruned, skipped };
  }

  for (const row of rows) {
    let items;
    try {
      items = JSON.parse(row.items || "[]");
    } catch {
      items = [];
    }

    for (const item of items) {
      if (!item || item.severity !== "act") continue;

      // Per-item isolation: a D1 error on one item must not abort the rest, mirroring
      // dispatchExitPushes' per-intent try/catch.
      try {
        const already = await db
          .prepare(`SELECT 1 FROM position_events WHERE trade_id = ? AND trade_date = ? AND event_type = 'preclose_push_sent' LIMIT 1`)
          .bind(item.trade_id, trade_date)
          .first();
        if (already) {
          skipped++;
          continue;
        }

        const subs = await listSubscriptionsForUser(db, row.user_id);
        if (subs.length === 0) {
          // No marker written — retries once a device subscribes, same rule as Tier-1.
          continue;
        }

        const payload = buildPreClosePushPayload({ ticker: item.ticker, signal: item.signal, price: item.price });

        let anySuccess = false;
        for (const sub of subs) {
          try {
            const res = await sendPushFn(sub, vapid, payload);
            if (res && res.gone) {
              await pruneSubscriptionById(db, sub.id);
              pruned++;
            } else if (res && res.ok) {
              anySuccess = true;
              sent++;
            }
          } catch {
            // Best-effort: a throw (network error, etc.) — continue to the next subscription.
          }
        }

        if (anySuccess) {
          await db
            .prepare(
              `INSERT INTO position_events (trade_id, user_id, ts, trade_date, event_type, payload) VALUES (?, ?, ?, ?, ?, ?)`
            )
            .bind(item.trade_id, row.user_id, now_iso, trade_date, "preclose_push_sent", JSON.stringify({ ticker: item.ticker }))
            .run();
        }
      } catch {
        // Best-effort: a D1 failure on this item is swallowed so the rest still dispatch.
      }
    }
  }

  return { sent, pruned, skipped };
}

// ── Dispatch orchestrator — the seam sweep.js calls; fully offline-testable via sendPushFn. ──────
// intents: [{ user_id, trade_id, ticker, reason?, price? }] — Tier-1 exit signals collected by this
// sweep run. `reason`/`price` are preferred (drive the ticker-named payload via
// buildExitPushPayload); when absent, the payload falls back to a ticker-only message.
// NEVER THROWS — every failure mode (no vapid config, no subscriptions, a send throwing, a non-ok
// non-gone response) is swallowed and counted, never rethrown. The caller relies on this.
export async function dispatchExitPushes(db, { intents, vapid, sendPushFn = sendPush, now_iso, trade_date }) {
  let sent = 0;
  let pruned = 0;
  let skipped = 0;

  if (!vapid || !intents || intents.length === 0) return { sent, pruned, skipped };

  for (const intent of intents) {
    // Per-intent isolation: a D1 error on one intent (the idempotency SELECT, the subscription
    // load, or the marker INSERT) must neither propagate out of this function — the documented
    // "NEVER THROWS" contract — nor abort the remaining intents in the same sweep. Each send is
    // additionally try/catched inside the inner loop.
    try {
      // Idempotency guard: skip if a push_sent event already exists for this (trade_id, trade_date).
      // Belt-and-suspenders — the closing-edge is already naturally once-per-position because the
      // sweep's advance loop excludes `closing` positions — but this guards a same-day re-dispatch and
      // any future change to that exclusion.
      const already = await db
        .prepare(`SELECT 1 FROM position_events WHERE trade_id = ? AND trade_date = ? AND event_type = 'push_sent' LIMIT 1`)
        .bind(intent.trade_id, trade_date)
        .first();
      if (already) {
        skipped++;
        continue;
      }

      const subs = await listSubscriptionsForUser(db, intent.user_id);
      if (subs.length === 0) {
        // Nothing to send to — do NOT write a push_sent marker, so it retries once a device
        // subscribes.
        continue;
      }

      const payload = buildExitPushPayload(intent);

      let anySuccess = false;
      for (const sub of subs) {
        try {
          const res = await sendPushFn(sub, vapid, payload);
          if (res && res.gone) {
            await pruneSubscriptionById(db, sub.id);
            pruned++;
          } else if (res && res.ok) {
            anySuccess = true;
            sent++;
          }
          // A non-ok, non-gone response: count nothing further, just move on (never rethrow).
        } catch {
          // A throw (network error, etc.): best-effort, continue to the next subscription.
        }
      }

      if (anySuccess) {
        // Mirrors distil's nag_log discipline: record ONLY after a real successful send, so a
        // transient failure doesn't permanently suppress the alert. Direct INSERT into
        // position_events — dispatchExitPushes runs AFTER the sweep's per-position D1 batches have
        // already committed (post-commit, best-effort), so this is not part of any CAS-guarded batch.
        await db
          .prepare(`INSERT INTO position_events (trade_id, user_id, ts, trade_date, event_type, payload) VALUES (?, ?, ?, ?, ?, ?)`)
          .bind(intent.trade_id, intent.user_id, now_iso, trade_date, "push_sent", JSON.stringify({ tier: 1 }))
          .run();
      }
    } catch {
      // Best-effort: a D1 failure on this intent is swallowed so the rest still dispatch.
    }
  }

  return { sent, pruned, skipped };
}

// ── Tier-2 decaying-cadence reminder push dispatch (WS5-4b PR-A, issue #348 tail) ────────────────
// MIRRORS dispatchExitPushes ABOVE, line-for-line. The only differences: the idempotency marker's
// event_type is 'reminder_push_sent' (not 'push_sent') so the two tiers never suppress each other
// for the same (trade_id, trade_date); the payload is built via buildReminderPushPayload; and the
// cadence gate (TIER2_REMINDER_SESSIONS) is enforced by the CALLER (sweep.js), not here — this
// function fires unconditionally for whatever intents it's handed, same as dispatchExitPushes.
// intents: [{ user_id, trade_id, ticker, sessions_in_closing, auto_confirm_sessions, reason?, price? }].
// NEVER THROWS — same contract as dispatchExitPushes; sweep.js wraps this call in its own try/catch
// besides.
export async function dispatchReminderPushes(db, { intents, vapid, sendPushFn = sendPush, now_iso, trade_date }) {
  let sent = 0;
  let pruned = 0;
  let skipped = 0;

  if (!vapid || !intents || intents.length === 0) return { sent, pruned, skipped };

  for (const intent of intents) {
    // Per-intent isolation, identical rationale to dispatchExitPushes.
    try {
      // Idempotency guard: at most one reminder per (trade_id, trade_date).
      const already = await db
        .prepare(`SELECT 1 FROM position_events WHERE trade_id = ? AND trade_date = ? AND event_type = 'reminder_push_sent' LIMIT 1`)
        .bind(intent.trade_id, trade_date)
        .first();
      if (already) {
        skipped++;
        continue;
      }

      const subs = await listSubscriptionsForUser(db, intent.user_id);
      if (subs.length === 0) {
        // No marker written — retries once a device subscribes, same rule as Tier-1.
        continue;
      }

      const payload = buildReminderPushPayload(intent);

      let anySuccess = false;
      for (const sub of subs) {
        try {
          const res = await sendPushFn(sub, vapid, payload);
          if (res && res.gone) {
            await pruneSubscriptionById(db, sub.id);
            pruned++;
          } else if (res && res.ok) {
            anySuccess = true;
            sent++;
          }
          // A non-ok, non-gone response: count nothing further, just move on (never rethrow).
        } catch {
          // A throw (network error, etc.): best-effort, continue to the next subscription.
        }
      }

      if (anySuccess) {
        // Marker written ONLY after a real successful send, same discipline as Tier-1.
        await db
          .prepare(`INSERT INTO position_events (trade_id, user_id, ts, trade_date, event_type, payload) VALUES (?, ?, ?, ?, ?, ?)`)
          .bind(
            intent.trade_id,
            intent.user_id,
            now_iso,
            trade_date,
            "reminder_push_sent",
            JSON.stringify({ tier: 2, sessions_in_closing: intent.sessions_in_closing })
          )
          .run();
      }
    } catch {
      // Best-effort: a D1 failure on this intent is swallowed so the rest still dispatch.
    }
  }

  return { sent, pruned, skipped };
}
