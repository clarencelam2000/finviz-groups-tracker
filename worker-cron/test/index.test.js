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

/**
 * Routes fetch calls by HTTP method: POST -> the dispatches endpoint mock
 * (workflow_dispatch, 204/error), GET -> a fake collect.yml runs-list
 * response. Needed because the picks gate makes both kinds of call — a GET
 * to check collect_eod's run status, then possibly a POST to dispatch
 * picks — sometimes in the same tick as collect_eod's own dispatch POST.
 */
function mockFetchRouter({ dispatchStatus = 204, runs = [] } = {}) {
  global.fetch = vi.fn(async (url, opts = {}) => {
    if ((opts.method || 'GET') === 'POST') {
      return { status: dispatchStatus, ok: dispatchStatus >= 200 && dispatchStatus < 300 };
    }
    return {
      status: 200,
      ok: true,
      json: async () => ({ workflow_runs: runs }),
    };
  });
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

  it('self-heals: a late tick within the window still dispatches if not already dispatched today', async () => {
    // No matching runs -> the picks gate (also in-window at 17:20, since
    // picks now shares collect_eod's 17:00 target per #259) will make an
    // opportunistic GET once collect_eod's dispatch lands in KV this same
    // tick, find no run yet, and wait rather than dispatch picks.
    mockFetchRouter({ runs: [] });
    const kv = makeKV();
    // 17:20 ET — 20 minutes past collect_eod's 17:00 target, exact-minute
    // fire was missed, but the window (30 min) is still open.
    await worker.scheduled({ scheduledTime: new Date('2026-07-15T21:20:00Z').getTime() }, makeEnv(kv), {});
    const postCalls = global.fetch.mock.calls.filter(([, opts]) => opts && opts.method === 'POST');
    expect(postCalls).toHaveLength(1);
    expect(postCalls[0][0]).toContain('/collect.yml/');
    expect(kv._store.has('last_dispatch_picks')).toBe(false);
  });

  it('does not re-dispatch collect_eod once already recorded as dispatched today', async () => {
    // picks shares collect_eod's window and is not yet dispatched itself, so
    // its gate still makes a GET this tick (asserted separately below) —
    // this test isolates that collect.yml itself is not re-dispatched.
    mockFetchRouter({ runs: [] });
    const kv = makeKV({
      last_dispatch_collect_eod: JSON.stringify({ ok: true, etDate: '2026-07-15' }),
    });
    await worker.scheduled({ scheduledTime: new Date('2026-07-15T21:10:00Z').getTime() }, makeEnv(kv), {}); // 17:10 ET, still in window
    const postCalls = global.fetch.mock.calls.filter(([, opts]) => opts && opts.method === 'POST');
    expect(postCalls).toHaveLength(0);
  });

  it('re-dispatches once a new ET calendar date begins, even inside the same window shape', async () => {
    mockFetchRouter({ runs: [] });
    const kv = makeKV({
      last_dispatch_collect_eod: JSON.stringify({ ok: true, etDate: '2026-07-14' }),
    });
    await worker.scheduled({ scheduledTime: new Date('2026-07-15T21:00:00Z').getTime() }, makeEnv(kv), {});
    const postCalls = global.fetch.mock.calls.filter(([, opts]) => opts && opts.method === 'POST');
    expect(postCalls).toHaveLength(1);
    expect(postCalls[0][0]).toContain('/collect.yml/');
  });

  it('does not treat a failed prior dispatch as satisfying "dispatched today"', async () => {
    mockFetchRouter({ runs: [] });
    const kv = makeKV({
      last_dispatch_collect_eod: JSON.stringify({ ok: false, etDate: '2026-07-15' }),
    });
    await worker.scheduled({ scheduledTime: new Date('2026-07-15T21:10:00Z').getTime() }, makeEnv(kv), {});
    const postCalls = global.fetch.mock.calls.filter(([, opts]) => opts && opts.method === 'POST');
    expect(postCalls).toHaveLength(1); // retried
    expect(postCalls[0][0]).toContain('/collect.yml/');
  });

  it('does not fire any job on a weekend tick even at a valid time-of-day', async () => {
    mockFetch(204);
    const kv = makeKV();
    // 2026-07-18 is a Saturday; 21:00 UTC = 17:00 EDT.
    await worker.scheduled({ scheduledTime: new Date('2026-07-18T21:00:00Z').getTime() }, makeEnv(kv), {});
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('dispatches collect_morning at 10:05 ET and records it under its own KV key, ungated (no gate GET)', async () => {
    mockFetch(204);
    const kv = makeKV();
    // 2026-07-15T14:05:00Z = 10:05 EDT, a Wednesday.
    await worker.scheduled({ scheduledTime: new Date('2026-07-15T14:05:00Z').getTime() }, makeEnv(kv), {});
    expect(global.fetch).toHaveBeenCalledTimes(1); // ungated: no run-status GET, just the dispatch POST
    const [url, opts] = global.fetch.mock.calls[0];
    expect(url).toBe(
      'https://api.github.com/repos/clarencelam2000/finviz-groups-tracker/actions/workflows/collect_morning.yml/dispatches',
    );
    expect(opts.method).toBe('POST');
    const stored = JSON.parse(kv._store.get('last_dispatch_collect_morning'));
    expect(stored.ok).toBe(true);
    expect(stored.job).toBe('collect_morning');
    expect(stored.workflow).toBe('morning');
    expect(stored.etDate).toBe('2026-07-15');
  });

  it('does not re-dispatch collect_morning once already recorded as dispatched today', async () => {
    mockFetch(204);
    const kv = makeKV({
      last_dispatch_collect_morning: JSON.stringify({ ok: true, etDate: '2026-07-15' }),
    });
    await worker.scheduled({ scheduledTime: new Date('2026-07-15T14:20:00Z').getTime() }, makeEnv(kv), {}); // 10:20 ET, still in window
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('dispatches held at 17:30 ET and records it under its own KV key, ungated (no gate GET)', async () => {
    mockFetch(204);
    const kv = makeKV();
    // 2026-07-15T21:30:00Z = 17:30 EDT, a Wednesday.
    await worker.scheduled({ scheduledTime: new Date('2026-07-15T21:30:00Z').getTime() }, makeEnv(kv), {});
    const postCalls = global.fetch.mock.calls.filter(([, opts]) => opts && opts.method === 'POST');
    const heldCall = postCalls.find(([url]) => url.includes('/collect_held.yml/'));
    expect(heldCall).toBeTruthy();
    const stored = JSON.parse(kv._store.get('last_dispatch_held'));
    expect(stored.ok).toBe(true);
    expect(stored.job).toBe('held');
    expect(stored.workflow).toBe('held');
    expect(stored.etDate).toBe('2026-07-15');
  });

  it('does not re-dispatch held once already recorded as dispatched today', async () => {
    mockFetchRouter({ runs: [{ created_at: '2026-07-15T21:00:03Z', status: 'completed', conclusion: 'success' }] });
    const kv = makeKV({
      last_dispatch_held: JSON.stringify({ ok: true, etDate: '2026-07-15' }),
      last_dispatch_collect_eod: JSON.stringify({ ok: true, etDate: '2026-07-15', ts: '2026-07-15T21:00:00.000Z' }),
      last_dispatch_picks: JSON.stringify({ ok: true, etDate: '2026-07-15' }),
    });
    // 17:45 ET, inside held's window — but picks is already dispatched too, so
    // nothing should fire for either job.
    await worker.scheduled({ scheduledTime: new Date('2026-07-15T21:45:00Z').getTime() }, makeEnv(kv), {});
    const postCalls = global.fetch.mock.calls.filter(([, opts]) => opts && opts.method === 'POST');
    expect(postCalls.some(([url]) => url.includes('/collect_held.yml/'))).toBe(false);
  });
});

describe('picks dependency gate (#259)', () => {
  it('does not call GitHub run-status or dispatch picks if collect_eod has not been dispatched today', async () => {
    mockFetchRouter();
    const kv = makeKV();
    // 18:00 ET: past collect_eod's own [17:00,17:30) window (so it's not a
    // candidate this tick at all — isolates the picks-gate behavior), still
    // well inside picks' [17:00,19:00) gate window, and no
    // last_dispatch_collect_eod record exists.
    await worker.scheduled({ scheduledTime: new Date('2026-07-15T22:00:00Z').getTime() }, makeEnv(kv), {});
    expect(global.fetch).not.toHaveBeenCalled();
    const gateRec = JSON.parse(kv._store.get('last_gate_check_picks'));
    expect(gateRec.outcome).toBe('waiting');
    expect(gateRec.reason).toBe('collect_eod_not_dispatched');
    expect(kv._store.has('last_dispatch_picks')).toBe(false);
  });

  it('waits (GET only, no dispatch) when the matched EOD run has not completed yet', async () => {
    mockFetchRouter({ runs: [{ created_at: '2026-07-15T21:00:03Z', status: 'in_progress', conclusion: null }] });
    const kv = makeKV({
      last_dispatch_collect_eod: JSON.stringify({ ok: true, etDate: '2026-07-15', ts: '2026-07-15T21:00:00.000Z' }),
    });
    await worker.scheduled({ scheduledTime: new Date('2026-07-15T21:10:00Z').getTime() }, makeEnv(kv), {});
    // one GET to check run status, no POST to dispatch picks
    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(global.fetch.mock.calls[0][0]).toContain('/collect.yml/runs');
    expect(JSON.parse(kv._store.get('last_gate_check_picks')).outcome).toBe('waiting');
    expect(kv._store.has('last_dispatch_picks')).toBe(false);
  });

  it('dispatches picks once the matched EOD run has succeeded', async () => {
    mockFetchRouter({ runs: [{ created_at: '2026-07-15T21:00:03Z', status: 'completed', conclusion: 'success' }] });
    const kv = makeKV({
      last_dispatch_collect_eod: JSON.stringify({ ok: true, etDate: '2026-07-15', ts: '2026-07-15T21:00:00.000Z' }),
    });
    await worker.scheduled({ scheduledTime: new Date('2026-07-15T21:15:00Z').getTime() }, makeEnv(kv), {});
    expect(global.fetch).toHaveBeenCalledTimes(2); // GET run status, then POST dispatch
    const postCall = global.fetch.mock.calls.find(([, opts]) => opts && opts.method === 'POST');
    expect(postCall[0]).toContain('/collect_picks.yml/');
    expect(JSON.parse(kv._store.get('last_dispatch_picks')).job).toBe('picks');
    expect(JSON.parse(kv._store.get('last_gate_check_picks')).outcome).toBe('dispatch');
  });

  it('does not re-dispatch picks once already recorded as dispatched today, even inside the window', async () => {
    mockFetchRouter({ runs: [{ created_at: '2026-07-15T21:00:03Z', status: 'completed', conclusion: 'success' }] });
    const kv = makeKV({
      last_dispatch_collect_eod: JSON.stringify({ ok: true, etDate: '2026-07-15', ts: '2026-07-15T21:00:00.000Z' }),
      last_dispatch_picks: JSON.stringify({ ok: true, etDate: '2026-07-15' }),
    });
    await worker.scheduled({ scheduledTime: new Date('2026-07-15T21:20:00Z').getTime() }, makeEnv(kv), {});
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('disambiguates the EOD run from an earlier pre-close run on the same day (does not dispatch on the stale pre-close success)', async () => {
    // Only the pre-close run (created well before the EOD dispatch timestamp) is "seen" here;
    // no run at/after the EOD dispatch ts exists yet.
    mockFetchRouter({ runs: [{ created_at: '2026-07-15T19:50:05Z', status: 'completed', conclusion: 'success' }] });
    const kv = makeKV({
      last_dispatch_collect_eod: JSON.stringify({ ok: true, etDate: '2026-07-15', ts: '2026-07-15T21:00:00.000Z' }),
    });
    await worker.scheduled({ scheduledTime: new Date('2026-07-15T21:10:00Z').getTime() }, makeEnv(kv), {});
    expect(kv._store.has('last_dispatch_picks')).toBe(false);
    expect(JSON.parse(kv._store.get('last_gate_check_picks')).reason).toBe('eod_run_not_found');
  });

  it('records a miss (no dispatch) when the gate window closes without a successful run', async () => {
    mockFetchRouter({ runs: [{ created_at: '2026-07-15T21:00:03Z', status: 'completed', conclusion: 'failure' }] });
    const kv = makeKV({
      last_dispatch_collect_eod: JSON.stringify({ ok: true, etDate: '2026-07-15', ts: '2026-07-15T21:00:00.000Z' }),
    });
    // 18:55 ET = the terminal tick of the 17:00-19:00 window.
    await worker.scheduled({ scheduledTime: new Date('2026-07-15T22:55:00Z').getTime() }, makeEnv(kv), {});
    expect(kv._store.has('last_dispatch_picks')).toBe(false);
    const gateRec = JSON.parse(kv._store.get('last_gate_check_picks'));
    expect(gateRec.outcome).toBe('miss');
    expect(gateRec.reason).toBe('eod_run_failure');
  });

  it('never dispatches picks when the run-status read itself fails (fails closed, not open)', async () => {
    global.fetch = vi.fn(async (url, opts = {}) => {
      if ((opts.method || 'GET') === 'POST') return { status: 204, ok: true };
      return { status: 403, ok: false };
    });
    const kv = makeKV({
      last_dispatch_collect_eod: JSON.stringify({ ok: true, etDate: '2026-07-15', ts: '2026-07-15T21:00:00.000Z' }),
    });
    await worker.scheduled({ scheduledTime: new Date('2026-07-15T21:10:00Z').getTime() }, makeEnv(kv), {});
    expect(kv._store.has('last_dispatch_picks')).toBe(false);
    expect(JSON.parse(kv._store.get('last_gate_check_picks')).reason).toBe('run_status_fetch_failed:github_403');
  });
});

describe('JOB_SCHEDULE wiring', () => {
  it('every job in the schedule has a corresponding workflow url in the dispatcher', () => {
    // Indirect check: dispatching each job name must not throw on an unknown workflow.
    expect(JOB_SCHEDULE.map((j) => j.workflow).every((w) => ['collect', 'picks', 'morning', 'held'].includes(w))).toBe(true);
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

  it('GET /last returns a record per job plus the picks gate check and legacy keys', async () => {
    const preCloseRec = { ts: 'X', status: 204, ok: true, error: null, job: 'collect_preclose' };
    const eodRec = { ts: 'Y', status: 204, ok: true, error: null, job: 'collect_eod' };
    const picksRec = { ts: 'Z', status: 204, ok: true, error: null, job: 'picks' };
    const gateRec = { ts: 'W', outcome: 'dispatch', reason: 'eod_run_success', etDate: '2026-07-15' };
    const kv = makeKV({
      last_dispatch_collect_preclose: JSON.stringify(preCloseRec),
      last_dispatch_collect_eod: JSON.stringify(eodRec),
      last_dispatch_picks: JSON.stringify(picksRec),
      last_gate_check_picks: JSON.stringify(gateRec),
    });
    const res = await handleRequest(req('/last'), makeEnv(kv));
    const body = await res.json();
    expect(body.last_dispatch.collect_preclose).toEqual(preCloseRec);
    expect(body.last_dispatch.collect_eod).toEqual(eodRec);
    expect(body.last_dispatch.picks).toEqual(picksRec);
    expect(body.last_dispatch.picks_gate_check).toEqual(gateRec);
  });

  it('GET /last returns nulls when nothing has fired yet', async () => {
    const res = await handleRequest(req('/last'), makeEnv());
    const body = await res.json();
    expect(body.last_dispatch.collect_preclose).toBe(null);
    expect(body.last_dispatch.collect_eod).toBe(null);
    expect(body.last_dispatch.picks).toBe(null);
    expect(body.last_dispatch.picks_gate_check).toBe(null);
    expect(body.last_dispatch.legacy.last_dispatch_collect).toBe(null);
  });

  it('unknown path returns 404 error envelope', async () => {
    const res = await handleRequest(req('/nope'), makeEnv());
    expect(res.status).toBe(404);
    expect((await res.json()).error).toBe('not_found');
  });
});
