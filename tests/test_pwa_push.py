"""
Playwright functional tests for WS5-4b VAPID web-push (PWA frontend half — backend PR A,
worker-positions/, already merged and NOT touched by this test).

Data-less Tier-1 only: the service worker shows one generic notification with no payload;
this suite only exercises the subscription lifecycle affordance rendered in the Positions
tab footer (#pos-alerts, posRenderAlerts()/posEnableAlerts()/posDisableAlerts()).

The live worker is never hit — every finviz-positions.* call is intercepted and fulfilled
with a canned response, same pattern as test_pwa_positions.py.

Covered:
  1. Signed-in Positions tab (empty-positions branch) renders the "Turn on exit alerts"
     footer affordance.
  2. Clicking it with Notification.requestPermission stubbed 'granted' and
     pushManager.subscribe stubbed to a fake subscription fires POST /push/subscribe with
     the expected endpoint+keys body.
  3. iOS + non-standalone + PushManager/Notification absent shows the "Add to Home Screen"
     guidance instead of the enable button.

Run with Playwright installed:
    python3 -m playwright install chromium
    python3 -m pytest tests/test_pwa_push.py -v
"""

import json
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PORT = 8192  # unique port to avoid colliding with other PWA test suites

FAKE_TOKEN = "fake-push-token-def456"

FAKE_SUBSCRIPTION_JSON = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/fake-endpoint-abc",
    "keys": {"p256dh": "fake-p256dh-key", "auth": "fake-auth-key"},
}


def _launch_server(port: int):
    return subprocess.Popen(
        ["python3", "-m", "http.server", str(port), "--directory", str(ROOT / "docs")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _base_routes(page):
    """Same stub set as test_pwa_positions.py — this suite never needs real CSV/picks data,
    only an empty signed-in Positions tab to reach the #pos-alerts footer."""
    papaparse_js = (ROOT / "tests" / "fixtures" / "papaparse.min.js").read_text(encoding="utf-8")
    page.route("**/cdn.tailwindcss.com/**",
               lambda r: r.fulfill(body="/* tailwind stub */", content_type="application/javascript"))
    page.route("**/cdnjs.cloudflare.com/**",
               lambda r: r.fulfill(body=papaparse_js, content_type="application/javascript"))
    page.route("**/sessions/morning_latest.csv", lambda r: r.fulfill(body="", content_type="text/plain"))
    page.route("**/picks_latest.csv",
               lambda r: r.fulfill(body="date,list_category,Ticker\n", content_type="text/plain"))
    page.route("**/snapshots.csv",
               lambda r: r.fulfill(body="date,collected_at,group_type,name,stocks,market_cap,pe,fwd_pe,perf_day,perf_week,perf_month,perf_quarter,perf_half,perf_year,perf_ytd,avg_volume,rel_volume,change\n", content_type="text/plain"))
    page.route("**/deltas.csv", lambda r: r.fulfill(body="date,name\n", content_type="text/plain"))
    page.route("**/fetch_log.csv", lambda r: r.fulfill(body="", content_type="text/plain"))
    page.route("**/releases.json",
               lambda r: r.fulfill(body='{"current":"","releases":[]}', content_type="application/json"))
    page.route("**/finviz_sector_industry_map.json",
               lambda r: r.fulfill(body='{"sectors":{}}', content_type="application/json"))


def _mock_worker(page, subscribe_capture=None, unsubscribe_capture=None):
    def handle_login(route):
        route.fulfill(status=200, body=json.dumps({"token": FAKE_TOKEN}), content_type="application/json")

    def handle_positions(route, request):
        # Empty-positions branch -- this suite doesn't exercise card rendering.
        route.fulfill(status=200, body=json.dumps({"positions": []}), content_type="application/json")

    def handle_subscribe(route, request):
        if subscribe_capture is not None:
            subscribe_capture.append(json.loads(request.post_data or "{}"))
        route.fulfill(status=200, body=json.dumps({"ok": True}), content_type="application/json")

    def handle_unsubscribe(route, request):
        if unsubscribe_capture is not None:
            unsubscribe_capture.append(json.loads(request.post_data or "{}"))
        route.fulfill(status=200, body=json.dumps({"ok": True}), content_type="application/json")

    page.route("**/auth/login", handle_login)
    page.route("**/push/subscribe", lambda r: handle_subscribe(r, r.request))
    page.route("**/push/unsubscribe", lambda r: handle_unsubscribe(r, r.request))
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


def test_signed_in_empty_positions_shows_enable_alerts_affordance(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        _mock_worker(page)
        # Headless Chromium reports Notification.permission='denied' by default (no display
        # server to grant it) -- stub 'default' so this test exercises the enable-button
        # branch rather than the "blocked" branch. Also stub serviceWorker.ready/pushManager:
        # posRenderAlerts() awaits navigator.serviceWorker.ready, and the real registration
        # never resolves in this harness (sw.js 404s -- served from docs/ root, not the
        # '/finviz-groups-tracker/' path it registers under), which would hang the render.
        page.add_init_script(
            """
            window.Notification = { permission: 'default', requestPermission: () => Promise.resolve('default') };
            const fakePushManager = { getSubscription: () => Promise.resolve(null) };
            const fakeRegistration = { pushManager: fakePushManager };
            if (!('serviceWorker' in navigator)) { navigator.serviceWorker = {}; }
            Object.defineProperty(navigator.serviceWorker, 'ready', { get: () => Promise.resolve(fakeRegistration), configurable: true });
            """
        )
        _boot(page, signed_in=True)
        page.click("[data-tab='positions']")
        page.wait_for_timeout(700)

        html = page.inner_html("#pos-alerts")
        assert "Turn on exit alerts" in html
        assert "Get a push when a position hits an exit signal." in html
        browser.close()


def test_enable_alerts_click_posts_subscribe_with_endpoint_and_keys(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        capture = []
        _mock_worker(page, subscribe_capture=capture)

        # Stub Notification + a minimal serviceWorker.ready/pushManager before the app's own
        # SW registration runs -- avoids depending on a real service worker in this headless
        # harness while still exercising posEnableAlerts()'s real subscribe() call path.
        page.add_init_script(
            """
            window.Notification = { permission: 'default', requestPermission: () => Promise.resolve('granted') };
            const fakeSub = {
              endpoint: %s,
              toJSON: () => ({ endpoint: %s, keys: %s }),
            };
            const fakePushManager = {
              getSubscription: () => Promise.resolve(null),
              subscribe: () => Promise.resolve(fakeSub),
            };
            const fakeRegistration = { pushManager: fakePushManager };
            if (!('serviceWorker' in navigator)) { navigator.serviceWorker = {}; }
            Object.defineProperty(navigator.serviceWorker, 'ready', { get: () => Promise.resolve(fakeRegistration), configurable: true });
            if (!('PushManager' in window)) { window.PushManager = function () {}; }
            """
            % (
                json.dumps(FAKE_SUBSCRIPTION_JSON["endpoint"]),
                json.dumps(FAKE_SUBSCRIPTION_JSON["endpoint"]),
                json.dumps(FAKE_SUBSCRIPTION_JSON["keys"]),
            )
        )

        _boot(page, signed_in=True)
        page.click("[data-tab='positions']")
        page.wait_for_timeout(700)

        assert "Turn on exit alerts" in page.inner_html("#pos-alerts")
        page.click("button:has-text('Turn on exit alerts')")
        page.wait_for_timeout(500)

        assert len(capture) == 1, "expected exactly one POST /push/subscribe"
        body = capture[0]
        assert body["endpoint"] == FAKE_SUBSCRIPTION_JSON["endpoint"]
        assert body["keys"] == FAKE_SUBSCRIPTION_JSON["keys"]
        browser.close()


def test_ios_non_standalone_without_push_support_shows_home_screen_guidance(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        _mock_worker(page)

        # Simulate an iOS Safari tab (not installed to Home Screen, no PushManager/Notification
        # support) -- posAlertsSupported() is false and posIsIOS()/!posIsStandalone() is true.
        page.add_init_script(
            """
            Object.defineProperty(window.navigator, 'userAgent', {
              get: () => 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15',
              configurable: true,
            });
            delete window.PushManager;
            delete window.Notification;
            """
        )

        _boot(page, signed_in=True)
        page.click("[data-tab='positions']")
        page.wait_for_timeout(700)

        html = page.inner_html("#pos-alerts")
        assert "Add to Home Screen" in html
        assert "Turn on exit alerts" not in html
        browser.close()
