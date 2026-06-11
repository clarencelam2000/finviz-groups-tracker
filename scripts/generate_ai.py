"""
generate_ai.py — Generate AI analysis from latest Finviz data using Gemini.
Writes data/ai/YYYY-MM-DD.json, which the dashboard reads and renders.

Run after compute_deltas.py. Exits 0 silently if GEMINI_API_KEY is not set.
"""

import json
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
AI_DIR = DATA_DIR / "ai"

GEMINI_MODEL = "gemini-flash-latest"

# Free tier: 5 requests/minute. Enforce >=13s between calls to stay safely under.
_INTER_CALL_DELAY = 13
_last_api_call: float = 0.0


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
    if delta_df.empty or "rank_ytd_delta_7d" not in delta_df.columns:
        return "No 7-day rank delta data available yet (need 7+ days of history)."
    valid = delta_df.dropna(subset=["rank_ytd_delta_7d"]).copy()
    if valid.empty:
        return "No 7-day rank delta data available yet."

    take = min(n, len(valid))
    gainers = valid.nlargest(take, "rank_ytd_delta_7d")[
        ["name", "rank_ytd_delta_7d", "rank_ytd", "momentum_score"]
    ]
    losers = valid.nsmallest(take, "rank_ytd_delta_7d")[
        ["name", "rank_ytd_delta_7d", "rank_ytd", "momentum_score"]
    ]

    lines = ["TOP GAINERS (rank improved most in 7 days):"]
    for _, r in gainers.iterrows():
        ms = f"{r['momentum_score']:.2f}" if pd.notna(r.get("momentum_score")) else "N/A"
        rank_str = f"{r['rank_ytd']:.0f}" if pd.notna(r.get("rank_ytd")) else "N/A"
        lines.append(
            f"  {r['name']}: +{r['rank_ytd_delta_7d']:.0f} spots, "
            f"rank {rank_str}, momentum {ms}"
        )

    lines.append("\nTOP LOSERS (rank declined most in 7 days):")
    for _, r in losers.iterrows():
        ms = f"{r['momentum_score']:.2f}" if pd.notna(r.get("momentum_score")) else "N/A"
        rank_str = f"{r['rank_ytd']:.0f}" if pd.notna(r.get("rank_ytd")) else "N/A"
        lines.append(
            f"  {r['name']}: {r['rank_ytd_delta_7d']:.0f} spots, "
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


def build_briefing_prompt(group_type: str, snap_df: pd.DataFrame,
                          delta_df: pd.DataFrame, date_str: str) -> str:
    group_name = "sectors" if group_type == "sector" else "industries"
    snapshot = serialize_snapshot_summary(snap_df)
    movers = serialize_top_movers(delta_df)
    leaders = serialize_momentum_leaders(delta_df)
    return f"""You are a quantitative market analyst. Based on the following Finviz {group_name} data for {date_str}, write a concise market briefing (3 short paragraphs, ~150 words total).

Focus on: (1) what is rotating in / gaining momentum, (2) what is weakening or losing ground, (3) any notable divergence or pattern worth watching.

Write in plain English, directly useful to an investor tracking sector rotation. Do not add generic risk disclaimers.

DATA:
{snapshot}

{movers}

{leaders}

Write 3 short paragraphs. No headings, no bullet points. Be specific — name the {group_name}."""


def build_phase_prompt(snap_df: pd.DataFrame, delta_df: pd.DataFrame, date_str: str) -> str:
    snapshot = serialize_snapshot_summary(snap_df)
    leaders = serialize_momentum_leaders(delta_df, n=5)
    return f"""You are a macro analyst specializing in sector rotation.

Based on the sector performance data below for {date_str}, classify the current market rotation phase.

Classic phases:
- Early Cycle: Financials, Consumer Discretionary leading
- Mid Cycle: Industrials, Materials, Technology leading
- Late Cycle: Energy, Materials leading; Utilities/Healthcare lagging
- Defensive: Utilities, Healthcare, Consumer Staples leading; Cyclicals lagging

DATA:
{snapshot}

{leaders}

Respond with EXACTLY this format (no other text):
PHASE: [one of: Early Cycle / Mid Cycle / Late Cycle / Defensive]
REASONING: [One sentence explaining which sectors are leading and why this suggests the stated phase]"""


def build_watchlist_prompt(snap_df: pd.DataFrame, delta_df: pd.DataFrame, date_str: str) -> str:
    leaders = serialize_momentum_leaders(delta_df, n=10)
    movers = serialize_top_movers(delta_df, n=5)
    return f"""You are a systematic trader. Based on the Finviz sector data for {date_str}, identify the top 3 sector setups worth watching.

{leaders}

{movers}

For each pick, respond with EXACTLY:
1. NAME: [sector name] | THESIS: [one sentence — why momentum/rank trajectory makes this interesting]
2. NAME: [sector name] | THESIS: [one sentence]
3. NAME: [sector name] | THESIS: [one sentence]

No other text. No disclaimers."""


# ---------------------------------------------------------------------------
# Response parsers
# ---------------------------------------------------------------------------

def parse_phase_response(text: str) -> dict:
    result = {"label": "Unknown", "reasoning": text.strip()}
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("PHASE:"):
            result["label"] = line[6:].strip()
        elif line.startswith("REASONING:"):
            result["reasoning"] = line[10:].strip()
    return result


def parse_watchlist_response(text: str) -> list:
    items = []
    for line in text.split("\n"):
        line = line.strip()
        if not line or not line[0].isdigit():
            continue
        content = line.lstrip("0123456789. ")
        if "NAME:" in content and "THESIS:" in content:
            try:
                name_part, thesis_part = content.split("|", 1)
                items.append({
                    "name": name_part.replace("NAME:", "").strip(),
                    "thesis": thesis_part.replace("THESIS:", "").strip(),
                })
            except ValueError:
                pass
    return items


# ---------------------------------------------------------------------------
# API call helper
# ---------------------------------------------------------------------------

def _call_api(client, prompt: str, max_retries: int = 3) -> str:
    """Call Gemini with rate-limit spacing and exponential-backoff retry."""
    global _last_api_call
    elapsed = time.monotonic() - _last_api_call
    if elapsed < _INTER_CALL_DELAY:
        time.sleep(_INTER_CALL_DELAY - elapsed)

    for attempt in range(max_retries + 1):
        _last_api_call = time.monotonic()
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL, contents=prompt
            )
            return response.text.strip()
        except Exception as e:
            err_str = str(e)
            is_quota = (
                "429" in err_str
                or "quota" in err_str.lower()
                or "resource_exhausted" in err_str.lower()
            )
            if is_quota and attempt < max_retries:
                wait = 30 * (2 ** attempt)  # 30s, 60s, 120s
                print(f"    Rate limited, waiting {wait}s (attempt {attempt + 1}/{max_retries + 1})...")
                time.sleep(wait)
                continue
            raise


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def generate_for_group(client, group_type: str, date_str: str) -> dict:
    snap_df = load_latest_snapshot(group_type)
    delta_df = load_latest_delta(group_type)

    if snap_df.empty:
        print(f"  [{group_type}] No snapshot data — skipping.")
        return {}

    result = {}

    print(f"  [{group_type}] Generating briefing...")
    try:
        result["briefing"] = _call_api(
            client, build_briefing_prompt(group_type, snap_df, delta_df, date_str)
        )
    except Exception as e:
        print(f"  [{group_type}] Briefing failed: {e}")

    if group_type == "sector":
        print(f"  [{group_type}] Generating rotation phase...")
        try:
            phase_text = _call_api(client, build_phase_prompt(snap_df, delta_df, date_str))
            result["rotation_phase"] = parse_phase_response(phase_text)
        except Exception as e:
            print(f"  [{group_type}] Phase generation failed: {e}")

        print(f"  [{group_type}] Generating watchlist...")
        try:
            watchlist_text = _call_api(client, build_watchlist_prompt(snap_df, delta_df, date_str))
            result["watchlist"] = parse_watchlist_response(watchlist_text)
        except Exception as e:
            print(f"  [{group_type}] Watchlist generation failed: {e}")

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY not set — skipping AI generation.")
        sys.exit(0)

    try:
        import google.genai as genai
    except ImportError:
        print("google-genai not installed. Run: pip install google-genai")
        sys.exit(0)

    client = genai.Client(api_key=api_key)

    today = date.today().isoformat()
    AI_DIR.mkdir(parents=True, exist_ok=True)
    output_path = AI_DIR / f"{today}.json"

    if output_path.exists():
        print(f"AI analysis for {today} already exists — skipping.")
        sys.exit(0)

    print(f"Generating AI analysis for {today}...")

    output = {
        "date": today,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": GEMINI_MODEL,
    }

    for group_type in ("sector", "industry"):
        key = "sectors" if group_type == "sector" else "industries"
        output[key] = generate_for_group(client, group_type, today)

    has_content = any(output.get(k) for k in ("sectors", "industries"))
    if not has_content:
        print("No AI content generated (all API calls failed) — skipping file write so next run can retry.")
        sys.exit(0)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Written to {output_path}")


if __name__ == "__main__":
    main()
