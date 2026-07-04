# Lookup Tab Improvements — Build Plan

> Pickup-able plan. Anyone on the team can drive this from the slice checklist
> below. Develop on `claude/lookup-tab-improvements-h7nw9b`; PR into
> `claude/elegant-babbage-hlxnfy`. See `.claude/rules/branch-commit-discipline.md`.

## Why

The PWA Lookup tab (`docs/index.html`) answers: *"I'm looking at this stock —
is its sector/industry a tailwind or a headwind?"* It already renders a company
header, INDUSTRY/SECTOR cards, and a SIGNAL box. The opportunity is to surface
our **moaty derived metrics** (rank trajectory, conviction/consistency,
breadth) that plain Finviz can't show — turning the tab into our clearest
differentiation, without adding noise.

## Decision: client-side first

Phase 1 is built **entirely client-side** in `docs/index.html`, reusing data
already downloaded and metrics already computed by `scripts/compute_deltas.py`.
The frontend already ships the full append-only CSV and discards all but the
latest day in `getLatest()` (`docs/index.html` ~L347) — so even the sparkline
needs **no new infra**, just stop discarding history. Cloudflare Worker/KV/D1
are deferred until CSV payload or logic-duplication actually hurts — see
`knowledge/cloudflare-edge-roadmap.md` and `knowledge/decisions/ADR-001-lookup-client-side-first.md`.

## Working agreement (every commit)

- Every code change ships its **docs + task-tracking** change in the same
  commit/PR (update this checklist, `.session/SPRINT.md`; on milestones
  `.session/WORK_LOG.md` + `session-notes.md`).
- HTML/dashboard-only changes need no pytest — say so in the commit message.
  Any `scripts/` logic change requires a `tests/` change (N/A in Phase 1).
- Small, single-logical-slice commits.

---

## Phase 0 — Knowledge & plan (no behavior change) — its own PR

- [ ] `planning/lookup-tab-improvements.md` — this plan.
- [ ] `knowledge/moaty-metrics.md` — inventory of every derived metric.
- [ ] `knowledge/decisions/ADR-001-lookup-client-side-first.md`
- [ ] `knowledge/decisions/ADR-002-rank-floor-metric.md`
- [ ] `knowledge/decisions/ADR-003-breadth-excludes-week.md`
- [ ] `knowledge/cloudflare-edge-roadmap.md`
- [ ] `README.md` — "What makes this different" moat section.
- [ ] `.session/SPRINT.md` — seed Phase 1 slices + deferred proposals.

## Phase 1 — Client-side slices (`docs/index.html`)

Each slice = code + docs + tracking.

- [x] **Slice 1 — Retain history + weekly-rank sparkline.** Done. `loadGroup`
      retains full delta history in `state.data[group].deltaAll`;
      `groupRankHistory()` + `rankSparkline()` render an inline SVG of `rank_week`
      over the last ~30d in each group card, y inverted (up = improving), labeled
      "Weekly rank · last Nd". Hidden when <2 points. SW cache bumped to v4.
- [x] **Slice 2 — Conviction chip + Rank Floor.** Done. `convictionInfo(delta,
      n)` computes Rank Floor = max(rank_month, rank_quarter, rank_half) →
      "Top #{floor} across 1/3/6mo" row, plus a chip: "Sustained" (floor ≤ top
      quartile) / "Consistent" (rank_agreement ≥ 0.85 AND floor ≤ top half) /
      hidden. Graceful null when the three ranks aren't all present.
- [x] **Slice 3 — Breadth dot strip.** Done. `breadthStrip(snap)` renders
      Day·Wk·Mo·Qtr·6M·YTD dots (green/red/grey per `perf_*` sign) and an
      "All green" badge / "k/4 green" count. Verdict gates on
      month/quarter/half/YTD only (`BREADTH_TFS[].gate`); day & week render but
      don't gate (ADR-003).
- [x] **Slice 4 — Evidence-backed SIGNAL copy.** Done. `groupReasons()` pulls
      concrete signals (rank trajectory, conviction+floor, momentum, breadth);
      `contextSignalCard` shows the 2–3 strongest under the verdict. Scoring
      spine unchanged.
- [x] **Slice 5 — Clarity wins.** Done. Rank label now "Rank (wk)"; 30d
      rank-delta chip ("▲N over 30d") beside the weekly arrow; `lookupSkeleton()`
      replaces the "Looking up…" text.
- [x] **Slice 6 — QoL.** Done. `lookupGlossary()` collapsed "Why this matters"
      `<details>` (copy from `knowledge/moaty-metrics.md`; the percentile-basis
      info affordance is folded into its Momentum/Breadth rows). Subtle Finviz
      (`quote.ashx?t=SYM`) + **TradingView** (`/symbols/SYM/`) deeplinks in the
      company header. Deepvue dropped — no public per-ticker URL (login-gated);
      owner chose TradingView instead.

## Phase 2 — Signal card v2 (2026-07-04)

Slice 4 above deliberately left the SIGNAL card's scoring spine (`groupScore()`)
untouched. By 2026-07-04 that day-1 3-factor heuristic predated most of what the
product now computes (RS vs S&P, `momentum_confirmed`, `regime_short_long`,
Focus/Picks per-stock context) and had drifted from its own evidence text and
from the in-app Guide hub's `tabs: [..., 'lookup']` metadata (which promised
`rs_score`/`rs_confirmed` on this tab — they never rendered anywhere on it).
See `.session/session-notes.md` for the full issue writeup. Fixed in one pass:

- [x] `groupScore()` replaced by `groupSignal()` — a factor-based composite
      (`momentum_confirmed` 0.30, `rs_confirmed` 0.30, short-window rank delta
      0.15, `regime_short_long` 0.15, breadth 0.10; missing factors excluded and
      weights renormalized, never faked as neutral). Evidence text is generated
      from the *same* factor list that produced the score, so it can no longer
      disagree with the verdict (the old `groupReasons()` used different
      thresholds on different inputs).
- [x] Missing-data caveat: when only one of industry/sector has any tracked
      data, the verdict uses that side alone with an explicit caveat line
      instead of silently averaging in a fake neutral 0.5. Both sides missing →
      a distinct "NO SIGNAL" state instead of forcing MIXED.
- [x] RS vs S&P surfaced on the group cards (`rsChip`/`rsBeatsChip`, previously
      Today/vs-Market only) and folded into the score.
- [x] `lookupGlossary()` rebuilt to generate from `GUIDE.metrics.filter(m =>
      m.tabs.includes('lookup'))` instead of a hand-maintained duplicate copy —
      closes the drift permanently (added `lookup` to `sustained_strength`'s
      tabs too, since its one-liner explains the Rank Floor chip).
- [x] "This stock" block: when the searched ticker is itself in today's
      Stage-2 picks, its own category tags, ATR extension, earnings proximity,
      and Focus score now surface directly on the signal card
      (`findTickerPickInfo()`/`tickerContextHtml()`), reusing the existing
      Focus/Picks helpers. Silently absent otherwise (no manufactured
      "not found" message — matches the existing silence-is-no-signal
      convention for row badges elsewhere in the app).
- [x] Copy moved off long-only, uniform-severity phrasing to context-only
      framing that scales with data quality.
- [x] `tests/test_pwa_lookup_signal.py` (new) — first test coverage for the
      Signal card at all.

## Deferred — backlog (seed into SPRINT)

- Sparkline rank-timeframe toggle (wk/mo/3mo/6mo).
- Acceleration hint from `perf_*_delta_*` (▲▲ accelerating / ▼ fading).
- Empty-state recent-searches + example-ticker quick chips.
- Tap group card → jump to that group in Today/Momentum (internal deeplink).
- AI rotation-phase line on the sector card.
- Promote Rank Floor to a computed column in `compute_deltas.py` (+ dashboard +
  tests).
- Revisit whether All-Green should re-include week gating (and align dashboard,
  which currently gates on week too).

## Rank Floor spec

- **Definition:** worst (numerically highest) rank across month/quarter/half →
  "never worse than #N over 1/3/6 months."
- **Display:** "Top {floor} across 1/3/6mo"; optional band "#{best}–#{floor}".
- **Why these timeframes:** matches `rank_agreement`'s inputs for a coherent
  sustained story; avoids weekly/daily noise.
- **Phase 1:** client-side from existing `rank_month/quarter/half`. **Later:**
  pipeline column.

## Critical files

- `docs/index.html` — all Lookup rendering; the `getLatest` history change.
- `scripts/compute_deltas.py` — reference for metric definitions
  (`compute_rank_agreement` L183, ranks L143, momentum L163).
- `dashboard/app.py` — reference for Sustained Strength (L552) + All Green
  (L628) logic to keep PWA and Streamlit consistent.

## Verification

Serve `docs/`; look up tickers spanning strong+sustained semi, weak group,
low-confidence match, untracked industry, ETF, `ticker_not_found`. Confirm each
new element matches the underlying `deltas.csv`/`snapshots.csv` rows. Cross-check
breadth/sustained against `dashboard/app.py`. Verify both deeplinks. No Python
changes in Phase 1.
