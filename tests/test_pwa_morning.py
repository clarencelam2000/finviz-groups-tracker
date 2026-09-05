"""
Playwright functional tests for the WS3 Morning check tab (ADR-013, issue #262).

Surface spec: planning/mocks/trade-lifecycle-surfaces.html (WS3 section) + ADR-013
Decisions 3/5. Rendered by renderMorning() in docs/index.html.

Covered:
  1. All six statuses render, in the ADR/mock actionability order.
  2. Provisional banner + "not settled" chrome is present (ADR-011, non-negotiable).
  3. ATR-from-LoD band labels render on every card with a quote (not gated to actionable
     states, since 2026-09-02), with correct color words.
  4. "I took it" CTA appears only on actionable states (Triggered / Gapped-through).
  5. Signed out, tapping "I took it" routes to sign-in (WS5 phase 1 #309 — it now creates a
     real authenticated position, not the old localStorage-only marker; signed-in path in
     tests/test_pwa_positions.py).
  6. Empty store → empty-state copy, no crash (covers pre-first-run / non-trading day).

Run with Playwright installed:
    python3 -m playwright install chromium
    python3 -m pytest tests/test_pwa_morning.py -v
"""

import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MORNING_FIXTURE = ROOT / "tests" / "fixtures" / "morning_latest.csv"
PORT = 8188  # unique port to avoid colliding with other PWA test suites


def _launch_server(port: int):
    return subprocess.Popen(
        ["python3", "-m", "http.server", str(port), "--directory", str(ROOT / "docs")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _open_morning_tab(page, morning_body: str):
    """Boot the PWA with stubbed CDNs + CSVs, intercept morning_latest.csv, open the tab.

    Route globs use the "**/filename.ext" form (literal "/" before the filename) — the
    "**domain**filename" form silently never matches (see
    knowledge/investigations/playwright-cloud-session-testing.md). CDN scripts must be
    stubbed or the app never boots where Chromium can't reach the real CDNs.
    """
    papaparse_js = (ROOT / "tests" / "fixtures" / "papaparse.min.js").read_text(encoding="utf-8")
    page.route("**/cdn.tailwindcss.com/**",
               lambda r: r.fulfill(body="/* tailwind stub */", content_type="application/javascript"))
    page.route("**/cdnjs.cloudflare.com/**",
               lambda r: r.fulfill(body=papaparse_js, content_type="application/javascript"))
    page.route("**/sessions/morning_latest.csv",
               lambda r: r.fulfill(body=morning_body, content_type="text/plain"))
    page.route("**/snapshots.csv",
               lambda r: r.fulfill(body="date,collected_at,group_type,name,stocks,market_cap,pe,fwd_pe,perf_day,perf_week,perf_month,perf_quarter,perf_half,perf_year,perf_ytd,avg_volume,rel_volume,change\n", content_type="text/plain"))
    page.route("**/deltas.csv",
               lambda r: r.fulfill(body="date,name\n", content_type="text/plain"))
    page.route("**/picks_latest.csv",
               lambda r: r.fulfill(body="date,ticker\n", content_type="text/plain"))
    # Morning tab fetches the pre-close read on first visit; without a stub Chromium hangs on
    # the unreachable domain in an offline sandbox (see playwright-cloud-session-testing.md).
    page.route("**/sessions/pre_close_latest.csv",
               lambda r: r.fulfill(body="date,session,collected_at,ticker,group,list_category,trigger,stop,atr,price,open,high,low,change,status,atr_from_lod\n", content_type="text/plain"))
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


def _morning_body() -> str:
    return MORNING_FIXTURE.read_text(encoding="utf-8")


def test_all_statuses_render_in_actionability_order(server):
    import re
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _open_morning_tab(page, _morning_body())
        html = page.inner_html("#morning-list")
        # 6 cards (one per status), each with the left severity stripe.
        assert html.count("border-l-4") == 6, f"expected 6 cards, got {html.count('border-l-4')}"
        pills = re.findall(r"rounded-full[^>]*>([A-Za-z ]+)</span>", html)
        order = [s for s in pills if s in (
            "Triggered", "Gapped through", "Failed breakout", "Setting up", "Invalidated", "No quote")]
        assert order == ["Triggered", "Gapped through", "Failed breakout",
                         "Setting up", "Invalidated", "No quote"], order
        browser.close()


def test_provisional_chrome_present(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _open_morning_tab(page, _morning_body())
        html = page.inner_html("#morning-list")
        assert "provisional — not settled" in html
        assert "Nothing here changes your EOD data" in html
        browser.close()


def test_atr_from_lod_bands_every_status(server):
    # Owner decision 2026-09-02: ATR-from-LoD is no longer gated to actionable states — it
    # renders (same color bands) on every card that has a quote, including failed_breakout/
    # setting_up/invalidated. Only no_quote (PWR, blank atr_from_lod) has nothing to show.
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _open_morning_tab(page, _morning_body())
        html = page.inner_html("#morning-list")
        # AXON triggered atr_from_lod=0.6 (<=0.8) → ok to act; VRT gapped=1.8 (>1.0) → chase risk.
        assert "ok to act" in html
        assert "chase risk" in html
        # 5 per-card occurrences (PWR has no_quote) + 1 permanent "ATR from LoD" sort-pill label
        # in the new sort toggle (2026-09-03) — see docs/CLAUDE.md § Morning tab sort/filter.
        assert html.count("ATR from LoD") == 6, "ATR-from-LoD should render on every card with a quote (5 of 6; PWR has no_quote) plus the sort pill"
        browser.close()


def test_i_took_it_only_on_actionable(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _open_morning_tab(page, _morning_body())
        html = page.inner_html("#morning-list")
        assert html.count("I took it") == 2, "CTA should appear only on Triggered + Gapped-through"
        browser.close()


def test_i_took_it_requires_signin_when_signed_out(server):
    # WS5 phase 1 (#309) superseded the old localStorage-only "✓ Taken" marker: "I took it"
    # now creates a real, authenticated position. Signed out, tapping it must NOT write a
    # marker — it routes the user to sign in. The signed-in confirm+POST path is covered in
    # tests/test_pwa_positions.py (which mocks the worker). Here we only assert the gate.
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _open_morning_tab(page, _morning_body())
        page.click("text=I took it →")
        page.wait_for_timeout(300)
        html = page.inner_html("#morning-list")
        assert "Sign in on the Positions tab to log trades" in html, "signed-out tap should show the sign-in note"
        assert "✓ Taken" not in html, "no marker flip when signed out"
        # No localStorage marker is written without a real (signed-in) log.
        val = page.evaluate("() => localStorage.getItem('taken:2026-08-07:AXON')")
        assert val is None, f"expected no taken marker when signed out, got {val!r}"
        browser.close()


RECLAIM_HEADER = ("date,session,collected_at,ticker,group,list_category,trigger,stop,atr,"
                  "price,open,high,low,change,status,atr_from_lod,reclaim_ref,reclaim_ref_value\n")


def _reclaim_body() -> str:
    # Two reclaim picks: one attributed to the prior low (exact value), one to the derived
    # 50MA (rendered with a "~" approximation prefix). Both are actionable.
    return RECLAIM_HEADER + (
        "2026-08-27,morning,2026-08-27T14:00:00Z,RCLO,Group A,leaders,44,42.15,2,43,42.5,43.4,41.9,0.5%,reclaim,0.6,prior_low,42.15\n"
        "2026-08-27,morning,2026-08-27T14:00:00Z,RCMA,Group B,leaders,44,39,2,41,40,41.2,38.5,0.7%,reclaim,0.7,sma50,39.80\n"
    )


def test_reclaim_pick_renders_actionable_with_named_level(server):
    # Owner decision 2026-08-27: picks now emit reclaim (undercut-and-reclaim / failed
    # breakdown), actionable, with the reclaimed level named. prior_low shows the exact
    # value; the derived 50MA is prefixed "~".
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _open_morning_tab(page, _reclaim_body())
        html = page.inner_html("#morning-list")
        assert html.count("Reclaimed") >= 2, "both reclaim picks should render a Reclaimed pill"
        assert "Reclaimed prior low" in html
        assert "42.15" in html
        assert "Reclaimed 50MA" in html
        assert "~39.80" in html
        # Actionable: ATR-from-LoD row + "I took it" CTA on both reclaim cards. +1 for the
        # permanent "ATR from LoD" sort-pill label (2026-09-03 sort toggle).
        assert html.count("ATR from LoD") == 3
        assert html.count("I took it") == 2
        browser.close()


def test_empty_store_shows_empty_state(server):
    from playwright.sync_api import sync_playwright
    header_only = "date,session,collected_at,ticker,group,list_category,trigger,stop,atr,price,open,high,low,change,status,atr_from_lod\n"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _open_morning_tab(page, header_only)
        html = page.inner_html("#morning-list")
        assert "No morning check yet" in html
        assert html.count("border-l-4") == 0
        browser.close()


# ── B-6 (issue #379 / A-2 seam): the shared "Volatility & setup" compression section on the
#    Morning family. B-1 raw cols (Vol W/M, Rel Volume, 52W High) come fresh from the A-1
#    scrape-wide morning store; B-2/B-3 sparkline cols come via a picks_latest cross-ref
#    (setupRowForCard → ws4FindPicksRow). Rendered by the shared volSetupSectionHtml(). ──

# Morning header WITH the A-1 SETUP_COLUMNS appended (matches collect_morning.STORE_COLUMNS order:
# the wide setup cols follow the 9-col status set, plus RSI).
_B6_MORNING_HEADER = ("date,session,collected_at,ticker,group,list_category,trigger,stop,atr,"
                      "price,open,high,low,change,status,atr_from_lod,"
                      "RSI,Volatility W,Volatility M,Rel Volume,52W High\n")


def _open_morning_with_picks(page, morning_body: str, picks_body: str):
    """Same as _open_morning_tab but serves a real picks_latest.csv for the B-6 cross-ref."""
    papaparse_js = (ROOT / "tests" / "fixtures" / "papaparse.min.js").read_text(encoding="utf-8")
    page.route("**/cdn.tailwindcss.com/**",
               lambda r: r.fulfill(body="/* tailwind stub */", content_type="application/javascript"))
    page.route("**/cdnjs.cloudflare.com/**",
               lambda r: r.fulfill(body=papaparse_js, content_type="application/javascript"))
    page.route("**/sessions/morning_latest.csv",
               lambda r: r.fulfill(body=morning_body, content_type="text/plain"))
    page.route("**/sessions/pre_close_latest.csv",
               lambda r: r.fulfill(body=_B6_MORNING_HEADER, content_type="text/plain"))
    page.route("**/snapshots.csv",
               lambda r: r.fulfill(body="date,collected_at,group_type,name,stocks,market_cap,pe,fwd_pe,perf_day,perf_week,perf_month,perf_quarter,perf_half,perf_year,perf_ytd,avg_volume,rel_volume,change\n", content_type="text/plain"))
    page.route("**/deltas.csv", lambda r: r.fulfill(body="date,name\n", content_type="text/plain"))
    page.route("**/picks_latest.csv", lambda r: r.fulfill(body=picks_body, content_type="text/plain"))
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


def test_volatility_setup_section_on_morning_card(server):
    # A triggered morning card whose fresh scrape-wide setup cols say Vol W (1.7%) < Vol M (2.5%)
    # → the section shows the raw values + a "contracting" fact tint, and the picks cross-ref
    # (dated 2026-09-01) supplies the renamed "Volume over last 10 sessions" + range sparklines,
    # each carrying an "as of last close 9/1" caveat (owner decision 2026-09-02) since that block
    # alone is a session behind the fresh B-1 values above it.
    from playwright.sync_api import sync_playwright
    morning = _B6_MORNING_HEADER + (
        "2026-09-01,morning,2026-09-01T14:05:00Z,CAH,Healthcare,leaders,236.97,230,5.4,"
        "238.48,236,239,237,1.65,triggered,0.45,58,1.70%,2.54%,0.31,-7.67%\n"
    )
    picks = ("date,Ticker,tight_range_7,range_atr_spark,atr_spark,relvol_spark\n"
             "2026-09-01,CAH,,0.67|1.07|0.71|0.64|0.87,5.13|5.16|5.15|5.40|5.45,1.10|1.13|0.61|0.76|0.61\n")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _open_morning_with_picks(page, morning, picks)
        html = page.inner_html("#morning-list")
        assert "Volatility &amp; setup" in html, "section header should render on the morning card"
        assert "1.7% / 2.5%" in html, "raw Vol W / M values shown"
        assert "contracting" in html, "Vol W < Vol M is a fact tint = contracting"
        assert "0.31×" in html, "Rel volume shown"
        assert "Volume over last 10 sessions" in html, "B-3 sub-block from the picks cross-ref, renamed 2026-09-02"
        assert "Range over last 10 sessions" in html, "B-2 sub-block from the picks cross-ref, renamed 2026-09-02"
        assert html.count("as of last close 9/1") == 2, "both stale sub-blocks name the picks-row date"
        assert "<polyline" in html, "at least one sparkline rendered"
        browser.close()


def test_volatility_setup_section_hidden_for_orphan(server):
    # A morning name with blank setup cols AND no picks_latest row (a watchlist-add orphan) must
    # render NO section — graceful degrade, never a wall of dashes.
    from playwright.sync_api import sync_playwright
    morning = _B6_MORNING_HEADER + (
        "2026-09-01,morning,2026-09-01T14:05:00Z,ORPH,Group X,leaders,50,47,1.5,"
        "51,50,51.5,49.9,1.0,triggered,0.5,55,,,,\n"
    )
    picks = "date,Ticker,tight_range_7,range_atr_spark,atr_spark,relvol_spark\n"  # ORPH absent
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _open_morning_with_picks(page, morning, picks)
        html = page.inner_html("#morning-list")
        assert "border-l-4" in html, "the orphan card itself still renders"
        assert "Volatility &amp; setup" not in html, "no section when there's no data (graceful degrade)"
        browser.close()


# ── Sort / launch-ready filter / bucket collapse + mini-nav (owner decision 2026-09-03) —
#    see docs/CLAUDE.md § Morning tab sort/filter. Status-bucket grouping (order from
#    MORNING_STATUS_META) always applies; these options only choose the tiebreak WITHIN each
#    bucket, except Rel volume's optional 'global' scope which flattens grouping entirely. ──

def _sort_morning_body() -> str:
    # Three 'setting_up' rows (one bucket, to exercise the intra-bucket tiebreak) with distinct
    # ATR-from-LoD and Rel Volume, plus one 'triggered' row (DDD) so there are two non-empty
    # buckets for the mini-nav/collapse tests.
    return _B6_MORNING_HEADER + (
        "2026-09-03,morning,2026-09-03T14:05:00Z,AAA,Group A,leaders,50,47,1.5,51,50,51.5,49.9,1.0,setting_up,0.5,55,1.0%,1.0%,0.50,-3\n"
        "2026-09-03,morning,2026-09-03T14:05:00Z,BBB,Group B,leaders,50,47,1.5,51,50,51.5,49.9,1.0,setting_up,0.9,55,1.0%,1.0%,2.50,-25\n"
        "2026-09-03,morning,2026-09-03T14:05:00Z,CCC,Group C,leaders,50,47,1.5,51,50,51.5,49.9,1.0,setting_up,0.2,55,1.0%,1.0%,1.20,-6\n"
        "2026-09-03,morning,2026-09-03T14:05:00Z,DDD,Group D,leaders,50,47,1.5,51,50,51.5,49.9,1.0,triggered,0.3,55,1.0%,1.0%,1.00,-4\n"
    )


def _sort_picks_body() -> str:
    # AAA is the only picks_latest row, so it's the sole Focus candidate (computeFocusScores'
    # n==1 branch always yields a real, non-null score) and its 52W High (-5 -> 5% below high)
    # + atr_ext_50 (1.5) land it in the Coiled launch-ready band (LAUNCH_NEAR_HIGH_PCT=8,
    # LAUNCH_CALM_EXT_MAX=3) — one fixture row exercising both the Focus chip and the filter.
    header = ("date,list_category,Ticker,Price,ATR,SMA20,SMA50,SMA200,Market Cap,Earnings,"
              "Avg Volume,atr_ext_50,risk_20ma_pct,risk_50ma_pct,range_atr,grp_sum_mid_rank,52W High\n")
    row = "2026-09-03,leaders,AAA,51.00,1.5,2.00%,5.00%,10.00%,10,,5000000,1.5,0.03,0.05,1.0,50,-5\n"
    return header + row


def test_default_sort_is_focus_with_chip_and_sort_bar(server):
    from playwright.sync_api import sync_playwright
    import re
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _open_morning_with_picks(page, _sort_morning_body(), _sort_picks_body())
        html = page.inner_html("#morning-list")
        assert "Sort:" in html and "Setup:" in html, "sort + launch-filter bars should render"
        assert re.search(r"Focus \d+%", html), "AAA's real Focus score should render as a card chip"
        browser.close()


def test_atr_lod_sort_reorders_within_bucket(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _open_morning_with_picks(page, _sort_morning_body(), _sort_picks_body())
        page.click('button[onclick="__setMorningSort(\'atr_lod\')"]')
        page.wait_for_timeout(300)
        html = page.inner_html("#morning-list")
        # Ascending ATR-from-LoD within the setting_up bucket: CCC(0.2) < AAA(0.5) < BBB(0.9).
        assert html.find("CCC") < html.find("AAA") < html.find("BBB"), "expected CCC, AAA, BBB order"
        browser.close()


def test_rel_volume_scope_toggle_and_global_flatten(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _open_morning_with_picks(page, _sort_morning_body(), _sort_picks_body())
        page.click('button[onclick="__setMorningSort(\'rel_volume\')"]')
        page.wait_for_timeout(300)
        html = page.inner_html("#morning-list")
        assert "In bucket" in html, "scope switch should appear only for the Rel volume sort"

        page.click('button[onclick="__setMorningSortScope(\'global\')"]')
        page.wait_for_timeout(300)
        html2 = page.inner_html("#morning-list")
        assert "__toggleMorningBucket" not in html2, "global scope flattens — no bucket headers/mini-nav"
        assert html2.count("border-l-4") == 4, "all 4 cards still render, just unbucketed"
        # Descending Rel volume across ALL statuses: BBB(2.5) > CCC(1.2) > DDD(1.0) > AAA(0.5).
        assert html2.find("BBB") < html2.find("CCC") < html2.find("DDD") < html2.find("AAA")
        browser.close()


def test_launch_ready_filter_narrows_and_shows_empty_state(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _open_morning_with_picks(page, _sort_morning_body(), _sort_picks_body())
        page.click('button[onclick="__setMorningLaunchFilter(\'Coiled\')"]')
        page.wait_for_timeout(300)
        html = page.inner_html("#morning-list")
        assert html.count("border-l-4") == 1, "only AAA (Coiled) should remain"
        assert "AAA" in html

        page.click('button[onclick="__setMorningLaunchFilter(\'Overhead\')"]')
        page.wait_for_timeout(300)
        html2 = page.inner_html("#morning-list")
        assert "try All" in html2, "no Overhead setups today -> filter empty-state copy"
        browser.close()


def test_collapse_expand_and_mininav_force_expand(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _open_morning_with_picks(page, _sort_morning_body(), _sort_picks_body())
        total = page.inner_html("#morning-list").count("border-l-4")
        assert total == 4

        page.click('button[onclick="__toggleMorningBucket(\'setting_up\')"]')
        page.wait_for_timeout(300)
        collapsed_html = page.inner_html("#morning-list")
        assert collapsed_html.count("border-l-4") == total - 3, "collapsing setting_up hides its 3 cards"

        # Jumping via the mini-nav must force-expand the collapsed bucket back.
        page.click('button[onclick="__jumpToMorningBucket(\'setting_up\')"]')
        page.wait_for_timeout(400)
        expanded_html = page.inner_html("#morning-list")
        assert expanded_html.count("border-l-4") == total, "mini-nav jump must force-expand a collapsed bucket"
        browser.close()
