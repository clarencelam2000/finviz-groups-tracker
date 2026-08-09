# Session Notes Archive

> Older session entries moved here periodically by a human reviewer. Not auto-loaded.
> Newest entries at the top.

---

## 2026-08-08 — WS2 session-dimension keystone (foundation slice, #261)

**Status: safe-to-close.** PR #279 open (feat: add session dimension SSOT), foundation slice complete.

**Context:** Picked up #261 per the roadmap front door → alignment § 10 → ADR-011 → issue → mocks
chain. Confirmed the dependency is cleared: WS1 (#258, commit 49b7cdd) and the picks gate (#259,
21e2815) both landed, so #261's "needs trigger headroom" blocker is resolved. Owner had already
locked ADR-011 **Option C** (existing files == eod, unchanged; provisional data in physically-
separate session-keyed stores).

**Owner scope call this session:** foundation only. Under Option C the ADR defers *both* concrete
provisional stores (group intraday = "no consumer yet"; ticker quotes = "location decided with
WS5"), so building either now would be speculative. CEO chose the thin keystone over standing up a
live provisional writer or writing a plan-first doc.

**What landed (PR #279):**
- `scripts/session_config.py` — SSOT for session identity: `Session` dataclass, `EOD/MORNING/
  PRE_CLOSE` constants, ordered `SESSIONS` registry with canonical ET capture times (eod 17:00 /
  morning 09:45 / pre_close 15:50 — the two provisional times match existing crons), `DEFAULT_
  SESSION = eod`, pure helpers, and `assert_provisional()` (the structural guard that makes "eod
  never enters a provisional store" enforceable in code). No store/writer/PWA chrome — deferred to
  consumers. Store-key convention `(date, session, <entity>)` documented as a constant only.
- `tests/test_session_config.py` — 11 tests, green. Full non-Playwright suite green (650 passed;
  the 62 failures are exclusively the known Playwright-in-cloud files).
- README § Configurable parameters + CLAUDE.md § Automation — session capture times triple-documented.
- ADR-011 — appended "WS2 resolution" section closing its three open questions.

**Delegation note:** module + tests + doc tables built by a Sonnet subagent from a main-model spec;
main model designed the module, wrote the ADR resolution note, and reviewed all code before commit.

**Next steps:** WS3 (#262) is the first real consumer — introduces the first provisional writer +
the PWA not-settled marking (deferred here). WS3b (#268) rides the same `pre_close` session.

---

## 2026-08-07 — Staff review of PR #257 + issues #258–#266 (trade-lifecycle workstream readiness)

**Status: safe to close once PR #267 merges.** Review + durable-capture session; no product code.
PR #257 was already merged by the owner before review — docs verified against the default branch.
Owner then answered the open decisions in a Q&A round; all answers committed (see below) rather than
left in chat — an earlier draft of this entry wrongly called the session safe-to-close while the
deliverables were still trapped in a chat artifact; corrected.

**Verdict: team is ready to pick up WS1.** All 7 docs read in full; a Sonnet subagent verified
every `file:line` citation against source — substance is accurate (minor line-number drift only;
one relocated fact: the earnings/days-to-earnings parse lives in `scripts/replay_picks.py` +
`docs/index.html`, NOT `scripts/picks_metrics.py` — WS4 (#263) needs it ported Python-side).

**Findings filed as issue comments (don't lose):**
- **#259** — the dependency gate's run-success check can be satisfied by the 15:50 *pre-close*
  run (same workflow file), dispatching picks against pre-close deltas; require run start ≥ EOD
  target ET. Also: `GITHUB_DISPATCH_TOKEN` is POST-only today — verify it can READ run status.
- **#258** — exact-minute tick matching is fragile (delayed/skipped CF ticks silently drop a
  job); use "target passed + no dispatch recorded today (KV)" within a bounded window. Also the
  stale `#FOLLOWUP` placeholder in the issue body.
- **#264** — exits should capture the user's *actual* fill like entries do (suggest a `closing`
  state between Managing/Closed); signal-close vs execution-close distinction; `pos.sma50` →
  `bar.sma50` pseudocode nit.

**Mocks created** (owner asked for visuals): claude.ai artifact "Picks Workstream Mocks —
WS3/WS4/WS5" — WS3 morning-confirmation states, WS4 trade ticket, WS5 position cards, in the
PWA's slate/sky idiom, each with embedded owner questions (gapped-through "I took it"?; where
does risk-per-trade $ come from?; exit auto-close vs confirmed fill?).

**Endorsements:** ADR-011 Option C (physical separation) — concur decisively; WS3-before-
morning-picks sequencing — correct; D1 spine+bag+event-log — right shape.

**Owner Q&A round (2026-08-07) — all decisions committed to `knowledge/cron-lifecycle-ideation-
and-alignment.md` § 10** (owner-intent source of truth). Locked: gapped-through also gets "I took
it"; risk-per-trade = free input on ticket; stop-hit awaits confirmed fill (new `closing` state —
design doc §4 needs updating, #264); ADR-011 **Option C**; `SEVERE_BREAKDOWN_ATR` default **3.0**;
**WS1 go-word GIVEN** (start #258). New scope: **WS3b pre-close ~15:30 surface** (owner checks the
last half-hour; more on-thesis than morning; needs its own issue), WS3 Failed-breakout + No-quote
states, WS5 aggregate-exposure footer.

**Durable capture (the fix for the process miss):** mocks committed to
`planning/mocks/trade-lifecycle-surfaces.html`; decision record appended to the alignment file § 10;
roadmap given a "START HERE" reading-order block naming the mocks + alignment record. Artifact alone
would have been lost — that was the miss the owner correctly flagged.

**Where the team picks up:** roadmap doc (front door) → alignment § 10 (intent+decisions) → per-WS
ADR/design → issue → mocks. Start coding at #258 with the #258/#259 amendments.

**Process gaps surfaced for follow-up (not yet actioned):** (1) no rule that ephemeral deliverables
(artifacts/mocks) must be committed — recommend adding to `.claude/rules`; (2) needs a WS3b tracking
issue; (3) design-doc §4 (auto-close) now contradicts the committed decision — must be reconciled
before WS5 phase 3.

**Next steps:** open a WS3b issue; reconcile trade-lifecycle-engine.md §4 with the `closing`-state
decision; then implement #258.

---

---

## 2026-08-06 — Cron consolidation → trade-lifecycle initiative (planning only, no code)

**Status: safe-to-close on Claude's side; one owner action remains — review/merge PR #257** so
the docs + memory record land on the default branch (until merged they're reachable only on
`claude/finviz-cron-consolidation-8uilrk`, so the next session won't auto-see them).

**What this was:** a staff-level ideation session (no implementation) triggered by the shared
Cloudflare account's hard 5-cron-trigger limit (issue #252 history) and the owner's pain point of
having no morning market-open data. Adopted the sibling project's doctrine: one cron trigger per
project, gate logical jobs in code by ET time-of-day/weekday.

**What landed (all on branch `claude/finviz-cron-consolidation-8uilrk`, PR #257):**
- `knowledge/decisions/ADR-010` — collapse 3 CF crons → one `*/5` tick, in-code ET routing,
  auto-DST via `Intl.DateTimeFormat`, dependency-driven picks dispatch (replaces 90-min margin).
- `planning/cron-consolidation-state-machine.md` — implementation-ready WS1 design.
- `planning/roadmap-cron-lifecycle.md` — sequenced WS1–WS5 + cheap wins + parked/rejected.
- `knowledge/cron-lifecycle-ideation-and-alignment.md` — **memory record**: idea-by-idea
  decisions, owner's swing-trading ruleset, corrections to Claude's thinking. Source of truth for
  owner intent.
- `knowledge/decisions/ADR-011` — WS2 session-dimension keystone. **Ends in an owner decision
  point: Option A (session column in existing files) vs Option C (canonical/provisional physical
  separation, recommended).** Not yet decided.
- `knowledge/decisions/ADR-012` + `planning/trade-lifecycle-engine.md` — WS5 lifecycle engine:
  D1 storage (spine + JSON bag + event log), app-layer tenant isolation, and the formalized
  daily-advancement engine encoding the owner's real rules (profit-floor invariant NOT naive
  ratchet-up; two-close-below-20MA exit; ATR≥7 10%-of-remaining trims).

**Tracked work:** issues #258–#266 (WS1×3, WS2, WS3, WS4, WS5 epic, taxonomy check, parked).

**Process note:** first drafts of the three cron docs were done by a Sonnet subagent; owner
correctly flagged that judgment-heavy design synthesis is main-model work. WS2/WS5 docs were then
authored directly by main-model Claude. WS3/WS4 deep docs deferred on purpose (depend on WS2's
A/C decision).

**Open decisions for the owner (none block review; all captured in the docs):** WS2 Option A vs C;
`SEVERE_BREAKDOWN_ATR` calibration; widen-policy auto-vs-opt-in; ticker-quote store CSV-vs-D1
(shared WS2/WS5 decision); picks dependency-gate window width; whether GitHub backstop crons go
ET-derived. **No implementation until the owner's explicit go-word — WS1 (#258) is the start.**

---

---

## 2026-07-19 — Harden data collection: AUD-4 + PICKS-2-CRON + PICKS-2-HDR

**Status: COMPLETE. PR open on `claude/harden-data-collection-5ac09d`. SAFE TO CLOSE once merged.**

Three failure modes in the append-only capture pipeline, settled under one design decision:
**every workflow that writes `data/` serializes on the single `finviz-data-commit` concurrency
group, and every guard on the irreplaceable picks capture fails loud (red CI) without trading a
partial capture for no capture.**

**1. AUD-4 (done — half had already landed).** PR #250 already added `git pull --rebase` to
collect.yml's push. This session moved generate_ai.yml from its own `generate-ai` group into
`finviz-data-commit`. Known trade-off (documented in the workflow comment): GitHub keeps only the
newest *pending* run per group, so an AI run superseded while queued gets dropped — recoverable
via workflow_dispatch force_ai, unlike a raced data commit.

**2. PICKS-2-CRON (done per the Phase 5 plan).** worker-cron: 4th cron `31 22 * * 2-6` (6:31 PM
EDT, EOD +90 min); `dispatchCollect` → `dispatchWorkflow(env, cron, workflow)` with routing by
exact `event.cron` string (`workflowForCron`); per-workflow KV keys; `/last` → `{collect, picks,
legacy}`. **Correction to the plan:** it wrote `1-5` day-of-week, but Cloudflare cron is
1=Sunday — deployed as `2-6` matching the existing entries. collect_picks.yml: GitHub `schedule:`
removed (deliberate — no backstop; 50-page scrape too expensive to misfire), success-only
`PICKS_HEALTHCHECK_URL` ping added. 20 worker tests pass. Deploys automatically via
deploy-workers.yml on merge. **Open VP action item: create the healthchecks.io check (period 24h,
grace 2h) and add the `PICKS_HEALTHCHECK_URL` repo secret — the ping skips silently until then,
meaning NO dead-man alert coverage yet.**

**3. PICKS-2-HDR (done — the judgment call).** Tiered header-drift policy in collect_picks.py:
`missing_header_labels()` + `header_check_action()`. `Ticker` missing or >10% of the 84 labels
(`HEADER_MISSING_ABORT_FRAC`) → abort BEFORE write; smaller drift → write the partial capture
then exit 1 AFTER the write (CI red, debug HTML uploads, healthcheck ping skipped). Rationale:
aborting the whole day over one renamed column would convert bounded column loss into total loss
of an unrecoverable day. 9 new unit tests; triple-documented.

**Verification:** CI-equivalent non-Playwright suite 578 passed; worker-cron vitest 20 passed.
Cannot live-test the CF dispatch or an actual picks run from cloud (Cloudflare/IP block) — first
real validation is the first post-merge 22:31 UTC fire; check `/last` on the worker if in doubt.

**Next steps:** merge PR → deploy-workers.yml ships the dispatcher; VP creates the healthchecks
check + secret; watch the first scheduled picks fire. Backlog unchanged otherwise (AUD-1/2/3/5,
PICKS-4B/4C remain).

---

---

## 2026-07-19 — PICKS-4: picks alpha scoreboard built + wired (the measurement instrument)

**Status: COMPLETE. PR open on `claude/picks-alpha-measurement-3fldvj`. SAFE TO CLOSE.**

Staff review of the PICKS-4 spec (`planning/picks-alpha-evaluation.md`) concluded it IS the
right thing to build — the ~60-session re-assessment (Sept) is impossible without it — but
shipped it with three deliberate amendments:
1. **`data/picks/eval/group_scores.csv` is derived, fully rebuilt each run** — not the spec'd
   append-only/last-write-wins design. Same output, partial-horizon rows self-correct for
   free, kills that bug class. Filter `n_sessions_avail == horizon` for settled rows.
2. **Added the non-selected control columns** (`n_nonsel`, `fwd_ret_nonsel_mean`,
   `excess_nonsel`) — the spec's own headline paired per-date test was not computable from
   its spec'd schema. Also stores `selector_version` per row (Part-3.3 discontinuity label).
3. **NOT a third data writer.** Wired as a step in `collect.yml` right after
   `compute_deltas.py` (rides `finviz-data-commit` + existing commit step) instead of the
   spec's "separate workflow joining the concurrency group." Also added the AUD-4
   `git pull --rebase` to collect.yml's push while touching it.
Deliberately did NOT build `ticker_scores.csv` — survivorship-biased until real OHLC
(PICKS-4B/FMP unlock remains the next big item).

Landed: `scripts/evaluate_picks.py` (+15 tests in `tests/test_evaluate_picks.py`, full suite
566 green), collect.yml wiring, first real build committed, triple-docs (README § Configurable
parameters, root + scripts CLAUDE.md, SPRINT PICKS-4 → done).

**First `--report` read (15 dates, still NOT powered — the report says so itself):** the
07-14 assessment's pattern holds and sharpens with horizon: `leaders` −6.30% vs SPY at h=10
(18% hit); `rs_new_high` +2.48% vs median at h=10 (76% hit), monotonically improving with h;
paired per-date h=10: 1/6 dates positive. Rotation-edge / leaders-drag hypothesis intact.
Do not tune the selector before ~40 dates (~mid-Sept); then it's just `--report`.

**Next steps:** PICKS-4B (FMP OHLC → stock-level scoreboard + R-multiple expectancy),
PICKS-4C (`risk_*_pct` rename). Both unchanged in SPRINT backlog.

---

---

## 2026-07-16 — Fix Focus/Picks ticker-duplication bug (prod)

**Status: COMPLETE. Pushed to `claude/focus-ticker-duplication-mkxlnd`, PR to be opened.
SAFE TO CLOSE once PR is up.**

User reported every ticker on the PWA Focus tab showing its leading character duplicated
(`C`→`CC`, `WFC`→`WWFC`, `HSBC`→`HHSBC`, etc.).

**RCA** (full writeup: `knowledge/investigations/picks-ticker-duplication-2026-07-15.md`):
confirmed the corruption was in `data/picks/picks.csv`/`picks_latest.csv` itself (not a display
bug) and isolated to exactly `2026-07-15` — 100% of that date's 229 rows matched the
duplicated-leading-character signature vs. a ~1-4% natural baseline across the prior 10 dates.
No code changed around that date, so the cause is external: Finviz's screener Ticker `<td>`
apparently added decorative markup (e.g. an avatar/logo-fallback letter) ahead of the real `<a>`
ticker link, and `probe_picks._parse_table()` was extracting `cell.get_text(strip=True)` on the
whole cell, swallowing both.

**Fix landed:**
- `scripts/probe_picks.py::_parse_table()` — Ticker column now reads from the cell's `<a>` tag
  specifically, not the whole cell text (falls back to full-cell text if no anchor).
  `collect_picks.py` imports this same function, so one fix covers both.
- `scripts/collect_picks.py` — added `ticker_dup_rate()` + `TICKER_DUP_RATE_MAX = 0.25` guard in
  `main()`, aborting (loud, no write) before `write_picks()` if too many tickers in a run show
  the duplication signature — defense-in-depth against any future Finviz markup change with the
  same symptom, independent of whether the anchor-text fix above fully covers it.
- Repaired `data/picks/picks.csv` + `picks_latest.csv`: stripped the one duplicated leading
  character from every `2026-07-15` ticker (verified inverse-correct against the 100% signature
  match).
- New regression tests: `tests/test_probe_picks.py` (avatar-markup fixture + anchor-fallback),
  `tests/test_collect_picks.py::TestTickerDupRate`. Full suite green (554 passed, CI ignore list
  unaffected — no new Playwright test files).
- Documented the gotcha in `scripts/CLAUDE.md` § Picks pipeline per house rules.

**Next steps:** open PR, verify CI green, merge. No further action needed after merge — next
`collect_picks.yml` cron run will naturally validate the anchor-text fix against live Finviz on
Azure IPs (can't verify live HTML from this cloud session; Cloudflare blocks it, see root
CLAUDE.md § Playwright notes).

---

---

## 2026-07-14 — Picks alpha assessment (first empirical read) + evaluation-pipeline spec

**Status: COMPLETE. PR #246 open on `claude/picks-alpha-assessment-p3jglg`. SAFE TO CLOSE.**
Docs/analysis only — no code, no pipeline change.

Owner asked whether the Picks tab is actually giving alpha, with an explicit risk/expectancy lens
(top traders win ~35% — it's about small losses / big wins, assuming users honor the displayed
stops). ~13 pick dates on hand (2026-06-25..07-14). A Sonnet subagent ran the empirical pass; I
designed the framework, verified the one actionable bug, and wrote the durable artifacts.

**Findings (`knowledge/investigations/picks-alpha-assessment-2026-07-14.md` — canonical):**
- **Group-selection alpha is NEGATIVE at this N.** Selected groups vs SPY: h=5 −2.72% (29% hit,
  N=140); vs the cross-sectional industry median −1.76%. Non-selected control ≈0 vs median.
  Paired per-date: selected beat non-selected on only 2/8 dates at h=5.
- **`leaders` bucket is the drag** (5d −4.70% vs SPY, 12% hit) — extended sustained-strength
  leaders mean-reverted. **`rs_new_high`/`accel` (rotation triggers) were the only positives**
  (rs_new_high +1.00% vs median, 67% hit, tiny N) — that's the product thesis holding.
- **Focus gate showed no edge** (directionally worse, within noise).
- **~10% of picks touched their stop within 5 sessions** (close-only ⇒ underestimate).
- Nothing is statistically conclusive — ~8–13 independent date-trials in ONE regime.
- Data-quality: **stooq unreachable** (anti-bot JS challenge) ⇒ no real OHLC ⇒ couldn't compute
  the R-multiple expectancy the owner most wanted. `risk_*_pct` fields are fractions despite the
  name (PWA-correct, but a footgun).

**Durable deliverables (the lasting-impact part, since I rotate off):**
- **`planning/picks-alpha-evaluation.md`** — full self-contained spec for `scripts/evaluate_picks.py`
  (daily forward-return scoreboard: group returns vs SPY + vs cross-sectional median, per bucket,
  last-write-wins with a settle column, `--report` roll-up + paired-date test) so the next
  assessment is a `--report` call, not a hand analysis. Plus a "future eyes" standing playbook:
  re-run at ~60/~100 sessions, the specific hypotheses to confirm/kill, the FMP-OHLC unlock for
  R-multiples, and the `risk_*_pct` rename.
- **SPRINT.md**: replaced the one-line `PICKS-4 (eval_picks.py)` placeholder with real referenced
  tasks — PICKS-4 (group scoreboard, M), PICKS-4B (stock-level + R-multiple, blocked on FMP OHLC,
  L), PICKS-4C (`risk_*_pct`→`_frac` rename, S). Added ~60/~100-session re-assessment rows to
  Next Milestones.

**Next steps:** merge PR #246. Highest-leverage follow-up is PICKS-4 (group scoreboard) — one
focused session, no external deps. Then the FMP `/history` unlock (PICKS-4B) for the real
expectancy analysis. Do NOT tune the selector on this data — N far too small.

---

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

---

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

## 2026-06-25 — Picks cron dispatcher plan (PICKS-2-CRON)

**Status: PLAN COMPLETE. IMPLEMENTATION READY FOR NEXT SESSION.**

Plan written and docs committed to `claude/picks-cloudflare-cron-f0t7fz`. Extend `finviz-cron-dispatcher` with a 4th cron `31 22 * * 1-5` (22:31 UTC = 6:31 PM EDT). Routes by `event.cron` — picks cron dispatches `collect_picks.yml`. GitHub cron retired from `collect_picks.yml` (50-page scrape too expensive to misfire). Healthchecks.io dead-man's-switch planned.

**VP action item:** create healthchecks.io monitor (period=24h, grace=2h) and add `PICKS_HEALTHCHECK_URL` as repo secret before implementation merges.

**Safe to close.** Next session: implementation (worker-cron/ + collect_picks.yml).

---

## 2026-06-28 — Phase 3c: Lookup Stage-2 section + Finviz deep-link button

**Status: PHASE 3c COMPLETE. PR OPEN. SAFE TO CLOSE.**

What landed:
- `docs/index.html` — `slugifyGroup()` + `buildScreenerUrl()` helpers; `renderLookupStage2()`; Stage-2 section hooked into BOTH `renderLookup()` branches (group-by-name + ticker→group); 4 BUTTON_* constants (BUTTON_V, BUTTON_BASE_FILTERS, BUTTON_SORT, BUTTON_FT) inlined near ATR_EXT_* constants block
- `docs/releases.json` — v2026.06.28 entry, tag "feature", tab "lookup"
- `docs/sw.js` — CACHE bumped to finviz-v33
- `tests/test_picks_button_config.py` — NEW: 9 tests (4 BUTTON_* anti-drift + 5 sector-slug tests)
- `CLAUDE.md` / `README.md` — 4 BUTTON_* constants triple-documented
- `planning/stock-picks-from-leading-groups.md` — Phase 3c marked COMPLETE
- `.session/SPRINT.md` — PICKS-3C marked Done

478 tests pass (9 new for Phase 3c).

**Phase 3d next:** inside-day polish, fundamental floor, Focus stacked-stop bonus, staleness banner.

---

## 2026-06-27 — Phase 3b: expandable risk panel + All/Focus toggle + Focus scoring

**Status: PHASE 3b COMPLETE. SAFE TO CLOSE.**

What landed:
- `docs/index.html` — `renderPickRow()` (module-level, 3b.0), expandable risk panel (3b.1), All/Focus toggle + `computeFocusScores()` (3b.2), 6 new constants (ATR_EXT_PENALTY_START, PENALTY_MAX, FOCUS_W_GROUP, FOCUS_W_TIGHT, FOCUS_W_QUIET, FOCUS_MIN_POOL), GUIDE entry for `focus_score`, `switchTab()` resets picksView='all' on tab entry (A4)
- `docs/releases.json` — v2026.06.27 entry, tag "feature", tab "picks"
- `docs/sw.js` — CACHE bumped to finviz-v32
- `knowledge/moaty-metrics.md` — `focus_score` entry
- `CLAUDE.md` / `README.md` — 6 Focus constants triple-documented
- `planning/stock-picks-from-leading-groups.md` — Phase 3b marked COMPLETE
- `tests/fixtures/picks_latest.csv` — 13th row: TESTAB20 (above50/below20 test case)
- `.session/SPRINT.md` — PICKS-3B marked Done

Playwright tests for 3b (`tests/test_pwa_picks.py`) written but deferred to separate branch `claude/pwa-picks-playwright-tests` pending cloud infra fix. Non-blocking.

---

## 2026-06-26 — Phase 3a: Picks tab MVP + backend derived metrics

**Status: PHASE 3a COMPLETE. SAFE TO CLOSE.**

What landed:
- `scripts/picks_metrics.py` — pure backend module: parsers + `compute_metrics_row()` for 5 METRICS_COLS
- `scripts/picks_config.py` — updated: METRICS_COLS added, `picks_columns()` now returns 113 cols
- `scripts/collect_picks.py` — updated: `ensure_picks_csv()` migration + `build_pick_rows()` computes metrics at scrape time
- `tests/test_picks_metrics.py` — 39 tests
- `tests/fixtures/picks_latest.csv` — 12-row 113-col EOD fixture
- `docs/index.html` — Picks tab button, section, loadPicks, renderPicks, C6 filter, C4 color bands, 5 GUIDE entries, WELCOME updated to 7 tabs, GUIDE_TAB_CHIPS updated, INTRO_KEY bumped to v2
- `docs/releases.json` — v2026.06.26 entry, tag "feature", tab "picks"
- `docs/sw.js` — CACHE bumped to finviz-v31
- `CLAUDE.md` / `README.md` — 3 new PWA constants triple-documented (MIN_MARKET_CAP_B, ATR_EXT_ACTIONABLE, ATR_EXT_TRIM)

522/522 non-Playwright tests pass. **Phase 3b next.**

---

## 2026-06-24 — Sector→industry hierarchy foundation complete

`data/finviz_sector_industry_map.json` merged (PR #171) — 11 sectors, 144 industries, 100% match against live snapshots. Full 22-feature hierarchy roadmap written to `planning/PLAN_sector_industry_hierarchy.md`. Sprint board updated with HIR-* tasks. Two items immediately unblocked: TASK-6B (Streamlit sidebar filter) and INS-7 (Sector Breadth).

---

## 2026-06-24 — Phase-1.5 spike: selector policy locked with VP

**Key findings:**
- All-green count: 21–46/day (self-shrinks on weakness — correct).
- `momentum_accel` is all NaN on all 10 dates (needs 11 sessions; unlocks ~Jun 25).
- `rs_score > 0.5` floor on `emerging` essential — drops qualifying count from 39–50 → 3–4 but removes noise.
- Sustained_strength most stable (Jaccard 0.691 avg); momentum_confirmed more responsive (0.605). Hybrid (8+2) captures both.

**Decisions locked (VP 2026-06-24):**
- Leaders metric: 8 by sustained_strength + 2 freshness fills by momentum_confirmed
- Anti-flash floor: Top 40% cross-sectional percentile by `momentum_score`
- Slot split: 10/4/3/3 (cap=20)

**Docs updated:** `planning/stock-picks-from-leading-groups.md` status block + Spike section.

**Not committed (Phase-1, paused per VP):** `scripts/probe_picks.py` + `.github/workflows/probe_picks.yml`.

---

## 2026-06-23 — Cron schedule adjustment for market hours

Updated `worker-cron/wrangler.toml` cron times to better align with US market hours. Key finding: Cloudflare Cron does NOT support timezone/DST. Manual adjustment required on Nov 2, 2026 (EDT→EST) and Mar 9, 2027 (EST→EDT). PR #168 opened.

---

## 2026-06-21 — Start Here onboarding intro

Implemented `planning/start-here-onboarding.md` in full. WELCOME constant (5-slide array), "Start Here" hub section, full-screen carousel, `fvt_intro_seen_v1` localStorage key. Anti-drift tests in `tests/test_pwa_intro.py`. `knowledge/product-intro-copy.md` canonical copy source. Release v2026.06.21, sw.js CACHE → v19.

---

## 2026-06-20 — ETF lookup overrides (ETF-1)

PR #137 merged. `data/etf_overrides.csv` — 31 curated ETFs. `build_taxonomy.js` extended to emit `etf_overrides.json`. `lookupEtf()` in `taxonomy.js`. PWA `renderLookup()` updated with thematic/sector/diversified card variants. ADR-005 written. releases.json 2026.06.20, SW cache v17→v18.

---

## 2026-06-20 — Lookup search enhancements (Ideas 1–7)

Ideas 1–4 (PR #131 merged): local group name search, typeahead dropdown, expanded group card, SW cache v15→v16.
Ideas 5–7 (PR #134): recent searches, pinned favorites, empty-state momentum chips, synonym map, fuzzy "did you mean". SW cache v17→v18, releases.json 2026.06.21.

---

## 2026-06-19 — Cloudflare Cron Scheduler live

PR #122 merged. Worker `finviz-cron-dispatcher` deployed. All three weekday cron triggers active. Live validation: end-to-end POST returned HTTP 204, `collect.yml` run #38 launched. KV namespace connected. Phase 3 (edge-scrape spike) deferred.

---

## 2026-06-19 — Guide & What's New hub

PWA header ℹ️ hub (slide-up sheet) with What's New (`docs/releases.json`) + Guide (11-metric glossary). Unseen dot + one-time banner. Contextual "why this matters →" deep-links. Dashboard sidebar mirrors both. SW cache v9→v10. `tests/test_guide_releases.py` + TestPWAHub Playwright class green.

---

## 2026-06-17 — Lookback config + momentum variants

`scripts/delta_config.py` single source of truth — `LOOKBACK_WINDOWS=[5,10,20,50]`. Trading-day lookbacks via `find_trading_date_back` (position-based, gap-tolerant). Six momentum variants added. PWA minimal window renumber. `generate_ai.py` repointed. 159 tests pass. LB-FF1 tracked in SPRINT (PWA full-dynamic windows).

---

## 2026-06-16 — Date/timezone hardening + stale-delta fix

Real bug: daily cron fired Sat/Sun, re-scraping stale close. `trading_date()` rolled Monday-pre-9am to Sunday. Stale-delta `existing_keys` guard locked first-run ranks. Fixes: `existing_keys` removed (last-write-wins), `trading_date()` rolls weekends + Monday-pre-open to preceding Friday, crons changed to weekday-only. Phantom weekend rows purged (Jun 13/14). CLAUDE.md Automation section updated.

---

## 2026-06-16 — Lookup tab improvements Phase 1

Six Phase 1 slices in `docs/index.html`: rank sparkline, conviction info (Rank Floor + Sustained/Consistent chip), breadth strip, RS spread chips, moat score, export button. Each its own commit with paired SPRINT + plan-doc updates.
