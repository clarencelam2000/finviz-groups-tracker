#!/usr/bin/env python3
"""Build the public agent-consumption feed: data/api/manifest.json + latest_signals.json.

WHY THIS EXISTS
---------------
External read-only agents (e.g. Muse) should NOT couple to our raw CSV schemas —
`picks_latest.csv` alone is 118 columns and has migrated many times, and the delta
schema is generated from `delta_config.delta_columns()`. If a consumer hard-codes
column positions off today's CSVs, a routine internal schema change silently breaks it.

So we publish two small, stable JSON files the daily workflows regenerate:

- ``manifest.json`` — tiny "table of contents": freshness (as_of / generated_at),
  the data branch, row counts, a self-describing file index, config constants an
  agent needs to *derive* display bands itself (ATR bands, lookback windows), and
  stable pointers to the append-only history files for full-history runs.
- ``latest_signals.json`` — a **versioned** compact summary (top-N lists only) that
  is the consumer's read contract. ``schema_version`` is major.minor and additive-only
  within a major; a major bump signals a breaking shape change.

PRIVACY BOUNDARY: everything here is derived from data already public in this repo
(rankings, signals, the picks *list*). Nothing derived from the private position book
(worker-positions D1) is ever written here. See CLAUDE.md § privacy boundary and
.claude/rules/data-pipeline.md.

CONFIG-DEPENDENT BANDS ARE NEVER PERSISTED AS LABELS. Per .claude/rules/data-pipeline.md,
we emit the raw ``atr_ext_50`` multiple per pick and publish the *thresholds* in the
manifest, so a consumer computes the band (actionable/caution/trim) itself. Retuning a
threshold then never leaves stale labels in the feed.

Run standalone or as the last step of collect.yml / collect_picks.yml. Reads whatever
is currently committed on disk; idempotent.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# Bumped only by a human editing this file. Contract: additive-only within a major.
# major.minor — consumers trust a minor bump blindly and must halt on a major bump.
SCHEMA_VERSION = "1.0"

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "data" / "api"

# Canonical ATR-extension band thresholds. SOURCE OF TRUTH is the PWA display
# constants ATR_EXT_ACTIONABLE / ATR_EXT_TRIM (docs/CLAUDE.md § PWA display thresholds
# and docs/index.html). Kept in sync here only to *publish* them for external consumers
# — if you change them in docs/, change them here in the same PR (3-places rule).
ATR_BANDS = {"actionable_max": 4.0, "trim_min": 8.0}

# How many rows each top-N signal list carries. Keeps the file KBs, not MBs.
TOP_N = 15

# Per-window rank-delta column used for the movers/fading lists. 20 sessions ≈ 1
# trading month — a rotation horizon, not day-to-day noise. Must exist in
# delta_config.LOOKBACK_WINDOWS.
MOVERS_WINDOW = 20


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _current_branch() -> str:
    """Best-effort git branch name; empty string if unavailable (detached CI checkout)."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
        return "" if out == "HEAD" else out
    except Exception:
        return ""


def _latest_rows(csv_path: Path) -> pd.DataFrame:
    """Return only the rows for the max date in a deltas/snapshots CSV (empty-safe)."""
    if not csv_path.exists():
        return pd.DataFrame()
    df = pd.read_csv(csv_path)
    if len(df) == 0 or "date" not in df.columns:
        return pd.DataFrame()
    return df[df["date"] == df["date"].max()].copy()


def _round(v, ndigits=4):
    """JSON-safe rounded float; None for NaN/missing."""
    if v is None or pd.isna(v):
        return None
    return round(float(v), ndigits)


def build_signals(industries: pd.DataFrame, sectors: pd.DataFrame,
                  picks: pd.DataFrame, branch: str) -> dict:
    """Pure builder for latest_signals.json — takes latest-date frames, returns a dict."""
    as_of = None
    for df in (industries, sectors, picks):
        if len(df) and "date" in df.columns:
            d = str(df["date"].max())
            as_of = d if as_of is None else max(as_of, d)

    out: dict = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now_iso(),
        "as_of": as_of,
        "session": "eod",  # settled close; see scripts/session_config.py
        "data_branch": branch,
        "universe": {"sectors": int(len(sectors)), "industries": int(len(industries))},
        "emerging_leaders": [],
        "top_movers": [],
        "fading": [],
        "picks": {},
    }

    # Emerging leaders: strongest short-vs-long rotation (regime_short_long desc).
    if len(industries) and "regime_short_long" in industries.columns:
        lead = industries.dropna(subset=["regime_short_long"]).nlargest(
            TOP_N, "regime_short_long")
        out["emerging_leaders"] = [
            {
                "group": r["name"],
                "rank_ytd": _round(r.get("rank_ytd"), 0),
                "regime_short_long": _round(r.get("regime_short_long")),
                "momentum_score": _round(r.get("momentum_score")),
                "rs_score": _round(r.get("rs_score")),
            }
            for _, r in lead.iterrows()
        ]

    # Movers / fading: biggest rank improvement / deterioration over MOVERS_WINDOW.
    delta_col = f"rank_ytd_delta_{MOVERS_WINDOW}d"
    if len(industries) and delta_col in industries.columns:
        valid = industries.dropna(subset=[delta_col])

        def _mover(r):
            return {
                "group": r["name"],
                "timeframe": f"{MOVERS_WINDOW}d",
                "to_rank": _round(r.get("rank_ytd"), 0),
                "rank_delta": _round(r.get(delta_col), 0),
            }

        out["top_movers"] = [_mover(r) for _, r in valid.nlargest(TOP_N, delta_col).iterrows()]
        out["fading"] = [_mover(r) for _, r in valid.nsmallest(TOP_N, delta_col).iterrows()]

    # Picks grouped by their real selector bucket (list_category). Raw atr_ext_50 only —
    # band derived by the consumer from manifest.config.atr_bands.
    if len(picks) and "list_category" in picks.columns:
        for cat, grp in picks.groupby("list_category"):
            out["picks"][str(cat)] = [
                {
                    "ticker": r.get("ticker"),
                    "group": r.get("group"),
                    "list_category": str(cat),
                    "signal_date": r.get("date"),
                    "atr_ext_50": _round(r.get("atr_ext_50"), 2),
                }
                for _, r in grp.iterrows()
            ]

    return out


def build_manifest(industries: pd.DataFrame, sectors: pd.DataFrame,
                   picks: pd.DataFrame, branch: str, as_of: str | None) -> dict:
    """Pure builder for manifest.json — the self-describing index + config."""
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now_iso(),
        "as_of": as_of,
        "session": "eod",
        "data_branch": branch,
        "row_counts": {
            "sectors": int(len(sectors)),
            "industries": int(len(industries)),
            "picks": int(len(picks)),
        },
        "signals_file": "data/api/latest_signals.json",
        # Stable pointers to the append-only full-history files (for monthly full runs).
        "history": {
            "sectors_snapshots": "data/sectors/snapshots.csv",
            "sectors_deltas": "data/sectors/deltas.csv",
            "industries_snapshots": "data/industries/snapshots.csv",
            "industries_deltas": "data/industries/deltas.csv",
            "benchmark_snapshots": "data/benchmark/snapshots.csv",
            "picks_history": "data/picks/picks.csv",
            "picks_latest": "data/picks/picks_latest.csv",
        },
        # Config constants a consumer needs to DERIVE display bands itself, so we never
        # persist a config-dependent label (see module docstring + data-pipeline.md).
        "config": {
            "atr_bands": ATR_BANDS,
            "lookback_windows": [5, 10, 20, 50],
            "movers_window": MOVERS_WINDOW,
            "regime_short_long": {
                "short": ["perf_week", "perf_month"],
                "long": ["perf_quarter", "perf_half", "perf_year"],
            },
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", default=str(OUT_DIR),
                    help="Output directory for manifest.json + latest_signals.json")
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    industries = _latest_rows(REPO_ROOT / "data" / "industries" / "deltas.csv")
    sectors = _latest_rows(REPO_ROOT / "data" / "sectors" / "deltas.csv")
    picks_path = REPO_ROOT / "data" / "picks" / "picks_latest.csv"
    picks = pd.read_csv(picks_path) if picks_path.exists() else pd.DataFrame()

    branch = _current_branch()
    signals = build_signals(industries, sectors, picks, branch)
    manifest = build_manifest(industries, sectors, picks, branch, signals["as_of"])

    (out_dir / "latest_signals.json").write_text(json.dumps(signals, indent=2) + "\n")
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Wrote {out_dir}/manifest.json + latest_signals.json (as_of={signals['as_of']})")


if __name__ == "__main__":
    main()
