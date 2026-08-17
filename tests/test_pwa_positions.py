"""
Playwright functional tests for the WS5 phase 1 Positions tab + "I took it" real-write flow
(spec: WS5-1-PWA implementation spec, backend #309 — finviz-positions worker, already live
and merged under worker-positions/, NOT touched by this test).

Rendered by renderPositions()/ws5CardHtml()/ws5TicketHtml-adjacent helpers in docs/index.html,
reached either by the Positions tab itself or by tapping "I took it" on an actionable Morning
card (docs/CLAUDE.md § Morning tab). The live worker is never hit — every finviz-positions.*
call is intercepted and fulfilled with a canned response.

Covered:
  1. Signed out: Positions tab shows the sign-in card; tapping "I took it" on Morning shows
     the sign-in note instead of writing (no POST /positions).
  2. Sign-in success renders the open-positions list (mocked GET, 1 row) with correct fields.
  3. Sign-in with the wrong passphrase (mocked 401) shows "Wrong passphrase".
  4. Signed in: "I took it" shows the inline confirm step with the correct entry/stop/qty/risk
     line, Confirm posts the expected payload (ticker upper, stop_basis mapped, qty math), and
     the card flips to "✓ Logged" on the mocked 201.
  5. Cancel reverts the confirm step back to the plain button.

Run with Playwright installed:
    python3 -m playwright install chromium
    python3 -m pytest tests/test_pwa_positions.py -v
"""

import json
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MORNING_FIXTURE = ROOT / "tests" / "fixtures" / "ws4_morning.csv"
PORT = 8190  # unique port to avoid colliding with other PWA test suites

FAKE_TOKEN = "fake-pos-token-abc123"

# AXON: price=613.90, prior_low stop=597.10 -> riskShare=16.80, default $500 risk
# -> qty = floor(500/16.80) = 29, risk total = round(16.80*29) = 487.
EXPECTED_ENTRY = 613.90
EXPECTED_STOP = 597.10
EXPECTED_QTY = 29
EXPECTED_RISK = 487


def _launch_server(port: int):
    return subprocess.Popen(
        ["python3", "-m", "http.server", str(port), "--directory", str(ROOT / "docs")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _base_routes(page):
    """Stub CDNs + CSVs the same way test_pwa_trade_ticket.py does (empty picks/snapshots —
    this suite never needs an EOD picks join; prior_low stop basis only needs the morning
    fixture itself). Route glob form per
    knowledge/investigations/playwright-cloud-session-testing.md ("**/filename.ext")."""
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

    # Path-based globs: only the finviz-positions worker uses these paths, and a "**/host.*/exact"
    # glob does not reliably match a multi-label workers.dev host (the trailing-`**` positions
    # pattern did, the exact /auth/login one did not). Path-only is unambiguous here.
    page.route("**/auth/login", handle_login)
    page.route("**/positions**", lambda r: handle_positions(r, r.request))


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


def test_signed_out_positions_tab_shows_signin(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        _mock_worker(page)
        _boot(page, signed_in=False)
        page.click("[data-tab='positions']")
        page.wait_for_timeout(300)
        html = page.inner_html("#positions-content")
        assert "Track your positions" in html
        assert "pos-passphrase" in html
        browser.close()


def test_signed_out_take_it_shows_signin_note_no_post(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        capture = []
        _mock_worker(page, capture=capture)
        _boot(page, signed_in=False)
        page.click("[data-tab='morning']")
        page.wait_for_timeout(500)

        page.click("text=I took it → >> nth=0")
        page.wait_for_timeout(300)
        html = page.inner_html("#morning-list")
        assert "Sign in on the Positions tab to log trades" in html
        assert capture == [], "must not POST /positions while signed out"
        browser.close()


def test_signin_success_renders_open_positions(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        row = {
            "ticker": "NVDA", "entry_price": 120.50, "initial_stop": 110.00,
            "current_stop": 110.00, "qty": 40, "remaining_qty": 40,
            "stop_basis": "prior_day_low", "entry_date": "2026-08-12",
            "meta": {"source": "picks"}, "state": "open",
        }
        _mock_worker(page, positions_rows=[row])
        _boot(page, signed_in=False)
        page.click("[data-tab='positions']")
        page.wait_for_timeout(300)

        page.fill("#pos-passphrase", "correct-horse")
        page.locator("button:has-text('Sign in')").dispatch_event("click")
        page.wait_for_timeout(500)

        html = page.inner_html("#positions-content")
        assert "Open positions" in html
        assert "NVDA" in html
        assert "120.50" in html
        assert "110.00" in html
        assert "Prior low" in html
        assert "40" in html
        assert "No open positions" not in html
        browser.close()


def test_managing_and_closing_positions_still_render(server):
    # Regression: the tab used to call GET /positions?state=open, which excludes anything the
    # advance() engine has moved past its first bar (open -> managing) or flagged for exit
    # (-> closing) — a live position would silently vanish once the daily sweep advanced it.
    # See docs/CLAUDE.md § Positions tab for the 2026-08-17 fix.
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        rows = [
            {"ticker": "NVDA", "entry_price": 120.50, "initial_stop": 110.00,
             "current_stop": 110.00, "qty": 40, "remaining_qty": 40,
             "stop_basis": "prior_day_low", "entry_date": "2026-08-12",
             "meta": {"source": "picks"}, "state": "managing"},
            {"ticker": "AXON", "entry_price": 613.90, "initial_stop": 597.10,
             "current_stop": 597.10, "qty": 29, "remaining_qty": 29,
             "stop_basis": "prior_day_low", "entry_date": "2026-08-10",
             "meta": {"source": "picks"}, "state": "closing"},
            {"ticker": "OLD", "entry_price": 50.00, "initial_stop": 45.00,
             "current_stop": 45.00, "qty": 10, "remaining_qty": 10,
             "stop_basis": "prior_day_low", "entry_date": "2026-08-01",
             "meta": {"source": "picks"}, "state": "closed"},
        ]
        _mock_worker(page, positions_rows=rows)
        _boot(page, signed_in=True)
        page.click("[data-tab='positions']")
        page.wait_for_timeout(500)

        html = page.inner_html("#positions-content")
        assert "NVDA" in html, "a 'managing' position must still render"
        assert "AXON" in html, "a 'closing' position must still render"
        assert "OLD" not in html, "a 'closed' position must not render"
        browser.close()


def test_signin_wrong_passphrase_shows_error(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        _mock_worker(page, login_ok=False)
        _boot(page, signed_in=False)
        page.click("[data-tab='positions']")
        page.wait_for_timeout(300)

        page.fill("#pos-passphrase", "wrong-guess")
        page.locator("button:has-text('Sign in')").dispatch_event("click")
        page.wait_for_timeout(500)

        assert page.inner_text("#pos-login-error") == "Wrong passphrase"
        # Must stay on the sign-in card, not flip to the open-positions view.
        assert "Track your positions" in page.inner_html("#positions-content")
        browser.close()


def test_signed_in_take_it_confirm_flow_posts_correct_payload(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        capture = []
        _mock_worker(page, capture=capture)
        _boot(page, signed_in=True)
        page.click("[data-tab='morning']")
        page.wait_for_timeout(500)

        page.click("text=I took it → >> nth=0")
        page.wait_for_timeout(300)
        html = page.inner_html("#morning-list")
        assert f"entry ${EXPECTED_ENTRY:.2f}" in html
        assert f"stop ${EXPECTED_STOP:.2f}" in html
        assert "(Prior low)" in html
        assert f"{EXPECTED_QTY} sh" in html
        assert f"risk ${EXPECTED_RISK}" in html
        assert "Confirm — log it" in html

        page.click("text=Confirm — log it")
        page.wait_for_timeout(500)

        assert len(capture) == 1, "expected exactly one POST /positions"
        payload = capture[0]
        assert payload["ticker"] == "AXON"
        assert payload["entry_price"] == pytest.approx(EXPECTED_ENTRY)
        assert payload["initial_stop"] == pytest.approx(EXPECTED_STOP)
        assert payload["qty"] == EXPECTED_QTY
        assert payload["stop_basis"] == "prior_day_low"
        assert payload["meta"] == {"source": "picks"}

        html = page.inner_html("#morning-list")
        assert "✓ Logged" in html
        assert "view in Positions" in html
        browser.close()


def test_cancel_reverts_to_button(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        capture = []
        _mock_worker(page, capture=capture)
        _boot(page, signed_in=True)
        page.click("[data-tab='morning']")
        page.wait_for_timeout(500)

        page.click("text=I took it → >> nth=0")
        page.wait_for_timeout(300)
        assert "Confirm — log it" in page.inner_html("#morning-list")

        page.click("text=Cancel")
        page.wait_for_timeout(300)
        html = page.inner_html("#morning-list")
        assert "Confirm — log it" not in html
        assert "I took it →" in html
        assert capture == [], "Cancel must never POST"
        browser.close()


def test_confirm_double_submit_guard_posts_once(server):
    # Regression for the submitting-guard fix (PR #311 review): two confirms fired in the same
    # JS tick (a double-tap) must create only ONE position. The guard is synchronous — the first
    # call sets card.submitting before its await, so the second returns immediately.
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        capture = []
        _mock_worker(page, capture=capture)
        _boot(page, signed_in=True)
        page.click("[data-tab='morning']")
        page.wait_for_timeout(500)

        page.click("text=I took it → >> nth=0")
        page.wait_for_timeout(300)
        assert "Confirm — log it" in page.inner_html("#morning-list")

        # Fire confirm twice synchronously — simulates a double-tap before the first resolves.
        page.evaluate("() => { window.ws5ConfirmTakeIt('AXON'); window.ws5ConfirmTakeIt('AXON'); }")
        page.wait_for_timeout(500)

        assert len(capture) == 1, f"double-submit guard failed: {len(capture)} POSTs"
        assert "✓ Logged" in page.inner_html("#morning-list")
        browser.close()


def test_positions_load_error_shows_retry(server):
    # Regression for the positionsError fix (PR #311 review): a non-401 GET failure must show
    # an explicit error + retry, NOT the "no open positions" empty state.
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        page.route("**/auth/login", lambda r: r.fulfill(
            status=200, body=json.dumps({"token": FAKE_TOKEN}), content_type="application/json"))
        page.route("**/positions**", lambda r: r.fulfill(
            status=500, body=json.dumps({"error": "boom"}), content_type="application/json"))
        _boot(page, signed_in=True)
        page.click("[data-tab='positions']")
        page.wait_for_timeout(600)

        html = page.inner_html("#positions-content")
        assert "Couldn't load positions" in html
        assert "Try again" in html
        assert "No open positions" not in html, "a fetch error must not read as an empty portfolio"
        browser.close()
