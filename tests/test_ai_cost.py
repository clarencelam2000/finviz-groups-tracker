"""Tests for scripts/ai_cost.py — date-aware pricing + actual-cost accounting."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import ai_cost


# ---------------------------------------------------------------------------
# price_for — date-aware selection + the intro->standard cliff
# ---------------------------------------------------------------------------

def test_price_for_picks_intro_rate_before_cliff():
    rate = ai_cost.price_for("gemini-3.8-flash", "2026-10-01")
    assert rate == {"input": 0.75, "output": 3.75}


def test_price_for_picks_standard_rate_after_cliff():
    rate = ai_cost.price_for("gemini-3.8-flash", "2027-02-01")
    assert rate == {"input": 1.50, "output": 7.50}


def test_price_for_exact_cliff_date_is_standard():
    # 2027-01-01 is the standard entry's effective_date — inclusive.
    rate = ai_cost.price_for("gemini-3.8-flash", "2027-01-01")
    assert rate["output"] == 7.50


def test_price_for_before_any_entry_uses_earliest():
    rate = ai_cost.price_for("gemini-3.8-flash", "2026-01-01")
    assert rate == {"input": 0.75, "output": 3.75}


def test_price_for_unknown_model_returns_none():
    assert ai_cost.price_for("gemini-9-ultra", "2026-10-01") == {"input": None, "output": None}


def test_price_for_historical_model():
    assert ai_cost.price_for("gemini-3.5-flash", "2026-08-01") == {"input": 1.50, "output": 9.00}


# ---------------------------------------------------------------------------
# billed_tokens — thinking counts as output
# ---------------------------------------------------------------------------

def test_billed_tokens_uses_thoughts_when_present():
    usage = {"prompt_tokens": 800, "output_tokens": 250, "thoughts_tokens": 1900,
             "total_tokens": 2950}
    assert ai_cost.billed_tokens(usage) == {"input": 800, "output": 2150}


def test_billed_tokens_falls_back_to_total_minus_prompt():
    # Old captures: no thoughts field, only the 3 headline counts.
    usage = {"prompt_tokens": 800, "output_tokens": 250, "total_tokens": 2950}
    assert ai_cost.billed_tokens(usage) == {"input": 800, "output": 2150}


def test_billed_tokens_never_below_visible_output():
    usage = {"prompt_tokens": 800, "output_tokens": 250, "total_tokens": 900}
    assert ai_cost.billed_tokens(usage)["output"] == 250


def test_billed_tokens_empty():
    assert ai_cost.billed_tokens({}) == {"input": 0, "output": 0}


# ---------------------------------------------------------------------------
# cost_of_usage
# ---------------------------------------------------------------------------

def test_cost_of_usage_intro_rate():
    usage = {"prompt_tokens": 7000, "output_tokens": 2650, "thoughts_tokens": 21240,
             "total_tokens": 30890}
    c = ai_cost.cost_of_usage("gemini-3.8-flash", usage, "2026-10-01")
    # input 7000 * 0.75/1e6; output (2650+21240)=23890 * 3.75/1e6
    assert c["input_usd"] == pytest.approx(0.00525, abs=1e-6)
    assert c["output_usd"] == pytest.approx(0.0895875, abs=1e-6)
    assert c["total_usd"] == pytest.approx(0.0948375, abs=1e-6)
    assert c["priced"] is True
    assert c["billed_output_tokens"] == 23890


def test_cost_of_usage_unknown_model_not_priced_but_safe():
    c = ai_cost.cost_of_usage("mystery", {"prompt_tokens": 10, "total_tokens": 20})
    assert c["priced"] is False
    assert c["total_usd"] == 0.0
    assert c["billed_output_tokens"] == 10  # total - prompt still computed


# ---------------------------------------------------------------------------
# sum_usage
# ---------------------------------------------------------------------------

def test_sum_usage_aggregates_and_skips_empty():
    usages = [
        {"prompt_tokens": 100, "output_tokens": 10, "thoughts_tokens": 50, "total_tokens": 160},
        {},
        None,
        {"prompt_tokens": 200, "output_tokens": 20, "thoughts_tokens": 60, "total_tokens": 280},
    ]
    s = ai_cost.sum_usage(usages)
    assert s["prompt_tokens"] == 300
    assert s["output_tokens"] == 30
    assert s["thoughts_tokens"] == 110
    assert s["total_tokens"] == 440
