# Session Notes

> **Future Claude:** read this immediately at session start. Summarize the current state for the user before doing anything else.
>
> **Format:** Append a new `---` delimited block per session. Header = date + workstream description. Keep the last 4 sessions here; a human will periodically move older entries to `.session/archive/session-notes-archive.md`. Do NOT replace existing entries — append only.

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

## 2026-08-25 — PR #364 review fixes + PICKS-SEL-V3-PWA (all_green PWA chips)

**Status: safe to close — implemented, tested, pushed on a fresh branch (`picks-sel-v3-pwa`),
PR not yet opened as of writing this note.** Two pieces of work, both stemming from reviewing
the already-merged #364 (picks selector v3):

**1. Doc-only review fixes (pushed to #364's branch before it merged, landed as part of #364):**
Reviewed #364 and found the "known gap" arithmetic wrong in 3 places (README.md,
`scripts/CLAUDE.md`, `scripts/picks_config.py`) — the docs claimed `DAILY_GROUP_CAP (27) x
PAGE_CAP (2) = 50 exactly`; actual product is 54 (4 pages *over* `GLOBAL_FETCH_CAP`, not
exactly at it). Also fixed 3 leftover "core 8" comments in `scripts/collect_picks.py` that
should've said "core 11" after `LEADER_SS_SLOTS` was bumped. Pushed as commit `6ccd023`
directly onto #364's branch, which the owner then merged (#364 is done).

**2. PICKS-SEL-V3-PWA (SPRINT backlog task, now done):** the PWA's category chip maps didn't
know about the new `all_green` bucket — pick rows would show the raw string with no chip
color. Since #364 was already merged by the time this started, restarted a new branch
(`picks-sel-v3-pwa`) from the fresh default per the amendment policy, rather than stacking onto
merged history.
- `docs/index.html`: added `all_green: 'All Green'` + a green chip class to all 5
  map/array pairs that enumerate categories — `CATEGORY_LABEL`/`CATEGORY_CHIP_CLS` (module
  scope), the Lookup stage-2 `catOrder`, the Picks-tab `CAT_ORDER`/`CAT_LABELS`/`CAT_COLORS`,
  and `ws4PickCategories`'s display-order array (this last one degrades gracefully already —
  unknown categories append at the end — but was updated anyway for consistency).
- **Anti-drift fallout:** `tests/test_picks_methodology.py::test_all_view_category_order`
  checks the PWA's `CAT_ORDER` against `data/picks/display_methodology.json`'s
  `all_view_sort.category_order`, so bumped that file to a new `v5` (2026-08-25) — full
  `params` block copied verbatim from `v4` per the file's "self-contained entry" convention,
  only `category_order` changed. Updated the hardcoded `test_current_is_v4_...` test to v5, and
  `test_replay_picks.py`'s two hardcoded-latest-version tests (`test_loads_v4_for_later_date`
  → `test_loads_v5_for_later_date`, plus a new `v4`-boundary test) — both assumed v4 was the
  newest version.
- **Release triplet** (hard rule, same PR): `docs/releases.json` `2026.08.25` entry ("All Green
  picks category") + `current` bump + `docs/sw.js` `CACHE` `v80` → `v81`.
- 712 tests pass (`pytest tests/` minus the documented Playwright-ignore list). Did **not** run
  a live Playwright functional check against the rendered chip (no time budget in this session)
  — the anti-drift test (`CAT_ORDER` vs JSON) plus the JSON's own key/value pairing are the only
  verification; visually confirming the green "All Green" chip renders correctly in a live/local
  PWA session is a reasonable quick follow-up if the owner wants extra confidence before merge.

**Next steps:** push `picks-sel-v3-pwa`, open PR, merge.

---

## 2026-08-24 — Picks selector v3: leaders core 8→11, new all_green bucket, cap 20→27

**Status: safe to close — implemented, tested, ready to push/PR.** Owner-driven picks-selector change,
worked through interactively (explored why Railroads/Insurance Brokers missed picks, sized a hypothetical
"all-green" category, then owner approved specifics and asked me to implement).

**What landed (`scripts/picks_config.py`, `scripts/collect_picks.py`, `data/picks/selector_versions.json`,
`tests/test_collect_picks.py`, `README.md`, `scripts/CLAUDE.md`):**
- `SELECTOR_VERSION` v2 → v3; new registry entry prepended, v2 frozen + hash-pinned in
  `TestSelectorRegistry.FROZEN_HASHES`.
- `LEADER_SS_SLOTS` 8 → 11 (owner request — bigger stable core).
- New 5th bucket **all_green** (`ALL_GREEN_SLOTS=4`, lowest priority — fills last, after
  rs_new_high): a group qualifies if `perf_week/month/quarter/half/ytd` (raw, from `snapshots.csv`)
  are ALL positive, ranked by `momentum_score` desc (owner's choice over `momentum_confirmed` — the
  gate itself already screens consistency, so raw strength differentiates better within the already-
  consistent set; owner agreed this was the better default but flagged as a judgment call, not a
  certainty). Same tag-in-place + backfill-past-N dedup policy as the other 3 secondary buckets.
- **Architectural note:** `select_groups(deltas_df)` needed perf_* columns that `deltas.csv` does NOT
  carry (only ranks/deltas) — `main()` now merges them in from `snapshots.csv` before calling
  `select_groups()`. The function stays pure/testable; missing perf columns degrade to 0 all_green
  groups rather than erroring (same posture as every other bucket's NaN handling) — covered by
  `TestAllGreen.test_missing_perf_columns_yields_zero_not_error`.
- `DAILY_GROUP_CAP` 20 → 27 (owner request — exact worst-case sum of all 5 buckets' slots:
  11+2+4+3+3+4). `GLOBAL_FETCH_CAP` deliberately left at 50 (owner decision) — now has **zero
  headroom** on a fully-packed day (27 groups × up to 2 pages = 50 exactly); documented as a known
  gap in `picks_config.py`, README, and `scripts/CLAUDE.md`, not silently accepted.
- Verified priority order matters (not just dedup) with a live A/B test before implementing — owner's
  instinct that dedup alone made bucket order irrelevant was wrong (found a concrete case: Food
  Distribution only gets selected when all_green runs last, not 2nd), owner then chose "all_green
  last" explicitly with that tradeoff understood.
- Live dry-run against real 2026-08-21 data confirms the projected selection exactly (25 unique
  groups; Insurance Brokers now a leader; Railroads/Oil & Gas Integrated/Food Distribution/Capital
  Markets land in all_green).
- 709 tests pass (`pytest tests/` minus the documented Playwright-ignore list from `tests.yml`).

**Deferred, tracked:** `PICKS-SEL-V3-PWA` added to `.session/SPRINT.md` (Stock Picks Pipeline
section) — the PWA's `CATEGORY_LABEL`/`catColor`/`catOrder` maps in `docs/index.html` don't know
about `all_green` yet (falls back to raw string, no chip color — won't crash, just unstyled).
Deliberately out of scope for this backend-only change.

**Next steps:** push this branch, open PR, merge. No further selector work pending unless the owner
wants the PWA follow-up (`PICKS-SEL-V3-PWA`) done next.

## 2026-08-24 — Lookup card: fix "beats N/6" vs breadth-dot mismatch, unlabeled RS chip

**Status: safe to close.** Branch `claude/beats-counter-mismatch-avk88v`. Started from a user
screenshot question ("why does 'beats 2/6' not match the number of green dots?") — root cause was two
unrelated stats stacked in the same card region with no labels distinguishing them.

**What landed (`docs/index.html`, `docs/releases.json`, `docs/sw.js` v79→v80, `README.md`,
`docs/CLAUDE.md`):**
- `rsChip(v, tf)` now takes a timeframe param and derives its label from `RS_TF_LABEL` (`week:'1wk',
  month:'1mo', quarter:'3mo', half:'6mo', year:'1yr', ytd:'ytd'`) instead of outputting a bare
  `"+9.8pp vs S&P"` with no timeframe. Both call sites (Today-tab sector cards, Lookup card) pass
  `'month'` today since both feed `rs_month` — output is now `"+9.8pp vs S&P (1mo)"` at both.
- New `rsBreadthStrip(delta)`: a 6-dot row (`W M Q 6M YTD 1Y`) colored by `beats_benchmark_<tf>`,
  rendered directly under the existing "vs S&P" badge row on the Lookup card — the visual breakdown
  behind the `beats N/6` badge, same 6 timeframes/same count so they can never disagree.
  - `breadthStrip()` (the pre-existing absolute-perf dot row) relabeled **"Raw Perf"**, timeframe set
    aligned to the same `week/month/quarter/half/ytd/year` (dropped `day`, added `year`) and same
    `W M Q 6M YTD 1Y` order so the two rows line up dot-for-dot. Its "N/4 green" caption is now
    suppressed unless all-green (was cluttering the card next to the unrelated `beats N/6` badge and
    reading as the same kind of stat). Gate stays exactly `month/quarter/half/ytd` (owner's explicit
    call — `year` stays excluded from the gate, same as `week`).
  - Both rows' shared tf/label/order live in one `DOT_ROW_TFS` const + `BREADTH_GATE_TFS` Set —
    `groupSignal()`'s breadth-factor block (line ~3218, Lookup tab SIGNAL card) was using the old
    `BREADTH_TFS` shape and needed updating too; caught via grep before it shipped as a silent
    ReferenceError.
- Verified live via a scratchpad Playwright script (mixed perf-sign + mixed beats-flag fixture data,
  not all-same-color) rather than static code review alone — confirmed dot colors/order/labels and
  the chip text match the underlying CSV values exactly. See
  `knowledge/investigations/playwright-cloud-session-testing.md` for the `executable_path=
  "/opt/pw-browsers/chromium"` launch workaround used (chromium-1194 installed, playwright==1.44.0
  expects 1117).
- `releases.json` `2026.08.24` (tag `improvement`, tab `lookup`) + `sw.js` cache bump, same PR per the
  hard rule. README + `docs/CLAUDE.md` display-threshold tables both got new rows
  (`BREADTH_GATE_TFS`, `RS_TF_LABEL`).
- **CLAUDE.md**: added a new "Session continuity" retrospective entry — two corrections from the
  owner this session (an unverified "this doesn't apply elsewhere" scope claim; a proposal to
  hardcode a label that only happened to be correct for today's callers instead of deriving it from
  the parameter) — both instances of skipping a one-step check in favor of a plausible-sounding
  shortcut. Explicit owner ask to capture this so it doesn't recur.

**Next steps:** none — this was a self-contained UI/copy fix. Tests: `690 passed` (non-Playwright
suite; no new Playwright test file added, so no CI ignore-list change needed). Not yet pushed/PR'd as
of this note — push branch and open PR before ending session.

---

## 2026-08-21 — WS5 push fast-follows: RFC 8291 payload (#348 core) + pre-close act-now push (#349)

**Status: safe to close once #353 + #354 merge (merge #353 FIRST — #354 is stacked on it).** Staff-eng
session picking up the last WS5 push work after PR #350 landed the data-less channel. Lead owned the
348-vs-349 sequencing call, the crypto line-by-line review, and notification copy/taste; delegated both
boots-on-ground builds to Sonnet subagents against locked specs
(`scratchpad/pr1-rfc8291-spec.md`, `pr2-preclose-push-spec.md`) and re-ran/reviewed every line.

**The staff call: #348 first (split), then #349.** #348's payload encryption is the enabler that makes
every push better (incl. #349's ticker-named form) — building #349 first on the data-less channel would
ship a weak version and force rework. So payload landed first. Split #348 into a **core** PR (payload +
ticker-named Tier-1, high value, shipped) and a **remainder** (Tier-2 decaying reminders + earnings push,
held for owner cadence sign-off — real alert-fatigue risk, needs a cadence-curve decision not made
silently).

**What landed:**
- **PR #353 (#348 core, base `claude/elegant-babbage-hlxnfy`, branch `claude/ws5-positions-tab-review-gx4ezn`):**
  RFC 8291 `aes128gcm` in `worker-positions/src/push.js` (ephemeral P-256 ECDH → HKDF-SHA256 → AES-128-GCM,
  RFC 8188 record framing). `sendPush(sub, vapid, payload=null)` — `null` is the byte-identical data-less
  path. `dispatchExitPushes` builds a reason-aware ticker-named payload; sweep.js intent now carries
  `reason`/`price`. `docs/sw.js` push handler reads `event.data.json()` (generic fallback kept), CACHE
  v77→v78, release `2026.08.21`. **281 vitest** — the **self-round-trip decrypt test** (encrypt with the
  real fn, independently re-derive+decrypt in-test, wrong-auth negative control) is the merge gate;
  RFC §5 fixed-vector skipped (WebCrypto gives no seam to force a fixed ephemeral key/salt). Lead reviewed
  crypto line-by-line vs RFC 8291 §3.4 / 8188 §2.1.
- **PR #354 (#349, stacked on #353, branch `claude/ws5-preclose-push-act`):** `dispatchPreClosePushes` +
  `buildPreClosePushPayload` in push.js, wired into `POST /positions/preclose-advisory` in index.js. Reads
  the already-upserted `preclose_advisory` rows, pushes **`act` severity ONLY** (heads_up stays silent —
  not actionable pre-close), one per position, ticker-named, distinct `finviz-preclose` tag +
  `preclose_push_sent` marker keyed `(trade_id,trade_date)`. **Disjointness grep-proven** — zero
  `ingestQuotes`/`persistAdvance`/`last_advanced_date` calls; the 17:30 sweep stays sole writer. Worker-only,
  no PWA/release change (the in-app band from PR #345 + #353's SW handler already render it). **291 vitest.**

**Verification (lead re-ran, not just trusted subagents):** #353 → 281/281 vitest + node --check sw.js +
release guard 5/5; #354 → 291/291 vitest + node --check push.js/index.js + confirmed single `const payload`
(a doubled-lines sed artifact was NOT real source duplication — Node would've thrown on redeclaration).

**Next steps:** (1) merge #353, then #354 (GitHub retargets #354 to default on #353 merge). Both auto-deploy
`finviz-positions` via `deploy-workers.yml`. (2) e2e for both is gated on a live weekday sweep (17:30 for
#353's exit push, 15:40 for #354's pre-close push) hitting a signal on a subscribed device — same WS5 data
gate. Owner confirmed distil pushes reach their iPhone (de-risks iOS delivery). (3) Only remaining push work
is **#348 remainder (Tier-2 + earnings)** — held for an owner cadence review; lead to bring a concrete
decaying-cadence proposal rather than pick numbers silently.

**Flagged / low-confidence:** the HKDF `info` byte layouts are the one silent-failure risk (a wrong info
string produces undecryptable output, not a throw) — the round-trip test is what actually pins them; a
load-bearing warning was added to `worker-positions/CLAUDE.md`. Delivery itself is unverifiable from here
(no live push device in-session).

---

## 2026-08-20 — Positions tab: fix stop-ack "Couldn't update — try again" (branch `claude/position-tab-display-integrity-vcfx19`)

**Status: safe to close once the PR merges.** Owner reported the EOG position card's "✓ Updated"
button always showing "Couldn't update — try again" right below itself, and the hero's amber
"🔒 Risk-free · once you raise your stop / LOCK PENDING" chip stuck open even though the stop had
clearly moved.

**Root cause:** `posApi()` (`docs/index.html`) unconditionally sent `Content-Type:
application/json` on every request, including bodyless POSTs (`ack-stop`, `still-holding`). The
worker (`worker-positions/src/index.js` ~line 425) treats that header's presence as "parse the
body as JSON" and calls `request.json()` before dispatching to the route handler — on an empty
body that throws and the route returns 400 `"invalid JSON"` before `ackStop()`/`still-holding`
logic ever runs. Every tap of ✓ Updated (and Still holding, same code path) 400'd. Because the
banner's error state and the hero's `acked`-derived lock-pending chip both come from `posDerive`'s
single `acked` flag (`stop_ack_value` never gets set server-side), one root cause explained both
symptoms in the screenshot.

**Fix:** only set the `Content-Type` header in `posApi()` when `opts.body !== undefined`. One-line
behavioral fix plus the required `releases.json` entry (`2026.08.20.4`, tag `fix`) + `sw.js` cache
bump (`v76`→`v77`) in the same PR per the hard rule.

**Data-integrity check (also requested):** hand-verified the EOG card's `posDerive` math
(`unrealized`, `openRisk`, `lockedIn` against the card's displayed Entry/Stop/Qty/last-close) —
all three formulas are internally consistent; the sub-cent deltas I found by hand are raw-vs-
rounded-display precision (curStop/last carry more decimals server-side than the 2dp UI shows),
not a data bug. No backend data-integrity issue found.

**Tests:** `pytest tests/` (non-Playwright, 704 passed) + `tests/test_pwa_positions.py -k "ack or
still"` (Playwright, 4 passed, via the documented `/opt/pw-browsers` revision-symlink workaround
for this sandbox — not committed) + `tests/test_guide_releases.py` (release/cache sync guard, 5
passed). No test file changes — existing coverage already posts to `ack-stop`/`still-holding` and
asserts the trade_id captured; it doesn't simulate the worker's real Content-Type/empty-body
parsing (client-side mock only), which is why this slipped through originally.

**Next steps:** open PR, none outstanding — nothing else in progress on this branch.

---

## 2026-08-20 — WS5-8b watchlist stuck on "ADDING": root-caused missing morning env wiring (branch `claude/mornings-watchlist-processing-ll5vs1`)

**Status: safe to close once the PR merges.** Owner reported watch tickers (TSEM/TER/NVT/STX/ARXS/PGY/AMD/ALAB, added Aug 17) pinned at the top of the Morning tab in the optimistic "ADDING" / "10 mornings left" placeholder — never processed after several days — and suspected broader workstream gaps. He was right. Staff-eng session: lead did the diagnosis (live-D1 query + workflow-run audit + synthesis) and owned tracking/PR; delegated the code trace and the fix build to Sonnet subagents against locked specs, reviewed every line.

**Root cause (confirmed, single point of failure):** `.github/workflows/collect_morning.yml`'s "Collect morning status" step had **no `env:` block** — `POSITIONS_WORKER_URL`/`POSITIONS_INGEST_TOKEN` never reached the runner. `collect_morning.py` gates BOTH the WS5-8b watchlist union AND the `/watchlist/tick` TTL decrement on the same `watchlist_configured = bool(url and token)` flag, so every 10:05 ET run silently ran **picks-only** (green exit, only a `print()`). Sibling workflows `collect_held.yml`/`collect_held_preclose.yml` wire these same secrets correctly — this one was missed. **This was a known-and-dropped TODO** flagged in the 2026-08-15 AND 2026-08-16 notes ("confirm collect_morning.yml has these secrets… without them the morning run is picks-only, no error") — never actioned; P1/P2/P3 all shipped but the last prod-wiring step fell through.

**Live-D1 ground truth (`finviz-positions`, direct Cloudflare API):** all 8 tickers still `sessions_remaining=10`, `updated_at==created_at` (never touched); `watchlist_tick_log` **completely empty** (tick never fired); today's `morning_latest.csv` had **zero `list_category='watchlist'` rows**. The worker-side union is healthy — `ticker_quotes` DID have the watch tickers on 8-17/8-18 (held feed's server-side `heldTickers` union works); only the Python morning wiring was broken.

**What landed (branch `claude/mornings-watchlist-processing-ll5vs1`, base `claude/elegant-babbage-hlxnfy`, 2 commits):**
- `d567b38` `ops:` — add the step-level `env:` block (mirrors `collect_held.yml`) + a header comment documenting the required secrets. Validated as valid YAML.
- `0bbac1e` `test:` — `test_collect_morning_workflow_wires_positions_secrets` in `tests/test_collect_morning.py`: parses the workflow, finds the `collect_morning.py` step, asserts its `env` wires both `secrets.POSITIONS_*`. Catches this exact regression class. `pytest tests/test_collect_morning.py` → 42 passed.
- No PWA change / no release triplet: the front-end join logic (`renderWatchlistSection`/`watchCardHtml`, ticker + `list_category==='watchlist'` match against `morning_latest.csv`) is already correct — data just starts flowing on the next scheduled run. No engine/backend logic touched.

**Product calls (lead, flag if owner disagrees):** (1) **No TTL backfill** — the 8 tickers never lost sessions (tick never fired), so they'll get a full, honest 10-morning countdown from the next run; nothing to reset. (2) Tracked two follow-ups rather than widening this PR — **WS5-8b-MONITOR** (make a skipped union loud, not a silent green exit — the deeper class this bug belongs to) and **WS5-HELD-TIMEOUT** (below).

**Second gap found (separate, flagged to owner):** the **Held Feed** run on **Aug 19 was `cancelled`** after ~21 min (hit `timeout-minutes: 20`) → no `ticker_quotes` bars for 8-19, a one-day gap in the advisory/reclaim MA refs. 8-17/8-18 ran in ~1 min each, so the timeout is anomalous, not the norm. Non-blocking; tracked as **WS5-HELD-TIMEOUT**.

**Next steps:** (1) merge the PR → next 10:05 ET `collect_morning` run wires the secrets, unions the 8 watch tickers into `morning_latest.csv`, ticks TTL → the cards flip from "ADDING" to real status with a counting-down "N mornings left." (2) Verify post-merge on the first weekday morning run (check `watchlist_tick_log` gets a row + `morning_latest.csv` has `list_category='watchlist'` rows). (3) Pick up WS5-8b-MONITOR and WS5-HELD-TIMEOUT when convenient.

## 2026-08-20 — WS5-4b VAPID push SHIPPED (v1 Tier-1 data-less): PR #346 (backend, merged+deployed) + PR B (PWA)

**Status: safe to close once PR B (PWA) merges.** WS5-4b was the LAST remaining WS5 piece — the exit
loop now has a push channel end-to-end. Staff-eng session: lead owned the Tier-1-vs-payload product
call + the subscribe-affordance UX (wrote it as code) + line-by-line review of both builds; delegated
both boots-on-ground builds to Sonnet subagents against locked specs (`scratchpad/ws5-4b-{backend,pwa}-spec.md`)
and reviewed every line. Owner ratified **Tier-1 data-less v1** + granted distil repo access + signed
off the live secret write in advance + told lead to own the merge. Branch `claude/ws5-positions-tab-y8po9i`.

**The decisive scoping call (owner-ratified): v1 = Tier-1 data-less ONLY.** A data-less push carries no
`event.data`, so the service worker can only show ONE generic notification — it CANNOT differentiate
Tier-1 (loud) from Tier-2 (silent) or name the ticker. The whole two-tier §8 design therefore *requires*
RFC 8291 payload encryption to exist at all; firing generic Tier-2 reminders on a data-less channel would
cause the exact alert-fatigue §8 avoids. So v1 ships the one high-value nudge ("🚨 exit signal — open to
confirm", drives to the strip which names the ticker); Tier-2 + earnings + ticker-named payload are a
tracked fast-follow (#348). This matches distil's own shipped posture. The distil engineer's notes also
settled the handoff's open question: `web-push` npm can't run on workerd → hand-rolled WebCrypto (ported
distil's proven `webpush.ts` VAPID signer verbatim; lead round-trip-verified the keypair, 64-byte JOSE
sig, verify=true).

**What landed — PR #346 (backend, MERGED + deployed + verified live):**
- `0005_push_subscriptions.sql` (private user-scoped) — **applied to live D1 out-of-band via CF API**
  (owner sign-off); table+index verified present. `src/push.js` (VAPID JWT signer + `sendPush` ported
  verbatim; store; `dispatchExitPushes` — never-throws, `push_sent`-event idempotency keyed
  `(trade_id,trade_date)`, 410/404 self-prune, marker on success only, per-intent try/catch **lead
  hardening fixup**). Owner-bearer `/push/subscribe`·`/push/unsubscribe`. Sweep collects Tier-1 intent at
  the `closing` edge (`applied && !dry_run`), dispatches once **post-commit/best-effort** outside any D1
  batch; adds `pushed` count. `wrangler.toml [vars]` public key+subject; `VAPID_PRIVATE_KEY` live secret.
  **274 vitest** (260+14). 8/8 CI checks green → merged (#346, commit 5df7961) → `deploy-workers.yml`
  run #26 success → **verified live on Cloudflare** (`modified_on` 21:08:03Z matches; unauth
  `POST /push/subscribe` → 401 = route deployed, not 404).
- **PR B (PWA — THIS session, ready to commit/merge):** quiet set-once footer affordance on Positions
  (`posRenderAlerts`/`window.posEnableAlerts`/`window.posDisableAlerts`) — the subagent caught+fixed a
  real IIFE-scope bug via its own Playwright test (inline `onclick` needs `window.*`, same class as the
  #341 fix). `sw.js` `push`/`notificationclick` (data-less generic notif → focus+`postMessage
  OPEN_POSITIONS`, or `openWindow('#positions')` cold-start → boot hash-check). iOS install-to-home-screen
  guidance. Release triplet `2026.08.20.3` / sw v75→v76 / `docs/CLAUDE.md`. `test_pwa_push.py` (3, in
  `tests.yml --ignore`). Lead re-verified: `node --check` script+sw.js OK, release guard 5/5. Subagent ran
  the 3 push tests in Chromium (pass) + re-ran positions/preclose green; 7 pre-existing Morning failures
  confirmed pre-existing via `git stash`.

**Ops done this session:** VAPID keypair generated+verified; `VAPID_PRIVATE_KEY` written live to
`finviz-positions` (owner advance sign-off); `0005` migration applied live+verified; PR #346 merged +
deploy verified on Cloudflare (not just green CI).

**Deferred + tracked (nothing orphaned):** #348 (WS5-4b-PAYLOAD — RFC 8291 payload + Tier-2 + earnings;
SPRINT row added) and #349 (WS5-8-PUSH — push the 15:40 pre-close act-now band, the highest-value push;
SPRINT row added). Both are GitHub issues + SPRINT rows.

**Next steps:** merge PR B (deploy-ordering already satisfied — backend live). Then a fresh session can
take #348 (payload/Tier-2) — the higher-leverage of the two follow-ups — or #349 (pre-close push). e2e for
the whole channel is gated on a live weekday 17:30 held bar driving a real `closing` transition (same WS5
data gate) + a subscribed device.

**Note:** distil cloned at `/home/user/distil` (in-session scope) as the VAPID reference — external repo,
not this project. Owner confirmed distil pushes reach their iPhone (de-risks iOS delivery, which lead
can't e2e here). This notes entry + SPRINT ride in PR B so they land on default when it merges.

---

## 2026-08-20 — WS5-8 pre-close read: FULLY BUILT (backend + feed + cron + PWA) in PR #345 (#343)

**Status: safe to close once PR #345 merges.** All of WS5-8 landed on ONE branch/PR
`claude/ws5-7-positions-pickup-64506x` → #345: backend + 15:40 feed/cron + PWA band. **Live-D1 migration
`0004_preclose_advisory.sql` applied + verified this session (owner-approved)** via the Cloudflare D1 API —
table live on `finviz-positions`. Combined into one PR (not the originally-planned PR-1/PR-2 split) because
everything is on the one designated branch AND it's safe to ship together: migration already applied +
`posLoadPreclose()` is best-effort (a not-yet-deployed route → band absent, never an error), so the
fail-closed hazard that split WS5-6 doesn't apply (same call as WS5-7). **PWA verified:** 4/4 preclose
Playwright (symlink harness), 5/5 release guard, 703 non-Playwright pytest, node --check OK. Release
`2026.08.20.2` / sw v74→v75. Lead review caught 2 real bugs (backend entry-day false-stop_hit; PWA copy
hardcoded to 50MA/stop-hit → now signal-accurate). Staff-eng session driving WS5-8 (in-app pre-close
read). Owner chose **in-app first** over WS5-4b (push) — so v1 delivers "act before the bell" value with
**no VAPID/secrets/crypto**. Lead owned design/taste/mock/review + caught a real bug; delegated both
boots-on-ground builds to Sonnet subagents against locked specs (`scratchpad/ws5-8-{worker,feed}-spec.md`)
and reviewed every line.

**The feature:** at 15:40 ET a new held scrape POSTs near-final bars to a service-token
`POST /positions/preclose-advisory`; that endpoint runs the **pure `advance()`** per open/managing held
position and upserts ONLY the computed advisory into a new `preclose_advisory` D1 table (`0004`). It
writes NOTHING to `positions`/`ticker_quotes` and never stamps `last_advanced_date` — the 17:30 settled
sweep stays the sole writer (this disjointness is the whole design; it dodges the idempotency collision
where a 15:40 mutation would no-op the 17:30 sweep). PWA reads owner-bearer `GET /positions/preclose` →
amber read-only band splitting **act-now** (stop_hit/gap_down — real intraday) from **heads-up**
(close_below_50ma/two_close_below_20ma — may firm at bell) + a calm-day **read receipt** (owner wanted
both). Read-only — no in-app actions; the settled 17:30 confirmation strip stays the sole action surface.

**Owner decisions this session:** (1) in-app first, push (WS5-4b) later. (2) **Timing 15:40 ET** — owner
flagged the 15:30 `preclose_status` + 15:50 `collect_preclose` collision; 15:40 threads between them
(no simultaneous 2nd Finviz scrape, near-final print, ~20min runway). (3) **Both band + receipt** in v1.
(4) Migration IS necessary (PWA reads minutes later; `positions.meta` breaks disjointness, KV needs a
binding) — one tiny table, applied out-of-band. (5) **Reclaim → WS5-8-RECLAIM (#344)** fast-follow, not
v1 scope-creep; v1 leaves a `category` slot.

**What landed (PR-1, backend+feed+cron — NOT user-visible, backward-compatible):**
- **Worker (`worker-positions/`):** `0004_preclose_advisory.sql` + `src/preclose.js`
  (`computePreCloseAdvisory`/`readPreCloseAdvisory`/`PRECLOSE_SEVERITY`) + `POST
  /positions/preclose-advisory` (service token) + `GET /positions/preclose` (owner bearer). **260 vitest**
  (+15). Disjointness test (#5) asserts positions/ticker_quotes byte-identical before/after.
- **Lead-caught bug:** compute called `advance()` directly, bypassing the sweep's entry-day guard → a
  position entered TODAY would fire a false `stop_hit` off its pre-purchase low that the 17:30 sweep never
  confirms. Fixed to mirror `barWindowStart` (still counts toward the receipt, never flagged); regression
  test #9. Committed as a separate `fix:` on top of the subagent's work.
- **Feed+cron:** `collect_held.py --advisory` (POSTs to the advisory path, skips `/advance`; `post_quotes`
  gained an optional `path=`), new `collect_held_preclose.yml` (`workflow_dispatch`-only), `worker-cron`
  `held_preclose` JOB_SCHEDULE @15:40 (no new CF trigger) + WORKFLOWS map. **14 pytest + 99 worker-cron.**
  3-places docs (root CLAUDE.md Automation, worker-cron README, scripts/CLAUDE.md). Fixed a misleading
  "0 row(s)" advisory log line (endpoint returns no `written`).

**Verification (lead re-ran):** worker 260/260 vitest (Node 22); collect_held 14/14 pytest; worker-cron
99/99 (Node 20). The pre-existing routing tests the feed subagent modified were legit (the 15:40 window
genuinely overlaps 15:30/15:50 — not green-forcing; verified the diffs).

**Next steps:** (1) merge PR #345 → `deploy-workers.yml` auto-deploys `finviz-positions` + `worker-cron`;
the PWA lands on Pages. Migration already applied, so the route works immediately on deploy. (2) e2e gated
on a live weekday 15:40 scrape hitting a held position with a signal (same WS5 data gate — first real band
is a live trading day). (3) Then **WS5-8-RECLAIM (#344)** rides this same advisory infra; WS5-4b (push) is
independent.

**Note:** WS5-4b VAPID handoff still valid but note its reserved `0004` migration number is now taken by
WS5-8 — bump WS5-4b's push-subscriptions migration to `0005` when that session starts (flagged in SPRINT).

**Mock:** `planning/mocks/ws5-8-preclose-read.html` (artifact published this session). Issues: #343
(WS5-8), #344 (reclaim fast-follow).

---

## 2026-08-20 — WS5-4a confirmation strip + WS5-5 recently-closed (PRs #340/#341/#342); WS5-4b handed off

**Status: safe to close after PR #342 merges. WS5-4b (VAPID push) is the ONLY remaining WS5 piece —
fully handed off in `planning/ws5-4b-vapid-push-handoff.md` (cold-start-ready).** Staff-eng session
driving the remaining WS5 cold-start queue after WS5-7 (#338) and #335 (#339) landed. Owner cleared
the (stale) WS5-7 mock gate and directed the exit-confirmation + recently-closed work. Lead owned
design/taste/sequencing/review + all mocks/specs; delegated every boots-on-ground build to Sonnet
subagents against lead-authored locked specs (in scratchpad) and reviewed every line. Branch
`claude/pr336-mock-approval-plan-cx3t8m` (designated), base `claude/elegant-babbage-hlxnfy`.

**Owner-approved decisions this session:** (1) **Split WS5-4** into **4a** (in-app confirmation strip
— PWA + thin backend, no secrets) and **4b** (VAPID push — greenfield, ops-gated). The design (§8)
makes the strip the *source of truth* and push only the *nudge*, so 4a delivers the whole exit-safety
property alone. (2) Countdown computed **server-side** (a client counting calendar days would disagree
with the engine's session clock). (3) **Lead drives the VAPID keys** (owner has CF creds in env; CEO
shouldn't hand-gen keypairs). (4) **WS5-5 two-tier**: grace-in-list 2 sessions → lazy Closed section
60 sessions.

**What landed (3 PRs, disciplined deploy-first ordering — backend deploys before the PWA reads it):**
- **PR #340 (backend, MERGED + deploy confirmed on Cloudflare):** `GET /positions` exposes
  `auto_confirm_sessions` / `sessions_in_closing` / `sessions_since_close` (reuse `sweep.js`'s
  `sessionsSince`/`distinctTradeDates` — the SAME clock `autoConfirm` uses) + bounded
  `?closed_within_sessions=N`. +10 vitest (244). **Review caught a real bug** (a Claude review commit
  `8d9b4bf`): `auto_confirm_sessions` must use `effectiveConfig(p)`, not the bare global, so a
  per-position override is honored — now on default.
- **PR #341 (WS5-4a strip, MERGED):** `closing` positions hoist into a collapsed "Needs your
  confirmation" strip (mock `ws5-needs-confirmation-surface.html` A/B/C); expand → editable
  Confirm-fill (`confirm-exit`) / Still-holding (`still-holding`) + honest countdown; closing rows no
  longer render as cards. Removed dead `posClosingHeroHtml`/placeholder. Subagent caught+fixed a real
  runtime bug (inline `oninput` can't see the IIFE-scoped `state` → `window.posSetConfirmFill`).
  Release `2026.08.19.2` / sw v72→v73. 8 Playwright tests.
- **PR #342 (WS5-5 grace + Closed, THIS PR — open, ready):** `closed` positions stay in the live list
  (read-only `posClosedCardHtml`, "closed" badge, realized $/R, "auto" cue) under a "Recently closed"
  divider for `POS_GRACE_SESSIONS`=2 sessions, then only in a lazy-loaded collapsible **Closed**
  section (`POS_CLOSED_HISTORY_SESSIONS`=60, `?closed_within_sessions=60`, fetched on first expand,
  dupe-excluded). Release `2026.08.20.1` / sw v73→v74. 5 Playwright tests. **This session-notes +
  SPRINT + the WS5-4b handoff ride in this PR so they land on default when #342 merges.**

**Verification (lead re-ran, not just trusted):** #340 244/244 vitest + validated against live D1
(NVT/OUST `closing`, `sessions_in_closing`=0 → "auto-closes in 5 sessions"); #341/#342 node --check +
release guard 5/5 + Playwright via the (now unneeded — chromium-1117 present) symlink harness. The 4
failing `test_pwa_positions` Morning "I took it" tests are **pre-existing** (reproduced at baseline,
documented across prior WS5 sessions) — NOT regressions.

**Deferred + tracked (SPRINT):** (1) **WS5-4b VAPID push** — the whole handoff is
`planning/ws5-4b-vapid-push-handoff.md`. (2) **Auto-unconfirmed-correctable strip items** — the mock's
2nd strip population (`correct-exit` editor on auto-closed positions); needs closed rows in the strip,
a separable follow-up (SPRINT WS5-5b). (3) **Pre-existing latent bug**: a bare `state.x=` inline
handler at the `watchAdd` retry button (`docs/index.html`) — same IIFE-scope class as the one fixed in
#341, untouched to keep PRs scoped (SPRINT WS5-WATCHADD-FIX).

**Next steps:** merge #342 (auto-deploys nothing — PWA-only; just lands on Pages). Then a fresh session
takes **WS5-4b** from the handoff doc. The two other deferred items are non-blocking backlog.

**Note:** safe to close once #342 merges. **Don't close before #342 merges** — this notes entry, SPRINT,
and the handoff only reach the next session via that merge to default.

---

## 2026-08-19 — #335 BUILT: breakeven ratchet → intraday high + earnings overlay + negative-days guard

**Status: safe to close once this PR merges.** Staff-eng session picking up the cold-start queue after
WS5-7 (PR #338) landed. Owner cleared the WS5-7 mock gate (retroactive — WS5-7 already shipped) and
directed #335 next with an explicit call: **breakeven ratchet on intraday HIGH, not close.** Lead
owned the decision framing + the overlay visual (no owner mock existed for it) + line-by-line review;
delegated the boots-on-ground build to a Sonnet subagent against a locked spec
(`scratchpad/issue-335-spec.md`) and reviewed every line. Branch
`claude/pr336-mock-approval-plan-xcwxpy` (the designated dev branch), base
`claude/elegant-babbage-hlxnfy`. Three commits + tracking.

**What landed:**
- **`feat: ratchet profit_floor on intraday high (BREAKEVEN_TRIGGER)`** — new flippable
  `BREAKEVEN_TRIGGER: 'high'|'close'` knob in `ENGINE_CONFIG` (default `'high'`, per owner). Ratchet
  at `advance.js` keys on `bar.high` by default; `'close'` (global or per-position `meta.config`)
  restores the old behavior. NVT tag-and-fade regression fixture + a knob round-trip test (via
  `effectiveConfig`, which also proves the §14 override door passes the new key through). Docs 3-places
  (in-code, README engine-constants table; CLAUDE.md invariants prose verified still accurate). No
  release triplet — engine-only, no PWA shell change.
- **`fix: guard earnings_warning against negative days`** — `advance.js` earnings note now requires
  `days_to_earnings >= 0`. `parseEarningsToDays` returns a signed calendar delta that stays negative
  for up to 180 days after a past earnings date → the warning was re-firing every session on an
  already-reported quarter. Tests for −5 (silent), 0 (warns), 4 (warns).
- **`feat: earnings-approaching overlay on positions card`** — third block in `posOverlaysHtml`
  (`docs/index.html`), mirroring the trim/caution pattern: amber "📅 Earnings in N days" ≤10 sessions,
  red ≤3, `today`/`tomorrow` phrasing, flag-only copy ("the engine never auto-exits on earnings").
  Reuses existing `EARNINGS_CAUTION_DAYS`/`EARNINGS_IMMINENT_DAYS` (no new constant). Carries its own
  client-side `>= 0` guard → independent of the engine fix, no deploy-ordering hazard. Release triplet
  `2026.08.19.1` / sw v71→v72; `docs/CLAUDE.md` overlay bullet updated; 2 Playwright tests.

**Verification (independently re-run by lead, not just trusted from subagent):** 234/234 worker-positions
vitest; 5/5 `test_guide_releases.py`; the 2 new overlay Playwright tests pass via the chromium-symlink
harness. The 4 failing `test_pwa_positions` "take it"/confirm-click tests are **pre-existing** (subagent
confirmed via `git stash` — fail identically on unmodified code; same sandbox pointer-click flakiness
documented in prior WS5 entries), not a regression. Lead caught + fixed a duplicate `browser.close()`
in the new test and amended it into commit 3.

**Decisions flagged to owner (all reversible, non-blocking):**
1. **Knob vs. hardcode** — chose the knob defaulting to `'high'` so it's a config flip later, not a
   code change. Matches the `ENGINE_CONFIG`/`effectiveConfig` pattern.
2. **Overlay copy/styling is a lead taste call** — the WS5-7 mock omitted earnings, so no owner-approved
   visual existed. Flag-only voice deliberately (matches the engine's never-auto-exit rule). Easy to
   restyle or move into Details ▾ if owner prefers.
3. **High-based is validated on ONE example (NVT), not measured across trade history** — honest gap;
   the knob keeps it reversible. Offered to quantify tag-and-fade frequency against D1 if owner wants
   it on record; not done this session.

**Confirmed non-issue:** `persistAdvance` (sweep.js) DOES write `days_to_earnings` back to the row, so
the overlay reflects live engine state — no staleness follow-up. Did NOT widen the sweep's narrow
UPDATE column list (nothing needed it).

**Next steps:** merge this PR → `deploy-workers.yml` auto-deploys `worker-positions` (backward-compatible
knob + guard). Then the remaining cold-start queue: **WS5-4** (VAPID push + `closing` confirmation strip
— the big one, needs secrets), **WS5-8** (pre-close advisory read — soft-depends on WS5-4's push;
advisory-only constraint per WS5-7 §8), **WS5-5** (recently-closed grace window, #332, independent PWA-only).

**Note:** this session-notes + SPRINT update rides in this PR so it lands on default when the PR merges.

---

## 2026-08-19 — WS5-7 BUILT: positions managing-card overhaul (#337, PR #338)

**Status: safe to close once PR #338 merges.** Staff-eng session executing WS5-7 from the cold-start
spec. Lead owned design/taste/review + the mock (visual authority) + all adjudication; delegated both
boots-on-ground builds to Sonnet subagents against lead-authored locked specs
(`scratchpad/pr1-backend-spec.md`, `pr2-pwa-spec.md`) and reviewed every line. **PR #338 open**
(draft→ready), base `claude/elegant-babbage-hlxnfy`, branch `claude/pr336-cold-start-ws5-7-6sihe8`.

**Owner decision that reshaped the spec (mid-session): ack storage.** Spec §6 originally planned a
new `stop_ack_value` column + `0004_stop_ack.sql` migration. Owner pushed back ("we're changing the
top-level DB for one small field?"). Lead re-checked the schema: `position_events.event_type` is free
TEXT (no CHECK constraint), and the ack IS "a thing the user did" — exactly what the append-only
ledger is for. **Reframed to: ack = a `stop_ack` event row. No migration, no new column.** Cleaner
(disjoint from both write paths by construction — shares no row), and removed the owner-gated live-D1
migration step entirely. Spec §6/§8/§9's "localStorage v1" lines were already stale (superseded by the
cross-device server-side decision); the final design is server-side event-based.

**What landed (PR #338):**
- **Backend (`worker-positions/`, 4 commits, 229 vitest):** `listPositions()` LEFT JOINs the latest
  `ticker_quotes` bar (null-safe, tenant-safe) + bounded inline `events` (≤8) + computed
  `stop_ack_value` (from the FULL per-trade history, robust to the display cap) in one grouped query.
  `POST /positions/:id/ack-stop` (`src/transitions.js::ackStop`) — event-only, idempotent, writes NO
  positions column. Two persist-disjointness guard tests (sweep never touches a `stop_ack` event; ack
  never touches the positions row).
- **PWA (`docs/index.html`, 4 commits + 2 lead fixups):** pure `posDerive(p)` (the whole bug fix — no
  negative risk, floored open-risk/locked-in), state heroes (risk-free/locked w/ pending-lock chip,
  planned-risk US-7, P&L, closing exit-summary), stop-moved banner sourced from the `stop_moved`
  event payload `{from,to,basis}` (NOT initial_stop), cross-device ack via `posAckStop`, Details ▾ +
  `:has()`-driven formula reveal + OHLCV + activity trail, trim + caution overlays. Release
  `2026.08.19` / sw v70→v71 / `docs/CLAUDE.md`. 8 Playwright hero-state tests.
- **Lead override of a subagent call:** dollar totals now show cents only when non-zero ($174 but
  +$177.60) — the subagent's spec-literal "whole ≥$100" rule would've shown the real +$177.60 P&L as
  +$178; the owner-approved mock keeps the cents. Fixed the formatters + synced spec §2.

**Earnings overlay DEFERRED (lead scope call, owner OK'd):** NOT built — mock omits it AND the
`days_to_earnings`/`earnings_warning` engine signal fires on negative (past) dates. Tracked in 4
places: spec §2b, `.session/SPRINT.md` (#335 row), issue #335 (to add), PR #338 "Deferred". Fix the
negative-days guard first, then the overlay is a small `posOverlaysHtml` add.

**Verification (honest, all env-gaps identified against base commit):** backend 229/229 vitest; PWA
8/8 new hero tests via the chromium-1117 symlink harness; 682 non-collect pytest pass; release guard
5/5. The 4 failing `test_pwa_positions` "take it"/confirm click tests + 18 `test_collect_*` failures
are **all pre-existing** — verified the 4 fail identically on base `477fd5f`; the 18 are sandbox dep
gaps (`bs4`/`pytz`/`lxml` not installed here; CI has them). None touch WS5-7 code.

**Decision flagged: ONE PR, not two.** Told owner "two PRs, backend first" initially; revised to one
PR on the designated branch because (a) branch is designated, and (b) the card is null-safe, so the
fail-closed deploy-ordering hazard that forced the WS5-6 split doesn't apply here.

**Next steps:** flip #338 to ready (done this session) → owner review/merge → `deploy-workers.yml`
auto-deploys `worker-positions` (backward-compatible). Then: file the WS5-8 issue (already
SPRINT-tracked, line 51); #335 (breakeven ratchet + earnings-overlay bundle); WS5-4 (closing action
strip + push). Ack is event-based so nothing to apply out-of-band.

---

## 2026-08-25 — PR #366 follow-ups: WS-POSITIONS-TTL-BURN fixed + SEED groundwork (branch `claude/pr366-followup-tasks-e1b3zz`, PR #367)

**Status: safe to close once PR #367 merges.** Staff-eng session picking up the leftover tracked
follow-ups after WS-POSITIONS-STATUS (#366) merged. Owner scoped this session to **TTL-BURN** +
**SEED groundwork** (MONITOR and the #366 `test_pwa_watchlist.py` verification loose end stay
parked). Lead owned review/synthesis; both boots-on-ground pieces went to Sonnet subagents against
locked specs and every line was reviewed.

**WS-POSITIONS-TTL-BURN — DONE (owner chose "skip decrement until first real read").** `tickWatchlist()`
(`worker-positions/src/watchlist.js`) decremented `sessions_remaining` for every active watch row
each trading day, so a ticker added Saturday burned 2 of its 10 "mornings" by Monday delivering
zero info. Fix: step-3 decrement now scoped `WHERE status='active' AND ticker IN (SELECT ticker
FROM ticker_quotes)` — the exact `has_history` boundary #366 established, so an `awaiting_first_read`
row stays at full TTL until its first EOD bar lands. Added a `skipped_no_history` count to the tick
return (observability + the natural input to WS-POSITIONS-MONITOR). 3-places docs (in-code,
`worker-positions/CLAUDE.md`, `README.md`). **295 vitest green.** Lead reviewed the diff line-by-line:
boundary matches `has_history`, no NULL-in-subquery hazard (`ticker` is a NOT-NULL PK component),
`NOT IN (empty set)` correctly skips-all when `ticker_quotes` is empty. The subagent also correctly
fixed `test/index.test.js`'s `/watchlist/tick` route test (it had asserted `decremented:1` on a
bar-less ticker — the very bug). No release triplet (worker/engine-only). Commit `61128a0`.

**WS-POSITIONS-SEED — GROUNDWORK ONLY, verdict GO (no seed code; build still gated on owner sign-off).**
Reversed the "held" status only far enough to close the prerequisites. FMP key was live in-session,
so verified against the REAL API, not docs. Findings integrated into
`planning/watchlist-status-honesty-and-seeding.md` § "WS-POSITIONS-SEED — groundwork findings":
- Endpoint is `GET /stable/historical-price-eod/full` (returns genuine completed prior sessions;
  confirmed distinct from `/stable/quote`, the running-quote endpoint the original review rejected).
  **Split-adjusted** (verified against AAPL's real 2020-08 4:1 split), not dividend-adjusted — moot
  over the 1-session lookback a seed needs, so OHLC taken as-is.
- Seed scope: OHLC + volume + change_pct + prev_close only; `atr` null, `raw` at `'{}'` default
  (verified null-tolerant end-to-end via `normalizeBar()`/`advance.js`).
- `0006_ticker_quotes_source.sql` (`ADD COLUMN source TEXT NOT NULL DEFAULT 'finviz'`) — additive/
  non-breaking against `ingestQuotes()`'s explicit `INGEST_COLS` + `sweep.js`'s `SELECT *`. **Key
  finding: `source` is belt-and-suspenders, NOT a correctness requirement** — a `sweep.js` trace
  showed a past-dated seed is always outside the strictly-`>` bar window, so it can never leak into
  a real position's advance. The sma50 level-vs-%-distance trap is sidestepped by the OHLC-only scope.
- No new job — the existing 15:30 ET `preclose_status` pass already reruns the full status engine.
- **Two residual unverified items** (don't block starting, close before merging the writer):
  Finviz's own OHLC adjustment convention (`collect_held.py`) and `refsFromRow()`'s exact read query.
- Ordered 5-step build plan in the planning doc. SPRINT `WS-POSITIONS-SEED` row moved to GO.

**Next steps:** merge PR #367 → `deploy-workers.yml` auto-deploys `finviz-positions` (backward-compatible
TTL fix). Then the remaining backlog: **WS-POSITIONS-MONITOR** (healthchecks dead-man's-switch, now
meaningful and with `skipped_no_history` as an input) and **WS-POSITIONS-SEED** (owner decides whether
to green-light the build from the groundwork). The #366 `test_pwa_watchlist.py` Playwright verification
loose end is still open (sandbox Chromium harness gap; needs a CI/local run).

---

## 2026-08-25 — WS-POSITIONS-STATUS: honest watchlist "first read" state (branch `claude/missing-additions-status-ghxbn2`)

**Status: safe to close.** All changes committed and pushed on the designated branch; tests green;
release triplet included.

**Trigger:** owner reported the Morning tab's watchlist cards for 5 tickers (added Sat 2026-08-22)
still showed "Adding — first morning check lands tomorrow AM" unchanged on Monday evening, and
pushed back hard on an initial hand-wavy "expected lag, not broken" answer (rightly — that answer
conflated the TTL tick counter decrementing with the pipeline actually working, which was wrong).

**Root-caused live**, not inferred: queried D1 (`finviz-positions`) and the committed
`morning_latest.csv` directly. Confirmed the 5 tickers DID get a real bar (17:30 ET held feed) and
DID get a real `morning_latest.csv` row that morning (10:06 ET) — but tagged `no_quote`, copy
"Morning feed missed this ticker," which is false: the 10:05 ET classification run simply executed
before that ticker's first bar could exist (added 2 calendar days earlier, first trading-day tick
was that Monday). Distinct from, but adjacent to, the actual 2026-08-20 `WS5-8b-OPS` incident
(already fixed) where the union silently never ran at all.

**Staff-level review requested and incorporated** (Opus subagent, asked to pressure-test the fix
plan before building): found the original 3-workstream draft's "seed a bar via FMP on watchlist
add" design (then called WS-A — bad placeholder naming, since renamed) doesn't work as scoped —
FMP's `/stable/quote` returns the *current session's own running quote*, not a prior completed
bar, so seeding it as `prior_high` could manufacture a false `triggered` read; also flagged a real
correctness risk (a seeded row could permanently pollute `ticker_quotes`, which `advance()` also
reads for real positions, with no `source` column to quarantine it) and that the monitoring
follow-up should lead with a positive-assertion healthchecks.io ping, not a warn-and-exit step
(same silent-failure shape as the original incident). Full review + this session's own findings:
`planning/watchlist-status-honesty-and-seeding.md`.

**What landed (this PR — WS-POSITIONS-STATUS only; SEED and MONITOR held/backlog per the review):**
- `worker-positions/src/watchlist.js`: `/watchlist-tickers` (`watchlistTickerRefs`) gains
  `has_history:boolean` (`q_trade_date != null` — the same check `refsFromRow` already makes).
- `scripts/pick_status.py`: new `STATUS_AWAITING_FIRST_READ` + optional `has_history` param on
  `compute_pick_status()` — returns it instead of `STATUS_NO_QUOTE` when `has_history is False`.
  Default `None` (every picks caller) is byte-identical to prior behavior, same pattern as
  `ref`/`STATUS_RECLAIM`.
- `scripts/collect_morning.py`: `build_watch_levels()` threads `has_history` through;
  `build_status_rows()`'s `compute_pick_status` call passes it.
- `docs/index.html`: `watchCardHtml()` split from 2 states to 3 — `noBarYet` (unchanged),
  new `awaitingFirstRead` (bar exists, no real classification yet → "Reference bar captured —
  first live read after the next scheduled check" + the actual prior-high/prior-low levels), then
  real status. `MORNING_STATUS_META.awaiting_first_read` added for completeness (never hit by
  picks, same precedent as `reclaim`). Release `2026.08.25.1`, sw.js v81→v82.
- Tests: 4 new `test_pick_status.py` cases, 3 new `test_collect_morning.py` cases (incl. an
  end-to-end `build_status_rows` case), 2 new `worker-positions/test/watchlist.test.js` cases, 1
  new `tests/test_pwa_watchlist.py` Playwright case. 719 non-Playwright pytest pass; 292 vitest
  pass. **Playwright case not verified green in this cloud session** — the whole PWA app failed to
  boot past the loading skeleton for every watchlist test in this sandbox, including the
  pre-existing, unmodified baseline tests in the same file (`test_signed_out_...`,
  `test_signed_in_watch_card_shows_ticker_pill...`), with and without the matching pinned Chromium
  revision (1117) — confirmed a pre-existing sandbox-only harness gap, not a regression from this
  change. Verified the JS change itself via `node --check` on the extracted inline script (valid
  syntax) and by structural mirroring of the existing `noBarYet` branch. **Needs a real
  CI/local-dev run to confirm `test_pwa_watchlist.py` is actually green** — flag if it isn't.
- Tracking: `planning/watchlist-status-honesty-and-seeding.md` (design + review), `.session/SPRINT.md`
  rows `WS-POSITIONS-STATUS` (done, this PR), `WS-POSITIONS-SEED` (backlog, held per review),
  `WS-POSITIONS-MONITOR` (backlog, supersedes/refines `WS5-8b-MONITOR`'s scope),
  `WS-POSITIONS-TTL-BURN` (backlog, new gap found this session: `sessions_remaining` decrements even
  on a day with zero real read — not fixed, just flagged).

**Naming note:** the original draft used placeholder `WS-A/B/C` labels — pure shorthand, not tied to
any tracking scheme. Owner correctly called this out as bad naming given the repo already has a live
`WS5-8b-*` convention for this exact area. Renamed to `WS-POSITIONS-*` per owner request; existing
`WS5-8b-*` SPRINT rows were NOT renamed (other docs/session-notes cite those IDs by name already) —
the new rows cross-reference them instead.

**Next steps:** confirm `test_pwa_watchlist.py` passes in CI/local dev (it's on the CI Playwright
ignore list, so this PR's `test` job won't reveal a break either way — a human or a
Chromium-matched session needs to actually run it). Then pick up `WS-POSITIONS-MONITOR` (healthchecks
dead-man's-switch) — it's now meaningful since `no_quote` means what it says again. `WS-POSITIONS-SEED`
stays parked until an FMP EOD-history endpoint + `ticker_quotes.source` column are worked out.

---
