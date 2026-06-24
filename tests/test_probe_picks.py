"""
Tests for probe_picks.py Phase-1 artifacts.

Covers:
  - slugify_industry (pure function)
  - finviz_industry_slugs.csv completeness vs snapshots.csv
  - screener_config.json structure and required fields
  - _parse_table (pure HTML parser)
  - _build_url (pure URL builder from config)
"""

import csv
import io
import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Import the module under test (Playwright is NOT imported at module level)
# ---------------------------------------------------------------------------
import importlib
import sys

# probe_picks imports playwright inside main() only — safe to import here.
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from probe_picks import (
    slugify_industry,
    _build_url,
    _parse_table,
    _dump_diagnostics,
    SCREENER_TABLE_SELECTOR,
    EXPECTED_COL_COUNT,
    EXPECTED_COL_0,
    GOLDEN_HEADER_PATH,
)

BASE_DIR = Path(__file__).parent.parent
SLUGS_PATH = BASE_DIR / "data" / "picks" / "finviz_industry_slugs.csv"
CONFIG_PATH = BASE_DIR / "data" / "picks" / "screener_config.json"
SNAPSHOTS_PATH = BASE_DIR / "data" / "industries" / "snapshots.csv"


# ---------------------------------------------------------------------------
# slugify_industry
# ---------------------------------------------------------------------------

class TestSlugifyIndustry:
    def test_alphanumeric_passthrough(self):
        assert slugify_industry("Semiconductors") == "semiconductors"

    def test_ampersand_removed(self):
        assert slugify_industry("Aerospace & Defense") == "aerospacedefense"

    def test_dash_removed(self):
        assert slugify_industry("Banks - Regional") == "banksregional"

    def test_spaces_removed(self):
        assert slugify_industry("Advertising Agencies") == "advertisingagencies"

    def test_slash_removed(self):
        assert slugify_industry("Software - Application") == "softwareapplication"

    def test_comma_removed(self):
        assert slugify_industry("Furnishings, Fixtures & Appliances") == "furnishingsfixturesappliances"

    def test_lowercase(self):
        assert slugify_industry("SEMICONDUCTORS") == "semiconductors"

    def test_empty_string(self):
        assert slugify_industry("") == ""

    def test_known_slugs(self):
        cases = {
            "Oil & Gas Integrated": "oilgasintegrated",
            "Drug Manufacturers - Specialty & Generic": "drugmanufacturersspecialtygeneric",
            "Beverages - Non-Alcoholic": "beveragesnonalcoholic",
        }
        for name, expected in cases.items():
            assert slugify_industry(name) == expected, f"Failed for {name!r}"


# ---------------------------------------------------------------------------
# finviz_industry_slugs.csv completeness
# ---------------------------------------------------------------------------

class TestSlugMap:
    def _load_slugs(self):
        return list(csv.DictReader(open(SLUGS_PATH)))

    def _load_snapshot_names(self):
        rows = list(csv.DictReader(open(SNAPSHOTS_PATH)))
        return {r["name"] for r in rows}

    def test_slug_file_exists(self):
        assert SLUGS_PATH.exists(), f"{SLUGS_PATH} does not exist"

    def test_slug_file_has_header(self):
        rows = self._load_slugs()
        assert len(rows) > 0
        assert "industry_name" in rows[0]
        assert "ind_slug" in rows[0]

    def test_every_snapshot_industry_has_slug(self):
        """Every industry in snapshots.csv must appear in finviz_industry_slugs.csv."""
        snap_names = self._load_snapshot_names()
        slug_names = {r["industry_name"] for r in self._load_slugs()}
        missing = snap_names - slug_names
        assert not missing, (
            f"{len(missing)} industries in snapshots.csv missing from slug map: "
            f"{sorted(missing)[:5]}..."
        )

    def test_144_industries(self):
        rows = self._load_slugs()
        assert len(rows) == 144, f"Expected 144 rows, got {len(rows)}"

    def test_slugs_match_slugify_function(self):
        """ind_slug in CSV must equal slugify_industry(industry_name)."""
        rows = self._load_slugs()
        mismatches = []
        for r in rows:
            expected = slugify_industry(r["industry_name"])
            if r["ind_slug"] != expected:
                mismatches.append((r["industry_name"], r["ind_slug"], expected))
        assert not mismatches, f"Slug mismatches: {mismatches[:3]}"

    def test_no_duplicate_industry_names(self):
        rows = self._load_slugs()
        names = [r["industry_name"] for r in rows]
        assert len(names) == len(set(names)), "Duplicate industry names in slug map"

    def test_no_duplicate_slugs(self):
        rows = self._load_slugs()
        slugs = [r["ind_slug"] for r in rows]
        assert len(slugs) == len(set(slugs)), "Duplicate ind_slugs in slug map (name collision after slugify)"


# ---------------------------------------------------------------------------
# screener_config.json structure
# ---------------------------------------------------------------------------

class TestScreenerConfig:
    def _load(self):
        return json.loads(CONFIG_PATH.read_text())

    def test_config_file_exists(self):
        assert CONFIG_PATH.exists(), f"{CONFIG_PATH} does not exist"

    def test_has_wide_and_button_blocks(self):
        cfg = self._load()
        assert "wide" in cfg
        assert "button" in cfg

    def test_wide_has_required_keys(self):
        wide = self._load()["wide"]
        for key in ("v", "base_filters", "sort", "ft", "columns"):
            assert key in wide, f"Missing key {key!r} in wide config"

    def test_wide_columns_have_id_and_label(self):
        wide = self._load()["wide"]
        for col in wide["columns"]:
            assert "id" in col, f"Column missing 'id': {col}"
            assert "label" in col, f"Column missing 'label': {col}"
            assert isinstance(col["id"], int), f"Column id not int: {col}"
            assert isinstance(col["label"], str) and col["label"], f"Column label empty: {col}"

    def test_wide_columns_count_matches_expected(self):
        wide = self._load()["wide"]
        assert len(wide["columns"]) == EXPECTED_COL_COUNT, (
            f"Config has {len(wide['columns'])} columns; EXPECTED_COL_COUNT == {EXPECTED_COL_COUNT}"
        )

    def test_first_column_is_ticker(self):
        wide = self._load()["wide"]
        assert wide["columns"][0]["label"] == EXPECTED_COL_0, (
            f"First column label is {wide['columns'][0]['label']!r}; expected {EXPECTED_COL_0!r}"
        )

    def test_no_duplicate_column_ids(self):
        wide = self._load()["wide"]
        ids = [c["id"] for c in wide["columns"]]
        assert len(ids) == len(set(ids)), "Duplicate column IDs in wide config"

    def test_no_duplicate_column_labels(self):
        wide = self._load()["wide"]
        labels = [c["label"] for c in wide["columns"]]
        assert len(labels) == len(set(labels)), "Duplicate column labels in wide config"

    def test_wide_base_filters_include_liquidity_floor(self):
        # sh_avgvol_o100 is the liquidity floor — must stay in the wide net (D11)
        wide = self._load()["wide"]
        assert "sh_avgvol_o100" in wide["base_filters"], (
            "Liquidity floor sh_avgvol_o100 missing from wide base_filters"
        )

    def test_button_has_required_keys(self):
        button = self._load()["button"]
        for key in ("v", "base_filters", "sort", "ft"):
            assert key in button, f"Missing key {key!r} in button config"


# ---------------------------------------------------------------------------
# _parse_table (pure HTML parser — no network)
# ---------------------------------------------------------------------------

SAMPLE_HTML = """
<html><body>
<table class="screener_table">
<tr><td>Ticker</td><td>Company</td><td>Price</td></tr>
<tr><td>NVDA</td><td>NVIDIA</td><td>142.50</td></tr>
<tr><td>AMD</td><td>Advanced Micro</td><td>165.20</td></tr>
</table>
</body></html>
"""

EMPTY_TABLE_HTML = """
<html><body>
<table class="screener_table">
<tr><td>Ticker</td><td>Company</td><td>Price</td></tr>
</table>
</body></html>
"""

NO_TABLE_HTML = "<html><body><p>No results</p></body></html>"


class TestParseTable:
    def test_parses_header_and_rows(self):
        headers, rows = _parse_table(SAMPLE_HTML)
        assert headers == ["Ticker", "Company", "Price"]
        assert len(rows) == 2
        assert rows[0]["Ticker"] == "NVDA"
        assert rows[1]["Price"] == "165.20"

    def test_returns_empty_on_no_table(self):
        headers, rows = _parse_table(NO_TABLE_HTML)
        assert headers == []
        assert rows == []

    def test_returns_empty_on_header_only_table(self):
        headers, rows = _parse_table(EMPTY_TABLE_HTML)
        assert headers == ["Ticker", "Company", "Price"]
        assert rows == []

    def test_returns_empty_on_empty_string(self):
        headers, rows = _parse_table("")
        assert headers == []
        assert rows == []


# ---------------------------------------------------------------------------
# _build_url (pure URL builder)
# ---------------------------------------------------------------------------

class TestBuildUrl:
    def _minimal_config(self):
        return {
            "wide": {
                "v": "151",
                "base_filters": ["cap_midover", "sh_avgvol_o100"],
                "sort": "-marketcap",
                "ft": "4",
                "columns": [{"id": 1, "label": "Ticker"}, {"id": 67, "label": "Price"}],
            }
        }

    def test_contains_ind_slug(self):
        url = _build_url(self._minimal_config(), "semiconductors", offset=1)
        assert "ind_semiconductors" in url

    def test_ind_slug_replaces_only_per_group_variable(self):
        url1 = _build_url(self._minimal_config(), "semiconductors", offset=1)
        url2 = _build_url(self._minimal_config(), "aerospacedefense", offset=1)
        assert "ind_semiconductors" in url1
        assert "ind_aerospacedefense" in url2
        # Everything except the slug is identical
        assert url1.replace("ind_semiconductors", "X") == url2.replace("ind_aerospacedefense", "X")

    def test_offset_in_url(self):
        url_p1 = _build_url(self._minimal_config(), "semiconductors", offset=1)
        url_p2 = _build_url(self._minimal_config(), "semiconductors", offset=21)
        assert "r=1" in url_p1 or "&r=1" in url_p1
        assert "r=21" in url_p2 or "&r=21" in url_p2

    def test_column_ids_in_url(self):
        url = _build_url(self._minimal_config(), "semiconductors", offset=1)
        assert "c=1,67" in url

    def test_base_filters_in_url(self):
        url = _build_url(self._minimal_config(), "semiconductors", offset=1)
        assert "cap_midover" in url
        assert "sh_avgvol_o100" in url

    def test_no_ind_slug_in_base_filters(self):
        # Ensures we're not baking the slug into the stored config
        config = json.loads(CONFIG_PATH.read_text())
        for f in config["wide"]["base_filters"]:
            assert not f.startswith("ind_"), f"ind_ slug found in base_filters: {f}"


# ---------------------------------------------------------------------------
# _dump_diagnostics (failure diagnostics — uses a fake page object)
# ---------------------------------------------------------------------------

class _FakePage:
    """Minimal stand-in for a Playwright page exposing .content()."""

    def __init__(self, html):
        self._html = html

    def content(self):
        return self._html


class TestDumpDiagnostics:
    def test_selector_constant_used_by_parser(self):
        # Guards against the parser and the wait selector drifting apart.
        assert SCREENER_TABLE_SELECTOR == "table.screener_table"

    def test_detects_cloudflare_marker(self, capsys):
        html = "<html><head><title>Just a moment...</title></head><body>Checking your browser</body></html>"
        _dump_diagnostics(_FakePage(html))
        out = capsys.readouterr().out.lower()
        assert "cloudflare challenge marker detected" in out

    def test_lists_table_classes(self, capsys):
        html = "<html><body><table class='foo bar'></table></body></html>"
        _dump_diagnostics(_FakePage(html))
        out = capsys.readouterr().out
        assert "foo.bar" in out

    def test_handles_no_tables(self, capsys):
        _dump_diagnostics(_FakePage("<html><body>nothing</body></html>"))
        out = capsys.readouterr().out
        assert "tables present (0)" in out
