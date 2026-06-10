# Work Log

> Gitignored. Track milestones, decisions, and discoveries as the project evolves.

---

## Data Collection Milestones

| Date | Milestone | Notes |
|------|-----------|-------|
| 2026-06-09 | First successful scrape | 11 sectors, 144 industries |
| 2026-06-09 | Pipeline verified end-to-end | collect → deltas → dashboard all working |
| | Confirmed Finviz update time | Probe intraday — TBD |
| 2026-06-09 | GitHub Actions cron enabled | Runners confirmed working |
| 2026-06-09 | Mobile PWA live on GitHub Pages | https://clarencelam2000.github.io/finviz-groups-tracker/ |
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
| 2026-06-09 | GitHub Actions runners not allocating | Open | Enable Actions in repo Settings → Actions → General |

## 2026-06-09 — Mobile iPhone PWA dashboard shipped (PR #7, merged)

Three static files added to `docs/`: `index.html` (full PWA), `manifest.json`, `sw.js`. Hosted on GitHub Pages — no server required. Fetches CSVs live from `raw.githubusercontent.com` on every load. Three tabs: Today (color-coded perf cards), Movers (rank delta leaderboard, placeholder until ~June 16), Momentum (works immediately). Installable as a home screen app on iPhone via Safari → Add to Home Screen.

## 2026-06-10 — rank_agreement metric + Strength tab (Streamlit + PWA) shipped (PR #17, merged)

`rank_agreement` now accumulates in `deltas.csv` from today — measures how consistently rank_month, rank_quarter, and rank_half agree for each group (1.0 = all timeframes confirm same standing, 0.0 = maximum disagreement). New Strength tab in both Streamlit and PWA surfaces Sustained Strength (top-N in all three timeframes simultaneously) and All Green (all perf timeframes positive, emoji dot matrix). Works on day-1 data since perf_quarter/half are scraped live from Finviz.

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
