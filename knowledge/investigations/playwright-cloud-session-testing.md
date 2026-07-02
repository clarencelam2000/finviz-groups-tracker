# Investigation: Running the PWA's Playwright tests in a Claude Code cloud session

**Date**: 2026-06-30
**Scope**: Getting the existing fixture-intercept Playwright pattern (used by `tests/test_pwa_picks_hod.py`,
`tests/test_functional_playwright.py`) to actually run in this Claude Code cloud session — distinct from
CI or a developer's local machine, where the same tests are expected to just work.

## Symptom

`python3 -m pytest tests/ -m functional` reported all Playwright tests failing with:

```
playwright._impl._errors.Error: BrowserType.launch: Executable doesn't exist at
/opt/pw-browsers/chromium-1117/chrome-linux/chrome
```

Running `playwright install chromium --with-deps` to "fix" this fails with an apt error
(`E: Package 'libasound2' has no installation candidate`) — don't chase that; it's a dead end in this image.

## Root cause 1: pinned Playwright version vs. pre-installed browser revision

This repo pins `playwright==1.44.0` (`requirements.txt`, `requirements-test.txt`), which expects Chromium
revision **1117**. The cloud session's pre-installed browser at `/opt/pw-browsers/` is revision **1194**
(a newer Playwright's expected revision). `playwright install` can't reconcile this without network access
to the Playwright CDN, which the apt failure above suggests isn't cleanly available either.

**Fix**: don't fight the version pin. Pass the pre-installed binary's path explicitly:

```python
browser = p.chromium.launch(
    headless=True,
    executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome",  # or just "/opt/pw-browsers/chromium" — it's a symlink to the same binary
)
```

This is a per-session environment fact, not a repo fact — don't hardcode revision `1194` into committed
test files (it'll be stale the moment the cloud image updates). For ad hoc verification scripts this is
fine to hardcode; for anything committed, resolve it dynamically (e.g. glob `/opt/pw-browsers/chromium-*`)
or just rely on existing CI/local dev where the pinned version and installed browser already match.

## Root cause 2: CDN scripts and `raw.githubusercontent.com` aren't reachable directly from Chromium

The PWA loads Tailwind and PapaParse from CDNs (`cdn.tailwindcss.com`, `cdnjs.cloudflare.com`) and fetches
its data from `raw.githubusercontent.com`. In this sandbox, **`curl` reaches all of these fine** (it picks
up the `HTTPS_PROXY` env var automatically), but **Chromium launched via `p.chromium.launch()` without
proxy configuration cannot** — requests hang or fail with `net::ERR_CONNECTION_CLOSED`. Passing
`proxy={"server": ...}` to `launch()` did not reliably fix this either (still saw `ERR_CONNECTION_CLOSED`
on `raw.githubusercontent.com` specifically, even though `cdn.tailwindcss.com` requests succeeded).

**Fix**: don't rely on Chromium reaching the real internet at all. `curl` (or the `WebFetch` tool) the CDN
scripts once, cache the content, and serve everything — CDN scripts included — via `page.route()`. This is
already the pattern `test_pwa_picks_hod.py` uses for the CSV/JSON data; it just wasn't applied to the two
`<script src=...>` tags in `docs/index.html`'s `<head>`, which is why those tests never exercised CDN
reachability before (CI/local dev presumably have real internet access, so this gap was invisible there).

```python
tailwind_js = Path("tailwind.js").read_text()   # curl -sSL https://cdn.tailwindcss.com -o tailwind.js
papaparse_js = Path("papaparse.js").read_text() # curl -sSL https://cdnjs.cloudflare.com/.../papaparse.min.js -o papaparse.js
page.route("**/cdn.tailwindcss.com/**", lambda r: r.fulfill(body=tailwind_js, content_type="application/javascript"))
page.route("**/cdnjs.cloudflare.com/**", lambda r: r.fulfill(body=papaparse_js, content_type="application/javascript"))
```

## Root cause 3 (sharpest gotcha): Playwright glob patterns need `**/` as a segment boundary

This one is worth flagging loudly because **the existing committed test files may already have this bug**.

`page.route(pattern, handler)` patterns like `"**raw.githubusercontent.com**picks_latest.csv"` (no `/`
immediately before the literal suffix) **silently never match** — the handler is never invoked, and the
real network request proceeds (and then fails per Root cause 2, or hangs). This was confirmed by isolated
testing in this session:

| Pattern | Matches `https://raw.githubusercontent.com/.../picks_latest.csv`? |
|---|---|
| `"**/*"` | ✅ |
| `"https://raw.githubusercontent.com/**"` | ✅ |
| `"**/picks_latest.csv"` | ✅ |
| `"**/raw.githubusercontent.com/**picks_latest.csv"` | ❌ |
| `"**raw.githubusercontent.com**"` | ❌ |
| `"**picks_latest.csv"` | ❌ |

The rule that falls out of this: every `**` in a Playwright route pattern needs to be immediately followed
by a literal `/` if you intend it to span path segments and then match a bare filename. `"**X"` (no slash)
behaves like a single-segment glob, not "anything ending in X".

**Update 2026-07-01**: `tests/test_pwa_picks_hod.py` fixed — confirmed it hung in this sandboxed
session with exactly `Page.goto: Timeout 30000ms exceeded ... waiting until "networkidle"`. Fixed
by applying all three workarounds above: glob patterns changed from `"**/raw.githubusercontent.com/
**picks_latest.csv"` to `"**/picks_latest.csv"`, CDN stubs added for `cdn.tailwindcss.com` /
`cdnjs.cloudflare.com` (vendored `tests/fixtures/papaparse.min.js`), and `goto()` switched from
`wait_until="networkidle"` to `"domcontentloaded"` + an explicit `wait_for_timeout`. All 5 tests
pass now. `executable_path` was *not* added to the committed file (Root cause 1 fix) — CI/local dev
already have the matching pinned browser revision; that mismatch is a per-session sandbox fact, not
a repo fact (see Root cause 1 above).

**Still open**: `tests/test_functional_playwright.py` has the identical broken-glob pattern
(`"**/raw.githubusercontent.com/**snapshots.csv"` etc., ~10 occurrences) and multiple
`wait_until="networkidle"` calls, with no CDN stubs — same three root causes, much larger surface
area (10+ test methods across ~1100 lines). Not fixed yet; flagged for whoever picks it up next.

## A working minimal harness

```python
import subprocess, time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path("/home/user/finviz-groups-tracker")
PORT = 8195
server = subprocess.Popen(["python3", "-m", "http.server", str(PORT), "--directory", str(ROOT / "docs")],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    page = browser.new_page()

    # CDN scripts — must stub these or the app never boots (Papa/tailwind undefined)
    page.route("**/cdn.tailwindcss.com/**", lambda r: r.fulfill(body=tailwind_js, content_type="application/javascript"))
    page.route("**/cdnjs.cloudflare.com/**", lambda r: r.fulfill(body=papaparse_js, content_type="application/javascript"))

    # Data CSVs/JSON — use "**/filename.ext" form, not "**domain**filename"
    page.route("**/picks_latest.csv", lambda r: r.fulfill(body=picks_body, content_type="text/plain"))
    page.route("**/snapshots.csv", lambda r: r.fulfill(body="date,...\n", content_type="text/plain"))
    page.route("**/deltas.csv", lambda r: r.fulfill(body="date,name\n", content_type="text/plain"))

    # Skip the first-run intro carousel before it can intercept clicks
    page.add_init_script("try { localStorage.setItem('fvt_intro_seen_v2','true'); } catch(e){}")

    page.goto(f"http://localhost:{PORT}/", wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    page.click("[data-tab='picks']")
    # ... assertions ...
    browser.close()

server.terminate()
server.wait()
```

## Verdict

Once all three root causes are worked around, the project's existing fixture-intercept pattern works
exactly as designed — confirmed end-to-end against real changes during this session (Picks tab Charts
links, dedup, scroll retention). The workarounds are environment-specific (this cloud session), not repo
bugs, except possibly Root cause 3's existing test files, which is flagged above for someone to verify.

## Update 2026-07-02: verifying without touching any committed file, and Root cause 2 generalizes

Built two new committed Playwright test files this session (`TestPWALookupChart` in
`test_functional_playwright.py`, `tests/test_pwa_picks_chart.py`) for a TradingView chart-embed
feature. Root cause 1's documented fix (pass `executable_path=` explicitly) means editing the test
file itself — fine for the ad hoc verification scripts this doc already sanctions hardcoding revision
numbers into, but for a *quick sanity check of a file you're about to commit*, there's a zero-diff
alternative: symlink the revision Playwright expects to the one actually installed, so the default
(no-`executable_path`) `p.chromium.launch()` call the committed test already uses just works.

```bash
ls /opt/pw-browsers/          # confirm the installed revision, e.g. chromium-1194
ln -s /opt/pw-browsers/chromium-1194 /opt/pw-browsers/chromium-1117   # 1117 = what playwright==1.44.0 expects
python3 -m pytest tests/test_pwa_picks_chart.py -v   # now passes with zero code changes
rm /opt/pw-browsers/chromium-1117   # clean up — this is a session-local /opt edit, never commit it
```

This confirms both new test files pass the actual committed assertions (lazy iframe load, correct
symbol embedded in the TradingView URL, toggle state) without any temporary code changes to revert
before committing — strictly better than the `executable_path=` edit-and-revert dance for a one-off
check, though `executable_path=` is still the right call for anything meant to run repeatedly (a
project skill, a CI debug step) since a symlink under `/opt/` doesn't survive a fresh container.

**Root cause 2 generalizes beyond `raw.githubusercontent.com` and CDN scripts**: this sandbox's
Chromium also cannot reach `s.tradingview.com` (the TradingView chart-embed iframe target), even
though `curl https://s.tradingview.com/...` from the same shell returns `200`. So Root cause 2 isn't
specific to those two domains — assume **no external domain is reachable from Chromium in this
sandbox**, full stop, and route-stub (or accept-as-unverifiable) anything that loads a third-party
iframe/script/fetch. For a feature like an embedded chart widget, this means the *rendering* of the
third-party content can't be visually confirmed in this sandbox — only the surrounding app mechanics
(does the iframe get inserted with the right `src`, does it lazy-load, does the toggle work) — actual
visual rendering needs a check in a real browser outside the sandbox (e.g. after deploying to GitHub
Pages).
