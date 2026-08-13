// finviz-positions — WS5 trade-lifecycle store (Cloudflare Worker + D1).
// Phase 1: authenticated, ticker-generic "I took it" write path (positions spine + first event)
// and a read-back list. No engine (phase 3), no held-tickers feed (phase 2), no push (phase 4).
// Design: planning/trade-lifecycle-engine.md; ADR-012. Auth seam: src/auth.js (see README § Auth).

import { authenticate, authenticateService, login } from "./auth.js";
import { validateCreatePayload, buildPositionRow, insertPosition, listPositions } from "./positions.js";
import { validateIngestBatch, ingestQuotes, heldTickers } from "./quotes.js";

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
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
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

  return json({ error: "not found" }, 404, request, env);
}
