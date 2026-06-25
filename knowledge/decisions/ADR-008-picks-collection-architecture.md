# ADR-008: Picks pipeline — collection architecture

- **Status:** Accepted
- **Date:** 2026-06-25
- **Context plan:** `planning/stock-picks-from-leading-groups.md`
- **Related ADR:** ADR-007 (selector policy)

## Context

The picks pipeline scrapes individual stocks from the Finviz screener for each selected
leading group, appends results to an event log, and surfaces them in the PWA. This ADR
covers the structural decisions around the scrape job, data storage, column breadth,
fetch volume, and the PWA fetch pattern. Selector policy decisions are in ADR-007.

## Decisions

### D7 — Separate GitHub Actions workflow (`collect_picks.yml`)

`collect_picks.py` runs in its own workflow, independent from `collect.py`. Rationale:
(a) failure isolation — a screener-side issue doesn't take down the group snapshot job;
(b) independent cron control — the picks job triggers *after* the groups job (needs
today's `deltas.csv` to select groups); (c) separate retry budget.

**Shared concurrency guard (mandatory):** Both `collect_picks.yml` and `collect.yml`
must declare `concurrency: { group: finviz-data-commit, cancel-in-progress: false }`.
A concurrency group only serializes workflows that declare the **same group name** — so
adding it to the new file alone gives no protection. `cancel-in-progress: false` ensures
neither data job is killed mid-run. This requires editing the existing `collect.yml`.

**Stale-read guard:** `collect_picks.py` asserts `deltas['date'].max() == trading_date()`
before scraping — aborts if today's deltas aren't present, so cron drift can't cause picks
to be selected against yesterday's group rankings.

**Rebase-before-push:** `git pull --rebase` before every commit, same pattern as `collect.py`.

### D5 — Store all 84 columns (`v=151` custom view, explicit `c=` list)

The `v=151` screener URL with the VP-supplied `c=` list returns ~84 columns of fundamental,
technical, and performance data per stock. We store all 84 — maximally future-proofing
attribution (we don't know today which columns will matter).

**Pin the explicit `c=` list in `screener_config.json`, never rely on a bare saved view.**
Saved-view membership is account/cookie-bound and can drift; the explicit `c=` is
request-scoped and stable regardless of VP account state.

The 84-col header is committed as a golden fixture (`tests/fixtures/probe_header_84col.txt`).
A test asserts future scrape headers match it (drift tripwire). Column *removal or reorder*
fails the test; a pure *append* is allowed and triggers the header-migration path.

**Filter vs column breadth are orthogonal axes (important distinction):**
- *Column breadth* (`c=` list): how many attributes are stored per passing stock. We store
  84 regardless of filter decisions.
- *Filter width* (`f=` tokens): how many stocks pass at all. This is the survivorship axis.
Only names that pass the filter ever enter the log — names below the filter are gone
permanently. See D11 on the stored-net decision.

### D11 — Store wide, tag Stage-2 in-house (temporary, bounded)

The stored filter is **wide** (relaxed trend gates) so we capture names that are pre-Stage-2
or in a mild pullback. Stage-2 qualification is recomputed as an in-house boolean from the
stored SMA/price columns. The VP accepted this *cautiously* as a **non-long-term solution**.

**Current wide-net filters (`screener_config.json` `base_filters`):**
- `cap_midover` — mid-cap+; excludes micro/nano-caps
- `sh_avgvol_o100` — avg volume > 100K; liquidity floor (also reduces page count)
- `ta_highlow52w_a20h` — **more than 20% ABOVE the 52-week LOW** (bottom-of-barrel
  exclusion; screens out deeply beaten-down names). Note: this is NOT "within 20% of the
  52-week high" — the direction is from the low, not down from the high.

Removed (2026-06-24, VP): `ta_sma200_sb50` (50SMA > 200SMA), `ta_sma50_pa` (price >
50SMA) — these SMA trend gates caused survivorship by excluding names in a correction
that may re-emerge. Recomputed in-house from stored `SMA50`/`Price` columns.

**Fetch cap (VP-set 2026-06-25): `GLOBAL_FETCH_CAP = 50` screener pages/day.** The job
scrapes in priority order (leaders first) and stops at 50 pages regardless of how many
groups qualified. This bounds volume by VP decision rather than a probe measurement.
Revisit after live data shows real daily page demand. This is a configurable constant
(triple-documented per house rules: in-code, README, CLAUDE.md).

**Survivorship note:** only names *already* passing the wide-net filter ever enter the log.
Names below the floor on any given day are permanently absent from that day's record.
This is the "irreplaceable axis" — the group selector is replayable from `deltas.csv`;
per-stock point-in-time technicals are not. The store-wide decision was made specifically
to minimise survivorship on the stock axis.

**Phase-4 sunset obligation:** once attribution identifies which stored signals predict
winners, narrow the filter back toward a tight Stage-2 net. This is a tracked commitment
(`.session/SPRINT.md` backlog item), not an aspiration.

### D9 — Membership-only, append-only event log; derive positions offline

`picks.csv` is pure append-only. One row per `(date, list_category, ticker)`. Nothing
stateful is maintained between runs — no "current positions" file, no hand-maintained
entry/exit state. Phase-4 `eval_picks.py` derives positions by reconstructing continuous
runs from the log: `entry` = first date in a continuous streak; `exit` = first gap.

Rationale: hand-maintained state is fragile (bugs, partial runs, re-runs). An event log
is always reconstructible, auditable, and diff-friendly in git.

**`picks.csv` uniqueness key: `(date, list_category, ticker)`.** A stock can appear in
multiple categories on the same day (e.g. both `leaders` and `accel`) — both rows are
kept for clean per-category attribution. Last-write-wins per that key on re-runs (mirrors
`collect.py` dedup discipline).

### `picks_latest.csv` — PWA fetch isolation

The full `picks.csv` log grows multi-MB within weeks (20 groups × ~40 names × 84 cols ×
trading days). The PWA must never fetch the full log. `collect_picks.py` writes a second
file `picks_latest.csv` containing only the max-date slice. The PWA fetches only this file
from `raw.githubusercontent.com`.

`picks_latest.csv` is written atomically in the same commit as the `picks.csv` append —
never committed separately. A test asserts it equals the max-date slice of `picks.csv`.

### `grp_*` columns — snapshot group metrics at selection time

Every stock row in `picks.csv` carries a fixed set of `grp_*` columns snapshotting the
selecting group's metrics from `deltas.csv` at the moment of selection. This enables
Phase-4 attribution without re-joining to `deltas.csv` (which is replayable but couples
attribution to selector internals that may have changed).

**One-way/two-way door analysis:**
- *Adding `grp_*` columns later:* two-way door — superset migration adds new columns with
  blank backfill for old rows (same `ensure_deltas_csv()` pattern).
- *Renaming or removing existing columns:* effectively one-way — historical rows have the
  old name; attribution queries referencing it break or silently get blanks. Column names
  chosen now are sticky once data flows.
- *Column semantics changing:* acceptable if the value truly changes (e.g. `grp_momentum_score_pctile`
  will reflect the actual percentile used on each day — it's not locked to 0.40). Document
  any semantic shift with a `selector_version` bump.

**Exact column spec (all written per row regardless of bucket) — 19 columns:**

> Note: this table was reconciled on 2026-06-25 to match the implemented plan spec
> (`planning/stock-picks-from-leading-groups.md §grp_* spec`). The initial ADR draft
> listed `grp_selection_priority` (global fill-order int 1–20) and 15 other columns.
> The final plan replaced that with `grp_category_rank` (within-bucket rank among all
> qualifying candidates, independently computed per category for dedup groups), and added
> three rejected-alternative columns for Phase-4 head-to-head comparison. `grp_category_rank`
> is more useful for per-category attribution; `grp_selection_priority` cannot be recovered
> from `deltas.csv` either — but the plan spec was the canonical just-merged design.

| Column | Source | Notes |
|--------|--------|-------|
| `grp_rank_basis` | computed | `"sustained_strength"` / `"freshness_fill"` for leaders rows; bucket name for the other buckets |
| `grp_category_rank` | computed | Integer: within-bucket rank among all qualifying candidates for that bucket, sorted by the bucket's rank-within criterion. Rank 1 = strongest qualifying candidate in that bucket that day. For dedup groups appearing in multiple buckets, each category row independently carries the counterfactual within-bucket rank. Cannot be reconstructed later. |
| `grp_sum_mid_rank` | `rank_month + rank_quarter + rank_half` | Leaders sustained_strength ranking value |
| `grp_rank_month` | `rank_month` | Transparency / re-derive sum |
| `grp_rank_quarter` | `rank_quarter` | Transparency / re-derive sum |
| `grp_rank_half` | `rank_half` | Transparency / re-derive sum |
| `grp_momentum_confirmed` | `momentum_confirmed` | Freshness-fill basis; strength × agreement |
| `grp_momentum_score` | `momentum_score` | Floor input |
| `grp_momentum_score_pctile` | computed cross-sectionally | Actual percentile used for the anti-flash floor; invariant to formula rescaling |
| `grp_momentum_accel` | `momentum_accel` | `accel` bucket basis; NaN until 11 sessions of history |
| `grp_momentum_weighted_mid` | `momentum_weighted_mid` | Spike runner-up (Jaccard 0.650 vs sustained_strength 0.691); stored for Phase-4 head-to-head |
| `grp_rank_agreement` | `rank_agreement` | Cross-timeframe rank sign agreement; tested in spike (Jaccard 0.578, rejected as primary); stored for Phase-4 head-to-head |
| `grp_regime_short_long` | `regime_short_long` | `emerging` bucket basis |
| `grp_rs_score` | `rs_score` | Floor input for emerging / accel / rs_new_high |
| `grp_rs_agreement` | `rs_agreement` | RS directional consistency across mo/qtr/half; needed to re-derive `rs_confirmed` |
| `grp_rs_confirmed` | `rs_confirmed` | rs_score × rs_agreement; **explicitly rejected as the leaders metric** (see ADR-007) but stored for Phase-4 head-to-head comparison |
| `grp_rs_accel` | `rs_accel` | RS-score acceleration; RS-domain analog of `grp_momentum_accel` |
| `grp_rs_new_high` | `rs_new_high` | `rs_new_high` bucket basis |
| `grp_rs_slope` | `rs_slope` | `rs_new_high` rank-within basis; LS slope of `rs_month` over trailing window |

Three columns (`grp_rs_confirmed`, `grp_momentum_weighted_mid`, `grp_rank_agreement`) are
stored even though they are not used as selector gates — specifically so Phase-4 can answer
"would an alternative selector have produced different stocks?" without re-deriving from `deltas.csv`.

## Alternatives considered

**Single combined workflow (picks inside `collect.yml`):** Rejected — couples failure
domains. A Finviz screener block shouldn't prevent group snapshot commits.

**Sidecar file for `grp_*` columns (separate `picks_groups.csv`):** Rejected — requires
a join on every attribution query; inline columns are self-contained and simpler. The
column count (~15 `grp_*` + 84 stock cols = ~99) is manageable.

**Tight Stage-2 filter in the stored net:** Rejected for now (D11 / ADR context) —
survivorship was the dominant concern. Revisit at Phase-4 attribution.

**Per-day `picks_YYYY-MM-DD.csv` files instead of single append-only log:** Rejected —
fragmented attribution, no standard dedup discipline, git history harder to audit.
`picks_latest.csv` gives the PWA a small daily file without fragmenting the archive.

**LFS / yearly partition for `picks.csv`:** Deferred. PWA is insulated via
`picks_latest.csv`. Revisit at ~6 months when file size becomes a checkout concern.
