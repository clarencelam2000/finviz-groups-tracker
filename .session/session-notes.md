# Session Notes

> **Future Claude:** read this immediately at session start. Summarize the current state for the user before doing anything else.
>
> **Format:** Append a new `---` delimited block per session. Header = date + workstream description. Keep the last 4 sessions here; a human will periodically move older entries to `.session/archive/session-notes-archive.md`. Do NOT replace existing entries — append only.

---

## 2026-09-04 — Chart-toggle tap target: 3+5 combo shipped (CHART-TAP-1)

**Status: safe to close** — implemented, verified, pushed, release triplet shipped.

Follow-through on the same-day mock session below: owner picked a **combination of options 3
(drawer handle) and 5 (edge rails)** rather than a single standalone mock. Before implementing,
surfaced a real conflict found while reading the code — on Picks, the outer card row already
owns tap-to-expand (`__togglePickRow`), so edge rails there can't live on the same row as that
handler. Asked 4 clarifying questions (Picks placement, rail visibility, whether to keep the old
button, Lookup scope); owner took the recommended answer on all four (rails inside the *expanded*
panel on Picks only, visible chevron cue on the rails, remove the old pill entirely, same
treatment on all 4 surfaces for consistency).

**What shipped:** New shared `chartToggleFooterHtml()` / `updateChartToggleFooterState()` helper
(`docs/index.html`, near `tradingViewChartHtml`) — a full-width "Show/Hide chart" drawer bar plus
two tall edge rails in one `.chart-toggle-wrap`, all three wired to the same toggle call. The
wrap's height includes the chart panel once open, so the rails run alongside the open chart too —
closing has the same reach as opening (confirmed via a real screenshot, not just code review).
Replaced the old ~34×24pt corner pill across **5** surfaces: Lookup, Picks, Morning, Positions,
and the Watchlist cards (found mid-implementation — same component, not in the original 4-surface
scope, included for consistency rather than leaving one surface with the old small button).

**Verification:** `test_pwa_picks_chart.py` and `TestPWALookupChart` (the two existing
chart-toggle-specific Playwright suites) pass **unmodified** — the old `.pick-chart-toggle`/
`.lookup-chart-toggle` classes and `data-*` attributes were carried forward onto the new bar
element on purpose, so no test changes were needed. Manually verified Morning/Positions/Watchlist
(no dedicated chart-toggle test coverage exists for those yet — pre-existing gap) via a scratch
Playwright script: rail clicks toggle correctly, bar label flips, and a real screenshot (with the
actual Tailwind CDN build, not the test suite's inert stub) confirms the visual layout. Ran the
full 8-file Playwright suite touching every surface this PR changed — 26 failures, all
`networkidle`/click-timeout flakes in tests this change never touches (lookback windows, intro
carousel, hub, momentum, deeplink cards, positions take-it flow); the positions failures were
double-checked via `git stash` and reproduce identically on the unmodified branch, confirming
they predate this change. Non-Playwright suite: 746 passed.

**Release surface:** `docs/releases.json` `2026.09.04` entry + `current` bump, `docs/sw.js`
`CACHE` v96→v97 — same PR, per the hard rule.

**Where it lives:** Same branch/PR as the earlier mock (`claude/trading-chart-expand-ux-lo9man`,
PR #398) — updated its description to describe the real implementation instead of a design-only
mock.

**Next steps:** None — CHART-TAP-1 is closed. If the owner wants Morning/Positions/Watchlist to
get the same dedicated Playwright chart-toggle coverage Picks/Lookup already have, that's a
separate, smaller follow-up (not blocking, not requested here).

---

## 2026-09-04 — Chart-toggle tap-target UX proposals + mock

**Status: safe to close** — design-only, no code shipped, nothing blocking.

**What landed:** Owner flagged the `Show chart ▾`/`Hide chart ▲` toggle on Lookup, Picks, Morning,
and Positions as a hard-to-hit mobile tap target (confirmed: `text-[0.65rem] px-2 py-1` pill,
roughly 34×24pt — under Apple's 44×44pt HIG minimum, tucked in one card corner). Proposed and
mocked five alternatives at real card scale (336pt width) using a live Picks row (`GH 86 ·
Guardant Health`) as content:
1. **Padded button** — same visible pill, bigger invisible hit-slop.
2. **Whole-row tap** — entire ticker header toggles the chart (Positions already half-does this
   on the ticker text alone).
3. **Drawer handle** — full-width strip replaces the corner pill.
4. **Live sparkline** — always-on mini chart doubles as the tap target.
5. **Edge rails** — the owner's original idea: tall tap strips down the card's left/right margins.

Each mock is interactive (tap to expand/collapse for real) with a dashed amber "redline" overlay
showing the actual tap-zone size, plus pros/cons. Recommended pairing: ship **02 (whole row)** as
the default everywhere charts appear, keep a padded chevron (01-style) as the visual "there's more
here" cue riding along for free.

**Where it lives:** Published as an Artifact for the owner to review (interactive, themed) — link
is in-conversation, not repeated here since Artifact URLs aren't durable across sessions. Source
committed to `planning/mocks/chart-toggle-redlines.html` per CLAUDE.md § Deliver mocks/visuals as
Artifacts (durable record). Tracked as `CHART-TAP-1` in `.session/SPRINT.md` Backlog — nothing
implemented yet, blocked on the owner's pick among the five.

**Next steps:** Owner picks an option (or a different pairing) → implement across all 4 surfaces
(`docs/index.html`) in one PR, add/update Playwright coverage per surface touched, ship the usual
release triplet (`releases.json` + `sw.js` cache bump) since this is user-facing.

---

## 2026-09-03 — Picks tab: group tap opens quick detail sheet + reason chips on group headers

**Status: safe to close** — implemented, verified functionally with a Playwright fixture-intercept
smoke test (headless Chromium, both changes confirmed rendering correctly, screenshots taken),
release surface updated in the same PR. Non-Playwright pytest suite green (797 passed — the 75
"failed" in a raw pytest run are the known sandbox-only Chromium revision mismatch documented in
`knowledge/investigations/playwright-cloud-session-testing.md` Root cause 1, not a regression).

**Two small UX asks from the owner (screenshots of the live PWA):**
1. Tapping a group name on the Picks tab (`data-pick-group-lookup` — both the All view's group
   headers and the Focus view's per-row group subtitle share this one click handler) used to
   `switchTab('lookup')` + `doGroupLookup()`, navigating away entirely. It now calls
   `openGroupPeek(name, 'industries', true)` instead — the same slide-up sheet the AI tab's
   inline group-name chips (`groupChipHtml()`) already open, reusing `groupPerfCard()` so there's
   only one renderer to keep in sync with the full Lookup tab. `openGroupPeek()` gained a third
   `expanded` param (default `false`, preserving the AI tab's existing compact-card behavior) so
   Picks can land the reader straight on the full breakdown (`_peekExpanded = true`) since they
   already picked this exact group — no second tap needed. "Full lookup ↗" inside the sheet still
   reaches the full Lookup tab for anyone who wants more than the peek.
2. Each group header in the Picks tab's All view now shows the same reason chips
   (Leaders/Emerging/Accel/RS New High/All Green, `CATEGORY_LABEL`/`CATEGORY_CHIP_CLS`) the
   Lookup tab's `renderLookupStage2()` already shows — built from a `groupCatMap` (group →
   Set of categories) derived from the same `catMap` the All view already groups by, so a group
   qualifying under several buckets today isn't only visible in the one category section it
   happens to render under.

**Release surface (hard rule, same PR):** `docs/releases.json` `2026.09.03` entry prepended,
`current` bumped; `docs/sw.js` `CACHE` bumped `v94` → `v95`.

**Next steps:** none outstanding — PR opened, ready for review.

---

## 2026-09-03 — Morning tab: sort, launch-ready filter, bucket collapse + mini-nav

**Status: safe to close** — implemented, verified functionally with a headless-Chromium
Playwright smoke run (executable_path workaround for this sandbox's Chromium revision mismatch
— see `knowledge/investigations/playwright-cloud-session-testing.md`), 5 new committed
Playwright tests added and passing (14/14 in `tests/test_pwa_morning.py`), non-Playwright
pytest suite green (746 passed), release surface updated in the same PR.

**Owner ask:** the Morning tab's picks-confirmation list only ever sorted by status bucket then
ticker A–Z — with most cards landing in the same "Setting up" bucket on a typical day, it read
as "just alphabetical." Worked through several rounds of design discussion (sort options, Focus
score reuse-vs-recompute, Launch-ready filter interaction, bucket-navigation options) before
building.

**What shipped** (`renderMorning()` and helpers in `docs/index.html`; full design writeup in
`docs/CLAUDE.md` § Morning tab):
1. **Sort pills** (`state.morningSort`): A–Z / **Focus score (default)** / ATR from LoD / Rel
   volume. Status-bucket grouping (Triggered → ... → No quote) is a constant — every sort mode
   only reorders *within* a bucket, via one shared null-safe comparator
   (`sortMorningEntries()`).
2. **Rel volume's Bucket/Global scope switch** (`state.morningSortScope`) — a conditional
   control that only appears when Rel volume is the active sort, rather than a permanent 5th
   pill, given how much chrome already stacks above the first card. Global flattens every
   status bucket into one cross-sectional "what's most active right now" list.
3. **Focus score chip + sort share ONE computation.** Pulled the candidate-pool derivation +
   `computeFocusScores()` call out of `ws4FocusScore()` into `focusScoreMapForPool()`, computed
   once per render into `_morningFocusMap`. The new card chip, the `'focus'` sort branch, and
   the existing trade-ticket footnote (`ws4TicketHtml`) all now read that one map — a future
   Focus-formula change updates all three for free instead of risking silent disagreement.
4. **Launch-ready filter** (`state.morningLaunchFilter`): All / Coiled / Extended / Overhead,
   on the same `computeLaunchReady()` label already shown as a card chip — independent axis
   from sort. Empties-to-zero shows filter-specific copy, not the generic no-picks-today state.
5. **Bucket collapse + sticky mini-nav** (`state.morningCollapsed`, a `Set`): each bucket header
   is a collapse toggle with a live count; the mini-nav (only rendered with >1 bucket) jumps to
   any bucket and **force-expands it first** if collapsed, so a jump never lands on an empty
   collapsed section. Starts fully expanded (no default-collapsed density change) — kept
   conservative since that wasn't explicitly asked for beyond "can we do both."

**Test-suite fallout from the new permanent "ATR from LoD" sort-pill label:** two existing
`test_pwa_morning.py` assertions counted exact occurrences of the literal string "ATR from
LoD" in the rendered HTML; the new sort pill (deliberately reusing that exact on-card copy
rather than inventing a different label) adds one more permanent occurrence per render. Updated
both expected counts (5→6, 2→3) with an inline comment explaining why — a real, expected
consequence of shipping the feature, not a bug.

**Pre-existing, unrelated finding (not fixed here, flagged as a separate task):**
`tests/test_pwa_positions.py` never stubs `**/sessions/pre_close_latest.csv` the way every
other Morning-adjacent test file does — 4 of its tests hang for the full 30s timeout in this
network-restricted sandbox (confirmed reproducible against the pre-change baseline via `git
stash`, so unrelated to this PR). Presumably invisible in CI/local dev with real network access
(an unstubbed request just resolves instead of hanging), per Root cause 2 in
`knowledge/investigations/playwright-cloud-session-testing.md`.

**Release surface (hard rule, same PR):** `docs/releases.json` `2026.09.03.1` entry prepended,
`current` bumped; `docs/sw.js` `CACHE` bumped `v95` → `v96`.

**Next steps:** none outstanding — PR opened, ready for review. Optional follow-up (not
blocking): add the missing pre-close stub to `test_pwa_positions.py`, and/or revisit whether
non-actionable buckets (Setting up/Invalidated/Failed breakout/No quote) should default-collapse
now that the toggle exists — deferred since it wasn't explicitly requested.

---

## 2026-09-02 — Volatility floor gate: hide near-dead stocks from Picks/Focus/Morning

**Status: safe to close — implemented, tested (740 non-PW + 5/5 new volatility-gate PWA green,
verified no regression in Focus/Morning/Lookup/methodology suites), PR to open.** Follow-up to
the B-5 "Pre-Power of 3" session above: owner spotted APGE (a buyout-frozen biotech) showing a
false "Coiled 2.8x" chip in the Volatility & setup section — its MAs and price were only
bunched because the stock barely moves at all (Vol W 0.07%, ATR/Price 0.26%), not because it's
a genuine coil.

**Investigation before building:** owner asked for a histogram of the live picks pool's
Volatility W % and ATR/Price % (published as an Artifact) before locking a threshold. Result:
both distributions are bimodal with a real gap between ~0.5% and ~1.2% — a 1.0% floor sits
exactly in that gap, catching only 5 tickers today (APGE, CRNX, OGN, TECH — all read as
halted/frozen biotech/spin-off names — plus STRC, which turned out to not even be a common
stock: "Strategy Inc - VR PRF PERPETUAL Series A", a perpetual preferred). Going to 1.5% would
have started cutting legitimate low-vol mega-caps (Novartis, JNJ, ADP, Shell, Enterprise
Products) that are just boring, not dead. Validated the choice wasn't an eyeball guess.

**Decision (owner, locked in-session):** `VOLATILITY_FLOOR_PCT = 1.0`. Gate fires on
`Volatility W % < 1.0 OR ATR/Price % < 1.0` (either trips it — both already-scraped columns,
no new CSV data). Hides the row from Picks (`passesPicksBaseFilter`), Focus (`isFocusEligible`
— duplicated at the predicate level since 2 of 3 call sites don't also call
`passesPicksBaseFilter`), and the Morning tab's picks-confirmation read (`renderMorning`'s
non-watchlist filter). Missing data (NaN) passes through — this only excludes what's
positively measured as too quiet, never an unknown. **Exempt: the user's own watchlist**
(explicit intent — those tickers ride the same morning scrape but the exclusion filter is
only applied to `list_category !== 'watchlist'` rows) **and a direct Lookup ticker search**
(explicit intent — shown with a new amber "Low volatility" warning chip in
`tickerContextHtml` instead of being hidden).

**Why client-side, not scrape-time (owner asked, both options presented):** `Volatility W`,
`Volatility M`, `ATR`, `Price` are already scraped/stored in picks.csv/picks_latest.csv and
morning.csv/morning_latest.csv — nothing new to collect. `.claude/rules/data-pipeline.md`
treats those CSVs as append-only, irreplaceable ground truth; a scrape-time drop would make a
wrongly-excluded (or later-retuned-threshold) row unrecoverable. Every existing per-stock
exclusion in this codebase (`passesPicksBaseFilter`'s market-cap/MA filter, `isFocusEligible`'s
liquidity gate, the Ariel match filter's own ATR%-band precedent) is already a client-side view
filter, not a scrape-time drop — followed that precedent.

**Shipped:** `VOLATILITY_FLOOR_PCT` constant + `atrPctOfPrice()`/`passesVolatilityFloor()`
helpers in `docs/index.html`, wired into `passesPicksBaseFilter`/`isFocusEligible`/
`renderMorning`, Lookup warning chip in `tickerContextHtml`/`findTickerPickInfo`.
`display_methodology.json` v6 (base_filter + focus_dq `volatility_floor` block).
`tests/test_picks_methodology.py` updated (v6 current, v5 preserved, 2 new sync tests).
New `tests/test_pwa_volatility_gate.py` (5 tests: Picks-All exclusion, Focus exclusion,
OR-logic via ATR-alone, Morning-card exclusion, Lookup warning-chip-not-hidden) — added to the
CI Playwright `--ignore=` list. README § Configurable parameters + `docs/CLAUDE.md` § PWA
display thresholds updated. Release surface: `releases.json` 2026.09.02.3 + `sw.js`
finviz-v93→v94, same PR per the hard rule.

**Not done / explicitly deferred:** no warning chip added to the Watchlist card itself (its
existing "Volatility & setup" section already shows raw Vol W/ATR values, so the data is
visible without a new badge) — flagged as an assumption in the PR description in case the
owner wants the same amber chip there too.

**Next steps:** open the PR, watch CI, then resume B-5b (the full undercut→reclaim Power-of-3
trigger) from the prior session's notes above, unless the owner redirects.

---

## 2026-09-02 — Effort B B-5: "Power of 3" MA-bunching chip + shown MA distances

**Status: safe to close — implemented, tested (742 non-PW + 11/11 picks PWA + 18/18 morning/watch
PWA green), PR to open.** Continues the compression/expansion workstream (planning doc + #378/#379);
A-2/B-6/A-3 (#390) merged last session. Owner picked B-5 next and gave a decisive spec correction.

**Owner spec (2026-09-02, locked in-session):** it's **"Power of 3"**, not "Rule of Three". Power
of 3 normally uses price/10/20/50 MAs — we don't scrape the 10MA so drop it, and the 200 isn't this
pattern's third line, so **price/20MA/50MA only**. The chip fires when all three sit inside a single
**2×ATR band** — a band the OWNER specified (domain authority per §4.0), which dissolves the
threshold tension: a binary chip is legit because the trader set the number, not me. "Values AND the
chip"; render on the shared seam (all card families).

**What landed:**
- **Pipeline (Sonnet subagent):** new 6th `METRICS_COLS` col `power_of_3` in
  `picks_metrics.compute_metrics_row` = `1 if spread(price,20MA$,50MA$) ≤ POWER_OF_3_ATR_MULT×ATR
  else 0`, NaN if any input missing — computed next to `stage2`, reusing its reconstructed MA
  prices. New constant `POWER_OF_3_ATR_MULT = 2.0` in `picks_config.py`, imported into
  picks_metrics (no cycle). `picks_columns()` 118→119. `ensure_picks_csv` migration backfilled
  picks.csv (13,395 rows) + picks_latest.csv (119 cols; power_of_3 138×'1' / 297×'0', no NaN in the
  latest slice). 5 new unit tests. 3-places doc'd (in-code + README § Configurable parameters +
  scripts/CLAUDE.md).
- **PWA (`docs/index.html`):** "MA bunching" sub-block added to the shared `volSetupSectionHtml`
  (A-2 seam) — a green "Power of 3" chip when `power_of_3==='1'` + the two SHOWN SMA % distances
  (Price vs 20MA / 50MA). **No PWA constant** — the flag is precomputed in the pipeline (single
  source of truth), the PWA just reads it (same pattern as `tight_range_7`). Reaches Picks +
  Morning + Watchlist + Ticket for free via B-6's existing `setupRowForCard` cross-ref (SMA/
  power_of_3 come from picks_latest, not the morning store — MAs barely move intraday); orphans
  self-hide. Placed last in the section (weakest confirmer, §5.3).
- **Release triplet:** `docs/releases.json` `2026.09.02.1` (feature, tab picks) + `current` bumped;
  `docs/sw.js` v91→v92.
- **Tests:** 2 new picks PWA tests (`test_power_of_3_chip_and_ma_distances`,
  `..._no_chip_when_not_bunched`); added `power_of_3` to `tests/fixtures/picks_latest.csv` (computed
  via the real `compute_metrics_row` — ANET bunched→'1', TESTBLK no-ATR→''). Verified live headless
  via the executable_path override (`/opt/pw-browsers/chromium-1194/chrome-linux/chrome`; pip
  playwright expected -1234, sandbox has -1194 — Root Cause 1 in the playwright-cloud investigation,
  NOT committed). picks file 11/11, morning+watch 18/18 (seam inheritance, no regression).

**Delegation:** pipeline half done by a Sonnet subagent (self-contained metric+migration+unit
tests+pipeline docs, ~125k tokens); PWA render/test/release/planning kept in the main loop.

**Amendment (2026-09-02, same PR #392, still unmerged) — relabel to "Pre-Power of 3" + show the
cluster spread %.** Owner shared the full Power-of-3 definition: it's a *sequence*
(bunched → undercut the cluster → **reclaim** the highest MA = the trigger), not a static state.
What B-5 ships is only step 1 (the tight cluster). Owner decision: **relabel the chip "Pre-Power of
3"** (honest — it's the coil precondition, not the trigger), keep the 2×ATR gate, and **also show
the classic MA-to-MA cluster spread %** (`|20MA$−50MA$|/price`, derived client-side from
Price/SMA20/SMA50 — no new column). The full undercut→reclaim trigger is a new next slice **B-5b**,
which composes on `pick_status.py`'s existing reclaim engine (`compute_reclaim`/`reclaim_refs`,
already an `ACTIONABLE_STATUS`). Changed: chip text + a `maSpreadStr` header value in
`volSetupSectionHtml`; the 2 picks PWA tests (assert "Pre-Power of 3" + "spread 2.25%" for ANET);
`releases.json` `2026.09.02.1` title/notes; planning §5.3/§12 (+ B-5b ⏳ row); docs/CLAUDE.md; SPRINT.
Re-verified: picks+morning+watch PWA **29/29** green (relabel is in the shared seam); JS parses;
ANET spread = 2.25% exact; `test_guide_releases` 5/5. The `power_of_3` **data column name is
unchanged** (it's the bunched fact) — only the user-facing label moved.

**Amendment 2 (2026-09-02, same PR #392) — moved power_of_3 OUT of the CSV to client-side + made
Morning/Watch real-time (owner review changes-requested).** Two correct owner findings: (1) SMA20/
SMA50 render off *last night's close* on Morning/Watch (setupRowForCard only overrode 4 B-1 cols),
and Finviz's SMA%-distance columns track the **live** price so they DO go stale intraday — my "MAs
barely move intraday" assumption was wrong, corrected on the record. (2) `power_of_3` never needed a
CSV column: it's a pure single-row function of already-stored Price/ATR/SMA20/SMA50 and is
**config-dependent** (POWER_OF_3_ATR_MULT), so persisting it as ground truth would silently drift if
the constant changed — exactly what the new `.claude/rules/data-pipeline.md` § Schema-changes rule
(#393, merged to default) forbids. **What I did:** reverted the pipeline change entirely
(`picks_metrics.py`/`picks_config.py` back to 5 METRICS_COLS / 118 cols; restored picks.csv,
picks_latest.csv, and the test fixture from default — no more 13k-row backfill, no more merge-
conflict surface); moved the chip to a **client-side** computation in `volSetupSectionHtml` (reads
Price/ATR/SMA20/SMA50, reconstructs the MA $ levels, fires the chip on the 2×ATR span);
`POWER_OF_3_ATR_MULT` is now a **PWA display constant** (docs/index.html), triple-documented in the
PWA tables. **Real-time fix:** added `Price`,`SMA20`,`SMA50`,`ATR` to `collect_morning.SETUP_COLUMNS`
(morning store) and to `_SETUP_FRESH_COLS` (PWA), so setupRowForCard overrides them with this-
morning's scrape → the chip + MA distances re-fire off fresh MA levels on Morning/Watch. B-5b (the
trigger) needs this same fresh-MA plumbing. Tests: reverted the 5 pipeline unit tests; the 2 PWA
tests now drive the chip via raw cols (bunched via ANET; not-bunched via `SMA50:30%`); extended
`test_build_status_rows_carries_setup_columns` for the 4 new cols. Re-verified: picks_metrics +
collect_picks + collect_morning 152 green; the 2 PWA power_of_3 tests green (client-computed); JS
parses. Also **synced first**: another Claude rebased the B-5 stack onto post-#391 default; I reset
local to origin/2ljelo before working.

**Next steps:** **B-5b** (the full undercut→reclaim Power-of-3 trigger — gate on B-5's bunched read,
detect undercut below the cluster low = min MA, fire on reclaim above the cluster high = max MA;
actionable *real-time* morning read, entry on reclaim / stop under undercut low; computed per-run in
`collect_morning`/`pick_status` and stored in the **session** store — a live status, NOT a persisted
historical fact, so it honors #393 by construction; reclaim is a fact so §4.0-clean; **verify the
reclaim-engine wiring before building**). Alternatively **B-4** (VCP-style contraction proxy from
B-2+B-3+52W; label "Contraction (VCP-style)", never "VCP detected", NOT "lower highs"). Remaining
tracked follow-ups (planning §12): orphan sparkline backfill from D1 `ticker_quotes` (§7.3 option-b),
projected vol/RVol (§5.5b, parked), filter-sort + "Triggers today" (§9), fuller card superset
(RSI/Perf/Avg$Vol/Earnings — #378). B-7/B-8 stay parked.

---

## 2026-09-02 — Effort A A-2 + B-6/A-3: compression "Volatility & setup" section on the Morning family

**Status: safe to close — implemented, tested, PR #390 open (ready).** Owner chose the strategic
A-2→B-6 lever this session (over the contained Picks-only B-4/B-5 slices). Two slices landed in one
PR because A-2 has no standalone value (it's the seam B-6 rides on).

**A-2 (shared card seam).** Extracted the "Volatility & setup" section (B-1 Vol W/M·RelVol·52W +
B-2 range tightening + B-3 volume dry-up) out of `renderPickRow` into one shared
`volSetupSectionHtml(r)` in `docs/index.html`. **Pure refactor — Picks card byte-identical** (its
9 PWA tests green). Returns `''` when a row has nothing → graceful degrade for morning orphans.
Fulfills §8's "shared-component seam before B metrics spread" + ordering rule #2.

**B-6 / A-3 (render on the Morning family).** New `setupRowForCard(ticker, freshRow)` assembles the
render row: base = `ws4FindPicksRow` cross-ref to `picks_latest` (B-2/B-3 trailing sparkline cols,
multi-day), with the B-1 raw cols (Vol W/M, Rel Volume, 52W High) overridden by this-morning's fresh
scrape-wide values from the morning store `r` / watch public read `pub` (those cols landed on the
morning store in A-1-IMPL / #384). Rendered in `morningCardBody` (all live statuses, after the metric
rows, before the ticket/CTA — context before action, matching the owner-approved mock) and
`watchCardHtml` (after `body`). **Trade ticket deliberately NOT rendered separately** — it lives
inside the morning card which already shows the section above it (a second render would duplicate).
Lookup Stage-2 already had it (reuses `renderPickRow`). Orphans with no picks history + no fresh
scrape show no section (graceful degrade §3).

**Owner interaction:** built a real-data before/after mock (`planning/mocks/b6-morning-volatility-setup.html`,
published as an Artifact) using the actual `volSetupSectionHtml` output on a real CAH morning card.
Owner approved ("wire it into the morning family"), then I implemented.

**Tests:** `test_pwa_morning.py` +2 (`test_volatility_setup_section_on_morning_card`, `..._hidden_for_orphan`)
and a `pre_close_latest.csv` stub added to that file's shared `_open_morning_tab` harness so the file
runs in the cloud sandbox (it was hanging on the unreachable domain — the documented Root Cause 2, not
a regression; now all 9 pass in-sandbox). `test_pwa_watchlist.py` +1 (`test_watch_card_shows_volatility_setup_section`,
9/9). `test_pwa_picks_atr_earnings.py` 9/9 (A-2 unchanged Picks card). Also rendered the real morning
card headlessly to confirm placement/values match the mock. Release triplet `2026.09.02` (feature, tab
morning) / `sw.js` v90→v91; `test_guide_releases.py` 5/5.

**Docs (3-places-style):** `docs/CLAUDE.md` § Morning tab new B-6 subsection; planning doc §12
(A-2/A-3/B-6 ✅ + progress log). No new configurable constant (reuses B-1/B-2/B-3 metrics).

**Next steps:** **B-5** (MA bunching / Rule-of-Three — the last *named* spine item still unbuilt) or
**B-4** (compose the VCP-style contraction proxy from B-2+B-3+52W). Both Picks-only, contained,
ephemeral-safe. Deferred/tracked (planning §12): orphan sparkline backfill from D1 `ticker_quotes`
(§7.3 option-b), projected vol/RVol (§5.5b), filter/sort + "Triggers today" list (§9). **Don't merge
#390 until the owner has eyeballed the live Morning tab** (or is comfortable from the mock) — CI's
Playwright jobs validate the morning/positions files that only hang in this sandbox.

---

## 2026-09-02 — PR #387 merge-conflict fix (picks.csv/picks_latest.csv)

**Status: safe to close.** PR #387 (B-3 relvol_spark) went `mergeable_state: dirty` because two
new picks runs (2026-08-31, 2026-09-01) landed on default while the PR was open, appending newer
rows to `data/picks/picks.csv`/`picks_latest.csv` without the PR's new `relvol_spark` column —
diverging whole-file content, not a line-level conflict.

**Fix:** merged default into the PR branch (`claude/volatility-compression-expansion-pcvzda`);
took default's `data/picks/picks.csv` + `picks_latest.csv` (theirs — the newer, larger append-only
dataset) over the PR's stale version, then re-ran `collect_picks.ensure_picks_csv()` against the
merged data to backfill `relvol_spark` (+ the other `TRAILING_COLS`) onto the new max-date
(2026-09-01) slice — same migration path the PR's `write_picks()` already exercises on every
scrape, so this is not a new mechanism. All other files (scripts, docs, other data CSVs) merged
clean with no conflicts. Verified: no `(date, list_category, ticker)` dupes, 118 cols matching in
both files, single max-date slice in `picks_latest.csv`, `pytest tests/ -q` with the CI ignore
list — 737 passed. Pushed to the PR's own branch (`d261c27`).

**Next steps:** none — just confirm PR #387 shows green/mergeable after GitHub recomputes
`mergeable_state` (was `unknown` immediately post-push).

---

## 2026-09-01 — Effort B B-3: "Volume dry-up" (RelVol trend sparkline) on Picks cards

**Status: safe to close — implemented, tested (737 non-PW green + PWA green), PR to open.**
Continues the compression/expansion workstream (planning doc + #378/#379). B-1 (#380), B-2 (#383),
A-1/A-1-IMPL (#384) merged.

**Decision — chose B-3 over the PR384 author's recommended A-2→B-6.** Reasoning surfaced to owner:
(1) B-3 matches the owner's re-stated first principle — the spine is *content* (Vol W/M, ATR, range
tightening, **volume behavior**, MA bunching); volume dry-up is the one signal the doc records the
owner naming as the strongest/cheapest VCP piece. A-2 adds zero new signal (pure plumbing).
(2) Ephemeral-safe: B-3 is a contained pipeline + single-card slice mirroring B-1/B-2 exactly,
shippable in one focused session; A-2 is a cross-card refactor whose worst failure is being left
half-extracted — better for a fresh session. (3) Ordering rule #2: Picks-only B slices are safe.
(4) Deferring B-6 costs ~nothing — B-6 propagates the whole "Volatility & setup" section at once
regardless of how many signals live in it, so landing B-3 first just makes the section more complete.

**What landed:**
- **Pipeline:** new 4th `TRAILING_COLS` col `relvol_spark` in `picks_config.py`;
  `picks_metrics.compute_trailing_setup` now also emits `row["relvol_spark"] = _series("Rel Volume")`
  — same trailing-window/dedup/graceful-degrade machinery as B-2's sparks, reusing `SPARK_WINDOW`
  (10) / `SPARK_MIN_BARS` (3). **No new constant, nothing thresholded** (doc §4.0 — a SHOWN trend).
  `picks_columns()` count 117→118 (4 trailing). No selector_version bump (deterministic transform).
  Ran `ensure_picks_csv` migration on real data: backfilled `relvol_spark` onto 487/535 picks_latest
  rows (blank where <3 bars); picks.csv header widened to 118 cols (older rows "").
- **PWA (`docs/index.html`):** `relvol_spark` read + a "Volume dry-up" sub-block under the B-1
  "Volatility & setup" section in `renderPickRow`, rendered via the existing `volSpark()`/
  `volSparkLast()` helpers (Rel volume · last bars, latest value labeled `×`). `hasVolDryup` gate
  hides it for names without a series. No new PWA threshold constant → no `display_methodology.json`
  bump needed.
- **Docs (3-places):** README § Configurable parameters (`SPARK_WINDOW` row now lists `relvol_spark`),
  scripts/CLAUDE.md (117→118 / 3→4 trailing, picks_metrics row), in-code comments in both scripts.
- **Release triplet:** `docs/releases.json` `2026.09.01` (feature, tab picks) + `current` bumped;
  `docs/sw.js` v89→v90.

**Tests (light per owner):** 1 new unit test `test_trailing_relvol_spark_series_and_degrade` in
`tests/test_picks_metrics.py` (series built oldest→newest + graceful-degrade blank under spark_min);
extended the existing B-2 PWA test `test_range_tightening_shows_flag_and_sparklines` to also assert
the "Volume dry-up" block + a 3rd sparkline polyline (ANET fixture now carries `relvol_spark`).
Verified: `test_picks_metrics.py` + `test_collect_picks.py` 102 passed; full non-Playwright suite
737 passed (was 736 + 1 new); PWA test green in-sandbox (chromium-1234 matched playwright 1.62 — no
symlink trick needed this session). The column-count asserts in `test_collect_picks.py` derive from
`TRAILING_COLS`, so they auto-adapted.

**Data note:** committed `picks.csv`/`picks_latest.csv` now carry `relvol_spark` (migration ran in
cloud — this is a pure derived-column backfill, no Finviz scrape). Live values refresh on the next
Actions picks run like any other trailing column.

**Next steps:** **A-2** — extract ONE shared card component from B-1's "Volatility & setup" layout
(now B-1+B-2+B-3) so B-6 rides one seam. Then **B-6** — render the section on the Morning/Lookup/
Ticket cards (B-1 raw cols fresh from the A-1 morning store; B-2/B-3 sparkline cols via cross-ref to
`picks_latest`). A-2 is the strategic lever that cashes in A-1 — recommend a fresh session for it
(cross-card refactor, wants uninterrupted context). Remaining Picks-only spine slices if preferred:
B-4 (compose VCP proxy from B-2+B-3+52W), B-5 (Rule-of-Three MA bunching).

---

## 2026-09-01 — Effort A A-1: decide morning data path (scrape-wide) + A-1-IMPL pipeline slice

**Status: safe to close — decision made + implemented, tested (736 non-PW green), PR to open.**
Continues the compression/expansion workstream (planning doc + #378/#379). B-1 (#380) and B-2
(#383) are merged. This session took **A-1** — the one gate that unblocks propagating B-1/B-2 to
the Morning/Lookup/Ticket family (B-6).

**A-1 verification (planning doc §7.3a, subagent-assisted):**
- Cross-ref orphan rate is **worse than the doc's ~15%**: measured on 2026-08-31 data, morning
  **33.6%** (42/125) and pre-close **21%** (21/100) of tickers are NOT in `picks_latest` (watchlist
  adds + setting-up names) → pure cross-ref leaves ~⅓ of morning cards blank on the volatility
  section, disproportionately the pre-open action surface.
- Scrape-wide's feared cost **does not materialize**: `collect_morning.fetch_ticker_quotes` `page.goto`
  count is driven by ticker count (batched ≤50, 20 rows/page), NOT column count — switching 9→84
  cols changes only the `c=` param. The 84-col `t=`-filtered scrape already runs in prod as
  `block="held"` (collect_held.py). So scrape-wide = 100% coverage + fresh values at ~zero extra
  Cloudflare exposure.
- **Owner greenlit scrape-wide.**

**A-1-IMPL (this session's shipped slice, `collect_morning.py`):**
- New `WIDE_SCRAPE_BLOCK = "held"`; the single `fetch_ticker_quotes` call site now passes it, so the
  live morning/pre_close run scrapes the 84-col block.
- New `SETUP_COLUMNS = ["RSI","Volatility W","Volatility M","Rel Volume","52W High"]`, appended to
  `STORE_COLUMNS` (superset-additive, write_store backfills "" on old rows). `build_status_rows`
  carries these through **verbatim from the scraped quote, keyed by Finviz label** (raw strings like
  "3.92%") for render symmetry with `picks_latest` — so B-6 can reuse B-1's render by the same keys.
- B-2's derived sparkline cols (`tight_range_7`, `range_atr_spark`, `atr_spark`) are NOT scraped —
  they'll reach the morning card via a client-side cross-ref to `picks_latest` (multi-day; last
  night's values are current enough; orphans have no picks history under any path).
- The narrow `morning` block stays in `screener_config.json` as documentation of the minimal status
  set (no longer used live).
- 3-places doc'd (in-code + README § Configurable parameters + scripts/CLAUDE.md § WS3). No release
  triplet — backend/pipeline change, no PWA copy yet.

**Tests (light, per owner):** 1 new unit test `test_build_status_rows_carries_setup_columns`
(full wide row passes through; a 9-col thin quote and an absent quote both yield blank setup cols,
never KeyError). Existing `set(r.keys()) == set(STORE_COLUMNS)` assertion auto-covers the schema
widening. `test_collect_morning.py` 50/50; full non-Playwright suite 736 green.

**Data note:** committed `morning_latest.csv`/`morning.csv` stay old-schema until the next Actions
morning run rewrites them (can't scrape Finviz from cloud — Cloudflare). No manual migration:
write_store rewrites with the full schema and backfills "". Setup columns will populate live on the
next real run.

**Next steps:** **A-2** — extract the shared card component (B-1's "Volatility & setup" layout as
the reference) so B-6 rides one seam instead of hand-adding to 3+ diverging paths. Then **B-6**
(render B-1 from the fresh morning store + B-2 via cross-ref on the Morning family). Alternative if
the owner prefers to keep the single-card spine moving: **B-3** (volume dry-up, Picks-only).

---

## 2026-08-31 — Effort B B-2: "Range tightening" (tightest-range flag + sparklines) on Picks cards

**Status: safe to close — implemented, tested, PR #383 open.** Continues the compression/expansion
workstream (planning doc + issues #378/#379); B-1 (PR #380) is merged. Owner picked B-2 next after
I laid out the reasoning (compression spine, unblocked, single-card so no Effort-A dependency).
Owner also made one call at a decision boundary: because `picks.csv` history is **gappy per-ticker**
(a name only gets a row on days its group was selected), a true consecutive-session NR7 can't be
guaranteed — owner chose **"honest-labeled over available bars"** (not strict NR7, not deferring).

**What landed:**
- **Pipeline (3 new `TRAILING_COLS`, additive superset migration).** `picks_config.py`:
  `tight_range_7`, `range_atr_spark`, `atr_spark` + constants `TIGHT_RANGE_WINDOW`=7 /
  `SPARK_WINDOW`=10 / `SPARK_MIN_BARS`=3 (triple-documented: in-code + README § Configurable
  parameters + scripts/CLAUDE.md). `picks_metrics.compute_trailing_setup(latest_rows, history_rows)`
  — pure, trailing-window over a ticker's **available** bars, **dedups same-date multi-bucket rows**
  to one bar/date (a ticker can appear under several `list_category` buckets on one date, same
  scrape). `tight_range_7` = 1 when today's raw H−L is the narrowest of the last 7 available bars
  (a FACT, doc §4.0); the two `*_spark` are pipe-joined shown-value series. Wired into
  `collect_picks.write_picks` (enrich latest slice **before** writing both files — latest_rows are
  refs into all_rows) and `ensure_picks_csv` backfill. **Populated only on the max-date
  picks_latest slice** the PWA reads; older picks.csv rows stay "" by design. Ran the migration on
  real data: 60 tightest-range flags, 379/468 sparklines populated, blanks where history is thin.
- **PWA (`docs/index.html`).** New `volSpark()` / `volSparkLast()` helpers + a "Range tightening"
  block inside the B-1 "Volatility & setup" section of `renderPickRow`: honest green
  "Tightest range · last 7 bars" flag when `tight_range_7==='1'` (never "NR7"), plus two mini SVG
  sparklines (Range/ATR and ATR $) with the latest value labeled. `hasTightening` gate hides the
  whole block for names with no series/flag (graceful degrade). No new PWA threshold constant.
- **Release triplet:** `docs/releases.json` `2026.08.31.1` (feature, tab picks) + `current` bumped;
  `docs/sw.js` v88→v89.

**Tests (kept light per owner):** 4 unit tests for `compute_trailing_setup` in
`tests/test_picks_metrics.py` (flag fires on narrowest / zero when a prior bar is tighter /
graceful-degrade under-window / same-date dedup) + 1 PWA test in
`tests/test_pwa_picks_atr_earnings.py` (already in CI `--ignore`) asserting the flag + 2 sparkline
polylines + no "NR7" claim. Added the 3 trailing cols to `tests/fixtures/picks_latest.csv` (ANET
populated). Verified: `test_picks_metrics.py` 43/43; `test_pwa_picks_atr_earnings.py` 9/9 via the
revision-symlink harness (`ln -sfn chromium-1194 chromium-1117`); full non-Playwright suite 734
passed. The 73 red PWA tests in a bare run are the known cloud-sandbox Chromium-1117 gap, not this
change.

**Next steps / decision for next session:** B-3 (volume dry-up — RelVol trend over a window, still
Picks-card-only, no A dependency) is the natural next compression slice. The bigger open lever is
**A-1** (the morning-card data-path decision: scrape-wide-84 vs cross-ref `picks_latest` ~85% + D1
orphan backfill ~15%) — it's the gate that unblocks propagating both B-1 and B-2 to the
Morning/Lookup/Ticket family (B-6, A-2/A-3). A-1 needs verification (scrape-time / Cloudflare
exposure / exact coverage) before a recommendation — worth surfacing to the owner as the next fork.

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
