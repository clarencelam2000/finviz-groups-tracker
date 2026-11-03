# Roadmap triage — 2026-09-27

Staff-eng triage of SPRINT.md, 50 open issues and 15 open PRs. What's below is what I checked
myself; claims marked *unverified* I did not check.

## The headline: the picks don't beat their own control group (yet)

`python scripts/evaluate_picks.py --report` on data through 2026-09-25 (the paired test, run
date by date):

| horizon | selected − non-selected (mean pp) | dates positive |
|---|---|---|
| 1d | −0.13 | 29/62 |
| 3d | −0.46 | 26/60 |
| 5d | −0.70 | 21/58 |
| 10d | −0.76 | 24/53 |

`leaders`, the biggest bucket (N≈620 at 5d), is the worst: −0.76pp compared with the median at
5d, and −0.85pp at 10d. `all_green` is the only bucket that's positive, at +2.02pp at 10d with
N=88.

**Caveats (why this isn't a verdict yet):** the windows overlap, so the same move gets counted
more than once and N overstates how much independent evidence there is (#402). There's no
significance estimate (#401). `excess_spy` is skewed by cap-weighting (#403). These are
**group-level** returns, not the tickers actually traded (#404). So the honest reading is that
there's no evidence of edge, and some weak evidence of the opposite. That's exactly the
question epic #408 exists to answer.

**Why this reorders the roadmap:** most of the backlog (AI-NEXT P1/P2 prose on picks, the
OVERHEAD-3 retune, Focus scoring polish) builds more on top of picks. If the selector has no
edge, those features just explain noise more persuasively. Measure first, then build.

## Priority tiers

### P0: this week (cheap, time-sensitive, or unblocks everything else)

1. **Merge PR #425 (SPY full-column scrape, #419).** Each trading day it stays unmerged is SPY
   history we can never recover. It has been open for 7 days. *Owner: review/merge.*
2. **#401 + #402 + #403: make the alpha report trustworthy.** Add a moving-block bootstrap CI,
   count independent windows instead of dates, and demote `excess_spy`. All three live in
   `scripts/evaluate_picks.py`, touch no schema, and fit in one PR. After that the table above
   either holds up or it doesn't.
3. **Open-PR hygiene.** 15 are open. Proposed disposition:
   - Close as stale/superseded: #55, #76, #95, #146, #148, #172, #277, #278, #361, #362
     (all at least a month old, targeting code that has since moved). *Needs owner OK.*
   - Decide: #357/#358 (WS5-4b Tier-2 reminders + earnings push, a month old). Either rebase and
     land them or close them. I lean toward landing #358, because earnings risk ties straight to
     #356.
   - Land: #424 (#406 docs housekeeping, low-risk). Decide on #418 (exec-brief skill plus the
     emerging-alpha study plan, which feeds #405).

### P1: next 2–4 weeks

4. **PICKS-4B / #404: ticker-level scoreboard + R-multiple expectancy.** This is the system
   actually being traded. It has been blocked on real OHLC data. The WS5 `ticker_quotes`
   feed and the wide morning scrape may now cover held/watched names, but not the full pick
   universe (*unverified*; needs a scoping check first).
5. **#405: the leaders vs emerging gradient / ADR-007 bucket caps.** The data above
   (leaders worst, all_green best) points the same way. Run it after #401–#403 so it rests on
   real confidence intervals.
6. **Close the WS5 loop that already exists.** The engine and feed are live, so finish the
   high-value owner-facing gaps: **#337 WS5-7 managing-card overhaul (tagged HIGH)**, #332
   (recently-closed grace window), and #325 (when actions take effect copy).
7. **Ops reliability:** #276 (no retry when the collect_eod run itself fails), #274 (right-size
   `PICKS_GATE_WINDOW_MINUTES` from run history), and WS5-HELD-TIMEOUT. The winter DST
   transition (2026-11-01) is the first real test of the ADR-010 single-trigger design, and #275
   says the backstop crons are fixed-UTC and can land inside the picks gate window in winter.
   **Fix #275 before 2026-11-01.**

### P2: after the alpha verdict (gated on P0-2 / P1-4)

8. **AI-NEXT P0b → P2a → P2b/P2c (Morning prose).** The design is locked, and the spike picked
   renderer-owned templates. P2a needs batching or concurrency (median 141s per call, #416).
   This is **gated on the verdict**: the Morning tab reads status, not the selector, so it could
   go ahead independently. But AI-NEXT-P1 (Picks thesis) should wait.
9. **Effort A #378 (shared per-ticker card schema).** This refactor pays off before more card
   surfaces get added (#379, #305, and AI P2b all touch the cards).
10. OVERHEAD-3/6, VOL-FLOOR-2, and MORN-SORT-2: small tuning work. Only worth doing once the
    scoring shows it has edge.

### P3: parked / consider closing

- Old spec rows (INS-*, HIR-*, LOOK-B*, MOT-*, GAP-*, AI-1/2/4, PLAN-2) date from June and
  largely predate the Picks/WS5 direction. I recommend a one-time prune: keep HIR-I
  (since-last-look digest) and HIR-TAX-TRIPWIRE, and archive the rest.
- **D1 / PWA-1 / DEBT-3 (rename the default branch to `main`).** It has been open since June and
  the whole toolchain hardcodes `claude/elegant-babbage-hlxnfy`. It's cheap to keep deferring,
  but it gets costlier with every new workflow. Either schedule it for one quiet weekend or
  formally won't-fix it.
- #256 (Google 2.5 model deprecation): probably obsolete now that we're on 3.8 Flash. Close it.
- **AUD-3 (ruff gate)** and **AUD-2 (tests for export_db/backfill)** are good first tasks for
  cheap-model subagents.

## Housekeeping done in this PR

- AGENT-FEED-VERIFY is **verified**: `data/api/manifest.json` was `generated_at`
  2026-09-26T01:50Z with `as_of` 2026-09-25, committed by the scheduled pipeline. Marked Done.

## Low-confidence calls / what I need from the owner

1. **The alpha reading is not yet significant.** Please don't retune or kill anything based on
   the table above until #401–#403 land.
2. **I'm judging the stale-PR closures by age and title only.** I didn't review each diff. Say
   the word and I'll go through them one by one before closing.
3. **The PICKS-4B OHLC data source is unresolved.** FMP `/history` via `worker/` is the plan of
   record. Is FMP's plan and quota OK for about 400 tickers a day?
4. **Priority of WS5 (#337) vs measurement (#401–404).** You're the trader, so you decide which
   hurts more right now: position-management UX gaps, or not knowing whether the picks have edge.
   I've put measurement first.
5. **Branch rename (D1).** Do it or won't-fix it? Only you can change the default branch.
