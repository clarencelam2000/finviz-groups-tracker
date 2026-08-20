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


def test_authed_request_sets_non_generic_user_agent(monkeypatch):
    # Cloudflare's Bot Fight Mode 403s the default "Python-urllib/x.y" User-Agent on
    # workers.dev zones before the request reaches the Worker's own auth code (verified
    # live 2026-08-13) — regression guard for that outage.
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["req"] = req
        return None

    monkeypatch.setattr(ch.urllib.request, "urlopen", fake_urlopen)
    ch._authed_request("https://example.com/held-tickers", "tok")

    ua = captured["req"].get_header("User-agent")
    assert ua is not None
    assert "python-urllib" not in ua.lower()
    assert "python-requests" not in ua.lower()


def test_trigger_advance_returns_counts_on_200(monkeypatch):
    import io
    import json as jsonlib

    captured = {}
    body = jsonlib.dumps(
        {"dry_run": False, "positions": 3, "advanced": 3, "signalled": 1, "unchanged": 0, "stale": 0}
    ).encode("utf-8")

    class FakeResp(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        captured["req"] = req
        return FakeResp(body)

    monkeypatch.setattr(ch.urllib.request, "urlopen", fake_urlopen)
    result = ch.trigger_advance("https://example.com", "tok")

    assert result == {
        "dry_run": False, "positions": 3, "advanced": 3, "signalled": 1, "unchanged": 0, "stale": 0,
    }
    req = captured["req"]
    assert req.full_url == "https://example.com/advance"
    assert req.get_method() == "POST"
    assert req.get_header("Authorization") == "Bearer tok"
    ua = req.get_header("User-agent")
    assert ua is not None
    assert "python-urllib" not in ua.lower()
    assert "python-requests" not in ua.lower()


def test_trigger_advance_returns_none_on_http_error(monkeypatch):
    import io

    def fake_urlopen(req, timeout=None):
        raise ch.urllib.error.HTTPError(
            req.full_url, 500, "Internal Server Error", hdrs=None, fp=io.BytesIO(b"boom")
        )

    monkeypatch.setattr(ch.urllib.request, "urlopen", fake_urlopen)
    result = ch.trigger_advance("https://example.com", "tok")
    assert result is None


def test_trigger_advance_returns_none_on_generic_exception(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise ConnectionError("network is unreachable")

    monkeypatch.setattr(ch.urllib.request, "urlopen", fake_urlopen)
    result = ch.trigger_advance("https://example.com", "tok")
    assert result is None


def test_post_quotes_advisory_path_posts_to_preclose_advisory_endpoint(monkeypatch):
    # WS5-8: --advisory routes post_quotes() at the /positions/preclose-advisory endpoint
    # instead of /ingest/quotes, via the optional `path=` param.
    import io
    import json as jsonlib

    captured = {}
    body = jsonlib.dumps({"written": 2}).encode("utf-8")

    class FakeResp(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        captured["req"] = req
        return FakeResp(body)

    monkeypatch.setattr(ch.urllib.request, "urlopen", fake_urlopen)
    payload = {"trade_date": "2026-08-20", "collected_at": "2026-08-20T19:40:00Z", "quotes": []}
    written = ch.post_quotes("https://example.com", "tok", payload, path=ch.PRECLOSE_ADVISORY_PATH)

    assert written == 2
    req = captured["req"]
    assert req.full_url == "https://example.com/positions/preclose-advisory"
    assert req.get_method() == "POST"


def test_post_quotes_default_path_is_ingest_quotes(monkeypatch):
    # Regression guard: the default (non-advisory) call must still hit /ingest/quotes.
    import io
    import json as jsonlib

    captured = {}
    body = jsonlib.dumps({"written": 1}).encode("utf-8")

    class FakeResp(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        captured["req"] = req
        return FakeResp(body)

    monkeypatch.setattr(ch.urllib.request, "urlopen", fake_urlopen)
    payload = {"trade_date": "2026-08-20", "collected_at": "2026-08-20T19:40:00Z", "quotes": []}
    ch.post_quotes("https://example.com", "tok", payload)

    assert captured["req"].full_url == "https://example.com/ingest/quotes"


def test_main_advisory_mode_skips_advance_and_posts_advisory_path(monkeypatch, capsys):
    # WS5-8 HARD INVARIANT: --advisory must POST to /positions/preclose-advisory and
    # must NOT call trigger_advance (no /advance, no sweep).
    import sys as sys_mod

    monkeypatch.setattr(ch, "fetch_held_tickers", lambda worker_url, token: ["AAPL"])

    def fake_fetch_ticker_quotes(page, tickers, config, block=None):
        return [_row(ticker="AAPL")]

    monkeypatch.setattr(ch, "fetch_ticker_quotes", fake_fetch_ticker_quotes)

    posted = {}

    def fake_post_quotes(worker_url, token, payload, path=ch.INGEST_QUOTES_PATH):
        posted["path"] = path
        return 1

    monkeypatch.setattr(ch, "post_quotes", fake_post_quotes)

    def fail_trigger_advance(*args, **kwargs):
        raise AssertionError("trigger_advance must not be called in --advisory mode")

    monkeypatch.setattr(ch, "trigger_advance", fail_trigger_advance)

    class FakeBrowser:
        def close(self):
            pass

    class FakeContext:
        def new_page(self):
            return object()

    class FakePlaywright:
        def __enter__(self):
            class Chromium:
                def launch(self, headless=True):
                    return FakeBrowser()

            class P:
                chromium = Chromium()

            return P()

        def __exit__(self, *a):
            return False

    class FakeBrowserWithContext(FakeBrowser):
        def new_context(self, **kwargs):
            return FakeContext()

    class ChromiumLaunch:
        def launch(self, headless=True):
            return FakeBrowserWithContext()

    class PlaywrightP:
        chromium = ChromiumLaunch()

    class FakeSyncPlaywright:
        def __enter__(self):
            return PlaywrightP()

        def __exit__(self, *a):
            return False

    import types
    fake_module = types.SimpleNamespace(sync_playwright=lambda: FakeSyncPlaywright())
    monkeypatch.setitem(sys_mod.modules, "playwright.sync_api", fake_module)

    monkeypatch.setenv("POSITIONS_WORKER_URL", "https://example.com")
    monkeypatch.setenv("POSITIONS_INGEST_TOKEN", "tok")
    monkeypatch.setattr(sys_mod, "argv", ["collect_held.py", "--advisory"])

    ch.main()

    assert posted["path"] == ch.PRECLOSE_ADVISORY_PATH
    out = capsys.readouterr().out
    assert "advisory" in out.lower()


def test_payload_shape_matches_worker_expectation():
    payload = ch.build_quote_payload([_row(), _row(ticker="MSFT")], "2026-08-13", "2026-08-13T21:05:00Z")
    assert isinstance(payload["quotes"], list)
    for q in payload["quotes"]:
        assert isinstance(q["ticker"], str) and q["ticker"]
        assert isinstance(q["raw"], dict)
        for field in ("prev_close", "open", "high", "low", "close", "change_pct", "atr", "volume"):
            assert field in q
