# ADR-012: Trade lifecycle engine — architecture, storage, and the domain invariant

**Date**: 2026-08-06 (reconciled 2026-08-10; extended 2026-08-11 with the design-review pass)
**Status**: Proposed (architecture accepted in principle; per-phase implementation pending owner go-word)

> **2026-08-10 reconciliation.** Folded the owner decisions from `knowledge/cron-lifecycle-ideation-and-alignment.md`
> § 10 and the 2026-08-10 owner Q&A into this ADR and `planning/trade-lifecycle-engine.md`: the
> **`closing` state** (exit awaits the user's confirmed fill, symmetric with entry — Decision 6 below);
> the **held-tickers feed is append-only** and doubles as a **backtest substrate** (Decision 1);
> the write path is **ticker-generic** so arbitrary user-entered tickers are a future UI addition,
> not a migration (Decision 7); `SEVERE_BREAKDOWN_ATR = 3.0`, widen = auto-with-per-position-toggle,
> breakeven = +1R (design doc § 6/§ 11).
>
> **2026-08-11 design-review pass** (this session, PR #295). Added Decisions 8–11: **scale-ins are
> independent lots** (not average-in); **missed-push safety** via an in-app pull surface + two-tier
> alerts + auto-confirm; **backtesting demoted to nice-to-have** with only the cheap append-only +
> full-column *capture* kept as the one-way door; **effective-config `advance()`** for a future
> per-position/LLM rule door. Also: `hard_exit` split into `close_below_50ma`/`severe_breakdown`;
> two-close-below-20MA fires on 50MA basis by design; caution re-arms on "still holding"; the two feeds
> (morning picks vs. held) are kept separate and both freely add-able; retrace-to-MA risk view specced
> (design doc § 3a, § 5a, § 6–8, § 12–14). Full session narrative:
> `knowledge/trade-lifecycle-design-review-2026-08-11.md`.

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
  carry. Tiny (open positions × trading days). **Store the full scrape column set**, not just the
  fields `advance()` reads today — an un-captured bar can never be backfilled and the extra columns are
  nearly free (Decision 10). See `planning/trade-lifecycle-engine.md` § 5/§ 12.

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

### 8. Scale-ins are independent lots, not an average-in (owner ruleset, 2026-08-11)

Each add-on buy is its **own trade** — own entry, own stop, own R, own trim ledger — so **each lot is
one `positions` row**. We do **not** blend adds into one volume-weighted position; that would erase
the per-tranche risk the owner actually manages. This makes § 3's frozen-single-entry invariant
*correct*, not a limitation, and requires **no change to `advance()`** (it already runs per position;
N lots on one ticker share one daily bar). The only additions are a `meta.group_id` linking lots for
**display** and a UI aggregation (weighted-avg entry, summed qty, summed heat) that is presentation
only. Rejected: VWAP/average-in (one averaged stop matching neither tranche). Phase-1 obligation:
**do not assume one-position-per-ticker**; reserve `meta.group_id`. Tracked as its own issue. (Design
doc § 3a / § 8b.)

### 9. Missed-push safety + honest record: pull surface, two-tier alerts, auto-confirm

The confirmed-fill model (Decision 6) has a single point of failure — one VAPID push — and a failure
mode where unconfirmed `Closing` positions rot the expectancy record. Decisions: (a) an **in-app
"needs your confirmation" pull surface** makes push the nudge and the app the source of truth
(survives a missed push); (b) **two-tier notifications** (a rare high-salience Tier-1 exit signal vs.
de-escalated Tier-2 reminders) prevent alert-fatigue from training the user to ignore exit pushes;
(c) **auto-confirm** after `EXIT_AUTOCONFIRM_SESSIONS` closes a stuck position at the modeled price
labeled `confirmation_status = 'auto'` — never silently wrong (labeled + correctable). Corrections are
**append-only events** (`exit_corrected` / `reopened`), never destructive edits. (Design doc § 6–8.)

### 10. Backtesting is a nice-to-have; only the cheap data capture is a one-way door

Backtesting the *feature* is deferred. The two irreversible decisions — the feed is **append-only**
and stores the **full scrape column set** — are kept regardless, because an un-captured bar can never
be backfilled and both cost almost nothing on a tiny table. `ticker_quotes` honestly backs
trade-outcome expectancy and exit-variant replay over trades actually taken; it is **not** a general
strategy backtester (no counterfactual entries / unentered universe / post-exit bars). Widening the
feed to un-taken picks is **rejected** (scrape-load explosion); a true strategy backtester, if ever
wanted, uses a **bulk OHLCV provider (Alpaca) through a pluggable source**, keeping the live engine's
truth on `ticker_quotes`. (Design doc § 12.)

### 11. The engine door stays open: effective-config `advance()`

`advance()` reads an **effective config** (global constants + per-position `meta` overrides) passed
in as a parameter, never a hard-coded global lookup. Empty today, but this keeps a per-position rule —
set in the UI or by a future LLM layer — a data change rather than an engine rewrite. Combined with
Decisions 7 (ticker-generic write path) and 8 (independent lots), a natural-language position-manager
is an additive third caller, not a redesign. (Design doc § 14.)

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
