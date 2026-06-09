# Session Notes

> Future Claude: read this immediately at session start. Summarize the current state for the user before doing anything else.

---

## Session: 2026-06-09 — Initial build + first live scrape

### What was done
Built the full project from scratch, then validated and fixed the scraper in a second cloud session (with unrestricted network).

**Session 1 (this repo's setup):**
- Created SPEC.md, all scripts, dashboard, GitHub Actions workflow, CLAUDE.md, .claude/rules/

**Session 2 (first live run — another Claude agent):**
- Fixed CSS selector: `.table-groups` → `.groups_table` (the actual class on live Finviz)
- Fixed `wait_until="load"` → `"domcontentloaded"` (analytics scripts block full page load event)
- Added `ignore_https_errors=True` (needed for TLS-proxy in cloud env; harmless in Actions)
- Fixed `perf_day` always empty: Finviz's "Change" column = perf_day; added copy fallback
- Added `pytz` + `plotly` to requirements.txt (were missing, would break GitHub Actions)
- Added `na_option='bottom'` to all rank() calls per spec
- Added `COLLECT_RETRY_DELAY` env var to override retry delays for fast debugging
- Made session-notes.md and WORK_LOG.md tracked in Git (removed from .gitignore)

**First live data: 2026-06-09 — 11 sectors, 144 industries. Pipeline fully verified end-to-end.**

### Key technical discoveries
- `perf_day` and `change` are always identical (both come from Finviz's "Change" column)
- `rel_volume` is always NaN — not served for this custom group URL. Low priority.
- PEG and Volume columns exist on page but are intentionally skipped in HEADER_MAP
- `COLLECT_RETRY_DELAY=0` env var makes retries instant for debugging
- Dashboard all 4 tabs verified with Plotly charts rendering

### Current state
- **Data**: 1 day (2026-06-09). All 7d/14d/30d lookback deltas are NaN — expected, need more data.
- **Pipeline**: collect.py → compute_deltas.py → dashboard fully working.
- **Branch**: Everything on `claude/elegant-babbage-hlxnfy`. No `main` branch yet.
- **GitHub Actions cron**: NOT running — scheduled workflows only fire on the default branch.

### Blockers / user actions needed
1. **Create `main` branch or set `claude/elegant-babbage-hlxnfy` as default branch** — this is the only thing blocking automated daily collection. GitHub → Settings → Branches.
2. **Run collect.py intraday** on a trading day (10am, 1pm, 4pm, 6pm ET) to find when Finviz finalizes data.

### Next steps (prioritized)
1. [ ] Set default branch → cron activates automatically
2. [ ] Intraday probing to confirm 22:00 UTC cron is right timing
3. [ ] After ~7 days of data: first meaningful 7d deltas, start reviewing movers
4. [ ] After ~30 days: full delta set, build `notebooks/analysis.ipynb`
5. [ ] Dashboard polish: multi-select Time Series, rank_day in snapshot view, heatmap tab

---

## Session: [DATE] — [FOCUS/TITLE]

### What I was working on


### What I found / discovered
-

### Decisions made
-

### Current blockers
-

### Next steps
1. [ ]
