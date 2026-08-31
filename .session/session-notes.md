# Session Notes

> **Future Claude:** read this immediately at session start. Summarize the current state for the user before doing anything else.
>
> **Format:** Append a new `---` delimited block per session. Header = date + workstream description. Keep the last 4 sessions here; a human will periodically move older entries to `.session/archive/session-notes-archive.md`. Do NOT replace existing entries — append only.

---

## 2026-08-31 — Fix: misleading "not tracked" message on Lookup + data-load completeness guard

**Status: safe to close — implemented, tested (739 non-Playwright + `test_pwa_lookup_signal.py`
8/8 green), PR to open.**

**Report.** Owner saw the Lookup tab's Industry card for "Asset Management" say "Not separately
tracked in the Finviz data yet" — the industry *was* fully tracked (verified live: worker
`/lookup` and both `data/industries/snapshots.csv`/`deltas.csv` had complete rows for the
latest date). Closing and reopening the app fixed it, pointing at a one-off data-load problem
rather than a genuine coverage gap.

**Root cause (best available evidence, not fully proven live).** `findGroupData()` can't tell
"group genuinely isn't in Finviz's taxonomy" apart from "the CSV fetch was interrupted and this
name's row never arrived" — both look like a missing row. Reproduced the failure mode
end-to-end with a deliberately truncated `industries/snapshots.csv` fixture (Playwright, local
harness, real code path): Papa Parse's `results.errors` flags the ragged trailing row from a
cut-short download, confirming a truncated fetch *is* detectable and *was* previously being
cached anyway.

**What landed (`docs/index.html`):**
- `loadGroup()` now rejects a sectors/industries fetch outright when Papa Parse reports any
  row-level parse error, instead of silently caching a dataset that "completed" but is missing
  rows. Leaves prior good data in place; surfaces the existing error+Retry banner.
- `groupPerfCard()`'s empty-state copy no longer asserts "not tracked" as settled fact — says
  data didn't load and adds a "↻ Refresh data" button (`window.__refresh()`).
- `contextSignalCard()`'s "no tracked data for X yet" / "Not enough tracked history..." copy
  (same underlying `findGroupData()` root cause, same misleading pattern) reworded to "no data
  loaded... right now" with a refresh nudge.
- Confirmed for the owner: both the top-right refresh button and pull-to-refresh call
  `window.__refresh()`, which does a real cache-busted re-fetch (`?_=timestamp`) of
  sectors/industries — not a cache replay. Either is a legitimate fix for this failure mode.

**Not fixed, flagged for a future session:** while reproducing, found that switching to the
Industries group (Today tab) after its load has failed re-triggers `loadAndRender()` on every
click via `switchGroup()`'s `if (!state.data[group].snap) loadAndRender()` check, and in the
Playwright test harness this consistently threw inside `setLoading()` (`gainers-list` element
not found) — but the same throw reproduces identically on a stashed, fully-unmodified checkout
with no data at all, so it looks like a pre-existing headless/Tailwind-CDN test-harness quirk
rather than something this session's change caused or fixed. Did not chase further — out of
scope for this fix, and unconfirmed as a real production issue vs. a sandbox artifact.

**Release triplet:** `docs/releases.json` `2026.08.31.1` (fix, tab lookup) + `current` bumped;
`docs/sw.js` v88→v89. Also updated `tests/test_pwa_lookup_signal.py`'s caveat-text assertion to
match the new copy, and documented the fix in `docs/CLAUDE.md` + README § PWA display thresholds
(no new tunable constant — the guard is unconditional, not threshold-based).

---

## 2026-08-31 — Effort B first slice: "Volatility & setup" section on Picks cards

**Status: safe to close — implemented, tested (8/8 Playwright file + 731 non-PW suite green), PR to open.**
Continues the compression/expansion workstream from merged PR #377 (planning doc) + issues
#378 (Effort A, card standardization) / #379 (Effort B, metrics). Owner directive: compression
is the spine — surface the factual, repeatable, proven stuff (Vol W/M, ATR, range tightening,
volume behavior, MA bunching); show raw values, let the trader assess; **never invent
thresholds** (doc §4.0). Owner chose "B-spine on the Picks card first" for this slice (the card
that already has all the data — no data decision, no pipeline change).

**What landed (`docs/index.html`, `renderPickRow` expanded panel).** A new "Volatility & setup"
section under the risk-basis grid, rendered once from the full row `r` (basis-independent, so it
lives in `renderPickRow`, not `__buildRiskBasisContent`):
- **Vol W / Vol M** — both raw (`_pPct`), e.g. `4.3% / 4.6%`. The one derived read is a
  `contracting` (emerald) / `expanding` (amber) / `flat` label = pure sign of (Vol W − Vol M),
  a *fact* (which is larger), not a magnitude cutoff. Neutral/blank when either is NaN.
- **Rel volume** — `_pF(r['Rel Volume'])`, shown as `0.87×`.
- **From 52W high** — `_pF(r['52W High'])` (Finviz's signed % distance, negative = below), shown
  as-is, e.g. `−8.0%`.
All four already flow daily in `picks_latest.csv` — **no scrape change, no new column, no new
configurable constant** (the whole point of §4.0 — nothing to threshold, so nothing to
triple-document). Verified the columns + formats against a live `picks_latest.csv` row and the
ANET fixture before writing.

**Why this shape.** Establishes the named "Setup/Volatility" card section that Effort A (#378)
will propagate to the Morning-family cards, so Effort B doesn't hand-add chips to diverging code
paths later (the doc §8 soft-ordering, honored without blocking on A's harder data decision).

**Tests.** 2 new tests in `tests/test_pwa_picks_atr_earnings.py` (already in the CI `--ignore`
list): `test_volatility_setup_section_shows_raw_values` (ANET: Vol W<M → contracting, RelVol,
From-52W-high strings) and `test_volatility_setup_expanding_when_week_hotter` (override Vol W>M →
expanding). Ran live via the revision-symlink harness (`ln -sfn chromium-1194 chromium-1117`,
per `knowledge/investigations/playwright-cloud-session-testing.md`) — full 8/8 file green.
Non-Playwright suite 731 passed. Release triplet: `docs/releases.json` `2026.08.31` (feature,
tab picks) + `current` bumped; `docs/sw.js` v87→v88.

**Next steps / open Effort-B slices (tracked, #379 + SPRINT EFFORTB-VOLSETUP-1):**
- **NR7 flag + range_atr / ATR sparkline** — need per-name trailing session history → these are
  *derived pipeline columns* (graceful-degrade per name/metric, doc §3), a bigger slice than pure
  display. Next natural build.
- **Rule-of-Three** MA-bunching confirmer (doc §5.3) — weakest signal, confirmer only.
- **Propagate the section to Lookup + Morning cards** — rides Effort A's (#378) shared-component
  seam; the §7.3 morning-data decision (scrape-wide vs cross-ref hybrid) is still open and
  needs the verification the doc flags before championing either.
- Expansion side stays parked/secondary per owner (doc §5.5a) — not touched here.

---

## 2026-08-27 — Fix: Watchlist "⋯" kebab menu never opened (Remove unreachable)

**Status: safe to close — fixed, tested, PR to open.**

**Report.** Owner asked how to remove a stock from the watchlist; walked them to Morning →
Watchlist subtab → "⋯" kebab → Remove (per PR #370, `2026.08.26.2`). Owner replied: "I see a
kebab but nothing happens when I tap."

**Root cause.** `docs/index.html` `watchKebabHtml(entry)`:
```js
const isOpen = state.watchMenu === entry.id;
```
`entry.id` comes from `finviz-positions`' D1 `watchlist` table, `id INTEGER PRIMARY KEY
AUTOINCREMENT` (migration 0003) — a JS **number** once parsed from the worker's JSON response.
But the onclick handler that sets `state.watchMenu` is built as a template literal —
`onclick="__toggleWatchMenu('${entry.id}')"` — which necessarily quotes it into a **string**
in the generated HTML. So `state.watchMenu` was always a string (e.g. `"5"`) while `entry.id`
stayed a number (`5`); `"5" === 5` is `false` in JS, so `isOpen` was always false. The tap did
register (state updated correctly), it just never rendered the menu open — every tap looked
like a no-op. Fix: `String(state.watchMenu) === String(entry.id)`.

**Why existing tests missed it.** `tests/test_pwa_watchlist.py`'s `WATCH_ENTRY` fixture used a
string id (`"w1"`), which happened to satisfy the (buggy) strict-equal check by coincidence —
masking the bug since PR #370. Fixed the fixture to use real numeric ids (`1`/`3`), matching
production D1 data, and confirmed the test now actually fails on the pre-fix code (reverted
`docs/index.html`, reran — `test_remove_sends_patch_not_delete` timed out waiting for "Remove"
to appear, exactly reproducing the owner's symptom) and passes with the fix restored.

**Bonus find while debugging in this cloud sandbox:** the same test file's `_base_routes()`
was missing a stub for `pre_close_latest.csv`. `switchTab('morning')` unconditionally fetches
`PRECLOSE_URL` on first visit; with no stub, Chromium in this sandbox hangs indefinitely on
that unreachable domain (known Root Cause 2 in
`knowledge/investigations/playwright-cloud-session-testing.md`) rather than failing fast —
this silently broke every test in the file until stubbed, not caused by this session's change
but discovered and fixed here since it blocked verification.

**Verification.** Node-level minimal repro of the strict-equal bug (proved both broken and
fixed behavior in isolation) + full headless-Chromium Playwright run via the documented
symlink trick (`chromium-1117` → `chromium-1194`) — all 8 tests in
`tests/test_pwa_watchlist.py` pass; full non-Playwright suite (`pytest tests/ -q`, 731 tests)
green.

**Shipped:** `docs/index.html` fix, `tests/test_pwa_watchlist.py` fixture fix +
`pre_close_latest.csv` stub, `docs/releases.json` entry `2026.08.27.1`, `docs/sw.js`
v86→v87, `.session/SPRINT.md` Done entry.

**Next steps:** none — self-contained fix. No other `entry.id`-style comparisons found
elsewhere in the watchlist code (grepped; only `watchKebabHtml`'s `isOpen` check does a
strict-equal against an id — the other `entry.id` usages just interpolate it into API call
URLs/bodies, where the number/string distinction doesn't matter).

---

## 2026-08-27 — Morning Picks: failed-breakdown / undercut-and-reclaim ("Reclaimed")

**Status: safe to close pending CI — implemented + committed on
`claude/failed-breakdown-undercut-unr-2vdvhk`, Python core fully tested (92 targeted + 731
full non-Playwright suite green), PR to open.** Closes the deferred "picks opting into
`reclaim`" item from `planning/watchlist-build-brief-8b.md` §10 line 305.

**What it does.** The `reclaim` engine state (undercut a reference level, recover above it —
mirror of `failed_breakout`) previously fired only for watchlist tickers (they pass
`ref=sma50`); picks passed `ref=None` and never lit. Now Morning **picks** emit `reclaim` too.

**Owner decisions (2026-08-27, all locked in-session):**
1. **Both refs** — a pick reclaims against EITHER its prior swing low OR its derived 50MA.
2. **Full entry trigger** — actionable (ATR-from-LoD + "I took it"), not just an info flag.
3. **Label "Reclaimed"** (consistent with watch cards).
4. **Name the level** on the card → two new store columns.
5. **50MA derived from picks_latest's %-distance `SMA50`, ~1 session stale — accepted.**
6. **Reclaim ranks ABOVE `failed_breakout`, applied uniformly to picks AND watch** (owner: "it
   doesn't make sense to change one and not the other"). Kept `invalidated` > `reclaim`.

**Changes.**
- `scripts/pick_status.py`: `STATUS_PRECEDENCE` reordered (reclaim above failed_breakout); new
  pure `matched_reclaim_ref(price, today_low, prior_low, candidates)`; `compute_pick_status`
  gains `reclaim_refs` param + `_reclaim_candidates` normalizer; reclaim check moved above the
  failed_breakout check. Legacy scalar `ref` (watch) still works, byte-identical except the
  intended reorder. Docstrings/precedence comments updated.
- `scripts/collect_morning.py`: `load_pick_levels` attaches `reclaim_refs` via new
  `_pick_reclaim_refs(row, stop)` (prior_low + derived abs 50MA = `Price/(1+SMA50%/100)`);
  `build_status_rows` threads `reclaim_refs=` and, on a reclaim row, re-derives the fired level
  into new columns `reclaim_ref`/`reclaim_ref_value`. `STORE_COLUMNS` +2 (superset-additive —
  `write_store` full-rewrites + backfills "" via `r.get(col,"")`, no ensure/migration needed).
- `docs/index.html`: new `reclaim` case in `morningCardBody` naming the level (50MA `~`-prefixed
  as stale/derived); `MORNING_STATUS_META.reclaim.actionable` false→true. **Verified watch cards
  don't read `.actionable`** (only stripe/pill/label), so the flip is isolated to picks.
- Release triplet `2026.08.27` / `sw.js` v85→v86. ADR-013 Decision 3 amended (precedence table +
  two dated amendment notes). `scripts/CLAUDE.md` + `docs/CLAUDE.md` updated.
- Tests: `tests/test_pick_status.py` (precedence flip + `reclaim_refs`/`matched_reclaim_ref`
  coverage), `tests/test_collect_morning.py` (reclaim_refs derivation + picks reclaim status +
  reclaim beats failed_breakout), `tests/test_pwa_morning.py` (new reclaim render test — already
  in the CI `--ignore=` list).

**Verification note (honest).** Python core executed green. **Could not run the Playwright PWA
tests in this cloud sandbox** — the pinned `playwright==1.44.0` vs pre-installed browser layout +
the offline route-stubbing hang means ALL `test_pwa_morning.py` tests (pre-existing ones
included) fail identically here; it's the environment, not the change. The new PWA test follows
the exact established harness and will run in CI. The main `<script>` block parses cleanly
(node `new Function`).

**Next steps:** open PR, confirm CI (esp. the Playwright `test` jobs) goes green. Still deferred
(unchanged, tracked in brief §10): multi-day reclaim.

---

## 2026-08-26 — PR #368 review follow-up: watch-add FMP seed was blocking, not fire-and-forget

**Status: safe to close — fix implemented, tested, pushed on `claude/fix-watchlist-seed-await`, PR
open against default.** Reviewed merged PR #368 (WS-POSITIONS-SEED). Found one bug: `src/index.js`'s
`POST /watchlist` handler did `await seedTickerBar(...)` before responding, even though both the PR
description and `worker-positions/CLAUDE.md` document the seed as "fire-and-forget — never changes
the response." A slow/unresponsive FMP call added up to `FMP_TIMEOUT_MS` (5s) of real latency to
every watchlist add (and every re-add/renew, which hits the same code path), even though the watch
row was already durably written before the wait started.

**Fix:** threaded `ctx` (the Cloudflare `ExecutionContext`) through `fetch()` → `handleRequest()`,
and at the call site handed the seed promise to `ctx.waitUntil()` instead of awaiting it — response
now returns as soon as the D1 write lands; the FMP fetch + insert continue in the background.
`ctx` is optional everywhere it's threaded (existing test call sites that don't pass a third arg are
unaffected — the seed promise just runs undetached, same as any environment without `waitUntil`).

**Tests:** added one test in `test/index.test.js` that stubs a slow `fetch`, passes a `ctx.waitUntil`
spy, and asserts `POST /watchlist` resolves (201) well before the stubbed fetch settles, with the
seed promise captured by `waitUntil` rather than awaited inline. 311 worker-positions vitest tests
pass (was 310, this is the 1 new test).

**Docs:** added a fifth "thing to internalize" to `worker-positions/CLAUDE.md`'s § The watch-add
seed, and updated the `WS-POSITIONS-SEED` SPRINT row with this follow-up.

**Next steps:** none blocking — this is a self-contained fix. Owner should merge the PR; no schema
change, no ops impact, no release-surface entry needed (backend latency fix only, no user-visible
copy change).

---

## 2026-08-26 — Morning tab: Picks/Watchlist subtabs, levels-hidden default, soft-remove watchlist

**Status: safe to close — implemented, backend tests pass (310 vitest), PWA functionally
verified in a real headless-Chromium harness (revision-symlink workaround, see
`knowledge/investigations/playwright-cloud-session-testing.md`), committed on
`claude/morning-subtabs-watchlist-q70cvm`. Not yet pushed/PR'd as of this note — see Next
steps.** Owner request (three asks in one message, no issue #): split the Morning tab's
watchlist out of the picks scroll, hide the price-levels bar by default, and let a removed
watch ticker stop being scraped while still showing a chart.

**1. Morning subtabs (`docs/index.html`).** New `#morning-subtab-picks` / `#morning-subtab-
watchlist` panes inside `#tab-morning`, switched by a segmented-pill nav
(`renderMorningSubtabs()` / `window.__setMorningSubtab`, styled like the existing Picks
All/Focus toggle). Both panes render unconditionally on every `state.tab === 'morning'` pass
(`render()` calls all three: `renderMorningSubtabs(); renderWatchlistSection(); renderMorning();`)
— switching subtabs is a pure `classList.toggle('hidden', ...)`, no extra fetch. Default pane
is `'picks'` (`state.morningSubtab`, session-only). Watchlist button shows an active-entry
count badge when non-zero.

**2. Levels gauge hidden by default.** `state.watchGauge[ticker]`'s meaning flipped from
"collapsed?" (absent/false = shown, the old default) to "shown?" (absent/false = hidden, the
new default) — a pure polarity flip in `watchCardHtml`/`__toggleWatchGauge`, no new state
shape. Comments updated in both places to spell out the new default explicitly (the SPRINT
board's "gauge on-by-default" line from WS5-8b's original design is now superseded).

**3. Soft-remove watchlist entries (`worker-positions` + PWA).** New terminal status
`'removed'` on the `watchlist` table (migration `0007_watchlist_removed.sql` adds
`removed_at`, mirroring `expired_at`'s shape). `PATCH /watchlist/:id {remove:true}` (new
`patchWatch` branch) replaces the old hard `DELETE` for the kebab's "Remove" button — the row
survives so it renders in a new collapsed "Recently removed" bin (`watchRemovedCardHtml`,
mirrors the existing "Expired" bin) instead of vanishing. Key design point: `watchlistTickers()`
(feeds `heldTickers()`'s scrape union AND the public `GET /watchlist-tickers` feed) already
filters `status = 'active'` — `'removed'` is excluded identically to `'expired'` with **zero
new filter code**, so a removed ticker stops being scraped on the very next held-feed run for
free. The removed card still renders a free TradingView chart
(`watchChartAffordance(ticker)` needs only the symbol, independent of any backend feed) plus a
`{restore:true}` button (same renew-with-fresh-TTL semantics as the existing Renew action). The
hard `DELETE`/`watchDeleteApi` path still exists, now used ONLY for graduation cleanup
(`watchGraduate`'s post-`POST /positions` cleanup — a graduated ticker should vanish outright,
not sit in a removed bin). `tickWatchlist()` purges `'removed'` rows after
`WATCHLIST_PURGE_DAYS`, symmetric with the existing `'expired'` purge.

**Verification:**
- `worker-positions`: `npm test` → 310 vitest passing (was 295; +9 counting the new remove/
  restore/purge tests plus `d1.js` helper updates for the migration + `removed_at` default).
- Root pytest suite (non-Playwright): 719 passed, same baseline as the prior session's note —
  no regressions.
- **PWA functional verification actually ran a real headless Chromium** (not just code
  review) — `p.chromium.launch(executable_path="/opt/pw-browsers/chromium")` per the
  documented revision-symlink workaround, plus a local stub for `pre_close_latest.csv` (a
  pre-existing gap in `_base_routes()` — not stubbed by the committed test file at all,
  real internet reaches `raw.githubusercontent.com` fine in CI/dev so it was never hit
  there; **not fixed here, out of scope for this change** — flagged for whoever next hits
  it in this sandbox). Confirmed live: subtab default + switch, gauge default-hidden +
  toggle-shows, existing active-card rendering unaffected, "Recently removed" bin renders
  a removed entry with chart + Restore, and the kebab's Remove sends `PATCH {remove:true}`
  (not `DELETE`). 4 new/updated tests added to `tests/test_pwa_watchlist.py`
  (`test_gauge_toggle_hides_panel_and_flips_label` rewritten for the flipped default;
  `test_removed_entry_renders_in_collapsed_recently_removed_bin`,
  `test_remove_sends_patch_not_delete`, `test_morning_subtabs_default_picks_switch_to_
  watchlist` new) — file stays in the CI Playwright `--ignore=` list, no change needed there
  (already present).
- Release triplet done in-PR: `docs/releases.json` new `2026.08.26.2` entry (tag
  `improvement`, tab `morning`) + `current` bumped; `docs/sw.js` `CACHE` `finviz-v84` →
  `finviz-v85`.
- Docs updated 3-places-style: `worker-positions/README.md` (routes table + constants
  table), `worker-positions/CLAUDE.md` (§ watchlist, new soft-remove subsection),
  `docs/CLAUDE.md` (§ Watchlist + § Morning tab).

**Next steps (blocking merge, same shape as WS-POSITIONS-SEED/#368 before it):** (1) push
the branch, open the PR; (2) **apply `migrations/0007_watchlist_removed.sql` to prod
`finviz-positions` D1 out-of-band before/alongside merge** — the writer's `remove`/`restore`
branches reference `removed_at`, and merge auto-deploys the worker; (3) merge; (4) post-merge,
remove a watch ticker and confirm it drops into "Recently removed" and stops updating on the
next held-feed run.

---

## 2026-08-26 — Lookup rank sparkline: margin fix + touch/hover scrub tooltip + owner-review follow-up

**Status: safe to close — implemented, verified in a headless-Playwright harness with real
Tailwind CSS loaded (proxy-fetched once, stubbed locally — see below), committed on
`claude/sparkline-view-improvements-u93bq1`.**

User feedback on a screenshot of the Lookup tab's weekly-rank sparkline (`rankSparkline()`,
`docs/index.html`): (1) the `#lo`/`#hi` range labels on the right crowded right up against the
plotted line with no breathing room, and (2) requested an iOS-Stocks-style touch interaction —
drag/hover along the line to see the rank + date at that point.

- **Margin fix**: `rankSparkline()` now uses an asymmetric `padRight` (20 SVG units) vs
  `padX`/`padY` (2/4), shrinking the plotted line's width so the range labels get clear space
  instead of sitting on top of the line's end.
- **Scrub tooltip**: each rendered sparkline embeds its points (date, rank, precomputed pixel
  x/y) as a JSON `data-points` attribute on a wrapper div. New `window.sparkScrub`/
  `window.sparkEnd` functions (pointer events — covers both touch and mouse) find the nearest
  point by x-distance, move a cursor dot + vertical guide line to it, and show a floating tip
  (`posFmtDate()` reused for the "Mon DD" format, no new date-formatting helper needed) reading
  `"Aug 9 · #34 of 143"`. Tip position clamped 10–90% so it can't clip off either edge.
- **Verification**: no existing pytest file covers the sparkline, and this is PWA-only (no
  `scripts/` change), so no new test file was added per the "dashboard-only — note it in the
  commit" testing-requirements carve-out. Instead ran a throwaway Playwright script (not
  committed) reusing the CSV-route-interception pattern from `docs/CLAUDE.md`, seeding 25 days
  of one industry's delta history so the sparkline had enough points to scrub. Confirmed via
  screenshot + DOM assertions that the tooltip renders the correct date/rank and that the margin
  looks right. **Note for future sessions**: the default `page.route` Tailwind-CDN stub (an
  empty JS comment, used in the existing `test_pwa_*.py` suite) leaves all `.absolute`/
  `.relative` positioning classes inert — fine for text-content assertions but not for visually
  confirming an absolutely-positioned element's actual screen position. Fetching the real
  `cdn.tailwindcss.com` script once via `curl` and stubbing *that* body instead (kept it in the
  session scratchpad, not committed) got real CSS applied for a true visual check.
- **Release surface updated in the same PR** (hard rule): `docs/releases.json` new
  `2026.08.26` entry (tag `improvement`, tab `lookup`) + `current` bumped; `docs/sw.js`
  `CACHE` bumped `finviz-v82` → `finviz-v83`.
- Ran the full non-Playwright pytest suite (719 passed) plus confirmed the 65 Playwright-based
  failures are pre-existing (identical failure count/list with `git stash` reverting this
  change) — the known cloud-sandbox Chromium-revision gap documented in
  `knowledge/investigations/playwright-cloud-session-testing.md`, not a regression.

**Owner review follow-up, same PR (#369), still unmerged so amended in place per the
Amendment policy** — two real issues from a screenshot re-check:
- **Labels still looked squished, root cause was distortion not spacing.** The `#lo`/`#hi`
  labels were `<text>` elements *inside* the sparkline's `<svg>`, which uses
  `preserveAspectRatio="none"` — height scales 1:1 (`h-8` = the viewBox's 32 units exactly) but
  width stretches ~2-3x to fill the card. That non-uniform scaling stretched the text glyphs
  horizontally, reading as vertically-compressed/distorted regardless of how much margin they
  had. Fix: moved both labels out of the SVG entirely, rendered as plain absolutely-positioned
  HTML `<span>`s (`top-2 right-0` / `bottom-2 right-0`) overlaid on the reserved `padRight`
  gutter — real CSS pixels, immune to the SVG's viewBox distortion.
- **Touch target was only 32px tall.** The scrub wrapper matched the SVG's own height exactly
  (`h-8`), under Apple's ~44px touch-target guideline, even though the scrub math only reads
  x-position (y is irrelevant). Fixed with the padding+negative-margin trick: `py-2 -my-2` on
  the wrapper gives a 48px-tall pointer/touch hit box while contributing zero extra height to
  the surrounding layout (verified via `getBoundingClientRect()` in the same Playwright
  harness — wrapper rect height came back 48px, unchanged row spacing above/below in the
  screenshot). Neighboring rows have no click handlers, so the small overlap is safe.
- Re-verified visually with the same real-Tailwind Playwright harness (still uncommitted,
  scratchpad-only): labels now render crisp, tooltip still shows the correct
  `"Aug 9 · #34 of 2"` text with the taller hit box. Re-ran the same pytest suite — still 719
  passed, 65 pre-existing Playwright failures.
- `docs/releases.json`: same `2026.08.26` entry's `notes[]` amended in place (added the
  distortion-fix + bigger-touch-target lines) — no new version bump, no `sw.js` re-bump, since
  the PR carrying that version is still open (per the release-cutting rule, a version bump is
  per-PR, not per-commit).

**Second owner round, same PR, same day: chart itself was too short (separate from the touch-
target ask).** Bumped the sparkline's viewBox/CSS height from 32px (`H=32`, `h-8`) to 48px
(`H=48`, `h-12`), and `padY` proportionally 4→6 to keep the same ~12.5% top/bottom breathing
room. Height still scales 1:1 (viewBox units == CSS px via the matching `h-*` class), so this
adds no new distortion — same non-uniform-scaling caveat as before applies only to the
horizontal axis, unchanged. The `py-2 -my-2` touch-padding trick stacks on top unchanged, so the
scrub hit box is now ~64px tall (48 visible + 16 padding). Re-verified with the same throwaway
Playwright+real-Tailwind harness; re-ran pytest (719 passed, same 65 pre-existing failures).
`docs/releases.json`'s `2026.08.26` entry got one more amended note line; still no version bump
(PR still open).

**Next steps**: none outstanding — PR ready to open against
`origin/claude/sparkline-view-improvements-u93bq1`.

---

## 2026-08-26 — WS-POSITIONS-SEED build (seed first bar on watchlist add)

**Status: DON'T CLOSE YET — draft PR #368 open, needs to be marked ready; owner approved the
build this session.** Implemented the seed feature whose groundwork landed in #367.

**What it does (plain):** on `POST /watchlist`, best-effort-fetch the ticker's newest completed
daily bar from FMP `historical-price-eod/full` and `INSERT OR IGNORE` it into `ticker_quotes` as
`source='fmp_seed'`. A brand-new watch ticker then resolves to a real level on its next status
read (10:05 or 15:30 ET) instead of waiting for the 17:30 held feed. Ceiling: saves one trading
morning; for an evening/weekend add it's a live card next morning vs. the morning after.

**What landed (branch `claude/ws-positions-seed-proposal-9tmnr7`, PR #368, base = default):**
- **Commit 1 (step 1):** `migrations/0006_ticker_quotes_source.sql` — `ALTER TABLE ticker_quotes
  ADD COLUMN source TEXT NOT NULL DEFAULT 'finviz'`. Additive/non-breaking (ingestQuotes'
  INGEST_COLS never mentions it; sweep reads SELECT *). Added to test harness MIGRATIONS list.
- **Commit 2 (steps 2-3):** new `src/seed.js` (`mapFmpBar` pure mapper + `seedTickerBar`), one-line
  wire into `index.js`'s POST /watchlist handler (fire-and-forget, double try/catch), 9 new tests
  in `test/seed.test.js`. Safety pinned by tests: INSERT OR IGNORE never clobbers; a seed bar is
  excluded from a synthetic position's `loadBarsAfter` window (strictly `> floor`).
- **Commit 3 (docs+tracking):** README endpoint row + CLAUDE.md new "§ The watch-add seed" section,
  this SPRINT row flipped to BUILT, these notes.

**Both residuals closed this session (not just deferred):** (1) Finviz OHLC — `collect_morning.py::
fetch_ticker_quotes` takes displayed prices as-is via `_to_float`, no adjustment math; Finviz
screener prices are split-adjusted, FMP `full` is split-adjusted → consistent, and moot anyway
since seed (prior session) and Finviz (today+) are never the same date and MAX(trade_date)
supersedes. (2) `refsFromRow()`/`watchlistTickerRefs()` join on MAX(trade_date), no source-
awareness → seeded bar picked up transparently. FMP flat-array shape re-verified live (curl AAPL).

**Verification:** 304 worker-positions vitest tests pass (was 295). FMP response shape confirmed
live. Did NOT run a real end-to-end POST /watchlist against prod (needs deploy + prod D1).

**Next steps (blocking merge):** (1) mark PR #368 ready; (2) **owner applies migration 0006 to
prod finviz-positions D1 out-of-band BEFORE merge** — the writer's INSERT sets `source`, and merge
auto-deploys the worker; (3) merge; (4) post-merge, add a watch ticker and confirm the card shows a
real level at the next status read. No release-surface triplet needed (backend behavior, no new PWA
copy) — re-confirm before merge if any PWA copy turns out to change.

---

## 2026-08-28 — Fix: Morning ticket "ATR from LoD" had no way to correct a wrong scraped Low

**Status: safe to close — fixed, tested, PR to open.**

**Report.** Owner flagged a RPRX Reclaim card's "ATR from LoD" reading (0.1, "ok to act") as
implausible next to the actual chart. First pass (wrong): assumed the session low had simply
kept falling *after* the 10:05 ET morning scrape (a staleness story). Owner corrected this —
their broker's chart showed the day's actual low (61.01) printed in the very first 5-minute bar
(9:30–9:35 ET), well *before* the 10:07:32 ET scrape. Pulled the real stored row
(`data/picks/sessions/morning.csv`, 2026-08-27) to check: `open=61.44, high=61.67, low=61.42,
price=61.60`. So Finviz itself told our scraper `Low=61.42` at 10:07 ET — 37 minutes after a
day-low print of 61.01 had already happened. Confirmed this is **not** a parsing/column bug on
our side (checked `screener_config.json`'s `morning` block id 88 → "Low" against
`tests/test_collect_morning.py`'s fixture header — matches; `compute_atr_from_lod`'s math on the
stored value is correct: `(61.60−61.42)/1.35=0.133→"0.1"`). Root cause is either a genuine
Finviz delayed-quote lag/quirk specific to this narrow `t=`-filtered screener block, or something
about our request timing — couldn't pin down which from this cloud sandbox (Cloudflare blocks
live Finviz access here, per root `CLAUDE.md`).

**Shipped (per owner's direction — go straight to the fix + a tracked watch-item, not further
live-data investigation this session):**
- `docs/index.html`: added a second "Low so far" input (`ws4-low-${ticker}`) in the trade
  ticket, next to the existing "Price now" input — mirrors that field's override pattern exactly
  (`ts.lowOverride`, `ws4LowForCalc()` alongside `ws4PriceForCalc()`), wired into both
  `ws4Recompute` (live patch) and `ws4TicketHtml` (initial render). Previously "Price now" was
  the *only* editable input despite the ticket's own copy claiming "both gates ... recompute off
  your number" — the ATR-from-LoD gate's `low` input had no correction path at all, so a wrong or
  stale scraped low stayed wrong for the rest of the session with no fix available. Deliberately
  left the "Today low" stop-basis option (in the 4-way stop menu) on the raw scraped value —
  different concept (a structural stop level, not a live chase-risk read); scope stayed to the
  gate the owner actually reported on.
- `tests/test_pwa_trade_ticket.py`: new `test_low_edit_recomputes_atr_from_lod_label`, mirrors
  the existing price-edit test (AXON fixture: price=613.90, atr=14.20; typing low=590 pushes
  `(613.90−590)/14.20=1.68` past the 1.0 chase-risk threshold). Verified locally via the
  documented revision-symlink harness (`knowledge/investigations/playwright-cloud-session-testing.md`)
  — full 8-test file green (was 7).
- `.session/SPRINT.md`: `WS4-LOW` (done) under the WS4 section, plus a new **`DATA-FINVIZ-LOW`**
  backlog watch-item under Data Pipeline — the open question (Finviz data lag vs. our request
  timing) is *not* resolved by this fix, just made correctable in the UI. Next-session pickup
  path documented there: cross-check a few more `reclaim`/`triggered` mornings' `low` column
  against an independent source to see if this is a one-off or a systematic pattern.
- No release triplet (`releases.json`/`sw.js` bump) — internal tool-correctness fix to an
  existing ADR-014 ticket input, not a new user-facing feature per se; the owner can ask for one
  in a follow-up if they want it announced in What's New.

**Next steps:** none blocking. `DATA-FINVIZ-LOW` is a watch item, not an open task with a
deadline — pick it up opportunistically next time a `reclaim`/`triggered` morning card looks off
against a live chart, and log what's found (confirms Finviz-side lag vs. rules out our own code
further).

---

## 2026-08-30 — PR #374 review follow-up: low override → Today-low stop + localStorage persistence

**Status: safe to close — implemented, tested (12/12 trade-ticket + 731 non-PW suite green), PR to open.**

Reviewed PR #374 (adds a "Low so far" override to the Morning trade ticket's ATR-from-LoD
gate). Author OOTO; owner asked me to make two recommended changes directly on top of the PR
branch. Built on `origin/claude/atr-lod-calculation-bug-9vqnwo` (the PR head) so the low-override
code is present, branch `claude/pr374-review-emuagm`.

**Change 1 — corrected low now flows to the `today_low` stop, not just the gate.** The PR wired
`lowOverride` only into the ATR-from-LoD gate; `ws4StopLevels`'s `today_low` option still read raw
`r.low`. That's the same fact ("today's low = X") feeding two consumers with different values —
and worse, `ws5BuildPayload` (the real `POST /positions` payload) used the raw low, so a corrected
low + "Today low" stop would have created a position with a stop the user had explicitly flagged
as wrong. Fix: `ws4StopLevels(r, dm, ts)` reads `today_low` through `ws4LowForCalc`; `ts` optional
(falls back to raw low). Updated all three call sites (`ws4Recompute`, `ws4TicketHtml`,
`ws5BuildPayload`).

**Change 2 — low override persists across reload.** Was in-memory (`state.morningTicket`), lost on
refresh. Added `ws4LoadLowOverride`/`ws4SaveLowOverride`/`ws4HydrateLow`, keyed
`ws4_low_override:<ticker>` storing `{date, value}` and gated on a date match at read time, so a
new trading day's fresh scrape is never shadowed by a stale correction (no key enumeration/cleanup
needed). Saved on every `oninput` (mirrors `ws4SaveRiskDefault`), hydrated once per session via a
`ts.lowHydrated` guard. `priceOverride` deliberately stays session-only — "price now" is a live
value the user re-checks, not a lasting factual fix.

**Deliberately NOT done:** ATR editable (owner decision — 14-day average, doesn't move intraday);
DATA-FINVIZ-LOW upstream investigation (owner not pursuing). No release triplet — internal
correctness fix to an existing tool input, same category as PR #374 itself.

**Tests:** 2 new Playwright tests in `tests/test_pwa_trade_ticket.py`
(`test_low_override_flows_to_today_low_stop_and_sizing`,
`test_low_override_persists_across_reload`). Added a `clear_storage=False` param to
`_open_morning_tab` so the persistence test survives a reload (the harness's init script clears
localStorage on every load otherwise). Verified in-sandbox via the pre-installed chromium-1234
(matched this session's playwright build — no symlink trick needed this time). Full 12/12
trade-ticket file green; 731 non-Playwright suite green.

**Next steps:** none blocking. If the owner wants the Today-low-stop correctness fix called out in
What's New, add a `releases.json`/`sw.js` triplet in a follow-up.

---
