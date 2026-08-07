import { describe, it, expect, vi, afterEach } from 'vitest';
import worker, { dispatchJob, handleRequest } from '../src/index.js';
import { JOB_SCHEDULE } from '../src/routing.js';

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

describe('dispatchJob — GitHub call shape', () => {
  it('POSTs to the collect.yml dispatches endpoint with the configured ref', async () => {
    mockFetch(204);
    const env = makeEnv();
    await dispatchJob(env, 'collect_preclose', 'collect', '2026-07-15');

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [url, opts] = global.fetch.mock.calls[0];
    expect(url).toBe(
      'https://api.github.com/repos/clarencelam2000/finviz-groups-tracker/actions/workflows/collect.yml/dispatches',
    );
    expect(opts.method).toBe('POST');
    expect(JSON.parse(opts.body)).toEqual({ ref: 'claude/elegant-babbage-hlxnfy' });
  });

  it('POSTs to the collect_picks.yml dispatches endpoint for the picks job', async () => {
    mockFetch(204);
    await dispatchJob(makeEnv(), 'picks', 'picks', '2026-07-15');
    const [url] = global.fetch.mock.calls[0];
    expect(url).toBe(
      'https://api.github.com/repos/clarencelam2000/finviz-groups-tracker/actions/workflows/collect_picks.yml/dispatches',
    );
  });

  it('sends the required GitHub API headers', async () => {
    mockFetch(204);
    await dispatchJob(makeEnv(), 'collect_eod', 'collect', '2026-07-15');
    const [, opts] = global.fetch.mock.calls[0];
    expect(opts.headers.Authorization).toBe('Bearer test-token');
    expect(opts.headers.Accept).toBe('application/vnd.github+json');
    expect(opts.headers['User-Agent']).toBe('finviz-cron-dispatcher');
    expect(opts.headers['X-GitHub-Api-Version']).toBe('2022-11-28');
  });

  it('records a successful (204) dispatch under the job-specific KV key with its ET date', async () => {
    mockFetch(204);
    const kv = makeKV();
    const record = await dispatchJob(makeEnv(kv), 'collect_eod', 'collect', '2026-07-15');
    expect(record.ok).toBe(true);
    expect(record.status).toBe(204);
    expect(record.error).toBe(null);
    expect(record.job).toBe('collect_eod');
    expect(record.workflow).toBe('collect');
    expect(record.etDate).toBe('2026-07-15');
    const stored = JSON.parse(kv._store.get('last_dispatch_collect_eod'));
    expect(stored.ok).toBe(true);
    expect(stored.ref).toBe('claude/elegant-babbage-hlxnfy');
  });

  it('tracks collect_preclose and collect_eod under independent KV keys', async () => {
    mockFetch(204);
    const kv = makeKV();
    await dispatchJob(makeEnv(kv), 'collect_preclose', 'collect', '2026-07-15');
    expect(kv._store.has('last_dispatch_collect_preclose')).toBe(true);
    expect(kv._store.has('last_dispatch_collect_eod')).toBe(false);
  });

  it('records a picks dispatch under last_dispatch_picks, not a collect key', async () => {
    mockFetch(204);
    const kv = makeKV();
    const record = await dispatchJob(makeEnv(kv), 'picks', 'picks', '2026-07-15');
    expect(record.workflow).toBe('picks');
    expect(kv._store.has('last_dispatch_picks')).toBe(true);
    expect(kv._store.has('last_dispatch_collect_eod')).toBe(false);
  });

  it('records a non-204 response as a failure but does not throw', async () => {
    mockFetch(422);
    const kv = makeKV();
    const record = await dispatchJob(makeEnv(kv), 'collect_preclose', 'collect', '2026-07-15');
    expect(record.ok).toBe(false);
    expect(record.status).toBe(422);
    expect(record.error).toBe('github_422');
    expect(JSON.parse(kv._store.get('last_dispatch_collect_preclose')).ok).toBe(false);
  });

  it('handles a fetch rejection (network failure) gracefully', async () => {
    global.fetch = vi.fn(async () => { throw new Error('network down'); });
    const kv = makeKV();
    const record = await dispatchJob(makeEnv(kv), 'collect_eod', 'collect', '2026-07-15');
    expect(record.ok).toBe(false);
    expect(record.error).toBe('fetch_failed');
    expect(kv.put).toHaveBeenCalled();
  });

  it('does not call GitHub when the token is missing', async () => {
    global.fetch = vi.fn();
    const env = makeEnv();
    delete env.GITHUB_DISPATCH_TOKEN;
    const record = await dispatchJob(env, 'collect_eod', 'collect', '2026-07-15');
    expect(global.fetch).not.toHaveBeenCalled();
    expect(record.error).toBe('missing_token');
    expect(record.ok).toBe(false);
  });

  it('does not throw if the KV write fails', async () => {
    mockFetch(204);
    const kv = makeKV();
    kv.put = vi.fn(async () => { throw new Error('kv down'); });
    const record = await dispatchJob(makeEnv(kv), 'collect_eod', 'collect', '2026-07-15');
    expect(record.ok).toBe(true); // dispatch still succeeded
  });
});

describe('scheduled handler — single-tick routing (ADR-010)', () => {
  it('is a no-op (no fetch, no KV) on a tick outside every job window', async () => {
    mockFetch(204);
    const kv = makeKV();
    await worker.scheduled({ scheduledTime: new Date('2026-07-15T16:00:00Z').getTime() }, makeEnv(kv), {}); // 12:00 ET
    expect(global.fetch).not.toHaveBeenCalled();
    expect(kv.get).not.toHaveBeenCalled();
    expect(kv.put).not.toHaveBeenCalled();
  });

  it('dispatches collect_eod at its ET target and records it under its own KV key', async () => {
    mockFetch(204);
    const kv = makeKV();
    // 2026-07-15T21:00:00Z = 17:00 EDT, a Wednesday.
    await worker.scheduled({ scheduledTime: new Date('2026-07-15T21:00:00Z').getTime() }, makeEnv(kv), {});
    expect(global.fetch.mock.calls[0][0]).toContain('/collect.yml/');
    const stored = JSON.parse(kv._store.get('last_dispatch_collect_eod'));
    expect(stored.job).toBe('collect_eod');
    expect(stored.etDate).toBe('2026-07-15');
  });

  it('dispatches picks at its ET target to collect_picks.yml', async () => {
    mockFetch(204);
    const kv = makeKV();
    // 2026-07-15T22:30:00Z = 18:30 EDT.
    await worker.scheduled({ scheduledTime: new Date('2026-07-15T22:30:00Z').getTime() }, makeEnv(kv), {});
    expect(global.fetch.mock.calls[0][0]).toContain('/collect_picks.yml/');
    expect(JSON.parse(kv._store.get('last_dispatch_picks')).job).toBe('picks');
  });

  it('self-heals: a late tick within the window still dispatches if not already dispatched today', async () => {
    mockFetch(204);
    const kv = makeKV();
    // 17:20 ET — 20 minutes past collect_eod's 17:00 target, exact-minute
    // fire was missed, but the window (30 min) is still open.
    await worker.scheduled({ scheduledTime: new Date('2026-07-15T21:20:00Z').getTime() }, makeEnv(kv), {});
    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(global.fetch.mock.calls[0][0]).toContain('/collect.yml/');
  });

  it('does not re-dispatch a job already recorded as dispatched today', async () => {
    mockFetch(204);
    const kv = makeKV({
      last_dispatch_collect_eod: JSON.stringify({ ok: true, etDate: '2026-07-15' }),
    });
    await worker.scheduled({ scheduledTime: new Date('2026-07-15T21:10:00Z').getTime() }, makeEnv(kv), {}); // 17:10 ET, still in window
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('re-dispatches once a new ET calendar date begins, even inside the same window shape', async () => {
    mockFetch(204);
    const kv = makeKV({
      last_dispatch_collect_eod: JSON.stringify({ ok: true, etDate: '2026-07-14' }),
    });
    await worker.scheduled({ scheduledTime: new Date('2026-07-15T21:00:00Z').getTime() }, makeEnv(kv), {});
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  it('does not treat a failed prior dispatch as satisfying "dispatched today"', async () => {
    mockFetch(204);
    const kv = makeKV({
      last_dispatch_collect_eod: JSON.stringify({ ok: false, etDate: '2026-07-15' }),
    });
    await worker.scheduled({ scheduledTime: new Date('2026-07-15T21:10:00Z').getTime() }, makeEnv(kv), {});
    expect(global.fetch).toHaveBeenCalledTimes(1); // retried
  });

  it('does not fire any job on a weekend tick even at a valid time-of-day', async () => {
    mockFetch(204);
    const kv = makeKV();
    // 2026-07-18 is a Saturday; 21:00 UTC = 17:00 EDT.
    await worker.scheduled({ scheduledTime: new Date('2026-07-18T21:00:00Z').getTime() }, makeEnv(kv), {});
    expect(global.fetch).not.toHaveBeenCalled();
  });
});

describe('JOB_SCHEDULE wiring', () => {
  it('every job in the schedule has a corresponding workflow url in the dispatcher', () => {
    // Indirect check: dispatching each job name must not throw on an unknown workflow.
    expect(JOB_SCHEDULE.map((j) => j.workflow).every((w) => ['collect', 'picks'].includes(w))).toBe(true);
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

  it('GET /last returns a record per job plus legacy keys', async () => {
    const preCloseRec = { ts: 'X', status: 204, ok: true, error: null, job: 'collect_preclose' };
    const eodRec = { ts: 'Y', status: 204, ok: true, error: null, job: 'collect_eod' };
    const picksRec = { ts: 'Z', status: 204, ok: true, error: null, job: 'picks' };
    const kv = makeKV({
      last_dispatch_collect_preclose: JSON.stringify(preCloseRec),
      last_dispatch_collect_eod: JSON.stringify(eodRec),
      last_dispatch_picks: JSON.stringify(picksRec),
    });
    const res = await handleRequest(req('/last'), makeEnv(kv));
    const body = await res.json();
    expect(body.last_dispatch.collect_preclose).toEqual(preCloseRec);
    expect(body.last_dispatch.collect_eod).toEqual(eodRec);
    expect(body.last_dispatch.picks).toEqual(picksRec);
  });

  it('GET /last returns nulls when nothing has fired yet', async () => {
    const res = await handleRequest(req('/last'), makeEnv());
    const body = await res.json();
    expect(body.last_dispatch.collect_preclose).toBe(null);
    expect(body.last_dispatch.collect_eod).toBe(null);
    expect(body.last_dispatch.picks).toBe(null);
    expect(body.last_dispatch.legacy.last_dispatch_collect).toBe(null);
  });

  it('unknown path returns 404 error envelope', async () => {
    const res = await handleRequest(req('/nope'), makeEnv());
    expect(res.status).toBe(404);
    expect((await res.json()).error).toBe('not_found');
  });
});
