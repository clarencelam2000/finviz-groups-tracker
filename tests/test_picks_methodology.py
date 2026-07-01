"""
Anti-drift guard for the Picks display methodology (planning/picks-methodology-tracking.md).

data/picks/display_methodology.json versions[0] ("current") records every constant
that drives the Picks/Focus display logic in docs/index.html at the time it was
authored. This test asserts each recorded numeric/string param still matches the
live JS constant, so a future constant change reddens CI until the JSON is updated.

Known gap (documented in the JSON's `known_gaps` block, tracked as PICKS-METH-V2 in
.session/SPRINT.md): v1 only covers the original Phase 3b formula. It intentionally
does not model the Phase 3d liquidity/earnings penalties or the Phase 4 Ariel-match
filter — those are out of scope until a v2 entry is authored.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _load_methodology() -> dict:
    return json.loads((ROOT / "data/picks/display_methodology.json").read_text())


def _load_html() -> str:
    return (ROOT / "docs/index.html").read_text()


def _extract_constant(name: str, html: str) -> str:
    """Return the raw RHS of a JS `const NAME = <value>;` declaration."""
    pattern = rf"const\s+{re.escape(name)}\s*=\s*(.*?);"
    m = re.search(pattern, html, re.DOTALL)
    assert m, f"Constant {name!r} not found in docs/index.html"
    return m.group(1).strip()


def _parse_js_float(raw: str) -> float:
    """Parse a JS numeric literal like '4.0' or '0.4' -> float."""
    return float(raw.strip())


class TestDisplayMethodologyStructure:
    def setup_method(self):
        self.meth = _load_methodology()

    def test_current_matches_first_version(self):
        assert self.meth["current"] == self.meth["versions"][0]["version"]

    def test_versions_sorted_newest_first(self):
        dates = [v["effective_date"] for v in self.meth["versions"]]
        assert dates == sorted(dates, reverse=True)

    def test_v1_effective_date(self):
        assert self.meth["versions"][0]["effective_date"] == "2026-06-25"


class TestDisplayMethodologySyncWithHtml:
    """Every v1 param must mirror the live constant in docs/index.html."""

    def setup_method(self):
        self.html = _load_html()
        self.p = _load_methodology()["versions"][0]["params"]

    def test_base_filter_min_market_cap(self):
        raw = _extract_constant("MIN_MARKET_CAP_B", self.html)
        assert _parse_js_float(raw) == self.p["base_filter"]["min_market_cap_b"]

    def test_focus_dq_max_matches_atr_ext_actionable(self):
        raw = _extract_constant("ATR_EXT_ACTIONABLE", self.html)
        assert _parse_js_float(raw) == self.p["focus_dq"]["max_inclusive"]

    def test_atr_bands_emerald_max_matches_atr_ext_actionable(self):
        raw = _extract_constant("ATR_EXT_ACTIONABLE", self.html)
        assert _parse_js_float(raw) == self.p["atr_bands"]["emerald_max"]

    def test_atr_bands_amber_max_matches_atr_ext_trim(self):
        raw = _extract_constant("ATR_EXT_TRIM", self.html)
        assert _parse_js_float(raw) == self.p["atr_bands"]["amber_max"]

    def test_focus_score_weights(self):
        weights = self.p["focus_score"]["weights"]
        assert _parse_js_float(_extract_constant("FOCUS_W_GROUP", self.html)) == weights["group"]
        assert _parse_js_float(_extract_constant("FOCUS_W_TIGHT", self.html)) == weights["tight"]
        assert _parse_js_float(_extract_constant("FOCUS_W_QUIET", self.html)) == weights["quiet"]

    def test_focus_score_weights_sum_to_one(self):
        weights = self.p["focus_score"]["weights"]
        assert weights["group"] + weights["tight"] + weights["quiet"] == 1.0

    def test_normalization_fallback_threshold(self):
        raw = _extract_constant("FOCUS_MIN_POOL", self.html)
        norm = self.p["focus_score"]["normalization"]
        assert _parse_js_float(raw) == norm["fallback_threshold"]

    def test_extension_penalty_ramp_start(self):
        raw = _extract_constant("ATR_EXT_PENALTY_START", self.html)
        ep = self.p["focus_score"]["extension_penalty"]
        assert _parse_js_float(raw) == ep["ramp_start"]

    def test_extension_penalty_ramp_end_matches_atr_ext_actionable(self):
        raw = _extract_constant("ATR_EXT_ACTIONABLE", self.html)
        ep = self.p["focus_score"]["extension_penalty"]
        assert _parse_js_float(raw) == ep["ramp_end"]

    def test_extension_penalty_max_fraction(self):
        raw = _extract_constant("PENALTY_MAX", self.html)
        ep = self.p["focus_score"]["extension_penalty"]
        assert _parse_js_float(raw) == ep["max_fraction"]

    def test_all_view_category_order(self):
        m = re.search(
            r"CAT_ORDER\s*=\s*\[(.*?)\]", self.html, re.DOTALL
        )
        assert m, "CAT_ORDER not found in docs/index.html"
        cats = re.findall(r"""['"]([^'"]+)['"]""", m.group(1))
        assert cats == self.p["all_view_sort"]["category_order"]
