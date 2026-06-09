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
| T7 | Test: `collect()` row-count guard | `tests/test_collect_parsing.py` | S | Mock `fetch_html` + `parse_table`; verify RuntimeError on 0 rows, warn-only when below floor. |
| T8 | GitHub Actions CI workflow | `.github/workflows/tests.yml` (new) | S | Run `pytest tests/ -v` on every push; no Playwright needed since tests mock the browser. |
| T9 | Test: `ensure_deltas_csv` all paths | `tests/test_compute_deltas.py` | S | Test: file doesn't exist (creates), correct schema (no-op), old schema (migrates — already covered). |

---

### 🟢 In Progress

_(nothing)_

---

### ✅ Done

| # | Task | Date |
|---|------|------|
| — | First live scrape: 11 sectors, 144 industries | 2026-06-09 |
| — | End-to-end pipeline verified (collect → deltas → dashboard) | 2026-06-09 |
| — | GitHub Actions cron wired (weekdays 22:00 UTC) | 2026-06-09 |
| — | Scraper fixes: CSS selector, domcontentloaded, TLS, perf_day | 2026-06-09 |
| 1 | Test infrastructure: 50 tests, all green (`pytest tests/ -v`) | 2026-06-09 |
| 2a | `rank_day` metric added to delta schema; existing CSVs auto-migrated | 2026-06-09 |
| 2b | Momentum score NaN fix: all-NaN columns excluded from mean | 2026-06-09 |
| 3a | Rank columns (rank_day/week/month/ytd) in Snapshot tab | 2026-06-09 |
| 3b | CSV export buttons on Snapshot, Top Movers, Momentum tables | 2026-06-09 |
| 3c | Multi-select Time Series (up to 3 groups, color-coded) | 2026-06-09 |
| 4a | `collect()` post-parse row-count guard (RuntimeError on 0 rows) | 2026-06-09 |
| 4b | Unknown Finviz column names logged as summary line to stderr | 2026-06-09 |
| 4c | `fetch_html()` runtime timing logged | 2026-06-09 |
| 5a | GitHub Actions job timeout: `timeout-minutes: 30` | 2026-06-09 |
| 5b | GitHub Actions post-collect row-count verification step | 2026-06-09 |
| 6a | Heatmap tab (RdYlGn; gated behind ≥7 day data guard) | 2026-06-09 |

---

## Effort Key
| Label | Time |
|-------|------|
| S | < 1h |
| M | 1–2h |
| L | 2–4h |

---

## Next Milestones

| Date | Event |
|------|-------|
| ~2026-06-16 | 7d deltas available — Heatmap + Top Movers light up |
| ~2026-06-23 | 14d deltas available |
| ~2026-07-09 | 30d deltas available — full picture |

After 7d data arrives: consider adding `rank_day_delta_7d` to the delta schema (same pattern as `rank_week_delta_7d`).

---

## Pending Task Details

### T7: Test `collect()` row-count guard
```python
# In tests/test_collect_parsing.py — requires monkeypatch
def test_collect_raises_on_zero_rows(monkeypatch, tmp_path):
    import scripts.collect as m
    monkeypatch.setattr(m, "DATA_DIR", tmp_path)
    monkeypatch.setattr(m, "fetch_html", lambda url: "<html/>")
    monkeypatch.setattr(m, "parse_table", lambda *a, **kw: [])
    with pytest.raises(RuntimeError, match="0 rows"):
        m.collect("sector")

def test_collect_warns_below_floor(monkeypatch, tmp_path, capsys):
    import scripts.collect as m
    monkeypatch.setattr(m, "DATA_DIR", tmp_path)
    monkeypatch.setattr(m, "fetch_html", lambda url: "<html/>")
    # Return 3 rows — above 0, below floor of 8 for sectors
    monkeypatch.setattr(m, "parse_table", lambda *a, **kw: [
        {"date": "2026-06-09", "name": f"G{i}", "collected_at": "", "group_type": "sector",
         "stocks": 1, "market_cap": 1.0, "pe": None, "fwd_pe": None,
         "perf_day": 0.1, "perf_week": 0.1, "perf_month": 0.1, "perf_quarter": 0.1,
         "perf_half": 0.1, "perf_year": 0.1, "perf_ytd": 0.1,
         "avg_volume": 1000, "rel_volume": None, "change": 0.1}
        for i in range(3)
    ])
    m.collect("sector")  # should not raise
    assert "warn" in capsys.readouterr().err
```

### T8: GitHub Actions CI workflow
New file `.github/workflows/tests.yml`:
```yaml
name: Tests
on:
  push:
    branches-ignore: [claude/elegant-babbage-hlxnfy]
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install dependencies
        run: pip install -r requirements.txt -r requirements-dev.txt
      - name: Run tests
        run: pytest tests/ -v
```
Note: no Playwright install needed since tests mock the browser entirely.

### T9: Test `ensure_deltas_csv` all paths
```python
# In tests/test_compute_deltas.py
def test_ensure_deltas_csv_creates_fresh(tmp_path):
    path = tmp_path / "deltas.csv"
    ensure_deltas_csv(path)
    assert path.exists()
    with open(path) as f:
        header = f.readline().strip().split(",")
    assert header == DELTA_COLUMNS

def test_ensure_deltas_csv_noop_on_correct_schema(tmp_path):
    path = tmp_path / "deltas.csv"
    ensure_deltas_csv(path)
    mtime_before = path.stat().st_mtime
    ensure_deltas_csv(path)  # second call — should be no-op
    assert path.stat().st_mtime == mtime_before
```

---

## Verification Checklist

- [x] `pytest tests/ -v` — 50 tests pass
- [x] `python scripts/compute_deltas.py` — migrates existing CSVs, `rank_day` in output
- [x] Dashboard: rank cols in Snapshot, download buttons, Time Series multiselect, Heatmap "need 7 days" message
- [x] GH Actions `collect.yml` — timeout + row-count step present
- [x] Push branch; draft PR #3 created
- [ ] T7: `collect()` guard tests added
- [ ] T8: `tests.yml` CI workflow added
- [ ] T9: `ensure_deltas_csv` path tests added
