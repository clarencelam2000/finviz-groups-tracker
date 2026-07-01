"""
Playwright functional tests for Focus scoring's liquidity gate/penalty and earnings
penalty (Phase 3d): tests/test_pwa_focus_scoring.py

Tests covered:
  1. Liquidity hard gate — a candidate below FOCUS_MIN_DOLLAR_VOL ($30M avg $ volume) is
     excluded from Focus entirely.
  2. Liquidity penalty — among two otherwise-identical candidates, the one in the thin
     $30M-$60M band scores lower than the one at/above LIQUIDITY_PENALTY_START ($60M).
  3. Earnings penalty — among two otherwise-identical candidates, the one with imminent
     earnings scores lower than the one with no known earnings date.
  4. Collapsed-row earnings badge — shown only for the imminent (red) tier, not for the
     caution (amber) tier or no-earnings-known case.

Uses the harness from knowledge/investigations/playwright-cloud-session-testing.md
(CDN stubs, "**/filename.ext" route globs, wait_until="domcontentloaded").

Run with Playwright installed:
    python3 -m playwright install chromium
    python3 -m pytest tests/test_pwa_focus_scoring.py -v -m functional
"""

import csv
import io
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "picks_latest.csv"


def _launch_server(port: int):
    docs_dir = ROOT / "docs"
    return subprocess.Popen(
        ["python3", "-m", "http.server", str(port), "--directory", str(docs_dir)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _multi_row_csv(rows_overrides: list) -> str:
    """Build a picks_latest.csv with N rows, each ANET-based with its own overrides.

    All rows share ANET's group/tight/quiet/extension inputs (grp_sum_mid_rank,
    risk_20ma_pct, risk_50ma_pct, range_atr, atr_ext_50) unless overridden, so
    the base score + extension penalty are identical across rows — isolating the
    liquidity/earnings penalties under test.
    """
    with FIXTURE.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames
        rows = list(reader)
    base = next(r for r in rows if r["ticker"] == "ANET")

    out_rows = []
    for overrides in rows_overrides:
        row = dict(base)
        row.update(overrides)
        out_rows.append(row)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols)
    writer.writeheader()
    writer.writerows(out_rows)
    return buf.getvalue()


def _finviz_earnings_str(days_from_today: int, session: str = "b") -> str:
    dt = datetime.now() + timedelta(days=days_from_today)
    return f"{dt.strftime('%b')} {dt.day}/{session}"


@pytest.mark.functional
class TestFocusLiquidityAndEarningsScoring:
    PORT = 8185

    @pytest.fixture(autouse=True, scope="class")
    def server(self):
        proc = _launch_server(self.PORT)
        time.sleep(1)
        yield proc
        proc.terminate()
        proc.wait()

    def _open_picks_focus(self, page, picks_body: str):
        papaparse_js = (ROOT / "tests" / "fixtures" / "papaparse.min.js").read_text(encoding="utf-8")

        page.route("**/cdn.tailwindcss.com/**",
                   lambda r: r.fulfill(body="/* tailwind stub */", content_type="application/javascript"))
        page.route("**/cdnjs.cloudflare.com/**",
                   lambda r: r.fulfill(body=papaparse_js, content_type="application/javascript"))
        page.route("**/picks_latest.csv",
                   lambda r: r.fulfill(body=picks_body, content_type="text/plain"))
        page.route("**/snapshots.csv",
                   lambda r: r.fulfill(body="date,collected_at,group_type,name,stocks,market_cap,pe,fwd_pe,perf_day,perf_week,perf_month,perf_quarter,perf_half,perf_year,perf_ytd,avg_volume,rel_volume,change\n", content_type="text/plain"))
        page.route("**/deltas.csv", lambda r: r.fulfill(body="date,name\n", content_type="text/plain"))
        page.route("**/releases.json",
                   lambda r: r.fulfill(body='{"current":"","releases":[]}', content_type="application/json"))

        page.add_init_script("try { localStorage.setItem('fvt_intro_seen_v1','true'); } catch(e){}")
        page.goto(f"http://localhost:{self.PORT}/", wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        page.click("[data-tab='picks']")
        page.wait_for_timeout(300)
        page.click("#picks-toggle-focus")
        page.wait_for_timeout(300)

    def test_liquidity_gate_excludes_thin_stock(self):
        """A stock below FOCUS_MIN_DOLLAR_VOL ($30M) never appears in the Focus list."""
        from playwright.sync_api import sync_playwright

        # ANET Price=165.45; 151,103 shares/day * 165.45 ~= $25M (below the $30M floor)
        body = _multi_row_csv([
            {"ticker": "THINCO", "Ticker": "THINCO", "Avg Volume": "151103"},
            {"ticker": "LIQCO", "Ticker": "LIQCO", "Avg Volume": "543971"},  # ~$90M, well above floor
        ])

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_picks_focus(page, body)

            text = page.locator("#tab-picks").inner_text()
            assert "THINCO" not in text, f"Thin stock should be gated out of Focus; got:\n{text}"
            assert "LIQCO" in text, f"Liquid stock should appear in Focus; got:\n{text}"

            browser.close()

    def test_liquidity_penalty_lowers_thin_but_eligible_score(self):
        """A stock in the $30M-$60M band scores lower than an otherwise-identical $90M stock."""
        from playwright.sync_api import sync_playwright

        # 271,985 shares/day * 165.45 ~= $45M (thin band, partial penalty)
        # 543,971 shares/day * 165.45 ~= $90M (at/above LIQUIDITY_PENALTY_START, no penalty)
        body = _multi_row_csv([
            {"ticker": "MIDCO", "Ticker": "MIDCO", "Avg Volume": "271985"},
            {"ticker": "LIQCO", "Ticker": "LIQCO", "Avg Volume": "543971"},
        ])

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_picks_focus(page, body)

            def score_for(ticker):
                row = page.locator(f"text={ticker}").locator("xpath=ancestor::div[contains(@onclick,'__togglePickRow')]")
                score_el = row.locator(".text-indigo-300")
                return int(score_el.inner_text().strip())

            mid_score = score_for("MIDCO")
            liq_score = score_for("LIQCO")
            assert mid_score < liq_score, \
                f"Thin-liquidity MIDCO ({mid_score}) should score lower than liquid LIQCO ({liq_score})"

            browser.close()

    def test_earnings_penalty_lowers_imminent_score(self):
        """A stock with imminent earnings scores lower than one with none known, all else equal."""
        from playwright.sync_api import sync_playwright

        body = _multi_row_csv([
            {"ticker": "SOONCO", "Ticker": "SOONCO", "Avg Volume": "543971",
             "Earnings": _finviz_earnings_str(2)},
            {"ticker": "CLEARCO", "Ticker": "CLEARCO", "Avg Volume": "543971", "Earnings": "-"},
        ])

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_picks_focus(page, body)

            def score_for(ticker):
                row = page.locator(f"text={ticker}").locator("xpath=ancestor::div[contains(@onclick,'__togglePickRow')]")
                score_el = row.locator(".text-indigo-300")
                return int(score_el.inner_text().strip())

            soon_score = score_for("SOONCO")
            clear_score = score_for("CLEARCO")
            assert soon_score < clear_score, \
                f"Imminent-earnings SOONCO ({soon_score}) should score lower than CLEARCO ({clear_score})"

            browser.close()

    def test_collapsed_row_earnings_badge_imminent_only(self):
        """The 'E' badge on the collapsed row appears only for imminent (<=3d) earnings."""
        from playwright.sync_api import sync_playwright

        body = _multi_row_csv([
            {"ticker": "IMMCO", "Ticker": "IMMCO", "Avg Volume": "543971",
             "Earnings": _finviz_earnings_str(2)},   # imminent -> badge
            {"ticker": "CAUTCO", "Ticker": "CAUTCO", "Avg Volume": "543971",
             "Earnings": _finviz_earnings_str(7)},   # caution -> no badge
            {"ticker": "NOECO", "Ticker": "NOECO", "Avg Volume": "543971",
             "Earnings": "-"},                        # none -> no badge
        ])

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_picks_focus(page, body)

            def badge_count_for(ticker):
                row = page.locator(f"text={ticker}").locator("xpath=ancestor::div[contains(@onclick,'__togglePickRow')]")
                return row.locator("span:has-text('E')").count()

            assert badge_count_for("IMMCO") >= 1, "Imminent earnings should show the collapsed-row badge"
            imm_badge = page.locator(f"text=IMMCO").locator(
                "xpath=ancestor::div[contains(@onclick,'__togglePickRow')]//span[contains(@class,'bg-red-900')]"
            )
            assert imm_badge.count() >= 1, "Expected a red earnings badge on the imminent-earnings row"

            cauc_badge = page.locator(f"text=CAUTCO").locator(
                "xpath=ancestor::div[contains(@onclick,'__togglePickRow')]//span[contains(@class,'bg-red-900')]"
            )
            assert cauc_badge.count() == 0, "Caution-tier earnings should NOT show the collapsed-row badge"

            noe_badge = page.locator(f"text=NOECO").locator(
                "xpath=ancestor::div[contains(@onclick,'__togglePickRow')]//span[contains(@class,'bg-red-900')]"
            )
            assert noe_badge.count() == 0, "No known earnings should NOT show the collapsed-row badge"

            browser.close()
