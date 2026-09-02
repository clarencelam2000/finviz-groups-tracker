"""
Playwright functional tests for the Picks tab expanded-card additions:
  - new "ATR / 20MA stop (ATR) / 50MA stop (ATR)" row (replaces "Stop dist (ATR)")
  - Avg $ Volume (Price x Avg Volume)
  - Earnings proximity badge (amber within EARNINGS_CAUTION_DAYS, red within
    EARNINGS_IMMINENT_DAYS, neutral for past/stale dates)

Uses the harness documented in knowledge/investigations/playwright-cloud-session-testing.md:
CDN scripts (Tailwind/PapaParse) must be stubbed via page.route or the app never boots in a
sandboxed session, route globs need "**/" immediately before the literal filename, and
wait_until="domcontentloaded" (not "networkidle") avoids hanging on unreachable CDN checks.

Run with Playwright installed:
    python3 -m playwright install chromium
    python3 -m pytest tests/test_pwa_picks_atr_earnings.py -v -m functional
"""

import csv
import io
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "picks_latest.csv"


def _launch_server(port: int):
    docs_dir = ROOT / "docs"
    return subprocess.Popen(
        ["python3", "-m", "http.server", str(port), "--directory", str(docs_dir)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _single_row_csv(overrides: dict) -> str:
    """Build a one-row picks_latest.csv using ANET as the base, with overrides."""
    with FIXTURE.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames
        rows = list(reader)

    base = next(r for r in rows if r["ticker"] == "ANET")
    row = dict(base)
    row.update(overrides)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols)
    writer.writeheader()
    writer.writerow(row)
    return buf.getvalue()


def _finviz_earnings_str(days_from_today: int, session: str = "b") -> str:
    """Format a date `days_from_today` away as Finviz's 'Mon D/s' earnings string."""
    dt = datetime.now() + timedelta(days=days_from_today)
    return f"{dt.strftime('%b')} {dt.day}/{session}"


@pytest.mark.functional
class TestPicksAtrRowAndEarnings:
    PORT = 8184

    @pytest.fixture(autouse=True, scope="class")
    def server(self):
        proc = _launch_server(self.PORT)
        time.sleep(1)
        yield proc
        proc.terminate()
        proc.wait()

    def _open_picks_tab(self, page, picks_body: str):
        tailwind_js = "/* tailwind stub: styling not asserted in these tests */"
        papaparse_js = (ROOT / "tests" / "fixtures" / "papaparse.min.js").read_text(encoding="utf-8")

        page.route("**/cdn.tailwindcss.com/**",
                   lambda r: r.fulfill(body=tailwind_js, content_type="application/javascript"))
        page.route("**/cdnjs.cloudflare.com/**",
                   lambda r: r.fulfill(body=papaparse_js, content_type="application/javascript"))
        page.route("**/picks_latest.csv",
                   lambda r: r.fulfill(body=picks_body, content_type="text/plain"))
        page.route("**/snapshots.csv",
                   lambda r: r.fulfill(body="date,collected_at,group_type,name,stocks,market_cap,pe,fwd_pe,perf_day,perf_week,perf_month,perf_quarter,perf_half,perf_year,perf_ytd,avg_volume,rel_volume,change\n", content_type="text/plain"))
        page.route("**/deltas.csv",
                   lambda r: r.fulfill(body="date,name\n", content_type="text/plain"))
        page.route("**/releases.json",
                   lambda r: r.fulfill(body='{"current":"","releases":[]}', content_type="application/json"))

        page.add_init_script("try { localStorage.setItem('fvt_intro_seen_v1','true'); } catch(e){}")
        page.goto(f"http://localhost:{self.PORT}/", wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        page.click("[data-tab='picks']")
        page.wait_for_timeout(400)

    def _expand_first_card(self, page):
        card = page.locator("[onclick*='__togglePickRow']").first
        card.click()
        page.wait_for_timeout(300)

    def test_new_atr_row_replaces_stop_dist(self):
        """Panel shows ATR / 20MA stop (ATR) / 50MA stop (ATR); 'Stop dist (ATR)' is gone."""
        from playwright.sync_api import sync_playwright

        anet_body = _single_row_csv({})  # ANET: Price=165.45 ATR=8.39 SMA20=1.16% SMA50=3.52%

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_picks_tab(page, anet_body)
            self._expand_first_card(page)

            panel_text = page.locator("[id^='risk-panel-']").first.inner_text()

            assert "Stop dist (ATR)" not in panel_text, \
                f"'Stop dist (ATR)' should be removed; got:\n{panel_text}"
            assert "20MA stop (ATR)" in panel_text and "50MA stop (ATR)" in panel_text, \
                f"Expected new ATR-multiple row labels; got:\n{panel_text}"
            # ANET: atr_ext_20 ~= 0.226 -> "0.2x", atr_ext_50 ~= 0.671 -> "0.7x" (Last basis)
            assert "0.2×" in panel_text, f"Expected 20MA stop (ATR) ~0.2x; got:\n{panel_text}"
            assert "0.7×" in panel_text, f"Expected 50MA stop (ATR) ~0.7x (matches Ext (x50MA)); got:\n{panel_text}"

            browser.close()

    def test_avg_dollar_volume_displayed(self):
        """Avg $ Vol = Price x Avg Volume, formatted compactly (e.g. $1.53B for ANET)."""
        from playwright.sync_api import sync_playwright

        anet_body = _single_row_csv({})  # ANET: Price=165.45, Avg Volume=9.24M -> ~$1.53B

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_picks_tab(page, anet_body)
            self._expand_first_card(page)

            panel_text = page.locator("[id^='risk-panel-']").first.inner_text()
            assert "Avg $ Vol" in panel_text
            assert "$1.53B" in panel_text, f"Expected Avg $ Vol ~$1.53B; got:\n{panel_text}"

            browser.close()

    def test_earnings_imminent_is_red(self):
        """Earnings 2 days out (within EARNINGS_IMMINENT_DAYS=3) gets the red badge class."""
        from playwright.sync_api import sync_playwright

        body = _single_row_csv({"Earnings": _finviz_earnings_str(2)})

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_picks_tab(page, body)
            self._expand_first_card(page)

            panel = page.locator("[id^='risk-panel-']").first
            earnings_el = panel.locator("text=Earnings").locator("xpath=following-sibling::span")
            cls = earnings_el.get_attribute("class") or ""
            assert "text-red-400" in cls, f"Expected red class for 2-day-out earnings; got: {cls}"

            browser.close()

    def test_earnings_caution_is_amber(self):
        """Earnings 7 days out (within EARNINGS_CAUTION_DAYS=10, beyond IMMINENT=3) gets amber."""
        from playwright.sync_api import sync_playwright

        body = _single_row_csv({"Earnings": _finviz_earnings_str(7)})

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_picks_tab(page, body)
            self._expand_first_card(page)

            panel = page.locator("[id^='risk-panel-']").first
            earnings_el = panel.locator("text=Earnings").locator("xpath=following-sibling::span")
            cls = earnings_el.get_attribute("class") or ""
            assert "text-amber-400" in cls, f"Expected amber class for 7-day-out earnings; got: {cls}"

            browser.close()

    def test_earnings_past_is_neutral(self):
        """A past earnings date (Finviz hasn't refreshed yet) is shown neutrally, never flagged."""
        from playwright.sync_api import sync_playwright

        body = _single_row_csv({"Earnings": _finviz_earnings_str(-5)})

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_picks_tab(page, body)
            self._expand_first_card(page)

            panel_text = page.locator("[id^='risk-panel-']").first.inner_text()
            panel = page.locator("[id^='risk-panel-']").first
            earnings_el = panel.locator("text=Earnings").locator("xpath=following-sibling::span")
            cls = earnings_el.get_attribute("class") or ""

            assert "(past)" in panel_text, f"Expected '(past)' suffix; got:\n{panel_text}"
            assert "text-red-400" not in cls and "text-amber-400" not in cls, \
                f"Past earnings date must not be flagged; got class: {cls}"

            browser.close()

    def test_volatility_setup_section_shows_raw_values(self):
        """Expanded card's 'Volatility & setup' section shows Vol W/M, RelVol, From 52W high
        as raw values, and the fact-derived 'contracting' read when Vol W < Vol M (Effort B,
        issue #379, governing principle §4.0 — values shown, no invented thresholds)."""
        from playwright.sync_api import sync_playwright

        # ANET fixture: Vol W 4.29% (<) Vol M 4.61% -> contracting; RelVol 0.87; 52W High -7.98%
        body = _single_row_csv({})

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_picks_tab(page, body)
            self._expand_first_card(page)

            panel_text = page.locator("[id^='risk-panel-']").first.inner_text()
            assert "Volatility & setup" in panel_text, f"section header missing; got:\n{panel_text}"
            assert "Vol W / M" in panel_text
            assert "4.3% / 4.6%" in panel_text, f"expected raw Vol W/M values; got:\n{panel_text}"
            assert "contracting" in panel_text, f"Vol W<M should read contracting; got:\n{panel_text}"
            assert "0.87×" in panel_text, f"expected RelVol 0.87x; got:\n{panel_text}"
            assert "From 52W high" in panel_text and "-8.0%" in panel_text, \
                f"expected From-52W-high value; got:\n{panel_text}"

            browser.close()

    def test_volatility_setup_expanding_when_week_hotter(self):
        """Vol W > Vol M reads 'expanding' (pure sign of W-M, no magnitude cutoff)."""
        from playwright.sync_api import sync_playwright

        body = _single_row_csv({"Volatility W": "6.20%", "Volatility M": "4.10%"})

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_picks_tab(page, body)
            self._expand_first_card(page)

            panel_text = page.locator("[id^='risk-panel-']").first.inner_text()
            assert "6.2% / 4.1%" in panel_text, f"expected raw Vol W/M; got:\n{panel_text}"
            assert "expanding" in panel_text, f"Vol W>M should read expanding; got:\n{panel_text}"

            browser.close()

    def test_range_tightening_shows_flag_and_sparklines(self):
        """B-2 (issue #379): the 'Range over last 10 sessions' block (renamed from 'Range
        tightening' 2026-09-02 — same rename applies everywhere volSetupSectionHtml renders,
        Picks included, since it's clearer copy; only the Morning/Watch 'as of last close'
        caveat is conditional) shows the honest 'Tightest range · last 7 bars' flag when
        tight_range_7 == '1' and renders both *_spark sparklines as SVG polylines (SHOWN
        values, doc §4.0). ANET fixture carries populated series. The Picks tab never gets
        the 'as of last close' caveat — there the whole card, trailing cols included, is
        from the same EOD run, so there's no lag to caveat."""
        from playwright.sync_api import sync_playwright

        body = _single_row_csv({})  # ANET: tight_range_7='1', both spark series populated

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_picks_tab(page, body)
            self._expand_first_card(page)

            panel = page.locator("[id^='risk-panel-']").first
            panel_text = panel.inner_text()
            assert "Range over last 10 sessions" in panel_text, f"missing block; got:\n{panel_text}"
            assert "as of last close" not in panel_text, f"Picks tab must not show the staleness caveat; got:\n{panel_text}"
            assert "Tightest range" in panel_text and "last 7 bars" in panel_text, \
                f"expected honest tightest-range flag; got:\n{panel_text}"
            # B-3 (issue #379): the 'Volume over last 10 sessions' block shows the Rel Volume trend series.
            assert "Volume over last 10 sessions" in panel_text, f"missing B-3 block; got:\n{panel_text}"
            # Three sparklines now (range/ATR + ATR $ + rel-volume) as SVG polylines.
            assert panel.locator("svg polyline").count() >= 3, "expected 3 sparkline polylines"
            # Never claims 'NR7' (gappy history — labeled honestly).
            assert "NR7" not in panel_text, f"must not claim NR7; got:\n{panel_text}"

            browser.close()

    def test_power_of_3_chip_and_ma_distances(self):
        """B-5 (issue #379): the 'MA bunching' block shows the green 'Pre-Power of 3' coil-precondition
        chip when price/20MA/50MA are bunched within the 2xATR band (power_of_3 == '1'), plus the two
        shown SMA % distances and the classic MA-to-MA cluster spread % (SHOWN values, doc §4.0). ANET
        fixture: Price 165.45, SMA20 1.16%, SMA50 3.52%, power_of_3 == '1' → spread ~2.25%."""
        from playwright.sync_api import sync_playwright

        body = _single_row_csv({})  # ANET: power_of_3='1' (bunched)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_picks_tab(page, body)
            self._expand_first_card(page)

            panel_text = page.locator("[id^='risk-panel-']").first.inner_text()
            assert "MA bunching" in panel_text, f"missing block; got:\n{panel_text}"
            assert "Pre-Power of 3" in panel_text, f"expected chip when bunched; got:\n{panel_text}"
            assert "spread 2.25%" in panel_text, f"expected MA-to-MA cluster spread; got:\n{panel_text}"
            assert "Price vs 20MA" in panel_text and "+1.2%" in panel_text, \
                f"expected 20MA distance; got:\n{panel_text}"
            assert "Price vs 50MA" in panel_text and "+3.5%" in panel_text, \
                f"expected 50MA distance; got:\n{panel_text}"

            browser.close()

    def test_power_of_3_no_chip_when_not_bunched(self):
        """power_of_3 == '0' shows the MA-distance values but NOT the 'Pre-Power of 3' chip — the chip
        is a fact that either fires or doesn't, never a score (doc §4.0)."""
        from playwright.sync_api import sync_playwright

        body = _single_row_csv({"power_of_3": "0"})

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_picks_tab(page, body)
            self._expand_first_card(page)

            panel_text = page.locator("[id^='risk-panel-']").first.inner_text()
            assert "MA bunching" in panel_text, f"block should still show distances; got:\n{panel_text}"
            assert "Pre-Power of 3" not in panel_text, f"chip must be absent when not bunched; got:\n{panel_text}"

            browser.close()

    def test_earnings_none_known_shows_dash(self):
        """Earnings == '-' (none known) renders as an em dash, no crash."""
        from playwright.sync_api import sync_playwright

        body = _single_row_csv({"Earnings": "-"})

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_picks_tab(page, body)
            self._expand_first_card(page)

            panel_text = page.locator("[id^='risk-panel-']").first.inner_text()
            assert "Earnings" in panel_text

            browser.close()
