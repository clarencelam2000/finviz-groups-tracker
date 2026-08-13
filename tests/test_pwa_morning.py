"""
Playwright functional tests for the WS3 Morning check tab (ADR-013, issue #262).

Surface spec: planning/mocks/trade-lifecycle-surfaces.html (WS3 section) + ADR-013
Decisions 3/5. Rendered by renderMorning() in docs/index.html.

Covered:
  1. All six statuses render, in the ADR/mock actionability order.
  2. Provisional banner + "not settled" chrome is present (ADR-011, non-negotiable).
  3. ATR-from-LoD band labels render only on actionable states, with correct color words.
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


def test_atr_from_lod_bands_actionable_only(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _open_morning_tab(page, _morning_body())
        html = page.inner_html("#morning-list")
        # AXON triggered atr_from_lod=0.6 (<=0.8) → ok to act; VRT gapped=1.8 (>1.0) → chase risk.
        assert "ok to act" in html
        assert "chase risk" in html
        # Non-actionable states (setting_up/failed/invalidated/no_quote) must not show ATR-from-LoD.
        assert html.count("ATR from LoD") == 2, "ATR-from-LoD should render on the 2 actionable cards only"
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
