"""Tests for dashboard/sector_breadth.py — compute_sector_breadth."""

import math
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "dashboard"))
from sector_breadth import compute_sector_breadth


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TAX = {
    "Technology": ["Semiconductors", "Software - Application", "Consumer Electronics"],
    "Energy": ["Oil & Gas E&P", "Oil & Gas Integrated"],
}


def _df(rows):
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


def test_returns_expected_sectors():
    df = _df([
        {"name": "Semiconductors", "rank_week": 1},
        {"name": "Software - Application", "rank_week": 2},
        {"name": "Consumer Electronics", "rank_week": 3},
        {"name": "Oil & Gas E&P", "rank_week": 4},
        {"name": "Oil & Gas Integrated", "rank_week": 5},
    ])
    result = compute_sector_breadth(df, TAX)
    assert set(result["sector"]) == {"Technology", "Energy"}


def test_top_half_count():
    # 5 total → threshold = 2.5 → ranks 1 and 2 are top-half
    df = _df([
        {"name": "Semiconductors", "rank_week": 1},
        {"name": "Software - Application", "rank_week": 2},
        {"name": "Consumer Electronics", "rank_week": 3},
        {"name": "Oil & Gas E&P", "rank_week": 4},
        {"name": "Oil & Gas Integrated", "rank_week": 5},
    ])
    result = compute_sector_breadth(df, TAX)
    tech = result[result["sector"] == "Technology"].iloc[0]
    assert tech["n_top_half"] == 2
    assert tech["n_mapped"] == 3

    energy = result[result["sector"] == "Energy"].iloc[0]
    assert energy["n_top_half"] == 0
    assert energy["pct_top_half"] == 0.0


def test_sorted_descending_by_pct():
    df = _df([
        {"name": "Semiconductors", "rank_week": 1},
        {"name": "Software - Application", "rank_week": 2},
        {"name": "Consumer Electronics", "rank_week": 3},
        {"name": "Oil & Gas E&P", "rank_week": 4},
        {"name": "Oil & Gas Integrated", "rank_week": 5},
    ])
    result = compute_sector_breadth(df, TAX)
    assert list(result["pct_top_half"]) == sorted(result["pct_top_half"], reverse=True)


def test_all_in_top_half():
    # 4 total → threshold = 2.0 → only rank 1 and 2 are top-half
    df = _df([
        {"name": "Semiconductors", "rank_week": 1},
        {"name": "Software - Application", "rank_week": 2},
        {"name": "Oil & Gas E&P", "rank_week": 3},
        {"name": "Oil & Gas Integrated", "rank_week": 4},
    ])
    result = compute_sector_breadth(df, TAX)
    tech = result[result["sector"] == "Technology"].iloc[0]
    # Consumer Electronics is not in the delta df → n_mapped=2; both ≤2 → n_top_half=2
    assert tech["n_mapped"] == 2
    assert tech["n_top_half"] == 2
    assert math.isclose(tech["pct_top_half"], 1.0)


def test_alternate_rank_col():
    df = _df([
        {"name": "Semiconductors", "rank_week": 99, "rank_ytd": 1},
        {"name": "Oil & Gas E&P", "rank_week": 99, "rank_ytd": 2},
    ])
    tax = {"Technology": ["Semiconductors"], "Energy": ["Oil & Gas E&P"]}
    # 2 total → threshold = 1.0 → only rank 1 is top-half
    result = compute_sector_breadth(df, tax, rank_col="rank_ytd")
    tech = result[result["sector"] == "Technology"].iloc[0]
    assert tech["n_top_half"] == 1
    energy = result[result["sector"] == "Energy"].iloc[0]
    assert energy["n_top_half"] == 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_delta_returns_empty():
    result = compute_sector_breadth(pd.DataFrame(), TAX)
    assert result.empty


def test_missing_rank_col_returns_empty():
    df = _df([{"name": "Semiconductors", "rank_ytd": 1}])
    result = compute_sector_breadth(df, TAX, rank_col="rank_week")
    assert result.empty


def test_empty_taxonomy_returns_empty():
    df = _df([{"name": "Semiconductors", "rank_week": 1}])
    result = compute_sector_breadth(df, {})
    assert result.empty


def test_nan_ranks_excluded_from_top_half_count():
    # NaN rank should not count as top-half
    df = _df([
        {"name": "Semiconductors", "rank_week": 1.0},
        {"name": "Software - Application", "rank_week": float("nan")},
        {"name": "Consumer Electronics", "rank_week": 3.0},
        {"name": "Oil & Gas E&P", "rank_week": 4.0},
        {"name": "Oil & Gas Integrated", "rank_week": 5.0},
    ])
    result = compute_sector_breadth(df, TAX)
    tech = result[result["sector"] == "Technology"].iloc[0]
    assert tech["n_mapped"] == 3  # NaN row still counted in n_mapped
    # threshold = 5/2 = 2.5; rank 1 ≤ 2.5 (yes); NaN excluded; rank 3 > 2.5 (no)
    assert tech["n_top_half"] == 1


def test_industry_not_in_taxonomy_is_ignored():
    # Delta has an industry that doesn't appear in the taxonomy — should not crash
    df = _df([
        {"name": "Semiconductors", "rank_week": 1},
        {"name": "Unknown Industry", "rank_week": 2},
    ])
    result = compute_sector_breadth(df, {"Technology": ["Semiconductors"]})
    assert len(result) == 1
    assert result.iloc[0]["sector"] == "Technology"
