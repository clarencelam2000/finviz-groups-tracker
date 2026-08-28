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
    """AXON has TWO picks rows sharing identical Finviz/metrics columns but different
    list_category ('leaders' and 'accel') — mirrors collect_picks.py's real behavior of
    writing one row per (ticker x list_category) when a ticker's group qualifies in more
    than one bucket (~30% of a typical day's picks, verified against live picks_latest.csv).
    This exercises ws4PickCategories() reading the true category set directly off the data
    (no re-derived grp_* threshold heuristics).

    Columns include the real METRICS_COLS set (atr_ext_50, risk_20ma_pct, risk_50ma_pct,
    range_atr — scripts/picks_metrics.py) plus grp_sum_mid_rank, so this exercises the same
    3-component base Focus score real rows do (an earlier draft omitted risk_20ma_pct/
    risk_50ma_pct, which isn't representative of production picks_latest.csv and silently
    changed the expected score via computeFocusScores' NaN-component fallback). Score is
    pinned by construction, not just derived by hand — verified via a standalone extraction
    of computeFocusScores() from docs/index.html run under plain Node (see PR discussion):
    with only these two identical-valued rows in the candidate pool (n=2 < FOCUS_MIN_POOL=5),
    normalizeInv's rank-based fallback gives every component a perfect 1.0 (both entries tie
    for "best" in a 2-way tie) -> base = 0.2*1 + 0.4*1 + 0.4*1 = 1.0. 0 liquidity penalty
    (ample Avg Volume), 0 extension penalty (atr_ext_50=1.0 is below ATR_EXT_PENALTY_START),
    EARNINGS_PENALTY_MAX (0.7) from the 2-day-out earnings date (computed at test time so
    this is stable regardless of when the suite runs) -> score = 1.0 * (1-0.7) = 0.30.
    Market Cap/SMA200 are populated so both rows clear the Picks tab's own C6 base filter
    (passesPicksBaseFilter), matching what the Picks tab itself would show. VRT (present in
    the morning fixture) is intentionally absent here to exercise the no-EOD-match degraded
    path."""
    d = datetime.date.today() + datetime.timedelta(days=2)
    earnings = f"{MONTHS[d.month - 1]} {d.day:02d}/a"
    header = ("date,list_category,Ticker,Price,ATR,SMA20,SMA50,SMA200,Market Cap,Earnings,"
              "Avg Volume,atr_ext_50,risk_20ma_pct,risk_50ma_pct,range_atr,grp_sum_mid_rank\n")
    common = "610.00,14.00,2.00%,5.00%,10.00%,50,{earnings},5000000,1.0,0.03,0.05,1.0,50"
    row1 = f"2026-08-08,leaders,AXON,{common.format(earnings=earnings)}\n"
    row2 = f"2026-08-08,accel,AXON,{common.format(earnings=earnings)}\n"
    return header + row1 + row2


def _launch_server(port: int):
    return subprocess.Popen(
        ["python3", "-m", "http.server", str(port), "--directory", str(ROOT / "docs")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _open_morning_tab(page, picks_body=None):
    """Boot the PWA with stubbed CDNs + CSVs, intercept morning_latest.csv and
    picks_latest.csv, open the Morning tab. Route glob form per
    knowledge/investigations/playwright-cloud-session-testing.md ("**/filename.ext",
    literal slash before the filename — "**domain**filename" silently never matches).
    picks_body defaults to _picks_body(); pass an override for tests that need a
    different picks_latest.csv shape (e.g. an unrecognized list_category)."""
    papaparse_js = (ROOT / "tests" / "fixtures" / "papaparse.min.js").read_text(encoding="utf-8")
    page.route("**/cdn.tailwindcss.com/**",
               lambda r: r.fulfill(body="/* tailwind stub */", content_type="application/javascript"))
    page.route("**/cdnjs.cloudflare.com/**",
               lambda r: r.fulfill(body=papaparse_js, content_type="application/javascript"))
    page.route("**/sessions/morning_latest.csv",
               lambda r: r.fulfill(body=MORNING_FIXTURE.read_text(encoding="utf-8"), content_type="text/plain"))
    page.route("**/picks_latest.csv",
               lambda r: r.fulfill(body=picks_body if picks_body is not None else _picks_body(), content_type="text/plain"))
    # switchTab('morning') unconditionally fetches PRECLOSE_URL on first visit (WS3b) — with
    # no stub, Chromium in this sandbox hangs indefinitely on the unreachable domain (known
    # Root Cause 2, knowledge/investigations/playwright-cloud-session-testing.md) rather than
    # failing fast, which silently broke every test in this file (all 10 timed out waiting on
    # "Trade ticket" text that never rendered) until this stub was added — same gap already
    # found and fixed in test_pwa_watchlist.py's _base_routes(), just not applied here yet.
    page.route("**/pre_close_latest.csv",
               lambda r: r.fulfill(body="date,session,collected_at,ticker,group,list_category,trigger,stop,atr,price,open,high,low,change,status,atr_from_lod\n", content_type="text/plain"))
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


def test_low_edit_recomputes_atr_from_lod_label(server):
    """2026-08-28 owner report: Finviz's own scraped Low (613.00 in the fixture) can
    understate a ticker's real day low, giving a falsely clean ATR-from-LoD reading with
    no way to correct it — unlike price, which already had an edit affordance. Typing a
    lower observed low must recompute the same gate, mirroring the price-edit test above."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _open_morning_tab(page)
        page.click("text=▾ Trade ticket >> nth=0")
        page.wait_for_timeout(300)

        label_before = page.inner_text("#ws4-atrlod-AXON")
        assert "ok to act" in label_before

        # AXON: price=613.90, atr=14.20. A lower observed low (590) widens the distance
        # from price to (613.90-590)/14.20 = 1.68 -> chase risk (threshold is 1.0).
        page.fill("#ws4-low-AXON", "590")
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


def test_pick_reason_line_lists_every_real_category(server):
    """AXON has two real picks.csv rows for today — list_category 'leaders' AND 'accel' —
    so the reason line must show both, straight off the data (ws4PickCategories), not a
    re-derived grp_* threshold guess. Primary category is 'leaders' (selector priority
    order), the rest render as 'also <category>'."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _open_morning_tab(page)
        page.click("text=▾ Trade ticket >> nth=0")
        page.wait_for_timeout(300)
        html = page.inner_html("#morning-list")
        assert "from Picks · leaders · also accel" in html
        browser.close()


def test_pick_reason_line_surfaces_unrecognized_category(server):
    """Regression test for a real bug caught in review: ws4PickCategories()'s first draft
    was `order.filter(c => cats.has(c))`, which silently DROPS any list_category not in the
    hardcoded 4-category `order` array — a category the selector starts writing in the
    future (a hypothetical 5th bucket) would vanish from the reason line with no error. AXON
    here has one row tagged with a made-up category, 'breakout', that will never be in
    `order`; it must still render (appended after any known categories), never disappear."""
    from playwright.sync_api import sync_playwright
    d = datetime.date.today() + datetime.timedelta(days=2)
    earnings = f"{MONTHS[d.month - 1]} {d.day:02d}/a"
    header = ("date,list_category,Ticker,Price,ATR,SMA20,SMA50,SMA200,Market Cap,Earnings,"
              "Avg Volume,atr_ext_50,risk_20ma_pct,risk_50ma_pct,range_atr,grp_sum_mid_rank\n")
    common = f"610.00,14.00,2.00%,5.00%,10.00%,50,{earnings},5000000,1.0,0.03,0.05,1.0,50"
    picks_body = header + f"2026-08-08,breakout,AXON,{common}\n"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _open_morning_tab(page, picks_body=picks_body)
        page.click("text=▾ Trade ticket >> nth=0")
        page.wait_for_timeout(300)
        html = page.inner_html("#morning-list")
        assert "from Picks · breakout" in html
        browser.close()


def test_focus_score_shown_in_footnote(server):
    """See _picks_body()'s docstring for the full score derivation (pinned at 0.30 on the
    app's internal 0-1 scale, verified against a standalone Node extraction of
    computeFocusScores()). Displayed as a rounded 0-100 integer (Math.round(score * 100))
    to match every other Focus score display in the app (Picks tab badge, expanded-card
    debug breakdown, GUIDE glossary's "blended 0-100 quality score" description) — an
    earlier version of this footnote showed the raw 0-1 decimal ("0.30"), which was the
    only place in the app using that scale."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _open_morning_tab(page)
        page.click("text=▾ Trade ticket >> nth=0")
        page.wait_for_timeout(300)
        html = page.inner_html("#morning-list")
        assert "Focus score: 30" in html
        assert "pool-relative" in html
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
