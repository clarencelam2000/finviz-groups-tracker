# WS5 Trade-Lifecycle — Design-Review Session Narrative (2026-08-11)

**Participants:** Repo owner (swing trader) + Claude (staff eng / product advisor).
**Trigger:** Review of PR #294 (docs-only reconciliation of the `closing` state), its design docs
(`planning/trade-lifecycle-engine.md`, `knowledge/decisions/ADR-012-trade-lifecycle-engine.md`), the
decisions inside them, and a UX-backward pass on what the trader actually wants.
**Outputs:** ADR-012 Decisions 8–11; design-doc §§ 3a, 5a, 6, 7, 8, 8b, 11a-resolved, 12, 13, 14;
mock `planning/mocks/ws5-needs-confirmation-surface.html`; PR #295; tracking issues (below).

> This is the durable narrative so the team has the *why*, not just the diffs. The normative spec is
> the design doc + ADR; this file is the reasoning and the owner's own words behind them.

---

## 1. The review verdict on #294

#294 is an accurate, mergeable reconciliation. Its core correction — replacing auto-close-at-modeled-
price with the user-confirmed `Closing` state — fixes a real defect (the engine wrote `exit_price`
from a fill the user never got). Working backwards from the trader's experience surfaced a set of gaps
that #294 didn't cover; those became the edits below. Notably the committed WS5 mock already contained
the exit-signal card and the aggregate-exposure footer *ahead of* the spec — the mock led the doc.

## 2. Threads worked, and where each landed

### The `Closing` exit loop
- **"Still holding" re-signals daily → feature, not bug** (owner). For a `stop_hit`, re-pinging while
  you sit below your own risk line is correct — an app that goes quiet enables abandoning the stop.
  **Condition:** the repeat must be a *different, de-escalated notification class* or it trains the
  user to ignore all exit pushes (the monitoring-dashboard cry-wolf failure). → **two-tier
  notifications** (design § 8).
- **Missed-push single point of failure** (Claude, owner agreed). The whole loop hinged on one VAPID
  push; iOS drops it silently without install-to-home. → **in-app "needs your confirmation" pull
  surface**: push = nudge, app = source of truth (design § 8; mock).
- **Auto-confirm after N sessions** (owner approved, N=5). A stuck `Closing` auto-closes at the
  modeled price, labeled `confirmation_status='auto'`, correctable. Resolves the "unconfirmed rows rot
  the expectancy record" tension without forcing the user to be a data-entry clerk (design § 6/§ 7).
- **Editable actual exit price on confirm** (owner asked). Already implied by spec ("writes the
  user's price"); the mocks showed only a button. Now: Confirm opens a price field pre-filled with the
  modeled price, editable — symmetric with entry's "I took it" (design § 7; mock updated).
- **caution_flag on revert** — a genuine two-way door, ~1 day of difference. Owner chose **re-arm**
  (`CAUTION_REARM_ON_HOLD=true`): "still holding" resets the two-close counter (design § 6/§ 7).

### Exit rules
- **`hard_exit` split** (owner approved) into `close_below_50ma` (slow bleed) and `severe_breakdown`
  (≥ 3 ATR one-day crash) — the record/UI can now say *why*. `gap_through_stop` renamed
  `gap_down_below_stop`. Canonical enum in design § 6.
- **Two-close-below-20MA while on 50MA basis** — Claude first flagged as a bug ("defeats the widen");
  owner pushed back that a caution has real signal even above the 50MA, and it was oversold.
  **Resolution:** it fires by design → `Closing` → "still holding" if you want 50MA room; the confirm
  loop absorbs it. Documented, not suppressed (design § 4/§ 7). Downgraded from "bug" to "choice."
- **Trim rule confirmed present**: every whole ATR multiple ≥ 7 of extension-from-50MA trims 10% of
  *remaining* (owner asked to verify; it's `TRIM_START_ATR=7` / `TRIM_PCT=0.10`, design § 4/§ 6).

### Storage / feeds / backtesting
- **Full-column capture** (owner: "make sure eng builds it"). Store the full Finviz scrape column set
  in `ticker_quotes`, not just `advance()`'s 8 fields — the one thing you can't backfill; nearly free
  on a tiny table (design § 5/§ 12; ADR Decision 10; **issue filed**). Current `collect_morning`
  fetch code likely needs editing to persist the wider set.
- **Two feeds are separate and both freely add-able** (owner example: Mon-night add AVGO to watch for
  Tue AM). Morning picks feed (what to consider) vs. held feed (what you own); membership independent;
  user *and* future LLM can add to either (design § 5a).
- **Should the morning feed also store full columns?** Yes — same cheap-insurance logic; noted for the
  WS3 feed implementer (design § 5a references the principle).
- **Backtesting demoted to nice-to-have** (owner aligned). Only the *capture* (append-only +
  full-column) is a one-way door; the harness/export/Alpaca are deferrable compute with no data loss.
  Honest scope: expectancy + exit-variant replay over *taken* trades — **not** a general strategy
  backtester (no counterfactual entries, unentered universe, or post-exit bars). **Selection-bias
  mitigation deferred**: widening the feed to un-taken picks was rejected (many picks/day → scrape-load
  explosion); if ever wanted, use a **bulk OHLCV provider (Alpaca) via a pluggable source**, keeping
  live truth on `ticker_quotes` (design § 12; ADR Decision 10).

### Scale-ins (the owner's better model)
- Owner reframed: **each add-on buy is an independent lot** — own entry/stop/R/trim — grouped for
  display with a share-weighted average, not an average-in. This is *lighter* than the blend model
  Claude first raised as a conflict: it makes § 3's frozen-single-entry invariant **correct**, needs
  **no `advance()` change**, and only adds `meta.group_id` + a display aggregation. Phase-1 obligation:
  don't assume one-position-per-ticker; reserve `group_id` (design § 3a/§ 8b; ADR Decision 8; **issue
  filed**). "Close whole ticker vs. close one lot" UX deferred to the building phase (no mock now).

### Extensibility / think-big
- **Effective-config `advance()`**: the engine reads global constants merged with per-position `meta`
  overrides, passed in as a parameter — never a hard-coded global lookup. Keeps a per-position rule (UI
  or future LLM) a data change, not an engine rewrite (design § 14; ADR Decision 11).
- **LLM position-manager** is an additive *third caller* of the ticker-generic write path (§ 8a) — not
  boxed in. Read-side: the append-only event ledger is an ideal LLM substrate (trade summaries, stop
  explanations, portfolio Q&A). Broader LLM directions captured in a **tracking issue**.

### Retrace-to-MA risk awareness (owner's hard-won lesson)
Owner: unrealized profit is exposure, not safety. Real losses came from oversized add-ons, not seeing
that a more-extended position loses more on a *normal* retrace to its 50MA, and higher adds dragging
cost basis up. Framings to encode: "your unrealized profits belong to the market"; "your real equity
is where you'd be if stopped at your MA"; "a pullback to the 20/50MA is normal — your sizing should
survive it." → a **retrace-to-MA give-back / extension / equity-at-MA view**, all from existing fields,
information-only (design § 13). Feeds off the grouped-lot heat aggregation (§ 8b).

## 3. What blocks what
- **Phase 1 (D1 schema + write path)** — unblocked. Obligations it must honor so later phases stay
  cheap: don't assume one-position-per-ticker; reserve `meta.group_id`; `confirmation_status` column;
  capture full columns + append-only; `advance()` signature takes effective-config.
- **Phase 3 (`advance()` engine)** — build to the resolved § 4/§ 7 rules (split reasons, caution
  re-arm, two-close-on-50MA, effective-config).
- **Phase 4 (push)** — build the two-tier notifications + pull surface + auto-confirm job.

## 4. Tracking issues opened this session
- Full-column `ticker_quotes` capture (+ likely `collect_morning` edit).
- Scale-in independent lots + `meta.group_id` grouping/aggregation UI.
- LLM position-management layer (directions catalogue).
- (Retrace-to-MA risk view rides the position/group-card phase; noted in design § 13.)
