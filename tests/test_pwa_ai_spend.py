"""
Playwright functional tests for the AI-WALLET-PWA spend card rendered at the bottom
of the AI tab (data/ai/spend.json, backend already shipped by AI-WALLET — see
scripts/CLAUDE.md § AI spend controls). Covers the normal, over-budget, and
missing-file states.

Run with Playwright installed:
    python3 -m playwright install chromium
    python3 -m pytest tests/test_pwa_ai_spend.py -v -m functional
"""

import json
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

SPEND = {
    "updated_at": "2026-09-10T22:01:08Z",
    "model": "gemini-3.8-flash",
    "month": "2026-09",
    "month_to_date_usd": 4.32,
    "runs": 23,
    "runs_with_cost": 2,
    "soft_budget_usd": 10.0,
    "budget_is_shared": True,
    "last_run": {
        "date": "2026-09-10",
        "cost_usd": 0.18,
        "tokens": {
            "prompt_tokens": 7000, "output_tokens": 2600, "thoughts_tokens": 3000,
            "cached_tokens": 0, "total_tokens": 12600,
        },
        "outcome": "success",
    },
}

SPEND_OVER_BUDGET = dict(SPEND, month_to_date_usd=12.5)


def _launch_server(port: int):
    docs_dir = ROOT / "docs"
    return subprocess.Popen(
        ["python3", "-m", "http.server", str(port), "--directory", str(docs_dir)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


@pytest.mark.functional
class TestAiSpendCard:
    PORT = 8191

    @pytest.fixture(autouse=True, scope="class")
    def server(self):
        proc = _launch_server(self.PORT)
        time.sleep(1)
        yield proc
        proc.terminate()
        proc.wait()

    def _open_ai_tab(self, page, spend_body=None, spend_status=200, extra_routes=None):
        """Stub CSV/CDN/AI-JSON/spend.json fetches and land on the AI tab.

        Route globs use the "**/filename.ext" form (a literal "/" immediately before
        the filename) — "**domain**filename" silently never matches (knowledge/
        investigations/playwright-cloud-session-testing.md, Root cause 3).
        """
        papaparse_js = (ROOT / "tests" / "fixtures" / "papaparse.min.js").read_text(encoding="utf-8")
        page.route("**/cdn.tailwindcss.com/**",
                   lambda r: r.fulfill(body="/* tailwind stub */", content_type="application/javascript"))
        page.route("**/cdnjs.cloudflare.com/**",
                   lambda r: r.fulfill(body=papaparse_js, content_type="application/javascript"))

        page.route("**/sectors/snapshots.csv",
                   lambda r: r.fulfill(path=str(ROOT / "data" / "sectors" / "snapshots.csv"), content_type="text/plain"))
        page.route("**/sectors/deltas.csv",
                   lambda r: r.fulfill(path=str(ROOT / "data" / "sectors" / "deltas.csv"), content_type="text/plain"))
        page.route("**/industries/snapshots.csv",
                   lambda r: r.fulfill(path=str(ROOT / "data" / "industries" / "snapshots.csv"), content_type="text/plain"))
        page.route("**/industries/deltas.csv",
                   lambda r: r.fulfill(path=str(ROOT / "data" / "industries" / "deltas.csv"), content_type="text/plain"))
        page.route("**/fetch_log.csv", lambda r: r.fulfill(body="", content_type="text/plain"))
        page.route("**/finviz_sector_industry_map.json",
                   lambda r: r.fulfill(path=str(ROOT / "data" / "finviz_sector_industry_map.json"), content_type="application/json"))
        page.route("**/picks/picks_latest.csv",
                   lambda r: r.fulfill(path=str(ROOT / "tests" / "fixtures" / "picks_latest.csv"), content_type="text/plain"))
        page.route("**/picks/sessions/morning_latest.csv", lambda r: r.fulfill(body="", content_type="text/plain"))
        page.route("**/picks/sessions/pre_close_latest.csv", lambda r: r.fulfill(body="", content_type="text/plain"))
        page.route("**/ai/index.json",
                   lambda r: r.fulfill(body='{"entries":[{"date":"2026-07-02","status":"complete"}]}',
                                        content_type="application/json"))
        page.route("**/ai/2026-07-02.json",
                   lambda r: r.fulfill(path=str(ROOT / "data" / "ai" / "2026-07-02.json"), content_type="application/json"))
        page.route("**/ai/provenance/2026-07-02.json", lambda r: r.abort())
        page.route("**/releases.json",
                   lambda r: r.fulfill(body='{"current":"","releases":[]}', content_type="application/json"))

        if spend_body is None:
            page.route("**/ai/spend.json", lambda r: r.fulfill(status=404, body="not found"))
        else:
            page.route("**/ai/spend.json",
                        lambda r: r.fulfill(status=spend_status, body=json.dumps(spend_body),
                                             content_type="application/json"))

        # Registered last so they win over the defaults above (Playwright tries routes
        # most-recently-registered-first for a given URL).
        for pattern, handler in (extra_routes or {}).items():
            page.route(pattern, handler)

        page.add_init_script("try { localStorage.setItem('fvt_intro_seen_v3','true'); } catch(e){}")
        page.goto(f"http://localhost:{self.PORT}/", wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        page.click("[data-tab='ai']")
        page.wait_for_timeout(600)

    def test_spend_card_renders_at_bottom_of_ai_tab(self):
        """The card shows month-to-date cost, budget, run count, last-run outcome,
        model, and an updated timestamp — and it's the last thing in the tab."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_ai_tab(page, spend_body=SPEND)

            text = page.inner_text("#ai-content")
            assert "AI Spend" in text
            assert "$4.32" in text
            assert "$10" in text
            assert "23 run" in text
            assert "2 priced" in text
            assert "success" in text
            assert "gemini-3.8-flash" in text

            # Spend card is the label+card pair at the very end of the AI content
            # container (the label div immediately precedes the card div).
            last_two_text = page.evaluate(
                "() => [...document.querySelectorAll('#ai-content > div')].slice(-2).map(el => el.textContent).join(' ')"
            )
            assert "AI Spend" in last_two_text
            assert "$4.32" in last_two_text

            browser.close()

    def test_over_budget_shows_warning_copy(self):
        """Spend past the soft budget gets an explicit 'display ceiling only' note
        (SPEND_SOFT_BUDGET_USD is documented as non-enforcing — nothing is blocked)."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_ai_tab(page, spend_body=SPEND_OVER_BUDGET)

            text = page.inner_text("#ai-content")
            assert "$12.50" in text
            assert "Over the soft budget" in text
            assert "nothing is blocked" in text.lower() or "nothing is blocked" in text

            browser.close()

    def test_missing_spend_json_omits_section_without_breaking_tab(self):
        """A repo that hasn't run generate_ai.py since AI-WALLET landed (2026-09-10)
        has no spend.json yet — a 404 must not show the section or break the rest
        of the AI tab's render."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_ai_tab(page, spend_body=None)

            text = page.inner_text("#ai-content")
            assert "AI Spend" not in text
            # The rest of the note still rendered fine.
            assert "RISKS" in text.upper()

            browser.close()

    def test_spend_card_renders_when_ai_analysis_not_yet_available(self):
        """The spend card is account-wide, not tied to any one date's AI analysis —
        it should still render in the "AI analysis not yet available" empty state
        (both index.json and the per-date fallback missing/failing)."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # Force a known, controlled fallback date via the small fixture CSVs
            # (real production data always has *some* AI analysis, so the "not yet
            # available" branch needs a snapshot date with no corresponding AI JSON).
            fixtures = ROOT / "tests" / "fixtures" / "ai"
            extra_routes = {
                "**/sectors/snapshots.csv": lambda r: r.fulfill(path=str(fixtures / "sectors_snapshots.csv"), content_type="text/plain"),
                "**/sectors/deltas.csv": lambda r: r.fulfill(path=str(fixtures / "sectors_deltas.csv"), content_type="text/plain"),
                "**/industries/snapshots.csv": lambda r: r.fulfill(path=str(fixtures / "industries_snapshots.csv"), content_type="text/plain"),
                "**/industries/deltas.csv": lambda r: r.fulfill(path=str(fixtures / "industries_deltas.csv"), content_type="text/plain"),
                "**/ai/index.json": lambda r: r.fulfill(status=404, body="not found"),
                "**/ai/2026-06-22.json": lambda r: r.fulfill(status=404, body="not found"),
            }

            self._open_ai_tab(page, spend_body=SPEND, extra_routes=extra_routes)

            text = page.inner_text("#ai-content")
            assert "AI analysis not yet available" in text
            assert "AI Spend" in text
            assert "$4.32" in text

            browser.close()
