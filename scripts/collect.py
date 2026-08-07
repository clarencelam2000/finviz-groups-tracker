"""
collect.py — Fetch Finviz Groups data (sectors + industries) using Playwright
and append to append-only snapshot CSVs. Also scrapes SPY benchmark data.
"""

import csv
import os
import sys
import time
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

import pytz
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
from delta_config import BENCH_CSV_COLUMNS, BENCH_PERF_COLS, SNAPSHOT_COLS

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"

URLS = {
    "sector": (
        "https://finviz.com/groups?g=sector&v=152&o=name"
        "&c=0,1,2,3,4,5,15,16,17,18,19,20,22,24,25,26"
    ),
    "industry": (
        "https://finviz.com/groups?g=industry&v=152&o=name"
        "&c=0,1,2,3,4,5,15,16,17,18,19,20,22,24,25,26"
    ),
}

CSV_COLUMNS = SNAPSHOT_COLS

# Map Finviz header text → internal column name (None = skip)
HEADER_MAP = {
    "No.": None,
    "Name": "name",
    "Stocks": "stocks",
    "Market Cap": "market_cap",
    "P/E": "pe",
    "Fwd P/E": "fwd_pe",
    "PEG": None,
    "Perf Day": "perf_day",
    "Perf Week": "perf_week",
    "Perf Month": "perf_month",
    "Perf Quart": "perf_quarter",
    "Perf Quarter": "perf_quarter",
    "Perf Half": "perf_half",
    "Perf Year": "perf_year",
    "Perf YTD": "perf_ytd",
    "Avg Volume": "avg_volume",
    "Rel Volume": "rel_volume",
    "Volume": None,
    "Change": "change",
    "Change %": "change",
}

PERF_COLS = {
    "perf_day", "perf_week", "perf_month", "perf_quarter",
    "perf_half", "perf_year", "perf_ytd", "change",
}

# ---------------------------------------------------------------------------
# Benchmark (SPY) config
# ---------------------------------------------------------------------------

# Finviz SPY quote page. The &p=d parameter selects the daily chart view.
# NOTE: this URL is Cloudflare-gated. collect_spy() requires GitHub Actions
# (Azure IPs) or a local machine — it will 403 from Google Cloud IPs.
SPY_URL = "https://finviz.com/stock?t=SPY&p=d"

# BENCH_CSV_COLUMNS and BENCH_PERF_COLS are imported from delta_config above.

# Map Finviz quote-page performance label text → internal column name.
# Multiple label forms accepted for resilience to Finviz wording changes.
SPY_LABEL_MAP = {
    "Change": "perf_day",
    "Change %": "perf_day",
    "Perf Day": "perf_day",
    "Perf Week": "perf_week",
    "Perf Month": "perf_month",
    "Perf Quart": "perf_quarter",
    "Perf Quarter": "perf_quarter",
    "Perf Half Y": "perf_half",
    "Perf Half": "perf_half",
    "Perf Year": "perf_year",
    "Perf YTD": "perf_ytd",
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# Value parsers
# ---------------------------------------------------------------------------

def parse_perf(val: str):
    """Return float percentage (e.g. '-1.23') or None."""
    v = val.strip().rstrip("%")
    if v in ("", "-", "N/A"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def parse_market_cap(val: str):
    """Return float in billions or None."""
    v = val.strip()
    if v in ("", "-", "N/A"):
        return None
    multipliers = {"T": 1000.0, "B": 1.0, "M": 0.001, "K": 0.000001}
    for suffix, mult in multipliers.items():
        if v.endswith(suffix):
            try:
                return float(v[:-1]) * mult
            except ValueError:
                return None
    try:
        return float(v)
    except ValueError:
        return None


def parse_avg_volume(val: str):
    """Return integer volume or None."""
    v = val.strip()
    if v in ("", "-", "N/A"):
        return None
    multipliers = {"B": 1_000_000_000, "M": 1_000_000, "K": 1_000}
    for suffix, mult in multipliers.items():
        if v.endswith(suffix):
            try:
                return int(float(v[:-1]) * mult)
            except ValueError:
                return None
    try:
        return int(float(v))
    except ValueError:
        return None


def parse_int(val: str):
    v = val.strip()
    if v in ("", "-", "N/A"):
        return None
    try:
        return int(v.replace(",", ""))
    except ValueError:
        return None


def parse_float(val: str):
    v = val.strip()
    if v in ("", "-", "N/A"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def fetch_html(url: str, wait_selector: str = ".groups_table") -> str:
    """Fetch page HTML using Playwright with retry logic.

    wait_selector: CSS selector that must appear before capturing HTML.
    Groups pages use the default '.groups_table'; the SPY quote page uses
    '.snapshot-table2'. If the selector is never found, the attempt raises
    a timeout and retry logic fires.
    """
    _rd = os.environ.get("COLLECT_RETRY_DELAY")
    delays = [int(_rd)] * 3 if _rd is not None else [30, 60, 120]
    last_exc = None
    for attempt in range(3):
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent=USER_AGENT,
                    ignore_https_errors=True,
                )
                page = context.new_page()
                print(f"  Fetching {url} (attempt {attempt + 1}/3) …")
                page.goto(url, timeout=60_000, wait_until="domcontentloaded")
                page.wait_for_selector(wait_selector, timeout=30_000)
                html = page.content()
                browser.close()
                return html
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                wait = delays[attempt]
                print(f"  Attempt {attempt + 1} failed: {exc}. Retrying in {wait}s …")
                time.sleep(wait)
    raise RuntimeError(f"All 3 fetch attempts failed for {url}") from last_exc


def parse_table(html: str, group_type: str, snapshot_date: str, collected_at: str):
    """Parse the .table-groups HTML table and return list of row dicts."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one(".groups_table")
    if table is None:
        raise ValueError("Could not find .groups_table in HTML")

    rows = table.find_all("tr")
    if not rows:
        return []

    # Parse header
    header_cells = rows[0].find_all(["th", "td"])
    col_mapping = []  # list of internal column names (None = skip)
    unknown_headers = []
    for cell in header_cells:
        text = cell.get_text(strip=True)
        mapped = HEADER_MAP.get(text, None)
        if text and text not in HEADER_MAP:
            unknown_headers.append(text)
        col_mapping.append(mapped)
    if unknown_headers:
        print(f"  [warn] Unknown headers (will be dropped): {unknown_headers}", file=sys.stderr)

    records = []
    for row in rows[1:]:
        cells = row.find_all(["td", "th"])
        if not cells:
            continue

        raw = {}
        for idx, cell in enumerate(cells):
            if idx >= len(col_mapping):
                break
            col = col_mapping[idx]
            if col is None:
                continue
            raw[col] = cell.get_text(strip=True)

        if "name" not in raw or not raw["name"]:
            continue

        # Normalize values
        rec = {
            "date": snapshot_date,
            "collected_at": collected_at,
            "group_type": group_type,
            "name": raw.get("name", ""),
            "stocks": parse_int(raw.get("stocks", "")),
            "market_cap": parse_market_cap(raw.get("market_cap", "")),
            "pe": parse_float(raw.get("pe", "")),
            "fwd_pe": parse_float(raw.get("fwd_pe", "")),
        }
        for col in PERF_COLS:
            rec[col] = parse_perf(raw.get(col, ""))

        rec["avg_volume"] = parse_avg_volume(raw.get("avg_volume", ""))
        rec["rel_volume"] = parse_float(raw.get("rel_volume", ""))

        # Finviz shows "Change" (not "Perf Day") for the daily metric; keep both in sync
        if rec.get("perf_day") is None and rec.get("change") is not None:
            rec["perf_day"] = rec["change"]

        records.append(rec)

    return records


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def load_existing_keys(csv_path: Path) -> set:
    """Return set of (date, name) tuples already in the CSV."""
    keys = set()
    if not csv_path.exists():
        return keys
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            keys.add((row.get("date", ""), row.get("name", "")))
    return keys


def evict_today_rows(csv_path: Path, date_str: str) -> int:
    """Remove all rows for date_str and rewrite atomically. Returns count removed."""
    if not csv_path.exists():
        return 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        all_rows = list(reader)
    kept = [r for r in all_rows if r.get("date") != date_str]
    evicted = len(all_rows) - len(kept)
    if evicted == 0:
        return 0
    tmp = csv_path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in kept:
            writer.writerow({col: row.get(col, "") for col in CSV_COLUMNS})
    tmp.replace(csv_path)
    return evicted


def ensure_csv(csv_path: Path):
    """Create CSV with header row if it doesn't exist."""
    if not csv_path.exists():
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writeheader()
        print(f"  Created {csv_path}")


def append_records(csv_path: Path, records: list, existing_keys: set):
    """Append new records (not in existing_keys) to CSV."""
    new_rows = []
    for rec in records:
        key = (rec["date"], rec["name"])
        if key not in existing_keys:
            new_rows.append(rec)
            existing_keys.add(key)

    if not new_rows:
        print(f"  No new rows to append (all {len(records)} already present).")
        return 0

    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        for row in new_rows:
            writer.writerow({col: row.get(col, "") for col in CSV_COLUMNS})

    print(f"  Appended {len(new_rows)} rows to {csv_path}")
    return len(new_rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# NYSE full-day market holidays (observed dates). Half-days (e.g. the day after
# Thanksgiving) still trade and are deliberately excluded. Extend this table as
# new years are scheduled — a year that is absent simply gets weekend-only
# handling for that year (holidays would then be stamped under their own date).
NYSE_HOLIDAYS = frozenset({
    # 2025
    "2025-01-01", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26",
    "2025-06-19", "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25",
    # 2026
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    # 2027
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
    "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
    # 2028 (Note: New Year's Day is observed on 2027-12-31, so it is absent here)
    "2028-01-17", "2028-02-21", "2028-04-14", "2028-05-29", "2028-06-19", 
    "2028-07-04", "2028-09-04", "2028-11-23", "2028-12-25",
    # 2029
    "2029-01-01", "2029-01-15", "2029-02-19", "2029-03-30", "2029-05-28", 
    "2029-06-19", "2029-07-04", "2029-09-03", "2029-11-22", "2029-12-25",
})

NYSE_HOLIDAY_YEARS = frozenset(int(d[:4]) for d in NYSE_HOLIDAYS)


def _is_trading_day(d: date) -> bool:
    """True if d is a weekday and not a known NYSE full-day holiday."""
    if d.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        return False
    return d.strftime("%Y-%m-%d") not in NYSE_HOLIDAYS


def trading_date(now_et: datetime) -> str:
    """Return the trading date for a given ET datetime.

    Three adjustments keep the stored date aligned with the session whose data
    Finviz is actually showing:

    1. Before 9 AM ET the market hasn't opened and Finviz still shows the prior
       session's close, so step back one calendar day.
    2. Weekends are closed, so a Saturday/Sunday run (or a Monday pre-open run,
       which step 1 lands on Sunday) rolls back to the most recent trading day.
    3. NYSE holidays are closed too, so a holiday run (or the morning after one)
       rolls back across the holiday to the prior trading day.

    The combined effect: the returned date is always a real trading day, so no
    row is ever stamped with a weekend or holiday date no matter when collection
    runs (scheduled cron drift, manual dispatch, or a holiday run). On those days
    Finviz is still showing the prior session's close, which is exactly what we
    store under the prior trading day.

    Caveat: the holiday table (NYSE_HOLIDAYS) is hardcoded. For a year not yet in
    the table, only the weekend rule applies — a holiday that year would be
    stamped under its own date until the table is extended.
    """
    d = now_et.date()
    if now_et.hour < 9:
        d = d - timedelta(days=1)
    while not _is_trading_day(d):
        d = d - timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def parse_spy_quote(html: str, snapshot_date: str, collected_at: str) -> dict:
    """Parse Finviz SPY quote page HTML and return a benchmark row dict.

    Scans all <td> elements for known performance labels; the next sibling <td>
    holds the value. Robust to different table structures on the quote page.
    Any missing label leaves the corresponding column as None.
    """
    soup = BeautifulSoup(html, "lxml")

    rec: dict = {
        "date": snapshot_date,
        "collected_at": collected_at,
        "ticker": "SPY",
        "perf_day": None,
        "perf_week": None,
        "perf_month": None,
        "perf_quarter": None,
        "perf_half": None,
        "perf_year": None,
        "perf_ytd": None,
    }

    for td in soup.find_all("td"):
        label = td.get_text(strip=True)
        if label in SPY_LABEL_MAP:
            col = SPY_LABEL_MAP[label]
            value_td = td.find_next_sibling("td")
            if value_td:
                rec[col] = parse_perf(value_td.get_text(strip=True))

    return rec


def _evict_bench_row(csv_path: Path, date_str: str) -> int:
    """Remove the SPY row for date_str from benchmark CSV (atomic rewrite).

    Returns the number of rows removed (0 or 1 in normal operation).
    """
    if not csv_path.exists():
        return 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        all_rows = list(reader)
    kept = [r for r in all_rows if r.get("date") != date_str]
    evicted = len(all_rows) - len(kept)
    if evicted == 0:
        return 0
    tmp = csv_path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=BENCH_CSV_COLUMNS)
        writer.writeheader()
        for row in kept:
            writer.writerow({col: row.get(col, "") for col in BENCH_CSV_COLUMNS})
    tmp.replace(csv_path)
    return evicted


def collect_spy(bench_path: Path = None):
    """Fetch SPY quote page and append/overwrite in data/benchmark/snapshots.csv.

    Last-write-wins per date: a later run on the same trading day replaces the
    earlier one. If the scrape fails after all retries, raises RuntimeError —
    the caller is responsible for logging the warning and exiting non-zero.

    bench_path: override for the benchmark CSV path (default: data/benchmark/snapshots.csv).
    Exposed for testability — tests pass a tmp_path here.
    """
    if bench_path is None:
        bench_path = DATA_DIR / "benchmark" / "snapshots.csv"

    eastern = pytz.timezone("US/Eastern")
    now_utc = datetime.now(timezone.utc)
    snapshot_date = trading_date(datetime.now(eastern))
    collected_at = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    if not bench_path.exists():
        bench_path.parent.mkdir(parents=True, exist_ok=True)
        with open(bench_path, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=BENCH_CSV_COLUMNS).writeheader()
        print(f"  Created {bench_path}")

    evicted = _evict_bench_row(bench_path, snapshot_date)
    if evicted:
        print(f"  Evicted {evicted} existing SPY row(s) for {snapshot_date} (last-write-wins).")

    print(f"\n[benchmark/SPY] snapshot_date={snapshot_date}")

    # The SPY quote page uses '.snapshot-table2' (not '.groups_table').
    # Selector verified against live Finviz via GitHub Actions (Azure IPs).
    t0 = time.time()
    html = fetch_html(SPY_URL, wait_selector=".snapshot-table2")
    print(f"  fetch_html took {time.time() - t0:.1f}s")

    rec = parse_spy_quote(html, snapshot_date, collected_at)

    # Validate parse completeness. SPY always has full perf history, so fewer
    # than all 7 values means a Finviz label change or page-structure failure —
    # not a legitimate data gap. Raise so the caller exits non-zero and GitHub
    # Actions flags the run (groups success must not mask SPY parse failure).
    parsed_count = sum(1 for c in BENCH_PERF_COLS if rec.get(c) is not None)
    if parsed_count < len(BENCH_PERF_COLS):
        raise RuntimeError(
            f"SPY parse yielded only {parsed_count}/{len(BENCH_PERF_COLS)} perf values "
            "— possible Finviz label change on quote page"
        )

    with open(bench_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=BENCH_CSV_COLUMNS)
        writer.writerow(
            {col: ("" if rec.get(col) is None else rec[col]) for col in BENCH_CSV_COLUMNS}
        )
    print(f"  Wrote SPY benchmark row for {snapshot_date} to {bench_path}")


def collect(group_type: str):
    """Fetch and store one group type."""
    subdir = "sectors" if group_type == "sector" else "industries"
    csv_path = DATA_DIR / subdir / "snapshots.csv"

    eastern = pytz.timezone("US/Eastern")
    now_utc = datetime.now(timezone.utc)
    snapshot_date = trading_date(datetime.now(eastern))
    collected_at = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    ensure_csv(csv_path)
    evicted = evict_today_rows(csv_path, snapshot_date)
    if evicted:
        print(f"  Evicted {evicted} existing rows for {snapshot_date} (last-write-wins).")
    existing_keys = load_existing_keys(csv_path)

    print(f"\n[{group_type}] snapshot_date={snapshot_date}")

    url = URLS[group_type]
    t0 = time.time()
    html = fetch_html(url)
    print(f"  fetch_html took {time.time() - t0:.1f}s")

    records = parse_table(html, group_type, snapshot_date, collected_at)
    print(f"  Parsed {len(records)} rows from HTML.")

    _EXPECTED_MIN_ROWS = {"sector": 8, "industry": 100}
    min_expected = _EXPECTED_MIN_ROWS.get(group_type, 1)
    if len(records) == 0:
        raise RuntimeError(
            f"[{group_type}] parse_table returned 0 rows — "
            "possible page structure change or block."
        )
    if len(records) < min_expected:
        print(
            f"  [warn] Only {len(records)} rows for {group_type}; "
            f"expected at least {min_expected}. Proceeding but this may indicate a problem.",
            file=sys.stderr,
        )

    n_written = append_records(csv_path, records, existing_keys)
    if n_written == 0:
        raise RuntimeError(
            f"[{group_type}] 0 rows written despite {len(records)} records parsed — "
            "eviction may have failed; aborting to prevent silent data loss."
        )


def main():
    for group_type in ("sector", "industry"):
        collect(group_type)

    # SPY benchmark — must not silently fail. Groups success does not mask SPY failure.
    spy_failed = False
    try:
        collect_spy()
    except Exception as exc:
        eastern = pytz.timezone("US/Eastern")
        date_str = trading_date(datetime.now(eastern))
        print(
            f"[WARN] SPY scrape failed for {date_str} — RS will be NaN: {exc}",
            file=sys.stderr,
        )
        spy_failed = True

    print("\nDone.")
    if spy_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
