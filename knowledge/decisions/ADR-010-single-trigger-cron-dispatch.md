# ADR-010: Single Cron Trigger with in-code ET routing, auto-DST, and dependency-driven dispatch

**Date**: 2026-08-06
**Status**: Accepted

## Context

`worker-cron/finviz-cron-dispatcher` (introduced in ADR-004) currently burns **3 of the
Cloudflare account's hard 5-cron-trigger limit** (shared with unrelated `distil-*` workers —
`worker-cron/wrangler.toml:34`) on three timestamps that differ only by time-of-day within
the same weekday range:

- `48 19 * * 2-6` — collect, pre-close
- `01 21 * * 2-6` — collect, EOD
- `31 22 * * 2-6` — picks, EOD + 90 min

Hitting the account limit already caused a real outage: issue #252 — the picks cron failed
to deploy and picks silently had no trigger and no data from 2026-07-17 onward (see
`CLAUDE.md` § Automation). An intraday collect trigger had to be removed just to free a slot
for picks, which was itself only a stopgap.

Two further problems compound the trigger scarcity:

1. **DST is fixed-UTC and manual.** Cloudflare Cron Triggers do not follow DST. Every March
   and November, `worker-cron/wrangler.toml` `[triggers] crons` *and* the `PICKS_CRON` string
   constant in `worker-cron/src/index.js:26` must be hand-edited in lockstep (plus the mirrored
   GitHub `schedule:` cron in `collect.yml`), or jobs silently fire an hour off local time.
   This is a recurring footgun, not a one-time cost.
2. **Picks timing is hope, not verification.** `31 22` is chosen as "EOD collect + 90 minutes,"
   a margin meant to cover `collect.yml` + `compute_deltas.py` + git push finishing in time
   (`worker-cron/wrangler.toml:27-31`). There is no check that those steps actually succeeded
   before picks fires — just a time buffer and a stale-read guard in `collect_picks.py` that
   makes a too-early fire a safe no-op (at the cost of that day's picks run being lost, not
   retried).
3. **No trigger budget for new jobs.** A morning market-open workflow (see
   `planning/roadmap-cron-lifecycle.md` WS3/WS4) has been wanted but there is no room under the
   5-trigger ceiling to add it as a fourth distinct cron.

A senior engineer on a sibling Cloudflare Worker project shared the applicable doctrine: use
**one cron trigger per project**, ride a single tick, and gate multiple logical jobs inside
`scheduled()` by time-of-day/day-of-week computed in code — not one trigger per cadence. This
scales to effectively unlimited logical jobs on a single trigger.

This ADR **builds on ADR-004** (which established the Worker-as-scheduler,
`workflow_dispatch`-not-scrape architecture) — it does not reverse that decision, it refines
*how the trigger layer is structured* underneath it.

## Decision

**Collapse the 3 Cloudflare Cron Triggers to ONE: `*/5 * * * *`** (fires every 5 minutes, all
days, all times — gating happens entirely in code, not in the cron expression). This frees 2 of
the account's 5 trigger slots immediately and, more importantly, makes the number of logical
jobs the dispatcher can run **unbounded** — no longer trigger-budget-limited. New jobs (weekly
taxonomy check, held-tickers feed, a future morning surface) become a code change, not a
Cloudflare-account-limit negotiation.

**Route inside `scheduled()` via a pure, unit-testable function** `(etNow) -> string[]`
(job names to dispatch on this tick), replacing today's exact-cron-string match
(`workflowForCron(cron)` in `worker-cron/src/index.js:52-54`, which routes on
`cron === PICKS_CRON`). Because the tick is now a fixed 5-minute grid, job firing minutes shift
to the nearest 5-minute boundary — e.g. `:48 → :50`, `:01 → :00`, `:31 → :30`. This is harmless:
`collect.py` is last-write-wins per `date` (irrelevant which minute within the hour it lands),
and picks gains an explicit dependency gate (below) that supersedes the old fixed-margin timing
entirely.

**Auto-DST via `Intl.DateTimeFormat`.** Compute Eastern wall-clock time inside the Worker with
`Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', ... })` — Cloudflare Workers'
V8 runtime ships full ICU timezone data, so this correctly tracks EST/EDT transitions with no
lookup table to maintain. Jobs are gated on ET wall-clock (e.g. "collect EOD fires at 17:00
ET"), which makes the twice-yearly manual UTC edit **disappear entirely** — this is the single
biggest correctness win in this change, since it eliminates a whole class of "forgot to shift
the cron string → row stamped against the wrong hour" bugs that the current design invites
twice a year. Weekday gating (Mon–Fri) is likewise computed from ET wall-clock weekday, not UTC
weekday — this correctly handles the edge case where a Friday-evening tick in ET is already
Saturday in UTC (or vice versa on Sunday night). With both weekday and time-of-day gated in
code from one ET wall-clock computation, the single trigger `*/5 * * * *` plus the routing
function becomes the **single source of truth** for the whole schedule — no more parallel
cron-expression bookkeeping across `wrangler.toml`, `index.js`, and `collect.yml`.

**Trade-off, stated honestly:** running every 5 minutes around the clock produces roughly
2,000 extra no-op ticks/month (nights, weekends, hours with nothing scheduled) versus today's
3 triggers/day. These are free on the Workers free tier (Cron Trigger invocations are billed
as ordinary requests), but the no-op path must be genuinely cheap: no KV writes and no log
noise on a tick where nothing was dispatched, or observability degrades under the added volume.
See `planning/cron-consolidation-state-machine.md` § Observability for the concrete guard.

**Dependency-driven dispatch for picks, replacing the time-margin.** Today picks fires 90
minutes after collect and merely hopes `compute_deltas.py` + the git push finished
(`worker-cron/wrangler.toml:27-31`). Replace this with a state check: on each tick in the picks
window, the dispatcher asks the GitHub API (it already holds `GITHUB_DISPATCH_TOKEN`, scoped to
this repo) whether today's EOD `collect.yml` run **succeeded** and whether a deltas commit for
today's date has landed on the default branch, before dispatching `collect_picks.yml`. Two
mechanisms were considered for how the dispatcher learns this (see Alternatives) — **polling
on each tick is the chosen mechanism**: no new inbound HTTP surface, reuses the existing
token, and fits naturally into an already-periodic tick. Self-heal and retry-on-miss fall out
of the same check for free: if the expected ET window has passed and today's dispatch record
shows no success, the next tick can re-dispatch and/or write an alert record, instead of the
day silently going missing (as happened in issue #252). This state-check loop is intended to
let the project **retire the healthchecks.io dead-man's-switch on `collect_picks.yml`** and
reduce reliance on GitHub's failure-email path as the only signal.

**Keep both existing GitHub `schedule:` backstops** (in `collect.yml` and, per the issue #252
interim fix, `collect_picks.yml`). A single Worker on a single trigger is now a *stronger*
single point of failure than 3 independent triggers were — if the Worker is ever paused,
misconfigured, or hits an unrelated Cloudflare account issue, every job it owns goes dark at
once. The GitHub backstop matters **more** under this design, not less, and should not be
removed as part of this change.

## Alternatives considered

- **Keep 3 separate cron triggers (status quo).** Rejected: trigger-budget-limited (blocks any
  new job without either cutting an existing one or renegotiating account limits — this already
  bit the project once via issue #252), and does nothing about the recurring manual DST edit.
- **Hourly tick, `0 * * * *`, with jobs gated to the top of the hour.** Rejected: forces every
  job off its natural minute. The `:48` pre-close job in particular is deliberately a few
  minutes before market close (16:00 ET) to snapshot the pre-close tape; rounding to the top of
  the hour would move it to `:00` = 4:00 PM ET, which *is* the close, defeating the "pre-close"
  distinction the job exists for.
- **Every-minute tick, `* * * * *`.** Rejected as unnecessary — nothing in this pipeline needs
  sub-5-minute precision, and it multiplies no-op tick volume for no benefit over the 5-minute
  grid.
- **Success-callback from `collect.yml` to a Worker endpoint**, instead of the dispatcher
  polling GitHub. Rejected: adds a new inbound HTTP surface to the Worker (a new route,
  presumably authenticated) and a new secret for `collect.yml` to call it back with, for a
  capability (`GITHUB_DISPATCH_TOKEN` already reads workflow-run state) the dispatcher already
  has read access to via polling. Polling is simpler and has a smaller blast radius.

## Consequences

- **2 of 5 Cloudflare cron-trigger slots freed** immediately; the number of logical jobs the
  dispatcher can host is no longer trigger-budget-limited, which is what unblocks
  `planning/roadmap-cron-lifecycle.md` WS3 (morning confirmation surface) and the WS5
  held-tickers feed without any further Cloudflare-account negotiation.
- **DST toil is gone.** No more twice-yearly manual edits to `wrangler.toml` crons,
  `PICKS_CRON` in `index.js`, or the mirrored GitHub `schedule:` entries for time-of-day
  reasons (the GitHub-side entries still need to exist as backstops, but their UTC values can
  now be picked once and left — see the implementation doc for whether they also move to an
  ET-anchored equivalent or stay a fixed UTC approximation).
- **Picks timing becomes correct-by-dependency, not correct-by-hope.** The `31 22` fixed-margin
  guess is replaced by an actual state check against GitHub; a slow `compute_deltas.py`/push no
  longer risks a silently-skipped picks day.
- **Routing logic moves from declarative `wrangler.toml` cron strings to imperative code** (the
  `(etNow) -> string[]` routing function plus the ET/DST wall-clock calculation). This is a
  net positive for flexibility but means the routing function and the ET calculation **must be
  unit-tested** (`worker-cron/test/` already exists as a home for this) — a bug in either is now
  the single point of control for every job's schedule, where before a bug in one cron string
  only affected that one job.
- **The `PICKS_CRON` byte-identical-string-match constraint disappears** — routing no longer
  depends on `event.cron` matching a specific literal, removing a fragile coupling between
  `wrangler.toml` and `index.js` that required editing both files in lockstep (documented as a
  known footgun in the current `wrangler.toml:23-24` comment).
- **New config constants** (per-job ET target times, the 5-minute tick interval, the
  dependency-gate check window) must be documented in all three required places per this
  repo's standard (in-code comment on the constant; README § Configurable parameters; CLAUDE.md)
  — see `planning/cron-consolidation-state-machine.md` § Config constants table for the concrete
  list.
- **No-op ticks must stay quiet** (no KV write, no log line) or observability noise scales with
  the ~2,000/month extra idle ticks; this is a new operational requirement that didn't exist
  when every trigger fire was, by construction, a real dispatch.
