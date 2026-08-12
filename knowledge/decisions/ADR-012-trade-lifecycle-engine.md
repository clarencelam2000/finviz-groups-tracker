# ADR-012: Trade lifecycle engine — architecture, storage, and the domain invariant

**Date**: 2026-08-06 (reconciled 2026-08-10 with owner decisions of 2026-08-07/08-10)
**Status**: Proposed (architecture accepted in principle; per-phase implementation pending owner go-word)

> **2026-08-10 reconciliation.** Folded the owner decisions from `knowledge/cron-lifecycle-ideation-and-alignment.md`
> § 10 and the 2026-08-10 owner Q&A into this ADR and `planning/trade-lifecycle-engine.md`: the
> **`closing` state** (exit awaits the user's confirmed fill, symmetric with entry — Decision 6 below);
> the **held-tickers feed is append-only** and doubles as a **backtest substrate** (Decision 1);
> the write path is **ticker-generic** so arbitrary user-entered tickers are a future UI addition,
> not a migration (Decision 7); `SEVERE_BREAKDOWN_ATR = 3.0`, widen = auto-with-per-position-toggle,
> breakeven = +1R (design doc § 6/§ 11).

> Companion implementation design: `planning/trade-lifecycle-engine.md`. Owner-intent source of
> truth: `knowledge/cron-lifecycle-ideation-and-alignment.md` § 6 (the ruleset) and § 7 (storage).
> This ADR records the *architectural* decisions; the design doc records the *how*.

## Context

WS4 gives the owner an entry ticket. Nothing manages the trade **after** entry — which is the
owner's stated personal gap: *"addresses one of my gaps in my own trading."* The product goal is
"the app holds the user's state so they don't have to": a daily engine that advances stops,
applies scale-out trims, and fires exit/earnings alerts per the owner's real ruleset, for a
**swing** trader (multi-day holds, daily bars, no profit targets).

Three architectural questions must be settled before any code: (1) where mutable position state
lives, (2) how the domain's core invariant is modeled, (3) how a held position gets daily data.

## Decision

### 1. Storage: Cloudflare D1, not append-only CSV

Positions **mutate daily** (state, stop, remaining quantity all change in place) — a poor fit for
the repo's append-only-observation CSV convention, which models *observations*, not *evolving
records*. Separately, **live positions are personal financial data** and must not be committed to
a public repo the way `data/*.csv` is. Use **Cloudflare D1**: the sibling project already runs D1
+ VAPID web-push on the same account (owner-confirmed), so it is proven, already paid for, and
brings push support for free.

**Shape: typed relational spine + JSON `meta` bag + append-only event log** (the owner asked
directly about SQL-vs-NoSQL / "spine and a flexible bag"):
- `positions` — typed, queryable, constraint-enforced columns for everything the engine computes
  on, plus a `meta` JSON column (SQLite JSON functions) for notes/tags/UI-state/fields not worth a
  migration.
- `position_events` — append-only ledger (`entered | stop_moved | partial_exit | caution |
  exit_signal | closed | note`) giving audit trail, replay, and new event types with no schema change.
- `ticker_quotes` — **append-only** daily-bar feed for held tickers, keyed `(ticker, trade_date)`,
  **no `user_id`** (a daily bar is public market data; only the *selection* of which symbols to fetch
  derives from private positions, at query time). Append-only, **not** latest-bar-only (owner Q,
  2026-08-10): it doubles as a **backtest substrate** — with `position_events` (what happened) and
  closed `positions` (outcomes), D1 then supports both trade-outcome expectancy and hypothetical
  rule-variant replay of the pure `advance()` function. It also preserves daily-bar history for
  *off-picks* held names, the one market-data set the committed `data/*.csv` files don't already
  carry. Tiny (open positions × trading days). See `planning/trade-lifecycle-engine.md` § 5/§ 12.

Rejected: one wide mutable table with no history (loses the audit/replay and makes the scale-out
trim ledger fragile), and JSON-document-only (loses typed constraints on the fields the engine
queries every day). Also rejected: a **latest-bar-only** quote feed (would forfeit the backtest
substrate for zero storage saving) and a **committed-CSV** quote feed (its only consumer is the
D1-resident Worker engine, for which reading a Git CSV is the awkward path, and the CSV split would
force a cross-store join on every advance).

**Accepted consequence of a D1 (not CSV) feed:** the scraper runs in GitHub Actions (Cloudflare
blocks headless Chromium on our cloud IPs), so writing to D1 needs an **authenticated ingest path**
(a Worker endpoint or the D1 HTTP API + a GH secret) rather than a `git commit`. This cost is paid
**once** and is needed regardless — the "I took it" write path (phase 1) and the push-subscription
store (phase 4) require the same authenticated Worker→D1 surface.

### 2. The domain invariant: a ratcheting **profit floor**, not a monotonic stop

This is the single most important correctness decision and the one the owner personally corrected
(alignment record § 5.3). The naive "stops only ratchet up" model is **wrong** and would forbid
the owner's real strategy of widening the trail from the 20MA to the 50MA.

**The invariant:** *once past breakeven, the trade never goes red again.* A monotonic
non-decreasing `profit_floor` enforces this. The **active stop may widen** (20MA → 50MA, i.e.
move to a numerically lower level) as long as it stays **at or above** the floor — which is safe
precisely because the 50MA is only adopted once it has risen above entry, so even the looser stop
still locks in green. `profit_floor` is monotonic; `current_stop` is deliberately **not**. The
design doc formalizes and unit-tests this.

### 3. Held positions need their own daily data feed

A position must be advanced daily even after its ticker **falls off the picks list** — so WS5
requires a **held-tickers feed**: a small daily job scraping quotes only for open-position
tickers, independent of the picks screener. This is another gated job on ADR-010's single tick —
a concrete payoff of the cron consolidation (no trigger budget needed). Shares its mechanism with
WS3's morning-confirmation quote feed (see ADR-011 § Coupling); the two must not be built twice.

### 4. Multi-tenancy from day one, even at user = 1

The owner raised row-level-security and one-way-door concerns. Decisions:
- **`user_id` on every row; every query scoped to it** from the first migration — cheap now,
  brutal to retrofit. This is the one-way door we walk through the safe side of.
- **D1/SQLite has no row-level security** (that is a Postgres/Supabase feature) — tenant isolation
  is **app-layer**: the Worker derives `user_id` from the authenticated token and **never trusts a
  client-supplied `user_id`**. At user = 1, auth may be a single shared token; the `user_id`
  column exists purely to leave the door open for user > 1 without a migration.

### 5. Delivery: VAPID web-push

Stop-hit and earnings-approach alerts delivered via VAPID web-push (same CF account already does
this). Constraint recorded: **iOS PWA push requires the app installed to the home screen
(iOS 16.4+)** — the UX must nudge install or some users silently get nothing.

### 6. Exits are user-confirmed, not auto-closed: the `closing` state

Symmetric with entry. Entry freezes the user's *actual* fill (not the computed trigger); an exit
must likewise be the user's *actual* fill (not the modeled stop/close). The engine runs **after** the
close, so a detected exit is a **signal**, and the real-world execution is next session's open at
earliest. An exit check therefore moves the position to **`Closing`** — modeled price recorded as
*expected*, an `exit_signal` event emitted, a push sent — and the user confirms the real fill
(→ `Closed`, writing `exit_price`) or taps "still holding" (→ back to `Managing`, a discretionary
override). This resolves both staff findings on #264 (asymmetric fill-truth; signal-close vs
execution-close) and is required for the honest R-multiple / expectancy record. `advance()` never
writes `exit_price`; only the user's confirmation does. (Owner decision, alignment § 10.)

### 7. The position is the root entity; the write path is ticker-generic

The phase-1 "I took it" write path accepts `{ticker, entry_price, initial_stop, stop_basis, qty}` —
the WS4 picks ticket is one caller; a future manual-entry form (open a position on **any** typed
ticker) is a second caller filling the same payload. Because the held-tickers feed is driven by the
`positions` table (Decision 3), not the picks list, an arbitrary ticker is fetched and advanced with
no new architecture. Provenance is `meta.source = 'picks' | 'manual'`. **Do not** key the create
path on a picks-row identity — that would turn arbitrary tickers into a migration instead of deferred
UI work. (Owner "think big", 2026-08-10; needs no storage change — see design doc § 8a.)

## Consequences

- A new backend (D1) enters the project alongside the CSV data tier; the two are deliberately
  separate (settled market observations in CSV/Git; mutable private position state in D1).
- The engine's daily advancement is a **pure function** of (frozen entry state + prior settled
  position state + today's quote), which makes it fully unit-testable and idempotent per trading
  date — required, because WS1's job may fire more than once a day (last-write-wins ethos).
- Push introduces a subscription store (D1) and a sender path (Worker) — scoped into WS5 phase 4.
- Auth is intentionally minimal at user = 1 but the schema and query discipline are already
  multi-tenant, so user > 1 is a feature addition, not a migration.

## Phasing (each phase independently useful)

1. D1 schema + "I took this" write path (positions spine + first event).
2. Held-tickers feed (rides the ADR-010 tick).
3. Stop-advancement engine (profit-floor invariant, 20/50MA trailing, stateful two-close exit,
   ATR≥7 scale-out) + tests.
4. Push notifications (VAPID; stop-hit + earnings-approach).
