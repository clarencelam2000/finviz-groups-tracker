# finviz-positions — WS5 trade-lifecycle store

Cloudflare Worker + D1 that owns the **private, per-position trade-lifecycle data** for WS5
(GitHub issue #264). Design: `planning/trade-lifecycle-engine.md`, `knowledge/decisions/ADR-012-trade-lifecycle-engine.md`.

Kept **separate** from `finviz-ticker-lookup` (public, unauthenticated cache API) on purpose: the
private financial-data write path must never share an origin or auth surface with the public cache.

## Phase status

This is **phase 1** of the four-phase WS5 plan (ADR-012 §10), with **phase 2 in progress**:

1. ✅ **D1 schema + authenticated, ticker-generic "I took it" write path** (this worker) — positions
   spine + first `entered` event, plus a read-back list.
2. 🟡 **Held-tickers feed (daily quote job → `ticker_quotes`, full column set, issue #297)** —
   in progress. `GET /held-tickers` and `POST /ingest/quotes` have landed on this worker; the
   GitHub Actions side (`scripts/collect_held.py`, `.github/workflows/collect_held.yml`) and the
   `worker-cron` `held` scheduled job are wired up alongside them. Not yet exercised against a
   live D1 instance / real held positions — treat as unverified end-to-end until a real run
   confirms it.
3. ⬜ `advance()` daily engine + tests.
4. ⬜ Push notifications (VAPID; the sibling `distil` worker's web-push code is the reference).

Phase 1 has **no engine and no feed** — a created position is a frozen record until phase 3. That is
by design (each phase is independently useful).

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/health` | none | liveness |
| `POST` | `/auth/login` | passphrase in body | exchange the login passphrase for a bearer token |
| `POST` | `/positions` | Bearer | create a position (one **lot**) + its `entered` event — the ticker-generic "I took it" write path (§ 8a) |
| `GET` | `/positions?state=` | Bearer | list the caller's positions, newest first (optional state filter) |
| `GET` | `/held-tickers` | Service token | WS5 phase 2: the union of open/managing/closing tickers the held feed must scrape (`{ tickers: [...] }`) |
| `POST` | `/ingest/quotes` | Service token | WS5 phase 2: append-only batch write of a day's scraped bars into `ticker_quotes` (`{ trade_date, collected_at, quotes:[...] }` → `{ written }`) |

**Two auth paths, one seam.** The interactive `Bearer` rows above are the owner's HMAC login token
(`authenticate()`); the two WS5-phase-2 machine rows use a **separate service token**
(`authenticateService()`, secret `POSITIONS_INGEST_TOKEN`) held only by the GitHub-Actions held-feed
job. The service token can read the held set and append market bars but **cannot** read, create, or
mutate positions — and the owner token cannot satisfy the service routes. Both live behind
`src/auth.js` (§ Auth). Market data (`ticker_quotes`) carries **no `user_id`** — it is public bars;
only the *selection* of tickers to fetch derives from private positions, at query time.

`POST /positions` body: `{ ticker, entry_price, initial_stop, qty, stop_basis?, meta?, days_to_earnings? }`.
`stop_basis` ∈ `prior_day_low | todays_low | 20ma | 50ma | manual` (default `manual`).
Validation rejects `initial_stop >= entry_price` (long-only: R = entry − stop must be > 0).
Each call creates an **independent lot** — "I took it" twice on one ticker makes two rows on purpose
(§ 3a scale-ins); there is deliberately no `(user_id, ticker)` uniqueness assumption.

## Auth (§ Auth — the one security decision, owner call 2026-08-13)

**Worker-native HMAC bearer token, not Cloudflare Access.** The PWA is a cross-origin GitHub-Pages
page (`clarencelam2000.github.io`) calling this worker on `*.workers.dev`. Cloudflare Access
authenticates via a cookie on the worker's domain, which is a *third-party* cookie to the PWA —
blocked by default in modern browsers. So Access would be fragile exactly where it matters. The
sibling `distil` worker on this same account already proves the worker-native pattern (session +
bearer). This meets the actual security goal (no world-readable secret in the public page): the
token is minted server-side from a login passphrase and lives only in the owner's browser.

- **`src/auth.js` is the swap seam.** Everything else calls `authenticate(request, env) → {user_id}|null`.
  Migrating to Cloudflare Access later (e.g. if the PWA moves onto Cloudflare Pages / a custom domain,
  where the Access cookie becomes first-party) is a change to **that one function** — verify
  `Cf-Access-Jwt-Assertion` instead of the bearer token, return the same shape. No caller/schema change.
- **user = 1 today.** Login is a single passphrase (`POSITIONS_AUTH_PASSPHRASE`). Multi-user email-OTP
  is a later drop-in; `user_id` is threaded through every row/query from day one, so user > 1 is a
  policy change, not a migration. Tenant isolation is **app-layer only** (D1 has no row-level security).

## Configurable parameters

| Where | Name | Default | Controls |
|---|---|---|---|
| `wrangler.toml` `[vars]` | `ALLOWED_ORIGINS` | github.io + localhost | comma-separated exact origins allowed by CORS |
| `src/auth.js` | `TOKEN_TTL_SECONDS` | `2592000` (30 d) | bearer-token lifetime before re-login |
| secret | `POSITIONS_SESSION_SECRET` | — | HMAC key signing bearer tokens (rotating it invalidates all tokens) |
| secret | `POSITIONS_AUTH_PASSPHRASE` | — | the owner's login passphrase (user = 1) |
| secret | `POSITIONS_INGEST_TOKEN` | — | WS5 phase 2 machine token for the GH-Actions held feed (`/held-tickers`, `/ingest/quotes`); also a GitHub Actions secret. Least-privilege, distinct from the owner passphrase. |

## One-time setup (already done in prod; documented for reproducibility)

```bash
wrangler d1 create finviz-positions                       # → database_id in wrangler.toml
wrangler d1 execute finviz-positions --remote --file migrations/0001_init.sql
wrangler secret put POSITIONS_SESSION_SECRET              # random 32+ bytes
wrangler secret put POSITIONS_AUTH_PASSPHRASE            # owner's passphrase
wrangler deploy
```

`wrangler deploy` does **not** touch secrets, the D1 schema, or the data — only the code.
Auto-deploy: `.github/workflows/deploy-workers.yml` (job `deploy-positions`) on push to default when
`worker-positions/**` changes; runs `npm test` before deploying.

## Tests

`npm test` (vitest): `test/auth.test.js` (token mint/verify/expiry/tamper, login),
`test/positions.test.js` (validation edge cases, row init invariants),
`test/index.test.js` (routing, CORS, 401 gating, create+list, independent lots, user isolation).
No network — a small in-memory D1 mock drives the router tests.
