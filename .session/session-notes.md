# Session Notes

> **Future Claude:** read this immediately at session start. Summarize the current state for the user before doing anything else.
>
> **Format:** Append a new `---` delimited block per session. Header = date + workstream description. Keep the last 4 sessions here; a human will periodically move older entries to `.session/archive/session-notes-archive.md`. Do NOT replace existing entries — append only.

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
