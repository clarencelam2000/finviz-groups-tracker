# ADR-011: Session dimension — keep provisional intraday observations without contaminating the settled close

**Date**: 2026-08-06
**Status**: Proposed — **ends in a decision point for the owner** (see § Decision, Option A vs C)

## Context

The pipeline records exactly one observation per trading date per entity, and treats the latest
write as authoritative:

- `data/{sectors,industries}/snapshots.csv` — last-write-wins on `(date, name)`
  (`.claude/rules/data-pipeline.md` § CSV deduplication).
- `data/{sectors,industries}/deltas.csv` — one row per `(date, name)`, derived from the above.
- `data/picks/picks.csv` — keyed `(date, list_category, ticker)`.
- `data/benchmark/snapshots.csv` — one SPY row per date.

The cron consolidation (ADR-010) removes the trigger-budget ceiling that blocked a morning
market-open job. But a morning capture stamped with today's date would be **overwritten** by the
EOD run on the same date under last-write-wins — the two cannot coexist. Keeping a morning
artifact alongside the EOD one is the load-bearing schema change that WS3 (morning
confirmation), WS4 (trade tickets needing prior-session levels), and WS5 (held-tickers feed)
all depend on. This is the "session dimension keystone" (roadmap WS2).

**The invariant that dominates the design.** Morning `perf_*` values from Finviz are
**provisional mid-session numbers**. The delta / momentum / RS / picks pipeline is a settled-close
computation — feeding provisional data into it silently would corrupt every downstream signal
(a 10:00 AM `perf_week` is not the week's settled change). So the real requirement is not merely
"store two rows" — it is: **provisional intraday data must never reach a computation that assumes
the settled close.** How we guarantee that is the actual decision.

## Decision

Introduce a **`session` dimension** — values `eod` (the canonical settled close) plus
`morning` and any future intraday labels — **designed for N sessions, not hardcoded to two**
(the owner was explicit on this). The question is *where* the session dimension lives.

### Options considered

**Option A — add a `session` column to the existing files**, widening the uniqueness keys to
`(date, session, name)` / `(date, session, list_category, ticker)`. One schema, one file per
entity. Every existing consumer must now remember to filter `session == 'eod'` before any
settled-close computation, or provisional rows leak in. Migration backfills `session='eod'` on
all history.

**Option B — a separate file per session** (`snapshots_morning.csv`, …). Rejected: schema
duplication, file sprawl, and the confirmation surface's morning-vs-prior-EOD comparison becomes
a cross-file join keyed by hand. Strictly worse than either A or C.

**Option C (recommended) — canonical/provisional physical separation.** The existing files keep
their **exact current semantics** — they *are* the `eod` settled session, one row per
`(date, name)`, and the entire delta/momentum/RS/picks pipeline reads them **unchanged**.
Provisional intraday observations go into **new, physically separate append-only stores** keyed
`(date, session, <entity>)`. Nothing that computes a settled signal can even see provisional
data, because it lives in a different file the settled pipeline never opens.

### Recommendation: Option C

**The provisional-never-contaminates-settled invariant should be structural, not disciplinary.**
Option A makes it a rule every current and *future* reader must remember (`df[df.date == max]`
silently grabbing a morning row is a one-line footgun waiting years to fire). Option C makes it
impossible by construction, at the cost of one extra file and a simple keyed cross-file read on
the confirmation surface. For a system whose entire value is signal integrity, structural
safety beats a saved file. Option C also keeps ADR-010's low-regret spirit: the proven pipeline
is touched **zero**.

Concrete stores under Option C:

| Store | Key | Status |
|---|---|---|
| `data/{sectors,industries}/snapshots.csv` (+ deltas) | `(date, name)` — **unchanged**, = `session eod` | exists |
| `data/picks/picks.csv` | `(date, list_category, ticker)` — **unchanged**, = settled EOD picks | exists |
| Group-level intraday snapshots | `(date, session, name)` | **deferred** — no consumer yet (opening-breadth was rejected for swing; see roadmap Parked) |
| Ticker-level morning quotes | `(date, session, ticker)` | **needed for WS3/WS5 — location decided *with* WS5** (see Coupling) |

### The decision point that is genuinely yours

Adopt **Option C** (canonical/provisional separation) as recommended, **or** Option A (single
unified table with a `session` column) if you would rather have one mental model / one file per
entity and accept the discipline of filtering `session='eod'` everywhere. My staff recommendation
is C, decisively, on the integrity argument above. **What would change my mind toward A:** if we
foresee wanting *many* symmetric per-session computations (a full morning delta/momentum stack
that mirrors EOD), a single table with a session column is more uniform than a growing set of
`intraday` siblings. Given morning picks are deferred and opening-breadth is rejected, I don't
see that symmetric need today — which is why I land on C.

## Coupling to WS5 (do not decide the ticker-quote store in isolation)

WS3's morning confirmation needs a **per-ticker morning quote** for yesterday's picks. WS5's
held-tickers feed needs a **per-ticker daily quote** for open positions. These are the *same
mechanism* — a quote scrape for a set of tickers — and their storage should be decided together,
not twice. Because WS5 already puts mutable position state in **D1** (ADR-012), the ticker-quote
store's CSV-vs-D1 choice is deferred to WS5's design doc (`planning/trade-lifecycle-engine.md`),
so we don't duplicate the feed or split ticker data across two backends by accident. The *group*
session dimension (this ADR) and the *ticker* quote store (WS5) are separate decisions that share
only the `(date, session, …)` naming convention.

## Consequences

- **The settled pipeline is untouched** — snapshots/deltas/picks retain byte-identical semantics;
  no migration of existing history under Option C.
- **A new, physically-separate provisional tier exists**, keyed by `session`, ready for N sessions.
- **The confirmation surface (WS3)** reads provisional morning data + prior-session settled data
  as an explicit cross-store lookup — a keyed read, not a heavy join.
- **`trading_date()` semantics still hold** — a morning capture on a trading day stamps
  `(date=today, session=morning)`; weekend/holiday roll-back is unchanged.
- **If Option A is chosen instead**, the consequences flip: one file per entity, but a mandatory
  `session='eod'` filter audit across every existing reader (`compute_deltas.py`, `export_db.py`,
  `dashboard/app.py`, the PWA, `evaluate_picks.py`) and a history backfill — larger blast radius
  on proven code, which is exactly what ADR-010 worked to avoid.

## Open questions (for WS2 implementation, after the A/C decision)

- Exact enum of `session` values and their canonical ET capture times (`morning` ≈ 09:45?).
- Whether the deferred group-level `intraday.csv` is created now (empty, schema-ready) or only
  when a consumer appears.
- PWA display: how a provisional/morning reading is visually marked as *not settled* so a user
  never mistakes a 09:45 number for a close.

## WS2 resolution — 2026-08-08 (foundation slice, issue #261)

Owner scope call: **foundation only** — establish the session dimension as a single source of
truth, without building consumer-less stores or premature UI. Resolves the open questions above:

- **Session enum + capture times — pinned** in `scripts/session_config.py` (the SSOT, mirroring
  `delta_config.py`). Three sessions, designed for N: `eod` (17:00 ET, **settled** — this *is* the
  existing pipeline, unchanged), `morning` (09:45 ET, provisional), `pre_close` (15:50 ET,
  provisional). The two provisional times deliberately match the existing `collect_preclose`/
  `collect_eod` cron targets (CLAUDE.md § Automation) so a future capture job needs no new schedule.
- **Group-level `intraday.csv` — not created now.** Per Option C's "deferred — no consumer yet":
  no store file, no writer, no schema is created until WS3/WS3b actually reads one. The module
  documents the store *convention* (append-only, keyed `(date, session, <entity>)`, provisional
  only) as constants, and provides an `assert_provisional()` guard so the "eod never enters a
  provisional store" invariant is enforceable in code — but nothing is wired to a writer yet.
- **PWA "not settled" marking — deferred to WS3.** There is no provisional data flowing to the PWA
  until the morning surface exists; adding the visual convention now would ship chrome that shows
  nothing (and would drag in a `releases.json`/`sw.js` cache bump for an invisible feature). The
  marking lands with its first real consumer (WS3, issue #262) — the mock already shows the intended
  treatment (`planning/mocks/trade-lifecycle-surfaces.html`: provisional banner + timestamp + amber).

The ticker-level morning-quote store's backend (CSV vs D1) remains deferred to WS5's design doc,
unchanged from § Coupling above.
