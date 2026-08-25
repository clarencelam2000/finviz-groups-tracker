"""
Playwright functional tests for the WS5 §8b P3 personal-watchlist feature in docs/index.html
(build spec: knowledge/... watchlist P3; backend already live on the finviz-positions worker,
NOT touched by this test).

Two surfaces exercised:
  - Morning tab "Your watchlist" section (#watchlist-section, above #morning-list):
    renderWatchlistSection() / watchCardHtml(). Merges the public system read
    (morning_latest.csv rows with list_category='watchlist') with the private owner-bearer
    GET /watchlist feed (level_type/level_value + reference values).
  - Positions tab "＋ Add to watchlist" collapsible: watchAddHtml() / watchAddSubmit()
    -> POST /watchlist.

The live worker is never hit — every finviz-positions.* call is intercepted and fulfilled
with a canned response, same pattern as test_pwa_positions.py.

Covered:
  1. Signed out: #watchlist-section shows the "Your watchlist" sign-in prompt, no cards.
  2. Signed in + one active GET /watchlist entry (level_type=above, level_value=144) merged
     with a matching morning_latest.csv watchlist row (status=triggered, price=145.10) ->
     a watch card renders with ticker, "Triggered" pill, and the violet "Your level" block
     showing "above 144.00" / "now above".
  3. Add flow: Positions tab -> "＋ Add to watchlist" -> fill #watch-ticker -> click "Above"
     seg -> fill #watch-levelvalue -> click "Watch" -> POST /watchlist body asserted exactly.
  4. Gauge toggle: "▾ Hide levels" click flips to "▸ Show levels" and hides the gauge panel.

Run with Playwright installed:
    python3 -m playwright install chromium
    python3 -m pytest tests/test_pwa_watchlist.py -v
"""

import json
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PORT = 8191  # unique port to avoid colliding with other PWA test suites

FAKE_TOKEN = "fake-watch-token-xyz789"

# AXON watchlist row: prior_high/prior_low give the card a real body (not the "Added —
# first morning check lands tomorrow" no-bar-yet state); level_type=above @144 vs
# price=145.10 -> met=True -> "now above".
WATCH_ENTRY = {
    "id": "w1",
    "ticker": "AXON",
    "level_type": "above",
    "level_value": 144.00,
    "sessions_remaining": 7,
    "status": "active",
    "prior_high": 143.00,
    "prior_low": 138.00,
    "atr": 5.00,
    "sma20": None,
    "sma50": None,
}

MORNING_WATCHLIST_CSV = (
    "date,session,collected_at,ticker,group,list_category,trigger,stop,atr,price,open,high,low,change,status,atr_from_lod\n"
    "2026-08-14,morning,2026-08-14T14:05:00Z,AXON,Aerospace & Defense,watchlist,140.00,130.00,5.00,145.10,144.00,145.50,143.80,0.9,triggered,0.26\n"
)


def _launch_server(port: int):
    return subprocess.Popen(
        ["python3", "-m", "http.server", str(port), "--directory", str(ROOT / "docs")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _base_routes(page, morning_csv=MORNING_WATCHLIST_CSV):
    """Stub CDNs + CSVs the same way test_pwa_positions.py does. Route glob form per
    knowledge/investigations/playwright-cloud-session-testing.md ("**/filename.ext")."""
    papaparse_js = (ROOT / "tests" / "fixtures" / "papaparse.min.js").read_text(encoding="utf-8")
    page.route("**/cdn.tailwindcss.com/**",
               lambda r: r.fulfill(body="/* tailwind stub */", content_type="application/javascript"))
    page.route("**/cdnjs.cloudflare.com/**",
               lambda r: r.fulfill(body=papaparse_js, content_type="application/javascript"))
    page.route("**/sessions/morning_latest.csv",
               lambda r: r.fulfill(body=morning_csv, content_type="text/plain"))
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


def _mock_worker(page, login_ok=True, watchlist_rows=None, capture=None):
    """Intercept every finviz-positions.* call this suite needs. `capture` (if given) is a
    list that POST /watchlist bodies get appended to. Path-based globs, per the gotcha in
    test_pwa_positions.py: a host-based glob silently never matches the workers.dev host."""
    if watchlist_rows is None:
        watchlist_rows = []

    def handle_login(route):
        if login_ok:
            route.fulfill(status=200, body=json.dumps({"token": FAKE_TOKEN}),
                          content_type="application/json")
        else:
            route.fulfill(status=401, body=json.dumps({"error": "invalid passphrase"}),
                          content_type="application/json")

    def handle_watchlist(route, request):
        if request.method == "POST":
            if capture is not None:
                capture.append(json.loads(request.post_data or "{}"))
            route.fulfill(status=201, body=json.dumps({"watch": {"id": "w2"}}),
                          content_type="application/json")
        else:  # GET
            route.fulfill(status=200, body=json.dumps({"watchlist": watchlist_rows}),
                          content_type="application/json")

    def handle_watchlist_item(route, request):
        # PATCH/DELETE /watchlist/<id> — not exercised by these tests' assertions but must
        # not 404 if the card's kebab menu fires one incidentally.
        route.fulfill(status=200, body=json.dumps({"ok": True}), content_type="application/json")

    page.route("**/auth/login", handle_login)
    page.route("**/watchlist/**", lambda r: handle_watchlist_item(r, r.request))
    page.route("**/watchlist", lambda r: handle_watchlist(r, r.request))
    # Positions list isn't exercised here but the Positions tab still calls GET /positions on
    # sign-in; stub it to an empty list so renderPositions() doesn't dangle on an unmocked call.
    page.route("**/positions**", lambda r: r.fulfill(
        status=200, body=json.dumps({"positions": []}), content_type="application/json"))


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


def test_signed_out_watchlist_section_shows_signin_no_cards(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        _mock_worker(page)
        _boot(page, signed_in=False)
        page.click("[data-tab='morning']")
        page.wait_for_timeout(500)

        html = page.inner_html("#watchlist-section")
        assert "Your watchlist" in html
        assert "Sign in on the" in html
        assert "Positions tab" in html
        assert "AXON" not in html, "signed-out section must not render any watch cards"
        browser.close()


def test_signed_in_watch_card_shows_ticker_pill_and_your_level(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        _mock_worker(page, watchlist_rows=[WATCH_ENTRY])
        _boot(page, signed_in=True)
        page.click("[data-tab='morning']")
        page.wait_for_timeout(500)

        html = page.inner_html("#watchlist-section")
        assert "AXON" in html
        assert "Triggered" in html
        assert "Your level" in html
        assert "above 144.00" in html
        assert "now above" in html
        browser.close()


def test_signed_in_watch_card_shows_awaiting_first_read_not_no_quote(server):
    """WS-POSITIONS-STATUS (2026-08-25): a watch ticker whose first bar has landed (prior_high/
    prior_low set) but has no morning_latest.csv row yet must show the honest "reference bar
    captured" copy, never a bare "Adding" and never no_quote's "feed missed this ticker" —
    nothing was missed, the classification run just hasn't had a chance to run against this
    ticker's first bar yet."""
    from playwright.sync_api import sync_playwright
    entry = {**WATCH_ENTRY, "ticker": "SMCI"}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page, morning_csv="date,session,collected_at,ticker,group,list_category,trigger,stop,atr,price,open,high,low,change,status,atr_from_lod\n")
        _mock_worker(page, watchlist_rows=[entry])
        _boot(page, signed_in=True)
        page.click("[data-tab='morning']")
        page.wait_for_timeout(500)

        html = page.inner_html("#watchlist-section")
        assert "SMCI" in html
        assert "Reference bar captured" in html
        assert "Morning feed missed this ticker" not in html
        assert "Added — first morning check lands tomorrow" not in html
        browser.close()


def test_add_to_watchlist_flow_posts_correct_payload(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        capture = []
        _mock_worker(page, capture=capture)
        _boot(page, signed_in=True)
        page.click("[data-tab='positions']")
        page.wait_for_timeout(500)

        page.locator("text=＋ Add to watchlist").dispatch_event("click")
        page.wait_for_timeout(300)

        page.fill("#watch-ticker", "msft")
        page.locator("button:has-text('Above')").dispatch_event("click")
        page.wait_for_timeout(200)
        page.fill("#watch-levelvalue", "410.5")

        page.locator("button:has-text('Watch')").dispatch_event("click")
        page.wait_for_timeout(500)

        assert len(capture) == 1, "expected exactly one POST /watchlist"
        payload = capture[0]
        assert payload["ticker"] == "MSFT"
        assert payload["level_type"] == "above"
        assert payload["level_value"] == pytest.approx(410.5)
        browser.close()


def test_gauge_toggle_hides_panel_and_flips_label(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        _mock_worker(page, watchlist_rows=[WATCH_ENTRY])
        _boot(page, signed_in=True)
        page.click("[data-tab='morning']")
        page.wait_for_timeout(500)

        toggle = page.locator("#watch-gauge-toggle-AXON")
        assert toggle.count() == 1, "gauge toggle should render (prior_high/prior_low both present)"
        assert toggle.inner_text() == "▾ Hide levels"

        toggle.dispatch_event("click")
        page.wait_for_timeout(200)

        assert toggle.inner_text() == "▸ Show levels"
        panel_html = page.inner_html("#watch-gauge-panel-AXON")
        assert panel_html.strip() == "", "panel content should be cleared when levels are hidden"
        browser.close()
