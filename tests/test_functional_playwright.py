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
