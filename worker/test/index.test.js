import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { handleRequest } from '../src/index.js';

/** In-memory stand-in for a Cloudflare KV namespace. */
function makeKV(initial = {}) {
  const store = new Map(Object.entries(initial));
  return {
    get: vi.fn(async (k) => (store.has(k) ? store.get(k) : null)),
    put: vi.fn(async (k, v) => { store.set(k, v); }),
    delete: vi.fn(async (k) => { store.delete(k); }),
    _store: store,
  };
}

function makeEnv(kv = makeKV()) {
  return { LOOKUP_CACHE: kv, FMP_API_KEY: 'test-key', CACHE_TTL_SECONDS: '2592000' };
}

function req(path, method = 'GET') {
  return new Request(`https://worker.example.dev${path}`, { method });
}

/** A representative FMP `stable/profile` record (post-migration field names). */
function fmpRecord(overrides = {}) {
  return {
    symbol: 'AAPL',
    companyName: 'Apple Inc.',
    description: 'Apple designs phones.',
    image: 'https://images.financialmodelingprep.com/symbol/AAPL.png',
    exchange: 'NASDAQ',
    country: 'US',
    marketCap: 3200000000000, // 3.2e12 → 3200 B
    ceo: 'Tim Cook',
    website: 'https://www.apple.com',
    sector: 'Technology',
    industry: 'Consumer Electronics',
    isEtf: false,
    isAdr: false,
    isFund: false,
    ...overrides,
  };
}

function mockFetch(status, body) {
  global.fetch = vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }));
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('CORS + routing', () => {
  it('OPTIONS preflight returns 204 with CORS headers', async () => {
    const res = await handleRequest(req('/lookup', 'OPTIONS'), makeEnv());
    expect(res.status).toBe(204);
    expect(res.headers.get('Access-Control-Allow-Origin')).toBe('*');
    expect(res.headers.get('Access-Control-Allow-Methods')).toContain('GET');
  });

  it('every response carries CORS headers', async () => {
    mockFetch(200, [fmpRecord()]);
    const res = await handleRequest(req('/lookup?t=AAPL'), makeEnv());
    expect(res.headers.get('Access-Control-Allow-Origin')).toBe('*');
  });

  it('unknown path returns 404 error envelope', async () => {
    const res = await handleRequest(req('/nope'), makeEnv());
    expect(res.status).toBe(404);
    expect((await res.json()).error).toBe('not_found');
  });
});

describe('/health', () => {
  it('returns status ok and kv_ok true when KV responds', async () => {
    const res = await handleRequest(req('/health'), makeEnv());
    const body = await res.json();
    expect(body.status).toBe('ok');
    expect(body.kv_ok).toBe(true);
    expect(body.timestamp).toBeTruthy();
  });

  it('reports kv_ok false when KV throws', async () => {
    const kv = makeKV();
    kv.get = vi.fn(async () => { throw new Error('kv down'); });
    const res = await handleRequest(req('/health'), makeEnv(kv));
    expect((await res.json()).kv_ok).toBe(false);
  });
});

describe('/lookup validation', () => {
  it('missing symbol returns missing_symbol', async () => {
    const res = await handleRequest(req('/lookup'), makeEnv());
    expect((await res.json()).error).toBe('missing_symbol');
  });

  it('lowercases input to uppercase symbol for the FMP call + KV key', async () => {
    mockFetch(200, [fmpRecord()]);
    const kv = makeKV();
    await handleRequest(req('/lookup?t=aapl'), makeEnv(kv));
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('symbol=AAPL'),
      expect.anything(),
    );
    expect(kv._store.has('AAPL')).toBe(true);
  });
});

describe('cache behavior', () => {
  it('cache hit skips FMP and returns cached value', async () => {
    global.fetch = vi.fn();
    const cached = { symbol: 'AAPL', finviz_industry: 'Consumer Electronics', cached_at: 'X' };
    const kv = makeKV({ AAPL: JSON.stringify(cached) });
    const res = await handleRequest(req('/lookup?t=AAPL'), makeEnv(kv));
    const body = await res.json();
    expect(body.cached_at).toBe('X');
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('cache miss calls FMP, writes KV with TTL, returns mapped result', async () => {
    mockFetch(200, [fmpRecord()]);
    const kv = makeKV();
    const res = await handleRequest(req('/lookup?t=AAPL'), makeEnv(kv));
    const body = await res.json();
    expect(body.finviz_industry).toBe('Consumer Electronics');
    expect(kv.put).toHaveBeenCalledWith('AAPL', expect.any(String), { expirationTtl: 2592000 });
  });

  it('does not cache lookup errors', async () => {
    mockFetch(200, []); // unknown ticker
    const kv = makeKV();
    await handleRequest(req('/lookup?t=FAKEXYZ'), makeEnv(kv));
    expect(kv.put).not.toHaveBeenCalled();
  });
});

describe('FMP field mapping (stable/profile schema)', () => {
  it('maps marketCap (raw) to market_cap_b in billions', async () => {
    mockFetch(200, [fmpRecord({ marketCap: 3200000000000 })]);
    const res = await handleRequest(req('/lookup?t=AAPL'), makeEnv());
    expect((await res.json()).market_cap_b).toBe(3200);
  });

  it('applies taxonomy: Technology / Consumer Electronics with confidence', async () => {
    mockFetch(200, [fmpRecord()]);
    const body = await (await handleRequest(req('/lookup?t=AAPL'), makeEnv())).json();
    expect(body.finviz_sector).toBe('Technology');
    expect(body.finviz_industry).toBe('Consumer Electronics');
    expect(body.industry_confidence).toBe(1);
  });

  it('normalizes name-variant industry (Chemicals - Specialty → Specialty Chemicals)', async () => {
    mockFetch(200, [fmpRecord({ sector: 'Basic Materials', industry: 'Chemicals - Specialty' })]);
    const body = await (await handleRequest(req('/lookup?t=SHW'), makeEnv())).json();
    expect(body.finviz_industry).toBe('Specialty Chemicals');
    expect(body.industry_confidence).toBeLessThan(1);
  });

  it('unmapped industry still resolves sector via fallback (Financial Services → Financial)', async () => {
    mockFetch(200, [fmpRecord({ sector: 'Financial Services', industry: 'Totally Unknown Industry' })]);
    const body = await (await handleRequest(req('/lookup?t=XYZ'), makeEnv())).json();
    expect(body.finviz_industry).toBe(''); // unmapped → empty string
    expect(body.finviz_sector).toBe('Financial'); // sector fallback
  });

  it('passes through ETF/ADR/fund flags', async () => {
    mockFetch(200, [fmpRecord({ isEtf: true, isAdr: true, isFund: false })]);
    const body = await (await handleRequest(req('/lookup?t=SPY'), makeEnv())).json();
    expect(body.is_etf).toBe(true);
    expect(body.is_adr).toBe(true);
    expect(body.is_fund).toBe(false);
  });
});

describe('/stats', () => {
  it('returns date and fmp_calls_today=0 when no counter key exists', async () => {
    const res = await handleRequest(req('/stats'), makeEnv());
    const body = await res.json();
    expect(body.fmp_calls_today).toBe(0);
    expect(body.date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it('reflects fmp_calls_today incremented by a cache-miss lookup', async () => {
    mockFetch(200, [fmpRecord()]);
    const kv = makeKV();
    const env = makeEnv(kv);
    await handleRequest(req('/lookup?t=AAPL'), env);
    const res = await handleRequest(req('/stats'), env);
    const body = await res.json();
    expect(body.fmp_calls_today).toBe(1);
  });

  it('does not increment counter on cache hit', async () => {
    global.fetch = vi.fn();
    const cached = { symbol: 'AAPL', finviz_industry: 'Consumer Electronics', cached_at: 'X' };
    const kv = makeKV({ AAPL: JSON.stringify(cached) });
    const env = makeEnv(kv);
    await handleRequest(req('/lookup?t=AAPL'), env);
    const res = await handleRequest(req('/stats'), env);
    expect((await res.json()).fmp_calls_today).toBe(0);
  });
});

describe('DELETE /cache', () => {
  it('deletes the KV entry for the given ticker', async () => {
    const cached = { symbol: 'AAPL', finviz_industry: 'Consumer Electronics' };
    const kv = makeKV({ AAPL: JSON.stringify(cached) });
    const env = makeEnv(kv);
    const res = await handleRequest(
      new Request('https://worker.example.dev/cache?t=AAPL', { method: 'DELETE' }),
      env,
    );
    const body = await res.json();
    expect(body.deleted).toBe('AAPL');
    expect(kv.delete).toHaveBeenCalledWith('AAPL');
  });

  it('returns missing_symbol when t param is absent', async () => {
    const res = await handleRequest(
      new Request('https://worker.example.dev/cache', { method: 'DELETE' }),
      makeEnv(),
    );
    expect((await res.json()).error).toBe('missing_symbol');
  });

  it('uppercases the ticker before deleting', async () => {
    const kv = makeKV();
    await handleRequest(
      new Request('https://worker.example.dev/cache?t=tsla', { method: 'DELETE' }),
      makeEnv(kv),
    );
    expect(kv.delete).toHaveBeenCalledWith('TSLA');
  });
});

describe('ETF override layer', () => {
  it('COPX: thematic ETF → Copper / Basic Materials with etf_override source', async () => {
    mockFetch(200, [fmpRecord({
      symbol: 'COPX',
      sector: 'Financial Services',
      industry: 'Asset Management',
      isEtf: true,
    })]);
    const body = await (await handleRequest(req('/lookup?t=COPX'), makeEnv())).json();
    expect(body.finviz_industry).toBe('Copper');
    expect(body.finviz_sector).toBe('Basic Materials');
    expect(body.classification_source).toBe('etf_override');
    expect(body.etf_kind).toBe('thematic');
    expect(body.industry_confidence).toBeNull();
  });

  it('ITA: thematic ETF → Aerospace & Defense / Industrials', async () => {
    mockFetch(200, [fmpRecord({
      symbol: 'ITA',
      sector: 'Financial Services',
      industry: 'Asset Management',
      isEtf: true,
    })]);
    const body = await (await handleRequest(req('/lookup?t=ITA'), makeEnv())).json();
    expect(body.finviz_industry).toBe('Aerospace & Defense');
    expect(body.finviz_sector).toBe('Industrials');
    expect(body.classification_source).toBe('etf_override');
    expect(body.etf_kind).toBe('thematic');
  });

  it('XLE: sector ETF → Energy sector, blank finviz_industry', async () => {
    mockFetch(200, [fmpRecord({
      symbol: 'XLE',
      sector: 'Financial Services',
      industry: 'Asset Management',
      isEtf: true,
    })]);
    const body = await (await handleRequest(req('/lookup?t=XLE'), makeEnv())).json();
    expect(body.finviz_industry).toBe('');
    expect(body.finviz_sector).toBe('Energy');
    expect(body.classification_source).toBe('etf_override');
    expect(body.etf_kind).toBe('sector');
  });

  it('SPY: diversified ETF → both fields blank with diversified kind', async () => {
    mockFetch(200, [fmpRecord({
      symbol: 'SPY',
      sector: 'Financial Services',
      industry: 'Asset Management',
      isEtf: true,
    })]);
    const body = await (await handleRequest(req('/lookup?t=SPY'), makeEnv())).json();
    expect(body.finviz_industry).toBe('');
    expect(body.finviz_sector).toBe('');
    expect(body.classification_source).toBe('etf_override');
    expect(body.etf_kind).toBe('diversified');
  });

  it('AAPL (non-ETF): unchanged, classification_source = fmp_taxonomy', async () => {
    mockFetch(200, [fmpRecord()]);
    const body = await (await handleRequest(req('/lookup?t=AAPL'), makeEnv())).json();
    expect(body.finviz_industry).toBe('Consumer Electronics');
    expect(body.finviz_sector).toBe('Technology');
    expect(body.classification_source).toBe('fmp_taxonomy');
    expect(body.etf_kind).toBeNull();
    expect(body.industry_confidence).not.toBeNull();
  });

  it('unlisted ETF (isEtf:true but not in overrides) falls back to fmp_taxonomy', async () => {
    mockFetch(200, [fmpRecord({
      symbol: 'UNKNWNETF',
      sector: 'Financial Services',
      industry: 'Asset Management',
      isEtf: true,
    })]);
    const body = await (await handleRequest(req('/lookup?t=UNKNWNETF'), makeEnv())).json();
    expect(body.classification_source).toBe('fmp_taxonomy');
    expect(body.etf_kind).toBeNull();
    expect(body.industry_confidence).not.toBeNull();
  });

  it('fmp_sector and fmp_industry raw fields are always present', async () => {
    mockFetch(200, [fmpRecord({
      symbol: 'COPX',
      sector: 'Financial Services',
      industry: 'Asset Management',
      isEtf: true,
    })]);
    const body = await (await handleRequest(req('/lookup?t=COPX'), makeEnv())).json();
    expect(body.fmp_sector).toBe('Financial Services');
    expect(body.fmp_industry).toBe('Asset Management');
  });
});

describe('FMP error handling', () => {
  it('unknown ticker (empty array) → ticker_not_found', async () => {
    mockFetch(200, []);
    const body = await (await handleRequest(req('/lookup?t=FAKEXYZ'), makeEnv())).json();
    expect(body.error).toBe('ticker_not_found');
  });

  it('HTTP 429 → rate_limited', async () => {
    mockFetch(429, {});
    const body = await (await handleRequest(req('/lookup?t=AAPL'), makeEnv())).json();
    expect(body.error).toBe('rate_limited');
  });

  it('HTTP 5xx → fmp_unavailable', async () => {
    mockFetch(503, {});
    const body = await (await handleRequest(req('/lookup?t=AAPL'), makeEnv())).json();
    expect(body.error).toBe('fmp_unavailable');
  });

  it('network failure / timeout → fmp_timeout', async () => {
    global.fetch = vi.fn(async () => { throw new Error('aborted'); });
    const body = await (await handleRequest(req('/lookup?t=AAPL'), makeEnv())).json();
    expect(body.error).toBe('fmp_timeout');
  });

  it('missing FMP_API_KEY → internal_error', async () => {
    const env = makeEnv();
    delete env.FMP_API_KEY;
    const body = await (await handleRequest(req('/lookup?t=AAPL'), env)).json();
    expect(body.error).toBe('internal_error');
  });

  it('all error responses are HTTP 200 (front-ends read body.error)', async () => {
    mockFetch(429, {});
    const res = await handleRequest(req('/lookup?t=AAPL'), makeEnv());
    expect(res.status).toBe(200);
  });
});
