"""
Seed the Finviz sector→industry taxonomy map from fasiha/finviz-git-scraper.

The fasiha repo scrapes finviz.com/map nightly and publishes map-sec_all.json —
a 3-level tree (Root → Sector → Industry → Stock) using the same Finviz taxonomy
as our groups pipeline. This script extracts the sector/industry layer, optionally
cross-validates against our snapshot CSVs, and writes:

  data/finviz_sector_industry_map.json  — sectors dict + metadata
  data/finviz_sector_industry_map.csv   — flat (finviz_sector, finviz_industry) pairs

Run once to seed; re-run only after Finviz restructures taxonomy (rare, ~yearly).
No Playwright, no Cloudflare — plain HTTP fetch from raw.githubusercontent.com.

Usage:
  python scripts/seed_taxonomy.py [--no-validate]
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


def write_outputs(sector_map: dict[str, list[str]]) -> None:
    """Write JSON and CSV artifacts to data/."""
    all_industries = [ind for inds in sector_map.values() for ind in inds]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
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
    args = parser.parse_args()

    print(f"Fetching {SOURCE_URL} ...")
    try:
        data = fetch_fasiha_json()
    except Exception as e:
        print(f"ERROR: fetch failed — {e}", file=sys.stderr)
        sys.exit(1)

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

    write_outputs(sector_map)
    print(f"\nWrote {OUT_JSON}")
    print(f"Wrote {OUT_CSV}")


if __name__ == "__main__":
    main()
