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
- [ ] **Slice 4 — Evidence-backed SIGNAL copy.** Rewrite `contextSignalCard` to
      cite the 2–3 strongest concrete reasons. Same scoring spine.
- [ ] **Slice 5 — Clarity wins.** Label rank basis ("Rank (wk) #41 of 144"),
      add 30d rank-delta context (`rank_week_delta_30d`), loading skeleton.
- [ ] **Slice 6 — QoL.** "Why this matters" collapsible glossary (copy from
      `knowledge/moaty-metrics.md`), breadth/momentum info affordance, subtle
      Finviz (`https://finviz.com/quote.ashx?t=SYM`) + Deepvue deeplinks in the
      company header (verify exact Deepvue URL during impl).

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
