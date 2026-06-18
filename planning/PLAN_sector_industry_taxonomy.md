# Plan: Finviz Native Sector → Industry Taxonomy

**Status:** Approved — ready to implement  
**Branch:** `claude/blissful-ritchie-gxaqkc`  
**Backlog items unblocked:** INS-7 (Sector Breadth), Task 6b (Sector Drill-down)

---

## Background

Sectors and industries are currently two independent flat lists. `data/sectors/snapshots.csv`
and `data/industries/snapshots.csv` have no relationship column — there is no way to ask
"which industries belong to Technology?" from our stored data.

This blocks two high-value features:

| Task | Description | Blocked on |
|---|---|---|
| **INS-7** | Sector Breadth — "7 of 18 Technology industries are top-half of the full universe" | Sector→industry map |
| **Task 6b** | Streamlit sidebar sector filter — narrows all tabs to one sector's industries | Sector→industry map |

We also have `data/taxonomy_map.csv` (133 rows, FMP industry names → Finviz industry names),
built in session TICKER-0 from 242 sampled FMP profiles. That solves the ticker-lookup direction
(FMP name → Finviz name). It does NOT solve the sector containment tree natively within Finviz.
The two maps coexist and serve different purposes.

---

## Key Discovery: Finviz `sg=` Parameter

Finviz exposes a sub-group filter via the `sg=` URL parameter that returns only the industries
belonging to a given sector:

```
https://finviz.com/groups?g=industry&sg=basicmaterials&v=152&o=name&st=d1&c=0,1,2,3,4,5,6,7,8,9,10,11,12,13,15,16,17,18,19,20,21,22,23,24,25,26,27,28
```

Changing `sg=` for each of the 11 sectors gives the complete, authoritative Finviz sector→industry
containment tree — no inference, no confidence scores.

### The 11 Sector Slugs

| Finviz Display Name | URL slug |
|---|---|
| Basic Materials | `basicmaterials` |
| Communication Services | `communicationservices` |
| Consumer Cyclical | `consumercyclical` |
| Consumer Defensive | `consumerdefensive` |
| Energy | `energy` |
| Financial | `financial` |
| Healthcare | `healthcare` |
| Industrials | `industrials` |
| Real Estate | `realestate` |
| Technology | `technology` |
| Utilities | `utilities` |

---

## Output Artifacts

Two files written to `data/`:

### `data/finviz_sector_industry_map.json`
```json
{
  "generated_at": "2026-06-17T...",
  "source": "finviz.com/groups?g=industry&sg=<sector>",
  "total_industries": 144,
  "sectors": {
    "Basic Materials": ["Aluminum", "Chemicals", "Copper", "Gold", "..."],
    "Technology": ["Application Software", "Communication Equipment", "..."],
    "...": ["..."]
  }
}
```

### `data/finviz_sector_industry_map.csv`
Two columns: `finviz_sector`, `finviz_industry` — flat pairs for pandas joins.

Both files are committed to the repo. This is a static artifact that changes only when
Finviz restructures their taxonomy (rare; maybe once a year).

---

## Execution Constraint

Same as `collect.py`: Cloudflare blocks headless Chromium on Google Cloud IPs (AS396982).
Must run on GitHub Actions (Azure IPs pass Cloudflare) or locally.

**Solution:** New workflow `.github/workflows/fetch_taxonomy.yml` with `workflow_dispatch`
trigger only. Not part of the daily cron. Run once to generate the map; re-run only after
Finviz restructures their taxonomy.

---

## Implementation Plan

### Step 1 — `scripts/fetch_taxonomy.py` (NEW)

One-shot script that:
1. Opens one Playwright browser instance
2. Iterates all 11 sector slugs, fetches each filtered industry page
3. Parses industry names from `.groups_table` (same CSS selector as `collect.py`)
4. Writes `data/finviz_sector_industry_map.json` and `data/finviz_sector_industry_map.csv`
5. Prints a summary: sector name, industry count, total

**Key function:** `parse_industry_names(html: str) -> list[str]`
- Finds `.groups_table`, extracts the `Name` column from every data row
- Skips header row, skips empty name cells
- Returns sorted list of industry names

**Retry logic:** Same pattern as `collect.py` — 3 attempts per sector, 30s/60s/120s backoff.
Set `COLLECT_RETRY_DELAY=0` to skip waits during debugging.

### Step 2 — `.github/workflows/fetch_taxonomy.yml` (NEW)

```yaml
name: Fetch Taxonomy
on:
  workflow_dispatch:
permissions:
  contents: write
jobs:
  fetch:
    runs-on: ubuntu-22.04
    steps:
      - checkout
      - setup python 3.12
      - pip install -r requirements.txt && playwright install chromium --with-deps
      - python scripts/fetch_taxonomy.py
      - git commit and push data/finviz_sector_industry_map.*
```

### Step 3 — `tests/test_fetch_taxonomy.py` (NEW)

Tests for `parse_industry_names()`:
- Happy path: standard table with Name column, returns sorted list
- Empty table (header only): returns `[]`
- Missing `.groups_table`: raises `ValueError`
- Missing `Name` column in header: raises `ValueError`
- Rows with empty name cells are skipped

No test for the network layer (same decision as `collect.py` — Playwright fetch is integration-only).

---

## Downstream Usage (after map is generated)

### INS-7 — Sector Breadth

```python
import json
tax = json.loads(Path("data/finviz_sector_industry_map.json").read_text())

def sector_breadth(sector_name, industries_delta_df, n_total):
    """Fraction of this sector's industries in the top half of the full universe."""
    siblings = tax["sectors"][sector_name]
    sector_df = industries_delta_df[industries_delta_df["name"].isin(siblings)]
    top_half = (sector_df["rank_week"] <= n_total / 2).sum()
    return top_half, len(siblings)
```

Show on sector cards: "9 / 11 industries in top half"

### Task 6b — Streamlit Sector Filter

```python
SECTOR_INDUSTRY_MAP = json.loads(Path("data/finviz_sector_industry_map.json").read_text())["sectors"]
sector_choice = st.sidebar.selectbox("Sector", ["All"] + list(SECTOR_INDUSTRY_MAP.keys()))
if sector_choice != "All":
    industries_df = industries_df[industries_df["name"].isin(SECTOR_INDUSTRY_MAP[sector_choice])]
```

### Future: `finviz_sector` column in snapshots

Once the map exists, `collect.py` can stamp a `finviz_sector` column on each industry row at
scrape time. This enables `groupby("finviz_sector")` in `compute_deltas.py` and removes the need
to join at query time. Deferred to avoid a schema migration — the map must be validated first.

### Future: PWA breadth dots

Each sector card shows "k / N industries green" using the map to identify siblings, then
cross-referencing with loaded industry delta data. Implementation in `docs/index.html`.

### Future: AI briefing enrichment

"Technology is rank 2 but only 6/18 industries are improving — narrow leadership" is a much
sharper AI signal than what's available today. Can be added to the `generate_ai.py` briefing
context once the map is committed.

---

## Cross-Validation

After generating the map, verify:
1. Sum of industry counts across all 11 sectors ≈ total industry rows in `data/industries/snapshots.csv`
   (may differ slightly if Finviz adds/removes industries since last collect run)
2. All `finviz_sector` values in `data/taxonomy_map.csv` appear as keys in the new map
3. Industry names in the map match names in `data/industries/snapshots.csv` (spot-check 10 names)

---

## Files Created / Modified

| File | Change |
|---|---|
| `scripts/fetch_taxonomy.py` | NEW — one-shot Playwright scraper |
| `.github/workflows/fetch_taxonomy.yml` | NEW — `workflow_dispatch` CI wrapper |
| `tests/test_fetch_taxonomy.py` | NEW — parsing unit tests |
| `data/finviz_sector_industry_map.json` | NEW — generated artifact (committed) |
| `data/finviz_sector_industry_map.csv` | NEW — generated artifact (committed) |
| `planning/PLAN_sector_industry_taxonomy.md` | This file |

Files NOT changed in this phase:
- `scripts/collect.py` (future: add `finviz_sector` stamp column — deferred)
- `dashboard/app.py` (INS-7 / 6b — separate PR once map is validated)
- `docs/index.html` (PWA breadth dots — separate PR)
- `scripts/compute_deltas.py` (breadth column — separate PR)

---

## Effort

| Step | Label | Notes |
|---|---|---|
| `fetch_taxonomy.py` + tests | S | ~80 lines of script, ~40 lines of tests |
| `fetch_taxonomy.yml` | S | Clone of `collect.yml` pattern, simpler |
| Run workflow + validate output | S | Manual `workflow_dispatch` trigger |
| INS-7 / 6b implementation | M each | Separate PRs, unblocked once map is validated |
