"""Tests for scripts/seed_taxonomy.py — parse_sector_industry_map and cross_validate."""

import csv
import json
import pytest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from seed_taxonomy import parse_sector_industry_map, cross_validate


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
