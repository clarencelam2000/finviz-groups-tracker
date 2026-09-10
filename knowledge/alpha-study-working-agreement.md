# Working agreement for alpha-seeking studies

> Written 2026-09-08 after a session where the owner had to correct the same class of
> mistake five separate times. **Read this before starting any signal/alpha/backtest
> work in this repo.** It is not style guidance — it is a record of framings that were
> tried, rejected by the owner, and must not be re-proposed.

## Who the owner is

A momentum swing trader. Holds days to weeks. Reads charts. Trades individual names
inside a group the system points at. Not a quant, not publishing research, not
interested in statistical purity for its own sake. **The standard is whether an
analysis changes where money goes.**

## Rejected framings — do not re-raise these

Each of these was proposed in the 2026-09-08 session and explicitly shot down.

### 1. "We only have N days — wait for more data"

Rejected, and the owner's reasoning is better than the objection. Their hypothesis is
that signal efficacy is **regime-dependent** — a swing trader adapts to the tape, so a
strategy that works in a thrust may fail in chop. If that is true, a longer sample
spanning several regimes produces an average that is true in **no** regime. More data
would make the number worse, not better.

**Do instead:** condition on regime. Segment the history. Work with what exists.

### 2. "We should isolate the buckets / control for confounds"

Rejected. Bucket overlap (a group tagged Emerging *and* Accel *and* RS New High) is a
**conviction signal**, not contamination — the owner's phrase is "firing on more
cylinders." The goal is deciding where to look, not a clean experiment.

**Do instead:** if overlap might mislead a decision, say which decision and show both
numbers. Otherwise say nothing.

### 3. "This might just be momentum"

Rejected, and it is the worst of the five because it misunderstands the whole product.
**Momentum continuing is the thesis.** "Groups that have been going up keep going up"
is not a confound to be explained away — it is what the system is for.

**Do instead:** ask the comparative question. Not "is this momentum?" but **"does our
filter find momentum better than a simpler filter?"** That version produced the
session's only genuinely actionable finding: the two-floor emerging gate
(`regime_short_long > 0.15 AND rs_score > 0.5`, ~7 groups/day, +0.60pp over 10 sessions,
positive on 60% of days) is **beaten by simply taking the top decile by
`regime_short_long`** (~14 groups/day, +1.27pp, 71% of days). The extra floor costs
money. That is a finding; "we cannot cleanly attribute the effect" is not.

### 4. Publication vocabulary

p-values, "not yet powered", "report it as a case study, never with a p-value",
"the honest strongest claim this design could support". All rejected —
*"I'm not submitting this to the Quant Trader Association."*

**Do instead:** "48 observations, don't size on it." One line, owner's language, then
move on. Real limits still get stated; they just get stated once and never become the
headline.

### 5. Anthropomorphising a filter

*"the gate just along for the ride"* — the owner rightly asked why a filter is being
described as though it has market-moving power. A gate is a filter on a list.

**Do instead:** describe what it selects and whether that selection outperforms.

## The h=1 mistake (worth its own entry)

An adviser recommended trusting the **1-session-forward** result above all others,
because 1-day windows do not overlap and so are statistically cleanest. This was
relayed to the owner more or less intact, with hedging about "smoke alarms" and
"warning lights."

The owner's response: *"so are we day trading now?"*

**They were right.** h=1 means holding for one day. It is not their trade. Statistical
cleanliness is not a reason to elevate a horizon the owner will never hold. The correct
move was to report h=5 and h=10 — the horizons they actually trade — note in one line
that shorter windows are noisier evidence, and stop.

**Rule:** measurement horizons follow the trading horizon. Always. If the tradeable
horizon has weaker statistics, say that in one sentence and carry on measuring it.

## Concerns the owner accepted

Not everything was rejected. These landed and are worth raising again in future work:

- **Row-pooling bias.** Averaging per-row lets a day with 16 firing groups outvote a day
  with 3, and busy days are usually strong-market days. Collapse to one number per date.
- **The two arithmetic defects** (§ below) — real, and the owner wanted them fixed.
- **Only seeing part of the signal.** `picks.csv` caps Emerging at 4 slots, so it holds
  202 of the 393 group-days where the gate actually fires. Replay from `deltas.csv`.
- **A negative control.** Running the same measurement on randomly-picked groups, to
  check the harness does not manufacture an edge from nothing.

### The two arithmetic defects (keep these fixed)

1. **Count-dependent gain.** `mean(fire) − mean(nonfire)` equals
   `N/(N−k) × (mean(fire) − mean(all))`. With k = 3..16 over N ≈ 144 that is a
   1.02x..1.12x multiplier — and k is regime-correlated (more groups fire in a trending
   tape), so it inflates exactly the days a regime analysis is about. **Always subtract
   the full cross-sectional mean.**
2. **Compound-then-subtract.** Differencing simple compounded returns leaves a
   market×spread cross term. A group beating the market by 1%/day for 10 sessions shows
   an 11.4pp gap in a +1%/day market but 10.5pp in a flat one — same skill, 9% bigger
   reading. **Compound in log space, convert back only for display.** Compounding is not
   discarded; only the double-count is.

## The playbook — how to answer "does bucket X earn its place?"

**This is now one command.** `scripts/analyze_signals.py` scores any selection rule
against every other on identical dates and identical forward windows, so the answer to
"should we drop Accel", "are Leaders giving us alpha", "is top-10 better than top-20"
is a leaderboard, not a new study.

```bash
python3 scripts/analyze_signals.py --compare --horizons 5,10        # everything
python3 scripts/analyze_signals.py --compare leaders,top14_regime   # head-to-head
```

Rules live in `RULES` in that file. Adding one is a function plus a dict entry. The
deployed buckets (`emerging`, `leaders`, `accel`, `rs_new_high`) import their floors
from `picks_config.py`, so they track the live selector instead of drifting.

**Always include a single-variable baseline.** A multi-condition screen has to beat
"rank on one column, take the top N" to justify its complexity. That comparison is what
found the 2026-09-08 result; without it the emerging gate looked fine in isolation.

**Always split by regime** (thrust vs chop) before recommending anything. A rule that
loses in both tapes is dead. A rule that loses in one is a scheduling question, not a
deletion question.

### Results as of 2026-09-08 (54 dates, mostly chop, one thrust 07-28..08-14)

Excess return vs the day's average industry group, 10 sessions forward:

| Rule | Picks/day | All dates | Thrust | Chop | Hit rate |
|---|---|---|---|---|---|
| `top5_regime` | 5 | **+1.72pp** | — | — | 54% |
| `top10_regime` | 10 | **+1.64pp** | +3.35 | +0.94 | 73% |
| `top14_regime` | 14 | +1.30pp | +2.43 | +0.84 | 73% |
| `top28_regime` | 28 | +0.87pp | — | — | 75% |
| `emerging` (deployed gate) | 7 | +0.60pp | +0.79 | +0.51 | 60% |
| `accel` (deployed) | 18 | **−1.02pp** | −2.26 | −0.40 | 36% |
| `rs_new_high` (deployed) | 8 | **−1.36pp** | −3.43 | −0.39 | 41% |
| `leaders` (deployed) | 11 | **−2.00pp** | −1.56 | −2.16 | 31% |
| `top10_momentum` | 10 | **−2.69pp** | −2.06 | −2.93 | 25% |

**Three of the four deployed buckets lose money against simply holding the average
industry group, in BOTH tapes.** Leaders is the worst and has the most slots (11 of a
27-name daily budget). Only `regime_short_long` cuts are positive, and they are positive
in both regimes.

`momentum_score`-ranked cuts are strongly negative, which says high-momentum groups
mean-reverted over 10 sessions across this sample. 14 thrust dates is thin — but the
signs are consistent across both segments and both horizons, which is the part to trust.

**Do not treat this as settled product direction.** It is a measurement. Changing
`picks_config.py` is a product change and needs the owner's explicit sign-off.

## Communication

`.claude/skills/exec-brief` is mandatory and now carries the examples rule. The short
version: headline first, one decision with a recommendation and the cost of not
deciding, **a worked numeric example for every concept**, and detail layered so the
owner can stop reading at any point. Mental load is the binding constraint — when the
owner says it is rising, that is a signal the answer is too long and too abstract, not
that they need more caveats.
