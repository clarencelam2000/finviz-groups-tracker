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
| 2026-06-09 | Rank columns in Snapshot tab | rank_day/week/month/ytd joined from deltas |
| 2026-06-09 | CSV download buttons | Snapshot, Top Movers, Momentum tabs |
| 2026-06-09 | Multi-select Time Series | Up to 3 groups, color-coded |
| 2026-06-09 | Heatmap tab (5th tab) | RdYlGn colorscale, gated behind ≥7 days of data |

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

## Infrastructure Issues

| Date | Issue | Status | Fix |
|------|-------|--------|-----|
| 2026-06-09 | GitHub Actions runners not allocating | Fixed | Adding a payment method to the GitHub account resolved runner allocation (account-level billing gate, even on public repos) |
| 2026-06-09 | Node.js 20 action deprecation | Fixed | Added FORCE_JAVASCRIPT_ACTIONS_TO_NODE24 to both workflows; forced migration deadline is 2026-06-16 |

## 2026-06-09 — GitHub Actions CI now working (PR #6)

Root cause of all previous CI failures identified and resolved: GitHub required a payment method on the account before allocating hosted runners, even for public repos. Once added, runners allocated normally. Also restored push/PR triggers to tests.yml and pre-emptively opted both workflows into Node.js 24 before the June 16th forced migration deadline.

---

## 2026-06-09 — Commit discipline rules and test scaffolding

`.claude/rules/commit-discipline.md` committed — covers small-commit sizing, per-change test requirements, and the session handoff checklist. PR #3 (merged) already delivered the comprehensive 57-test suite; this session contributed the written rules. PR #4 open as draft.

---

## Open Questions / Future Ideas

- [ ] Confirm Finviz data finalization time (probe intraday)
- [ ] Find historical Finviz-equivalent data for backfill (deferred)
- [ ] Add sub-industry level tracking
- [ ] Consider adding alert when momentum_score crosses threshold
- [ ] Cross-reference with SPY/QQQ volume on same day
- [ ] 6b: Sector → Industry drill-down in dashboard sidebar (L effort)
