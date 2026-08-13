# docs/ — PWA (GitHub Pages)

> Loads only when working in `docs/`. Root `CLAUDE.md` has the project-wide picture; this
> file holds detail specific to `index.html` / `sw.js` that doesn't need to load every session.

`docs/` is named per GitHub Pages convention: "Deploy from branch → /docs" only supports `/`
or `/docs` as source. Do not rename it without switching to GitHub Actions deployment first.

## PWA display thresholds (near top of `<script>` in `index.html`)

These constants gate visual indicators in the PWA. Edit them directly in `index.html` — they
are not derived from the CSV pipeline. Any change must also update `README.md` § Configurable
parameters and, if it's a scoring/display constant tracked by the anti-drift guard, bump
`data/picks/display_methodology.json` (see `scripts/CLAUDE.md` § Picks pipeline).

| Constant | Default | Controls |
|----------|---------|---------|
| `REGIME_THRESHOLD` | `0.15` | Boundary between Emerging / Established / Fading buckets in Rotation view. Also the card color cutoff — must stay consistent (uses `REGIME_THRESHOLD` in both places). |
| `ACCEL_STRONG` | `0.08` | `momentum_accel` threshold for double-arrow (▲▲/▼▼) badge on Momentum cards. |
| `ACCEL_SLIGHT` | `0.02` | `momentum_accel` threshold for single-arrow (▲/▼) badge. Within ±`ACCEL_SLIGHT` = neutral `~` glyph (steady); NaN/insufficient history = dimmed `—`. |
| `SLOPE_STRONG` | `0.05` | `rank_trend_slope` threshold for double-arrow (↑↑/↓↓) glyph on Today cards. |
| `SLOPE_SLIGHT` | `0.01` | `rank_trend_slope` threshold for single-arrow (↑/↓) glyph. Within ±`SLOPE_SLIGHT` = `~`. |
| `RS_STRONG` | `2.0` | RS spread (pp vs S&P) threshold for deep-color badge in vs Market tab and Today cards. |
| `RS_SLIGHT` | `0.5` | RS spread threshold for mild-color badge. Within ±`RS_SLIGHT` = neutral chip. |
| `SIGNAL_WEIGHTS` | `{momentumConfirmed:0.30, rsConfirmed:0.30, rankDeltaShort:0.15, regime:0.15, breadth:0.10}` | Lookup tab SIGNAL card (`groupSignal()`): per-factor weight in the 0–1 composite. A factor with no source data is excluded and the remaining weights renormalized (same convention as `momentum_score`'s NaN handling), so missing data shrinks the average instead of injecting a fake neutral value. |
| `SIGNAL_FAVORABLE` / `SIGNAL_CAUTION` | `0.65` / `0.35` | Lookup tab SIGNAL card verdict thresholds on the `groupSignal()` composite score. `>= SIGNAL_FAVORABLE` → FAVORABLE, `<= SIGNAL_CAUTION` → CAUTION, between → MIXED, no data on either side → NO SIGNAL. |
| `BREADTH_TOP_HALF_FRACTION` | `0.5` | Sector-breadth "top half" cutoff, shared by `computeSectorBreadth()` (Strength-tab breadth table, week/month/quarter/half toggle) and `computeSectorTopHalfCounts()` (Today-tab sector card breadth bar + expand-in-place drill-down, YTD only). One threshold, two render targets — added when PR #178 (Today-tab breadth bar) was reconciled with the independently-shipped Strength-tab table (`122a4d1`). |
| `MIN_MARKET_CAP_B` | `5` | Picks tab base display filter (C6); rows below this market cap ($B) are hidden. |
| `ATR_EXT_ACTIONABLE` | `4.0` | ATR-extension emerald band cap; also the Focus hard-DQ line (Phase 3b). |
| `ATR_EXT_TRIM` | `8.0` | ATR-extension red band start; flags a held position as a trim-10% candidate. |
| `ATR_FROM_LOD_CLEAN` / `ATR_FROM_LOD_CHASE` | `0.8` / `1.0` | Morning tab (WS3, ADR-013) entry-quality bands on `atr_from_lod` = (price − session low) / ATR, shown only on actionable cards (Triggered / Gapped-through). `<= 0.8` clean entry (emerald "ok to act"), `> 1.0` chasing (red), between = caution (amber). Owner-set 2026-08-08. |
| `LAUNCH_NEAR_HIGH_PCT` | `8` | Launch-ready chip (Picks tab, Phase 1, `computeLaunchReady()`): `ohMag` (% below 52-week high) `<=` this = "near the high" (little overhead supply). Display-only, no scoring effect. |
| `LAUNCH_CALM_EXT_MAX` | `3` | Launch-ready chip: `atr_ext_50` `<=` this (and `> 0`) alongside near-high = `Coiled`; `>` this = `Extended`. |
| `LAUNCH_OVERHEAD_PCT` | `20` | Launch-ready chip: `ohMag >` this = `Overhead` (deep below high, heavy overhead supply). |
| `ATR_EXT_PENALTY_START` | `2.5` | Focus-score extension penalty ramp start; 0 penalty below this, ramps to `PENALTY_MAX` at `ATR_EXT_ACTIONABLE`. |
| `PENALTY_MAX` | `0.5` | Max Focus extension-discount fraction (50% haircut at 4×). `score = base × (1 − penalty_fraction)`, always ∈ [0, 1]. |
| `FOCUS_W_GROUP` | `0.2` | Focus score weight for group sustained-strength component (`grp_sum_mid_rank`). Lowered from `0.4` on 2026-07-16 (`display_methodology.json` v3); freed weight moved to `FOCUS_W_QUIET`. |
| `FOCUS_W_TIGHT` | `0.4` | Focus score weight for nearest-MA stop tightness component. |
| `FOCUS_W_QUIET` | `0.4` | Focus score weight for quiet-bar component (`range_atr`). Raised from `0.2` on 2026-07-16 (`display_methodology.json` v3). |
| `FOCUS_MIN_POOL` | `5` | Min Focus candidates before falling back from min–max to rank-based normalization. |
| `BUTTON_V` | `'311'` | Lookup deep-link button: Finviz screener view number (tight Stage-2 layout). Mirror of `data/picks/screener_config.json` `button.v`. Anti-drift guard in `tests/test_picks_button_config.py`. |
| `BUTTON_BASE_FILTERS` | `['cap_midover','ta_sma20_sa50','ta_sma50_pa']` | Lookup deep-link button: base Finviz filters prepended before `ind_<slug>` / `sec_<slug>` token. Mirror of `screener_config.json` `button.base_filters`. |
| `BUTTON_SORT` | `'sma50'` | Lookup deep-link button: sort order (ascending distance from 50MA). Mirror of `screener_config.json` `button.sort`. |
| `BUTTON_FT` | `'4'` | Lookup deep-link button: `ft` (filter type) parameter. Mirror of `screener_config.json` `button.ft`. |
| `EARNINGS_IMMINENT_DAYS` | `3` | Picks tab expanded card: earnings-date badge turns red when the next known earnings date is within this many days. |
| `EARNINGS_CAUTION_DAYS` | `10` | Picks tab expanded card: earnings-date badge turns amber when within this many days (and beyond `EARNINGS_IMMINENT_DAYS`). Only upcoming dates are colored — a past/stale date (Finviz hasn't refreshed) shows neutrally. |
| `FOCUS_MIN_DOLLAR_VOL` | `30_000_000` | Focus scoring (Phase 3d): hard gate — a stock must have avg $ volume (Price × Avg Volume) at or above this to be a Focus candidate at all. |
| `LIQUIDITY_PENALTY_START` | `60_000_000` | Focus scoring: above this avg $ volume, zero liquidity penalty; ramps to `LIQUIDITY_PENALTY_MAX` right above the `FOCUS_MIN_DOLLAR_VOL` floor. |
| `LIQUIDITY_PENALTY_MAX` | `0.3` | Focus scoring: max multiplicative score haircut for a Focus candidate near the liquidity floor. |
| `EARNINGS_PENALTY_MAX` | `0.7` | Focus scoring: max multiplicative score haircut for earnings within `EARNINGS_IMMINENT_DAYS`; ramps in from 0 at `EARNINGS_CAUTION_DAYS`. |
| `POST_EARNINGS_PENALTY_FRAC` | `0.25` | Focus scoring: one-day carry-over penalty (this fraction of `EARNINGS_PENALTY_MAX`) for a stock that reported exactly 1 day ago; 2+ days past is fully decayed to 0. |
| `OVERHEAD_PENALTY_START` | `8` | Focus scoring (Phase 2): `ohMag` (% below 52-week high) at/below this gets 0 overhead-supply penalty. Aligns with `LAUNCH_NEAR_HIGH_PCT`'s near-high free zone. |
| `OVERHEAD_PENALTY_END` | `30` | Focus scoring: `ohMag` at/above this gets the full `OVERHEAD_PENALTY_MAX` haircut; ramp is linear between START and END. Calibrated to the live pool's ~p25 `ohMag` (~28.6%). |
| `OVERHEAD_PENALTY_MAX` | `0.20` | Focus scoring: max multiplicative score haircut for deep overhead supply (far below 52wk high). Kept below the extension (`0.5`) and earnings (`0.7`) penalty ceilings so overhead acts as a tiebreaker, not a veto. |
| `ARIEL_GROUP_TOP_N_FULL` | `40` | Ariel match (Phase 4): group must rank in the top N industries by `rank_month + rank_quarter` ascending sum to fully qualify. Computed from `state.data.industries.delta` (all ~144 industries), not limited to groups picks.csv has stock rows for. |
| `ARIEL_GROUP_TOP_N_SOFT` | `50` | Ariel match: soft-qualify extension for ranks 41–50 (near-miss on the group gate). |
| `ARIEL_DOLLAR_VOL_MIN` | `100_000_000` | Ariel match: hard floor on avg $ volume (Price × Avg Volume, same formula as `FOCUS_MIN_DOLLAR_VOL`); no soft band — a liquidity floor, not a strength signal. |
| `ARIEL_ATR_PCT_FLOOR_SOFT` / `ARIEL_ATR_PCT_CEIL_SOFT` | `3.0` / `9.0` | Ariel match: daily-move gate (ATR/Price %) is excluded entirely outside this range — too quiet below the floor, too volatile above the ceiling. |
| `ARIEL_ATR_PCT_FULL_LOW` / `ARIEL_ATR_PCT_FULL_HIGH` | `4.0` / `7.0` | Ariel match: full-qualify band for the daily-move gate; the two outer bands (floor–low, high–ceiling) are soft-qualify. |
| `ARIEL_GROWTH_MIN_FULL` | `25` | Ariel match: EPS YoY TTM AND Sales YoY TTM must each be ≥ this % for the growth gate to fully qualify (AND, not OR). |
| `ARIEL_GROWTH_MIN_SOFT` | `15` | Ariel match: soft-qualify floor for EPS YoY TTM AND Sales YoY TTM — either metric below this fails the growth gate outright. |

## Morning tab (WS3, ADR-013)

The **Morning** tab (`renderMorning()` in `index.html`) reads the provisional store
`data/picks/sessions/morning_latest.csv` (fetched via `MORNING_URL`) and tags each of
yesterday's picks with a status computed server-side by `scripts/pick_status.py`. A missing
file (pre-first-run, or a non-trading day when `collect_morning.py` exits without writing) is
the empty state — a 404 is expected, never an error.

- **Provisional chrome is non-negotiable** (ADR-011): the amber banner + "provisional — not
  settled" timestamp must always render so a 10:05 ET read is never mistaken for settled EOD.
- **Actionability sort** (`MORNING_STATUS_META[*].order`): Triggered → Gapped-through → Failed
  breakout → Setting up → Invalidated → No quote. This is the *display* order and is
  deliberately different from the engine's evaluation precedence (`pick_status.STATUS_PRECEDENCE`).
- **`atr_from_lod` and the "I took it" button render only on actionable states** (Triggered /
  Gapped-through), gated by `MORNING_STATUS_META[*].actionable`.
- **"I took it" creates a real position (WS5 phase 1, #309).** It is login-gated: signed out, the
  tap shows a "Sign in on the Positions tab" note (no write); signed in, it opens an inline confirm
  (entry/stop/qty captured from the trade ticket's current state via `ws5BuildPayload`) → `POST
  /positions` to the `finviz-positions` worker (`POSITIONS_API`). The old `taken:<date>:<ticker>`
  localStorage marker is **kept, additively** — it still drives the card's "✓ Logged" state, but is
  now written only after a confirmed 201 (see `ws5ConfirmTakeIt`). `window.__morningTookIt` was
  removed; the writer is now `window.ws5TakeIt` → `ws5ConfirmTakeIt`.

## Positions tab (WS5 phase 1, #309)

Read-only. Signed out → a passphrase sign-in card (`posLogin` → `POST /auth/login` → bearer token in
`localStorage['fv_pos_token']`). Signed in → `GET /positions?state=open` renders frozen open-position
cards (entry/stop/risk/qty). No stop management or alerts yet — that is phase 3 (`advance()` engine)
and phase 4 (VAPID push). Auth is a worker-native bearer token (not Cloudflare Access — the PWA is a
cross-origin GitHub-Pages page); the whole auth surface is the swap seam `worker-positions/src/auth.js`.
See `worker-positions/README.md` and ADR-012 for the backend contract.

## Cutting a release ("What's New") — 3 steps, always together

The PWA's **What's New** hub reads `docs/releases.json`. Release versions use the
`YYYY.MM.DD` convention (human-scannable, monotonic, no semver to maintain). For multiple
releases on the same calendar day, append `.N` (e.g. `2026.06.21.1`, `2026.06.21.2`).
When you ship a user-facing change, do **all three** of these in the same PR:

1. **Prepend** a new entry to `releases.json` `releases[]` (newest-first): `version`
   (`YYYY.MM.DD` or `YYYY.MM.DD.N` for same-day releases), `date`, `title`, `tag`
   (`feature|fix|data|improvement`), optional
   `tab` (deep-links the entry to a tab), and a short user-facing `notes[]`.
2. **Update** the top-level `current` to the new `version` (this drives the unseen-update
   dot). `tests/test_guide_releases.py` asserts `current === releases[0].version`.
3. **Bump** `CACHE` in `docs/sw.js` (e.g. `finviz-v10` → `v11`) so the new shell +
   `releases.json` aren't served from a stale cache.

> **Hard rule:** code change + `releases.json` entry + `sw.js` cache bump must all land in the
> same PR. Splitting them across PRs creates gaps where the feature ships with a stale cache,
> or the release dot fires before the code is live. If you catch yourself opening a separate PR
> for "just the cache bump", stop — that's the failure mode. The only exception: housekeeping
> PRs (typos, session notes, refactors) with no user-facing change skip the release surface
> entirely. Full checklist: `.claude/rules/branch-commit-discipline.md`.

**Pre-commit check**: if your diff touches `docs/index.html` with a user-facing change, confirm
`docs/releases.json` and `docs/sw.js` are also staged before committing.

> The in-app **Guide** glossary copy lives in the `GUIDE` constant in `docs/index.html`,
> copied **verbatim** from the User one-liners in `knowledge/moaty-metrics.md`. The legend
> reads the live threshold constants (`REGIME_THRESHOLD`, `ACCEL_*`, `SLOPE_*`) so it can't
> drift. If you add a metric, add its `GUIDE` entry too — the anti-drift test enforces that
> every "why this matters" link targets a real `GUIDE` id.

## "Start Here" intro — `WELCOME` constant and first-run carousel

The **Start Here** hub section and the first-run full-screen carousel both draw from the
`WELCOME` array constant in `docs/index.html` (defined near `GUIDE`). The two surfaces
share one content source; `renderWelcome(mode)` switches rendering between hub ('hub')
and carousel ('carousel') modes.

**Canonical copy source:** `knowledge/product-intro-copy.md` — all `body` and `desc`
strings in `WELCOME` must appear verbatim there. `tests/test_pwa_intro.py` enforces the
sync (same discipline as `moaty-metrics.md` ↔ `GUIDE`).

**First-run behavior:** on page boot, if `localStorage.getItem(INTRO_KEY)` is
not `'true'`, the carousel auto-opens. Dismissing (Skip / Get started) calls
`setIntroSeen()` which sets the key. Re-openable anytime: hub ⓘ → Start Here → Replay
intro.

**`INTRO_KEY` versioning (currently `fvt_intro_seen_v3`, `docs/index.html`):** bump the
suffix only when the intro content changes substantially enough that existing users
should see it again (e.g. a new tab added, a new slide, a major rewrite — v2 added the
Picks tab, v3 added the vs Mkt tab + the Focus-picks slide). Minor copy edits do **not**
warrant a bump — they don't justify re-nagging users who already dismissed it. Record
any bump as a `feat:` commit with an explicit rationale; do not bump silently. Keep this
note's version number current — it drifted out of sync with the code once already.

**Tab deep-links:** each item in the tabs-tour slide carries a `tab` field (one of the
real tab ids in `VALID_TAB_IDS`, `tests/test_pwa_intro.py`). Adding a new tab requires
updating `WELCOME` + `product-intro-copy.md` + `VALID_TAB_IDS` — the anti-drift test
will catch a mismatch.

## Functional testing with Playwright (headless, no deployment needed)

The PWA fetches CSVs from `raw.githubusercontent.com`. Playwright can **intercept those
requests** and return local fixture CSV data, so the full UI can be tested without deploying
to GitHub Pages and without live data. Before running this in a Claude Code cloud session,
read `knowledge/investigations/playwright-cloud-session-testing.md` for cloud-specific gotchas
(Chromium revision mismatch, CDN/raw.githubusercontent.com route-stubbing, glob boundary bug).

```python
# Pattern: serve the PWA locally, intercept GitHub raw CSV fetches
import subprocess, time
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    server = subprocess.Popen(['python3', '-m', 'http.server', '8080', '--directory', 'docs'])
    time.sleep(1)
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    # Intercept CSV fetches and return local fixture data. Use "**/filename.ext" (slash
    # immediately before the literal suffix) — "**domain**filename" silently never matches.
    page.route('**/snapshots.csv', lambda r: r.fulfill(
        body=open('tests/fixtures/sectors_snapshots.csv').read(), content_type='text/plain'
    ))
    page.route('**/deltas.csv', lambda r: r.fulfill(
        body=open('tests/fixtures/sectors_deltas.csv').read(), content_type='text/plain'
    ))

    page.goto('http://localhost:8080/', wait_until='networkidle')
    # Now assert on rendered cards, tab switching, sort behavior, etc.
    server.terminate()
```

What this lets us test: tab switching, card rendering, sort/filter, movers gainers/losers,
momentum scores, empty-data placeholders, pull-to-refresh state, search filtering — all of
it, headlessly, in cloud.
