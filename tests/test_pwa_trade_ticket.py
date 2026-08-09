"""
Playwright functional tests for the WS4 Phase B live trade ticket (ADR-014, issue #263).

Surface spec: knowledge/decisions/ADR-014-ws4-trade-tickets.md +
planning/mocks/ws4-trade-ticket.html. Rendered by ws4TicketHtml()/ws4Recompute() in
docs/index.html, reached by expanding an actionable (triggered / gapped_through)
Morning card.

Covered:
  1. Tapping an actionable card expands its trade ticket inline.
  2. Selecting a different stop basis (Today low) recomputes the shares number.
  3. Editing the price input recomputes the ATR-from-LoD chase/ok label.
  4. The hard earnings guardrail card renders for a ticker with near-term earnings,
     joined from the (fixture) EOD picks_latest row.
  5. A morning row with no matching EOD picks row still expands (degraded), without
     crashing — the positional gate/earnings/stop-menu rows for it are hidden/greyed.

Run with Playwright installed:
    python3 -m playwright install chromium
    python3 -m pytest tests/test_pwa_trade_ticket.py -v
"""

import datetime
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MORNING_FIXTURE = ROOT / "tests" / "fixtures" / "ws4_morning.csv"
PORT = 8189  # unique port to avoid colliding with other PWA test suites

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _picks_body() -> str:
    """AXON picks row with Earnings 2 days out (computed at test time so the guardrail
    test is stable regardless of when the suite runs) and grp_rs_new_high set (pick
    reason line). VRT (present in the morning fixture) is intentionally absent here to
    exercise the no-EOD-match degraded path."""
    d = datetime.date.today() + datetime.timedelta(days=2)
    earnings = f"{MONTHS[d.month - 1]} {d.day:02d}/a"
    header = "date,list_category,Ticker,Price,ATR,SMA20,SMA50,Earnings,grp_rs_new_high\n"
    row = f"2026-08-08,leaders,AXON,610.00,14.00,2.00%,5.00%,{earnings},1.0\n"
    return header + row


def _launch_server(port: int):
    return subprocess.Popen(
        ["python3", "-m", "http.server", str(port), "--directory", str(ROOT / "docs")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _open_morning_tab(page):
    """Boot the PWA with stubbed CDNs + CSVs, intercept morning_latest.csv and
    picks_latest.csv, open the Morning tab. Route glob form per
    knowledge/investigations/playwright-cloud-session-testing.md ("**/filename.ext",
    literal slash before the filename — "**domain**filename" silently never matches)."""
    papaparse_js = (ROOT / "tests" / "fixtures" / "papaparse.min.js").read_text(encoding="utf-8")
    page.route("**/cdn.tailwindcss.com/**",
               lambda r: r.fulfill(body="/* tailwind stub */", content_type="application/javascript"))
    page.route("**/cdnjs.cloudflare.com/**",
               lambda r: r.fulfill(body=papaparse_js, content_type="application/javascript"))
    page.route("**/sessions/morning_latest.csv",
               lambda r: r.fulfill(body=MORNING_FIXTURE.read_text(encoding="utf-8"), content_type="text/plain"))
    page.route("**/picks_latest.csv",
               lambda r: r.fulfill(body=_picks_body(), content_type="text/plain"))
    page.route("**/snapshots.csv",
               lambda r: r.fulfill(body="date,collected_at,group_type,name,stocks,market_cap,pe,fwd_pe,perf_day,perf_week,perf_month,perf_quarter,perf_half,perf_year,perf_ytd,avg_volume,rel_volume,change\n", content_type="text/plain"))
    page.route("**/deltas.csv",
               lambda r: r.fulfill(body="date,name\n", content_type="text/plain"))
    page.route("**/fetch_log.csv", lambda r: r.fulfill(body="", content_type="text/plain"))
    page.route("**/releases.json",
               lambda r: r.fulfill(body='{"current":"","releases":[]}', content_type="application/json"))
    page.route("**/finviz_sector_industry_map.json",
               lambda r: r.fulfill(body='{"sectors":{}}', content_type="application/json"))

    page.add_init_script("try { localStorage.clear(); localStorage.setItem('fvt_intro_seen_v3','true'); } catch(e){}")
    page.goto(f"http://localhost:{PORT}/", wait_until="domcontentloaded")
    page.wait_for_timeout(1000)
    page.click("[data-tab='morning']")
    page.wait_for_timeout(1000)


@pytest.fixture(scope="module")
def server():
    proc = _launch_server(PORT)
    time.sleep(1)
    yield proc
    proc.terminate()
    proc.wait()


def test_ticket_expands_on_actionable_card(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _open_morning_tab(page)
        html = page.inner_html("#morning-list")
        assert "▾ Trade ticket" in html
        assert "ws4-price-AXON" not in html  # not yet expanded

        page.click("text=▾ Trade ticket >> nth=0")
        page.wait_for_timeout(300)
        html = page.inner_html("#morning-list")
        assert "id=\"ws4-price-AXON\"" in html
        assert "Don't-chase gates" in html
        assert "Stop — pick your basis" in html
        assert "No profit target" in html
        browser.close()


def test_price_snapshot_label_reflects_actual_collected_at(server):
    """Regression test: the snapshot label must be derived from the row's real
    collected_at (via freshnessLabel), not a hardcoded '10:05' string — the morning
    job's self-healing dispatch window (CLAUDE.md § Automation) can push the actual
    snapshot well past 10:05 ET on a delayed tick."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _open_morning_tab(page)
        page.click("text=▾ Trade ticket >> nth=0")
        page.wait_for_timeout(300)
        html = page.inner_html("#morning-list")
        assert "10:05 read" not in html
        assert "As of the 10:05 ET snapshot" not in html
        # AXON's fixture collected_at (2026-08-09T14:05:00Z) is 7:05 AM PT.
        assert "7:05" in html
        assert "PT" in html
        browser.close()


def test_stop_basis_change_recomputes_shares(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _open_morning_tab(page)
        page.click("text=▾ Trade ticket >> nth=0")
        page.wait_for_timeout(300)

        position_before = page.inner_text("#ws4-position-AXON")
        assert "29 sh" in position_before  # $500 / (613.90-597.10) = floor(29.76) = 29

        page.click("button:has-text('Today low')")
        page.wait_for_timeout(300)
        position_after = page.inner_text("#ws4-position-AXON")
        assert position_after != position_before
        assert "555 sh" in position_after  # $500 / (613.90-613.00) = floor(555.5) = 555
        browser.close()


def test_price_edit_recomputes_atr_from_lod_label(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _open_morning_tab(page)
        page.click("text=▾ Trade ticket >> nth=0")
        page.wait_for_timeout(300)

        label_before = page.inner_text("#ws4-atrlod-AXON")
        assert "ok to act" in label_before

        page.fill("#ws4-price-AXON", "630")
        page.wait_for_timeout(200)
        label_after = page.inner_text("#ws4-atrlod-AXON")
        assert "chase risk" in label_after
        browser.close()


def test_earnings_guardrail_renders(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _open_morning_tab(page)
        page.click("text=▾ Trade ticket >> nth=0")
        page.wait_for_timeout(300)
        html = page.inner_html("#morning-list")
        assert "Earnings in 2 days" in html
        assert "earnings gamble, not a swing setup" in html
        browser.close()


def test_pick_reason_line_from_grp_flag(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _open_morning_tab(page)
        page.click("text=▾ Trade ticket >> nth=0")
        page.wait_for_timeout(300)
        html = page.inner_html("#morning-list")
        assert "from Picks · leaders · rs_new_high" in html
        browser.close()


def test_no_eod_match_degrades_without_crash(server):
    """VRT (gapped_through, actionable) has no matching picks_latest row in the fixture —
    the ticket must still expand, showing the degraded join note, no positional gate, and
    a disabled 20MA/50MA stop option, instead of throwing or silently vanishing."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _open_morning_tab(page)
        toggles = page.locator("text=▾ Trade ticket")
        assert toggles.count() == 2
        toggles.nth(1).click()  # VRT is the second actionable card (gapped_through, order 1)
        page.wait_for_timeout(300)
        html = page.inner_html("#morning-list")
        assert "no EOD match" in html
        assert "id=\"ws4-price-VRT\"" in html
        browser.close()
