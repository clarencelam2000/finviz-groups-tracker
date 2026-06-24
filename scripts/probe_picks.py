"""
probe_picks.py — ONE-SHOT Phase-1 validation probe for the stock-picks pipeline.

Run this via GitHub Actions (probe_picks.yml) on an Azure IP to:
  1. Confirm all 84 columns return populated on a headless/anonymous client.
  2. Count pages and rows for Semiconductors under the VP-supplied wide-net filters.
  3. Extrapolate to the ~20-group daily cap and report the projected fetch budget.
  4. Emit a golden-header fixture to tests/fixtures/probe_header_84col.txt.

NEVER run this from the cloud (Google Cloud IPs get cf-mitigated: challenge).
Must run on GitHub Actions (Azure IPs pass Cloudflare).

Usage:
  python scripts/probe_picks.py [--group INDUSTRY_NAME]
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Config — document all constants per house rules
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
PICKS_DIR = DATA_DIR / "picks"
CONFIG_PATH = PICKS_DIR / "screener_config.json"
SLUGS_PATH = PICKS_DIR / "finviz_industry_slugs.csv"

# Fixture file committed after a successful probe run — used as golden header
GOLDEN_HEADER_PATH = BASE_DIR / "tests" / "fixtures" / "probe_header_84col.txt"

# Groups whose size exercises multi-page pagination; used as the probe target
DEFAULT_PROBE_GROUP = "Semiconductors"

# Polite inter-page delay in seconds (prevent rate-limit hammering)
# Set PROBE_PAGE_DELAY=0 in env to skip delays during debugging.
PAGE_DELAY_S = float(__import__("os").environ.get("PROBE_PAGE_DELAY", "2"))

# How many rows Finviz returns per screener page
PAGE_SIZE = 20

# Expected column count from screener_config.json.
# The exact label names are provisional until the probe run writes the golden header —
# Finviz may abbreviate (e.g. "EPS Q/Q" vs "EPS growth qtr over qtr"). Only position 0
# (c=1 = Ticker) is safe to assert by name independent of Elite gating or label drift.
EXPECTED_COL_COUNT = 84
EXPECTED_COL_0 = "Ticker"

SCREENER_BASE = "https://finviz.com/screener.ashx"

# CSS selector for the screener results table. Verified against live Finviz
# (v=151 custom view). Must be waited-for before reading page.content() — see
# _scrape_group. If Finviz renames this class the probe will time out and
# _dump_diagnostics will print the page title/snippet to identify the new class.
SCREENER_TABLE_SELECTOR = "table.screener_table"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify_industry(name: str) -> str:
    """Convert an industry name to the Finviz ind_<slug> token."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _build_url(config: dict, ind_slug: str, offset: int = 1) -> str:
    """
    Build a screener URL from the wide config block.
    offset is the &r= parameter (1-based; page 2 = r=21, page 3 = r=41 ...).
    """
    wide = config["wide"]
    filters = wide["base_filters"] + [f"ind_{ind_slug}"]
    f_str = ",".join(filters)
    col_ids = ",".join(str(c["id"]) for c in wide["columns"])
    url = (
        f"{SCREENER_BASE}"
        f"?v={wide['v']}"
        f"&f={f_str}"
        f"&ft={wide['ft']}"
        f"&o={wide['sort']}"
        f"&c={col_ids}"
        f"&r={offset}"
    )
    return url


def _parse_table(html: str) -> tuple[list[str], list[dict]]:
    """
    Parse Finviz screener HTML → (header_labels, rows).
    Returns ([], []) if the screener table is absent or empty.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one(SCREENER_TABLE_SELECTOR)
    if not table:
        # Finviz returns HTTP 200 with no table when the slug is wrong or 0 results
        return [], []

    rows = table.find_all("tr")
    if not rows:
        return [], []

    # First <tr> is the header row
    headers = [th.get_text(strip=True) for th in rows[0].find_all("td")]

    data_rows = []
    for tr in rows[1:]:
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cells) == len(headers):
            data_rows.append(dict(zip(headers, cells)))

    return headers, data_rows


def _dump_diagnostics(page) -> None:
    """Print page diagnostics when the screener table can't be found.

    Distinguishes the three common failure modes — Cloudflare challenge,
    wrong/renamed selector, and a genuine 0-result page — which otherwise all
    surface identically as "no table found".
    """
    try:
        html = page.content()
        soup = BeautifulSoup(html, "html.parser")
        title = (soup.title.get_text(strip=True) if soup.title else "(no title)")
        print(f"  [diag] page title: {title!r}")
        print(f"  [diag] content length: {len(html)} bytes")
        text = soup.get_text(" ", strip=True).lower()
        for marker in ("just a moment", "checking your browser",
                       "cloudflare", "cf-mitigated", "verify you are human"):
            if marker in text:
                print(f"  [diag] Cloudflare challenge marker detected: {marker!r}")
                break
        # List a sample of <table> classes present to spot a renamed selector.
        classes = []
        for tbl in soup.find_all("table"):
            cls = tbl.get("class")
            if cls:
                classes.append(".".join(cls))
        print(f"  [diag] tables present ({len(classes)}): {classes[:10]}")
    except Exception as exc:
        print(f"  [diag] failed to gather diagnostics: {exc}")


def _scrape_group(page, config: dict, ind_slug: str) -> tuple[list[str], list[dict]]:
    """
    Paginate through all screener pages for one industry slug.
    Returns (header_labels, all_rows).
    Prints page-level diagnostics to stdout.
    """
    all_rows: list[dict] = []
    header: list[str] = []
    offset = 1
    page_num = 0

    while True:
        page_num += 1
        url = _build_url(config, ind_slug, offset=offset)
        print(f"  [page {page_num}] GET {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)

        # The screener table is rendered after domcontentloaded fires, so reading
        # page.content() immediately captures HTML before the table exists. Wait
        # for the table selector to appear first — same pattern collect.py uses
        # for .groups_table. Without this wait the probe sees 0 rows / 0 cols
        # even though the URL renders fine in a real browser.
        try:
            page.wait_for_selector(SCREENER_TABLE_SELECTOR, timeout=30_000)
        except Exception as exc:
            # Selector never appeared — dump diagnostics so the failure is
            # debuggable from CI logs (Cloudflare challenge vs. wrong selector
            # vs. 0 results all look like "no table" without this context).
            print(f"  WARNING: '{SCREENER_TABLE_SELECTOR}' not found after 30s: {exc}")
            _dump_diagnostics(page)

        html = page.content()

        hdrs, rows = _parse_table(html)

        if page_num == 1:
            if not hdrs:
                print("  WARNING: No screener table found — slug may be wrong or 0 results")
                return [], []
            header = hdrs
            print(f"  [page 1] Header ({len(header)} cols): {header[:5]}...")

        if not rows:
            print(f"  [page {page_num}] 0 data rows — done paginating")
            break

        all_rows.extend(rows)
        print(f"  [page {page_num}] {len(rows)} rows (cumulative: {len(all_rows)})")

        if len(rows) < PAGE_SIZE:
            break  # last page

        offset += PAGE_SIZE
        if PAGE_DELAY_S > 0:
            time.sleep(PAGE_DELAY_S)

    return header, all_rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--group",
        default=DEFAULT_PROBE_GROUP,
        help=f"Industry name to probe (default: {DEFAULT_PROBE_GROUP!r})",
    )
    args = parser.parse_args()

    config = json.loads(CONFIG_PATH.read_text())
    expected_col_count = len(config["wide"]["columns"])  # must equal EXPECTED_COL_COUNT

    ind_slug = slugify_industry(args.group)
    print(f"\n=== Phase-1 Probe: {args.group!r} (slug: ind_{ind_slug}) ===\n")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            ignore_https_errors=True,
        )
        page = ctx.new_page()

        header, all_rows = _scrape_group(page, config, ind_slug)
        browser.close()

    # --------------- Validation -------------------------------------------

    print(f"\n=== Results ===")
    print(f"  Group:         {args.group!r}")
    print(f"  Slug:          ind_{ind_slug}")
    print(f"  Total rows:    {len(all_rows)}")
    print(f"  Header cols:   {len(header)} (expected {expected_col_count})")

    ok = True

    # 1. Column count — must be exactly EXPECTED_COL_COUNT (84).
    # A lower count means Finviz withheld Elite-gated columns; higher is unexpected.
    if len(header) != EXPECTED_COL_COUNT:
        print(f"  FAIL: col count mismatch — got {len(header)}, expected {EXPECTED_COL_COUNT}")
        ok = False
    else:
        print(f"  PASS: col count == {EXPECTED_COL_COUNT}")

    # 2. Position-0 sanity check — c=1 is always Ticker regardless of Elite gating.
    if header:
        if header[0] != EXPECTED_COL_0:
            print(f"  FAIL: header[0] == {header[0]!r}, expected {EXPECTED_COL_0!r}")
            ok = False
        else:
            print(f"  PASS: header[0] == {EXPECTED_COL_0!r}")

    # 3. At least some rows returned
    if len(all_rows) == 0:
        print(f"  FAIL: 0 rows — wrong slug or Cloudflare block")
        ok = False
    else:
        print(f"  PASS: {len(all_rows)} rows captured")

    # 4. Full column map: position × c_id × scraped_label × config_label.
    # DRIFT means Finviz renders a different string than screener_config.json documents.
    # These are expected for abbreviated labels (e.g. "EPS Q/Q" vs long-form names) —
    # the golden header written below becomes the authoritative source after this probe.
    if header:
        col_ids = [c["id"] for c in config["wide"]["columns"]]
        config_labels = [c["label"] for c in config["wide"]["columns"]]
        print(f"\n=== Column map (pos, c_id, scraped, config) ===")
        print(f"  {'pos':>3}  {'c_id':<5}  {'':5}  {'scraped':<35}  config")
        drifted = 0
        for i, (scraped, cid, cfglabel) in enumerate(zip(header, col_ids, config_labels)):
            if scraped == cfglabel:
                status = "MATCH"
            else:
                status = "DRIFT"
                drifted += 1
            print(f"  {i:>3}  {cid:<5}  {status:<5}  {scraped!r:<35}  {cfglabel!r}")
        if drifted:
            print(f"\n  {drifted} DRIFT(s) above — update screener_config.json labels to match scraped values.")
        else:
            print(f"\n  All {len(header)} labels match config exactly.")

    # --------------- Fetch-budget projection ------------------------------

    print(f"\n=== Fetch-budget projection ===")
    if len(all_rows) > 0:
        import math
        pages_for_group = math.ceil(len(all_rows) / PAGE_SIZE)
        # ~20 groups/day; scale by the Semis ratio vs a "median" group (~40 rows / 2 pages)
        # We report the actual Semis page count and ask VP to extrapolate
        print(f"  {args.group}: {len(all_rows)} rows → {pages_for_group} page(s)")
        print(f"  Median-group estimate: ~40 rows → 2 pages")
        print(f"  20-group daily cap extrapolation (if all were Semis-sized): "
              f"{pages_for_group * 20} fetches/day")
        print(f"  20-group daily cap extrapolation (mixed, ~15 avg-sized + 5 large): "
              f"{2 * 15 + pages_for_group * 5} fetches/day")
        print(f"\n  >>> VP: please review the row count above and sign off on the "
              f"daily fetch volume before the daily job (Phase 2) turns on. <<<")

    # --------------- Golden-header fixture --------------------------------

    if header and ok:
        GOLDEN_HEADER_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN_HEADER_PATH.write_text("\n".join(header) + "\n")
        print(f"\n  Golden header written to {GOLDEN_HEADER_PATH}")
        print(f"  Commit this file; the schema test will guard against future drift.")

    # --------------- Exit -------------------------------------------------

    print(f"\n=== {'PROBE PASSED' if ok else 'PROBE FAILED'} ===\n")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
