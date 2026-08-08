"""
Static integrity tests for the "Start Here" onboarding intro.

Covers plan §4 (anti-drift) and §5 (verification):
- Every `tab` id in WELCOME items is a real tab id so a renamed tab can't
  silently break the tour.
- Every non-empty `body` and `desc` string in WELCOME appears verbatim in
  knowledge/product-intro-copy.md (the canonical copy source). Mirrors the
  moaty-metrics.md ↔ GUIDE sync test in test_guide_releases.py.

Playwright behavioral tests (first-run auto-open, skip/dismiss, replay,
hub Start Here section) live in tests/test_functional_playwright.py inside
TestPWAIntro and require Playwright + Chromium to be installed.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "docs" / "index.html"
RELEASES = ROOT / "docs" / "releases.json"
PRODUCT_INTRO_COPY = ROOT / "knowledge" / "product-intro-copy.md"

# Must match the data-tab values on the PWA tab bar (#tab-bar in index.html).
VALID_TAB_IDS = {"today", "movers", "momentum", "strength", "vsmarket", "ai", "lookup", "picks", "morning"}


def _welcome_block():
    """Return the JS source between `const WELCOME = [` and its closing `];`."""
    html = INDEX.read_text(encoding="utf-8")
    start = html.index("const WELCOME = [")
    # Find the matching ]; — first occurrence after start that closes the array
    end = html.index("];", start)
    return html[start : end + 2]


def _welcome_tab_ids():
    """Return all tab: 'xxx' values inside the WELCOME items arrays."""
    block = _welcome_block()
    return re.findall(r"tab:\s*'([^']+)'", block)


def _welcome_text_strings(field):
    """Return all `field: '...'` or `field: "..."` values from WELCOME."""
    block = _welcome_block()
    pattern = rf"{re.escape(field)}:\s*(?:'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*?)\")"
    pairs = re.findall(pattern, block)
    result = []
    for grp in pairs:
        text = next((g for g in grp if g is not None), "")
        result.append(text)
    return result


def test_welcome_tab_ids_are_valid():
    """Every tab field in WELCOME items must be one of the real tab ids.
    A renamed or removed tab would otherwise silently break the tour deep-links."""
    ids = _welcome_tab_ids()
    assert ids, "expected at least one tab id in WELCOME items"
    assert len(ids) == 8, f"expected exactly 8 tab ids in the tour, got {ids}"
    bad = set(ids) - VALID_TAB_IDS
    assert not bad, f"WELCOME items contain unknown tab ids: {bad}"


def test_intro_release_entry_valid():
    """The Start Here intro release entry exists in releases.json with required fields."""
    data = json.loads(RELEASES.read_text(encoding="utf-8"))
    releases = data.get("releases", [])
    # The intro release must exist somewhere in the list (newest entry at index 0).
    intro = next(
        (r for r in releases if "Start Here" in r.get("title", "")),
        None,
    )
    assert intro is not None, (
        "No 'Start Here' release entry found in releases.json. "
        "Add one when shipping the intro feature (see CLAUDE.md § Cutting a release)."
    )
    for field in ("version", "date", "title", "tag", "notes"):
        assert field in intro, f"Start Here release entry missing field: {field}"
    assert intro["tag"] in {"feature", "fix", "data", "improvement"}, (
        f"Unexpected tag value: {intro['tag']}"
    )
    assert intro["notes"], "Start Here release entry must have non-empty notes"


def test_welcome_body_strings_in_product_intro_copy():
    """Each non-empty body and desc string in WELCOME must appear verbatim in
    knowledge/product-intro-copy.md, the canonical copy source.

    Mirrors test_guide_one_liners_match_metrics_md — same sync discipline."""
    assert PRODUCT_INTRO_COPY.exists(), (
        "knowledge/product-intro-copy.md not found — create it alongside WELCOME"
    )
    md = PRODUCT_INTRO_COPY.read_text(encoding="utf-8")
    md_norm = re.sub(r"\s+", " ", md)

    bodies = _welcome_text_strings("body")
    descs = _welcome_text_strings("desc")

    assert bodies, "expected at least one body string in WELCOME"
    assert descs, "expected at least one desc string in WELCOME"

    non_empty_bodies = [b for b in bodies if b.strip()]
    assert non_empty_bodies, "expected at least one non-empty body string"

    for text in non_empty_bodies:
        text = text.replace("\\'", "'").replace('\\"', '"')
        assert text in md_norm, (
            f"WELCOME body not found verbatim in product-intro-copy.md: {text!r}"
        )

    for text in descs:
        if not text.strip():
            continue
        text = text.replace("\\'", "'").replace('\\"', '"')
        assert text in md_norm, (
            f"WELCOME desc not found verbatim in product-intro-copy.md: {text!r}"
        )
