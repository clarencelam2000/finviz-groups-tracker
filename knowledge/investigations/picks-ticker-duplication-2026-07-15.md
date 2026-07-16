# Investigation: every Focus/Picks ticker showed a duplicated leading character (2026-07-15)

**Date investigated**: 2026-07-16
**Status**: Fixed (parser + guard shipped; corrupted date repaired)

## Symptom

PWA Focus tab showed every ticker with its leading character doubled — `C` (Citigroup) as
`CC`, `WFC` (Wells Fargo) as `WWFC`, `HSBC` as `HHSBC`, `BBVA` as `BBBVA`, `JPM` as `JJPM`,
`ING` as `IING`, `SAN` (Santander) as `SSAN`, `CM` (Canadian Imperial) as `CCM`, etc.

## Root cause analysis

1. Confirmed the corruption was in the data, not a display bug: `data/picks/picks.csv` and
   `data/picks/picks_latest.csv` themselves had the duplicated tickers in both the `ticker`
   and `Ticker` columns. `Company` and every other scraped column were unaffected.
2. Measured the duplicate-leading-character rate (`ticker[0] == ticker[1]`) per date across
   all captured picks dates. Real tickers occasionally start with a repeated letter (AA, EE,
   MMM, ...), giving a natural baseline of ~1-4%. `2026-07-15` measured **100%** (229/229
   rows) — an unambiguous corruption signature, not noise.
3. `git log` showed **no code changes** to `scripts/collect_picks.py`, `scripts/probe_picks.py`,
   `scripts/picks_metrics.py`, `scripts/picks_config.py`, or `.github/workflows/collect_picks.yml`
   around that date — ruling out a regression in our own code. The scrape ran unmodified on
   2026-07-13/14 (clean) and 2026-07-15 (100% corrupted), which points at an external change:
   Finviz altered the screener's Ticker `<td>` markup between those runs.
4. `scripts/probe_picks.py::_parse_table()` built every field (including Ticker) via
   `cell.get_text(strip=True)` on the whole `<td>` — concatenating **all** text nodes inside
   the cell. The doubling pattern (`real_ticker[0] + real_ticker`) is exactly what you'd get
   if Finviz's redesigned Ticker cell now renders a decorative element (e.g. a single-letter
   logo/avatar placeholder shown when a stock logo image is unavailable) immediately before
   the actual `<a>` ticker link, and `get_text()` swallowed both.
5. Could not fetch live Finviz HTML to see the exact new markup — this sandbox's outbound IP
   is Cloudflare-blocked (see root `CLAUDE.md` § Playwright notes) and no debug HTML was saved
   for a *successful* scrape (only on-parse-failure runs write `debug_html/`, and this run
   didn't fail — it silently produced wrong data). The anchor-text-based fix below does not
   depend on knowing the exact wrapper markup, only that the real ticker text lives inside the
   cell's `<a>` link, which has held true since this scraper was built.

## Fix

1. **`scripts/probe_picks.py::_parse_table()`** — for the `Ticker` column specifically, read
   the text from the cell's `<a>` tag (the actual ticker quote link) instead of the whole
   cell's `get_text()`. Falls back to full-cell text if no anchor is present. `collect_picks.py`
   imports `_parse_table` from here, so this one fix covers both the probe and the daily
   scrape.
2. **`scripts/collect_picks.py`** — added `ticker_dup_rate()` (pure) and a
   `TICKER_DUP_RATE_MAX = 0.25` guard in `main()`, run right after `build_run_rows()` and
   before `write_picks()` (same "abort before write" reasoning as the existing D14
   empty-scrape guard, since `write_picks` evicts the date's rows before appending). If more
   than 25% of a run's scraped tickers show the duplicated-leading-character signature, the
   run aborts with `exit(1)` instead of writing — this catches *any* future variant of this
   corruption class (not just the specific avatar-markup cause found here) before it reaches
   `picks.csv`.
3. **Data repair** — `data/picks/picks.csv` and `data/picks/picks_latest.csv` rows for
   `2026-07-15` had their `ticker`/`Ticker` columns de-duplicated (stripped exactly one
   leading character, which is the exact inverse of the observed corruption — validated
   against 100% of that date's rows matching the signature, so no genuine data was at risk of
   being mis-stripped).

## Why this wasn't caught earlier

- `tests/test_probe_picks.py`'s existing `_parse_table` fixtures used flat `<td>NVDA</td>`
  markup with no nested elements, so they never exercised a cell with extra text nodes.
- There was no data-level sanity check on scraped ticker values before writing — the
  empty-scrape guard (D14) only catches *zero* rows, not *wrong* rows.

## Prevention going forward

- New regression tests in `tests/test_probe_picks.py` (`TestParseTable`) model the
  avatar-markup shape and assert the anchor-text extraction.
- New `TestTickerDupRate` tests in `tests/test_collect_picks.py` cover the guard's baseline
  vs. corrupted-signature behavior.
- The `TICKER_DUP_RATE_MAX` guard will fire loudly (CI red, no write) on any future Finviz
  markup change with this signature, even if the anchor-text fix above turns out not to fully
  cover whatever Finviz changes next.
