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
4. ⬜ Push notifications (VAPID; reuse the sibling `distil` worker's web-push + `push_subscriptions`).

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
`ticker_quotes` bar with `trade_date > max(last_advanced_date, entry_date)` and fold `advance()`
over them in order. That one mechanism gives same-day idempotency, missed-day self-heal, and
backfill over bars captured before the engine had a caller.

Four things to internalize before editing the wiring:

- **Two rules live here, not in the design doc** (lead decisions, 2026-08-13, not yet owner-ratified).
  (1) A position is **never advanced on its own entry-day bar** — the bound is strictly `>`
  `entry_date`, because that day's `low` is largely pre-purchase and would fire a false `stop_hit`
  on the day of entry. (2) **Persistence is gated on `last_advanced_date` moving**, not on "were
  there events" — a stale bar emits a `note` without stamping the date, so it never leaves the query
  window; the weaker gate re-appends that note on every sweep, forever. Both are pinned by tests;
  don't "simplify" either away.
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

## Tests

`npm test` (vitest, no network). `test/advance.test.js` is the engine's spec-lock — every design-§9
rule has a fixture, plus randomized property tests for the invariants above. `test/sweep.test.js`
covers the wiring. Any engine or wiring change must land its test in the same commit.

`test/helpers/d1.js` shims the D1 surface over **Node 22's built-in `node:sqlite`** and applies the
**real migration files** — so the tests run actual SQL and break on schema drift. Two gotchas:
`node:sqlite` must be reached via `createRequire`, because the pinned vite doesn't know the builtin
and tries to resolve it as a package named `sqlite`; and the worker-positions CI jobs pin
`node-version: '22'` for this reason while `worker`/`worker-cron` stay on 20.
