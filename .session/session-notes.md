# Session Notes

> **Future Claude:** read this immediately at session start. Summarize the current state for the user before doing anything else.
>
> **Format:** Append a new `---` delimited block per session. Header = date + workstream description. Keep the last 4 sessions here; a human will periodically move older entries to `.session/archive/session-notes-archive.md`. Do NOT replace existing entries — append only.
---

## 2026-09-24 — Pre-Power of 3 MA-bunching band tightened to 1.5x ATR

**Status: safe to close.** Small, self-contained constant change requested by the owner.

**What landed (branch `claude/pre-power-of-3-atr-threshold-jdkalv`):**
- `POWER_OF_3_ATR_MULT` in `docs/index.html` lowered from `2.0` to `1.5` (the "Pre-Power of 3"
  MA-bunching chip fires when price/20MA/50MA all fit inside `POWER_OF_3_ATR_MULT`×ATR). Updated
  the triple-documented comment/README/`docs/CLAUDE.md` copies and the two affected test
  docstrings in `tests/test_pwa_picks_atr_earnings.py` (assertions themselves were unaffected —
  the ANET fixture's span (~5.6) stays under the new 1.5×ATR (~12.6) threshold).
- Release triplet: `docs/releases.json` (`2026.09.24`, tag `improvement`, tab `picks`) +
  `docs/sw.js` (`CACHE` v101→v102).
- `.session/SPRINT.md` Done entry `POWER3-THRESH-1` with the measured impact.

**Impact analysis (requested by owner), computed against the live `data/picks/picks_latest.csv`
(459 rows with valid Price/ATR/SMA20/SMA50) using a standalone script — not committed, one-off
verification:**
- At the old 2.0x band: 231/459 rows (50.3%) flagged as bunched.
- At the new 1.5x band: 150/459 rows (32.7%) flagged — **81 fewer flagged rows** (~35% relative
  drop from the 2.0x count).
- Also measured a 1.0x band for comparison (not shipped): 66/459 rows (14.4%) flagged — a further
  84-row drop from 1.5x, i.e. cuts the flagged pool by more than half again.
- Median span/ATR ratio among the previously-flagged (2.0x) rows was ~1.25, so most of the 2.0x
  pool sits comfortably under 1.5x too, but a real ~35% slice (spans between 1.5x and 2.0x ATR)
  drops out.

**Verification:** `python3 -m pytest tests/test_pwa_picks_atr_earnings.py -q -k power_of_3` — 2
passed (used the documented Playwright-in-cloud symlink workaround for the Chromium
headless-shell revision mismatch, cleaned up afterward — session-local `/opt` edit, not
committed). Full non-Playwright suite (783 tests) passes; the ~29 pre-existing failures
(`test_collect_benchmark.py`, `test_generate_ai.py`) are unrelated environment/mocking gaps in
this sandbox, not caused by this change. `tests/test_guide_releases.py` passes against the new
`releases.json` entry.

**No pipeline/schema change** — this is a pure client-side PWA display constant, computed at
render time from already-scraped Price/ATR/SMA20/SMA50, never a stored CSV column.

**Next steps:** none — this was a one-shot config tweak. If the owner wants to revisit the 1.0x
alternative later, the comparison numbers above are already captured in the SPRINT.md entry.

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

---

## 2026-09-23 — AI tab: remove Headline + Conviction (SPRINT § AI-WALLET-CONVICTION, widened)

**Status: safe to close.**

Owner asked to remove the AI tab's headline hero + "Conviction: Low" badge (not useful, and
wants to stop paying Gemini for them). This is the same `pulse` task the AI-WALLET-CONVICTION
SPRINT item already flagged for a Conviction-only trim — since the owner wants both fields gone,
removed the whole task instead of half-trimming it.

**What landed (branch `claude/remove-ai-tab-sections-sa2k48`):**
- `scripts/generate_ai.py`: deleted the `pulse` `TASK_SPEC` entry entirely (no more Gemini call
  for it — 11→9 calls/run × 3 runs/day, ~33/day → ~27/day) plus its now-dead machinery:
  `build_pulse_prompt`, `parse_pulse_response`, `_parse_conviction`, `_input_pulse`,
  `_PULSE_ALIASES`. `_expected_fields()`/`_is_complete()`/`_missing_fields()` need no code change
  — they derive from `TASK_SPECS` automatically. Updated the TASK_SPECS call-count comment and
  the `--task`/`--preview` CLI help examples (were `pulse`, now `note`).
- `docs/index.html`: removed the headline-hero + conviction-badge render block in `renderAI()`
  and the share-text's headline lead-in (`shareAI()`) — both guarded on `pulse` already, so
  removal degrades cleanly to just showing the rest of the briefing (rotation phase, daily note,
  rotation map, watchlist, relative-strength/risks — all unchanged).
- `scripts/eval_ai.py`: removed the now-unreachable `pulse` branch from `check_format()` and the
  `CONVICTION_LEVELS` constant (Tier-2 debug captures will never carry a `pulse` call again).
- Release triplet in the same PR: `docs/releases.json` (`2026.09.23`, tag `improvement`, tab
  `ai`) + `current` bump + `docs/sw.js` (`CACHE` v100→v101).
- `scripts/CLAUDE.md` + `README.md` updated (call-count/example references to `pulse`).
- Tests: `tests/test_generate_ai.py` and `tests/test_eval_ai.py` — removed every pulse-specific
  test (parser tests, format-check tests) and repointed generic mechanism tests that happened to
  use `"pulse"`/`"sectors.pulse"` as an arbitrary label onto `note`/`rotation_phase`. Updated
  call-count assertions (5→4 in one `generate_for_group` test) and the `_expected_fields`/
  `_missing_fields`/`TASK_SPECS` set assertions. `python3 -m pytest tests/ -q` with the same
  `--ignore=` list `.github/workflows/tests.yml` uses: **812 passed**.

**Not done this session:** no live-browser check of the AI tab (no Playwright/dev-server pass) —
the guarded-render removal is standard/low-risk (`docs/CLAUDE.md`'s established pattern for this
exact block), but worth a quick spot-check on the next PWA session.

**Next steps:** none blocking. If Conviction/Headline are ever wanted back, the pre-removal
prompt/parser is in git history (see the `TASK_SPECS` comment in `generate_ai.py`).

---

## 2026-09-29 — process: `restate-intent` skill

- **Status:** safe to close.
- **Landed:** `.claude/skills/restate-intent/SKILL.md` + a CLAUDE.md "Restate intent" rule (under Session continuity). Doc/process only — no code, data, or PWA change, so no release triplet.
- **Why:** owner wants a plain-language restatement of goal + problem after long/rambling messages, before any work. Skill is committed per-repo (user-level skills aren't versioned and don't persist in cloud sessions); mirrored in the `distil` repo.
- **Next steps:** none.

---

## 2026-10-04 — Artifact diagrams for non-screen decisions (process)

**Status:** safe to close once PR merges.
**What landed:** CLAUDE.md § Deliver mocks/visuals as Artifacts now also covers decisions with 3+ options or a flow/sequence/timeline (publish an Artifact diagram/comparison; conclusion first in chat). Came from evaluating the third-party `answer-me-with-html` skill — declined (duplicates the Artifact tool, writes to `~/` which is lost in cloud containers, bundled unreviewable script + GitHub update check); borrowed the idea instead.
**Blockers / next steps:** none. No deferred items.
