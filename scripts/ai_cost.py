"""
ai_cost.py — actual-cost accounting for Gemini/Vertex calls (AI-WALLET, 2026-09-10).

A tiny, dependency-free "meter" that turns the REAL token counts returned in each
response's usage_metadata into dollars, using a date-aware published-price table. It is
the single seam every Vertex call path is meant to share:

  - generate_ai.py calls cost_of_usage() per run and records it to ai_run_log.jsonl +
    data/ai/spend.json (surfaced at the bottom of the PWA's AI tab).
  - The AI-NEXT workstream (Morning/Pre-close per-card prose) reuses the exact same
    functions so its spend lands in the same ledger and surface — no second accountant.

Design notes:
  - Thinking/reasoning tokens bill at the OUTPUT rate (confirmed for Gemini 3.x Flash),
    so billed output = candidates (output_tokens) + thoughts_tokens. When a usage dict
    lacks an explicit thoughts count, we fall back to total - prompt, which captures the
    same billed-output total.
  - PRICING is DATE-AWARE on purpose. Gemini 3.8 Flash ships at an introductory rate that
    reverts UP on 2027-01-01 — a silent cliff. Effective-dated entries mean the spend
    surface keeps reporting the right number across that date with no code change, and the
    model-migration history (3.5 -> 3.8) stays costable for old captures.

Prices are USD per 1,000,000 tokens. Update them here (and in README § Configurable
parameters + scripts/CLAUDE.md § AI spend controls — the 3-places rule) when Google changes
published rates. Rates below are the Vertex AI rates for the backend this repo uses; verify
against https://cloud.google.com/vertex-ai/generative-ai/pricing before relying on them for
a billing decision.
"""

from __future__ import annotations

from datetime import date, datetime

# model -> list of effective-dated rate entries (any order; newest-effective <= the query
# date wins). input/output are USD per 1M tokens.
PRICING: dict[str, list[dict]] = {
    # Gemini 3.8 Flash (our current model). Intro rate through 2026-12-31, then the
    # standard list price from 2027-01-01 — encode BOTH so the cliff isn't silent.
    "gemini-3.8-flash": [
        {"effective_date": "2026-09-02", "input": 0.75, "output": 3.75},  # intro
        {"effective_date": "2027-01-01", "input": 1.50, "output": 7.50},  # standard
    ],
    # Gemini 3.5 Flash (prior model) — kept so historical captures remain costable.
    # AI-Studio list price; Vertex ran ~10-20% higher, so this slightly understates our
    # actual 3.5-era Vertex spend (we have since migrated off it).
    "gemini-3.5-flash": [
        {"effective_date": "2026-05-19", "input": 1.50, "output": 9.00},
    ],
}

# Returned when a model has no pricing entry at all — flagged so callers can surface
# "unknown model, cost not computed" rather than silently reporting $0.
UNKNOWN_PRICE = {"input": None, "output": None}


def _as_date(d) -> date:
    if isinstance(d, date):
        return d
    if isinstance(d, datetime):
        return d.date()
    # Accept "YYYY-MM-DD" or a full ISO timestamp.
    return datetime.fromisoformat(str(d).replace("Z", "+00:00")).date()


def price_for(model: str, on_date=None) -> dict:
    """Return {"input": per_1M, "output": per_1M} effective for `model` on `on_date`.

    Picks the entry with the largest effective_date that is <= on_date (today if None).
    Returns UNKNOWN_PRICE (Nones) for an unpriced model. If on_date precedes every entry
    (e.g. a capture older than the first listed rate), the earliest entry is used as the
    best available approximation.
    """
    entries = PRICING.get(model)
    if not entries:
        return dict(UNKNOWN_PRICE)
    on = _as_date(on_date) if on_date is not None else date.today()
    applicable = [e for e in entries if _as_date(e["effective_date"]) <= on]
    chosen = max(applicable, key=lambda e: _as_date(e["effective_date"])) if applicable \
        else min(entries, key=lambda e: _as_date(e["effective_date"]))
    return {"input": chosen["input"], "output": chosen["output"]}


def billed_tokens(usage: dict) -> dict:
    """Split a usage dict into billed input vs billed output tokens.

    billed_output = output_tokens + thoughts_tokens (thinking bills at the output rate);
    when thoughts isn't itemized, fall back to total - prompt (same billed-output total).
    Missing values are treated as 0. Returns {"input": int, "output": int}.
    """
    prompt = usage.get("prompt_tokens") or 0
    output = usage.get("output_tokens") or 0
    thoughts = usage.get("thoughts_tokens")
    total = usage.get("total_tokens")
    if thoughts is not None:
        billed_out = output + thoughts
    elif total is not None:
        billed_out = max(total - prompt, output)  # never below the visible-output count
    else:
        billed_out = output
    return {"input": int(prompt), "output": int(billed_out)}


def cost_of_usage(model: str, usage: dict, on_date=None) -> dict:
    """Dollar cost of one call's (or summed run's) usage dict.

    Returns {"input_usd", "output_usd", "total_usd", "billed_input_tokens",
    "billed_output_tokens", "priced": bool}. `priced` is False when the model has no rate
    (costs come back 0.0 so sums don't crash, but the caller can flag it).
    """
    tok = billed_tokens(usage or {})
    rate = price_for(model, on_date)
    if rate["input"] is None:
        return {"input_usd": 0.0, "output_usd": 0.0, "total_usd": 0.0,
                "billed_input_tokens": tok["input"], "billed_output_tokens": tok["output"],
                "priced": False}
    input_usd = tok["input"] / 1_000_000 * rate["input"]
    output_usd = tok["output"] / 1_000_000 * rate["output"]
    return {
        "input_usd": round(input_usd, 6),
        "output_usd": round(output_usd, 6),
        "total_usd": round(input_usd + output_usd, 6),
        "billed_input_tokens": tok["input"],
        "billed_output_tokens": tok["output"],
        "priced": True,
    }


def sum_usage(usages) -> dict:
    """Sum an iterable of per-call usage dicts into one run-level usage dict."""
    out = {"prompt_tokens": 0, "output_tokens": 0, "thoughts_tokens": 0,
           "cached_tokens": 0, "total_tokens": 0}
    for u in usages:
        if not u:
            continue
        for k in out:
            v = u.get(k)
            if v:
                out[k] += v
    return out
