"""
Seed the Finviz sector→industry taxonomy map and industry→stock map
from fasiha/finviz-git-scraper.

The fasiha repo scrapes finviz.com/map nightly and publishes map-sec_all.json —
a 3-level tree (Root → Sector → Industry → Stock) using the same Finviz taxonomy
as our groups pipeline. This script extracts both layers in a single HTTP fetch:

  data/finviz_sector_industry_map.json  — sectors dict + metadata
  data/finviz_sector_industry_map.csv   — flat (finviz_sector, finviz_industry) pairs
  data/finviz_industry_stock_map.json   — industry→stocks + reverse ticker index

Run once to seed; re-run only after Finviz restructures taxonomy (rare, ~yearly).
No Playwright, no Cloudflare — plain HTTP fetch from raw.githubusercontent.com.

Usage:
  python scripts/seed_taxonomy.py [--no-validate] [--skip-stocks]
"""

import argparse
import csv
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SOURCE_URL = "https://raw.githubusercontent.com/fasiha/finviz-git-scraper/main/map-sec_all.json"
OUT_JSON = Path("data/finviz_sector_industry_map.json")
OUT_CSV = Path("data/finviz_sector_industry_map.csv")
OUT_STOCK_JSON = Path("data/finviz_industry_stock_map.json")


def fetch_fasiha_json(url: str = SOURCE_URL) -> dict:
    """Download and parse the fasiha map-sec_all.json treemap file."""
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read())


def parse_sector_industry_map(data: dict) -> dict[str, list[str]]:
    """
    Extract sector→industry mapping from the 3-level treemap JSON.

    Expected structure: Root → Sector nodes → Industry nodes → Stock nodes.
    Returns dict of {sector_name: sorted list of industry names}.
    Raises ValueError if the root has no children or any sector node is malformed.
    """
    top_children = data.get("children")
    if not top_children:
        raise ValueError("Root node has no 'children' — unexpected JSON structure")

    sector_map: dict[str, list[str]] = {}
    for sector_node in top_children:
        sector_name = sector_node.get("name")
        if not sector_name:
            raise ValueError(f"Sector node missing 'name': {sector_node!r}")
        industry_names = []
        for ind_node in sector_node.get("children", []):
            ind_name = ind_node.get("name")
            if ind_name:
                industry_names.append(ind_name)
        sector_map[sector_name] = sorted(industry_names)

    return sector_map


def cross_validate(sector_map: dict[str, list[str]]) -> tuple[set, set, set]:
    """
    Compare sector_map against our live snapshot CSVs.

    Returns (in_both, only_ours, only_theirs) sets of industry names.
    Silently skips validation if snapshot CSVs are missing or empty.
    """
    our_inds: set[str] = set()
    snap_path = Path("data/industries/snapshots.csv")
    if snap_path.exists():
        with open(snap_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get("name", "").strip()
                if name:
                    our_inds.add(name)

    if not our_inds:
        return set(), set(), set()

    all_theirs = {ind for inds in sector_map.values() for ind in inds}
    in_both = our_inds & all_theirs
    only_ours = our_inds - all_theirs
    only_theirs = all_theirs - our_inds
    return in_both, only_ours, only_theirs


def parse_industry_stock_map(data: dict) -> dict:
    """
    Extract industry→stock mapping from the 3-level treemap JSON.

    Each industry entry includes:
      - sector: parent sector name
      - stock_count: number of stocks
      - total_market_cap_m: sum of all stock market caps (millions USD)
      - top_concentration_pct: largest single stock as % of industry total market cap;
        high values (>40%) signal that the industry rank is a single-stock proxy
      - stocks: list of {ticker, name, market_cap_m}, sorted descending by market cap

    market_cap_m = raw treemap value / 1000 (Finviz stores in thousands of USD).
    Stocks with no ticker or zero market cap are included with market_cap_m=0.

    Also builds a flat ticker_to_industry reverse index for O(1) Worker fallback
    classification without any FMP API call.

    Returns dict with keys "industries" and "ticker_to_industry".
    """
    top_children = data.get("children")
    if not top_children:
        raise ValueError("Root node has no 'children' — unexpected JSON structure")

    industries: dict = {}
    ticker_to_industry: dict[str, str] = {}

    for sector_node in top_children:
        sector_name = sector_node.get("name", "")
        for ind_node in sector_node.get("children", []):
            ind_name = ind_node.get("name")
            if not ind_name:
                continue

            stocks = []
            for stock_node in ind_node.get("children", []):
                ticker = stock_node.get("name", "").strip()
                name = stock_node.get("description", "").strip()
                raw_value = stock_node.get("value", 0) or 0
                market_cap_m = int(raw_value / 1000)
                if ticker:
                    stocks.append({"ticker": ticker, "name": name, "market_cap_m": market_cap_m})
                    ticker_to_industry[ticker] = ind_name

            # Sort descending by market cap so stocks[0] is the dominant name
            stocks.sort(key=lambda s: s["market_cap_m"], reverse=True)

            total_cap = sum(s["market_cap_m"] for s in stocks)
            top_concentration_pct = round(
                stocks[0]["market_cap_m"] / total_cap * 100, 1
            ) if (stocks and total_cap > 0) else None

            industries[ind_name] = {
                "sector": sector_name,
                "stock_count": len(stocks),
                "total_market_cap_m": total_cap,
                "top_concentration_pct": top_concentration_pct,
                "stocks": stocks,
            }

    return {"industries": industries, "ticker_to_industry": ticker_to_industry}


def write_stock_map_output(stock_data: dict, generated_at: str) -> None:
    """Write data/finviz_industry_stock_map.json."""
    industries = stock_data["industries"]
    ticker_index = stock_data["ticker_to_industry"]
    total_stocks = sum(v["stock_count"] for v in industries.values())

    payload = {
        "generated_at": generated_at,
        "source": "fasiha/finviz-git-scraper (map-sec_all.json)",
        "source_url": SOURCE_URL,
        "total_industries": len(industries),
        "total_stocks": total_stocks,
        # market_cap_m = raw treemap value / 1000; unit is millions USD
        "note_market_cap": "market_cap_m is market cap in millions USD (Finviz treemap value/1000)",
        # Flat reverse lookup: ticker → industry name. Enables O(1) Worker fallback
        # classification without FMP. ~5000 entries, typically <300KB.
        "ticker_to_industry": ticker_index,
        "industries": industries,
    }

    OUT_STOCK_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_STOCK_JSON.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")


def write_outputs(sector_map: dict[str, list[str]], generated_at: str) -> None:
    """Write JSON and CSV artifacts to data/."""
    all_industries = [ind for inds in sector_map.values() for ind in inds]

    payload = {
        "generated_at": generated_at,
        "source": "fasiha/finviz-git-scraper (map-sec_all.json)",
        "source_url": SOURCE_URL,
        "total_sectors": len(sector_map),
        "total_industries": len(all_industries),
        "sectors": sector_map,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")

    with open(OUT_CSV, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["finviz_sector", "finviz_industry"])
        for sector, inds in sector_map.items():
            for ind in inds:
                writer.writerow([sector, ind])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-validate", action="store_true",
                        help="Skip cross-validation against snapshot CSVs")
    parser.add_argument("--skip-stocks", action="store_true",
                        help="Skip writing the industry→stock map (taxonomy only)")
    args = parser.parse_args()

    print(f"Fetching {SOURCE_URL} ...")
    try:
        data = fetch_fasiha_json()
    except Exception as e:
        print(f"ERROR: fetch failed — {e}", file=sys.stderr)
        sys.exit(1)

    generated_at = datetime.now(timezone.utc).isoformat()

    sector_map = parse_sector_industry_map(data)

    total_sectors = len(sector_map)
    total_industries = sum(len(v) for v in sector_map.values())
    print(f"\nParsed: {total_sectors} sectors, {total_industries} industries")
    for sec, inds in sorted(sector_map.items()):
        print(f"  {sec}: {len(inds)} industries")

    if not args.no_validate:
        print("\nCross-validating against data/industries/snapshots.csv ...")
        in_both, only_ours, only_theirs = cross_validate(sector_map)
        if in_both or only_ours or only_theirs:
            match_pct = len(in_both) / (len(in_both) + len(only_ours)) * 100 if (in_both or only_ours) else 0
            print(f"  Match: {len(in_both)}/{len(in_both)+len(only_ours)} of our industries ({match_pct:.0f}%)")
            if only_ours:
                print(f"  WARNING — in our CSVs but NOT in fasiha map ({len(only_ours)}):")
                for x in sorted(only_ours):
                    print(f"    missing: {x!r}")
            if only_theirs:
                print(f"  Note — in fasiha but NOT in our CSVs ({len(only_theirs)}) — likely newer additions:")
                for x in sorted(only_theirs):
                    print(f"    extra:   {x!r}")
            if not only_ours:
                print("  All our tracked industries are covered. Validation passed.")
        else:
            print("  Snapshot CSV empty or missing — skipping validation.")

    write_outputs(sector_map, generated_at)
    print(f"\nWrote {OUT_JSON}")
    print(f"Wrote {OUT_CSV}")

    if not args.skip_stocks:
        print("\nParsing industry→stock map ...")
        stock_data = parse_industry_stock_map(data)
        industries = stock_data["industries"]
        ticker_index = stock_data["ticker_to_industry"]
        total_stocks = sum(v["stock_count"] for v in industries.values())
        print(f"  {len(industries)} industries, {total_stocks} stocks, {len(ticker_index)} tickers indexed")

        # Highlight high-concentration industries (top stock > 40% of industry cap)
        high_conc = [
            (name, v["top_concentration_pct"], v["stocks"][0]["ticker"] if v["stocks"] else "?")
            for name, v in industries.items()
            if v["top_concentration_pct"] is not None and v["top_concentration_pct"] >= 40
        ]
        if high_conc:
            high_conc.sort(key=lambda x: x[1], reverse=True)
            print(f"  High-concentration industries (top stock ≥40% of cap) — {len(high_conc)} found:")
            for ind_name, pct, ticker in high_conc[:8]:
                print(f"    {ticker:6s} {pct:4.0f}%  {ind_name}")

        write_stock_map_output(stock_data, generated_at)
        print(f"\nWrote {OUT_STOCK_JSON}")


if __name__ == "__main__":
    main()
