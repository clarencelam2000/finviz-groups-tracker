# Picks alpha scoreboard — significance audit (2026-09-05)

**Why this exists:** a session quoted `evaluate_picks.py --report` as showing the selector is
"negative at every horizon" and used it to argue a product direction. The owner pushed back and
asked for the methodology. Auditing it found the headline overstated. This note records what the
instrument actually measures, the three corrections, and what the data does and does not support,
so nobody re-derives it — or re-quotes the raw table without the caveats.

## What `evaluate_picks.py` actually measures

Read directly from `compute_scores()` (`scripts/evaluate_picks.py:112-175`):

1. For each `pick_date`, take the set of **industry groups** the selector chose.
2. Forward window starts **strictly after** `pick_date` (`start = date_pos[pick_date] + 1`) — no
   look-ahead.
3. Each group's forward return = compounded `perf_day` of the **group index** over the next
   1/3/5/10 trading sessions (`_compound`, `:105-115`). A window with any missing day → NaN, so
   every group is scored over an identical session set.
4. Three controls per date: SPY (`excess_spy`), the cross-sectional median of **all 144** tracked
   industries (`excess_median`), and the mean of the **non-selected** industries (`excess_nonsel`).
5. `--report` rolls up settled rows only (`n_sessions_avail == horizon`).

**So the measured strategy is: "buy the whole industry group at the pick-day close, hold N
sessions, no entry condition, no stop."** That is a test of the *group selector as a standalone
index strategy*. It is **not** a test of the picks the trader actually sees, and it does not touch
the Morning trigger/stop logic or the position engine at all. Ticker-level scoring is deliberately
unbuilt (`evaluate_picks.py` docstring: internal price chain is survivorship-biased → PICKS-4B).

## Correction 1 — `excess_spy` is contaminated; use `excess_median`

Over the sample window (62 sessions, 2026-06-09 → 2026-09-04): **SPY +3.93%**, **median tracked
industry +1.48%**. SPY is cap-weighted and mega-caps led; the median industry is not. So a large
part of `excess_spy` is the cap-weighting difference, not selector skill. `excess_median` and
`excess_nonsel` are the fair controls, and they are roughly half as negative.

## Correction 2 — the CIs in the report don't exist, and a naive bootstrap is wrong

`--report` prints means and hit rates with **no significance test**. Adding a naive by-date
bootstrap is also wrong: forward windows overlap heavily, so 39 h=10 dates over 62 sessions are
**~6 independent windows**, not 39. (The script's own `MIN_POWERED_DATES = 40` counts *dates*, so
the "powered" flag is too generous at long horizons — worth revisiting.)

Redone with a **moving-block bootstrap** (block length = horizon, 20k resamples), vs the median
control, the share of resamples above zero:

| horizon | mean excess vs median | 95% CI | share > 0 |
|---|---|---|---|
| 1 | −0.15% | [−0.38, +0.08] | 0.11 |
| 3 | −0.40% | [−0.90, +0.04] | 0.04 |
| 5 | −0.59% | [−1.21, +0.20] | 0.08 |
| 10 | −0.71% | [−1.90, +0.22] | 0.07 |

**Three of the four straddle zero.** The aggregate is weakly negative-leaning, not established.

## Correction 3 — it is regime-dependent within the sample

Split at the sample midpoint (`excess_median`, date-level means):

| horizon | first half | second half |
|---|---|---|
| 1 | −0.31% (n=24) | +0.01% (n=24) |
| 5 | −0.94% (n=24) | −0.15% (n=20) |
| 10 | −1.25% (n=24) | +0.16% (n=15) |

The negative aggregate is driven by the first half; the second half is roughly flat. A property
that flips sign across a 2.5-month sample is not a settled property.

## What the data *does* support (weakly)

Per bucket, vs median, h=10, moving-block bootstrap:

| bucket | mean | 95% CI | share > 0 |
|---|---|---|---|
| leaders | −1.58% | [−2.98, −0.14] | 0.01 |
| emerging | +1.48% | [−0.33, +2.75] | 0.94 |
| accel | −0.36% | [−2.60, +1.73] | 0.29 |
| rs_new_high | +0.06% | [−2.40, +1.89] | 0.42 |

The one finding that survives the honest estimator is the **opposite gradient between `leaders`
and `emerging`**: `leaders` gets monotonically worse with horizon (−0.28 → −1.00 → −1.58 vs median
at h=1/5/10) and `emerging` monotonically better (−0.03 → +0.50 → +1.48). A monotonic gradient is
harder to produce by chance than a single point estimate, and it matches a plausible mechanism
(already-extended leadership mean-reverting; early rotation continuing). `leaders` is also the
largest bucket — 13 of the ≤27 daily slots.

**This is a selector-tuning question (ADR-007 bucket caps), not an AI question.** It is not
actionable yet: one regime, ~6 independent windows, no out-of-sample period.

## What it does NOT support

- **It is not a short signal.** −1.6% over 10 sessions on a group index, before costs, in one
  regime, from ~6 independent windows, with the sign flipping across sample halves.
- **It does not say the system doesn't work.** The part of the system that does the work — entry
  at a trigger, a stop, and trailing management — is entirely unmeasured by this instrument. An
  edge that lives in entry timing and exit discipline can sit on top of a group set with no
  group-level alpha.
- **It does not justify a product posture on its own.** That was the overstatement being corrected
  here.

## Follow-ups worth tracking

- **PICKS-4B (ticker-level scoring)** is now more buildable than when it was deferred: D1
  `ticker_quotes` holds real daily OHLC for held + watchlist names, and
  `data/picks/sessions/morning.csv` holds 20+ sessions of trigger/stop/status. Until it exists,
  nobody can say whether the *traded* system has an edge.
- Add a significance estimator (moving-block bootstrap) to `--report` so the table is never again
  read as settled fact.
- Revisit `MIN_POWERED_DATES` — counting dates overstates power at h=5/10.
