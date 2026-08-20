/**
 * Finviz Cron Dispatcher — Cloudflare Worker.
 *
 * Pure scheduler: ONE Cron Trigger (every-5-minutes, defined in wrangler.toml)
 * fires scheduled() every 5 minutes, all day, every day. All schedule logic —
 * which job (if any) is due — lives in code (src/routing.js), gated on
 * Eastern wall-clock time, not on the cron expression itself. This replaced
 * the previous 3-cron-trigger / exact-cron-string-match design (ADR-010,
 * planning/cron-consolidation-state-machine.md — read those for the why).
 *
 * scheduled() POSTs a workflow_dispatch to GitHub to launch collect.yml or
 * collect_picks.yml on GitHub's Azure runners (which pass Finviz's
 * Cloudflare bot-detection; our Cloudflare/GCP IPs do not — see
 * planning/cloudflare-cron-scheduler.md).
 *
 * workflow_dispatch is event-driven and processed promptly, so it is NOT
 * subject to the schedule-drop / multi-hour drift that GitHub's schedule:
 * cron suffers.
 *
 * fetch() exposes GET /health (KV connectivity) and GET /last (last dispatch
 * record per job) for debugging. Same response conventions as
 * worker/src/index.js.
 */

import { computeEtNow, jobsInWindow, jobsForTick, JOB_SCHEDULE } from './routing.js';
import { evaluatePicksGate, findEodRun } from './picksGate.js';

const REPO_WORKFLOWS_URL =
  'https://api.github.com/repos/clarencelam2000/finviz-groups-tracker/actions/workflows';

// GET endpoint for the picks dependency gate (issue #259) to read collect.yml's
// actual run history/status — distinct from the dispatches POST endpoints in
// WORKFLOWS below, which only ever get a 204-or-not accepted/rejected signal,
// never the underlying workflow's real outcome.
const COLLECT_RUNS_URL = `${REPO_WORKFLOWS_URL}/collect.yml/runs`;

// Maps a job's `workflow` field (routing.js JOB_SCHEDULE) to the GitHub
// Actions dispatch endpoint. Job-level "already dispatched today" tracking
// lives in per-job KV keys (last_dispatch_<jobName>), not here — two jobs
// can share a workflow (both collect_preclose and collect_eod dispatch
// collect.yml) while tracking their own daily dispatch state independently.
const WORKFLOWS = {
  collect: { url: `${REPO_WORKFLOWS_URL}/collect.yml/dispatches` },
  picks: { url: `${REPO_WORKFLOWS_URL}/collect_picks.yml/dispatches` },
  // WS3 Phase B (ADR-013 Decision 6): ungated, dispatched directly by
  // scheduled() like `collect` — ADR-013 morning status workflow.
  morning: { url: `${REPO_WORKFLOWS_URL}/collect_morning.yml/dispatches` },
  // WS5 phase 2 (planning/trade-lifecycle-engine.md §5/§5a/§10/§11): ungated, same
  // dispatch shape as `morning` — held-tickers EOD quote feed, writes to D1 (not git).
  held: { url: `${REPO_WORKFLOWS_URL}/collect_held.yml/dispatches` },
  // WS3b (issue #268): ungated, same dispatch shape as `morning` — pre-close
  // "confirming into the close" status pass, thin wrapper workflow that calls
  // scripts/collect_morning.py --session pre_close (see
  // .github/workflows/collect_preclose_status.yml). Distinct from the
  // `collect_preclose` job above, which dispatches the unrelated collect.yml.
  preclose_status: { url: `${REPO_WORKFLOWS_URL}/collect_preclose_status.yml/dispatches` },
  // WS5-8: ungated, same dispatch shape as `held` — 15:40 ET pre-close advisory read,
  // POSTs to /positions/preclose-advisory (no D1 positions/ticker_quotes write, no
  // /advance sweep). See collect_held_preclose.yml.
  held_preclose: { url: `${REPO_WORKFLOWS_URL}/collect_held_preclose.yml/dispatches` },
};

function jsonResponse(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function log(fields) {
  try {
    console.log(JSON.stringify({ ts: new Date().toISOString(), ...fields }));
  } catch (_) {
    // logging must never break a request
  }
}

/**
 * Read the last *successful* dispatch date (ET, "YYYY-MM-DD") for each job
 * name, or null if none/unavailable. Only called for jobs `jobsInWindow`
 * already says are due this tick — see scheduled() below — so no-op ticks
 * never touch KV.
 */
async function loadDispatchedToday(env, jobNames) {
  const dispatchedToday = {};
  await Promise.all(
    jobNames.map(async (name) => {
      try {
        const raw = await env.DISPATCH_LOG.get(`last_dispatch_${name}`);
        const rec = raw ? JSON.parse(raw) : null;
        dispatchedToday[name] = rec && rec.ok ? rec.etDate : null;
      } catch (_) {
        dispatchedToday[name] = null;
      }
    }),
  );
  return dispatchedToday;
}

/**
 * POST workflow_dispatch to GitHub to launch the workflow for `jobName`,
 * then record the outcome to KV under that job's own key. Throws nothing —
 * KV write and GitHub call failures are logged and recorded, never
 * propagated (a Cron Trigger has no caller to surface to).
 */
export async function dispatchJob(env, jobName, workflow, etDateStr) {
  const { url } = WORKFLOWS[workflow];
  const kvKey = `last_dispatch_${jobName}`;
  const ts = new Date().toISOString();
  let status = 0;
  let ok = false;
  let error = null;

  if (!env.GITHUB_DISPATCH_TOKEN) {
    error = 'missing_token';
    log({ level: 'error', message: 'GITHUB_DISPATCH_TOKEN not configured', job: jobName, workflow });
  } else {
    try {
      const resp = await fetch(url, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${env.GITHUB_DISPATCH_TOKEN}`,
          Accept: 'application/vnd.github+json',
          'User-Agent': 'finviz-cron-dispatcher',
          'X-GitHub-Api-Version': '2022-11-28',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ ref: env.DISPATCH_REF }),
      });
      status = resp.status;
      // GitHub returns 204 No Content on a successful workflow_dispatch.
      ok = resp.status === 204;
      if (!ok) {
        error = `github_${resp.status}`;
        log({ level: 'error', message: 'workflow_dispatch failed', status, job: jobName, workflow });
      }
    } catch (e) {
      error = 'fetch_failed';
      log({ level: 'error', message: String(e && e.message ? e.message : e), job: jobName, workflow });
    }
  }

  const record = {
    ts,
    status,
    ok,
    error,
    job: jobName,
    workflow,
    ref: env.DISPATCH_REF,
    etDate: etDateStr || null,
  };
  try {
    await env.DISPATCH_LOG.put(kvKey, JSON.stringify(record));
  } catch (_) {
    // observability write must never break the dispatch path
  }
  log({ event: 'dispatch', ...record });
  return record;
}

/**
 * Fetch collect.yml's recent run history and pick out the run that
 * corresponds to our own EOD dispatch (disambiguating from the earlier
 * same-day pre-close dispatch — issue #259 review finding #1). Never
 * throws: a fetch/auth failure surfaces as `fetchError`, which
 * evaluatePicksGate treats as "not yet satisfied" (never dispatches picks
 * on an unverifiable read) so the gate fails closed, not open.
 *
 * GITHUB_DISPATCH_TOKEN is documented (wrangler.toml) as a fine-grained PAT
 * with "Actions: Read and write" on this repo, which per GitHub's
 * permission model covers this GET as well as the dispatches POST already
 * in use — but this was flagged in the #259 review as worth confirming live
 * (a classic PAT would also work; a narrower fine-grained grant might not).
 * A `github_401`/`github_403` fetchError here is the concrete signal if
 * that assumption turns out wrong in prod.
 */
export async function fetchEodRun(env, dispatchTs) {
  if (!env.GITHUB_DISPATCH_TOKEN) return { eodRun: null, fetchError: 'missing_token' };
  try {
    const url = `${COLLECT_RUNS_URL}?event=workflow_dispatch&branch=${encodeURIComponent(env.DISPATCH_REF)}&per_page=10`;
    const resp = await fetch(url, {
      headers: {
        Authorization: `Bearer ${env.GITHUB_DISPATCH_TOKEN}`,
        Accept: 'application/vnd.github+json',
        'User-Agent': 'finviz-cron-dispatcher',
        'X-GitHub-Api-Version': '2022-11-28',
      },
    });
    if (!resp.ok) {
      return { eodRun: null, fetchError: `github_${resp.status}` };
    }
    const body = await resp.json();
    return { eodRun: findEodRun(body.workflow_runs || [], dispatchTs), fetchError: null };
  } catch (e) {
    return { eodRun: null, fetchError: 'fetch_failed' };
  }
}

/**
 * The picks dependency gate (issue #259): reads collect_eod's own dispatch
 * record, fetches the corresponding GitHub Actions run's real outcome,
 * decides dispatch/waiting/miss via the pure evaluatePicksGate, records the
 * outcome to KV (`last_gate_check_picks`, surfaced via /last), and only
 * calls dispatchJob when collect.yml's EOD run has actually concluded
 * `success` — replacing the old "EOD + 90min, hope for the best" margin.
 */
export async function runPicksGate(env, job, etNow) {
  let collectEodDispatch = null;
  try {
    const raw = await env.DISPATCH_LOG.get('last_dispatch_collect_eod');
    collectEodDispatch = raw ? JSON.parse(raw) : null;
  } catch (_) {
    collectEodDispatch = null;
  }

  let eodRun = null;
  let fetchError = null;
  if (collectEodDispatch && collectEodDispatch.ok && collectEodDispatch.etDate === etNow.dateStr) {
    ({ eodRun, fetchError } = await fetchEodRun(env, collectEodDispatch.ts));
  }

  const { outcome, reason } = evaluatePicksGate({ job, etNow, collectEodDispatch, eodRun, fetchError });

  const record = { ts: new Date().toISOString(), outcome, reason, etDate: etNow.dateStr };
  try {
    await env.DISPATCH_LOG.put('last_gate_check_picks', JSON.stringify(record));
  } catch (_) {
    // observability write must never break the gate path
  }
  log({ event: 'picks_gate', ...record });

  if (outcome === 'dispatch') {
    await dispatchJob(env, 'picks', job.workflow, etNow.dateStr);
  } else if (outcome === 'miss') {
    log({
      level: 'error',
      message: "picks dependency gate window closed without a successful EOD collect run",
      reason,
      etDate: etNow.dateStr,
    });
  }
}

async function handleHealth(env) {
  let kvOk = false;
  try {
    await env.DISPATCH_LOG.get('__health_ping__');
    kvOk = true;
  } catch (_) {
    kvOk = false;
  }
  return jsonResponse({ status: 'ok', timestamp: new Date().toISOString(), kv_ok: kvOk });
}

async function handleLast(env) {
  const out = {};
  for (const { name } of JOB_SCHEDULE) {
    try {
      const raw = await env.DISPATCH_LOG.get(`last_dispatch_${name}`);
      out[name] = raw ? JSON.parse(raw) : null;
    } catch (_) {
      out[name] = null;
    }
  }
  // Picks dependency-gate outcome (issue #259) — distinct from
  // last_dispatch_picks: this records every gate *check* (dispatch/waiting/
  // miss), not just an eventual successful dispatch, so a stuck "waiting"
  // or a "miss" is visible on /last even on a day picks never fires.
  try {
    const raw = await env.DISPATCH_LOG.get('last_gate_check_picks');
    out.picks_gate_check = raw ? JSON.parse(raw) : null;
  } catch (_) {
    out.picks_gate_check = null;
  }
  // Legacy per-workflow keys from before WS1's per-job KV keys existed —
  // surfaced so the first /last check after deploy still shows the
  // pre-migration dispatch record.
  out.legacy = {};
  for (const legacyKey of ['last_dispatch_collect', 'last_dispatch_picks', 'last_dispatch']) {
    try {
      const raw = await env.DISPATCH_LOG.get(legacyKey);
      out.legacy[legacyKey] = raw ? JSON.parse(raw) : null;
    } catch (_) {
      out.legacy[legacyKey] = null;
    }
  }
  return jsonResponse({ last_dispatch: out });
}

export async function handleRequest(request, env) {
  const url = new URL(request.url);
  if (url.pathname === '/health') {
    return handleHealth(env);
  }
  if (url.pathname === '/last') {
    return handleLast(env);
  }
  return jsonResponse({ error: 'not_found' }, 404);
}

export default {
  async scheduled(event, env, ctx) {
    // event.scheduledTime (ms epoch) is when Cloudflare intended this tick to
    // fire — using it instead of `new Date()` keeps routing accurate even if
    // the Worker's own clock read happens a moment late, and makes this
    // testable with fixed fixtures.
    const scheduledAt = event && event.scheduledTime ? new Date(event.scheduledTime) : new Date();
    const etNow = computeEtNow(scheduledAt);

    // Cheap, I/O-free check first: if no job's window is open this tick,
    // return immediately with no KV read, no fetch, no log — this is what
    // keeps the ~288 ticks/day no-op path free (ADR-010 § observability).
    const candidates = jobsInWindow(etNow);
    if (candidates.length === 0) return;

    const dispatchedToday = await loadDispatchedToday(env, candidates);
    const due = jobsForTick(etNow, dispatchedToday);

    for (const jobName of due) {
      const job = JOB_SCHEDULE.find((j) => j.name === jobName);
      // gated jobs (currently just 'picks', issue #259) don't dispatch
      // directly on window-open — they re-check collect.yml's actual EOD
      // run outcome first; runPicksGate calls dispatchJob itself once that
      // check passes.
      if (job.gated) {
        await runPicksGate(env, job, etNow);
      } else {
        await dispatchJob(env, jobName, job.workflow, etNow.dateStr);
      }
    }
  },
  fetch: handleRequest,
};
