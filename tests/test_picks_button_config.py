"""
Anti-drift guard for Phase-3c deep-link button constants (B1/B2).

BUTTON_V, BUTTON_BASE_FILTERS, BUTTON_SORT, BUTTON_FT in docs/index.html
must stay in sync with the "button" block in data/picks/screener_config.json.
This test asserts they match so a future config change reddens CI until
index.html is also updated.

Also tests the 11 Finviz sector slugs used by the sec_<slug> deep-link button
(A3) and the Python-side slugify_group() helper.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _load_config() -> dict:
    return json.loads((ROOT / "data/picks/screener_config.json").read_text())


def _load_html() -> str:
    return (ROOT / "docs/index.html").read_text()


def _extract_constant(name: str, html: str) -> str:
    """Return the raw RHS of a JS `const NAME = <value>;` declaration."""
    pattern = rf"const\s+{re.escape(name)}\s*=\s*(.*?);"
    m = re.search(pattern, html, re.DOTALL)
    assert m, f"Constant {name!r} not found in docs/index.html"
    return m.group(1).strip()


def _parse_js_string(raw: str) -> str:
    """Parse a JS string literal like '311' or \"311\" → '311'."""
    m = re.match(r"""['"](.+)['"]""", raw.strip())
    return m.group(1) if m else raw.strip()


def _parse_js_array(raw: str) -> list:
    """Parse a JS string-array like ['a', 'b'] → ['a', 'b']."""
    return re.findall(r"""['"]([^'"]+)['"]""", raw)


class TestButtonConfigSync:
    """Every BUTTON_* constant in index.html must mirror screener_config.json 'button' block."""

    def setup_method(self):
        self.html = _load_html()
        self.cfg  = _load_config()["button"]

    def test_button_v_matches_config(self):
        raw = _extract_constant("BUTTON_V", self.html)
        assert _parse_js_string(raw) == self.cfg["v"]

    def test_button_base_filters_matches_config(self):
        raw = _extract_constant("BUTTON_BASE_FILTERS", self.html)
        assert _parse_js_array(raw) == self.cfg["base_filters"]

    def test_button_sort_matches_config(self):
        raw = _extract_constant("BUTTON_SORT", self.html)
        assert _parse_js_string(raw) == self.cfg["sort"]

    def test_button_ft_matches_config(self):
        raw = _extract_constant("BUTTON_FT", self.html)
        assert _parse_js_string(raw) == self.cfg["ft"]


# The 11 Finviz sector names and their expected slugs for sec_<slug> tokens.
# Slugify: name.lower() → strip all non-[a-z0-9].
SECTOR_SLUGS = [
    ("Basic Materials",        "basicmaterials"),
    ("Communication Services", "communicationservices"),
    ("Consumer Cyclical",      "consumercyclical"),
    ("Consumer Defensive",     "consumerdefensive"),
    ("Energy",                 "energy"),
    ("Financial",              "financial"),
    ("Healthcare",             "healthcare"),
    ("Industrials",            "industrials"),
    ("Real Estate",            "realestate"),
    ("Technology",             "technology"),
    ("Utilities",              "utilities"),
]


def _slugify(name: str) -> str:
    """Python mirror of JS slugifyGroup() in docs/index.html."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


class TestSectorSlugs:
    """sec_<slug> tokens for all 11 Finviz sectors must be stable and unique."""

    def test_all_11_sectors_present(self):
        assert len(SECTOR_SLUGS) == 11

    def test_slug_formula_matches_all_sectors(self):
        for name, expected in SECTOR_SLUGS:
            got = _slugify(name)
            assert got == expected, f"{name!r}: expected {expected!r}, got {got!r}"

    def test_no_duplicate_slugs(self):
        slugs = [_slugify(name) for name, _ in SECTOR_SLUGS]
        assert len(slugs) == len(set(slugs)), "Sector slugs are not unique"

    def test_slugify_industry_examples(self):
        """Spot-check industry slugs to confirm the formula also covers industries."""
        cases = [
            ("Semiconductors",          "semiconductors"),
            ("Aerospace & Defense",     "aerospacedefense"),
            ("Software - Application",  "softwareapplication"),
            ("Oil & Gas E&P",           "oilgasep"),
            ("Real Estate - General",   "realestategeneral"),
        ]
        for name, expected in cases:
            got = _slugify(name)
            assert got == expected, f"{name!r}: expected {expected!r}, got {got!r}"

    def test_sectors_match_snapshot_csv(self):
        """Every sector slug must correspond to a sector that appears in snapshots.csv."""
        import pandas as pd
        snap = pd.read_csv(ROOT / "data/sectors/snapshots.csv")
        known_sectors = set(snap["name"].dropna().unique())
        for name, _ in SECTOR_SLUGS:
            assert name in known_sectors, f"Sector {name!r} not in sectors/snapshots.csv"
