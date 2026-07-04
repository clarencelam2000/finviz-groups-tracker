"""
Playwright functional tests for inline group-name chips in the AI tab daily note
and the floating group-peek sheet they open (planning/ai-tab-inline-groups.md).

Uses real production data (data/ai/2026-07-02.json + data/*/snapshots.csv,deltas.csv)
rather than the small synthetic fixtures, since the collision-prone names this
feature must get right — "Financial" (sector) vs "Financial Conglomerates"
(industry), "Healthcare" (sector) vs "Healthcare Facilities"/"Healthcare Plans"
(industries) — only exist in the real taxonomy. The 2026-07-02 note is also the
one that names the same group two different ways in the same response
("Diversified Banks" vs the canonical "Banks - Diversified"), which is why it's
used verbatim rather than a shorter hand-written fixture.

Run with Playwright installed:
    python3 -m playwright install chromium
    python3 -m pytest tests/test_pwa_ai_group_chips.py -v -m functional
"""

import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _launch_server(port: int):
    docs_dir = ROOT / "docs"
    return subprocess.Popen(
        ["python3", "-m", "http.server", str(port), "--directory", str(docs_dir)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


@pytest.mark.functional
class TestAiGroupChips:
    PORT = 8190

    @pytest.fixture(autouse=True, scope="class")
    def server(self):
        proc = _launch_server(self.PORT)
        time.sleep(1)
        yield proc
        proc.terminate()
        proc.wait()

    def _open_ai_industries_note(self, page):
        """Navigate to the PWA, stub CSV/CDN/AI-JSON fetches with real production
        data, and switch to the AI tab's Industries note.

        Route globs use the "**/filename.ext" form (a literal "/" immediately
        before the filename) — "**domain**filename" silently never matches and
        falls through to the real network (knowledge/investigations/
        playwright-cloud-session-testing.md, Root cause 3). CDN scripts
        (Tailwind/PapaParse) must also be stubbed or the app never boots in an
        environment where Chromium can't reach the real CDNs (Root cause 2).
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
        page.route("**/ai/index.json",
                   lambda r: r.fulfill(body='{"entries":[{"date":"2026-07-02","status":"complete"}]}',
                                        content_type="application/json"))
        page.route("**/ai/2026-07-02.json",
                   lambda r: r.fulfill(path=str(ROOT / "data" / "ai" / "2026-07-02.json"), content_type="application/json"))
        page.route("**/ai/provenance/2026-07-02.json", lambda r: r.abort())
        page.route("**/releases.json",
                   lambda r: r.fulfill(body='{"current":"","releases":[]}', content_type="application/json"))

        page.add_init_script("try { localStorage.setItem('fvt_intro_seen_v3','true'); } catch(e){}")
        page.goto(f"http://localhost:{self.PORT}/", wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        page.click("[data-tab='ai']")
        page.wait_for_timeout(400)
        # AI tab defaults to the Sectors note; this feature's key test cases
        # (the collisions, the two-different-names-for-one-group case) are all
        # in the Industries note.
        page.click("#tab-ai .group-toggle-btn[data-group='industries']")
        page.wait_for_timeout(800)

    def test_group_names_become_chips_without_truncation(self):
        """Every collision-prone canonical name renders fully — not truncated to
        a shorter name that happens to be a prefix (e.g. "Financial" swallowing
        "Financial Conglomerates")."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_ai_industries_note(page)

            chip_names = [el.get_attribute("data-name") for el in page.query_selector_all(".group-chip")]
            assert len(chip_names) > 0, "Expected at least one group-name chip in the note"

            for expected in [
                "Financial Conglomerates",
                "REIT - Healthcare Facilities",
                "Healthcare Plans",
                "Biotechnology",
                "Banks - Diversified",
            ]:
                assert expected in chip_names, (
                    f'Expected untruncated chip "{expected}" not found among: {chip_names}'
                )

            browser.close()

    def test_chip_click_opens_peek_with_group_snapshot(self):
        """Tapping a chip opens the peek sheet showing that group's real snapshot
        (reused from groupPerfCard(), the same renderer Lookup uses)."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_ai_industries_note(page)

            chip = page.locator(".group-chip", has_text="Biotechnology").first
            chip.click()
            page.wait_for_timeout(400)

            visible = page.eval_on_selector("#peek-overlay", "el => !el.classList.contains('hidden')")
            assert visible, "Peek overlay should be visible after clicking a chip"

            body_text = page.inner_text("#peek-body")
            assert "Biotechnology" in body_text
            assert "Momentum" in body_text
            assert "Rank" in body_text

            browser.close()

    def test_show_full_breakdown_expands_in_place(self):
        """The compact peek defaults to groupPerfCard(expanded=false); "Show full
        breakdown" re-renders with expanded=true instead of switching tabs."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_ai_industries_note(page)

            page.locator(".group-chip", has_text="Biotechnology").first.click()
            page.wait_for_timeout(400)

            compact_text = page.inner_text("#peek-body")
            assert "All ranks" not in compact_text, "Compact peek should not show the full breakdown by default"

            page.click("#peek-more-toggle")
            page.wait_for_timeout(300)
            expanded_text = page.inner_text("#peek-body")
            assert "All ranks" in expanded_text
            assert "Momentum deep dive" in expanded_text

            browser.close()

    def test_full_lookup_handoff_switches_tab_and_populates_group(self):
        """"Full lookup" closes the peek and hands off to the real Lookup tab
        with the tapped group already resolved — no re-typing the name."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_ai_industries_note(page)

            page.locator(".group-chip", has_text="Biotechnology").first.click()
            page.wait_for_timeout(400)
            page.click("#peek-full-lookup")
            page.wait_for_timeout(500)

            active_tab = page.evaluate("document.querySelector('.tab-btn.tab-active')?.dataset.tab")
            assert active_tab == "lookup"

            lookup_text = page.inner_text("#lookup-result")
            assert "Biotechnology" in lookup_text

            overlay_hidden = page.eval_on_selector("#peek-overlay", "el => el.classList.contains('hidden')")
            assert overlay_hidden, "Peek sheet should close after handing off to Full lookup"

            browser.close()

    def test_backdrop_click_closes_peek(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._open_ai_industries_note(page)

            page.locator(".group-chip", has_text="Biotechnology").first.click()
            page.wait_for_timeout(400)
            page.eval_on_selector("#peek-backdrop", "el => el.click()")
            page.wait_for_timeout(400)

            overlay_hidden = page.eval_on_selector("#peek-overlay", "el => el.classList.contains('hidden')")
            assert overlay_hidden

            browser.close()
