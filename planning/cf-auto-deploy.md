# CF Auto-Deploy: Cloudflare Workers CI/CD

**Status:** Planned — not yet implemented  
**Branch:** `claude/cloudflare-auto-deploy-mi0cb5`  
**Requested:** 2026-06-21 — "auto-deploy merged CF code to CF; stop relying on best intentions"

---

## Problem

Two production Cloudflare Workers handle live traffic but have no deployment automation.
Merging code changes requires a developer to manually remember to run `npm run deploy`
from `worker/` or `worker-cron/`. This is a "best intentions" deployment model — no
enforcement, no audit trail, and a missed deploy on a critical fix has real downstream
consequences.

**`finviz-cron-dispatcher` is the heartbeat of the entire data collection pipeline.**
A code fix merged but not deployed means the collection schedule breaks silently.
**`finviz-ticker-lookup` serves the PWA's `/lookup` endpoint.** A fix not deployed
means users see bugs despite the code being "fixed."

---

## Solution

Add `.github/workflows/deploy-workers.yml` — a GitHub Actions workflow that:

1. Triggers on push to the default branch when `worker/` or `worker-cron/` files change
2. Runs the full test suite first (`npm ci && npm test`) — fails fast before any deploy
3. Deploys each worker independently in separate jobs (neither blocks the other)
4. Also triggerable manually via `workflow_dispatch` for ad-hoc deploys or debugging

---

## What is NOT changing

- Worker source code (`worker/src/`, `worker-cron/src/`) — no changes
- `wrangler.toml` files — KV bindings, vars, cron expressions unchanged
- Worker secrets (FMP_API_KEY, GITHUB_DISPATCH_TOKEN) — `wrangler deploy` does NOT
  reset or touch secrets set via `wrangler secret put`; live worker secrets are safe
- `tests.yml` workflow — its test jobs remain; this workflow is purely additive

---

## Trigger design

```yaml
on:
  push:
    branches: [claude/elegant-babbage-hlxnfy]   # current default; update to main at D1
    paths:
      - 'worker/**'
      - 'worker-cron/**'
      - '.github/workflows/deploy-workers.yml'
  workflow_dispatch:
```

Path filtering prevents noisy deploys on unrelated changes (Python script edits,
dashboard changes, data commits from GitHub Actions, etc.).

**When default branch changes to `main` (task D1):** update the `branches:` list and
also update `DISPATCH_REF` in `worker-cron/wrangler.toml` at the same time.

---

## Two independent jobs

### `deploy-ticker-lookup` (in `worker/`)

```
npm ci → npm test → npm run deploy
```

`npm run deploy` in `worker/` expands to: `npm run build:taxonomy && wrangler deploy`

`build:taxonomy` reads `data/sectors/snapshots.csv` and `data/industries/snapshots.csv`
(both committed to the repo) to validate Finviz group names and regenerate
`worker/src/taxonomy_map.json` and `worker/src/etf_overrides.json`. These JSON files
are committed, but regenerating them at deploy time ensures the deployed Worker always
reflects the latest snapshot data without a separate manual step.

### `deploy-cron-dispatcher` (in `worker-cron/`)

```
npm ci → npm test → npm run deploy
```

`npm run deploy` in `worker-cron/` = `wrangler deploy`. Simple — no build step.

---

## Required GitHub Secrets

| Secret | Already set? | Notes |
|--------|-------------|-------|
| `CLOUDFLARE_API_TOKEN` | Yes (set 2026-06-14) | Scoped: Workers Scripts:Edit, KV Storage:Edit, Account Settings:Read |
| `CLOUDFLARE_ACCOUNT_ID` | **Needs verification** | Required by wrangler in CI; check GitHub → Settings → Secrets → Actions |

If `CLOUDFLARE_ACCOUNT_ID` is not already in repo secrets, add it before the
implementation PR. It's visible in the Cloudflare dashboard URL
(`https://dash.cloudflare.com/<account-id>`) or via `wrangler whoami`.

---

## Deployment safety notes

- `wrangler deploy` is **not destructive** — it pushes new code but leaves:
  - Secrets (FMP_API_KEY, GITHUB_DISPATCH_TOKEN) intact
  - KV namespace data intact
  - Cron trigger expressions (defined in `wrangler.toml`, re-applied on deploy — no
    change to active triggers unless the toml changes)
- Both workers are already live; a CI deploy of unmodified code is a no-op functionally
- Rollback: Cloudflare keeps deployment history; manual rollback via the Cloudflare
  dashboard takes ~30 seconds, or via `wrangler deployments deploy <version-id>`

---

## File to create

**`.github/workflows/deploy-workers.yml`**

```yaml
name: Deploy Cloudflare Workers

on:
  push:
    branches: [claude/elegant-babbage-hlxnfy]
    paths:
      - 'worker/**'
      - 'worker-cron/**'
      - '.github/workflows/deploy-workers.yml'
  workflow_dispatch:

jobs:
  deploy-ticker-lookup:
    name: Deploy finviz-ticker-lookup
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - name: Install dependencies
        working-directory: worker
        run: npm ci
      - name: Run tests
        working-directory: worker
        run: npm test
      - name: Deploy
        working-directory: worker
        env:
          CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
          CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
        run: npm run deploy

  deploy-cron-dispatcher:
    name: Deploy finviz-cron-dispatcher
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - name: Install dependencies
        working-directory: worker-cron
        run: npm ci
      - name: Run tests
        working-directory: worker-cron
        run: npm test
      - name: Deploy
        working-directory: worker-cron
        env:
          CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
          CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
        run: npm run deploy
```

---

## Verification (after implementation PR is merged)

1. Confirm the workflow appears in the GitHub Actions tab under "Deploy Cloudflare Workers"
2. Trigger manually via `workflow_dispatch` — both deploy jobs should pass
3. Check the Cloudflare dashboard: both workers show a new deployment timestamp
4. Hit `/health` on both worker URLs to confirm liveness post-deploy:
   - `https://finviz-ticker-lookup.salmonbaby8.workers.dev/health`
   - `https://finviz-cron-dispatcher.salmonbaby8.workers.dev/health`
5. Make a trivial change to `worker-cron/src/index.js` only, push — confirm only
   `deploy-cron-dispatcher` fires (path filter working correctly)

---

## What this doesn't solve

- **No staging environment** — deploys go straight to production. Acceptable given the
  test gate and the workers' simple, well-tested logic. A CF `[env.staging]` block in
  `wrangler.toml` would be the next step if complexity grows.
- **No rollback automation** — manual via Cloudflare dashboard or
  `wrangler deployments deploy <version-id>`. Fast enough given the simplicity.
