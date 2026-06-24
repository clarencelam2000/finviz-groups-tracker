"""Tests for scripts/seed_taxonomy.py — parse_sector_industry_map, cross_validate, parse_industry_stock_map."""

import csv
import json
import pytest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from seed_taxonomy import parse_sector_industry_map, cross_validate, parse_industry_stock_map


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def make_tree(sectors: dict[str, list[str]]) -> dict:
    """Build a minimal fasiha-style treemap dict from a sector→industry dict."""
    children = []
    for sector_name, industries in sectors.items():
        ind_nodes = [
            {"name": ind, "children": [{"name": "TICK", "description": "Co", "value": 1}]}
            for ind in industries
        ]
        children.append({"name": sector_name, "children": ind_nodes})
    return {"name": "Root", "children": children}


# ---------------------------------------------------------------------------
# parse_sector_industry_map — happy paths
# ---------------------------------------------------------------------------

def test_parse_returns_correct_sectors():
    data = make_tree({
        "Technology": ["Semiconductors", "Software - Application"],
        "Financial": ["Banks - Diversified", "Capital Markets"],
    })
    result = parse_sector_industry_map(data)
    assert set(result.keys()) == {"Technology", "Financial"}


def test_parse_industries_are_sorted():
    data = make_tree({"Technology": ["Software - Application", "Semiconductors", "Consumer Electronics"]})
    result = parse_sector_industry_map(data)
    assert result["Technology"] == sorted(result["Technology"])


def test_parse_industry_counts():
    sectors = {
        "Technology": ["Semiconductors", "Software - Application", "Consumer Electronics"],
        "Energy": ["Oil & Gas E&P", "Oil & Gas Integrated"],
    }
    data = make_tree(sectors)
    result = parse_sector_industry_map(data)
    assert len(result["Technology"]) == 3
    assert len(result["Energy"]) == 2


def test_parse_sector_with_no_industries():
    data = make_tree({"Technology": ["Semiconductors"], "EmptySector": []})
    result = parse_sector_industry_map(data)
    assert result["EmptySector"] == []


def test_parse_skips_industry_nodes_with_no_name():
    data = make_tree({"Technology": ["Semiconductors"]})
    # Inject a nameless industry node
    data["children"][0]["children"].append({"description": "No name here"})
    result = parse_sector_industry_map(data)
    assert "Semiconductors" in result["Technology"]
    assert len(result["Technology"]) == 1  # nameless node skipped


# ---------------------------------------------------------------------------
# parse_sector_industry_map — error cases
# ---------------------------------------------------------------------------

def test_parse_raises_on_empty_children():
    with pytest.raises(ValueError, match="no 'children'"):
        parse_sector_industry_map({"name": "Root"})


def test_parse_raises_on_null_children():
    with pytest.raises(ValueError, match="no 'children'"):
        parse_sector_industry_map({"name": "Root", "children": None})


def test_parse_raises_on_sector_missing_name():
    data = {"name": "Root", "children": [{"description": "No name", "children": []}]}
    with pytest.raises(ValueError, match="missing 'name'"):
        parse_sector_industry_map(data)


# ---------------------------------------------------------------------------
# cross_validate
# ---------------------------------------------------------------------------

def test_cross_validate_perfect_match(tmp_path, monkeypatch):
    snap = tmp_path / "snapshots.csv"
    snap.write_text("date,name\n2026-06-01,Semiconductors\n2026-06-01,Software - Application\n")
    monkeypatch.chdir(tmp_path)
    # cross_validate reads relative path data/industries/snapshots.csv
    (tmp_path / "data" / "industries").mkdir(parents=True)
    (tmp_path / "data" / "industries" / "snapshots.csv").write_text(
        "date,name\n2026-06-01,Semiconductors\n2026-06-01,Software - Application\n"
    )
    sector_map = {"Technology": ["Semiconductors", "Software - Application"]}
    in_both, only_ours, only_theirs = cross_validate(sector_map)
    assert in_both == {"Semiconductors", "Software - Application"}
    assert only_ours == set()
    assert only_theirs == set()


def test_cross_validate_missing_in_fasiha(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "industries").mkdir(parents=True)
    (tmp_path / "data" / "industries" / "snapshots.csv").write_text(
        "date,name\n2026-06-01,Semiconductors\n2026-06-01,NewIndustry\n"
    )
    sector_map = {"Technology": ["Semiconductors"]}
    in_both, only_ours, only_theirs = cross_validate(sector_map)
    assert "NewIndustry" in only_ours
    assert "Semiconductors" in in_both


def test_cross_validate_extra_in_fasiha(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "industries").mkdir(parents=True)
    (tmp_path / "data" / "industries" / "snapshots.csv").write_text(
        "date,name\n2026-06-01,Semiconductors\n"
    )
    sector_map = {"Technology": ["Semiconductors", "Infrastructure Operations"]}
    in_both, only_ours, only_theirs = cross_validate(sector_map)
    assert "Infrastructure Operations" in only_theirs
    assert only_ours == set()


def test_cross_validate_empty_snapshot_returns_empty_sets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "industries").mkdir(parents=True)
    (tmp_path / "data" / "industries" / "snapshots.csv").write_text("date,name\n")
    sector_map = {"Technology": ["Semiconductors"]}
    in_both, only_ours, only_theirs = cross_validate(sector_map)
    assert in_both == set()
    assert only_ours == set()
    assert only_theirs == set()


def test_cross_validate_missing_snapshot_file_returns_empty_sets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "industries").mkdir(parents=True)
    sector_map = {"Technology": ["Semiconductors"]}
    in_both, only_ours, only_theirs = cross_validate(sector_map)
    assert in_both == set()


# ---------------------------------------------------------------------------
# parse_industry_stock_map — happy paths
# ---------------------------------------------------------------------------

def make_full_tree(sectors_with_stocks: dict) -> dict:
    """Build a treemap dict: sector → industry → list of (ticker, name, value)."""
    children = []
    for sector_name, industries in sectors_with_stocks.items():
        ind_nodes = []
        for ind_name, stocks in industries.items():
            stock_nodes = [
                {"name": t, "description": n, "value": v}
                for t, n, v in stocks
            ]
            ind_nodes.append({"name": ind_name, "children": stock_nodes})
        children.append({"name": sector_name, "children": ind_nodes})
    return {"name": "Root", "children": children}


def test_stock_map_sector_assignment():
    data = make_full_tree({
        "Technology": {"Semiconductors": [("NVDA", "NVIDIA", 3_000_000_000)]},
        "Financial": {"Banks - Diversified": [("JPM", "JPMorgan", 500_000_000)]},
    })
    result = parse_industry_stock_map(data)
    assert result["industries"]["Semiconductors"]["sector"] == "Technology"
    assert result["industries"]["Banks - Diversified"]["sector"] == "Financial"


def test_stock_map_market_cap_conversion():
    # value / 1000 = market_cap_m
    data = make_full_tree({
        "Technology": {"Semiconductors": [("NVDA", "NVIDIA", 3_255_318_000)]}
    })
    result = parse_industry_stock_map(data)
    stock = result["industries"]["Semiconductors"]["stocks"][0]
    assert stock["ticker"] == "NVDA"
    assert stock["market_cap_m"] == 3_255_318  # 3_255_318_000 / 1000


def test_stock_map_stocks_sorted_by_market_cap_descending():
    data = make_full_tree({
        "Technology": {"Semiconductors": [
            ("AMD", "AMD", 250_000_000),
            ("NVDA", "NVIDIA", 3_000_000_000),
            ("QCOM", "Qualcomm", 200_000_000),
        ]}
    })
    result = parse_industry_stock_map(data)
    stocks = result["industries"]["Semiconductors"]["stocks"]
    caps = [s["market_cap_m"] for s in stocks]
    assert caps == sorted(caps, reverse=True)
    assert stocks[0]["ticker"] == "NVDA"


def test_stock_map_ticker_to_industry_reverse_index():
    data = make_full_tree({
        "Technology": {"Semiconductors": [("NVDA", "NVIDIA", 1_000_000)]},
        "Financial": {"Banks - Diversified": [("JPM", "JPMorgan", 500_000)]},
    })
    result = parse_industry_stock_map(data)
    assert result["ticker_to_industry"]["NVDA"] == "Semiconductors"
    assert result["ticker_to_industry"]["JPM"] == "Banks - Diversified"


def test_stock_map_concentration_pct():
    # NVDA = 3000, AMD = 1000 → total = 4000 → concentration = 75%
    data = make_full_tree({
        "Technology": {"Semiconductors": [
            ("NVDA", "NVIDIA", 3_000_000),
            ("AMD", "AMD", 1_000_000),
        ]}
    })
    result = parse_industry_stock_map(data)
    ind = result["industries"]["Semiconductors"]
    assert ind["top_concentration_pct"] == 75.0
    assert ind["total_market_cap_m"] == 4000


def test_stock_map_total_market_cap_and_stock_count():
    data = make_full_tree({
        "Technology": {"Semiconductors": [
            ("NVDA", "NVIDIA", 3_000_000),
            ("AMD", "AMD", 1_000_000),
            ("QCOM", "Qualcomm", 500_000),
        ]}
    })
    result = parse_industry_stock_map(data)
    ind = result["industries"]["Semiconductors"]
    assert ind["stock_count"] == 3
    assert ind["total_market_cap_m"] == 4500


def test_stock_map_empty_industry_has_zero_concentration():
    data = make_full_tree({"Technology": {"EmptyIndustry": []}})
    result = parse_industry_stock_map(data)
    ind = result["industries"]["EmptyIndustry"]
    assert ind["stock_count"] == 0
    assert ind["top_concentration_pct"] is None


def test_stock_map_skips_stocks_with_no_ticker():
    data = make_full_tree({"Technology": {"Semiconductors": [("NVDA", "NVIDIA", 1_000_000)]}})
    # Inject nameless stock node
    data["children"][0]["children"][0]["children"].append(
        {"name": "", "description": "No ticker", "value": 500_000}
    )
    result = parse_industry_stock_map(data)
    assert result["industries"]["Semiconductors"]["stock_count"] == 1
    assert "" not in result["ticker_to_industry"]


def test_stock_map_zero_value_stock_included_with_zero_cap():
    data = make_full_tree({"Technology": {"Semiconductors": [("NVDA", "NVIDIA", 0)]}})
    result = parse_industry_stock_map(data)
    stock = result["industries"]["Semiconductors"]["stocks"][0]
    assert stock["ticker"] == "NVDA"
    assert stock["market_cap_m"] == 0
