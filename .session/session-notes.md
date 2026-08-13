# Session Notes

> **Future Claude:** read this immediately at session start. Summarize the current state for the user before doing anything else.
>
> **Format:** Append a new `---` delimited block per session. Header = date + workstream description. Keep the last 4 sessions here; a human will periodically move older entries to `.session/archive/session-notes-archive.md`. Do NOT replace existing entries — append only.

---

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

## 2026-08-13 — #259 token-read-scope verification closed

**Status: safe to close.** Follow-up to the 2026-08-07 WS1 picks-gate entry, which flagged
"token read-scope risk is mitigated by setup docs, not proven live" as the one thing that
session couldn't verify from a sandboxed dev environment. Owner asked for a quick verify of
both #259 review findings; checked live `GET /last` on the deployed worker.

**Confirmed live (2026-08-12 ET):**
- `picks_gate_check`: `{"outcome":"dispatch","reason":"eod_run_success"}` at 21:05 UTC, fired
  within one tick of `collect_eod`'s 21:00 UTC dispatch — `GITHUB_DISPATCH_TOKEN` successfully
  read `collect.yml/runs` (no `github_401`/`github_403`). Token-read-scope question from the
  2026-08-07 entry is settled: the PAT's grant covers both the dispatch POST and the runs GET.
- `findEodRun`'s disambiguation also confirmed against real traffic: `collect_preclose` (19:50
  UTC) and `collect_eod` (21:00 UTC) both dispatched today, and the gate matched the EOD run
  specifically (not the earlier pre-close run) before dispatching `picks`.

No code change needed — both #259 review findings are implemented and working in prod. This
entry just closes the verification loop the 2026-08-07 entry left open.

---

## 2026-08-12 — PR #306 review follow-up: overhead-penalty test coverage + stale-52W-High handling

**Status: safe to close, pushed to PR #306's branch.** Addressed review feedback on the Phase 2
overhead-supply penalty (see prior entry below) before merge.

**What landed:**
- **Test coverage gap closed.** `overhead_penalty_frac()` in `scripts/replay_picks.py` had no
  direct unit tests (unlike its siblings `liquidity_penalty_frac`/`earnings_penalty_frac`, which
  each have ramp-boundary/midpoint/NaN tests) and no fixture exercised `_replay_focus`'s v4 branch
  end-to-end (both existing fixtures predate the 2026-08-12 v4 effective date and lack a `52W High`
  column). Added `TestOverheadPenaltyFrac` (ramp start/end/midpoint, dash/None/NaN) and a new
  `tests/fixtures/replay_picks_v4_fixture.csv` + `TestReplayV4Fixture` driving the full pipeline.
- **Owner-flagged edge case: Finviz can report a positive '52W High'** (data lag — price already
  broke to a new high before Finviz's stored 52-week high catches up; owner has observed this
  live). Checked both P1 (`computeLaunchReady`, PR #303) and P2 (this PR's overhead penalty): the
  math in both was **already graceful** — `ohMag = -parse('52W High')` goes negative in that case,
  and both the chip's `ohMag <= LAUNCH_NEAR_HIGH_PCT` checks and the penalty's
  `Math.max(0, Math.min(1, t))` / Python `max(0.0, min(1.0, t))` clamp already floor that to
  "near-high, 0 penalty" — the semantically correct read (a stock above its old high has no
  overhead supply). No functional fix needed. What *was* wrong: the methodology JSON's note
  claimed `52W High` is "always <= 0", which is inaccurate and could mislead a future edit into
  breaking the clamp. Corrected that note plus added explicit comments at both clamp sites
  (`docs/index.html` computeLaunchReady + overheadPenaltyFrac, `replay_picks.py`
  overhead_penalty_frac docstring) documenting this is intentional handling, not incidental.
  Added `test_positive_value_from_stale_finviz_data_is_zero_not_negative` +
  `test_deeply_positive_value_still_zero_penalty` (pure-function) and
  `test_stale_finviz_high_treated_as_near_high_not_penalized` (fixture, STALEHIGH ticker) to lock
  this in as regression coverage.
- 659/659 non-Playwright tests pass (648 baseline + 11 new).

**Not done (scoped out):** no new Playwright test added for `computeLaunchReady`'s positive-value
case — P1 has no existing Playwright/JS-level test coverage at all (chip rendering was verified
manually per PR #303), and the math needed no fix, only a doc correction, so this was judged
lower-value than the P2 fixture/unit tests. Flagging here in case a future session wants to close
that pre-existing gap.

---

## 2026-08-12 — Overhead-supply signal (Picks chip + Focus penalty)

**Status: Phase 2 in review (new PR after a stranded-commit fix); Phase 1 merged.** Owner-driven feature: integrate overhead supply (trapped sellers above price) into Picks/Focus.

**Design (agreed with owner over several rounds):** Overhead supply ≈ distance below 52-week high (`52W High` column, signed %). Separate axis from short-term froth (`atr_ext_50`). The product thesis is the **intersection**: "near the high but not vertical." An early "headroom" framing was scrapped (owner caught a sign error — more distance below high = *more* overhead = worse, not better).

**What landed:**
- **Phase 1 (PR #303, MERGED):** display-only Launch-ready chip per Picks row — `computeLaunchReady()`, Coiled / Extended / Overhead, `LAUNCH_*` constants. Owner confirmed the chips render.
- **Phase 2 (new PR, in review):** Focus-score overhead penalty `score *= (1 − overheadPen)`, `overheadPen = 0.20 × clamp((ohMag−8)/(30−8),0,1)`. Mirrored across the triplicated contract — `docs/index.html` (both n=1 and main paths), `scripts/replay_picks.py`, `display_methodology.json` v4 — anti-drift guard updated. Cap held at conservative 0.20 (tiebreaker, not veto); raising to 0.30 is deferred (OVERHEAD-3).

**Process failure + fix (important):** Phase 2 was pushed onto the #303 branch **after** #303 was already merged → the commit was stranded (feature branch has no path into default). Root cause: did not re-fetch default before starting Phase 2, and treated session-notes/SPRINT tracking as optional. Corrected: rebased Phase 2 onto latest default, opened a new PR. **Two new hard rules written into root `CLAUDE.md`:** (1) sync/fetch before *every* new work phase and confirm the target PR is still open before pushing follow-ups; (2) session-notes + SPRINT + issue tracking are mandatory inside the PR — never ask, never defer.

**Deferred (all tracked):** OVERHEAD-3 (0.20→0.30 bump), Lookup surfacing (GH #304 / OVERHEAD-4), Morning surfacing (GH #305 / OVERHEAD-5).

**Next:** get the Phase 2 PR merged; watch the Focus reshuffle for a few sessions before the 0.30 bump.

---

## 2026-08-11 — Picks chart height + Morning tab TradingView charts

**Status: safe to close, PR open.** Small self-contained UI request from the owner.

**What landed:**
- `tradingViewChartHtml(ticker, 560)` — Picks tab's per-pick TradingView embed doubled from
  280px to 560px tall (both the initial render and the DOM-patch toggle in `__togglePickChart`).
- Morning tab cards get the same click-to-expand chart affordance as Picks, reusing
  `tradingViewChartHtml()` verbatim. New `morningChartAffordance(ticker)` +
  `window.__toggleMorningChart(ticker)` mirror `__togglePickChart`'s DOM-patch pattern (no full
  `renderMorning()` re-render on toggle). New `state.morningChartOpen` Set persists open/closed
  chart state across re-renders — keyed by ticker alone (morning rows are one-per-ticker, unlike
  Picks' `ticker_category` composite key, so no `expandKey` needed).
- Release surface: `docs/releases.json` (`2026.08.11`, tag `improvement`) + `docs/sw.js`
  `CACHE` bumped `v61` → `v62`, same PR per the hard rule.

**How it was verified:** `python3 -m pytest tests/ -q` (excluding the documented Playwright
ignore list) — 632 passed, no regressions; `test_guide_releases.py` (5 passed) confirms the
release/cache sync. Also ran the *actual* Playwright suite in-sandbox via the documented
`chromium-1117 → chromium-1194` symlink workaround (see
`knowledge/investigations/playwright-cloud-session-testing.md`) — `test_pwa_morning.py`,
`test_pwa_trade_ticket.py`, `test_pwa_picks_chart.py` all pass (18/18) against the changed code.
Additionally ran an ad hoc script against a live-rendered Morning tab: 5 chart-toggle buttons
render, clicking one injects a TradingView iframe with `style="height:560px;"`. Symlink removed
after — session-local only, never committed.

**Next steps:** none — this was a complete, narrow request. No deferred items.

---

## 2026-08-08 — WS3 Phase A: morning status engine + provisional store (#262)

**Status: safe to close once PR #281 merges.** Senior-eng session driving WS3 forward on the
staff ADR-013 guidance (PR #280). Reviewed the staff guidance against the code first —
**it's congruent and complete; all 7 junior questions genuinely closed.** Two senior flags,
neither blocking: (1) owner's "missing earnings?" concern is *resolved not a gap* — WS3 status
math needs only price/open/high/low + prior trigger/stop/atr, all already on the EOD pick row;
earnings is WS4's ticket, so the narrow 9-col morning set is correct. (2) The one real unknown
is whether Finviz screener High(87)/Low(88) are *today's intraday* at 9:45 ET — `failed_breakout`
+ ATR-from-LoD depend on it; unverifiable from cloud, correctly deferred to Phase B's dry-run
(ADR-013 § Decision 2, `quote.ashx` fallback documented).

**What landed (PR #281, Phase A):**
- `scripts/pick_status.py` — pure, session-agnostic status engine (`compute_pick_status`
  top-down precedence per ADR-013 Decision 3; `compute_atr_from_lod`; `STATUS_PRECEDENCE`;
  `ACTIONABLE_STATUSES`). WS3b (#268) reuses verbatim.
- `scripts/collect_morning.py` — writer skeleton: shared `fetch_ticker_quotes` (batch ≤50,
  `&r=` pagination reusing `probe_picks`), pure `load_pick_levels`/`build_status_rows`,
  `write_store` (last-write-wins `(date,ticker)`) gated by `assert_provisional("morning")` —
  first real call site of the WS2 guard. Non-trading-day exit-0 (NOT collect's rollback) +
  stale-input guard + `--dry-run` hook for Phase B.
- `data/picks/sessions/morning{,_latest}.csv` store (committed, public data per Decision 4).
- `morning` block in `screener_config.json` (9 cols, empty filters, matches owner's sample link).
- Tests: `tests/test_pick_status.py` (15), `tests/test_collect_morning.py` (18); full suite
  632 passed, no regressions. Neither test file needs the Playwright ignore list (lazy imports).
- Docs: README § Configurable parameters + scripts/CLAUDE.md WS3 subsection (3-places rule).

**Delegation:** Phase A mechanical build done by a Sonnet subagent against a main-model spec
derived from ADR-013; main model reviewed all code (precedence, guards, tz/dep checks) before commit.

**Next steps:** Phase B (Sonnet — live scrape wiring + `collect_morning.yml` dry-run-first +
ungated 09:45 ET `collect_morning` job in `worker-cron/routing.js` + KV/tests), then Phase C
(lead owns markup vs `planning/mocks/trade-lifecycle-surfaces.html` + release triplet).

**Phase B (also this session, same PR #281):** shipped the scrape workflow +
scheduled job. `.github/workflows/collect_morning.yml` (`workflow_dispatch` + `dry_run`
boolean input, default false; shared `finviz-data-commit` concurrency; commits only
`data/picks/sessions/`). `worker-cron`: new **ungated** `collect_morning` job at 09:45 ET
Mon–Fri in `JOB_SCHEDULE` (no dependency gate — yesterday's picks already exist at dispatch;
`collect_morning.py` stale-input guard covers failure), `morning` endpoint in `WORKFLOWS`.
worker-cron `npm test` 83 passed (12 new). No new Cloudflare *trigger* (rides the single
`*/5` tick — stays under the 5-trigger limit). No `schedule:` backstop/healthcheck yet
(deferred, documented in workflow header). **Senior staging call:** merging auto-deploys the
worker (cron live next trading day) and GitHub only surfaces `workflow_dispatch` on default,
so the workflow defaults to a real run and the owner runs one manual `dry_run=true` on a
trading day post-merge to confirm intraday High/Low freshness at 9:45 ET (the one
unverifiable-from-cloud item; `quote.ashx` fallback in ADR-013 Decision 2). Low blast radius
(store is provisional). **Only Phase C (PWA surface, lead owns taste) remains.**

---

## 2026-08-08 — WS3 staff guidance: ADR-013 closes all open decisions (#262)

**Status: safe to close once PR merges.** Staff-eng session (docs only, no product code).
Senior-eng WS3 assessment raised 7 open decision points; verified their findings against the
repo/issues myself and closed **all of them** in
**`knowledge/decisions/ADR-013-ws3-morning-status.md`** — read that first, it is now the
implementation spec for #262 (and by reuse #268). Roadmap § WS3 links it.

**Decisions locked (headline):** state-machine predicates with explicit top-down precedence
(no_quote → invalidated → gapped_through → triggered → failed_breakout → setting_up;
Invalidated on `price <= stop`, whipsaw deferred); committed store `data/picks/sessions/
morning{,_latest}.csv` keyed (date, ticker) with a `session` column + `assert_provisional()`
at the write boundary; quote scrape = screener `&t=` ticker filter, **batched ≤50** (225
unique tickers/day — batching is required, senior eng missed the count), narrow 9-column
`morning` block in `screener_config.json`, shared `fetch_ticker_quotes()` for WS3b/WS5;
"I took it" ships as a **localStorage marker** (not a dead stub, not omitted); 3 PRs
(A engine+store, B scrape+cron 09:45 ET ungated, C PWA vs mock + release triplet); no
separate design-review gate — the ADR is the design doc.

**Corrections to the senior-eng report:** #268 already exists (their Q7 moot); screener
config lives at `data/picks/screener_config.json` not `scripts/`; morning runs must **skip**
non-trading days (exit 0, no write) — do NOT copy `collect.py`'s `trading_date()` rollback;
also guard that `picks_latest.csv`'s max date is strictly before today's ET date.

**Owner verification aid** (owner said assume `t=` works; this confirms field shape):
`https://finviz.com/screener.ashx?v=151&t=ABNB,ACIW,ADBE,ADIG,ADP,ADSK,AER,AG&c=1,81,86,87,88,65,66,49,67`
— should render Ticker/Prev Close/Open/High/Low/Price/Change/ATR/Volume. Phase B's first
slice is a `workflow_dispatch` dry-run on Actions (Azure IPs) before enabling the cron.

**Next steps:** implement Phase A per ADR-013 § Decision 6 (Sonnet subagent against the ADR;
`scripts/pick_status.py` pure engine + `collect_morning.py` writer + tests). Then B, then C
(lead owns Phase C markup against the mock).

---

## 2026-08-07 — WS1 follow-up: picks dependency gate + self-heal (#259)

**Status: safe to close.** Implemented #259 — the last piece of ADR-010's "dependency-driven
dispatch" — right after WS1 (#258/PR #269) merged. Entry point was the roadmap's "START HERE"
front door → alignment § 10 → ADR-010 → `planning/cron-consolidation-state-machine.md` →
issue #259 (incl. its staff-review comment) → mocks (not applicable, no UI surface for WS1/#259).

**What landed:**
- `worker-cron/src/picksGate.js` (new) — pure decision logic, no I/O: `findEodRun(runs,
  dispatchTs)` disambiguates the EOD collect.yml run from the earlier same-day pre-close run
  (the #259 review's finding #1 — "most recent run succeeded" can be satisfied by the wrong
  run), `isTerminalTick` / `evaluatePicksGate` decide `dispatch`/`waiting`/`miss` per tick.
  `PICKS_GATE_WINDOW_MINUTES = 120` (17:00–19:00 ET).
- `worker-cron/src/routing.js` — picks' `JOB_SCHEDULE` entry now targets 17:00 ET (same as
  `collect_eod`, not a fixed 18:31/18:30 margin after it) with the 120-min gate window, marked
  `gated: true`.
- `worker-cron/src/index.js` — new `fetchEodRun` (GET `collect.yml/runs`, reusing
  `GITHUB_DISPATCH_TOKEN`) and `runPicksGate` (reads `last_dispatch_collect_eod` KV, calls
  `fetchEodRun`, evaluates the gate, writes every check outcome to `last_gate_check_picks` KV,
  dispatches picks only on a confirmed EOD success). `scheduled()` branches on `job.gated` to
  call `runPicksGate` instead of `dispatchJob` directly for picks. `/last` now also surfaces
  `picks_gate_check`.
- Fails closed: a GitHub API read failure (auth/network) is treated as "not yet satisfied," never
  as a green light — picks never fires on an unverifiable check.
- Tests: `worker-cron/test/picksGate.test.js` (new, 19 tests, no network) + updates to
  `worker-cron/test/index.test.js` (new "picks dependency gate" describe block, 8 tests covering
  wait/dispatch/miss/disambiguation/fetch-failure) and `worker-cron/test/routing.test.js`
  (existing collect_eod-window tests updated since picks now shares its 17:00 target). 70/70 pass.
- Docs (3-places rule): in-code comments in `picksGate.js`/`routing.js`/`index.js`; new
  `worker-cron/README.md` § Picks dependency gate + § Token read scope + updated Configurable
  parameters table; `CLAUDE.md` § Automation updated; `.github/workflows/collect_picks.yml`
  header comments updated to stop describing the retired fixed-margin behavior.

**Two non-obvious things worth flagging:**
1. **Token read-scope risk is mitigated by setup docs, not proven live.** `wrangler.toml`'s setup
   comment says the PAT was provisioned with "Actions: Read and write," which per GitHub's
   permission model should cover the new GET as well as the existing dispatch POST — but this
   session had no way to exercise the real deployed token against the real GitHub API (sandboxed,
   no live secrets). **Owner: after deploying, check `GET /last`'s `picks_gate_check` — if
   `reason` ever shows `run_status_fetch_failed:github_401` or `github_403`, the token needs a
   scope fix/rotation.** The design fails closed either way (never dispatches on an unverifiable
   read), so the failure mode is "picks stays gated, GitHub backstop still covers it" rather than
   a wrong dispatch — but it's the one thing I couldn't fully verify.
2. **`session-notes.md`'s actual convention is newest-entry-at-top**, not literally "append" as
   the file's own header text says (confirmed by checking where PR #269's WS1 entry landed — right
   after the header, not at the bottom). This entry follows that established practice, not the
   literal instruction text; flagging the mismatch in case it's worth fixing the header wording
   itself sometime.

**Also ran the requested `curl .../last` health check** (see PR body / chat) — `collect_preclose`,
`collect_eod`, and `picks` all showed fresh 2026-08-07 dispatch records under the new per-job KV
keys before this session's changes were deployed, confirming #258/PR #269 is live and healthy.
No action needed there.

**Next steps:** deploy this PR (`cd worker-cron && npm run deploy`), then watch `GET /last`'s
`picks_gate_check` over a few trading days to confirm the gate fires cleanly (ideally `dispatch`
within a tick or two of `collect_eod` landing, not riding out the full 120-min window) and to
settle the token-read-scope question above. After that, WS2 (session dimension, ADR-011 Option C
already decided) is next per the roadmap.

---

## 2026-08-07 — Daily Snapshot failure investigation: Finviz "Change %" rename

**Status: safe to close.** User asked to investigate 3 failing Daily Snapshot runs today
(19:50, 20:23, 21:00 UTC) and whether they were related to recent PRs (#269 WS1 cron
dispatcher, #267 docs, #257 docs).

**Root cause (confirmed via WebFetch against live Finviz):** Finviz renamed the daily-change
column/label from `"Change"` to `"Change %"` on both the groups table
(`finviz.com/groups?g=sector|industry`) and the SPY quote page (`finviz.com/stock?t=SPY&p=d`),
some time today. `scripts/collect.py`'s `HEADER_MAP` and `SPY_LABEL_MAP` only recognized the
old `"Change"` label, so: (1) the groups table's `change` column silently dropped (logged as
`[warn] Unknown headers (will be dropped): ['Change %']`, sector/industry row counts
unaffected), and (2) `collect_spy()`'s parse-completeness guard (added 2026-06-20, by design)
correctly caught only 6/7 perf values and raised, exiting `collect.py` non-zero — which is why
CI went red on all 3 runs despite `data/sectors|industries/snapshots.csv` being written fine
each time (last-write-wins commits succeeded via `if: always()`). Verify/compute_deltas/
evaluate_picks were skipped on all 3 runs since they lack `if: always()`.

**Ruled out the recent PRs:** `scripts/collect.py` was last touched 2026-06-21 — none of
#269/#267/#257 touch it. Separately verified the 3 runs firing within ~70min today
(preclose@15:50 ET, GitHub-cron backstop@~19:48 UTC drifted late, EOD@17:00 ET) is the
existing, expected multi-trigger pattern (same shape seen on prior successful days like
2026-08-05) — not a WS1 dispatcher regression.

**Fix:** added `"Change %"` as an accepted alias alongside `"Change"` in both `HEADER_MAP` and
`SPY_LABEL_MAP` (`scripts/collect.py`). Added regression tests:
`test_collect_parsing.py::test_change_pct_header_accepted`,
`test_collect_benchmark.py::test_change_pct_label_accepted`. Full suite: 637 passed.

**Next steps:** none required from this session — PR fixes the label immediately. No SPY
benchmark row exists yet for 2026-08-07 (all 3 attempts failed before writing); once this PR
merges, the next Daily Snapshot dispatch (or a manual `workflow_dispatch`) should backfill it.

---

## 2026-08-07 — WS1 implementation: single-tick cron dispatcher (#258)

**Status: safe to close** (see caveat on deploy below). Implemented WS1 from
`planning/roadmap-cron-lifecycle.md` — the first coding step of the cron→trade-lifecycle
roadmap, on the owner's go-word recorded in the alignment doc § 10 and issue #258's comments.
Entry point was the roadmap's "START HERE" front door (not #257, which is superseded) →
alignment § 10 → ADR-010 → `planning/cron-consolidation-state-machine.md` → issue #258 (incl.
its staff-review comment) → the mocks (not applicable to WS1, no UI surface).

**What landed:**
- `worker-cron/src/routing.js` (new) — pure, I/O-free routing: `computeEtNow(date)` (ET
  wall-clock via `Intl.DateTimeFormat`, auto-DST — no more twice-yearly manual edit),
  `JOB_SCHEDULE` (3 jobs: `collect_preclose` 15:50 ET, `collect_eod` 17:00 ET, `picks` 18:30 ET,
  all shifted from the legacy `:48`/`:01`/`:31` minutes onto the new 5-minute tick grid),
  `jobsInWindow(etNow)`, and `jobsForTick(etNow, dispatchedToday)`.
- `worker-cron/src/index.js` — rewritten around the new routing module. `scheduled()` now:
  (1) computes `etNow` from `event.scheduledTime`, (2) does a **zero-I/O** check
  (`jobsInWindow`) — if nothing's in-window, returns immediately (no KV read, no fetch, no
  log), (3) only for in-window jobs, reads each job's `last_dispatch_<jobName>` KV record to
  build `dispatchedToday`, (4) calls `jobsForTick` and dispatches whatever comes back.
  `dispatchWorkflow` → `dispatchJob(env, jobName, workflow, etDateStr)`, KV keyed per job name
  (not per workflow — `collect_preclose`/`collect_eod` share the `collect` workflow but must
  track "dispatched today" independently, or the pre-close dispatch would wrongly suppress the
  EOD one). Removed `workflowForCron`/`PICKS_CRON`/`dispatchCollect` (obsolete exact-cron-string
  routing).
- **Folded in the #258 staff-review amendment**: don't match ticks by exact-minute equality — a
  delayed/skipped Cloudflare tick would silently drop that day's job with nothing to retry.
  Instead a job is due whenever the tick falls in `[target, target+30min)` ET **and** has no
  successful dispatch recorded for today's ET date — self-healing, one mechanism (not a separate
  one for the #259 picks gate later).
- `worker-cron/wrangler.toml` — single trigger `crons = ["*/5 * * * *"]`, replacing the 3
  per-job cron strings; DST comment block removed (no longer applicable).
- Tests: `worker-cron/test/routing.test.js` (new, 21 tests) — ET/DST calc incl. both 2026
  transition days verified against real `Intl.DateTimeFormat` output (not hand-derived),
  Friday-23:55-ET-is-Saturday-UTC and Sunday-night-is-Monday-UTC boundary cases, full window/
  self-heal table. `worker-cron/test/index.test.js` — rewritten for the new `dispatchJob`/
  `scheduled()` contract (24 tests). All 45 pass (`npm test` in `worker-cron/`).
- Docs (3-places rule): in-code comments in `routing.js`; `worker-cron/README.md` rewritten
  (design section + Configurable parameters table); `CLAUDE.md` § Automation updated to describe
  the single-trigger design and current job list; `.github/workflows/collect_picks.yml` comments
  updated to stop citing the retired fixed `31 22 UTC` cron string.

**Explicitly out of scope (per issue #258's own scope line and the roadmap):** the picks
dependency gate against `collect.yml`'s actual run state (#259) — `picks` still fires on a fixed
ET time target here, just via the new self-healing mechanism instead of the old exact-match one.
Also out of scope: WS2+ (session dimension and everything downstream).

**Not done in this session (operational, not code):** the design doc's rollout steps 3–5 —
running the new routing in parallel with the old 3 triggers in production for a few trading days
before cutting `wrangler.toml` over, and confirming the 2 freed trigger slots on the Cloudflare
dashboard. This PR ships the code in its final single-trigger form directly (matches issue
#258's acceptance criterion "3→1 trigger cut confirmed on the CF dashboard") since a real
multi-day production comparison isn't something a coding session can execute — **the owner
should deploy (`cd worker-cron && npm run deploy`) and then confirm on the CF dashboard that
exactly 1 trigger shows for `finviz-cron-dispatcher`.**

**Next steps:** #259 (picks dependency gate + self-heal, replacing the fixed-margin `picks` job
time), then WS2 (session-dimension ADR-011 Option C, already decided) per the roadmap sequencing.

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

## 2026-08-09 — WS4 trade tickets (design gate: ADR-014 + approved mock)

**Status:** Phase A landed on branch `claude/ws4-gh-issue-263-qkzq16`; Phase B (PWA build) delegated
to a Sonnet subagent under main-model direction. Safe to close after Phase A PR merges; Phase B is a
follow-up PR.

**Staff read that reshaped WS4 (all confirmed against code):**
- WS3 is fully shipped (A/B/C, #281/#282/#285). WS4 is **not a new surface** — it's the expansion of
  the shipped WS3 morning pick card into a full trade ticket.
- `atr_from_lod` already computed + stored by WS3 (`collect_morning.py`/`pick_status.py`) at bands
  **0.8/1.0** (owner-set 2026-08-08; ADR-013's 1.0/1.5 already superseded). WS4 inherits it — NOT a
  new `picks_metrics.py` EOD column.
- Entry-trigger `status` also already computed by WS3.
- Earnings is re-derivable from the `Earnings` column already in `picks.csv` + existing JS parse — no
  Python port, no `days_to_earnings` column.
- **Net: WS4 has essentially no backend work.** The earlier "delegate backend to Sonnet" plan
  (add `atr_from_lod` METRICS_COL + earnings port) was cancelled as dead weight.

**Owner decisions this session (folded into ADR-014):**
- Ticket is **live-first, one render state** — the stray "EOD" mock label was an error, dropped.
- Price is **snapshot-labeled + user-overridable** (localStorage); no live feed yet → #287 (Alpaca).
  No minute-precise trigger timestamp (twice-daily snapshot cadence can't support it).
- **Two** don't-chase gates: ATR-from-LoD (intraday, 0.8/1.0) + ATR-ext-50MA (positional, existing
  `atr_ext_50` config 2.5/4.0).
- Pick-reason in header; Focus stays a footnote; risk-per-trade free input (no config constant).
- Pre-close ticket rendering = **Phase C, blocked on WS3b (#268)** (pre_close store not populated).

**What landed (Phase A PR):** `ADR-014`, approved mock `planning/mocks/ws4-trade-ticket.html`
(supersede note added to the old combined mock), `CLAUDE.md` "deliver mocks as Artifacts not files"
rule (owner directive), SPRINT WS4 block, this note. Issue **#287** opened (Alpaca revisit).

**Next steps:** Phase B — PWA ticket surface built against the mock + ADR-014, Sonnet-drafted /
main-reviewed, own PR with release triplet. Add any new Playwright test to `tests.yml` `--ignore=`.

---

## 2026-08-09 — WS4 Phase B (trade-ticket PWA surface)

**Status:** Phase B built + verified; committed and pushed on `claude/ws4-gh-issue-263-qkzq16`, PR
opened. Safe to close after the Phase B PR merges.

**What landed:** `docs/index.html` (~275 lines) expands actionable morning cards (triggered /
gapped_through) into the WS4 live trade ticket per ADR-014 + `planning/mocks/ws4-trade-ticket.html`:
per-ticker join to `picks_latest` (`ws4FindPicksRow`), 4-base stop menu, two don't-chase gates
(ATR-from-LoD reusing `morningAtrLabel`; ATR-ext-50MA via `deriveRiskMetrics`), overridable
snapshot price with in-place recompute (`ws4Recompute`, no full re-render — smooth typing),
free-input risk (localStorage `ws4_risk_default`), earnings hard-card, pick-reason header,
graceful no-EOD-match degrade. Release triplet (releases.json `2026.08.09` + `current` + sw.js
v58→v59). New `tests/test_pwa_trade_ticket.py` (6 tests) + fixture, added to `tests.yml --ignore`.

**Delegation + verification:** implementation by a Sonnet subagent from a main-model spec (mock +
ADR + exact integration points/helpers). Main model verified: full diff read, JS `node --check`,
JSON validity, math/helpers (no 20/50MA swap, correct sizing), and **ran the 6 Playwright tests
live (all pass)** + a rendered screenshot to check content/order — using the Chromium
revision-symlink trick (sandbox ships rev 1194, pip playwright wants 1234; symlinked the inner
`chrome-headless-shell` path). Symlinks are ephemeral, not committed.

**Staff decision folded in:** ADR-014 §7 amended — earnings guardrail reuses existing
`EARNINGS_IMMINENT_DAYS`/`EARNINGS_CAUTION_DAYS` instead of a new `EARNINGS_GUARDRAIL_SESSIONS`
(DRY, avoids days-vs-sessions mismatch). WS4 adds **no** new configurable constant, no backend
column.

**Next steps:** WS4-C (pre-close 15:50 rendering of the same component) — blocked on WS3b (#268)
populating the `pre_close` session store. WS4-RT (real-time quotes / Alpaca) parked at #287.
Follow-ups noted: pick-reason currently wires only `grp_rs_new_high` — extend to other `grp_*`
flags if desired; Focus score omitted from the footnote (pool-relative `computeFocusScores` not
cleanly reusable for a single row) — revisit if a numeric Focus value is wanted on the ticket.

---

## 2026-08-09 — WS4 Phase B follow-up: fix hardcoded snapshot timestamp

**Status:** Done, safe to close. Found during a post-merge review of PR #289 (owner requested
a full roadmap + user-perspective review after merge) and fixed in a same-day follow-up PR,
per the merged-PR amendment policy (`.claude/rules/branch-commit-discipline.md`).

**What was wrong:** `ws4TicketHtml()` hardcoded the ticket's "Price now" label as
`(10:05 read · edit)` and the note below it as "As of the 10:05 ET snapshot..." — always,
regardless of the row's actual `collected_at`. The morning job dispatches inside a
self-healing `[10:05, 10:35)` ET window (CLAUDE.md § Automation), so on a delayed-tick day
the label would understate how stale the read actually was — directly contradicting
ADR-014 §3's own "never call it more precise than it is" rationale for not showing a
live/minute-precise price.

**Fix:** `ws4TicketHtml()` now calls the existing `freshnessLabel(r.date, r.collected_at)`
helper — the same one the Morning-tab header already uses above the list — and derives both
the compact chip (last `·`-segment of `fresh.text`, e.g. "7:05 AM PT") and the full sentence
from it. As a side effect this also correctly flags genuinely stale morning data (e.g.
"Yesterday's data · ...") instead of always implying "read this morning," which the old
hardcoded string could not do.

**Verified:** added a 7th Playwright test (`test_price_snapshot_label_reflects_actual_collected_at`)
asserting the old hardcoded strings are gone and the label reflects the fixture's
`collected_at` (2026-08-09T14:05:00Z → 7:05 AM PT). Ran all 7 `test_pwa_trade_ticket.py`
tests live (Chromium revision-symlink trick, same as PR #289) — all pass. `node --check` on
the extracted script — valid. Full non-Playwright suite (632 tests, same `--ignore=` list CI
uses) — all pass.

**Release surface:** this changes ticket copy users see, so it gets the release triplet per
house rule even though it's a fix, not a feature: `releases.json` `2026.08.09.1` (tag `fix`,
same-day `.1` suffix per convention), `current` bumped, `sw.js` `CACHE` `finviz-v59` → `v60`.

**Next steps:** none — this closes out the PR #289 review finding. WS4-C/WS4-RT next steps
are unchanged from the entry above.

---

## 2026-08-09 — WS4 trade ticket: extend pick-reason + add Focus score (follow-up to #289)

**Status:** Done, safe to close. Owner explicitly asked to close both follow-ups flagged in
PR #289's own review notes (see the "Follow-ups noted" paragraph two entries above).

**Pick-reason (ADR-014 §9):** `ws4PickReason()` previously only checked `grp_rs_new_high`.
It now also checks `grp_momentum_accel > ACCEL_STRONG` (→ `accel+`) and
`grp_regime_short_long > REGIME_THRESHOLD` (→ `emerging regime`) — reusing the existing PWA
display constants rather than inventing new thresholds; they happen to equal the selector's
own `ACCEL_THRESHOLD`/`EMERGING_REGIME_FLOOR` (`scripts/picks_config.py`), so the label lines
up with what the selector itself gated on. Each tag is skipped when it just restates the
row's own `list_category` (already shown next to it), so e.g. an `accel`-category pick
doesn't get a redundant `accel+` tag — only *other* grp_* signals that also fired show up.
Multiple tags join with ` + `.

**Focus score:** the ticket footnote now shows the pick's actual Focus score instead of the
static "watchlist context only" line. `ws4FocusScore(picksRow)` builds the same global
Focus-eligible/deduped-by-ticker candidate pool the Lookup tab's `globalFocusCandidates` /
`lookupFocusMap` already builds (`isFocusEligible` filter + ticker dedup over
`state.picksData`), runs it through the existing `computeFocusScores()`, and looks up this
row's score — so the "not cleanly reusable for a single row" concern in the original PR note
turned out to already have a working precedent elsewhere in the file; it just hadn't been
applied here yet. Returns `null` (rendered as "n/a — not a Focus candidate today") when the
row fails `isFocusEligible` (ATR-extension or liquidity gate) or isn't in the pool at all.
The pool-relative caveat stays in the copy since the owner confirmed they want the number
despite knowing it's min-max'd against the day's other candidates, not an absolute score.

**Verified:** extended `tests/fixtures` inline picks CSV in `tests/test_pwa_trade_ticket.py`
with `atr_ext_50`/`Avg Volume`/`range_atr`/`grp_sum_mid_rank`/`grp_momentum_accel`/
`grp_regime_short_long` so AXON clears `isFocusEligible` and exercises all three reason
flags; added `test_focus_score_shown_in_footnote` (expects exactly `0.30` — single-candidate
pool, 0 liquidity penalty, `EARNINGS_PENALTY_MAX` earnings penalty from the fixture's 2-day-out
earnings date) and rewrote `test_pick_reason_line_from_grp_flag` to assert all three tags
render (`rs_new_high + accel+ + emerging regime`). Ran the full `test_pwa_trade_ticket.py`
suite live (Chromium revision-symlink trick per
`knowledge/investigations/playwright-cloud-session-testing.md`) — all 8 pass. Full
non-Playwright suite (632 tests, CI's `--ignore=` list) — all pass.

**Release surface:** user-visible ticket copy change, so it gets the release triplet:
`releases.json` `2026.08.09.2` (tag `feature`, same-day suffix per convention), `current`
bumped, `sw.js` `CACHE` `finviz-v60` → `v61`.

**Next steps:** none outstanding from this thread.

---

## 2026-08-10 — Correction to the above: pick-reason/Focus-score design was wrong, fixed same PR (#292)

**Status:** Done, safe to close. Owner reviewed PR #292 and correctly called out that the
prior approach was needlessly re-deriving data that already exists, and asked for evidence
the Focus score actually matches the Picks tab. Both concerns were valid and confirmed
against live `data/picks/picks_latest.csv` before fixing — recording the evidence here since
it's the kind of thing a future Claude could plausibly re-introduce by copying the old pattern.

**Pick-reason bug:** `collect_picks.py`'s `build_pick_rows()` already writes ONE ROW PER
(ticker × list_category) — a ticker landing in multiple selector buckets (leaders/emerging/
accel/rs_new_high) gets one row per bucket, each tagged with that bucket's own name. That's
the actual, exact, zero-drift-risk answer to "why was this picked." The original
`ws4PickReason()` ignored this and instead re-checked `grp_momentum_accel`/
`grp_regime_short_long` against copies of the PWA's own display thresholds (`ACCEL_STRONG`,
`REGIME_THRESHOLD`) — an approximation of the *real* selector logic in
`scripts/picks_config.py`, which additionally requires `rs_score` floors and a
`momentum_score` percentile floor that the PWA doesn't mirror at all. Checked against the
live picks file: the accel-tag heuristic disagreed with the real `list_category` set on 98
of 225 tickers checked (44%), the emerging-tag heuristic on 32 (14%). It also silently could
never show "leaders" as an extra tag (no heuristic existed for it) even though ~30% of a
day's picks carry 2+ real categories. **Fix:** replaced the threshold heuristics with
`ws4PickCategories(ticker)`, which reads the actual `list_category` set for that ticker
straight from `state.picksData` — no thresholds, can't drift. Primary category (shown next
to "from Picks ·") is the highest-priority one present (selector priority order:
leaders/emerging/accel/rs_new_high); any others render as "also X".

**Focus score bug:** the original `ws4FocusScore()` mirrored the Lookup tab's
`globalFocusCandidates` pattern (dedup by ticker, `isFocusEligible` only) rather than the
canonical pool the Picks tab's own Focus view and All-view Focus badges use
(`displayRows.filter(isFocusEligible)` in `renderPicks()`, where `displayRows` is built from
`rows.filter(<C6 base filter>)` — market cap + trend gate — first). Checked against the live
picks file: 20 of 124 tickers that pass `isFocusEligible` fail the C6 gate (mostly sub-$5B
market cap) and would never appear in the Picks tab's Focus view at all — the old code would
have confidently shown a Focus score for stocks that aren't Focus candidates by the app's own
definition, and the normalization pool composition differed even for tickers that do pass
both. **Fix:** extracted the C6 filter out of `renderPicks()` into a shared
`passesPicksBaseFilter(r)` (used by both call sites now, so this gate can't re-diverge), and
rewrote `ws4FocusScore()` to filter by `passesPicksBaseFilter` THEN `isFocusEligible`, not
deduped by ticker — exactly matching `allFocusCandidates` in `renderPicks()`. Documented
caveat: the ticket always uses the Picks tab's *default* settings (Ariel filter off, 'last'
price basis); if the user has an Ariel filter active in the Picks tab right now, the number
can legitimately differ from what's currently on screen there, since Ariel further narrows
that view's pool. This is a disclosed, deliberate divergence (an opt-in display toggle), not
silent drift.

**Verified:** rewrote the `tests/test_pwa_trade_ticket.py` fixture to give AXON two real
picks rows (`list_category` leaders + accel, identical Finviz/metrics columns — mirrors how
`collect_picks.py` actually writes multi-category picks) plus the full real `METRICS_COLS`
set (`risk_20ma_pct`/`risk_50ma_pct` were missing before, which silently changed the Focus
score via `computeFocusScores`' NaN-component fallback — an earlier version of this session's
test had that gap). Pinned Focus score (0.30) verified by extracting `computeFocusScores()`
out of `docs/index.html` into a standalone Node snippet and running it directly against the
fixture rows, not just hand-derived. Full `test_pwa_trade_ticket.py` suite (8 tests, Chromium
revision-symlink trick) + the four Picks-tab-adjacent Playwright suites that exercise
`renderPicks()`/Focus scoring (`test_pwa_focus_scoring.py`, `test_pwa_picks_hod.py`,
`test_pwa_picks_atr_earnings.py`, `test_pwa_picks_chart.py`, `test_pwa_lookup_signal.py` —
32 tests, confirming the `passesPicksBaseFilter` extraction is behavior-preserving for the
Picks tab itself) — all pass. Full non-Playwright suite (632 tests) — all pass.

**Release surface:** updated the existing (still-unmerged) `2026.08.09.2` entry's copy in
place rather than adding a new `.3` — this is a same-PR correction to work that hasn't
landed on default yet, not a new user-visible change on top of a shipped one.

**Next steps:** none outstanding. If a future change touches Focus scoring again, remember
there are now three related-but-distinct pools in the codebase (Lookup tab's
ticker-deduped/no-C6 `globalFocusCandidates`, Picks tab's C6-filtered/non-deduped/
Ariel-aware `displayRows`-based pool, and WS4's ticket `ws4FocusScore` which now matches the
Picks tab's default-settings pool) — worth eventually consolidating into one shared builder
if a fourth call site shows up, but not done here since the Lookup tab's existing pool choice
wasn't in scope for this fix and changing it wasn't requested.

---

## 2026-08-11 — WS5 trade-lifecycle design review (PR #294 → PR #295)

**Status: safe to close.** Design-review workstream; all edits committed + pushed to
`claude/pr294-design-review-mxmtvm`, PR #295 open (ready for review). No code shipped — planning +
knowledge docs + one mock only.

**What landed:**
- Reviewed PR #294 (docs-only `closing`-state reconciliation), its design docs, the decisions inside,
  and did a UX-backward pass. Verdict: #294 is accurate/mergeable; the review surfaced gaps #294
  didn't cover, which became the edits below.
- Merged origin/`claude/ws5-gh-264-onboard-om79x9` (PR #294's branch) into the review branch so edits
  build **on top of** #294's reconciled docs (not the stale default). ⇒ **PR #295 now contains #294's
  commits.** Owner must decide merge order: merge #294 then #295 (clean), or merge #295 alone (makes
  #294 redundant). Flagged to owner; not closed unilaterally.
- `planning/trade-lifecycle-engine.md`: §3a independent-lots scale-in model; §5a two-feeds separation;
  §5 `confirmation_status` + full-column `ticker_quotes` + `exit_corrected`/`reopened` events; §6
  new constants (`EXIT_AUTOCONFIRM_SESSIONS=5`, `AUTO_CLOSE_STRIP_SESSIONS=3`, `CAUTION_REARM_ON_HOLD`)
  + split exit-reason enum; §7 editable fill / caution re-arm / two-close-on-50MA / auto-confirm /
  append-only correction; §8 two-tier notifications + in-app pull surface; §8b grouped-lot UX; §11a
  resolved; §12 backtesting demoted to nice-to-have (honest scope); §13 retrace-to-MA risk view; §14
  effective-config `advance()` for the per-position/LLM door.
- ADR-012: Decisions 8–11 + full-column note + 2026-08-11 reconciliation header.
- `knowledge/cron-lifecycle-ideation-and-alignment.md`: §11 owner-decision table (2026-08-11).
- `knowledge/trade-lifecycle-design-review-2026-08-11.md`: NEW full session narrative.
- Mock `planning/mocks/ws5-needs-confirmation-surface.html` (in-app confirmation pull surface, editable
  fill). Artifact: https://claude.ai/code/artifact/2dc19c36-8e5f-4405-b03f-127fc26b7992

**Issues filed:** #297 (full-column capture), #298 (independent-lots grouping UI), #299 (LLM layer
directions). All under #264 (WS5).

**Next steps:** owner to (1) decide #294/#295 merge order; (2) skim the design-doc edits; (3) WS5
phase 1 starts by provisioning D1 + honoring the phase-1 obligations (no one-position-per-ticker
assumption, reserve `meta.group_id`, `confirmation_status` column, full-column append-only capture,
effective-config `advance()` signature).

**Note:** session-notes commit is on the feature branch — must land on the default branch via a merged
PR to be visible next session (see branch-commit-discipline § "Session notes MUST land on default").
