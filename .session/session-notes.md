# Session Notes

> **Future Claude:** read this immediately at session start. Summarize the current state for the user before doing anything else.
>
> **Format:** Append a new `---` delimited block per session. Header = date + workstream description. Keep the last 4 sessions here; a human will periodically move older entries to `.session/archive/session-notes-archive.md`. Do NOT replace existing entries — append only.

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

---

## 2026-07-04 — Picks Phase B: global HoD toggle re-ranks the Focus list

**Status: LANDED on branch `claude/hod-price-basis-toggle-94xhj6`. SAFE TO CLOSE once PR is reviewed/merged.**

Implemented PICKS-3E-HOD-PHASE-B per `planning/picks-hod-price-basis-toggle.md` §6 — the tab-level
`[ Last | HoD ]` toggle that was the committed end goal of the HoD price-basis work (Phase A, the
per-card ephemeral toggle, shipped 2026-06-30). Phase B changes *which stocks appear at the top*,
not just what one expanded card displays.

**What landed** (all in `docs/index.html` — client-side only, no pipeline change, no new
constants — reuses `ATR_EXT_*`/`FOCUS_W_*` per plan §10):
- `state.picksBasis` (`'last'`|`'hod'`, default `'last'`) + a `[ Last | HoD ]` segmented control
  in the Picks tab header, next to the existing All/Focus toggle.
- `renderPicks()` now derives every displayed row via the zero-mutation spread overlay mandated
  by the plan — `{...r, ...deriveRiskMetrics(r, state.picksBasis)}` — **before** the Focus hard
  gate (`isFocusEligible`), `computeFocusScores`, the All-view ascending-atr_ext sort, and the
  pre-scored All-view badge map. This is the same `deriveRiskMetrics` pure function Phase A built
  (per the plan's explicit mandate that both phases share one engine) — no new formula code.
- Collapsed-row badges (`atrExt`/`isTrim`/`atrCls` in `renderPickRow`) update automatically with
  no extra code, since they read off whichever row object they're passed and now receive the
  derived row — confirmed with a dedicated test rather than just trusting the plan's note.
- Per-card toggle (Phase A) interaction per §6.3: a freshly-opened card now defaults to the
  *global* basis (`state.picksBasis`) instead of hardcoded `'last'`; collapsing a card with a
  local override now reverts to the global basis, not hardcoded `'last'`. The per-card toggle
  still works as a one-off peek independent of the global switch.
- `price_basis` GUIDE entry and its `knowledge/moaty-metrics.md` counterpart rewritten to
  describe both phases (Phase A section was previously the only content).
- 6 new Playwright tests appended to `tests/test_pwa_picks_hod.py` (new `TestPicksBasisToggleGlobal`
  class, own port 8184 to avoid colliding with the existing Phase A test class): header toggle
  renders/defaults to Last, a wide-bar name drops out of Focus once flipped to HoD (built the
  fixture math out by hand — Last atr_ext_50 ≈0.2 vs HoD ≈20.2, comfortably past
  `ATR_EXT_ACTIONABLE`=4.0), collapsed-badge text changes without expanding, a freshly-opened
  card defaults to the global basis, a per-card override reverts to the global basis (not Last)
  on collapse, and an All-view two-row sort-order flip under HoD. All 11 tests in the file pass
  (5 original Phase A + 6 new), confirming no Phase A regression.
- Release triplet: `docs/releases.json` `2026.07.04.1` (today already had a `2026.07.04` entry
  from the same-day Lookup Signal card PR, so this uses the `.1` same-day suffix), `sw.js`
  `finviz-v54` → `finviz-v55`.
- Docs: `planning/picks-hod-price-basis-toggle.md` status header marked Phase B shipped;
  `.session/SPRINT.md` PICKS-3E-HOD-PHASE-B moved to Done with full implementation notes.

**Verification:** full non-Playwright suite (545 tests) passes unchanged. New/updated Playwright
suite in `tests/test_pwa_picks_hod.py` (11 tests) passes standalone with
`playwright install chromium`. `tests/test_guide_releases.py` (GUIDE oneLiner/moaty-metrics.md
verbatim-sync anti-drift) and `tests/test_picks_methodology.py` (no drift — Phase B added no new
tunable constants) both pass.

**Next steps**: none outstanding. Push branch and open PR.

---

## 2026-07-10 — Dev-process audit (staff-engineer review)

**Status: COMPLETE. PR open. SAFE TO CLOSE.**

Full audit of dev process/standards vs. reality (CI workflows, tests, rules docs, git history),
exploration fanned out to 3 Sonnet subagents, findings verified before acting. Deliverable:
**`knowledge/dev-process-audit-2026-07-10.md`** — read it; it's the canonical record.

Landed on `claude/dreamy-lamport-awqdai`:
- Audit report + 6 new SPRINT backlog items (AUD-1…AUD-5, LB-FF1-RESIDUAL).
- Doc-rot fixes: ADR-005 duplicate renumbered → ADR-009 (ETF classification; refs updated in
  CLAUDE.md + worker/CLAUDE.md, renumber note in the ADR), stale 4-file Playwright ignore list
  in branch-commit-discipline.md updated to the real 8, data-pipeline.md's "LB-FF1 pending"
  claim corrected (shipped PR #110), CLAUDE.md "Retry 3x" ambiguity clarified (script-level only).

Headline open findings: (1) **branch hygiene failed** — 142 unmerged remote branches, ≥3 with
stranded session-notes commits; enable auto-delete-on-merge + one-time sweep (AUD-1). (2) **no
lint gate anywhere** — add ruff to tests.yml (AUD-3). (3) generate_ai.yml is a third data/
writer outside the `finviz-data-commit` concurrency group; collect.yml push lacks rebase (AUD-4).
(4) backfill.py + export_db.py are the only untested scripts (AUD-2). What's working well:
release-triplet 100% conformance, TODO discipline perfect, ADR/session-notes practices alive.

**Verification:** CI-equivalent non-Playwright suite passes (545 tests). Docs-only change.

**Next steps:** merge PR, then pick up AUD-1 (branch sweep) and AUD-3 (ruff) — both small.
