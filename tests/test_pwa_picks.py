"""
Playwright functional tests for the PWA Picks tab — Phase 3b acceptance criteria.

Covers:
- renderPickRow() helper extracted and used for All view rows
- Expandable risk panel (HoD, 20MA/50MA stops, extension, tightness lines)
- All / Focus toggle: Focus DQ logic, reset on tab entry
- Focus scoring: all scores ∈ [0,1]; extension penalty observable in ordering
- Nearest-positive-MA stop: TESTAB20 (above 50MA, below 20MA) correctly scored
- Normalization edge cases implied by pool composition

Run manually (needs Playwright + Chromium installed):
    python3 -m playwright install chromium
    python3 -m pytest tests/test_pwa_picks.py -v

Skipped automatically when Playwright is not installed.
"""

import io
import subprocess
import time
import csv
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
FIXTURE_PICKS = ROOT / "tests" / "fixtures" / "picks_latest.csv"
DOCS_DIR = ROOT / "docs"
TEST_PORT = 8085


def _empty_snapshot_csv():
    cols = [
        "date", "collected_at", "group_type", "name", "stocks", "market_cap",
        "pe", "fwd_pe", "perf_day", "perf_week", "perf_month", "perf_quarter",
        "perf_half", "perf_year", "perf_ytd", "avg_volume", "rel_volume", "change",
    ]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    # One minimal sector row so the PWA doesn't show error state
    w.writerow({
        "date": "2026-06-25", "collected_at": "2026-06-25T20:00:00Z",
        "group_type": "sector", "name": "Technology",
        "stocks": "500", "market_cap": "50.0", "pe": "25.0", "fwd_pe": "22.0",
        "perf_day": "0.5", "perf_week": "1.0", "perf_month": "2.0",
        "perf_quarter": "5.0", "perf_half": "8.0", "perf_year": "12.0", "perf_ytd": "10.0",
        "avg_volume": "1000000", "rel_volume": "", "change": "0.5",
    })
    return buf.getvalue()


def _empty_delta_csv():
    """Minimal delta CSV — just enough to avoid PWA parse errors."""
    # Import delta_columns from the scripts directory
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    from delta_config import delta_columns
    cols = delta_columns()
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    row = {c: "" for c in cols}
    row.update({
        "date": "2026-06-25", "name": "Technology",
        "momentum_score": "0.80", "rank_agreement": "0.9",
        "rank_week": "1", "rank_ytd": "1",
    })
    w.writerow(row)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Shared page fixture
# ---------------------------------------------------------------------------

class _PicksPage:
    """Context manager: starts http.server, creates a Playwright page with
    route intercepts pointing the PWA at our fixture picks_latest.csv."""

    def __init__(self):
        self._server = None
        self._pw_cm = None   # sync_playwright() context manager
        self._playwright = None  # Playwright object (result of __enter__)
        self._browser = None
        self.page = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        self._server = subprocess.Popen(
            ["python3", "-m", "http.server", str(TEST_PORT), "--directory", str(DOCS_DIR),
             "--bind", "0.0.0.0"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(1)

        snap_body  = _empty_snapshot_csv()
        delta_body = _empty_delta_csv()
        picks_body = FIXTURE_PICKS.read_text()
        taxonomy   = '{"sectors":{"Technology":["Semiconductors","Computer Hardware"]}}'

        # Keep context manager separate from the Playwright object it returns
        self._pw_cm = sync_playwright()
        self._playwright = self._pw_cm.__enter__()
        # --proxy-server=direct:// bypasses HTTPS_PROXY which would block localhost connections.
        # --ignore-certificate-errors lets CDN resources (PapaParse, Tailwind) load through the
        # transparent network proxy without needing its CA cert in Chromium's trust store.
        # Both flags are safe in this headless test context (no user credentials, fixture data only).
        self._browser = self._playwright.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--proxy-server=direct://', '--ignore-certificate-errors'],
        )
        page = self._browser.new_page()

        # Pre-seed localStorage to suppress the first-run intro carousel overlay,
        # which would otherwise block clicks on nav tabs.
        # Use v2 — the key was bumped in Phase 3a (see INTRO_KEY in index.html).
        page.add_init_script("localStorage.setItem('fvt_intro_seen_v2', 'true');")

        # Intercept all raw.githubusercontent.com CSV/JSON fetches
        page.route("**/raw.githubusercontent.com/**sectors/snapshots.csv",
                   lambda r: r.fulfill(body=snap_body, content_type="text/plain"))
        page.route("**/raw.githubusercontent.com/**sectors/deltas.csv",
                   lambda r: r.fulfill(body=delta_body, content_type="text/plain"))
        page.route("**/raw.githubusercontent.com/**industries/snapshots.csv",
                   lambda r: r.fulfill(body=snap_body, content_type="text/plain"))
        page.route("**/raw.githubusercontent.com/**industries/deltas.csv",
                   lambda r: r.fulfill(body=delta_body, content_type="text/plain"))
        page.route("**/raw.githubusercontent.com/**benchmark/snapshots.csv",
                   lambda r: r.fulfill(body="date,collected_at,group_type,name,perf_week,perf_month,perf_quarter,perf_half,perf_year,perf_ytd\n",
                                       content_type="text/plain"))
        page.route("**/raw.githubusercontent.com/**picks/picks_latest.csv",
                   lambda r: r.fulfill(body=picks_body, content_type="text/plain"))
        page.route("**/raw.githubusercontent.com/**finviz_sector_industry_map.json",
                   lambda r: r.fulfill(body=taxonomy, content_type="application/json"))
        # Silence non-critical endpoints
        page.route("**/raw.githubusercontent.com/**fetch_log.csv",
                   lambda r: r.fulfill(body="", content_type="text/plain"))
        page.route("**/raw.githubusercontent.com/**ai/**",
                   lambda r: r.fulfill(status=404))
        page.route("**/finviz-ticker-lookup**", lambda r: r.fulfill(status=404))

        page.goto(f"http://127.0.0.1:{TEST_PORT}/", wait_until="networkidle", timeout=20000)
        self.page = page
        return self

    def __exit__(self, *_):
        if self._browser:
            self._browser.close()
        if self._pw_cm:
            self._pw_cm.__exit__(None, None, None)
        if self._server:
            self._server.terminate()
            self._server.wait()

    def go_to_picks_tab(self):
        """Click the Picks tab and wait for picks-list to appear."""
        picks_tab = self.page.locator("button[data-tab='picks'], button:has-text('Picks')")
        picks_tab.first.click()
        self.page.wait_for_timeout(800)

    def click_focus(self):
        """Click the Focus toggle button."""
        self.page.locator("#picks-toggle-focus").click()
        self.page.wait_for_timeout(400)

    def click_all(self):
        """Click the All toggle button."""
        self.page.locator("#picks-toggle-all").click()
        self.page.wait_for_timeout(400)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.functional
class TestPicksTab3b:
    """Phase 3b acceptance tests for the PWA Picks tab."""

    def test_picks_tab_exists(self):
        """Picks tab button is present in the nav bar."""
        try:
            with _PicksPage() as ctx:
                tab = ctx.page.locator("button[data-tab='picks'], button:has-text('Picks')")
                assert tab.count() > 0, "Picks tab button not found"
        except ImportError:
            pytest.skip("playwright not installed")

    def test_toggle_buttons_present(self):
        """All and Focus toggle buttons are present when on the Picks tab."""
        try:
            with _PicksPage() as ctx:
                ctx.go_to_picks_tab()
                assert ctx.page.locator("#picks-toggle-all").count() > 0, "All button missing"
                assert ctx.page.locator("#picks-toggle-focus").count() > 0, "Focus button missing"
        except ImportError:
            pytest.skip("playwright not installed")

    def test_all_view_base_filter_removes_small_cap(self):
        """TESTMC (market cap 2B < 5B floor) is excluded from All view."""
        try:
            with _PicksPage() as ctx:
                ctx.go_to_picks_tab()
                picks_list = ctx.page.locator("#picks-list").inner_text()
                assert "TESTMC" not in picks_list, "TESTMC (2B cap) should be hidden by base filter"
        except ImportError:
            pytest.skip("playwright not installed")

    def test_all_view_base_filter_removes_blank_sma(self):
        """TESTBLK (blank SMA columns) is excluded from All view (no price-structure signal)."""
        try:
            with _PicksPage() as ctx:
                ctx.go_to_picks_tab()
                picks_list = ctx.page.locator("#picks-list").inner_text()
                assert "TESTBLK" not in picks_list, "TESTBLK (blank SMAs) should be hidden by base filter"
        except ImportError:
            pytest.skip("playwright not installed")

    def test_all_view_real_picks_visible(self):
        """ANET, STX, DELL, SNDK appear in All view (pass base filter, large cap)."""
        try:
            with _PicksPage() as ctx:
                ctx.go_to_picks_tab()
                picks_list = ctx.page.locator("#picks-list").inner_text()
                for ticker in ["ANET", "STX", "DELL", "SNDK"]:
                    assert ticker in picks_list, f"{ticker} should appear in All view"
        except ImportError:
            pytest.skip("playwright not installed")

    def test_all_view_trim_tag_on_high_extension(self):
        """TESTHGH (9.0×) shows trim label in All view."""
        try:
            with _PicksPage() as ctx:
                ctx.go_to_picks_tab()
                picks_html = ctx.page.locator("#picks-list").inner_html()
                assert "trim" in picks_html, "trim label should appear for TESTHGH (9.0× extension)"
        except ImportError:
            pytest.skip("playwright not installed")

    def test_all_view_risk_panel_toggle(self):
        """Clicking a row in All view expands the risk panel showing HoD and stop levels."""
        try:
            with _PicksPage() as ctx:
                ctx.go_to_picks_tab()
                # Click first expandable row (picks-list has rows with onclick=__togglePickRow)
                first_row = ctx.page.locator("#picks-list [onclick*='__togglePickRow']").first
                assert first_row.count() > 0, "No expandable rows found"
                first_row.click()
                ctx.page.wait_for_timeout(200)
                # Check that at least one risk panel is now visible
                panels = ctx.page.locator("#picks-list [id^='risk-panel-']")
                visible = [panels.nth(i) for i in range(panels.count())
                           if panels.nth(i).is_visible()]
                assert len(visible) > 0, "No risk panel became visible after clicking row"
                # Panel should contain HoD label
                panel_text = "".join(p.inner_text() for p in visible)
                assert "HoD" in panel_text or "next buy" in panel_text, \
                    "Risk panel should show HoD (next buy trigger)"
        except ImportError:
            pytest.skip("playwright not installed")

    def test_risk_panel_shows_stop_levels(self):
        """Risk panel shows 20MA and 50MA stop sections."""
        try:
            with _PicksPage() as ctx:
                ctx.go_to_picks_tab()
                first_row = ctx.page.locator("#picks-list [onclick*='__togglePickRow']").first
                first_row.click()
                ctx.page.wait_for_timeout(200)
                panels = ctx.page.locator("#picks-list [id^='risk-panel-']:visible")
                if panels.count() == 0:
                    # Try alternative: any visible div that was hidden before click
                    visible = ctx.page.locator("#picks-list [id^='risk-panel-']").first
                    panel_html = visible.inner_html()
                else:
                    panel_html = panels.first.inner_html()
                assert "20MA" in panel_html or "stop" in panel_html.lower(), \
                    "Risk panel should mention 20MA stop"
                assert "50MA" in panel_html, "Risk panel should mention 50MA stop"
        except ImportError:
            pytest.skip("playwright not installed")

    def test_focus_toggle_switches_view(self):
        """Clicking Focus changes the toggle button appearance."""
        try:
            with _PicksPage() as ctx:
                ctx.go_to_picks_tab()
                # All should be active initially
                all_btn = ctx.page.locator("#picks-toggle-all")
                focus_btn = ctx.page.locator("#picks-toggle-focus")
                assert "text-white" in (all_btn.get_attribute("class") or ""), \
                    "All button should be active (text-white) initially"
                # Click Focus
                ctx.click_focus()
                assert "text-white" in (focus_btn.get_attribute("class") or ""), \
                    "Focus button should be active after click"
        except ImportError:
            pytest.skip("playwright not installed")

    def test_focus_excludes_over_extended(self):
        """Focus view excludes TESTDQ (6.0× > 5.0 hard-DQ) and TESTHGH (9.0×)."""
        try:
            with _PicksPage() as ctx:
                ctx.go_to_picks_tab()
                ctx.click_focus()
                picks_text = ctx.page.locator("#picks-list").inner_text()
                assert "TESTDQ" not in picks_text, "TESTDQ (6.0×) should be DQ'd from Focus"
                assert "TESTHGH" not in picks_text, "TESTHGH (9.0×) should be DQ'd from Focus"
        except ImportError:
            pytest.skip("playwright not installed")

    def test_focus_excludes_below_50ma(self):
        """Focus view excludes TESTBEL (atr_ext_50 = -0.95, price below 50MA)."""
        try:
            with _PicksPage() as ctx:
                ctx.go_to_picks_tab()
                ctx.click_focus()
                picks_text = ctx.page.locator("#picks-list").inner_text()
                assert "TESTBEL" not in picks_text, "TESTBEL (below 50MA) should be excluded from Focus"
        except ImportError:
            pytest.skip("playwright not installed")

    def test_focus_includes_above_50ma_below_20ma(self):
        """TESTAB20 (above 50MA, below 20MA) passes Focus gate and appears in Focus view."""
        try:
            with _PicksPage() as ctx:
                ctx.go_to_picks_tab()
                ctx.click_focus()
                picks_text = ctx.page.locator("#picks-list").inner_text()
                assert "TESTAB20" in picks_text, \
                    "TESTAB20 (above 50MA, below 20MA) should appear in Focus (positive atr_ext_50=0.58)"
        except ImportError:
            pytest.skip("playwright not installed")

    def test_focus_scores_all_in_range(self):
        """All score badges in Focus view show integers between 0 and 100."""
        try:
            with _PicksPage() as ctx:
                ctx.go_to_picks_tab()
                ctx.click_focus()
                # Score badges are <span class="... text-indigo-300 ...">NN</span>
                badges = ctx.page.locator("#picks-list span.text-indigo-300")
                count = badges.count()
                assert count > 0, "No score badges found in Focus view"
                for i in range(count):
                    text = badges.nth(i).inner_text().strip()
                    try:
                        v = int(text)
                        assert 0 <= v <= 100, f"Score badge {text!r} out of [0,100] range"
                    except ValueError:
                        pytest.fail(f"Score badge {text!r} is not an integer")
        except ImportError:
            pytest.skip("playwright not installed")

    def test_focus_score_debug_in_risk_panel(self):
        """Expanding a row in Focus view shows the score component breakdown (tuning aid)."""
        try:
            with _PicksPage() as ctx:
                ctx.go_to_picks_tab()
                ctx.click_focus()
                first_row = ctx.page.locator("#picks-list [onclick*='__togglePickRow']").first
                first_row.click()
                ctx.page.wait_for_timeout(200)
                # Find any now-visible risk panel
                panel = ctx.page.locator("#picks-list [id^='risk-panel-']").first
                panel_text = panel.inner_html()
                # Score debug shows "Group", "Tight", "Quiet", "base", "score"
                assert "Group" in panel_text, "Score debug should show Group component"
                assert "Tight" in panel_text, "Score debug should show Tight component"
                assert "Quiet" in panel_text, "Score debug should show Quiet component"
                assert "score" in panel_text.lower(), "Score debug should show final score"
        except ImportError:
            pytest.skip("playwright not installed")

    def test_focus_reset_on_tab_reentry(self):
        """Switching away from Picks and back resets the view to All (A4)."""
        try:
            with _PicksPage() as ctx:
                ctx.go_to_picks_tab()
                ctx.click_focus()
                # Confirm Focus is active
                focus_btn = ctx.page.locator("#picks-toggle-focus")
                assert "text-white" in (focus_btn.get_attribute("class") or ""), \
                    "Focus should be active before switching away"
                # Switch to a different tab
                today_tab = ctx.page.locator("button[data-tab='today'], button:has-text('Today')")
                today_tab.first.click()
                ctx.page.wait_for_timeout(300)
                # Return to Picks
                ctx.go_to_picks_tab()
                # All button should now be active (reset to 'all')
                all_btn = ctx.page.locator("#picks-toggle-all")
                assert "text-white" in (all_btn.get_attribute("class") or ""), \
                    "After re-entering Picks tab, view should reset to All (A4)"
        except ImportError:
            pytest.skip("playwright not installed")

    def test_extension_penalty_observable(self):
        """Less-extended Focus candidates rank above more-extended ones (qualitative penalty check).

        ANET (0.67×) has a lower extension than SNDK (4.55×) and similar group strength
        (same Computer Hardware group). ANET should rank above SNDK in Focus view.
        """
        try:
            with _PicksPage() as ctx:
                ctx.go_to_picks_tab()
                ctx.click_focus()
                picks_text = ctx.page.locator("#picks-list").inner_text()
                # Both must appear in Focus
                assert "ANET" in picks_text, "ANET not found in Focus"
                assert "SNDK" in picks_text, "SNDK not found in Focus"
                # ANET should appear before SNDK (ranked higher due to lower extension)
                anet_pos = picks_text.find("ANET")
                sndk_pos = picks_text.find("SNDK")
                assert anet_pos < sndk_pos, \
                    "ANET (0.67×) should rank above SNDK (4.55×) in Focus due to lower extension penalty"
        except ImportError:
            pytest.skip("playwright not installed")
