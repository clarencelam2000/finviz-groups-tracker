#!/usr/bin/env python3
"""eval_ai.py — offline quality guards for AI outputs.

No API calls, no credentials required.  Runs over Tier-2 debug captures.

Usage:
  python scripts/eval_ai.py                     # latest capture in data/ai/debug/
  python scripts/eval_ai.py --date 2026-06-22   # specific date
  python scripts/eval_ai.py path/to/file.json   # specific file path
  python scripts/eval_ai.py --all               # every capture in debug dir

Guards (all zero-cost):
  1. Hallucination guard — every Finviz group name in the raw output must appear
     in that call's input_blocks.  Catches invented sectors/industries.
  2. Format adherence:
     - pulse: parsed_output has non-empty 'headline' and conviction.level ∈ {High,Medium,Low}
     - rotation_phase: parsed_output label ∈ {Early Cycle, Mid Cycle, Late Cycle, Defensive}
     - watchlist: raw_response has ≤ 5 bullet lines
     - risk_radar: parsed_output has non-empty 'relative_strength' and 'risks'

Exit 0 if all checks pass; exit 1 if any guard fires (CI-friendly).
"""

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent.parent / "data"
DEBUG_DIR = DATA_DIR / "ai" / "debug"

PHASE_LABELS = frozenset({"Early Cycle", "Mid Cycle", "Late Cycle", "Defensive"})
CONVICTION_LEVELS = frozenset({"High", "Medium", "Low"})


# ---------------------------------------------------------------------------
# Known group names
# ---------------------------------------------------------------------------

def load_known_names() -> set:
    """Return all Finviz group names from snapshot CSVs."""
    names: set = set()
    for sub in ("sectors", "industries"):
        p = DATA_DIR / sub / "snapshots.csv"
        if p.exists():
            try:
                df = pd.read_csv(p, usecols=["name"], dtype=str)
                names.update(df["name"].dropna().unique())
            except Exception as e:
                print(f"  WARN: could not load {p}: {e}", file=sys.stderr)
    return names


# ---------------------------------------------------------------------------
# Hallucination guard
# ---------------------------------------------------------------------------

def _name_in(name: str, text: str, case_sensitive: bool = False) -> bool:
    """Word-boundary search for a group name in text.

    case_sensitive=True for raw_response checks: Finviz group names are always
    Title Case, so a lowercase match (e.g. 'steel' in 'primary steel inputs') is
    a generic noun, not a hallucinated group reference.
    """
    flags = 0 if case_sensitive else re.IGNORECASE
    return bool(re.search(r"\b" + re.escape(name) + r"\b", text, flags))


def check_hallucinations(fkey: str, call: dict, known_names: set) -> list:
    """Return issue strings for group names in output absent from input."""
    raw = call.get("raw_response") or ""
    input_text = call.get("input_blocks") or ""
    if not raw or not known_names:
        return []
    issues = []
    for name in sorted(known_names):
        # Use case-sensitive match on raw_response: group names are capitalized;
        # generic lowercase uses (e.g. 'steel' in 'primary steel inputs') are not hallucinations.
        if _name_in(name, raw, case_sensitive=True) and not _name_in(name, input_text):
            issues.append(f"  hallucination: {name!r} in output but not in input_blocks")
    return issues


# ---------------------------------------------------------------------------
# Format adherence
# ---------------------------------------------------------------------------

def check_format(fkey: str, call: dict) -> list:
    """Return format violation strings for a single call."""
    # Calls that did not complete are not evaluated for format
    status = call.get("status") or ""
    if status not in ("ok", ""):
        return []

    task = fkey.rsplit(".", 1)[-1] if "." in fkey else fkey
    raw = call.get("raw_response") or ""
    parsed = call.get("parsed_output")
    issues = []

    if task == "pulse":
        if not isinstance(parsed, dict):
            issues.append(f"  format: pulse parsed_output is not a dict (got {type(parsed).__name__})")
            return issues
        headline = (parsed.get("headline") or "").strip()
        if not headline:
            issues.append("  format: pulse headline is empty")
        conv = parsed.get("conviction")
        if not isinstance(conv, dict):
            issues.append(f"  format: pulse conviction is not a dict (got {type(conv).__name__})")
        else:
            level = (conv.get("level") or "").strip()
            if level not in CONVICTION_LEVELS:
                issues.append(
                    f"  format: conviction.level={level!r} not in "
                    f"{sorted(CONVICTION_LEVELS)}"
                )

    elif task == "rotation_phase":
        if not isinstance(parsed, dict):
            issues.append(
                f"  format: rotation_phase parsed_output is not a dict "
                f"(got {type(parsed).__name__})"
            )
            return issues
        label = (parsed.get("label") or "").strip()
        if label not in PHASE_LABELS:
            issues.append(
                f"  format: rotation_phase label={label!r} not in "
                f"{sorted(PHASE_LABELS)}"
            )

    elif task == "watchlist":
        bullets = [ln for ln in raw.split("\n") if re.match(r"^\s*[-*•]\s", ln)]
        if len(bullets) > 5:
            issues.append(
                f"  format: watchlist has {len(bullets)} bullets (max 5)"
            )

    elif task == "risk_radar":
        if not isinstance(parsed, dict):
            issues.append(
                f"  format: risk_radar parsed_output is not a dict "
                f"(got {type(parsed).__name__})"
            )
            return issues
        if not (parsed.get("relative_strength") or "").strip():
            issues.append("  format: risk_radar missing relative_strength section")
        if not (parsed.get("risks") or "").strip():
            issues.append("  format: risk_radar missing risks section")

    return issues


# ---------------------------------------------------------------------------
# Capture-level check
# ---------------------------------------------------------------------------

def check_capture(capture: dict, known_names: set,
                  skip_hallucination: bool = False) -> list:
    """Run all guards on one Tier-2 capture file.

    Returns a flat list of issue strings (empty = all clean).
    skip_hallucination: set True when no snapshot CSVs are available, to
      avoid spurious failures when running against a stale or partial repo.
    """
    issues = []
    calls = capture.get("calls") or {}
    for fkey, call in sorted(calls.items()):
        h = [] if skip_hallucination else check_hallucinations(fkey, call, known_names)
        f = check_format(fkey, call)
        if h or f:
            issues.append(f"[{fkey}]")
            issues.extend(h)
            issues.extend(f)
    return issues


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _resolve_paths(args) -> list:
    """Return list of Path objects to check, based on CLI args."""
    if args.files:
        return [Path(p) for p in args.files]
    if args.date:
        p = DEBUG_DIR / f"{args.date}.json"
        return [p] if p.exists() else []
    if getattr(args, 'all_', False):
        return sorted(DEBUG_DIR.glob("*.json")) if DEBUG_DIR.exists() else []
    # Default: latest capture
    if DEBUG_DIR.exists():
        candidates = sorted(DEBUG_DIR.glob("*.json"))
        return [candidates[-1]] if candidates else []
    return []


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline quality guards for AI Tier-2 debug captures."
    )
    parser.add_argument(
        "files", nargs="*",
        help="Tier-2 JSON files to check (default: latest in data/ai/debug/)",
    )
    parser.add_argument("--date", metavar="YYYY-MM-DD", help="Check capture for a specific date")
    parser.add_argument("--all", dest="all_", action="store_true",
                        help="Check all captures in data/ai/debug/")
    parser.add_argument("--no-hallucination", action="store_true",
                        help="Skip hallucination guard (useful when snapshot CSVs are absent)")
    args = parser.parse_args(argv)

    paths = _resolve_paths(args)
    if not paths:
        print("No capture files found — nothing to check. (Captures are written by "
              "generate_ai.py when AI_CAPTURE=1 or --capture is set.)")
        return 0

    known = load_known_names()
    skip_halluc = args.no_hallucination or not known

    if skip_halluc and not args.no_hallucination:
        print("WARN: no snapshot CSVs found — skipping hallucination guard.", file=sys.stderr)

    fail_count = 0
    for path in paths:
        try:
            capture = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"ERROR: {path.name}: {e}")
            fail_count += 1
            continue

        issues = check_capture(capture, known, skip_hallucination=skip_halluc)
        if issues:
            print(f"\n{path.name}  (date={capture.get('date','?')}):")
            for line in issues:
                print(line)
            fail_count += 1
        else:
            print(f"{path.name}: OK")

    print()
    if fail_count:
        print(f"FAIL: {fail_count}/{len(paths)} capture(s) have issues.")
        return 1
    print(f"All {len(paths)} capture(s) passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
