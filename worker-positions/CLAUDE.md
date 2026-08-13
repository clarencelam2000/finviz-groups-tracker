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

1. ✅ D1 schema + ticker-generic "I took it" write path (`src/positions.js`, `/positions`).
2. ✅ Held-tickers feed → `ticker_quotes` (`src/quotes.js`, `/held-tickers`, `/ingest/quotes`;
   GH-Actions `scripts/collect_held.py` + `worker-cron` `held` job at 17:30 ET).
3. 🟡 **`advance()` daily engine** — **3a (the pure engine) is `src/advance.js`**; **3b (wiring) is
   next** (see below).
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

## Phase 3b (next PR) — the wiring, deliberately NOT in 3a

The pure engine has no caller yet. 3b adds: load a position + its trailing `ticker_quotes` bars,
call `advance()`, persist the new spine state + append the emitted events, enforce `last_advanced_date`
idempotency at the DB layer, a service-token `/advance` route (or an ingest-triggered sweep), and the
daily trigger after the held ingest lands. It's gated on a few accumulated bars for a live dry-run
anyway, so shipping the exhaustively-tested pure heart first is the de-risking move. Tracked: SPRINT
WS5-3b.

## Tests

`npm test` (vitest, no network). `test/advance.test.js` is the engine's spec-lock — every design-§9
rule has a fixture, plus randomized property tests for the invariants above. Any engine change must
land its test in the same commit.
