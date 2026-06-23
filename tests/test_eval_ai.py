"""Tests for scripts/eval_ai.py — offline AI quality guards."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from eval_ai import (
    _name_in,
    check_hallucinations,
    check_format,
    check_capture,
    main,
    CONVICTION_LEVELS,
    PHASE_LABELS,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

KNOWN = {"Technology", "Financials", "Energy", "Healthcare", "Semiconductors", "Airlines"}


def make_call(task, raw="", parsed=None, input_blocks="", status="ok"):
    return {
        "input_blocks": input_blocks,
        "prompt": "...",
        "raw_response": raw,
        "parsed_output": parsed,
        "status": status,
    }


def make_capture(calls: dict) -> dict:
    return {"date": "2026-06-22", "model": "test", "calls": calls}


# ---------------------------------------------------------------------------
# _name_in
# ---------------------------------------------------------------------------

def test_name_in_exact():
    assert _name_in("Technology", "Technology leads the market")


def test_name_in_case_insensitive():
    assert _name_in("Healthcare", "healthcare is defensive")


def test_name_in_word_boundary():
    assert not _name_in("Energy", "energetics are rising")


def test_name_in_absent():
    assert not _name_in("Financials", "Tech and Healthcare lead")


# ---------------------------------------------------------------------------
# check_hallucinations
# ---------------------------------------------------------------------------

def test_hallucination_catches_name_absent_from_input():
    call = make_call(
        "pulse",
        raw="Technology leads the market broadly.",
        input_blocks="MARKET STATE: breadth 5/5",  # "Technology" NOT here
    )
    issues = check_hallucinations("sectors.pulse", call, {"Technology"})
    assert any("hallucination" in i and "Technology" in i for i in issues)


def test_hallucination_passes_when_name_in_input():
    call = make_call(
        "pulse",
        raw="Technology leads the market broadly.",
        input_blocks="TOP GAINERS: Technology δ=+3 mom=0.88",
    )
    issues = check_hallucinations("sectors.pulse", call, {"Technology"})
    assert issues == []


def test_hallucination_empty_raw_no_issues():
    call = make_call("pulse", raw="", input_blocks="")
    assert check_hallucinations("sectors.pulse", call, KNOWN) == []


def test_hallucination_empty_known_no_issues():
    call = make_call("pulse", raw="Technology leads", input_blocks="")
    assert check_hallucinations("sectors.pulse", call, set()) == []


def test_hallucination_multi_names():
    call = make_call(
        "note",
        raw="Energy is rising. Financials lag. Semiconductors break out.",
        input_blocks="TOP GAINERS: Energy δ=+5",  # only Energy in input
    )
    issues = check_hallucinations("sectors.note", call, {"Energy", "Financials", "Semiconductors"})
    names_flagged = [i for i in issues if "hallucination" in i]
    assert any("Financials" in i for i in names_flagged)
    assert any("Semiconductors" in i for i in names_flagged)
    # Energy was in input — should NOT be flagged
    assert not any("Energy" in i for i in names_flagged)


# ---------------------------------------------------------------------------
# check_format — pulse
# ---------------------------------------------------------------------------

def test_format_pulse_good():
    call = make_call(
        "pulse",
        parsed={"headline": "Tech leads broad recovery", "conviction": {"level": "High", "why": "All-green breadth"}},
    )
    assert check_format("sectors.pulse", call) == []


def test_format_pulse_bad_level():
    call = make_call(
        "pulse",
        parsed={"headline": "Tech leads", "conviction": {"level": "Very High", "why": "..."}},
    )
    issues = check_format("sectors.pulse", call)
    assert any("conviction.level" in i and "Very High" in i for i in issues)


def test_format_pulse_empty_headline():
    call = make_call(
        "pulse",
        parsed={"headline": "", "conviction": {"level": "High", "why": "..."}},
    )
    issues = check_format("sectors.pulse", call)
    assert any("headline is empty" in i for i in issues)


def test_format_pulse_none_parsed():
    call = make_call("pulse", parsed=None)
    issues = check_format("sectors.pulse", call)
    assert any("not a dict" in i for i in issues)


def test_format_pulse_conviction_not_dict():
    call = make_call(
        "pulse",
        parsed={"headline": "X", "conviction": "High"},
    )
    issues = check_format("sectors.pulse", call)
    assert any("conviction is not a dict" in i for i in issues)


def test_format_pulse_all_valid_levels():
    for level in CONVICTION_LEVELS:
        call = make_call(
            "pulse",
            parsed={"headline": "X", "conviction": {"level": level, "why": "ok"}},
        )
        assert check_format("sectors.pulse", call) == []


# ---------------------------------------------------------------------------
# check_format — rotation_phase
# ---------------------------------------------------------------------------

def test_format_rotation_phase_good():
    for label in PHASE_LABELS:
        call = make_call("rotation_phase", parsed={"label": label, "reasoning": "..."})
        assert check_format("sectors.rotation_phase", call) == []


def test_format_rotation_phase_bad_label():
    call = make_call("rotation_phase", parsed={"label": "Unknown Cycle", "reasoning": "..."})
    issues = check_format("sectors.rotation_phase", call)
    assert any("rotation_phase label" in i and "Unknown Cycle" in i for i in issues)


def test_format_rotation_phase_empty_label():
    call = make_call("rotation_phase", parsed={"label": "", "reasoning": "..."})
    issues = check_format("sectors.rotation_phase", call)
    assert any("rotation_phase label" in i for i in issues)


def test_format_rotation_phase_not_dict():
    call = make_call("rotation_phase", parsed="Early Cycle")
    issues = check_format("sectors.rotation_phase", call)
    assert any("not a dict" in i for i in issues)


# ---------------------------------------------------------------------------
# check_format — watchlist
# ---------------------------------------------------------------------------

def test_format_watchlist_ok():
    raw = "- Technology: rs_cross\n- Energy: rs_new_high\n- Financials: emerging"
    call = make_call("watchlist", raw=raw)
    assert check_format("sectors.watchlist", call) == []


def test_format_watchlist_five_bullets_ok():
    raw = "\n".join(f"- Group{i}: trigger" for i in range(5))
    call = make_call("watchlist", raw=raw)
    assert check_format("sectors.watchlist", call) == []


def test_format_watchlist_too_many_bullets():
    raw = "\n".join(f"- Group{i}: trigger" for i in range(6))
    call = make_call("watchlist", raw=raw)
    issues = check_format("sectors.watchlist", call)
    assert any("6 bullets" in i for i in issues)


def test_format_watchlist_star_bullets():
    raw = "\n".join(f"* Group{i}: trigger" for i in range(7))
    call = make_call("watchlist", raw=raw)
    issues = check_format("sectors.watchlist", call)
    assert any("7 bullets" in i for i in issues)


# ---------------------------------------------------------------------------
# check_format — risk_radar
# ---------------------------------------------------------------------------

def test_format_risk_radar_good():
    call = make_call(
        "risk_radar",
        parsed={"relative_strength": "Tech beats SPY.", "risks": "Energy fading."},
    )
    assert check_format("sectors.risk_radar", call) == []


def test_format_risk_radar_missing_rs():
    call = make_call(
        "risk_radar",
        parsed={"relative_strength": "", "risks": "Energy fading."},
    )
    issues = check_format("sectors.risk_radar", call)
    assert any("relative_strength" in i for i in issues)


def test_format_risk_radar_missing_risks():
    call = make_call(
        "risk_radar",
        parsed={"relative_strength": "Tech leads.", "risks": ""},
    )
    issues = check_format("sectors.risk_radar", call)
    assert any("risks" in i for i in issues)


def test_format_risk_radar_not_dict():
    call = make_call("risk_radar", parsed="some string")
    issues = check_format("sectors.risk_radar", call)
    assert any("not a dict" in i for i in issues)


# ---------------------------------------------------------------------------
# check_format — skip non-ok status
# ---------------------------------------------------------------------------

def test_format_skips_error_status():
    call = make_call("pulse", parsed=None, status="error")
    assert check_format("sectors.pulse", call) == []


def test_format_skips_quota_exhausted():
    call = make_call("rotation_phase", parsed=None, status="quota_exhausted")
    assert check_format("sectors.rotation_phase", call) == []


# ---------------------------------------------------------------------------
# check_format — note and rotation_map (no format constraints)
# ---------------------------------------------------------------------------

def test_format_note_no_checks():
    call = make_call("note", raw="Any text.", parsed=None)
    assert check_format("sectors.note", call) == []


def test_format_rotation_map_no_checks():
    call = make_call("rotation_map", raw="Any text.", parsed=None)
    assert check_format("sectors.rotation_map", call) == []


# ---------------------------------------------------------------------------
# check_capture
# ---------------------------------------------------------------------------

def test_check_capture_clean():
    capture = make_capture({
        "sectors.pulse": make_call(
            "pulse",
            raw="Technology leads",
            input_blocks="Technology δ=+3",
            parsed={"headline": "Tech leads", "conviction": {"level": "High", "why": "..."}},
        ),
        "sectors.rotation_phase": make_call(
            "rotation_phase",
            raw="Label: Mid Cycle\nWhy: Tech leads",
            input_blocks="Technology δ=+3",
            parsed={"label": "Mid Cycle", "reasoning": "Tech leads"},
        ),
    })
    assert check_capture(capture, {"Technology"}) == []


def test_check_capture_with_issues():
    capture = make_capture({
        "sectors.pulse": make_call(
            "pulse",
            raw="Financials lead strongly",  # Financials not in input
            input_blocks="Technology δ=+3",
            parsed={"headline": "", "conviction": {"level": "VeryHigh", "why": "..."}},
        ),
    })
    issues = check_capture(capture, {"Technology", "Financials"})
    assert len(issues) > 0
    # Should have a header line for the fkey
    assert any("[sectors.pulse]" in i for i in issues)


def test_check_capture_skip_hallucination():
    capture = make_capture({
        "sectors.pulse": make_call(
            "pulse",
            raw="Financials lead",
            input_blocks="",
            parsed={"headline": "ok", "conviction": {"level": "High", "why": "..."}},
        ),
    })
    # With skip_hallucination=True, Financials mention should not be flagged
    issues = check_capture(capture, {"Financials"}, skip_hallucination=True)
    assert not any("hallucination" in i for i in issues)


def test_check_capture_no_calls():
    capture = {"date": "2026-06-22", "calls": {}}
    assert check_capture(capture, KNOWN) == []


# ---------------------------------------------------------------------------
# main() integration
# ---------------------------------------------------------------------------

def test_main_no_files_returns_zero(tmp_path):
    # Point DEBUG_DIR to an empty directory
    import eval_ai
    orig = eval_ai.DEBUG_DIR
    eval_ai.DEBUG_DIR = tmp_path
    try:
        rc = main([])
        assert rc == 0
    finally:
        eval_ai.DEBUG_DIR = orig


def test_main_good_file_returns_zero(tmp_path):
    capture = make_capture({
        "sectors.pulse": make_call(
            "pulse",
            raw="Technology is strong",
            input_blocks="Technology δ=+3",
            parsed={"headline": "Tech leads", "conviction": {"level": "High", "why": "ok"}},
        ),
        "sectors.rotation_phase": make_call(
            "rotation_phase",
            raw="Label: Mid Cycle\nWhy: ...",
            input_blocks="...",
            parsed={"label": "Mid Cycle", "reasoning": "..."},
        ),
    })
    p = tmp_path / "2026-06-22.json"
    p.write_text(json.dumps(capture), encoding="utf-8")
    rc = main([str(p), "--no-hallucination"])
    assert rc == 0


def test_main_bad_file_returns_one(tmp_path):
    capture = make_capture({
        "sectors.pulse": make_call(
            "pulse",
            parsed={"headline": "", "conviction": {"level": "UNKNOWN", "why": ""}},
        ),
    })
    p = tmp_path / "2026-06-22.json"
    p.write_text(json.dumps(capture), encoding="utf-8")
    rc = main([str(p), "--no-hallucination"])
    assert rc == 1


def test_main_invalid_json_returns_one(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("not json", encoding="utf-8")
    rc = main([str(p)])
    assert rc == 1


def test_main_date_flag_missing_returns_zero(tmp_path):
    import eval_ai
    orig = eval_ai.DEBUG_DIR
    eval_ai.DEBUG_DIR = tmp_path
    try:
        rc = main(["--date", "2099-01-01"])
        assert rc == 0
    finally:
        eval_ai.DEBUG_DIR = orig


def test_main_all_flag(tmp_path):
    for date in ("2026-06-20", "2026-06-21", "2026-06-22"):
        capture = make_capture({
            "sectors.rotation_phase": make_call(
                "rotation_phase",
                parsed={"label": "Mid Cycle", "reasoning": "ok"},
            )
        })
        (tmp_path / f"{date}.json").write_text(json.dumps(capture), encoding="utf-8")
    import eval_ai
    orig = eval_ai.DEBUG_DIR
    eval_ai.DEBUG_DIR = tmp_path
    try:
        rc = main(["--all", "--no-hallucination"])
        assert rc == 0
    finally:
        eval_ai.DEBUG_DIR = orig
