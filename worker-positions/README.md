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
   - ✅ **3b-ii — the owner transition routes + `autoConfirm`** (`src/transitions.js`): the four
     owner-bearer actions `confirm-exit` / `still-holding` / `correct-exit` / `reopen` over the pure
     functions already in `advance.js`, plus `autoConfirm()` wired into the sweep. Ordered AFTER 3b-i
     on purpose — shipping `autoConfirm` first would auto-close every exit at
     `EXIT_AUTOCONFIRM_SESSIONS` with no endpoint for the owner to confirm or reject it.
4. ⬜ Push notifications (VAPID; the sibling `distil` worker's web-push code is the reference).

The PWA surfaces that *call* these transition routes (the "needs your confirmation" strip, the
editable Confirm-fill / Still-holding actions, the two-tier exit push) are phase-4 work — the
routes exist and are tested; the PWA client is not wired to them yet.

### Owner transition routes + auto-confirm (3b-ii)

`src/transitions.js` is the mirror image of the sweep's engine write path. The sweep's
`persistAdvance()` UPDATE deliberately **never** writes `exit_price` / `closed_at` /
`confirmation_status` — those are user-owned, and they are written **only** here, by
`persistTransition()`. The two write paths keep disjoint column lists (`caution_flag` is the one
shared column, legitimately re-armed by `still-holding`/`reopen`, and only ever touched while the
position is in `closing`/`closed` — a state the sweep does not advance), so neither can clobber the
other's fields.

- **State preconditions.** `confirm-exit` / `still-holding` require `closing`; `correct-exit` /
  `reopen` require `closed`. Any other current state is a `409`, not a silent no-op.
- **Idempotency = CAS on `state`.** `persistTransition()` guards every statement on the pre-state
  (`WHERE … state = ?`), events-first then the UPDATE, in one `db.batch` — so a double-submitted
  "confirm exit" applies once and the retry no-ops (its guard no longer matches). A retry that
  arrives *after* the row settled is caught earlier still, by the precondition check → `409`.
- **`autoConfirm` in the sweep.** After the advance loop, the sweep loads every `closing` position
  and closes any that has sat past `EXIT_AUTOCONFIRM_SESSIONS` sessions, at the price **frozen at
  signal time** (`expected_exit_price`, never re-derived), labeled `confirmation_status = 'auto'`.
  The session clock is the **global** trading-session calendar — `SELECT DISTINCT trade_date FROM
  ticker_quotes` (the union across all held tickers, so a feed gap for one symbol can't understate
  how long its position has been parked) — counted strictly after `exit_signal_date`. Reported via
  the sweep's new `auto_confirmed` count (and per-position `results` rows tagged
  `action: "auto_confirm"`, stripped for a service caller like every other result). `dry_run`
  computes it and writes nothing.

### How the sweep runs (3b-i)

`sweep()` is a **catch-up fold**, not a single-day advance: for each position it loads every bar with
`trade_date > max(last_advanced_date, entry_date, openedAtEtDate)` and folds `advance()` over them in
order. One mechanism therefore covers same-day idempotency, a missed feed day, and a deliberate
backfill over bars captured before the engine had a caller.

Three rules the wiring layer adds on top of the pure engine, none of which is in the design doc:

- **A position is never advanced on its own entry-day bar** (the window bound is strictly `>`
  `entry_date`). That day's `low` is largely *pre-purchase* — advancing on it risks firing a false
  `stop_hit` on the very day the user bought. Lead decision, 2026-08-13.
- **A position is never advanced on bars that predate its real creation** (the window bound is also
  strictly `>` `opened_at`'s ET trading date). `ticker_quotes` is a global, un-scoped-by-position
  feed, so a §8a backdated `entry_date` can land on a ticker that already has bars sitting in the
  table from before this position existed (e.g. a prior or concurrent position on the same ticker).
  Without this floor the first sweep after a backdated create would fold `advance()` over that
  pre-existing history in one shot — a genuine retroactive replay, contradicting the "a backdate is
  a label, not a replay" design promise. For a non-backdated position `entry_date == opened_at`'s ET
  date already, so this floor is a no-op there. Lead decision, 2026-08-15.
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
| `GET` | `/positions?state=&closed_within_sessions=` | Bearer | list the caller's positions, newest first. `state` is optional and accepts one or more values — repeated (`?state=open&state=managing`) and/or comma-separated (`?state=open,managing,closing`) are both accepted and merged; omitted/empty = all states. An unrecognized state value 400s rather than silently returning zero rows. WS5-7: each row is also augmented (null-safe, additive) with the latest `ticker_quotes` bar (`last_close/last_bar_date/last_open/last_high/last_low/last_change_pct/last_volume/last_raw`), a bounded newest-first `events` array (cap 8), and a computed `stop_ack_value` (the latest `stop_ack` event's value, or `null`) — all from ONE extra grouped query, no N+1. Each row also gets three session-calendar fields (this PR, reusing `sweep.js`'s `distinctTradeDates`/`sessionsSince` — the SAME clock `autoConfirm` uses, so the client and engine never disagree): `auto_confirm_sessions` (== `effectiveConfig(pos).EXIT_AUTOCONFIRM_SESSIONS` — the global default, or the position's own `meta.config` override when set, same as `autoConfirm` reads), `sessions_in_closing` (sessions since `exit_signal_date`, only for `state === 'closing'`, else `null`), and `sessions_since_close` (sessions since `closed_at`'s ET date, only for `state === 'closed'`, else `null`; strictly-after, so a just-closed position reads `0`). Optional `?closed_within_sessions=N` (positive integer; non-integer/`≤0` 400s, same style as an unknown `state`) drops any returned `closed` row whose `sessions_since_close > N` — bounds the WS5-6 closed-history payload without re-transferring the caller's entire closed history on every load. Omitted = no filter (unchanged behavior). |
| `GET` | `/held-tickers` | Service token | WS5 phase 2: the union of open/managing/closing tickers the held feed must scrape (`{ tickers: [...] }`) |
| `POST` | `/ingest/quotes` | Service token | WS5 phase 2: append-only batch write of a day's scraped bars into `ticker_quotes` (`{ trade_date, collected_at, quotes:[...] }` → `{ written }`) |
| `POST` | `/advance?dry_run=1` | Service token **or** Bearer | WS5 phase 3b: run the daily engine sweep over stored bars. Service caller gets **counts only**; the owner bearer additionally gets per-position `results`. |
| `POST` | `/positions/<trade_id>/confirm-exit` | Bearer | WS5 phase 3b-ii: `closing → closed` at the confirmed fill. Body `{ exit_price? }` — omitted/absent defaults to the modeled `expected_exit_price`; a supplied fill must be `> 0`. |
| `POST` | `/positions/<trade_id>/still-holding` | Bearer | WS5 phase 3b-ii: reject an exit signal, `closing → managing`; clears the exit fields and re-arms the two-close rule. |
| `POST` | `/positions/<trade_id>/correct-exit` | Bearer | WS5 phase 3b-ii: append-only correction of a `closed` position's fill. Body `{ exit_price }` (required, `> 0`); emits `exit_corrected`, recomputes R. |
| `POST` | `/positions/<trade_id>/reopen` | Bearer | WS5 phase 3b-ii: `closed → managing` for a wrongly-closed trade; clears the exit fields so the sweep resumes from the next bar. |
| `POST` | `/positions/<trade_id>/ack-stop` | Bearer | WS5-7: owner acknowledges "I raised my broker's resting stop." Appends a single `stop_ack` event to `position_events` with `payload.value` = the position's current `current_stop`; idempotent (a repeat tap at an unchanged stop does not duplicate the event). Writes **no** `positions` column — disjoint from both the engine (`persistAdvance`) and transition (`persistTransition`) write paths by construction. 404 on an unknown/other-user `trade_id`; 409 if the position has no `current_stop` to acknowledge. |
| `POST` | `/watchlist` | Bearer | WS5 §8b P1: add `{ticker, level_type?, level_value?}` — UPSERT on `(user_id, ticker)`, so re-adding an existing ticker renews the TTL and updates the level. |
| `GET` | `/watchlist` | Bearer | WS5 §8b P1: list the caller's watch entries (active + expired), each joined to its latest `ticker_quotes` bar → `prior_high/prior_low/atr/sma20/sma50` (null until the first EOD bar lands). Includes `level_value`. |
| `PATCH` | `/watchlist/<id>` | Bearer | WS5 §8b P1: `{renew:true}` resets the TTL/status, or an edit-level body `{level_type?, level_value?}`. |
| `DELETE` | `/watchlist/<id>` | Bearer | WS5 §8b P1: remove a watch entry (also called on graduation, right after `POST /positions` succeeds). |
| `GET` | `/watchlist-tickers` | Service token | WS5 §8b P1: for `scripts/collect_morning.py` — active watch tickers + `level_type` + latest-bar refs. **Omits `level_value`** (privacy — see `src/watchlist.js::watchlistTickerRefs`). |
| `POST` | `/watchlist/tick` | Service token | WS5 §8b P1: idempotent-per-ET-date TTL decrement + expire + purge (`src/watchlist.js::tickWatchlist`); optional body `{date}` overrides the derived ET date. |
| `POST` | `/positions/preclose-advisory` | Service token | WS5-8: the 15:40 ET provisional-bar batch (SAME shape as `/ingest/quotes` — `{trade_date, collected_at, quotes:[...]}`, reuses `validateIngestBatch`). Runs the pure `advance()` **in memory only** against each `open`/`managing` position + its matching bar and upserts the classified result into `preclose_advisory`. Never writes `ticker_quotes` or `positions` (`src/preclose.js`). Returns counts only: `{trade_date, users, checked, flagged}`. |
| `GET` | `/positions/preclose` | Bearer | WS5-8: today's (ET) pre-close advisory read for the caller — `{ran_at, n_checked, n_flagged, items}`. Null-safe: returns the same shape with `ran_at:null` and empty `items` if no advisory has run yet today, never a 404. |

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

`POST /positions` body: `{ ticker, entry_price, initial_stop, qty, stop_basis?, meta?, days_to_earnings?, entry_date? }`.
`stop_basis` ∈ `prior_day_low | todays_low | 20ma | 50ma | manual` (default `manual`).
`entry_date` (optional, § 8a manual entry) is `YYYY-MM-DD`, must be ≤ today's ET date, and defaults
to today when omitted. It lets the owner log a trade taken on an earlier date; `opened_at` (the real
creation timestamp) is never backdated, and a backdate does not replay the engine — `advance()` still
only runs forward from the next fed bar.
Validation rejects `initial_stop >= entry_price` (long-only: R = entry − stop must be > 0).
Each call creates an **independent lot** — "I took it" twice on one ticker makes two rows on purpose
(§ 3a scale-ins); there is deliberately no `(user_id, ticker)` uniqueness assumption.

## Pre-close advisory (WS5-8)

A 15:40 ET GitHub-Actions job scrapes near-final bars for held tickers and POSTs them to `POST
/positions/preclose-advisory`. That route runs the **pure** `advance(pos, bar, cfg)` engine against
each `open`/`managing` position's CURRENT persisted state and the provisional bar — **in memory
only** — and stores the classified result in a new `preclose_advisory` table (migration 0004,
applied out-of-band like 0001-0003). It does **not** call `ingestQuotes()` or `persistAdvance()`, so
`ticker_quotes`/`positions`/`position_events` are byte-identical before and after — the 17:30 settled
sweep (`src/sweep.js`) stays the sole writer of those three. This is load-bearing: a 15:40 write to
`ticker_quotes` or `positions.last_advanced_date` would make the 17:30 sweep a no-op.

Each item is `{trade_id, ticker, category:"exit", severity, signal, price, ref_level}`. `severity`
is `"act"` (a real intraday signal — stop hit/gap/severe breakdown) or `"heads_up"` (a
close-referenced MA rule that may still firm up by the real close) — see `PRECLOSE_SEVERITY` in
`src/preclose.js`. `category` is always `"exit"` in v1 (WS5-8b will add `"reclaim"`). `GET
/positions/preclose` (owner Bearer) reads today's ET-date row, or a null-safe empty shape if no
15:40 run has landed yet.

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

### Watchlist constants (`src/watchlist.js`, WS5 §8b)

Private, user-scoped personal watchlist (issue #319) — an owner can add an arbitrary ticker to
track ahead of taking a position; no stop, no size, ever (that's what makes it a watch item and not
a trade ticket). These two constants govern its TTL lifecycle.

| Name | Default | Controls |
|---|---|---|
| `WATCHLIST_TTL_SESSIONS` | `10` | Trading mornings a watch entry survives before expiring; `sessions_remaining`'s starting/renew value, decremented once per ET trading date by `tickWatchlist()`. |
| `WATCHLIST_PURGE_DAYS` | `14` | Calendar days an `expired` entry lingers (collapsed bin) before `tickWatchlist()` purges it (keyed off `expired_at`, not trading sessions). |

### Engine constants (`src/advance.js` `ENGINE_CONFIG`, design §6)

These are the phase-3 daily-engine tunables. Each is a per-position override candidate: `advance()`
reads an **effective config** = these globals merged with a position's `meta.config` overrides
(design §14), so a per-position rule is a data change, not a code change. To change a global default,
edit `ENGINE_CONFIG` (each has an in-code comment) — no other engine code references the raw values.

| Name | Default | Controls |
|---|---|---|
| `BREAKEVEN_R` | `1.0` | R-multiple at which `profit_floor` ratchets up to entry (breakeven). The floor is the only monotonic quantity; `current_stop` is not (the widen lowers it on purpose). |
| `BREAKEVEN_TRIGGER` | `'high'` | Price basis the breakeven ratchet keys on: `'high'` ratchets the moment the intraday high tags `+BREAKEVEN_R`; `'close'` requires the daily close to confirm it (spike-and-fade unprotected). Owner-set `'high'` 2026-08-19, issue #335. Flip via a per-position `meta.config.BREAKEVEN_TRIGGER` override or by editing the global default. |
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
`test/positions.test.js` (validation edge cases, row init invariants, and `listPositions`'s
session-calendar fields + `closed_within_sessions` bound against the real-SQLite harness),
`test/index.test.js` (routing, CORS, 401 gating, create+list, independent lots, user isolation),
`test/advance.test.js` (the engine's spec-lock — every design-§9 rule plus randomized property
tests), `test/sweep.test.js` (catch-up fold, entry-day exclusion, idempotency, CAS races, stale-bar
handling, dry run, `/advance` response shaping, **auto-confirm of stuck `closing` positions +
`sessionsSince` session-counting**), `test/transitions.test.js` (the four owner transition routes:
state preconditions → 409, editable/validated fill, tenant scoping → 404, double-submit safety,
`persistTransition` CAS, and the HTTP surface incl. owner-only gating), `test/watchlist.test.js`
(WS5 §8b P1 — validation, UPSERT renew semantics, latest-bar join/level recovery, tenant scoping,
tick idempotency/expire/purge, and the `heldTickers()` watchlist union).

No network. `test/helpers/d1.js` shims the D1 surface over **Node 22's built-in `node:sqlite`**
(zero dependencies) and applies the **real migration files**, so the tests exercise actual SQL and
break immediately on schema drift — the previous hand-rolled regex mock could do neither. That is
why the worker-positions CI jobs pin `node-version: '22'` while `worker`/`worker-cron` stay on 20.
`npm test` runs on every PR via the `worker-positions-test` job in `.github/workflows/tests.yml`
(added in phase 3b — before that, these tests only ran post-merge in `deploy-workers.yml`).
