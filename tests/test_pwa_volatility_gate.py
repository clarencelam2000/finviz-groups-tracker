"""
Playwright functional tests for the volatility floor gate (2026-09-02, owner call after the
APGE false-"coiled" case): docs/index.html's passesVolatilityFloor() hides a stock from
Picks/Focus/Morning when its Volatility W % OR ATR/Price % is below VOLATILITY_FLOOR_PCT
(1.0%) — provably near-dead (buyout-frozen, halted, a perpetual preferred) rather than a
genuine tight coil. A direct Lookup ticker search is exempt (explicit user intent) and shows
a "Low volatility" warning chip instead of being hidden.

Covered:
  1. Picks tab (All view) excludes a below-floor stock, keeps a normal one.
  2. Focus view excludes a below-floor stock even when otherwise Focus-eligible.
  3. Morning tab's picks-confirmation read excludes a below-floor card.
  4. Lookup shows the "Low volatility" warning chip for a below-floor ticker instead of
     hiding it.

Run with Playwright installed:
    python3 -m playwright install chromium
    python3 -m pytest tests/test_pwa_volatility_gate.py -v -m functional
"""

import csv
import io
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PICKS_FIXTURE = ROOT / "tests" / "fixtures" / "picks_latest.csv"


def _launch_server(port: int):
    return subprocess.Popen(
        ["python3", "-m", "http.server", str(port), "--directory", str(ROOT / "docs")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _multi_row_picks_csv(rows_overrides: list) -> str:
    """Build a picks_latest.csv with N rows, each ANET-based with its own overrides — same
    helper shape as test_pwa_focus_scoring.py's _multi_row_csv."""
    with PICKS_FIXTURE.open(encoding="utf-8") as f:
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


# APGE-style dead name: Volatility W 0.07%, ATR/Price = 0.35/135.08 = 0.26% — both well below
# the 1.0% floor. LIVECO: Volatility W 4.29%, ATR/Price ~5.1% (ANET's own real values) — well
# above the floor, included as the control.
DEADCO_OVERRIDES = {
    "ticker": "DEADCO", "Ticker": "DEADCO",
    "Price": "135.08", "ATR": "0.35", "Volatility W": "0.07%", "Volatility M": "0.21%",
}


def _open_picks(page, port, picks_body: str, focus: bool = False):
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
    page.route("**/finviz_sector_industry_map.json",
               lambda r: r.fulfill(body='{"sectors":{}}', content_type="application/json"))

    page.add_init_script("try { localStorage.setItem('fvt_intro_seen_v3','true'); } catch(e){}")
    page.goto(f"http://localhost:{port}/", wait_until="domcontentloaded")
    page.wait_for_timeout(1000)
    page.click("[data-tab='picks']")
    page.wait_for_timeout(300)
    if focus:
        page.click("#picks-toggle-focus")
        page.wait_for_timeout(300)


@pytest.mark.functional
class TestVolatilityGatePicksAndFocus:
    PORT = 8189

    @pytest.fixture(autouse=True, scope="class")
    def server(self):
        proc = _launch_server(self.PORT)
        time.sleep(1)
        yield proc
        proc.terminate()
        proc.wait()

    def test_below_floor_stock_excluded_from_picks_all(self):
        from playwright.sync_api import sync_playwright

        body = _multi_row_picks_csv([
            DEADCO_OVERRIDES,
            {"ticker": "LIVECO", "Ticker": "LIVECO"},  # inherits ANET's real Vol W/ATR/Price
        ])

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            _open_picks(page, self.PORT, body, focus=False)

            text = page.locator("#tab-picks").inner_text()
            assert "DEADCO" not in text, f"Below-floor stock should be hidden from Picks All; got:\n{text}"
            assert "LIVECO" in text, f"Normal-volatility stock should still appear; got:\n{text}"

            browser.close()

    def test_below_floor_stock_excluded_from_focus(self):
        from playwright.sync_api import sync_playwright

        body = _multi_row_picks_csv([
            DEADCO_OVERRIDES,
            {"ticker": "LIVECO", "Ticker": "LIVECO"},
        ])

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            _open_picks(page, self.PORT, body, focus=True)

            text = page.locator("#tab-picks").inner_text()
            assert "DEADCO" not in text, f"Below-floor stock should be hidden from Focus; got:\n{text}"
            assert "LIVECO" in text, f"Otherwise-eligible stock should still appear in Focus; got:\n{text}"

            browser.close()

    def test_atr_pct_alone_excludes_even_with_normal_volatility_w(self):
        """The OR logic: a low ATR/Price % alone (Volatility W normal) still trips the gate."""
        from playwright.sync_api import sync_playwright

        # Volatility W left at ANET's normal 4.29%, but ATR/Price forced under 1.0% —
        # (0.5 / 135.08 = 0.37%) — the OR condition should still exclude it.
        body = _multi_row_picks_csv([
            {"ticker": "QUIETATR", "Ticker": "QUIETATR", "Price": "135.08", "ATR": "0.5"},
            {"ticker": "LIVECO", "Ticker": "LIVECO"},
        ])

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            _open_picks(page, self.PORT, body, focus=False)

            text = page.locator("#tab-picks").inner_text()
            assert "QUIETATR" not in text, f"Low ATR/Price alone should exclude the row; got:\n{text}"
            assert "LIVECO" in text

            browser.close()


MORNING_HEADER = (
    "date,session,collected_at,ticker,group,list_category,trigger,stop,atr,price,open,high,"
    "low,change,status,atr_from_lod,reclaim_ref,reclaim_ref_value,RSI,Volatility W,"
    "Volatility M,Rel Volume,52W High,Price,SMA20,SMA50,ATR"
)


def _morning_row(ticker, status, vol_w, atr, price, group="Biotechnology", list_category="leaders"):
    return (
        f"2026-09-02,morning,2026-09-02T14:05:00Z,{ticker},{group},{list_category},"
        f"{price},{price},{atr},{price},{price},{price},{price},0.0,{status},0.5,,,"
        f"55,{vol_w},{vol_w},0.40x,-1.0%,{price},1.0,1.0,{atr}"
    )


@pytest.mark.functional
class TestVolatilityGateMorning:
    PORT = 8190

    @pytest.fixture(autouse=True, scope="class")
    def server(self):
        proc = _launch_server(self.PORT)
        time.sleep(1)
        yield proc
        proc.terminate()
        proc.wait()

    def _open_morning(self, page, morning_body: str):
        papaparse_js = (ROOT / "tests" / "fixtures" / "papaparse.min.js").read_text(encoding="utf-8")
        page.route("**/cdn.tailwindcss.com/**",
                   lambda r: r.fulfill(body="/* tailwind stub */", content_type="application/javascript"))
        page.route("**/cdnjs.cloudflare.com/**",
                   lambda r: r.fulfill(body=papaparse_js, content_type="application/javascript"))
        page.route("**/sessions/morning_latest.csv",
                   lambda r: r.fulfill(body=morning_body, content_type="text/plain"))
        page.route("**/snapshots.csv",
                   lambda r: r.fulfill(body="date,collected_at,group_type,name,stocks,market_cap,pe,fwd_pe,perf_day,perf_week,perf_month,perf_quarter,perf_half,perf_year,perf_ytd,avg_volume,rel_volume,change\n", content_type="text/plain"))
        page.route("**/deltas.csv", lambda r: r.fulfill(body="date,name\n", content_type="text/plain"))
        page.route("**/picks_latest.csv", lambda r: r.fulfill(body="date,ticker\n", content_type="text/plain"))
        page.route("**/sessions/pre_close_latest.csv",
                   lambda r: r.fulfill(body="date,session,collected_at,ticker,group,list_category,trigger,stop,atr,price,open,high,low,change,status,atr_from_lod\n", content_type="text/plain"))
        page.route("**/fetch_log.csv", lambda r: r.fulfill(body="", content_type="text/plain"))
        page.route("**/releases.json",
                   lambda r: r.fulfill(body='{"current":"","releases":[]}', content_type="application/json"))
        page.route("**/finviz_sector_industry_map.json",
                   lambda r: r.fulfill(body='{"sectors":{}}', content_type="application/json"))

        page.add_init_script("try { localStorage.clear(); localStorage.setItem('fvt_intro_seen_v3','true'); } catch(e){}")
        page.goto(f"http://localhost:{self.PORT}/", wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        page.click("[data-tab='morning']")
        page.wait_for_timeout(1000)

    def test_below_floor_card_excluded_from_morning(self):
        from playwright.sync_api import sync_playwright

        body = MORNING_HEADER + "\n" + "\n".join([
            _morning_row("DEADCO", "setting_up", "0.07%", "0.35", "135.08"),
            _morning_row("LIVECO", "setting_up", "4.29%", "8.39", "165.45"),
        ]) + "\n"

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_morning(page, body)

            html = page.inner_html("#morning-list")
            assert "DEADCO" not in html, f"Below-floor morning card should be hidden; got:\n{html}"
            assert "LIVECO" in html, f"Normal-volatility morning card should still render; got:\n{html}"

            browser.close()


@pytest.mark.functional
class TestVolatilityGateLookup:
    PORT = 8191

    @pytest.fixture(autouse=True, scope="class")
    def server(self):
        proc = _launch_server(self.PORT)
        time.sleep(1)
        yield proc
        proc.terminate()
        proc.wait()

    def _open_lookup(self, page, picks_body: str, symbol: str):
        papaparse_js = (ROOT / "tests" / "fixtures" / "papaparse.min.js").read_text(encoding="utf-8")
        lookup_body = (
            f'{{"symbol":"{symbol}","company_name":"{symbol} Inc.","exchange":"NASDAQ",'
            f'"market_cap_b":100,"finviz_industry":null,"finviz_sector":null,'
            f'"industry_confidence":0.0,"image":null,"etf_kind":null}}'
        )
        # Catch-all first (registered first = checked last per Playwright route ordering),
        # specific routes after — same pattern as test_pwa_lookup_signal.py's _run().
        page.route("**/raw.githubusercontent.com/**", lambda r: r.fulfill(status=404))
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
        page.route("**/finviz_sector_industry_map.json",
                   lambda r: r.fulfill(body='{"sectors":{}}', content_type="application/json"))
        page.route("**/finviz-ticker-lookup.salmonbaby8.workers.dev/lookup*",
                   lambda r: r.fulfill(body=lookup_body, content_type="application/json"))

        page.add_init_script("try { localStorage.setItem('fvt_intro_seen_v3','true'); } catch(e){}")
        page.goto(f"http://localhost:{self.PORT}/", wait_until="domcontentloaded")
        page.wait_for_timeout(800)
        page.click("[data-tab='lookup']")
        page.wait_for_timeout(300)
        page.fill("#ticker-input", symbol)
        page.locator("#ticker-submit").click()
        page.wait_for_timeout(800)

    def test_lookup_shows_warning_chip_not_hidden(self):
        """A direct Lookup search for a below-floor ticker still shows the stock (explicit
        user intent) with a 'Low volatility' warning chip, unlike Picks/Focus/Morning."""
        from playwright.sync_api import sync_playwright

        body = _multi_row_picks_csv([DEADCO_OVERRIDES])

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(ignore_https_errors=True)
            page = ctx.new_page()
            self._open_lookup(page, body, "DEADCO")

            text = page.locator("#lookup-result").inner_text()
            assert "Low volatility" in text, f"Expected the low-volatility warning chip; got:\n{text}"

            browser.close()
