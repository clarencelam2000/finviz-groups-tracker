# Session Notes

> **Future Claude:** read this immediately at session start. Summarize the current state for the user before doing anything else.
>
> **Format:** Append a new `---` delimited block per session. Header = date + workstream description. Keep the last 4 sessions here; a human will periodically move older entries to `.session/archive/session-notes-archive.md`. Do NOT replace existing entries — append only.
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

## 2026-09-27 — Roadmap triage + prioritization

**Status:** safe to close once the PR merges. Docs/planning only, no code changes.

**What landed:** `planning/roadmap-triage-2026-09-27.md` (P0–P3 tiers + owner asks), a pointer to
the priority order at the top of the SPRINT backlog, and AGENT-FEED-VERIFY marked verified
(manifest committed by the pipeline 2026-09-26).

**Key finding:** `evaluate_picks.py --report` paired test: selected minus non-selected is negative
at every horizon (−0.13/−0.46/−0.70/−0.76pp at 1/3/5/10d). `leaders` is worst and `all_green` is
the only positive bucket. This is **not significant yet** (overlapping windows #402, no bootstrap
#401), so measurement rigor (#401–#404) now leads the roadmap, ahead of more Picks-surface work.

**Next steps:** owner merges #425 (SPY history is unrecoverable daily), then decides the stale-PR
closures and the other asks in the doc's "what I need" section. After that, one PR for
#401/#402/#403.

---

## 2026-09-29 — process: `restate-intent` skill

- **Status:** safe to close.
- **Landed:** `.claude/skills/restate-intent/SKILL.md` + a CLAUDE.md "Restate intent" rule (under Session continuity). Doc/process only — no code, data, or PWA change, so no release triplet.
- **Why:** owner wants a plain-language restatement of goal + problem after long/rambling messages, before any work. Skill is committed per-repo (user-level skills aren't versioned and don't persist in cloud sessions); mirrored in the `distil` repo.
- **Next steps:** none.

---
## 2026-09-28 — PR #425 review + multi-ETF benchmark extension (SPY/QQQ/IWM)

**Status:** safe to close once the stacked PR is reviewed. Nothing merged by Claude.

**What landed (branch `claude/pr425-etf-extension-9psr9a`, PR stacked onto `feat/spy-full-columns` / #425):**
- Reviewed #425: sound, merges clean, tests pass. Findings: unknown quote labels were *dropped*, not "captured" as the docstring/warning claimed (now worded correctly); `BENCH_FIELD_MAP` mirrors the stock page, ETF-page labels unverified.
- Generalised the benchmark scrape to `BENCH_TICKERS = ["SPY","QQQ","IWM"]` (`delta_config.py`), eviction key `(date, ticker)`, renames `spy_index`→`index`, `SPY_*`→`BENCH_*`, `parse_spy_quote`→`parse_bench_quote`, `collect_spy`→`collect_bench`.
- `RS_BENCHMARK_TICKER = "SPY"`: `compute_deltas.load_benchmark` and `evaluate_picks.compute_scores` now filter to it. The evaluate_picks filter matters: its `drop_duplicates(keep="last")` would otherwise have silently scored picks against IWM.
- Only a SPY failure exits collect.py non-zero; QQQ/IWM failures emit `::warning::` — a non-zero exit would skip deltas and fail the picks gate for the day.
- Docs: CLAUDE.md benchmark section, README data tree + config table (`BENCH_TICKERS`, `RS_BENCHMARK_TICKER`).

**Next steps:** merge #425 then the stacked PR (or retarget), dispatch `collect.yml` once, do BENCH-ETF-2 (add real ETF labels). BENCH-ETF-3/4 in SPRINT backlog.

---
## 2026-10-23 — Picks scrape outage RCA + fix (Finviz screener redesign)

- **Status:** PR open, awaiting merge. Not safe to close until it merges (picks stays broken until then).
- **RCA:** since 2026-10-17 Finviz serves a redesigned screener (`/screener/stocks`, no `table.screener_table`, canvas grid). Not Cloudflare, not filter codes; I checked both on Actions. Full data is in `<script data-ssr-props>` JSON.
- **Landed (PR):** `_parse_table` SSR-JSON fallback rendered in legacy formats under legacy labels; `SCREENER_READY_SELECTOR` wait; `tests/test_screener_ssr_parse.py` + trimmed real fixture; `knowledge/investigations/finviz-screener-redesign-2026-10.md`. Verified live: probe on fix branch → Semiconductors 37 rows / 2 pages / 84 cols PASS.
- **Data gap:** picks for 2026-10-19..10-22 are lost (screen is live-only). Morning/pre-close/held use the same parser; they worked through 10-22 (probably a gradual rollout) but are covered by this fix too.
- **Next steps:** merge, then manually dispatch `collect_picks.yml` to capture 2026-10-23. Delete the `claude/diag-picks-screener` branch (push --delete was refused from the session).

---

## 2026-11-03 — picks outage: review + merge of screener-redesign fix (PR #435)

- **Status:** safe to close once post-merge verification below passes.
- **Landed:** reviewed PR #435. One fix applied: `_fmt_ssr_value` "earn" no longer guesses `/b` for date-only `earningsDate`; it emits bare `Mon DD` (already accepted by `replay_picks.py` and the PWA's earnings parser). Regression test added. Merged #435 and dispatched `collect_picks.yml` on default to confirm.
- **Outage scope:** picks failed 2026-10-17 → 2026-11-02 (fix sat unmerged 10-23 → 11-03). Dates 10-19..11-02 are unrecoverable (screener is live-only).
- **Next steps:** watch the next morning / pre-close / held runs (same parser). Delete stale `claude/diag-picks-screener` branch.

---

## 2026-11-03 — Open-PR triage (#418, #424, #425, #429, #430)

- **Status:** don't close until the owner merges the #425 → #430 stack in the GitHub UI (see below).
- **Merged this session:** #424 (#406 docs), #429 (roadmap triage), #418 (emerging-alpha study + exec-brief skill). For #418/#429/#430 I resolved conflicts by merging default in (only `.session/` files, plus derived `group_scores.csv` in #430: took default's, regenerated, identical). Session-note entries default had already archived were not re-added.
- **Fix pushed to #430:** `scripts/analyze_signals.py` `efficiency_series` now filters to `RS_BENCHMARK_TICKER`. Once #430 writes QQQ/IWM rows, its `drop_duplicates(keep="last")` would otherwise have measured the tape on IWM (the same bug #430 already fixed in `evaluate_picks`). Regression test added; 875 tests pass.
- **Blocker:** GitHub's API refuses to merge stacked PRs ("Merging stacked PRs via this endpoint is not supported"; auto-merge is also refused). #425 → #430 must be merged from the GitHub UI.
- **CI note:** `test` job is red on default (and so on every PR) from `eval_ai.py --all` flagging the 2026-10-26 AI capture ("Industrials" not in input). Pre-existing, unrelated to these PRs, tracked as #437. pytest itself passes.
- **Next steps:** owner merges #425, then #430. Then manually dispatch `collect.yml` once to confirm the 38 new benchmark columns and the QQQ/IWM rows populate (never live-verified; Cloudflare blocks the cloud sandbox). Then BENCH-ETF-2 (real ETF-page labels; see SPRINT).

---

## 2026-11-04 — Unblock and merge PR #430 (BENCH-ETF-1) + eval_ai exclusion

**Status:** safe to close once the exclusion PR is merged.

**What landed:** #430 was conflicted and flagged as a GitHub *stacked* PR (parent #425 already merged), so
the merge endpoint, auto-merge and base change were all refused. Merged default into its branch (clean, 875
pytest pass locally), then opened #438 from the identical head as a non-stacked PR and merged it (merge
`3ed4b4b`). Owner explicitly approved merging over the red `test` check. #430 itself may still show open:
close it by hand if so (its commits are in default).

**CI red cause (pre-existing):** `eval_ai.py --all` flagged `data/ai/debug/2026-10-26.json`
(`sectors.rotation_phase`: 'Industrials' not in input_blocks). Owner approved excluding it:
`EXCLUDED_CAPTURES` in `scripts/eval_ai.py` (`--all` only), SPRINT AI-EVAL-EXCLUDE.

**Next:** BENCH-ETF-2 (one live `collect.yml` run to confirm QQQ/IWM columns populate). Open question: was the
2026-10-26 'Industrials' a real hallucination or a guard false positive (cf. #414)?
