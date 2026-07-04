"""
Playwright functional tests for the Lookup tab's SIGNAL card rework (v2):
  - groupSignal() factor-based composite replacing the old day-1 groupScore()
  - RS (vs S&P 500) folded into the score + shown on the group cards
  - evidence text generated from the same factors that drove the score
  - missing-data caveat instead of a silently-averaged fake-neutral score
  - "This stock" block surfacing the ticker's own Stage-2/Focus context
  - lookupGlossary() generated from GUIDE.metrics (fixes the rs_score/rs_confirmed
    'lookup' tab drift) instead of a separate hand-maintained copy

Uses the harness documented in knowledge/investigations/playwright-cloud-session-testing.md:
CDN scripts (Tailwind/PapaParse) must be stubbed via page.route or the app never boots in a
sandboxed session, route globs need "**/" immediately before the literal filename, and
wait_until="domcontentloaded" (not "networkidle") avoids hanging on unreachable CDN checks.

Run with Playwright installed:
    python3 -m playwright install chromium
    python3 -m pytest tests/test_pwa_lookup_signal.py -v -m functional
"""

import csv
import io
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

INDUSTRIES_SNAP_HEADER = "date,collected_at,group_type,name,stocks,market_cap,pe,fwd_pe,perf_day,perf_week,perf_month,perf_quarter,perf_half,perf_year,perf_ytd,avg_volume,rel_volume,change"
DELTA_HEADER = (
    "date,name,rank_day,rank_week,rank_month,rank_quarter,rank_half,rank_year,rank_ytd,"
    "rank_week_delta_5d,rank_ytd_delta_5d,momentum_score,momentum_confirmed,rank_agreement,"
    "momentum_accel,regime_short_long,rank_trend_slope,rs_month,rs_score,rs_confirmed,"
    "beats_benchmark_week,beats_benchmark_month,beats_benchmark_quarter,beats_benchmark_half,"
    "beats_benchmark_year,beats_benchmark_ytd"
)

DATE = "2026-07-01"

# Two profiles reused for both industries and sectors: a strong ("Semiconductors"/
# "Technology") and a weak ("Coal"/"Energy") group, so tests can combine them into
# FAVORABLE / CAUTION / MIXED verdicts without hand-tuning a new profile per test.
STRONG = dict(
    perf=dict(day=1, week=3, month=5, quarter=10, half=15, year=20, ytd=18),
    rank_week_delta_5d=5, momentum_score=0.85, momentum_confirmed=0.85, rank_agreement=0.9,
    regime_short_long=0.30, rs_month=3.5, rs_score=0.9, rs_confirmed=0.80, beats="1",
)
WEAK = dict(
    perf=dict(day=-1, week=-3, month=-5, quarter=-8, half=-10, year=-15, ytd=-12),
    rank_week_delta_5d=-4, momentum_score=0.15, momentum_confirmed=0.15, rank_agreement=0.85,
    regime_short_long=-0.25, rs_month=-3.0, rs_score=0.1, rs_confirmed=0.10, beats="0",
)


def _snap_row(name, rank, profile, group_type):
    p = profile["perf"]
    return (f"{DATE},{DATE}T21:00:00Z,{group_type},{name},50,10.0,20,22,"
            f"{p['day']},{p['week']},{p['month']},{p['quarter']},{p['half']},{p['year']},{p['ytd']},"
            f"1000000,,0")


def _delta_row(name, rank, profile):
    b = profile["beats"]
    return (f"{DATE},{name},{rank},{rank},{rank},{rank},{rank},{rank},{rank},"
            f"{profile['rank_week_delta_5d']},{profile['rank_week_delta_5d']},"
            f"{profile['momentum_score']},{profile['momentum_confirmed']},{profile['rank_agreement']},"
            f"0.01,{profile['regime_short_long']},0.01,"
            f"{profile['rs_month']},{profile['rs_score']},{profile['rs_confirmed']},"
            f"{b},{b},{b},{b},{b},{b}")


def _group_csvs(rows, group_type):
    """rows: list of (name, rank, profile). Returns (snap_csv, delta_csv)."""
    snap = INDUSTRIES_SNAP_HEADER + "\n" + "\n".join(_snap_row(*r, group_type) for r in rows) + "\n"
    delta = DELTA_HEADER + "\n" + "\n".join(_delta_row(*r) for r in rows) + "\n"
    return snap, delta


def _finviz_earnings_str(days_from_today: int, session: str = "b") -> str:
    dt = datetime.now() + timedelta(days=days_from_today)
    return f"{dt.strftime('%b')} {dt.day}/{session}"


def _picks_csv(ticker: str, list_category: str = "leaders", earnings_days: int = 5):
    """Minimal one-row picks_latest.csv — only the columns findTickerPickInfo()/
    isFocusEligible()/computeFocusScores() actually read (single-candidate pool,
    so no grp_* normalization columns are needed)."""
    cols = ["date", "list_category", "ticker", "Ticker", "atr_ext_50", "Avg Volume", "Price", "Earnings"]
    row = {
        "date": DATE, "list_category": list_category, "ticker": ticker, "Ticker": ticker,
        "atr_ext_50": "1.5", "Avg Volume": "1M", "Price": "100",
        "Earnings": _finviz_earnings_str(earnings_days),
    }
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    w.writerow(row)
    return buf.getvalue()


def _lookup_response(symbol, industry, sector):
    industry_field = f'"{industry}"' if industry else "null"
    sector_field = f'"{sector}"' if sector else "null"
    return (
        f'{{"symbol":"{symbol}","company_name":"{symbol} Inc.","exchange":"NASDAQ",'
        f'"market_cap_b":100,"finviz_industry":{industry_field},"finviz_sector":{sector_field},'
        f'"industry_confidence":0.95,"image":null,"etf_kind":null}}'
    )


@pytest.mark.functional
class TestLookupSignalCard:
    PORT = 8189

    def _run(self, fn, industries_rows, sectors_rows, lookup_body, picks_body="date,list_category,ticker,Ticker\n"):
        from playwright.sync_api import sync_playwright

        docs_dir = ROOT / "docs"
        server = subprocess.Popen(
            ["python3", "-m", "http.server", str(self.PORT), "--directory", str(docs_dir)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(1)
        ind_snap, ind_delta = _group_csvs(industries_rows, "industries")
        sec_snap, sec_delta = _group_csvs(sectors_rows, "sectors")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(ignore_https_errors=True)
                ctx.add_init_script("localStorage.setItem('fvt_intro_seen_v1','true');")
                page = ctx.new_page()

                # Catch-all first (registered first = checked last), specific routes after.
                page.route("**/raw.githubusercontent.com/**", lambda r: r.fulfill(status=404))
                page.route("**/cdn.tailwindcss.com/**",
                            lambda r: r.fulfill(body="/* tailwind stub */", content_type="application/javascript"))
                papaparse_js = (ROOT / "tests" / "fixtures" / "papaparse.min.js").read_text(encoding="utf-8")
                page.route("**/cdnjs.cloudflare.com/**",
                            lambda r: r.fulfill(body=papaparse_js, content_type="application/javascript"))
                page.route("**/industries/snapshots.csv", lambda r: r.fulfill(body=ind_snap, content_type="text/plain"))
                page.route("**/industries/deltas.csv", lambda r: r.fulfill(body=ind_delta, content_type="text/plain"))
                page.route("**/sectors/snapshots.csv", lambda r: r.fulfill(body=sec_snap, content_type="text/plain"))
                page.route("**/sectors/deltas.csv", lambda r: r.fulfill(body=sec_delta, content_type="text/plain"))
                page.route("**/picks_latest.csv", lambda r: r.fulfill(body=picks_body, content_type="text/plain"))
                page.route("**/finviz-ticker-lookup.salmonbaby8.workers.dev/lookup*",
                            lambda r: r.fulfill(body=lookup_body, content_type="application/json"))

                page.goto(f"http://localhost:{self.PORT}/", wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(800)
                fn(page)
                ctx.close()
                browser.close()
        finally:
            server.terminate()
            server.wait()

    def _do_ticker_lookup(self, page, symbol):
        page.locator("[data-tab='lookup']").click()
        page.fill("#ticker-input", symbol)
        page.locator("#ticker-submit").click()
        page.wait_for_timeout(800)

    def test_favorable_verdict_with_matching_evidence(self):
        """Both groups strong (confirmed momentum + RS) -> FAVORABLE, evidence names the drivers."""
        def check(page):
            self._do_ticker_lookup(page, "AAPL")
            result = page.locator("#lookup-result").inner_text()
            assert "SIGNAL: FAVORABLE" in result, result[:400]
            assert "confirmed momentum" in result
            assert "beating S&P" in result
        self._run(
            check,
            industries_rows=[("Semiconductors", 1, STRONG), ("Coal", 2, WEAK)],
            sectors_rows=[("Technology", 1, STRONG), ("Energy", 2, WEAK)],
            lookup_body=_lookup_response("AAPL", "Semiconductors", "Technology"),
        )

    def test_caution_verdict_with_matching_evidence(self):
        """Both groups weak -> CAUTION, evidence names the drivers (not the old mismatched text)."""
        def check(page):
            self._do_ticker_lookup(page, "XYZ")
            result = page.locator("#lookup-result").inner_text()
            assert "SIGNAL: CAUTION" in result, result[:400]
            assert "lagging S&P" in result
        self._run(
            check,
            industries_rows=[("Semiconductors", 1, STRONG), ("Coal", 2, WEAK)],
            sectors_rows=[("Technology", 1, STRONG), ("Energy", 2, WEAK)],
            lookup_body=_lookup_response("XYZ", "Coal", "Energy"),
        )

    def test_mixed_verdict_when_industry_and_sector_diverge(self):
        """Strong industry + weak sector -> MIXED, not silently rounded to FAVORABLE/CAUTION."""
        def check(page):
            self._do_ticker_lookup(page, "DIVX")
            result = page.locator("#lookup-result").inner_text()
            assert "SIGNAL: MIXED" in result, result[:400]
            assert "lean on the stock" in result
        self._run(
            check,
            industries_rows=[("Semiconductors", 1, STRONG), ("Coal", 2, WEAK)],
            sectors_rows=[("Technology", 1, STRONG), ("Energy", 2, WEAK)],
            lookup_body=_lookup_response("DIVX", "Semiconductors", "Energy"),
        )

    def test_partial_data_caveat_instead_of_fake_neutral(self):
        """Industry untracked, sector strong -> verdict driven by sector alone + explicit caveat
        (regression guard: the old groupScore() averaged in a fake 0.5 for the missing side)."""
        def check(page):
            self._do_ticker_lookup(page, "ETFX")
            result = page.locator("#lookup-result").inner_text()
            assert "SIGNAL: FAVORABLE" in result, result[:400]
            assert "Based on Technology only" in result
            assert "no tracked data for NotTracked" in result
        self._run(
            check,
            industries_rows=[("Semiconductors", 1, STRONG), ("Coal", 2, WEAK)],
            sectors_rows=[("Technology", 1, STRONG), ("Energy", 2, WEAK)],
            lookup_body=_lookup_response("ETFX", "NotTracked", "Technology"),
        )

    def test_rs_chip_appears_on_group_card(self):
        """RS vs S&P (rs_month + 'beats' chip) now renders on the Lookup group cards —
        previously computed but never shown here despite GUIDE tagging it for 'lookup'."""
        def check(page):
            self._do_ticker_lookup(page, "AAPL")
            result = page.locator("#lookup-result").inner_text()
            assert "vs S&P" in result
            assert "+3.5pp" in result
            assert "beats 6/6" in result
        self._run(
            check,
            industries_rows=[("Semiconductors", 1, STRONG), ("Coal", 2, WEAK)],
            sectors_rows=[("Technology", 1, STRONG), ("Energy", 2, WEAK)],
            lookup_body=_lookup_response("AAPL", "Semiconductors", "Technology"),
        )

    def test_glossary_includes_rs_metrics(self):
        """lookupGlossary() is now generated from GUIDE.metrics — rs_score/rs_confirmed (already
        tagged 'lookup' in GUIDE) must actually appear, closing the Guide-hub drift bug."""
        def check(page):
            self._do_ticker_lookup(page, "AAPL")
            page.locator("#lookup-result summary", has_text="why this matters").click()
            page.wait_for_timeout(200)
            text = page.locator("#lookup-result details").inner_text()
            assert "RS Score" in text
            assert "Confirmed RS" in text
        self._run(
            check,
            industries_rows=[("Semiconductors", 1, STRONG), ("Coal", 2, WEAK)],
            sectors_rows=[("Technology", 1, STRONG), ("Energy", 2, WEAK)],
            lookup_body=_lookup_response("AAPL", "Semiconductors", "Technology"),
        )

    def test_this_stock_block_appears_when_ticker_in_todays_picks(self):
        """Ticker's own Stage-2 category/ATR-extension/Focus context surfaces inline instead of
        requiring the user to scroll down and find themselves in the group's Stage-2 list."""
        def check(page):
            self._do_ticker_lookup(page, "ANET")
            block = page.locator(".lookup-ticker-context")
            assert block.count() == 1
            text = block.inner_text()
            assert "Leaders" in text
            assert "ATR ext" in text
            assert "Focus" in text
        self._run(
            check,
            industries_rows=[("Semiconductors", 1, STRONG), ("Coal", 2, WEAK)],
            sectors_rows=[("Technology", 1, STRONG), ("Energy", 2, WEAK)],
            lookup_body=_lookup_response("ANET", "Semiconductors", "Technology"),
            picks_body=_picks_csv("ANET"),
        )

    def test_this_stock_block_absent_when_ticker_not_in_todays_picks(self):
        """Silence = no signal: no manufactured 'not found' message when the ticker isn't
        in today's picks at all."""
        def check(page):
            self._do_ticker_lookup(page, "MSFT")
            assert page.locator(".lookup-ticker-context").count() == 0
        self._run(
            check,
            industries_rows=[("Semiconductors", 1, STRONG), ("Coal", 2, WEAK)],
            sectors_rows=[("Technology", 1, STRONG), ("Energy", 2, WEAK)],
            lookup_body=_lookup_response("MSFT", "Semiconductors", "Technology"),
            picks_body=_picks_csv("ANET"),
        )
