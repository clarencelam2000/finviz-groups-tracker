"""Tests for scripts/collect_held.py — WS5 phase 2 held-tickers feed.

Pure-function tests only: build_quote_payload has no I/O and no network. This file does
NOT import playwright at module scope for its own sake — collect_held imports
`playwright.sync_api` lazily inside main() only (mirrors collect_morning.py). It does
import `collect_held`, which imports `collect` (module-scope `import playwright.sync_api`,
a plain import with no browser launch — same as test_collect_morning.py) and
`collect_morning` (same lazy-import pattern) — neither launches a browser or touches
network, so this file stays OFF the tests.yml Playwright-ignore list.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import collect_held as ch  # noqa: E402


def _row(ticker="AAPL", **overrides):
    row = {
        "Ticker": ticker,
        "Company": "Apple Inc",
        "Prev Close": "150.00",
        "Open": "151.00",
        "High": "152.50",
        "Low": "149.75",
        "Price": "152.00",
        "Change": "1.33%",
        "ATR": "3.45",
        "Volume": "50,123,456",
        "Earnings": "Oct 30 AMC",
    }
    row.update(overrides)
    return row


def test_build_quote_payload_maps_fields_correctly():
    payload = ch.build_quote_payload([_row()], "2026-08-13", "2026-08-13T21:05:00Z")
    assert payload["trade_date"] == "2026-08-13"
    assert payload["collected_at"] == "2026-08-13T21:05:00Z"
    assert len(payload["quotes"]) == 1

    q = payload["quotes"][0]
    assert q["ticker"] == "AAPL"
    assert q["prev_close"] == 150.00
    assert q["open"] == 151.00
    assert q["high"] == 152.50
    assert q["low"] == 149.75
    assert q["close"] == 152.00
    assert q["change_pct"] == 1.33
    assert q["atr"] == 3.45
    assert q["volume"] == 50123456.0
    assert q["days_to_earnings"] is None


def test_raw_contains_all_original_keys_verbatim():
    row = _row()
    payload = ch.build_quote_payload([row], "2026-08-13", "2026-08-13T21:05:00Z")
    raw = payload["quotes"][0]["raw"]
    assert raw == row
    # Every scraped label survives, not just the ones pulled into typed fields (#297).
    assert set(row.keys()) <= set(raw.keys())
    assert raw["Company"] == "Apple Inc"
    assert raw["Earnings"] == "Oct 30 AMC"


def test_unparseable_or_blank_numerics_become_none():
    row = _row(**{"Prev Close": "-", "ATR": "", "Volume": "n/a"})
    payload = ch.build_quote_payload([row], "2026-08-13", "2026-08-13T21:05:00Z")
    q = payload["quotes"][0]
    assert q["prev_close"] is None
    assert q["atr"] is None
    assert q["volume"] is None


def test_row_missing_ticker_is_skipped():
    rows = [_row(ticker=""), _row(ticker="MSFT")]
    payload = ch.build_quote_payload(rows, "2026-08-13", "2026-08-13T21:05:00Z")
    assert [q["ticker"] for q in payload["quotes"]] == ["MSFT"]


def test_row_with_missing_ticker_key_is_skipped():
    row = _row()
    del row["Ticker"]
    payload = ch.build_quote_payload([row], "2026-08-13", "2026-08-13T21:05:00Z")
    assert payload["quotes"] == []


def test_empty_input_returns_empty_quotes_list():
    payload = ch.build_quote_payload([], "2026-08-13", "2026-08-13T21:05:00Z")
    assert payload == {
        "trade_date": "2026-08-13",
        "collected_at": "2026-08-13T21:05:00Z",
        "quotes": [],
    }


def test_payload_shape_matches_worker_expectation():
    payload = ch.build_quote_payload([_row(), _row(ticker="MSFT")], "2026-08-13", "2026-08-13T21:05:00Z")
    assert isinstance(payload["quotes"], list)
    for q in payload["quotes"]:
        assert isinstance(q["ticker"], str) and q["ticker"]
        assert isinstance(q["raw"], dict)
        for field in ("prev_close", "open", "high", "low", "close", "change_pct", "atr", "volume"):
            assert field in q
