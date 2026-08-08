# Roadmap: Cron Lifecycle → Trade Lifecycle

> **START HERE if you're picking up this workstream.** Read in this order:
> 1. **This roadmap** — the map (workstreams, sequencing, what's parked and why).
> 2. **`knowledge/cron-lifecycle-ideation-and-alignment.md`** — owner intent + all decisions
>    (incl. § 10, the 2026-08-07 decision update). If any doc contradicts it on intent, it wins.
> 3. The per-workstream ADR + design doc (linked per row below), then the tracking issue.
> 4. **`planning/mocks/trade-lifecycle-surfaces.html`** — committed WS3/WS4/WS5 UI mocks (open in a browser).
>
> **Start coding at #258 (WS1)** — owner go-word given 2026-08-07; fold in the review amendments on
> #258/#259. Everything else waits on the decisions recorded in the alignment record § 10.

## Framing

Cron consolidation (WS1) looks like small infra cleanup, but it's the unblocker for a cascade
of product value: once the dispatcher can host unlimited logical jobs on one Cloudflare Cron
Trigger instead of being capped at 5 per account, every downstream idea in this roadmap that
needs "a small job that runs at a specific time of day" becomes a code change instead of a
scarce-resource negotiation.

**Product philosophy: the app holds the user's state so they don't have to.** The user is a
**swing trader** — not day trading. They react to price action over days, not intraday ticks,
and they do not trade to a pre-set profit target; exits are governed by trailing risk rules, not
"take profit at X." Every workstream below should be read against that lens: features that
demand intraday reaction speed or fixed profit targets are out of scope by design (see § Parked
/ Deferred for two ideas rejected on exactly this basis).

## Workstreams

| ID | Name | Value (one line) | Depends on | Status | Sequence |
|---|---|---|---|---|---|
| WS1 | Cron consolidation + state-machine dispatcher + auto-DST | Frees trigger budget, kills DST toil, makes picks timing correct-by-dependency not by-hope | — | Ready | 1 |
| WS2 | Session dimension (keystone schema change) | Lets a morning snapshot coexist with the EOD snapshot instead of being clobbered by last-write-wins `(date, name)` | WS1 (needs headroom for a morning job) | Design-spike | 2 |
| WS3 | Morning confirmation/invalidation surface | Makes the *existing* EOD picks product usable at the moment of action (Triggered / Still-setting-up / Gapped-through / Invalidated) | WS1, WS2 | Ready-after-keystone | 3 |
| WS4 | Trade tickets (entry + stop menu + risk sizing) | Turns already-computed metrics into an actionable, no-profit-target trade plan per pick | WS2 (needs prior-session levels) | Ready-after-keystone | 4 |
| WS5 | Trade lifecycle engine (Watching→Open→Managing→Closed) | Manages a position *after* entry: profit-floor stop ratchet, stateful exit rule, scale-out ledger, push alerts | WS1 (held-tickers feed), WS2, WS4 | Design-spike (own ADR to follow) | 5 |

WS1 is the only item with no dependencies and is deliberately sequenced first — see
`planning/cron-consolidation-state-machine.md` for its implementation-ready design and
`knowledge/decisions/ADR-010-single-trigger-cron-dispatch.md` for the decision record.

---

### WS2 — Session dimension (keystone)

Add a `session` concept (e.g. `session = morning | eod`, designed from the start to hold *N*
sessions, not hardcoded to exactly two) across `collect.py`, `compute_deltas.py`,
`collect_picks.py`, and PWA display. This is the load-bearing schema change nearly every
downstream workstream needs, because:

- `collect.py` snapshots are last-write-wins on `(date, name)` (`.claude/rules/data-pipeline.md`
  § CSV deduplication) — a morning collect run today would simply be overwritten by the EOD run
  on the same trading date, not coexist with it.
- `data/picks/picks.csv` is keyed `(date, list_category, ticker)` — same subtlety, different key
  shape.

Keeping a morning artifact alongside the EOD one **requires** widening these keys (or an
equivalent schema mechanism) to include session. This needs its own ADR before implementation —
not sketched further here.

### WS3 — Morning confirmation/invalidation surface

A ~9:45 ET snapshot that tags each **prior-session's** pick with a live status: Triggered /
Still-setting-up / Gapped-through (chase risk) / Invalidated (below stop). This is sequenced
*before* any net-new morning picks list because it's cheaper (read-only against yesterday's
picks, no new selection logic) and higher-value (it makes the product usable at the actual
moment of action — when the user is deciding whether to act on yesterday's setup), and it
exercises the WS2 session schema on a read path before anything writes against it.

> **Design record:** `knowledge/decisions/ADR-013-ws3-morning-status.md` (2026-08-08) closes
> all WS3 open decisions — state-machine predicates + precedence, provisional store under
> `data/picks/sessions/`, batched `t=` screener quote scrape, "I took it" local-marker behavior,
> and the 3-PR phasing. Implement against it; amend it there if reality disagrees.

### WS4 — Trade tickets

Surface the metrics `scripts/picks_metrics.py` already computes as a trade-ready ticket:

- **Entry trigger**: prior-day-high breakout.
- **Stop menu**: prior-day low / today's low / 20MA / 50MA — pulling directly from the already-
  computed `risk_20ma_pct` and `risk_50ma_pct` (`scripts/picks_metrics.py:107-119`, documented
  in `scripts/picks_config.py:183-184`) for the resulting stop-distance-as-%-of-price.
- **Resulting risk-per-share and shares-for-my-risk**, derived from whichever stop the user
  picks.
- **No profit targets** — consistent with the swing-trader framing above; the user reacts to
  price, they don't trade to a bias target.
- **New cheap metric — ATR-from-LoD**: `(price − Low) / ATR`, a don't-chase entry-quality gate.
  Rationale: if price is already >1 ATR off the day's low, the day's expected range is largely
  spent, so entering now offers poor risk/reward even if the setup itself is valid. This is a
  new derived column in the same family as `atr_ext_50`/`range_atr`
  (`scripts/picks_metrics.py:98-134`) and should follow that file's existing pattern (pure
  function, `METRICS_COLS`-style triple documentation) when implemented.
- **Earnings guardrail**: reuse the Finviz `Earnings` date already parsed for Focus scoring to
  stamp days-to-earnings on each ticket, with a hard flag — "reports in N sessions, this is an
  earnings gamble, not a swing setup" — so an entry isn't taken unknowingly into an earnings
  print.
- **Picks/Focus score stays a watchlist gate, not the ticket headline.** The existing score
  answers "is this a good stock to be in"; the ticket answers "is this a good trade right now."
  Keep them visually and conceptually separate — don't double-count one signal as both a
  screening gate and a headline metric on the same surface.

Depends on WS2 because the entry trigger (prior-day-high breakout) needs the *prior session's*
row to be addressable independently of today's — which is exactly what the session-dimension
schema change provides. Otherwise "ready-after-keystone": the underlying metrics largely already
exist.

### WS5 — Trade lifecycle engine

The biggest value and the biggest design surface of the roadmap — will get its **own ADR and
design doc** when it's picked up; this section only sketches it so it's visible on the board and
not proposed cold later.

**States**: `Watching → Open → Managing → Closed`, one row per position.

**The user's actual ruleset** (captured faithfully here; these become tunable config constants,
documented in the repo's standard 3 places once implemented):

- **Entry freezes**: entry price, entry date, initial stop, and stop basis, at the moment the
  user confirms they took the trade. The user's real fill may differ from the computed trigger
  price — the UI must let them enter their actual fill, or all downstream risk/R-multiple math
  is wrong from the start.
- **Corrected invariant — read carefully, this is not "the stop only ratchets up."** The real
  rule is a **profit floor** that ratchets and never retreats: *once past breakeven, never go red
  again.* The *active* stop is allowed to widen (e.g. 20MA → 50MA) as long as it stays at or
  above that floor. Widening to the 50MA is only safe specifically because, by the time that
  widening happens, the 50MA has risen above entry — so even the looser stop still locks in a
  green trade. This distinction matters: a naive "stop only ever moves up" model would forbid
  the 20MA→50MA widening that this ruleset explicitly wants, because the 50MA stop level can be
  numerically *below* the current 20MA stop level even while both are above the profit floor.
- **Trailing mechanics**: trail to the 20MA as price rises; widen the trail to the 50MA once the
  50MA itself rises above entry (the condition that makes the profit-floor invariant hold for the
  wider stop, per above).
- **Exit rule is stateful, not a single-bar trigger.** Cut a winner only on the **second
  consecutive close** below the 20MA — a first close below the 20MA is a `caution`/watch-next-
  close flag, not an exit signal by itself. A discretionary hard-exit override exists for a
  position that "really breaks" (e.g. a close under the 50MA, or a severe ATR breakdown) that
  should exit immediately regardless of the two-close rule. This requires tracking a caution flag
  and a consecutive-closes-below-20MA counter per position, not just today's close in isolation.
- **Scaling out is v1 core, not a later nicety.** Trim 10% of the *remaining* position at each
  whole ATR-multiple of extension from the 50MA, starting at 7 (i.e. 7, 8, 9, …). Requires a trim
  ledger tracking the highest multiple already executed, so the same extension level is never
  re-trimmed on a subsequent tick that re-observes it. The user sometimes runs several partial
  stops across a position's life — model the position as a **reducing quantity with a trim
  history**, not an all-or-none open/closed flag.

**Data / architecture implications:**

- **Non-obvious consequence: a held position needs a daily quote even after the ticker falls off
  the picks list.** WS5 therefore requires a **held-tickers feed** — a small daily job that
  scrapes quotes only for the user's currently-open-position tickers, independent of the picks
  screener run. This is exactly the kind of "one more small job at a specific time of day" that
  WS1's unbounded-jobs-per-tick design exists to make cheap — call this out explicitly as a
  concrete beneficiary of WS1 when WS5 is scoped.
- **Storage: not append-only CSV.** Positions *mutate* daily (state, stop level, remaining
  quantity all change in place), which is a poor fit for the repo's append-only-observations CSV
  convention (`.claude/rules/data-pipeline.md`) — CSVs model *observations*, not *evolving
  records*. Separately, live position data is personal financial information and should not be
  committed to a public repo the way `data/*.csv` is today. Use **Cloudflare D1** — the sibling
  project on the same Cloudflare account already runs D1 plus VAPID web-push, so this is a
  proven path on infrastructure already paid for and already integrated, and it gets push-
  notification support essentially for free.
- **Shape**: narrow typed relational **spine** + a JSON `meta` bag + an append-only **event
  log**, not one wide mutable table with no history:
  - `positions` (spine — typed, queryable, constraint-enforced): `user_id, trade_id, ticker,
    state, entry_date, entry_price, initial_stop, stop_basis, profit_floor, current_stop,
    remaining_qty, caution_flag, closes_below_20ma, highest_trim_atr, opened_at, closed_at,
    exit_price`, plus a `meta` JSON column (SQLite JSON functions) for notes/tags/UI-state/future
    fields that don't warrant a schema migration.
  - `position_events` (append-only ledger): `trade_id, ts, event_type (entered | stop_moved |
    partial_exit | caution | closed | note), payload JSON` — gives an audit trail, replay
    capability, and a place to add new event types without a schema change.
- **Multi-tenancy / security — do this now even at user = 1.** Put `user_id` on every row and
  scope every query by it from day one; this is cheap now and brutal to retrofit later. D1/SQLite
  has no row-level security (that's a Postgres/Supabase feature) — tenant isolation here is
  **app-layer only**: the Worker derives `user_id` from the authenticated token and must never
  trust a client-supplied `user_id`. At user = 1, auth can be a single shared token; the
  `user_id` column's entire purpose right now is to leave the door open for user > 1 later
  without a migration.
- **UX loop**: the WS3 confirmation surface says "TICKER triggered" → user taps "I took it,"
  enters their actual fill and chosen stop → this creates a position → the engine manages it
  daily per the ruleset above → push notifications fire on stop-hit and on the earnings-approach
  guardrail (VAPID, available on the same Cloudflare account already; note iOS PWA push requires
  the app to be installed to the home screen, iOS 16.4+).

**Phasing within WS5** (each phase independently useful, do not require the whole engine to ship
at once):
1. D1 schema + the "I took this" write path (positions spine + first event).
2. Held-tickers feed (the daily quote job for open positions, riding WS1's tick).
3. Stop-advancement engine: profit-floor invariant, 20MA/50MA trailing, stateful two-close exit
   rule, with tests.
4. Push notifications (VAPID, stop-hit + earnings-approach alerts).

---

## Cross-cutting cheap wins

Short, low-effort items that ride along on the WS1 infrastructure rather than requiring their
own workstream:

- **Auto-DST** (part of WS1) — see ADR-010; eliminates the twice-yearly manual cron edit.
- **Self-heal + retry-on-miss, and retiring the healthchecks.io dead-man's switch / reduced
  reliance on GitHub failure emails** (part of WS1) — falls out of the picks dependency-gate
  state check described in `planning/cron-consolidation-state-machine.md`.
- **Weekly taxonomy drift check** — a gated Sunday job (riding the same single tick) that
  dispatches a validation-only run and alerts if Finviz has restructured its sector/industry
  taxonomy or if tracked row counts deviate from the known-good 11 sectors / ~145 industries
  baseline (see `CLAUDE.md` § finviz_sector_industry_map files for the baseline numbers and
  `scripts/seed_taxonomy.py`, which already has re-run-and-validate logic this job can lean on).
- **Earnings guardrail** — see WS4; reuses the Focus-scoring earnings-date parse.
- **Light sizing/crowding reminder** — surfaced as *information*, not a diversification
  prescription: "5 of your positions are in one group, moving as one bet; a stop day stops you
  out of all five, so know your true aggregate exposure," plus a one-line reminder to "pick the
  best horse in the firing group, not the laggards." Deliberately not framed as "you should
  diversify" — the user is a rotation trader who intentionally concentrates into the leading
  group, and prescriptive diversification advice would fight that strategy rather than support
  it. Keep this light: informational surfacing only, no automated position limits.

## Parked / deferred

Kept here explicitly so these aren't re-proposed cold without the prior context:

- **Morning picks (net-new opening list).** Deferred, not rejected — a brand-new morning
  selection list was judged less actionable than WS3's confirmation surface for the *existing*
  EOD picks, so WS3 is sequenced first as the higher-value, cheaper option. Morning picks stays
  on the board as a possible future addition once WS3 has shipped and been used.
- **Rotation-narrative digest.** Needs further polish/refinement before it's ready to land;
  not rejected on substance, just not yet ready.
- **Gap surface / opening-breadth gauge.** Rejected for this product. It's condition-dependent
  and a comparatively thin signal, and it leans day-trading in flavor — reacting to the open in
  real time doesn't fit a swing trader who acts on daily closes, not on the opening print.
- **Intraday persistence/decay tracking.** Rejected — this is day-trading territory (tracking
  how a signal decays over the course of a single session), which is explicitly out of scope
  given the swing-trading framing at the top of this document.

## Open questions

- WS2's exact session-key shape (a `session` column value set, how it interacts with the
  existing `(date, name)` / `(date, list_category, ticker)` uniqueness keys) is intentionally
  left to WS2's own ADR — not resolved here.
- WS5's D1 schema above is a design sketch pending its own ADR + design doc; field types,
  indices, and the exact `meta`/event-log split are not finalized.
- Whether the weekly taxonomy check's alert path reuses the picks dependency-gate's KV "miss
  record" pattern from WS1, or needs its own — not decided.
