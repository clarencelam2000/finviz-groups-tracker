# Session Notes

> **Future Claude:** read this immediately at session start. Summarize the current state for the user before doing anything else.
>
> **Format:** Append a new `---` delimited block per session. Header = date + workstream description. Keep the last 4 sessions here; a human will periodically move older entries to `.session/archive/session-notes-archive.md`. Do NOT replace existing entries — append only.

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

## 2026-08-07 — Staff review of PR #257 + issues #258–#266 (trade-lifecycle workstream readiness)

**Status: safe to close.** Review-only session; no code. PR #257 was already merged by the owner
before review — docs verified against the default branch instead.

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

**Next steps:** owner answers the mock questions + ADR-011 A/C + gives WS1 go-word → implement
#258 with the two robustness amendments above.
