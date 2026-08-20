"""
Playwright functional tests for the WS5-8 (PR-2) pre-close advisory band + receipt on the
Positions tab (spec: LOCKED SPEC ws5-8-pwa-spec.md, design authority
planning/mocks/ws5-8-preclose-read.html, backend PR-1 GET /positions/preclose on
worker-positions — not touched by this test, mocked here).

Rendered by advisoryBandHtml() in docs/index.html, fed by posLoadPreclose() (fired alongside
posLoadPositions() from renderPositions()'s loading branch). The live worker is never hit —
every finviz-positions.* call is intercepted and fulfilled with a canned response.

Covered (per the LOCKED SPEC § Tests):
  1. Band renders with an act row + a heads-up row from a seeded items payload; amber styling
     present (border-amber-500/40 bg-amber-500/[.05]).
  2. Receipt line renders (emerald) when ran_at is set and items is empty.
  3. Band/receipt is ABSENT (zero pixels contributed) when ran_at is null.
  4. Read-only: no confirm/still-holding buttons render inside the band.

Run with Playwright installed:
    python3 -m playwright install chromium
    python3 -m pytest tests/test_pwa_preclose.py -v
"""

import json
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MORNING_FIXTURE = ROOT / "tests" / "fixtures" / "ws4_morning.csv"
PORT = 8191  # unique port — avoid colliding with test_pwa_positions.py's 8190

FAKE_TOKEN = "fake-pos-token-abc123"

ITEMS_PAYLOAD = {
    "ran_at": "2026-08-20T19:32:00Z",  # 3:32 PM ET (EDT, UTC-4)
    "n_checked": 3,
    "n_flagged": 2,
    "items": [
        {
            "trade_id": "t-eog", "ticker": "EOG", "category": "exit",
            "severity": "heads_up", "signal": "close_below_50ma",
            "price": 141.80, "ref_level": 142.90,
        },
        {
            "trade_id": "t-nvt", "ticker": "NVT", "category": "exit",
            "severity": "act", "signal": "stop_hit",
            "price": 167.44, "ref_level": 168.00,
        },
    ],
}

RECEIPT_PAYLOAD = {"ran_at": "2026-08-20T19:40:00Z", "n_checked": 4, "n_flagged": 0, "items": []}

ABSENT_PAYLOAD = {"ran_at": None, "n_checked": 0, "n_flagged": 0, "items": []}

ONE_POSITION = [{
    "trade_id": "p1", "ticker": "AVGO", "state": "managing",
    "entry_price": 100.0, "initial_stop": 90.0, "current_stop": 100.0,
    "initial_qty": 10, "remaining_qty": 10, "last_close": 105.0,
    "last_bar_date": "2026-08-19", "events": [], "stop_ack_value": 100.0,
}]


def _launch_server(port: int):
    return subprocess.Popen(
        ["python3", "-m", "http.server", str(port), "--directory", str(ROOT / "docs")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _base_routes(page):
    """Same stubbing pattern as test_pwa_positions.py's _base_routes — CDNs + empty CSVs, this
    suite never needs real group/picks data."""
    papaparse_js = (ROOT / "tests" / "fixtures" / "papaparse.min.js").read_text(encoding="utf-8")
    page.route("**/cdn.tailwindcss.com/**",
               lambda r: r.fulfill(body="/* tailwind stub */", content_type="application/javascript"))
    page.route("**/cdnjs.cloudflare.com/**",
               lambda r: r.fulfill(body=papaparse_js, content_type="application/javascript"))
    page.route("**/sessions/morning_latest.csv",
               lambda r: r.fulfill(body=MORNING_FIXTURE.read_text(encoding="utf-8"), content_type="text/plain"))
    page.route("**/picks_latest.csv",
               lambda r: r.fulfill(body="date,list_category,Ticker\n", content_type="text/plain"))
    page.route("**/snapshots.csv",
               lambda r: r.fulfill(body="date,collected_at,group_type,name,stocks,market_cap,pe,fwd_pe,perf_day,perf_week,perf_month,perf_quarter,perf_half,perf_year,perf_ytd,avg_volume,rel_volume,change\n", content_type="text/plain"))
    page.route("**/deltas.csv",
               lambda r: r.fulfill(body="date,name\n", content_type="text/plain"))
    page.route("**/fetch_log.csv", lambda r: r.fulfill(body="", content_type="text/plain"))
    page.route("**/releases.json",
               lambda r: r.fulfill(body='{"current":"","releases":[]}', content_type="application/json"))
    page.route("**/finviz_sector_industry_map.json",
               lambda r: r.fulfill(body='{"sectors":{}}', content_type="application/json"))


def _mock_worker(page, preclose_payload, positions_rows=None):
    """Intercept auth/login, GET /positions/preclose, and GET /positions. The preclose route
    MUST be registered before the broader "**/positions**" glob (Playwright matches routes in
    registration order — same discipline as test_pwa_positions.py's ack/confirm/still-holding
    stubs) or the plain positions handler would swallow it."""
    if positions_rows is None:
        positions_rows = []

    def handle_login(route):
        route.fulfill(status=200, body=json.dumps({"token": FAKE_TOKEN}), content_type="application/json")

    def handle_preclose(route):
        route.fulfill(status=200, body=json.dumps(preclose_payload), content_type="application/json")

    def handle_positions(route, request):
        if request.method == "POST":
            route.fulfill(status=201, body=json.dumps({"position": {"id": "p1"}}), content_type="application/json")
        else:
            route.fulfill(status=200, body=json.dumps({"positions": positions_rows}), content_type="application/json")

    page.route("**/auth/login", handle_login)
    page.route("**/positions/preclose", lambda r: handle_preclose(r))
    page.route("**/positions**", lambda r: handle_positions(r, r.request))


def _boot(page):
    page.add_init_script(
        "try { localStorage.clear(); localStorage.setItem('fvt_intro_seen_v3','true');"
        f" localStorage.setItem('fv_pos_token','{FAKE_TOKEN}'); }} catch(e){{}}"
    )
    page.goto(f"http://localhost:{PORT}/", wait_until="domcontentloaded")
    page.wait_for_timeout(1000)


@pytest.fixture(scope="module")
def server():
    proc = _launch_server(PORT)
    time.sleep(1)
    yield proc
    proc.terminate()
    proc.wait()


def test_band_renders_act_and_heads_up_rows(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        _mock_worker(page, ITEMS_PAYLOAD, positions_rows=ONE_POSITION)
        _boot(page)
        page.click("[data-tab='positions']")
        page.wait_for_timeout(500)
        # Expand the band (collapsed by default) to see the per-item rows.
        page.click("text=Pre-close read")
        page.wait_for_timeout(200)
        html = page.inner_html("#positions-content")
        assert "Pre-close read" in html
        assert "border-amber-500/40" in html
        assert "Act now" in html
        assert "Heads-up" in html
        assert "NVT" in html and "EOG" in html
        assert "167.44" in html
        assert "Real intraday exit" in html
        assert "may firm up at the bell" in html
        browser.close()


def test_receipt_renders_when_calm_day(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        _mock_worker(page, RECEIPT_PAYLOAD, positions_rows=ONE_POSITION)
        _boot(page)
        page.click("[data-tab='positions']")
        page.wait_for_timeout(500)
        html = page.inner_html("#positions-content")
        assert "Pre-close checked" in html
        assert "nothing to act on before the close" in html
        assert "4 position" in html
        # No band toggle chrome on the calm-day receipt.
        assert "Pre-close read" not in html
        browser.close()


def test_band_and_receipt_absent_when_ran_at_null(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        _mock_worker(page, ABSENT_PAYLOAD, positions_rows=ONE_POSITION)
        _boot(page)
        page.click("[data-tab='positions']")
        page.wait_for_timeout(500)
        html = page.inner_html("#positions-content")
        assert "Pre-close read" not in html
        assert "Pre-close checked" not in html
        browser.close()


def test_band_is_read_only_no_confirm_buttons(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        _mock_worker(page, ITEMS_PAYLOAD, positions_rows=ONE_POSITION)
        _boot(page)
        page.click("[data-tab='positions']")
        page.wait_for_timeout(500)
        page.click("text=Pre-close read")
        page.wait_for_timeout(200)
        band = page.query_selector("text=Pre-close read >> xpath=ancestor::div[contains(@class,'border-amber-500/40')]")
        assert band is not None
        band_html = band.inner_html()
        assert "onclick=\"posConfirmExit" not in band_html
        assert "onclick=\"posStillHolding" not in band_html
        assert "Confirm this fill" not in band_html
        assert "Still holding" not in band_html
        browser.close()
