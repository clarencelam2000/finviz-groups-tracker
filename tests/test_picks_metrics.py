"""
Tests for scripts/picks_metrics.py — backend derived columns for Phase 3a.

Covers:
  - Parser functions (_pct, _cap_b, _float)
  - compute_metrics_row on the four spec worked examples (EOD 2026-06-25)
  - NaN safety when ATR / SMA fields are blank
  - stage2 truth table
  - ensure_picks_csv migration (old 108-col rows gain the 5 new columns)
"""
import csv
import io
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from picks_metrics import (
    METRICS_COLS,
    _cap_b,
    _float,
    _pct,
    compute_metrics_row,
    compute_trailing_setup,
)
import picks_config as pc
from collect_picks import ensure_picks_csv


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------

def test_pct_percent_string():
    assert abs(_pct("3.52%") - 3.52) < 1e-9

def test_pct_bare_float():
    assert abs(_pct("3.52") - 3.52) < 1e-9

def test_pct_negative():
    assert abs(_pct("-5.26%") - (-5.26)) < 1e-9

def test_pct_blank():
    assert math.isnan(_pct(""))

def test_pct_dash():
    assert math.isnan(_pct("-"))

def test_pct_none():
    assert math.isnan(_pct(None))

def test_cap_b_billion():
    assert abs(_cap_b("208.34B") - 208.34) < 1e-9

def test_cap_b_trillion():
    assert abs(_cap_b("1.5T") - 1500.0) < 1e-9

def test_cap_b_million():
    assert abs(_cap_b("850M") - 0.85) < 1e-6

def test_cap_b_thousand():
    assert abs(_cap_b("500K") - 0.0005) < 1e-9

def test_cap_b_blank():
    assert math.isnan(_cap_b(""))

def test_cap_b_dash():
    assert math.isnan(_cap_b("-"))

def test_float_plain():
    assert abs(_float("165.45") - 165.45) < 1e-9

def test_float_comma():
    assert abs(_float("1,025.36") - 1025.36) < 1e-9

def test_float_blank():
    assert math.isnan(_float(""))

def test_float_none():
    assert math.isnan(_float(None))

def test_float_dash():
    assert math.isnan(_float("-"))


# ---------------------------------------------------------------------------
# Worked examples — EOD 2026-06-25 data (spec §Phase 3a acceptance criteria)
# Tolerance ±0.01 for atr_ext_50, ±0.003 for risk_* (all as raw fractions).
# ---------------------------------------------------------------------------

def _row_from_csv(ticker):
    """Load one row from the 113-col EOD fixture."""
    fixture = ROOT / "tests" / "fixtures" / "picks_latest.csv"
    with fixture.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["ticker"] == ticker:
                return row
    raise KeyError(f"ticker {ticker!r} not in fixture")


def test_anet_atr_ext_50():
    row = _row_from_csv("ANET")
    m = compute_metrics_row(row)
    # ANET EOD: Price=165.45, SMA50=3.52%, ATR=8.39 → ≈0.67
    assert abs(m["atr_ext_50"] - 0.67) < 0.01, m["atr_ext_50"]

def test_stx_atr_ext_50():
    row = _row_from_csv("STX")
    m = compute_metrics_row(row)
    assert abs(m["atr_ext_50"] - 3.16) < 0.01, m["atr_ext_50"]

def test_dell_atr_ext_50():
    row = _row_from_csv("DELL")
    m = compute_metrics_row(row)
    assert abs(m["atr_ext_50"] - 3.64) < 0.01, m["atr_ext_50"]

def test_sndk_atr_ext_50():
    row = _row_from_csv("SNDK")
    m = compute_metrics_row(row)
    assert abs(m["atr_ext_50"] - 4.55) < 0.01, m["atr_ext_50"]

def test_anet_risk_20ma_pct():
    row = _row_from_csv("ANET")
    m = compute_metrics_row(row)
    # ANET EOD: risk_20ma_pct ≈ 1.15% = 0.0115 fraction
    assert abs(m["risk_20ma_pct"] - 0.0115) < 0.003, m["risk_20ma_pct"]

def test_anet_risk_50ma_pct():
    row = _row_from_csv("ANET")
    m = compute_metrics_row(row)
    # ANET EOD: risk_50ma_pct ≈ 3.40% = 0.0340 fraction
    assert abs(m["risk_50ma_pct"] - 0.0340) < 0.003, m["risk_50ma_pct"]

def test_anet_range_atr():
    row = _row_from_csv("ANET")
    m = compute_metrics_row(row)
    # (170.16 - 159.46) / 8.39 ≈ 1.275
    assert abs(m["range_atr"] - 1.275) < 0.01, m["range_atr"]

def test_anet_stage2():
    row = _row_from_csv("ANET")
    m = compute_metrics_row(row)
    assert m["stage2"] == 1

def test_sndk_stage2():
    row = _row_from_csv("SNDK")
    m = compute_metrics_row(row)
    assert m["stage2"] == 1


# ---------------------------------------------------------------------------
# NaN safety
# ---------------------------------------------------------------------------

def test_blank_atr_gives_nan_atr_ext():
    row = {"Price": "100.0", "ATR": "", "SMA20": "2.0%", "SMA50": "3.0%",
           "SMA200": "10.0%", "High": "102.0", "Low": "98.0"}
    m = compute_metrics_row(row)
    assert math.isnan(m["atr_ext_50"])
    assert math.isnan(m["range_atr"])
    # risk values are still computable when ATR is blank
    assert not math.isnan(m["risk_20ma_pct"])
    assert not math.isnan(m["risk_50ma_pct"])

def test_blank_price_gives_nan_for_price_derived():
    # range_atr = (High-Low)/ATR and stage2 = f(SMA50_pct, SMA200_pct) do NOT require
    # price — both are still computable. atr_ext_50 and risk_* need price (or sma_price).
    row = {"Price": "", "ATR": "5.0", "SMA20": "2%", "SMA50": "3%",
           "SMA200": "10%", "High": "102", "Low": "98"}
    m = compute_metrics_row(row)
    assert math.isnan(m["atr_ext_50"])
    assert math.isnan(m["risk_20ma_pct"])
    assert math.isnan(m["risk_50ma_pct"])
    assert not math.isnan(m["range_atr"]), "range_atr computable without price"
    assert not math.isnan(m["stage2"]), "stage2 computable without price (uses SMA pcts)"
    assert m["stage2"] == 1  # SMA50=3>0, SMA200=10>3

def test_blank_sma50_gives_nan_metrics():
    row = {"Price": "100", "ATR": "5", "SMA20": "2%", "SMA50": "",
           "SMA200": "10%", "High": "102", "Low": "98"}
    m = compute_metrics_row(row)
    assert math.isnan(m["atr_ext_50"])
    assert math.isnan(m["risk_50ma_pct"])
    assert math.isnan(m["stage2"])

def test_testblk_fixture_has_nan_atr_ext():
    row = _row_from_csv("TESTBLK")
    m = compute_metrics_row(row)
    assert math.isnan(m["atr_ext_50"]) or row.get("atr_ext_50", "") == ""


# ---------------------------------------------------------------------------
# stage2 truth table
# ---------------------------------------------------------------------------

def _s2(sma50_pct, sma200_pct):
    row = {"Price": "100", "ATR": "5", "SMA20": "2%",
           "SMA50": f"{sma50_pct}%", "SMA200": f"{sma200_pct}%",
           "High": "102", "Low": "98"}
    return compute_metrics_row(row)["stage2"]

def test_stage2_price_above_50ma_and_50ma_above_200ma():
    # SMA50=3 (>0), SMA200=10 (>SMA50) → stage2=1
    assert _s2(3.0, 10.0) == 1

def test_stage2_price_below_50ma():
    # SMA50=-5 (≤0) → stage2=0 regardless of SMA200
    assert _s2(-5.0, 5.0) == 0

def test_stage2_50ma_below_200ma():
    # SMA50=10 (>0) but SMA200=5 (<SMA50) → 50MA < 200MA → stage2=0
    assert _s2(10.0, 5.0) == 0

def test_stage2_both_above_but_200_equal_50():
    # SMA50=5, SMA200=5 → not strictly greater → stage2=0
    assert _s2(5.0, 5.0) == 0

def test_stage2_nan_when_sma50_blank():
    row = {"Price": "100", "SMA50": "", "SMA200": "10%"}
    m = compute_metrics_row(row)
    assert math.isnan(m["stage2"])

def test_stage2_nan_when_sma200_blank():
    row = {"Price": "100", "SMA50": "3%", "SMA200": ""}
    m = compute_metrics_row(row)
    assert math.isnan(m["stage2"])


# ---------------------------------------------------------------------------
# ensure_picks_csv migration
# ---------------------------------------------------------------------------

def _make_old_csv(tmp_path, rows_data):
    """Write a picks.csv with only the original 108 cols (no METRICS_COLS, no
    collected_at — predates both; hardcoded rather than derived from
    pc.PICKS_LEAD_COLS since that now includes collected_at)."""
    config = pc.load_config()
    old_lead_cols = ["date", "list_category", "selector_version", "group", "ticker"]
    old_cols = old_lead_cols + pc.finviz_cols(config) + pc.PICKS_GRP_COLS
    csv_path = tmp_path / "picks.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=old_cols, extrasaction="ignore")
        writer.writeheader()
        for r in rows_data:
            writer.writerow({c: r.get(c, "") for c in old_cols})
    return csv_path, old_cols


def test_ensure_picks_csv_adds_metrics_cols(tmp_path):
    rows = [
        {"date": "2026-06-25", "list_category": "leaders", "selector_version": "v1",
         "group": "Semiconductors", "ticker": "ANET", "Ticker": "ANET",
         "Price": "165.45", "ATR": "8.39", "SMA20": "1.16%", "SMA50": "3.52%",
         "SMA200": "15.96%", "High": "170.16", "Low": "159.46",
         "Market Cap": "208.34B",
         "grp_rank_basis": "sustained_strength", "grp_category_rank": "1",
         "grp_sum_mid_rank": "4.0"},
    ]
    csv_path, old_cols = _make_old_csv(tmp_path, rows)
    latest_path = tmp_path / "picks_latest.csv"

    ensure_picks_csv(csv_path, latest_path)

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        new_cols = reader.fieldnames
        migrated = list(reader)

    # All METRICS_COLS must now be present
    for col in METRICS_COLS:
        assert col in new_cols, f"Missing {col} after migration"

    # atr_ext_50 should be ≈0.67 (ANET EOD worked example)
    row = migrated[0]
    assert abs(float(row["atr_ext_50"]) - 0.67) < 0.01, row["atr_ext_50"]
    assert row["stage2"] == "1"

    # latest_csv should also have been rewritten
    assert latest_path.exists()
    with open(latest_path) as f:
        latest_reader = csv.DictReader(f)
        latest_cols = latest_reader.fieldnames
    for col in METRICS_COLS:
        assert col in latest_cols


def test_ensure_picks_csv_noop_when_cols_present(tmp_path):
    """Second call is a pure no-op: no rewrite happens."""
    config = pc.load_config()
    all_cols = pc.picks_columns(config)
    csv_path = tmp_path / "picks.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_cols)
        writer.writeheader()
        writer.writerow({c: "" for c in all_cols})

    mtime_before = csv_path.stat().st_mtime
    ensure_picks_csv(csv_path)
    mtime_after = csv_path.stat().st_mtime
    assert mtime_before == mtime_after, "ensure_picks_csv should be a no-op if cols present"


def test_ensure_picks_csv_noop_on_missing_file(tmp_path):
    """Missing file → no crash."""
    ensure_picks_csv(tmp_path / "nonexistent.csv")  # must not raise


# ---------------------------------------------------------------------------
# compute_trailing_setup (B-2, issue #379) — trailing-window compression columns
# ---------------------------------------------------------------------------

def _bar(ticker, date, high, low, atr, range_atr):
    return {"ticker": ticker, "date": date, "High": str(high), "Low": str(low),
            "ATR": str(atr), "range_atr": str(range_atr)}


def test_trailing_tight_range_fires_when_today_narrowest():
    """tight_range_7 = 1 when today's H-L is the narrowest of the last `window` bars."""
    hist = [
        _bar("X", "2026-08-20", 110, 100, 5, 2.0),  # range 10
        _bar("X", "2026-08-21", 109, 100, 5, 1.8),  # range 9
        _bar("X", "2026-08-22", 108, 100, 5, 1.6),  # range 8
        _bar("X", "2026-08-25", 104, 100, 5, 0.8),  # range 4  <- today, narrowest
    ]
    latest = [dict(hist[-1])]
    compute_trailing_setup(latest, hist, window=4, spark_window=10, spark_min=3)
    assert latest[0]["tight_range_7"] == 1
    # range_atr sparkline = last values oldest->newest
    assert latest[0]["range_atr_spark"] == "2.00|1.80|1.60|0.80"
    assert latest[0]["atr_spark"] == "5.00|5.00|5.00|5.00"


def test_trailing_tight_range_zero_when_prior_bar_tighter():
    hist = [
        _bar("X", "2026-08-20", 103, 100, 5, 0.6),  # range 3 (tighter)
        _bar("X", "2026-08-21", 109, 100, 5, 1.8),
        _bar("X", "2026-08-22", 108, 100, 5, 1.6),
        _bar("X", "2026-08-25", 105, 100, 5, 1.0),  # today range 5, not narrowest
    ]
    latest = [dict(hist[-1])]
    compute_trailing_setup(latest, hist, window=4, spark_window=10, spark_min=3)
    assert latest[0]["tight_range_7"] == 0


def test_trailing_graceful_degrade_when_too_few_bars():
    """<window bars -> tight flag ''; <spark_min bars -> spark ''."""
    hist = [
        _bar("X", "2026-08-24", 108, 100, 5, 1.6),
        _bar("X", "2026-08-25", 105, 100, 5, 1.0),
    ]
    latest = [dict(hist[-1])]
    compute_trailing_setup(latest, hist, window=7, spark_window=10, spark_min=3)
    assert latest[0]["tight_range_7"] == ""      # only 2 bars, need 7
    assert latest[0]["range_atr_spark"] == ""    # only 2 bars, need 3


def test_trailing_relvol_spark_series_and_degrade():
    """relvol_spark (B-3) = trailing Rel Volume series oldest->newest; '' below spark_min.
    A SHOWN value (doc §4.0) — volume dry-up reads off the series, never a threshold."""
    def _rv(date, rv):
        return {"ticker": "X", "date": date, "High": "10", "Low": "9",
                "ATR": "1", "range_atr": "1", "Rel Volume": str(rv)}
    hist = [_rv("2026-08-20", 1.4), _rv("2026-08-21", 1.1),
            _rv("2026-08-22", 0.9), _rv("2026-08-25", 0.7)]  # drying up
    latest = [dict(hist[-1])]
    compute_trailing_setup(latest, hist, window=4, spark_window=10, spark_min=3)
    assert latest[0]["relvol_spark"] == "1.40|1.10|0.90|0.70"
    # graceful degrade: fewer than spark_min bars -> blank, never a fabricated series
    latest2 = [dict(hist[-1])]
    compute_trailing_setup(latest2, hist[-2:], window=7, spark_window=10, spark_min=3)
    assert latest2[0]["relvol_spark"] == ""


def test_trailing_dedups_same_date_multi_category_rows():
    """A ticker appearing twice on one date (two buckets) counts as ONE bar, not two."""
    hist = [
        _bar("X", "2026-08-20", 110, 100, 5, 2.0),
        _bar("X", "2026-08-21", 109, 100, 5, 1.8),
        _bar("X", "2026-08-22", 108, 100, 5, 1.6),
        _bar("X", "2026-08-25", 104, 100, 5, 0.8),
        _bar("X", "2026-08-25", 104, 100, 5, 0.8),  # duplicate date (2nd bucket)
    ]
    latest = [dict(hist[-1])]
    compute_trailing_setup(latest, hist, window=4, spark_window=10, spark_min=3)
    # 4 unique dates -> spark has 4 points, not 5
    assert len(latest[0]["range_atr_spark"].split("|")) == 4
