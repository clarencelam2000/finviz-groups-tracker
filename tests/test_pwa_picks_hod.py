"""
Playwright functional tests for the Picks tab HoD / Last price-basis toggle (Phase A).

Spec: planning/picks-hod-price-basis-toggle.md §7

Tests covered:
  1. Regression anchor — Last mode reproduces stored CSV atr_ext_50 / risk_* values.
  2. HoD toggle changes atr_ext_50 and risk_* upward vs Last (HoD > Close).
  3. Bar/instrument properties (range_atr, ATR%) stay fixed between Last and HoD.
  4. Collapse resets basis to Last.
  5. trim→extended label swap when atrExt ≥ ATR_EXT_TRIM in HoD mode (uses TESTHOD fixture row).

Run with Playwright installed:
    python3 -m playwright install chromium
    python3 -m pytest tests/test_pwa_picks_hod.py -v -m functional
"""

import csv
import io
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "picks_latest.csv"


def _picks_csv_body() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def _launch_server(port: int):
    docs_dir = ROOT / "docs"
    return subprocess.Popen(
        ["python3", "-m", "http.server", str(port), "--directory", str(docs_dir)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


# ---------------------------------------------------------------------------
# Helpers to build a picks_latest.csv with one known row so we can assert
# predictable values without depending on the fixture evolving.
# ---------------------------------------------------------------------------

def _single_row_csv(overrides: dict) -> str:
    """Build a one-row picks_latest.csv using ANET as the base, with overrides."""
    with FIXTURE.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames
        rows = list(reader)

    # Find ANET row as base
    base = next(r for r in rows if r["ticker"] == "ANET")
    row = dict(base)
    row.update(overrides)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols)
    writer.writeheader()
    writer.writerow(row)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.functional
class TestPicksHodToggle:
    """Phase A: per-card [ Last | HoD ] toggle inside the expanded risk panel."""

    PORT = 8183

    @pytest.fixture(autouse=True, scope="class")
    def server(self):
        proc = _launch_server(self.PORT)
        time.sleep(1)
        yield proc
        proc.terminate()
        proc.wait()

    def _open_picks_tab(self, page, picks_body: str):
        """Navigate to the PWA, intercept the picks_latest.csv fetch, open Picks tab.

        Route globs use the "**/filename.ext" form (a literal "/" immediately before the
        filename) — "**domain**filename" silently never matches and falls through to the
        real network (see knowledge/investigations/playwright-cloud-session-testing.md,
        Root cause 3). CDN scripts (Tailwind/PapaParse) must also be stubbed or the app
        never boots in an environment where Chromium can't reach the real CDNs (Root
        cause 2) — and "domcontentloaded" is used instead of "networkidle" since the app
        has no further network activity worth waiting on once those are stubbed.
        """
        papaparse_js = (ROOT / "tests" / "fixtures" / "papaparse.min.js").read_text(encoding="utf-8")
        page.route("**/cdn.tailwindcss.com/**",
                   lambda r: r.fulfill(body="/* tailwind stub: styling not asserted in these tests */",
                                        content_type="application/javascript"))
        page.route("**/cdnjs.cloudflare.com/**",
                   lambda r: r.fulfill(body=papaparse_js, content_type="application/javascript"))

        page.route(
            "**/picks_latest.csv",
            lambda r: r.fulfill(body=picks_body, content_type="text/plain"),
        )
        # Also stub the other CSV routes so page doesn't hang on missing data
        page.route("**/snapshots.csv",
                   lambda r: r.fulfill(body="date,collected_at,group_type,name,stocks,market_cap,pe,fwd_pe,perf_day,perf_week,perf_month,perf_quarter,perf_half,perf_year,perf_ytd,avg_volume,rel_volume,change\n", content_type="text/plain"))
        page.route("**/deltas.csv",
                   lambda r: r.fulfill(body="date,name\n", content_type="text/plain"))
        page.route("**/releases.json",
                   lambda r: r.fulfill(body='{"current":"","releases":[]}', content_type="application/json"))

        page.add_init_script("try { localStorage.setItem('fvt_intro_seen_v1','true'); } catch(e){}")
        page.goto(f"http://localhost:{self.PORT}/", wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        # Click the Picks tab
        page.click("[data-tab='picks']")
        page.wait_for_timeout(400)

    def _expand_first_card(self, page):
        """Click the first expandable pick card to open the risk panel."""
        card = page.locator("[onclick*='__togglePickRow']").first
        card.click()
        page.wait_for_timeout(300)

    def test_regression_anchor_last_matches_csv(self):
        """deriveRiskMetrics(row, 'last') must reproduce stored atr_ext_50 = 0.67 for ANET."""
        from playwright.sync_api import sync_playwright

        anet_body = _single_row_csv({})  # pure ANET row — no overrides

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_picks_tab(page, anet_body)
            self._expand_first_card(page)

            # The Last button should be active by default
            last_btn = page.locator("[id^='basis-btn-last-']").first
            assert "bg-slate-600" in (last_btn.get_attribute("class") or ""), \
                "Last button should be active (bg-slate-600) by default"

            # atr_ext_50 should render as "0.7×" (ANET = 0.6705 → rounds to 0.7)
            panel_text = page.locator("[id^='risk-panel-']").first.inner_text()
            assert "0.7×" in panel_text, \
                f"Expected ANET atr_ext_50 ≈ 0.7× in panel text; got:\n{panel_text}"

            browser.close()

    def test_hod_toggle_increases_risk_metrics(self):
        """HoD > Close → atr_ext_50 and risk_* increase when HoD button is clicked."""
        from playwright.sync_api import sync_playwright

        # Use ANET: Price=165.45, High=170.16, ATR=8.39, SMA50=3.52%
        # Last: atr_ext_50 ≈ 0.67;  HoD: atr_ext_50 = (170.16 - sma50_price)/8.39 > 0.67
        anet_body = _single_row_csv({})

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_picks_tab(page, anet_body)
            self._expand_first_card(page)

            # Capture the Last-basis atr_ext content
            content_el = page.locator("[id^='risk-basis-content-']").first
            last_text = content_el.inner_text()

            # Click HoD button
            hod_btn = page.locator("[id^='basis-btn-hod-']").first
            hod_btn.click()
            page.wait_for_timeout(200)

            hod_text = content_el.inner_text()
            assert last_text != hod_text, "HoD mode must change the risk panel content"

            # HoD context note must appear
            assert "last session high" in hod_text.lower() or "entry" in hod_text.lower(), \
                f"Expected HoD context note in panel; got:\n{hod_text}"

            # HoD button is now active
            hod_btn_class = hod_btn.get_attribute("class") or ""
            assert "bg-slate-600" in hod_btn_class, "HoD button should be active after click"

            browser.close()

    def test_range_atr_fixed_between_bases(self):
        """range_atr and ATR% must not change between Last and HoD (bar properties)."""
        from playwright.sync_api import sync_playwright

        anet_body = _single_row_csv({})

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_picks_tab(page, anet_body)
            self._expand_first_card(page)

            content_el = page.locator("[id^='risk-basis-content-']").first

            def _extract_range_atr(text):
                import re
                # "Range/ATR\n1.27" or similar
                m = re.search(r"Range/ATR\s*([\d.—]+)", text)
                return m.group(1) if m else None

            last_text = content_el.inner_text()
            range_last = _extract_range_atr(last_text)

            hod_btn = page.locator("[id^='basis-btn-hod-']").first
            hod_btn.click()
            page.wait_for_timeout(200)

            hod_text = content_el.inner_text()
            range_hod = _extract_range_atr(hod_text)

            assert range_last is not None, f"Could not find Range/ATR in Last panel:\n{last_text}"
            assert range_hod is not None, f"Could not find Range/ATR in HoD panel:\n{hod_text}"
            assert range_last == range_hod, \
                f"range_atr changed between Last ({range_last}) and HoD ({range_hod}) — must be fixed"

            browser.close()

    def test_collapse_resets_basis_to_last(self):
        """Collapsing a card must reset its basis to Last (ephemeral state rule §5.2)."""
        from playwright.sync_api import sync_playwright

        anet_body = _single_row_csv({})

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_picks_tab(page, anet_body)

            card = page.locator("[onclick*='__togglePickRow']").first
            card.click()
            page.wait_for_timeout(300)

            # Switch to HoD
            hod_btn = page.locator("[id^='basis-btn-hod-']").first
            hod_btn.click()
            page.wait_for_timeout(200)

            # Collapse (same click target)
            card.click()
            page.wait_for_timeout(300)

            # Re-expand
            card.click()
            page.wait_for_timeout(300)

            # Last button must now be active again
            last_btn = page.locator("[id^='basis-btn-last-']").first
            last_cls = last_btn.get_attribute("class") or ""
            assert "bg-slate-600" in last_cls, \
                "After collapse+re-expand, Last button must be active (basis reset)"

            hod_btn_cls = page.locator("[id^='basis-btn-hod-']").first.get_attribute("class") or ""
            assert "bg-slate-800" in hod_btn_cls, \
                "After collapse+re-expand, HoD button must be inactive (bg-slate-800)"

            browser.close()

    def test_hod_trim_becomes_extended_label(self):
        """In HoD mode, when atrExt >= ATR_EXT_TRIM (8.0), label switches to 'extended'."""
        from playwright.sync_api import sync_playwright

        # TESTHOD: Price=100, High=200, ATR=5, SMA50=1%
        # HoD atr_ext_50 = (200 - 100/1.01) / 5 = (200 - 99.01) / 5 = 20.20 >> 8.0 (trim)
        testhod_body = _single_row_csv({
            "ticker": "TESTHOD", "Ticker": "TESTHOD",
            "Price": "100.0", "High": "200.0", "ATR": "5.0",
            "SMA20": "2.0%", "SMA50": "1.0%", "SMA200": "10.0%",
            "atr_ext_50": "0.198", "risk_20ma_pct": "0.01961",
            "risk_50ma_pct": "0.00990", "range_atr": "20.2", "stage2": "1",
        })

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_picks_tab(page, testhod_body)
            self._expand_first_card(page)

            # In Last mode: atr_ext_50 = 0.198 — below ATR_EXT_TRIM (8.0), no trim/extended label
            content_el = page.locator("[id^='risk-basis-content-']").first
            last_text = content_el.inner_text()
            assert "trim" not in last_text.lower() and "extended" not in last_text.lower(), \
                f"Last mode: no trim/extended label expected for atrExt=0.198; got:\n{last_text}"

            # Switch to HoD: atr_ext_50 ≈ 20.2, which is >> ATR_EXT_TRIM (8.0)
            hod_btn = page.locator("[id^='basis-btn-hod-']").first
            hod_btn.click()
            page.wait_for_timeout(200)

            hod_text = content_el.inner_text()
            assert "extended" in hod_text.lower(), \
                f"HoD mode: 'extended' label expected when atrExt >> ATR_EXT_TRIM; got:\n{hod_text}"
            # Must NOT say "trim" in HoD mode (§5.3 label swap)
            assert "trim" not in hod_text.lower(), \
                f"HoD mode: must not say 'trim', only 'extended'; got:\n{hod_text}"

            browser.close()
