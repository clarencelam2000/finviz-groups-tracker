"""
generate_ai.py — Generate AI analysis from latest Finviz data using Gemini.
Writes data/ai/YYYY-MM-DD.json, which the dashboard reads and renders.

Run after compute_deltas.py.

Dual-mode auth, selected by the GOOGLE_GENAI_USE_VERTEXAI env toggle:
  - Vertex AI (toggle on):  identity from ADC; requires GOOGLE_CLOUD_PROJECT
    (and optionally GOOGLE_CLOUD_LOCATION, default us-central1). No API key.
  - AI Studio (toggle off): requires GEMINI_API_KEY.
Exits 0 silently when the selected backend is not configured.
"""

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from delta_config import LOOKBACK_WINDOWS

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
AI_DIR = DATA_DIR / "ai"

# Short-horizon rank-delta column used for movers/divergence signals. Derived
# from the configured lookbacks so a window change doesn't silently empty the
# AI output (the shortest window is the closest analog to the old 7d signal).
SHORT_WIN = LOOKBACK_WINDOWS[0]
SHORT_DELTA_COL = f"rank_ytd_delta_{SHORT_WIN}d"

GEMINI_MODEL = "gemini-3.5-flash"

# ---------------------------------------------------------------------------
# Capture artifact paths and constants (documented in README + CLAUDE.md too)
# ---------------------------------------------------------------------------
# CAPTURE_DIR: Tier-2 debug captures (committed, rolling CAPTURE_RETENTION_DAYS
#   in HEAD; older files pruned from HEAD but kept in git history).
# PROVENANCE_DIR: Tier-1 provenance — input data blocks only (committed permanently;
#   ~5-15 KB/day; powers the PWA "Behind this" drawer).
# CAPTURE_RETENTION_DAYS: rolling window for Tier-2 files in HEAD. Tune up for
#   more in-repo history, down to shrink the working tree. Currently 30 days ≈ 1 MB.
CAPTURE_DIR = DATA_DIR / "ai" / "debug"
PROVENANCE_DIR = DATA_DIR / "ai" / "provenance"
CAPTURE_RETENTION_DAYS = 30


class DailyQuotaExhaustedError(Exception):
    """Gemini daily free-tier RPD quota is fully consumed. Cannot retry until reset."""


@dataclass
class CallResult:
    """Return value of _call_api(). Carries text, token usage, and API latency.

    Usage and latency are captured here so the generate_for_group() loop can
    forward them to _record_capture() without side-channel globals.
    """
    text: str
    usage: dict
    latency: float


# Courtesy spacing between calls. The binding free-tier limit was 20 requests/DAY
# (RPD), not per-minute; on Vertex AI paid tier per-minute limits are high.
# Daily-quota exhaustion is handled separately (DailyQuotaExhaustedError, abort-no-retry).
_INTER_CALL_DELAY = 2
_last_api_call: float = 0.0
# Base delay (seconds) for exponential retry backoff: 3s, 6s, 12s.
# Tests set this to 0 via monkeypatch to avoid real sleeps.
_RETRY_BASE_DELAY = 3

# Run-level tracking (reset by main() at start of each run).
_api_call_count: int = 0
_rate_limit_hits: int = 0
_field_log: dict = {}  # "sectors.briefing" -> {status, was_new, elapsed_seconds?, error?}
_capture_log: dict = {}  # fkey -> {input_blocks, prompt, raw_response, parsed_output, usage, latency, status}
_backend: str = "unset"  # "vertex_ai" | "vertex_express" | "google_ai_studio" | "unset"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_latest_snapshot(group_type: str) -> pd.DataFrame:
    subdir = "sectors" if group_type == "sector" else "industries"
    path = DATA_DIR / subdir / "snapshots.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    if df.empty:
        return pd.DataFrame()
    for col in ["perf_day", "perf_week", "perf_month", "perf_quarter",
                "perf_half", "perf_year", "perf_ytd", "market_cap", "pe", "fwd_pe"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    latest = df["date"].max()
    return df[df["date"] == latest].copy()


def load_latest_delta(group_type: str) -> pd.DataFrame:
    subdir = "sectors" if group_type == "sector" else "industries"
    path = DATA_DIR / subdir / "deltas.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    if df.empty:
        return pd.DataFrame()
    for col in df.columns:
        if col not in ("date", "name"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    latest = df["date"].max()
    return df[df["date"] == latest].copy()


def _has_new_delta_data(date_str: str) -> bool:
    """Return True if today's date appears in at least one delta CSV."""
    for subdir in ("sectors", "industries"):
        path = DATA_DIR / subdir / "deltas.csv"
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path, dtype=str, usecols=["date"])
            if (df["date"] == date_str).any():
                return True
        except Exception:
            print(
                f"WARNING: could not read {path} while checking for delta data — will skip",
                flush=True,
            )
    return False


# ---------------------------------------------------------------------------
# Run tracking helpers
# ---------------------------------------------------------------------------

def _reset_tracking() -> None:
    global _api_call_count, _rate_limit_hits, _field_log, _backend, _capture_log
    _api_call_count = 0
    _rate_limit_hits = 0
    _field_log = {}
    _capture_log = {}
    _backend = "unset"


def _record_field(key: str, status: str, *, was_new: bool = True,
                  elapsed: float = 0.0, error: str = "") -> None:
    entry = {"status": status, "was_new": was_new}
    if was_new and elapsed:
        entry["elapsed_seconds"] = round(elapsed, 1)
    if error:
        entry["error"] = error
    _field_log[key] = entry


def _extract_usage(response) -> dict:
    """Pull usage_metadata from a genai response defensively.

    Returns {} when metadata is absent — some error/retry paths don't include it.
    """
    try:
        meta = response.usage_metadata
        return {
            "prompt_tokens": getattr(meta, "prompt_token_count", None),
            "output_tokens": getattr(meta, "candidates_token_count", None),
            "total_tokens": getattr(meta, "total_token_count", None),
        }
    except Exception:
        return {}


def _record_capture(fkey: str, *, input_blocks: str, prompt: str = "",
                    generation_config: dict = None, raw: str = "",
                    parsed=None, usage: dict = None,
                    latency: float = 0.0, status: str = "ok") -> None:
    """Accumulate one Tier-2 capture entry into _capture_log.

    Tier-1 provenance (input_blocks) is always recorded; the rest is Tier-2.
    Both tiers are written by _write_capture_tiers() in main().
    """
    _capture_log[fkey] = {
        "input_blocks": input_blocks,
        "prompt": prompt,
        "generation_config": generation_config or {},
        "raw_response": raw,
        "parsed_output": parsed,
        "usage": usage if usage is not None else {},
        "latency_seconds": round(latency, 2),
        "status": status,
    }




# ---------------------------------------------------------------------------
# Prompt builders / serializers
# ---------------------------------------------------------------------------

def serialize_snapshot_summary(snap_df: pd.DataFrame) -> str:
    if snap_df.empty:
        return "No snapshot data available."
    perf_cols = [c for c in ["perf_week", "perf_month", "perf_ytd"] if c in snap_df.columns]
    if not perf_cols:
        return "No performance data available."
    sort_col = "perf_ytd" if "perf_ytd" in perf_cols else perf_cols[0]
    sorted_df = snap_df.sort_values(sort_col, ascending=False)
    lines = ["PERFORMANCE SNAPSHOT (sorted by YTD):"]
    for _, r in sorted_df.iterrows():
        parts = [str(r["name"])]
        for col in perf_cols:
            if pd.notna(r.get(col)):
                parts.append(f"{col.replace('perf_', '')}={r[col]:+.1f}%")
        lines.append("  " + ", ".join(parts))
    return "\n".join(lines)


def serialize_top_movers(delta_df: pd.DataFrame, n: int = 10) -> str:
    if delta_df.empty or SHORT_DELTA_COL not in delta_df.columns:
        return f"No {SHORT_WIN}-day rank delta data available yet (need {SHORT_WIN}+ sessions of history)."
    valid = delta_df.dropna(subset=[SHORT_DELTA_COL]).copy()
    if valid.empty:
        return f"No {SHORT_WIN}-day rank delta data available yet."

    take = min(n, len(valid))
    gainers = valid.nlargest(take, SHORT_DELTA_COL)[
        ["name", SHORT_DELTA_COL, "rank_ytd", "momentum_score"]
    ]
    losers = valid.nsmallest(take, SHORT_DELTA_COL)[
        ["name", SHORT_DELTA_COL, "rank_ytd", "momentum_score"]
    ]

    lines = [f"TOP GAINERS (rank improved most in {SHORT_WIN} sessions):"]
    for _, r in gainers.iterrows():
        ms = f"{r['momentum_score']:.2f}" if pd.notna(r.get("momentum_score")) else "N/A"
        rank_str = f"{r['rank_ytd']:.0f}" if pd.notna(r.get("rank_ytd")) else "N/A"
        lines.append(
            f"  {r['name']}: +{r[SHORT_DELTA_COL]:.0f} spots, "
            f"rank {rank_str}, momentum {ms}"
        )

    lines.append(f"\nTOP LOSERS (rank declined most in {SHORT_WIN} sessions):")
    for _, r in losers.iterrows():
        ms = f"{r['momentum_score']:.2f}" if pd.notna(r.get("momentum_score")) else "N/A"
        rank_str = f"{r['rank_ytd']:.0f}" if pd.notna(r.get("rank_ytd")) else "N/A"
        lines.append(
            f"  {r['name']}: {r[SHORT_DELTA_COL]:.0f} spots, "
            f"rank {rank_str}, momentum {ms}"
        )
    return "\n".join(lines)


def serialize_momentum_leaders(delta_df: pd.DataFrame, n: int = 5) -> str:
    if delta_df.empty or "momentum_score" not in delta_df.columns:
        return "No momentum data available."
    valid = delta_df.dropna(subset=["momentum_score"]).sort_values(
        "momentum_score", ascending=False
    )
    if valid.empty:
        return "No momentum data available."
    lines = ["MOMENTUM LEADERS (score 0=weakest, 1=strongest):"]
    for _, r in valid.head(n).iterrows():
        rank_ytd = r.get("rank_ytd")
        rank_str = f"{rank_ytd:.0f}" if pd.notna(rank_ytd) else "N/A"
        lines.append(f"  {r['name']}: {r['momentum_score']:.3f} (rank_ytd={rank_str})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Computed-signal serializers — the analytical "moat" fed to the model.
# These narrate metrics the plain Finviz groups page can't: all-green breadth,
# sustained strength, momentum laggards, and rank/momentum divergences.
# ---------------------------------------------------------------------------

PERF_TIMEFRAMES = ["perf_week", "perf_month", "perf_quarter", "perf_half", "perf_ytd"]
SUSTAINED_RANK_COLS = ["rank_month", "rank_quarter", "rank_half"]

# Divergence thresholds
_STRONG_MOMENTUM = 0.60   # "strong" momentum_score
_RANK_JUMP_SHORT = 3.0    # spots improved in the short window to count as "emerging"
_LOW_AGREEMENT = 0.50     # rank_agreement below this is "fragile"


def _all_green_mask(df: pd.DataFrame):
    """Boolean Series (True where every available perf timeframe is > 0) plus the
    list of timeframes actually checked. Returns (None, []) if no perf columns."""
    available = [c for c in PERF_TIMEFRAMES if c in df.columns]
    if not available:
        return None, []
    mask = pd.Series(True, index=df.index)
    for tf in available:
        mask = mask & (pd.to_numeric(df[tf], errors="coerce").fillna(0) > 0)
    return mask, available


def _strength_frame(snap_df: pd.DataFrame, delta_df: pd.DataFrame) -> pd.DataFrame:
    """Snapshot perf rows joined with momentum/agreement/sustained-rank columns."""
    merged = snap_df.copy()
    if delta_df is not None and not delta_df.empty and "name" in delta_df.columns \
            and "name" in merged.columns:
        keep = ["name"] + [
            c for c in ["momentum_score", "rank_agreement"] + SUSTAINED_RANK_COLS
            if c in delta_df.columns
        ]
        merged = merged.merge(delta_df[keep].drop_duplicates("name"), on="name", how="left")
    return merged


def serialize_strength_signals(snap_df: pd.DataFrame, delta_df: pd.DataFrame,
                               top_n: int = None) -> str:
    """All-green breadth, the all-green names, and sustained-strength leaders."""
    if snap_df.empty or "name" not in snap_df.columns:
        return "STRENGTH SIGNALS:\n  Not enough data yet."
    merged = _strength_frame(snap_df, delta_df)
    mask, available = _all_green_mask(merged)
    if mask is None:
        return "STRENGTH SIGNALS:\n  No performance columns available."

    n_total = len(merged)
    all_green = merged[mask].copy()
    lines = [
        "STRENGTH SIGNALS:",
        f"  Breadth: {len(all_green)} of {n_total} groups are all-green "
        f"(positive across {', '.join(tf.replace('perf_', '') for tf in available)}).",
    ]
    if not all_green.empty:
        if "momentum_score" in all_green.columns:
            all_green = all_green.sort_values("momentum_score", ascending=False)
        names = []
        for _, r in all_green.head(8).iterrows():
            ms = r.get("momentum_score")
            names.append(str(r["name"]) + (f" (momentum {ms:.2f})" if pd.notna(ms) else ""))
        lines.append("  All-green: " + "; ".join(names))

    if all(c in merged.columns for c in SUSTAINED_RANK_COLS):
        if top_n is None:
            top_n = max(3, n_total // 4)
        sustained = merged[
            (merged["rank_month"] <= top_n)
            & (merged["rank_quarter"] <= top_n)
            & (merged["rank_half"] <= top_n)
        ].copy()
        if not sustained.empty:
            if "momentum_score" in sustained.columns:
                sustained = sustained.sort_values("momentum_score", ascending=False)
            lines.append(
                f"  Sustained strong (top {top_n} across 1/3/6-month rank): "
                + ", ".join(str(nm) for nm in sustained["name"].head(8))
            )
    return "\n".join(lines)


def serialize_momentum_laggards(delta_df: pd.DataFrame, n: int = 5) -> str:
    if delta_df.empty or "momentum_score" not in delta_df.columns:
        return "No momentum data available."
    valid = delta_df.dropna(subset=["momentum_score"]).sort_values(
        "momentum_score", ascending=True
    )
    if valid.empty:
        return "No momentum data available."
    lines = ["MOMENTUM LAGGARDS (score 0=weakest, 1=strongest):"]
    for _, r in valid.head(n).iterrows():
        rank_ytd = r.get("rank_ytd")
        rank_str = f"{rank_ytd:.0f}" if pd.notna(rank_ytd) else "N/A"
        lines.append(f"  {r['name']}: {r['momentum_score']:.3f} (rank_ytd={rank_str})")
    return "\n".join(lines)


def serialize_divergences(snap_df: pd.DataFrame, delta_df: pd.DataFrame) -> str:
    """Rank/momentum conflicts — the early-warning signal no other tab shows."""
    if delta_df.empty or "momentum_score" not in delta_df.columns \
            or SHORT_DELTA_COL not in delta_df.columns:
        return "DIVERGENCES:\n  Not enough history for divergence signals yet."
    d = delta_df.dropna(subset=["momentum_score"]).copy()
    if d.empty:
        return "DIVERGENCES:\n  Not enough history for divergence signals yet."
    d[SHORT_DELTA_COL] = pd.to_numeric(d[SHORT_DELTA_COL], errors="coerce")
    median_mom = d["momentum_score"].median()

    lines = ["DIVERGENCES (early-warning):"]
    found = False

    fading = d[(d["momentum_score"] >= _STRONG_MOMENTUM) & (d[SHORT_DELTA_COL] < 0)]
    fading = fading.sort_values(SHORT_DELTA_COL)  # most negative first
    if not fading.empty:
        found = True
        items = [
            f"{r['name']} (momentum {r['momentum_score']:.2f}, rank {r[SHORT_DELTA_COL]:+.0f} in {SHORT_WIN}d)"
            for _, r in fading.head(5).iterrows()
        ]
        lines.append("  Fading (strong momentum, rank slipping): " + "; ".join(items))

    emerging = d[(d[SHORT_DELTA_COL] >= _RANK_JUMP_SHORT) & (d["momentum_score"] < median_mom)]
    emerging = emerging.sort_values(SHORT_DELTA_COL, ascending=False)
    if not emerging.empty:
        found = True
        items = [
            f"{r['name']} (rank {r[SHORT_DELTA_COL]:+.0f} in {SHORT_WIN}d, momentum {r['momentum_score']:.2f})"
            for _, r in emerging.head(5).iterrows()
        ]
        lines.append("  Emerging (rank jumping, momentum still low): " + "; ".join(items))

    if "rank_agreement" in d.columns and not snap_df.empty and "name" in snap_df.columns:
        mask, _ = _all_green_mask(snap_df)
        if mask is not None:
            green_names = set(snap_df[mask]["name"])
            agree = pd.to_numeric(d["rank_agreement"], errors="coerce")
            fragile = d[d["name"].isin(green_names) & (agree < _LOW_AGREEMENT)]
            fragile = fragile.assign(_a=agree).sort_values("_a")
            if not fragile.empty:
                found = True
                items = [
                    f"{r['name']} (agreement {r['rank_agreement']:.2f})"
                    for _, r in fragile.head(5).iterrows()
                ]
                lines.append("  Fragile all-green (green but unstable rank): " + "; ".join(items))

    if not found:
        lines.append("  No notable divergences today.")
    return "\n".join(lines)


def _perf_lookup(snap_df: pd.DataFrame, cols):
    """name -> {col: value} map for the requested perf columns (empty if absent).

    Uses set_index/to_dict instead of iterrows; no behaviour change, but avoids
    the O(n) Python loop over DataFrame rows.
    """
    if snap_df is None or snap_df.empty or "name" not in snap_df.columns:
        return {}
    have = [c for c in cols if c in snap_df.columns]
    if not have:
        return {}
    return (
        snap_df.drop_duplicates("name")
        .set_index("name")[have]
        .to_dict("index")
    )


def serialize_breadth_metrics(snap_df: pd.DataFrame, delta_df: pd.DataFrame) -> str:
    """Quantified market-state numbers for the Conviction call so the model rates
    conviction from real figures, not a guess: all-green breadth %, mean rank
    agreement, and the momentum-accel build/fade split."""
    if snap_df.empty or "name" not in snap_df.columns:
        return "MARKET STATE:\n  Not enough data yet."
    merged = _strength_frame(snap_df, delta_df)
    mask, available = _all_green_mask(merged)
    n_total = len(merged)
    lines = ["MARKET STATE (quantified — use these to set the Conviction level):"]
    if mask is not None and n_total:
        n_green = int(mask.sum())
        lines.append(
            f"  All-green breadth: {n_green}/{n_total} ({100 * n_green / n_total:.0f}%) "
            f"positive across {', '.join(tf.replace('perf_', '') for tf in available)}."
        )
    if delta_df is not None and not delta_df.empty and "rank_agreement" in delta_df.columns:
        agree = pd.to_numeric(delta_df["rank_agreement"], errors="coerce").dropna()
        if not agree.empty:
            lines.append(
                f"  Mean rank agreement: {agree.mean():.2f} "
                f"(1 = timeframes unanimous, 0 = conflicting)."
            )
    if delta_df is not None and not delta_df.empty and "momentum_accel" in delta_df.columns:
        acc = pd.to_numeric(delta_df["momentum_accel"], errors="coerce").dropna()
        if not acc.empty:
            building = int((acc > 0.02).sum())
            fading = int((acc < -0.02).sum())
            lines.append(
                f"  Momentum accel: {building} groups building, {fading} fading "
                f"(of {len(acc)} with data)."
            )
    return "\n".join(lines)


def serialize_rotation_pairs(snap_df: pd.DataFrame, delta_df: pd.DataFrame, n: int = 5) -> str:
    """Capital-flow framing with the metric context the model needs to assert a
    REAL out->in pairing instead of inventing one: each leaving/arriving group is
    annotated with its week/month perf, rs_slope, regime, and any RS cross."""
    if delta_df.empty or SHORT_DELTA_COL not in delta_df.columns:
        return "ROTATION FLOW:\n  Not enough history for rotation signals yet."
    d = delta_df.copy()
    d[SHORT_DELTA_COL] = pd.to_numeric(d[SHORT_DELTA_COL], errors="coerce")
    perf = _perf_lookup(snap_df, ["perf_week", "perf_month"])
    valid = d.dropna(subset=[SHORT_DELTA_COL])
    if valid.empty:
        return "ROTATION FLOW:\n  Not enough history for rotation signals yet."

    def _metrics(r):
        bits = []
        pm = perf.get(r["name"], {})
        for col, lbl in (("perf_week", "wk"), ("perf_month", "mo")):
            v = pm.get(col)
            if pd.notna(v):
                bits.append(f"{lbl}={v:+.1f}%")
        if "rs_slope" in r and pd.notna(r.get("rs_slope")):
            bits.append(f"rs_slope={r['rs_slope']:+.3f}")
        if "regime_short_long" in r and pd.notna(r.get("regime_short_long")):
            bits.append(f"regime={r['regime_short_long']:+.2f}")
        if "rs_cross" in r and pd.notna(r.get("rs_cross")) and float(r["rs_cross"]) > 0:
            bits.append("RS-cross-up")
        return (", " + ", ".join(bits)) if bits else ""

    take = min(n, len(valid))
    leaving = valid.nsmallest(take, SHORT_DELTA_COL)   # rank slipping = capital leaving
    arriving = valid.nlargest(take, SHORT_DELTA_COL)   # rank rising = capital arriving
    lines = [f"ROTATION FLOW (rank change over {SHORT_WIN} sessions; "
             f"regime>0 = short-horizon leader, <0 = fading):"]
    lines.append("  OUTFLOWS — capital leaving (rank slipping):")
    for _, r in leaving.iterrows():
        lines.append(f"    {r['name']}: {r[SHORT_DELTA_COL]:+.0f} spots{_metrics(r)}")
    lines.append("  INFLOWS — capital arriving (rank rising):")
    for _, r in arriving.iterrows():
        lines.append(f"    {r['name']}: {r[SHORT_DELTA_COL]:+.0f} spots{_metrics(r)}")
    return "\n".join(lines)


# RS (relative-strength vs SPY) columns produced by compute_deltas. NaN when the
# benchmark snapshot lacks a row for the date — handled gracefully below.
_RS_BEAT_COLS = ["beats_benchmark_week", "beats_benchmark_month",
                 "beats_benchmark_quarter", "beats_benchmark_half",
                 "beats_benchmark_year", "beats_benchmark_ytd", "beats_benchmark_day"]


def serialize_rs_signals(delta_df: pd.DataFrame, n: int = 6) -> str:
    """Absolute outperformance vs the S&P 500: rs_score AND rs_confirmed (breadth
    gated by directional consistency), how many of the 7 timeframes each beats SPY
    on, plus fresh RS new-highs and RS crosses. A rising tide does NOT inflate these."""
    if delta_df.empty or "rs_score" not in delta_df.columns:
        return "RELATIVE STRENGTH vs S&P:\n  No benchmark (SPY) data available for this date."
    d = delta_df.copy()
    d["rs_score"] = pd.to_numeric(d["rs_score"], errors="coerce")
    valid = d.dropna(subset=["rs_score"])
    if valid.empty:
        return "RELATIVE STRENGTH vs S&P:\n  No benchmark (SPY) data available for this date."

    beat_cols = [c for c in _RS_BEAT_COLS if c in valid.columns]
    has_conf = "rs_confirmed" in valid.columns

    def _beats(r):
        if not beat_cols:
            return "N/A"
        cnt = sum(1 for c in beat_cols if pd.notna(r.get(c)) and float(r[c]) > 0)
        return f"{cnt}/{len(beat_cols)} timeframes"

    lines = ["RELATIVE STRENGTH vs S&P (rs_score = fraction of 7 timeframes beating SPY; "
             "rs_confirmed gates that by directional consistency):"]
    leaders = valid.sort_values("rs_score", ascending=False).head(n)
    for _, r in leaders.iterrows():
        conf = f", rs_confirmed {r['rs_confirmed']:.2f}" if has_conf and pd.notna(r.get("rs_confirmed")) else ""
        lines.append(f"  {r['name']}: rs_score {r['rs_score']:.2f}{conf}, beats SPY on {_beats(r)}")

    if "rs_new_high" in valid.columns:
        nh = valid[pd.to_numeric(valid["rs_new_high"], errors="coerce") > 0]
        if not nh.empty:
            lines.append("  RS new highs (20-session): " + ", ".join(nh["name"].head(8)))
    if "rs_cross" in valid.columns:
        cx = valid[pd.to_numeric(valid["rs_cross"], errors="coerce") > 0]
        if not cx.empty:
            lines.append("  RS crosses (just turned positive vs SPY): " + ", ".join(cx["name"].head(8)))
    return "\n".join(lines)


def serialize_watchlist_candidates(snap_df: pd.DataFrame, delta_df: pd.DataFrame,
                                   n: int = 8) -> str:
    """Pre-labelled watch candidates, each tagged with its TRIGGER TYPE so the model
    names the specific reason instead of a generic 'watch for confirmation'. Triggers,
    in priority order: RS cross, RS new high, emerging divergence, fading divergence."""
    if delta_df.empty:
        return "WATCHLIST CANDIDATES:\n  Not enough data yet."
    d = delta_df.copy()
    for c in (SHORT_DELTA_COL, "momentum_score", "momentum_accel", "rank_trend_slope",
              "rs_cross", "rs_new_high"):
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors="coerce")

    picked = {}  # name -> label (first/highest-priority trigger wins)

    # Per-category cap so one common trigger (e.g. RS new highs in a broad rally)
    # can't flood the list and crowd out the rarer emerging/fading signals.
    _PER_TRIGGER_CAP = 3

    def _add(name, label):
        if name not in picked:
            picked[name] = label

    if "rs_cross" in d.columns:
        for _, r in d[d["rs_cross"] > 0].head(_PER_TRIGGER_CAP).iterrows():
            _add(r["name"], "rs_cross: RS just flipped positive vs SPY (earliest rotation trigger)")
    if "rs_new_high" in d.columns:
        for _, r in d[d["rs_new_high"] > 0].head(_PER_TRIGGER_CAP).iterrows():
            _add(r["name"], "rs_new_high: RS at a 20-session high (IBD-style leadership)")

    if "momentum_score" in d.columns and SHORT_DELTA_COL in d.columns:
        valid = d.dropna(subset=["momentum_score"])
        if not valid.empty:
            med = valid["momentum_score"].median()
            emerging = valid[(valid[SHORT_DELTA_COL] >= _RANK_JUMP_SHORT)
                             & (valid["momentum_score"] < med)]
            for _, r in emerging.sort_values(SHORT_DELTA_COL, ascending=False).head(_PER_TRIGGER_CAP).iterrows():
                accel = f", accel {r['momentum_accel']:+.2f}" if "momentum_accel" in r and pd.notna(r.get("momentum_accel")) else ""
                _add(r["name"], f"emerging: rank {r[SHORT_DELTA_COL]:+.0f} in {SHORT_WIN}d but momentum still {r['momentum_score']:.2f}{accel}")

            fading = valid[(valid["momentum_score"] >= _STRONG_MOMENTUM)
                           & (valid[SHORT_DELTA_COL] < 0)]
            for _, r in fading.sort_values(SHORT_DELTA_COL).head(_PER_TRIGGER_CAP).iterrows():
                slope = f", trend_slope {r['rank_trend_slope']:+.3f}" if "rank_trend_slope" in r and pd.notna(r.get("rank_trend_slope")) else ""
                _add(r["name"], f"fading: strong momentum {r['momentum_score']:.2f} but rank {r[SHORT_DELTA_COL]:+.0f} in {SHORT_WIN}d{slope}")

    if not picked:
        return "WATCHLIST CANDIDATES:\n  No standout triggers today."
    lines = ["WATCHLIST CANDIDATES (each tagged with its trigger type):"]
    for name, label in list(picked.items())[:n]:
        lines.append(f"  - {name} [{label}]")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Focused briefing prompts (one job each — better adherence than one mega-prompt)
# ---------------------------------------------------------------------------

def build_pulse_prompt(group_type: str, snap_df: pd.DataFrame,
                       delta_df: pd.DataFrame, date_str: str) -> str:
    """Headline + Conviction. Fed quantified breadth so the rating is grounded."""
    group_name = "sectors" if group_type == "sector" else "industries"
    state = serialize_breadth_metrics(snap_df, delta_df)
    movers = serialize_top_movers(delta_df, n=5)
    divergences = serialize_divergences(snap_df, delta_df)
    return f"""You are a markets strategist summarizing US {group_name} for {date_str}.

Use ONLY the data below. Do not invent numbers or {group_name} not present.

Respond in Markdown with EXACTLY these two `##` sections, in order, nothing before the first header, no `###`:

## Headline
One punchy line, 12 words or fewer, capturing today's single most important {group_name} takeaway. No bullet, no bold.

## Conviction
Exactly two lines:
Level: <one of High, Medium, Low>
Why: <one sentence citing the breadth %, mean agreement, and divergence count>

Set the level by these thresholds (use the MARKET STATE numbers):
- High: all-green breadth >55% AND mean rank agreement >0.65 AND few divergences.
- Low: all-green breadth <30% OR many fading divergences.
- Medium: anything in between.

DATA:
{state}

{movers}

{divergences}"""


def build_rotation_map_prompt(group_type: str, snap_df: pd.DataFrame,
                              delta_df: pd.DataFrame, date_str: str) -> str:
    """Rotation Map only — with a strict pairing guardrail and an escape hatch."""
    group_name = "sectors" if group_type == "sector" else "industries"
    rotation = serialize_rotation_pairs(snap_df, delta_df, n=5)
    return f"""You are a sector-rotation analyst describing capital flow across US {group_name} for {date_str}.

Use ONLY the ROTATION FLOW data below. Do not invent numbers or {group_name} not present.

Write Markdown (no header, no preamble). Prefer 2-4 bullets of the form:
`- OUT: <group> -> IN: <group> - <one-clause reason citing the metrics>`

PAIRING RULE: only pair an OUT group with an IN group when their metrics suggest a linked trade (e.g. a cyclical rotating in as a defensive rotates out, or a clear leadership handoff). NEVER pair {group_name} that have no plausible economic relationship. If no clean pairing exists, instead list them under two plain lines:
`Outflows:` then bullets, and `Inflows:` then bullets.
If fewer than 2 groups are in either list, write exactly `- Insufficient rotation signal today.` as the only line.

ROTATION DATA:
{rotation}"""


def build_watchlist_prompt(group_type: str, snap_df: pd.DataFrame,
                           delta_df: pd.DataFrame, date_str: str) -> str:
    """Watchlist only — fed pre-labelled candidates so triggers stay specific."""
    group_name = "sectors" if group_type == "sector" else "industries"
    candidates = serialize_watchlist_candidates(snap_df, delta_df, n=8)
    return f"""You are building a watchlist of US {group_name} to monitor into the next session, dated {date_str}.

Use ONLY the candidates below — do not add {group_name} that are not listed. Pick the 3-5 most actionable.

Write 3-5 Markdown bullets, each `- <group> - <the specific thing to watch, naming the trigger type and what would confirm or invalidate it>`. Name the trigger explicitly (RS cross, RS new high, emerging, or fading). Do not restate already-obvious leaders without a fresh trigger. If there are no candidates, write exactly `- No standout watch candidates today.`

WATCHLIST CANDIDATES:
{candidates}"""


def build_risk_radar_prompt(group_type: str, snap_df: pd.DataFrame,
                            delta_df: pd.DataFrame, date_str: str) -> str:
    """Relative Strength summary + Risks & Fragility, both from RS + divergence data."""
    group_name = "sectors" if group_type == "sector" else "industries"
    rs = serialize_rs_signals(delta_df, n=6)
    divergences = serialize_divergences(snap_df, delta_df)
    return f"""You are a risk-aware markets analyst covering US {group_name} for {date_str}.

Use ONLY the data below. Do not invent numbers or {group_name} not present.

Respond in Markdown with EXACTLY these two `##` sections, in order, nothing before the first header, no `###`:

## Relative Strength
1-2 sentences on which {group_name} are genuinely beating the S&P 500 — cite rs_score / rs_confirmed and the beats-SPY timeframe counts, and call out any RS new highs or crosses. If no benchmark data is available, say so in one line.

## Risks
2-4 bullets on fragile or fading setups: strong momentum with a slipping rank, all-green {group_name} with low rank agreement, or crowded leadership. Cite the numbers. If none, write exactly `- No notable risks today.`

DATA:
{rs}

{divergences}"""


# ---------------------------------------------------------------------------
# Briefing response parsers — tolerant markdown-section splitters
# ---------------------------------------------------------------------------

def _split_markdown_sections(text: str, alias_map) -> dict:
    """Split `## `-delimited markdown into {canonical_key: body}. Tolerant of
    `###`/`####`, preamble before the first header, and renamed headers (via the
    alias_map). Omitted sections are simply absent keys (never empty strings).

    alias_map: list of (canonical_key, tuple_of_lowercase_aliases) pairs, e.g.:
        [("headline", ("headline", "tl;dr")), ("conviction", ("conviction",))]
    """
    text = (text or "").strip()
    if not text:
        return {}
    # Build reverse alias -> key lookup.
    rev = {}
    for key, aliases in alias_map:
        for a in aliases:
            rev[a] = key
    normalized = re.sub(r"^#{2,}\s+", "## ", text, flags=re.MULTILINE)
    sections, current, buf = {}, None, []

    def _flush():
        if current and buf:
            body = "\n".join(buf).strip()
            if body:
                sections[current] = body

    for line in normalized.split("\n"):
        m = re.match(r"^##\s+(.*)$", line.strip())
        if m:
            _flush()
            buf = []
            current = rev.get(m.group(1).strip().lower().rstrip(":").strip())
        elif current:
            buf.append(line)
    _flush()
    return sections


_PULSE_ALIASES = [
    ("headline", ("headline", "daily headline", "tl;dr")),
    ("conviction", ("conviction", "conviction meter")),
]
_RISK_ALIASES = [
    ("relative_strength", ("relative strength", "relative strength vs s&p", "rs", "vs market")),
    ("risks", ("risks", "risks & fragility", "risks and fragility", "fragility")),
]


def parse_pulse_response(text: str) -> dict:
    """Parse the pulse call into {headline, conviction:{level,why}}."""
    sections = _split_markdown_sections(text, _PULSE_ALIASES)
    if "conviction" in sections:
        sections["conviction"] = _parse_conviction(sections["conviction"])
    return sections


def parse_risk_radar_response(text: str) -> dict:
    """Parse the risk-radar call into {relative_strength, risks}."""
    return _split_markdown_sections(text, _RISK_ALIASES)


def _parse_conviction(body: str) -> dict:
    """Parse the conviction body into {level, why}. Tolerant of missing prefixes:
    falls back to a word-boundary scan for a High/Medium/Low token (so a phrase
    like 'Medium-term risk' in a Why line does NOT get mistaken for the level)."""
    result = {"level": "", "why": ""}
    for line in body.split("\n"):
        low = line.strip().lower()
        if low.startswith("level:"):
            result["level"] = line.split(":", 1)[1].strip()
        elif low.startswith("why:") or low.startswith("reasoning:"):
            result["why"] = line.split(":", 1)[1].strip()
    if not result["level"]:
        # Only scan lines that aren't the Why line, with word boundaries.
        for line in body.split("\n"):
            if line.strip().lower().startswith("why:"):
                continue
            m = re.search(r"\b(High|Medium|Low)\b", line, re.IGNORECASE)
            if m:
                result["level"] = m.group(1).capitalize()
                break
    if not result["why"]:
        for line in body.split("\n"):
            s = line.strip()
            if s and not s.lower().startswith("level:"):
                result["why"] = s
                break
    return result


def build_note_prompt(group_type: str, snap_df: pd.DataFrame,
                      delta_df: pd.DataFrame, date_str: str) -> str:
    """The single combined prompt: a freeform markdown daily note built ONLY from
    our computed signals (the analytical moat over the plain Finviz groups page)."""
    group_name = "sectors" if group_type == "sector" else "industries"
    strength = serialize_strength_signals(snap_df, delta_df)
    movers = serialize_top_movers(delta_df, n=8)
    leaders = serialize_momentum_leaders(delta_df, n=5)
    laggards = serialize_momentum_laggards(delta_df, n=5)
    divergences = serialize_divergences(snap_df, delta_df)
    return f"""You are a markets analyst writing a concise daily note on US {group_name} for {date_str}.

Write in Markdown, using ONLY the computed signals below. Do not invent numbers or {group_name} not present in the data.

Structure:
- Start with one line: `**TL;DR:**` followed by the single most important takeaway.
- Then 1-2 short narrative paragraphs on what is leading, rotating, and fading.
- Then exactly these three sections, each a `##` header followed by 2-4 tight bullets:
  ## Strength
  ## Movers & Momentum
  ## Divergences

Name specific {group_name} and cite the numbers from the signals. Be concise and concrete. No preamble, no disclaimers, no meta commentary about the data or being an AI.

COMPUTED SIGNALS:
{strength}

{movers}

{leaders}

{laggards}

{divergences}"""


def build_phase_prompt(snap_df: pd.DataFrame, delta_df: pd.DataFrame, date_str: str) -> str:
    """Lightweight plain-text phase classifier (sectors only) for the history strip."""
    strength = serialize_strength_signals(snap_df, delta_df)
    leaders = serialize_momentum_leaders(delta_df, n=5)
    return f"""You are a macro analyst specializing in sector rotation. Classify the current US market rotation phase for {date_str}.

Classic phases:
- Early Cycle: Financials, Consumer Discretionary leading
- Mid Cycle: Industrials, Materials, Technology leading
- Late Cycle: Energy, Materials leading; Utilities/Healthcare lagging
- Defensive: Utilities, Healthcare, Consumer Staples leading; Cyclicals lagging

DATA:
{strength}

{leaders}

Respond in exactly two plain-text lines (no code blocks, no markdown):
Label: <exactly one of Early Cycle, Mid Cycle, Late Cycle, Defensive>
Why: <one sentence naming which sectors are leading and why it fits>"""


# ---------------------------------------------------------------------------
# Response parsers
# ---------------------------------------------------------------------------

def parse_phase_response(text: str) -> dict:
    """Parse the two-line plain-text phase response into {label, reasoning}.
    Tolerant: if the `Label:` / `Why:` prefixes are absent, treat the first
    non-empty line as the label and the rest as reasoning. Empty label means
    "no phase" (the frontend skips the card / strip pill) — never "Unknown"."""
    text = (text or "").strip()
    result = {"label": "", "reasoning": ""}
    for line in text.split("\n"):
        line = line.strip()
        low = line.lower()
        if low.startswith("label:"):
            result["label"] = line.split(":", 1)[1].strip()
        elif low.startswith("why:") or low.startswith("reasoning:"):
            result["reasoning"] = line.split(":", 1)[1].strip()
    if not result["label"]:
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        if lines:
            result["label"] = lines[0]
            result["reasoning"] = result["reasoning"] or " ".join(lines[1:])
    return result


# ---------------------------------------------------------------------------
# Task registry — single source of truth for what to generate and for whom
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Input-block builders (Tier-1 provenance) — same data as the prompts, no instructions
# ---------------------------------------------------------------------------
# Each function mirrors the serializer calls made by the corresponding build_*_prompt(),
# returning the raw data block that the model actually sees. This is what powers the
# PWA "Behind this" provenance drawer and --preview mode.

def _input_note(group_type: str, snap_df: pd.DataFrame, delta_df: pd.DataFrame) -> str:
    parts = [
        serialize_strength_signals(snap_df, delta_df),
        serialize_top_movers(delta_df, n=8),
        serialize_momentum_leaders(delta_df, n=5),
        serialize_momentum_laggards(delta_df, n=5),
        serialize_divergences(snap_df, delta_df),
    ]
    return "\n\n".join(p for p in parts if p)


def _input_phase(snap_df: pd.DataFrame, delta_df: pd.DataFrame) -> str:
    parts = [
        serialize_strength_signals(snap_df, delta_df),
        serialize_momentum_leaders(delta_df, n=5),
    ]
    return "\n\n".join(p for p in parts if p)


def _input_pulse(group_type: str, snap_df: pd.DataFrame, delta_df: pd.DataFrame) -> str:
    parts = [
        serialize_breadth_metrics(snap_df, delta_df),
        serialize_top_movers(delta_df, n=5),
        serialize_divergences(snap_df, delta_df),
    ]
    return "\n\n".join(p for p in parts if p)


def _input_rotation_map(group_type: str, snap_df: pd.DataFrame, delta_df: pd.DataFrame) -> str:
    return serialize_rotation_pairs(snap_df, delta_df, n=5)


def _input_watchlist(group_type: str, snap_df: pd.DataFrame, delta_df: pd.DataFrame) -> str:
    return serialize_watchlist_candidates(snap_df, delta_df, n=8)


def _input_risk_radar(group_type: str, snap_df: pd.DataFrame, delta_df: pd.DataFrame) -> str:
    parts = [
        serialize_rs_signals(delta_df, n=6),
        serialize_divergences(snap_df, delta_df),
    ]
    return "\n\n".join(p for p in parts if p)


def _build_input_blocks(spec: dict, group_type: str, snap_df, delta_df) -> str:
    """Return the serialized data block for a task — what the model sees, sans instructions."""
    fn = spec.get("input_fn")
    if fn is None:
        return ""
    if spec.get("pass_group_type"):
        return fn(group_type, snap_df, delta_df)
    return fn(snap_df, delta_df)


def _build_prompt(spec: dict, group_type: str, snap_df, delta_df, date_str: str) -> str:
    fn = spec["build_prompt"]
    if spec.get("pass_group_type"):
        return fn(group_type, snap_df, delta_df, date_str)
    return fn(snap_df, delta_df, date_str)


# TASK_SPECS — one entry per AI call.  Each entry drives one Gemini call per
# group type listed in "group_types".  Total call count per daily run:
#
#   note          × 2 (sector + industry)  = 2 calls
#   rotation_phase × 1 (sector only)       = 1 call
#   pulse          × 2                     = 2 calls
#   rotation_map   × 2                     = 2 calls
#   watchlist      × 2                     = 2 calls
#   risk_radar     × 2                     = 2 calls
#                                  TOTAL   = 11 calls/run × 3 runs/day = ~33/day
#
# This is intentionally more calls than the original single-call design.  Each
# task has its own focused prompt and purpose-curated input, so adherence and
# output quality are much better.  The cost increase is acceptable on Vertex AI
# (no per-day request ceiling; pay-per-token).  If budget becomes a concern,
# the four briefing tasks (pulse/rotation_map/watchlist/risk_radar) can be
# collapsed back into one call by merging their prompts and re-adding a combined
# parser — see git history for the pre-refactor design.
TASK_SPECS = [
    {
        "name": "note",
        "group_types": ("sector", "industry"),
        "build_prompt": build_note_prompt,
        "input_fn": _input_note,
        "pass_group_type": True,
        "generation_config": {"temperature": 0.6},
    },
    {
        "name": "rotation_phase",
        "group_types": ("sector",),   # sectors only — no industry-level phase
        "build_prompt": build_phase_prompt,
        "input_fn": _input_phase,
        "generation_config": {"temperature": 0.2},
    },
    # ---- Focused briefing tasks (one job per call) ---------------------------
    # On Vertex AI there is no per-day request ceiling, so the single mega-call
    # is split into four: pulse (headline+conviction), rotation_map, watchlist,
    # and risk_radar (RS+risks).  Each prompt does one job, which dramatically
    # improves section adherence and isolates failures (a bad watchlist response
    # doesn't corrupt the rotation map).  Low temps on structural tasks keep the
    # bullet/label syntax stable; pulse/risk allow a little more creativity.
    {
        "name": "pulse",
        # headline: one punchy line. conviction: High/Med/Low + one-sentence why.
        # Parsed into {headline: str, conviction: {level: str, why: str}}.
        "group_types": ("sector", "industry"),
        "build_prompt": build_pulse_prompt,
        "input_fn": _input_pulse,
        "pass_group_type": True,
        "parse": parse_pulse_response,
        "generation_config": {"temperature": 0.4},
    },
    {
        "name": "rotation_map",
        # Freeform markdown string — OUT->IN pairing bullets, or plain
        # Outflows/Inflows lists when no clean economic pairing exists.
        "group_types": ("sector", "industry"),
        "build_prompt": build_rotation_map_prompt,
        "input_fn": _input_rotation_map,
        "pass_group_type": True,
        "generation_config": {"temperature": 0.25},
    },
    {
        "name": "watchlist",
        # Freeform markdown — 3-5 bullets, each group tagged with its trigger
        # type (rs_cross / rs_new_high / emerging / fading).
        "group_types": ("sector", "industry"),
        "build_prompt": build_watchlist_prompt,
        "input_fn": _input_watchlist,
        "pass_group_type": True,
        "generation_config": {"temperature": 0.25},
    },
    {
        "name": "risk_radar",
        # Parsed into {relative_strength: str, risks: str} — two sections from
        # one call since they both draw on RS + divergence data.
        "group_types": ("sector", "industry"),
        "build_prompt": build_risk_radar_prompt,
        "input_fn": _input_risk_radar,
        "pass_group_type": True,
        "parse": parse_risk_radar_response,
        "generation_config": {"temperature": 0.4},
    },
]


def _expected_fields() -> list:
    seen = {}
    for spec in TASK_SPECS:
        for gtype in spec["group_types"]:
            prefix = "sectors" if gtype == "sector" else "industries"
            seen[f"{prefix}.{spec['name']}"] = True
    return list(seen)


def _is_complete(data: dict) -> bool:
    for field in _expected_fields():
        prefix, name = field.split(".", 1)
        if not data.get(prefix, {}).get(name):
            return False
    return True


def _missing_fields(data: dict) -> list:
    missing = []
    for field in _expected_fields():
        prefix, name = field.split(".", 1)
        if not data.get(prefix, {}).get(name):
            missing.append(field)
    return missing


# ---------------------------------------------------------------------------
# API call helper
# ---------------------------------------------------------------------------

def _call_api(client, prompt: str, max_retries: int = 3,
              generation_config: dict = None) -> CallResult:
    """Call Gemini for freeform text with rate-limit spacing and retry.

    No JSON mode, no response schema, no max_output_tokens — the model writes a
    markdown note and we display it verbatim. Only the temperature is set.

    Returns CallResult(text, usage, latency) instead of a bare string so callers
    can forward usage/latency to _record_capture() without side-channel globals.
    """
    global _last_api_call, _api_call_count, _rate_limit_hits
    elapsed = time.monotonic() - _last_api_call
    if elapsed < _INTER_CALL_DELAY:
        time.sleep(_INTER_CALL_DELAY - elapsed)

    extra = {}
    if generation_config:
        from google.genai import types  # noqa: PLC0415 — lazy; google-genai only required at runtime
        cfg_kwargs = {"temperature": generation_config.get("temperature", 0.6)}
        if generation_config.get("max_output_tokens"):
            cfg_kwargs["max_output_tokens"] = generation_config["max_output_tokens"]
        extra["config"] = types.GenerateContentConfig(**cfg_kwargs)

    _api_call_count += 1
    call_start = time.monotonic()
    for attempt in range(max_retries + 1):
        _last_api_call = time.monotonic()
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL, contents=prompt, **extra
            )
            # Handle None or whitespace-only response text (transient API error)
            if not response.text or not response.text.strip():
                raise ValueError("empty response (503-like transient error)")

            return CallResult(
                text=response.text.strip(),
                usage=_extract_usage(response),
                latency=time.monotonic() - call_start,
            )
        except Exception as e:
            err_str = str(e)
            # Daily quota is not recoverable by retrying — abort immediately.
            if "GenerateRequestsPerDayPerProjectPerModel" in err_str:
                raise DailyQuotaExhaustedError(err_str) from e
            is_retryable = (
                "429" in err_str or "quota" in err_str.lower() or "resource_exhausted" in err_str.lower()
                or "503" in err_str or "unavailable" in err_str.lower()
                or "empty response" in err_str.lower()
            )
            if is_retryable and attempt < max_retries:
                _rate_limit_hits += 1
                wait = _RETRY_BASE_DELAY * (2 ** attempt)  # 30s, 60s, 120s
                print(f"    Transient error, waiting {wait}s (attempt {attempt + 1}/{max_retries + 1})...")
                time.sleep(wait)
                continue
            raise


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def generate_for_group(client, group_type: str, date_str: str, existing=None) -> dict:
    result = dict(existing or {})
    key_prefix = "sectors" if group_type == "sector" else "industries"
    snap_df = load_latest_snapshot(group_type)
    delta_df = load_latest_delta(group_type)

    applicable = [s for s in TASK_SPECS if group_type in s["group_types"]]

    if snap_df.empty:
        print(f"  [{group_type}] No snapshot data — skipping.")
        for spec in applicable:
            fkey = f"{key_prefix}.{spec['name']}"
            if fkey not in _field_log:
                status = "skipped" if spec["name"] in result else "no_data"
                _record_field(fkey, status, was_new=False)
        return result

    for spec in applicable:
        fkey = f"{key_prefix}.{spec['name']}"
        if spec["name"] in result:
            _record_field(fkey, "skipped", was_new=False)
            continue
        print(f"  [{group_type}] Generating {spec['name']}...")
        t0 = time.monotonic()
        input_blocks = _build_input_blocks(spec, group_type, snap_df, delta_df)
        prompt = _build_prompt(spec, group_type, snap_df, delta_df, date_str)
        try:
            call_result = _call_api(
                client, prompt,
                generation_config=spec.get("generation_config"),
            )
            raw = call_result.text
            parsed_data = None
            if spec["name"] == "rotation_phase":
                parsed_data = parse_phase_response(raw)
                result["rotation_phase"] = parsed_data
            elif spec.get("parse"):
                # Structured task: store the parsed section dict, not raw text, so
                # the frontend reads typed fields. A non-empty result also keeps
                # _is_complete honest (an empty parse must not mark the field done).
                parsed_data = spec["parse"](raw)
                if not parsed_data:
                    raise ValueError(f"{spec['name']} response parsed to no sections")
                result[spec["name"]] = parsed_data
            else:  # freeform markdown (note, rotation_map, watchlist) — stored verbatim
                result[spec["name"]] = raw.strip()
            _record_field(fkey, "ok", was_new=True, elapsed=time.monotonic() - t0)
            _record_capture(fkey, input_blocks=input_blocks, prompt=prompt,
                            generation_config=spec.get("generation_config"),
                            raw=raw, parsed=parsed_data, usage=call_result.usage,
                            latency=call_result.latency, status="ok")
        except DailyQuotaExhaustedError:
            _record_field(fkey, "quota_exhausted", was_new=True, elapsed=time.monotonic() - t0)
            _record_capture(fkey, input_blocks=input_blocks, prompt=prompt,
                            generation_config=spec.get("generation_config"),
                            status="quota_exhausted", latency=time.monotonic() - t0)
            raise  # propagate to main() — do not continue generating other fields
        except Exception as e:
            print(f"  [{group_type}] {spec['name']} failed: {e}")
            _record_field(fkey, "error", was_new=True, elapsed=time.monotonic() - t0, error=str(e))
            _record_capture(fkey, input_blocks=input_blocks, prompt=prompt,
                            generation_config=spec.get("generation_config"),
                            status="error", latency=time.monotonic() - t0)

    return result


# ---------------------------------------------------------------------------
# Run artifact writing
# ---------------------------------------------------------------------------

def _write_run_artifacts(outcome: str, was_incremental: bool,
                         run_elapsed: float, date_str: str) -> None:
    """Append one entry to ai_run_log.jsonl and overwrite ai_run_summary.json."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    log_entry = {
        "timestamp": timestamp,
        "run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "trigger": os.environ.get("GITHUB_EVENT_NAME", ""),
        "date": date_str,
        "model": GEMINI_MODEL,
        "backend": _backend,
        "outcome": outcome,
        "was_incremental": was_incremental,
        "elapsed_seconds": round(run_elapsed, 1),
        "api_calls": _api_call_count,
        "rate_limit_hits": _rate_limit_hits,
        "fields": dict(_field_log),
    }
    try:
        log_path = DATA_DIR / "ai_run_log.jsonl"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        print(f"  [log] Failed to write ai_run_log.jsonl: {e}")

    # Sidecar for collect.yml: fields that failed or had no snapshot data
    error_fields = [k for k, v in _field_log.items() if v.get("status") in ("error", "no_data")]
    summary = {"outcome": outcome, "fields_missing": ",".join(error_fields)}
    try:
        with open(DATA_DIR / "ai_run_summary.json", "w", encoding="utf-8") as f:
            json.dump(summary, f)
    except Exception as e:
        print(f"  [log] Failed to write ai_run_summary.json: {e}")


# ---------------------------------------------------------------------------
# Capture tier writers (Phase 1)
# ---------------------------------------------------------------------------

def _prune_tier2() -> None:
    """Remove Tier-2 debug files beyond the CAPTURE_RETENTION_DAYS rolling window.

    Pruned files remain fully recoverable via git history. Called once per run
    after writing the day's Tier-2 file so HEAD stays bounded.
    """
    if not CAPTURE_DIR.exists():
        return
    files = sorted(CAPTURE_DIR.glob("*.json"), reverse=True)
    for old_path in files[CAPTURE_RETENTION_DAYS:]:
        try:
            old_path.unlink()
        except Exception:
            pass


def _write_capture_tiers(date_str: str, capture_on: bool) -> None:
    """Write Tier-1 provenance (always) and Tier-2 debug (when capture_on is True).

    Tier-1 (data/ai/provenance/{date}.json): input data blocks only, committed
    permanently. Powers the PWA "Behind this" drawer.

    Tier-2 (data/ai/debug/{date}.json): full prompt + raw + parsed + usage +
    latency. Committed with rolling CAPTURE_RETENTION_DAYS window in HEAD.
    Enabled via --capture flag or AI_CAPTURE=1 env (ON in CI by default).
    """
    if not _capture_log:
        return

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Tier 1 — provenance: input blocks only, always written
    PROVENANCE_DIR.mkdir(parents=True, exist_ok=True)
    provenance: dict = {"date": date_str, "captured_at": timestamp}
    for fkey, entry in _capture_log.items():
        provenance[fkey] = {"input_blocks": entry.get("input_blocks", "")}
    prov_path = PROVENANCE_DIR / f"{date_str}.json"
    try:
        tmp = prov_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(provenance, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(prov_path)
        print(f"  [capture] Tier-1 provenance → {prov_path.name}")
    except Exception as e:
        print(f"  [capture] Failed to write provenance: {e}")

    if not capture_on:
        return

    # Tier 2 — debug: full forensic record, rolling 30d in HEAD
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    debug: dict = {
        "date": date_str,
        "model": GEMINI_MODEL,
        "backend": _backend,
        "captured_at": timestamp,
        "calls": dict(_capture_log),
    }
    debug_path = CAPTURE_DIR / f"{date_str}.json"
    try:
        tmp = debug_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(debug, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(debug_path)
        print(f"  [capture] Tier-2 debug → {debug_path.name} (rolling {CAPTURE_RETENTION_DAYS}d)")
        _prune_tier2()
    except Exception as e:
        print(f"  [capture] Failed to write debug capture: {e}")


# ---------------------------------------------------------------------------
# Preview mode (Phase 2) — build prompts, no API calls
# ---------------------------------------------------------------------------

def _run_preview(date_str: str, task_filter: str = None,
                 group_filter: str = None, as_json: bool = False) -> None:
    """Build prompts from CSVs, write Tier-1 provenance, print output. No API calls.

    Usage:
        python scripts/generate_ai.py --preview [--date YYYY-MM-DD]
                                                 [--task pulse] [--group sector]
                                                 [--json]
    """
    print(f"[preview] Building prompts for {date_str} — no API calls")

    for group_type in ("sector", "industry"):
        if group_filter and group_type != group_filter:
            continue
        key_prefix = "sectors" if group_type == "sector" else "industries"
        snap_df = load_latest_snapshot(group_type)
        delta_df = load_latest_delta(group_type)

        if snap_df.empty:
            print(f"  [{group_type}] No snapshot data — skipping.")
            continue

        applicable = [s for s in TASK_SPECS if group_type in s["group_types"]]
        if task_filter:
            applicable = [s for s in applicable if s["name"] == task_filter]

        for spec in applicable:
            fkey = f"{key_prefix}.{spec['name']}"
            input_blocks = _build_input_blocks(spec, group_type, snap_df, delta_df)
            prompt = _build_prompt(spec, group_type, snap_df, delta_df, date_str)
            # Populate capture log so Tier-1 provenance is written below
            _capture_log[fkey] = {"input_blocks": input_blocks}

            if as_json:
                print(json.dumps({"fkey": fkey, "prompt": prompt,
                                  "input_blocks": input_blocks}))
            else:
                sep = "=" * 60
                print(f"\n{sep}\n[{fkey}] INPUT BLOCKS:")
                print(input_blocks)
                print(f"\n[{fkey}] FULL PROMPT:")
                print(prompt)

    # Write Tier-1 provenance (no Tier-2 in preview — no API was called)
    _write_capture_tiers(date_str, capture_on=False)


# ---------------------------------------------------------------------------
# Index manifest
# ---------------------------------------------------------------------------

def _update_index(date_str: str, status: str, output: dict) -> None:
    """Upsert one entry in data/ai/index.json so the dashboard/PWA can find the latest file."""
    index_path = AI_DIR / "index.json"
    try:
        existing = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    except (json.JSONDecodeError, OSError):
        existing = {}

    entries = existing.get("entries", [])
    rotation_phase_val = output.get("sectors", {}).get("rotation_phase")
    new_entry = {
        "date": date_str,
        "status": status,
        "model": GEMINI_MODEL,
        "generated_at": output.get("generated_at", ""),
        "rotation_phase": (
            rotation_phase_val.get("label", "")
            if isinstance(rotation_phase_val, dict)
            else ""
        ),
    }

    entries = [e for e in entries if e.get("date") != date_str]
    entries.insert(0, new_entry)
    entries.sort(key=lambda e: e.get("date", ""), reverse=True)
    entries = entries[:90]

    index = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "entries": entries,
    }
    try:
        tmp = index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(index_path)
    except Exception as e:
        print(f"  [index] Failed to write index.json: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    _reset_tracking()
    run_start = time.monotonic()

    parser = argparse.ArgumentParser()
    parser.add_argument("--force-ai", action="store_true",
                        help="Force regeneration even if no new delta data")
    # Phase 2: --preview builds prompts and writes Tier-1 provenance, no API calls
    parser.add_argument("--preview", action="store_true",
                        help="Build prompts from CSVs and print them (no API calls, no creds required)")
    parser.add_argument("--task", default=None,
                        help="With --preview: limit to one task name (e.g. pulse, note)")
    parser.add_argument("--group", default=None, choices=["sector", "industry"],
                        help="With --preview: limit to one group type")
    parser.add_argument("--json", dest="as_json", action="store_true",
                        help="With --preview: print output as JSON")
    # Phase 1: --capture writes Tier-2 debug file; also controlled via AI_CAPTURE env
    parser.add_argument("--capture", action="store_true",
                        help="Write Tier-2 debug capture (full prompt+raw+parsed+usage+latency)")
    args, _ = parser.parse_known_args()
    force = args.force_ai or bool(os.getenv("FORCE_AI"))
    # AI_CAPTURE=1 env is the CI switch; --capture is the CLI switch for local dev
    capture_on = args.capture or bool(os.getenv("AI_CAPTURE"))

    # Use the latest snapshot date as the AI file name so the PWA can match them.
    # The workflow starts at 22:00 UTC but the AI step can run past midnight UTC
    # (due to rate-limit retries), making date.today() return the next calendar
    # day while the snapshot CSV still holds the prior market date.
    snap_df = load_latest_snapshot("sector")
    snap_date = None
    if not snap_df.empty and "date" in snap_df.columns:
        d = snap_df["date"].max()
        if pd.notna(d):
            snap_date = d.isoformat()
    today = snap_date if snap_date else date.today().isoformat()

    # Phase 2: --preview mode — build prompts, write Tier-1, no API calls
    if args.preview:
        _run_preview(today, task_filter=args.task, group_filter=args.group,
                     as_json=args.as_json)
        return

    if not force and not _has_new_delta_data(today):
        print(f"No new delta data for {today} — skipping AI regeneration.")
        _write_run_artifacts("skipped", False, time.monotonic() - run_start, today)
        sys.exit(0)

    use_vertexai = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("1", "true", "yes")
    api_key = os.getenv("GEMINI_API_KEY")
    gcp_project = os.getenv("GOOGLE_CLOUD_PROJECT")
    # Phase 7: Vertex express-key — sidesteps ADC and AI Studio 429s.
    # GOOGLE_API_KEY doubles as a Vertex express key when GOOGLE_GENAI_USE_VERTEXAI=true.
    # Priority: Vertex express key > Vertex ADC > AI Studio key.
    vertex_api_key = os.getenv("GOOGLE_API_KEY")

    # Graceful skip when no backend is configured (exit 0, not error).
    if use_vertexai and not gcp_project and not vertex_api_key:
        print(
            "GOOGLE_GENAI_USE_VERTEXAI=true but neither GOOGLE_CLOUD_PROJECT nor "
            "GOOGLE_API_KEY (Vertex express key) is set — skipping AI generation."
        )
        _write_run_artifacts("no_key", False, time.monotonic() - run_start, today)
        sys.exit(0)
    if not use_vertexai and not api_key:
        print("GEMINI_API_KEY not set — skipping AI generation.")
        _write_run_artifacts("no_key", False, time.monotonic() - run_start, today)
        sys.exit(0)

    try:
        import google.genai as genai
    except ImportError:
        print("google-genai not installed. Run: pip install google-genai")
        _write_run_artifacts("no_key", False, time.monotonic() - run_start, today)
        sys.exit(0)

    global _backend
    if use_vertexai:
        if vertex_api_key:
            # Vertex express-key path: no ADC, no WIF required. Works locally
            # and in CI when GOOGLE_API_KEY is provisioned as a repo secret.
            client = genai.Client(vertexai=True, api_key=vertex_api_key)
            _backend = "vertex_express"
        else:
            # Vertex ADC path: identity from google-github-actions/auth (CI) or
            # gcloud ADC (local). Requires GOOGLE_CLOUD_PROJECT.
            client = genai.Client(
                vertexai=True,
                project=gcp_project,
                location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
            )
            _backend = "vertex_ai"
    else:
        client = genai.Client(api_key=api_key)
        _backend = "google_ai_studio"
    print(f"  [backend] {_backend}")

    AI_DIR.mkdir(parents=True, exist_ok=True)
    output_path = AI_DIR / f"{today}.json"

    was_incremental = False
    existing_output = {}

    if output_path.exists():
        try:
            with open(output_path, encoding="utf-8") as f:
                candidate = json.load(f)
            if not _is_complete(candidate):
                missing = _missing_fields(candidate)
                print(
                    f"Partial file found ({len(missing)} field(s) missing: {', '.join(missing)})"
                    f" — resuming incrementally."
                )
                existing_output = candidate
                was_incremental = True
            # Complete file: regenerate fresh (always produce up-to-date insights)
        except Exception:
            pass  # existing_output stays {}

    print(f"{'Completing' if was_incremental else 'Generating'} AI analysis for {today}...")

    output = {
        "date": today,
        "generated_at": existing_output.get(
            "generated_at",
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ),
        "model": GEMINI_MODEL,
    }

    try:
        for group_type in ("sector", "industry"):
            key = "sectors" if group_type == "sector" else "industries"
            output[key] = generate_for_group(
                client, group_type, today, existing=existing_output.get(key, {})
            )

    except DailyQuotaExhaustedError:
        print(
            "Daily free-tier quota exhausted — saving partial output and aborting.\n"
            "Next scheduled run will resume from this partial file."
        )
        has_partial = any(output.get(k) for k in ("sectors", "industries"))
        if has_partial:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=2, ensure_ascii=False)
            print(f"Partial output saved to {output_path}")
        _write_capture_tiers(today, capture_on)
        _write_run_artifacts("quota_exhausted", was_incremental, time.monotonic() - run_start, today)
        sys.exit(0)

    has_content = any(output.get(k) for k in ("sectors", "industries"))
    if not was_incremental and not has_content:
        print("No AI content generated (all API calls failed) — skipping file write so next run can retry.")
        _write_capture_tiers(today, capture_on)
        _write_run_artifacts("failed", False, time.monotonic() - run_start, today)
        sys.exit(0)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    action = "Updated" if was_incremental else "Written"
    print(f"{action} {output_path}")

    outcome = "complete" if _is_complete(output) else "partial"
    _write_capture_tiers(today, capture_on)
    _write_run_artifacts(outcome, was_incremental, time.monotonic() - run_start, today)
    _update_index(today, outcome, output)


if __name__ == "__main__":
    main()
