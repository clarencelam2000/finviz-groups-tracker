# finviz-cron-dispatcher (Cloudflare Worker)

A **scheduler only**. Cloudflare Cron Triggers fire this Worker on time, and it
POSTs a GitHub `workflow_dispatch` to launch the existing `collect.yml` workflow
on GitHub's Azure runners — which pass Finviz's Cloudflare bot-detection (our
Cloudflare/Google-Cloud IPs do not). This decouples *scheduling* (now reliable,
on Cloudflare) from *scraping* (still on GitHub Actions, unchanged).

Why not run the scrape here? Workers can't drive a 2–4 min Chromium session,
can't run pandas `compute_deltas.py`, can't `git commit` CSVs, and would scrape
from Cloudflare IPs into a Cloudflare-protected site. See
`planning/cloudflare-cron-scheduler.md` for the full rationale.

## Live deployment

**URL:** `https://finviz-cron-dispatcher.salmonbaby8.workers.dev`

Deployed 2026-06-19. `GITHUB_DISPATCH_TOKEN` and `DISPATCH_LOG` KV (id `8edeadedaf9345748592320549669ff4`) are already configured.

## What it does

- `scheduled(event, env, ctx)` — on each Cron Trigger, `POST`s to the GitHub
  `collect.yml/dispatches` API with `{ "ref": DISPATCH_REF }`, then records the
  outcome (`{ ts, status, ok, error, cron, ref }`) to the `DISPATCH_LOG` KV.
- `GET /health` — liveness + KV ping.
- `GET /last` — the last dispatch record (for debugging drift / failures).

## Cron schedule

Defined in `wrangler.toml` `[triggers] crons` (UTC, weekday-only) — identical
expressions to the GitHub cron in `collect.yml`:

| Cron (UTC) | ~ET (summer / winter) | Purpose |
|------------|-----------------------|---------|
| `49 13 * * 1-5` | 9:49 / 8:49 AM | just after the open |
| `51 14 * * 1-5` | 10:51 / 9:51 AM | mid-morning |
| `48 19 * * 1-5` | 3:48 / 2:48 PM | EOD snapshot before the close |

Cloudflare cron is fixed-UTC and cannot follow DST (same as GitHub) — see
`CLAUDE.md` § Automation.

## Monitoring and validation

### Ongoing health checks (no setup required)

```bash
# Is the Worker alive and KV connected?
curl https://finviz-cron-dispatcher.salmonbaby8.workers.dev/health

# What did the last cron fire produce?
curl https://finviz-cron-dispatcher.salmonbaby8.workers.dev/last
```

`/last` returns `{ts, status, ok, error, cron, ref}` — written to KV on every scheduled fire.
- `ok: true, status: 204` = GitHub accepted the dispatch.
- `error: "github_401"` = PAT expired — rotate `GITHUB_DISPATCH_TOKEN`.
- `error: "github_422"` = `DISPATCH_REF` branch no longer exists; update `wrangler.toml` vars and redeploy.
- `error: "fetch_failed"` = network issue on Cloudflare's side.

### Cross-check: did the scrape actually run?

Every successful dispatch produces a `workflow_dispatch` run in GitHub Actions and a row in `data/fetch_log.csv`. If you want to confirm the timing improvement is working, compare `fetch_log.csv` `timestamp` vs. the cron schedule over the first few trading days — drift should be minutes, not hours.

### Cloudflare-side logs

```bash
wrangler tail finviz-cron-dispatcher   # streams structured JSON logs live
```

The CF dashboard → Workers → `finviz-cron-dispatcher` → Logs/Metrics shows invocation counts and error rates.

### Dead-man's-switch alert (already in place)

The `HEALTHCHECK_URL` secret in `collect.yml` (healthchecks.io) pings on every successful scrape, regardless of trigger. Its "no ping in 26h" alert catches the case where the Worker silently stops dispatching — no new code needed. The Worker's `/last` then tells you why.

### Token expiry

If `GITHUB_DISPATCH_TOKEN` has an expiration date, note it. When it lapses, dispatches fail silently (`/last` will show `error: "github_401"`). Rotate via:

```bash
printf '%s' "$NEW_TOKEN" | wrangler secret put GITHUB_DISPATCH_TOKEN
```

No redeploy needed — secret updates take effect immediately.

## Deploy / redeploy

```bash
cd worker-cron
npm ci
npm run deploy
```

Headless-token deploy pattern: `knowledge/cloudflare-headless-deploy.md`.
Auth: `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` env vars (already in session config).

## Test

```bash
npm test   # vitest, offline, no network (13 tests)
```

## Local scheduled trigger

```bash
wrangler dev --test-scheduled
# then in another shell:
curl "http://localhost:8787/__scheduled?cron=48+19+*+*+1-5"
```

Note: local dev needs a preview KV namespace (`wrangler kv namespace create DISPATCH_LOG --preview`) and a `preview_id` in `wrangler.toml` before `wrangler dev` will start.
