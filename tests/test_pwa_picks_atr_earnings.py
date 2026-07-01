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
