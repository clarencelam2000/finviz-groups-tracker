# ADR-004: Cloudflare Cron Trigger as primary scrape scheduler

**Date**: 2026-06-19
**Status**: Accepted

## Context

The daily Finviz scrape was scheduled by three `schedule:` cron entries in
`.github/workflows/collect.yml`. GitHub's *scheduled* workflows are documented to
be delayed under load and **dropped entirely** during peak periods; our own
`data/fetch_log.csv` confirmed 4–10 hour drift between the scheduled UTC time and
the actual run. That made "the EOD snapshot just before the close" unreliable.

The complaint is about *scheduling*, but the scrape itself is pinned to GitHub's
infrastructure for a hard reason: `scripts/collect.py` drives Playwright/Chromium
for 2–4 minutes, and Finviz sits behind Cloudflare bot-detection that 403s Google
Cloud IPs while letting GitHub's Azure IPs through (see `CLAUDE.md` § Playwright/
Finviz notes). So the two concerns — *when* to run vs. *where* to run — must be
decoupled.

## Decision

Use a **new dedicated Cloudflare Worker `finviz-cron-dispatcher`** (`worker-cron/`)
purely as the scheduler. Its Cron Triggers fire on time and POST a GitHub
`workflow_dispatch` to launch the existing, proven `collect.yml` on Azure runners.
`workflow_dispatch` is event-driven and processed promptly — it is *not* subject
to the schedule-drop behavior that causes the drift. `trading_date()` in
`collect.py` already normalizes any residual timing drift to the correct trading
day, so the pipeline needs no logic changes.

Keep **one** GitHub cron (`48 19 * * 1-5`, the EOD entry) as a redundancy
backstop. Both fire simultaneously at `:48` every trading day — intentional
redundancy, not a delayed fallback. Last-write-wins per date makes the double-run
harmless.

## Alternatives considered

- **Cron → `workflow_dispatch` (chosen).** Minimal blast radius; reuses the
  proven Azure-runner pipeline; precise scheduling.
- **Cloudflare Browser Rendering edge-scrape.** Move the whole scrape to a Worker
  via `@cloudflare/puppeteer`. Rejected for now: Workers can't run a 2–4 min
  Chromium session or pandas `compute_deltas.py`, can't `git commit` CSVs, and
  would scrape from Cloudflare IPs into a Cloudflare-protected site (untested,
  likely challenged). Whether this is *ever* viable is the Phase 3 research spike
  (`planning/cloudflare-cron-scheduler.md`); deferred, findings to land as a
  follow-up ADR.
- **`scheduled()` handler on the live `finviz-ticker-lookup` Worker.** Rejected:
  couples the scheduler's deploy cycle to the live ticker-lookup Worker. A
  dedicated Worker has an independent deploy and zero blast radius.
- **Remove the GitHub cron entirely.** Rejected: the single same-time backstop is
  cheap insurance if the Worker is ever paused/misconfigured.
- **Time-offset GitHub fallback (fire 15 min later).** Rejected: GitHub's cron is
  itself too timing-unreliable to provide a meaningful delayed-safety guarantee.

## Consequences

- Scheduling becomes reliable; the EOD run should land near the close (drift
  collapses from hours to minutes — to be validated against `fetch_log.csv`).
- New deploy surface: a second Worker + a small KV namespace (`DISPATCH_LOG`,
  observability only) + one GitHub fine-grained PAT secret (`GITHUB_DISPATCH_TOKEN`,
  this repo, Actions: R/W).
- Cron expressions now live in `worker-cron/wrangler.toml`; the EOD entry is
  mirrored by the backstop cron in `collect.yml` — change both together.
- The scrape pipeline (`collect.py`, `compute_deltas.py`, commit) is untouched.
