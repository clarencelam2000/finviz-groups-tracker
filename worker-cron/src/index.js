/**
 * Finviz Cron Dispatcher — Cloudflare Worker.
 *
 * Pure scheduler: Cron Triggers (defined in wrangler.toml) fire the scheduled()
 * handler, which POSTs a workflow_dispatch to GitHub to launch collect.yml (2
 * crons/day) or collect_picks.yml (1 cron/day, PICKS-2-CRON) on GitHub's Azure
 * runners (which pass Finviz's Cloudflare bot-detection; our Cloudflare/GCP IPs
 * do not — see planning/cloudflare-cron-scheduler.md).
 *
 * workflow_dispatch is event-driven and processed promptly, so it is NOT subject
 * to the schedule-drop / multi-hour drift that GitHub's schedule: cron suffers.
 *
 * fetch() exposes GET /health (KV connectivity) and GET /last (last dispatch
 * record per workflow) for debugging. Same response conventions as
 * worker/src/index.js.
 */

const REPO_WORKFLOWS_URL =
  'https://api.github.com/repos/clarencelam2000/finviz-groups-tracker/actions/workflows';

// PICKS_CRON must stay byte-identical to the picks entry in wrangler.toml
// [triggers] crons — scheduled() routes by exact event.cron string match.
// Any other cron expression (the two collect entries, or a future addition
// not routed here) dispatches collect.yml, the safe default: collect is
// last-write-wins per date so a spurious extra run is harmless, whereas a
// spurious picks run scrapes up to 50 screener pages.
const PICKS_CRON = '31 22 * * 2-6';

const WORKFLOWS = {
  collect: {
    url: `${REPO_WORKFLOWS_URL}/collect.yml/dispatches`,
    kvKey: 'last_dispatch_collect',
  },
  picks: {
    url: `${REPO_WORKFLOWS_URL}/collect_picks.yml/dispatches`,
    kvKey: 'last_dispatch_picks',
  },
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

/** Map a fired cron expression to a workflow name ('collect' | 'picks'). */
export function workflowForCron(cron) {
  return cron === PICKS_CRON ? 'picks' : 'collect';
}

/**
 * POST workflow_dispatch to GitHub to launch the named workflow, then record
 * the outcome to KV under that workflow's own key. Throws nothing — KV write
 * and GitHub call failures are logged and recorded, never propagated (a Cron
 * Trigger has no caller to surface to).
 */
export async function dispatchWorkflow(env, cron, workflow) {
  const { url, kvKey } = WORKFLOWS[workflow];
  const ts = new Date().toISOString();
  let status = 0;
  let ok = false;
  let error = null;

  if (!env.GITHUB_DISPATCH_TOKEN) {
    error = 'missing_token';
    log({ level: 'error', message: 'GITHUB_DISPATCH_TOKEN not configured', cron, workflow });
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
        log({ level: 'error', message: 'workflow_dispatch failed', status, cron, workflow });
      }
    } catch (e) {
      error = 'fetch_failed';
      log({ level: 'error', message: String(e && e.message ? e.message : e), cron, workflow });
    }
  }

  const record = { ts, status, ok, error, cron: cron || null, workflow, ref: env.DISPATCH_REF };
  try {
    await env.DISPATCH_LOG.put(kvKey, JSON.stringify(record));
  } catch (_) {
    // observability write must never break the dispatch path
  }
  log({ event: 'dispatch', ...record });
  return record;
}

/** Back-compat wrapper (pre-PICKS-2-CRON name) — dispatches collect.yml. */
export async function dispatchCollect(env, cron) {
  return dispatchWorkflow(env, cron, 'collect');
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
  for (const [name, { kvKey }] of Object.entries(WORKFLOWS)) {
    try {
      const raw = await env.DISPATCH_LOG.get(kvKey);
      out[name] = raw ? JSON.parse(raw) : null;
    } catch (_) {
      out[name] = null;
    }
  }
  // Legacy key from before per-workflow keys existed — surfaced so the first
  // /last check after deploy still shows the pre-migration dispatch record.
  try {
    const raw = await env.DISPATCH_LOG.get('last_dispatch');
    out.legacy = raw ? JSON.parse(raw) : null;
  } catch (_) {
    out.legacy = null;
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
    // event.cron is the matched cron expression (e.g. "48 19 * * 2-6").
    const cron = event && event.cron;
    await dispatchWorkflow(env, cron, workflowForCron(cron));
  },
  fetch: handleRequest,
};
