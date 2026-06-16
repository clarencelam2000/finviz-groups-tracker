# ADR-001: Lookup tab Phase 1 is client-side; defer Cloudflare KV/D1

**Date**: 2026-06-15
**Status**: Accepted

## Context

The PWA Lookup tab (`docs/index.html`) should surface our derived metrics (rank
trajectory, conviction, breadth) for a looked-up ticker's sector/industry. The
question was whether to build this on the edge (Cloudflare Worker enriches the
`/lookup` response from a KV blob or D1 time-series) or in the browser.

Key facts:
- The frontend already downloads the full append-only `deltas.csv` /
  `snapshots.csv` and computes views from them. `getLatest()` (~L347) currently
  discards all but the latest day.
- All metrics needed for Phase 1 (`rank_*`, `rank_agreement`, `momentum_score`,
  `perf_*`) already exist per row. Rank Floor is derivable from existing columns.
- CSV history is currently only ~days long, so payload size is not yet a problem.

## Decision

Build Phase 1 entirely client-side in `docs/index.html`, reusing already-
downloaded data and already-computed metrics. The sparkline is unlocked simply
by not discarding history in the lookup path. No Worker/KV/D1 changes.

## Alternatives considered

- **Enrich `/lookup` via a nightly KV `groups:latest` blob.** Centralizes moat
  logic and makes the tab one fetch. Rejected for now: adds infra + an Action
  step for value we already have client-side; premature.
- **D1 edge SQLite for real time-series + `/group-history`.** Rejected for now:
  only justified once full-history CSV is too heavy to ship to mobile.

## Consequences

- Fastest path to user value; no new infra, secrets, or deploy surface.
- Some moat logic lives in JS (and is mirrored from `dashboard/app.py`); keep
  them consistent and documented in `knowledge/moaty-metrics.md`.
- Promotion triggers are recorded in `knowledge/cloudflare-edge-roadmap.md`;
  revisit when CSV payload or logic duplication starts to hurt.
