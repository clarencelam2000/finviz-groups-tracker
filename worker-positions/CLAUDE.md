# worker-positions — WS5 trade-lifecycle store (Claude orientation)

> Loads only when you touch `worker-positions/**`. Full detail: `worker-positions/README.md`,
> `planning/trade-lifecycle-engine.md`, `knowledge/decisions/ADR-012-trade-lifecycle-engine.md`.
> Owner-intent source of truth: `knowledge/cron-lifecycle-ideation-and-alignment.md` §6/§10-11.

## What this worker is

A private, D1-backed store for the swing-trade lifecycle: **positions** (spine + append-only
`position_events`) and the **held-tickers quote feed** (`ticker_quotes`). Auth has two paths behind
the single seam `src/auth.js`: the owner HMAC **bearer** (`authenticate`) for interactive routes, and
a least-privilege **service token** (`authenticateService`, `POSITIONS_INGEST_TOKEN`) for the
GitHub-Actions held feed. See README § Auth — the Cloudflare-Access-vs-bearer decision is settled.

## Phase status (ADR-012 §10)

1. ✅ D1 schema + ticker-generic "I took it" write path (`src/positions.js`, `/positions`). The
   create path takes an optional `entry_date` (§ 8a manual/backdated entry) — `opened_at` always
   stays the real creation time regardless.
2. ✅ Held-tickers feed → `ticker_quotes` (`src/quotes.js`, `/held-tickers`, `/ingest/quotes`;
   GH-Actions `scripts/collect_held.py` + `worker-cron` `held` job at 17:30 ET).
3. ✅ **`advance()` daily engine** — **3a (pure engine) = `src/advance.js`**; **3b-i (wiring) =
   `src/sweep.js` + `POST /advance`**; **3b-ii (owner transition routes + `autoConfirm`) =
   `src/transitions.js`**, all done (see below).
4. 🟡 **Push notifications (WS5-4b) — Tier-1 ticker-named exit push done (PR-1, issue #348).**
   `migrations/0005_push_subscriptions.sql` + `src/push.js` + `POST /push/subscribe` / `POST
   /push/unsubscribe` + a two-tier `sweep.js` dispatch (collect intents during the advance loop,
   dispatch once post-commit). The push now carries an RFC 8291 `aes128gcm`-encrypted payload
   naming the ticker + exit reason. Tier-2 decaying-cadence reminders and earnings-approach push are
   still deferred fast-follows. See § below.
5. 🟡 **Personal watchlist (WS5 §8b, issue #319) — P1 (this worker) done.** `migrations/0003_watchlist.sql`
   + `src/watchlist.js` + the `/watchlist*` routes + `heldTickers()` union. P2 (`pick_status.py`
   reclaim state + `collect_morning.py` union) and P3 (PWA) are separate, not-yet-started phases —
   see `planning/watchlist-build-brief-8b.md`.
6. ✅ **Pre-close advisory (WS5-8, PR-1a) — backend done.** `migrations/0004_preclose_advisory.sql` +
   `src/preclose.js` + `POST /positions/preclose-advisory` (service token) + `GET
   /positions/preclose` (Bearer). PWA read (PR-1b) is separate, not-yet-started.

## The engine: `src/advance.js` (phase 3a)

`advance(pos, bar, cfg) → { position, events, stale? }` is a **pure** function — no D1, no network,
no clock. That purity is load-bearing: it's what makes the design §9 test suite and the future
rule-variant replay (design §12) possible. **Do not add I/O or a global-config lookup inside it.**

Three things to internalize before editing the engine:

- **SMA columns are %-distance, not levels.** Finviz's `SMA20/50/200` are the percent distance of
  price from the MA (see migration 0002). `advance()` needs LEVELS and gets them already-recovered:
  `normalizeBar()` does `level = close / (1 + pct/100)` in exactly one place. The engine body never
  touches the %-distance. If you add an MA rule, take the level off `bar`, don't re-derive.
- **Exit-before-advance, first match returns.** Exit checks (stop-hit/gap, close-below-50MA,
  severe-breakdown, two-close-below-20MA) run first and `signalExit()` returns immediately → the
  bar that signals an exit never also emits a trim/stop-move (a test pins this). An exit moves the
  position to **`closing`** (modeled price as *expected* fill), **never straight to `closed`** — the
  user confirms the real fill (`confirmExit`) or reverts (`stillHolding`). This exit symmetry with
  entry is the owner decision that the honest R/expectancy record depends on.
- **`effectiveConfig(pos)` = globals + `pos.meta.config` overrides** (design §14). `advance()` reads
  tunables from the passed-in cfg, so a per-position rule ("exit this one below its 30MA") is a data
  change, not an engine rewrite. Every position's overrides are empty today, so effective == globals.

Invariants (property-tested): `profit_floor` is the **only** monotonic quantity (ratchets to entry at
+1R, never decreases); `current_stop >= profit_floor` **always** (the 20MA→50MA widen lowers the stop
on purpose, but never below the floor); `remaining_qty` is non-increasing and stays > 0 (trims take a
fraction of the *remainder*). Trims are idempotent + catch-up-correct via the `highest_trim_atr`
ledger; same-date re-runs are no-ops via the `last_advanced_date` guard.

Config constants (`ENGINE_CONFIG`) are triple-documented: in-code comments here, the README §
Configurable parameters › Engine constants table, and this file. To change a default, edit
`ENGINE_CONFIG` — nothing reads the raw values directly.

## The wiring: `src/sweep.js` (phase 3b-i)

`sweep()` is the engine's only caller. It is a **catch-up fold**: per position, load every
`ticker_quotes` bar with `trade_date > max(last_advanced_date, entry_date, openedAtEtDate)` and fold
`advance()` over them in order. That one mechanism gives same-day idempotency, missed-day self-heal,
and backfill over bars captured before the engine had a caller.

Four things to internalize before editing the wiring:

- **Three rules live here, not in the design doc** (lead decisions, 2026-08-13/15, not yet
  owner-ratified). (1) A position is **never advanced on its own entry-day bar** — the bound is
  strictly `>` `entry_date`, because that day's `low` is largely pre-purchase and would fire a false
  `stop_hit` on the day of entry. (2) A position is **never advanced on bars that predate its own
  creation** — the bound is also strictly `>` `opened_at`'s ET trading date, closing a gap the §8a
  backdated `entry_date` feature opened: `ticker_quotes` is global/un-scoped-by-position, so a
  backdate onto a ticker with pre-existing bars (from a prior or concurrent position) would otherwise
  make the very next sweep fold `advance()` over real history in one shot — a genuine replay, not
  just a label, breaking the §8a design promise. A no-op for non-backdated positions (`entry_date ==
  opened_at`'s ET date already). (3) **Persistence is gated on `last_advanced_date` moving**, not on
  "were there events" — a stale bar emits a `note` without stamping the date, so it never leaves the
  query window; the weaker gate re-appends that note on every sweep, forever. All three are pinned
  by tests; don't "simplify" any of them away.
- **`meta` is a JSON string in D1, an object to the engine.** `loadAdvanceablePositions()` parses it
  at the load boundary. Skip that and `effectiveConfig()` silently sees no overrides and
  `meta.widen_enabled=false` stops working — a bug with no exception to catch it.
- **Idempotency is enforced in SQL, not just by the caller.** `persistAdvance()` emits ONE
  `db.batch` (a single transaction): guarded `INSERT … SELECT … WHERE EXISTS` event rows **first**,
  then the compare-and-set `UPDATE`. The order is load-bearing — update-first would invalidate the
  guard and silently drop every event in the same batch. `IS`, not `=`, because the expected value
  is NULL on a position's first advance.
- **The UPDATE is deliberately narrow.** It never writes `meta`, `exit_price`, `closed_at`, or
  `confirmation_status` — those belong to the user-driven transitions. Widening that column list is
  how a sweep would come to clobber a field the user owns.

`POST /advance` is dual-auth on one route: the service token (the held-feed job) gets **counts
only**; the owner bearer additionally gets per-position `results`. Trigger is
`scripts/collect_held.py` immediately after a successful `/ingest/quotes` — dependency-gated, no new
cron trigger, no new secret.

## The owner transitions: `src/transitions.js` (phase 3b-ii)

The four owner-bearer routes `confirm-exit` / `still-holding` / `correct-exit` / `reopen` (at
`POST /positions/<trade_id>/<action>`, matched by an anchored regex in `index.js` so they never
shadow the exact `/positions` collection routes) over the already-pure functions in `advance.js`,
plus `autoConfirm()` folded into the sweep. Ordered after 3b-i on purpose: `autoConfirm` without a
confirm route would silently auto-close every exit at `EXIT_AUTOCONFIRM_SESSIONS`.

Three things to internalize before editing the transitions:

- **`persistTransition` is the MIRROR of `persistAdvance`.** It writes exactly the columns the
  sweep's UPDATE refuses to (`state`, the exit-signal fields, `exit_price`, `closed_at`,
  `confirmation_status`, `caution_flag`) and none of the engine columns. That disjointness is the
  whole safety story — neither write path clobbers the other's fields. Same load-bearing batch
  order (guarded event INSERTs first, CAS UPDATE last), but the CAS version column is **`state`**,
  not `last_advanced_date`: a transition is valid only from a known pre-state, so guarding on it
  makes a double-submit a no-op. `state` is NOT NULL, so it's `state = ?` (plain `=`), unlike
  persistAdvance's nullable `last_advanced_date IS ?`.
- **The pure fns return `trade_date` as a SIBLING of `events`, not stamped per-event** (unlike the
  fold in `advanceThroughBars`). `position_events.trade_date` is NOT NULL, so the wiring stamps
  each event with the transition's `trade_date` before persisting — in `applyTransition` and in the
  sweep's auto-confirm block. Miss that and the batch throws a NOT NULL constraint.
- **`autoConfirm`'s session clock is the GLOBAL calendar.** `sessionsSince(distinctTradeDates(db),
  exit_signal_date)` counts distinct `trade_date`s in `ticker_quotes` (union across all held
  tickers) strictly after the signal — global, not the position's own ticker, so a one-symbol feed
  gap can't understate how long a position has been parked. The price is the one frozen at signal
  (`expected_exit_price`), labeled `confirmation_status='auto'`. Global-vs-per-ticker is a lead
  interpretation of the design's "natural session calendar" — flagged for owner ratification
  (SPRINT WS5-3b-OWNER), non-blocking.

The PWA client that calls these routes (confirmation strip, editable Confirm-fill) is phase-4 work;
3b-ii ships the routes + tests only. Tracked: SPRINT WS5-3b-ii.

**`ack-stop` (WS5-7) is an event-only owner action, not a fifth transition.** `POST
/positions/<trade_id>/ack-stop` (`src/transitions.js::ackStop`) records that the owner raised their
broker's resting stop to match the position's current `current_stop`. It does **not** go through
`applyTransition`/`persistTransition` — it writes NO `positions` column at all, only appending a
`stop_ack` event to `position_events`. That makes it disjoint from both existing write paths by
construction (not just by convention like `TRANSITION_COLS` vs. the sweep's UPDATE list): there is no
column list to keep out of sync because there is no column write. `stop_ack` is a new
`position_events.event_type` — no migration needed, since `event_type` has no CHECK constraint (see
migration 0001). `GET /positions` (`src/positions.js::listPositions`) surfaces the latest ack as
`stop_ack_value`, computed from the full per-trade event history (not the capped inline `events`
display slice), so it stays correct even if the display cap hides the ack event itself.

- **`listPositions()` (`src/positions.js`) surfaces three session-calendar fields** (PR after
  WS5-7's `stop_ack_value`, backing the WS5-4a confirmation countdown and WS5-5 closed-history
  aging): `auto_confirm_sessions` (== `effectiveConfig(pos).EXIT_AUTOCONFIRM_SESSIONS` — the global
  default, layered with the position's own `meta.config` override when set, same as `autoConfirm`
  itself reads — every row),
  `sessions_in_closing` (`closing` only), `sessions_since_close` (`closed` only, anchored on
  `closed_at`'s ET date, not `exit_signal_date` — a position can sit in `closing` for several
  sessions before it settles). All three reuse `sweep.js`'s `distinctTradeDates`/`sessionsSince` —
  the same global session clock `autoConfirm` itself uses — loaded ONCE per `listPositions()` call,
  never re-implemented. `GET /positions?closed_within_sessions=N` filters returned `closed` rows on
  `sessions_since_close` (a positive-integer 4th `opts` arg on `listPositions`); no SQL-side row cap
  was added (see the in-code comment above `listPositions` for why a per-state SQL LIMIT doesn't fit
  the shared query shape cleanly) — the session filter is the actual payload bound.

## The watchlist: `src/watchlist.js` (WS5 §8b, P1)

A **private, user-scoped** membership+level+TTL store for tickers the owner is tracking ahead of
taking a position — an arbitrary ticker, not necessarily a pick. A watch item carries **no stop, no
size, ever**: that's the load-bearing distinction from a position (design brief § 1). It carries a
ticker and an OPTIONAL "carry your own" level of interest (`above`/`below` a price, or
`reclaim_20ma`/`reclaim_50ma`); the system read (breakout vs prior high) is computed separately by
`scripts/pick_status.py` and always runs regardless of whether a level is set — that engine lives in
Python (P2, not yet built) and is unioned into `scripts/collect_morning.py`'s scrape universe via
`GET /watchlist-tickers`, never re-implemented here.

- **Privacy posture is the mirror image of `ticker_quotes`.** Migration 0002's `ticker_quotes` is
  deliberately user-less (public market data); migration 0003's `watchlist` is deliberately
  user-scoped (private membership/level/TTL). Only an ANONYMOUS status row for the ticker — no
  level, no size — is meant to ride the public morning store (P2, `collect_morning.py`), built from
  `GET /watchlist-tickers`'s response, which **omits `level_value`** on purpose: the your-level read
  is computed client-side in the PWA off the owner's own `GET /watchlist` (which DOES include
  `level_value`), so the private price target never has to leave this worker's owner-bearer surface.
- **Two constants, both TTL/lifecycle, not scoring.** `WATCHLIST_TTL_SESSIONS = 10` (trading
  mornings a watch entry survives; `sessions_remaining`'s starting/renew value) and
  `WATCHLIST_PURGE_DAYS = 14` (calendar days an `expired` row lingers before purge). Both live in
  `src/watchlist.js` with in-code comments; see README § Configurable parameters › Watchlist
  constants for the public-facing table.
- **Tick idempotency is a dedicated table, not KV.** `watchlist_tick_log(tick_date TEXT PRIMARY
  KEY)` + `INSERT OR IGNORE` — this worker has no KV binding (unlike `worker-cron`'s dispatch-guard
  pattern), so the guard lives in D1 instead, co-located with the data it protects.
  `tickWatchlist(db, {date, now})` resolves `date` from `now` via `etDateStr()` when omitted, tries
  the guarded insert first, and returns `{ticked:false, decremented:0, expired:0, purged:0,
  skipped_no_history:0}` immediately if that date was already ticked — a same-day retry (a double
  GitHub Actions dispatch, the `collect.yml`/`collect_picks.yml`-style GitHub cron backstop) is a
  true no-op, never a double decrement. **`tickWatchlist()` also skips the decrement for active rows
  whose ticker has no `ticker_quotes` bar yet** (`WS-POSITIONS-TTL-BURN`) — a brand-new watch ticker
  in the "awaiting_first_read" state (no bar, so no real classification could have happened) is left
  at full TTL rather than burning a morning over a weekend/holiday gap before its first EOD read; the
  count of such skipped rows is returned as `skipped_no_history`.
- **UPSERT-on-add is the intended renew UX**, not a bug to guard against: `addWatch()` upserts on
  `(user_id, ticker)` — re-adding an already-watched ticker resets `sessions_remaining` to
  `WATCHLIST_TTL_SESSIONS`, clears `expired_at`/`status`, and updates the level, while `created_at`
  survives untouched (not referenced in the `ON CONFLICT … DO UPDATE`). This is the opposite
  uniqueness stance from `positions.js::insertPosition`, which deliberately allows duplicate
  `(user_id, ticker)` rows (independent lots, § 3a) — a watch item has no lot/qty concept to make a
  second row meaningful.
- **`normalizeBar()` reuse, not re-derivation.** `listWatch()` and `watchlistTickerRefs()` both join
  each ticker to its latest `ticker_quotes` bar and run it through `src/advance.js`'s
  `normalizeBar()` to recover `prior_high`/`prior_low`/`atr`/`sma20`/`sma50` from Finviz's
  %-distance SMA columns — the exact math `advance()` itself depends on (module header there). A
  freshly-added ticker with no bar yet gets all-null refs — the "adding, first check tomorrow AM"
  state the build brief describes; expected, not an error.
- **Auth split mirrors `/held-tickers` + `/ingest/quotes` exactly.** `GET /watchlist-tickers` and
  `POST /watchlist/tick` sit ABOVE the owner-auth gate in `src/index.js`, guarded by
  `authenticateService()`; `POST/GET /watchlist` and `PATCH/DELETE /watchlist/:id` sit BELOW it,
  guarded by `authenticate()`. Same reasoning as the held feed (`src/auth.js`'s comment): the
  service token can read/tick the watchlist's market-data-adjacent surface but can never see or
  touch a specific owner's private rows, and the owner bearer can't satisfy the service check.
- **`heldTickers()` (`src/quotes.js`) now unions in the active watchlist.** The held-tickers feed
  job scrapes `positions(open/managing/closing) ∪ watchlist(active)` — a watch item rides the SAME
  EOD 17:30 ET held-feed run as open positions so it accumulates the prior-day High/Low/ATR/MAs a
  brand-new watch has no history for. `watchlistTickers(db)` (user-less, same rationale as
  `heldTickers` itself) is the seam; do not inline a second `SELECT DISTINCT ticker FROM watchlist`
  elsewhere — always route through it so the "active" definition never drifts.
- **Migration 0003 is applied out-of-band**, exactly like 0001/0002 — `wrangler deploy` does not run
  it. `test/helpers/d1.js`'s `MIGRATIONS` array runs it for real in tests (real SQLite, real schema),
  plus `_seedWatchlist()`/`_watchlist()` test-only conveniences mirroring `_seedQuote()`/`_quotes()`.

## The pre-close advisory: `src/preclose.js` (WS5-8)

A 15:40 ET GitHub-Actions job scrapes near-final bars and calls `POST /positions/preclose-advisory`
(service token). `computePreCloseAdvisory(db, {quotes, trade_date, now})` runs the SAME pure
`advance(pos, bar, cfg)` the 17:30 sweep uses, but calls it **in memory only** — the returned
`position` is discarded, never persisted — against each `open`/`managing` position's currently
persisted state. It writes to exactly ONE new table, `preclose_advisory` (one row per `(user_id,
trade_date)`, upserted so a self-healing re-dispatch is last-write-wins).

**The disjointness invariant is the whole point.** This module NEVER calls `ingestQuotes()` or
`persistAdvance()` and never stamps `positions.last_advanced_date` — a write to `ticker_quotes` or
that column at 15:40 would make the 17:30 settled sweep's `loadBarsAfter()` window already-consumed,
i.e. the real sweep becomes a no-op for that day. `test/preclose.test.js`'s disjointness test asserts
`positions`/`ticker_quotes` are byte-identical before and after a compute — that is the test that
would catch this exact bug, treat it as load-bearing if you touch this file.

**It mirrors the sweep's entry-day window guard** (lead review, PR-1a). It only *flags* a position
whose `barWindowStart(pos) < trade_date` — the same exclusive floor `sweep()` uses — so a position
entered today (or backdated, or already advanced today) is counted toward the receipt's book size but
never evaluated. Without this a 15:40 bar's largely-pre-purchase entry-day `low` would fire a FALSE
`stop_hit` in the advisory that the 17:30 sweep then never confirms (the sweep excludes the entry-day
bar), so the advisory would contradict the settled engine. `test/preclose.test.js` #9 pins it.

An exit surfaces as advance.js's single `exit_signal` event (`event_type: "exit_signal"`, the reason
in `payload.reason` — NOT a reason-named `event_type`); `PRECLOSE_SEVERITY` maps that reason to
`"act"` (stop_hit/gap_down_below_stop/severe_breakdown — real intraday) or `"heads_up"`
(close_below_50ma/two_close_below_20ma — close-referenced, may still firm by the real close).
`readPreCloseAdvisory(db, user_id, trade_date)` is `GET /positions/preclose`'s (Bearer) read path —
null-safe empty shape when nothing has run yet today, never a 404.

**Spec deviation, worth knowing if you touch the ingest route:** `validateIngestBatch()`'s output
puts `trade_date` at the BATCH level, not per-row — each validated `rows[i]` has no `trade_date`
field (`ingestQuotes()` only stamps it on at INSERT time). `computePreCloseAdvisory` stamps the
batch's `trade_date` onto each row before calling `normalizeBar()` (which requires `row.trade_date`
to stay a pure function of the row — see advance.js's own comment on that). Don't be surprised the
`quotes` param here isn't literally `ticker_quotes`-row-shaped on its own.

## The push dispatch: `src/push.js` (WS5-4b)

Ported VERBATIM from the sibling `distil` worker's proven `src/cron/webpush.ts` (VAPID JWT signer +
`sendPush`) and adapted from its `src/store/push.ts` (subscription store). **v1 is Tier-1
exit-signal push, now with an RFC 8291 `aes128gcm` payload (PR-1, issue #348)** — RFC 8292 VAPID
auth plus ephemeral ECDH + HKDF-SHA256 + AES-128-GCM single-record encryption
(`encryptAes128Gcm()`), producing a ticker-named notification instead of a generic one. A future
Tier-2/decaying-cadence and earnings-approach push is still a separate PR — the payload-encryption
constraint that used to block it here is lifted (this file now does encryption), but the Tier-2
cadence/scheduling logic itself is out of scope for this file and hasn't been added.

Four things to internalize before editing this file:

- **`sendPush(sub, vapid, payload = null)` takes the full subscription object, not just the
  endpoint** — encryption needs `sub.p256dh`/`sub.auth`. `payload === null` is EXACTLY the old
  data-less request (`Content-Length: 0`, no `Content-Encoding`); a string payload is encrypted via
  `encryptAes128Gcm()` against `sub`'s keys and sent as `Content-Encoding: aes128gcm`,
  `Content-Type: application/octet-stream`. `dispatchExitPushes()`'s inner loop calls
  `sendPushFn(sub, vapid, payload)` — if you add a new call site, pass the subscription object, not
  `sub.endpoint`.
- **The HKDF `info` byte layouts are exact-bytes-or-it-silently-fails.** `"WebPush: info\0" ||
  ua_public(65B) || as_public(65B)` for `PRK_key`; `"Content-Encoding: aes128gcm\0"` for the CEK;
  `"Content-Encoding: nonce\0"` for the nonce — each a distinct HKDF-Expand call keyed off the SAME
  `PRK_key`/per-message salt. Get a byte wrong here and encryption doesn't throw, it just produces
  garbage the push service (or a client) can't decrypt — there's no compile-time or runtime check
  that would catch a subtly-wrong `info` string. `test/push.test.js`'s self-round-trip decrypt test
  is what actually verifies this; treat it as load-bearing if you touch `encryptAes128Gcm()`.

- **`dispatchExitPushes()` is the seam `sweep.js` calls, and it NEVER throws.** Every failure mode
  — no `vapid` config, zero subscriptions for a user, a `sendPushFn` throw, a non-ok/non-gone
  response — is caught and counted (`sent`/`pruned`/`skipped`), never rethrown. `sweep.js`'s call
  site wraps the call in its own try/catch on top of that, so a push failure is structurally unable
  to fail the sweep, block a D1 write, or surface as an error to `/advance`'s caller.
- **The `push_sent` idempotency marker is written ONLY after a real successful send** — never
  pre-emptively, never on a failure. That's what makes a transient send failure self-healing (the
  next sweep retries) while a genuine duplicate dispatch for the same `(trade_id, trade_date)` is
  a true no-op. It's disjoint from both `persistAdvance` and `persistTransition` by construction:
  it's a plain `INSERT` into `position_events` with no matching `positions` column write at all —
  same shape as `stop_ack` (WS5-7), and like `stop_ack`, no migration is needed since `event_type`
  has no CHECK constraint.
- **Dispatch runs strictly AFTER both `sweep()` loops finish, not inside `persistAdvance`'s batch.**
  `sweep.js` collects `exitIntents` during the advance loop (gated on `applied === true &&
  !dry_run`, so a lost CAS race or a dry run never queues a push) and calls
  `dispatchExitPushes(db, {...})` once, after the auto-confirm pass, right before building the
  return value. This is the "outside the transaction, post-commit, best-effort" rule — push must
  never be able to observe (or worse, block on) a still-open D1 batch.
- **`readVapidConfig(env)` is the single missing-secret guard.** It returns `null` unless all three
  of `VAPID_PUBLIC_KEY`/`VAPID_PRIVATE_KEY`/`VAPID_SUBJECT` are set; every caller (`index.js`'s
  `/advance` route) passes its result through unconditionally, and `sweep()`/`dispatchExitPushes()`
  no-op cleanly on `null` — there is no second "is push configured" branch to keep in sync.

## Tests

`npm test` (vitest, no network). `test/advance.test.js` is the engine's spec-lock — every design-§9
rule has a fixture, plus randomized property tests for the invariants above. `test/sweep.test.js`
covers the wiring. Any engine or wiring change must land its test in the same commit.

`test/helpers/d1.js` shims the D1 surface over **Node 22's built-in `node:sqlite`** and applies the
**real migration files** — so the tests run actual SQL and break on schema drift. Two gotchas:
`node:sqlite` must be reached via `createRequire`, because the pinned vite doesn't know the builtin
and tries to resolve it as a package named `sqlite`; and the worker-positions CI jobs pin
`node-version: '22'` for this reason while `worker`/`worker-cron` stay on 20.
