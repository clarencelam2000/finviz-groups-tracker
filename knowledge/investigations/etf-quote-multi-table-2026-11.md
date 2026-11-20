# ETF quote page split into multiple snapshot tables (2026-11)

**Symptom:** every `collect.yml` (Daily Snapshot) run failed 2026-11-04 → 2026-11-19 with
`SPY parse yielded only 0/7 perf values`. Group snapshots were still committed, but
`compute_deltas.py` never ran (step skipped after collect exit 1). Cascade:
`collect_picks.yml` aborted on stale deltas (while still reporting success),
`collect_morning.py` / `--session pre_close` refused stale `picks_latest.csv`, AI analysis skipped.

**Root cause:** PR #425/#430 (merged 2026-11-03/04) scoped `parse_bench_quote` to
`soup.select_one(".snapshot-table2")`. The live ETF quote page has **six** `.snapshot-table2`
tables; the perf/price block (`Perf Week … Perf 10Y, Prev Close, Price, Change %`) is the
last. The old parser scanned every `<td>` on the page, so it never hit this.

Table layout seen 2026-11-20 (SPY and IWM identical):

| # | Labels |
|---|--------|
| 0 | Category, Sponsor, Fund Family, Index, Index Weighting, Active/Passive, Dividend TTM, Dividend Ex-Date, Dividend Gr. 3/5Y, Expense, Inverse/Leveraged, IPO |
| 1 | Asset Type, ETF Type, Bond Type, Average Maturity, Commodity Type, Quant Type, ESG Type, Dividend Type, Structure Type, Growth/Value, Market Cap, Option/Short |
| 2 | Tags ×7, Sector/Theme, Region, SMA20, SMA50, SMA200 |
| 3 | Return% 1Y/3Y/5Y/10Y/SI, Flows% 1M/3M/YTD/1Y/3Y/5Y, Trades |
| 4 | Total Holdings, AUM, NAV/sh, 52W High, 52W Low, Volatility, ATR (14), RSI (14), Beta, Rel Volume, Avg Volume, Volume |
| 5 | Perf Week, Perf Month, Perf Quarter, Perf Half Y, Perf YTD, Perf Year, Perf 3Y, Perf 5Y, Perf 10Y, Prev Close, Price, Change % |

**How it was verified:** the cloud sandbox can't reach Finviz (Cloudflare), so a throwaway
diagnostic step was pushed to the work branch's copy of `probe_picks.yml` and dispatched with
`ref=<branch>` (workflow_dispatch uses the branch's workflow file). It printed each perf label's
parent table and uploaded the raw HTML as an artifact. That artifact is the source of
`tests/fixtures/etf_quote_spy_2026-11.html` (snapshot tables only, trimmed).

**Fix:** scan every `.snapshot-table2` table (`soup.select(...)`), falling back to the whole page.

**Lesson:** the healthcheck dead-man's-switch on collect.yml went unpinged for 12 trading days,
and the picks job stayed green throughout. See SPRINT BENCH-QUOTE-FIX-2/3.
