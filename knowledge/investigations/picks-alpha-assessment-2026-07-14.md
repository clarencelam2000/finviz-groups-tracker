# Picks Pipeline Alpha Assessment — 2026-06-25 to 2026-07-14

Local data only: 13 pick dates in `data/picks/picks.csv` (2,854 rows, 641 unique tickers),
industry `perf_day` from `data/industries/snapshots.csv`, SPY from `data/benchmark/snapshots.csv`.
All returns in raw %, forward windows in trading sessions. Analysis code ran in a session
scratchpad (not committed); the methodology below is sufficient to reproduce.

## A) Group-selection alpha (highest-N test)

Forward cumulative return per selected group (deduped per date), compounding `perf_day` over the
next 1/3/5 sessions, vs (i) SPY and (ii) same-date cross-sectional median of all ~145 industries.
Control = all non-selected industries same dates.

| Cohort | h | N | mean exSPY | med exSPY | hit vs SPY | mean exMED | med exMED | hit vs MED |
|---|---|---|---|---|---|---|---|---|
| Selected | 1 | 206 | −0.50 | −0.52 | 38% | −0.37 | −0.18 | 42% |
| Selected | 3 | 175 | −1.34 | −0.99 | 32% | −0.71 | −0.20 | 46% |
| Selected | 5 | 140 | −2.72 | −2.81 | 29% | −1.76 | −1.13 | 37% |
| Non-selected | 1 | 1522 | −0.11 | −0.18 | 46% | +0.01 | +0.02 | 51% |
| Non-selected | 3 | 1265 | −0.57 | −0.55 | 41% | +0.01 | +0.03 | 51% |
| Non-selected | 5 | 1012 | −0.77 | −0.83 | 41% | +0.16 | +0.09 | 52% |

By bucket (a group can be tagged in multiple buckets), 5-session horizon:

| Bucket | N (5d) | mean exSPY | hit SPY | mean exMED | hit MED |
|---|---|---|---|---|---|
| leaders | 80 | **−4.70** | 12% | −3.76 | 20% |
| emerging | 32 | −1.00 | 44% | −0.06 | 56% |
| accel | 29 | −0.44 | 45% | +0.57 | 48% |
| rs_new_high | 27 | −0.05 | 52% | **+1.00** | 67% |

Paired per-date test (mean selected − mean non-selected): h=1 mean −0.36 (5/12 dates positive);
h=3 −0.78 (5/10); h=5 −1.95 (2/8). Selected groups **underperformed** in this window; the
`leaders` bucket (sustained-strength) was the drag — classic short-horizon mean reversion of
extended leaders. `rs_new_high` and `accel` were the only buckets with positive cross-sectional
alpha, at tiny N.

## B) Stock-level forward returns (internal price chain)

Per-ticker date→Price series built from repeated appearances in picks.csv. 384/641 unique tickers
(60%) have a price observed ≥3 sessions after first selection. Return from first-pick Price to the
latest such observation: **mean +0.42%, median +0.24%, hit-rate 52.1%** (N=384).

**Severe survivorship bias:** a ticker is re-observed only while the system keeps picking its
group — tickers in groups that fell out of favor (likely the worst performers) drop out of the
sample entirely (257/641 have no follow-up). Treat these numbers as an upper bound.

**Stooq real-OHLC sub-analysis: skipped — unreachable.** The dated CSV endpoint returns HTTP 404;
the undated endpoint returns 200 with an anti-bot JavaScript challenge page (HTML, not CSV), on
stooq.com and stooq.pl, through the configured proxy. No real daily Low data → no gap-accurate
stop-loss / R-multiple simulation possible with local data.

## C) Focus-eligible vs non-Focus

Gate replicated from `display_methodology.json` v2 (effective 2026-07-01) + `docs/CLAUDE.md`:
`stage2` truthy AND `0 < atr_ext_50 ≤ 4.0` (ATR_EXT_ACTIONABLE) AND avg dollar volume
(Price × parsed Avg Volume) ≥ $30M (FOCUS_MIN_DOLLAR_VOL). Earnings proximity is a score
*penalty* in v2, not a hard gate, so it is not in the eligibility flag. 1,309/2,854 rows (45.9%)
eligible.

Stock-level forward return (part B sample) split by Focus flag at first pick:
- Focus-eligible: N=165, mean **−0.72%**, median 0.00%, hit 49.7%
- Non-eligible: N=219, mean **+1.28%**, median +0.30%, hit 53.9%

Focus filtering showed **no edge in this window — directionally worse**, though the ~2pp mean gap
is well within noise for N of this size and the survivorship bias applies unevenly (non-eligible
includes extended high-atr_ext names that kept running).

## D) Risk-field sanity

**Unit gotcha (documented, but the name is a footgun):** `risk_20ma_pct` and `risk_50ma_pct`
are stored as **fractions** despite the `_pct` suffix (median risk_20ma = 0.06 ⇒ 6% to the
20MA). This is intentional and documented in `scripts/picks_metrics.py` ("fraction; display
as % in PWA") and `scripts/picks_config.py`, and the PWA handles it correctly — but the
analyst writing this report initially misread it as a bug, which is itself evidence the
`_pct` naming misleads. Distributions at pick time (0% missing for both):

| Field | min | q25 | med | q75 | max | ≤0 share |
|---|---|---|---|---|---|---|
| risk_20ma_pct (frac) | −0.47 | 0.02 | 0.06 | 0.09 | 0.54 | 17.3% |
| atr_ext_50 | −4.50 | 0.91 | 2.57 | 3.92 | 11.17 | 15.5% |

Stop rule (entry = first-pick Price; stop distance = risk_20ma fraction if >0 else 1.5×ATR/Price;
median stop distance 7.2%, IQR 4.2–11.1%): using the internal price chain (pick-date closes only,
not daily lows), **10.0% of tickers with follow-up data (44/441) traded at/below the stop within
5 sessions**. This understates true stop-outs — intraday lows unobserved, and dropped tickers
never re-sampled.

## Statistical caveats

- Only **13 pick dates**, and forward windows overlap heavily — the effective number of
  independent observations is closer to ~8–12 date-level trials than to the row Ns shown. All
  picks share one market regime (a period when extended leaders mean-reverted).
- Per-date sign test on A (h=5): 2/8 positive days — suggestive of underperformance but a fair
  coin gives ≥6 tails 14% of the time; not conclusive.
- Bucket results (N=27–32 group-instances at 5d, clustered on ~8 dates) are anecdotal.
- Part B/C numbers carry survivorship bias in the *favorable* direction for the pipeline; the
  negative Focus result carries its own selection distortions.
- No real OHLC (stooq blocked) → no expectancy/R-multiple/win-loss stats.

## Verdict

At this sample size, **no evidence of positive alpha, and the point estimates are negative** —
selected groups underperformed both SPY and the industry median at every horizon, driven by the
`leaders` bucket. The only faint positives (`rs_new_high`, `accel` cross-sectional alpha) are
too small-N to act on. None of this is statistically conclusive; it is equally consistent with
"the selector buys strength and this 3-week window was a mean-reversion regime." Re-run after
60–100+ trading days spanning more than one regime; consider renaming `risk_*_pct` → `risk_*_frac`
(or documenting the units at every consumer) before anyone new builds stop logic on it.
