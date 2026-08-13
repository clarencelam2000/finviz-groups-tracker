// Auth layer for finviz-positions (WS5 phase 1).
//
// SWAP POINT — this whole file is the auth seam. The rest of the worker only ever calls
// `authenticate(request, env)` and gets back `{ user_id }` or `null`. Today that is a
// worker-native HMAC bearer token (chosen because the PWA is a cross-origin GitHub-Pages page and
// Cloudflare Access's cookie would be third-party there — see worker-positions/README.md § Auth).
// If the PWA ever moves onto Cloudflare Pages / a custom domain, switching to Cloudflare Access is
// a change to THIS function alone: verify the `Cf-Access-Jwt-Assertion` header against the team
// certs instead of the bearer token, and return the same `{ user_id }`. No caller changes, no
// schema change. (Owner decision 2026-08-13; kept non-blocking to a future Access migration.)
//
// At user = 1, "login" is a single passphrase (POSITIONS_AUTH_PASSPHRASE secret) exchanged for a
// signed, expiring token via POST /auth/login. The token is minted server-side, lives only in the
// owner's browser localStorage, and is NEVER embedded in the public page source — so this is not
// the "world-readable shared secret" pattern that was explicitly rejected. Multi-user email-OTP
// (the sibling `distil` worker already implements it) is a later drop-in; `user_id` is threaded
// through everything from day one so that is a policy change, not a migration.

const TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30; // 30 days; re-login after expiry. Tune via redeploy.
const SINGLE_USER_ID = "owner"; // the only user_id at user = 1; never client-supplied.

const enc = new TextEncoder();

function b64urlEncode(bytes) {
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function b64urlDecodeToBytes(str) {
  const pad = str.length % 4 === 0 ? "" : "=".repeat(4 - (str.length % 4));
  const bin = atob(str.replace(/-/g, "+").replace(/_/g, "/") + pad);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

async function hmacKey(secret) {
  return crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, [
    "sign",
    "verify",
  ]);
}

// Constant-time-ish compare of two byte arrays (avoids leaking length/prefix via early return).
function timingSafeEqual(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

// Mint a signed token for user_id. payload.exp is a unix-seconds expiry.
export async function mintToken(env, userId = SINGLE_USER_ID, now = Date.now()) {
  const secret = env.POSITIONS_SESSION_SECRET;
  if (!secret) throw new Error("POSITIONS_SESSION_SECRET not configured");
  const payload = { uid: userId, iat: Math.floor(now / 1000), exp: Math.floor(now / 1000) + TOKEN_TTL_SECONDS };
  const payloadB64 = b64urlEncode(enc.encode(JSON.stringify(payload)));
  const key = await hmacKey(secret);
  const sig = new Uint8Array(await crypto.subtle.sign("HMAC", key, enc.encode(payloadB64)));
  return `${payloadB64}.${b64urlEncode(sig)}`;
}

// Verify a token string → payload object, or null if invalid/expired/tampered.
export async function verifyToken(env, token, now = Date.now()) {
  const secret = env.POSITIONS_SESSION_SECRET;
  if (!secret || typeof token !== "string" || !token.includes(".")) return null;
  const [payloadB64, sigB64] = token.split(".");
  if (!payloadB64 || !sigB64) return null;
  let expected;
  try {
    const key = await hmacKey(secret);
    expected = new Uint8Array(await crypto.subtle.sign("HMAC", key, enc.encode(payloadB64)));
  } catch {
    return null;
  }
  let given;
  try {
    given = b64urlDecodeToBytes(sigB64);
  } catch {
    return null;
  }
  if (!timingSafeEqual(expected, given)) return null;
  let payload;
  try {
    payload = JSON.parse(new TextDecoder().decode(b64urlDecodeToBytes(payloadB64)));
  } catch {
    return null;
  }
  if (!payload || typeof payload.exp !== "number" || Math.floor(now / 1000) >= payload.exp) return null;
  return payload;
}

// The one function the rest of the worker calls. Returns { user_id } or null.
export async function authenticate(request, env, now = Date.now()) {
  const header = request.headers.get("authorization") || "";
  const m = header.match(/^Bearer\s+(.+)$/i);
  if (!m) return null;
  const payload = await verifyToken(env, m[1].trim(), now);
  if (!payload) return null;
  return { user_id: payload.uid };
}

// ── Machine (service) auth — WS5 phase 2 held-tickers ingest ────────────────────────────────────
// SECOND auth path on the same seam, for the GitHub-Actions held-tickers job (issue #312). It is
// deliberately DISTINCT from the interactive owner bearer above:
//   * different secret  — POSITIONS_INGEST_TOKEN (a long random string), not the owner passphrase.
//   * different power    — a caller holding this token may ONLY read the held-ticker set and append
//                          market-data bars; it can NEVER read, create, or mutate the owner's
//                          private positions (those routes call authenticate(), which this token
//                          cannot satisfy — it is not a valid HMAC-signed user token).
// Least-privilege: if the CI secret leaks, the blast radius is "someone can write junk market bars
// or learn which symbols are held", NOT "someone can see/alter the owner's trades". A dropped-in
// Cloudflare Access migration (see top of file) would leave this path untouched — machine-to-machine
// auth is orthogonal to the human login seam.
//
// The token rides in the same Authorization: Bearer header for transport simplicity; there is no
// ambiguity because service routes call authenticateService() and user routes call authenticate(),
// and neither token can pass the other's check (static-secret compare vs HMAC-signature verify).
export function authenticateService(request, env) {
  const secret = env.POSITIONS_INGEST_TOKEN;
  if (!secret) return false; // fail closed: no secret configured => no machine writes accepted.
  const header = request.headers.get("authorization") || "";
  const m = header.match(/^Bearer\s+(.+)$/i);
  if (!m) return false;
  const given = enc.encode(m[1].trim());
  const expected = enc.encode(secret);
  // Length check first is safe (the token is a high-entropy secret; its length is not sensitive) and
  // lets timingSafeEqual assume equal lengths.
  if (given.length !== expected.length) return false;
  return timingSafeEqual(given, expected);
}

// Exchange the login passphrase for a token. Constant-time compare; generic failure (no oracle).
export async function login(env, passphrase, now = Date.now()) {
  const expected = env.POSITIONS_AUTH_PASSPHRASE;
  if (!expected) throw new Error("POSITIONS_AUTH_PASSPHRASE not configured");
  const ok =
    typeof passphrase === "string" &&
    passphrase.length === expected.length &&
    timingSafeEqual(enc.encode(passphrase), enc.encode(expected));
  if (!ok) return null;
  return await mintToken(env, SINGLE_USER_ID, now);
}

export const _internal = { TOKEN_TTL_SECONDS, SINGLE_USER_ID, b64urlEncode, b64urlDecodeToBytes };
