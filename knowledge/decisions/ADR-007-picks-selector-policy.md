# ADR-007: Picks pipeline — group selector policy

- **Status:** Accepted
- **Date:** 2026-06-25
- **Context plan:** `planning/stock-picks-from-leading-groups.md`
- **Related ADR:** ADR-008 (collection architecture)

## Context

The picks pipeline needs a daily policy for selecting which of the 144 Finviz industry
groups to screen for individual stocks. The selector is run daily by `collect_picks.py`
against `data/industries/deltas.csv` (the full historical archive of group-level metrics).

Because the input archive is append-only and immutable, the selector is the **cheapest
axis to change** in the entire pipeline: any policy revision can be re-run over all prior
days at any time. This replayability means we optimise for *correct first principles*
now and tune via attribution later, rather than over-engineering upfront.

The key risk is the opposite of the stock-filter axis: a bad selector is recoverable
(replay with a new policy); a stock-filter that's too narrow is **not recoverable** —
point-in-time Finviz technicals for names we didn't log are gone.

## Decision

### Four-bucket, priority-fill architecture (cap = 20 unique groups/day)

Groups are selected by priority until 20 unique groups are filled. A group that qualifies
in multiple buckets is **scraped once** but **tagged per bucket** in `picks.csv` so
per-methodology attribution is clean.

| Priority | Bucket | Gate | Slots | Rank-within |
|----------|--------|------|-------|-------------|
| 1 | `leaders` | (no hard gate — all groups eligible) | ≤ 10 | See below |
| 2 | `emerging` | `regime_short_long > 0.15` AND `rs_score > 0.5` | ≤ 4 | `regime_short_long` desc |
| 3 | `accel` | `momentum_accel > 0.08` AND top-40% by `momentum_score` AND `rs_score > 0.5` | ≤ 3 | `momentum_accel` desc |
| 4 | `rs_new_high` | `rs_new_high == 1` AND `rs_score ≥ 0.6` AND top-40% by `momentum_score` | ≤ 3 | `rs_slope` desc |

**Leaders ranking (VP-locked 2026-06-24/25):**
- Core 8 slots: rank all 144 groups by `sum(rank_month + rank_quarter + rank_half)` ascending
  (lowest sum = strongest sustained mid-timeframe leader). Take top 8.
- Freshness-fill 2 slots: from groups NOT in the core 8, rank by `momentum_confirmed` desc.
  Take top 2.
- Tag each row's `grp_rank_basis`: `"sustained_strength"` (core 8) / `"freshness_fill"` (2).

**Why sum-of-ranks, not a hard intersection gate:**
The PWA's "Sustained" tab uses a hard intersection gate (`rank_month ≤ N AND rank_quarter ≤ N
AND rank_half ≤ N`). We deliberately do NOT replicate that for the selector because:
(a) an intersection gate silently drops groups that are strong on 2 of 3 mid-timeframes but
marginally outside N on the third — sum-of-ranks degrades gracefully;
(b) the PWA gate's `effectiveN` is a UI parameter; the selector needs a reproducible,
config-free ranking;
(c) sum-of-ranks produces a continuous ordering that makes per-methodology attribution
cleaner (we can measure "did top-5 leaders beat bottom-5?").

**Why not `rs_confirmed` alone as the leaders metric:**
`rs_confirmed` (= `rs_score × rs_agreement`) measures RS *vs SPY* — it is an above-market
relative-strength signal, not an absolute-strength signal. In a broad bull run, it inflates
for all groups; in a correction it deflates even for groups that are strong *relative to
their peers*. We want the picks pipeline to surface stocks in groups that are genuine
rotational leaders regardless of market direction. `rs_confirmed` is retained as a floor
gate on the smaller buckets (emerging, accel, rs_new_high) where it IS the right signal.
It is also stored as a `grp_*` snapshot column for Phase-4 attribution to test head-to-head.

### Anti-flash floor (top-40% cross-sectional percentile by `momentum_score`)

The `accel` and `rs_new_high` buckets gate on a floor expressed as a **cross-sectional
percentile**, not an absolute threshold. Reason: `momentum_score` is computed from
`PERF_RANK_METRICS` in `delta_config.py` (currently 6 timeframes). If that config changes,
an absolute `≥ 0.5` floor silently means something different. A top-40% percentile ("today's
top 40% of groups by momentum") is invariant to formula rescaling.

Starting at top-40% (conservative); may loosen toward top-50% after 30+ days of data if
the buckets chronically yield too few qualifying groups. Threshold is `ANTIFLASH_PCTILE = 0.40`
in `collect_picks.py` (triple-documented per house rules).

**Caveat:** the floor gates on `rs_score > 0.5` and `rs_new_high` require `data/benchmark/
snapshots.csv` rows (SPY data). If the benchmark is missing for a date, these columns are
NaN and those buckets yield 0 groups — correct behavior, not a failure. `select_groups`
must handle 0-group buckets gracefully (fill from next priority; total stays ≤ 20).

### `selector_version` scheme and registry

Every pick row is stamped with a `selector_version` column. The version is a monotonic
string constant (`"v1"`, `"v2"`, …) defined in `collect_picks.py`. A committed append-only
registry (`data/picks/selector_versions.json`) records every version with: `version`,
`effective_date`, `description`, and a `params` block snapshotting every constant (slot
split, floors, percentile cutoff, ranking-metric name, cap).

**Bump rule:** any change to selection logic OR any `params` value ⇒ new version id +
prepended registry entry. Published entries are immutable; a test pins a hash of each
non-active entry so accidental edits to history fail CI.

**Important caveat (document in ADR and in code):** the registry captures *constants*,
not arbitrary code logic. A change to the ranking math in `select_groups()` without
bumping the version would make the stamp lie. The mitigation is the bump rule + code
review, not a technical lock. This obligation must be visible in comments near the
`SELECTOR_VERSION` constant.

Rationale for single-registry over per-version files: the same immutability guarantee,
fewer directory artifacts, and diff-friendly — mirrors the `docs/releases.json` pattern
already used in this repo.

## Alternatives considered

**rs_confirmed as the leaders primary sort:** Rejected — conflates absolute group
strength with RS-vs-SPY (see "Why not rs_confirmed alone" above).

**PWA intersection gate + sort by momentum_confirmed:** Rejected for the selector —
produces a different (smaller) group set than sum-of-ranks, doesn't degrade gracefully
when a strong group misses one of the three timeframe gates by a small margin. The PWA
gate is appropriate for a user-facing "Sustained" label; the selector needs a continuous
rank, not a binary pass/fail.

**All-green gate (perf > 0 on all mid timeframes):** Was tested in the spike.
Counts ranged 21–46/day (Jun 9–23). Rejected as a leaders *primary* gate — it is
a signal, not a selector (all-green doesn't distinguish a group at rank 5 from one
at rank 40). Used informally to cross-validate the spike's candidate lists.

**Jaccard-based stability metric for selector design:** Used during the Phase-1.5 spike
to pick the leaders metric. Stability scores: sustained_strength 0.691, momentum_weighted_mid
0.650, momentum_confirmed 0.605, rank_agreement 0.578. Sustained_strength chosen for
the core 8; momentum_confirmed chosen for freshness-fill because it is *more* responsive
(the point of the freshness slot is to catch fresh movers the stable core would miss).

**Per-version config files (one file per selector version):** Same immutability guarantee
as the single registry, but adds directory ceremony and a loader that must select the
active file. Rejected in favour of the append-only registry.
