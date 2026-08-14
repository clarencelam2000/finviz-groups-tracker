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
3. 🟡 **`advance()` daily engine + tests** — in progress.
   - ✅ **3a — the pure engine `src/advance.js`**: `advance(pos, bar, cfg)` plus the user-driven
     transitions (`confirmExit`/`stillHolding`/`autoConfirm`/`correctExit`/`reopen`), the §6 config
     constants with per-position `effectiveConfig` merge, and the `normalizeBar` bar-loader
     (recovers SMA **levels** from Finviz's %-distance columns — see migration 0002). Pure: no D1,
     no network, no clock.
   - ✅ **3b-i — the wiring `src/sweep.js`**: loads each advanceable position + its trailing
     `ticker_quotes` bars, folds `advance()` over them, and persists the new spine state + appended
     `position_events` under a DB-layer compare-and-set on `last_advanced_date`. Exposed as
     `POST /advance`; triggered by `scripts/collect_held.py` immediately after a successful
     `/ingest/quotes`.
   - ⬜ **3b-ii — the owner transition routes** (`confirm-exit`, `still-holding`, `correct-exit`,
     `reopen`) + `autoConfirm()` wired into the sweep. Deliberately ordered AFTER 3b-i: shipping
     `autoConfirm` first would mean every exit signal auto-closes at `EXIT_AUTOCONFIRM_SESSIONS`
     with no endpoint for the owner to confirm or reject it.
4. ⬜ Push notifications (VAPID; the sibling `distil` worker's web-push code is the reference).

Until 3b-ii lands, an exit signal parks the position in `closing` and stays there — nothing
auto-closes, and the position keeps accruing bars (`closing` is in `HELD_STATES`), so no history is
lost while the confirmation surface is being built.

### How the sweep runs (3b-i)

`sweep()` is a **catch-up fold**, not a single-day advance: for each position it loads every bar with
`trade_date > max(last_advanced_date, entry_date)` and folds `advance()` over them in order. One
mechanism therefore covers same-day idempotency, a missed feed day, and a deliberate backfill over
bars captured before the engine had a caller.

Two rules the wiring layer adds on top of the pure engine, neither of which is in the design doc:

- **A position is never advanced on its own entry-day bar** (the window bound is strictly `>`
  `entry_date`). That day's `low` is largely *pre-purchase* — advancing on it risks firing a false
  `stop_hit` on the very day the user bought. Lead decision, 2026-08-13.
- **Persistence is gated on `last_advanced_date` actually moving**, not on "were there events".
  A stale bar emits a `note` but deliberately does not stamp the date, so it stays inside the query
  window forever; persisting on events alone would re-append that note every sweep, compounding
  across a run of stale sessions. Staleness is reported through the sweep's `stale` counter (which
  `/advance` returns and the held-feed job logs) — the append-only ledger is the wrong channel for a
  condition that repeats daily.

**No new cron trigger and no new secret.** The sweep fires from `collect_held.py` right after the
day's bars land, reusing `POSITIONS_WORKER_URL` / `POSITIONS_INGEST_TOKEN`. That is dependency-gated
by construction (the engine runs exactly when fresh bars exist) and keeps us clear of the Cloudflare
5-cron-trigger account limit that already cost us a week of picks data (issue #252).

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/health` | none | liveness |
| `POST` | `/auth/login` | passphrase in body | exchange the login passphrase for a bearer token |
| `POST` | `/positions` | Bearer | create a position (one **lot**) + its `entered` event — the ticker-generic "I took it" write path (§ 8a) |
| `GET` | `/positions?state=` | Bearer | list the caller's positions, newest first (optional state filter) |
| `GET` | `/held-tickers` | Service token | WS5 phase 2: the union of open/managing/closing tickers the held feed must scrape (`{ tickers: [...] }`) |
| `POST` | `/ingest/quotes` | Service token | WS5 phase 2: append-only batch write of a day's scraped bars into `ticker_quotes` (`{ trade_date, collected_at, quotes:[...] }` → `{ written }`) |
| `POST` | `/advance?dry_run=1` | Service token **or** Bearer | WS5 phase 3b: run the daily engine sweep over stored bars. Service caller gets **counts only**; the owner bearer additionally gets per-position `results`. |

**Two auth paths, one seam.** The interactive `Bearer` rows above are the owner's HMAC login token
(`authenticate()`); the machine rows use a **separate service token** (`authenticateService()`,
secret `POSITIONS_INGEST_TOKEN`) held only by the GitHub-Actions held-feed job. The service token can
read the held set, append market bars, and **trigger** the engine sweep — but it **cannot** read,
create, or mutate positions directly, and the owner token cannot satisfy the service routes.

On the phase-3b widening: letting a CI-held token kick off `/advance` is a real (if small) increase
in its blast radius, accepted on these grounds — the sweep's outcome is a pure function of bars
already in D1, so the caller cannot steer it; it cannot set arbitrary position state; and `results`
is stripped from a service caller's response, so it learns counts, never which positions moved. If
that trade stops looking right, the fix is a third `POSITIONS_ENGINE_TOKEN` + an `authenticateEngine`
beside the existing two in `src/auth.js` — one secret and one function, no schema or caller change. Both live behind
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

### Engine constants (`src/advance.js` `ENGINE_CONFIG`, design §6)

These are the phase-3 daily-engine tunables. Each is a per-position override candidate: `advance()`
reads an **effective config** = these globals merged with a position's `meta.config` overrides
(design §14), so a per-position rule is a data change, not a code change. To change a global default,
edit `ENGINE_CONFIG` (each has an in-code comment) — no other engine code references the raw values.

| Name | Default | Controls |
|---|---|---|
| `BREAKEVEN_R` | `1.0` | R-multiple at which `profit_floor` ratchets up to entry (breakeven). The floor is the only monotonic quantity; `current_stop` is not (the widen lowers it on purpose). |
| `WIDEN_TRAIL_BASIS` | `true` | Widen the trail 20MA→50MA once the 50MA rises above entry. Per-position opt-out via `meta.widen_enabled=false`. |
| `TRIM_START_ATR` | `7` | First whole ATR-extension-from-50MA level that triggers a scale-out trim. |
| `TRIM_PCT` | `0.10` | Fraction of **remaining** qty trimmed at each newly-crossed whole ATR level (asymptotic — never trims a lot to zero). Idempotent + catch-up-correct via the `highest_trim_atr` ledger. |
| `TWO_CLOSE_EXIT` | `2` | Consecutive closes below the 20MA that force a winner's soft exit (`caution_flag` counts them). |
| `HARD_EXIT_BASIS` | `50ma` | Close below this MA is an immediate hard exit — `close_below_50ma` (default) or `close_below_20ma` (per-position `20ma` override), reported distinct from `two_close_below_20ma`'s stateful two-consecutive-close rule so an immediate single-close exit is never mislabeled as two closes. `20ma` \| `50ma`. |
| `SEVERE_BREAKDOWN_ATR` | `3.0` | Single-day `prev_close→close` drop (in ATRs) counting as a one-day crash (`severe_breakdown`). `Infinity` disables it (rely on the 50MA hard-exit alone). |
| `EARNINGS_WARN_SESSIONS` | `10` | Days-to-earnings at/under which the guardrail **flags** (never auto-exits). Reuses the Focus `EARNINGS_CAUTION_DAYS`. |
| `EXIT_AUTOCONFIRM_SESSIONS` | `5` | Sessions a position may sit in `Closing` before `autoConfirm()` closes it at `expected_exit_price` with `confirmation_status='auto'`. |
| `CAUTION_REARM_ON_HOLD` | `true` | On "still holding", reset `caution_flag` so the two-close rule re-arms (needs two fresh closes) instead of re-signalling on the next single close. |

### Sweep constants (`src/sweep.js` `SWEEP_CONFIG`, WS5 phase 3b)

Wiring-layer tunables, distinct from the engine constants above: these govern how bars are *fed to*
`advance()`, not what it decides.

| Name | Default | Controls |
|---|---|---|
| `MAX_CATCHUP_BARS` | `30` | Most bars ONE position may advance through in a single `sweep()` call. The sweep is a catch-up fold, so a long feed outage could otherwise replay months of history in one Worker request. The cap bounds work per invocation; `last_advanced_date` lands where the cap stopped and the next sweep continues from there. Raise only for a deliberate one-off backfill, then lower it back. |
| `ADVANCEABLE_STATES` | `["open","managing"]` | Which positions the sweep loads. `closing` (awaiting the user's confirmed fill) and `closed` are excluded — `advance()` no-ops on both anyway, so including them would only mean loading bars to throw away. |

Exit reasons are a canonical enum (`EXIT_REASONS`): `stop_hit`, `gap_down_below_stop`,
`close_below_50ma`, `close_below_20ma`, `severe_breakdown`, `two_close_below_20ma`, `manual_close`.
Earnings is **not** an exit reason — it only flags.

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
`test/index.test.js` (routing, CORS, 401 gating, create+list, independent lots, user isolation),
`test/advance.test.js` (the engine's spec-lock — every design-§9 rule plus randomized property
tests), `test/sweep.test.js` (catch-up fold, entry-day exclusion, idempotency, CAS races, stale-bar
handling, dry run, `/advance` response shaping).

No network. `test/helpers/d1.js` shims the D1 surface over **Node 22's built-in `node:sqlite`**
(zero dependencies) and applies the **real migration files**, so the tests exercise actual SQL and
break immediately on schema drift — the previous hand-rolled regex mock could do neither. That is
why the worker-positions CI jobs pin `node-version: '22'` while `worker`/`worker-cron` stay on 20.
`npm test` runs on every PR via the `worker-positions-test` job in `.github/workflows/tests.yml`
(added in phase 3b — before that, these tests only ran post-merge in `deploy-workers.yml`).
