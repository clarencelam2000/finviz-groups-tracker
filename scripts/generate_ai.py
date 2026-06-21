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
import sys
import time
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


class DailyQuotaExhaustedError(Exception):
    """Gemini daily free-tier RPD quota is fully consumed. Cannot retry until reset."""


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
_backend: str = "unset"  # "vertex_ai" | "google_ai_studio" | "unset"; set during client init


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
    global _api_call_count, _rate_limit_hits, _field_log, _backend
    _api_call_count = 0
    _rate_limit_hits = 0
    _field_log = {}
    _backend = "unset"


def _record_field(key: str, status: str, *, was_new: bool = True,
                  elapsed: float = 0.0, error: str = "") -> None:
    entry = {"status": status, "was_new": was_new}
    if was_new and elapsed:
        entry["elapsed_seconds"] = round(elapsed, 1)
    if error:
        entry["error"] = error
    _field_log[key] = entry




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


def serialize_rotation_pairs(delta_df: pd.DataFrame, n: int = 5) -> str:
    """Capital-flow framing: the biggest rank decliners (capital leaving) paired
    against the biggest improvers (capital arriving), plus regime context so the
    model can phrase rotation as OUT-of / INTO. Feeds the Rotation Map section."""
    if delta_df.empty or SHORT_DELTA_COL not in delta_df.columns:
        return "ROTATION FLOW:\n  Not enough history for rotation signals yet."
    d = delta_df.copy()
    d[SHORT_DELTA_COL] = pd.to_numeric(d[SHORT_DELTA_COL], errors="coerce")
    valid = d.dropna(subset=[SHORT_DELTA_COL])
    if valid.empty:
        return "ROTATION FLOW:\n  Not enough history for rotation signals yet."

    has_regime = "regime_short_long" in valid.columns

    def _regime(r):
        if not has_regime or pd.isna(r.get("regime_short_long")):
            return ""
        return f", regime {r['regime_short_long']:+.2f}"

    take = min(n, len(valid))
    leaving = valid.nsmallest(take, SHORT_DELTA_COL)   # rank slipping = capital leaving
    arriving = valid.nlargest(take, SHORT_DELTA_COL)   # rank rising = capital arriving
    lines = [f"ROTATION FLOW (rank change over {SHORT_WIN} sessions; "
             f"regime>0 = short-horizon leader, <0 = fading):"]
    lines.append("  Capital LEAVING (rank slipping):")
    for _, r in leaving.iterrows():
        lines.append(f"    {r['name']}: {r[SHORT_DELTA_COL]:+.0f} spots{_regime(r)}")
    lines.append("  Capital ARRIVING (rank rising):")
    for _, r in arriving.iterrows():
        lines.append(f"    {r['name']}: {r[SHORT_DELTA_COL]:+.0f} spots{_regime(r)}")
    return "\n".join(lines)


# RS (relative-strength vs SPY) columns produced by compute_deltas. NaN when the
# benchmark snapshot lacks a row for the date — handled gracefully below.
_RS_BEAT_COLS = ["beats_benchmark_week", "beats_benchmark_month",
                 "beats_benchmark_quarter", "beats_benchmark_half",
                 "beats_benchmark_year", "beats_benchmark_ytd", "beats_benchmark_day"]


def serialize_rs_signals(delta_df: pd.DataFrame, n: int = 6) -> str:
    """Absolute outperformance vs the S&P 500: rs_score leaders, how many of the 7
    timeframes each beats SPY on, plus fresh RS new-highs and RS crosses (rotation
    triggers). Unlike peer-rank, a rising tide does NOT inflate these."""
    if delta_df.empty or "rs_score" not in delta_df.columns:
        return "RELATIVE STRENGTH vs S&P:\n  No benchmark (SPY) data available for this date."
    d = delta_df.copy()
    d["rs_score"] = pd.to_numeric(d["rs_score"], errors="coerce")
    valid = d.dropna(subset=["rs_score"])
    if valid.empty:
        return "RELATIVE STRENGTH vs S&P:\n  No benchmark (SPY) data available for this date."

    beat_cols = [c for c in _RS_BEAT_COLS if c in valid.columns]

    def _beats(r):
        if not beat_cols:
            return "N/A"
        cnt = sum(1 for c in beat_cols if pd.notna(r.get(c)) and float(r[c]) > 0)
        return f"{cnt}/{len(beat_cols)} timeframes"

    lines = ["RELATIVE STRENGTH vs S&P (rs_score = fraction of 7 timeframes beating SPY):"]
    leaders = valid.sort_values("rs_score", ascending=False).head(n)
    for _, r in leaders.iterrows():
        lines.append(f"  {r['name']}: rs_score {r['rs_score']:.2f}, beats SPY on {_beats(r)}")

    if "rs_new_high" in valid.columns:
        nh = valid[pd.to_numeric(valid["rs_new_high"], errors="coerce") > 0]
        if not nh.empty:
            lines.append("  RS new highs (20-session): " + ", ".join(nh["name"].head(8)))
    if "rs_cross" in valid.columns:
        cx = valid[pd.to_numeric(valid["rs_cross"], errors="coerce") > 0]
        if not cx.empty:
            lines.append("  RS crosses (just turned positive vs SPY): " + ", ".join(cx["name"].head(8)))
    return "\n".join(lines)


def build_briefing_prompt(group_type: str, snap_df: pd.DataFrame,
                          delta_df: pd.DataFrame, date_str: str) -> str:
    """Structured multi-section desk briefing. Returns a STRICT markdown template
    parsed by parse_briefing_response into headline/conviction/rotation_map/
    watchlist/relative_strength/risks. One API call delivers six AI-tab cards."""
    group_name = "sectors" if group_type == "sector" else "industries"
    strength = serialize_strength_signals(snap_df, delta_df)
    rotation = serialize_rotation_pairs(delta_df, n=5)
    rs = serialize_rs_signals(delta_df, n=6)
    divergences = serialize_divergences(snap_df, delta_df)
    return f"""You are a markets strategist writing a structured desk briefing on US {group_name} for {date_str}.

Use ONLY the computed signals below. Do not invent numbers or {group_name} not present in the data. Name specific {group_name} and cite numbers.

Respond in Markdown using EXACTLY these six `##` sections, in this order, with these exact titles. Do not add a preamble, intro, or any text before the first `##` header. Do not use `###`.

## Headline
A single punchy line, 12 words or fewer, capturing today's most important {group_name} takeaway. No bullet, no bold.

## Conviction
Exactly two lines:
Level: <one of High, Medium, Low>
Why: <one sentence — judge conviction from breadth, cross-timeframe agreement, and how many divergences are present>

## Rotation Map
2-4 bullets, each `- OUT: <group> -> IN: <group> - <short reason>`, using the ROTATION FLOW signal (capital leaving the rank-slipping {group_name}, arriving at the rank-rising ones).

## Watchlist
3-5 bullets, each `- <group> - <the specific trigger to watch>`, drawn from divergences, RS crosses, and RS new highs. Pick names that are actionable, not already-obvious leaders.

## Relative Strength
1-2 sentences on which {group_name} are beating the S&P 500 (use rs_score and the beats-SPY timeframe counts, and call out any RS new highs or crosses). If no benchmark data is available, say so in one line.

## Risks
2-4 bullets on fragile or fading setups: strong names with slipping ranks, all-green {group_name} with low rank agreement, or crowded leadership. If none, say "No notable risks today." as a single bullet.

COMPUTED SIGNALS:
{strength}

{rotation}

{rs}

{divergences}"""


# ---------------------------------------------------------------------------
# Briefing response parser
# ---------------------------------------------------------------------------

# Canonical section keys, in render order, with the header aliases each accepts.
# Tolerant by design: a malformed/renamed/missing header must never break the
# whole briefing — missing sections are simply absent keys (not empty strings),
# so the frontend can distinguish "model skipped it" from "" and the file is
# still considered complete once a non-empty briefing dict exists.
_BRIEFING_SECTIONS = [
    ("headline", ("headline", "daily headline", "tl;dr")),
    ("conviction", ("conviction", "conviction meter")),
    ("rotation_map", ("rotation map", "rotation", "rotation flow")),
    ("watchlist", ("watchlist", "watch list", "actionable watchlist")),
    ("relative_strength", ("relative strength", "relative strength vs s&p", "rs", "vs market")),
    ("risks", ("risks", "risks & fragility", "risks and fragility", "fragility")),
]


def _briefing_key_for(title: str):
    t = title.strip().lower().rstrip(":").strip()
    for key, aliases in _BRIEFING_SECTIONS:
        if t in aliases:
            return key
    return None


def parse_briefing_response(text: str) -> dict:
    """Split the structured briefing markdown into a section dict. Tolerant of
    `###` headers, preamble before the first header, and renamed/missing sections.
    Returns absent keys for sections the model omitted. `conviction` is parsed into
    {level, why}; all other sections are stored as their raw markdown body."""
    text = (text or "").strip()
    if not text:
        return {}
    # Normalize ### / #### down to ## so the splitter sees one header level.
    import re  # noqa: PLC0415 — local; only needed here
    normalized = re.sub(r"^#{3,}\s+", "## ", text, flags=re.MULTILINE)

    sections: dict = {}
    current_key = None
    buf: list = []

    def _flush():
        if current_key and buf:
            body = "\n".join(buf).strip()
            if body:
                sections[current_key] = body

    for line in normalized.split("\n"):
        m = re.match(r"^##\s+(.*)$", line.strip())
        if m:
            _flush()
            buf = []
            current_key = _briefing_key_for(m.group(1))
        elif current_key:
            buf.append(line)
    _flush()

    if "conviction" in sections:
        sections["conviction"] = _parse_conviction(sections["conviction"])
    return sections


def _parse_conviction(body: str) -> dict:
    """Parse the conviction body into {level, why}. Tolerant of missing prefixes:
    falls back to scanning for a High/Medium/Low token and using the rest as why."""
    result = {"level": "", "why": ""}
    for line in body.split("\n"):
        low = line.strip().lower()
        if low.startswith("level:"):
            result["level"] = line.split(":", 1)[1].strip()
        elif low.startswith("why:") or low.startswith("reasoning:"):
            result["why"] = line.split(":", 1)[1].strip()
    if not result["level"]:
        for token in ("High", "Medium", "Low"):
            if token.lower() in body.lower():
                result["level"] = token
                break
    if not result["why"]:
        # Use the first non-level line as the rationale.
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

def _build_prompt(spec: dict, group_type: str, snap_df, delta_df, date_str: str) -> str:
    fn = spec["build_prompt"]
    if spec.get("pass_group_type"):
        return fn(group_type, snap_df, delta_df, date_str)
    return fn(snap_df, delta_df, date_str)


TASK_SPECS = [
    {
        "name": "note",
        "group_types": ("sector", "industry"),
        "build_prompt": build_note_prompt,
        "pass_group_type": True,
        "generation_config": {"temperature": 0.6},
    },
    {
        "name": "rotation_phase",
        "group_types": ("sector",),
        "build_prompt": build_phase_prompt,
        "generation_config": {"temperature": 0.2},
    },
    {
        # Structured six-section desk briefing. max_output_tokens caps rambling on
        # the larger industries set (~150 groups) so a retry can't blow per-minute
        # limits; 2000 comfortably fits six tight sections.
        "name": "briefing",
        "group_types": ("sector", "industry"),
        "build_prompt": build_briefing_prompt,
        "pass_group_type": True,
        "generation_config": {"temperature": 0.5, "max_output_tokens": 2000},
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
              generation_config: dict = None) -> str:
    """Call Gemini for freeform text with rate-limit spacing and retry.

    No JSON mode, no response schema, no max_output_tokens — the model writes a
    markdown note and we display it verbatim. Only the temperature is set."""
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
    for attempt in range(max_retries + 1):
        _last_api_call = time.monotonic()
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL, contents=prompt, **extra
            )
            # Handle None or whitespace-only response text (transient API error)
            if not response.text or not response.text.strip():
                raise ValueError("empty response (503-like transient error)")

            return response.text.strip()
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
        try:
            prompt = _build_prompt(spec, group_type, snap_df, delta_df, date_str)
            raw = _call_api(
                client, prompt,
                generation_config=spec.get("generation_config"),
            )
            if spec["name"] == "rotation_phase":
                result["rotation_phase"] = parse_phase_response(raw)
            elif spec["name"] == "briefing":
                # Structured: store the parsed section dict, not the raw text, so
                # the frontend can read .headline/.watchlist/etc. A non-empty dict
                # also keeps _is_complete honest (empty parse won't mark complete).
                parsed = parse_briefing_response(raw)
                if not parsed:
                    raise ValueError("briefing response parsed to no sections")
                result["briefing"] = parsed
            else:  # "note" — freeform markdown, stored verbatim
                result[spec["name"]] = raw.strip()
            _record_field(fkey, "ok", was_new=True, elapsed=time.monotonic() - t0)
        except DailyQuotaExhaustedError:
            _record_field(fkey, "quota_exhausted", was_new=True, elapsed=time.monotonic() - t0)
            raise  # propagate to main() — do not continue generating other fields
        except Exception as e:
            print(f"  [{group_type}] {spec['name']} failed: {e}")
            _record_field(fkey, "error", was_new=True, elapsed=time.monotonic() - t0, error=str(e))

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
    parser.add_argument(
        "--force-ai",
        action="store_true",
        help="Force regeneration even if no new delta data",
    )
    args, _ = parser.parse_known_args()
    force = args.force_ai or bool(os.getenv("FORCE_AI"))

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

    if not force and not _has_new_delta_data(today):
        print(f"No new delta data for {today} — skipping AI regeneration.")
        _write_run_artifacts("skipped", False, time.monotonic() - run_start, today)
        sys.exit(0)

    use_vertexai = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("1", "true", "yes")
    api_key = os.getenv("GEMINI_API_KEY")
    gcp_project = os.getenv("GOOGLE_CLOUD_PROJECT")

    # Graceful skip when the selected backend is not configured (exit 0, not error).
    if use_vertexai and not gcp_project:
        print("GOOGLE_GENAI_USE_VERTEXAI=true but GOOGLE_CLOUD_PROJECT not set — skipping AI generation.")
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

    if use_vertexai:
        # Vertex AI: identity comes from ADC (CI: google-github-actions/auth; local: gcloud ADC).
        # If both the toggle and GEMINI_API_KEY are set, the toggle wins.
        client = genai.Client(
            vertexai=True,
            project=gcp_project,
            location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
        )
    else:
        client = genai.Client(api_key=api_key)

    global _backend
    _backend = "vertex_ai" if use_vertexai else "google_ai_studio"
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

    except DailyQuotaExhaustedError as e:
        print(
            f"Daily free-tier quota exhausted — saving partial output and aborting.\n"
            f"Next scheduled run will resume from this partial file."
        )
        has_partial = any(output.get(k) for k in ("sectors", "industries"))
        if has_partial:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=2, ensure_ascii=False)
            print(f"Partial output saved to {output_path}")
        _write_run_artifacts("quota_exhausted", was_incremental, time.monotonic() - run_start, today)
        sys.exit(0)

    has_content = any(output.get(k) for k in ("sectors", "industries"))
    if not was_incremental and not has_content:
        print("No AI content generated (all API calls failed) — skipping file write so next run can retry.")
        _write_run_artifacts("failed", False, time.monotonic() - run_start, today)
        sys.exit(0)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    action = "Updated" if was_incremental else "Written"
    print(f"{action} {output_path}")

    outcome = "complete" if _is_complete(output) else "partial"
    _write_run_artifacts(outcome, was_incremental, time.monotonic() - run_start, today)
    _update_index(today, outcome, output)


if __name__ == "__main__":
    main()
