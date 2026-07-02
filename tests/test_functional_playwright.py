"""
Playwright functional tests for the PWA (docs/index.html) and Streamlit dashboard.

Verifies that the 5/10/20/50 trading-day window change from PR #105 is visible
in both UIs. Run manually (needs Playwright + Chromium installed):

    python3 -m playwright install chromium
    python3 -m pytest tests/test_functional_playwright.py -v

These tests are excluded from the default CI run (test_collect_parsing exclusion
list) because they require Playwright. Add --ignore=tests/test_functional_playwright.py
to skip, or run directly when Playwright is available.
"""

# TODO(PWA-TEST-GAP): The tests below cover only the Movers tab lookback buttons
# (PR #105 regression guard). The following PWA behaviors are NOT tested yet.
# See SPRINT.md task PWA-TEST-GAP for pick-up instructions and prioritization.
#
# Gap 1 — Movers cards render actual delta data
#   When a window button (5d/10d/20d/50d) is clicked, the gainer/loser cards must
#   populate with real group names and rank-delta values from the fixture delta CSV.
#   Currently we only assert the buttons exist, not that clicking them loads data.
#   Entry point: intercept deltas.csv with fixture that has non-empty rank_ytd_delta_Nd
#   columns; click each button; assert at least one gainer card and one loser card appear.
#
# Gap 2 — Today tab: card rendering, color coding, sort dropdown
#   The Today tab is the primary landing view. No tests cover: snapshot cards render
#   with group names and perf values; green/red color class applied based on perf_week
#   sign; sort dropdown (Week/YTD/Month/Qtr/6-Month/1-Year/Day) re-orders cards;
#   sector↔industry toggle reloads with a different set of cards.
#
# Gap 3 — Momentum tab populates from momentum_score
#   Breadth leaderboard (momentum_score, progress bar) renders for at least 3 rows;
#   the highest-score group appears first.
#
# Gap 4 — Strength tab: Sustained Strength and All Green views
#   Clicking the Strength tab renders the two sub-views. Sustained Strength shows
#   groups with floor ≤ top quartile across month/quarter/half. All Green shows
#   dot matrix only for groups where all perf_* are positive.
#
# Gap 5 — AI tab: rotation phase label and briefing text load
#   Intercept the data/ai/YYYY-MM-DD.json fetch (or the index.json fallback) with
#   a fixture that has a known rotation_phase and briefing string; assert those
#   strings appear in the rendered tab.
#
# Gap 6 — Lookup tab: ticker search → group score card
#   Intercept the Worker /lookup endpoint (finviz-ticker-lookup.salmonbaby8.workers.dev)
#   and return a fixture response mapping AAPL → Technology / Consumer Electronics.
#   Assert the sector card and industry card render with the group's momentum score
#   and the FAVORABLE/MIXED/CAUTION signal badge. Also test deeplink hrefs.
#
# Gap 7 — Empty state / data-accumulating placeholder
#   When delta columns are all empty (e.g. fixture with empty rank_ytd_delta_5d),
#   the Movers tab must show the "Data accumulating" placeholder instead of cards.
#
# Gap 8 — Sector ↔ Industry toggle reloads data
#   Switching the group type (sector/industry segmented control) must trigger a
#   new CSV fetch (or use cached data) and render a different card set.
#
# Gap 9 — Offline / service worker: app loads from cache
#   After first load (populates SW cache), take the browser offline (page.context()
#   .set_offline(True)) and reload; assert core UI elements still render from cache.
#
# Gap 10 — Streamlit: time series and momentum charts render
#   The existing Streamlit test only checks the lookback selectbox options. Add:
#   - Time Series tab renders a chart element (data-testid="stVegaLiteChart" or similar)
#   - Momentum tab table has ≥1 data row
#   - Snapshot tab download buttons are present

import csv
import io
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from delta_config import LOOKBACK_WINDOWS, delta_columns

# ---------------------------------------------------------------------------
# Fixture data builders
# ---------------------------------------------------------------------------

SNAPSHOT_COLS = [
    "date", "collected_at", "group_type", "name", "stocks", "market_cap",
    "pe", "fwd_pe", "perf_day", "perf_week", "perf_month", "perf_quarter",
    "perf_half", "perf_year", "perf_ytd", "avg_volume", "rel_volume", "change",
]

def _snapshot_csv() -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=SNAPSHOT_COLS)
    w.writeheader()
    for name, pw, pm in [("Technology", 3.0, 2.5), ("Energy", 1.0, 0.5),
                          ("Healthcare", 2.0, 1.5)]:
        w.writerow({
            "date": "2026-06-17", "collected_at": "2026-06-17T20:00:00Z",
            "group_type": "sector", "name": name,
            "stocks": "100", "market_cap": "5.0", "pe": "25.0", "fwd_pe": "22.0",
            "perf_day": pw * 0.3, "perf_week": pw, "perf_month": pm,
            "perf_quarter": pm * 0.8, "perf_half": pm * 0.6,
            "perf_year": pm * 0.5, "perf_ytd": pw * 0.7,
            "avg_volume": "1000000", "rel_volume": "", "change": pw * 0.3,
        })
    return buf.getvalue()


def _delta_csv() -> str:
    cols = delta_columns()
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for name, delta5, score in [("Technology", "3", "0.80"),
                                  ("Energy", "-2", "0.35"),
                                  ("Healthcare", "1", "0.55")]:
        row = {c: "" for c in cols}
        row.update({
            "date": "2026-06-17", "name": name,
            "rank_week": "1" if name == "Technology" else ("2" if name == "Healthcare" else "3"),
            "rank_ytd": "1" if name == "Technology" else ("2" if name == "Healthcare" else "3"),
            "momentum_score": score,
            "rank_agreement": "0.9",
            f"rank_ytd_delta_{LOOKBACK_WINDOWS[0]}d": delta5,
        })
        w.writerow(row)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# PWA functional tests
# ---------------------------------------------------------------------------

@pytest.mark.functional
class TestPWALookbackWindows:
    """Verify the PWA Movers tab shows 5/10/20/50-session buttons."""

    def test_lookback_buttons_are_5_10_20_50(self):
        from playwright.sync_api import sync_playwright

        docs_dir = Path(__file__).parent.parent / "docs"
        server = subprocess.Popen(
            ["python3", "-m", "http.server", "8181", "--directory", str(docs_dir)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(1)

        snap_body = _snapshot_csv()
        delta_body = _delta_csv()

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()

                # Intercept CSV fetches and return fixture data.
                page.route("**/raw.githubusercontent.com/**sectors/snapshots.csv",
                           lambda r: r.fulfill(body=snap_body, content_type="text/plain"))
                page.route("**/raw.githubusercontent.com/**sectors/deltas.csv",
                           lambda r: r.fulfill(body=delta_body, content_type="text/plain"))
                page.route("**/raw.githubusercontent.com/**industries/snapshots.csv",
                           lambda r: r.fulfill(body=snap_body, content_type="text/plain"))
                page.route("**/raw.githubusercontent.com/**industries/deltas.csv",
                           lambda r: r.fulfill(body=delta_body, content_type="text/plain"))
                # Silence non-critical network calls.
                page.route("**/data/fetch_log.csv",
                           lambda r: r.fulfill(body="", content_type="text/plain"))
                page.route("**/data/ai/**", lambda r: r.fulfill(status=404))

                page.goto("http://localhost:8181/", wait_until="networkidle",
                          timeout=15000)

                # Navigate to Movers tab.
                movers_tab = page.locator("[data-tab='movers'], button:has-text('Movers')")
                if movers_tab.count() > 0:
                    movers_tab.first.click()
                    page.wait_for_timeout(500)

                # Assert lookback buttons show the new trading-day windows.
                expected = [f"{w}d" for w in LOOKBACK_WINDOWS]   # ["5d","10d","20d","50d"]
                for win in expected:
                    btn = page.locator(f"button[data-window='{win}']")
                    assert btn.count() > 0, (
                        f"Expected lookback button data-window='{win}' not found in PWA. "
                        f"LOOKBACK_WINDOWS={LOOKBACK_WINDOWS}"
                    )

                # Assert old 7d/14d/30d buttons are gone.
                for old_win in ["7d", "14d", "30d"]:
                    btn = page.locator(f"button[data-window='{old_win}']")
                    assert btn.count() == 0, (
                        f"Stale lookback button data-window='{old_win}' still present in PWA."
                    )

                browser.close()
        finally:
            server.terminate()
            server.wait()

    def test_lookback_buttons_derived_from_csv_header(self):
        """LB-FF1: buttons come from the CSV header, not hardcoded JS.

        Serve a delta CSV whose only rank_ytd_delta_* columns are 3d and 7d.
        Assert that exactly those two window buttons appear in the PWA, and that
        the old 5d/10d/20d/50d buttons are NOT present.
        """
        from playwright.sync_api import sync_playwright
        import csv
        import io

        # Build a minimal delta CSV with windows 3d and 7d only.
        custom_windows = ["3d", "7d"]
        base_cols = ["date", "name", "rank_day", "rank_week", "rank_month",
                     "rank_quarter", "rank_half", "rank_year", "rank_ytd"]
        delta_cols = base_cols[:]
        for w in custom_windows:
            for m in ["rank_week", "rank_month", "rank_ytd"]:
                delta_cols.append(f"{m}_delta_{w}")
            for m in ["perf_week", "perf_month", "perf_ytd"]:
                delta_cols.append(f"{m}_delta_{w}")
        delta_cols += ["momentum_score", "momentum_confirmed", "momentum_weighted_mid",
                       "momentum_weighted_fast", "momentum_accel", "regime_short_long",
                       "rank_trend_slope", "rank_agreement"]

        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=delta_cols)
        w.writeheader()
        row = {c: "" for c in delta_cols}
        row.update({"date": "2026-06-17", "name": "Technology",
                    "rank_ytd": "1", "rank_ytd_delta_3d": "2", "momentum_score": "0.8"})
        w.writerow(row)
        custom_delta = buf.getvalue()
        snap_body = _snapshot_csv()

        docs_dir = Path(__file__).parent.parent / "docs"
        server = subprocess.Popen(
            ["python3", "-m", "http.server", "8183", "--directory", str(docs_dir)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(1)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context()
                page = ctx.new_page()

                page.route("**/raw.githubusercontent.com/**snapshots.csv",
                           lambda r: r.fulfill(body=snap_body, content_type="text/plain"))
                page.route("**/raw.githubusercontent.com/**deltas.csv",
                           lambda r: r.fulfill(body=custom_delta, content_type="text/plain"))
                page.route("**/data/fetch_log.csv",
                           lambda r: r.fulfill(body="", content_type="text/plain"))
                page.route("**/data/ai/**", lambda r: r.fulfill(status=404))

                page.goto("http://localhost:8183/", wait_until="networkidle",
                          timeout=15000)

                movers_tab = page.locator("[data-tab='movers'], button:has-text('Movers')")
                if movers_tab.count() > 0:
                    movers_tab.first.click()
                    page.wait_for_timeout(500)

                # Derived buttons should match the custom CSV header.
                for win in custom_windows:
                    btn = page.locator(f"button[data-window='{win}']")
                    assert btn.count() > 0, (
                        f"Expected button data-window='{win}' derived from CSV header."
                    )

                # Hardcoded windows must not appear.
                for old_win in ["5d", "10d", "20d", "50d"]:
                    btn = page.locator(f"button[data-window='{old_win}']")
                    assert btn.count() == 0, (
                        f"Hardcoded window button '{old_win}' still appears; "
                        f"buttons are not being derived from CSV header."
                    )

                ctx.close()
                browser.close()
        finally:
            server.terminate()
            server.wait()

    def test_default_lookback_is_5d(self):
        """First load: active lookback button is 5d (the new default)."""
        from playwright.sync_api import sync_playwright

        docs_dir = Path(__file__).parent.parent / "docs"
        server = subprocess.Popen(
            ["python3", "-m", "http.server", "8182", "--directory", str(docs_dir)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(1)

        snap_body = _snapshot_csv()
        delta_body = _delta_csv()

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                # Fresh context — no saved localStorage from prior tests.
                ctx = browser.new_context()
                page = ctx.new_page()

                page.route("**/raw.githubusercontent.com/**snapshots.csv",
                           lambda r: r.fulfill(body=snap_body, content_type="text/plain"))
                page.route("**/raw.githubusercontent.com/**deltas.csv",
                           lambda r: r.fulfill(body=delta_body, content_type="text/plain"))
                page.route("**/data/fetch_log.csv",
                           lambda r: r.fulfill(body="", content_type="text/plain"))
                page.route("**/data/ai/**", lambda r: r.fulfill(status=404))

                page.goto("http://localhost:8182/", wait_until="networkidle",
                          timeout=15000)

                # Navigate to Movers tab.
                movers_tab = page.locator("[data-tab='movers'], button:has-text('Movers')")
                if movers_tab.count() > 0:
                    movers_tab.first.click()
                    page.wait_for_timeout(500)

                # The active (highlighted) lookback button should be 5d.
                active_btn = page.locator("button[data-window='5d'].bg-slate-600")
                assert active_btn.count() > 0, (
                    "Expected 5d to be the active (bg-slate-600) lookback button on first load."
                )

                ctx.close()
                browser.close()
        finally:
            server.terminate()
            server.wait()


# ---------------------------------------------------------------------------
# PWA intro / onboarding tests
# ---------------------------------------------------------------------------

@pytest.mark.functional
class TestPWAIntro:
    """Verify the first-run intro carousel and hub Start Here section.

    Uses the local-server + route-intercept pattern from CLAUDE.md
    "What Playwright in cloud unlocks". Port 8184 to avoid conflicts.
    """

    PORT = 8184

    def _make_page(self, p, snap_body, delta_body, *, clear_intro=True):
        """Return a configured Playwright page with CSV routes mocked."""
        docs_dir = Path(__file__).parent.parent / "docs"
        server = subprocess.Popen(
            ["python3", "-m", "http.server", str(self.PORT), "--directory", str(docs_dir)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(1)
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()

        # Pre-set or clear the intro localStorage key before the page loads.
        # We intercept the first about:blank load to inject storage state.
        if not clear_intro:
            ctx.add_init_script("localStorage.setItem('fvt_intro_seen_v1','true');")

        for pattern in [
            "**/raw.githubusercontent.com/**snapshots.csv",
            "**/raw.githubusercontent.com/**sectors/snapshots.csv",
            "**/raw.githubusercontent.com/**industries/snapshots.csv",
        ]:
            page.route(pattern, lambda r: r.fulfill(body=snap_body, content_type="text/plain"))
        for pattern in [
            "**/raw.githubusercontent.com/**deltas.csv",
            "**/raw.githubusercontent.com/**sectors/deltas.csv",
            "**/raw.githubusercontent.com/**industries/deltas.csv",
        ]:
            page.route(pattern, lambda r: r.fulfill(body=delta_body, content_type="text/plain"))
        page.route("**/data/fetch_log.csv",
                   lambda r: r.fulfill(body="", content_type="text/plain"))
        page.route("**/data/ai/**", lambda r: r.fulfill(status=404))

        return server, browser, ctx, page

    def test_carousel_auto_opens_on_first_visit(self):
        """fvt_intro_seen_v1 unset → carousel auto-opens on load."""
        from playwright.sync_api import sync_playwright
        snap_body = _snapshot_csv()
        delta_body = _delta_csv()
        server = None
        try:
            with sync_playwright() as p:
                server, browser, ctx, page = self._make_page(
                    p, snap_body, delta_body, clear_intro=True
                )
                page.goto(f"http://localhost:{self.PORT}/", wait_until="networkidle",
                          timeout=15000)
                overlay = page.locator("#intro-overlay")
                assert overlay.count() > 0, "#intro-overlay element missing"
                # Should be visible (flex, not hidden)
                assert overlay.is_visible(), "intro overlay should be visible on first visit"
                ctx.close()
                browser.close()
        finally:
            if server:
                server.terminate()
                server.wait()

    def test_skip_dismisses_carousel(self):
        """Clicking Skip hides the carousel."""
        from playwright.sync_api import sync_playwright
        snap_body = _snapshot_csv()
        delta_body = _delta_csv()
        server = None
        try:
            with sync_playwright() as p:
                server, browser, ctx, page = self._make_page(
                    p, snap_body, delta_body, clear_intro=True
                )
                page.goto(f"http://localhost:{self.PORT}/", wait_until="networkidle",
                          timeout=15000)
                page.locator("#intro-skip").click()
                page.wait_for_timeout(200)
                overlay = page.locator("#intro-overlay")
                assert not overlay.is_visible(), "carousel should be hidden after Skip"
                ctx.close()
                browser.close()
        finally:
            if server:
                server.terminate()
                server.wait()

    def test_carousel_stays_dismissed_after_reload(self):
        """After Skip, localStorage persists — carousel must not reopen on reload."""
        from playwright.sync_api import sync_playwright
        snap_body = _snapshot_csv()
        delta_body = _delta_csv()
        server = None
        try:
            with sync_playwright() as p:
                server, browser, ctx, page = self._make_page(
                    p, snap_body, delta_body, clear_intro=True
                )
                page.goto(f"http://localhost:{self.PORT}/", wait_until="networkidle",
                          timeout=15000)
                page.locator("#intro-skip").click()
                page.wait_for_timeout(200)
                # Reload the page in the same context (localStorage persists).
                page.reload(wait_until="networkidle", timeout=15000)
                page.wait_for_timeout(500)
                overlay = page.locator("#intro-overlay")
                assert not overlay.is_visible(), (
                    "carousel should stay hidden after reload when localStorage is set"
                )
                ctx.close()
                browser.close()
        finally:
            if server:
                server.terminate()
                server.wait()

    def test_carousel_not_shown_when_already_seen(self):
        """fvt_intro_seen_v1 already set → no carousel on load."""
        from playwright.sync_api import sync_playwright
        snap_body = _snapshot_csv()
        delta_body = _delta_csv()
        server = None
        try:
            with sync_playwright() as p:
                server, browser, ctx, page = self._make_page(
                    p, snap_body, delta_body, clear_intro=False  # pre-seeds localStorage
                )
                page.goto(f"http://localhost:{self.PORT}/", wait_until="networkidle",
                          timeout=15000)
                page.wait_for_timeout(300)
                overlay = page.locator("#intro-overlay")
                assert not overlay.is_visible(), (
                    "carousel must not auto-open when fvt_intro_seen_v1 is already set"
                )
                ctx.close()
                browser.close()
        finally:
            if server:
                server.terminate()
                server.wait()

    def test_hub_start_here_section_renders(self):
        """Hub 'Start Here' button opens the welcome section with slide content."""
        from playwright.sync_api import sync_playwright
        snap_body = _snapshot_csv()
        delta_body = _delta_csv()
        server = None
        try:
            with sync_playwright() as p:
                server, browser, ctx, page = self._make_page(
                    p, snap_body, delta_body, clear_intro=False
                )
                page.goto(f"http://localhost:{self.PORT}/", wait_until="networkidle",
                          timeout=15000)
                # Open the hub via the ⓘ button
                page.locator("#hub-btn").click()
                page.wait_for_timeout(400)
                # Click "Start Here"
                page.locator(".hub-section-btn[data-section='welcome']").click()
                page.wait_for_timeout(200)
                hub_body = page.locator("#hub-body")
                # Should contain at least one slide title
                assert "Welcome to Finviz Tracker" in hub_body.inner_text() or \
                       "Why groups matter" in hub_body.inner_text(), (
                    "Start Here hub section should render WELCOME slide titles"
                )
                ctx.close()
                browser.close()
        finally:
            if server:
                server.terminate()
                server.wait()

    def test_replay_intro_reopens_carousel(self):
        """Hub Start Here section 'Replay intro' button re-opens the carousel."""
        from playwright.sync_api import sync_playwright
        snap_body = _snapshot_csv()
        delta_body = _delta_csv()
        server = None
        try:
            with sync_playwright() as p:
                server, browser, ctx, page = self._make_page(
                    p, snap_body, delta_body, clear_intro=False
                )
                page.goto(f"http://localhost:{self.PORT}/", wait_until="networkidle",
                          timeout=15000)
                # Open hub → Start Here
                page.locator("#hub-btn").click()
                page.wait_for_timeout(400)
                page.locator(".hub-section-btn[data-section='welcome']").click()
                page.wait_for_timeout(200)
                # Click Replay intro
                page.locator("#hub-body button:has-text('Replay intro')").click()
                page.wait_for_timeout(300)
                overlay = page.locator("#intro-overlay")
                assert overlay.is_visible(), (
                    "clicking 'Replay intro' in the hub should re-open the intro carousel"
                )
                ctx.close()
                browser.close()
        finally:
            if server:
                server.terminate()
                server.wait()


# ---------------------------------------------------------------------------
# Streamlit functional tests
# ---------------------------------------------------------------------------

@pytest.mark.functional
class TestStreamlitLookbackSelector:
    """Verify the Streamlit dashboard's lookback selector shows 5/10/20/50."""

    def test_lookback_selectbox_options(self, tmp_path):
        from playwright.sync_api import sync_playwright

        # Write fixture CSVs to a temp data dir so the dashboard loads without
        # touching the real data/ directory.
        sectors_dir = tmp_path / "data" / "sectors"
        industries_dir = tmp_path / "data" / "industries"
        sectors_dir.mkdir(parents=True)
        industries_dir.mkdir(parents=True)

        for d in [sectors_dir, industries_dir]:
            (d / "snapshots.csv").write_text(_snapshot_csv())
            (d / "deltas.csv").write_text(_delta_csv())

        repo_root = Path(__file__).parent.parent
        env = {
            **__import__("os").environ,
            "PYTHONPATH": str(repo_root),
            # Point the dashboard at the tmp data dir.
            "FINVIZ_DATA_DIR": str(tmp_path / "data"),
        }

        proc = subprocess.Popen(
            [
                sys.executable, "-m", "streamlit", "run",
                str(repo_root / "dashboard" / "app.py"),
                "--server.headless", "true",
                "--server.port", "8503",
                "--server.runOnSave", "false",
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(4)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto("http://localhost:8503/", wait_until="networkidle",
                          timeout=20000)

                # Click the Top Movers tab (index 1 in sidebar or tab strip).
                movers = page.locator("button:has-text('Top Movers'), [data-baseweb='tab']:has-text('Top Movers')")
                if movers.count() > 0:
                    movers.first.click()
                    page.wait_for_timeout(1500)

                # The selectbox for lookback window should have 5d/10d/20d/50d options.
                # Streamlit selectbox shows the current value in a div; open it to see options.
                selectbox = page.locator("[data-testid='stSelectbox']").filter(
                    has_text="Lookback"
                )
                # Fall back to any selectbox if label isn't rendered yet.
                if selectbox.count() == 0:
                    selectbox = page.locator("[data-testid='stSelectbox']").first

                if selectbox.count() > 0:
                    selectbox.click()
                    page.wait_for_timeout(500)
                    # All expected window values should appear as listbox options.
                    expected = [f"{w}d" for w in LOOKBACK_WINDOWS]
                    options_text = page.locator("[role='option']").all_text_contents()
                    for win in expected:
                        assert any(win in opt for opt in options_text), (
                            f"Lookback option '{win}' not found in Streamlit selectbox. "
                            f"Found: {options_text}"
                        )
                    # Old windows should not be present.
                    for old in ["7d", "14d", "30d"]:
                        assert not any(old in opt for opt in options_text), (
                            f"Stale lookback option '{old}' still present in Streamlit selectbox."
                        )

                browser.close()
        finally:
            proc.terminate()
            proc.wait()


@pytest.mark.functional
class TestPWAHub:
    """Verify the Guide & What's New hub (plan: planning/whats-new-and-guide.md §9)."""

    def _serve(self):
        docs_dir = Path(__file__).parent.parent / "docs"
        server = subprocess.Popen(
            ["python3", "-m", "http.server", "8183", "--directory", str(docs_dir)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(1)
        return server

    def _wire_routes(self, page):
        snap_body, delta_body = _snapshot_csv(), _delta_csv()
        page.route("**/raw.githubusercontent.com/**snapshots.csv",
                   lambda r: r.fulfill(body=snap_body, content_type="text/plain"))
        page.route("**/raw.githubusercontent.com/**deltas.csv",
                   lambda r: r.fulfill(body=delta_body, content_type="text/plain"))
        page.route("**/data/fetch_log.csv",
                   lambda r: r.fulfill(body="", content_type="text/plain"))
        page.route("**/data/ai/**", lambda r: r.fulfill(status=404))

    def test_hub_opens_guide_deeplink_and_unseen_dot(self):
        from playwright.sync_api import sync_playwright

        server = self._serve()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                # Fresh context: no stored seen-release → first visit seeds, no dot.
                page = browser.new_page()
                self._wire_routes(page)
                page.goto("http://localhost:8183/", wait_until="networkidle", timeout=15000)

                # First visit: dot is hidden (seeded to current).
                assert page.locator("#hub-dot.hidden").count() == 1

                # ℹ️ opens the hub on What's New, listing release entries.
                page.locator("#hub-btn").click()
                page.wait_for_timeout(400)
                assert page.locator("#hub-overlay:not(.hidden)").count() == 1
                assert "Guide & What's New" in page.locator("#hub-body").inner_text() or \
                       page.locator("#hub-body").inner_text().strip() != ""

                # Switch to Guide; accordions present.
                page.locator(".hub-section-btn[data-section='guide']").click()
                page.wait_for_timeout(200)
                assert page.locator("#guide-momentum_score").count() == 1

                # Contextual deep-link from Today opens hub scrolled to momentum_score.
                page.locator("#hub-close").click()
                page.wait_for_timeout(400)
                page.locator("[data-tab='today']").click()
                page.locator("#tab-today .why-link").first.click()
                page.wait_for_timeout(300)
                assert page.locator("#guide-momentum_score[open]").count() == 1

                browser.close()
        finally:
            server.terminate()
            server.wait()

    def test_guide_tab_filter_and_smart_default(self):
        from playwright.sync_api import sync_playwright

        server = self._serve()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                self._wire_routes(page)
                page.goto("http://localhost:8183/", wait_until="networkidle", timeout=15000)

                # Open hub → Guide; the chip row has all 7 chips.
                page.locator("#hub-btn").click()
                page.wait_for_timeout(300)
                page.locator(".hub-section-btn[data-section='guide']").click()
                page.wait_for_timeout(200)
                assert page.locator(".guide-chip").count() == 7

                # Filter to Momentum: a momentum metric shows, a movers-only one hides.
                page.locator(".guide-chip[data-chip='momentum']").click()
                page.wait_for_timeout(150)
                assert page.locator("#guide-regime_short_long:not(.hidden)").count() == 1
                assert page.locator("#guide-rank_delta.hidden").count() == 1

                # 'All' restores the movers-only metric.
                page.locator(".guide-chip[data-chip='all']").click()
                page.wait_for_timeout(150)
                assert page.locator("#guide-rank_delta:not(.hidden)").count() == 1

                # Smart default: from the Movers tab, opening the Guide scopes to movers.
                page.locator("#hub-close").click()
                page.wait_for_timeout(300)
                page.locator("[data-tab='movers']").click()
                page.wait_for_timeout(150)
                page.locator("#hub-btn").click()
                page.wait_for_timeout(200)
                page.locator(".hub-section-btn[data-section='guide']").click()
                page.wait_for_timeout(200)
                assert page.locator(".guide-chip[data-chip='movers'].bg-sky-600").count() == 1
                assert page.locator("#guide-rank_delta:not(.hidden)").count() == 1
                assert page.locator("#guide-regime_short_long.hidden").count() == 1

                browser.close()
        finally:
            server.terminate()
            server.wait()

    def test_unseen_dot_when_stored_release_is_stale(self):
        from playwright.sync_api import sync_playwright

        server = self._serve()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                context.add_init_script(
                    "localStorage.setItem('fvt_seen_release_v1','2000.01.01');"
                )
                page = context.new_page()
                self._wire_routes(page)
                page.goto("http://localhost:8183/", wait_until="networkidle", timeout=15000)
                page.wait_for_timeout(400)

                # Stale stored version → dot visible + banner shown.
                assert page.locator("#hub-dot:not(.hidden)").count() == 1
                assert page.locator("#update-banner:not(.hidden)").count() == 1

                # Opening the hub clears the dot and persists the seen version to
                # localStorage (so it stays cleared across a real reload). We assert
                # the stored value rather than reloading, because add_init_script
                # re-seeds the stale value on every navigation including reload.
                page.locator("#hub-btn").click()
                page.wait_for_timeout(300)
                page.locator("#hub-close").click()
                page.wait_for_timeout(300)
                assert page.locator("#hub-dot.hidden").count() == 1
                seen = page.evaluate("() => localStorage.getItem('fvt_seen_release_v1')")
                assert seen == "2026.06.20", f"seen release not persisted: {seen!r}"

                browser.close()
        finally:
            server.terminate()
            server.wait()


def _momentum_snapshot_csv() -> str:
    """Three sectors with monotonic perfs so ranks/percentiles are predictable."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=SNAPSHOT_COLS)
    w.writeheader()
    for name, pw, pm in [("Technology", 3.0, 2.5), ("Energy", 1.0, 0.5),
                          ("Healthcare", 2.0, 1.5)]:
        w.writerow({
            "date": "2026-06-17", "collected_at": "2026-06-17T20:00:00Z",
            "group_type": "sector", "name": name,
            "stocks": "100", "market_cap": "5.0", "pe": "25.0", "fwd_pe": "22.0",
            "perf_day": pw * 0.3, "perf_week": pw, "perf_month": pm,
            "perf_quarter": pm * 0.8, "perf_half": pm * 0.6,
            "perf_year": pm * 0.5, "perf_ytd": pw * 0.7,
            "avg_volume": "1000000", "rel_volume": "", "change": pw * 0.3,
        })
    return buf.getvalue()


def _momentum_delta_csv() -> str:
    """Delta fixture exercising the Momentum tab: momentum_confirmed (headline),
    momentum_score (secondary), the full rank set used for percentile evidence, and
    regime_short_long for the Rotation buckets. n=3, so percentile=(3-rank)/2."""
    cols = delta_columns()
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    # rank 1=Technology (best), 2=Healthcare, 3=Energy across every timeframe so the
    # short bucket (wk+mo) and long bucket (qtr+half+yr) percentiles are unambiguous.
    rank_of = {"Technology": "1", "Healthcare": "2", "Energy": "3"}
    rows = [
        # name,        confirmed, score, regime
        ("Technology", "0.72", "0.80", "0.90"),   # short ≫ long → Emerging
        ("Healthcare", "0.45", "0.55", "0.00"),   # balanced → Established
        ("Energy",     "0.10", "0.35", "-0.90"),  # long ≫ short → Fading
    ]
    for name, confirmed, score, regime in rows:
        row = {c: "" for c in cols}
        r = rank_of[name]
        row.update({
            "date": "2026-06-17", "name": name,
            "rank_week": r, "rank_month": r, "rank_quarter": r,
            "rank_half": r, "rank_year": r, "rank_ytd": r,
            "momentum_score": score, "momentum_confirmed": confirmed,
            "rank_agreement": "0.9", "regime_short_long": regime,
        })
        w.writerow(row)
    return buf.getvalue()


@pytest.mark.functional
class TestPWAMomentum:
    """Verify the Momentum tab headlines momentum_confirmed and shows percentile
    evidence in the Rotation view (PR: Momentum tab improvements A/B/C/D)."""

    def _run(self, port, fn):
        from playwright.sync_api import sync_playwright

        docs_dir = Path(__file__).parent.parent / "docs"
        server = subprocess.Popen(
            ["python3", "-m", "http.server", str(port), "--directory", str(docs_dir)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(1)
        snap_body, delta_body = _momentum_snapshot_csv(), _momentum_delta_csv()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                # ignore_https_errors: TLS-intercepting proxy in cloud envs breaks the
                # CDN <script> certs otherwise (see CLAUDE.md Playwright notes).
                context = browser.new_context(ignore_https_errors=True)
                # Skip the first-run intro carousel so it doesn't intercept tab clicks.
                context.add_init_script("localStorage.setItem('fvt_intro_seen_v1','true');")
                page = context.new_page()
                page.route("**/raw.githubusercontent.com/**snapshots.csv",
                           lambda r: r.fulfill(body=snap_body, content_type="text/plain"))
                page.route("**/raw.githubusercontent.com/**deltas.csv",
                           lambda r: r.fulfill(body=delta_body, content_type="text/plain"))
                page.route("**/data/fetch_log.csv",
                           lambda r: r.fulfill(body="", content_type="text/plain"))
                page.route("**/data/ai/**", lambda r: r.fulfill(status=404))
                page.goto(f"http://localhost:{port}/", wait_until="networkidle", timeout=15000)
                page.locator("[data-tab='momentum']").click()
                page.wait_for_timeout(400)
                fn(page)
                browser.close()
        finally:
            server.terminate()
            server.wait()

    def test_momentum_headline_is_confirmed_with_score_secondary(self):
        def check(page):
            txt = page.locator("#momentum-list").inner_text()
            # Headline = momentum_confirmed (0.72 → 72%); raw score shown as secondary.
            assert "72%" in txt, txt
            assert "Score 80%" in txt, txt
            # Tab description reflects the confirmed framing, not the old "100% = top".
            assert "Confirmed momentum" in page.locator("#momentum-tab-desc").inner_text()
        self._run(8184, check)

    def test_rotation_shows_percentile_evidence(self):
        def check(page):
            page.locator(".momentum-view-btn[data-mview='rotation']").click()
            page.wait_for_timeout(300)
            txt = page.locator("#momentum-list").inner_text()
            # Percentile evidence replaces the old raw-% "Short: Wk +X%" line.
            assert "pctile" in txt, txt
            # Technology: short bucket rank 1 → 100th percentile.
            assert "Short 100th" in txt, txt
            # Buckets render with their headers (CSS uppercases them).
            assert "EMERGING" in txt.upper() and "FADING" in txt.upper(), txt
        self._run(8185, check)


# ---------------------------------------------------------------------------
# Card deep-link tests (PR #165 — card tap → Lookup)
# ---------------------------------------------------------------------------

def _deeplink_snapshot_csv() -> str:
    """Snapshot fixture for deep-link tests: 4 groups, 3 with all-positive perfs
    (Technology, Healthcare, Oil & Gas) for All Green coverage. Energy is negative."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=SNAPSHOT_COLS)
    w.writeheader()
    for name, pw, pm in [
        ("Technology", 4.0,  3.0),
        ("Healthcare", 2.0,  1.5),
        ("Energy",    -1.0, -0.5),   # negative: excluded from All Green
        ("Oil & Gas",  1.5,  1.0),   # ampersand name; all positive perfs
    ]:
        abs_pm = abs(pm)
        w.writerow({
            "date": "2026-06-17", "collected_at": "2026-06-17T20:00:00Z",
            "group_type": "sector", "name": name,
            "stocks": "100", "market_cap": "5.0", "pe": "25.0", "fwd_pe": "22.0",
            "perf_day": abs(pw) * 0.2, "perf_week": pw, "perf_month": pm,
            "perf_quarter": abs_pm * 0.8, "perf_half": abs_pm * 0.6,
            "perf_year": abs_pm * 0.5, "perf_ytd": abs(pw) * 0.7,
            "avg_volume": "1000000", "rel_volume": "", "change": pw * 0.2,
        })
    return buf.getvalue()


def _deeplink_delta_csv() -> str:
    """Delta fixture for deep-link tests: full RS + momentum + regime columns.
    Technology rank 1, Healthcare 2, Energy 3, Oil & Gas 4.
    RS columns non-empty so vs Market tab renders its card list."""
    cols = delta_columns()
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    entries = [
        # name,       rank, confirmed, score,  regime,  rs_score, rs_regime
        ("Technology",  "1", "0.80",  "0.90",  "0.90",  "0.86",   "0.80"),
        ("Healthcare",  "2", "0.50",  "0.60",  "0.00",  "0.50",   "0.00"),
        ("Energy",      "3", "0.15",  "0.30",  "-0.80", "0.14",  "-0.80"),
        ("Oil & Gas",   "4", "0.20",  "0.35",  "-0.40", "0.30",  "-0.40"),
    ]
    for name, rank, confirmed, score, regime, rs_score, rs_regime in entries:
        row = {c: "" for c in cols}
        row.update({
            "date": "2026-06-17", "name": name,
            "rank_week": rank, "rank_month": rank, "rank_quarter": rank,
            "rank_half": rank, "rank_year": rank, "rank_ytd": rank,
            "momentum_score": score, "momentum_confirmed": confirmed,
            "rank_agreement": "0.9",
            "regime_short_long": regime,
            "rs_score": rs_score, "rs_regime_short_long": rs_regime,
            f"rank_ytd_delta_{LOOKBACK_WINDOWS[0]}d": "2",
        })
        w.writerow(row)
    return buf.getvalue()


@pytest.mark.functional
class TestPWACardDeeplink:
    """Verify card-tap → Lookup deep-link for all 6 new card types (PR #165).

    Each test: navigate to the target tab/view, click a [data-group-name] card
    (or [data-today-lookup] button for Today), assert the group name appears in
    #lookup-result (i.e., doGroupLookup was called and renderLookup rendered it).
    """

    PORT = 8185

    def _run(self, fn):
        from playwright.sync_api import sync_playwright

        docs_dir = Path(__file__).parent.parent / "docs"
        server = subprocess.Popen(
            ["python3", "-m", "http.server", str(self.PORT), "--directory", str(docs_dir)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(1)
        snap_body = _deeplink_snapshot_csv()
        delta_body = _deeplink_delta_csv()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(ignore_https_errors=True)
                ctx.add_init_script("localStorage.setItem('fvt_intro_seen_v1','true');")
                page = ctx.new_page()
                page.route("**/raw.githubusercontent.com/**snapshots.csv",
                           lambda r: r.fulfill(body=snap_body, content_type="text/plain"))
                page.route("**/raw.githubusercontent.com/**deltas.csv",
                           lambda r: r.fulfill(body=delta_body, content_type="text/plain"))
                page.route("**/data/fetch_log.csv",
                           lambda r: r.fulfill(body="", content_type="text/plain"))
                page.route("**/data/ai/**", lambda r: r.fulfill(status=404))
                page.goto(f"http://localhost:{self.PORT}/", wait_until="networkidle",
                          timeout=15000)
                fn(page)
                ctx.close()
                browser.close()
        finally:
            server.terminate()
            server.wait()

    def _click_card_assert_lookup(self, page, container_id, group_name):
        """Click the first [data-group-name] card in container; assert group in #lookup-result."""
        container = page.locator(f"#{container_id}")
        card = container.locator(f"[data-group-name='{group_name}']").first
        assert card.count() > 0, \
            f"No card with data-group-name='{group_name}' in #{container_id}"
        card.click()
        page.wait_for_timeout(400)
        result = page.locator("#lookup-result").inner_text()
        assert group_name in result, \
            f"Expected '{group_name}' in lookup result, got: {result[:200]}"

    def test_momentum_card_tap_opens_lookup(self):
        """Click a Momentum card; assert Lookup tab becomes active and shows that group."""
        def check(page):
            page.locator("[data-tab='momentum']").click()
            page.wait_for_timeout(400)
            self._click_card_assert_lookup(page, "momentum-list", "Technology")
        self._run(check)

    def test_rotation_card_tap_opens_lookup(self):
        """Switch to Rotation view on Momentum tab; click a card; assert Lookup opens."""
        def check(page):
            page.locator("[data-tab='momentum']").click()
            page.wait_for_timeout(400)
            page.locator(".momentum-view-btn[data-mview='rotation']").click()
            page.wait_for_timeout(300)
            self._click_card_assert_lookup(page, "momentum-list", "Technology")
        self._run(check)

    def test_strength_card_tap_opens_lookup(self):
        """Click a Sustained Strength card; assert Lookup tab opens."""
        def check(page):
            page.locator("[data-tab='strength']").click()
            page.wait_for_timeout(400)
            self._click_card_assert_lookup(page, "strength-list", "Technology")
        self._run(check)

    def test_allgreen_card_tap_opens_lookup(self):
        """Switch to All Green view on Strength tab; click a card; assert Lookup opens."""
        def check(page):
            page.locator("[data-tab='strength']").click()
            page.wait_for_timeout(400)
            page.locator(".strength-view-btn[data-view='allgreen']").click()
            page.wait_for_timeout(300)
            self._click_card_assert_lookup(page, "strength-list", "Technology")
        self._run(check)

    def test_rscore_card_tap_opens_lookup(self):
        """Click an RS Score card on vs Market tab; assert Lookup tab opens."""
        def check(page):
            page.locator("[data-tab='vsmarket']").click()
            page.wait_for_timeout(400)
            self._click_card_assert_lookup(page, "vsmarket-list", "Technology")
        self._run(check)

    def test_rsregime_card_tap_opens_lookup(self):
        """Switch to RS Regime view; click a card; assert Lookup tab opens."""
        def check(page):
            page.locator("[data-tab='vsmarket']").click()
            page.wait_for_timeout(400)
            page.locator(".vsmarket-view-btn[data-mview='regime']").click()
            page.wait_for_timeout(300)
            self._click_card_assert_lookup(page, "vsmarket-list", "Technology")
        self._run(check)

    def test_today_card_lookup_button(self):
        """Tap the › lookup button on a Today card; Lookup opens, card does NOT expand."""
        def check(page):
            # Today tab is default — already on it.
            btn = page.locator("[data-today-lookup='Technology']").first
            assert btn.count() > 0, "Expected Today card lookup button for Technology"
            btn.click()
            page.wait_for_timeout(400)
            # Lookup tab is now active.
            result = page.locator("#lookup-result").inner_text()
            assert "Technology" in result, \
                f"Expected 'Technology' in lookup result: {result[:200]}"
            # Switching to Lookup hides Today — confirm Lookup section is not hidden.
            lookup_cls = page.locator("#tab-lookup").get_attribute("class") or ""
            assert "hidden" not in lookup_cls, \
                "Lookup section should be visible after tapping the › button"
        self._run(check)

    def test_ampersand_group_name_round_trips(self):
        """Tap an industry card whose name contains '&'; Lookup renders the decoded name.

        Sectors have no '&' names; switch to Industries to get names like
        'Aerospace & Defense'. Uses has_text filter rather than attribute-value CSS
        selector because Playwright's CSS engine can mishandle '&' in attribute selectors.
        The data-group-name attribute value is verified separately via get_attribute()
        (Playwright returns the decoded DOM value, not the raw HTML entity).
        """
        def check(page):
            page.locator("[data-tab='momentum']").click()
            page.wait_for_timeout(400)
            # Switch to Industries so cards with '&' in their names appear.
            page.locator("#tab-momentum .group-toggle-btn[data-group='industries']").click()
            page.wait_for_load_state("networkidle", timeout=20000)
            page.wait_for_timeout(500)
            container = page.locator("#momentum-list")
            # Find the first industry card with '&' in its name.
            card = container.locator("[data-group-name]").filter(has_text="&").first
            assert card.count() > 0, \
                "Expected at least one industry Momentum card with '&' in its name"
            # Verify the attribute value contains '&' and NOT the HTML entity '&amp;'.
            attr_val = card.get_attribute("data-group-name")
            assert attr_val is not None, "data-group-name attribute must be present"
            assert "&" in attr_val, \
                f"data-group-name should contain '&', got: {attr_val!r}"
            assert "&amp;" not in attr_val, \
                f"data-group-name should not contain HTML entity, got: {attr_val!r}"
            card.click()
            page.wait_for_timeout(400)
            result = page.locator("#lookup-result").inner_text()
            assert attr_val in result, \
                f"Expected {attr_val!r} in lookup result: {result[:200]}"
            assert "&amp;" not in result, \
                f"HTML entity should not appear in inner_text: {result[:200]}"
        self._run(check)


@pytest.mark.functional
class TestPWALookupChart:
    """Ticker lookup's lazy-loaded TradingView chart toggle.

    Covers part of Gap 6 (see TODO block at top of file): intercepts the
    Worker /lookup endpoint and drives a ticker search, then verifies the
    chart panel is absent until the user opens it (no iframe on every
    lookup) and correctly targets the looked-up symbol once opened.
    """

    PORT = 8187

    def _run(self, fn):
        from playwright.sync_api import sync_playwright

        docs_dir = Path(__file__).parent.parent / "docs"
        server = subprocess.Popen(
            ["python3", "-m", "http.server", str(self.PORT), "--directory", str(docs_dir)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(1)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(ignore_https_errors=True)
                ctx.add_init_script("localStorage.setItem('fvt_intro_seen_v1','true');")
                page = ctx.new_page()
                page.route("**/raw.githubusercontent.com/**", lambda r: r.fulfill(status=404))
                page.route("**/finviz-ticker-lookup.salmonbaby8.workers.dev/lookup*",
                            lambda r: r.fulfill(
                                body='{"symbol":"AAPL","company_name":"Apple Inc.",'
                                     '"exchange":"NASDAQ","market_cap_b":3000,'
                                     '"finviz_industry":"Consumer Electronics",'
                                     '"finviz_sector":"Technology","industry_confidence":0.9,'
                                     '"image":null,"etf_kind":null}',
                                content_type="application/json"))
                page.goto(f"http://localhost:{self.PORT}/", wait_until="domcontentloaded",
                          timeout=15000)
                page.wait_for_timeout(500)
                fn(page)
                ctx.close()
                browser.close()
        finally:
            server.terminate()
            server.wait()

    def test_chart_hidden_until_toggled_open(self):
        """No iframe renders on a fresh ticker lookup; the toggle button is present."""
        def check(page):
            page.locator("[data-tab='lookup']").click()
            page.fill("#ticker-input", "AAPL")
            page.locator("#ticker-submit").click()
            page.wait_for_timeout(800)
            assert page.locator("#lookup-result iframe").count() == 0, \
                "Chart iframe must not load until the user opens the panel"
            toggle = page.locator(".lookup-chart-toggle")
            assert toggle.count() == 1
            assert "Show chart" in toggle.inner_text()
        self._run(check)

    def test_toggle_opens_chart_with_symbol_and_closes(self):
        """Clicking the toggle lazily inserts an iframe scoped to the looked-up symbol."""
        def check(page):
            page.locator("[data-tab='lookup']").click()
            page.fill("#ticker-input", "AAPL")
            page.locator("#ticker-submit").click()
            page.wait_for_timeout(800)

            page.locator(".lookup-chart-toggle").click()
            page.wait_for_timeout(200)
            iframe = page.locator("#lookup-result iframe")
            assert iframe.count() == 1
            src = iframe.get_attribute("src")
            assert src.startswith("https://s.tradingview.com/embed-widget/advanced-chart/")
            assert "AAPL" in src
            assert "Hide chart" in page.locator(".lookup-chart-toggle").inner_text()

            page.locator(".lookup-chart-toggle").click()
            page.wait_for_timeout(200)
            assert page.locator("#lookup-result iframe").count() == 0
            assert "Show chart" in page.locator(".lookup-chart-toggle").inner_text()
        self._run(check)
