"""
Playwright functional tests for the WS5 §8a "log a position on any ticker" manual-entry
form (Positions tab) + the Lookup -> Positions redirect.

Rendered by manualEntryHtml()/manualFormHtml()/manualConfirmHtml() in docs/index.html,
reached either by the Positions tab's "+ Log a position manually" expander or by tapping
"Open a position on {SYM} ->" on a ticker's Lookup result. The finviz-positions worker is
never hit for real — every finviz-positions.* call is intercepted and fulfilled with a
canned response, same pattern as tests/test_pwa_positions.py.

Covered:
  1. Signed out: Positions tab shows no manual-entry expander.
  2. Signed in: expander is present, collapsed by default.
  3. Open form, fill ticker/entry/stop(price), Risk $ sizing -> confirm -> POST body has
     entry_price/initial_stop/qty/stop_basis:'manual'/meta.source:'manual'.
  4. Shares sizing mode derives qty directly (no risk input needed to compute qty).
  5. %-stop mode computes the stop price from entry * (1 - pct/100).
  6. Backdate + earnings-days optional fields appear in the payload (entry_date,
     days_to_earnings) when filled, and are omitted/null when left blank.
  7. Lookup tab's "Open a position on {SYM} ->" prefills the Positions-tab form and
     switches tabs.

Run with Playwright installed:
    python3 -m playwright install chromium
    python3 -m pytest tests/test_pwa_manual_entry.py -v
"""

import json
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PORT = 8191  # unique port to avoid colliding with other PWA test suites

FAKE_TOKEN = "fake-pos-token-abc123"


def _launch_server(port: int):
    return subprocess.Popen(
        ["python3", "-m", "http.server", str(port), "--directory", str(ROOT / "docs")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _base_routes(page):
    """Stub CDNs + CSVs (same convention as test_pwa_positions.py's _base_routes). Route
    glob form per knowledge/investigations/playwright-cloud-session-testing.md
    ("**/filename.ext")."""
    papaparse_js = (ROOT / "tests" / "fixtures" / "papaparse.min.js").read_text(encoding="utf-8")
    page.route("**/cdn.tailwindcss.com/**",
               lambda r: r.fulfill(body="/* tailwind stub */", content_type="application/javascript"))
    page.route("**/cdnjs.cloudflare.com/**",
               lambda r: r.fulfill(body=papaparse_js, content_type="application/javascript"))
    page.route("**/sessions/morning_latest.csv", lambda r: r.fulfill(status=404))
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


def _mock_worker(page, login_ok=True, positions_rows=None, capture=None):
    """Intercept every finviz-positions.* call. `capture` (if given) is a list that POST
    /positions bodies get appended to, so tests can assert on the exact payload sent."""
    if positions_rows is None:
        positions_rows = []

    def handle_login(route):
        if login_ok:
            route.fulfill(status=200, body=json.dumps({"token": FAKE_TOKEN}),
                          content_type="application/json")
        else:
            route.fulfill(status=401, body=json.dumps({"error": "invalid passphrase"}),
                          content_type="application/json")

    def handle_positions(route, request):
        if request.method == "POST":
            if capture is not None:
                capture.append(json.loads(request.post_data or "{}"))
            route.fulfill(status=201, body=json.dumps({"position": {"id": "p1"}}),
                          content_type="application/json")
        else:  # GET
            route.fulfill(status=200, body=json.dumps({"positions": positions_rows}),
                          content_type="application/json")

    # Path-based globs (not host-based) — see test_pwa_positions.py's comment for why.
    page.route("**/auth/login", handle_login)
    page.route("**/positions**", lambda r: handle_positions(r, r.request))


def _mock_ticker_lookup(page, body=None):
    """Stub the finviz-ticker-lookup worker's /lookup endpoint used by both the ticker
    resolve line (debounced, inside the manual form) and the Lookup tab itself."""
    if body is None:
        body = json.dumps({
            "symbol": "AAPL", "company_name": "Apple Inc.", "exchange": "NASDAQ",
            "market_cap_b": 3000, "finviz_industry": "Consumer Electronics",
            "finviz_sector": "Technology", "industry_confidence": 0.95,
            "image": None, "etf_kind": None,
        })
    page.route("**/finviz-ticker-lookup.salmonbaby8.workers.dev/lookup*",
               lambda r: r.fulfill(body=body, content_type="application/json"))


def _boot(page, signed_in=False):
    page.add_init_script(
        "try { localStorage.clear(); localStorage.setItem('fvt_intro_seen_v3','true');"
        + (f" localStorage.setItem('fv_pos_token','{FAKE_TOKEN}');" if signed_in else "")
        + " } catch(e){}"
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


def _open_form(page):
    page.click("[data-tab='positions']")
    page.wait_for_timeout(300)
    page.locator("text=＋ Log a position manually").dispatch_event("click")
    page.wait_for_timeout(200)


def _fill_price_stop_risk(page, ticker="NVDA", entry="120", stop="110", risk="500"):
    page.fill("#manual-ticker", ticker)
    page.fill("#manual-entry", entry)
    page.fill("#manual-stopprice", stop)
    page.fill("#manual-risk", risk)
    page.wait_for_timeout(100)


def test_signed_out_no_manual_form(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        _mock_worker(page)
        _mock_ticker_lookup(page)
        _boot(page, signed_in=False)
        page.click("[data-tab='positions']")
        page.wait_for_timeout(300)
        html = page.inner_html("#positions-content")
        assert "Log a position manually" not in html
        browser.close()


def test_signed_in_expander_present_and_collapsed(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        _mock_worker(page)
        _mock_ticker_lookup(page)
        _boot(page, signed_in=True)
        page.click("[data-tab='positions']")
        page.wait_for_timeout(300)
        html = page.inner_html("#positions-content")
        assert "＋ Log a position manually" in html
        assert "manual-ticker" not in html  # form itself not yet mounted
        browser.close()


def test_manual_entry_risk_sizing_posts_correct_payload(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        capture = []
        _mock_worker(page, capture=capture)
        _mock_ticker_lookup(page)
        _boot(page, signed_in=True)
        _open_form(page)

        _fill_price_stop_risk(page, ticker="nvda", entry="120", stop="110", risk="500")
        # riskShare = 10, qty = floor(500/10) = 50
        readout = page.inner_text("#manual-position")
        assert "50 sh" in readout

        page.click("text=I took it →")
        page.wait_for_timeout(300)
        html = page.inner_html("#positions-content")
        assert "Log NVDA" in html
        assert "entry $120.00" in html
        assert "stop $110.00" in html
        assert "(Manual)" in html
        assert "50 sh" in html

        page.click("text=Confirm — log it")
        page.wait_for_timeout(400)

        assert len(capture) == 1, "expected exactly one POST /positions"
        payload = capture[0]
        assert payload["ticker"] == "NVDA"
        assert payload["entry_price"] == pytest.approx(120.0)
        assert payload["initial_stop"] == pytest.approx(110.0)
        assert payload["qty"] == 50
        assert payload["stop_basis"] == "manual"
        assert payload["meta"] == {"source": "manual"}

        # Confirmed POST resets the form back to the collapsed expander.
        html = page.inner_html("#positions-content")
        assert "＋ Log a position manually" in html
        browser.close()


def test_shares_sizing_derives_risk(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        capture = []
        _mock_worker(page, capture=capture)
        _mock_ticker_lookup(page)
        _boot(page, signed_in=True)
        _open_form(page)

        page.fill("#manual-ticker", "MSFT")
        page.fill("#manual-entry", "400")
        page.fill("#manual-stopprice", "380")
        page.locator("text=Shares").dispatch_event("click")
        page.wait_for_timeout(150)
        page.fill("#manual-qty", "25")
        page.wait_for_timeout(100)

        # riskShare=20, qty=25 -> total risk = 500
        page.click("text=I took it →")
        page.wait_for_timeout(300)
        html = page.inner_html("#positions-content")
        assert "25 sh" in html
        assert "risk $500" in html

        page.click("text=Confirm — log it")
        page.wait_for_timeout(400)
        assert len(capture) == 1
        payload = capture[0]
        assert payload["ticker"] == "MSFT"
        assert payload["qty"] == 25
        assert payload["initial_stop"] == pytest.approx(380.0)
        browser.close()


def test_pct_stop_mode_computes_stop_price(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        capture = []
        _mock_worker(page, capture=capture)
        _mock_ticker_lookup(page)
        _boot(page, signed_in=True)
        _open_form(page)

        page.fill("#manual-ticker", "AMD")
        page.fill("#manual-entry", "200")
        page.locator("text=% below").dispatch_event("click")
        page.wait_for_timeout(150)
        page.fill("#manual-stoppct", "10")
        page.fill("#manual-risk", "200")
        page.wait_for_timeout(100)

        # stop = 200 * (1 - 0.10) = 180; riskShare = 20; qty = floor(200/20) = 10
        page.click("text=I took it →")
        page.wait_for_timeout(300)
        html = page.inner_html("#positions-content")
        assert "stop $180.00" in html
        assert "10 sh" in html

        page.click("text=Confirm — log it")
        page.wait_for_timeout(400)
        assert len(capture) == 1
        payload = capture[0]
        assert payload["initial_stop"] == pytest.approx(180.0)
        assert payload["qty"] == 10
        browser.close()


def test_backdate_and_earnings_appear_in_payload(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        capture = []
        _mock_worker(page, capture=capture)
        _mock_ticker_lookup(page)
        _boot(page, signed_in=True)
        _open_form(page)

        _fill_price_stop_risk(page, ticker="TSLA", entry="250", stop="230", risk="400")
        page.fill("#manual-entrydate", "2026-08-10")
        page.fill("#manual-earningsdays", "4")
        page.wait_for_timeout(100)

        page.click("text=I took it →")
        page.wait_for_timeout(300)
        page.click("text=Confirm — log it")
        page.wait_for_timeout(400)

        assert len(capture) == 1
        payload = capture[0]
        assert payload["entry_date"] == "2026-08-10"
        assert payload["days_to_earnings"] == 4
        browser.close()


def test_backdate_and_earnings_omitted_when_blank(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        capture = []
        _mock_worker(page, capture=capture)
        _mock_ticker_lookup(page)
        _boot(page, signed_in=True)
        _open_form(page)

        _fill_price_stop_risk(page, ticker="TSLA", entry="250", stop="230", risk="400")
        page.click("text=I took it →")
        page.wait_for_timeout(300)
        page.click("text=Confirm — log it")
        page.wait_for_timeout(400)

        assert len(capture) == 1
        payload = capture[0]
        assert "entry_date" not in payload
        assert payload["days_to_earnings"] is None
        browser.close()


def test_lookup_open_position_prefills_form(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        _mock_worker(page)
        _mock_ticker_lookup(page)
        _boot(page, signed_in=True)

        page.click("[data-tab='lookup']")
        page.fill("#ticker-input", "AAPL")
        page.locator("#ticker-submit").click()
        page.wait_for_timeout(800)

        page.click("text=Open a position on AAPL →")
        page.wait_for_timeout(300)

        # Redirected to the Positions tab with the form open and ticker prefilled.
        assert page.locator("[data-tab='positions']").get_attribute("class") is not None
        html = page.inner_html("#positions-content")
        assert "manual-ticker" in html
        ticker_val = page.input_value("#manual-ticker")
        assert ticker_val == "AAPL"
        browser.close()
