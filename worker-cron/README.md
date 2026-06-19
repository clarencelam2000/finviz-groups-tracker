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

## First deploy

```bash
cd worker-cron
npm ci

# 1. Create the KV namespace, paste the printed id into wrangler.toml
wrangler kv namespace create DISPATCH_LOG

# 2. Set the GitHub PAT secret (fine-grained, THIS repo only, Actions: R/W)
wrangler secret put GITHUB_DISPATCH_TOKEN

# 3. Deploy
npm run deploy
```

Headless-token deploy pattern: `knowledge/cloudflare-headless-deploy.md`.

## Test

```bash
npm test   # vitest, offline, no network
```

## Local scheduled trigger

```bash
wrangler dev --test-scheduled
# then in another shell:
curl "http://localhost:8787/__scheduled?cron=48+19+*+*+1-5"
```
