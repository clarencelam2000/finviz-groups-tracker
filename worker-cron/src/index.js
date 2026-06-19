/**
 * Finviz Cron Dispatcher — Cloudflare Worker.
 *
 * Pure scheduler: Cron Triggers (defined in wrangler.toml) fire the scheduled()
 * handler, which POSTs a workflow_dispatch to GitHub to launch collect.yml on
 * GitHub's Azure runners (which pass Finviz's Cloudflare bot-detection; our
 * Cloudflare/GCP IPs do not — see planning/cloudflare-cron-scheduler.md).
 *
 * workflow_dispatch is event-driven and processed promptly, so it is NOT subject
 * to the schedule-drop / multi-hour drift that GitHub's schedule: cron suffers.
 *
 * fetch() exposes GET /health (KV connectivity) and GET /last (last dispatch
 * record) for debugging. Same response conventions as worker/src/index.js.
 */

const GITHUB_DISPATCH_URL =
  'https://api.github.com/repos/clarencelam2000/finviz-groups-tracker/actions/workflows/collect.yml/dispatches';
const LAST_DISPATCH_KEY = 'last_dispatch';

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
 * POST workflow_dispatch to GitHub to launch collect.yml, then record the
 * outcome to KV. Throws nothing — KV write and GitHub call failures are logged
 * and recorded, never propagated (a Cron Trigger has no caller to surface to).
 */
export async function dispatchCollect(env, cron) {
  const ts = new Date().toISOString();
  let status = 0;
  let ok = false;
  let error = null;

  if (!env.GITHUB_DISPATCH_TOKEN) {
    error = 'missing_token';
    log({ level: 'error', message: 'GITHUB_DISPATCH_TOKEN not configured', cron });
  } else {
    try {
      const resp = await fetch(GITHUB_DISPATCH_URL, {
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
        log({ level: 'error', message: 'workflow_dispatch failed', status, cron });
      }
    } catch (e) {
      error = 'fetch_failed';
      log({ level: 'error', message: String(e && e.message ? e.message : e), cron });
    }
  }

  const record = { ts, status, ok, error, cron: cron || null, ref: env.DISPATCH_REF };
  try {
    await env.DISPATCH_LOG.put(LAST_DISPATCH_KEY, JSON.stringify(record));
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
  let record = null;
  try {
    const raw = await env.DISPATCH_LOG.get(LAST_DISPATCH_KEY);
    record = raw ? JSON.parse(raw) : null;
  } catch (_) {
    record = null;
  }
  return jsonResponse({ last_dispatch: record });
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
    // event.cron is the matched cron expression (e.g. "48 19 * * 1-5").
    await dispatchCollect(env, event && event.cron);
  },
  fetch: handleRequest,
};
