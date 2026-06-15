/**
 * Finviz Ticker Lookup — Cloudflare Worker (TICKER-1 / Phase 2).
 *
 * GET /lookup?t=AAPL → company profile + Finviz sector/industry classification.
 *   - KV cache (30d TTL) keyed by uppercased symbol.
 *   - On miss, calls FMP `stable/profile` (see knowledge/fmp-api-findings.md:
 *     the plan's legacy /api/v3/profile/ endpoint is dead for new free keys).
 * GET /health → liveness + KV ping.
 * OPTIONS    → CORS preflight.
 *
 * All errors return HTTP 200 with {error: "..."} so front-ends distinguish error
 * types without catching HTTP status codes.
 */
import { lookupTaxonomy, lookupSector } from './taxonomy.js';

const FMP_PROFILE_URL = 'https://financialmodelingprep.com/stable/profile';
const DEFAULT_TTL_SECONDS = 2592000; // 30 days
const FMP_TIMEOUT_MS = 5000;

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

function jsonResponse(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json', ...CORS_HEADERS },
  });
}

function log(fields) {
  try {
    console.log(JSON.stringify({ ts: new Date().toISOString(), ...fields }));
  } catch (_) {
    // logging must never break a request
  }
}

export async function handleRequest(request, env) {
  const url = new URL(request.url);

  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }
  if (url.pathname === '/health') {
    return handleHealth(env);
  }
  if (url.pathname === '/lookup') {
    return handleLookup(url, env);
  }
  if (url.pathname === '/stats') {
    return handleStats(env);
  }
  if (url.pathname === '/cache' && request.method === 'DELETE') {
    return handleCacheBust(url, env);
  }
  return jsonResponse({ error: 'not_found' }, 404);
}

async function handleHealth(env) {
  let kvOk = false;
  try {
    await env.LOOKUP_CACHE.get('__health_ping__');
    kvOk = true;
  } catch (_) {
    kvOk = false;
  }
  return jsonResponse({ status: 'ok', timestamp: new Date().toISOString(), kv_ok: kvOk });
}

async function handleLookup(url, env) {
  const start = Date.now();
  const symbol = (url.searchParams.get('t') || '').trim().toUpperCase();
  if (!symbol) {
    return jsonResponse({ error: 'missing_symbol' });
  }

  let cacheHit = false;
  let fmpCalled = false;
  let response;

  try {
    const cached = await env.LOOKUP_CACHE.get(symbol);
    if (cached) {
      cacheHit = true;
      response = JSON.parse(cached);
    } else {
      fmpCalled = true;
      const result = await fetchProfile(symbol, env);
      if (result.error) {
        response = { error: result.error };
        // don't cache transient/lookup errors
      } else {
        response = result.data;
        const ttl = parseInt(env.CACHE_TTL_SECONDS, 10) || DEFAULT_TTL_SECONDS;
        await env.LOOKUP_CACHE.put(symbol, JSON.stringify(response), { expirationTtl: ttl });
        await incrementFmpCallCount(env);
      }
    }
  } catch (e) {
    response = { error: 'internal_error' };
    log({ symbol, level: 'error', message: String(e && e.message ? e.message : e) });
  }

  log({
    symbol,
    cache_hit: cacheHit,
    fmp_called: fmpCalled,
    error: (response && response.error) || null,
    latency_ms: Date.now() - start,
  });
  return jsonResponse(response);
}

/**
 * Fetch + normalize an FMP `stable/profile` record into our response schema.
 * Returns {data} on success or {error} on any failure.
 */
async function fetchProfile(symbol, env) {
  const apiKey = env.FMP_API_KEY;
  if (!apiKey) {
    log({ symbol, level: 'error', message: 'FMP_API_KEY not configured' });
    return { error: 'internal_error' };
  }

  const apiUrl =
    `${FMP_PROFILE_URL}?symbol=${encodeURIComponent(symbol)}&apikey=${encodeURIComponent(apiKey)}`;

  let resp;
  try {
    resp = await fetch(apiUrl, { signal: AbortSignal.timeout(FMP_TIMEOUT_MS) });
  } catch (e) {
    log({ symbol, level: 'error', message: `FMP fetch failed: ${e && e.name}` });
    return { error: 'fmp_timeout' };
  }

  if (resp.status === 429) {
    console.error(`FMP rate limited (429) for ${symbol}`);
    return { error: 'rate_limited' };
  }
  if (resp.status >= 500) {
    console.error(`FMP ${resp.status} for ${symbol}`);
    return { error: 'fmp_unavailable' };
  }
  if (!resp.ok) {
    console.error(`FMP ${resp.status} for ${symbol}`);
    return { error: 'fmp_unavailable' };
  }

  let payload;
  try {
    payload = await resp.json();
  } catch (e) {
    console.error(`FMP returned non-JSON for ${symbol}`);
    return { error: 'internal_error' };
  }

  if (!Array.isArray(payload) || payload.length === 0) {
    return { error: 'ticker_not_found' };
  }

  const p = payload[0];
  const tax = lookupTaxonomy(p.industry);
  const finvizSector = tax.finviz_sector || lookupSector(p.sector);

  const rawCap = typeof p.marketCap === 'number' ? p.marketCap : Number(p.marketCap);
  const marketCapB = Number.isFinite(rawCap) ? rawCap / 1e9 : null;

  return {
    data: {
      symbol: p.symbol || symbol,
      company_name: p.companyName || '',
      description: p.description || '',
      image: p.image || '',
      exchange: p.exchange || '',
      country: p.country || '',
      market_cap_b: marketCapB,
      ceo: p.ceo || '',
      website: p.website || '',
      fmp_sector: p.sector || '',
      fmp_industry: p.industry || '',
      finviz_sector: finvizSector,
      finviz_industry: tax.finviz_industry,
      industry_confidence: tax.confidence,
      is_etf: Boolean(p.isEtf),
      is_adr: Boolean(p.isAdr),
      is_fund: Boolean(p.isFund),
      cached_at: new Date().toISOString(),
      error: null,
    },
  };
}

/** Increment today's FMP API call counter in KV (best-effort; never throws). */
async function incrementFmpCallCount(env) {
  try {
    const day = new Date().toISOString().slice(0, 10);
    const key = `fmp_calls_${day}`;
    const prev = parseInt((await env.LOOKUP_CACHE.get(key)) || '0', 10);
    await env.LOOKUP_CACHE.put(key, String(prev + 1), { expirationTtl: 86400 * 7 });
  } catch (_) {
    // counter failure must never fail a lookup request
  }
}

async function handleStats(env) {
  const day = new Date().toISOString().slice(0, 10);
  const key = `fmp_calls_${day}`;
  const fmpCallsToday = parseInt((await env.LOOKUP_CACHE.get(key)) || '0', 10);
  return jsonResponse({ date: day, fmp_calls_today: fmpCallsToday });
}

async function handleCacheBust(url, env) {
  const sym = (url.searchParams.get('t') || '').trim().toUpperCase();
  if (!sym) {
    return jsonResponse({ error: 'missing_symbol' });
  }
  await env.LOOKUP_CACHE.delete(sym);
  return jsonResponse({ deleted: sym });
}

export default {
  fetch: handleRequest,
};
