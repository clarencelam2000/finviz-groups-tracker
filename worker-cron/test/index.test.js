import { describe, it, expect, vi, afterEach } from 'vitest';
import worker, { dispatchCollect, handleRequest } from '../src/index.js';

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
  return {
    DISPATCH_LOG: kv,
    GITHUB_DISPATCH_TOKEN: 'test-token',
    DISPATCH_REF: 'claude/elegant-babbage-hlxnfy',
  };
}

function req(path, method = 'GET') {
  return new Request(`https://worker.example.dev${path}`, { method });
}

/** Mock fetch returning a Response-like object with the given status. */
function mockFetch(status = 204) {
  global.fetch = vi.fn(async () => ({ status, ok: status >= 200 && status < 300 }));
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('dispatchCollect — GitHub call shape', () => {
  it('POSTs to the collect.yml dispatches endpoint with the configured ref', async () => {
    mockFetch(204);
    const env = makeEnv();
    await dispatchCollect(env, '48 19 * * 1-5');

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [url, opts] = global.fetch.mock.calls[0];
    expect(url).toBe(
      'https://api.github.com/repos/clarencelam2000/finviz-groups-tracker/actions/workflows/collect.yml/dispatches',
    );
    expect(opts.method).toBe('POST');
    expect(JSON.parse(opts.body)).toEqual({ ref: 'claude/elegant-babbage-hlxnfy' });
  });

  it('sends the required GitHub API headers', async () => {
    mockFetch(204);
    await dispatchCollect(makeEnv(), '49 13 * * 1-5');
    const [, opts] = global.fetch.mock.calls[0];
    expect(opts.headers.Authorization).toBe('Bearer test-token');
    expect(opts.headers.Accept).toBe('application/vnd.github+json');
    expect(opts.headers['User-Agent']).toBe('finviz-cron-dispatcher');
    expect(opts.headers['X-GitHub-Api-Version']).toBe('2022-11-28');
  });

  it('records a successful (204) dispatch to KV', async () => {
    mockFetch(204);
    const kv = makeKV();
    const record = await dispatchCollect(makeEnv(kv), '51 14 * * 1-5');
    expect(record.ok).toBe(true);
    expect(record.status).toBe(204);
    expect(record.error).toBe(null);
    expect(record.cron).toBe('51 14 * * 1-5');
    const stored = JSON.parse(kv._store.get('last_dispatch'));
    expect(stored.ok).toBe(true);
    expect(stored.ref).toBe('claude/elegant-babbage-hlxnfy');
  });

  it('records a non-204 response as a failure but does not throw', async () => {
    mockFetch(422);
    const kv = makeKV();
    const record = await dispatchCollect(makeEnv(kv), '48 19 * * 1-5');
    expect(record.ok).toBe(false);
    expect(record.status).toBe(422);
    expect(record.error).toBe('github_422');
    expect(JSON.parse(kv._store.get('last_dispatch')).ok).toBe(false);
  });

  it('handles a fetch rejection (network failure) gracefully', async () => {
    global.fetch = vi.fn(async () => { throw new Error('network down'); });
    const kv = makeKV();
    const record = await dispatchCollect(makeEnv(kv), '49 13 * * 1-5');
    expect(record.ok).toBe(false);
    expect(record.error).toBe('fetch_failed');
    expect(kv.put).toHaveBeenCalled();
  });

  it('does not call GitHub when the token is missing', async () => {
    global.fetch = vi.fn();
    const env = makeEnv();
    delete env.GITHUB_DISPATCH_TOKEN;
    const record = await dispatchCollect(env, '48 19 * * 1-5');
    expect(global.fetch).not.toHaveBeenCalled();
    expect(record.error).toBe('missing_token');
    expect(record.ok).toBe(false);
  });

  it('does not throw if the KV write fails', async () => {
    mockFetch(204);
    const kv = makeKV();
    kv.put = vi.fn(async () => { throw new Error('kv down'); });
    const record = await dispatchCollect(makeEnv(kv), '48 19 * * 1-5');
    expect(record.ok).toBe(true); // dispatch still succeeded
  });
});

describe('scheduled handler', () => {
  it('passes event.cron through to the dispatch record', async () => {
    mockFetch(204);
    const kv = makeKV();
    await worker.scheduled({ cron: '48 19 * * 1-5' }, makeEnv(kv), {});
    expect(JSON.parse(kv._store.get('last_dispatch')).cron).toBe('48 19 * * 1-5');
  });
});

describe('fetch — debug endpoints', () => {
  it('GET /health returns ok with kv_ok true', async () => {
    const res = await handleRequest(req('/health'), makeEnv());
    const body = await res.json();
    expect(body.status).toBe('ok');
    expect(body.kv_ok).toBe(true);
  });

  it('GET /health reports kv_ok false when KV throws', async () => {
    const kv = makeKV();
    kv.get = vi.fn(async () => { throw new Error('kv down'); });
    const res = await handleRequest(req('/health'), makeEnv(kv));
    expect((await res.json()).kv_ok).toBe(false);
  });

  it('GET /last returns the stored dispatch record', async () => {
    const rec = { ts: 'X', status: 204, ok: true, error: null, cron: '48 19 * * 1-5' };
    const kv = makeKV({ last_dispatch: JSON.stringify(rec) });
    const res = await handleRequest(req('/last'), makeEnv(kv));
    expect((await res.json()).last_dispatch).toEqual(rec);
  });

  it('GET /last returns null when nothing has fired yet', async () => {
    const res = await handleRequest(req('/last'), makeEnv());
    expect((await res.json()).last_dispatch).toBe(null);
  });

  it('unknown path returns 404 error envelope', async () => {
    const res = await handleRequest(req('/nope'), makeEnv());
    expect(res.status).toBe(404);
    expect((await res.json()).error).toBe('not_found');
  });
});
