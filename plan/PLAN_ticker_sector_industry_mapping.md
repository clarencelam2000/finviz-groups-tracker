# Plan: Ticker → Sector/Industry Lookup

**Status:** Phase 0 complete — ready for implementation  
**Created:** 2026-06-13  
**Branch:** `claude/ticker-sector-industry-mapping-wbg5bd`  
**Base:** `origin/claude/elegant-babbage-hlxnfy`  
**Location:** `plan/PLAN_ticker_sector_industry_mapping.md` (committed to repo)

---

## Context & Motivation

The dashboard tracks Finviz group-level performance (11 sectors, ~150 industries) but has no connection between individual stocks and those groups. A user who owns AAPL, JPM, or XOM cannot currently answer: "Which sector/industry is this stock in, and how is that group performing today versus a month ago?"

This feature adds a **Ticker Lookup tab** to the dashboard. The user enters a stock symbol, the system maps it to a Finviz sector and industry, then surfaces the live performance data for those groups from the already-collected CSVs.

**Intended outcome:** Type a ticker → instantly see its Finviz sector + industry with current rank, momentum score, and performance across all tracked timeframes.

---

## State Tracking

Progress is tracked in this file. After completing each phase:
1. Check off completed tasks below
2. Commit the updated plan alongside the code changes
3. Each phase = one commit

**Phase checklist:**
- [x] Phase 0: Plan file written and pushed, draft PR open
- [ ] Phase 1: `requirements.txt` updated, `scripts/ticker_lookup.py` created + tested
- [ ] Phase 2: Dashboard tab added to `dashboard/app.py`
- [ ] Phase 3: End-to-end verification

---

## Scope of Changes

| File | Action |
|------|--------|
| `requirements.txt` | Add `yfinance>=0.2.18` |
| `scripts/ticker_lookup.py` | Create: pure lookup functions |
| `dashboard/app.py` | Modify: add Ticker Lookup tab (tab 8) |
| `tests/test_ticker_lookup.py` | Create: unit tests with mocked yfinance |
| `plan/PLAN_ticker_sector_industry_mapping.md` | This file — updated per phase |

---

## Design Decisions

### Decision 1: Data Source for Ticker → Sector/Industry

**Problem:** We need to map a user-supplied ticker (e.g., "AAPL") to a Finviz sector and industry. The sector/industry names in our CSVs come from Finviz's own taxonomy (e.g., "Consumer Cyclical", "Consumer Electronics"), so any mapping source must either use those exact names or be normalized to them.

**Chosen approach: `yfinance`**

`yfinance` uses Yahoo Finance's API. A single call — `yf.Ticker("AAPL").info` — returns `sector` and `industry` fields. Yahoo Finance's taxonomy overlaps heavily with Finviz's (both ultimately derive from GICS), with a small number of known naming differences handled by a hardcoded normalization dict (see below).

**Alternatives considered:**

1. **`finvizfinance` Python package** — scrapes Finviz's individual stock quote page (`finviz.com/quote.ashx?t=AAPL`). Returns exact Finviz sector/industry names, so no normalization needed.
   - *Assessment:* Finviz blocks bot-like HTTP requests (we already use Playwright for the groups scraper to work around this). `finvizfinance` uses plain `requests`, which is likely blocked on Finviz's end. Even if it worked occasionally, it is fragile and would silently fail in a cloud environment. Not reliable enough for a user-facing feature. Also not currently in `requirements.txt`, meaning another new dependency for a less-reliable source.
   - *Decision:* Rejected.

2. **NASDAQ stock screener CSV (static file)** — Download once from `nasdaqtrader.com`, parse all tickers → sector/industry into a static CSV committed to the repo. No network call at lookup time.
   - *Assessment:* NASDAQ's taxonomy (`SIC`-based) doesn't closely match Finviz's. The mapping would be imprecise and require significant manual curation. Additionally the file (100k+ rows) adds repo bloat and needs periodic refreshes. Works offline but brittle to sector reclassifications (e.g., Alphabet moved from "Technology" to "Communication Services" in 2018 GICS revision).
   - *Decision:* Rejected.

3. **`yfinance`** *(chosen)* — Uses Yahoo Finance API, works in cloud (no Playwright, no blocked host), returns sector + industry with ~1–2 second latency, no API key required. Known naming differences from Finviz are documented and handled deterministically.
   - *Assessment:* Some versions of yfinance (≥0.2.14) changed how sector/industry are returned. The implementation must gracefully handle both `.info['sector']` being present and the fallback via `sectorKey`. Fuzzy matching handles the industry name gap for cases not covered by the normalization dict.
   - *Decision:* Accepted.

---

### Decision 2: Industry Name Matching Strategy

**Problem:** Yahoo Finance industry names (e.g., "Drug Manufacturers—General") often but not always match Finviz exactly (e.g., "Drug Manufacturers - General"). A strict equality check would fail on minor punctuation differences.

**Chosen approach: Exact match → `difflib` fuzzy fallback**

1. Normalize both strings to lowercase + strip extra spaces
2. Try exact match against all industries in our snapshot data
3. On miss, use `difflib.get_close_matches(industry, finviz_industries, n=1, cutoff=0.5)`
4. Return `None` if fuzzy match score < 0.5 (no result shown rather than wrong result)

**Alternatives considered:**

1. **Hardcoded mapping dict for all industries** — Enumerate every known difference between Yahoo Finance and Finviz industry names (~150 industries).
   - *Assessment:* Exhaustive and brittle. Finviz periodically renames/merges industries; a hardcoded dict silently goes stale. `difflib` handles new cases automatically.
   - *Decision:* Rejected (except for known sector-level differences, which are fewer and more stable).

2. **`rapidfuzz` library** — Better fuzzy matching performance and algorithms than `difflib`.
   - *Assessment:* Overkill for ~150 strings; `difflib` is stdlib. No new dependency needed. `rapidfuzz` would be appropriate if matching thousands of rows, not a single lookup.
   - *Decision:* Rejected.

---

## Phase 0: Plan File (complete)

- [x] Write `plan/PLAN_ticker_sector_industry_mapping.md`
- [x] Commit and push to `claude/ticker-sector-industry-mapping-wbg5bd`
- [x] Open draft PR

---

## Phase 1: Core Lookup Module + Tests

### Task 1.1 — Add `yfinance` to `requirements.txt`

**Purpose/motivation:** `yfinance` is the chosen data source for ticker → sector/industry lookup. It must be installed in all environments (local, GitHub Actions, cloud dashboard host) for the feature to work.

**Detailed description:** Append `yfinance>=0.2.18` to `requirements.txt`. The `>=` lower bound is set to a version known to expose `sectorKey`/`industryKey` on `.info` as fallback. No upper bound is set to allow future patch releases.

**Acceptance criteria:**
- `yfinance` appears in `requirements.txt`
- `pip install -r requirements.txt` completes without error in a clean venv
- `python -c "import yfinance; print(yfinance.__version__)"` prints a version ≥ 0.2.18

**Alternatives:**
1. Pin to an exact version (e.g., `yfinance==0.2.18`) — more reproducible but requires manual bumps on security patches. Rejected: overkill for a data-fetch utility.
2. Add to `requirements-dev.txt` only — wrong; the dashboard needs it at runtime.

**Happy path:** `pip install -r requirements.txt` installs yfinance alongside existing packages.

**Edge cases:** If an existing package in `requirements.txt` pins a transitive dep that conflicts with yfinance, `pip` will error. Mitigation: add yfinance without upper bound to maximize compatibility.

**Dependencies:** None.

**Error/failure cases:** Version conflict with another package. Resolution: inspect `pip install -r requirements.txt` output; if conflict, add explicit yfinance version to requirements.

**Follow-up tasks:** If this is deployed via GitHub Actions, verify Actions workflow installs `requirements.txt` (current `collect.yml` and `generate_ai.yml` do `pip install -r requirements.txt` — confirmed compatible).

---

### Task 1.2 — Create `scripts/ticker_lookup.py`

**Purpose/motivation:** The ticker → sector/industry mapping logic must be in a standalone module, not embedded in `dashboard/app.py`. This enables unit testing without Streamlit, reuse from scripts or notebooks, and clean separation of concerns.

**Detailed description:**

Create `scripts/ticker_lookup.py` with the following functions:

```python
SECTOR_NORMALIZE: dict[str, str]
# Maps Yahoo Finance / GICS sector names → Finviz sector names.
# Full mapping:
#   "Financial Services" → "Financial"
#   "Financials"         → "Financial"
#   "Consumer Discretionary" → "Consumer Cyclical"
#   "Consumer Staples"   → "Consumer Defensive"
#   "Health Care"        → "Healthcare"
#   "Information Technology" → "Technology"
#   "Materials"          → "Basic Materials"

def normalize_sector(yahoo_sector: str) -> str | None:
    """
    Map Yahoo Finance sector name to Finviz sector name.
    Returns the Finviz name if known, or yahoo_sector unchanged if it already
    matches a Finviz sector name (case-insensitive), or None if unrecognizable.
    """

def match_industry(yahoo_industry: str, finviz_industries: list[str]) -> tuple[str | None, float]:
    """
    Find the closest Finviz industry name for a Yahoo Finance industry name.
    Returns (matched_name, score) where score is 0.0–1.0.
    Returns (None, 0.0) if no match above cutoff=0.5 found.
    """

def lookup_ticker(
    symbol: str,
    finviz_sector_names: list[str],
    finviz_industry_names: list[str],
) -> dict:
    """
    Look up a ticker's sector and industry via yfinance, then map to Finviz names.

    Returns dict with keys:
        symbol          str   — uppercased input
        company_name    str   — long company name or ""
        yf_sector       str   — sector as returned by Yahoo Finance, or ""
        yf_industry     str   — industry as returned by Yahoo Finance, or ""
        matched_sector  str | None — Finviz sector name, None if no match
        matched_industry str | None — Finviz industry name, None if no match
        industry_match_score float — 0.0–1.0 confidence of industry match
        error           str   — non-empty if yfinance raised an exception
    """
```

**Key implementation notes:**
- Call `yf.Ticker(symbol).info` inside a `try/except` to catch network errors, invalid tickers, and rate limits
- Check both `info.get('sector')` and `info.get('sectorKey')` as fallbacks
- `finviz_sector_names` is the caller's responsibility (passed in from dashboard, not loaded inside the function) — this keeps the function pure and testable
- `difflib.get_close_matches` with `n=1, cutoff=0.5` for industry matching

**Acceptance criteria:**
- `lookup_ticker("AAPL", sectors, industries)` returns `matched_sector="Technology"` and `matched_industry="Consumer Electronics"` (or nearest match)
- `lookup_ticker("JPM", sectors, industries)` returns `matched_sector="Financial"` (normalized from Yahoo's "Financial Services")
- `lookup_ticker("FAKE123XYZ", sectors, industries)` returns `error` key with non-empty string, no exception raised
- `lookup_ticker("XOM", sectors, industries)` returns `matched_sector="Energy"`
- All 8 unit tests in Task 1.3 pass

**Alternatives:**
1. Embed the logic directly in `dashboard/app.py` — faster to write but untestable and creates a 700+ line app file.
2. Use a class-based API (`TickerLookup` object) — unnecessary complexity for what are essentially 3 pure functions.

**Happy path:** `yf.Ticker("AAPL").info` returns `{'sector': 'Technology', 'industry': 'Consumer Electronics', 'longName': 'Apple Inc.'}`. `normalize_sector("Technology")` returns `"Technology"` (passthrough). `match_industry("Consumer Electronics", finviz_industries)` returns exact match.

**Edge cases:**
- Ticker entered in lowercase (e.g., "aapl") — uppercase before calling yfinance
- yfinance returns empty string for `sector` or `industry` — return `None` for matched fields, not an error
- yfinance returns sector not in SECTOR_NORMALIZE and not in Finviz sectors — log and return `None`
- Industry match score between 0.5–0.7 — return the match but expose the score so the dashboard can show a confidence warning
- ETFs and index funds (SPY, QQQ) — yfinance returns `sector=""` for ETFs; handled gracefully (matched_sector=None, not an error)

**Dependencies:** Task 1.1 (yfinance installed).

**Error/failure cases:**
- Network timeout: `yf.Ticker.info` may hang. Add `timeout` via environment variable or just let it fail naturally — yfinance has its own internal timeout.
- Rate limit: Yahoo Finance occasionally throttles. Return error message, not exception.
- Invalid ticker: yfinance returns `info = {}`. Detect via `info.get('symbol')` being None or absent.

**Follow-up tasks:**
- Backlog: Cache lookup results in `st.cache_data` so repeated lookups don't hit Yahoo Finance on every re-render.
- Backlog: Add batch-lookup function for CSV upload (many tickers at once).

---

### Task 1.3 — Create `tests/test_ticker_lookup.py`

**Purpose/motivation:** The lookup functions must be tested with mocked yfinance to avoid network calls in CI, verify normalization correctness, and catch regressions when yfinance changes its API.

**Detailed description:**

Create `tests/test_ticker_lookup.py` with these 8 tests:

| Test | What it verifies |
|------|-----------------|
| `test_normalize_sector_known_mappings` | All 7 entries in SECTOR_NORMALIZE dict return correct Finviz name |
| `test_normalize_sector_passthrough` | Names already in Finviz vocabulary (e.g., "Technology") pass through unchanged |
| `test_normalize_sector_unknown` | Completely unknown string returns `None` |
| `test_match_industry_exact` | "Consumer Electronics" against a list containing "Consumer Electronics" → exact match, score=1.0 |
| `test_match_industry_fuzzy` | "Drug Manufacturers—General" (em dash) close enough to "Drug Manufacturers - General" → match |
| `test_match_industry_no_match` | "XYZZY Nonsense Corp" returns `(None, 0.0)` |
| `test_lookup_ticker_success` | Mock `yf.Ticker("AAPL").info` returning sector/industry; verify full output dict shape |
| `test_lookup_ticker_unknown_symbol` | Mock `yf.Ticker.info` raising `Exception`; verify `error` key present, no crash |
| `test_lookup_ticker_empty_sector` | Mock returns `{'sector': '', 'industry': ''}` (ETF case); verify `matched_sector=None`, no error |

Use `pytest-mock`'s `mocker.patch` to mock `yfinance.Ticker`.

**Acceptance criteria:**
- `python3 -m pytest tests/test_ticker_lookup.py -v` — all 9 tests pass
- `python3 -m pytest tests/ -q` — full suite still passes (no regressions)
- Tests run without network access (all yfinance calls mocked)

**Alternatives:**
1. Integration tests hitting real Yahoo Finance — validates actual API but is slow (2–5s per test), flaky (rate limits), and not suitable for CI.
2. No tests — violates project rules in `branch-commit-discipline.md`.

**Happy path:** All mocks configured, 9 tests pass in < 1 second.

**Edge cases:** `pytest-mock` is already in `requirements-dev.txt` — no additional dependency needed.

**Dependencies:** Task 1.2 (module to test exists).

**Error/failure cases:** If `yfinance` import fails at test collection time (package not installed), pytest will error with `ModuleNotFoundError`. Fix: run `pip install -r requirements.txt` first.

**Follow-up tasks:** None.

---

## Phase 2: Dashboard Tab

### Task 2.1 — Add Ticker Lookup tab to `dashboard/app.py`

**Purpose/motivation:** The lookup logic is only useful if it's surfaced in the UI. The Streamlit dashboard is the primary user interface. Adding a dedicated tab keeps the feature discoverable without disrupting the existing 7 tabs.

**Detailed description:**

**Line 176** — change tabs declaration from 7 to 8:
```python
# Before:
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(
    ["Snapshot", "Top Movers", "Time Series", "Momentum", "Heatmap", "Strength", "AI Insights"]
)

# After:
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs(
    ["Snapshot", "Top Movers", "Time Series", "Momentum", "Heatmap", "Strength", "AI Insights", "Ticker Lookup"]
)
```

**Import block** — add at top of file:
```python
import sys
sys.path.insert(0, str(BASE_DIR / "scripts"))
from ticker_lookup import lookup_ticker
```

**Tab 8 body** (after `with tab7:` block):
```python
with tab8:
    st.subheader("Ticker Lookup")
    st.caption("Enter a stock ticker to find its Finviz sector and industry, then see live performance data.")

    col_input, col_btn = st.columns([3, 1])
    with col_input:
        ticker_input = st.text_input("Ticker symbol", placeholder="e.g. AAPL, JPM, XOM", key="ticker_input")
    with col_btn:
        st.write("")  # vertical alignment spacer
        lookup_clicked = st.button("Look up", type="primary")

    if lookup_clicked and ticker_input.strip():
        symbol = ticker_input.strip().upper()

        # Load sector + industry names from full (unfiltered) snapshot data
        sectors_snap = load_snapshots("Sectors")
        industries_snap = load_snapshots("Industries")
        sector_names = sorted(sectors_snap["name"].dropna().unique().tolist()) if not sectors_snap.empty else []
        industry_names = sorted(industries_snap["name"].dropna().unique().tolist()) if not industries_snap.empty else []

        with st.spinner(f"Looking up {symbol}..."):
            result = lookup_ticker(symbol, sector_names, industry_names)

        if result.get("error"):
            st.error(f"Could not look up {symbol}: {result['error']}")
        else:
            # Company header
            company = result.get("company_name") or symbol
            st.markdown(f"### {company} ({symbol})")

            col_sec, col_ind = st.columns(2)

            # Sector card
            with col_sec:
                matched_sector = result.get("matched_sector")
                yf_sector = result.get("yf_sector", "")
                st.markdown("**Sector**")
                if not matched_sector:
                    st.warning(f"Sector '{yf_sector}' not matched in Finviz data.")
                else:
                    if yf_sector != matched_sector:
                        st.caption(f"Yahoo Finance: '{yf_sector}' → Finviz: '{matched_sector}'")
                    else:
                        st.caption(f"Finviz sector: {matched_sector}")

                    # Pull latest sector metrics
                    if not sectors_snap.empty:
                        latest_sec_date = sectors_snap["date"].max()
                        sec_row = sectors_snap[
                            (sectors_snap["date"] == latest_sec_date) &
                            (sectors_snap["name"] == matched_sector)
                        ]
                        if not sec_row.empty:
                            r = sec_row.iloc[0]
                            st.metric("Perf Day", f"{r.get('perf_day', float('nan')):.2f}%" if pd.notna(r.get("perf_day")) else "—")
                            sec_perf_cols = ["perf_week", "perf_month", "perf_ytd"]
                            perf_data = {c: r.get(c) for c in sec_perf_cols if pd.notna(r.get(c))}
                            if perf_data:
                                st.dataframe(
                                    pd.DataFrame([perf_data]).rename(columns={
                                        "perf_week": "Week %", "perf_month": "Month %", "perf_ytd": "YTD %"
                                    }),
                                    use_container_width=True, hide_index=True,
                                )
                        # Pull rank + momentum from deltas
                        sectors_delta = load_deltas("Sectors")
                        if not sectors_delta.empty:
                            latest_delta_date = sectors_delta["date"].max()
                            sec_delta_row = sectors_delta[
                                (sectors_delta["date"] == latest_delta_date) &
                                (sectors_delta["name"] == matched_sector)
                            ]
                            if not sec_delta_row.empty:
                                d = sec_delta_row.iloc[0]
                                rank_ytd = d.get("rank_ytd")
                                mom = d.get("momentum_score")
                                metrics_row = {}
                                if pd.notna(rank_ytd):
                                    metrics_row["YTD Rank"] = int(rank_ytd)
                                if pd.notna(mom):
                                    metrics_row["Momentum"] = f"{mom:.2f}"
                                if metrics_row:
                                    st.dataframe(
                                        pd.DataFrame([metrics_row]),
                                        use_container_width=True, hide_index=True,
                                    )

            # Industry card (same pattern as sector card)
            with col_ind:
                matched_industry = result.get("matched_industry")
                yf_industry = result.get("yf_industry", "")
                match_score = result.get("industry_match_score", 1.0)
                st.markdown("**Industry**")
                if not matched_industry:
                    st.warning(f"Industry '{yf_industry}' not matched in Finviz data.")
                else:
                    label = f"Finviz industry: {matched_industry}"
                    if match_score < 1.0:
                        label += f" (fuzzy match: {match_score:.0%})"
                    st.caption(label)

                    if not industries_snap.empty:
                        latest_ind_date = industries_snap["date"].max()
                        ind_row = industries_snap[
                            (industries_snap["date"] == latest_ind_date) &
                            (industries_snap["name"] == matched_industry)
                        ]
                        if not ind_row.empty:
                            r = ind_row.iloc[0]
                            st.metric("Perf Day", f"{r.get('perf_day', float('nan')):.2f}%" if pd.notna(r.get("perf_day")) else "—")
                            ind_perf_cols = ["perf_week", "perf_month", "perf_ytd"]
                            perf_data = {c: r.get(c) for c in ind_perf_cols if pd.notna(r.get(c))}
                            if perf_data:
                                st.dataframe(
                                    pd.DataFrame([perf_data]).rename(columns={
                                        "perf_week": "Week %", "perf_month": "Month %", "perf_ytd": "YTD %"
                                    }),
                                    use_container_width=True, hide_index=True,
                                )
                        industries_delta = load_deltas("Industries")
                        if not industries_delta.empty:
                            latest_delta_date = industries_delta["date"].max()
                            ind_delta_row = industries_delta[
                                (industries_delta["date"] == latest_delta_date) &
                                (industries_delta["name"] == matched_industry)
                            ]
                            if not ind_delta_row.empty:
                                d = ind_delta_row.iloc[0]
                                rank_ytd = d.get("rank_ytd")
                                mom = d.get("momentum_score")
                                metrics_row = {}
                                if pd.notna(rank_ytd):
                                    metrics_row["YTD Rank"] = int(rank_ytd)
                                if pd.notna(mom):
                                    metrics_row["Momentum"] = f"{mom:.2f}"
                                if metrics_row:
                                    st.dataframe(
                                        pd.DataFrame([metrics_row]),
                                        use_container_width=True, hide_index=True,
                                    )
    elif lookup_clicked:
        st.warning("Please enter a ticker symbol.")
```

**Acceptance criteria:**
- `streamlit run dashboard/app.py` shows 8 tabs; "Ticker Lookup" is the last
- Entering "AAPL" shows sector="Technology" and industry="Consumer Electronics" (or nearest match) with performance metrics
- Entering "JPM" shows sector="Financial" (normalized from Yahoo's "Financial Services")
- Entering "FAKE123XYZ" shows an error message without crashing the app
- Entering "" and clicking Look up shows a warning "Please enter a ticker symbol"
- No regression on any of tabs 1–7

**Alternatives:**
1. Add to the sidebar instead of a new tab — would require sector/industry lookup to be visible at all times, cluttering the sidebar. Tab is better for optional contextual use.
2. Separate Streamlit page (`pages/` directory) — more isolated but requires navigation and doesn't share the sidebar filter state. Overkill for a single-screen feature.

**Happy path:** User enters "AAPL", clicks "Look up", sees Apple Inc. with Technology sector + Consumer Electronics industry cards showing today's perf_day/week/month/ytd + rank + momentum.

**Edge cases:**
- No data in CSVs yet (sector_names / industry_names empty) — show lookup result with "No performance data available yet" message instead of metrics
- Ticker entered with spaces or mixed case ("  aapl  ") — strip + uppercase before lookup
- Non-US ticker (e.g., "0700.HK") — yfinance may return a sector not in Finviz; matched_sector=None; show warning with the raw Yahoo Finance sector
- ETFs (SPY, QQQ) — yfinance returns empty sector; matched_sector=None; show "No sector data available from Yahoo Finance for SPY (ETFs are not classified by sector)"
- Dashboard sidebar filters sector/industry separately — the Ticker Lookup tab uses `load_snapshots("Sectors")` and `load_snapshots("Industries")` directly, bypassing the sidebar group_label filter intentionally (always shows both)

**Dependencies:** Task 1.2 (lookup module), Task 1.3 (tests pass).

**Error/failure cases:**
- yfinance network timeout in dashboard: `st.spinner` will appear frozen. Add a user-visible note: "This may take a few seconds — Yahoo Finance is queried live."
- `load_snapshots` returns empty DataFrame (no data collected yet): gracefully show "—" for all metrics.

**Follow-up tasks:**
- Backlog: Add `st.cache_data` wrapper around `lookup_ticker` with TTL=3600 so repeated lookups of the same ticker don't re-hit Yahoo Finance.
- Backlog: "View in Time Series" button that pre-populates the Time Series tab with the matched sector/industry selected.

---

## Phase 3: Verification

All verification steps are **mandatory** before marking this plan complete.

### Verification 3.1 — Unit tests pass

```bash
python3 -m pytest tests/ -q
```

**Expected output:** All tests pass. Zero failures. `test_ticker_lookup.py` shows 9 items passing.

**Observable:** Exit code 0. Test summary line shows `passed` for test_ticker_lookup.py items.

### Verification 3.2 — Module smoke test (no network)

```bash
python3 -c "
from scripts.ticker_lookup import normalize_sector, match_industry, SECTOR_NORMALIZE
# Verify all 7 normalization mappings
assert normalize_sector('Financial Services') == 'Financial'
assert normalize_sector('Consumer Discretionary') == 'Consumer Cyclical'
assert normalize_sector('Technology') == 'Technology'  # passthrough
assert normalize_sector('UNKNOWN_SECTOR_XYZ') is None
# Verify industry fuzzy match
result, score = match_industry('Consumer Electronics', ['Consumer Electronics', 'Software - Application'])
assert result == 'Consumer Electronics' and score == 1.0
print('smoke test passed')
"
```

**Observable:** Prints `smoke test passed` with exit code 0.

### Verification 3.3 — Dashboard loads with 8 tabs

```bash
streamlit run dashboard/app.py --server.headless true &
sleep 3
curl -s http://localhost:8501 | grep -c "Ticker Lookup"
```

**Expected output:** `1` (the tab label appears in the page source). Kill the streamlit process after.

### Verification 3.4 — Live ticker lookup (requires network)

```bash
python3 -c "
from scripts.ticker_lookup import lookup_ticker
sectors = ['Basic Materials', 'Communication Services', 'Consumer Cyclical',
           'Consumer Defensive', 'Energy', 'Financial', 'Healthcare',
           'Industrials', 'Real Estate', 'Technology', 'Utilities']
# Load actual industry names from data
import pandas as pd
try:
    industries = pd.read_csv('data/industries/snapshots.csv')['name'].dropna().unique().tolist()
except FileNotFoundError:
    industries = ['Consumer Electronics', 'Drug Manufacturers - General', 'Banks - Regional']

r = lookup_ticker('AAPL', sectors, industries)
print('AAPL:', r)
assert r.get('matched_sector') == 'Technology', f'Expected Technology, got {r.get(\"matched_sector\")}'

r2 = lookup_ticker('JPM', sectors, industries)
print('JPM:', r2)
assert r2.get('matched_sector') == 'Financial', f'Expected Financial, got {r2.get(\"matched_sector\")}'

r3 = lookup_ticker('FAKE123XYZ', sectors, industries)
print('FAKE123XYZ:', r3)
assert r3.get('error'), 'Expected error for invalid ticker'

print('all live checks passed')
"
```

**Observable:** Prints `all live checks passed`. If yfinance is unavailable (network blocked in cloud), this step is skipped — note it explicitly in the PR description.

### Verification 3.5 — No regression on existing tests

```bash
python3 -m pytest tests/ -q --tb=short
```

**Expected output:** All pre-existing tests (test_collect_parsing, test_compute_deltas, test_momentum, test_generate_ai) still pass. Zero new failures.

---

## Rollback Strategy

If anything goes wrong post-merge:
- `scripts/ticker_lookup.py` and `tests/test_ticker_lookup.py` are new files — delete them with no side effects
- `dashboard/app.py` change is additive (new tab) — revert the two modified lines (tab declaration + import + tab8 block) to restore the 7-tab layout
- `requirements.txt` — remove `yfinance>=0.2.18` line
- yfinance is never called by any automated pipeline (GitHub Actions), only by the interactive dashboard — no risk to data collection

---

## Backlog / Follow-up Tasks

These are discovered during planning but out of scope for this branch:

1. **Cache ticker lookups in dashboard** — wrap `lookup_ticker` in `st.cache_data(ttl=3600)` to avoid repeated Yahoo Finance calls within a session. Simple 2-line change.
2. **"View in Time Series" deep link** — after a successful lookup, show a button that pre-selects the matched sector/industry in the Time Series tab. Requires Streamlit session state.
3. **Batch ticker CSV upload** — let users upload a CSV of tickers and get back a table of sector/industry + performance for all of them. Useful for portfolio analysis.
4. **Sector-to-industry drill-down** — on the Snapshot tab, make sector names clickable to filter the Industries view to only that sector's industries.
5. **Watchlist persistence** — save recently looked-up tickers to `st.session_state` so they persist across tab switches within a session.
