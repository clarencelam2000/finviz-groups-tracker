"""Redesigned Finviz screener (2026-10): _parse_table falls back to SSR JSON.

Fixture is a trimmed real page captured from GitHub Actions on 2026-10-22
(Semiconductors, picks `wide` URL) — first 3 rows of data.rows only.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import probe_picks  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def parsed():
    return probe_picks._parse_table((FIX / "screener_ssr_redesign_2026-10.html").read_text())


def test_headers_match_legacy_84col_fixture(parsed):
    headers, _ = parsed
    legacy = [l for l in (FIX / "probe_header_84col.txt").read_text().splitlines() if l]
    assert headers == legacy


def test_values_rendered_in_legacy_display_format(parsed):
    _, rows = parsed
    assert [r["Ticker"] for r in rows] == ["NVDA", "TSM", "MU"]
    nvda = rows[0]
    assert nvda["Market Cap"] == "5114.26B"
    assert nvda["Volume"] == "125,409,020"
    assert nvda["Change"] == "-4.40%"
    assert nvda["Earnings"] == "Aug 26/a"
    assert nvda["Avg Volume"] == "117.71M"
    assert nvda["Income"] == "192.88B"
    assert nvda["ATR"] == "6.25"
    assert nvda["52W High"] == "-12.80%"
    assert nvda["Price"] == "212.21"
    assert nvda["Sector"] == "Technology"
    assert all(len(r) == 84 for r in rows)


@pytest.mark.parametrize("value,fmt,expected", [
    (None, "pct", "-"), ("", "text", "-"), (float("nan"), "f2", "-"),
    (187.9, "money", "187.90M"), (429770, "count", "429.77K"),
    ("2026-10-21T08:00:00", "earn", "Oct 21/b"), ("garbage", "earn", "-"),
    ("x", "f2", "-"),
])
def test_fmt_ssr_value_edges(value, fmt, expected):
    assert probe_picks._fmt_ssr_value(value, fmt) == expected


def test_no_table_and_no_ssr_json_returns_empty():
    assert probe_picks._parse_table("<html><body>Just a moment...</body></html>") == ([], [])


def test_ssr_json_with_zero_rows_returns_empty():
    html = ('<script type="application/json" data-ssr-props="x">'
            '{"data": {"rows": [], "totalCount": 0}}</script>')
    assert probe_picks._parse_table(html) == ([], [])


def test_legacy_table_still_preferred():
    html = ('<table class="screener_table"><tr><th>Ticker</th><th>Price</th></tr>'
            '<tr><td><a href="quote.ashx?t=ABC">ABC</a></td><td>1.00</td></tr></table>')
    headers, rows = probe_picks._parse_table(html)
    assert headers == ["Ticker", "Price"] and rows[0]["Price"] == "1.00"
