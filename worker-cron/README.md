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

**Picks is dependency-gated (issue #259), not fixed-time.** Instead of firing
at a fixed margin after collect_eod and hoping, `src/picksGate.js` +
`runPicksGate` in `index.js` re-check collect.yml's *actual* EOD run outcome
every tick inside picks' window (which now starts at the same 17:00 ET
target as collect_eod, not 90 minutes later): read `last_dispatch_collect_eod`
KV, fetch collect.yml's run history from the GitHub Actions API, match the
run that corresponds to the EOD dispatch (disambiguating from the earlier
same-day pre-close run by `created_at`), and dispatch picks the moment that
run is `conclusion === 'success'`. If the window closes without a success, a
`last_gate_check_picks` "miss" record is written (surfaced via `/last`)
instead of the day silently going missing — see § Picks dependency gate
below for the full detail.

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
  failures), the picks dependency-gate's last check outcome
  (`picks_gate_check`), plus legacy pre-WS1 per-workflow keys if present.

## Picks dependency gate (issue #259)

Replaces the old "EOD collect + 90 minutes, hope `compute_deltas.py` and the
git push finished" margin with an actual state check, closing out the last
piece of ADR-010's dependency-driven dispatch:

1. Picks' `JOB_SCHEDULE` entry (`gated: true`) targets the **same** 17:00 ET
   time as `collect_eod`, with a much wider window
   (`PICKS_GATE_WINDOW_MINUTES`, 120 min = 17:00–19:00 ET) — not a fixed
   later time.
2. On each tick inside that window where picks hasn't dispatched
   successfully yet today, `index.js`'s `runPicksGate` reads the
   `last_dispatch_collect_eod` KV record. If collect_eod hasn't been
   dispatched for today's ET date yet, the gate just waits (no GitHub call)
   — nothing to check yet.
3. Once collect_eod has been dispatched today, the gate fetches
   `collect.yml`'s recent run history (`GET .../collect.yml/runs`) and picks
   out the run that corresponds to *that* dispatch (`picksGate.js`'s
   `findEodRun` — matched by `created_at` at/after the dispatch timestamp,
   within a small clock-skew tolerance). This disambiguates from the
   earlier same-day `collect_preclose` dispatch's run — collect.yml fires
   twice a day, so "most recent run succeeded" alone can be satisfied by
   the wrong one (the #259 review's finding #1).
4. If the matched run is `conclusion === 'success'`, picks dispatches
   immediately (`dispatchJob`, same as any other job). If not yet resolved
   (still running, or no matching run found yet), the gate records
   `outcome: 'waiting'` and retries next tick — the same self-heal mechanism
   `jobsForTick` already provides, not a second one-off.
5. If the window closes (120 min after target) without a success, the gate
   records `outcome: 'miss'` and logs at `error` level, instead of the day
   silently going missing (issue #252's failure mode). This satisfies issue
   #260's self-heal + retry-on-miss scope. This is also the basis for
   eventually retiring the healthchecks.io dead-man's-switch on
   `collect_picks.yml` — **not done yet; see ADR-010 rollout step 7 and
   CLAUDE.md § Automation "Issue #260" bullet.** The gate went live with PR
   #272 (merged 2026-08-08, a non-trading day); do not remove the
   `PICKS_HEALTHCHECK_URL` ping before **2026-08-17** — that's after the
   first full trading week (2026-08-10–2026-08-14) of `picks_gate_check`
   history has been observed via `GET /last`.
6. Every gate check (`waiting`/`dispatch`/`miss`) is written to
   `last_gate_check_picks` KV, surfaced as `picks_gate_check` on `GET /last`
   — so a stuck "waiting" or a "miss" is visible without digging through
   Worker logs.

`collect.yml` runs `collect.py → compute_deltas.py → evaluate_picks.py →
git commit && git push` all in one job, push last — so a `success`
conclusion on the matched run already implies deltas were computed and
pushed; no separate commit-presence check is needed (resolved during design
review, see `planning/cron-consolidation-state-machine.md`).

**Fails closed, not open:** if the GitHub Actions runs-list read itself
fails (e.g. `GITHUB_DISPATCH_TOKEN` lacks read scope — see § Token read
scope below), the gate treats that the same as "not yet successful" and
keeps waiting/eventually misses — it never dispatches picks on an
unverifiable check.

### Token read scope

`GITHUB_DISPATCH_TOKEN` is documented (see `wrangler.toml`'s setup comment)
as a fine-grained PAT scoped to this repo with **"Actions: Read and
write"** — which per GitHub's permission model should already cover the
`GET .../collect.yml/runs` call the gate makes, the same token already used
for the `workflow_dispatch` POST. This was flagged in the #259 review as
worth confirming live rather than assumed: **after first deploy, check
`GET /last`'s `picks_gate_check` for a `run_status_fetch_failed:github_401`
or `github_403` reason** — that's the concrete signal the token can't read
run status and needs a scope fix (or rotation to a classic PAT with `repo`
scope, which always includes Actions read).

## Configurable parameters

All schedule constants live in `src/routing.js` (job timing) and
`src/picksGate.js` (gate window). Edit `JOB_SCHEDULE` to change *when*
something fires, or add a new job — not `wrangler.toml` (which now only
holds the fixed `*/5 * * * *` trigger).

| Parameter | Default | What it controls |
|-----------|---------|-------------------|
| Tick interval (`wrangler.toml [triggers] crons`) | `*/5 * * * *` | How often `scheduled()` fires; the grid every `JOB_SCHEDULE` target time must land on (target minutes must be multiples of 5). |
| `DISPATCH_WINDOW_MINUTES` | `30` | How long after `collect_preclose`/`collect_eod`'s target ET time the tick keeps considering that job due, and the self-heal retry budget for a delayed/skipped Cloudflare tick. |
| `PICKS_GATE_WINDOW_MINUTES` (`picksGate.js`) | `120` | How long after picks' 17:00 ET target the dependency gate keeps re-checking collect.yml's EOD run status before giving up and recording a `miss`. Wider than `DISPATCH_WINDOW_MINUTES` since it must cover collect_eod's own self-heal window plus its run time, not just one job's normal margin. |
| `JOB_SCHEDULE[*].hour` / `.minute` | `collect_preclose` 15:50, `collect_eod` 17:00, `picks` 17:00 (ET, gated — see § Picks dependency gate) | Per-job target wall-clock time. |
| `JOB_SCHEDULE[*].weekdays` | `[1,2,3,4,5]` (Mon–Fri) for all current jobs | ISO weekday gate per job; a future Sunday-only job (e.g. the roadmap's weekly taxonomy check) would use `[7]`. |
| `JOB_SCHEDULE[*].gated` | `true` for `picks` only | Marks a job as dependency-gated (routed through `runPicksGate` instead of dispatched directly on window-open). |

Also documented in `CLAUDE.md` § Automation, per this repo's 3-places rule
for configurable constants.

## Cron schedule (legacy jobs migrated to `JOB_SCHEDULE`)

| Job | ET target (auto-DST) | Purpose |
|-----|-----------------------|---------|
| `collect_preclose` | 15:50 | pre-close snapshot before the market close |
| `collect_eod` | 17:00 | EOD post-close snapshot |
| `picks` | 17:00 (gated, window through 19:00) | picks selector — dependency-gated on collect_eod's actual run success (issue #259), not a fixed later time; see § Picks dependency gate |

## Monitoring and validation

### Ongoing health checks (no setup required)

```bash
# Is the Worker alive and KV connected?
curl https://finviz-cron-dispatcher.salmonbaby8.workers.dev/health

# What did the last tick's dispatches produce, per job?
curl https://finviz-cron-dispatcher.salmonbaby8.workers.dev/last
```

`/last` returns
`{last_dispatch: {collect_preclose, collect_eod, picks, picks_gate_check, legacy}}`.
`collect_preclose`/`collect_eod`/`picks` are each a
`{ts, status, ok, error, job, workflow, ref, etDate}` record written to KV on
every successful or attempted dispatch (never on a no-op tick).
- `ok: true, status: 204` = GitHub accepted the dispatch.
- `error: "github_401"` = PAT expired — rotate `GITHUB_DISPATCH_TOKEN`.
- `error: "github_422"` = `DISPATCH_REF` branch no longer exists; update `wrangler.toml` vars and redeploy.
- `error: "fetch_failed"` = network issue on Cloudflare's side.

`picks_gate_check` is a separate `{ts, outcome, reason, etDate}` record
(issue #259) — written on **every** gate evaluation, not just an eventual
dispatch, so a stuck check is visible even on a day picks never fires:
- `outcome: "dispatch"` = the gate found a successful matching EOD run and
  dispatched picks this tick (a `last_dispatch_picks` record follows).
- `outcome: "waiting"` = not yet resolved; will retry next tick within the
  17:00–19:00 ET window. Check `reason`: `collect_eod_not_dispatched` (EOD
  collect hasn't fired yet today), `eod_run_not_found` /
  `eod_run_in_progress` (dispatched, but the matching Actions run hasn't
  shown up / finished yet), `eod_run_<conclusion>` (e.g.
  `eod_run_failure` — the EOD run itself failed), or
  `run_status_fetch_failed:<code>` (the GitHub Actions runs-list read
  itself failed — see § Token read scope if this persists).
- `outcome: "miss"` = the window closed (120 min after target) without a
  successful EOD run; picks did not fire today. Logged at `error` level too.

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
