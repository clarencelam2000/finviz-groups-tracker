// finviz-positions — WS5 trade-lifecycle store (Cloudflare Worker + D1).
// Phase 1: authenticated, ticker-generic "I took it" write path (positions spine + first event)
// and a read-back list. No engine (phase 3), no held-tickers feed (phase 2), no push (phase 4).
// Design: planning/trade-lifecycle-engine.md; ADR-012. Auth seam: src/auth.js (see README § Auth).

import { authenticate, authenticateService, login } from "./auth.js";
import { validateCreatePayload, buildPositionRow, insertPosition, listPositions, ALL_STATES } from "./positions.js";
import { validateIngestBatch, ingestQuotes, heldTickers } from "./quotes.js";
import { sweep } from "./sweep.js";
import { subscribePush, unsubscribePush, readVapidConfig, dispatchPreClosePushes } from "./push.js";
import { computePreCloseAdvisory, readPreCloseAdvisory } from "./preclose.js";
import { etDateStr } from "./time.js";
import { applyTransition, ackStop } from "./transitions.js";
import { seedTickerBar } from "./seed.js";
import {
  validateAddPayload,
  validatePatchPayload,
  addWatch,
  listWatch,
  patchWatch,
  deleteWatch,
  watchlistTickerRefs,
  tickWatchlist,
} from "./watchlist.js";

// Anchored :id route for the owner watchlist collection, matched AFTER the exact /watchlist string
// checks below so it can never shadow them (mirror of TRANSITION_PATH's placement rationale). \d+
// cannot match the literal "tick" of /watchlist/tick, but that exact check is still tried first.
const WATCHLIST_ID_PATH = /^\/watchlist\/(\d+)$/;

// Owner exit-transition actions (WS5 phase 3b-ii). The path is /positions/<trade_id>/<action>; the
// trade_id is identity (in the path), not payload — the editable fill / corrected price ride in the
// body. Anchored ^…$ so it can never shadow the exact /positions collection routes above it.
const TRANSITION_PATH = /^\/positions\/([^/]+)\/(confirm-exit|still-holding|correct-exit|reopen|ack-stop)$/;

// ── CORS ──────────────────────────────────────────────────────────────────────────────────────
// The PWA is a cross-origin GitHub-Pages page, so every response needs CORS headers scoped to the
// allowed origin(s). Auth rides in the Authorization header (a bearer token), NOT a cookie, so we
// do NOT send Access-Control-Allow-Credentials and can pin the exact origin instead of "*".
// ALLOWED_ORIGINS is a comma-separated env var (e.g. the github.io origin + a localhost dev origin).
function allowedOrigin(request, env) {
  const origin = request.headers.get("origin");
  if (!origin) return null;
  const list = (env.ALLOWED_ORIGINS || "").split(",").map((s) => s.trim()).filter(Boolean);
  return list.includes(origin) ? origin : null;
}
function corsHeaders(request, env) {
  const origin = allowedOrigin(request, env);
  const h = {
    "Access-Control-Allow-Methods": "GET, POST, PATCH, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "authorization, content-type",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
  if (origin) h["Access-Control-Allow-Origin"] = origin;
  return h;
}
function json(body, status, request, env) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...corsHeaders(request, env) },
  });
}

export default {
  async fetch(request, env, ctx) {
    return handleRequest(request, env, ctx);
  },
};

export async function handleRequest(request, env, ctx) {
  const url = new URL(request.url);
  const { pathname } = url;
  const method = request.method.toUpperCase();

  // Preflight.
  if (method === "OPTIONS") return new Response(null, { status: 204, headers: corsHeaders(request, env) });

  if (pathname === "/health") return json({ ok: true, service: "finviz-positions" }, 200, request, env);

  // Login: passphrase -> bearer token. Generic 401 on failure (no username/password oracle).
  if (pathname === "/auth/login" && method === "POST") {
    let body;
    try {
      body = await request.json();
    } catch {
      return json({ error: "invalid JSON" }, 400, request, env);
    }
    let token;
    try {
      token = await login(env, body && body.passphrase);
    } catch (e) {
      return json({ error: "auth not configured" }, 500, request, env);
    }
    if (!token) return json({ error: "invalid credentials" }, 401, request, env);
    return json({ token }, 200, request, env);
  }

  // ── Machine (service-token) routes — WS5 phase 2 held-tickers feed (issue #312) ────────────────
  // Gated by authenticateService() (POSITIONS_INGEST_TOKEN), a path DISTINCT from the owner bearer
  // below: it can read the held set + append market bars, never touch private positions. See auth.js.
  if (pathname === "/held-tickers" && method === "GET") {
    if (!authenticateService(request, env)) return json({ error: "unauthorized" }, 401, request, env);
    let tickers;
    try {
      tickers = await heldTickers(env.POSITIONS_DB);
    } catch (e) {
      return json({ error: "read failed" }, 500, request, env);
    }
    return json({ tickers }, 200, request, env);
  }

  if (pathname === "/ingest/quotes" && method === "POST") {
    if (!authenticateService(request, env)) return json({ error: "unauthorized" }, 401, request, env);
    let body;
    try {
      body = await request.json();
    } catch {
      return json({ error: "invalid JSON" }, 400, request, env);
    }
    const v = validateIngestBatch(body);
    if (!v.ok) return json({ error: v.error }, 400, request, env);
    let written;
    try {
      written = await ingestQuotes(env.POSITIONS_DB, v.value);
    } catch (e) {
      return json({ error: "write failed" }, 500, request, env);
    }
    return json({ written, trade_date: v.value.trade_date }, 200, request, env);
  }

  // ── Pre-close advisory ingest — WS5-8 PR-1a ─────────────────────────────────────────────────────
  // Service-token, machine route: the 15:40 ET GitHub-Actions job POSTs a provisional bar batch here.
  // Payload shape is IDENTICAL to /ingest/quotes ({trade_date, collected_at, quotes[]}), so it reuses
  // the SAME validateIngestBatch(). This route only COMPUTES (calls the pure advance() per position
  // in memory) and writes to preclose_advisory — it never calls ingestQuotes(), so ticker_quotes is
  // untouched (HARD INVARIANT: a write here must never make the 17:30 sweep a no-op — see
  // src/preclose.js header + worker-positions/CLAUDE.md § pre-close advisory).
  if (pathname === "/positions/preclose-advisory" && method === "POST") {
    if (!authenticateService(request, env)) return json({ error: "unauthorized" }, 401, request, env);
    let body;
    try {
      body = await request.json();
    } catch {
      return json({ error: "invalid JSON" }, 400, request, env);
    }
    const v = validateIngestBatch(body);
    if (!v.ok) return json({ error: v.error }, 400, request, env);
    let result;
    try {
      result = await computePreCloseAdvisory(env.POSITIONS_DB, { quotes: v.value.rows, trade_date: v.value.trade_date });
    } catch (e) {
      return json({ error: "advisory failed" }, 500, request, env);
    }
    // WS5-8 PR-2 (issue #349): fire act-now pushes for the advisory's `act`-severity items. Best-
    // effort — never lets a push failure fail this route's response (see push.js's dispatch
    // comment); readVapidConfig(env) returns null when the VAPID secrets aren't set, in which case
    // dispatchPreClosePushes no-ops cleanly and `result.pushed` is simply omitted.
    const vapid = readVapidConfig(env);
    if (vapid) {
      try {
        const pushRes = await dispatchPreClosePushes(env.POSITIONS_DB, {
          trade_date: v.value.trade_date,
          vapid,
          now_iso: new Date().toISOString(),
        });
        result.pushed = (pushRes && pushRes.sent) || 0;
      } catch (e) {
        console.error("dispatchPreClosePushes failed", e);
      }
    }
    return json(result, 200, request, env);
  }

  // ── Watchlist machine routes — WS5 §8b P1 (issue #319) ──────────────────────────────────────────
  // Same auth split as /held-tickers + /ingest/quotes above: service-token only, no owner bearer can
  // satisfy authenticateService(). GET /watchlist-tickers omits level_value on purpose (privacy —
  // see watchlistTickerRefs()'s comment); POST /watchlist/tick is the idempotent-per-ET-date TTL
  // decrement collect_morning.py calls after a successful morning run.
  if (pathname === "/watchlist-tickers" && method === "GET") {
    if (!authenticateService(request, env)) return json({ error: "unauthorized" }, 401, request, env);
    let tickers;
    try {
      tickers = await watchlistTickerRefs(env.POSITIONS_DB);
    } catch (e) {
      return json({ error: "read failed" }, 500, request, env);
    }
    return json({ tickers }, 200, request, env);
  }

  if (pathname === "/watchlist/tick" && method === "POST") {
    if (!authenticateService(request, env)) return json({ error: "unauthorized" }, 401, request, env);
    let body = {};
    if ((request.headers.get("content-type") || "").includes("application/json")) {
      try {
        body = await request.json();
      } catch {
        body = {}; // invalid/absent JSON tolerated — `date` is optional, defaults to today's ET date.
      }
    }
    let result;
    try {
      result = await tickWatchlist(env.POSITIONS_DB, { date: body.date, now: new Date() });
    } catch (e) {
      return json({ error: "tick failed" }, 500, request, env);
    }
    return json(result, 200, request, env);
  }

  // ── /advance — WS5 phase 3b daily-engine sweep (SPRINT WS5-3b) ─────────────────────────────────
  // Dual auth, ONE route: either the service token (the GitHub-Actions cron caller, once the daily
  // trigger lands) or the owner bearer (so the owner can also fire a sweep manually / for a live
  // dry-run from the PWA) may call this. Must sit HERE — in the machine-routes block, BEFORE the
  // owner-only gate below — because that gate 401s any request lacking an owner bearer token, which
  // would make this route unreachable for a service-token caller if it were placed after.
  if (pathname === "/advance" && method === "POST") {
    const service = authenticateService(request, env);
    const owner = service ? null : await authenticate(request, env); // skip the second auth check once service already passed
    if (!service && !owner) return json({ error: "unauthorized" }, 401, request, env);

    const dry_run = url.searchParams.get("dry_run") === "1";
    // WS5-4b: readVapidConfig(env) returns null when VAPID_PUBLIC_KEY/VAPID_PRIVATE_KEY/
    // VAPID_SUBJECT aren't all set — sweep() then no-ops push entirely (see push.js). Safe to pass
    // unconditionally.
    const push = { vapid: readVapidConfig(env) };
    let result;
    try {
      result = await sweep(env.POSITIONS_DB, { dry_run, push });
    } catch (e) {
      // Match the existing error-handling style exactly: never leak exception text to the caller.
      return json({ error: "advance failed" }, 500, request, env);
    }

    // RESPONSE SHAPING (security): a SERVICE-token caller gets COUNTS ONLY — `results` is
    // stripped. The service token is held by GitHub Actions (a CI secret, not the owner's private
    // credential), and `results` carries per-position trade_ids/tickers/states — private position
    // data the least-privilege machine path must not be able to read back, even though it's now
    // allowed to TRIGGER the computation that produces it (see auth.js's authenticateService
    // comment for the updated blast-radius argument). Counts are enough for the CI job to log and
    // alarm on ("advanced 4, signalled 1") without exposing what those 4 positions actually are.
    // Only the owner's own bearer token gets the full object, `results` included.
    if (!owner) {
      const { results, ...counts } = result;
      return json(counts, 200, request, env);
    }
    return json(result, 200, request, env);
  }

  // Everything below requires a valid owner bearer token (interactive human auth).
  const auth = await authenticate(request, env);
  if (!auth) return json({ error: "unauthorized" }, 401, request, env);

  if (pathname === "/positions" && method === "POST") {
    let body;
    try {
      body = await request.json();
    } catch {
      return json({ error: "invalid JSON" }, 400, request, env);
    }
    const v = validateCreatePayload(body);
    if (!v.ok) return json({ error: v.error }, 400, request, env);
    const row = buildPositionRow(v.value, { trade_id: crypto.randomUUID(), user_id: auth.user_id });
    try {
      await insertPosition(env.POSITIONS_DB, row);
    } catch (e) {
      return json({ error: "write failed" }, 500, request, env);
    }
    return json({ position: { ...row, meta: JSON.parse(row.meta) } }, 201, request, env);
  }

  if (pathname === "/positions" && method === "GET") {
    // Accepts repeated params (?state=open&state=managing) and/or a comma-separated value
    // (?state=open,managing,closing) — merged and deduped. No `state` (or all-empty) = all states,
    // matching the old single-`state` behavior. Unknown values 400 rather than silently returning
    // zero rows (a typo shouldn't look identical to "no live positions").
    const rawStates = url.searchParams.getAll("state").flatMap((s) => s.split(","));
    const states = [...new Set(rawStates.map((s) => s.trim()).filter((s) => s.length > 0))];
    const unknown = states.filter((s) => !ALL_STATES.includes(s));
    if (unknown.length > 0) {
      return json({ error: `unknown state(s): ${unknown.join(", ")}` }, 400, request, env);
    }

    // Optional bound on returned `closed` rows by sessions-since-close (WS5-6 closed-history
    // payload guard). Absent/empty = no filter, matching current PWA behavior unchanged. Must be a
    // positive integer — same "reject, don't silently ignore" stance as the unknown-state check above.
    const rawClosedWithin = url.searchParams.get("closed_within_sessions");
    let closedWithinSessions;
    if (rawClosedWithin != null && rawClosedWithin !== "") {
      const n = Number(rawClosedWithin);
      if (!Number.isInteger(n) || n <= 0) {
        return json({ error: "closed_within_sessions must be a positive integer" }, 400, request, env);
      }
      closedWithinSessions = n;
    }

    let rows;
    try {
      rows = await listPositions(env.POSITIONS_DB, auth.user_id, states, { closedWithinSessions });
    } catch (e) {
      return json({ error: "read failed" }, 500, request, env);
    }
    return json({ positions: rows }, 200, request, env);
  }

  // ── Owner push-subscription routes — WS5-4b (issue #264 epic) ───────────────────────────────────
  // Owner-bearer only (private, user-scoped push endpoints — never exposed via GET; the PWA only
  // needs to subscribe/unsubscribe, never to list its own subscriptions back).
  if (pathname === "/push/subscribe" && method === "POST") {
    let body;
    try {
      body = await request.json();
    } catch {
      return json({ error: "invalid JSON" }, 400, request, env);
    }
    // Shape matches PushSubscription.toJSON(): { endpoint, keys: { p256dh, auth } }.
    const endpoint = body && typeof body.endpoint === "string" ? body.endpoint : null;
    const keys = body && body.keys;
    const p256dh = keys && typeof keys.p256dh === "string" ? keys.p256dh : null;
    const authSecret = keys && typeof keys.auth === "string" ? keys.auth : null;
    if (!endpoint || !p256dh || !authSecret) {
      return json({ error: "endpoint and keys.p256dh/keys.auth are required" }, 400, request, env);
    }
    try {
      await subscribePush(env.POSITIONS_DB, auth.user_id, { endpoint, p256dh, auth: authSecret });
    } catch (e) {
      return json({ error: "write failed" }, 500, request, env);
    }
    return json({ ok: true }, 200, request, env);
  }

  if (pathname === "/push/unsubscribe" && method === "POST") {
    let body;
    try {
      body = await request.json();
    } catch {
      return json({ error: "invalid JSON" }, 400, request, env);
    }
    const endpoint = body && typeof body.endpoint === "string" ? body.endpoint : null;
    if (!endpoint) return json({ error: "endpoint is required" }, 400, request, env);
    try {
      await unsubscribePush(env.POSITIONS_DB, auth.user_id, endpoint);
    } catch (e) {
      return json({ error: "write failed" }, 500, request, env);
    }
    return json({ ok: true }, 200, request, env);
  }

  // ── Owner watchlist routes — WS5 §8b P1 (issue #319) ────────────────────────────────────────────
  // Exact-string checks for the /watchlist collection FIRST, then the anchored WATCHLIST_ID_PATH
  // regex for /watchlist/:id — same shadowing-avoidance order as TRANSITION_PATH below.
  if (pathname === "/watchlist" && method === "POST") {
    let body;
    try {
      body = await request.json();
    } catch {
      return json({ error: "invalid JSON" }, 400, request, env);
    }
    const v = validateAddPayload(body);
    if (!v.ok) return json({ error: v.error }, 400, request, env);
    let row;
    try {
      row = await addWatch(env.POSITIONS_DB, { ...v.value, user_id: auth.user_id });
    } catch (e) {
      return json({ error: "write failed" }, 500, request, env);
    }
    // Fire-and-forget: never await this in the response path (best-effort, per src/seed.js's
    // contract). ctx.waitUntil keeps the Worker alive to let it finish after the response is
    // sent; without a ctx (e.g. some test harnesses), the promise still runs but isn't awaited.
    const seedPromise = seedTickerBar(env.POSITIONS_DB, v.value.ticker, env).catch(() => {
      // seed is best-effort; never fail the add
    });
    if (ctx && typeof ctx.waitUntil === "function") ctx.waitUntil(seedPromise);
    return json({ watch: row }, 201, request, env);
  }

  if (pathname === "/watchlist" && method === "GET") {
    let rows;
    try {
      rows = await listWatch(env.POSITIONS_DB, auth.user_id);
    } catch (e) {
      return json({ error: "read failed" }, 500, request, env);
    }
    return json({ watchlist: rows }, 200, request, env);
  }

  const watchId = pathname.match(WATCHLIST_ID_PATH);
  if (watchId && method === "PATCH") {
    const id = Number(watchId[1]);
    let body;
    try {
      body = await request.json();
    } catch {
      return json({ error: "invalid JSON" }, 400, request, env);
    }
    const v = validatePatchPayload(body);
    if (!v.ok) return json({ error: v.error }, 400, request, env);
    let result;
    try {
      result = await patchWatch(env.POSITIONS_DB, { ...v.value, user_id: auth.user_id, id });
    } catch (e) {
      return json({ error: "write failed" }, 500, request, env);
    }
    if (!result.changed) return json({ error: "not found" }, 404, request, env);
    return json({ ok: true }, 200, request, env);
  }

  if (watchId && method === "DELETE") {
    const id = Number(watchId[1]);
    let result;
    try {
      result = await deleteWatch(env.POSITIONS_DB, { user_id: auth.user_id, id });
    } catch (e) {
      return json({ error: "write failed" }, 500, request, env);
    }
    if (!result.changed) return json({ error: "not found" }, 404, request, env);
    return json({ ok: true }, 200, request, env);
  }

  // ── Pre-close advisory read — WS5-8 PR-1a ───────────────────────────────────────────────────────
  // Owner-bearer, exact-path route. Placed BEFORE the TRANSITION_PATH regex below so the literal
  // "/positions/preclose" can never be mistaken for a /positions/<trade_id>/<action> transition
  // (mirrors this file's existing shadowing-avoidance convention for WATCHLIST_ID_PATH/TRANSITION_PATH).
  if (pathname === "/positions/preclose" && method === "GET") {
    const trade_date = etDateStr(new Date());
    let row;
    try {
      row = await readPreCloseAdvisory(env.POSITIONS_DB, auth.user_id, trade_date);
    } catch (e) {
      return json({ error: "read failed" }, 500, request, env);
    }
    return json(row || { ran_at: null, n_checked: 0, n_flagged: 0, items: [] }, 200, request, env);
  }

  // ── Owner exit-transition + ack-stop routes — WS5 phase 3b-ii / WS5-7 ───────────────────────────
  // POST /positions/<trade_id>/{confirm-exit|still-holding|correct-exit|reopen|ack-stop}. Owner-
  // bearer only (the machine service token gets no say over a human's exit fill or stop ack), so
  // these correctly sit BELOW the owner-auth gate above. applyTransition() owns the load ->
  // precondition -> pure-fn -> CAS-persist pipeline for the first four; here we only parse the body
  // and map its typed result to a Response. ack-stop is handled separately below — see its comment.
  const tx = pathname.match(TRANSITION_PATH);
  if (tx && method === "POST") {
    let trade_id;
    try {
      trade_id = decodeURIComponent(tx[1]);
    } catch {
      return json({ error: "invalid trade_id" }, 400, request, env);
    }
    const action = tx[2];
    let body = {};
    if ((request.headers.get("content-type") || "").includes("application/json")) {
      try {
        body = await request.json();
      } catch {
        return json({ error: "invalid JSON" }, 400, request, env);
      }
    }
    // ack-stop is event-only (no positions-column write; see transitions.js's ackStop comment) —
    // it does NOT go through applyTransition/persistTransition, which write TRANSITION_COLS and
    // enforce state preconditions that don't apply to a plain activity-log append. Branch first.
    if (action === "ack-stop") {
      let result;
      try {
        result = await ackStop(env.POSITIONS_DB, { user_id: auth.user_id, trade_id });
      } catch (e) {
        return json({ error: "ack failed" }, 500, request, env);
      }
      if (result.error) return json({ error: result.error }, result.status, request, env);
      return json({ ok: true, stop_ack_value: result.stop_ack_value }, 200, request, env);
    }

    let result;
    try {
      result = await applyTransition(env.POSITIONS_DB, { user_id: auth.user_id, trade_id, action, body });
    } catch (e) {
      return json({ error: "transition failed" }, 500, request, env);
    }
    if (result.error) return json({ error: result.error }, result.status, request, env);
    return json({ position: result.position }, 200, request, env);
  }

  return json({ error: "not found" }, 404, request, env);
}
