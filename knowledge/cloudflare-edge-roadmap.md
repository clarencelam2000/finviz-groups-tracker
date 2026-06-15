# Cloudflare Edge Roadmap (deferred)

> Why the Lookup tab is client-side today and what would move it to the edge.
> Decision recorded in `knowledge/decisions/ADR-001-lookup-client-side-first.md`.

The existing `worker/` Cloudflare Worker handles ticker lookup (FMP) + cache
ops. The roadmap below extends it only when there's a concrete trigger — not
speculatively.

## Phase 1 (current) — client-side

The PWA already downloads `deltas.csv` / `snapshots.csv` and computes views in
the browser. All Lookup metrics (rank trajectory, conviction, breadth, Rank
Floor) are derivable from data already on the client. No edge changes.

## Phase 2 — KV `groups:latest` blob

**What:** A nightly GitHub Action step (after `compute_deltas.py`) writes a
compact JSON blob of the latest day's per-group derived metrics to Workers KV.
The Worker's `/lookup` response is enriched from KV so the tab is one
self-contained fetch and moat logic centralizes server-side.

**Trigger:** the CSV-to-browser payload grows large enough to hurt mobile load,
OR client JS and worker logic start duplicating the same metric computations.

**Cost:** one KV namespace + one write/day; well within free tier.

## Phase 3 — D1 edge time-series

**What:** Mirror the append-only CSVs into a Cloudflare D1 (edge SQLite) table;
add `/group-history?name=X` for real server-side time-series (sparklines over
arbitrary windows without shipping full history).

**Trigger:** full-history CSV (≈ a year of data) is too heavy to ship to the
browser for the sparkline, i.e. when Phase 1's "keep history client-side"
approach stops scaling.

**Cost:** D1 free tier covers this volume comfortably; main cost is the sync
step + schema maintenance.
