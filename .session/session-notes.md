# Session Notes

> **Future Claude:** read this immediately at session start. Summarize the current state for the user before doing anything else.
>
> **Format:** Append a new `---` delimited block per session. Header = date + workstream description. Keep the last 4 sessions here; a human will periodically move older entries to `.session/archive/session-notes-archive.md`. Do NOT replace existing entries — append only.

---

## 2026-07-02 — PR #178 rebased, reconciled, and landed (sector breadth bar + drill-down)

**Status: LANDED on this session's branch, PR open for review. SAFE TO CLOSE once PR merges.**

Follow-up to the same-day "found an abandoned draft PR" session below. VP approved proceeding
with the rebase-and-reconcile plan; this session executed it.

**What landed (branch `claude/pr178-rebase-reconcile-ziu90h`):**
- Cherry-picked PR #178's single commit (`ea0a6c2`) onto current default (166 commits ahead of
  where #178 branched). Resolved all 6 conflicting files.
- `.session/WORK_LOG.md` and `.session/session-notes.md`: took default's side, not PR #178's.
  WORK_LOG is now an archived stub (process changed since 2026-06-24 — do not resurrect the old
  entry). session-notes.md's stale "Current Status" line from 2026-06-24 was superseded by ~10
  sessions of real history since; re-inserting it would have been out of chronological order.
- `docs/releases.json` / `docs/sw.js`: kept default's history, prepended a fresh
  `2026.07.02.1` entry (today's date, current constants), bumped CACHE `v48` → `v49`.
- `docs/index.html` (the real conflict): default already had `computeSectorBreadth(delta,
  taxonomy, rankCol)` powering the Strength-tab table (shipped independently as `122a4d1` while
  #178 sat unmerged). #178 had its own same-named-but-different-signature `computeSectorBreadth
  (industryDelta, taxonomy)`. Renamed #178's version to `computeSectorTopHalfCounts()`, made it
  a thin wrapper around the existing 3-arg function (rankCol='rank_ytd'), and pointed
  `loadTaxonomyAndBreadth()` at the existing `loadTaxonomy()` instead of duplicating the fetch.
  Promoted the inlined `n/2` "top half" threshold to a named constant,
  `BREADTH_TOP_HALF_FRACTION` — documented in README.md and CLAUDE.md per the
  configurable-constants rule.

**Bug caught during reconciliation (not present in either original branch alone):** the merge
produced two `taxonomy:` keys in the PWA `state` object literal. JS silently keeps the last
duplicate key, so `taxonomy: null` was shadowed by `taxonomy: {}` — which made
`loadTaxonomy()`'s already-loaded guard true from page load, so the taxonomy JSON would never
have been fetched and the new breadth bar/drill-down would have silently stayed empty forever,
with zero console errors. Only caught because the merged build was smoke-tested end-to-end with
Playwright (fixture CSVs served locally, `docs/index.html` driven headlessly) before landing —
unit tests alone (566 non-Playwright tests, all green both before and after the fix) would not
have caught this, since nothing in `tests/` drives the PWA's actual data-load sequence for this
feature.

**Playwright environment note:** the pre-installed Chromium in this sandbox lives at
`/opt/pw-browsers/chromium-1194/chrome-linux/chrome`, not the `chromium-1117` path the pinned
`playwright==1.44.0` expects — matches the known gotcha in
`knowledge/investigations/playwright-cloud-session-testing.md`. Worked around locally with a
symlink for manual verification; did not touch the pinned version or `tests/` fixtures.

**Verification:**
- `python3 -m pytest tests/ --ignore=tests/test_functional_playwright.py -q` → 566 passed, 15
  failed (all pre-existing browser-launch failures unrelated to this change — same 15 fail on
  default before this branch).
- Manual Playwright smoke test (fixture CSVs, CDN scripts route-stubbed per the known
  `raw.githubusercontent.com`/CDN sandbox gotcha): Today-tab sector card shows `N/M ↑` breadth
  bar; tapping expands the industry drill-down with YTD perf + universe rank; Strength tab's
  independent breadth table (week/month/3mo/6mo toggle) still renders correctly, confirming no
  regression to the already-merged feature.

**Docs updated:** `README.md` § Configurable parameters, `CLAUDE.md` § PWA display thresholds
(both get the new `BREADTH_TOP_HALF_FRACTION` row), and
`planning/PLAN_sector_industry_hierarchy.md` (Phase 2 table + Files Changed table marked done,
new "Phase 2 landed" section added above the historical "Current State" note).

**Next steps:** open PR against default; VP smoke-test on a phone/mobile viewport recommended
before merge (this session verified via headless Playwright + fixture data, not a live device).
Un-started Phase 2 items C (Leaders & Laggards mini-list) and R (market-wide breadth gauge)
remain backlog. Phase 3 gate (feature D tab placement) still needs a VP decision — unrelated to
this PR, no action taken this session.

---

## 2026-07-02 — Resuming sector→industry hierarchy: found an abandoned draft PR with real work

**Status: PLAN DOC UPDATED. NO CODE CHANGES. SAFE TO CLOSE.**

VP asked to resume the sector→industry hierarchy workstream (paused 2026-06-25 for Picks).
This session was research + plan-doc maintenance only, no feature code touched.

**Branch hygiene note:** `claude/practical-mccarthy-i6ubme` (this session's designated branch)
had zero unique commits — everything on it was already merged into default via other PRs. Reset
it to `origin/claude/elegant-babbage-hlxnfy` (151 commits had landed since this branch was last
current, all Picks-workstream work) rather than trying to rebase nothing onto something.

**Key finding — draft PR #178 is a real, unmerged implementation of Phase 2:**
`claude/fervent-thompson-rlvfs1` (commit `ea0a6c2`, PR #178, still open/draft) implements
Features A (expand-in-place drill-down), B (Today-tab breadth bar), and F (rank within sector)
exactly per the VP's 2026-06-24 UX decisions recorded in the PR body. It was never merged before
the team pivoted to Picks and is now 177 commits behind default.

Dry-ran the merge in a scratch worktree (`git merge --no-commit --no-ff`, then cleaned up) to
check real severity, since GitHub's `mergeable_state: dirty` flag doesn't say how bad. Result:
6 files conflict — `.session/WORK_LOG.md`, `.session/session-notes.md`, `docs/index.html`,
`docs/releases.json`, `docs/sw.js`, and `planning/PLAN_sector_industry_hierarchy.md` (add/add,
because this session's edits and the abandoned branch both touched it). Five are mechanical.
`docs/index.html` has a genuine semantic conflict: a *different* sector-breadth feature
(`122a4d1`, "add sector breadth table to PWA Strength tab") shipped independently while PR #178
sat unmerged — both add their own taxonomy-loading + breadth-computation code under similar
names (`loadTaxonomy()` + 3-arg `computeSectorBreadth()` on default vs. PR #178's
`loadTaxonomyAndBreadth()` + 2-arg `computeSectorBreadth()`). They're complementary features
(Strength-tab table vs. Today-tab card bar+drilldown), not duplicates, but landing PR #178 means
reconciling into one taxonomy loader, not a blind textual merge.

**What I did to the plan doc (`planning/PLAN_sector_industry_hierarchy.md`):**
- Added a "⚠️ Current State" section up top documenting all of the above and recommending
  rebase-and-reconcile PR #178 (~1 session) rather than discarding or re-implementing.
- Updated the Phase 2 table to mark A/B/F as built-but-unmerged with pointers to PR #178.
- Marked the Phase 1 VP gate as passed and the Phase 2 gate as already decided.
- Folded in a separate plan-review pass (from an earlier conversation in this session) not yet
  applied to the doc: flagged the D3.js-in-vanilla-JS-PWA constraint on the Phase 4 (Feature H)
  gate, flagged Feature I's snapshot-vs-replay implementation ambiguity as a pre-code decision,
  noted Features A/D's tab-placement decisions are linked and should be made together, noted
  Feature E's schema change actually requires a full historical recompute (like PIPE-1), and
  added a TODO tag pointer for the deferred `finviz_sector` column idea.
- `.session/SPRINT.md` HIR section: added HIR-B (was missing entirely), updated HIR-A/HIR-F to
  point at PR #178 instead of reading as not-started, struck through the stale duplicate
  TASK-6B/INS-7 entries in the Data/Insight Features table that hadn't been marked done.

**Not done this session:** did not rebase or land PR #178, did not touch any code. That's the
recommended next step but is real engineering work (reconcile two taxonomy-loading paths in
`docs/index.html`, re-run Playwright verification, bump release triplet to current cache version
`finviz-v48` from the PR's stale `finviz-v30`) — a deliberate call to leave for a dedicated
session rather than rush inside a "get resituated" pass.

**Next session, in order:**
1. Decide whether to actually land PR #178 now (my recommendation) or keep prioritizing Picks —
   VP call.
2. If landing: `git checkout -B <new-branch> origin/claude/elegant-babbage-hlxnfy`, cherry-pick
   or manually reapply `ea0a6c2`'s `docs/index.html` changes, reconciling with the merged
   Strength-tab breadth code; regenerate the release triplet against current versions; verify
   live in a Playwright session before merging; close PR #178 once superseded.
3. Then continue Phase 2 with C (Leaders & Laggards) and R (market-wide breadth gauge), the two
   Phase 2 items that are genuinely un-started.

**Safe to close.**

---

## 2026-06-25 — Picks cron dispatcher plan (PICKS-2-CRON)

**Status: PLAN COMPLETE. IMPLEMENTATION READY FOR NEXT SESSION.**

Plan written and docs committed to `claude/picks-cloudflare-cron-f0t7fz`. Extend `finviz-cron-dispatcher` with a 4th cron `31 22 * * 1-5` (22:31 UTC = 6:31 PM EDT). Routes by `event.cron` — picks cron dispatches `collect_picks.yml`. GitHub cron retired from `collect_picks.yml` (50-page scrape too expensive to misfire). Healthchecks.io dead-man's-switch planned.

**VP action item:** create healthchecks.io monitor (period=24h, grace=2h) and add `PICKS_HEALTHCHECK_URL` as repo secret before implementation merges.

**Safe to close.** Next session: implementation (worker-cron/ + collect_picks.yml).

---

## 2026-06-30 — Phase A: HoD price-basis toggle for Picks risk panel

**Status: PHASE A COMPLETE. SAFE TO CLOSE. PR #205 open.**

What landed (all in one commit on `claude/hod-price-basis-toggle-phase-a-8o28by`):
- `docs/index.html` — 4 edits:
  1. `deriveRiskMetrics(row, basis)` pure JS function + `window.__buildRiskBasisContent(rowData, basis)`
  2. `renderPickRow` if-expandable block: `data-row-json` attribute, `[ Last | HoD ]` toggle buttons, `risk-basis-content-{key}` wrapper
  3. `__togglePickRow` resets basis on collapse; new `__setPickBasis(key, basis)` function
  4. GUIDE `price_basis` entry (verbatim-synced with moaty-metrics.md)
- `docs/releases.json` — v2026.06.30 entry; `current` bumped
- `docs/sw.js` — CACHE finviz-v35 → finviz-v36
- `knowledge/moaty-metrics.md` — `price_basis` section added
- `planning/picks-hod-price-basis-toggle.md` — status line updated to Phase A shipped
- `tests/fixtures/picks_latest.csv` — TESTHOD row added (Price=100, High=200, ATR=5 for trim→extended test)
- `tests/test_pwa_picks_hod.py` — 5 new Playwright tests (require chromium)
- `.session/SPRINT.md` — PICKS-3E done; PICKS-3E-HOD-PHASE-B tracking task added

531 non-Playwright tests pass. Playwright HoD tests require `playwright install chromium` to run.

Next for this workstream:
- **Phase B** (PICKS-3E-HOD-PHASE-B): global tab-level [ Last | HoD ] toggle that re-ranks the entire Focus list on HoD metrics. Design complete in `planning/picks-hod-price-basis-toggle.md` §4. Prerequisite: validate Phase A in prod first.
- **PICKS-3D polish**: true inside-day H/L (schema bump), fundamental floor, search/filter, sort toggles.

---

## 2026-06-30 — Charts deep-links (v=211 multi-ticker grid) + scroll retention

**Status: COMPLETE. PR open. SAFE TO CLOSE.**

User asked for Finviz's multi-ticker charts-grid URL (`screener?v=211&ft=3&t=A,B,C`) to be
surfaced anywhere the PWA shows a list of stocks. Scoped to Picks tab + Lookup Stage-2 section.

What landed (all on `claude/pensive-albattani-jm9k7q`):
- `docs/index.html`:
  - `buildChartsUrl(tickers)` — dedupes via `Set`, no cap (tickers are short; URL length is a
    non-issue), inlined next to `buildScreenerUrl()`.
  - "Charts ↗" links added in 4 places: per-group header in Picks All view (next to the
    "N names" count), tab-level "View all N charts in Finviz ↗" in both All and Focus views,
    and beside the existing Stage-2 screener button in the Lookup tab's Stage-2 section
    (only shown when the group has picks today).
  - Fixed 2 pre-existing internal-nav buttons that incorrectly used `↗` (the external-link
    convention) instead of `›` (the internal nav-to-Lookup convention used everywhere else in
    the app): the All-view per-group name button and the Focus/Lookup row group-subtitle button.
  - Scroll position retention: `state.scrollPos` (per-tab) + `state.restoreScrollOnRender` flag;
    saved in `switchTab()`, restored at the end of `render()`. Skips saving when leaving Picks
    from Focus view, since `switchTab` always resets `picksView` to `'all'` on re-entry (A4,
    PICKS-3B) — a saved Focus-view scroll position wouldn't match the All-view content shown
    on return.
- `docs/releases.json` — v2026.06.30.5 entry, tag "feature", tab "picks".
- `docs/sw.js` — CACHE finviz-v40 → finviz-v41.
- `.session/SPRINT.md` — PICKS-CHARTS marked done; new PICKS-STATE-PERSIST fast-follow task
  for the deferred scope (expanded-row state + All/Focus view retention — see below).

**Verification:** 531 non-Playwright tests pass unchanged. Manually verified the full feature
end-to-end with a real headless Chromium session (fixture-intercept pattern matching
`tests/test_pwa_picks_hod.py`) — confirmed dedup on both per-group and tab-level Charts links,
the `›`/`↗` convention fix, and scroll-position restore across a tab switch away-and-back.
No new automated Playwright tests added (none of the existing Picks/Lookup Playwright suites
run in this environment — pinned `playwright==1.44.0` expects browser revision 1117 but the
cloud session's pre-installed Chromium is revision 1194; this is a pre-existing environment gap,
not something introduced this session — see PICKS-3C-PLAYWRIGHT-GAP for the existing tracked gap).

**Deferred** (discussed with owner, explicit decision to split into a follow-up PR):
- Expanded risk-panel rows currently collapse on every Picks tab re-entry (full `innerHTML`
  rebuild loses panel state) — needs a persisted identity key per row.
- All/Focus view selection always resets to All on tab entry (A4, intentional prior design) —
  retaining it would reverse that decision and needs an explicit call before changing.
- Tracked as **PICKS-STATE-PERSIST** in SPRINT.md.

---

## 2026-06-30 — Charts link ordering + PICKS-STATE-PERSIST (A4 reversal) + Playwright knowledge doc

**Status: COMPLETE. PR open. SAFE TO CLOSE.**

Follow-up session after PR #216 merged. PR #216's branch was restarted from the latest default
per the amendment policy (`git checkout -B claude/pensive-albattani-jm9k7q origin/claude/elegant-babbage-hlxnfy`)
since amending a merged PR isn't possible.

Three things landed, three commits on `claude/pensive-albattani-jm9k7q`:

**1. Charts deep-link ordering fix + `&o=tickersfilter`** — owner noticed the All-view
tab-level Charts link's ticker order was effectively random (raw CSV/scrape row order). Traced
all 4 link sites:
- Per-group header + Lookup Stage-2: already ATR-extension ascending, matches what's rendered — no change.
- Focus tab-level: was a genuine bug — built from `candidates` *before* the `scored.sort(score desc)`
  ran, so it never matched the visible Focus list. Fixed to read from `scored`.
- All tab-level: switched from raw CSV order to a flatten of the same category → group →
  ATR-ascending order already used to render the list (not "Focus score desc" — most All-view
  stocks don't qualify for a Focus score at all, so that wouldn't generalize cleanly).
- Added `&o=tickersfilter` to `buildChartsUrl()` so Finviz actually renders the charts grid in
  the URL's ticker order instead of its own default sort.
- Release triplet v2026.06.30.6.

**2. PICKS-STATE-PERSIST — reverses A4 (explicit VP call)** — `state.picksExpanded` (Set of
stable `ticker_category` keys) persists which risk panels are open; `renderPickRow` checks it
to start a row pre-expanded; `__togglePickRow(key, expandKey)` updates the set. `switchTab()` no
longer forces `picksView` back to `'all'`. Because `renderPickRow` is shared between the Picks
tab and the Lookup Stage-2 section, expand-persistence applies to both for free — not scoped
to just the Picks tab as originally planned. A4's original rationale ("stale-Focus confusion on
data reload") is preserved as a `> Note` in `planning/stock-picks-from-leading-groups.md`, with
the reversal appended below it (not rewritten) — same treatment in the `state.picksView` code
comment, the All/Focus toggle HTML comment, and the PICKS-3B SPRINT.md entry (footnoted, not
edited). Release triplet v2026.06.30.7, `sw.js` → finviz-v42.

**3. `knowledge/investigations/playwright-cloud-session-testing.md`** — wrote up the debugging
from PR #216's verification work: pinned `playwright==1.44.0` expects Chromium revision 1117 but
this cloud session's pre-installed browser is revision 1194 (needs explicit `executable_path`);
CDN scripts and `raw.githubusercontent.com` aren't reachable directly from Chromium in this
sandbox even though `curl` reaches them fine (route-stub everything); and a sharp glob-pattern
gotcha — `page.route()` patterns need `**/` with a trailing slash as a segment boundary, `"**X"`
without it silently never matches. **Found and fixed the same bug in CLAUDE.md's own canonical
Playwright example** (`'**/raw.githubusercontent.com/**snapshots.csv'` → `'**/snapshots.csv'`).
Flagged but did **not** fix: `tests/test_pwa_picks_hod.py` may have the same broken pattern —
noted in the investigation doc for whoever's next in that file, not chased further to keep this
session scoped.

**Verification:** 531 non-Playwright tests pass. Both the ordering fix and the state-persistence
feature were verified end-to-end with a real headless Chromium session (the harness documented
in the new investigation doc) — confirmed `o=tickersfilter` present, Focus-view expand+collapse
persisting correctly across a tab switch away and back, and the All/Focus selection surviving
tab navigation.

**Next steps**: none outstanding from this session. `PICKS-STATE-PERSIST-LOOKUP` SPRINT entry
from the prior session was folded into the main PICKS-STATE-PERSIST entry once it became clear
the Lookup Stage-2 coverage was automatic, not a separate task.

---

## 2026-07-02 — Picks selector dedup fix + per-group page cap (SELECTOR_VERSION v2)

**Status: safe to close.** Two related, user-requested changes to the picks selector, spiked
against real `data/picks/picks.csv` + `deltas.csv` history before implementing.

**1. Selector dedup fix (`scripts/collect_picks.py`, ADR-007 amendment).** Confirmed via the
5 days of picks.csv on hand that dedup was costing 1–4 unique-group slots *every single day*
(e.g. REIT - Healthcare Facilities was tagged leaders+accel+rs_new_high on both 6/29 and 7/1) —
`select_groups()` filled emerging/accel/rs_new_high with `head(N)` from each bucket's own ranked
list without excluding groups a higher-priority bucket had already claimed, so a group's repeat
appearance silently starved a bucket of a genuinely-new candidate. User confirmed the multi-
category attribution (a group visibly tagged as *both* leader and accelerating) has been useful,
so the fix is additive rather than a straight skip: `add_bucket_with_backfill()` still tags a
group within a bucket's natural top-N regardless of dedup (attribution unchanged), but now
backfills past rank N — skipping already-selected groups without tagging them there — until N
*new* groups are added or the qualifying pool runs out. Leaders' own freshness-fill sub-bucket
already excluded the core 8 by construction, so it didn't need this. Bumped `SELECTOR_VERSION`
v1→v2 per ADR-007, prepended the v2 entry to `selector_versions.json`, froze v1's hash in
`test_published_entries_immutable`. Replayed against real 6/29 and 7/1 `deltas.csv` rows:
`unique_groups` went from 16→20 on both dates with attribution preserved (`total_rows` rose to
25/24 since backfilled groups still carry their natural-rank tag in whichever bucket they also
qualify for). New test: `test_backfill_past_natural_top_n_when_leader_dups_in`.

**2. Per-group page cap (`scripts/picks_config.py`).** `PAGE_CAP` 15→2 (40 names). This was a
1-line config change — `paginate_group()` already took `page_cap` as a parameter, nothing new to
build. Data check: across all 5 days of picks.csv, **only Biotechnology** ever exceeded 40 names
(consistently ~100/day); every other group observed stayed ≤34. The `wide` screener sorts
`-marketcap` desc, so the cap keeps the biggest/most-liquid names in an oversized group. Existing
`PAGE_CAP` was never actually binding before (max observed was ~6 pages for Biotech, well under
the old 15) — this is the first time it does anything. No `SELECTOR_VERSION` bump needed (doesn't
change *which* groups are selected, only scrape depth per group). Had to update 2 pagination unit
tests (`test_multi_page_until_short`, `test_exact_page_boundary_stops`) that relied on the old
`PAGE_CAP=15` default to pass an explicit higher `page_cap`/`max_pages` — they test the pagination
walk's own short-page-stop logic, not the configured cap value.

**Docs:** triple-documented per house rules — in-code comments (`picks_config.py`), README
§ Configurable parameters, CLAUDE.md § Picks pipeline (selector description + fetch-caps bullet).

**Verification:** `python3 -m pytest tests/test_collect_picks.py -q` → 34 passed. Full non-
Playwright suite (566 tests) passes; the ~40 Playwright-dependent failures in this environment
are pre-existing (missing Chromium executable, confirmed by stashing this diff and re-running on
base — same failures) and unrelated to this change.

**Next steps**: none outstanding. PR open for this branch, ready for review.

---

## 2026-07-04 — Lookup tab Signal card rework (v2)

**Status: LANDED on branch `claude/signal-card-lookup-improvements-7fxy3z`. SAFE TO CLOSE once PR is reviewed/merged.**

User asked to improve the Lookup tab's SIGNAL card — hadn't been touched since first-week
launch and had gotten "iffy"/misleading as the rest of the product grew. Did read-only
exploration first (per user's explicit request to plan before implementing), found the
scoring spine (`groupScore()`) was literally unchanged from `planning/PLAN_ticker_lookup.md`
(2026-06-14) — a 3-factor day-1 heuristic that predated `momentum_confirmed`, RS-vs-SPY
(`rs_score`/`rs_confirmed`, added 2026-06-21), `regime_short_long`, and the whole Picks/Focus
pipeline. Concrete bugs found: (1) score never used RS at all; (2) `GUIDE.metrics` tagged
`rs_score`/`rs_confirmed` for the `'lookup'` tab (driving the in-app Guide hub's filter chip)
but neither ever rendered anywhere on the actual tab; (3) the evidence text (`groupReasons()`)
used different thresholds than the score (`groupScore()`), so the "why" could silently disagree
with the verdict; (4) missing group data was scored as a fake neutral 0.5 and blended into the
average with no indication; (5) the card only ever judged group context, never the searched
stock's own Stage-2/Focus setup even though that's computed a few hundred lines later in the
same render pass; (6) zero test coverage existed for any of this.

**What landed** (all in `docs/index.html` — client-side only, no pipeline change):
- `groupScore()` → `groupSignal()`: factor-based composite (`momentum_confirmed` 0.30,
  `rs_confirmed` 0.30, short-window rank delta 0.15, `regime_short_long` 0.15, breadth 0.10).
  Missing factors are excluded and the remaining weights renormalized (same convention as
  `momentum_score`'s NaN handling) instead of injecting a fake neutral value. New
  `SIGNAL_WEIGHTS`/`SIGNAL_FAVORABLE`/`SIGNAL_CAUTION` constants, triple-documented (in-code +
  README + CLAUDE.md).
- Evidence lines (`topSignalReasons()`) now read directly off the same factor list that
  produced the score — can't disagree with the verdict anymore.
- Missing-data handling: one side missing → score from the other side alone + an explicit
  caveat line; both sides missing → new "NO SIGNAL" state instead of forcing MIXED.
- RS vs S&P (`rsChip`/`rsBeatsChip`, previously Today/vs-Market only) now renders on the
  Lookup group cards too.
- `lookupGlossary()` rewritten to generate from `GUIDE.metrics.filter(tabs.includes('lookup'))`
  instead of a separate hand-maintained array — permanently closes the drift class of bug (also
  added `'lookup'` to `sustained_strength`'s tabs since its one-liner explains the Rank Floor
  chip).
- New "This stock" block (`findTickerPickInfo()`/`tickerContextHtml()`): when the searched
  ticker is itself in today's Stage-2 picks, its category tags, ATR extension, earnings
  proximity, and Focus score now surface directly on the card. Silently absent when the ticker
  isn't in today's picks (matches the existing silence-is-no-signal convention).
- Copy moved off long-only, uniform-severity phrasing ("favorable context for a long entry")
  to context-only framing that scales with data quality.
- New `tests/test_pwa_lookup_signal.py` (8 Playwright tests, added to the `tests.yml` ignore
  list) — first coverage this card has ever had. All pass, including two that regression-guard
  the exact bugs fixed (evidence-matches-score, missing-data caveat vs fake-neutral).
- Docs: `CLAUDE.md`, `README.md`, `knowledge/moaty-metrics.md`,
  `planning/lookup-tab-improvements.md` (Phase 2 section), `.session/SPRINT.md` (`LOOK-SIG2`),
  release triplet (`releases.json` 2026.07.04 + `sw.js` CACHE v52→v53).

**Verification:** full non-Playwright suite (545 tests) passes; new Playwright suite (8 tests)
passes standalone with `playwright install chromium`.

**Next steps**: none outstanding. Push branch and open PR.
