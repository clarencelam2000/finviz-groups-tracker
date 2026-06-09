# Work Log

> Gitignored. Track milestones, decisions, and discoveries as the project evolves.

---

## Data Collection Milestones

| Date | Milestone | Notes |
|------|-----------|-------|
| 2026-06-09 | First successful scrape | 11 sectors, 144 industries |
| 2026-06-09 | Pipeline verified end-to-end | collect → deltas → dashboard all working |
| | Confirmed Finviz update time | Probe intraday — TBD |
| | GitHub Actions cron enabled | Needs default branch set first |
| | First 7d deltas available | Need 7 days of data |
| | First 30d deltas available | Need 30 days of data |
| | First `notebooks/analysis.ipynb` | After 30+ days of data |

---

## Scraper / Pipeline Issues

| Date | Issue | Resolution | Status |
|------|-------|------------|--------|
| 2026-06-09 | CSS selector `.table-groups` wrong | Changed to `.groups_table` | Fixed |
| 2026-06-09 | `wait_until="load"` times out | Changed to `"domcontentloaded"` | Fixed |
| 2026-06-09 | `perf_day` always empty | Copy from `change` column (same value) | Fixed |
| 2026-06-09 | `pytz` + `plotly` missing from requirements.txt | Added | Fixed |
| 2026-06-09 | `na_option='bottom'` missing from rank() calls | Added per spec | Fixed |
| 2026-06-09 | `rel_volume` always NaN | Not served by Finviz for this URL — low priority | Known |

---

## Dashboard Updates

| Date | Feature Added | Notes |
|------|--------------|-------|
| 2026-06-09 | Initial 4-tab dashboard | Snapshot, Top Movers, Time Series, Momentum |

---

## Decisions Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-06-09 | CSV as source of truth; SQLite/Parquet derived | Binary files bloat Git history |
| 2026-06-09 | Rank computed from perf values, not scraped | Finviz display rank depends on sort order |
| 2026-06-09 | Playwright over Elite subscription | Elite not available; Playwright works at low frequency |
| 2026-06-09 | Positive rank delta = improvement | rank_prior - rank_today; lower rank = better |
| 2026-06-09 | session-notes.md + WORK_LOG.md tracked in Git | Cloud containers are ephemeral — gitignoring loses them |
| 2026-06-09 | `perf_day` sourced from `change` column | Finviz doesn't serve a separate Perf Day column for groups |

---

## Open Questions / Future Ideas

- [ ] Confirm Finviz data finalization time (probe intraday)
- [ ] Find historical Finviz-equivalent data for backfill (deferred)
- [ ] Add sub-industry level tracking
- [ ] Consider adding alert when momentum_score crosses threshold
- [ ] Cross-reference with SPY/QQQ volume on same day
- [ ] Dashboard: multi-select Time Series, heatmap view
