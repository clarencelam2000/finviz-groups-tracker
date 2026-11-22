# Session Notes

> **Future Claude:** read this immediately at session start. Summarize the current state for the user before doing anything else.
>
> **Format:** Append a new `---` delimited block per session. Header = date + workstream description. Keep the last 4 sessions here; a human will periodically move older entries to `.session/archive/session-notes-archive.md`. Do NOT replace existing entries — append only.
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

---

## 2026-11-20 — Daily scrape outage RCA + fix (ETF quote page multi-table)

- **Status:** PR open. Don't close until it is merged (ideally before the 17:00 ET EOD run today).
- **RCA:** `collect.yml` failed every run 2026-11-04..11-19. `parse_bench_quote` (from #425/#430) read only the first of six `.snapshot-table2` tables on the ETF quote page; perf labels are in the last → 0/7 → exit 1 → deltas skipped → picks aborted (green!) → morning/pre-close refused stale picks. Verified with a live-HTML probe on Actions (throwaway step on this branch's `probe_picks.yml`, reverted before the PR).
- **Landed (PR):** scan all `.snapshot-table2` tables; regression test on trimmed real fixture `tests/fixtures/etf_quote_spy_2026-11.html`; `knowledge/investigations/etf-quote-multi-table-2026-11.md`. 915 tests pass.
- **Data gap:** snapshots exist for every day; deltas missing 11-04..11-19 (recoverable, BENCH-QUOTE-FIX-4, owner decision); SPY/QQQ/IWM rows and picks for those dates are lost (live-only).
- **Next steps:** merge, then dispatch `collect.yml` (or let the 17:00 ET run go) and confirm deltas for 2026-11-20 + picks + Monday morning status. Owner decisions pending: BENCH-QUOTE-FIX-3 (decouple benchmark failure from deltas) and -4 (backfill). BENCH-QUOTE-FIX-2 (picks job false green) is a straightforward fix.
