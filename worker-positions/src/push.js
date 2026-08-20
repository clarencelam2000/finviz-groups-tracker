// WS5-4b Web Push (Tier-1 exit-signal push, backend half). Design: the epic issue (#264) + the lead's
// locked spec for this PR. Ported from the sibling `distil` worker's proven `src/cron/webpush.ts` /
// `src/store/push.ts` (Phase 3 plan §6-D3 there) — see the header comment on buildVapidJwt/sendPush
// below for why it's a small vendored implementation, not a Node-shimmed `web-push` dependency.
//
// SCOPE, v1: Tier-1 ONLY — one data-less, VAPID-authenticated push fired when the 17:30 sweep first
// transitions a position to `closing`. Data-less means RFC 8292 VAPID auth with NO RFC 8291
// `aes128gcm` payload encryption — no ephemeral ECDH, no HKDF, no AES-GCM. Tier-2 reminders,
// decaying cadence, and earnings-approach push are explicitly OUT OF SCOPE for this file; they need
// payload encryption to differentiate salience, which this file deliberately does not implement.
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

/** Send a data-less, VAPID-authenticated push to one subscription endpoint. */
export async function sendPush(endpoint, vapid) {
  const jwt = await buildVapidJwt(endpoint, vapid.privateKey, vapid.publicKey, vapid.contactEmail);
  const res = await fetch(endpoint, {
    method: "POST",
    headers: {
      Authorization: `vapid t=${jwt}, k=${vapid.publicKey}`,
      TTL: "86400",
      "Content-Length": "0",
    },
  });
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

// ── Dispatch orchestrator — the seam sweep.js calls; fully offline-testable via sendPushFn. ──────
// intents: [{ user_id, trade_id, ticker }] — Tier-1 exit signals collected by this sweep run.
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

      let anySuccess = false;
      for (const sub of subs) {
        try {
          const res = await sendPushFn(sub.endpoint, vapid);
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
