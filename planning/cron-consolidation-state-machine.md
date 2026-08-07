# Plan: Cron Consolidation — Single-Trigger State-Machine Dispatcher

## Overview

Implementation-ready design for WS1 (`planning/roadmap-cron-lifecycle.md`) — collapsing
`worker-cron/finviz-cron-dispatcher`'s 3 Cloudflare Cron Triggers to 1, moving all schedule
logic into in-code, unit-tested routing gated on Eastern wall-clock time, and replacing the
picks fixed-time-margin with a dependency check against GitHub run/commit state. This is the
low-regret unblocker for the rest of the cron-lifecycle roadmap: no downstream workstream needs
a new Cloudflare cron trigger once this lands.

The **decision record** for *why* is `knowledge/decisions/ADR-010-single-trigger-cron-dispatch.md`
— read that first if you need the rationale or the rejected alternatives. This document is the
*how*.

## Current state

- `worker-cron/wrangler.toml:34` — `crons = ["01 21 * * 2-6", "48 19 * * 2-6", "31 22 * * 2-6"]`
  (3 of the account's hard 5-trigger limit, shared with unrelated `distil-*` workers).
- `worker-cron/src/index.js:26` — `PICKS_CRON = '31 22 * * 2-6'`, a string constant that must
  stay byte-identical to the picks entry in `wrangler.toml`.
- `worker-cron/src/index.js:52-54` — `workflowForCron(cron)` routes by exact string match:
  `cron === PICKS_CRON ? 'picks' : 'collect'`. Any other cron value (i.e. either collect entry,
  or any future addition not explicitly routed) defaults to `collect` — chosen as the "safe"
  default because collect is last-write-wins per date, so a spurious extra collect run is
  harmless, whereas a spurious picks run scrapes up to 50 screener pages.
- `worker-cron/src/index.js:57-71` — `scheduled()` handler calls `dispatchWorkflow(env, cron,
  workflowForCron(cron))` on every fire; no state check beyond "this cron fired."
- DST: manual. `wrangler.toml:16-24` documents the twice-yearly UTC-shift procedure and the
  winter-equivalent cron strings in a comment block; nothing enforces it's actually done.
- Picks timing safety net: `collect_picks.py`'s stale-read guard (referenced in
  `wrangler.toml:27-31`) makes an early fire a safe no-op, but the day's picks are then simply
  lost — no retry.

## Target design

### The single tick

`wrangler.toml [triggers] crons = ["*/5 * * * *"]` — one Cron Trigger, fires every 5 minutes,
every day, all year. No weekday restriction in the cron expression itself; weekday gating moves
entirely into code (see ET/DST below).

### The routing function contract

```js
// Pure function: no I/O, no env access. Fully unit-testable with a fixed Date.
// etNow: { hour: number, minute: number, weekday: 1-7 (Mon=1..Sun=7), dateStr: "YYYY-MM-DD" }
//   — the caller derives etNow from Intl.DateTimeFormat before calling this.
// Returns: string[] — job names to dispatch on this tick, e.g. ["collect"], ["picks"], [].
function jobsForTick(etNow) { ... }
```

Design constraints:
- **No I/O inside the routing function.** GitHub API calls (for the picks dependency gate) are
  a separate concern layered on top in `scheduled()`, not inside `jobsForTick`. This keeps the
  time-based routing itself trivially unit-testable with fixed clock fixtures — no mocking
  `fetch`.
- Weekday check: `etNow.weekday` in `[1..5]` (Mon–Fri) for all current jobs; Sunday-only jobs
  (taxonomy drift check, WS-cross-cutting) check `weekday === 7`.
- Time-of-day check: each job has a target ET `{hour, minute}` and fires when the current tick's
  `{hour, minute}` (already rounded to the 5-minute grid by construction) equals it. Because the
  tick is a fixed 5-minute grid, target minutes must themselves be multiples of 5 — see the
  config table below for the shifted values.

**Illustrative routing table** (ET time → jobs dispatched this tick; all times America/New_York,
DST-adjusted automatically by the wall-clock calculation, not hardcoded per season):

| ET time | Weekday | Jobs dispatched |
|---|---|---|
| 15:50 | Mon–Fri | `collect` (pre-close; shifted from legacy `:48`) |
| 17:00 | Mon–Fri | `collect` (EOD; shifted from legacy `:01`) |
| 17:00–close of window | Mon–Fri | `picks`, gated on the dependency check (see below) — no longer a fixed `18:30` fire |
| any other tick | any | `[]` (no-op) |
| 09:00 (example, WS-cross-cutting) | Sunday | `taxonomy_check` |

The picks row is intentionally not pinned to one clock time — see next section.

### DST handling detail

Inside `scheduled(event, env, ctx)`, before calling `jobsForTick`:

```js
const parts = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York',
  weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false,
}).formatToParts(new Date());
// assemble { hour, minute, weekday, dateStr } from parts
```

`Intl.DateTimeFormat` with `timeZone: 'America/New_York'` returns the correct EST/EDT-adjusted
wall-clock time automatically — Cloudflare Workers' V8 runtime carries full ICU tz data, so this
requires no seasonal lookup table and no manual edit on the DST transition Sundays. This
replaces every hardcoded UTC cron string in the current design; `wrangler.toml` no longer needs
a "winter UTC equivalents" comment block at all.

`dateStr` (the ET calendar date, `YYYY-MM-DD`) is also needed for the picks dependency gate
below, to check "did *today's* EOD collect run land."

### Dependency-gate detail (picks)

Replaces the fixed `EOD + 90min` margin. On each tick where ET time is within a bounded window
after the EOD collect target (e.g. 17:00–19:00 ET, Mon–Fri — an upper bound exists so the gate
doesn't poll indefinitely into the evening if collect never lands), and picks has not already
been dispatched successfully today:

1. Query the GitHub Actions API for the most recent `collect.yml` run on `DISPATCH_REF` —
   confirm `conclusion === 'success'` and that its date corresponds to today's ET trading date.
   (`mcp__github__actions_get` / `actions_list` equivalents, or a direct `GET
   /repos/{owner}/{repo}/actions/workflows/collect.yml/runs` call from the Worker, mirroring the
   existing `dispatchWorkflow()` POST pattern in `worker-cron/src/index.js:73-113`.)
2. **Deltas-landed proxy — resolved.** `collect.yml` runs `collect.py` → `compute_deltas.py` →
   `evaluate_picks.py` → `git commit && git push` **all in one job**, with the push as the final
   data step (`.github/workflows/collect.yml:48–195`). So a `collect.yml` run whose
   `conclusion === 'success'` for today's ET date **already implies deltas were computed and
   pushed** — step 1's run-success check is sufficient on its own, and a separate commit-presence
   check is optional hardening, not a requirement. (One benign edge: a same-day re-run with
   identical data hits `git diff --cached --quiet` and pushes no new commit, but in that case the
   prior successful run already pushed today's deltas, so picks still has fresh data — the
   run-success proxy stays correct.)
3. If both checks pass: dispatch `collect_picks.yml`, write a KV dispatch record as today.
4. If checks fail and the bounded window has not yet closed: no-op, try again next tick (5 min
   later) — this is the free retry/self-heal.
5. If the bounded window closes without success: write an explicit KV "missed" record (distinct
   from a normal dispatch record) so `/last` surfaces it, and log at `error` level. This record
   is what future alerting keys off, and is the basis for retiring the healthchecks.io dead-man's
   switch on `collect_picks.yml` — but do not remove that switch in this workstream until the
   missed-record path has been observed working for at least one real week, per the rollout
   plan below.

### Observability

- KV schema stays per-workflow (`last_dispatch_collect`, `last_dispatch_picks`, matching
  `WORKFLOWS` in `worker-cron/src/index.js:29-38`), plus a new `last_gate_check_picks` (or
  similar) record capturing the dependency-check outcome, not just the eventual dispatch.
- **No-op ticks must not write to KV and must not log**, other than perhaps a debug-level line
  gated off in production. With ~288 ticks/day on a 5-minute grid and only a handful being real
  dispatches, an unconditional log line per tick would flood Worker logs relative to today's
  3-fires-a-day baseline. This is a new requirement introduced by this design, not carried over
  from the 3-trigger version where every fire was by definition meaningful.

### Backstops retained

Both GitHub `schedule:` cron backstops (`collect.yml`'s `48 19 * * 1-5` and `collect_picks.yml`'s
interim `31 23 * * 1-5`) stay in place, unchanged by this workstream. Per ADR-010, a single
Cloudflare trigger is a stronger single point of failure than 3 independent ones were, so the
backstop's role increases, not decreases. Whether their UTC times get any adjustment is an open
question below.

### Config constants table

| Constant | Value | Controls | Documented in |
|---|---|---|---|
| Tick interval (`wrangler.toml` cron) | `*/5 * * * *` | How often `scheduled()` fires; the grid every job's target time must land on | in-code comment in `wrangler.toml`, README § Configurable parameters, CLAUDE.md § Automation |
| Collect pre-close target ET time | `15:50` (was `15:48`) | When the pre-close collect job dispatches | same three places |
| Collect EOD target ET time | `17:00` (was `17:01`) | When the EOD collect job dispatches | same three places |
| Picks dependency-gate window | e.g. `17:00`–`19:00` ET (exact bound TBD at implementation) | How long the picks gate keeps retrying before giving up and recording a miss | same three places |
| Taxonomy-check target (Sunday) | TBD | When the weekly drift check dispatches (see roadmap doc § Cross-cutting cheap wins) | same three places |

Exact final target-time values (whether pre-close/EOD shift to `:50`/`:00` as shown, or some
other 5-minute-aligned choice) are an implementation decision, not re-litigated here — this
table is the required 3-places-documented pattern per `CLAUDE.md` § "Configurable items."

## Testing plan

- `worker-cron/test/` already exists (per ADR-010) as the home for these tests — confirm its
  current test runner/framework during implementation before adding to it.
- **Routing function** (`jobsForTick`): table-driven unit tests covering every row of the
  illustrative routing table above, plus edge cases: Friday 23:55 ET vs the UTC-equivalent
  Saturday date (weekday-gating correctness across the day boundary), a DST-transition day
  (verify `Intl.DateTimeFormat` produces the pre- and post-shift wall-clock hour correctly on
  the same UTC instant either side of 2:00 AM local on transition Sunday), and a plain no-op
  tick.
- **ET/DST wall-clock calculation**: isolate the `Intl.DateTimeFormat`-based conversion into its
  own small pure function so it can be tested independently of the routing function, with fixed
  UTC `Date` inputs spanning both DST regimes.
- **Dependency-gate logic**: unit-testable separately from its GitHub API call by injecting a
  fake "run status" result — test the three outcomes (success → dispatch, not-yet → no-op-retry,
  window-closed-without-success → miss record) independently of network I/O.

## Rollout / migration steps

1. Implement `jobsForTick`, the ET/DST helper, and their unit tests in `worker-cron/` without
   touching `wrangler.toml` yet (code lands, dead code path, verified by tests alone).
2. Implement the dependency-gate check and its KV record shape; unit test with fake GitHub
   responses.
3. Wire `scheduled()` to call the new routing + gate logic, but **keep the 3 existing cron
   triggers active** for one deploy cycle so behavior can be compared against the old
   string-match routing in production logs/KV records before cutting over the trigger itself
   (the routing function runs on every 5-minute-equivalent boundary regardless of which cron
   string caused the fire, so this comparison is possible without a hard cutover instant).
4. Once the new routing's dispatch times match the old schedule's for a few trading days, update
   `wrangler.toml [triggers] crons` to `["*/5 * * * *"]` and remove `PICKS_CRON` /
   `workflowForCron`'s string-match logic (or leave `workflowForCron` as a thin back-compat
   wrapper if `/last` or tests still reference it — decide during implementation).
5. Confirm the 2 freed cron slots by checking the Cloudflare dashboard trigger count for the
   account (5-limit, shared with `distil-*` workers) — this is the concrete proof the outage
   condition from issue #252 cannot recur in this exact shape.
6. Update `CLAUDE.md` § Automation and README § Configurable parameters to describe the new
   single-trigger design (out of scope for this planning doc itself, but required before the
   implementation PR is considered done, per repo's 3-places documentation rule).
7. Leave the healthchecks.io dead-man's switch on `collect_picks.yml` in place through at least
   one full week of the new dependency-gate running in production; only remove it in a follow-up
   change once the "missed" KV record path has been observed to fire correctly (or not needed to
   fire) across that week.

## Open questions

- Should the GitHub `schedule:` backstop UTC times also move to be computed/derived rather than
  hardcoded, or is a fixed UTC approximation (accepting a 1-hour seasonal drift in the backstop
  only, never in the primary path) acceptable given it's explicitly a last-resort fallback? ADR-010
  doesn't resolve this either way.
- Exact width of the picks dependency-gate retry window (this doc used `17:00`–`19:00` ET as an
  illustrative placeholder) — needs a decision informed by how long `collect.yml` +
  `compute_deltas.py` + push realistically take in the worst observed case.
- ~~Whether "collect.yml run succeeded" alone is a sufficient proxy for "deltas commit landed"~~
  — **RESOLVED** (see § Dependency-gate detail, step 2): `compute_deltas.py` + push are steps in
  the same `collect.yml` job, so run-success is sufficient; a commit-presence check is optional
  hardening only.
- Whether `workflowForCron`/`PICKS_CRON` should be deleted outright or kept as a deprecated
  back-compat shim during the rollout window described in step 3 above.
- Final target ET times for each job (the `:50`/`:00` values above are illustrative nearest-5-
  minute shifts of the legacy `:48`/`:01`, not independently re-derived from first principles) —
  confirm they still make sense operationally before locking them into the config table.
