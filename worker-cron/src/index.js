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

const REPO_WORKFLOWS_URL =
  'https://api.github.com/repos/clarencelam2000/finviz-groups-tracker/actions/workflows';

// Maps a job's `workflow` field (routing.js JOB_SCHEDULE) to the GitHub
// Actions dispatch endpoint. Job-level "already dispatched today" tracking
// lives in per-job KV keys (last_dispatch_<jobName>), not here — two jobs
// can share a workflow (both collect_preclose and collect_eod dispatch
// collect.yml) while tracking their own daily dispatch state independently.
const WORKFLOWS = {
  collect: { url: `${REPO_WORKFLOWS_URL}/collect.yml/dispatches` },
  picks: { url: `${REPO_WORKFLOWS_URL}/collect_picks.yml/dispatches` },
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
      await dispatchJob(env, jobName, job.workflow, etNow.dateStr);
    }
  },
  fetch: handleRequest,
};
