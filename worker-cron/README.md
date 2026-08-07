# finviz-cron-dispatcher (Cloudflare Worker)

A **scheduler only**. One Cloudflare Cron Trigger fires this Worker every 5
minutes, and in-code routing (gated on Eastern wall-clock time) decides
whether any job is actually due on that tick; when one is, it POSTs a GitHub
`workflow_dispatch` to launch `collect.yml` or `collect_picks.yml` on GitHub's
Azure runners — which pass Finviz's Cloudflare bot-detection (our
Cloudflare/Google-Cloud IPs do not). This decouples *scheduling* (now
reliable, on Cloudflare) from *scraping* (still on GitHub Actions, unchanged).

Why not run the scrape here? Workers can't drive a 2–4 min Chromium session,
can't run pandas `compute_deltas.py`, can't `git commit` CSVs, and would scrape
from Cloudflare IPs into a Cloudflare-protected site. See
`planning/cloudflare-cron-scheduler.md` for the full rationale.

## Single-trigger design (ADR-010, WS1)

As of WS1 (`knowledge/decisions/ADR-010-single-trigger-cron-dispatch.md`,
`planning/cron-consolidation-state-machine.md`), this Worker runs on **one**
Cloudflare Cron Trigger — `*/5 * * * *`, i.e. every 5 minutes, all day, every
day — instead of one trigger per job. This frees 2 of the Cloudflare
account's hard 5-cron-trigger limit (shared with unrelated `distil-*`
workers) and makes the number of logical jobs this dispatcher can host
unbounded, since adding a job is now a code change rather than a
Cloudflare-account-limit negotiation.

All schedule logic lives in `src/routing.js`:

- `computeEtNow(date)` — pure ET wall-clock calculation via
  `Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', ... })`.
  Cloudflare Workers' V8 runtime ships full ICU timezone data, so this tracks
  EST/EDT transitions automatically — **no more twice-yearly manual DST
  edit** to this file, `wrangler.toml`, or `collect.yml`.
- `JOB_SCHEDULE` — the single source of truth for what fires when (see
  § Configurable parameters below).
- `jobsInWindow(etNow)` / `jobsForTick(etNow, dispatchedToday)` — pure
  routing functions, fully unit-tested with fixed clock fixtures
  (`test/routing.test.js`).

**Self-healing dispatch, not exact-minute matching.** A job is due whenever
the current tick falls anywhere inside its `[target, target + windowMinutes)`
ET window **and** it has no successful dispatch recorded for today's ET date
yet (per-job KV key `last_dispatch_<jobName>`). This means a Cloudflare tick
that's delayed or skipped doesn't silently drop that day's job — the next
5-minute tick still picks it up, as long as it's inside the window. No-op
ticks (no job's window open) do zero I/O — no KV read, no fetch, no log — so
the ~288 ticks/day this design produces stay free of observability noise.

The picks job is still fired on a **fixed ET time target**, not a dependency
check against whether `collect.yml` actually succeeded — that dependency
gate is tracked separately (issue #259), deliberately out of scope for WS1.

## Live deployment

**URL:** `https://finviz-cron-dispatcher.salmonbaby8.workers.dev`

`GITHUB_DISPATCH_TOKEN` and `DISPATCH_LOG` KV (id `8edeadedaf9345748592320549669ff4`) are already configured.

## What it does

- `scheduled(event, env, ctx)` — on each 5-minute tick, computes ET wall-clock
  time from `event.scheduledTime`, checks `JOB_SCHEDULE` for any job whose
  window is open, and for each due job `POST`s to the corresponding GitHub
  `*.yml/dispatches` API with `{ "ref": DISPATCH_REF }`, then records the
  outcome (`{ ts, status, ok, error, job, workflow, ref, etDate }`) to
  `DISPATCH_LOG` KV under `last_dispatch_<jobName>`.
- `GET /health` — liveness + KV ping.
- `GET /last` — the last dispatch record per job (for debugging drift /
  failures), plus legacy pre-WS1 per-workflow keys if present.

## Configurable parameters

All schedule constants live in `src/routing.js`. Edit `JOB_SCHEDULE` to
change *when* something fires, or add a new job — not `wrangler.toml` (which
now only holds the fixed `*/5 * * * *` trigger).

| Parameter | Default | What it controls |
|-----------|---------|-------------------|
| Tick interval (`wrangler.toml [triggers] crons`) | `*/5 * * * *` | How often `scheduled()` fires; the grid every `JOB_SCHEDULE` target time must land on (target minutes must be multiples of 5). |
| `DISPATCH_WINDOW_MINUTES` | `30` | How long after a job's target ET time the tick keeps considering that job due, and the self-heal retry budget for a delayed/skipped Cloudflare tick. |
| `JOB_SCHEDULE[*].hour` / `.minute` | `collect_preclose` 15:50, `collect_eod` 17:00, `picks` 18:30 (ET) | Per-job target wall-clock time. Shifted from the legacy `:48`/`:01`/`:31` cron minutes to land on the 5-minute grid. |
| `JOB_SCHEDULE[*].weekdays` | `[1,2,3,4,5]` (Mon–Fri) for all current jobs | ISO weekday gate per job; a future Sunday-only job (e.g. the roadmap's weekly taxonomy check) would use `[7]`. |

Also documented in `CLAUDE.md` § Automation, per this repo's 3-places rule
for configurable constants.

## Cron schedule (legacy jobs migrated to `JOB_SCHEDULE`)

| Job | ET target (auto-DST) | Purpose |
|-----|-----------------------|---------|
| `collect_preclose` | 15:50 | pre-close snapshot before the market close |
| `collect_eod` | 17:00 | EOD post-close snapshot |
| `picks` | 18:30 | picks selector (fixed time margin — dependency gate is #259) |

## Monitoring and validation

### Ongoing health checks (no setup required)

```bash
# Is the Worker alive and KV connected?
curl https://finviz-cron-dispatcher.salmonbaby8.workers.dev/health

# What did the last tick's dispatches produce, per job?
curl https://finviz-cron-dispatcher.salmonbaby8.workers.dev/last
```

`/last` returns `{last_dispatch: {collect_preclose, collect_eod, picks, legacy}}`,
each a `{ts, status, ok, error, job, workflow, ref, etDate}` record written to
KV on every successful or attempted dispatch (never on a no-op tick).
- `ok: true, status: 204` = GitHub accepted the dispatch.
- `error: "github_401"` = PAT expired — rotate `GITHUB_DISPATCH_TOKEN`.
- `error: "github_422"` = `DISPATCH_REF` branch no longer exists; update `wrangler.toml` vars and redeploy.
- `error: "fetch_failed"` = network issue on Cloudflare's side.

### Cross-check: did the scrape actually run?

Every successful dispatch produces a `workflow_dispatch` run in GitHub Actions and a row in `data/fetch_log.csv`. If you want to confirm the timing improvement is working, compare `fetch_log.csv` `timestamp` vs. the job's ET target over the first few trading days — drift should be minutes, not hours.

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

After deploying, confirm on the Cloudflare dashboard that this Worker shows
exactly **1** Cron Trigger (down from 3) — the concrete proof the
5-trigger-limit outage from issue #252 cannot recur in this shape.

## Test

```bash
npm test   # vitest, offline, no network
```

`test/routing.test.js` covers the pure ET/DST calculation and routing
functions (table-driven, DST-transition-day, weekday-across-UTC-boundary,
no-op tick, self-heal-on-delayed-tick). `test/index.test.js` covers the
GitHub dispatch call shape, the `scheduled()` handler wiring, and the debug
endpoints.

## Local scheduled trigger

```bash
wrangler dev --test-scheduled
# then in another shell:
curl "http://localhost:8787/__scheduled?cron=*/5+*+*+*+*"
```

Note: local dev needs a preview KV namespace (`wrangler kv namespace create DISPATCH_LOG --preview`) and a `preview_id` in `wrangler.toml` before `wrangler dev` will start.
