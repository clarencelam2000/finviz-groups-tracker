"""
backfill.py — Helper that shows current date coverage and instructions for
manually running collect.py multiple times to backfill historical data.
"""

import argparse
import csv
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"


def get_dates_in_csv(csv_path: Path) -> list:
    """Return sorted list of unique dates present in the snapshots CSV."""
    if not csv_path.exists():
        return []
    dates = set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            d = row.get("date", "").strip()
            if d:
                dates.add(d)
    return sorted(dates)


def show_status():
    print("=== Finviz Groups Tracker — Data Coverage Status ===\n")
    for subdir in ("sectors", "industries"):
        csv_path = DATA_DIR / subdir / "snapshots.csv"
        dates = get_dates_in_csv(csv_path)
        print(f"[{subdir}] {csv_path}")
        if not dates:
            print("  No data rows yet (file may only have headers or not exist).")
        else:
            print(f"  Date range : {dates[0]}  →  {dates[-1]}")
            print(f"  Total dates: {len(dates)}")
            print(f"  Dates      : {', '.join(dates[:10])}" +
                  (" …" if len(dates) > 10 else ""))
        print()


def show_instructions():
    print("=== Finviz Groups Tracker — Backfill Instructions ===\n")
    print("This project does NOT support automated historical backfill because")
    print("Finviz only shows current (live) group performance data.\n")
    print("To collect today's snapshot, run:")
    print()
    print("    python scripts/collect.py")
    print()
    print("The script is idempotent: running it multiple times on the same day")
    print("will not create duplicate rows (deduplication is based on date + name).\n")
    print("To build up a historical dataset, schedule collect.py to run daily.")
    print("GitHub Actions is already configured in .github/workflows/collect.yml")
    print("to run automatically on weekdays at 22:00 UTC (6 PM Eastern).\n")
    print("For manual multi-day backfill from the past, you would need access to")
    print("historical Finviz data snapshots — this is not available via the free")
    print("Finviz web interface.\n")
    print("Run with --status to see which dates are already in the CSVs.")


def main():
    parser = argparse.ArgumentParser(
        description="Show data coverage and backfill instructions."
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current date coverage in the snapshot CSVs.",
    )
    args = parser.parse_args()

    if args.status:
        show_status()
    else:
        show_instructions()
        print()
        show_status()


if __name__ == "__main__":
    main()
