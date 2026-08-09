# ADR-014 — WS4 trade tickets (live ticket = expansion of the shipped WS3 card)

- **Status:** Accepted (owner green-light 2026-08-09)
- **Issue:** #263 (part of #257). Depends on WS2 (#261, shipped) + WS3 (#262, shipped A/B/C).
- **Supersedes/clarifies:** the WS4 section of `planning/roadmap-cron-lifecycle.md` and the earlier
  WS4 mock in `planning/mocks/trade-lifecycle-surfaces.html`.
- **Companion mock:** `planning/mocks/ws4-trade-ticket.html` (approved rev 2026-08-09).

## Context

WS4 turns an already-computed pick into an actionable, **no-profit-target** trade plan for a swing
trader. The roadmap framed it as "surface metrics `picks_metrics.py` already computes" and listed a
new `atr_from_lod` metric + an earnings port as backend work. On inspection during this staff
session that framing was **overtaken by what WS3 already shipped**:

- `atr_from_lod` (= `(price − session low) / ATR`) is **already computed and stored** by
  `scripts/collect_morning.py` / `scripts/pick_status.py` into the morning session CSV, with
  owner-set bands `ATR_FROM_LOD_CLEAN = 0.8` / `ATR_FROM_LOD_CHASE = 1.0` (docs/CLAUDE.md).
  ADR-013's provisional "1.0/1.5" was already superseded — 0.8/1.0 is live. WS4 **inherits** it; it
  is **not** a new EOD `picks_metrics.py` column.
- The entry-trigger **status** (`triggered / setting_up / gapped_through / invalidated /
  failed_breakout / no_quote`) is already computed and stored by WS3 (`status` column).
- Earnings dates are already in `data/picks/picks.csv` as the `Earnings` column, with a JS parse
  mirrored in `docs/index.html`. Days-to-earnings is re-derivable at view time — **no Python port,
  no `days_to_earnings` backend column** is needed for WS4 (obvious signal, cheaply re-derived).

**Consequence: WS4 has essentially no backend work.** It is the **expansion of the shipped WS3
morning pick card into a full trade ticket**, almost entirely PWA-side.

## Decision

### 1. Shape — one live ticket, no EOD render state
The ticket answers **"is this a good trade right now."** It renders intraday against a session
snapshot (Phase B: morning; Phase C: pre-close). There is **no** EOD "plan" render state — the
stray "EOD" label on the earlier mock was an error, not a requirement. No profit targets anywhere
(stated explicitly on the surface so the absence reads as a choice).

### 2. Data model — a per-ticker join, zero new columns
Ticket = **WS3 morning session row ⋈ prior EOD `picks_latest` row**, keyed on `ticker`:

| Field | Source |
|---|---|
| snapshot price, today high/low, ATR, `trigger`, `status`, `atr_from_lod`, `list_category` | WS3 morning session CSV (`data/picks/sessions/morning_latest.csv`) |
| prior-session low, 20MA/50MA (from `SMA20`/`SMA50` %), `atr_ext_50`, `Earnings`, Focus score, pick-reason flags (`grp_rs_new_high`, …) | prior EOD `picks_latest` row |
| risk/share, %risk, position size, price-override recompute of both gates | computed in the PWA |

No new backend column is added. MA dollar levels are reconstructed in JS from `Price` + `SMA%`
(same formula as `picks_metrics.py`).

### 3. Price is snapshot-read + user-overridable (no live feed yet)
The app has no streaming quotes — only two snapshots/day. So the price field is **labeled by its
snapshot** ("10:05 read"), never called "live," and status is shown "as of `<snapshot>`" with **no
minute-precise trigger timestamp** (we cannot know it). The field is an **editable override**
(localStorage, per ticket): when the user checks between snapshots and the price has moved, they
type the real number and ATR-from-LoD, ATR-ext-from-50MA, risk/share and position **recompute off
their input**. Real live quotes are parked to **#287** (Alpaca integration).

### 4. Two don't-chase gates, above the stop menu
- **ATR-from-LoD** (intraday — "am I chasing today"): bands `0.8 / 1.0`, inherited from WS3
  (`ATR_FROM_LOD_CLEAN` / `ATR_FROM_LOD_CHASE`). Single source of truth stays WS3's config.
- **ATR-ext-from-50MA** (positional — "is it rubber-banded off the mean"): reuses the existing
  `atr_ext_50` column and its config bands (`ATR_EXT_PENALTY_START 2.5` / `ATR_EXT_ACTIONABLE 4.0`
  / `ATR_EXT_TRIM 8.0`). No new constant.

Both sit **above** the stop menu because chase-risk gates the decision to take a stop at all.

### 5. Stop menu — the one interaction
Segmented control over four bases — **prior low / today low / 20MA / 50MA** — live-recomputing
risk/share, %risk, and position on selection.

### 6. Risk-per-trade — free input, no config constant
Per-ticket $ the user types (localStorage); position recomputes. Not a global constant or % of
account (owner, alignment § 10). Nothing to triple-document.

### 7. Earnings guardrail — hard amber card
Days-to-earnings from the existing `Earnings` column + existing JS parse (`parseEarningsInfo`). A
**hard** card (not a chip — it should interrupt): amber when `daysUntil <= EARNINGS_CAUTION_DAYS`
(10), red when `<= EARNINGS_IMMINENT_DAYS` (3).

> **Amendment 2026-08-09 (implementation):** the earlier draft proposed a *new*
> `EARNINGS_GUARDRAIL_SESSIONS` constant (default 5). During Phase B this was **rejected** in favor
> of **reusing the existing `EARNINGS_IMMINENT_DAYS` / `EARNINGS_CAUTION_DAYS`** PWA constants — DRY,
> avoids a redundant constant, and sidesteps a days-vs-sessions unit mismatch (the parse yields
> calendar days). **WS4 adds no new configurable constant.**

### 8. Focus score stays a footnote
The screen gate ("good stock to be in") must not be re-used as the ticket headline ("good trade
right now"). Shown as small watchlist context only.

### 9. Pick reason in the header
`from Picks · <list_category> · <reason>` (e.g. `leaders · rs_new_high`) from `list_category` +
the `grp_*` reason flags, so the ticket says why the stock is on the list.

### 10. Missing-quote (`no_quote`) — degraded but honest
When a picked ticker has no live quote (feed miss), render the ticket in a degraded state: show the
static plan levels from the EOD row, grey out the live gate + trigger status, never silently drop
the ticket. Consistent with WS3 never hiding a `no_quote` pick.

## Phasing

- **Phase A (this PR):** ADR-014 + approved mock (`planning/mocks/ws4-trade-ticket.html`) +
  `CLAUDE.md` "Artifacts-not-files" rule + SPRINT/#287 tracking. Docs only.
- **Phase B:** PWA ticket surface — the join, stop menu, two gates, sizing, price override,
  earnings guardrail, pick reason; reached by expanding a WS3 morning pick card. Ships the release
  triplet (`releases.json` + `sw.js` cache bump) per house rule. Verified with the PWA Playwright
  harness (add any new Playwright test to the `tests.yml` `--ignore=` list in the same PR).
- **Phase C:** render the same ticket component on the **pre-close (15:50 ET)** snapshot.
  **Blocked on WS3b (#268):** the `pre_close` session is *registered* in `session_config` but its
  store is not yet populated. Phase C is "the same component keyed on `session=pre_close`" once
  WS3b writes that store — small, but not free until #268 lands. (Owner 2026-08-09: "the ticket
  should render there too … not sure if it's literally the same or a later phase" — it's a later
  phase, gated on #268.)

## Consequences

- WS4 ships as a PWA feature with **no backend/schema change** — low risk, fully in-cloud testable.
- **No new configurable constant** — all thresholds reuse existing PWA constants (see § 7 amendment).
- ATR-from-LoD's single source of truth stays in WS3's config; WS4 must not fork it.
- Pre-close coverage is explicitly deferred to Phase C behind #268, not dropped.

## Alternatives rejected
- **Backend `atr_from_lod` EOD column + earnings Python port** (original roadmap framing): rejected
  — `atr_from_lod` already ships from WS3; earnings is re-derivable from an existing column. Adding
  either would be dead weight. An EOD `(close − low)/ATR` also degenerates to a candle-position
  proxy that `range_atr` already covers.
- **A separate EOD "plan" render state:** rejected — a ticket is only used at the moment of action,
  which is intraday. The EOD label was an error.
- **Calling the snapshot price "live" / minute-precise trigger time:** rejected as dishonest given
  a twice-daily snapshot cadence; solved by snapshot labels + the user override (#287 for real
  live data).
