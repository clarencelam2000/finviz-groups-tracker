"""Tests for scripts/collect_morning.py — ADR-013 Phase A.

Does NOT import playwright at module scope (collect_morning imports
`playwright.sync_api` only lazily inside main(); the `collect` module it imports
for NYSE_HOLIDAYS does import `playwright.sync_api` at module scope too, but that
is a plain import — no browser launch — so this file stays off the
tests.yml Playwright-ignore list; it never launches a browser or touches network).
"""

import csv
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import collect_morning as cm  # noqa: E402
import session_config  # noqa: E402

MORNING_CONFIG = {
    "morning": {
        "v": "151",
        "base_filters": [],
        "sort": "",
        "ft": "4",
        "columns": [
            {"id": 1, "label": "Ticker"},
            {"id": 81, "label": "Prev Close"},
            {"id": 86, "label": "Open"},
            {"id": 87, "label": "High"},
            {"id": 88, "label": "Low"},
            {"id": 65, "label": "Price"},
            {"id": 66, "label": "Change"},
            {"id": 49, "label": "ATR"},
            {"id": 67, "label": "Volume"},
        ],
    }
}


# ---------------------------------------------------------------------------
# build_ticker_url
# ---------------------------------------------------------------------------


def test_build_ticker_url_basic():
    url = cm.build_ticker_url(MORNING_CONFIG, ["AAPL", "MSFT"], offset=1)
    assert "t=AAPL,MSFT" in url
    assert "&f=" not in url  # base_filters empty
    assert "c=1,81,86,87,88,65,66,49,67" in url
    assert "r=1" in url
    assert "v=151" in url
    assert "ft=4" in url


def test_build_ticker_url_offset():
    url = cm.build_ticker_url(MORNING_CONFIG, ["AAPL"], offset=21)
    assert "r=21" in url


def test_build_ticker_url_with_filters():
    config = {"morning": dict(MORNING_CONFIG["morning"], base_filters=["cap_midover"])}
    url = cm.build_ticker_url(config, ["AAPL"], offset=1)
    assert "&f=cap_midover" in url


# ---------------------------------------------------------------------------
# fetch_ticker_quotes batching, via a fake page
# ---------------------------------------------------------------------------


class _FakePage:
    """Stub Playwright Page: records URLs, returns fixture HTML rows via a
    caller-supplied function so _parse_table's real parsing logic still runs."""

    def __init__(self, rows_for_ticker):
        self.urls = []
        self._rows_for_ticker = rows_for_ticker
        self._last_html = ""

    def goto(self, url, wait_until=None, timeout=None):
        self.urls.append(url)
        # Extract the ticker list from the URL's t= param, honoring r= paging by
        # only returning rows for tickers not already "paged past" — simplified:
        # each batch's single page holds all its tickers (< PAGE_SIZE), so no
        # multi-page walk is needed for this fixture.
        import urllib.parse
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        tickers = qs.get("t", [""])[0].split(",")
        offset = int(qs.get("r", ["1"])[0])
        if offset > 1:
            self._last_html = _table_html([])
            return
        self._last_html = _table_html([self._rows_for_ticker[t] for t in tickers if t in self._rows_for_ticker])

    def wait_for_selector(self, selector, timeout=None):
        pass

    def content(self):
        return self._last_html


def _table_html(rows: list) -> str:
    header = "<tr><th>Ticker</th><th>Prev Close</th><th>Open</th><th>High</th><th>Low</th>" \
             "<th>Price</th><th>Change</th><th>ATR</th><th>Volume</th></tr>"
    body = ""
    for r in rows:
        body += (
            "<tr><td><a href='quote.ashx?t={t}'>{t}</a></td>"
            "<td>{pc}</td><td>{o}</td><td>{h}</td><td>{l}</td>"
            "<td>{p}</td><td>{c}</td><td>{atr}</td><td>{v}</td></tr>"
        ).format(**r)
    return f"<table class='screener_table'>{header}{body}</table>"


def test_fetch_ticker_quotes_batches_at_50():
    tickers = [f"T{i}" for i in range(120)]
    rows_for_ticker = {
        t: {"t": t, "pc": "1", "o": "1", "h": "1", "l": "1", "p": "1", "c": "0%", "atr": "1", "v": "1"}
        for t in tickers
    }
    page = _FakePage(rows_for_ticker)
    quotes = cm.fetch_ticker_quotes(page, tickers, MORNING_CONFIG)

    # 120 tickers / 50-per-batch => 3 batches, each issuing >=1 goto (page 1 + a
    # follow-up empty page since rows < PAGE_SIZE never triggers — here each
    # batch returns len(batch) rows in one page, which is >= PAGE_SIZE(20) for
    # the two full batches, so pagination continues until an empty page).
    assert len(quotes) == 120
    # Every URL's t= list must be <= MORNING_BATCH_SIZE tickers.
    import urllib.parse
    for url in page.urls:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        t_count = len(qs.get("t", [""])[0].split(","))
        assert t_count <= cm.MORNING_BATCH_SIZE
    # At least 3 distinct batches were issued (3 different t= lists).
    t_lists = {urllib.parse.parse_qs(urllib.parse.urlparse(u).query)["t"][0] for u in page.urls}
    assert len(t_lists) == 3


class _RaisingPage(_FakePage):
    """_FakePage whose wait_for_selector raises for any batch whose t= list contains
    `raise_on_ticker` — simulates a Cloudflare/timeout stall on one batch."""

    def __init__(self, rows_for_ticker, raise_on_ticker):
        super().__init__(rows_for_ticker)
        self._raise_on = raise_on_ticker

    def wait_for_selector(self, selector, timeout=None):
        if not self.urls:
            return
        import urllib.parse
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.urls[-1]).query)
        if self._raise_on in qs.get("t", [""])[0].split(","):
            raise TimeoutError("simulated wait_for_selector timeout")


def test_fetch_ticker_quotes_survives_wait_for_selector_timeout():
    # A timeout on one batch must NOT propagate and abort the run — later batches'
    # names must still be fetched ("no names lost"). Pre-fix this raised.
    tickers = [f"T{i}" for i in range(60)]  # 2 batches at MORNING_BATCH_SIZE=50: [50,10]
    rows_for_ticker = {
        t: {"t": t, "pc": "1", "o": "1", "h": "1", "l": "1", "p": "1", "c": "0%", "atr": "1", "v": "1"}
        for t in tickers
    }
    # T0 lives in the first batch; make that batch's wait_for_selector raise.
    page = _RaisingPage(rows_for_ticker, raise_on_ticker="T0")
    quotes = cm.fetch_ticker_quotes(page, tickers, MORNING_CONFIG)  # must not raise
    got = {q["Ticker"] for q in quotes}
    # Second batch (T50..T59) is untouched by the raise and must be present.
    assert {"T50", "T59"} <= got


def test_fetch_ticker_quotes_small_list_single_batch():
    tickers = ["AAPL", "MSFT"]
    rows_for_ticker = {
        "AAPL": {"t": "AAPL", "pc": "1", "o": "1", "h": "1", "l": "1", "p": "1", "c": "0%", "atr": "1", "v": "1"},
        "MSFT": {"t": "MSFT", "pc": "1", "o": "1", "h": "1", "l": "1", "p": "1", "c": "0%", "atr": "1", "v": "1"},
    }
    page = _FakePage(rows_for_ticker)
    quotes = cm.fetch_ticker_quotes(page, tickers, MORNING_CONFIG)
    assert len(quotes) == 2
    assert {q["Ticker"] for q in quotes} == {"AAPL", "MSFT"}


# ---------------------------------------------------------------------------
# select_focus_universe (issue #293)
# ---------------------------------------------------------------------------


def _focus_df(pairs):
    """pairs: list of (ticker, focus_score) -> DataFrame like replay(view='focus')."""
    import pandas as pd
    return pd.DataFrame(pairs, columns=["ticker", "focus_score"])


def test_select_focus_universe_top_n_cap():
    df = _focus_df([(f"T{i}", 0.9 - i * 0.001) for i in range(150)])
    out = cm.select_focus_universe(df, top_n=100, floor=0.0)
    assert len(out) == 100
    assert out[0] == "T0"  # best-first
    assert out[-1] == "T99"


def test_select_focus_universe_floor_trims_below_cap():
    # 40 strong (>=0.3) + 60 weak (<0.3): floor keeps only the 40, cap never binds.
    strong = [(f"S{i}", 0.5) for i in range(40)]
    weak = [(f"W{i}", 0.1) for i in range(60)]
    out = cm.select_focus_universe(_focus_df(strong + weak), top_n=100, floor=0.3)
    assert len(out) == 40
    assert all(t.startswith("S") for t in out)


def test_select_focus_universe_floor_and_cap_together():
    # 120 rows all >= floor: cap binds at top_n, floor is a no-op.
    df = _focus_df([(f"T{i}", 0.9 - i * 0.004) for i in range(120)])  # min score ~0.42
    out = cm.select_focus_universe(df, top_n=100, floor=0.3)
    assert len(out) == 100


def test_select_focus_universe_ordering_best_first():
    df = _focus_df([("LOW", 0.31), ("HIGH", 0.9), ("MID", 0.5)])
    out = cm.select_focus_universe(df, top_n=100, floor=0.3)
    assert out == ["HIGH", "MID", "LOW"]


def test_select_focus_universe_empty_and_all_below_floor():
    assert cm.select_focus_universe(_focus_df([])) == []
    below = _focus_df([("A", 0.1), ("B", 0.29)])
    assert cm.select_focus_universe(below, top_n=100, floor=0.3) == []


def test_select_focus_universe_nan_score_dropped():
    import pandas as pd
    df = pd.DataFrame([("A", "0.5"), ("B", ""), ("C", "0.4")], columns=["ticker", "focus_score"])
    out = cm.select_focus_universe(df, top_n=100, floor=0.3)
    assert out == ["A", "C"]  # B (unparseable score) dropped by the floor


def test_select_focus_universe_dedupes_ticker():
    # replay/picks rows are keyed (date, list_category, ticker): the same ticker can
    # appear more than once (multi-bucket tag). It must occupy exactly one output slot,
    # keeping its highest-scoring copy — not eat two slots of the cap.
    df = _focus_df([("DUP", 0.4), ("A", 0.9), ("DUP", 0.6), ("B", 0.5)])
    out = cm.select_focus_universe(df, top_n=100, floor=0.3)
    assert out.count("DUP") == 1
    assert out == ["A", "DUP", "B"]  # DUP ranked by its 0.6 copy, not 0.4


def test_select_focus_universe_dedupe_yields_full_top_n_unique():
    # 120 rows but only 100 distinct tickers (20 dupes): cap must yield 100 UNIQUE.
    rows = [(f"T{i}", 0.9 - i * 0.001) for i in range(100)]
    rows += [(f"T{i}", 0.5) for i in range(20)]  # duplicate the first 20 tickers
    out = cm.select_focus_universe(_focus_df(rows), top_n=100, floor=0.0)
    assert len(out) == 100
    assert len(set(out)) == 100


def test_select_focus_universe_uses_module_defaults():
    # Defaults wire through to MORNING_FOCUS_TOP_N / MORNING_FOCUS_SCORE_FLOOR.
    df = _focus_df([(f"T{i}", 0.5) for i in range(cm.MORNING_FOCUS_TOP_N + 25)])
    assert len(cm.select_focus_universe(df)) == cm.MORNING_FOCUS_TOP_N


# ---------------------------------------------------------------------------
# load_pick_levels
# ---------------------------------------------------------------------------


PICKS_CSV = """date,collected_at,list_category,selector_version,group,ticker,High,Low,ATR
2026-08-06,2026-08-06T22:00:00Z,leaders,v2,Group A,AAPL,190.5,185.0,3.2
2026-08-06,2026-08-06T22:00:00Z,leaders,v2,Group A,MSFT,420.0,410.0,5.0
2026-08-05,2026-08-05T22:00:00Z,leaders,v2,Group A,OLD,10.0,9.0,1.0
"""


def test_load_pick_levels_from_path(tmp_path):
    p = tmp_path / "picks_latest.csv"
    p.write_text(PICKS_CSV)
    levels = cm.load_pick_levels(p)
    assert len(levels) == 2  # only max date (2026-08-06)
    by_ticker = {lvl["ticker"]: lvl for lvl in levels}
    assert by_ticker["AAPL"]["trigger"] == 190.5
    assert by_ticker["AAPL"]["stop"] == 185.0
    assert by_ticker["AAPL"]["atr"] == 3.2
    assert "OLD" not in by_ticker


def test_load_pick_levels_from_rows():
    rows = list(csv.DictReader(io.StringIO(PICKS_CSV)))
    levels = cm.load_pick_levels(rows)
    assert len(levels) == 2


def test_load_pick_levels_handles_missing_values():
    csv_text = "date,collected_at,list_category,selector_version,group,ticker,High,Low,ATR\n" \
               "2026-08-06,x,leaders,v2,Group A,ZZZ,,,\n"
    levels = cm.load_pick_levels(list(csv.DictReader(io.StringIO(csv_text))))
    assert levels[0]["trigger"] is None
    assert levels[0]["stop"] is None
    assert levels[0]["atr"] is None


# ---------------------------------------------------------------------------
# build_status_rows
# ---------------------------------------------------------------------------


def test_build_status_rows_each_status_and_no_quote():
    pick_levels = [
        {"ticker": "TRIG", "group": "G", "list_category": "leaders", "trigger": 10.0, "stop": 8.0, "atr": 2.0},
        {"ticker": "GAP", "group": "G", "list_category": "leaders", "trigger": 10.0, "stop": 8.0, "atr": 2.0},
        {"ticker": "SETUP", "group": "G", "list_category": "leaders", "trigger": 10.0, "stop": 8.0, "atr": 2.0},
        {"ticker": "INVALID", "group": "G", "list_category": "leaders", "trigger": 10.0, "stop": 8.0, "atr": 2.0},
        {"ticker": "FAILED", "group": "G", "list_category": "leaders", "trigger": 10.0, "stop": 8.0, "atr": 2.0},
        {"ticker": "ABSENT", "group": "G", "list_category": "leaders", "trigger": 10.0, "stop": 8.0, "atr": 2.0},
    ]
    quotes = [
        {"Ticker": "TRIG", "Price": "10.5", "Open": "9.5", "High": "10.6", "Low": "9.4", "Change": "1%"},
        {"Ticker": "GAP", "Price": "11.0", "Open": "10.5", "High": "11.2", "Low": "10.4", "Change": "2%"},
        {"Ticker": "SETUP", "Price": "9.0", "Open": "8.5", "High": "9.2", "Low": "8.4", "Change": "0%"},
        {"Ticker": "INVALID", "Price": "7.5", "Open": "8.5", "High": "9.0", "Low": "7.4", "Change": "-3%"},
        {"Ticker": "FAILED", "Price": "9.8", "Open": "9.5", "High": "10.1", "Low": "9.4", "Change": "0%"},
        # ABSENT has no quote row at all
    ]
    rows = cm.build_status_rows(pick_levels, quotes, "2026-08-07T13:45:00Z", "2026-08-07")
    by_ticker = {r["ticker"]: r for r in rows}

    assert by_ticker["TRIG"]["status"] == "triggered"
    assert by_ticker["GAP"]["status"] == "gapped_through"
    assert by_ticker["SETUP"]["status"] == "setting_up"
    assert by_ticker["INVALID"]["status"] == "invalidated"
    assert by_ticker["FAILED"]["status"] == "failed_breakout"
    assert by_ticker["ABSENT"]["status"] == "no_quote"

    # atr_from_lod only populated for actionable states
    assert by_ticker["TRIG"]["atr_from_lod"] != ""
    assert by_ticker["GAP"]["atr_from_lod"] != ""
    assert by_ticker["SETUP"]["atr_from_lod"] == ""
    assert by_ticker["INVALID"]["atr_from_lod"] == ""
    assert by_ticker["FAILED"]["atr_from_lod"] == ""
    assert by_ticker["ABSENT"]["atr_from_lod"] == ""

    for r in rows:
        assert r["date"] == "2026-08-07"
        assert r["session"] == "morning"
        assert r["collected_at"] == "2026-08-07T13:45:00Z"
        assert set(r.keys()) == set(cm.STORE_COLUMNS)


# ---------------------------------------------------------------------------
# write_store
# ---------------------------------------------------------------------------


def _row(date, ticker, status="setting_up", collected_at="2026-08-07T13:45:00Z"):
    return {
        "date": date, "session": "morning", "collected_at": collected_at,
        "ticker": ticker, "group": "G", "list_category": "leaders",
        "trigger": "10.0", "stop": "8.0", "atr": "2.0", "price": "9.0",
        "open": "8.5", "high": "9.2", "low": "8.4", "change": "0%",
        "status": status, "atr_from_lod": "",
    }


def test_write_store_dedup_and_latest_slice(tmp_path, monkeypatch):
    monkeypatch.setattr(cm, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(cm, "MORNING_STORE", tmp_path / "morning.csv")
    monkeypatch.setattr(cm, "MORNING_LATEST", tmp_path / "morning_latest.csv")

    cm.write_store([_row("2026-08-06", "AAPL"), _row("2026-08-06", "MSFT")])
    cm.write_store([_row("2026-08-07", "AAPL", status="triggered")])

    with open(cm.MORNING_STORE) as f:
        store_rows = list(csv.DictReader(f))
    assert len(store_rows) == 3  # 2026-08-06 x2 + 2026-08-07 x1, all distinct (date,ticker)

    with open(cm.MORNING_LATEST) as f:
        latest_rows = list(csv.DictReader(f))
    assert len(latest_rows) == 1
    assert latest_rows[0]["ticker"] == "AAPL"
    assert latest_rows[0]["date"] == "2026-08-07"
    assert latest_rows[0]["status"] == "triggered"


def test_write_store_last_write_wins_same_date_ticker(tmp_path, monkeypatch):
    monkeypatch.setattr(cm, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(cm, "MORNING_STORE", tmp_path / "morning.csv")
    monkeypatch.setattr(cm, "MORNING_LATEST", tmp_path / "morning_latest.csv")

    cm.write_store([_row("2026-08-07", "AAPL", status="setting_up", collected_at="2026-08-07T13:45:00Z")])
    cm.write_store([_row("2026-08-07", "AAPL", status="triggered", collected_at="2026-08-07T14:00:00Z")])

    with open(cm.MORNING_STORE) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["status"] == "triggered"
    assert rows[0]["collected_at"] == "2026-08-07T14:00:00Z"


def test_write_store_handles_no_existing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(cm, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(cm, "MORNING_STORE", tmp_path / "does_not_exist_yet.csv")
    monkeypatch.setattr(cm, "MORNING_LATEST", tmp_path / "does_not_exist_yet_latest.csv")
    cm.write_store([_row("2026-08-07", "AAPL")])
    assert cm.MORNING_STORE.exists()
    assert cm.MORNING_LATEST.exists()


def test_write_store_pre_close_session_writes_own_store(tmp_path, monkeypatch):
    # WS3b (issue #268): --session pre_close must write a session-keyed pair
    # (pre_close.csv / pre_close_latest.csv), not the morning store, and stamp
    # session="pre_close" on the row.
    monkeypatch.setattr(cm, "SESSIONS_DIR", tmp_path)

    row = _row("2026-08-17", "AAPL", status="triggered")
    row["session"] = "pre_close"
    cm.write_store([row], session=session_config.PRE_CLOSE)

    store_path, latest_path = cm.session_store_paths(session_config.PRE_CLOSE)
    assert store_path == tmp_path / "pre_close.csv"
    assert not (tmp_path / "morning.csv").exists()

    with open(latest_path) as f:
        latest_rows = list(csv.DictReader(f))
    assert len(latest_rows) == 1
    assert latest_rows[0]["session"] == "pre_close"
    assert latest_rows[0]["ticker"] == "AAPL"


def test_write_store_empty_rows_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(cm, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(cm, "MORNING_STORE", tmp_path / "morning.csv")
    monkeypatch.setattr(cm, "MORNING_LATEST", tmp_path / "morning_latest.csv")
    cm.write_store([])
    assert not cm.MORNING_STORE.exists()


def test_write_store_calls_assert_provisional(monkeypatch, tmp_path):
    # assert_provisional must raise for a settled session (eod) — write_store
    # must actually invoke it, not just import it decoratively.
    monkeypatch.setattr(cm, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(cm, "MORNING_STORE", tmp_path / "morning.csv")
    monkeypatch.setattr(cm, "MORNING_LATEST", tmp_path / "morning_latest.csv")

    calls = []
    orig = session_config.assert_provisional

    def spy(key):
        calls.append(key)
        return orig(key)

    monkeypatch.setattr(session_config, "assert_provisional", spy)
    monkeypatch.setattr(cm.session_config, "assert_provisional", spy)

    cm.write_store([_row("2026-08-07", "AAPL")])
    assert calls == [session_config.MORNING]


def test_assert_provisional_raises_for_eod():
    with pytest.raises(ValueError):
        session_config.assert_provisional(session_config.EOD)


# ---------------------------------------------------------------------------
# build_watch_levels (P2)
# ---------------------------------------------------------------------------


def test_build_watch_levels_maps_fields():
    watch_refs = [
        {"ticker": "AAPL", "level_type": "reclaim_50ma", "prior_high": 190.5,
         "prior_low": 185.0, "atr": 3.2, "sma20": 188.0, "sma50": 180.0},
    ]
    levels = cm.build_watch_levels(watch_refs)
    assert len(levels) == 1
    lvl = levels[0]
    assert lvl["ticker"] == "AAPL"
    assert lvl["group"] == ""
    assert lvl["list_category"] == "watchlist"
    assert lvl["trigger"] == 190.5
    assert lvl["stop"] == 185.0
    assert lvl["atr"] == 3.2
    assert lvl["ref"] == 180.0  # sma50, NOT sma20 — system read is always the 50MA


def test_build_watch_levels_keeps_null_prior_high():
    watch_refs = [
        {"ticker": "ZZZ", "prior_high": None, "prior_low": None, "atr": None, "sma50": None},
    ]
    levels = cm.build_watch_levels(watch_refs)
    assert len(levels) == 1
    assert levels[0]["trigger"] is None
    assert levels[0]["stop"] is None
    assert levels[0]["ref"] is None


def test_build_watch_levels_skips_blank_ticker():
    watch_refs = [
        {"ticker": "", "prior_high": 10, "prior_low": 8, "atr": 1, "sma50": 9},
        {"ticker": None, "prior_high": 10, "prior_low": 8, "atr": 1, "sma50": 9},
        {"ticker": "OK", "prior_high": 10, "prior_low": 8, "atr": 1, "sma50": 9},
    ]
    levels = cm.build_watch_levels(watch_refs)
    assert len(levels) == 1
    assert levels[0]["ticker"] == "OK"


def test_build_watch_levels_coerces_string_numbers():
    watch_refs = [
        {"ticker": "STR", "prior_high": "190.5", "prior_low": "185.0", "atr": "3.2", "sma50": "180.0"},
    ]
    lvl = cm.build_watch_levels(watch_refs)[0]
    assert lvl["trigger"] == 190.5
    assert lvl["stop"] == 185.0
    assert lvl["atr"] == 3.2
    assert lvl["ref"] == 180.0


# ---------------------------------------------------------------------------
# union_watch_levels (P2)
# ---------------------------------------------------------------------------


def test_union_watch_levels_dedupes_ticker():
    pick_levels = [
        {"ticker": "AAPL", "group": "G", "list_category": "leaders", "trigger": 190.0, "stop": 185.0, "atr": 3.0},
    ]
    watch_levels = [
        {"ticker": "AAPL", "group": "", "list_category": "watchlist", "trigger": 999, "stop": 999, "atr": 999, "ref": 999},
        {"ticker": "MSFT", "group": "", "list_category": "watchlist", "trigger": 420, "stop": 410, "atr": 5, "ref": 400},
    ]
    levels, tickers = cm.union_watch_levels(pick_levels, watch_levels)
    assert tickers == ["AAPL", "MSFT"]
    by_ticker = {lvl["ticker"]: lvl for lvl in levels}
    # AAPL keeps the Focus pick's level dict (real group/list_category), not the watch dup.
    assert by_ticker["AAPL"]["list_category"] == "leaders"
    assert by_ticker["AAPL"]["trigger"] == 190.0
    # MSFT is a pure watch addition.
    assert by_ticker["MSFT"]["list_category"] == "watchlist"
    assert by_ticker["MSFT"]["ref"] == 400


def test_union_watch_levels_empty_watch_is_noop():
    pick_levels = [{"ticker": "AAPL", "group": "G", "list_category": "leaders",
                     "trigger": 1, "stop": 1, "atr": 1}]
    levels, tickers = cm.union_watch_levels(pick_levels, [])
    assert levels == pick_levels
    assert tickers == ["AAPL"]


# ---------------------------------------------------------------------------
# build_status_rows with reclaim ref (P2)
# ---------------------------------------------------------------------------


def test_build_status_rows_watch_level_reclaim():
    pick_levels = [
        {"ticker": "WATCH1", "group": "", "list_category": "watchlist",
         "trigger": 999.0, "stop": 8.0, "atr": 2.0, "ref": 8.5},
        # A regular picks level (no "ref" key) must be unaffected — regression.
        {"ticker": "PICK1", "group": "G", "list_category": "leaders",
         "trigger": 10.0, "stop": 8.0, "atr": 2.0},
    ]
    quotes = [
        # price=9.0 > ref=8.5; today_low=7.5 < ref=8.5 -> reclaim (price/high/open all < trigger=999)
        {"Ticker": "WATCH1", "Price": "9.0", "Open": "8.0", "High": "9.1", "Low": "7.5", "Change": "0.5%"},
        {"Ticker": "PICK1", "Price": "9.0", "Open": "8.5", "High": "9.2", "Low": "8.4", "Change": "0%"},
    ]
    rows = cm.build_status_rows(pick_levels, quotes, "2026-08-07T13:45:00Z", "2026-08-07")
    by_ticker = {r["ticker"]: r for r in rows}

    assert by_ticker["WATCH1"]["status"] == "reclaim"
    assert by_ticker["WATCH1"]["atr_from_lod"] != ""  # actionable status

    assert by_ticker["PICK1"]["status"] == "setting_up"


# ---------------------------------------------------------------------------
# fetch_watchlist_tickers / post_watchlist_tick non-fatal behavior (P2)
# ---------------------------------------------------------------------------


def test_fetch_watchlist_tickers_non_fatal_on_error(monkeypatch):
    def raising_authed_request(*args, **kwargs):
        raise RuntimeError("network broke")

    monkeypatch.setattr(cm, "_authed_request", raising_authed_request)
    result = cm.fetch_watchlist_tickers("https://worker.example", "tok")
    assert result == []  # never raises, never exits


def test_fetch_watchlist_tickers_non_fatal_on_non_200(monkeypatch):
    class _Resp:
        status = 500
        def read(self):
            return b'{"tickers": []}'
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(cm, "_authed_request", lambda *a, **k: _Resp())
    assert cm.fetch_watchlist_tickers("https://worker.example", "tok") == []


def test_fetch_watchlist_tickers_success(monkeypatch):
    class _Resp:
        status = 200
        def read(self):
            return b'{"tickers": [{"ticker": "AAPL"}]}'
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(cm, "_authed_request", lambda *a, **k: _Resp())
    result = cm.fetch_watchlist_tickers("https://worker.example", "tok")
    assert result == [{"ticker": "AAPL"}]


def test_post_watchlist_tick_non_fatal_on_error(monkeypatch):
    def raising_authed_request(*args, **kwargs):
        raise RuntimeError("network broke")

    monkeypatch.setattr(cm, "_authed_request", raising_authed_request)
    result = cm.post_watchlist_tick("https://worker.example", "tok", "2026-08-07")
    assert result is None  # never raises, never exits


def test_post_watchlist_tick_success(monkeypatch):
    class _Resp:
        status = 200
        def read(self):
            return b'{"ticked": 3}'
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(cm, "_authed_request", lambda *a, **k: _Resp())
    result = cm.post_watchlist_tick("https://worker.example", "tok", "2026-08-07")
    assert result == {"ticked": 3}


# should_tick_watchlist (WS3b, issue #268) — gates the P2 watchlist tick to only the
# sessions in session_config.WATCHLIST_TICK_SESSIONS, so a pre_close run never
# double-decrements a watch entry's TTL for the same trading day.

def test_should_tick_watchlist_true_for_morning():
    assert cm.should_tick_watchlist(session_config.MORNING) is True


def test_should_tick_watchlist_false_for_pre_close():
    assert cm.should_tick_watchlist(session_config.PRE_CLOSE) is False


def test_should_tick_watchlist_false_for_unknown_session():
    assert cm.should_tick_watchlist("some_future_session") is False


# Regression guard (2026-08-20): the "Collect morning status" step in
# collect_morning.yml had no env: block, so POSITIONS_WORKER_URL/POSITIONS_INGEST_TOKEN
# were never exported to the runner. collect_morning.py gates both the WS5 §8b
# watchlist union and the /watchlist/tick TTL decrement on
# watchlist_configured = bool(worker_url and token), so this silently no-opped every
# scheduled run. Assert the workflow step wires both secrets so this can't regress
# without a test failure.

def test_collect_morning_workflow_wires_positions_secrets():
    import yaml

    workflow_path = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "collect_morning.yml"
    )
    workflow = yaml.safe_load(workflow_path.read_text())

    steps = workflow["jobs"]["morning"]["steps"]
    morning_steps = [
        s for s in steps if "collect_morning.py" in s.get("run", "")
    ]
    assert len(morning_steps) == 1, "expected exactly one step invoking collect_morning.py"
    step = morning_steps[0]

    env = step.get("env")
    assert env is not None, "Collect morning status step is missing an env: block"
    assert "POSITIONS_WORKER_URL" in env
    assert "secrets." in env["POSITIONS_WORKER_URL"]
    assert "POSITIONS_INGEST_TOKEN" in env
    assert "secrets." in env["POSITIONS_INGEST_TOKEN"]
