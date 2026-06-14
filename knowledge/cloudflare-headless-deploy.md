# Cloudflare Worker headless deploy from a Claude Code web session

**Date:** 2026-06-14
**Scope:** How to deploy the TICKER-1 Worker (`worker/`) from a Claude Code *web* session
without the interactive `wrangler login` browser popup.
**Verified against:** this repo's web execution environment, 2026-06-14.

---

## TL;DR

Earlier notes (PR #70, `planning/PLAN_ticker_lookup.md` Phase 0/2, and `worker/README.md`)
say the Worker deploy **cannot** run from a cloud session because it needs interactive
Cloudflare OAuth. **That is only true of the `wrangler login` path.** Wrangler also reads a
**`CLOUDFLARE_API_TOKEN`** environment variable and authenticates with it directly — no browser,
no popup. This is the standard CI/CD method, and it works from this web environment.

So: pre-generate a scoped API token in the Cloudflare dashboard, set it (plus the account ID and
the FMP key) as environment variables in the web session's environment configuration, and every
`wrangler` command runs non-interactively.

## Verified reachability (2026-06-14)

The web container's network policy permits the outbound endpoints a headless deploy needs:

| Endpoint | Result | Why it matters |
|---|---|---|
| `https://api.cloudflare.com/client/v4/` | reachable (real HTTP response) | `wrangler deploy`, `kv namespace create`, `secret put` all hit this |
| `https://registry.npmjs.org/` | HTTP 200 | `npm install` / `npx wrangler` |
| node / npm | v22 / 10.9 present | — |

> Note: the Playwright/finviz block documented in `CLAUDE.md` is a *different* concern
> (Playwright CDN + `finviz.com`). The Cloudflare API and npm registry are **not** blocked.
> `collect.py` still cannot run here; the Worker deploy now can.

## Auth precedence (the key fact)

If `CLOUDFLARE_API_TOKEN` is set in the environment, Wrangler uses it and **never** triggers the
OAuth browser flow. The popup is exclusive to `wrangler login`. Token auth fully replaces it for
deploy, KV, and secret operations.

## Token scope (least privilege)

Create at: Cloudflare dashboard → **My Profile → API Tokens → Create Token**. Use the
**"Edit Cloudflare Workers"** template, or a custom token with:

- Account → **Workers Scripts : Edit**
- Account → **Workers KV Storage : Edit**  (required for `kv namespace create` + the cache)
- Account → **Account Settings : Read**  (lets Wrangler resolve the account)
- **No Zone / DNS permissions** — deploy targets a `*.workers.dev` subdomain, not a custom domain.

Hygiene: set a short **expiration**, and **revoke** the token after the deploy URL is captured.
Scoped this way, a leak can only touch Workers/KV — never DNS or the whole account.

## Environment variables to set in the web session config

Three vars give a fully hands-off deploy:

| Var | Purpose | Committed? |
|---|---|---|
| `CLOUDFLARE_API_TOKEN` | scoped token above | never |
| `CLOUDFLARE_ACCOUNT_ID` | from CF dashboard sidebar; disambiguates multi-account logins | never |
| `FMP_API_KEY` | piped into `wrangler secret put` (becomes a Worker secret only) | never |

## Deploy sequence (run from `worker/` once the dir is on the base branch)

```bash
cd worker
npm install
npx wrangler kv namespace create LOOKUP_CACHE   # prints the namespace id
# write that id into worker/wrangler.toml ([[kv_namespaces]] id = "...") and COMMIT it
echo "$FMP_API_KEY" | npx wrangler secret put FMP_API_KEY   # non-interactive with token set
npm run deploy                                   # or: npx wrangler deploy
# capture the printed *.workers.dev URL — TICKER-2 (PWA) and TICKER-3 (Streamlit) need it
```

Sanity check after deploy:
```bash
curl "https://finviz-ticker-lookup.<subdomain>.workers.dev/lookup?t=AAPL"   # → Technology / Consumer Electronics
curl "https://finviz-ticker-lookup.<subdomain>.workers.dev/health"          # → {"status":"ok",...}
```

## Caveats

- **workers.dev subdomain:** if the account has never claimed one, the first deploy may prompt to
  register a subdomain (one-time, in the dashboard). Quick if it comes up.
- **wrangler.toml is committed with the KV namespace id** — that id is not a secret (it's an
  account-scoped resource handle), so committing it is expected and matches the plan.
- **FMP free-tier 429** after ~240 calls/session (see `fmp-api-findings.md`) — irrelevant at
  runtime thanks to the 30-day KV cache, but relevant if bulk-testing the live Worker.

## Follow-up: docs to correct after `worker/` lands on base

`worker/README.md` (in PR #70 / PR #74) and `planning/PLAN_ticker_lookup.md` Phase 0/2 both state
the deploy requires interactive OAuth and "cannot run from a cloud session." Update them to point
at the `CLOUDFLARE_API_TOKEN` headless path documented here. (Deferred from the 2026-06-14 session
because `worker/` was not yet on the base branch — editing it then would have conflicted with the
pending PR #74 merge.)
