"""
Playwright functional test for the Picks tab's lazy-loaded TradingView chart toggle.

Companion to the Lookup tab's chart toggle (tests/test_functional_playwright.py::
TestPWALookupChart). Same widget/helper (tradingViewChartHtml), but scoped per-row
via state.picksChartOpen instead of the single-ticker state.lookup.chartOpen.

Run with Playwright installed:
    python3 -m playwright install chromium
    python3 -m pytest tests/test_pwa_picks_chart.py -v -m functional
"""

import subprocess
import time
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


@pytest.mark.functional
class TestPicksChartToggle:
    """Per-row [ Show chart ] toggle inside the Picks expanded risk panel."""

    PORT = 8188

    @pytest.fixture(autouse=True, scope="class")
    def server(self):
        proc = _launch_server(self.PORT)
        time.sleep(1)
        yield proc
        proc.terminate()
        proc.wait()

    def _open_picks_tab(self, page):
        # See test_pwa_picks_hod.py._open_picks_tab for why CDN scripts + all CSV
        # routes must be stubbed (Root causes 2/3 in the Playwright cloud-testing doc).
        papaparse_js = (ROOT / "tests" / "fixtures" / "papaparse.min.js").read_text(encoding="utf-8")
        page.route("**/cdn.tailwindcss.com/**",
                   lambda r: r.fulfill(body="/* tailwind stub */", content_type="application/javascript"))
        page.route("**/cdnjs.cloudflare.com/**",
                   lambda r: r.fulfill(body=papaparse_js, content_type="application/javascript"))
        page.route("**/picks_latest.csv",
                   lambda r: r.fulfill(body=FIXTURE.read_text(encoding="utf-8"), content_type="text/plain"))
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

    def test_chart_hidden_until_toggled_open(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_picks_tab(page)
            self._expand_first_card(page)

            assert page.locator("[id^='risk-panel-'] iframe").count() == 0, \
                "Chart iframe must not load until the user opens the panel"
            toggle = page.locator(".pick-chart-toggle").first
            assert toggle.count() == 1
            assert "Show chart" in toggle.inner_text()
            browser.close()

    def test_toggle_opens_chart_scoped_to_row_ticker_and_closes(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_picks_tab(page)
            self._expand_first_card(page)

            row_ticker = page.locator(".pick-chart-toggle").first.get_attribute("data-ticker")
            assert row_ticker, "Expected data-ticker on the chart toggle button"

            page.locator(".pick-chart-toggle").first.click()
            page.wait_for_timeout(200)
            iframe = page.locator("[id^='risk-panel-'] iframe").first
            assert iframe.count() == 1
            src = iframe.get_attribute("src")
            assert src.startswith("https://s.tradingview.com/embed-widget/advanced-chart/")
            assert row_ticker in src
            assert "Hide chart" in page.locator(".pick-chart-toggle").first.inner_text()

            page.locator(".pick-chart-toggle").first.click()
            page.wait_for_timeout(200)
            assert page.locator("[id^='risk-panel-'] iframe").count() == 0
            assert "Show chart" in page.locator(".pick-chart-toggle").first.inner_text()
            browser.close()

    def test_chart_state_survives_full_rerender(self):
        """Opening a chart, then triggering a full renderPicks() (view switch), keeps it open."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_picks_tab(page)
            self._expand_first_card(page)
            page.locator(".pick-chart-toggle").first.click()
            page.wait_for_timeout(200)
            assert page.locator("[id^='risk-panel-'] iframe").count() == 1

            # Switch to Focus view and back to All — forces renderPicks() to rebuild the DOM.
            page.locator("[onclick*=\"__setPicksView('focus')\"]").first.click()
            page.wait_for_timeout(300)
            page.locator("[onclick*=\"__setPicksView('all')\"]").first.click()
            page.wait_for_timeout(300)

            self._expand_first_card(page)
            assert page.locator("[id^='risk-panel-'] iframe").count() == 1, \
                "Chart should still be open after a full renderPicks() re-render"
            browser.close()
