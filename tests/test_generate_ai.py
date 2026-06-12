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


# ---------------------------------------------------------------------------
# TASK_SPECS and _expected_fields
# ---------------------------------------------------------------------------

def test_task_specs_has_expected_names():
    names = {s["name"] for s in generate_ai.TASK_SPECS}
    assert names == {"briefing", "rotation_phase", "watchlist"}


def test_task_specs_briefing_covers_both_group_types():
    spec = next(s for s in generate_ai.TASK_SPECS if s["name"] == "briefing")
    assert "sector" in spec["group_types"]
    assert "industry" in spec["group_types"]


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


def test_expected_fields_returns_all_four():
    fields = set(generate_ai._expected_fields())
    assert fields == {
        "sectors.briefing",
        "sectors.rotation_phase",
        "sectors.watchlist",
        "industries.briefing",
    }


def test_generate_for_group_industry_calls_api_once(monkeypatch):
    """Industry group only runs briefing — 1 API call, not 3."""
    monkeypatch.setattr(generate_ai, "_last_api_call", 0.0)
    monkeypatch.setattr("time.sleep", lambda _: None)
    generate_ai._reset_tracking()

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

    client = _make_client(["Industry briefing text"])
    result = generate_ai.generate_for_group(client, "industry", "2026-06-11")

    assert client.models.generate_content.call_count == 1
    assert result.get("briefing") == "Industry briefing text"
    assert "rotation_phase" not in result
    assert "watchlist" not in result


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


def test_generate_for_group_json_parse_fallback(monkeypatch):
    """If JSON parse fails for rotation_phase, fallback parser is used."""
    monkeypatch.setattr(generate_ai, "_last_api_call", 0.0)
    monkeypatch.setattr("time.sleep", lambda _: None)
    generate_ai._reset_tracking()

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
    )

    ctor_kwargs = mock_types.GenerateContentConfig.call_args[1]
    assert ctor_kwargs["temperature"] == 0.2
    assert ctor_kwargs["max_output_tokens"] == 300


# ---------------------------------------------------------------------------
# main exits gracefully without API key
# ---------------------------------------------------------------------------

def test_main_exits_zero_without_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(generate_ai, "AI_DIR", tmp_path / "ai")
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)
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
    monkeypatch.setattr(generate_ai, "AI_DIR", tmp_path / "ai")
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)

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
    monkeypatch.setattr(generate_ai, "AI_DIR", tmp_path / "ai")
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)
    # Simulate missing snapshot by returning empty DataFrame
    monkeypatch.setattr(generate_ai, "load_latest_snapshot", lambda _: pd.DataFrame())

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
    monkeypatch.setattr(generate_ai, "AI_DIR", tmp_path / "ai")
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)
    # load_latest_snapshot returns empty when all dates are NaT (filters to latest == NaT → empty)
    monkeypatch.setattr(generate_ai, "load_latest_snapshot", lambda _: pd.DataFrame())

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
    monkeypatch.setattr(generate_ai, "AI_DIR", tmp_path / "ai")
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)
    monkeypatch.setattr(generate_ai, "generate_for_group", lambda *_, **__: {})
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
        "industries": {"briefing": "Industry text"},
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
        "industries": {"briefing": "text"},
    }
    assert generate_ai._missing_fields(data) == []


# ---------------------------------------------------------------------------
# generate_for_group skips already-present fields
# ---------------------------------------------------------------------------

def test_generate_for_group_skips_existing_briefing(monkeypatch):
    monkeypatch.setattr(generate_ai, "_last_api_call", 0.0)
    monkeypatch.setattr("time.sleep", lambda _: None)
    generate_ai._reset_tracking()

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
    monkeypatch.setattr(generate_ai, "AI_DIR", tmp_path / "ai")
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)

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

    # generate_for_group returns new content; verify briefing is NOT regenerated for sectors
    call_log = []
    def fake_generate(client, group_type, date_str, existing=None):
        call_log.append((group_type, list(existing.keys()) if existing else []))
        if group_type == "sector":
            return {
                "briefing": existing.get("briefing", ""),  # preserve
                "rotation_phase": {"label": "Defensive", "reasoning": "test"},
                "watchlist": [{"name": "Energy", "thesis": "ok"}],
            }
        return {"briefing": "Industry briefing"}

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

    assert result["sectors"]["briefing"] == "Existing briefing"  # preserved
    assert isinstance(result["sectors"]["rotation_phase"], dict)
    assert result["industries"]["briefing"] == "Industry briefing"

    # generate_for_group was called with the existing sector data
    sector_call = next(c for c in call_log if c[0] == "sector")
    assert "briefing" in sector_call[1]  # existing keys passed in

    # Sidecar was written
    assert (tmp_path / "ai_run_summary.json").exists()
    with open(tmp_path / "ai_run_summary.json") as f:
        summary = json.load(f)
    assert summary["outcome"] == "complete"


def test_main_skips_already_complete_file(monkeypatch, tmp_path):
    from unittest.mock import MagicMock
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(generate_ai, "AI_DIR", tmp_path / "ai")
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)

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
        "industries": {"briefing": "Industry text"},
    }
    with open(tmp_path / "ai" / f"{today}.json", "w") as f:
        json.dump(complete, f)

    generate_called = []
    monkeypatch.setattr(generate_ai, "generate_for_group",
                        lambda *_, **__: generate_called.append(True) or {})
    # Mock both parent and child so import succeeds even without google-genai installed.
    mock_genai = MagicMock()
    mock_google = MagicMock()
    mock_google.genai = mock_genai
    monkeypatch.setitem(sys.modules, "google", mock_google)
    monkeypatch.setitem(sys.modules, "google.genai", mock_genai)

    with pytest.raises(SystemExit) as exc_info:
        generate_ai.main()
    assert exc_info.value.code == 0
    # generate_for_group must NOT have been called — file was already complete
    assert generate_called == []

    with open(tmp_path / "ai_run_summary.json") as f:
        summary = json.load(f)
    assert summary["outcome"] == "skipped"
