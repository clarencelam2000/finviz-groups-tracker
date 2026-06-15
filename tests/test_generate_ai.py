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
# serialize_strength_signals
# ---------------------------------------------------------------------------

def test_strength_signals_all_green_breadth(snap_df, delta_df):
    # Energy (2.5/5.0/12.0) and Healthcare (0.8/1.5/4.0) are all-green; Tech is not.
    result = generate_ai.serialize_strength_signals(snap_df, delta_df)
    assert "STRENGTH SIGNALS" in result
    assert "2 of 3" in result
    assert "Energy" in result
    assert "Technology" not in result.split("Sustained")[0].split("All-green:")[-1]


def test_strength_signals_empty():
    result = generate_ai.serialize_strength_signals(pd.DataFrame(), pd.DataFrame())
    assert "Not enough data" in result


def test_strength_signals_sustained_strong():
    snap = pd.DataFrame({
        "name": ["A", "B", "C", "D"],
        "perf_week": [1.0, 1.0, -1.0, 1.0],
        "perf_month": [1.0, 1.0, 1.0, 1.0],
        "perf_ytd": [1.0, 1.0, 1.0, 1.0],
    })
    delta = pd.DataFrame({
        "name": ["A", "B", "C", "D"],
        "rank_month": [1.0, 2.0, 3.0, 10.0],
        "rank_quarter": [1.0, 2.0, 3.0, 10.0],
        "rank_half": [1.0, 2.0, 3.0, 10.0],
        "momentum_score": [0.9, 0.8, 0.7, 0.2],
    })
    result = generate_ai.serialize_strength_signals(snap, delta, top_n=3)
    assert "Sustained strong" in result
    assert "A" in result and "B" in result and "C" in result
    # D is rank 10 — outside top 3, should not be in the sustained line
    sustained_line = [ln for ln in result.splitlines() if "Sustained strong" in ln][0]
    assert "D" not in sustained_line


# ---------------------------------------------------------------------------
# serialize_momentum_laggards
# ---------------------------------------------------------------------------

def test_momentum_laggards_basic(delta_df):
    result = generate_ai.serialize_momentum_laggards(delta_df)
    assert "MOMENTUM LAGGARDS" in result
    assert "Technology" in result   # lowest momentum (0.30)
    assert "0.300" in result


def test_momentum_laggards_empty():
    result = generate_ai.serialize_momentum_laggards(pd.DataFrame())
    assert "No momentum data" in result


def test_momentum_laggards_orders_weakest_first(delta_df):
    result = generate_ai.serialize_momentum_laggards(delta_df, n=1)
    assert "Technology" in result
    assert "Energy" not in result   # strongest, excluded when n=1


# ---------------------------------------------------------------------------
# serialize_divergences
# ---------------------------------------------------------------------------

def test_divergences_not_enough_history():
    df = pd.DataFrame({"name": ["A"], "momentum_score": [0.5]})  # no rank_ytd_delta_7d
    result = generate_ai.serialize_divergences(pd.DataFrame(), df)
    assert "Not enough history" in result


def test_divergences_fading():
    # strong momentum (>=0.60) but rank slipping (delta < 0)
    delta = pd.DataFrame({
        "name": ["Tech"],
        "momentum_score": [0.72],
        "rank_ytd_delta_7d": [-4.0],
    })
    result = generate_ai.serialize_divergences(pd.DataFrame(), delta)
    assert "Fading" in result
    assert "Tech" in result


def test_divergences_emerging():
    # rank jumping (>=3) but momentum below median
    delta = pd.DataFrame({
        "name": ["Up", "Strong"],
        "momentum_score": [0.20, 0.90],
        "rank_ytd_delta_7d": [6.0, 0.0],
    })
    result = generate_ai.serialize_divergences(pd.DataFrame(), delta)
    assert "Emerging" in result
    assert "Up" in result


def test_divergences_fragile_all_green():
    snap = pd.DataFrame({
        "name": ["Frag"],
        "perf_week": [1.0], "perf_month": [1.0], "perf_ytd": [1.0],
    })
    delta = pd.DataFrame({
        "name": ["Frag"],
        "momentum_score": [0.55],
        "rank_ytd_delta_7d": [0.0],
        "rank_agreement": [0.40],   # below 0.50 threshold
    })
    result = generate_ai.serialize_divergences(snap, delta)
    assert "Fragile all-green" in result
    assert "Frag" in result


def test_divergences_none_found(delta_df):
    # default fixture: Energy momentum high but delta positive; no divergences
    result = generate_ai.serialize_divergences(pd.DataFrame(), delta_df)
    assert "No notable divergences" in result


# ---------------------------------------------------------------------------
# build_note_prompt
# ---------------------------------------------------------------------------

def test_note_prompt_contains_date(snap_df, delta_df):
    prompt = generate_ai.build_note_prompt("sector", snap_df, delta_df, "2026-06-10")
    assert "2026-06-10" in prompt


def test_note_prompt_contains_group_name(snap_df, delta_df):
    prompt = generate_ai.build_note_prompt("sector", snap_df, delta_df, "2026-06-10")
    assert "sectors" in prompt


def test_note_prompt_industry_label(snap_df, delta_df):
    prompt = generate_ai.build_note_prompt("industry", snap_df, delta_df, "2026-06-10")
    assert "industries" in prompt


def test_note_prompt_requests_markdown_sections(snap_df, delta_df):
    """The note must ask for the TL;DR + the three signal-driven sections."""
    prompt = generate_ai.build_note_prompt("sector", snap_df, delta_df, "2026-06-10")
    assert "TL;DR" in prompt
    for header in ["## Strength", "## Movers & Momentum", "## Divergences"]:
        assert header in prompt
    # No forced-JSON instructions
    assert "JSON" not in prompt
    assert "response_schema" not in prompt


def test_note_prompt_embeds_computed_signals(snap_df, delta_df):
    """Prompt feeds our computed signal blocks, not a raw snapshot table."""
    prompt = generate_ai.build_note_prompt("sector", snap_df, delta_df, "2026-06-10")
    assert "STRENGTH SIGNALS" in prompt
    assert "DIVERGENCES" in prompt
    assert "Energy" in prompt


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


def test_phase_prompt_is_plain_text(snap_df, delta_df):
    """Phase prompt asks for two plain-text lines, not JSON."""
    prompt = generate_ai.build_phase_prompt(snap_df, delta_df, "2026-06-10")
    assert "Label:" in prompt
    assert "Why:" in prompt
    assert "JSON" not in prompt


# ---------------------------------------------------------------------------
# parse_phase_response (plain-text Label: / Why:)
# ---------------------------------------------------------------------------

def test_parse_phase_structured():
    text = "Label: Late Cycle\nWhy: Energy leads while Utilities lag."
    result = generate_ai.parse_phase_response(text)
    assert result["label"] == "Late Cycle"
    assert "Energy" in result["reasoning"]


def test_parse_phase_case_insensitive_prefix():
    text = "LABEL: Mid Cycle\nWHY: Industrials and tech leading."
    result = generate_ai.parse_phase_response(text)
    assert result["label"] == "Mid Cycle"
    assert "Industrials" in result["reasoning"]


def test_parse_phase_fallback_first_line_is_label():
    result = generate_ai.parse_phase_response("Defensive\nUtilities and staples are bid.")
    assert result["label"] == "Defensive"
    assert "Utilities" in result["reasoning"]


def test_parse_phase_empty_label_when_blank():
    result = generate_ai.parse_phase_response("")
    assert result["label"] == ""
    assert result["reasoning"] == ""


# ---------------------------------------------------------------------------
# _call_api fake client helper
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


def test_gemini_model_is_pinned_version():
    assert generate_ai.GEMINI_MODEL == "gemini-3.5-flash"


# ---------------------------------------------------------------------------
# generate_for_group — freeform note + plain-text phase
# ---------------------------------------------------------------------------

def test_generate_for_group_stores_note_string(monkeypatch):
    """The note is stored verbatim as a plain string; sectors also get a phase dict."""
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

    note_md = "**TL;DR:** Energy leads.\n\n## Strength\n- Energy all-green"
    client = _make_client([note_md, "Label: Late Cycle\nWhy: Energy leads."])
    result = generate_ai.generate_for_group(client, "sector", "2026-06-11")

    assert result["note"] == note_md
    assert isinstance(result["note"], str)
    assert result["rotation_phase"] == {"label": "Late Cycle", "reasoning": "Energy leads."}
    assert "key_signals" not in result
    assert "watchlist" not in result


def test_generate_for_group_industry_note_only(monkeypatch):
    """Industries get a note but no rotation_phase (sectors-only) — one API call."""
    from unittest.mock import MagicMock
    monkeypatch.setattr(generate_ai, "_last_api_call", 0.0)
    monkeypatch.setattr("time.sleep", lambda _: None)
    generate_ai._reset_tracking()
    mock_genai = MagicMock()
    monkeypatch.setitem(sys.modules, "google.genai", mock_genai)

    snap = pd.DataFrame({
        "date": [pd.Timestamp("2026-06-11").date()],
        "name": ["Trucking"],
        "perf_week": [2.0], "perf_month": [3.0], "perf_ytd": [5.0],
    })
    delta = pd.DataFrame({
        "date": [pd.Timestamp("2026-06-11").date()],
        "name": ["Trucking"],
        "rank_ytd": [1.0], "rank_ytd_delta_7d": [2.0], "momentum_score": [0.8],
    })
    monkeypatch.setattr(generate_ai, "load_latest_snapshot", lambda _: snap)
    monkeypatch.setattr(generate_ai, "load_latest_delta", lambda _: delta)

    client = _make_client(["**TL;DR:** Trucking leads industries."])
    result = generate_ai.generate_for_group(client, "industry", "2026-06-11")

    assert result["note"].startswith("**TL;DR:**")
    assert "rotation_phase" not in result
    assert client.models.generate_content.call_count == 1


# ---------------------------------------------------------------------------
# TASK_SPECS and _expected_fields
# ---------------------------------------------------------------------------

def test_task_specs_has_expected_names():
    names = {s["name"] for s in generate_ai.TASK_SPECS}
    assert names == {"note", "rotation_phase"}


def test_task_specs_note_covers_both_group_types():
    spec = next(s for s in generate_ai.TASK_SPECS if s["name"] == "note")
    assert "sector" in spec["group_types"]
    assert "industry" in spec["group_types"]
    assert spec.get("pass_group_type") is True
    # No JSON-schema machinery anymore
    assert "response_schema" not in spec
    assert "use_json_schema" not in spec


def test_task_specs_rotation_phase_sector_only():
    spec = next(s for s in generate_ai.TASK_SPECS if s["name"] == "rotation_phase")
    assert spec["group_types"] == ("sector",)
    assert "response_schema" not in spec


def test_expected_fields_returns_three():
    fields = set(generate_ai._expected_fields())
    assert fields == {
        "sectors.note",
        "sectors.rotation_phase",
        "industries.note",
    }


def test_generate_for_group_empty_snapshot_returns_existing(monkeypatch):
    """Empty snapshot returns existing dict unchanged and records no_data/skipped."""
    generate_ai._reset_tracking()
    monkeypatch.setattr(generate_ai, "load_latest_snapshot", lambda _: pd.DataFrame())
    monkeypatch.setattr(generate_ai, "load_latest_delta", lambda _: pd.DataFrame())

    existing = {"note": "old note"}
    client = _make_client([])
    result = generate_ai.generate_for_group(client, "sector", "2026-06-11", existing=existing)

    assert result == existing
    assert client.models.generate_content.call_count == 0
    assert generate_ai._field_log["sectors.note"]["status"] == "skipped"
    assert generate_ai._field_log["sectors.rotation_phase"]["status"] == "no_data"


def test_generate_for_group_industry_empty_snapshot_records_no_data(monkeypatch):
    """Industry empty snapshot records no_data for the note."""
    generate_ai._reset_tracking()
    monkeypatch.setattr(generate_ai, "load_latest_snapshot", lambda _: pd.DataFrame())
    monkeypatch.setattr(generate_ai, "load_latest_delta", lambda _: pd.DataFrame())

    client = _make_client([])
    generate_ai.generate_for_group(client, "industry", "2026-06-11")

    assert client.models.generate_content.call_count == 0
    assert generate_ai._field_log["industries.note"]["status"] == "no_data"


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


def test_call_api_no_generation_config_omits_config_kwarg(monkeypatch):
    """Without a generation_config, generate_content is called without a config kwarg."""
    monkeypatch.setattr(generate_ai, "_last_api_call", 0.0)
    monkeypatch.setattr("time.sleep", lambda _: None)
    client = _make_client(["result"])
    generate_ai._call_api(client, "prompt")
    call_kwargs = client.models.generate_content.call_args[1]
    assert "config" not in call_kwargs


def test_call_api_config_has_no_schema_or_token_cap(monkeypatch):
    """Freeform mode: only temperature is set — no JSON schema, no max_output_tokens."""
    from unittest.mock import MagicMock
    monkeypatch.setattr(generate_ai, "_last_api_call", 0.0)
    monkeypatch.setattr("time.sleep", lambda _: None)

    mock_config_instance = MagicMock()
    mock_types = MagicMock()
    mock_types.GenerateContentConfig.return_value = mock_config_instance
    mock_genai_module = MagicMock()
    mock_genai_module.types = mock_types
    monkeypatch.setitem(sys.modules, "google.genai", mock_genai_module)

    client = _make_client(["result"])
    result = generate_ai._call_api(client, "prompt", generation_config={"temperature": 0.2})

    assert result == "result"
    mock_types.GenerateContentConfig.assert_called_once()
    ctor_kwargs = mock_types.GenerateContentConfig.call_args[1]
    assert ctor_kwargs["temperature"] == 0.2
    assert "response_mime_type" not in ctor_kwargs
    assert "response_schema" not in ctor_kwargs
    assert "max_output_tokens" not in ctor_kwargs

    call_kwargs = client.models.generate_content.call_args[1]
    assert call_kwargs["config"] is mock_config_instance


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
            "note": "Some markdown note",
            "rotation_phase": {"label": "Defensive", "reasoning": "..."},
        },
        "industries": {"note": "Industry note"},
    }
    assert generate_ai._is_complete(data) is True


def test_is_complete_returns_false_for_missing_note():
    data = {
        "sectors": {"rotation_phase": {"label": "Defensive", "reasoning": "..."}},
        "industries": {"note": "Industry note"},
    }
    assert generate_ai._is_complete(data) is False


def test_is_complete_returns_false_for_missing_industries_note():
    data = {
        "sectors": {
            "note": "Some markdown note",
            "rotation_phase": {"label": "Defensive", "reasoning": "..."},
        },
        "industries": {},
    }
    assert generate_ai._is_complete(data) is False


def test_is_complete_returns_false_for_actual_partial_file():
    data = {
        "sectors": {"note": "Defensive sectors leading..."},
        "industries": {},
    }
    assert generate_ai._is_complete(data) is False


# ---------------------------------------------------------------------------
# _missing_fields
# ---------------------------------------------------------------------------

def test_missing_fields_empty_data():
    missing = generate_ai._missing_fields({})
    assert set(missing) == {
        "sectors.note", "sectors.rotation_phase", "industries.note",
    }


def test_missing_fields_partial_file():
    data = {
        "sectors": {"note": "Some text"},
        "industries": {},
    }
    missing = generate_ai._missing_fields(data)
    assert "sectors.rotation_phase" in missing
    assert "industries.note" in missing
    assert "sectors.note" not in missing


def test_missing_fields_complete_data():
    data = {
        "sectors": {
            "note": "text",
            "rotation_phase": {"label": "Defensive", "reasoning": "..."},
        },
        "industries": {"note": "text"},
    }
    assert generate_ai._missing_fields(data) == []


# ---------------------------------------------------------------------------
# generate_for_group skips already-present fields
# ---------------------------------------------------------------------------

def test_generate_for_group_skips_existing_note(monkeypatch):
    from unittest.mock import MagicMock
    monkeypatch.setattr(generate_ai, "_last_api_call", 0.0)
    monkeypatch.setattr("time.sleep", lambda _: None)
    generate_ai._reset_tracking()
    mock_genai = MagicMock()
    monkeypatch.setitem(sys.modules, "google.genai", mock_genai)

    # Supply existing note so the API should NOT be called for it
    existing = {"note": "Already written note"}
    client = _make_client(["Label: Late Cycle\nWhy: Energy leads."])

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

    # Note was pre-existing — should NOT have been regenerated
    assert result["note"] == "Already written note"
    # API was called for rotation_phase only (1 call, not 2)
    assert client.models.generate_content.call_count == 1
    assert generate_ai._field_log["sectors.note"]["status"] == "skipped"
    assert generate_ai._field_log["sectors.note"]["was_new"] is False


# ---------------------------------------------------------------------------
# main() incremental completion
# ---------------------------------------------------------------------------

def test_main_completes_partial_file(monkeypatch, tmp_path):
    """Re-running with a partial file passes existing fields to generate_for_group (incremental)."""
    from unittest.mock import MagicMock
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.delenv("FORCE_AI", raising=False)
    monkeypatch.setattr(generate_ai, "AI_DIR", tmp_path / "ai")
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)
    monkeypatch.setattr(generate_ai, "_has_new_delta_data", lambda _: True)

    # Write the partial file (only sectors.note present)
    import datetime as _dt
    today = _dt.date.today().isoformat()
    (tmp_path / "ai").mkdir(parents=True)
    partial = {
        "date": today,
        "generated_at": "2026-06-11T04:30:50Z",
        "model": "gemini-flash-latest",
        "sectors": {"note": "Existing note"},
        "industries": {},
    }
    with open(tmp_path / "ai" / f"{today}.json", "w") as f:
        json.dump(partial, f)

    call_log = []
    def fake_generate(client, group_type, date_str, existing=None):
        call_log.append((group_type, list(existing.keys()) if existing else []))
        if group_type == "sector":
            return {
                "note": "Sector note",
                "rotation_phase": {"label": "Defensive", "reasoning": "test"},
            }
        return {"note": "Industry note"}

    monkeypatch.setattr(generate_ai, "generate_for_group", fake_generate)
    mock_genai = MagicMock()
    mock_google = MagicMock()
    mock_google.genai = mock_genai
    monkeypatch.setitem(sys.modules, "google", mock_google)
    monkeypatch.setitem(sys.modules, "google.genai", mock_genai)

    generate_ai.main()

    with open(tmp_path / "ai" / f"{today}.json") as f:
        result = json.load(f)

    assert result["sectors"]["note"] == "Sector note"
    assert isinstance(result["sectors"]["rotation_phase"], dict)
    assert result["industries"]["note"] == "Industry note"

    assert call_log[0][0] == "sector"
    assert call_log[1][0] == "industry"
    # With incremental loading: sectors existing has "note" key from partial file
    assert "note" in call_log[0][1]
    # industries existing is empty (no fields in partial industries)
    assert call_log[1][1] == []

    assert (tmp_path / "ai_run_summary.json").exists()
    with open(tmp_path / "ai_run_summary.json") as f:
        summary = json.load(f)
    assert summary["outcome"] == "complete"


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
            "note": "text",
            "rotation_phase": {"label": "Defensive", "reasoning": "..."},
        },
        "industries": {"note": "Industry text"},
    }
    with open(tmp_path / "ai" / f"{today}.json", "w") as f:
        json.dump(complete, f)

    generate_called = []
    def mock_generate(*_, **__):
        generate_called.append(True)
        # Return full data so outcome is "complete" not "failed"
        if len(generate_called) == 1:  # sector call
            return {
                "note": "Sector content",
                "rotation_phase": {"label": "Early Cycle", "reasoning": "test"},
            }
        else:  # industry call
            return {"note": "Industry content"}
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
def test_call_api_retries_on_empty_response(monkeypatch):
    """Test that empty response.text is treated as retryable error."""
    from unittest.mock import MagicMock

    client = MagicMock()
    # First two calls return empty text, third succeeds
    response_empty = MagicMock()
    response_empty.text = None
    response_ok = MagicMock()
    response_ok.text = "Energy leads."

    client.models.generate_content.side_effect = [response_empty, response_empty, response_ok]
    monkeypatch.setattr(generate_ai, "_INTER_CALL_DELAY", 0)
    monkeypatch.setattr(generate_ai, "_RETRY_BASE_DELAY", 0)

    result = generate_ai._call_api(client, "prompt", max_retries=3)
    assert result == "Energy leads."
    assert client.models.generate_content.call_count == 3


def test_call_api_retries_on_whitespace_response(monkeypatch):
    """Test that whitespace-only response.text is treated as retryable error."""
    from unittest.mock import MagicMock

    client = MagicMock()
    response_ws = MagicMock()
    response_ws.text = "   \n\n  "
    response_ok = MagicMock()
    response_ok.text = "Energy leads."

    client.models.generate_content.side_effect = [response_ws, response_ok]
    monkeypatch.setattr(generate_ai, "_INTER_CALL_DELAY", 0)
    monkeypatch.setattr(generate_ai, "_RETRY_BASE_DELAY", 0)

    result = generate_ai._call_api(client, "prompt", max_retries=3)
    assert result == "Energy leads."


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


# ---------------------------------------------------------------------------
# Fix 1: Incremental loading — complete files are regenerated fresh
# ---------------------------------------------------------------------------

def test_main_regenerates_complete_file_fresh(monkeypatch, tmp_path):
    """Complete file: main() regenerates all fields (no skip). was_incremental=False."""
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
        "sectors": {"note": "old", "rotation_phase": {"label": "Defensive", "reasoning": "x"}},
        "industries": {"note": "old"},
    }
    (tmp_path / "ai" / f"{today}.json").write_text(json.dumps(complete))

    call_log = []
    def fake_generate(client, group_type, date_str, existing=None):
        call_log.append((group_type, dict(existing or {})))
        if group_type == "sector":
            return {"note": "fresh", "rotation_phase": {"label": "Early Cycle", "reasoning": "x"}}
        return {"note": "fresh-ind"}

    monkeypatch.setattr(generate_ai, "generate_for_group", fake_generate)
    mock_genai = MagicMock()
    mock_google = MagicMock()
    mock_google.genai = mock_genai
    monkeypatch.setitem(sys.modules, "google", mock_google)
    monkeypatch.setitem(sys.modules, "google.genai", mock_genai)

    generate_ai.main()

    # Both groups regenerated (not skipped)
    assert len(call_log) == 2
    # existing passed to generate_for_group is empty (complete file not loaded as incremental)
    assert call_log[0][1] == {}
    assert call_log[1][1] == {}


def test_main_partial_file_corrupt_json_falls_back_to_full_generation(monkeypatch, tmp_path):
    """Corrupt partial file falls back to full generation, no crash."""
    from unittest.mock import MagicMock
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.delenv("FORCE_AI", raising=False)
    monkeypatch.setattr(generate_ai, "AI_DIR", tmp_path / "ai")
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)
    monkeypatch.setattr(generate_ai, "_has_new_delta_data", lambda _: True)

    import datetime as _dt
    today = _dt.date.today().isoformat()
    (tmp_path / "ai").mkdir(parents=True)
    (tmp_path / "ai" / f"{today}.json").write_text("NOT VALID JSON {{{")

    call_log = []
    def fake_generate(client, group_type, date_str, existing=None):
        call_log.append((group_type, dict(existing or {})))
        if group_type == "sector":
            return {"briefing": "text", "rotation_phase": {"label": "Defensive", "reasoning": "x"},
                    "watchlist": [{"name": "E", "thesis": "ok"}]}
        return {"briefing": "text", "rotation_phase": {"label": "Tech", "reasoning": "x"},
                "watchlist": [{"name": "S", "thesis": "ok"}]}

    monkeypatch.setattr(generate_ai, "generate_for_group", fake_generate)
    mock_genai = MagicMock()
    mock_google = MagicMock()
    mock_google.genai = mock_genai
    monkeypatch.setitem(sys.modules, "google", mock_google)
    monkeypatch.setitem(sys.modules, "google.genai", mock_genai)

    generate_ai.main()  # must not crash

    # Falls back to full generation with empty existing
    assert len(call_log) == 2
    assert call_log[0][1] == {}


# ---------------------------------------------------------------------------
# Fix 2: DailyQuotaExhaustedError — detection and abort
# ---------------------------------------------------------------------------

def test_call_api_raises_daily_quota_error_without_retrying(monkeypatch):
    """When Gemini returns GenerateRequestsPerDayPerProjectPerModel error, raise immediately, no retry."""
    daily_quota_err = Exception(
        "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': "
        "'Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, "
        "limit: 20, model: gemini-2.5-flash', 'status': 'RESOURCE_EXHAUSTED', 'details': [{"
        "'@type': 'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [{"
        "'quotaMetric': 'generativelanguage.googleapis.com/generate_content_free_tier_requests', "
        "'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}]}]}}"
    )
    monkeypatch.setattr(generate_ai, "_last_api_call", 0.0)
    sleep_calls = []
    monkeypatch.setattr("time.sleep", lambda s: sleep_calls.append(s))
    generate_ai._reset_tracking()
    client = _make_client([daily_quota_err])

    with pytest.raises(generate_ai.DailyQuotaExhaustedError):
        generate_ai._call_api(client, "prompt")

    # Only ONE API call — no retries
    assert client.models.generate_content.call_count == 1
    # No sleep for retries
    assert sleep_calls == []
    # rate_limit_hits not incremented for daily quota errors
    assert generate_ai._rate_limit_hits == 0


def test_call_api_retries_per_minute_quota_not_daily(monkeypatch):
    """Per-minute rate limit (no 'GenerateRequestsPerDayPerProjectPerModel') should still retry."""
    per_minute_err = Exception(
        "429 RESOURCE_EXHAUSTED. Quota exceeded for metric: "
        "generativelanguage.googleapis.com/generate_content_requests_per_minute"
    )
    monkeypatch.setattr(generate_ai, "_last_api_call", 0.0)
    sleep_calls = []
    monkeypatch.setattr("time.sleep", lambda s: sleep_calls.append(s))
    generate_ai._reset_tracking()
    client = _make_client([per_minute_err, "ok"])

    result = generate_ai._call_api(client, "prompt")
    assert result == "ok"
    assert client.models.generate_content.call_count == 2
    assert len(sleep_calls) >= 1
    assert generate_ai._rate_limit_hits == 1


def test_generate_for_group_propagates_daily_quota_error(monkeypatch):
    """DailyQuotaExhaustedError raised inside generate_for_group propagates to caller."""
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
    monkeypatch.setattr(generate_ai, "load_latest_snapshot", lambda _: snap)
    monkeypatch.setattr(generate_ai, "load_latest_delta", lambda _: pd.DataFrame())

    def fail_with_daily_quota(client, prompt, **kwargs):
        raise generate_ai.DailyQuotaExhaustedError("daily quota hit")

    monkeypatch.setattr(generate_ai, "_call_api", fail_with_daily_quota)

    with pytest.raises(generate_ai.DailyQuotaExhaustedError):
        generate_ai.generate_for_group(_make_client([]), "sector", "2026-06-11")

    # First field (note) was logged as quota_exhausted
    assert generate_ai._field_log["sectors.note"]["status"] == "quota_exhausted"


def test_main_saves_partial_and_aborts_on_daily_quota(monkeypatch, tmp_path):
    """When DailyQuotaExhaustedError raised during generation, partial output is saved and outcome=quota_exhausted."""
    from unittest.mock import MagicMock
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.delenv("FORCE_AI", raising=False)
    monkeypatch.setattr(generate_ai, "AI_DIR", tmp_path / "ai")
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)
    monkeypatch.setattr(generate_ai, "_has_new_delta_data", lambda _: True)

    import datetime as _dt
    today = _dt.date.today().isoformat()
    (tmp_path / "ai").mkdir(parents=True)

    call_count = {"n": 0}
    def fake_generate(client, group_type, date_str, existing=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # First call (sector): succeeds partially
            return {"briefing": "partial sector briefing"}
        # Second call (industry): hits daily quota
        raise generate_ai.DailyQuotaExhaustedError("daily quota exhausted")

    monkeypatch.setattr(generate_ai, "generate_for_group", fake_generate)
    mock_genai = MagicMock()
    mock_google = MagicMock()
    mock_google.genai = mock_genai
    monkeypatch.setitem(sys.modules, "google", mock_google)
    monkeypatch.setitem(sys.modules, "google.genai", mock_genai)

    with pytest.raises(SystemExit) as exc_info:
        generate_ai.main()
    assert exc_info.value.code == 0

    # Partial file should be written (sectors has content)
    ai_file = tmp_path / "ai" / f"{today}.json"
    assert ai_file.exists(), "Partial output file must be saved on quota exhaustion"
    with open(ai_file) as f:
        saved = json.load(f)
    assert saved["sectors"]["briefing"] == "partial sector briefing"

    # Run log shows quota_exhausted outcome
    log_path = tmp_path / "ai_run_log.jsonl"
    assert log_path.exists()
    log_entry = json.loads(log_path.read_text().strip().split("\n")[-1])
    assert log_entry["outcome"] == "quota_exhausted"


def test_main_no_partial_file_written_when_quota_hits_on_first_field(monkeypatch, tmp_path):
    """If quota hits on the very first field, no partial file is written."""
    from unittest.mock import MagicMock
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.delenv("FORCE_AI", raising=False)
    monkeypatch.setattr(generate_ai, "AI_DIR", tmp_path / "ai")
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)
    monkeypatch.setattr(generate_ai, "_has_new_delta_data", lambda _: True)

    import datetime as _dt
    today = _dt.date.today().isoformat()
    (tmp_path / "ai").mkdir(parents=True)

    def fake_generate(client, group_type, date_str, existing=None):
        raise generate_ai.DailyQuotaExhaustedError("quota on first call")

    monkeypatch.setattr(generate_ai, "generate_for_group", fake_generate)
    mock_genai = MagicMock()
    mock_google = MagicMock()
    mock_google.genai = mock_genai
    monkeypatch.setitem(sys.modules, "google", mock_google)
    monkeypatch.setitem(sys.modules, "google.genai", mock_genai)

    with pytest.raises(SystemExit) as exc_info:
        generate_ai.main()
    assert exc_info.value.code == 0

    # No partial file written — nothing was generated
    assert not (tmp_path / "ai" / f"{today}.json").exists()

    log_entry = json.loads((tmp_path / "ai_run_log.jsonl").read_text().strip())
    assert log_entry["outcome"] == "quota_exhausted"


# ---------------------------------------------------------------------------
# Vertex AI dual-mode client init (migration)
# ---------------------------------------------------------------------------

def _run_main_capture_client(monkeypatch, tmp_path):
    """Run main() far enough to init the client, then short-circuit generation.

    generate_for_group returns {} so main() hits the skip-trap and exits 0
    without writing a dated file. Returns the injected mock genai module so the
    caller can assert on the genai.Client(...) call kwargs.
    """
    from unittest.mock import MagicMock
    monkeypatch.delenv("FORCE_AI", raising=False)
    monkeypatch.setattr(generate_ai, "AI_DIR", tmp_path / "ai")
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)
    monkeypatch.setattr(generate_ai, "_has_new_delta_data", lambda _: True)
    monkeypatch.setattr(generate_ai, "generate_for_group", lambda *_, **__: {})
    monkeypatch.setattr(generate_ai, "_backend", "unset")
    mock_genai = MagicMock()
    mock_google = MagicMock()
    mock_google.genai = mock_genai
    monkeypatch.setitem(sys.modules, "google", mock_google)
    monkeypatch.setitem(sys.modules, "google.genai", mock_genai)
    with pytest.raises(SystemExit) as exc_info:
        generate_ai.main()
    assert exc_info.value.code == 0
    return mock_genai


def test_main_uses_vertex_client_when_flag_set(monkeypatch, tmp_path):
    """GOOGLE_GENAI_USE_VERTEXAI=true → genai.Client(vertexai=True, project, location)."""
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-east1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    mock_genai = _run_main_capture_client(monkeypatch, tmp_path)

    kwargs = mock_genai.Client.call_args.kwargs
    assert kwargs.get("vertexai") is True
    assert kwargs.get("project") == "test-project"
    assert kwargs.get("location") == "us-east1"
    assert "api_key" not in kwargs
    assert generate_ai._backend == "vertex_ai"


def test_main_uses_ai_studio_client_when_flag_absent(monkeypatch, tmp_path):
    """No toggle + GEMINI_API_KEY set → genai.Client(api_key=...), backward compatible."""
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    mock_genai = _run_main_capture_client(monkeypatch, tmp_path)

    kwargs = mock_genai.Client.call_args.kwargs
    assert kwargs.get("api_key") == "test-key"
    assert "vertexai" not in kwargs
    assert generate_ai._backend == "google_ai_studio"


def test_main_exits_zero_when_vertex_flag_set_but_no_project(monkeypatch, tmp_path):
    """Toggle on but GOOGLE_CLOUD_PROJECT unset → graceful skip (exit 0)."""
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("FORCE_AI", raising=False)
    monkeypatch.setattr(generate_ai, "AI_DIR", tmp_path / "ai")
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)
    monkeypatch.setattr(generate_ai, "_has_new_delta_data", lambda _: True)
    with pytest.raises(SystemExit) as exc_info:
        generate_ai.main()
    assert exc_info.value.code == 0


def test_main_exits_zero_when_no_flag_and_no_key(monkeypatch, tmp_path):
    """No toggle and no GEMINI_API_KEY → graceful skip (existing behavior preserved)."""
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("FORCE_AI", raising=False)
    monkeypatch.setattr(generate_ai, "AI_DIR", tmp_path / "ai")
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)
    monkeypatch.setattr(generate_ai, "_has_new_delta_data", lambda _: True)
    with pytest.raises(SystemExit) as exc_info:
        generate_ai.main()
    assert exc_info.value.code == 0


def test_run_log_includes_backend_field(monkeypatch, tmp_path):
    """_write_run_artifacts records the active backend in ai_run_log.jsonl."""
    monkeypatch.setattr(generate_ai, "DATA_DIR", tmp_path)
    generate_ai._reset_tracking()
    monkeypatch.setattr(generate_ai, "_backend", "vertex_ai")
    generate_ai._write_run_artifacts("complete", False, 1.0, "2026-06-14")
    log_entry = json.loads((tmp_path / "ai_run_log.jsonl").read_text().strip())
    assert log_entry["backend"] == "vertex_ai"
