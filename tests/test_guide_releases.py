"""
Static integrity tests for the Guide + What's New feature (no browser needed).

Covers plan §7.4 (anti-drift) and §7.5 (release/cache coupling):
- Every metric id referenced by a "why this matters" link exists in the GUIDE
  constant, and every GUIDE metric has non-empty copy.
- docs/releases.json parses and `current` equals the newest entry's version.
- Every GUIDE metric one-liner is present verbatim somewhere in
  knowledge/moaty-metrics.md (the canonical source of the wording).

The Playwright UI assertions (hub opens, dot clears, deep-link scroll) live in
tests/test_functional_playwright.py and run only when Playwright is installed.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "docs" / "index.html"
RELEASES = ROOT / "docs" / "releases.json"
METRICS_MD = ROOT / "knowledge" / "moaty-metrics.md"

VALID_TAGS = {"feature", "fix", "data", "improvement"}


def _index_html():
    return INDEX.read_text(encoding="utf-8")


def _guide_metric_ids():
    """Parse the `id` fields of the GUIDE.metrics array from index.html."""
    html = _index_html()
    start = html.index("const GUIDE = {")
    metrics_block = html[start:html.index("howto:", start)]
    return re.findall(r"\{\s*id:\s*'([^']+)'", metrics_block)


def _guide_one_liners():
    html = _index_html()
    start = html.index("const GUIDE = {")
    block = html[start:html.index("howto:", start)]
    # oneLiner may use ' or " quoting (some contain apostrophes)
    return re.findall(r"oneLiner:\s*(?:'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\")", block)


def test_why_links_target_existing_guide_ids():
    html = _index_html()
    linked = set(re.findall(r"__openHub\('guide','([^']+)'\)", html))
    assert linked, "expected at least one contextual 'why this matters' link"
    guide_ids = set(_guide_metric_ids())
    missing = linked - guide_ids
    assert not missing, f"why-link metric ids absent from GUIDE: {missing}"


def test_every_guide_metric_has_copy():
    html = _index_html()
    start = html.index("const GUIDE = {")
    block = html[start:html.index("howto:", start)]
    entries = re.findall(
        r"\{\s*id:\s*'([^']+)',\s*label:\s*'([^']+)',\s*oneLiner:",
        block,
    )
    ids = _guide_metric_ids()
    assert len(entries) == len(ids), "every GUIDE metric needs id + label + oneLiner"
    for mid, label in entries:
        assert label.strip(), f"GUIDE metric {mid} has empty label"
    for grp, (mid, _) in zip(_guide_one_liners(), entries):
        text = next((g for g in grp if g), "")
        assert text.strip(), f"GUIDE metric {mid} has empty oneLiner"


def test_releases_json_valid_and_current_matches_newest():
    data = json.loads(RELEASES.read_text(encoding="utf-8"))
    assert "current" in data and "releases" in data
    assert isinstance(data["releases"], list) and data["releases"]
    assert data["current"] == data["releases"][0]["version"], (
        "releases.current must equal releases[0].version (newest-first)"
    )
    seen_versions = set()
    for r in data["releases"]:
        for field in ("version", "date", "title", "tag", "notes"):
            assert field in r, f"release {r.get('version')} missing {field}"
        assert re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", r["version"]), (
            f"version {r['version']} must be YYYY.MM.DD"
        )
        assert r["tag"] in VALID_TAGS, f"unknown tag {r['tag']}"
        assert r["notes"], "release notes must be non-empty"
        assert r["version"] not in seen_versions, "duplicate version"
        seen_versions.add(r["version"])


def test_guide_one_liners_match_metrics_md():
    """The GUIDE copy must be lifted verbatim from moaty-metrics.md."""
    md = METRICS_MD.read_text(encoding="utf-8")
    # normalize whitespace (the md wraps one-liners across lines)
    md_norm = re.sub(r"\s+", " ", md)
    for grp in _guide_one_liners():
        text = next(g for g in grp if g)
        text = text.replace("\\'", "'").replace('\\"', '"')
        assert text in md_norm, f"GUIDE one-liner not found verbatim in moaty-metrics.md: {text!r}"
