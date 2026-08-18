# Session Notes

> **Future Claude:** read this immediately at session start. Summarize the current state for the user before doing anything else.
>
> **Format:** Append a new `---` delimited block per session. Header = date + workstream description. Keep the last 4 sessions here; a human will periodically move older entries to `.session/archive/session-notes-archive.md`. Do NOT replace existing entries — append only.

---

## 2026-08-18 — WS5-6: PWA switched to the multi-state /positions filter (follow-up to PR #333)

**Status: safe to close.** Closes out the review chain started on PR #331: doc fix → PR #331
(merged) → backend multi-state filter → PR #333 (merged, deploy independently verified) → this
PR, the PWA half.

**Verification before starting:** did not take "merged and deployed" on the user's word alone —
`git log` confirmed PR #333's merge commit on `origin/claude/elegant-babbage-hlxnfy`, and a direct
Cloudflare API query (`GET .../workers/scripts`) showed `finviz-positions` `modified_on` ~22
seconds after the merge commit's timestamp — the new worker code is genuinely live, not just a
green CI checkmark (same discipline as the 2026-08-16 PR #322 entry below).

**What changed:** `posLoadPositions()` (`docs/index.html`) now calls
`GET /positions?state=open,managing,closing` instead of an unfiltered fetch. `POS_VISIBLE_STATES`
client-side filtering stays (defense-in-depth against a future worker-side state this build
doesn't know about) but is no longer what excludes `closed` positions from the payload — the
server does that now, so a user with a year of trade history no longer re-transfers all of it on
every Positions tab load. `docs/CLAUDE.md` and README's `POS_VISIBLE_STATES` rows updated to
describe the dual role. WS5-6 marked done in SPRINT.md.

**Release triplet: judged N/A, not skipped by omission.** This is a pure payload-efficiency
change — the set of positions rendered and how they look is identical before/after; nothing new
is visible or actionable for the user. The repo's release-triplet rule is scoped to user-facing
changes, and the "housekeeping PRs skip it" carve-out doesn't quite fit either (this isn't a typo
fix), so calling it out explicitly here rather than silently leaving `releases.json`/`sw.js`
untouched.

**Not independently Playwright-verified in this session** — `playwright` isn't installed in this
sandbox (`ModuleNotFoundError`) and installing it is the known cloud-session gap documented in
`knowledge/investigations/playwright-cloud-session-testing.md`. Did check: (1) `node --check` on
the extracted `<script>` block — no syntax errors; (2) `tests/test_pwa_positions.py`'s existing
mock intercepts `**/positions**` (wildcard), so the added query string doesn't break its route
matching, and its mock server doesn't itself filter by the `state` param (returns all seeded rows
regardless) — the existing `test_managing_and_closing_positions_still_render` test still exercises
the real code path (client-side filter) and should still pass unmodified, but this was reasoned
through, not run. **Recommend the owner (or a session with Playwright available) run
`python3 -m pytest tests/test_pwa_positions.py -v` before/shortly after this merges** as the one
gap in this chain's verification.

**Next steps:** none outstanding from this specific thread. The advisor's other note — that
WS5-5's grace window will eventually need a shape this plain state param can't express, and that
pagination is the more durable long-term fix — is already captured in PR #333's description and
SPRINT WS5-5; no new tracking needed here.

---

## 2026-08-18 — GET /positions multi-state filter (backend-only, follow-up to PR #331)

**Status: safe to close.** Reviewed PR #331 (Positions tab empty-state fix), pushed a small
doc-only follow-up directly onto its branch (README.md + docs/CLAUDE.md rows for the
`POS_VISIBLE_STATES`/`POS_STATE_BADGE` constants it introduced but hadn't documented — merged as
part of #331), then scoped the larger finding into its own backend-only PR (this one).

**Finding:** PR #331 fixed the Positions tab dropping `managing`/`closing` positions by having the
PWA call `GET /positions` **unfiltered** and filter client-side (`POS_VISIBLE_STATES`), because
`listPositions()`'s `state` query param only supported a single exact match — no way to ask for
"open OR managing OR closing" server-side. That means every load re-transfers a user's **entire**
trade history (all `closed` positions ever logged), not just the handful of live ones.

**What landed (this PR, backend-only):**
- `worker-positions/src/positions.js`: `listPositions()` now accepts a single state, an array of
  states (→ parameterized `state IN (?, ?, ?)`), or nothing (all states) — same function, no new
  caller signature to remember. New `ALL_STATES`/`LIVE_STATES` exports. Deliberately did **not**
  reuse `quotes.js`'s `HELD_STATES` (same values today, different question — "should we poll a
  quote" vs "should the tab show it" — will diverge once WS5-5's grace window ships).
- `worker-positions/src/index.js`: `GET /positions?state=` now accepts repeated params
  (`?state=open&state=managing`) and/or comma-separated (`?state=open,managing,closing`), dedupes,
  and 400s on an unrecognized state value instead of silently returning zero rows.
- 7 new tests in `test/index.test.js` (union filtering, repeated-vs-comma equivalence, dedup,
  unknown-state 400, tenant-scoping still enforced on the multi-state path). 216/216 passing.
- README.md § Endpoints row updated for the new query-param shape.

**Deliberately NOT in this PR — the PWA change.** Got an Opus-advisor adversarial review of the
plan first, which flagged a real deploy-ordering hazard: the worker auto-deploys on merge
(`deploy-workers.yml`) but the PWA is a cached GitHub-Pages page behind a service worker, so if the
PWA shipped `?state=open,managing,closing` *before* this worker change is live, the old worker
would exact-match on that literal string, match nothing, and the Positions tab would go **empty**
— a fail-closed regression on live trades, worse than the bug PR #331 just fixed. Sequencing:
confirm this worker PR is merged AND deployed (check `deploy-workers.yml`'s run + Cloudflare's
`workers/scripts` `modified_on`, same verification pattern as the 2026-08-16 entry below) before
opening the PWA follow-up that switches `posLoadPositions()` off the unfiltered fetch.

**Next steps (not yet tracked as a SPRINT/issue item — do so before/with the PWA follow-up PR):**
1. Confirm this PR merges + deploys (verify against Cloudflare, not just green CI).
2. Open the PWA follow-up: `posLoadPositions()` → `/positions?state=open,managing,closing`; keep
   `POS_VISIBLE_STATES` as cheap defense-in-depth. Touches `docs/index.html` → triggers the
   release-triplet rule (`releases.json` + `sw.js` bump in the same PR).
3. Advisor flagged that WS5-5 (closed-position grace window, already tracked) will need
   `state IN (...) OR (closed AND recently)` — not expressible via this plain state-list param —
   so this IN-clause shape is a stepping stone, not the final shape. Consider `?limit=`/pagination
   as the more durable general fix once WS5-5 lands, rather than continuing to grow the state DSL.

---

## 2026-08-16 — PR #322 ops-verification: migration applied, deploy confirmed, bars claim corrected

**Status: safe to close — all four ops items resolved or explicitly flagged as needing a weekday
run.** Verified the "what the owner should verify after merge" list from PR #322 (WS5 §8b watchlist
P1+P2) directly against Cloudflare, not just against code:

1. **`0003_watchlist.sql` migration — was NOT applied at first check; now APPLIED.** Queried the
   live `finviz-positions` D1 (`SELECT name FROM sqlite_master WHERE type='table'`) via the
   Cloudflare API directly (`CLOUDFLARE_API_TOKEN`/`CLOUDFLARE_ACCOUNT_ID` were already in the
   session env — no OAuth needed). Initially found: `_cf_KV`, `position_events`, `positions`,
   `sqlite_sequence`, `ticker_quotes` — no `watchlist`/`watchlist_tick_log`. Ran the migration's 3
   statements (`CREATE TABLE watchlist`, `CREATE INDEX idx_watchlist_user_status`, `CREATE TABLE
   watchlist_tick_log`) directly via the D1 HTTP query API with owner sign-off, then re-verified
   live: all 3 objects now present. `/watchlist*` routes are unblocked.
2. **`deploy-workers.yml` auto-deploy — CONFIRMED, via Cloudflare, not just green CI.** GH Actions
   run 31972877074 (fired at PR #322's merge, 2026-08-16T21:13:54Z) shows all 3 deploy jobs
   succeeded. Cross-checked against Cloudflare's own `workers/scripts` listing: `finviz-positions`
   `modified_on` = `2026-08-16T21:14:15Z`, matching the deploy job's completion — the script was
   genuinely re-pushed, not just a green checkmark. Note `wrangler deploy` (ships worker code) and
   `wrangler d1 execute` (applies SQL migrations) are two independent commands — deploy succeeding
   says nothing about migration state, which is why #1 above still needed a separate live check.
3. **`collect_morning.yml` secrets — owner confirmed added to GH repo secrets.** GitHub does not
   expose secret values via API, so this can't be verified by name/value; instead triggered a real
   `workflow_dispatch` with `dry_run: true` (run queued from this session) to observe whether the
   watchlist union actually fires end-to-end instead of falling back to picks-only. See run result
   for outcome (check `collect_morning.yml` run at ~2026-08-16 21:3x UTC).
4. **"Feed is dormant until a few `ticker_quotes` bars accumulate" — WRONG, corrected in the brief.**
   Traced the actual data path: `sma20`/`sma50`/`atr`/`prior_high`/`prior_low` (the watchlist
   status engine's inputs, incl. the `reclaim` ref) are all recovered from a SINGLE scraped row —
   `recoverMaLevel()`/`pctFromRaw()` in `worker-positions/src/advance.js` reconstruct the MA price
   from Finviz's own `%`-from-SMA columns, which Finviz computes server-side per-row. Confirmed live:
   `ticker_quotes` currently has exactly 2 rows, both `trade_date=2026-08-14` (one day), and that's
   already sufficient.
   **Correction to this entry's own first draft (owner caught it same-day):** the first version of
   this note claimed the WS5 phase-3 `advance()` engine "genuinely does need several days of bars" —
   that's also wrong, checked directly against `advance.js`. `advance(pos, bar, cfg)` is a pure
   function of ONE current bar + the position's own persisted state (`current_stop`/`trail_basis`/
   `profit_floor`/`caution_flag`/`highest_trim_atr`, each updated one call at a time) — not a
   multi-day `ticker_quotes` lookback. `atrExt50()` and the trail-basis-widen check are both
   single-bar computations; the ratchet (`Math.max(next.current_stop, trailLevel, ...)`) reads
   yesterday's STATE on the position row, not yesterday's BAR. "Needs a few days to test
   meaningfully" (2026-08-15 entry below, GO-LIVE checklist) is a QA-confidence statement about
   watching real state transitions across live runs, not an algorithmic data dependency — same
   category of claim as the watchlist one this entry set out to correct, and equally wrong for the
   same reason. Fixed in `planning/watchlist-build-brief-8b.md` §7 and PR #322's description;
   not editing the 2026-08-15 entry's original prose per the append-only rule.

**Next steps:** none blocking. Only remaining open item is #3 — confirm the `POSITIONS_WORKER_URL`/
`POSITIONS_INGEST_TOKEN` secrets actually work end-to-end on a real weekday `collect_morning` run
(Monday 10:05 ET Cloudflare-dispatched, or a manual weekday `workflow_dispatch --dry-run`); the
2026-08-16 dry-run exited at the weekend guard before reaching that code path.

---

## 2026-08-15 — WS5 §8b: personal watchlist — P1 + P2 BUILT (#319, PR #322)

**Status: safe to close once PR #322 merges. P3 (PWA) NOT started — recommended as a fresh
focused session (taste-heavy, lead-owned).** Executed the locked build brief
(`planning/watchlist-build-brief-8b.md`). Lead delegated both boots-on-ground builds to Sonnet
subagents against self-contained locked specs (`scratchpad/p1-spec.md`, `p2-spec.md`) and reviewed
every line; lead studied the v2 mock by hand and mapped the P3 anchors but did not build P3.

**P1 (worker/D1) — branch `claude/ws5-watchlist-p1-tyj03t`, commit ca9bdf1:**
- `worker-positions/migrations/0003_watchlist.sql` — private user-scoped `watchlist` table
  (`UNIQUE(user_id,ticker)`, no stop/size) + `watchlist_tick_log(tick_date)` idempotency guard.
  Applied OUT-OF-BAND (`wrangler d1 execute … --file …`) — `wrangler deploy` doesn't run migrations.
- `src/watchlist.js` — validation (above/below need price; reclaim_* reject one) + CRUD + upsert-as-
  renew + `watchlistTickers`/`watchlistTickerRefs` + `tickWatchlist` (decrement→expire@0→purge>14d).
  Reuses `normalizeBar` for MA-ref recovery, not re-derived.
- `heldTickers` unions `positions(open/managing/closing) ∪ watchlist(active)`.
- 6 routes: owner-bearer `POST/GET /watchlist` + `PATCH/DELETE /watchlist/:id` (below auth gate);
  service-token `GET /watchlist-tickers` + `POST /watchlist/tick` (above it). 209 vitest (+36),
  incl. cross-auth isolation both directions, TTL idempotency, purge boundary, user-scoping.

**P2 (feed + engine) — commit 9279a7a:**
- `pick_status.py` — new `STATUS_RECLAIM` + `compute_reclaim(price, today_low, prior_low, ref)`
  (mirror of failed_breakout). `compute_pick_status` gains optional `ref=` → **byte-identical for
  picks** (they never pass ref). Reclaim sits between failed_breakout and setting_up; is actionable.
- `collect_morning.py` — unions active watch tickers into the single morning scrape; `build_watch_levels`
  maps `/watchlist-tickers` → pick_levels shape with `ref=sma50`; `union_watch_levels` (pure, dedupe,
  Focus wins collision); non-fatal `fetch_watchlist_tickers`/`post_watchlist_tick`. 68 tests in the
  two files (+25). Full non-Playwright suite green (only pre-existing Chromium-absent Playwright fails).
- **Lead-caught bug (subagent had it green but wrong):** union originally ran AFTER the empty-Focus
  `exit(0)` guard → a zero-Focus day would silently skip watch tickers. Moved union BEFORE the guard;
  guard now checks the combined universe. Watch tickers ride the morning scrape independently.

**Two lead calls flagged to owner (both reversible, non-blocking):**
1. `/watchlist-tickers` OMITS `level_value` (privacy; CI path never needs it; owner `GET /watchlist`
   still returns it). Deviation from brief §3's literal payload shape, deliberate.
2. **System-read `reclaim` ref = 50MA** (not prior_low, which degenerates the formula; matches the
   mock's §04 "Ref (50MA)"). User's own 20MA/50MA reclaim overlay is a separate client-side P3 read.
   One-liner to change if owner wants 20MA or per-level-type. **This is the one worth an owner nod.**

**Owner post-merge TODO:** (1) apply `0003_watchlist.sql` out-of-band to `finviz-positions` D1;
(2) confirm `collect_morning.yml` has `POSITIONS_WORKER_URL`/`POSITIONS_INGEST_TOKEN` (same secrets as
`collect_held.yml`) — without them the morning run is picks-only (no error). Feed dormant until a few
`ticker_quotes` bars accumulate (same WS5 gate). `deploy-workers.yml` auto-deploys the worker on merge.

**Next: P3 (PWA), lead-owned.** Build to the v2 mock `planning/mocks/ws5-watchlist-directions.html`.
Anchors mapped in `docs/index.html`: `renderMorning`@6114, `renderPositions`/`manualBuildPayload`
@5691/5866, `morningChartAffordance`@5058, `posApi`@5440, `computeLaunchReady`@3920,
`tradingViewChartHtml`@3547, `switchTab`@6199, `POSITIONS_API`@404, `MORNING_STATUS_META`. Scope:
Positions add collapsible (sibling to manualEntry) + Morning "Your watchlist" section + card + gauge
(client-side your-level read from private `GET /watchlist`; NEVER write level to public store) +
graduation ("I took it" → §8a ticket prefilled → DELETE watch) + release triplet + `test_pwa_watchlist.py`
(add to tests.yml `--ignore`). Add `reclaim` to `MORNING_STATUS_META` too.

---

## 2026-08-15 — WS5 §8b: personal watchlist — DESIGN LOCKED (#319, PR #321)

**Status: safe to close once PR #321 merges.** Senior-eng + product design session for the §8b
personal watchlist. No implementation — this session produced the **locked design + a cold-start
build brief**. Lead owned all design/taste/architecture and the mocks (wrote the mock code by hand,
iterated 3× on owner feedback); delegated ONE recon pass to a Sonnet subagent (force-include seam,
morning pipeline, §8a form, private-D1 pattern) and verified its findings against the code.

**Deliverables (all on PR #321, branch `claude/watchlist-force-include-picks-9w7rfo`):**
- **`planning/watchlist-build-brief-8b.md`** — the authoritative cold-start brief (supersedes §8b's
  think-big). Full architecture, D1 schema, worker routes, engine change, PWA spec, phasing, read list.
- Mocks: `planning/mocks/ws5-watchlist-directions.html` (final **watch card v2** — authoritative UI)
  + `ws5-watchlist-surface.html` (earlier three-surface context).

**The reframe (owner drove it; lead had over-anchored on the prev-eng §8b note):**
- **NOT public-picks force-include.** The picks selector is group-level with no ticker seam; force-in
  would make the ticker a full public pick. Instead: private D1 `watchlist` table; union watch tickers
  into the **morning + held feeds**; membership/level/TTL stay private.
- **A watch item is not a trade ticket** — no stop/size ever (a stop is born at entry, depends on an
  unknowable future fill). Add path = one-field radar-add + optional level. The §8a ticket is reused
  **only at graduation** ("I took it").
- **ONE status engine, no drift** — watch system-read MUST run through Python `pick_status.py`
  (union into `collect_morning`), never a re-impl. Add a state there → picks + watch inherit it.

**Locked decisions (see brief §2):** privacy posture (a) anonymous-public quote row, membership
private; trigger = carry-your-own + auto system-read; N=10 trading mornings, renew resets, 14-day
expired bin; your-level wording = direction + quiet met ("above 144.00 · now above"), no
"crossed/approaching"; block header = none (labeled rows like the current Morning card), word "System"
banned; **new `reclaim` engine state** = `price > ref AND (today_low < ref OR prior_low < ref)`, ref ∈
{prior low, 20/50MA} — both today's AND yesterday's low; gauge on-by-default+collapsible; level types
above/below/20MA/50MA; kebab = Renew/Edit/Remove; manage on Positions (sibling collapsible to §8a),
view on Morning ("Your watchlist" + quick-add deep-link); top-level one-tap Show chart.

**Verified code facts that shaped it:** morning status = prior High/Low/ATR only (no MAs) via
`compute_pick_status`; MAs (for ATR-ext / MA-reclaim / stops) ARE in the private `ticker_quotes.raw`
(84-col held scrape), recovered from %-distance via `advance.js::normalizeBar`; `collect_morning`
narrows to Focus top-100 so watch tickers need an explicit union (§8b's "rides for free" was optimistic).

**Low-confidence / owner-flagged:** (1) privacy posture (a) is the one-way door — accepted, fully-
private morning store tracked as a follow-up. (2) gauge density on a phone — landed on
on-by-default-but-collapsible. Neither blocks the build.

**Next steps:** merge PR #321 (lands brief + notes on default). Then a fresh session executes the brief:
**P1** worker/D1 (`0003_watchlist.sql` + CRUD + `/watchlist-tickers` + `/watchlist/tick` + `heldTickers`
union) → **P2** feed+engine (`pick_status.py` reclaim + `collect_morning` union) → **P3** PWA (add
collapsible + Morning section + card/gauge + graduation + release triplet + Playwright). Feed dormant
until a few `ticker_quotes` bars accumulate (same gate as the rest of WS5).

**Note:** this session-notes commit + the brief must land on default via #321 merging to be visible/usable next session.

---

## 2026-08-14 — WS5 §8a: manual "any ticker" position entry (#264, PR #320)

**Status: safe to close once PR #320 merges.** Senior-eng + product session driving epic #264 §8a —
letting the owner open a position on any typed ticker, not just a surfaced pick. Lead owned the design
+ taste + review; delegated both boots-on-ground builds to Sonnet subagents against locked specs and
reviewed every line. Design review artifact ("Manual Position Entry", 3 options A/B/C) → owner picked
**Option B** (guided ticket).

**Design decisions locked with owner:**
- **Placement:** top of the Positions tab (already the authed surface; no new-tab/anti-drift churn).
- **Payload:** identical to the picks path + `meta.source='manual'`, `stop_basis='manual'`. `posCardHtml`
  already renders `source`/manual-basis → zero list changes.
- **Bidirectional sizing** (size by risk $ ↔ by shares), **stop as price ↔ %-below-entry**, optional
  earnings-days, inline `lookupTicker` company resolve as a fat-finger guard (non-blocking — a symbol
  the lookup worker doesn't cover can still be logged; lead call, flag if owner wants a hard block).
- **Optional backdated `entry_date`** for historical trades — the one thing crossing into backend.

**What landed (PR #320, branch `claude/any-ticker-entry-form-guwbl2`, 3 commits):**
- **Backend** (`worker-positions/src/positions.js`): `POST /positions` accepts optional `entry_date`
  (YYYY-MM-DD, ≤ today ET, **real-calendar round-trip validated** — lead caught that the subagent's
  regex-only check let `2026-02-30`/`2026-13-01` through into the NOT-NULL `trade_date` events ledger).
  `buildPositionRow` uses it else stamps today; `opened_at` stays real-now. Engine advances forward —
  a backdate is a label, not a replay. 162 vitest (positions.test.js 8→14).
- **PWA** (`docs/index.html`): collapsed "＋ Log a position manually" expander in `renderPositions()`
  (signed-in only). Standalone `manualBuildPayload()` (NOT `ws5BuildPayload`, which stays morning-
  coupled). `manualRecompute()` id-patches the risk/position readouts on `oninput` (focus-preserving,
  mirrors `ws4Recompute`); toggles full-re-render (click, blur ok). `manualOpenFromLookup()` prefills
  from already-fetched lookup data + `switchTab('positions')`. Release triplet `2026.08.14` /
  sw.js v65→v66. New `tests/test_pwa_manual_entry.py` (8, added to `tests.yml --ignore`).
- **Verified end-to-end by the lead** via the chromium-1117→1194 symlink harness: `test_pwa_manual_entry`
  + `test_pwa_positions` = **16/16 pass** (after the lead's ticker-left-align taste edit); `node --check`
  on the extracted script OK; release guard `test_guide_releases.py` green; worker `npm test` 162.

**Deferred + tracked — §8b personal watchlist (#319):** owner think-big to add an arbitrary ticker to
the next N Morning scrapes. Key realization (owner's, lead under-weighted first): **force-include** the
ticker into the EOD picks scrape so it becomes a picks-adjacent row and rides Morning status unchanged —
NOT a separate pipeline. Two open Qs (public-CSV privacy signal; TTL). Unifies with §8a as the *same
form, two actions* ("Watch" vs "I took it"). Full brief: `trade-lifecycle-engine.md` §8b + #319 +
SPRINT WS5-8b (with a next-eng read list). Deferred to a dedicated session.

**Low-confidence calls flagged to owner:** (1) non-blocking ticker resolve (above). (2) None else —
placement, payload, sizing all owner-approved.

**Next steps:** merge #320 → `deploy-workers.yml` auto-deploys `finviz-positions` (backward-compatible
optional field). Then WS5-4 (VAPID push) is the remaining phase-4 item. §8b watchlist is its own session.

**Note:** this session-notes commit must land on default via #320 merging to be visible next session.

---

## 2026-08-14 — WS5-3b-ii: owner exit-transition routes + autoConfirm in the sweep

**Status: safe to close once this PR merges.** Shipped the owner-facing half of the daily engine.

**What landed** (branch `claude/ws5-trade-lifecycle-wiring-6t4sej`, all in `worker-positions/`):
- New `src/transitions.js` — owner-bearer `POST /positions/<trade_id>/{confirm-exit,still-holding,
  correct-exit,reopen}` over the pure fns already in `advance.js`. `applyTransition()` does load
  (user-scoped) → state precondition → pure fn → `persistTransition()`. Routes matched by an
  anchored regex in `index.js`, placed below the owner-auth gate (service token gets no say over a
  human's exit fill), and it can't shadow the exact `/positions` routes.
- `persistTransition()` is the deliberate **mirror** of the sweep's `persistAdvance()`: writes
  exactly the user-owned columns the sweep's UPDATE refuses to (`state`, exit-signal fields,
  `exit_price`, `closed_at`, `confirmation_status`, `caution_flag`), none of the engine columns.
  CAS version column is **`state`** (double-submit → second no-ops); same events-first/UPDATE-last
  batch order.
- `autoConfirm()` folded into `sweep()` after the advance loop, over the `closing` population the
  advance loop excludes. Closes anything past `EXIT_AUTOCONFIRM_SESSIONS` at the signal-frozen
  `expected_exit_price`, `confirmation_status='auto'`. New `auto_confirmed` count; `dry_run` writes
  nothing. Session clock = **global** `DISTINCT trade_date` calendar (`sessionsSince` +
  `distinctTradeDates`), strictly after `exit_signal_date`.
- Tests: new `test/transitions.test.js` (23) + auto-confirm/`sessionsSince` block in
  `test/sweep.test.js`. **155 vitest total (was 122, +33), all green.** No pytest/PWA touched.
- Docs: README (phase status ✅ 3b-ii, endpoint table, 3b-ii section, Tests), `worker-positions/
  CLAUDE.md` (transitions section, 3 gotchas), design §7 auto-confirm impl note, SPRINT WS5-3b-ii ✅.

**Two gotchas worth remembering:** (1) the pure transition fns return `trade_date` as a *sibling*
of `events`, NOT stamped per-event (unlike `advanceThroughBars`'s fold) — the wiring must stamp
each event before persist or the NOT-NULL `position_events.trade_date` throws. (2) `persistTransition`
guards on `state = ?` (NOT NULL → plain `=`), unlike persistAdvance's nullable `last_advanced_date
IS ?`.

**Owner decision flagged (non-blocking, SPRINT WS5-3b-OWNER item 4):** autoConfirm's session clock
uses the **global** held-ticker calendar, not the position's own ticker — robust to a one-symbol
feed gap. Reasonable reading of design §7's "natural session calendar"; flag if per-ticker is wanted.

**Next (phase 4 / a PWA task):** wire the PWA "needs your confirmation" strip + editable
Confirm-fill/Still-holding actions to these routes, and VAPID two-tier push. The routes exist and
are tested; nothing in the PWA calls them yet. **Still gated:** live e2e needs a few sessions of
real held bars — first safe check is an owner-bearer `POST /advance?dry_run=1`.

---

## 2026-08-13 — collect_held.yml first-run failure: Cloudflare Bot Fight Mode, not missing secrets (#312)

**Status: safe to close once this PR merges.** Owner reported the first manual `collect_held.yml`
dispatch failing and suspected missing GitHub Actions secrets. Investigated via the workflow logs.

**Root cause:** NOT a secrets problem — both `POSITIONS_WORKER_URL` and `POSITIONS_INGEST_TOKEN`
were confirmed present in the run's env (non-empty, masked `***`). The actual failure was `GET
/held-tickers failed: HTTP 403 Forbidden`. Live-verified (via curl against
`https://finviz-positions.salmonbaby8.workers.dev`) that this 403 comes from **Cloudflare's Bot
Fight Mode on the `workers.dev` zone**, not from `worker-positions/src/auth.js` — the app's own
auth code always returns a JSON `{"error":"unauthorized"}` 401, never a bare 403. Requests sent
with the default `Python-urllib/x.y` User-Agent get Cloudflare error 1010 ("browser signature
banned") even hitting the *unauthenticated* `/health` route; a non-generic User-Agent clears it
immediately. `collect_held.py` was the only script in the repo calling a Cloudflare Worker via raw
`urllib.request` (the ticker-lookup worker is called from the browser/PWA, not GH Actions), so this
UA-based block had never been hit before.

**Fix (this PR):** `scripts/collect_held.py`'s `_authed_request()` now sets `User-Agent:
finviz-groups-tracker-held-feed/1.0`. Added `test_authed_request_sets_non_generic_user_agent` to
`tests/test_collect_held.py` (monkeypatches `urlopen`, asserts the header) as a regression guard.
Full suite green (667 non-Playwright + this new one).

**Not done in this session:** re-running `collect_held.yml` live to confirm the fix end-to-end —
worth a manual dispatch on the next trading day now that the code is merged. WS5-2's go-live
checklist (`session-notes.md` 2026-08-13 WS5-phase-2 entry) is otherwise unchanged.

**Next steps:** owner re-dispatches `collect_held.yml` (or waits for the 17:30 ET cron) to confirm
green; if it still fails, check next for a live/`held` position actually existing (empty held set
is a normal `exit(0)`, not a signal either way here since this run failed before reaching that check).

## 2026-08-13 — WS5 phase 3a: pure `advance()` daily engine (#264, SPRINT WS5-3a)

**Status: safe to close once the PR merges.** Senior-eng session building the heart of the
trade-lifecycle engine. Lead wrote the engine + the taste-critical semantics tests by hand
(exit ordering, exit-signal→Closing symmetry, invariants); delegated ONLY the mechanical Finviz
"Earnings"→days parser port + its tests to a Sonnet subagent against a locked spec, reviewed every
line. Full suite green: **99 worker-positions vitest** (was 55; +44 in `advance.test.js`).

**Scope call (senior-eng): split phase 3 into 3a (pure engine, this PR) and 3b (D1 wiring, next).**
Mirrors the WS3 Phase A/B split. The pure function is the entire risk/taste surface and is
exhaustively testable with synthetic bars now; live advancement is gated on a few accumulated
`ticker_quotes` bars anyway, so wiring it live buys nothing today. 3a de-risks; 3b is mechanical.

**What landed (this PR, branch `claude/ws5-phase3-advance-engine-5yy5qn`):**
- **`worker-positions/src/advance.js`** — pure `advance(pos, bar, cfg) → {position, events, stale?}`
  implementing design §4 verbatim: exit-before-advance ordered checks (stop-hit incl. honest
  gap-down at the open; `close_below_50ma`; `severe_breakdown` ≥3 ATR one-day drop; stateful
  two-close-below-20MA), each **signalling → `closing`** (modeled price as *expected* fill, never
  straight to `closed`); then profit-floor ratchet (+1R), 20MA→50MA widen (per-position
  `meta.widen_enabled`), within-basis ratchet-up-only, ATR-extension trims with the
  `highest_trim_atr` ledger (idempotent + catch-up), earnings flag. Plus the user-driven
  transitions `confirmExit`/`stillHolding`/`autoConfirm`/`correctExit`/`reopen`, `effectiveConfig`
  (globals + `meta.config` overrides, §14 door), `ENGINE_CONFIG` (§6 constants), and `normalizeBar`.
- **The one non-obvious transform, isolated:** Finviz SMA20/50/200 are **%-distance, not levels**
  (migration 0002). `normalizeBar` recovers levels via `close/(1+pct/100)` in exactly one place; the
  engine body only ever sees levels. `days_to_earnings` derives from `raw["Earnings"]` via
  `parseEarningsToDays` (UTC-pure on the bar's `trade_date`, roll-forward year inference; calendar
  days as a conservative proxy for sessions), preferring a typed column if the feed derives one later.
- **Invariants property-tested** over 40 random 60-bar sequences: `profit_floor` monotonic
  non-decreasing; `current_stop >= profit_floor` always; `remaining_qty` non-increasing and > 0.
  Idempotency via `last_advanced_date` guard (also what stops the caution counter double-incrementing
  on a same-day re-run); stale/missing bar → flag + note, no advance.
- **Docs (3-places rule):** in-code comments; new `worker-positions/CLAUDE.md` (engine architecture +
  the SMA gotcha + `effectiveConfig` door); README § Configurable parameters › Engine constants
  table + phase status; root CLAUDE.md repo-structure pointer; SPRINT WS5-3 split into 3a✅/3b🔴.

**Low-confidence / open design questions (surface to owner; none block 3a merge):**
1. **`EARNINGS_WARN_SESSIONS = 10`** — I used one warn band (reused Focus `EARNINGS_CAUTION_DAYS`).
   Owner may want the flag only at the tighter imminent band (≤3). One-constant change.
2. **Widen is recomputed each bar, not latching.** I followed §4's pseudocode literally
   (`basis = sma50 > entry ? 50ma : 20ma`, recomputed daily), so if the 50MA later falls back below
   entry the basis flips BACK to 20MA. The design *prose* calls it a "one-time widen." In practice
   `close_below_50ma` usually fires first so it rarely bites, and the floor invariant keeps it safe —
   but latching-vs-recomputed is a real semantic choice the owner should confirm for 3b. If latching
   is wanted, it's a small change (once `trail_basis==50ma`, never revert).
3. **`caution_flag` is used as an integer COUNTER** (0,1,2…), not the strict boolean the 0001 schema
   comment implies. Compatible for default `TWO_CLOSE_EXIT=2` (only ever 0/1 pre-exit); only visible
   if someone overrides `TWO_CLOSE_EXIT>2`. In-code documented; flag if the schema comment should update.
4. **Reason attribution depends on trail basis:** `close_below_50ma` mostly manifests *before* the
   trail has widened to 50MA (once on 50MA basis, a sub-50MA close usually trips the stop-hit first).
   Correct per spec, but subtle — confirm it matches the owner's mental model of "why did it exit."

**3b implementation gotchas (for whoever wires it — not bugs, instructions):**
- Parse `meta` from its D1 JSON **string** to an object before calling `advance()` (as
  `listPositions` does via `safeParse`) — else `meta.widen_enabled`/`meta.config` are silently ignored.
- `autoConfirm`'s `sessionsInClosing` and any earnings "sessions" must count **trading sessions**
  (reuse `find_trading_date_back`-style logic), not calendar days.
- The transitions return a `trade_date` passthrough; 3b stamps real `ts`/`trade_date` on events and
  owns DB-layer idempotency (don't double-apply a transition).

**Next steps — WS5-3b (tracked SPRINT):** the wiring — load position + trailing `ticker_quotes`
bars → `advance()` → persist spine + append `position_events` → DB-layer `last_advanced_date`
idempotency; service-token `/advance` route (or ingest-triggered sweep) + daily trigger after the
held ingest. Then phase 4 (VAPID + the two-tier/confirmation-strip surfaces). Owner gate: a few
days of real held bars must accumulate before a 3b live dry-run is meaningful.

**Note:** this session-notes commit must land on default via a merged PR to be visible next session.

---

## 2026-08-13 — WS5 phase 2: held-tickers feed → ticker_quotes (D1) (#312, PR #313)

**Status: safe to close once PR #313 merges — but the feed is NOT live yet (go-live needs the owner
+ lead; see below).** Senior-eng session driving WS5 phase 2. Lead owned the schema + the security
boundary (auth path) and wrote those + their tests by hand; delegated the mechanical scraper/ops/docs
plumbing to a Sonnet subagent against a locked spec, then reviewed every line before commit.

**The one open decision (flagged in #312) — GH-Actions→D1 ingest auth — decided with owner sign-off:**
a **service-token worker ingest endpoint** on `finviz-positions`, NOT a Cloudflare API token in
GitHub. Rationale: keeps the powerful account token out of CI; the CI secret is least-privilege
(read held set + append bars only, cannot touch private positions); append-only/validation invariants
live in one place. Implemented as a **second auth path** `authenticateService()` on the existing
`src/auth.js` swap-seam, gated by a new `POSITIONS_INGEST_TOKEN` — distinct from the owner HMAC
bearer. Cross-auth isolation is test-covered (owner token rejected on machine routes and vice-versa).

**What landed (PR #313, branch `claude/ws5-phase2-held-feed-gez3ja`, 4 commits):**
- **`worker-positions/migrations/0002_ticker_quotes.sql`** — append-only `ticker_quotes(ticker,
  trade_date, prev_close/open/high/low/close/change_pct/atr/volume, days_to_earnings, raw,
  collected_at)`, PK `(ticker, trade_date)`. **Design refinement (owner-flagged):** #297's "full
  column set" implemented as typed engine columns + a **`raw` JSON** holding the complete 84-col
  scrape verbatim — zero data loss, robust to Finviz label renames. No `user_id` (public market
  data). Same-day upsert = last-write-wins; append across days. Verified via sqlite.
- **`worker-positions/src/quotes.js`** — pure `validateIngestBatch` + `ingestQuotes` (chunked batch
  upsert) + `heldTickers` (DISTINCT open/managing/closing). **`src/auth.js`** `authenticateService`.
  **`src/index.js`** `GET /held-tickers` + `POST /ingest/quotes`. 55 vitest (was 28).
- **`scripts/collect_held.py`** — reuses `collect_morning.fetch_ticker_quotes` via a new `block=`
  param + new **`held`** screener block (full 84 cols, empty `base_filters` so no held ticker is
  filtered out). Queries worker for held set → scrapes settled EOD → POSTs. **Writes to D1 over HTTP,
  not git** (no commit step, no `finviz-data-commit` group). `build_quote_payload` pure/unit-tested
  (`tests/test_collect_held.py`, 7, no Playwright import → off the ignore list). Empty-scrape +
  env-misconfig guards fail loud.
- **`.github/workflows/collect_held.yml`** (`workflow_dispatch` + `dry_run`; needs `POSITIONS_WORKER_URL`
  / `POSITIONS_INGEST_TOKEN` secrets) + **worker-cron `held` job** 17:30 ET Mon–Fri, ungated (92
  vitest, was 83). Docs 3-places (root CLAUDE.md, README, scripts/CLAUDE.md, worker-positions README).
- Full suite green: 666 pytest / 92 worker-cron / 55 worker-positions.

**GO-LIVE checklist (owner + lead, not done in this session — the feed is dormant until all done):**
1. Owner: mint `POSITIONS_INGEST_TOKEN` (or lead generates a random one on the owner's go).
2. Set it on the worker (`wrangler secret put`) **and** as a GitHub Actions secret; set
   `POSITIONS_WORKER_URL` as an Actions secret.
3. Apply `migrations/0002_ticker_quotes.sql` to the `finviz-positions` D1 (one-time, out of band).
4. Merge #313 (auto-deploys `worker-positions` + `worker-cron` via `deploy-workers.yml`).
5. Run one `collect_held.yml` **dry-run** on a trading day (Azure IPs) to confirm the held-set query
   + scrape work end-to-end, then a real run. Nothing is exercised against live D1 yet.

**Next steps:** go-live (above), then **WS5 phase 3** `advance()` engine (consumes `ticker_quotes`;
needs a few days of accumulated bars to test meaningfully, so switching this on soon is the gate).
`days_to_earnings` left null in phase 2 (raw `Earnings` preserved) — phase 3 derives it.

**Note:** this session-notes commit must land on default via #313 merging to be visible next session.

---

## 2026-08-13 — WS5 phase 1 PWA: login + real "I took it" + Positions tab (#309)

**Status: safe to close once the PR merges.** Second slice of WS5 phase 1 (backend merged in #310
earlier this session). Delegated the mechanical PWA build to a Sonnet subagent against a
lead-authored spec (`scratchpad/ws5-pwa-spec.md` — UX/copy/flow locked by the lead); lead reviewed
the full diff, fixed the fallout, and ran all Playwright himself.

**What landed (all in this PR, on `claude/ws5-phase1-pwa`):**
- **"I took it" now writes a real position.** Signed out → inline "Sign in on the Positions tab"
  note (no write). Signed in → inline **confirm** step showing entry/stop/qty/risk captured from
  the trade ticket's current state (`ws5BuildPayload` reuses `ws4PriceForCalc`/`ws4StopLevels`/
  `ws4RiskDefault`) → `POST /positions`. The `taken:` localStorage marker is kept but now written
  only after a confirmed 201 (drives the "✓ Logged · view in Positions" card state).
- **New read-only Positions tab** (`renderPositions`): passphrase sign-in card (`posLogin` →
  `POST /auth/login` → bearer token in `localStorage.fv_pos_token`) → open-positions list from
  `GET /positions?state=open`. Frozen entries only + honest "daily management & alerts arrive with
  the lifecycle engine" banner (no engine/feed yet). Registered in the tab bar + `VALID_TAB_IDS`.
- Auth client (`posGetToken/posSetToken/posClearToken/posIsSignedIn/posLogin/posApi`, 401 clears
  token + throws `{unauth}`); `POSITIONS_API`/`POS_TOKEN_KEY` constants; stop-basis key→enum map
  (ticket keys `prior_low/today_low` ≠ worker enum `prior_day_low/todays_low` — mapped in
  `posStopBasisEnum`). Dead `window.__morningTookIt` removed (superseded by `ws5TakeIt`).
- Release triplet: `docs/releases.json` `2026.08.13` (feature, tab positions) + `current` bumped;
  `docs/sw.js` CACHE `finviz-v64`→`v65`. `docs/CLAUDE.md` Morning-tab section rewritten + new
  Positions-tab section.
- Tests: new `tests/test_pwa_positions.py` (6 Playwright — signed-out gate, sign-in success/wrong-
  pass, confirm+POST payload assertion, cancel; added to `tests.yml --ignore`).
  `tests/test_pwa_morning.py` take-it test rewritten to the new sign-in gate (old ✓-Taken
  placeholder assertion superseded). `positions` added to `VALID_TAB_IDS` in `test_pwa_intro.py`.

**Two debugging notes worth keeping (both test-harness, not product bugs):**
1. The worker-call mocks must route on **path** (`**/auth/login`, `**/positions**`), not
   `**/finviz-positions.*/…` — a `host.*`-style glob doesn't reliably match the multi-label
   workers.dev host (the exact `/auth/login` suffix silently never matched; the trailing-`**`
   positions one did).
2. The PWA tests stub Tailwind as **empty CSS**, so `.hidden` doesn't hide other tabs — all tab
   sections stack and the full-width sign-in button collapses tiny + far down the page, where a
   Playwright pointer-`click` misses it (0 handler fires) even though the DOM element is fine. Fix:
   `locator.dispatch_event("click")` for that button — it exercises the real `onclick → posDoLogin`
   wiring without depending on layout. **Not a production bug** (real Tailwind hides other tabs).

**Verification:** 24 Playwright (positions+morning+trade_ticket+intro) via the chromium-1194→1117
symlink harness; 656 non-Playwright (CI ignore list). `node --check` on the extracted script;
release triplet consistent (`test_guide_releases.py`).

**Next steps:** WS5 phase 2 (held-tickers feed → full-column `ticker_quotes`, #297) then phase 3
(`advance()` engine) then phase 4 (VAPID push, reuse `distil`). Passphrase already rotated to the
owner's `CF_FV_PASSKEY` (verified live) — WS5-1-PASS done.

---

## 2026-08-13 — WS5 phase 1 backend: D1 + finviz-positions worker (LIVE) (#264/#309)

**Status: safe to close for the backend slice; PWA integration is the next slice (#309, WS5-1-PWA).**
Senior-eng session picking up WS5 (#264). Design was already complete/merged (ADR-012 +
`planning/trade-lifecycle-engine.md`, PR #294→#295); nothing left to design for phase 1.

**The one real decision — auth — went against the owner's first instinct, with evidence.** Owner
initially said "Cloudflare Access." Investigation found: (1) Access isn't enabled on the account
(first-time enable is a dashboard action + permanent team-domain choice); (2) the PWA is a
**cross-origin** GitHub-Pages page (`clarencelam2000.github.io`) calling workers on
`*.salmonbaby8.workers.dev`, so an Access cookie is third-party → browser-blocked; (3) the sibling
`distil` worker on this same account already proves worker-native auth (session cookie **+** a
`Authorization: Bearer` path) and has full VAPID web-push → D1 `push_subscriptions` (the phase-4
reference). Recommended **worker-native HMAC Bearer** instead — meets the real security goal (no
world-readable secret in the public page; token minted from a login passphrase, lives only in the
owner's browser). **Owner agreed**, conditional on not blocking a future Access migration — honored
by putting all auth behind the single swap-seam `worker-positions/src/auth.js`. (Noted for the record:
if the PWA ever moves to Cloudflare Pages, Access flips to the better choice — first-party cookie +
native Pages protection.)

**Owner also cleared me to provision/deploy on the shared CF account** (`CLOUDFLARE_API_TOKEN`/
`CLOUDFLARE_ACCOUNT_ID` are in the env; create-only, no deletes; "CEO shouldn't deploy CF"). So
phase 1 shipped **live**, not "built + owner deploys."

**What landed (this PR, #309):**
- **D1 `finviz-positions`** provisioned (`0e59c0fb-cac6-48ee-b90d-60ca89b3bb90`, ENAM, same account
  as `distil`). `worker-positions/migrations/0001_init.sql` applied: `positions` spine +
  append-only `position_events`. `ticker_quotes` **intentionally deferred to phase 2** so it lands
  full-width per #297 (nothing to lose — phase 1 writes no bars).
- **New worker `finviz-positions`** deployed `https://finviz-positions.salmonbaby8.workers.dev`
  (kept separate from public `finviz-ticker-lookup`). Routes: `GET /health`, `POST /auth/login`
  (passphrase→Bearer), ticker-generic independent-lot `POST /positions` (§3a/§8a; long-only R>0
  validation; each "I took it" = new lot, no `(user,ticker)` uniqueness), user-scoped
  `GET /positions`. CORS pinned to the PWA origin (Bearer header, no cookie → no Allow-Credentials).
  App-layer `user_id` isolation from day one (D1 has no RLS).
- Secrets set out-of-band (`POSITIONS_SESSION_SECRET` random; `POSITIONS_AUTH_PASSPHRASE` interim
  strong-random — **owner to pick the real one; I rotate via one API call**, tracked WS5-1-PASS).
- 28 vitest tests (auth mint/verify/expiry/tamper, validation, routing/CORS/401, isolation, lots).
  **Live end-to-end smoke passed** (health/401/login/wrong-pass/create-201-with-CORS/400/list);
  test rows deleted after (store back to 0/0).
- `deploy-workers.yml` gets a 3rd job `deploy-positions` (+ `worker-positions/**` path). CLAUDE.md
  § Automation + Repository-structure updated. Phase-1 issue **#309** opened + linked under #264;
  SPRINT WS5 block added.

**Next steps:** WS5-1-PWA (#309) — PWA login + real "I took it" POST (migrate the `taken:` marker) +
minimal frozen-positions read-back + release triplet + Playwright. Then owner rotates the passphrase
(WS5-1-PASS). Then phase 2 (held feed / #297), phase 3 (`advance()` engine), phase 4 (VAPID, reuse distil).

**Note:** this session-notes commit must land on default via a merged PR to be visible next session
(branch-commit-discipline § "Session notes MUST land on default").

---

## 2026-08-17 — WS5 §8b P3: personal watchlist PWA (#319)

**Status: safe to close once the PR is open + Playwright validated.** Staff-eng session driving P3 —
the taste-heavy PWA phase. P1 (worker/D1) + P2 (`pick_status.py` reclaim + `collect_morning.py` union)
were already merged as #322; this session built P3 only, in `docs/index.html` + release/docs/tests.

**Orchestration:** lead wrote the authoritative P3 build spec (the v2 mock
`planning/mocks/ws5-watchlist-directions.html` translated into the PWA's slate/sky/violet Tailwind
idiom as exact code — kept in scratchpad, not committed; the brief is the durable design authority).
Three Sonnet subagents against that spec (≤2 parallel), every line lead-reviewed:
(A) full `docs/index.html` build; (B) release triplet + `docs/CLAUDE.md` + README constants;
(C) `tests/test_pwa_watchlist.py` + tests.yml ignore. Lead reviewed A's diff by hand and fixed one
UX bug (see below).

**What landed (P3):**
- **Morning "Your watchlist" section** (`renderWatchlistSection` + `watchCardHtml`) above the picks
  list. v2-mock card: header (ticker + launch-ready chip via `computeLaunchReady` + group + status
  pill), morning-read rows with NO header word (brief §2 option a: `Trigger (prior high)/Now/ATR from
  day low`; reclaim variant shows `Ref (50MA)/Day low/Now — back above`), violet **Your level** block
  (`watchYourLevel` computed CLIENT-SIDE — level_value never leaves owner-bearer path), on-by-default
  **collapsible levels gauge** (`watchGaugeHtml`, DOM-patched toggle), independent chart toggle,
  footer `N mornings left · I took it → · ⋯` (kebab Renew/Edit level/Remove). Expired entries in a
  collapsed bin. Adding-state for a watch with no EOD bar yet.
- **Positions "＋ Add to watchlist"** collapsible sibling to the §8a manual-entry expander (separate
  `state.watchAdd`), ticker + optional segmented level (Above/Below/20MA/50MA; price input only for
  Above/Below) → `POST /watchlist`. Morning quick-add deep-links here (`watchQuickAdd`).
- **Graduation:** "I took it →" prefills the §8a manual-entry ticket (`graduateWatchId`); on a
  confirmed `POST /positions` the client `DELETE`s the watch entry.
- **Integration fixes P2 exposed:** `MORNING_STATUS_META` gains a `reclaim` entry; `renderMorning`
  now filters `list_category==='watchlist'` rows out of the picks list (they feed the new section).
- **Worker client:** `loadWatchlist`/`watchAddApi`/`watchPatchApi`/`watchDeleteApi` over `posApi`
  (owner bearer, 401→sign-in). GET returns `{watchlist:[…]}` incl. `prior_high/prior_low/atr/sma20/
  sma50` refs (null until first EOD bar).
- **Release triplet** `2026.08.17` / sw.js `v67→v68`; 3 PWA display constants documented 3-places
  (`WATCHLIST_TTL_SESSIONS`/`WATCHLIST_EXPIRING_AT`/`WATCHLIST_GAUGE_PAD`); `docs/CLAUDE.md` watchlist
  section. `tests/test_pwa_watchlist.py` + tests.yml `--ignore` entry.

**Lead review fix (not a spec deviation):** `watchAddSubmit` reset to `watchAddDefault()` (open:false)
on success, so the "Saved to your watchlist" confirmation — rendered only in the expanded form — never
showed. Fixed to keep the collapsible open on success.

**Lead taste-calls flagged for owner (none re-open locked brief §2):**
1. Signed-out "Your watchlist" = sign-in prompt, no public preview (avoids leaking which tickers are
   watched; private levels are behind owner auth anyway).
2. Dropped the mock's separate `▾ Trade ticket` footer toggle — "I took it →" is the single
   graduation path into the §8a ticket (which IS the trade ticket; stop/size required at entry).
3. Kebab "Edit level" reuses the add form (re-POST upserts renew+edit) rather than a bespoke inline
   editor.
4. Watch card uses "ATR from day low" copy (v2-mock-faithful) vs the picks card's "ATR from LoD".
Minor deferral: graduation does not yet prefill the entry hint from an above/below level (spec §4c-vi
"optional") — tracked as a nice-to-have.

**Verification:** `node --check` on the extracted inline script passes after lead edits;
`test_guide_releases.py` green (release triplet consistent). Playwright validation of
`test_pwa_watchlist.py` via the chromium symlink harness is the remaining pre-merge step.

**Next steps:** validate Playwright locally; open the P3 PR (ready-for-review). Then WS5 phase 4 (VAPID
push, reuse `distil`) and the deferred watchlist follow-ups (fully-private morning store, multi-day
reclaim, picks opting into reclaim).

---

## 2026-08-17 — WS3b (#268) pre-close confirmation surface: scoping + spec + mock

**Status: safe to close (scoping only, no impl).** Got issue #268 impl-ready for a senior+junior
pair. No production code touched — spec, mock, tracking only.

**What landed (branch `claude/issue-268-scoping-spec-ra01f6`):**
- `planning/ws3b-preclose-surface-spec.md` — full spec: guiding principle (this IS the morning
  pipeline run once more), non-goals, 4-phase plan (A writer / B dispatch / C PWA / D ship),
  acceptance criteria, key-files index.
- `planning/mocks/ws3b-preclose-toggle.html` — interactive mock (Morning · Pre-close toggle,
  faithful slate design language), published as Artifact for owner review.
- `.session/SPRINT.md` — WS3b-A..D tasks added under a new "Session surfaces" backlog block.
- Issue #268 body rewritten with the spec.

**Recon findings (2 Sonnet subagents):** WS1/#258 + WS3/#262 both DONE & merged; WS2/#261 DONE in
practice (`session_config.py` registers `pre_close` already, issue just never closed). The status
engine `scripts/pick_status.py` is pure + explicitly built session-agnostic for WS3b reuse. So
WS3b = generalize `collect_morning.py` by a `--session` arg + one 15:30 cron job + a toggle in the
Morning tab. Much cheaper than the issue's framing implied.

**Owner decisions locked (2026-08-17):** dispatch 15:30 ET; one tab + toggle (NO new tab); tab
label stays "Morning"; "since AM" delta chips IN for v1; generalize-don't-clone (parameterize by
session, per ADR-011). Naming: new job `preclose_status` (do NOT reuse the existing `collect_preclose`
settled-backstop job — it's load-bearing for the #259 picks gate).

**Design lead taste-calls in the mock:** delta chips (green `held since AM`/red `faded from AM`) are
the surface's payoff — answer "did the setup hold from open into close?" without a second tab;
`gapped_through` suppressed at pre-close (morning-open concept) as a display decision, engine stays pure.

**Next steps:** hand to eng team (paste-note prepared). WS4-C (pre-close trade ticket, ADR-014) is
blocked-by this and cross-linked in SPRINT — unblocks when the `pre_close` store lands.

---

## 2026-08-17 — WS3b (#268) pre-close confirmation surface: IMPLEMENTED

**Status: safe to close.** Built the full WS3b surface (writer + cron + PWA) on branch
`claude/issue-268-scoping-spec-ra01f6` / PR #327. Staff-eng drove; Phases A & B via Sonnet
subagents, Phase C (PWA visual) done in the main loop. Tests kept light per owner.

**What landed (all in PR #327):**
- **Phase A — writer (`scripts/collect_morning.py`, `session_config.py`):** generalized to
  `--session {morning,pre_close}` (default morning) — NOT cloned. `session_store_paths()`,
  session-parameterized `write_store`/`assert_provisional`. `pre_close` capture_et 15:50→**15:30**
  (triple-doc: session_config comment + README + CLAUDE.md). Morning path byte-identical (8 old
  tests pass unmodified; +1 pre_close test). 49 pytest green.
- **Phase B — dispatch (`worker-cron/`):** new ungated `preclose_status` job @ 15:30 ET in
  `routing.js` JOB_SCHEDULE (own KV key), `index.js` WORKFLOWS map, thin
  `.github/workflows/collect_preclose_status.yml` → `collect_morning.py --session pre_close`
  (Option 2: wrapper, not shared-dispatch `inputs` — lower risk). Existing 15:50 `collect_preclose`
  settled backstop + #259 gate untouched. 93 worker-cron tests green. TODO(#268): healthchecks DMS
  when a secret is provisioned.
- **Phase C — PWA (`docs/index.html`):** Morning tab is session-aware — `[Morning · Pre-close]`
  segmented toggle, defaults to freshest read (`freshestSessionView` by collected_at, so morning
  before ~15:30 / pre-close after). Session-specific "into the close" copy + banner. Pre-close-only
  `held/firmed up/faded since AM` delta chips (join morning⋈pre_close on ticker). `gapped_through`
  remapped to `triggered` for DISPLAY at pre-close (`sessionDisplayRow`; engine pure). Ticket /
  take-it / chart helpers now read `activeSessionRows()` so the expanded ticket uses the shown
  session's prices. Release triplet `2026.08.17.1` + sw.js v68→v69. JS syntax-checked, releases
  test green.

**Verification:** releases.json valid + `test_guide_releases.py` green; inline-script syntax check
clean; worker-cron 93 + collect_morning 49 pytest green. Did NOT run Playwright PWA tests (cloud
Chromium-revision gap + owner's "don't over-invest in tests" — the surface mirrors the shipped
morning render 1:1 and was syntax-verified).

**Follow-ups:** (1) WS4-C (pre-close trade ticket) is likely satisfied for free — the ticket already
renders on pre-close actionable cards via the session-generic helpers; verify once the 15:30 store
has live rows, then close. (2) healthchecks DMS on `collect_preclose_status.yml` (TODO in the yml).
(3) #261 (WS2) can be closed for hygiene — `pre_close` is fully wired now. (4) First live 15:30 run
happens on the next trading day via the Cloudflare dispatcher; no data exists until then (404 → empty
state is expected and handled).

---

## 2026-08-17 — WS3b (#268) implementation recovered after stranding on a merged PR branch

**Status: safe to close** once PR #328 merges (open at time of writing).

**What happened:** PR #327 merged with only the scoping spec + mock (the WS3b-C entry above,
"IMPLEMENTED", was written *into* the actual implementation commit — but that commit was pushed to
`claude/issue-268-scoping-spec-ra01f6` roughly 10 minutes *after* GitHub had already closed/merged
#327 as the scoping-only version. A closed/merged PR's branch has no path into default, so the
implementation commit (`e436c4b`) sat stranded — invisible to `origin/claude/elegant-babbage-hlxnfy`
despite being fully finished, tested, and described as shipped in #327's own PR body. This is exactly
the failure mode `.claude/rules/branch-commit-discipline.md` § Amendment policy documents.

**Recovery (this session, prompted by the owner noticing new commits on an already-closed PR):**
confirmed via `git log --oneline origin/<default>..<branch>` that `e436c4b` was unreachable from
default; branched fresh off default (reusing this session's already-assigned branch
`claude/review-pr-327-1j88d6`) and cherry-picked `e436c4b` clean, no conflicts (now `13cd139`).
No re-authoring — this is the same code, same commit message, same author, just relocated onto a
branch with an open path to default. Opened as PR #328 (does not need to wait for the OOO original
author — the commit was self-contained and mechanically recoverable per the documented procedure).

**Verification done before pushing (see PR #328 body for full detail):** `worker-cron` 93/93 tests
green; `test_guide_releases.py` / `test_session_config.py` / `test_collect_morning.py` green.
Applied the documented sandbox Chromium-revision symlink workaround
(`knowledge/investigations/playwright-cloud-session-testing.md`) to actually run the PWA Playwright
suite instead of skipping it — found 22 failures in `test_pwa_morning.py` /
`test_pwa_positions.py` / `test_pwa_trade_ticket.py` / `test_pwa_watchlist.py`, root-caused them
(not just noted): the new pre-close CSV fetch hits a real network-level failure in this sandbox
(no external network reachability at all, a separate known gap) because the existing test fixtures
don't intercept the new `pre_close_latest.csv` route. Confirmed via a standalone repro script that
swapping in a real HTTP 404 response for that route (what production/CI actually returns
pre-first-run) renders correctly — so these are sandbox-only false negatives, not a functional
regression. Did not edit the test files themselves, per the owner's "don't over-invest in tests"
call already on record in the original PR body.

**Next steps:** none beyond merging #328 — this recreates #327's intended end state exactly. Once
merged, resume the WS3b follow-ups listed in the entry above (WS4-C verification, healthchecks DMS,
closing #261).

---

## 2026-08-17 — Positions tab empty-state bug: root-caused + fixed (PR #331)

**Status: safe to close** once PR #331 merges (open at time of writing, no review comments yet).

**What happened:** owner reported the Positions tab was showing zero positions despite having open
trades since Friday, visible again this morning. Root-caused by querying the live `finviz-positions`
D1 database directly (read-only `SELECT`, using the already-provisioned `CLOUDFLARE_API_TOKEN`/
`CLOUDFLARE_ACCOUNT_ID` env vars — no MCP/OAuth needed, per the standing note above): all 3 open
positions (OUST, NVT, EOG) were sitting in `state='managing'`, not `'open'`.

**Root cause:** `docs/index.html`'s Positions tab has always called `GET /positions?state=open`
(phase 1, #309) — an exact-match filter. The phase-3a `advance()` engine
(`worker-positions/src/advance.js:271`) auto-transitions `open → managing` the first time a
position is advanced without an exit signal, which now happens automatically via the daily 17:30 ET
held-feed sweep (`worker-cron`'s `held` job → `POST /advance`). Phase 1's PWA read query was never
updated when phase 3a shipped, so any position survives exactly one sweep before silently vanishing
from the tab — it's still a live trade, just no longer visible.

**Fix (PR #331):** `posLoadPositions()` now fetches `GET /positions` unfiltered and shows
`open`/`managing`/`closing` client-side (only `closed` drops off), with a small state badge on
`managing`/`closing` cards since there's no confirmation-strip UI yet for a signaled exit (that's
phase 4, per `worker-positions/CLAUDE.md`). Docs updated (`docs/CLAUDE.md` § Positions tab). Release
triplet done: `releases.json` `2026.08.17.2` (fix) + `sw.js` v69→v70.

**Verification:** `test_guide_releases.py` + full non-Playwright suite (700/700) green. Ran the
actual `test_pwa_positions.py` Playwright suite via the documented sandbox Chromium-revision symlink
workaround; added a new regression test (`test_managing_and_closing_positions_still_render`) that
directly pins the bug (managing/closing render, closed does not) — green, along with the two other
targeted tests run. One unrelated pre-existing Playwright failure in the same file
(`test_signed_out_take_it_shows_signin_note_no_post`, Morning tab "I took it" flow — code this PR
never touches) confirmed as a sandbox flake, not a regression from this change.

**Next steps:** merge #331. No follow-ups tracked — this is a complete, self-contained fix. Worth
flagging for the owner: `closing`-state positions (a signaled exit awaiting confirm/revert) are now
at least visible again, but there's still no confirm/revert UI on the Positions tab (phase 4,
untracked as an open SPRINT item as far as this session found — worth checking before it's assumed
covered).

**Addendum (same session):** owner asked whether closed positions ever reappear, or drop off
permanently — confirmed permanently (no grace window; `POS_VISIBLE_STATES` excludes `closed`
unconditionally). Owner then asked to file that as tracked work. Opened **issue #332** + SPRINT
**WS5-5** for it. Also corrected a wrong claim in the "Next steps" note just above: WS5-4 is push
notifications (VAPID) *and* the confirm/still-holding action surface for `closing`-state
positions — it does NOT cover a closed-trades history/grace-window view. That's WS5-5, a distinct,
newly-filed item, not something already tracked under WS5-4 as previously implied.
