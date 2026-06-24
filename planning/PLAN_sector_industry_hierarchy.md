# Plan: Sector → Industry Hierarchy

**Goal:** Surface the sector→industry containment relationship throughout the product — breadth signals, drill-downs, and filter controls — so users can see not just which sectors are winning but *how broadly* those wins are distributed across constituent industries.

**Status:** Phase 1 DONE (PR #177). Phase 2 DONE (branch `claude/fervent-thompson-rlvfs1`, PR pending).

---

## Phase 1 — Streamlit Dashboard (DONE, PR #177)

### TASK-6B: Sidebar sector filter

Added a "Sector" selectbox to the Streamlit sidebar (Industries view). Choosing a sector narrows all six dashboard tabs (Snapshot, Top Movers, Time Series, Momentum, Heatmap, Strength) to that sector's constituent industries. Full-universe copies (`_delta_df_all`, `_snap_df_all`) are preserved for Phase 1's breadth computation so the sector filter doesn't skew the top-half threshold.

**Files:** `dashboard/app.py`

### INS-7: Sector Breadth table

New "Sector Breadth" section at the top of the Strength tab (Industries view). `compute_sector_breadth(industry_delta, taxonomy, rank_col)` in `dashboard/sector_breadth.py` counts how many of each sector's industries rank in the top half of the *full* 144-industry universe by the selected rank metric (week/month/ytd). A rank metric selectbox lets the user change the lens.

**Files:** `dashboard/sector_breadth.py`, `dashboard/app.py`, `tests/test_sector_breadth.py`

---

## Phase 2 — PWA Breadth Bars + Sector Drill-Down (DONE, branch `claude/fervent-thompson-rlvfs1`)

### VP decisions (captured via AskUserQuestion 2026-06-24)

| Feature | Options | VP choice |
|---------|---------|-----------|
| Feature A — drill-down UX | Expand-in-place vs new Sectors tab | **Expand-in-place** |
| Feature B — breadth detail | Percentage only vs count+mini-bar | **Count + mini-bar** |
| Feature F — sector rank | Everywhere vs drill-down only | **In drill-down only** |

### Feature B: Breadth bar on sector cards

Each sector card in the Today tab shows a fill bar and a count like "9/13 industries top-half". Computed client-side from the already-loaded industry delta data.

**Implementation:**
- `TAXONOMY_URL` constant (line 312): fetches `data/finviz_sector_industry_map.json` from GitHub raw.
- `state.taxonomy` / `state.sectorBreadth`: two new state fields (line 366–367).
- `fetchJSON(url)`: new helper (line 974) parallel to `fetchCSV()`.
- `loadTaxonomyAndBreadth()` (line 1091): fire-and-forget async; triggered after sector data loads (line 1013). Loads taxonomy JSON, then calls `computeSectorBreadth()`.
- `computeSectorBreadth(industryDelta, taxonomy)` (line 1031): "top half" = `rank_ytd ≤ n/2`. Returns `{sector: {top, total}}`.
- `breadthBar(top, total)` (line 1046): renders a fill bar + "N/M industries top-half" label (VP Feature B choice).
- `renderToday()` card template (lines 1329–1391): breadth bar injected between the main row and the expandedDetail.

### Feature A: Expand-in-place sector drill-down

Tapping a sector card toggles `state.expandedName` (same mechanism as industry card expansion). When expanded, `renderSectorDrillDown(sectorName)` (line 1060) renders a sorted list of the sector's constituent industries with their universe rank and YTD perf.

### Feature F: Sector rank in drill-down only

The "#N in Technology" label (universe rank within the sector) appears only inside the expanded drill-down view, not on the collapsed card.

### GUIDE and release

- New `sector_breadth` metric added to `GUIDE.metrics[]` in `docs/index.html` (line 470).
- Matching one-liner added to `knowledge/moaty-metrics.md`.
- `docs/releases.json`: version `2026.06.24.1`, tag `feature`, tab `today`.
- `docs/sw.js`: CACHE bumped `finviz-v29` → `finviz-v30`.

---

## Deferred / Fast-follow

| Task | Description | Tracked in SPRINT.md |
|------|-------------|----------------------|
| HIE-FF1 | PWA sector filter — analogous to Streamlit TASK-6B; filter Today/Momentum/Strength tabs to one sector's industries | HIE-FF1 |
| HIE-FF2 | Sector rank chip on collapsed card (Feature F surface on card, not just drill-down) | HIE-FF2 |

---

## Data dependency

The breadth computation requires `data/finviz_sector_industry_map.json` (seeded by `scripts/seed_taxonomy.py`, committed, 100% match against snapshot CSVs as of 2026-06-24). Re-run `seed_taxonomy.py` only if Finviz restructures taxonomy (rare, ~once/year).
