"""Tests for scripts/build_signals.py — the public agent feed (manifest + latest_signals)."""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_signals as bs  # noqa: E402


def _industries():
    return pd.DataFrame([
        {"date": "2026-09-14", "name": "Steel", "rank_ytd": 1,
         "regime_short_long": 0.8, "momentum_score": 0.9, "rs_score": 0.83,
         "rank_ytd_delta_20d": 6},
        {"date": "2026-09-14", "name": "Gold", "rank_ytd": 2,
         "regime_short_long": 0.4, "momentum_score": 0.7, "rs_score": 0.66,
         "rank_ytd_delta_20d": -4},
        {"date": "2026-09-14", "name": "Banks", "rank_ytd": 3,
         "regime_short_long": float("nan"), "momentum_score": 0.5, "rs_score": 0.5,
         "rank_ytd_delta_20d": float("nan")},
    ])


def _sectors():
    return pd.DataFrame([
        {"date": "2026-09-14", "name": "Basic Materials", "rank_ytd": 1,
         "regime_short_long": 0.5},
    ])


def _picks():
    return pd.DataFrame([
        {"date": "2026-09-14", "ticker": "NUE", "group": "Steel",
         "list_category": "leaders", "atr_ext_50": 3.7},
        {"date": "2026-09-14", "ticker": "STLD", "group": "Steel",
         "list_category": "emerging", "atr_ext_50": float("nan")},
    ])


def test_signals_shape_and_version():
    out = bs.build_signals(_industries(), _sectors(), _picks(), "branch-x")
    assert out["schema_version"] == bs.SCHEMA_VERSION
    assert out["as_of"] == "2026-09-14"
    assert out["session"] == "eod"
    assert out["data_branch"] == "branch-x"
    assert out["universe"] == {"sectors": 1, "industries": 3}


def test_emerging_leaders_sorted_and_drops_nan():
    out = bs.build_signals(_industries(), _sectors(), _picks(), "b")
    leaders = out["emerging_leaders"]
    # Banks (NaN regime) dropped; Steel (0.8) before Gold (0.4).
    assert [l["group"] for l in leaders] == ["Steel", "Gold"]
    assert leaders[0]["regime_short_long"] == 0.8


def test_movers_and_fading_split_on_delta():
    out = bs.build_signals(_industries(), _sectors(), _picks(), "b")
    # Steel improved (+6) leads movers; Gold (-4) leads fading; Banks (NaN) excluded.
    assert out["top_movers"][0]["group"] == "Steel"
    assert out["top_movers"][0]["rank_delta"] == 6
    assert out["fading"][0]["group"] == "Gold"
    assert all(m["group"] != "Banks" for m in out["top_movers"] + out["fading"])


def test_picks_grouped_by_category_raw_atr_only():
    out = bs.build_signals(_industries(), _sectors(), _picks(), "b")
    assert set(out["picks"]) == {"leaders", "emerging"}
    nue = out["picks"]["leaders"][0]
    assert nue["ticker"] == "NUE"
    assert nue["atr_ext_50"] == 3.7
    # No derived band label persisted — consumer derives from manifest thresholds.
    assert "band" not in nue
    # NaN atr passes through as None, not a crash.
    assert out["picks"]["emerging"][0]["atr_ext_50"] is None


def test_manifest_index_and_config():
    m = bs.build_manifest(_industries(), _sectors(), _picks(), "b", "2026-09-14")
    assert m["signals_file"] == "data/api/latest_signals.json"
    assert m["row_counts"] == {"sectors": 1, "industries": 3, "picks": 2}
    assert m["history"]["picks_history"] == "data/picks/picks.csv"
    assert m["config"]["atr_bands"] == {"actionable_max": 4.0, "trim_min": 8.0}


def test_empty_frames_do_not_crash():
    empty = pd.DataFrame()
    out = bs.build_signals(empty, empty, empty, "b")
    assert out["as_of"] is None
    assert out["emerging_leaders"] == []
    assert out["picks"] == {}
    m = bs.build_manifest(empty, empty, empty, "b", None)
    assert m["row_counts"] == {"sectors": 0, "industries": 0, "picks": 0}


def test_main_writes_both_files(tmp_path):
    # main() reads real repo data; just assert it produces valid, parseable JSON.
    import subprocess
    r = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent.parent / "scripts" / "build_signals.py"),
         "--out-dir", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    signals = json.loads((tmp_path / "latest_signals.json").read_text())
    assert manifest["schema_version"] == bs.SCHEMA_VERSION
    assert signals["schema_version"] == bs.SCHEMA_VERSION
