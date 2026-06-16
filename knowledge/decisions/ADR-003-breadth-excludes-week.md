# ADR-003: Lookup breadth/All-Green signal excludes week (and day) from gating

**Date**: 2026-06-15
**Status**: Accepted (flagged for possible reconciliation)

## Context

The Lookup tab's breadth element shows a Day·Wk·Mo·Qtr·6M·YTD dot strip and a
derived green/"All-Green" verdict. We had to decide which timeframes *gate* the
green verdict. The dashboard's All Green (`dashboard/app.py` L628) currently
gates on `perf_week, perf_month, perf_quarter, perf_half, perf_ytd` — i.e. it
includes week.

## Decision

In the Lookup tab, the green/All-Green verdict gates on **month, quarter, half,
and YTD only**. The **week and day dots still render** in the strip (useful
context) but do **not** gate the green verdict. Rationale: day/week movement is
the noisiest and most prone to flipping a verdict on intraday chop; the medium-
term timeframes are what a "tailwind/headwind" read should hinge on.

## Alternatives considered

- **Match the dashboard exactly (include week).** Rejected for the PWA's
  single-glance verdict — one red week shouldn't flip an otherwise-strong group
  to "not all green." Kept the week *dot* so the information isn't lost.
- **Also gate on day.** Rejected: even noisier than week.

## Consequences

- The PWA and dashboard diverge on what "all green" gates. This is intentional
  but tracked: **backlog item — revisit whether All-Green should re-include week
  gating, and if so align the dashboard, or instead drop week from the
  dashboard's gate too.**
- The dot strip remains a full six-timeframe view regardless of gating.
