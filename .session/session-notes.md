# Session Notes

> **Future Claude:** read this immediately at session start. Summarize the current state for the user before doing anything else.
>
> **Format:** Append a new `---` delimited block per session. Header = date + workstream description. Keep the last 4 sessions here; a human will periodically move older entries to `.session/archive/session-notes-archive.md`. Do NOT replace existing entries — append only.
---


## 2026-09-06 — AI-NEXT-P0c structured-output spike run (real API, owner-authorized)

**Status: safe to close** — spike run complete, decision recorded, a validator bug it surfaced
is fixed and tested, follow-ups tracked as issue #416.

**What happened:** owner explicitly authorized the spend (stated they hold ~$260 in Google API
credit expiring within days; not independently verified which billing account the in-session
`GOOGLE_API_KEY` draws from, taken on the owner's word) to run the real `AI-NEXT-P0c` spike — 60
real `gemini-3.5-flash` calls through
`scripts/spike_structured_output.py --limit 60`, using the `GOOGLE_API_KEY`/`VERTEX_API_KEY`
found present in this cloud session (see prior session-notes entry). Ran to completion (~55 min
wall clock, unusually slow per-call latency — see below).

**Headline result:** raw harness output said 90% dropped / 3.3% first-try, selecting
**renderer-owned templates** (the >15%-drop-rate design: AI picks the situation, app writes the
sentence). **Before accepting that number, re-inspected the two "first-try" successes against
their raw output and found both were actually malformed** — the model had written the field id
directly into the response text (e.g. `{row.status}`) instead of a short name mapped through
`slots`, and a gap in our own validator's regex (`_SLOT_RE` didn't match dots) let it slip
through undetected. Fixed `_SLOT_RE` in `scripts/evidence_pack.py` to also recognize dotted
field ids as placeholders, added a regression test, verified against the two real raw responses
that they now correctly get rejected. Corrected true result: **0/60 clean first-try passes**, not
2/60. The renderer-design decision doesn't change (still far past the >15% cutoff either way),
but the corrected number matters for anyone reading this later. Full writeup:
`knowledge/investigations/ai-next-structured-output-spike.md` §4/§4.0/§6.

**Also found, independent of the drop rate:** median 141s/call, p90 289s — a naive serial
per-row loop over a 40-row morning session would take ~94 minutes, blowing the documented
≤10-minute budget regardless of which renderer design ships. Not root-caused (possibly SDK-level
retry-on-rate-limit rather than genuine model latency).

**Why the number might not be the model's ceiling:** the model got `cites` (a flat array) right
100% of the time and only failed the semantically-redundant `slots` object every time —
`RESPONSE_SCHEMA` doesn't structurally require `slots` to be non-empty, so nothing but prose
instructions asked for it. A schema restructure (e.g. `slots` as `{name, field}` pairs, same
shape as `cites`) followed by a small ~10-20 call confirmatory run might tell a different story.
Not run — flagged in issue #416, needs owner sign-off given API spend already used.

**Tracking:** `.session/SPRINT.md` `AI-NEXT-P0c` row marked Done with the corrected result;
issue #416 opened for the two follow-ups (schema-fix retest, latency budget). `AI-NEXT-P0b`/`P2a`
are now unblocked per the SPRINT ordering.

**Next steps:** owner decides whether the ~10-20 call confirmatory retest (issue #416, item 1) is
worth the remaining API credit before the expiry window closes; otherwise `AI-NEXT-P0b` (shared
renderer) is next in the SPRINT order.
---


## 2026-09-06 — PR #412 review, fix, and merge (AI-NEXT-P0a evidence pack)

**Status: safe to close** — PR #412 merged to default; fixes verified with tests; one unrelated
pre-existing failure filed as its own issue rather than scope-creeped into the PR.

**What landed:** Code review of PR #412 (`scripts/evidence_pack.py` — the AI-NEXT-P0a evidence
pack builder/registry/validator) surfaced two confirmed bugs, both fixed and pushed to the PR
branch before merge:
1. `setup_present` ORed together two Finviz field groups with different coverage-cliff start
   dates (RSI/Volatility/RelVol/52W High from 2026-09-01 vs SMA20/SMA50/ATR from 2026-09-03).
   During that 2-day gap this wrongly emitted the still-missing SMA fields as `null` instead of
   omitting them, and skipped the required caveat note — contradicting the omitted-vs-null
   contract the PR itself documents. Fixed by splitting into independent `rsi_block_present` /
   `sma_block_present` flags, each gating only its own fields.
2. The confidence-downgrade "field flagged in notes" check used a raw substring test, so the
   field id `change` matched inside the routine no-prior-read note's "...what changed.",
   forcing every `row.change` citation to `low` confidence on the common case of a ticker with
   no prior read. Fixed with a word-boundary regex match.

Both fixes have regression tests (`tests/test_evidence_pack.py`, +3 tests, 49 total). Full
non-Playwright suite green (795/795) both before and after merge. `--check-schema` and
`--dry-run` (the PR's own "owner should verify after merge" commands) both confirmed passing
against the merged default branch.

**CI:** the `test` job's pytest suite was green throughout. Its later `eval_ai.py --all` step
failed on `data/ai/debug/2026-09-04.json` (`'Leisure' in output but not in input_blocks`,
`industries.note`/`industries.rotation_map`) — confirmed pre-existing and unrelated to PR #412
by reproducing it identically on the base branch with none of the PR's changes applied. Filed
as **#414** rather than pulled into this PR's scope; needs someone to inspect that capture file
and decide if it's a genuine hallucination or an `eval_ai.py` false positive.

**Notable finding for the owner:** while checking whether PR #412's `AI-NEXT-P0c` spike
(`scripts/spike_structured_output.py --limit 60`, real Gemini calls) could run from this cloud
session, found `GOOGLE_API_KEY` and `VERTEX_API_KEY` already present as env vars here —
contradicting the PR's (and `CLAUDE.md`'s Playwright-derived) assumption that Vertex creds are
never available in a Claude Code cloud session. Deliberately did **not** spend against them:
P0c's result is a recorded, hard-to-reverse decision (it selects the AI renderer design and the
owner explicitly wanted to paste its output into a knowledge doc). Flagged to the owner directly
and noted in the `AI-NEXT-P0c` SPRINT row; needs the owner to confirm the key is meant for this
before anyone runs it.

**Next steps:** (1) owner decides whether to authorize running `AI-NEXT-P0c` from this
environment or run it themselves per the PR's original instructions; (2) someone looks at issue
#414's hallucination flag; (3) once P0c's drop-rate table lands, `AI-NEXT-P0b`/`P2a` unblock per
the SPRINT ordering.
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


## 2026-09-04 — Inline "+ Watch" quick-add (Picks / Morning-picks / Lookup / Watchlist edit-level)

**Status: safe to close** — implemented, functionally verified with 6 new Playwright tests
(headless Chromium via the revision-symlink harness) plus the full non-Playwright suite (746)
and the existing watchlist/manual-entry/picks-hod/morning Playwright suites (42), all green,
no regressions. Release surface updated in the same PR.

**What the owner asked for:** easier ways to add a ticker to the watchlist — one-click entry
points across the app that expand inline instead of jumping to the Positions tab. Talked
through candidate spots first (no impl) before building: confirmed scope was Picks tab rows,
Morning tab's Picks-subtab cards, and the Lookup tab's ticker result (every spot that already
shows a TradingView chart), plus fixing the Watchlist-subtab's "Edit level" kebab, which had
the exact same jump-away problem. Positions-tab position cards were explicitly scoped out
(ticker's already a live trade there — low value).

**Design, confirmed with the owner before building:** the existing `state.watchAdd` /
`watchAddHtml()` / `watchAddApi()` (Positions-tab-only collapsible) already did ticker+optional
level submission — the gap was only that it was mounted in one place and other call sites
(`watchEditLevel`) navigated away via `switchTab('positions')` instead of expanding in place.
Generalized it into `quickWatchButtonHtml()`/`quickWatchPanelHtml()`, mountable anywhere via a
`mountKey` (namespaced per call site: `qw_pick_<key>`, `qw_morning_<ticker>`,
`qw_lookup_<symbol>`, `qw_watch_<ticker>`), DOM-patched by id on open/close/save (same
discipline as `__togglePickChart`/`__toggleMorningChart` — no full re-render, no lost focus).

**Owner-specified interaction (asked directly, confirmed before building):** tapping "+ Watch"
on an unwatched ticker fires the add immediately (`watchAddApi({ticker})`) — the tap alone
persists it, no second tap required. The panel then opens showing a receipt plus the optional
level-of-interest form (Above/Below/20MA/50MA, same as the existing form); setting a level is a
second, independent POST to the same upsert-by-ticker endpoint. An already-watched ticker's
button instead reads "✓ Watching" and opens straight into the level editor (seeded from the
existing entry), with zero re-POST until Save. Signed-out tap shows an inline sign-in nudge, no
add attempted. Unlike the Positions-tab form's free-text ticker field (which debounces an FMP
resolve lookup), every quick-watch mount is handed an already-known ticker — no resolve call
and no ticker input in this UI, per the owner's own observation that it's "clear which company
it is" at all three new spots.

**Technical note:** Picks and Lookup never previously triggered `loadWatchlist()` (only
Morning/Positions tab renders did), so a signed-in user landing on Picks would have seen
"+ Watch" on every row even for already-watched tickers. Added `ensureWatchlistLoaded()`
(deduped via `state.watchlistLoading`), called once per `renderPicks()` pass and once when the
Lookup ticker card renders — Morning needed no change, its batch loader already fetches
`watchlistData`.

**Release surface (hard rule, same PR):** `docs/releases.json` `2026.09.04` entry prepended,
`current` bumped; `docs/sw.js` `CACHE` bumped `v96` → `v97`.

**Next steps:** none outstanding — PR opened, ready for review.
---


## 2026-09-04 — Fix: watchlist stuck on "Pending read" for tickers that also qualify as Focus picks

**Status: safe to close — investigated, fixed, tested, PR to open.** Owner report with two
screenshots: several watchlist tickers (ELV, HUM, GH) added ~a week earlier were still showing
"PENDING READ" / "Reference bar captured — first live read after the next scheduled check.",
and lacked the full card (Volatility & setup, ATR-from-LoD, etc.) that other watch tickers
(SPCX, BAX) had. Owner asked for a full investigation first, no fix, "don't bear load on
unconfirmed assumptions."

**Investigation (evidence-based, not inferred).** Ruled out the two previously-fixed failure
modes in this area (`WS5-8b-OPS` missing secrets; `WS-POSITIONS-STATUS` no_quote/
awaiting_first_read copy) since neither matched: the private `/watchlist` feed showed real
`prior_high`/`prior_low` (a bar exists) and the TTL was decrementing normally (`tickWatchlist()`
only decrements when a bar exists), so `has_history` was clearly `True` server-side. Read the
actual committed `data/picks/sessions/morning.csv` directly (ground truth, not assumption) and
found the real root cause: `collect_morning.py`'s `union_watch_levels()` — when a watch ticker
ALSO qualifies as a Focus pick that day — keeps the Focus pick's row and never writes a second
`list_category='watchlist'`-tagged row for that ticker/date (by design, for scrape-count
purposes: "the watch dup contributes nothing"). ELV/HUM/GH had all started also qualifying as
Focus picks (`accel`/`leaders` buckets) — GH had been a recurring pick since before it was even
added to the watchlist, so its watch card had likely NEVER shown a real status.
`docs/index.html`'s watch-card lookup (`findPub`/`pub`, 2 call sites) filtered strictly on
`m.list_category === 'watchlist'`, found nothing on those days, and fell into the
`awaitingFirstRead` fallback — even though the exact same `pick_status` engine had computed a
real classification, just filed under a different bucket tag. Confirmed with grep evidence
against the CSV (GH: never once tagged `watchlist`, always `leaders`/`rs_new_high`/`all_green`;
ELV/HUM: correctly `watchlist`-tagged 8/27–9/1, then flipped to `accel` from 9/2 onward and
stuck since).

**Options presented, owner chose A.** (A) Client-side: relax the watch-pub lookup to accept any
row for the ticker (fallback after preferring an exact `'watchlist'` tag) — the lookup is
always called for one already-known ticker, so this can't cross-match an unrelated ticker's
row. (B) Backend: a new `is_watchlist` flag column, orthogonal to `list_category`. Rejected B
because `data/picks/sessions/*.csv` is a ground-truth CSV under
`.claude/rules/data-pipeline.md`'s schema-change rule (owner sign-off + a written
can't-be-a-pure-function justification required before building) and the fix genuinely doesn't
need a new column — same "compute at render time, don't persist a config/attribution-dependent
fact" precedent as the `power_of_3`/`VOLATILITY_FLOOR_PCT` sessions.

**Shipped:** new shared `findWatchPub(ticker)` helper in `docs/index.html` (replaces 3
duplicated inline `list_category === 'watchlist'` filters: `renderWatchlistSection`'s active +
expired card maps, and `__toggleWatchGauge`), with an in-code comment naming why the fallback
exists so a future cleanup doesn't revert it back to the strict filter. `docs/CLAUDE.md` §
Watchlist merge-model bullet updated to describe the new lookup and the collision it works
around. New regression test `tests/test_pwa_watchlist.py::
test_watch_card_finds_real_status_under_a_picks_bucket_tag` — verified it actually fails
pre-fix (`git stash` on `docs/index.html` reproduces the exact reported symptom: "PENDING READ"
pill + "Reference bar captured…" copy) and passes post-fix. Release triplet: `releases.json`
`2026.09.04.2` (fix, tab morning) + `current` bumped; `sw.js` `finviz-v98` → `v99`.

**Verified:** `test_pwa_watchlist.py` 10/10 (new test included), `test_pwa_morning.py` +
`test_pwa_quick_watch.py` 20/20 (unaffected — different render paths), full non-Playwright
suite 746 passed, `test_guide_releases.py` 5/5 (release-surface sync). Playwright run via the
documented revision-symlink harness (`chromium-1194` → `chromium-1117`, cleaned up after).

**Next steps:** open the PR. Not addressed (out of scope, no separate tracked item needed —
the fix is complete as scoped): the underlying `union_watch_levels()` collision behavior
itself is unchanged and intentional (attribution still correctly favors the picks bucket for
that CSV's own purposes); this fix only restores the PWA's ability to find the real status
regardless of which bucket won.
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

## 2026-09-05 — AI/LLM integration proposal + picks-alpha methodology audit

**Status: don't close yet** — PR #400 open (design doc + SPRINT + investigation note), 6 issues
filed, proposal artifact still rendering. No code shipped; this is a design gate.

**What the owner asked for:** a big-picture proposal for integrating LLM features into the Picks,
Morning and Positions tabs (and possibly at top level), given that the AI tab hasn't been touched
since it shipped while those tabs accumulated most of the app's differentiating signal.

**Recon (3 parallel sonnet agents, all claims file:line-cited).** Headline finding:
`generate_ai.py` reads **only** `data/{sectors,industries}/{snapshots,deltas}.csv` (`:98-122`) —
zero awareness of picks, session stores, positions, or watchlist. 11 Gemini calls/run ×
~3 runs/day, `gemini-3.5-flash` on Vertex. Naming trap for future readers: the AI layer has a
`watchlist` *task*, but it emits sectors/industries to watch — **unrelated** to the app's personal
watchlist feature. Every explanatory string on Picks/Morning today is a hardcoded per-status
`_mNote()` lookup; the Positions tab has no prose at all.

**The methodology audit — the most important thing that happened this session.** I quoted
`evaluate_picks.py --report` as showing the selector is "negative at every horizon" and built a
product recommendation on it. The owner pushed back and demanded the methodology. Auditing it found
the headline overstated in three ways: (1) `excess_spy` is contaminated — SPY returned +3.93% over
the sample vs +1.48% for the median industry, so much of the spread is cap-weighting, not skill;
(2) `--report` has no significance test and forward windows overlap heavily — 39 h=10 dates over 62
sessions is **~6 independent windows**, and under a moving-block bootstrap three of four horizons
straddle zero; (3) it flips sign across sample halves (h=10: first half −1.25%, second half +0.16%).
What survives is the `leaders`/`emerging` opposite gradient — and that is a selector question, not
an AI one, and not actionable on one regime. **Explicitly not a short signal, and it says nothing
about the traded system**, since trigger/stop/management are entirely unmeasured. Full writeup:
`knowledge/investigations/picks-alpha-2026-09-05-significance-audit.md`. Lesson is the CLAUDE.md
one, again: I asserted an empirical claim before auditing the instrument that produced it.

**Issues filed so the findings aren't orphaned** (owner's explicit instruction — out of scope for
current work, worth a focused sprint later): #401 add moving-block bootstrap to `--report` (ref
impl in the issue), #402 `MIN_POWERED_DATES` counts dates not independent windows, #403 demote
`excess_spy`, #404 PICKS-4B ticker-level scoring now buildable (D1 `ticker_quotes` + `morning.csv`)
— **we currently cannot measure the traded system at all**, #405 leaders/emerging research spike
(explicitly not actionable yet), #406 AI doc drift (`ai-architecture-revamp.md` cites the wrong
model/task-count) + the lingering AI Studio auth branch.

**Owner decisions locked.** Private position data to Vertex: **yes**, same GCP project. Mandatory
never-empty "the catch": **yes**. Positions read: **on-demand tap**. Start point: **Morning tab**
(P0→P2) — owner confirmed it's the tab they open first.

**Three owner corrections folded into the doc.** (1) "Posture" (skeptical critic vs balanced
analyst) was the wrong axis — the app is *not* one-sidedly positive (low Focus score, `invalidated`,
extension bands, earnings badges are all negative signals), and a persona dial pre-decides the
conclusion. Replaced with two separable properties: counter-evidence is a required field, and
confidence is derived from evidence strength. Correct label is **evidence-complete**, not skeptical.
(2) The proposed blocking numeric-grounding gate was brittle — replaced with a **slot-filling**
design: the model emits a sentence template plus named slots, the renderer fills values from the
pack, so numbers are correct *by construction* and validation reduces to "does the field exist".
(3) Pre-chewing model inputs was a small-context-window habit — feed broadly, require field
citation, render "Behind this" from the **cited subset** so provenance doesn't become a data dump.

**Next steps.** Owner to review the proposal (artifact link in-conversation). If Morning-first is
confirmed, next session starts at `AI-NEXT-P0` (evidence-pack builder — generalize the existing
`serialize_*()` discipline into a typed versioned pack, no new UI) then `AI-NEXT-P2`. P0 is a
prerequisite for every other phase; P4 (Tier B worker route) gates P5–P7. Nothing in P0–P7 needs a
ground-truth CSV schema change.

**Later in the same session — tracking hardened at the owner's request.**

Owner's standing instruction going forward: *persist everything a cold session needs at every
boundary, and keep a running task list / tracking section in the main planning doc so documentation
doesn't scatter.* Acted on as follows.

- **Evidence-pack schema is now its own design pass** (owner's call, not folded into P0):
  `planning/ai-evidence-pack-schema.md`. It exists because three review decisions turned the pack
  into a contract: slot-filling needs a stable addressable namespace, Tier A (Python) and Tier B
  (JS) must emit identical structures, and citation-driven provenance must resolve a field id back
  to a human label at render time. **3 open questions in §6 are unanswered** — registry drift a hard
  error vs warning (recommend hard), `context` budget ceiling for the on-demand Positions tap
  (recommend soft cap + `notes` entry on truncation), and whether `confidence` renders (recommend
  not in v1).
- **Epic #408** groups the methodology work with an explicit priority order and dependency graph:
  #401 → #403 → #402 are one PR (same file, `scripts/evaluate_picks.py` reporting layer); #404
  (ticker-level truth) is independent and the long pole; #405 (leaders/emerging) is blocked on both
  plus an out-of-sample period that does not exist. #406 deliberately excluded — it's AI doc drift,
  not methodology. Each child issue carries a comment stating its rank and blockers, so a cold
  reader landing on any one of them sees the shape.
- **#409** filed for the `serialize_*()` pre-chewing retrofit on the *existing* AI tab — feeding it
  broadly is an improvement to what already ships, separable from the new-surface work.
- **`planning/README.md` rebuilt as the real navigation index** (it had rotted: 7 of ~35 files
  listed, all with dead branch names). Now maps content-type → directory, groups live docs by
  workstream, and keeps shipped/superseded in separate tables. **This is the file a cold session
  should open first after `CLAUDE.md` and these notes.**

**Cold-start pointer for the next session.** Read in this order: `CLAUDE.md` → these notes →
`planning/README.md` → `planning/ai-llm-integration-proposal.md` → `planning/ai-evidence-pack-schema.md`.
Owner decisions already locked: private data to Vertex **yes**; mandatory never-empty "catch"
**yes**; Positions read **on-demand tap**; start with **Morning** (P0 → P2); posture framing
replaced by *evidence-complete* (counter-evidence required, confidence derived from evidence
strength); numbers handled by **slot filling**, never written by the model; **feed context broadly**
but require field citation so the "Behind this" drawer renders only the cited subset. The
methodology epic is explicitly **not scheduled** — a later focused sprint.

**Immediate next action:** owner answers the 3 open questions in `ai-evidence-pack-schema.md` §6,
then `AI-NEXT-P0` (the builder + registry) is implementable with no further design work.
---

## 2026-09-06 — AI-NEXT staff review: docs locked, tasks decomposed, user stories

**Status: safe to close** — docs-only PR, no code. Design gate is now *passed*, not "awaiting".

**What the owner asked for:** staff-eng / product / team-lead review of the SDE2's
`planning/ai-llm-integration-proposal.md` and `planning/ai-evidence-pack-schema.md`, plus the
`AI-NEXT-*` SPRINT rows, so the rest of the team can pick the epic up cold. Recon was one Sonnet
Explore agent (file:line-cited) plus direct checks of the session stores, workflow triggers, SW
caching, and the Gemini call config.

**Findings that changed the docs** (full logs: proposal §8, schema §9):
- Both docs still carried *open questions the owner had already answered* (proposal §6 asked about
  "posture", which §3.0 had retired; SPRINT header said "blocked on 4 open questions"). Replaced
  with a 12-row locked-decisions table; a cold reader would have re-asked all of them.
- Proposal §4 still said "blocking numeric-grounding gate" one section after §2 replaced it with
  slot filling; the P4 SPRINT row repeated it. Fixed everywhere.
- **Biggest missed risk:** slot filling needs strict JSON output, and `planning/ai-tab-daily-note.md`
  records the repo *already tried* forced JSON schema mode on the AI tab and backed it out
  (JSON-inside-JSON, truncation). Today `_call_api` sets only `temperature`
  (`generate_ai.py:1093-1094`). Added a mandatory spike `AI-NEXT-P0c` with go/no-go thresholds
  (schema §3.2) and a fallback design (renderer-owned templates).
- Schema gaps an implementer hits on day one: pack granularity (draft example was one row; Morning
  is ~115 rows + a cross-row triage), how a pattern found in broad `context` gets cited (rule 2 as
  written made it un-provenanced), the "no bare digits" rule rejecting `20MA`/`52W`/`10:05`, no
  failure behaviour, `confidence` undefined. All added, with a concrete Morning pack built from the
  real 27-column store — which showed `earnings.days_to` does **not** exist on Morning.
- Tier boundary nuance verified: watchlist *tickers* are already public in `morning.csv`
  (`list_category=watchlist`, 14/114 rows on 09-04); only the level is private.
- Verified facts corrected: 11 calls × **2** runs/day (not ~33/day); `generate_ai.yml` cascades
  only off "Daily Snapshot", so Morning prose needs a **new** cascade; AI JSON is fetched via
  `BASE` (raw.githubusercontent) which `sw.js` bypasses — new files must go the same way.

**Owner decisions taken this session (AskUserQuestion):** Morning prose ≤10 min after each read
(new Tier A cascade); per-card prose only for actionable + status-changed rows; schema Q1 hard
error, Q2 soft cap on Tier B; **confidence renders** — owner leaning all states, staff recommended
`low`-only marker (silence convention), **variant still open, does not block P0**; **honesty chip
dropped** from the AI roadmap (deterministic chip later, noted on #404).

**What landed:** proposal + schema edits; `planning/ai-next-user-stories.md` (stories + AC per
task + definition of ready); SPRINT block rewritten — P0 split into P0a builder / P0c spike / P0b
renderer, P2 into P2a pipeline / P2b cards / P2c triage, P1 after P2, `AI-NEXT-RETRO` for #409;
`planning/README.md` index rows; comment on #404.

**Next steps:** (1) owner confirms the confidence-render variant (one line, non-blocking);
(2) team picks up `AI-NEXT-P0a` — everything it needs is in schema §2.4/§8 and US-P0a; (3) P0c
spike must run in GitHub Actions or locally (Vertex creds), not from Claude cloud.


## 2026-09-06 — AI-NEXT-P0a: evidence-pack builder, registry, validator (+ P0c entry point)

**Status: safe to close** — implemented, 46 new tests green, docs corrected, PR opened. Nothing
blocking. Next task (`AI-NEXT-P0c`) is owner-run, not cloud-runnable.

**Picked up from** the 2026-09-06 staff-review session below (docs locked, tasks decomposed).
P0a was the only AI-NEXT task with zero API/network dependency, so it's the one that can actually
be finished from a cloud session.

**Sequencing correction made in this PR.** SPRINT said P0c blocks P0b/P2 — but P0c itself needs
the P0a validator *and* Vertex creds, which per root `CLAUDE.md` cannot run from Claude Code
cloud. Real chain: **P0a (cloud) → owner runs P0c locally/Actions → P0b/P2 unblock.** P0a
therefore also ships the spike's entry point so running it is one command, not a build.

**Also corrected: "go/no-go" was a misleading label** and the owner (rightly) asked whether the
spike could kill the workstream. It cannot. Schema §3.2's three outcomes select a *renderer
design* — ≤5% batched slot filling, 5–15% per-row slot filling, >15% renderer-owned templates
(model returns `kind`+`cites`, app owns the wording). All three ship a cited, AI-selected read;
the worst case is the *safer* product. Renamed in schema §3.2, the SPRINT row, and the knowledge
note so nobody re-reads that risk into it.

**What landed**
- `scripts/evidence_pack.py` — `FIELD_REGISTRY` (hard error on unregistered id, per schema §6.1),
  `UNITS`/`DIGIT_LEXICON`/`SURFACE_KINDS`, `build_morning_card` + `build_morning_triage`,
  `canonical()`/`pack_hash()`, `prompt_parts()`, `validate()` (all four §3.1 rules + caps +
  confidence downgrade), `validate_with_retry()`, `--emit-schema`/`--check-schema`.
- `data/ai/pack_schema.json` — the shared registry (committed == generated, test-enforced).
- `tests/test_evidence_pack.py` — 46 tests. Test-writing delegated to a Sonnet subagent against a
  precise spec; I reviewed the output and spot-checked that the parity tests genuinely
  hand-compute their expected values rather than calling the module's own helpers (they do).
- `scripts/spike_structured_output.py` + `knowledge/investigations/ai-next-structured-output-spike.md`
  (methodology committed, results section awaiting the owner's run).
- Doc corrections: schema §2.4 / §3.2 / §3.3 / §6, `scripts/CLAUDE.md` new sections, SPRINT rows.

**Three schema §2.4 errors found by building against the real store** (all corrected in the doc,
all now documented in `scripts/CLAUDE.md` so the next reader doesn't re-hit them):
1. `SMA20`/`SMA50`/`52W High` are Finviz **percent strings**, not prices — so `sma20_dist` is the
   column, not a derivation. Only the ATR-extensions are derived, via the PWA's
   `ma$ = price/(1+pct/100)` reconstruction (`deriveRiskMetrics()`, `docs/index.html` ~4603).
2. **Two disagreeing ATRs per row** — lowercase `atr` (status-engine quote block) vs capital `ATR`
   (Finviz screener block), differing on **224 of 234** rows. MA-extension must use capital (chip
   parity); stop/trigger geometry must use lowercase (the ATR the stop was planned with). Mixing
   them yields a plausible-looking wrong number. `price`/`Price` happen to agree exactly — that
   near-miss is what makes the ATR trap easy to walk into.
3. **Coverage cliff:** `RSI`/`Volatility`/`RelVol`/`52W` from 2026-09-01; `Price`/`SMA20`/`SMA50`/
   `ATR` from 2026-09-03 only. Builder *omits* (not nulls) absent fields + adds a `notes` caveat —
   omitted means "never collected", null means "collected and empty", and the model is prompted
   on that difference.

**Owner decisions taken this session**
- **Schema §6 Q3 closed: render all three confidence states** (`high`/`medium`/`low`), not the
  staff-recommended `low`-only variant. P0b builds it that way. Staff dissent recorded in §3.3
  rather than argued: three markers add chrome and `medium` may become noise the eye skips — but
  it's a pure render change to walk back later, nothing downstream moves.
- **P0c corpus: mixed, cohort-split.** Full history back to 2026-08-10; drop rate reported
  separately for full-field rows (2026-09-03+, the cohort the thresholds are read against) and
  thin-field rows. Owner didn't want to wait ~2 weeks for depth, and 234 rows over 2 days is too
  narrow to hang a threshold on. Dry run confirms the corpus clears US-P0c AC1: 60 packs, 30/30
  cohort split, all six statuses, 37 status-changed.

**Verification.** 46/46 new tests pass. Full CI-equivalent suite: **774 passed, 110 failed** — all
110 confirmed **pre-existing and environmental**, verified by `git stash`-ing every change and
reproducing an identical count. Two distinct sandbox failure modes, not one: ~92 are the documented
Chromium-revision issue (`knowledge/investigations/playwright-cloud-session-testing.md`), and
**18 in `tests/test_collect_benchmark.py` are a broken `bs4` in this sandbox**
(`'BeautifulSoup' object has no attribute 'contents'`) — *not* Playwright, and not previously
documented. Worth knowing before someone reads a red suite here as a regression.

**Deferred, tracked (nothing left only in prose):** `AI-NEXT-P0c-BATCH` — the spike measures
per-row only; batched 5/10-row calls (US-P0c AC3) are deliberately deferred until the per-row
numbers show whether batching is needed at all.

**Next steps.** Owner runs the spike (`GOOGLE_GENAI_USE_VERTEXAI=true GOOGLE_API_KEY=... python3
scripts/spike_structured_output.py --limit 60`), pastes the printed table into §4 of the knowledge
note, and records the outcome in the `AI-NEXT-P0c` SPRINT row. That unblocks P0b (shared renderer)
and P2a (Morning pipeline). No release triplet in this PR — nothing user-visible ships yet.
