# Picks Alpha Evaluation — automated scoreboard + standing playbook

**Owner-facing goal:** answer, continuously and without hand-analysis, *"are the groups and
stocks we surface in the Picks tab actually generating alpha, and are our risk levels
well-placed?"*

**Status:** SPEC (not built). Supersedes the one-line `PICKS-4 (eval_picks.py)` placeholder.
Written 2026-07-14 by the rotating staff analyst after the first empirical read
(`knowledge/investigations/picks-alpha-assessment-2026-07-14.md`). **Read that report first** —
it defines the methodology this doc automates and records the baseline (negative point
estimates at ~13 dates, driven by the `leaders` bucket; not statistically conclusive).

> **Why this exists / why now.** The one-off assessment took a full analyst session and had to
> reconstruct forward returns by hand from append-only CSVs, with no real OHLC (stooq was
> blocked). That is not repeatable weekly. The single highest-leverage thing we can build is a
> script that appends a forward-return scoreboard after each daily collect, so that in 2–3
> months the regime-spanning answer exists automatically instead of costing another hand
> analysis. **Everything else in this doc is secondary to getting the scoreboard writing rows.**

---

## Part 1 — `scripts/evaluate_picks.py` (the scoreboard)

A pure-ish batch script, run daily *after* `compute_deltas.py` (so that day's `perf_day` for
every group is already in `industries/snapshots.csv`). It does **not** scrape anything — it only
reads CSVs we already commit. Idempotent and last-write-wins per date, exactly like the rest of
the pipeline.

### What it writes

Two new append-only artifacts under `data/picks/`:

```
data/picks/eval/group_scores.csv    # one row per (pick_date, group, horizon)
data/picks/eval/ticker_scores.csv   # one row per (pick_date, ticker, horizon) — see caveat
```

`group_scores.csv` columns:

| col | meaning |
|-----|---------|
| `pick_date` | date the selector chose the group |
| `group` | Finviz industry name |
| `buckets` | pipe-joined `list_category` tags that selected it that day (e.g. `leaders\|accel`) |
| `horizon` | forward trading sessions: 1, 3, 5, 10 |
| `n_sessions_avail` | how many forward sessions actually existed when the row was computed (< horizon ⇒ the return is partial; row is rewritten once full) |
| `fwd_ret` | compounded `perf_day` of the group over `horizon` forward sessions |
| `fwd_ret_spy` | SPY forward return over the same window (from `data/benchmark/snapshots.csv`) |
| `fwd_ret_median` | same-window median forward return across **all** tracked industries (the cross-sectional control — this is the honest alpha benchmark) |
| `excess_spy` | `fwd_ret − fwd_ret_spy` |
| `excess_median` | `fwd_ret − fwd_ret_median` |

`ticker_scores.csv` mirrors it at the stock level (`pick_date`, `ticker`, `buckets`, `focus_eligible`,
`horizon`, `entry_price`, `fwd_ret`, `excess_spy`, `stopped_out`, `r_multiple`) — **but only once
we have real OHLC** (see § Data-quality blockers). Until then, write it from the internal
price-chain with a `price_source=internal_chain` column and treat every number as an upper bound
(survivorship bias — a ticker is only re-priced while its group stays picked).

### Algorithm (self-contained — a cold reader can implement from this)

1. Load `data/picks/picks.csv`; dedupe to unique `(date, group)` and `(date, ticker)`, carrying
   the pipe-joined `list_category` set.
2. Load `data/industries/snapshots.csv` (has `date`, `name`, `perf_day`) and
   `data/benchmark/snapshots.csv` (SPY `perf_day` per date).
3. Build the sorted list of trading dates from snapshots. `fwd_sessions(D, h)` = the next `h`
   dates strictly after `D` in that list (positional, so weekends/holidays are skipped for free —
   same convention as `find_trading_date_back` in `compute_deltas.py`).
4. For each `(pick_date, group, horizon)`: compound `(1+perf_day/100)` over the forward sessions
   → `fwd_ret` (pct). Same for SPY. For `fwd_ret_median`, compute every tracked industry's forward
   return over that exact window and take the median. Write NaN-safe; if `n_sessions_avail == 0`
   skip the row entirely (nothing to score yet).
5. Rewrite (last-write-wins per `(pick_date, group, horizon)`) so a row first written with a
   partial window gets corrected once the full horizon exists. This is why `n_sessions_avail` is
   stored — a consumer can filter to `n_sessions_avail == horizon` for the "settled" scoreboard.

### Report mode

`python scripts/evaluate_picks.py --report [--min-settled 5]` prints the roll-up the owner cares
about, straight from `group_scores.csv`:

- Mean/median `excess_spy` and `excess_median`, and hit-rate (% > 0), overall and **per bucket**,
  at each horizon — only over settled rows.
- The **paired per-date** test (mean selected − mean non-selected same date) — the single most
  honest number, since it cancels the market factor. This is what moved from −0.36 (h=1) to −1.95
  (h=5) in the baseline.
- Sample-size guard: print effective N = number of distinct pick_dates, and a one-line caveat
  whenever it's < 40 ("not yet powered — treat as directional").

### Testing (house rule: every `scripts/` change ships tests)

`tests/test_evaluate_picks.py`, all with `tmp_path`/`StringIO`, no real files:
- forward-compounding math on a hand-built 6-session fixture (positive and negative days);
- weekend/holiday gap is skipped positionally (insert a date gap, assert horizon still counts
  trading sessions not calendar days);
- partial-window row (`n_sessions_avail < horizon`) is written then correctly overwritten when a
  later date arrives (last-write-wins);
- empty/headers-only `picks.csv` ⇒ no crash, writes header only;
- median control excludes NaN groups.

### Wiring (do NOT bundle with the script PR — separate follow-up)

Add a step to `collect_picks.yml` (or better, `collect.yml` right after `compute_deltas.py`, since
eval needs the day's snapshot, not the day's picks) that runs `evaluate_picks.py` and commits the
two eval CSVs. **It is a third `data/` writer** — put it in the `finviz-data-commit` concurrency
group and give its commit step the `git pull --rebase` that AUD-4 is already tracking, or it will
race `collect.yml`/`generate_ai.yml`. Gate the report on ≥ enough history; the writer runs from
day one (it just writes fewer settled rows early).

---

## Part 2 — Standing playbook: what to re-check as data accrues

> This is the "future eyes" section. If you are a later Claude or teammate picking up the Picks
> alpha question, **start here.**

**Re-run the full assessment at ~60 and ~100 trading sessions** (≈ 2026-09 and 2026-11 at 1
run/day). ~13 dates in one mean-reversion regime proves nothing; the whole point is to see the
numbers across at least one regime change. The scoreboard (Part 1) makes this a `--report` call
instead of a fresh analysis.

**The specific hypotheses the baseline raised — confirm or kill each with more data:**

1. **The `leaders` bucket is the drag.** At 13 dates it ran −4.70% vs SPY at h=5 (12% hit) —
   consistent with "we buy extended sustained-strength leaders right as they mean-revert." If this
   holds at 60+ dates across regimes, that's a real selector finding, not noise → consider whether
   `leaders` should be entry-timed (only on a pullback to a moving average) rather than bought at
   arbitrary extension. **Do not act on it yet** — one chop regime will always punish a
   strength-chaser.

2. **The rotation-trigger buckets (`rs_new_high`, `accel`) were the only positives.** +1.00% vs
   the industry median (67% hit) for `rs_new_high` at tiny N. This *is* the product thesis
   ("catch capital rotating early"). **Watch whether it holds** — if these buckets keep the edge
   and `leaders` keeps bleeding, the product's alpha lives in rotation signals, and that should
   drive both selector weighting and what the PWA emphasizes.

3. **The Focus gate showed no edge (directionally worse).** Focus is supposed to *concentrate*
   quality, not just shrink the list. If after more data Focus-eligible still ≤ non-Focus on
   forward returns, the gate/scoring needs rework — revisit `PICKS-3B-FOCUSGATE` (tighten to full
   `stage2==1`?) and the Focus score weights. Currently it's a plausible-but-unproven filter.

4. **Extension vs. stop placement.** ~10% of picks touched their stop within 5 sessions on
   close-only data (an underestimate). The product buys strength, which is often extended
   (`atr_ext_50` median 2.57), then places a moving-average stop — structurally these fight each
   other. Once we have real intraday lows, compute the true stop-out rate and **R-multiple
   expectancy** (the number the owner actually asked for): a 35%-win system is fine if avg-win /
   avg-loss > ~2. Grade the *displayed* risk levels, not a theoretical one.

**Statistical discipline reminder:** at these sample sizes prefer the paired per-date test and
report effective N (distinct dates, not row counts — forward windows overlap heavily so rows are
not independent). Don't tune the selector on < ~40 dates; you'll fit noise.

---

## Part 3 — Data-quality blockers (fix before the stock-level scoreboard is trustworthy)

1. **No real OHLC.** stooq is blocked from this environment (dated CSV endpoint 404s; undated
   returns an anti-bot JS challenge, not CSV — on both `.com` and `.pl`, through the proxy). The
   internal price-chain from `picks.csv` repeats is survivorship-biased (tickers only re-priced
   while still picked; 257/641 tickers had no follow-up). **We already have an OHLC-capable
   source:** the FMP key wired into the Cloudflare Worker (`worker/`, TICKER-* tasks). A
   `/history` endpoint (or an offline FMP pull in `evaluate_picks.py` behind the key) gives real
   daily H/L for gap-accurate stop simulation and unbiased forward returns. This is the unlock for
   the whole R-multiple analysis — spec'd here, not built, because it needs the FMP key and is
   more than a half-day.

2. **`risk_*_pct` naming footgun.** `risk_20ma_pct` / `risk_50ma_pct` are stored as **fractions**
   (median 0.06 = 6%), which is intentional and documented in `scripts/picks_metrics.py` /
   `picks_config.py` and handled correctly by the PWA — but the `_pct` suffix misled even the
   analyst writing the assessment. Low-risk lasting fix: rename to `risk_20ma_frac` /
   `risk_50ma_frac` (schema migration via the `ensure_picks_csv()` superset pattern), or at
   minimum add the "fraction not percent" note at every consumer. Anyone building stop logic off
   the raw column is one `/100` away from 0.06%-wide stops.

3. **`display_methodology` version boundaries.** The Focus gate changed v1→v2 on 2026-07-01
   (added liquidity + earnings penalties). When the scoreboard compares Focus vs non-Focus across
   dates, label each row with the methodology version in effect (`replay_picks.py` already resolves
   this by date) so a gate change doesn't silently straddle the comparison — same discontinuity
   class as the `momentum_score` 7tf→6tf boundary noted in PIPE-1.

---

## Part 4 — What I would build in priority order (if I had more than half a day)

1. **`evaluate_picks.py` group-level scoreboard + tests** (Part 1). Highest leverage, no external
   deps, buildable in one focused session. Makes every future re-assessment a `--report` call.
2. **Wire it into CI** as a third data writer (respecting AUD-4's concurrency/rebase fix).
3. **FMP `/history` unlock** (Part 3.1) → real OHLC → the stock-level scoreboard, true stop-out
   rate, and R-multiple expectancy. This is the analysis the owner most wants and the one we
   couldn't do. Bigger than a half-day; needs the FMP key and a small Worker endpoint or offline
   pull.
4. **`risk_*_pct` rename** (Part 3.2) — small, prevents a future correctness bug.
5. Only after ~60 dates: revisit selector weighting / Focus gate using the scoreboard, per the
   Part 2 hypotheses. Not before — it would be fitting noise.
