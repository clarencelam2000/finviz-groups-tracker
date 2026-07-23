import { describe, it, expect, vi, afterEach } from 'vitest';
import worker, {
  dispatchCollect,
  dispatchWorkflow,
  workflowForCron,
  handleRequest,
} from '../src/index.js';

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

describe('workflowForCron — cron routing', () => {
  it('routes the picks cron to picks', () => {
    expect(workflowForCron('31 22 * * 2-6')).toBe('picks');
  });

  it('routes every collect cron to collect', () => {
    for (const cron of ['01 21 * * 2-6', '48 19 * * 2-6']) {
      expect(workflowForCron(cron)).toBe('collect');
    }
  });

  it('defaults an unknown cron to collect (safe default)', () => {
    expect(workflowForCron('0 0 * * *')).toBe('collect');
    expect(workflowForCron(undefined)).toBe('collect');
  });
});

describe('dispatchWorkflow — GitHub call shape', () => {
  it('POSTs to the collect.yml dispatches endpoint with the configured ref', async () => {
    mockFetch(204);
    const env = makeEnv();
    await dispatchWorkflow(env, '48 19 * * 2-6', 'collect');

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [url, opts] = global.fetch.mock.calls[0];
    expect(url).toBe(
      'https://api.github.com/repos/clarencelam2000/finviz-groups-tracker/actions/workflows/collect.yml/dispatches',
    );
    expect(opts.method).toBe('POST');
    expect(JSON.parse(opts.body)).toEqual({ ref: 'claude/elegant-babbage-hlxnfy' });
  });

  it('POSTs to the collect_picks.yml dispatches endpoint for picks', async () => {
    mockFetch(204);
    await dispatchWorkflow(makeEnv(), '31 22 * * 2-6', 'picks');
    const [url] = global.fetch.mock.calls[0];
    expect(url).toBe(
      'https://api.github.com/repos/clarencelam2000/finviz-groups-tracker/actions/workflows/collect_picks.yml/dispatches',
    );
  });

  it('sends the required GitHub API headers', async () => {
    mockFetch(204);
    await dispatchWorkflow(makeEnv(), '49 13 * * 2-6', 'collect');
    const [, opts] = global.fetch.mock.calls[0];
    expect(opts.headers.Authorization).toBe('Bearer test-token');
    expect(opts.headers.Accept).toBe('application/vnd.github+json');
    expect(opts.headers['User-Agent']).toBe('finviz-cron-dispatcher');
    expect(opts.headers['X-GitHub-Api-Version']).toBe('2022-11-28');
  });

  it('records a successful (204) collect dispatch under last_dispatch_collect', async () => {
    mockFetch(204);
    const kv = makeKV();
    const record = await dispatchWorkflow(makeEnv(kv), '51 14 * * 2-6', 'collect');
    expect(record.ok).toBe(true);
    expect(record.status).toBe(204);
    expect(record.error).toBe(null);
    expect(record.cron).toBe('51 14 * * 2-6');
    expect(record.workflow).toBe('collect');
    const stored = JSON.parse(kv._store.get('last_dispatch_collect'));
    expect(stored.ok).toBe(true);
    expect(stored.ref).toBe('claude/elegant-babbage-hlxnfy');
  });

  it('records a picks dispatch under last_dispatch_picks, not the collect key', async () => {
    mockFetch(204);
    const kv = makeKV();
    const record = await dispatchWorkflow(makeEnv(kv), '31 22 * * 2-6', 'picks');
    expect(record.workflow).toBe('picks');
    expect(kv._store.has('last_dispatch_picks')).toBe(true);
    expect(kv._store.has('last_dispatch_collect')).toBe(false);
  });

  it('records a non-204 response as a failure but does not throw', async () => {
    mockFetch(422);
    const kv = makeKV();
    const record = await dispatchWorkflow(makeEnv(kv), '48 19 * * 2-6', 'collect');
    expect(record.ok).toBe(false);
    expect(record.status).toBe(422);
    expect(record.error).toBe('github_422');
    expect(JSON.parse(kv._store.get('last_dispatch_collect')).ok).toBe(false);
  });

  it('handles a fetch rejection (network failure) gracefully', async () => {
    global.fetch = vi.fn(async () => { throw new Error('network down'); });
    const kv = makeKV();
    const record = await dispatchWorkflow(makeEnv(kv), '49 13 * * 2-6', 'collect');
    expect(record.ok).toBe(false);
    expect(record.error).toBe('fetch_failed');
    expect(kv.put).toHaveBeenCalled();
  });

  it('does not call GitHub when the token is missing', async () => {
    global.fetch = vi.fn();
    const env = makeEnv();
    delete env.GITHUB_DISPATCH_TOKEN;
    const record = await dispatchWorkflow(env, '48 19 * * 2-6', 'collect');
    expect(global.fetch).not.toHaveBeenCalled();
    expect(record.error).toBe('missing_token');
    expect(record.ok).toBe(false);
  });

  it('does not throw if the KV write fails', async () => {
    mockFetch(204);
    const kv = makeKV();
    kv.put = vi.fn(async () => { throw new Error('kv down'); });
    const record = await dispatchWorkflow(makeEnv(kv), '48 19 * * 2-6', 'collect');
    expect(record.ok).toBe(true); // dispatch still succeeded
  });

  it('dispatchCollect back-compat wrapper dispatches collect.yml', async () => {
    mockFetch(204);
    const kv = makeKV();
    const record = await dispatchCollect(makeEnv(kv), '48 19 * * 2-6');
    expect(record.workflow).toBe('collect');
    expect(global.fetch.mock.calls[0][0]).toContain('/collect.yml/');
  });
});

describe('scheduled handler', () => {
  it('routes a collect cron to collect.yml and records it', async () => {
    mockFetch(204);
    const kv = makeKV();
    await worker.scheduled({ cron: '48 19 * * 2-6' }, makeEnv(kv), {});
    expect(global.fetch.mock.calls[0][0]).toContain('/collect.yml/');
    expect(JSON.parse(kv._store.get('last_dispatch_collect')).cron).toBe('48 19 * * 2-6');
  });

  it('routes the picks cron to collect_picks.yml and records it', async () => {
    mockFetch(204);
    const kv = makeKV();
    await worker.scheduled({ cron: '31 22 * * 2-6' }, makeEnv(kv), {});
    expect(global.fetch.mock.calls[0][0]).toContain('/collect_picks.yml/');
    expect(JSON.parse(kv._store.get('last_dispatch_picks')).cron).toBe('31 22 * * 2-6');
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

  it('GET /last returns per-workflow records plus the legacy key', async () => {
    const collectRec = { ts: 'X', status: 204, ok: true, error: null, cron: '48 19 * * 2-6' };
    const picksRec = { ts: 'Y', status: 204, ok: true, error: null, cron: '31 22 * * 2-6' };
    const legacyRec = { ts: 'Z', status: 204, ok: true };
    const kv = makeKV({
      last_dispatch_collect: JSON.stringify(collectRec),
      last_dispatch_picks: JSON.stringify(picksRec),
      last_dispatch: JSON.stringify(legacyRec),
    });
    const res = await handleRequest(req('/last'), makeEnv(kv));
    const body = await res.json();
    expect(body.last_dispatch.collect).toEqual(collectRec);
    expect(body.last_dispatch.picks).toEqual(picksRec);
    expect(body.last_dispatch.legacy).toEqual(legacyRec);
  });

  it('GET /last returns nulls when nothing has fired yet', async () => {
    const res = await handleRequest(req('/last'), makeEnv());
    const body = await res.json();
    expect(body.last_dispatch.collect).toBe(null);
    expect(body.last_dispatch.picks).toBe(null);
    expect(body.last_dispatch.legacy).toBe(null);
  });

  it('unknown path returns 404 error envelope', async () => {
    const res = await handleRequest(req('/nope'), makeEnv());
    expect(res.status).toBe(404);
    expect((await res.json()).error).toBe('not_found');
  });
});
