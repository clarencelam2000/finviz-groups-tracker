// finviz-positions — WS5 trade-lifecycle store (Cloudflare Worker + D1).
// Phase 1: authenticated, ticker-generic "I took it" write path (positions spine + first event)
// and a read-back list. No engine (phase 3), no held-tickers feed (phase 2), no push (phase 4).
// Design: planning/trade-lifecycle-engine.md; ADR-012. Auth seam: src/auth.js (see README § Auth).

import { authenticate, authenticateService, login } from "./auth.js";
import { validateCreatePayload, buildPositionRow, insertPosition, listPositions } from "./positions.js";
import { validateIngestBatch, ingestQuotes, heldTickers } from "./quotes.js";
import { sweep } from "./sweep.js";
import { applyTransition } from "./transitions.js";
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
const TRANSITION_PATH = /^\/positions\/([^/]+)\/(confirm-exit|still-holding|correct-exit|reopen)$/;

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
  async fetch(request, env) {
    return handleRequest(request, env);
  },
};

export async function handleRequest(request, env) {
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
    let result;
    try {
      result = await sweep(env.POSITIONS_DB, { dry_run });
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
    const state = url.searchParams.get("state");
    let rows;
    try {
      rows = await listPositions(env.POSITIONS_DB, auth.user_id, state || null);
    } catch (e) {
      return json({ error: "read failed" }, 500, request, env);
    }
    return json({ positions: rows }, 200, request, env);
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

  // ── Owner exit-transition routes — WS5 phase 3b-ii (SPRINT WS5-3b-ii) ───────────────────────────
  // POST /positions/<trade_id>/{confirm-exit|still-holding|correct-exit|reopen}. Owner-bearer only
  // (the machine service token gets no say over a human's exit fill), so these correctly sit BELOW
  // the owner-auth gate above. applyTransition() owns the load → precondition → pure-fn → CAS-persist
  // pipeline; here we only parse the body and map its typed result to a Response.
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
