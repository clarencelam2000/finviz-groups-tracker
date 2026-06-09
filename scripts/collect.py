"""
collect.py — Fetch Finviz Groups data (sectors + industries) using Playwright
and append to append-only snapshot CSVs.
"""

import csv
import os
import sys
import time
from datetime import datetime, timezone, date
from pathlib import Path

import pytz
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

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

CSV_COLUMNS = [
    "date", "collected_at", "group_type", "name", "stocks", "market_cap",
    "pe", "fwd_pe", "perf_day", "perf_week", "perf_month", "perf_quarter",
    "perf_half", "perf_year", "perf_ytd", "avg_volume", "rel_volume", "change",
]

# Map Finviz header text → internal column name (None = skip)
HEADER_MAP = {
    "No.": None,
    "Name": "name",
    "Stocks": "stocks",
    "Market Cap": "market_cap",
    "P/E": "pe",
    "Fwd P/E": "fwd_pe",
    "Perf Day": "perf_day",
    "Perf Week": "perf_week",
    "Perf Month": "perf_month",
    "Perf Quart": "perf_quarter",
    "Perf Half": "perf_half",
    "Perf Year": "perf_year",
    "Perf YTD": "perf_ytd",
    "Avg Volume": "avg_volume",
    "Rel Volume": "rel_volume",
    "Change": "change",
}

PERF_COLS = {
    "perf_day", "perf_week", "perf_month", "perf_quarter",
    "perf_half", "perf_year", "perf_ytd", "change",
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

def fetch_html(url: str) -> str:
    """Fetch page HTML using Playwright with retry logic."""
    delays = [30, 60, 120]
    last_exc = None
    for attempt in range(3):
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context(user_agent=USER_AGENT)
                page = context.new_page()
                print(f"  Fetching {url} (attempt {attempt + 1}/3) …")
                page.goto(url, timeout=60_000)
                page.wait_for_selector(".table-groups", timeout=30_000)
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
    table = soup.select_one(".table-groups")
    if table is None:
        raise ValueError("Could not find .table-groups in HTML")

    rows = table.find_all("tr")
    if not rows:
        return []

    # Parse header
    header_cells = rows[0].find_all(["th", "td"])
    col_mapping = []  # list of internal column names (None = skip)
    for cell in header_cells:
        text = cell.get_text(strip=True)
        col_mapping.append(HEADER_MAP.get(text, None))

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

def collect(group_type: str):
    """Fetch and store one group type."""
    subdir = "sectors" if group_type == "sector" else "industries"
    csv_path = DATA_DIR / subdir / "snapshots.csv"

    ensure_csv(csv_path)
    existing_keys = load_existing_keys(csv_path)

    eastern = pytz.timezone("US/Eastern")
    now_utc = datetime.now(timezone.utc)
    snapshot_date = datetime.now(eastern).strftime("%Y-%m-%d")
    collected_at = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    print(f"\n[{group_type}] snapshot_date={snapshot_date}")

    url = URLS[group_type]
    html = fetch_html(url)
    records = parse_table(html, group_type, snapshot_date, collected_at)
    print(f"  Parsed {len(records)} rows from HTML.")

    append_records(csv_path, records, existing_keys)


def main():
    for group_type in ("sector", "industry"):
        collect(group_type)
    print("\nDone.")


if __name__ == "__main__":
    main()
