"""
Tests for scripts/generate_ai.py pure functions.
No real filesystem I/O, no real API calls.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import generate_ai


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def snap_df():
    return pd.DataFrame({
        "date": [pd.Timestamp("2026-06-10").date()] * 3,
        "name": ["Energy", "Technology", "Healthcare"],
        "perf_week":  [2.5, -1.0,  0.8],
        "perf_month": [5.0, -2.0,  1.5],
        "perf_ytd":   [12.0, -3.0, 4.0],
    })


@pytest.fixture
def delta_df():
    return pd.DataFrame({
        "date": [pd.Timestamp("2026-06-10").date()] * 3,
        "name": ["Energy", "Technology", "Healthcare"],
        "rank_ytd":          [1.0, 3.0, 2.0],
        "rank_ytd_delta_7d": [5.0, -3.0, 1.0],
        "momentum_score":    [0.85, 0.30, 0.60],
    })


# ---------------------------------------------------------------------------
# serialize_snapshot_summary
# ---------------------------------------------------------------------------

def test_snapshot_summary_basic(snap_df):
    result = generate_ai.serialize_snapshot_summary(snap_df)
    assert "Energy" in result
    assert "+12.0%" in result
    assert "PERFORMANCE SNAPSHOT" in result


def test_snapshot_summary_empty():
    result = generate_ai.serialize_snapshot_summary(pd.DataFrame())
    assert "No" in result


def test_snapshot_summary_sorted_by_ytd(snap_df):
    result = generate_ai.serialize_snapshot_summary(snap_df)
    energy_pos = result.index("Energy")
    tech_pos = result.index("Technology")
    assert energy_pos < tech_pos  # Energy (12% ytd) appears before Technology (-3% ytd)


# ---------------------------------------------------------------------------
# serialize_top_movers
# ---------------------------------------------------------------------------

def test_top_movers_basic(delta_df):
    result = generate_ai.serialize_top_movers(delta_df)
    assert "Energy" in result
    assert "TOP GAINERS" in result
    assert "TOP LOSERS" in result


def test_top_movers_empty_df():
    result = generate_ai.serialize_top_movers(pd.DataFrame())
    assert "No" in result


def test_top_movers_missing_delta_col():
    df = pd.DataFrame({"name": ["A"], "momentum_score": [0.5]})
    result = generate_ai.serialize_top_movers(df)
    assert "No" in result


def test_top_movers_all_nan_delta():
    df = pd.DataFrame({
        "name": ["A", "B"],
        "rank_ytd_delta_7d": [float("nan"), float("nan")],
    })
    result = generate_ai.serialize_top_movers(df)
    assert "No" in result


def test_top_movers_nan_rank_ytd_does_not_raise():
    # rank_ytd_delta_7d is valid but rank_ytd is NaN — must not raise ValueError
    df = pd.DataFrame({
        "name": ["A", "B"],
        "rank_ytd_delta_7d": [5.0, -3.0],
        "rank_ytd": [float("nan"), float("nan")],
        "momentum_score": [0.7, 0.3],
    })
    result = generate_ai.serialize_top_movers(df)
    assert "N/A" in result
    assert "A" in result


# ---------------------------------------------------------------------------
# serialize_momentum_leaders
# ---------------------------------------------------------------------------

def test_momentum_leaders_basic(delta_df):
    result = generate_ai.serialize_momentum_leaders(delta_df)
    assert "Energy" in result
    assert "0.850" in result
    assert "MOMENTUM LEADERS" in result


def test_momentum_leaders_empty():
    result = generate_ai.serialize_momentum_leaders(pd.DataFrame())
    assert "No" in result


def test_momentum_leaders_respects_n(delta_df):
    result = generate_ai.serialize_momentum_leaders(delta_df, n=1)
    assert "Energy" in result
    assert "Technology" not in result


# ---------------------------------------------------------------------------
# build_briefing_prompt
# ---------------------------------------------------------------------------

def test_briefing_prompt_contains_date(snap_df, delta_df):
    prompt = generate_ai.build_briefing_prompt("sector", snap_df, delta_df, "2026-06-10")
    assert "2026-06-10" in prompt


def test_briefing_prompt_contains_group_name(snap_df, delta_df):
    prompt = generate_ai.build_briefing_prompt("sector", snap_df, delta_df, "2026-06-10")
    assert "sectors" in prompt


def test_briefing_prompt_contains_data(snap_df, delta_df):
    prompt = generate_ai.build_briefing_prompt("sector", snap_df, delta_df, "2026-06-10")
    assert "Energy" in prompt


def test_briefing_prompt_industry_label(snap_df, delta_df):
    prompt = generate_ai.build_briefing_prompt("industry", snap_df, delta_df, "2026-06-10")
    assert "industries" in prompt


# ---------------------------------------------------------------------------
# build_phase_prompt
# ---------------------------------------------------------------------------

def test_phase_prompt_contains_date(snap_df, delta_df):
    prompt = generate_ai.build_phase_prompt(snap_df, delta_df, "2026-06-10")
    assert "2026-06-10" in prompt


def test_phase_prompt_lists_phases(snap_df, delta_df):
    prompt = generate_ai.build_phase_prompt(snap_df, delta_df, "2026-06-10")
    for phase in ["Early Cycle", "Mid Cycle", "Late Cycle", "Defensive"]:
        assert phase in prompt


# ---------------------------------------------------------------------------
# parse_phase_response
# ---------------------------------------------------------------------------

def test_parse_phase_structured():
    text = "PHASE: Late Cycle\nREASONING: Energy leads while Utilities lag."
    result = generate_ai.parse_phase_response(text)
    assert result["label"] == "Late Cycle"
    assert "Energy" in result["reasoning"]


def test_parse_phase_malformed():
    result = generate_ai.parse_phase_response("Something completely unexpected")
    assert result["label"] == "Unknown"
    assert "unexpected" in result["reasoning"]


def test_parse_phase_partial():
    result = generate_ai.parse_phase_response("PHASE: Mid Cycle")
    assert result["label"] == "Mid Cycle"


# ---------------------------------------------------------------------------
# parse_watchlist_response
# ---------------------------------------------------------------------------

def test_parse_watchlist_full():
    text = (
        "1. NAME: Energy | THESIS: Strong momentum across all timeframes.\n"
        "2. NAME: Financials | THESIS: Rising rank with high agreement.\n"
        "3. NAME: Industrials | THESIS: Consistent top-5 in month and quarter.\n"
    )
    result = generate_ai.parse_watchlist_response(text)
    assert len(result) == 3
    assert result[0]["name"] == "Energy"
    assert result[1]["name"] == "Financials"
    assert "momentum" in result[0]["thesis"].lower()


def test_parse_watchlist_empty():
    assert generate_ai.parse_watchlist_response("") == []


def test_parse_watchlist_skips_non_numbered_lines():
    text = "Here are the picks:\n1. NAME: Energy | THESIS: Good setup.\nExtra line\n"
    result = generate_ai.parse_watchlist_response(text)
    assert len(result) == 1
    assert result[0]["name"] == "Energy"


def test_parse_watchlist_missing_pipe():
    text = "1. NAME: Energy THESIS: No pipe character here.\n"
    result = generate_ai.parse_watchlist_response(text)
    assert result == []


# ---------------------------------------------------------------------------
# main exits gracefully without API key
# ---------------------------------------------------------------------------

def test_main_exits_zero_without_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(SystemExit) as exc_info:
        generate_ai.main()
    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# skip-trap: empty results must not write a file
# ---------------------------------------------------------------------------

def test_main_does_not_write_file_when_all_calls_fail(monkeypatch, tmp_path):
    # Simulate a total API outage: generate_for_group returns {} for both groups.
    from unittest.mock import MagicMock
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(generate_ai, "AI_DIR", tmp_path / "ai")
    monkeypatch.setattr(generate_ai, "generate_for_group", lambda *_: {})
    # Inject a fake google.generativeai so the lazy import inside main() succeeds
    monkeypatch.setitem(sys.modules, "google.generativeai", MagicMock())

    with pytest.raises(SystemExit) as exc_info:
        generate_ai.main()
    assert exc_info.value.code == 0
    # No JSON file should have been written — allows the next run to retry
    assert not any((tmp_path / "ai").glob("*.json"))
