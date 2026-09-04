"""
Playwright functional tests for the inline "+ Watch" quick-add — Picks / Morning-picks /
Lookup / Watchlist edit-level, built on top of the existing WS5 §8b P3 watchlist backend
(state.watchAdd's Positions-tab-only collapsible, watchAddApi() -> POST /watchlist).

Rendered by quickWatchButtonHtml()/quickWatchPanelHtml() in docs/index.html, mounted at:
  - Picks tab row action bar (renderPickRow -> quickWatchButtonHtml/'qw_pick_<key>')
  - Morning tab Picks-subtab card (morningChartAffordance -> 'qw_morning_<ticker>')
  - Lookup tab ticker result (renderLookup -> 'qw_lookup_<symbol>')
  - Morning tab Watchlist-subtab card's kebab "Edit level" (watchEditLevel ->
    'qw_watch_<ticker>') — previously routed through state.watchAdd + switchTab('positions');
    this now opens the same inline editor in place instead of leaving the tab.

The finviz-positions worker is never hit for real — every finviz-positions.* call is
intercepted, same pattern as test_pwa_watchlist.py / test_pwa_manual_entry.py.

Covered:
  1. Picks row, signed out: "+ Watch" button opens an inline sign-in nudge, zero POSTs.
  2. Picks row, signed in, not yet watched: one tap POSTs {ticker} only (no level) — the add
     persists on the first tap, matching "instant add, refine after" — and the panel shows a
     receipt + the optional level-of-interest form.
  3. Setting a level afterward ("Above" + price + Save level) fires a SECOND, separate POST
     with ticker + level_type + level_value — confirming the level is optional refinement,
     not required to persist the original add.
  4. Already-watched ticker: button reads "✓ Watching"; tapping it opens straight into the
     level editor seeded from the existing entry, with zero POSTs until Save is pressed.
  5. Lookup tab ticker result renders the same button and it works end to end.
  6. Watchlist-subtab "Edit level" opens the panel inline on the Morning tab — never navigates
     to the Positions tab — and Save posts the upsert.

Run with Playwright installed:
    python3 -m playwright install chromium
    python3 -m pytest tests/test_pwa_quick_watch.py -v
"""

import csv
import io
import json
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PORT = 8193  # unique port to avoid colliding with other PWA test suites
FIXTURE = ROOT / "tests" / "fixtures" / "picks_latest.csv"

FAKE_TOKEN = "fake-qw-token-def456"

WATCH_ENTRY = {
    "id": 5,
    "ticker": "ANET",
    "level_type": "below",
    "level_value": 150.00,
    "sessions_remaining": 9,
    "status": "active",
    "prior_high": 170.00,
    "prior_low": 160.00,
    "atr": 5.00,
    "sma20": None,
    "sma50": None,
}

MORNING_WATCHLIST_CSV = (
    "date,session,collected_at,ticker,group,list_category,trigger,stop,atr,price,open,high,low,change,status,atr_from_lod\n"
    "2026-08-14,morning,2026-08-14T14:05:00Z,ANET,Computer Hardware,watchlist,170.00,160.00,5.00,172.10,171.00,172.50,170.80,0.9,triggered,0.26\n"
)


def _single_row_picks_csv() -> str:
    """One-row picks_latest.csv (the ANET row, unmodified) — same helper shape as
    test_pwa_picks_hod.py's _single_row_csv, trimmed to no-override since these tests don't
    need specific field values, just a real expandable row."""
    with FIXTURE.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames
        rows = list(reader)
    row = next(r for r in rows if r["ticker"] == "ANET")
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols)
    writer.writeheader()
    writer.writerow(row)
    return buf.getvalue()


def _launch_server(port: int):
    return subprocess.Popen(
        ["python3", "-m", "http.server", str(port), "--directory", str(ROOT / "docs")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _base_routes(page, morning_csv=None):
    papaparse_js = (ROOT / "tests" / "fixtures" / "papaparse.min.js").read_text(encoding="utf-8")
    page.route("**/cdn.tailwindcss.com/**",
               lambda r: r.fulfill(body="/* tailwind stub */", content_type="application/javascript"))
    page.route("**/cdnjs.cloudflare.com/**",
               lambda r: r.fulfill(body=papaparse_js, content_type="application/javascript"))
    page.route("**/sessions/morning_latest.csv",
               lambda r: r.fulfill(status=404) if morning_csv is None
               else r.fulfill(body=morning_csv, content_type="text/plain"))
    page.route("**/pre_close_latest.csv",
               lambda r: r.fulfill(body="date,session,collected_at,ticker,group,list_category,trigger,stop,atr,price,open,high,low,change,status,atr_from_lod\n", content_type="text/plain"))
    page.route("**/picks_latest.csv",
               lambda r: r.fulfill(body=_single_row_picks_csv(), content_type="text/plain"))
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
    """Intercept finviz-positions.* calls. `capture` (if given) collects every POST /watchlist
    body — used to assert instant-add fires with ticker only, and a level save is a separate
    call, same convention as test_pwa_watchlist.py's capture list."""
    if watchlist_rows is None:
        watchlist_rows = []

    def handle_login(route):
        status = 200 if login_ok else 401
        body = {"token": FAKE_TOKEN} if login_ok else {"error": "invalid passphrase"}
        route.fulfill(status=status, body=json.dumps(body), content_type="application/json")

    def handle_watchlist(route, request):
        if request.method == "POST":
            if capture is not None:
                capture.append(json.loads(request.post_data or "{}"))
            route.fulfill(status=201, body=json.dumps({"watch": {"id": 6}}), content_type="application/json")
        else:  # GET
            route.fulfill(status=200, body=json.dumps({"watchlist": watchlist_rows}), content_type="application/json")

    page.route("**/auth/login", handle_login)
    page.route("**/watchlist/**", lambda r: r.fulfill(status=200, body=json.dumps({"ok": True}), content_type="application/json"))
    page.route("**/watchlist", lambda r: handle_watchlist(r, r.request))
    page.route("**/positions**", lambda r: r.fulfill(status=200, body=json.dumps({"positions": []}), content_type="application/json"))


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


def _open_picks_tab_and_expand(page):
    page.click("[data-tab='picks']")
    page.wait_for_timeout(400)
    card = page.locator("[onclick*='__togglePickRow']").first
    card.click()
    page.wait_for_timeout(300)


def test_picks_row_signed_out_opens_signin_nudge(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        capture = []
        _mock_worker(page, capture=capture)
        _boot(page, signed_in=False)
        _open_picks_tab_and_expand(page)

        btn = page.locator("button:has-text('＋ Watch')").first
        assert btn.count() == 1
        btn.dispatch_event("click")
        page.wait_for_timeout(300)

        html = page.inner_html("#picks-list")
        assert "sign in on the Positions tab" in html
        assert len(capture) == 0, "no add attempted while signed out"
        browser.close()


def test_picks_row_instant_add_posts_ticker_only(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        capture = []
        _mock_worker(page, capture=capture)
        _boot(page, signed_in=True)
        _open_picks_tab_and_expand(page)

        page.locator("button:has-text('＋ Watch')").first.dispatch_event("click")
        page.wait_for_timeout(400)

        assert len(capture) == 1, "the tap alone must persist the add — no second tap required"
        assert capture[0] == {"ticker": "ANET"}, "instant add carries no level"

        html = page.inner_html("#picks-list")
        assert "Added to your watchlist" in html
        assert "✓ Watching" in html
        browser.close()


def test_picks_row_save_level_is_a_separate_post(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        capture = []
        _mock_worker(page, capture=capture)
        _boot(page, signed_in=True)
        _open_picks_tab_and_expand(page)

        page.locator("button:has-text('＋ Watch')").first.dispatch_event("click")
        page.wait_for_timeout(400)
        assert len(capture) == 1

        page.locator("button:has-text('Above')").first.dispatch_event("click")
        page.wait_for_timeout(150)
        page.locator("input[placeholder='Price']").first.fill("175.5")
        page.locator("button:has-text('Save level')").first.dispatch_event("click")
        page.wait_for_timeout(400)

        assert len(capture) == 2, "the level save is a second, independent POST"
        assert capture[1]["ticker"] == "ANET"
        assert capture[1]["level_type"] == "above"
        assert capture[1]["level_value"] == pytest.approx(175.5)
        browser.close()


def test_picks_row_already_watched_shows_watching_no_repost(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        capture = []
        _mock_worker(page, watchlist_rows=[WATCH_ENTRY], capture=capture)
        _boot(page, signed_in=True)
        _open_picks_tab_and_expand(page)
        # Proactive fetch (ensureWatchlistLoaded) needs a moment to land before re-render.
        page.wait_for_timeout(400)

        btn = page.locator("button:has-text('✓ Watching')").first
        assert btn.count() == 1, "already-watched ticker must not offer a plain + Watch button"
        btn.dispatch_event("click")
        page.wait_for_timeout(300)

        assert len(capture) == 0, "opening the editor for an already-watched ticker must not re-POST"
        html = page.inner_html("#picks-list")
        assert "Below" in html  # seeded from WATCH_ENTRY's level_type
        browser.close()


def test_lookup_ticker_result_has_working_watch_button(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page)
        capture = []
        _mock_worker(page, capture=capture)
        page.route("**/finviz-ticker-lookup.salmonbaby8.workers.dev/lookup*", lambda r: r.fulfill(
            body=json.dumps({
                "symbol": "AAPL", "company_name": "Apple Inc.", "exchange": "NASDAQ",
                "market_cap_b": 3000, "finviz_industry": "Consumer Electronics",
                "finviz_sector": "Technology", "industry_confidence": 0.95,
                "image": None, "etf_kind": None,
            }), content_type="application/json"))
        _boot(page, signed_in=True)

        page.click("[data-tab='lookup']")
        page.fill("#ticker-input", "AAPL")
        page.locator("#ticker-submit").click()
        page.wait_for_timeout(800)

        btn = page.locator("button:has-text('＋ Watch')").first
        assert btn.count() == 1
        btn.dispatch_event("click")
        page.wait_for_timeout(400)

        assert len(capture) == 1
        assert capture[0] == {"ticker": "AAPL"}
        assert "Added to your watchlist" in page.inner_html("#lookup-result")
        browser.close()


def test_watchlist_edit_level_stays_inline_no_tab_switch(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _base_routes(page, morning_csv=MORNING_WATCHLIST_CSV)
        capture = []
        _mock_worker(page, watchlist_rows=[WATCH_ENTRY], capture=capture)
        _boot(page, signed_in=True)
        page.click("[data-tab='morning']")
        page.wait_for_timeout(500)
        page.locator("#morning-subtab-btn-watchlist").dispatch_event("click")
        page.wait_for_timeout(200)

        page.locator("text=⋯").first.dispatch_event("click")
        page.wait_for_timeout(150)
        page.locator("text=Edit level").first.dispatch_event("click")
        page.wait_for_timeout(300)

        # Still on the Morning tab — the whole point of this fix (was switchTab('positions')).
        morning_content = page.locator("#morning-content, [data-tab-content='morning']")
        assert page.locator("#watchlist-section").is_visible()
        html = page.inner_html("#watchlist-section")
        assert 'id="quickwatch-panel-qw_watch_ANET"' in html
        assert "Level of interest" in html
        assert len(capture) == 0, "opening the editor must not itself post anything"

        page.locator("button:has-text('Save level')").first.dispatch_event("click")
        page.wait_for_timeout(400)
        assert len(capture) == 1
        assert capture[0]["ticker"] == "ANET"
        assert capture[0]["level_type"] == "below"
        assert capture[0]["level_value"] == pytest.approx(150.0)
        browser.close()
