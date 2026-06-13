"""
Tests for scripts/generate_ai.py pure functions.
No real filesystem I/O, no real API calls.
"""

import json
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


def test_parse_watchlist_with_conviction():
    text = (
        "1. NAME: Energy | THESIS: Strong momentum. | CONVICTION: strong\n"
        "2. NAME: Financials | THESIS: Mixed signals. | CONVICTION: moderate\n"
        "3. NAME: Tech | THESIS: Early rotation. | CONVICTION: speculative\n"
    )
    result = generate_ai.parse_watchlist_response(text)
    assert len(result) == 3
    assert result[0]["conviction"] == "strong"
    assert result[1]["conviction"] == "moderate"
    assert result[2]["conviction"] == "speculative"


def test_parse_watchlist_invalid_conviction_omitted():
    text = "1. NAME: Energy | THESIS: Good setup. | CONVICTION: high\n"
    result = generate_ai.parse_watchlist_response(text)
    assert len(result) == 1
    assert "conviction" not in result[0]


def test_parse_watchlist_missing_conviction_omitted():
    text = "1. NAME: Energy | THESIS: Good setup.\n"
    result = generate_ai.parse_watchlist_response(text)
    assert len(result) == 1
    assert "conviction" not in result[0]


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
# _call_api
# ---------------------------------------------------------------------------

def _make_client(responses):
    """Return a fake client whose generate_content() yields responses in order.
    Each entry is either a string (success) or an exception instance (raise)."""
    from unittest.mock import MagicMock
    call_count = {"n": 0}

    def _generate_content(**_kwargs):
        idx = call_count["n"]
        call_count["n"] += 1
        r = responses[idx]
        if isinstance(r, Exception):
            raise r
        mock_resp = MagicMock()
        mock_resp.text = r
        return mock_resp

    client = MagicMock()
    client.models.generate_content.side_effect = _generate_content
    return client


# ---------------------------------------------------------------------------
# PHASE_SCHEMA and WATCHLIST_SCHEMA constants
# ---------------------------------------------------------------------------

def test_gemini_model_is_pinned_version():
    assert generate_ai.GEMINI_MODEL == "gemini-2.5-flash"


def test_phase_schema_required_fields():
    assert generate_ai.PHASE_SCHEMA["required"] == ["label", "reasoning", "confidence"]
    enum_vals = generate_ai.PHASE_SCHEMA["properties"]["label"]["enum"]
    assert set(enum_vals) == {"Early Cycle", "Mid Cycle", "Late Cycle", "Defensive"}


def test_watchlist_schema_has_picks_array():
    assert "picks" in generate_ai.WATCHLIST_SCHEMA["properties"]
    assert generate_ai.WATCHLIST_SCHEMA["properties"]["picks"]["type"] == "array"
    assert generate_ai.WATCHLIST_SCHEMA["required"] == ["picks"]
    item_props = generate_ai.WATCHLIST_SCHEMA["properties"]["picks"]["items"]["properties"]
    assert "name" in item_props and "thesis" in item_props
    assert "conviction" in item_props
    conviction_enum = item_props["conviction"]["enum"]
    assert set(conviction_enum) == {"strong", "moderate", "speculative"}
    item_required = generate_ai.WATCHLIST_SCHEMA["properties"]["picks"]["items"]["required"]
    assert "conviction" in item_required


def test_briefing_schema_has_key_signals_and_briefing():
    schema = generate_ai.BRIEFING_SCHEMA
    assert schema["required"] == ["key_signals", "briefing"]
    assert schema["properties"]["key_signals"]["type"] == "array"
    assert schema["properties"]["key_signals"]["items"]["type"] == "string"
    assert schema["properties"]["briefing"]["type"] == "string"


# ---------------------------------------------------------------------------
# parse_briefing_response
# ---------------------------------------------------------------------------

def test_parse_briefing_response_plain_text():
    result = generate_ai.parse_briefing_response("Some market analysis text.")
    assert result["briefing"] == "Some market analysis text."
    assert result["key_signals"] == []


def test_parse_briefing_response_strips_whitespace():
    result = generate_ai.parse_briefing_response("  text with spaces  \n")
    assert result["briefing"] == "text with spaces"


# ---------------------------------------------------------------------------
# generate_for_group briefing JSON extraction
# ---------------------------------------------------------------------------

def test_generate_for_group_briefing_extracts_key_signals(monkeypatch):
    """When briefing returns valid JSON, both briefing and key_signals are stored."""
    from unittest.mock import MagicMock
    monkeypatch.setattr(generate_ai, "_last_api_call", 0.0)
    monkeypatch.setattr("time.sleep", lambda _: None)
    generate_ai._reset_tracking()
    mock_genai = MagicMock()
    monkeypatch.setitem(sys.modules, "google.genai", mock_genai)

    snap = pd.DataFrame({
        "date": [pd.Timestamp("2026-06-11").date()],
        "name": ["Energy"],
        "perf_week": [2.0], "perf_month": [3.0], "perf_ytd": [5.0],
    })
    delta = pd.DataFrame({
        "date": [pd.Timestamp("2026-06-11").date()],
        "name": ["Energy"],
        "rank_ytd": [1.0], "rank_ytd_delta_7d": [2.0], "momentum_score": [0.8],
    })
    monkeypatch.setattr(generate_ai, "load_latest_snapshot", lambda _: snap)
    monkeypatch.setattr(generate_ai, "load_latest_delta", lambda _: delta)

    signals = ["Energy +5% YTD, rank #1", "Momentum score 0.80", "7d rank gain +2 spots"]
    briefing_json = json.dumps({"key_signals": signals, "briefing": "Energy is leading."})
    client = _make_client([briefing_json, "PHASE: Late Cycle\nREASONING: Energy leads.",
                           "1. NAME: Energy | THESIS: Strong.\n2. NAME: Fin | THESIS: Ok.\n3. NAME: Tech | THESIS: Watch."])
    result = generate_ai.generate_for_group(client, "sector", "2026-06-11")

    assert result["briefing"] == "Energy is leading."
    assert result["key_signals"] == signals


def test_generate_for_group_briefing_fallback_no_key_signals(monkeypatch):
    """When briefing JSON parse fails, prose is stored without key_signals."""
    from unittest.mock import MagicMock
    monkeypatch.setattr(generate_ai, "_last_api_call", 0.0)
    monkeypatch.setattr("time.sleep", lambda _: None)
    generate_ai._reset_tracking()
    mock_genai = MagicMock()
    monkeypatch.setitem(sys.modules, "google.genai", mock_genai)

    snap = pd.DataFrame({
        "date": [pd.Timestamp("2026-06-11").date()],
        "name": ["Energy"],
        "perf_week": [2.0], "perf_month": [3.0], "perf_ytd": [5.0],
    })
    delta = pd.DataFrame({
        "date": [pd.Timestamp("2026-06-11").date()],
        "name": ["Energy"],
        "rank_ytd": [1.0], "rank_ytd_delta_7d": [2.0], "momentum_score": [0.8],
    })
    monkeypatch.setattr(generate_ai, "load_latest_snapshot", lambda _: snap)
    monkeypatch.setattr(generate_ai, "load_latest_delta", lambda _: delta)

    client = _make_client(["Plain text briefing — not JSON.",
                           "PHASE: Late Cycle\nREASONING: Energy leads.",
                           "1. NAME: Energy | THESIS: Strong.\n2. NAME: Fin | THESIS: Ok.\n3. NAME: Tech | THESIS: Watch."])
    result = generate_ai.generate_for_group(client, "sector", "2026-06-11")

    assert result["briefing"] == "Plain text briefing — not JSON."
    assert "key_signals" not in result


# ---------------------------------------------------------------------------
# TASK_SPECS and _expected_fields
# ---------------------------------------------------------------------------

def test_task_specs_has_expected_names():
    names = {s["name"] for s in generate_ai.TASK_SPECS}
    assert names == {"briefing", "rotation_phase", "watchlist"}


def test_industry_phase_schema_has_free_form_label():
    schema = generate_ai.INDUSTRY_PHASE_SCHEMA
    assert schema["required"] == ["label", "reasoning", "confidence"]
    # Free-form label — no enum constraint
    assert "enum" not in schema["properties"]["label"]
    assert schema["properties"]["label"]["type"] == "string"


def test_task_specs_rotation_phase_covers_both_group_types():
    phase_specs = [s for s in generate_ai.TASK_SPECS if s["name"] == "rotation_phase"]
    assert len(phase_specs) == 2
    gtypes = {gt for s in phase_specs for gt in s["group_types"]}
    assert gtypes == {"sector", "industry"}
    sector_spec = next(s for s in phase_specs if "sector" in s["group_types"])
    assert sector_spec["response_schema"] is generate_ai.PHASE_SCHEMA
    industry_spec = next(s for s in phase_specs if "industry" in s["group_types"])
    assert industry_spec["response_schema"] is generate_ai.INDUSTRY_PHASE_SCHEMA


def test_task_specs_watchlist_covers_both_group_types():
    watchlist_specs = [s for s in generate_ai.TASK_SPECS if s["name"] == "watchlist"]
    assert len(watchlist_specs) == 2
    gtypes = {gt for s in watchlist_specs for gt in s["group_types"]}
    assert gtypes == {"sector", "industry"}


def test_task_specs_briefing_covers_both_group_types():
    spec = next(s for s in generate_ai.TASK_SPECS if s["name"] == "briefing")
    assert "sector" in spec["group_types"]
    assert "industry" in spec["group_types"]
    assert spec["use_json_schema"] is True
    assert spec["response_schema"] is generate_ai.BRIEFING_SCHEMA


def test_task_specs_rotation_phase_sector_only():
    spec = next(s for s in generate_ai.TASK_SPECS if s["name"] == "rotation_phase")
    assert spec["group_types"] == ("sector",)
    assert spec["use_json_schema"] is True
    assert spec["response_schema"] is generate_ai.PHASE_SCHEMA


def test_task_specs_watchlist_sector_only():
    spec = next(s for s in generate_ai.TASK_SPECS if s["name"] == "watchlist")
    assert spec["group_types"] == ("sector",)
    assert spec["use_json_schema"] is True
    assert spec["response_schema"] is generate_ai.WATCHLIST_SCHEMA


def test_expected_fields_returns_all_six():
    fields = set(generate_ai._expected_fields())
    assert fields == {
        "sectors.briefing",
        "sectors.rotation_phase",
        "sectors.watchlist",
        "industries.briefing",
        "industries.rotation_phase",
        "industries.watchlist",
    }


def test_generate_for_group_industry_calls_api_three_times(monkeypatch):
    """Industry group now runs briefing, rotation_phase, and watchlist — 3 API calls."""
    from unittest.mock import MagicMock
    monkeypatch.setattr(generate_ai, "_last_api_call", 0.0)
    monkeypatch.setattr("time.sleep", lambda _: None)
    generate_ai._reset_tracking()
    mock_genai = MagicMock()
    monkeypatch.setitem(sys.modules, "google.genai", mock_genai)

    snap = pd.DataFrame({
        "date": [pd.Timestamp("2026-06-11").date()],
        "name": ["Software"],
        "perf_week": [1.0], "perf_month": [2.0], "perf_ytd": [3.0],
    })
    delta = pd.DataFrame({
        "date": [pd.Timestamp("2026-06-11").date()],
        "name": ["Software"],
        "rank_ytd": [1.0], "rank_ytd_delta_7d": [1.0], "momentum_score": [0.7],
    })
    monkeypatch.setattr(generate_ai, "load_latest_snapshot", lambda _: snap)
    monkeypatch.setattr(generate_ai, "load_latest_delta", lambda _: delta)

    briefing_json = json.dumps({
        "key_signals": ["Software up 3% YTD", "Momentum score 0.70", "Rank stable week-over-week"],
        "briefing": "Industry briefing text",
    })
    client = _make_client([
        briefing_json,
        "PHASE: Tech pullback\nREASONING: Software leading defensively.",
        "1. NAME: Software | THESIS: Strong trend. | CONVICTION: strong\n"
        "2. NAME: Retail | THESIS: Early bid. | CONVICTION: moderate\n"
        "3. NAME: Energy | THESIS: Watch. | CONVICTION: speculative",
    ])
    result = generate_ai.generate_for_group(client, "industry", "2026-06-11")

    assert client.models.generate_content.call_count == 3
    assert result.get("briefing") == "Industry briefing text"
    assert result.get("key_signals") == ["Software up 3% YTD", "Momentum score 0.70", "Rank stable week-over-week"]
    assert result.get("rotation_phase", {}).get("label") == "Tech pullback"
    assert isinstance(result.get("watchlist"), list)


def test_generate_for_group_empty_snapshot_returns_existing(monkeypatch):
    """Empty snapshot returns existing dict unchanged and records no_data/skipped."""
    generate_ai._reset_tracking()
    monkeypatch.setattr(generate_ai, "load_latest_snapshot", lambda _: pd.DataFrame())
    monkeypatch.setattr(generate_ai, "load_latest_delta", lambda _: pd.DataFrame())

    existing = {"briefing": "old briefing"}
    client = _make_client([])
    result = generate_ai.generate_for_group(client, "sector", "2026-06-11", existing=existing)

    assert result == existing
    assert client.models.generate_content.call_count == 0
    assert generate_ai._field_log["sectors.briefing"]["status"] == "skipped"
    assert generate_ai._field_log["sectors.rotation_phase"]["status"] == "no_data"


def test_generate_for_group_industry_empty_snapshot_records_no_data(monkeypatch):
    """Industry empty snapshot records no_data for rotation_phase and watchlist."""
    generate_ai._reset_tracking()
    monkeypatch.setattr(generate_ai, "load_latest_snapshot", lambda _: pd.DataFrame())
    monkeypatch.setattr(generate_ai, "load_latest_delta", lambda _: pd.DataFrame())

    client = _make_client([])
    generate_ai.generate_for_group(client, "industry", "2026-06-11")

    assert client.models.generate_content.call_count == 0
    assert generate_ai._field_log["industries.rotation_phase"]["status"] == "no_data"
    assert generate_ai._field_log["industries.watchlist"]["status"] == "no_data"


def test_generate_for_group_json_parse_fallback(monkeypatch):
    """If JSON parse fails for rotation_phase, fallback parser is used."""
    from unittest.mock import MagicMock
    monkeypatch.setattr(generate_ai, "_last_api_call", 0.0)
    monkeypatch.setattr("time.sleep", lambda _: None)
    generate_ai._reset_tracking()
    # Phase/watchlist specs trigger the google.genai lazy import — mock it for CI.
    mock_genai = MagicMock()
    monkeypatch.setitem(sys.modules, "google.genai", mock_genai)

    snap = pd.DataFrame({
        "date": [pd.Timestamp("2026-06-11").date()],
        "name": ["Energy"],
        "perf_week": [2.0], "perf_month": [3.0], "perf_ytd": [5.0],
    })
    delta = pd.DataFrame({
        "date": [pd.Timestamp("2026-06-11").date()],
        "name": ["Energy"],
        "rank_ytd": [1.0], "rank_ytd_delta_7d": [2.0], "momentum_score": [0.8],
    })
    monkeypatch.setattr(generate_ai, "load_latest_snapshot", lambda _: snap)
    monkeypatch.setattr(generate_ai, "load_latest_delta", lambda _: delta)

    # API returns text format (JSON parse will fail → triggers fallback_parse)
    client = _make_client([
        "Market briefing text",
        "PHASE: Late Cycle\nREASONING: Energy leads.",
        "1. NAME: Energy | THESIS: Strong setup.\n2. NAME: Financials | THESIS: Rising.\n3. NAME: Tech | THESIS: Holding.",
    ])
    result = generate_ai.generate_for_group(client, "sector", "2026-06-11")

    assert result["rotation_phase"]["label"] == "Late Cycle"
    assert isinstance(result["watchlist"], list)


def test_call_api_happy_path(monkeypatch):
    monkeypatch.setattr(generate_ai, "_last_api_call", 0.0)
    monkeypatch.setattr("time.sleep", lambda _: None)
    client = _make_client(["  hello world  "])
    result = generate_ai._call_api(client, "prompt")
    assert result == "hello world"


def test_call_api_retries_on_quota_error(monkeypatch):
    monkeypatch.setattr(generate_ai, "_last_api_call", 0.0)
    sleep_calls = []
    monkeypatch.setattr("time.sleep", lambda s: sleep_calls.append(s))
    client = _make_client([Exception("429 quota exceeded"), "ok"])
    result = generate_ai._call_api(client, "prompt")
    assert result == "ok"
    assert len(sleep_calls) >= 1  # slept before retry


def test_call_api_reraises_non_quota_exception_immediately(monkeypatch):
    monkeypatch.setattr(generate_ai, "_last_api_call", 0.0)
    monkeypatch.setattr("time.sleep", lambda _: None)
    client = _make_client([ValueError("unrelated error")])
    with pytest.raises(ValueError, match="unrelated error"):
        generate_ai._call_api(client, "prompt")
    assert client.models.generate_content.call_count == 1


def test_call_api_reraises_after_max_retries(monkeypatch):
    monkeypatch.setattr(generate_ai, "_last_api_call", 0.0)
    monkeypatch.setattr("time.sleep", lambda _: None)
    quota_err = Exception("429 quota exceeded")
    client = _make_client([quota_err] * 4)  # fail all 4 attempts (0..3)
    with pytest.raises(Exception, match="429"):
        generate_ai._call_api(client, "prompt", max_retries=3)
    assert client.models.generate_content.call_count == 4  # initial + 3 retries


def test_call_api_no_schema_omits_config_kwarg(monkeypatch):
    """Without schema kwargs, generate_content is called without a config kwarg."""
    monkeypatch.setattr(generate_ai, "_last_api_call", 0.0)
    monkeypatch.setattr("time.sleep", lambda _: None)
    client = _make_client(["result"])
    generate_ai._call_api(client, "prompt")
    call_kwargs = client.models.generate_content.call_args[1]
    assert "config" not in call_kwargs


def test_call_api_passes_response_schema_as_config(monkeypatch):
    """With response_schema, generate_content receives a config kwarg with response_mime_type=application/json."""
    from unittest.mock import MagicMock
    monkeypatch.setattr(generate_ai, "_last_api_call", 0.0)
    monkeypatch.setattr("time.sleep", lambda _: None)

    mock_config_instance = MagicMock()
    mock_types = MagicMock()
    mock_types.GenerateContentConfig.return_value = mock_config_instance
    mock_genai_module = MagicMock()
    mock_genai_module.types = mock_types
    monkeypatch.setitem(sys.modules, "google.genai", mock_genai_module)

    schema = generate_ai.PHASE_SCHEMA
    client = _make_client(["result"])
    result = generate_ai._call_api(client, "prompt", response_schema=schema)

    assert result == "result"
    mock_types.GenerateContentConfig.assert_called_once()
    ctor_kwargs = mock_types.GenerateContentConfig.call_args[1]
    assert ctor_kwargs["response_mime_type"] == "application/json"
    assert ctor_kwargs["response_schema"] == schema

    call_kwargs = client.models.generate_content.call_args[1]
    assert "config" in call_kwargs
    assert call_kwargs["config"] is mock_config_instance


def test_call_api_passes_generation_config_values(monkeypatch):
    """Custom temperature and max_output_tokens are forwarded to GenerateContentConfig."""
    from unittest.mock import MagicMock
    monkeypatch.setattr(generate_ai, "_last_api_call", 0.0)
    monkeypatch.setattr("time.sleep", lambda _: None)

    mock_types = MagicMock()
    mock_genai_module = MagicMock()
    mock_genai_module.types = mock_types
    monkeypatch.setitem(sys.modules, "google.genai", mock_genai_module)

    client = _make_client(["result"])
    generate_ai._call_api(
        client, "prompt",
        generation_config={"temperature": 0.2, "max_output_tokens": 300},
        response_schema=generate_ai.PHASE_SCHEMA,  # schema required to trigger config build
    )

    ctor_kwargs = mock_types.GenerateContentConfig.call_args[1]
    assert ctor_kwargs["temperature"] == 0.2
    assert ctor_kwargs["max_output_tokens"] == 300


# ---------------------------------------------------------------------------
# main exits gracefully without API key
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# _find_prior_ai_file
# ---------------------------------------------------------------------------

def test_find_prior_ai_file_returns_nearest(tmp_path):
    orig = generate_ai.AI_DIR
    generate_ai.AI_DIR = tmp_path
    (tmp_path / "2026-06-10.json").write_text("{}")
    result = generate_ai._find_prior_ai_file("2026-06-11")
    generate_ai.AI_DIR = orig
    assert result is not None
    assert result.name == "2026-06-10.json"


def test_find_prior_ai_file_returns_none_when_missing(tmp_path):
    orig = generate_ai.AI_DIR
    generate_ai.AI_DIR = tmp_path
    result = generate_ai._find_prior_ai_file("2026-06-11")
    generate_ai.AI_DIR = orig
    assert result is None


def test_find_prior_ai_file_skips_beyond_5_days(tmp_path):
    orig = generate_ai.AI_DIR
    generate_ai.AI_DIR = tmp_path
    (tmp_path / "2026-06-04.json").write_text("{}")  # 7 days before June 11
    result = generate_ai._find_prior_ai_file("2026-06-11")
    generate_ai.AI_DIR = orig
    assert result is None


def test_find_prior_ai_file_skips_weekends_finds_friday(tmp_path):
    orig = generate_ai.AI_DIR
    generate_ai.AI_DIR = tmp_path
    (tmp_path / "2026-06-05.json").write_text("{}")  # Friday, 2 days before Monday June 8
    result = generate_ai._find_prior_ai_file("2026-06-08")
    generate_ai.AI_DIR = orig
    assert result is not None
    assert result.name == "2026-06-05.json"


def test_find_prior_ai_file_invalid_date():
    result = generate_ai._find_prior_ai_file("not-a-date")
    assert result is None


# ---------------------------------------------------------------------------
# _update_index
# ---------------------------------------------------------------------------

def test_update_index_creates_file_if_missing(tmp_path):
    idx = _run_update_index(tmp_path, "2026-06-11", "complete", {"generated_at": "2026-06-11T22:00:00Z"})
    assert len(idx["entries"]) == 1
    assert idx["entries"][0]["date"] == "2026-06-11"
    assert idx["entries"][0]["status"] == "complete"


def _run_update_index(tmp_path, date_str, status, output):
    orig = generate_ai.AI_DIR
    generate_ai.AI_DIR = tmp_path
    generate_ai._update_index(date_str, status, output)
    generate_ai.AI_DIR = orig
    return json.loads((tmp_path / "index.json").read_text())


def test_update_index_upserts_same_date(tmp_path):
    out = {"generated_at": "2026-06-11T22:00:00Z"}
    _run_update_index(tmp_path, "2026-06-11", "partial", out)
    idx = _run_update_index(tmp_path, "2026-06-11", "complete", out)
    dates = [e["date"] for e in idx["entries"]]
    assert dates.count("2026-06-11") == 1
    assert idx["entries"][0]["status"] == "complete"


def test_update_index_newest_first(tmp_path):
    out = {"generated_at": ""}
    for d in ["2026-06-09", "2026-06-11", "2026-06-10"]:
        _run_update_index(tmp_path, d, "complete", out)
    idx = json.loads((tmp_path / "index.json").read_text())
    dates = [e["date"] for e in idx["entries"]]
    assert dates == sorted(dates, reverse=True)


def test_update_index_trims_to_90(tmp_path):
    orig = generate_ai.AI_DIR
    generate_ai.AI_DIR = tmp_path
    # Seed with 90 existing entries
    entries = [{"date": f"2025-{i:04d}", "status": "complete"} for i in range(90)]
    (tmp_path / "index.json").write_text(json.dumps({"entries": entries}))
    generate_ai._update_index("2026-06-11", "complete", {"generated_at": ""})
    generate_ai.AI_DIR = orig
    idx = json.loads((tmp_path / "index.json").read_text())
    assert len(idx["entries"]) == 90


def test_update_index_corrupt_file_fallback(tmp_path):
    (tmp_path / "index.json").write_text("NOTJSON")
    idx = _run_update_index(tmp_path, "2026-06-11", "complete", {"generated_at": ""})
    assert len(idx["entries"]) == 1
    assert idx["entries"][0]["date"] == "2026-06-11"


def test_update_index_rotation_phase_extracted(tmp_path):
    output = {
        "generated_at": "2026-06-11T22:00:00Z",
        "sectors": {
            "rotation_phase": {"label": "Late Cycle", "reasoning": "Energy leads."}
        },
    }
    idx = _run_update_index(tmp_path, "2026-06-11", "complete", output)
    assert idx["entries"][0]["rotation_phase"] == "Late Cycle"


def test_update_index_missing_rotation_phase(tmp_path):
    idx = _run_update_index(tmp_path, "2026-06-11", "complete", {"generated_at": ""})
    assert idx["entries"][0]["rotation_phase"] == ""


def test_main_exits_zero_without_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("FORCE_AI", raising=False)
    monkeypatch.setattr(generate_ai, "AI_DIR", tmp_path / "ai")
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)
    monkeypatch.setattr(generate_ai, "_has_new_delta_data", lambda _: True)
    with pytest.raises(SystemExit) as exc_info:
        generate_ai.main()
    assert exc_info.value.code == 0


def _write_snap_csv(sectors_dir, snap_date):
    import csv
    snap_csv = sectors_dir / "snapshots.csv"
    with open(snap_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "name", "perf_week", "perf_ytd"])
        writer.writeheader()
        writer.writerow({"date": snap_date, "name": "Energy", "perf_week": "1.0", "perf_ytd": "5.0"})


def test_main_uses_snapshot_date_not_today(monkeypatch, tmp_path):
    """AI file name must match the latest snapshot date, not date.today().

    The workflow starts at 22:00 UTC but rate-limit retries can push the AI
    step past midnight UTC, making date.today() return the next calendar day
    while the snapshot CSV still holds the prior market date.
    """
    snap_date = "2026-06-10"  # market date, intentionally not today
    sectors_dir = tmp_path / "sectors"
    sectors_dir.mkdir(parents=True)
    _write_snap_csv(sectors_dir, snap_date)

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("FORCE_AI", raising=False)
    monkeypatch.setattr(generate_ai, "AI_DIR", tmp_path / "ai")
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)
    monkeypatch.setattr(generate_ai, "_has_new_delta_data", lambda _: True)

    artifact_calls = []
    monkeypatch.setattr(generate_ai, "_write_run_artifacts",
                        lambda *args: artifact_calls.append(args))

    with pytest.raises(SystemExit):
        generate_ai.main()

    assert artifact_calls, "expected _write_run_artifacts to be called"
    assert artifact_calls[0][3] == snap_date, (
        f"AI date should be snapshot date {snap_date!r}, got {artifact_calls[0][3]!r}"
    )


def test_main_falls_back_to_today_when_no_snapshot(monkeypatch, tmp_path):
    """With no snapshot data, date falls back to date.today() — no crash."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("FORCE_AI", raising=False)
    monkeypatch.setattr(generate_ai, "AI_DIR", tmp_path / "ai")
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)
    # Simulate missing snapshot by returning empty DataFrame
    monkeypatch.setattr(generate_ai, "load_latest_snapshot", lambda _: pd.DataFrame())
    monkeypatch.setattr(generate_ai, "_has_new_delta_data", lambda _: True)

    artifact_calls = []
    monkeypatch.setattr(generate_ai, "_write_run_artifacts",
                        lambda *args: artifact_calls.append(args))

    with pytest.raises(SystemExit):
        generate_ai.main()

    assert artifact_calls, "expected _write_run_artifacts to be called"
    date_used = artifact_calls[0][3]
    # Should be a valid YYYY-MM-DD string (date.today() fallback)
    assert len(date_used) == 10 and date_used[4] == "-" and date_used[7] == "-"


def test_main_falls_back_to_today_when_snapshot_dates_all_invalid(monkeypatch, tmp_path):
    """Snapshot with all-unparseable dates → load_latest_snapshot returns empty → fallback, no crash."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("FORCE_AI", raising=False)
    monkeypatch.setattr(generate_ai, "AI_DIR", tmp_path / "ai")
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)
    # load_latest_snapshot returns empty when all dates are NaT (filters to latest == NaT → empty)
    monkeypatch.setattr(generate_ai, "load_latest_snapshot", lambda _: pd.DataFrame())
    monkeypatch.setattr(generate_ai, "_has_new_delta_data", lambda _: True)

    artifact_calls = []
    monkeypatch.setattr(generate_ai, "_write_run_artifacts",
                        lambda *args: artifact_calls.append(args))

    with pytest.raises(SystemExit):
        generate_ai.main()

    date_used = artifact_calls[0][3]
    assert len(date_used) == 10 and date_used[4] == "-" and date_used[7] == "-"


# ---------------------------------------------------------------------------
# skip-trap: empty results must not write a file
# ---------------------------------------------------------------------------

def test_main_does_not_write_file_when_all_calls_fail(monkeypatch, tmp_path):
    # Simulate a total API outage: generate_for_group returns {} for both groups.
    from unittest.mock import MagicMock
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.delenv("FORCE_AI", raising=False)
    monkeypatch.setattr(generate_ai, "AI_DIR", tmp_path / "ai")
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)
    monkeypatch.setattr(generate_ai, "generate_for_group", lambda *_, **__: {})
    monkeypatch.setattr(generate_ai, "_has_new_delta_data", lambda _: True)
    # Inject a fake google.genai so the lazy import inside main() succeeds.
    mock_genai = MagicMock()
    monkeypatch.setitem(sys.modules, "google.genai", mock_genai)

    with pytest.raises(SystemExit) as exc_info:
        generate_ai.main()
    assert exc_info.value.code == 0
    # No dated JSON file should have been written — allows the next run to retry
    assert not any((tmp_path / "ai").glob("????-??-??.json"))


# ---------------------------------------------------------------------------
# _is_complete
# ---------------------------------------------------------------------------

def test_is_complete_returns_true_for_full_data():
    data = {
        "sectors": {
            "briefing": "Some text",
            "rotation_phase": {"label": "Defensive", "reasoning": "..."},
            "watchlist": [{"name": "Energy", "thesis": "Strong"}],
        },
        "industries": {
            "briefing": "Industry text",
            "rotation_phase": {"label": "Tech pullback", "reasoning": "Software leads."},
            "watchlist": [{"name": "Software", "thesis": "Strong trend."}],
        },
    }
    assert generate_ai._is_complete(data) is True


def test_is_complete_returns_false_for_missing_briefing():
    data = {
        "sectors": {
            "rotation_phase": {"label": "Defensive", "reasoning": "..."},
            "watchlist": [{"name": "Energy", "thesis": "Strong"}],
        },
        "industries": {"briefing": "Industry text"},
    }
    assert generate_ai._is_complete(data) is False


def test_is_complete_returns_false_for_empty_watchlist():
    data = {
        "sectors": {
            "briefing": "Some text",
            "rotation_phase": {"label": "Defensive", "reasoning": "..."},
            "watchlist": [],
        },
        "industries": {"briefing": "Industry text"},
    }
    assert generate_ai._is_complete(data) is False


def test_is_complete_returns_false_for_missing_industries_briefing():
    data = {
        "sectors": {
            "briefing": "Some text",
            "rotation_phase": {"label": "Defensive", "reasoning": "..."},
            "watchlist": [{"name": "Energy", "thesis": "Strong"}],
        },
        "industries": {},
    }
    assert generate_ai._is_complete(data) is False


def test_is_complete_returns_false_for_actual_partial_file():
    # Mirrors the real data/ai/2026-06-11.json: only sectors.briefing present
    data = {
        "sectors": {"briefing": "Defensive sectors leading..."},
        "industries": {},
    }
    assert generate_ai._is_complete(data) is False


# ---------------------------------------------------------------------------
# _missing_fields
# ---------------------------------------------------------------------------

def test_missing_fields_empty_data():
    missing = generate_ai._missing_fields({})
    assert set(missing) == {
        "sectors.briefing", "sectors.rotation_phase",
        "sectors.watchlist", "industries.briefing",
        "industries.rotation_phase", "industries.watchlist",
    }


def test_missing_fields_partial_file():
    data = {
        "sectors": {"briefing": "Some text"},
        "industries": {},
    }
    missing = generate_ai._missing_fields(data)
    assert "sectors.rotation_phase" in missing
    assert "sectors.watchlist" in missing
    assert "industries.briefing" in missing
    assert "sectors.briefing" not in missing


def test_missing_fields_complete_data():
    data = {
        "sectors": {
            "briefing": "text",
            "rotation_phase": {"label": "Defensive", "reasoning": "..."},
            "watchlist": [{"name": "Energy", "thesis": "..."}],
        },
        "industries": {
            "briefing": "text",
            "rotation_phase": {"label": "Tech pullback", "reasoning": "..."},
            "watchlist": [{"name": "Software", "thesis": "..."}],
        },
    }
    assert generate_ai._missing_fields(data) == []


# ---------------------------------------------------------------------------
# generate_for_group skips already-present fields
# ---------------------------------------------------------------------------

def test_generate_for_group_skips_existing_briefing(monkeypatch):
    from unittest.mock import MagicMock
    monkeypatch.setattr(generate_ai, "_last_api_call", 0.0)
    monkeypatch.setattr("time.sleep", lambda _: None)
    generate_ai._reset_tracking()
    # Phase/watchlist specs trigger the google.genai lazy import — mock it for CI.
    mock_genai = MagicMock()
    monkeypatch.setitem(sys.modules, "google.genai", mock_genai)

    # Supply existing briefing so the API should NOT be called for it
    existing = {"briefing": "Already written briefing"}
    client = _make_client(["Phase response", "Watchlist response"])

    # Use monkeypatch to avoid real data loading
    snap = pd.DataFrame({
        "date": [pd.Timestamp("2026-06-11").date()],
        "name": ["Energy"],
        "perf_week": [2.0], "perf_month": [3.0], "perf_ytd": [5.0],
    })
    delta = pd.DataFrame({
        "date": [pd.Timestamp("2026-06-11").date()],
        "name": ["Energy"],
        "rank_ytd": [1.0], "rank_ytd_delta_7d": [2.0], "momentum_score": [0.8],
    })
    monkeypatch.setattr(generate_ai, "load_latest_snapshot", lambda _: snap)
    monkeypatch.setattr(generate_ai, "load_latest_delta", lambda _: delta)

    result = generate_ai.generate_for_group(client, "sector", "2026-06-11", existing=existing)

    # Briefing was pre-existing — should NOT have been regenerated
    assert result["briefing"] == "Already written briefing"
    # API was called for rotation_phase and watchlist only (2 calls, not 3)
    assert client.models.generate_content.call_count == 2
    # Field log should show briefing as skipped
    assert generate_ai._field_log["sectors.briefing"]["status"] == "skipped"
    assert generate_ai._field_log["sectors.briefing"]["was_new"] is False


# ---------------------------------------------------------------------------
# main() incremental completion
# ---------------------------------------------------------------------------

def test_main_completes_partial_file(monkeypatch, tmp_path):
    """Re-running with a partial file fills in missing fields without re-calling for existing ones."""
    from unittest.mock import MagicMock
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.delenv("FORCE_AI", raising=False)
    monkeypatch.setattr(generate_ai, "AI_DIR", tmp_path / "ai")
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)
    monkeypatch.setattr(generate_ai, "_has_new_delta_data", lambda _: True)

    # Write the partial file (mirrors real 2026-06-11.json)
    import datetime as _dt
    today = _dt.date.today().isoformat()
    (tmp_path / "ai").mkdir(parents=True)
    partial = {
        "date": today,
        "generated_at": "2026-06-11T04:30:50Z",
        "model": "gemini-flash-latest",
        "sectors": {"briefing": "Existing briefing"},
        "industries": {},
    }
    with open(tmp_path / "ai" / f"{today}.json", "w") as f:
        json.dump(partial, f)

    # generate_for_group returns fresh content (force regeneration)
    call_log = []
    def fake_generate(client, group_type, date_str, existing=None):
        call_log.append((group_type, list(existing.keys()) if existing else []))
        if group_type == "sector":
            return {
                "briefing": "Sector briefing",  # always regenerate, not preserve
                "rotation_phase": {"label": "Defensive", "reasoning": "test"},
                "watchlist": [{"name": "Energy", "thesis": "ok"}],
            }
        return {
            "briefing": "Industry briefing",
            "rotation_phase": {"label": "Tech pullback", "reasoning": "test"},
            "watchlist": [{"name": "Software", "thesis": "ok"}],
        }

    monkeypatch.setattr(generate_ai, "generate_for_group", fake_generate)
    # Mock both parent and child so import succeeds even without google-genai installed.
    mock_genai = MagicMock()
    mock_google = MagicMock()
    mock_google.genai = mock_genai
    monkeypatch.setitem(sys.modules, "google", mock_google)
    monkeypatch.setitem(sys.modules, "google.genai", mock_genai)

    generate_ai.main()  # completes normally (no sys.exit on success)

    # File should now be complete
    with open(tmp_path / "ai" / f"{today}.json") as f:
        result = json.load(f)

    # File should have fresh generated data (not preserved from partial state)
    # Since we always force regenerate now, it should use fake_generate output
    assert result["sectors"]["briefing"] == "Sector briefing"  # regenerated, not preserved
    assert isinstance(result["sectors"]["rotation_phase"], dict)
    assert result["industries"]["briefing"] == "Industry briefing"
    assert isinstance(result["industries"]["rotation_phase"], dict)
    assert isinstance(result["industries"]["watchlist"], list)

    # generate_for_group was called for both groups
    assert call_log[0][0] == "sector"
    assert call_log[1][0] == "industry"
    # existing is always empty now (force regeneration)
    assert call_log[0][1] == []  # existing = {} for both groups
    assert call_log[1][1] == []

    # Sidecar was written
    assert (tmp_path / "ai_run_summary.json").exists()
    with open(tmp_path / "ai_run_summary.json") as f:
        summary = json.load(f)
    assert summary["outcome"] == "complete"


def test_main_generates_daily_delta_when_prior_file_exists(monkeypatch, tmp_path):
    """When a prior day's AI file exists, main() generates sectors.daily_delta."""
    from unittest.mock import MagicMock
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.delenv("FORCE_AI", raising=False)
    monkeypatch.setattr(generate_ai, "AI_DIR", tmp_path / "ai")
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)
    monkeypatch.setattr(generate_ai, "_has_new_delta_data", lambda _: True)

    import datetime as _dt
    today = _dt.date.today().isoformat()
    yesterday = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
    (tmp_path / "ai").mkdir(parents=True)

    # Write yesterday's AI file with a sectors briefing
    prior = {
        "date": yesterday,
        "sectors": {"briefing": "Yesterday energy was leading."},
        "industries": {},
    }
    (tmp_path / "ai" / f"{yesterday}.json").write_text(json.dumps(prior))

    calls = []
    def fake_generate(client, group_type, date_str, existing=None):
        calls.append(group_type)
        if group_type == "sector":
            return {
                "briefing": "Today briefing",
                "rotation_phase": {"label": "Late Cycle", "reasoning": "Energy leads."},
                "watchlist": [{"name": "Energy", "thesis": "ok"}],
            }
        return {
            "briefing": "Industry briefing",
            "rotation_phase": {"label": "Commodity", "reasoning": "..."},
            "watchlist": [{"name": "Software", "thesis": "ok"}],
        }

    delta_calls = []
    def fake_delta(client, prior_briefing, date_str):
        delta_calls.append(prior_briefing)
        return ["Energy rank improved to #1", "Healthcare lost momentum"]

    monkeypatch.setattr(generate_ai, "generate_for_group", fake_generate)
    monkeypatch.setattr(generate_ai, "_generate_daily_delta", fake_delta)
    mock_genai = MagicMock()
    mock_google = MagicMock()
    mock_google.genai = mock_genai
    monkeypatch.setitem(sys.modules, "google", mock_google)
    monkeypatch.setitem(sys.modules, "google.genai", mock_genai)

    generate_ai.main()

    with open(tmp_path / "ai" / f"{today}.json") as f:
        result = json.load(f)

    assert result["sectors"]["daily_delta"] == ["Energy rank improved to #1", "Healthcare lost momentum"]
    assert delta_calls[0] == "Yesterday energy was leading."


def test_main_skips_delta_when_no_prior_file(monkeypatch, tmp_path):
    """When no prior AI file exists, daily_delta is absent from output."""
    from unittest.mock import MagicMock
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.delenv("FORCE_AI", raising=False)
    monkeypatch.setattr(generate_ai, "AI_DIR", tmp_path / "ai")
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)
    monkeypatch.setattr(generate_ai, "_has_new_delta_data", lambda _: True)

    import datetime as _dt
    today = _dt.date.today().isoformat()
    (tmp_path / "ai").mkdir(parents=True)

    delta_calls = []
    def fake_delta(*args, **kwargs):
        delta_calls.append(True)
        return ["change"]

    def fake_generate(client, group_type, date_str, existing=None):
        if group_type == "sector":
            return {
                "briefing": "Today briefing",
                "rotation_phase": {"label": "Late Cycle", "reasoning": "..."},
                "watchlist": [{"name": "Energy", "thesis": "ok"}],
            }
        return {
            "briefing": "Industry briefing",
            "rotation_phase": {"label": "Commodity", "reasoning": "..."},
            "watchlist": [{"name": "Software", "thesis": "ok"}],
        }

    monkeypatch.setattr(generate_ai, "generate_for_group", fake_generate)
    monkeypatch.setattr(generate_ai, "_generate_daily_delta", fake_delta)
    mock_genai = MagicMock()
    mock_google = MagicMock()
    mock_google.genai = mock_genai
    monkeypatch.setitem(sys.modules, "google", mock_google)
    monkeypatch.setitem(sys.modules, "google.genai", mock_genai)

    generate_ai.main()

    assert delta_calls == []  # _generate_daily_delta was not called
    with open(tmp_path / "ai" / f"{today}.json") as f:
        result = json.load(f)
    assert "daily_delta" not in result.get("sectors", {})


def test_main_force_regenerates_complete_file(monkeypatch, tmp_path):
    '''Verify we force-regenerate even when file is complete. No caching ai insights. '''
    from unittest.mock import MagicMock
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.delenv("FORCE_AI", raising=False)
    monkeypatch.setattr(generate_ai, "AI_DIR", tmp_path / "ai")
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)
    monkeypatch.setattr(generate_ai, "_has_new_delta_data", lambda _: True)

    import datetime as _dt
    today = _dt.date.today().isoformat()
    (tmp_path / "ai").mkdir(parents=True)
    complete = {
        "date": today,
        "generated_at": "2026-06-11T04:30:50Z",
        "model": "gemini-flash-latest",
        "sectors": {
            "briefing": "text",
            "rotation_phase": {"label": "Defensive", "reasoning": "..."},
            "watchlist": [{"name": "Energy", "thesis": "ok"}],
        },
        "industries": {
            "briefing": "Industry text",
            "rotation_phase": {"label": "Tech pullback", "reasoning": "..."},
            "watchlist": [{"name": "Software", "thesis": "ok"}],
        },
    }
    with open(tmp_path / "ai" / f"{today}.json", "w") as f:
        json.dump(complete, f)

    generate_called = []
    def mock_generate(*_, **__):
        generate_called.append(True)
        # Return full data so outcome is "complete" not "failed"
        if len(generate_called) == 1:  # sector call
            return {
                "briefing": "Sector content",
                "rotation_phase": {"label": "Early Cycle", "reasoning": "test"},
                "watchlist": [{"name": "Tech", "thesis": "test"}],
            }
        else:  # industry call
            return {
                "briefing": "Industry content",
                "rotation_phase": {"label": "Growth", "reasoning": "test"},
                "watchlist": [{"name": "Healthcare", "thesis": "test"}],
            }
    monkeypatch.setattr(generate_ai, "generate_for_group", mock_generate)
    # Mock both parent and child so import succeeds even without google-genai installed.
    mock_genai = MagicMock()
    mock_google = MagicMock()
    mock_google.genai = mock_genai
    monkeypatch.setitem(sys.modules, "google", mock_google)
    monkeypatch.setitem(sys.modules, "google.genai", mock_genai)

    # main() completes normally (no SystemExit) since content is generated
    generate_ai.main()

    # generate_for_group MUST be called — we always force regenerate now
    assert generate_called == [True, True]  # called for sector and industry

    with open(tmp_path / "ai_run_summary.json") as f:
        summary = json.load(f)
    assert summary["outcome"] == "complete"  # regenerated, not skipped


# Error handling tests for transient API failures
def test_looks_like_preamble_detects_common_patterns():
    """Test preamble detection catches various LLM failure patterns."""
    assert generate_ai._looks_like_preamble("Here is the JSON requested:")
    assert generate_ai._looks_like_preamble("Below is the JSON response:")
    assert generate_ai._looks_like_preamble("The JSON follows:")
    assert generate_ai._looks_like_preamble("JSON output:\n```json")
    assert not generate_ai._looks_like_preamble('{"name": "Energy"}')  # valid JSON


def test_looks_like_preamble_case_insensitive():
    """Test preamble detection is case-insensitive."""
    assert generate_ai._looks_like_preamble("HERE IS THE JSON:")
    assert generate_ai._looks_like_preamble("Below Is The JSON:")


def test_call_api_retries_on_empty_response(monkeypatch):
    """Test that empty response.text is treated as retryable error."""
    from unittest.mock import MagicMock

    client = MagicMock()
    # First two calls return empty text, third succeeds
    response_empty = MagicMock()
    response_empty.text = None
    response_ok = MagicMock()
    response_ok.text = '{"result": "ok"}'

    client.models.generate_content.side_effect = [response_empty, response_empty, response_ok]
    monkeypatch.setattr(generate_ai, "_INTER_CALL_DELAY", 0)  # skip sleep in tests

    result = generate_ai._call_api(
        client, "prompt", max_retries=3,
        generation_config=None, response_schema=None
    )
    assert result == '{"result": "ok"}'
    assert client.models.generate_content.call_count == 3


def test_call_api_retries_on_whitespace_response(monkeypatch):
    """Test that whitespace-only response.text is treated as retryable error."""
    from unittest.mock import MagicMock

    client = MagicMock()
    response_ws = MagicMock()
    response_ws.text = "   \n\n  "
    response_ok = MagicMock()
    response_ok.text = '{"result": "ok"}'

    client.models.generate_content.side_effect = [response_ws, response_ok]
    monkeypatch.setattr(generate_ai, "_INTER_CALL_DELAY", 0)

    result = generate_ai._call_api(
        client, "prompt", max_retries=3,
        generation_config=None, response_schema=None
    )
    assert result == '{"result": "ok"}'


def test_call_api_retries_on_preamble_response(monkeypatch):
    """Test that preamble responses are detected and retried."""
    from unittest.mock import MagicMock

    client = MagicMock()
    response_preamble = MagicMock()
    response_preamble.text = "Here is the JSON requested:\n```json"
    response_ok = MagicMock()
    response_ok.text = '{"result": "ok"}'

    client.models.generate_content.side_effect = [response_preamble, response_ok]
    monkeypatch.setattr(generate_ai, "_INTER_CALL_DELAY", 0)

    result = generate_ai._call_api(
        client, "prompt", max_retries=3,
        generation_config=None, response_schema=None
    )
    assert result == '{"result": "ok"}'


# ---------------------------------------------------------------------------
# _normalize_briefing
# ---------------------------------------------------------------------------

def test_normalize_briefing_valid_dict():
    """Normalize a valid dict with briefing and key_signals."""
    parsed = {
        "briefing": "Energy maintains dominance.",
        "key_signals": ["Signal 1", "Signal 2"],
    }
    result = generate_ai._normalize_briefing(parsed)
    assert result == {
        "briefing": "Energy maintains dominance.",
        "key_signals": ["Signal 1", "Signal 2"],
    }


def test_normalize_briefing_dict_missing_key_signals():
    """Normalize a dict with only briefing, missing key_signals."""
    parsed = {"briefing": "Energy maintains dominance."}
    result = generate_ai._normalize_briefing(parsed)
    assert result == {"briefing": "Energy maintains dominance.", "key_signals": []}


def test_normalize_briefing_dict_with_null_key_signals():
    """Normalize a dict where key_signals is None."""
    parsed = {"briefing": "Energy maintains dominance.", "key_signals": None}
    result = generate_ai._normalize_briefing(parsed)
    assert result == {"briefing": "Energy maintains dominance.", "key_signals": []}


def test_normalize_briefing_dict_with_empty_key_signals():
    """Normalize a dict with empty key_signals list."""
    parsed = {"briefing": "Energy maintains dominance.", "key_signals": []}
    result = generate_ai._normalize_briefing(parsed)
    assert result == {"briefing": "Energy maintains dominance.", "key_signals": []}


def test_normalize_briefing_dict_with_null_items_in_key_signals():
    """Normalize key_signals that contains None and empty strings."""
    parsed = {
        "briefing": "Energy maintains dominance.",
        "key_signals": ["Signal 1", None, "", "Signal 2"],
    }
    result = generate_ai._normalize_briefing(parsed)
    assert result == {
        "briefing": "Energy maintains dominance.",
        "key_signals": ["Signal 1", "Signal 2"],
    }


def test_normalize_briefing_plain_string():
    """Normalize when parsed is a raw string."""
    parsed = "This is a briefing string."
    result = generate_ai._normalize_briefing(parsed)
    assert result == {"briefing": "This is a briefing string.", "key_signals": []}


def test_normalize_briefing_string_with_whitespace():
    """Normalize a string that has leading/trailing whitespace."""
    parsed = "  Energy briefing.  \n"
    result = generate_ai._normalize_briefing(parsed)
    assert result == {"briefing": "Energy briefing.", "key_signals": []}


def test_normalize_briefing_none_or_non_dict_non_string():
    """Normalize when parsed is None, int, or other invalid type."""
    assert generate_ai._normalize_briefing(None) == {"briefing": "", "key_signals": []}
    assert generate_ai._normalize_briefing(123) == {"briefing": "", "key_signals": []}
    assert generate_ai._normalize_briefing([]) == {"briefing": "", "key_signals": []}


def test_normalize_briefing_dict_missing_briefing():
    """Normalize a dict with key_signals but no briefing key."""
    parsed = {"key_signals": ["Signal 1"]}
    result = generate_ai._normalize_briefing(parsed)
    assert result == {"briefing": "", "key_signals": ["Signal 1"]}


def test_normalize_briefing_dict_with_null_briefing():
    """Normalize a dict where briefing is None."""
    parsed = {"briefing": None, "key_signals": ["Signal 1"]}
    result = generate_ai._normalize_briefing(parsed)
    assert result == {"briefing": "", "key_signals": ["Signal 1"]}


# ---------------------------------------------------------------------------
# _normalize_phase
# ---------------------------------------------------------------------------

def test_normalize_phase_valid_dict():
    """Normalize a valid phase dict."""
    parsed = {
        "label": "Early Cycle",
        "reasoning": "Momentum is strong.",
    }
    result = generate_ai._normalize_phase(parsed)
    assert result == {
        "label": "Early Cycle",
        "reasoning": "Momentum is strong.",
    }


def test_normalize_phase_dict_missing_reasoning():
    """Normalize a phase dict with only label."""
    parsed = {"label": "Mid Cycle"}
    result = generate_ai._normalize_phase(parsed)
    assert result == {"label": "Mid Cycle", "reasoning": ""}


def test_normalize_phase_dict_with_null_values():
    """Normalize a phase dict where fields are None."""
    parsed = {"label": None, "reasoning": None}
    result = generate_ai._normalize_phase(parsed)
    assert result == {"label": "", "reasoning": ""}


def test_normalize_phase_dict_with_whitespace():
    """Normalize a phase dict with whitespace in values."""
    parsed = {"label": "  Late Cycle  ", "reasoning": "\n  Defensive  "}
    result = generate_ai._normalize_phase(parsed)
    assert result == {"label": "Late Cycle", "reasoning": "Defensive"}


def test_normalize_phase_plain_string():
    """Normalize when parsed is a raw string (fallback)."""
    parsed = "This is the reasoning text."
    result = generate_ai._normalize_phase(parsed)
    assert result == {
        "label": "Unknown",
        "reasoning": "This is the reasoning text.",
    }


def test_normalize_phase_none_or_invalid():
    """Normalize when parsed is None or invalid type."""
    assert generate_ai._normalize_phase(None) == {"label": "Unknown", "reasoning": ""}
    assert generate_ai._normalize_phase(123) == {"label": "Unknown", "reasoning": ""}
    assert generate_ai._normalize_phase([]) == {"label": "Unknown", "reasoning": ""}


def test_normalize_phase_free_form_label():
    """Normalize a phase with free-form (non-enum) label."""
    parsed = {
        "label": "Market Micro-Phase: Transition",
        "reasoning": "Custom industry phase.",
    }
    result = generate_ai._normalize_phase(parsed)
    assert result == {
        "label": "Market Micro-Phase: Transition",
        "reasoning": "Custom industry phase.",
    }


# ---------------------------------------------------------------------------
# _has_new_delta_data
# ---------------------------------------------------------------------------

def _write_delta_csv(delta_dir: Path, date_str: str) -> None:
    delta_dir.mkdir(parents=True, exist_ok=True)
    csv_path = delta_dir / "deltas.csv"
    csv_path.write_text(f"date,name,rank_week\n{date_str},Energy,1\n")


def test_has_new_delta_data_true_when_sectors_has_date(monkeypatch, tmp_path):
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)
    _write_delta_csv(tmp_path / "sectors", "2026-06-13")
    assert generate_ai._has_new_delta_data("2026-06-13") is True


def test_has_new_delta_data_true_when_only_industries_has_date(monkeypatch, tmp_path):
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)
    # sectors CSV has older date; industries has today
    _write_delta_csv(tmp_path / "sectors", "2026-06-12")
    _write_delta_csv(tmp_path / "industries", "2026-06-13")
    assert generate_ai._has_new_delta_data("2026-06-13") is True


def test_has_new_delta_data_false_when_neither_has_date(monkeypatch, tmp_path):
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)
    _write_delta_csv(tmp_path / "sectors", "2026-06-12")
    _write_delta_csv(tmp_path / "industries", "2026-06-12")
    assert generate_ai._has_new_delta_data("2026-06-13") is False


def test_has_new_delta_data_false_when_csvs_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)
    # No CSVs at all
    assert generate_ai._has_new_delta_data("2026-06-13") is False


def test_has_new_delta_data_false_and_warns_on_corrupt_csv(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)
    sectors_dir = tmp_path / "sectors"
    sectors_dir.mkdir(parents=True)
    # Write a CSV without the "date" column — causes usecols KeyError
    (sectors_dir / "deltas.csv").write_text("name,rank_week\nEnergy,1\n")
    result = generate_ai._has_new_delta_data("2026-06-13")
    assert result is False
    captured = capsys.readouterr()
    assert "WARNING" in captured.out


# ---------------------------------------------------------------------------
# main() skip gate — force flag and env var
# ---------------------------------------------------------------------------

def test_main_skips_when_no_delta_data(monkeypatch, tmp_path):
    """main() exits 0 with outcome=skipped when no delta data and force=False."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("FORCE_AI", raising=False)
    monkeypatch.setattr(generate_ai, "AI_DIR", tmp_path / "ai")
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)
    monkeypatch.setattr(generate_ai, "_has_new_delta_data", lambda _: False)

    artifact_calls = []
    monkeypatch.setattr(generate_ai, "_write_run_artifacts",
                        lambda *args: artifact_calls.append(args))

    with pytest.raises(SystemExit) as exc_info:
        generate_ai.main()

    assert exc_info.value.code == 0
    assert artifact_calls, "expected _write_run_artifacts to be called"
    assert artifact_calls[0][0] == "skipped"


def test_main_force_flag_bypasses_skip(monkeypatch, tmp_path):
    """--force-ai flag causes generation even when _has_new_delta_data returns False."""
    from unittest.mock import MagicMock
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.delenv("FORCE_AI", raising=False)
    monkeypatch.setattr(generate_ai, "AI_DIR", tmp_path / "ai")
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)
    monkeypatch.setattr(generate_ai, "_has_new_delta_data", lambda _: False)

    generate_called = []
    def fake_generate(client, group_type, date_str, existing=None):
        generate_called.append(group_type)
        if group_type == "sector":
            return {
                "briefing": "text",
                "rotation_phase": {"label": "Defensive", "reasoning": "test"},
                "watchlist": [{"name": "Energy", "thesis": "ok"}],
            }
        return {
            "briefing": "text",
            "rotation_phase": {"label": "Tech", "reasoning": "test"},
            "watchlist": [{"name": "Software", "thesis": "ok"}],
        }

    monkeypatch.setattr(generate_ai, "generate_for_group", fake_generate)
    mock_genai = MagicMock()
    mock_google = MagicMock()
    mock_google.genai = mock_genai
    monkeypatch.setitem(sys.modules, "google", mock_google)
    monkeypatch.setitem(sys.modules, "google.genai", mock_genai)

    import sys as _sys
    orig_argv = _sys.argv
    _sys.argv = [orig_argv[0], "--force-ai"]
    try:
        (tmp_path / "ai").mkdir(parents=True)
        generate_ai.main()
    finally:
        _sys.argv = orig_argv

    assert "sector" in generate_called


def test_main_force_env_var_bypasses_skip(monkeypatch, tmp_path):
    """FORCE_AI=1 env var causes generation even when _has_new_delta_data returns False."""
    from unittest.mock import MagicMock
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("FORCE_AI", "1")
    monkeypatch.setattr(generate_ai, "AI_DIR", tmp_path / "ai")
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)
    monkeypatch.setattr(generate_ai, "_has_new_delta_data", lambda _: False)

    generate_called = []
    def fake_generate(client, group_type, date_str, existing=None):
        generate_called.append(group_type)
        if group_type == "sector":
            return {
                "briefing": "text",
                "rotation_phase": {"label": "Defensive", "reasoning": "test"},
                "watchlist": [{"name": "Energy", "thesis": "ok"}],
            }
        return {
            "briefing": "text",
            "rotation_phase": {"label": "Tech", "reasoning": "test"},
            "watchlist": [{"name": "Software", "thesis": "ok"}],
        }

    monkeypatch.setattr(generate_ai, "generate_for_group", fake_generate)
    mock_genai = MagicMock()
    mock_google = MagicMock()
    mock_google.genai = mock_genai
    monkeypatch.setitem(sys.modules, "google", mock_google)
    monkeypatch.setitem(sys.modules, "google.genai", mock_genai)

    (tmp_path / "ai").mkdir(parents=True)
    generate_ai.main()

    assert "sector" in generate_called
