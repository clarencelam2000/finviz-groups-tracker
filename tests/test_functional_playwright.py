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
