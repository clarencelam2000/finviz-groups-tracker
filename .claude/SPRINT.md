# Sprint: Pre-Data Improvements
**Branch:** `claude/explore-plan-next-steps-3jlhmh`  
**Goal:** Build robustness, tests, and dashboard features while waiting for data to accumulate (7d deltas arrive ~2026-06-16; full 30d picture ~2026-07-09)

---

## Board

### 🔴 Backlog

| # | Task | File(s) | Effort |
|---|------|---------|--------|
| 6b | Sector → Industry drill-down | `dashboard/app.py` | L |

> Hardcode `SECTOR_INDUSTRY_MAP` (11 sectors → 144 industries) in `app.py`. Sidebar selectbox filters all tabs. Effort is mostly cataloguing the mapping, not code.

---

### 🟡 Ready

| # | Task | File(s) | Effort | Notes |
|---|------|---------|--------|-------|
| 1 | Test infrastructure | `tests/` (new), `requirements-dev.txt` | M | `pytest` + `pytest-mock`. Three test files. See details below. |
| 2a | `rank_day` in compute_deltas | `scripts/compute_deltas.py` | S | Add to `rank_metrics` dict + `DELTA_COLUMNS` + `out` dict. |
| 2b | Momentum score NaN fix | `scripts/compute_deltas.py` | S | Skip missing/all-NaN columns; don't insert full-column NaN. |
| 3a | Rank columns in Snapshot tab | `dashboard/app.py` | S | Left-join `delta_df`; add `rank_day/week/month/ytd` to display. |
| 3b | CSV export buttons | `dashboard/app.py` | S | `st.download_button` after each `st.dataframe()` in tabs 1, 2, 4. |
| 3c | Multi-group Time Series | `dashboard/app.py` | M | `selectbox → multiselect(max_selections=3)`. Loop Plotly traces. |
| 4a | Post-parse row-count guard | `scripts/collect.py` | S | Raise on 0 rows; warn below floor (sector: 8, industry: 100). |
| 4b | Unknown column logging | `scripts/collect.py` | S | Collect unknown headers into list; one summary line to stderr. |
| 4c | Runtime timing | `scripts/collect.py` | S | `time.time()` around `fetch_html()` and full `collect()`. |
| 5a | GH Actions job timeout | `.github/workflows/collect.yml` | S | `timeout-minutes: 30` on the `snapshot:` job. |
| 5b | GH Actions row-count check | `.github/workflows/collect.yml` | S | Inline Python step: check today's rows in both CSVs after collect. |
| 6a | Heatmap tab (gated) | `dashboard/app.py` | M | Build now; info message until ≥7 days exist. RdYlGn heatmap. |

---

### 🟢 In Progress

_(nothing yet — approve sprint to begin)_

---

### ✅ Done

| # | Task | Date |
|---|------|------|
| — | First live scrape: 11 sectors, 144 industries | 2026-06-09 |
| — | End-to-end pipeline verified (collect → deltas → dashboard) | 2026-06-09 |
| — | GitHub Actions cron wired (weekdays 22:00 UTC) | 2026-06-09 |
| — | Scraper fixes: CSS selector, domcontentloaded, TLS, perf_day | 2026-06-09 |

---

## Effort Key
| Label | Time |
|-------|------|
| S | < 1h |
| M | 1–2h |
| L | 2–4h |

---

## Recommended Sequencing

**Phase 1 — this session (~3–4h, all data-independent):**
1. `requirements-dev.txt`
2. Refactor `compute_for_group` to accept optional `snap_path`/`delta_path` kwargs (unlocks testability)
3. Fix 2b (momentum NaN) + 2a (rank_day)
4. Write all tests → `pytest tests/ -v` green
5. Dashboard: 3a (rank cols) + 3b (CSV export)
6. collect.py: 4a + 4b + 4c
7. GH Actions: 5a + 5b

**Phase 2 — next session (~3h):**
8. Dashboard: 3c (multi-select Time Series)
9. Dashboard: 6a (Heatmap, gated on ≥7 days)

**Phase 3 — after 7+ days of data (~2026-06-16+):**
10. Dashboard: 6b (Sector → Industry drill-down)
11. Add `rank_day_delta_7d` once rank_day data has accumulated

---

## Test Plan (Task #1 detail)

### Files to create
```
tests/__init__.py
tests/conftest.py          ← shared fixtures
tests/test_collect_parsing.py
tests/test_compute_deltas.py
tests/test_momentum.py
```

### conftest.py fixtures
- `minimal_snapshot_df` — 3 rows, one with NaN `perf_ytd`, one with NaN `perf_week`
- `empty_snapshot_df` — zero rows, correct columns
- `tmp_snapshot_csv(tmp_path)` — writes minimal df to temp CSV, returns path

### test_collect_parsing.py
No Playwright needed — all parsers are `str → value`.
- `parse_perf`: valid, null sentinels (`""`, `"-"`, `"N/A"`)
- `parse_market_cap`: T/B/M/K suffixes
- `parse_avg_volume`: B/M/K suffixes + raw integers
- `parse_table`: valid HTML, unknown header (warn+skip), empty table, missing name, `perf_day` fallback from `change`
- `append_records`: dedup (0 written), new records (count returned)

### test_compute_deltas.py
Requires `compute_for_group` refactor (optional path kwargs).
- `compute_ranks`: basic ordering, all-NaN, single-row
- `find_nearest_date`: exact match, within 5-day tolerance, empty list
- `compute_for_group`: empty CSV (no crash), single day (all deltas NaN), idempotent, 2 synthetic dates 7 days apart (validate delta value)

### test_momentum.py
Documents current NaN bug + expected fixed behavior (red-green-refactor):
- All metrics present → top scorer approaches 1.0
- Single row → NaN (n ≤ 1 guard)
- One metric all-NaN → score from remaining 6 (was broken, fixed by 2b)
- Per-row mixed NaNs → valid scores produced
- One row all-NaN → that row NaN, others valid

---

## Key Implementation Snippets

### compute_for_group refactor (backward-compatible)
```python
def compute_for_group(group_type, target_date_str=None, snap_path=None, delta_path=None):
    subdir = "sectors" if group_type == "sector" else "industries"
    if snap_path is None: snap_path = DATA_DIR / subdir / "snapshots.csv"
    if delta_path is None: delta_path = DATA_DIR / subdir / "deltas.csv"
```

### Momentum NaN fix
```python
for col in PERF_RANK_METRICS:
    if col in df_day.columns and df_day[col].notna().any():
        ranks = df_day[col].rank(ascending=False, method="min", na_option="bottom")
        scores[col] = (n - ranks) / (n - 1)
# absent columns are ignored; mean(axis=1, skipna=True) handles partial coverage
```

### Snapshot rank join
```python
rank_cols = ["rank_day", "rank_week", "rank_month", "rank_ytd"]
latest_delta_for_join = delta_df[delta_df["date"] == latest_date][
    ["name"] + [c for c in rank_cols if c in delta_df.columns]
]
latest_snap = latest_snap.merge(latest_delta_for_join, on="name", how="left")
```

### Heatmap pivot
```python
pivot = delta_df.pivot(index="name", columns="date", values=selected_col)
pivot = pivot.loc[pivot.mean(axis=1, skipna=True).sort_values(ascending=False).index]
fig = go.Figure(go.Heatmap(z=pivot.values, x=pivot.columns.tolist(),
    y=pivot.index.tolist(), colorscale="RdYlGn", zmid=0))
```

---

## Verification Checklist

- [ ] `pytest tests/ -v` — all green
- [ ] `python scripts/compute_deltas.py` — no errors; `rank_day` in output
- [ ] `streamlit run dashboard/app.py` — rank cols in Snapshot, download buttons work, Time Series multiselect works, Heatmap shows "need 7 days" message
- [ ] GH Actions diff — timeout + row-count step in correct positions
- [ ] Push branch; draft PR created
