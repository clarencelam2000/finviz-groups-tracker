# Session Notes

> **Future Claude:** read this immediately at session start. Summarize the current state for the user before doing anything else.
>
> **Format:** Append a new `---` delimited block per session. Header = date + workstream description. Keep the last 4 sessions here; a human will periodically move older entries to `.session/archive/session-notes-archive.md`. Do NOT replace existing entries — append only.
---


## 2026-09-11 — AI-WALLET-PWA: render spend.json at the bottom of the AI tab

**Status: safe to close.** Follow-up to 2026-09-10's AI-WALLET-CORE (backend spend accounting)
— this closes the PWA half deferred there (see that entry below).

**What landed (branch `claude/ai-spend-controls-render-bpyfrk`):**
- `docs/index.html`: `SPEND_URL` (`${BASE}/ai/spend.json`), `state.spendData`, `loadSpend()`
  (fetched alongside the other `loadAndRender()` calls, best-effort — never blocks the render),
  and `spendSectionHtml()` — a small card rendered at the bottom of `renderAI()`'s output in
  **all three** of its exit branches (`_noData`, "AI analysis not yet available", and the normal
  briefing-cards path), since the spend card is account-wide, not tied to whichever AI date is
  being browsed. Shows month-to-date $ vs. `SPEND_SOFT_BUDGET_USD` with a color-coded bar
  (emerald/amber/red), run counts, last-run model/outcome/cost, and an "Updated Xh ago" caption.
  Going over budget shows red + an explicit "a display ceiling only, nothing is blocked" note,
  matching `SPEND_SOFT_BUDGET_USD`'s own doc contract (scripts/CLAUDE.md, root CLAUDE.md § AI
  spend controls) — it was never meant to be an enforcement mechanism. A missing/failed
  `spend.json` fetch (repo hasn't run `generate_ai.py` since AI-WALLET landed, or a network
  hiccup) silently omits the section — never breaks the rest of the AI tab.
- Release triplet in the same PR: `docs/releases.json` (`2026.09.11`, tag `feature`, tab `ai`)
  + `docs/sw.js` (`CACHE` v99→v100).
- `docs/CLAUDE.md` new § "AI tab — spend card"; README.md § AI spend controls updated to note
  the render now exists.
- **4 new Playwright tests** (`tests/test_pwa_ai_spend.py`, added to the CI `--ignore=` list
  per `.claude/rules/branch-commit-discipline.md`): normal render (all fields present), the
  over-budget red-warning state, silent omission on a 404, and rendering inside the "AI analysis
  not yet available" empty state (using the small `tests/fixtures/ai/*.csv` fixtures to force a
  controlled fallback date with no AI JSON). All 4 pass.

**Real-browser verification, done in this cloud session (the thing 2026-09-10 flagged as
needing "a real-browser check not reliable in a cloud session"):** installed `playwright==1.44.0`
+ pytest fresh (not preinstalled here), used the pre-installed `/opt/pw-browsers/chromium-1194`
via the documented symlink trick
(`knowledge/investigations/playwright-cloud-session-testing.md`) to run the committed test suite
headlessly, AND — beyond what that doc's harness does — fetched the **real** `cdn.tailwindcss.com`
script via `curl` (reachable from the shell even though not from Chromium directly, per that
doc's Root Cause 2) and served it through `page.route()` instead of the usual empty-comment
stub, so the visual (not just DOM-text) rendering could actually be screenshotted and eyeballed:
confirmed card styling, budget-bar color states (green under-budget / red over-budget), and
layout consistency with the rest of the AI tab's cards. Screenshots were scratch-only, not
committed.

**Next:** `AI-WALLET-CONVICTION` (remove Conviction from the `pulse` call) is the one remaining
item from the 2026-09-10 AI-WALLET backlog — still open, not touched this session.

---

## 2026-09-10 — AI-WALLET: protect Gemini spend before free-trial credits expire

**Status: safe to close** for the wallet core (5 commits, pushed, PR opened — backend only,
fully tested). Two user-facing PWA items deliberately deferred + tracked (see below).

**Why:** owner's $300 GCP free-trial credits expire within ~24h; after that spend draws on a
$10/mo Gemini credit **shared with other projects**. Measured the real bill from Tier-2
captures (29 clean runs): ~11 calls/run × **3 runs/day**, ~7k prompt + ~2.6k visible-output +
**~21k billed _thinking_ tokens/run**. Thinking bills at the output rate, so on
`gemini-3.5-flash` (~$9/1M out) that's **~$14–17/mo — exceeds the shared $10 alone.** (My first
pass wrongly called it "trivial" using a placeholder output price 20× too low; corrected with
real pricing via web search + the captured token metadata.)

**What landed (branch `claude/amazing-wozniak-vc8hwi`):**
1. `GEMINI_MODEL` 3.5→**3.8 Flash** — durably cheaper output, much cheaper during intro window
   (through 2026-12-31). API-safe (we never used the `minimal` level 3.8 dropped).
2. **`THINKING_LEVEL="low"`** — the big lever (~85% of the bill was MEDIUM-default thinking).
   Applied every call via `_build_call_config`, defensively (degrades to default, not outage).
3. **`AI_DISABLED=1` kill switch**, **`MAX_API_CALLS_PER_RUN=25`** runaway guard
   (`RunawayGuardError`, exit 1), **`DEFAULT_MAX_OUTPUT_TOKENS=2048`** anti-truncation rail.
4. **Actual-cost accounting:** `_extract_usage` now captures `thoughts_token_count` +
   `cached_content_token_count` + full `usage_metadata.model_dump()` (field names confirmed by
   introspecting the installed `google-genai`, not docs). New **`scripts/ai_cost.py`** meter
   (date-aware pricing incl. the 2027-01-01 intro→standard cliff) — **reused by AI-NEXT**.
   Per-run tokens+`cost_usd` logged to `ai_run_log.jsonl`; `data/ai/spend.json` = month-to-date.
5. **Input-diff dedupe** (`_compute_input_signature`) kills the EOD backstop's redundant 3rd
   run (~33%); also covers non-trading-day re-fires. No separate trading-day guard (unreachable).
6. Docs in 3 places (README / scripts CLAUDE.md / root CLAUDE.md).

Tests: 856 pass (full non-Playwright suite). ai_cost: 13 tests; generate_ai: +12 new tests.

**Owner to handle (GCP console, out of repo — owner said they'd do it):** billing budget +
**hard API quota cap** (the only real server-side stop; budgets only alert). Confirmed: the
expiring credit is the $300 trial, NOT the $10/mo (which survives).

**Deferred + tracked (both are `index.html` / user-facing → need real-browser verification not
reliable in this cloud session; see SPRINT AI-WALLET):**
- **AI-WALLET-PWA**: render `spend.json` at the bottom of the AI tab (owner's explicit ask — no
  Python dashboard). Backend data already ships; render is a small follow-up + release triplet.
- **AI-WALLET-CONVICTION**: remove the Conviction half of the `pulse` call (owner finds it
  unused; modest token save). Backend prompt/parser + guarded PWA render deletion + release triplet.

**Next:** do both PWA items in a follow-up PR with a browser check, then gate the AI-NEXT
expansion (60–90 calls/day) behind thinking_level + Batch API + the spend surface.

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

---

## 2026-09-17 — Public agent feed (manifest + latest_signals) for external agents

**Status:** safe-to-close once PR is merged. Public-feed work landed; private-book access is deliberate fast-follow (see SPRINT § AGENT-FEED).

**Context:** Owner (Clarence) wants his Meta agent "Muse" to read the Finviz tracker directly. Repo is public (verified), so reads need no credentials. Decided against Muse consuming raw CSVs (118-col picks, generated delta schema → brittle coupling) in favor of a small, versioned JSON contract the pipeline publishes.

**What landed:**
- `scripts/build_signals.py` — pure builders `build_signals()` / `build_manifest()` + `main()`. Writes `data/api/manifest.json` (freshness, self-describing file index, history pointers, config constants: `atr_bands`, `lookback_windows`, `regime_short_long`) and `data/api/latest_signals.json` (`schema_version` 1.0, `as_of`, `session=eod`, `universe`, `emerging_leaders` top-15 by regime, `top_movers`/`fading` by `rank_ytd_delta_20d`, `picks` grouped by real `list_category` = leaders/all_green/accel/emerging/rs_new_high). ~80KB output.
- Wired into `collect.yml` (after evaluate_picks; existing `git add data/` catches it) and `collect_picks.yml` (after scrape; expanded `git add` to `data/picks/ data/api/` so the picks section is same-day fresh).
- `tests/test_build_signals.py` — 7 tests (shape/version, sort+NaN drop, movers/fading split, picks-by-category with raw ATR + NaN passthrough, manifest index/config, empty-frame safety, main() writes valid JSON). Full non-playwright suite green (123 passed).
- Docs: README § Agent feed (config table), CLAUDE.md scripts table + data/api/ in the data-structure block.

**Design decisions (grounded, not assumed):**
- **Privacy boundary:** feed is public-signals-only. Position/held/P&L status lives only in worker-positions D1 (HMAC bearer auth) and is NEVER written to a public file. Muse's proposed picks `status` field was dropped for this reason.
- **ATR band not persisted:** per data-pipeline.md, emit raw `atr_ext_50` + publish thresholds in manifest; consumer derives the band. Avoids stale labels on retune.
- **Two files, not one:** manifest = cheap freshness poll + index; signals = payload. Combining would drag the full payload on every freshness check.
- Corrected two of Muse's assumptions against real schema: `list_category` is selector buckets (not All/Focus), and `atr_ext_50` is per-ticker (not per-group).

**Next steps / deferred (SPRINT § AGENT-FEED):**
- Fast-follow: read-only authenticated endpoint on worker-positions (`GET /positions/summary`) + vaulted token for Muse, if/when owner wants position-aware answers. Security-sensitive; needs explicit sign-off. Prefer a narrow REST endpoint over handing Muse Cloudflare/wrangler account keys (blast-radius).
- Verify the two new workflow steps actually run green in Actions on the next scheduled collect (couldn't run collect.py in cloud — Cloudflare blocks it).
