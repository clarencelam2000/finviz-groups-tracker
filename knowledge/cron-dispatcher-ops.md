# Ops guide: finviz-cron-dispatcher (Cloudflare Worker)

**Deployed:** 2026-06-19  
**Worker URL:** `https://finviz-cron-dispatcher.salmonbaby8.workers.dev`  
**Validated live:** 2026-06-19 — end-to-end test (real PAT, real dispatch endpoint, HTTP 204,
`collect.yml` run #38 launched via `workflow_dispatch`).

See `worker-cron/README.md` for the full monitoring reference. This file covers the
*why* and the *what-if* at an ops level.

---

## How to confirm it's working day-to-day

Three increasing-effort checks:

**1. `/last` endpoint** (5 seconds)
```bash
curl https://finviz-cron-dispatcher.salmonbaby8.workers.dev/last
```
`ok: true, status: 204` after the expected fire time = all good. `/last` is `null` until the first
real cron fires (it only writes on scheduled triggers, not on direct test POSTs).

**2. GitHub Actions** (10 seconds)  
After each expected fire time, a `workflow_dispatch`-triggered run should appear in
Actions → Daily Snapshot. If only `schedule`-triggered runs appear, the Worker dispatched
and the GitHub cron backstop caught it — but the Worker may have a problem.

**3. `data/fetch_log.csv` timing** (the real signal)  
Compare the `timestamp` column vs. the cron schedule. The whole point of this change is that
drift collapses from hours to minutes. This is the ground-truth validation over the first
week of operation.

---

## What `/last` errors mean

| `error` value | Cause | Fix |
|---|---|---|
| `null` (ok=true) | Successful dispatch | — |
| `"github_401"` | PAT expired or revoked | Rotate `GITHUB_DISPATCH_TOKEN` secret |
| `"github_422"` | `DISPATCH_REF` branch doesn't exist | Update `DISPATCH_REF` in `wrangler.toml` and redeploy |
| `"github_403"` | PAT doesn't have Actions write scope | Mint a new fine-grained PAT (Actions: R/W, this repo only) |
| `"fetch_failed"` | Cloudflare-side network error | Usually transient; check CF status page |
| `"missing_token"` | `GITHUB_DISPATCH_TOKEN` secret deleted | Re-set via `wrangler secret put` |

---

## Rotating the PAT

When the `GITHUB_DISPATCH_TOKEN` PAT expires:

1. Mint a new GitHub fine-grained PAT: this repo only, **Actions: Read and write**.
2. `printf '%s' "$NEW_TOKEN" | wrangler secret put GITHUB_DISPATCH_TOKEN` from `worker-cron/`.
3. No redeploy needed — Worker secrets update in-place.
4. Verify: `curl .../last` on the next scheduled fire.

---

## Changing the cron schedule

Edit `[triggers] crons` in `worker-cron/wrangler.toml`, then `npm run deploy` from `worker-cron/`.
Also mirror the EOD entry change in `.github/workflows/collect.yml` (the GitHub backstop).
See `CLAUDE.md` § Automation and `README.md` § Scrape schedule.

---

## Changing which branch collect.yml runs on

Update `DISPATCH_REF` in `worker-cron/wrangler.toml` `[vars]`, commit, then `npm run deploy`.
(CLAUDE.md has a `TODO(D1)` note to change this to `"main"` once that branch exists.)

---

## If the Worker needs to be paused

Pause via the Cloudflare dashboard (Workers → finviz-cron-dispatcher → Disable). The GitHub
cron backstop (`48 19 * * 1-5` in `collect.yml`) continues firing independently — so you still
get the EOD snapshot. The two intraday runs (09:49, 10:51 ET) are lost while the Worker is
paused.
