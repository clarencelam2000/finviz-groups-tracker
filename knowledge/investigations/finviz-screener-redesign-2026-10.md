# Finviz screener redesign broke picks scrape (2026-10)

**Symptom:** `Daily Picks Scrape` failed every run from 2026-10-17 01:23 UTC on (last good
picks date 2026-10-16). Log: every group page hit `WARNING: table selector not found ... Timeout
30000ms`, then `ABORT: scraped N group(s) ... got 0 rows total — likely a Cloudflare block`.
The groups snapshot (`collect.py`, `/groups` page) kept working.

**Assumptions tested (Actions diagnostic run 39889165589, 2026-10-23):**
- *Cloudflare block?* No — HTTP 200, full page, real data.
- *Filter codes / sort changed?* No — `ind_` is rewritten server-side to `industry_`, but every
  variant (full picks URL, no sort, no 52w filter, single filters, ticker `t=` control) returns
  correct results (Semiconductors: `totalCount` 37).
- *Actual cause:* screener redesign. `/screener.ashx` 302s to `/screener/stocks`; the page has
  no `<table>` at all. Rows render as `div.fv-table_row[data-row-key]` in a virtualized canvas
  grid (only ~22 of 84 cells in the DOM). The full page of results is server-rendered as JSON in
  `<script type="application/json" data-ssr-props>` → `data.rows[i].{text,numbers}`,
  `data.totalCount`, `data.firstRow`; `settings.hasRedesignEnabled: true`. `r=` pagination works.

**Fix:** `scripts/probe_picks.py` — `_parse_table` keeps the legacy table path and falls back to
`_parse_ssr_json`, which maps JSON keys → legacy header labels (`SSR_COLUMN_MAP`) and renders
values in the legacy display format (verified against stored NVDA rows: market cap in $M →
`"5114.26B"` never `T`; avg volume `"117.71M"`; `"-4.40%"`; earnings `"Aug 26/a"`). Scrapers wait
on `SCREENER_READY_SELECTOR` (legacy table OR grid row). Shared by collect_picks, collect_morning
(morning + pre_close) and collect_held.

**Gotchas:** numbers in JSON are unrounded floats; `News Time` passes through as the new
relative text. If Finviz drops `data-ssr-props`, `_parse_table` returns `([], [])` and
collect_picks' empty-scrape guard aborts (no data wiped) — check `data.rows` in a saved page first.
