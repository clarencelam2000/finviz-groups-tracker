"""
Anti-drift guard for the Picks display methodology (planning/picks-methodology-tracking.md).

data/picks/display_methodology.json versions[0] ("current") records every constant
that drives the Picks/Focus display logic in docs/index.html at the time it was
authored. This test asserts each recorded numeric/string param still matches the
live JS constant, so a future constant change reddens CI until the JSON is updated.

Only `current` (versions[0]) is checked against live docs/index.html — older entries
are immutable historical snapshots (same philosophy as selector_versions.json) and are
expected to diverge from current code once superseded.

Known gap (documented in the current version's `known_gaps` block, tracked as
PICKS-METH-V2 resolution notes / a permanent structural note in .session/SPRINT.md):
the opt-in Phase 4 Ariel-match filter is intentionally NOT modeled here at all — it's
versioned separately in data/picks/ariel_match_config.json with no anti-drift guard
by design (see that file's `_readme`).
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
    """Parse a JS numeric literal like '4.0' or '0.4' or '30_000_000' -> float."""
    return float(raw.strip().replace("_", ""))


class TestDisplayMethodologyStructure:
    def setup_method(self):
        self.meth = _load_methodology()

    def test_current_matches_first_version(self):
        assert self.meth["current"] == self.meth["versions"][0]["version"]

    def test_versions_sorted_newest_first(self):
        dates = [v["effective_date"] for v in self.meth["versions"]]
        assert dates == sorted(dates, reverse=True)

    def test_current_is_v5_effective_2026_08_25(self):
        assert self.meth["versions"][0]["version"] == "v5"
        assert self.meth["versions"][0]["effective_date"] == "2026-08-25"

    def test_v4_still_present_with_original_effective_date(self):
        v4 = next(v for v in self.meth["versions"] if v["version"] == "v4")
        assert v4["effective_date"] == "2026-08-12"

    def test_v3_still_present_with_original_effective_date(self):
        v3 = next(v for v in self.meth["versions"] if v["version"] == "v3")
        assert v3["effective_date"] == "2026-07-16"

    def test_v2_still_present_with_original_effective_date(self):
        v2 = next(v for v in self.meth["versions"] if v["version"] == "v2")
        assert v2["effective_date"] == "2026-07-01"

    def test_v1_still_present_with_original_effective_date(self):
        v1 = next(v for v in self.meth["versions"] if v["version"] == "v1")
        assert v1["effective_date"] == "2026-06-25"


class TestDisplayMethodologySyncWithHtml:
    """Every `current` (versions[0], i.e. v2) param must mirror the live constant
    in docs/index.html. Older entries (v1) are frozen snapshots, not checked here."""

    def setup_method(self):
        self.html = _load_html()
        self.p = _load_methodology()["versions"][0]["params"]

    def test_base_filter_min_market_cap(self):
        raw = _extract_constant("MIN_MARKET_CAP_B", self.html)
        assert _parse_js_float(raw) == self.p["base_filter"]["min_market_cap_b"]

    def test_focus_dq_atr_max_matches_atr_ext_actionable(self):
        raw = _extract_constant("ATR_EXT_ACTIONABLE", self.html)
        assert _parse_js_float(raw) == self.p["focus_dq"]["atr"]["max_inclusive"]

    def test_focus_dq_liquidity_min_matches_focus_min_dollar_vol(self):
        raw = _extract_constant("FOCUS_MIN_DOLLAR_VOL", self.html)
        assert _parse_js_float(raw) == self.p["focus_dq"]["liquidity"]["min_inclusive"]

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

    def test_liquidity_penalty_ramp_start_and_floor(self):
        lp = self.p["focus_score"]["liquidity_penalty"]
        assert _parse_js_float(_extract_constant("LIQUIDITY_PENALTY_START", self.html)) == lp["ramp_start"]
        assert _parse_js_float(_extract_constant("FOCUS_MIN_DOLLAR_VOL", self.html)) == lp["floor"]

    def test_liquidity_penalty_max_fraction(self):
        raw = _extract_constant("LIQUIDITY_PENALTY_MAX", self.html)
        lp = self.p["focus_score"]["liquidity_penalty"]
        assert _parse_js_float(raw) == lp["max_fraction"]

    def test_earnings_penalty_day_thresholds(self):
        ep = self.p["focus_score"]["earnings_penalty"]
        assert _parse_js_float(_extract_constant("EARNINGS_CAUTION_DAYS", self.html)) == ep["caution_days"]
        assert _parse_js_float(_extract_constant("EARNINGS_IMMINENT_DAYS", self.html)) == ep["imminent_days"]

    def test_earnings_penalty_max_fraction_and_carryover(self):
        ep = self.p["focus_score"]["earnings_penalty"]
        assert _parse_js_float(_extract_constant("EARNINGS_PENALTY_MAX", self.html)) == ep["max_fraction"]
        assert (
            _parse_js_float(_extract_constant("POST_EARNINGS_PENALTY_FRAC", self.html))
            == ep["post_earnings_carryover_fraction"]
        )
        assert ep["post_earnings_carryover_days"] == 1  # the JS hardcodes daysUntil === -1

    def test_overhead_penalty_ramp_start(self):
        raw = _extract_constant("OVERHEAD_PENALTY_START", self.html)
        op = self.p["focus_score"]["overhead_penalty"]
        assert _parse_js_float(raw) == op["ramp_start"]

    def test_overhead_penalty_ramp_end(self):
        raw = _extract_constant("OVERHEAD_PENALTY_END", self.html)
        op = self.p["focus_score"]["overhead_penalty"]
        assert _parse_js_float(raw) == op["ramp_end"]

    def test_overhead_penalty_max_fraction(self):
        raw = _extract_constant("OVERHEAD_PENALTY_MAX", self.html)
        op = self.p["focus_score"]["overhead_penalty"]
        assert _parse_js_float(raw) == op["max_fraction"]

    def test_all_view_category_order(self):
        m = re.search(
            r"CAT_ORDER\s*=\s*\[(.*?)\]", self.html, re.DOTALL
        )
        assert m, "CAT_ORDER not found in docs/index.html"
        cats = re.findall(r"""['"]([^'"]+)['"]""", m.group(1))
        assert cats == self.p["all_view_sort"]["category_order"]
