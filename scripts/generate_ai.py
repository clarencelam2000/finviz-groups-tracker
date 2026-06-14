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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
AI_DIR = DATA_DIR / "ai"

GEMINI_MODEL = "gemini-2.5-flash"


class DailyQuotaExhaustedError(Exception):
    """Gemini daily free-tier RPD quota is fully consumed. Cannot retry until reset."""

PHASE_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {
            "type": "string",
            "enum": ["Early Cycle", "Mid Cycle", "Late Cycle", "Defensive"],
        },
        "reasoning": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["label", "reasoning", "confidence"],
}

INDUSTRY_PHASE_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": "string"},
        "reasoning": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["label", "reasoning", "confidence"],
}

WATCHLIST_SCHEMA = {
    "type": "object",
    "properties": {
        "picks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "thesis": {"type": "string"},
                    "conviction": {
                        "type": "string",
                        "enum": ["strong", "moderate", "speculative"],
                    },
                    "confidence": {"type": "number"},
                },
                "required": ["name", "thesis", "conviction"],
            },
            "minItems": 3,
            "maxItems": 3,
        }
    },
    "required": ["picks"],
}

BRIEFING_SCHEMA = {
    "type": "object",
    "properties": {
        "key_signals": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 3,
            "maxItems": 5,
        },
        "briefing": {"type": "string"},
    },
    "required": ["key_signals", "briefing"],
}

DAILY_DELTA_SCHEMA = {
    "type": "object",
    "properties": {
        "changes": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
            "maxItems": 3,
        }
    },
    "required": ["changes"],
}

# Courtesy spacing between calls. The binding free-tier limit was 20 requests/DAY
# (RPD), not per-minute; on Vertex AI paid tier per-minute limits are high.
# Daily-quota exhaustion is handled separately (DailyQuotaExhaustedError, abort-no-retry).
_INTER_CALL_DELAY = 2
_last_api_call: float = 0.0

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
    return f"""You are a quantitative market analyst. Based on the following Finviz {group_name} data for {date_str}, write a market analysis.

Return JSON with exactly two fields:
- "key_signals": array of 3-5 short strings, each a specific actionable observation (e.g. "Energy +8% YTD, rank improved 4 spots in 7 days" — not vague like "Energy is rising")
- "briefing": 3 short paragraphs (~150 words total) covering rotation, weakness, and notable patterns

DATA:
{snapshot}

{movers}

{leaders}

Be specific — name the {group_name}. No generic risk disclaimers."""


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

For each pick include a conviction rating:
- "strong": momentum_score >0.65 AND rank improving across multiple timeframes (week, month, ytd aligned)
- "moderate": improving in 1-2 timeframes, mixed signals elsewhere
- "speculative": single-timeframe signal or very early trend, needs confirmation

For each pick, respond with EXACTLY:
1. NAME: [sector name] | THESIS: [one sentence — why momentum/rank trajectory makes this interesting] | CONVICTION: [strong/moderate/speculative]
2. NAME: [sector name] | THESIS: [one sentence] | CONVICTION: [strong/moderate/speculative]
3. NAME: [sector name] | THESIS: [one sentence] | CONVICTION: [strong/moderate/speculative]

No other text. No disclaimers."""


def _find_prior_ai_file(date_str: str) -> "Path | None":
    """Return the most recent AI JSON file dated before date_str, within 5 calendar days."""
    try:
        base = date.fromisoformat(date_str)
    except ValueError:
        return None
    for days_back in range(1, 6):
        candidate = AI_DIR / f"{(base - timedelta(days=days_back)).isoformat()}.json"
        if candidate.exists():
            return candidate
    return None


def build_daily_delta_prompt(prior_briefing: str, snap_df: pd.DataFrame,
                              delta_df: pd.DataFrame, date_str: str) -> str:
    movers = serialize_top_movers(delta_df, n=5)
    return f"""You are a quantitative analyst. Compare today's market data with yesterday's sector analysis and identify what changed.

YESTERDAY'S ANALYSIS:
{prior_briefing}

TODAY'S TOP MOVERS ({date_str}):
{movers}

Identify 2-3 specific things that changed since yesterday. Focus on:
- Sectors that gained or lost momentum relative to yesterday
- Notable rank changes
- Phase shifts or new patterns emerging

Return JSON with a "changes" array of 2-3 short specific strings.
Good example: "Energy rank improved from #3 to #1 YTD, up 2 spots in 7 days"
Bad example: "Energy sector improved"
No generic commentary."""


def _generate_daily_delta(client, prior_briefing: str, date_str: str) -> "tuple[list, str]":
    """Generate 2-3 change observations vs yesterday.
    Returns (changes, error_msg). error_msg is '' on success, message string on failure."""
    snap_df = load_latest_snapshot("sector")
    delta_df = load_latest_delta("sector")
    prompt = build_daily_delta_prompt(prior_briefing, snap_df, delta_df, date_str)
    try:
        raw = _call_api(client, prompt,
                        generation_config={"temperature": 0.4, "max_output_tokens": 300},
                        response_schema=DAILY_DELTA_SCHEMA)
        parsed = json.loads(raw)
        changes = parsed.get("changes", []) if isinstance(parsed, dict) else []
        return changes, ""
    except DailyQuotaExhaustedError:
        raise  # propagate to main() — do not swallow daily quota errors
    except Exception as e:
        msg = str(e)
        print(f"  [daily_delta] API call failed: {msg}")
        return [], msg


def build_industry_phase_prompt(snap_df: pd.DataFrame, delta_df: pd.DataFrame, date_str: str) -> str:
    movers = serialize_top_movers(delta_df, n=5)
    leaders = serialize_momentum_leaders(delta_df, n=5)
    return f"""You are a macro analyst. Based on the Finviz industry data for {date_str}, classify the current industry rotation in 1-3 words.

Example micro-phase labels: "Commodity rotation", "Defensive consumer", "Tech pullback", "Broad advance", "Cyclical recovery", "Healthcare bid", "Energy & materials", "Consumer staples", "Small-cap growth"

Use whichever label best describes which types of industries are leading RIGHT NOW.

DATA:
{movers}

{leaders}

Respond with EXACTLY this format (no other text):
PHASE: [1-3 word micro-phase label]
REASONING: [One sentence: which specific industries are leading and why this suggests the stated micro-phase]"""


def build_industry_watchlist_prompt(snap_df: pd.DataFrame, delta_df: pd.DataFrame, date_str: str) -> str:
    leaders = serialize_momentum_leaders(delta_df, n=10)
    movers = serialize_top_movers(delta_df, n=5)
    return f"""You are a systematic trader. Based on the Finviz industry data for {date_str}, identify the top 3 industry setups worth watching.

{leaders}

{movers}

For each pick include a conviction rating:
- "strong": momentum_score >0.65 AND rank improving across multiple timeframes
- "moderate": improving in 1-2 timeframes, mixed signals elsewhere
- "speculative": single-timeframe signal or very early trend

For each pick, respond with EXACTLY:
1. NAME: [industry name] | THESIS: [one sentence — why momentum/rank trajectory makes this interesting] | CONVICTION: [strong/moderate/speculative]
2. NAME: [industry name] | THESIS: [one sentence] | CONVICTION: [strong/moderate/speculative]
3. NAME: [industry name] | THESIS: [one sentence] | CONVICTION: [strong/moderate/speculative]

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


def parse_briefing_response(text: str) -> dict:
    """Fallback when JSON parse fails for briefing — treat entire response as prose."""
    return {"briefing": text.strip(), "key_signals": []}


def parse_watchlist_response(text: str) -> list:
    _valid_convictions = {"strong", "moderate", "speculative"}
    items = []
    for line in text.split("\n"):
        line = line.strip()
        if not line or not line[0].isdigit():
            continue
        content = line.lstrip("0123456789. ")
        if "NAME:" not in content or "THESIS:" not in content:
            continue
        try:
            parts = [p.strip() for p in content.split("|")]
            name = next(p.replace("NAME:", "").strip() for p in parts if p.startswith("NAME:"))
            thesis_raw = next(p for p in parts if p.startswith("THESIS:"))
            thesis = thesis_raw.replace("THESIS:", "").strip()
            item: dict = {"name": name, "thesis": thesis}
            conviction_part = next((p for p in parts if p.startswith("CONVICTION:")), None)
            if conviction_part:
                conviction_val = conviction_part.replace("CONVICTION:", "").strip().lower()
                if conviction_val in _valid_convictions:
                    item["conviction"] = conviction_val
            items.append(item)
        except (StopIteration, ValueError):
            pass
    return items


def _normalize_briefing(parsed) -> dict:
    """Normalize briefing response to guaranteed shape: {briefing: str, key_signals: list}."""
    if isinstance(parsed, dict):
        return {
            "briefing": str(parsed.get("briefing") or "").strip(),
            "key_signals": [s for s in (parsed.get("key_signals") or []) if s],
        }
    if isinstance(parsed, str):
        return {"briefing": parsed.strip(), "key_signals": []}
    return {"briefing": "", "key_signals": []}


def _normalize_phase(parsed) -> dict:
    """Normalize phase response to guaranteed shape: {label: str, reasoning: str}."""
    if isinstance(parsed, dict):
        return {
            "label": str(parsed.get("label") or "").strip(),
            "reasoning": str(parsed.get("reasoning") or "").strip(),
        }
    if isinstance(parsed, str):
        return {"label": "Unknown", "reasoning": parsed.strip()}
    return {"label": "Unknown", "reasoning": ""}


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
        "name": "briefing",
        "group_types": ("sector", "industry"),
        "build_prompt": build_briefing_prompt,
        "pass_group_type": True,
        "use_json_schema": True,
        "response_schema": BRIEFING_SCHEMA,
        "fallback_parse": parse_briefing_response,
        "generation_config": {"temperature": 0.7, "max_output_tokens": 800},
    },
    {
        "name": "rotation_phase",
        "group_types": ("sector",),
        "build_prompt": build_phase_prompt,
        "use_json_schema": True,
        "response_schema": PHASE_SCHEMA,
        "fallback_parse": parse_phase_response,
        "generation_config": {"temperature": 0.2, "max_output_tokens": 300},
    },
    {
        "name": "watchlist",
        "group_types": ("sector",),
        "build_prompt": build_watchlist_prompt,
        "use_json_schema": True,
        "response_schema": WATCHLIST_SCHEMA,
        "fallback_parse": parse_watchlist_response,
        "generation_config": {"temperature": 0.5, "max_output_tokens": 400},
    },
    {
        "name": "rotation_phase",
        "group_types": ("industry",),
        "build_prompt": build_industry_phase_prompt,
        "use_json_schema": True,
        "response_schema": INDUSTRY_PHASE_SCHEMA,
        "fallback_parse": parse_phase_response,
        "generation_config": {"temperature": 0.2, "max_output_tokens": 300},
    },
    {
        "name": "watchlist",
        "group_types": ("industry",),
        "build_prompt": build_industry_watchlist_prompt,
        "use_json_schema": True,
        "response_schema": WATCHLIST_SCHEMA,
        "fallback_parse": parse_watchlist_response,
        "generation_config": {"temperature": 0.5, "max_output_tokens": 400},
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

def _looks_like_preamble(text: str) -> bool:
    """Detect if text is a preamble (e.g., 'Here is the JSON requested:')
    rather than actual content. Catches LLM failures to follow JSON schema."""
    preamble_patterns = [
        "here is",
        "below is",
        "the json",
        "json requested",
        "json follows",
        "json response",
        "json output",
        "```json",  # code fence without closing
    ]
    text_lower = text.lower()
    return any(pattern in text_lower for pattern in preamble_patterns) and not text.startswith(
        "{"
    )


def _call_api(client, prompt: str, max_retries: int = 3,
              generation_config: dict = None, response_schema: dict = None) -> str:
    """Call Gemini with rate-limit spacing and exponential-backoff retry."""
    global _last_api_call, _api_call_count, _rate_limit_hits
    elapsed = time.monotonic() - _last_api_call
    if elapsed < _INTER_CALL_DELAY:
        time.sleep(_INTER_CALL_DELAY - elapsed)

    extra = {}
    if response_schema:  # only import google.genai when JSON mode is actually needed
        from google.genai import types  # noqa: PLC0415 — lazy; google-genai only required at runtime
        extra["config"] = types.GenerateContentConfig(
            temperature=(generation_config or {}).get("temperature", 0.7),
            max_output_tokens=(generation_config or {}).get("max_output_tokens", 500),
            response_mime_type="application/json",
            response_schema=response_schema,
        )

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

            text = response.text.strip()
            # Reject responses that are obvious preambles instead of content
            # (catches LLM failures to follow JSON schema instructions)
            if _looks_like_preamble(text):
                raise ValueError(f"response is preamble, not content: {text[:60]}")

            return text
        except Exception as e:
            err_str = str(e)
            # Daily quota is not recoverable by retrying — abort immediately.
            if "GenerateRequestsPerDayPerProjectPerModel" in err_str:
                raise DailyQuotaExhaustedError(err_str) from e
            is_retryable = (
                "429" in err_str or "quota" in err_str.lower() or "resource_exhausted" in err_str.lower()
                or "503" in err_str or "unavailable" in err_str.lower()
                or "empty response" in err_str.lower() or "preamble" in err_str.lower()
            )
            if is_retryable and attempt < max_retries:
                _rate_limit_hits += 1
                wait = 30 * (2 ** attempt)  # 30s, 60s, 120s
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
                response_schema=spec.get("response_schema"),
            )
            if spec["use_json_schema"]:
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    parsed = spec.get("fallback_parse", lambda t: t)(raw)
                if spec["name"] == "watchlist":
                    result["watchlist"] = (
                        parsed.get("picks", []) if isinstance(parsed, dict) else parsed
                    )
                elif spec["name"] == "briefing":
                    normalized = _normalize_briefing(parsed)
                    result["briefing"] = normalized["briefing"]
                    if normalized["key_signals"]:
                        result["key_signals"] = normalized["key_signals"]
                elif spec["name"] == "rotation_phase":
                    result["rotation_phase"] = _normalize_phase(parsed)
                else:
                    result[spec["name"]] = parsed
            else:
                result[spec["name"]] = raw
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
            location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
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

        # Daily delta — compare today vs yesterday's sectors briefing
        if not output.get("sectors", {}).get("daily_delta"):
            prior_path = _find_prior_ai_file(today)
            if prior_path:
                try:
                    prior_data = json.loads(prior_path.read_text(encoding="utf-8"))
                    prior_briefing = prior_data.get("sectors", {}).get("briefing", "")
                    if prior_briefing:
                        print(f"  [daily_delta] Generating from {prior_path.name}...")
                        t0 = time.monotonic()
                        changes, err_msg = _generate_daily_delta(client, prior_briefing, today)
                        t_elapsed = time.monotonic() - t0
                        if changes:
                            output["sectors"]["daily_delta"] = changes
                            _record_field("sectors.daily_delta", "ok", was_new=True,
                                          elapsed=t_elapsed)
                        elif err_msg:
                            _record_field("sectors.daily_delta", "error", was_new=True,
                                          elapsed=t_elapsed, error=err_msg)
                        else:
                            # Model returned empty list — valid, no notable changes today
                            _record_field("sectors.daily_delta", "ok_empty", was_new=True,
                                          elapsed=t_elapsed)
                except DailyQuotaExhaustedError:
                    raise  # propagate to outer handler
                except Exception as e:
                    print(f"  [daily_delta] Failed to load prior file: {e}")
                    _record_field("sectors.daily_delta", "error", was_new=True, error=str(e))

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
