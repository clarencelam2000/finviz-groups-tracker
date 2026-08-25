# scripts/ — data collection and processing

> Loads only when working in `scripts/`. Root `CLAUDE.md` covers the core collect →
> compute_deltas pipeline every session needs; this file holds detail specific to the
> Picks pipeline, AI capture, and Playwright dev workflows that don't need to load every time.

## Picks pipeline (`scripts/collect_picks.py`)

Daily Stage-2 stock-picks scraper: selects leading industry groups from
`data/industries/deltas.csv`, then scrapes the individual stocks inside them from the Finviz
screener and logs them to an append-only event log. **Phase 2 of
`planning/stock-picks-from-leading-groups.md`.** Required reading before editing:
**ADR-007** (selector policy) + **ADR-008** (collection architecture) in `knowledge/decisions/`.

> Like `collect.py`, the scrape MUST run on GitHub Actions (Azure IPs) — Cloudflare blocks the
> headless screener scrape from Google Cloud IPs. `select_groups` and all row-building/pagination
> helpers are **pure and fully unit-tested in cloud** (no Finviz access).

**Key scripts/config:**
| File | Role |
|------|------|
| `scripts/collect_picks.py` | `select_groups()` (pure selector) + paginated scrape + append. Inherits `slugify_industry`/`_build_url`/`_parse_table` from `probe_picks.py`. |
| `scripts/picks_config.py` | Single source of truth: schema (`picks_columns()`, 114 cols = 6 lead + 84 Finviz + 19 `grp_*` + 5 metrics) + all tunable constants. |
| `scripts/picks_metrics.py` | Pure helper module: parsers + `compute_metrics_row()` → 5 `METRICS_COLS` (`atr_ext_50`, `risk_20ma_pct`, `risk_50ma_pct`, `range_atr`, `stage2`). Fully unit-tested. |
| `data/picks/picks.csv` | Append-only log; 114 cols per row. Lead (incl. `collected_at`, the per-run UTC scrape timestamp) + 84 Finviz + 19 `grp_*` + 5 metrics. **Offline attribution only — never fetched by the PWA.** |
| `data/picks/picks_latest.csv` | Max-date slice of `picks.csv` — **this is what the PWA fetches.** |
| `data/picks/screener_config.json` | Modular URL config (`wide` net + `button`); 84-col `c=` list. Labels stay verbatim-synced to `tests/fixtures/probe_header_84col.txt`. |
| `data/picks/finviz_industry_slugs.csv` | 144 industry→slug rows. `validated` flips to `true` the first time a group scrapes >0 rows (G4). |
| `data/picks/selector_versions.json` | Append-only registry of every selector policy; newest-first. `current` must equal `SELECTOR_VERSION` and `versions[0].version` (test-enforced; published entries immutable). |
| `data/picks/display_methodology.json` | Append-only registry of the client-side (PWA) display/scoring constants active on any date — base filter, All-view sort, Focus DQ/scoring/weights, ATR display bands. Same versioning pattern as `selector_versions.json` (`current` + newest-first `versions[]`, lookup by largest `effective_date ≤ date`). Anti-drift guard: `tests/test_picks_methodology.py` (checks `versions[0].params` — the "current" entry only — against the live `docs/index.html` constants; older entries are frozen historical snapshots, not re-checked). **Bump whenever any of those constants changes, in the same PR** (see `planning/picks-methodology-tracking.md`) — no need to wait for a feature to be "locked" first; this file's job is to track live reality continuously. `v2` (current, effective 2026-07-01) added the Phase 3d Focus liquidity gate/penalty and earnings-proximity penalty on top of `v1`. The opt-in Phase 4 Ariel-match filter is intentionally **not** modeled in this file at all — it's versioned separately (see `ariel_match_config.json` below) since it's an optional additive layer, not part of the core All/Focus ranking. |
| `data/picks/ariel_match_config.json` | Documentation-only record of the Ariel Hernandez swing-trader match filter's `ARIEL_*` constants (group/liquidity/daily-move/growth gates). Same `current`/`versions[]` shape as the two files above, but **no anti-drift guard/test exists for it, by design** — it's an optional display layer with looser consistency requirements than the core methodology. Keep it updated as a courtesy when `ARIEL_*` constants change; nothing enforces it. |
| `scripts/evaluate_picks.py` | **PICKS-4 alpha scoreboard.** Rebuilds `data/picks/eval/group_scores.csv` from picks.csv + industry/benchmark snapshots (no scrape): forward group returns vs SPY, vs the cross-sectional industry median, and vs the mean of non-selected industries (the paired-test control), per bucket, at 1/3/5/10 forward trading sessions. Derived artifact — **fully rebuilt every run** (not append-only); unsettled rows (`n_sessions_avail < horizon`) self-correct. `--report` prints the roll-up + paired per-date test + `MIN_POWERED_DATES` (40) low-power caveat. Runs as a step in `collect.yml` after `compute_deltas.py` — deliberately NOT a third data-writer workflow. Spec: `planning/picks-alpha-evaluation.md`; baseline: `knowledge/investigations/picks-alpha-assessment-2026-07-14.md`. Tested in `tests/test_evaluate_picks.py`. |
| `scripts/replay_picks.py` | Deterministically reconstructs a historical Picks All/Focus view from `picks.csv` + `display_methodology.json`, for replay and A/B testing across methodology versions (`python scripts/replay_picks.py --date YYYY-MM-DD --view all\|focus [--methodology-version vN] [--pretty]`). Tested in `tests/test_replay_picks.py`. |

**`collected_at` (Phase 3e, 2026-07-03):** ISO 8601 UTC run timestamp, one value per run, stamped
identically on every row `main()` produces that day — mirrors `snapshots.csv`'s `collected_at` and
is **not** part of the picks uniqueness key (`date, list_category, ticker`); a same-day re-run just
carries the newer timestamp forward via `write_picks()`'s last-write-wins batch dedup. Rows scraped
before this column existed are backfilled once by `ensure_picks_csv()` with `date +
COLLECTED_AT_CRON_UTC` (`22:31:00` UTC, the `collect_picks.yml` cron fire time) — an approximation,
not a fabricated exact time, since the daily cron time is a known constant. The PWA's Picks tab
(`renderPicks()` in `docs/index.html`) surfaces this via the same `freshnessLabel()` helper already
used by Sectors/Industries, so a stale/blocked picks run shows the same red/amber/green badge.

**Selector (ADR-007, VP-locked; dedup policy amended v2 2026-07-02; widened v3 2026-08-24):**
five buckets filled in priority order to ≤ `DAILY_GROUP_CAP` (27) unique groups; a group
qualifying in multiple buckets is **scraped once but tagged per bucket** it naturally ranks in
(attribution preserved). Since v2, a group already selected by a higher-priority bucket no longer
eats one of a lower-priority bucket's N slots just by landing in that bucket's natural top-N —
emerging/accel/rs_new_high/all_green backfill past rank N with the next NEW candidate so each
bucket's N slots still yield N distinct groups when the qualifying pool is deep enough
(`add_bucket_with_backfill` in `collect_picks.py`). Leaders' own freshness-fill sub-bucket already
excluded the core by construction (unchanged). A 0-group bucket is normal (e.g. `momentum_accel`
is NaN until 11 sessions) — fill from the next priority, never error.
1. **leaders** ≤13 — 11 by sustained strength (`rank_month+rank_quarter+rank_half` asc; raised
   from 8 in v3) + 2 freshness fills (`momentum_confirmed` desc).
2. **emerging** ≤4 — `regime_short_long > 0.15` AND `rs_score > 0.5`.
3. **accel** ≤3 — `momentum_accel > 0.08` AND top-40% by `momentum_score` AND `rs_score > 0.5`.
4. **rs_new_high** ≤3 — `rs_new_high == 1` AND `rs_score ≥ 0.6` AND top-40% by `momentum_score`.
5. **all_green** ≤4 (v3, new; lowest priority — fills last) — `perf_week > 0` AND
   `perf_month > 0` AND `perf_quarter > 0` AND `perf_half > 0` AND `perf_ytd > 0` (raw group perf,
   not vs. SPY — a pure cross-timeframe consistency screen, no rs/strength floor of its own), sort
   `momentum_score` desc. **Needs snapshots.csv, not just deltas.csv**: `deltas.csv` carries no raw
   `perf_*` columns, only ranks/deltas, so `main()` merges `perf_week/month/quarter/half/ytd` from
   `snapshots.csv` onto the latest-date deltas slice before calling `select_groups()` — a caller
   that skips this merge gets 0 all_green groups (not an error, degrades like every other bucket's
   NaN handling). Being lowest priority is intentional: a group that also qualifies for a
   higher-conviction bucket is claimed there first, so all_green only ever picks up groups nothing
   else wanted.

The anti-flash floor (accel/rs_new_high only) is a **cross-sectional `momentum_score` percentile**
(`ANTIFLASH_PCTILE = 0.40`), not an absolute cutoff — invariant to `PERF_RANK_METRICS` rescaling.
all_green has no anti-flash floor of its own — its 5-timeframe-positive gate already screens for
consistency directly.

> **Known gap (v3):** `DAILY_GROUP_CAP` (27) x `PAGE_CAP` (2) = 54, which is 4 pages over
> `GLOBAL_FETCH_CAP` (50) — a fully-packed day (every bucket fills to its cap) already exceeds the
> page budget, not merely matches it. Owner decision 2026-08-24: raise `DAILY_GROUP_CAP` to fit the
> new all_green bucket, but keep `GLOBAL_FETCH_CAP` at 50. On such a day the lowest-priority bucket
> reached can be silently cut
> short by the page cap even though its own slot cap wasn't hit.

**`grp_*` columns (19):** each pick row snapshots the selecting group's `deltas.csv` metrics at
selection time (so Phase-4 attribution never re-derives them). Includes `grp_rank_basis`,
`grp_category_rank` (within-bucket rank among qualifying candidates, independent per category for
dedup groups), `grp_momentum_score_pctile` (the floor value actually used), and stored
rejected-alternatives (`grp_rs_confirmed`, `grp_momentum_weighted_mid`, `grp_rank_agreement`) for
head-to-head Phase-4 comparison. Renaming/removing one is one-way once data flows; **adding** one is
a two-way-door superset migration (`ensure_deltas_csv()` pattern).

**Workflow & guards:**
- `.github/workflows/collect_picks.yml` — separate workflow, `workflow_dispatch`-only (PICKS-2-CRON,
  2026-07-19): fired by the Cloudflare `finviz-cron-dispatcher` at `31 22 * * 2-6` UTC (6:31 PM EDT,
  90 min after the EOD `collect.yml` dispatch so deltas are pushed first). **No GitHub `schedule:`
  backstop by design** — this scrape costs up to 50 pages and a drift-early fire loses the day's
  list to the stale-read guard; the alert path is the healthchecks.io dead-man's-switch pinged on
  success (`PICKS_HEALTHCHECK_URL` secret; skipped silently if unset).
- **Shared concurrency guard (G1):** both `collect_picks.yml` AND `collect.yml` declare
  `concurrency: { group: finviz-data-commit, cancel-in-progress: false }` — a group only serializes
  workflows sharing the name, so **both files must have it.** Rebase-before-push.
- **Stale-read guard:** `collect_picks.py` asserts `deltas['date'].max() == trading_date()` before
  scraping — a too-early run is a safe no-op, never a wrong-day scrape.
- **Fetch caps:** per-group `PAGE_CAP = 2` (40 names; lowered from 15 on 2026-07-02 — historical
  data showed only Biotechnology, a structurally oversized industry at ~100 names/day, ever
  exceeded 40; the screener sorts `-marketcap` desc so the cap keeps the biggest/most-liquid names)
  and **hard global `GLOBAL_FETCH_CAP = 50` pages/day** (VP-set 2026-06-25). Scrapes in priority
  order (leaders first) and stops at 50. A wrong slug returns HTTP 200 with an empty table (NOT a
  404) — the scraper checks row count, not status.
- **Empty-scrape guard (D14):** if **no** selected group returns a single row (the signature of a
  Cloudflare block — every page is HTTP 200 with an empty table, no exception), `collect_picks.py`
  **aborts with `exit(1)` BEFORE writing** instead of letting `write_picks` evict the date and
  silently wipe an earlier same-day capture. The daily list is irreplaceable (no backfill), so a
  blocked run must be a loud no-op: CI goes red and `collect_picks.yml`'s `if:failure()` step
  uploads the debug HTML. Last-write-wins per date still applies to *non-empty* re-runs (the EOD
  run's picks win over an earlier intraday run's).
- **Ticker-corruption guard (2026-07-15 incident):** Finviz's screener Ticker `<td>` can carry
  extra decorative markup ahead of the real `<a>` ticker link (observed: a single-letter
  avatar/logo placeholder) — `probe_picks._parse_table()` reads the Ticker column from the
  cell's anchor text specifically (not `cell.get_text()` on the whole `<td>`) to avoid
  swallowing it, which was silently turning `HSBC` into `HHSBC`, `C` into `CC`, etc. across
  every scraped row. As defense-in-depth against a *different* future markup change with the
  same symptom, `collect_picks.py` also runs `ticker_dup_rate()` against `TICKER_DUP_RATE_MAX
  = 0.25` right before `write_picks()` and aborts (loud, no write) if too many tickers in a run
  show a duplicated leading character — real baseline is ~1-4% (AA, EE, MMM, ...), so 25% only
  trips on genuine corruption. Full RCA:
  `knowledge/investigations/picks-ticker-duplication-2026-07-15.md`. A follow-on 2026-07-16
  corruption (issue #252) exposed a blind spot: the real bug was `_parse_table()`'s Ticker
  branch reading `tag.find("a")` (first anchor), but Finviz's Ticker cell has a decorative
  avatar placeholder that is *itself* an `<a>` and comes first, so it silently returned the
  avatar's single-letter text (`"HSBC"` -> `"H"`) — and `ticker_dup_rate()` is blind to this
  class since a 1-char ticker has no duplicated pair. Fixed by `_extract_ticker()` (preferring
  the quote link's `t=` query param) plus a complementary guard, `single_char_ticker_rate()`
  against `TICKER_SHORT_RATE_MAX = 0.30`, run alongside `ticker_dup_rate()` right before
  `write_picks()`. Real baseline for single-char tickers is ~1.3-1.4%, so 30% only trips on
  genuine corruption.
- **Header-drift guard (PICKS-2-HDR, 2026-07-19):** `build_pick_rows` maps scraped cells by the
  config's 84 header labels — a Finviz label rename would write the affected columns **blank
  silently**. `missing_header_labels()` (union across all scraped group headers) +
  `header_check_action()` apply a tiered policy: `Ticker` missing or > `HEADER_MISSING_ABORT_FRAC`
  (0.10, ≈8 labels) missing → **abort before write** (parse untrustworthy); any smaller drift →
  **write the partial capture, then exit 1 after the write** — bounded column loss beats losing the
  whole irreplaceable day, but CI still goes red, the debug HTML uploads, and the healthcheck ping
  is skipped so the drift is fixed in `screener_config.json` before the next run.

## WS3 morning status (`collect_morning.py` / `pick_status.py`)

**ADR-013**, required reading before touching either file. First writer under the
provisional-session pattern (`scripts/session_config.py`, ADR-011 Option C) — tags each
prior-session pick with a morning status (Triggered / Setting-up / Gapped-through /
Failed-breakout / Invalidated / No-quote) at ~10:05 ET.

- **`scripts/pick_status.py`** — pure status engine, no I/O, no clock/file reads.
  `compute_pick_status(trigger, stop, price, open_, high, low, ref=None)` evaluates ADR-013
  Decision 3's precedence table top-down, first match wins (order matters — see the in-code doc
  comment for the invalidated-outranks-triggered / gapped-outranks-triggered rationale).
  Session-agnostic by contract: WS3b (#268, 15:30 ET) calls it verbatim against a different
  quote snapshot. `compute_atr_from_lod()` is the entry-quality metric, meaningful only for
  `ACTIONABLE_STATUSES` (`triggered`, `gapped_through`, `reclaim`) — display thresholds are a
  PWA concern, not this module's. **P2 (WS5 §8b watchlist build brief) added the `reclaim`
  state and `compute_reclaim(price, today_low, prior_low, ref)`** — the mirror of
  `failed_breakout` (dips below a level, then recovers, instead of poking above one and
  falling back). Sits between `failed_breakout` and `setting_up` in precedence; only ever
  evaluated when a caller passes `ref` — picks callers never do, so `ref=None` keeps
  `compute_pick_status` byte-identical to pre-P2 behavior for every existing caller.
- **`scripts/collect_morning.py`** — the writer. `fetch_ticker_quotes(page, tickers, config)` is
  the **shared component** WS3b and WS5's held-tickers feed reuse: batches tickers into
  `MORNING_BATCH_SIZE`-sized (50) chunks against the `morning` block in `screener_config.json`
  (a narrow 9-column `t=`-filtered screener URL, distinct from `wide`'s 84-column filter-based
  URL — see `build_ticker_url` vs `probe_picks._build_url`), and paginates each batch with `&r=`
  exactly like `probe_picks._scrape_group`. `load_pick_levels` / `build_status_rows` are pure and
  fully unit-tested in cloud; `fetch_ticker_quotes` itself is only exercised via fixtures (Phase
  A) since Cloudflare blocks it from a cloud dev session — live wiring is Phase B.
  - **Scrape-universe narrowing (issue #293):** `main()` does NOT scrape all of
    `picks_latest.csv` (75–375 tickers/day — too large to scrape or act on). It reconstructs
    the Focus view server-side via `replay_picks.replay(picks_max_date, "focus")` and scrapes
    only `select_focus_universe()`'s output: the top `MORNING_FOCUS_TOP_N` (100) tickers by
    `focus_score`, keeping only those `>= MORNING_FOCUS_SCORE_FLOOR` (0.3). The floor lets thin
    days self-trim (sample: min 22 / median 95 / max 100 names/day) instead of padding down to
    low-conviction setups. The Focus set is a subset of `picks_latest`'s tickers by construction,
    so trigger/stop/atr still come from `picks_latest`; `pick_levels` is reordered best-first so a
    partial scrape keeps the strongest names. A `replay` failure is a **loud `exit(1)`** — never a
    silent fall-back to the full list. Both constants are 3-places documented (in-code + README §
    Configurable parameters + here). Note `MORNING_BATCH_SIZE` stays **50, deliberately off a
    multiple of `PAGE_SIZE`=20**: a multiple-of-20 batch (40/60) ends on a full page and forces a
    wasted empty-probe goto, so 50 is *more* request-efficient (batch 50 = 6 gotos/~100 tickers vs
    batch 60 = 7). `fetch_ticker_quotes` wraps `wait_for_selector` in try/except (mirroring
    `probe_picks`) so an out-of-range empty page can't crash the run and drop later batches.
  - **Store:** `data/picks/sessions/morning.csv` (append-only, keyed `(date, ticker)`,
    last-write-wins, `collected_at` not part of the key — same convention as `picks.csv`) +
    `data/picks/sessions/morning_latest.csv` (max-date slice, the PWA fetch target). Committed
    to the repo, not gitignored — see ADR-013 Decision 4 for why (public data, static-Pages PWA).
  - **Write-boundary guard:** `write_store()` calls `session_config.assert_provisional("morning")`
    before writing anything — the first real enforcement of the ADR-011 invariant.
  - **Non-trading-day guard differs from `collect.py`:** `main()` imports `NYSE_HOLIDAYS` /
    `_is_trading_day` from `collect.py` but deliberately does **not** import `trading_date()`'s
    rollback logic — a weekend/holiday morning run exits 0 without writing (no live session to
    snapshot), it never re-stamps the prior day's data under today.
  - **Stale-input guard:** `picks_latest.csv`'s max date must be strictly before today's ET date
    and no more than `MAX_STALE_SESSIONS` (5) trading sessions old, else `sys.exit(1)` loud,
    no write.
  - **`--dry-run`:** scrapes + parses + prints row counts, skips `write_store()`. This is Phase
    B's `collect_morning.yml` first-slice hook (`workflow_dispatch` dry run before cron enable).
  - **P2 watchlist union (WS5 §8b build brief §3/§4c/§4d/§5):** after the Focus universe is
    built and before the scrape, `main()` reads `POSITIONS_WORKER_URL`/`POSITIONS_INGEST_TOKEN`
    (same env vars as `collect_held.py`) — if BOTH are set, it calls
    `fetch_watchlist_tickers()` (GET `/watchlist-tickers` on the `finviz-positions` Worker),
    maps the response through `build_watch_levels()` into `pick_levels`-shaped dicts (`ref` =
    the ticker's `sma50` — the SYSTEM-read reclaim level, always the 50-day MA regardless of
    the watch entry's own `level_type`; the user's `reclaim_20ma`/`reclaim_50ma` overlay is a
    separate client-side P3 read), and unions them into the scrape universe via
    `union_watch_levels()` (pure; de-dupes on ticker, Focus pick's level dict wins on a
    collision). If either env var is unset, the watchlist union is skipped entirely with an
    informational print — the morning job never hard-requires watchlist config. The single
    existing scrape covers both picks and watch tickers; `build_status_rows` threads
    `ref=lvl.get("ref")` into `compute_pick_status`, so Focus levels (no `ref` key) never
    reclaim and watch levels do. `fetch_watchlist_tickers`/`post_watchlist_tick` are both
    IMPURE and NON-FATAL by design (unlike `collect_held.py`'s loud-exit fetch): any fetch/POST
    failure prints a stderr warning and returns `[]`/`None` rather than exiting, since a
    watchlist/worker hiccup must never drop the picks-only morning run. After a successful,
    non-empty `write_store()` (never on `--dry-run`), and only when `should_tick_watchlist(session)`
    says the active session is in `session_config.WATCHLIST_TICK_SESSIONS` (currently `morning`
    only — WS3b, issue #268), `main()` calls `post_watchlist_tick(worker_url, token, today_str)`
    to decrement each watch entry's TTL for the day — also non-fatal (idempotent, self-heals on a
    later run). This gate exists because `collect_morning.py` was generalized (WS3b) to also serve
    the `pre_close` session (see the module docstring); without it, a `pre_close` run would tick
    the same day's TTL a second time. The non-trading-day exit guards run before any of this, so a
    closed-market day never ticks. `_authed_request` is
    replicated verbatim from `collect_held.py` in this module rather than imported —
    `collect_held.py` imports FROM `collect_morning.py` (`CONFIG_PATH`, `_to_float`,
    `fetch_ticker_quotes`), so importing back would create a cycle.

## WS5 held-tickers feed (`collect_held.py`)

**WS5 phase 2** (`planning/trade-lifecycle-engine.md` §5/§5a/§10/§11, ADR-012; issues #312,
#297). Settled-EOD quote feed for the **held** set — the union of open/managing/closing
`positions` — as distinct from WS3's morning picks/watch feed above (different membership,
different store, see §5a "Two separate feeds"). Required reading before touching this file:
the planning doc sections cited above, plus ADR-012 §10 Phasing / §11 Decisions resolved
("Ticker-quote store = D1, append-only").

- **Reuses `collect_morning.py`'s scrape mechanism verbatim** — `fetch_ticker_quotes(page,
  tickers, config, block="held")` and `build_ticker_url(config, tickers, offset, block="held")`
  are the exact same shared functions WS3 calls with `block="morning"`; this script imports
  them rather than reimplementing scraping. `held` is a distinct block in
  `data/picks/screener_config.json` — the full 84-column scrape (empty `base_filters`,
  `t=`-filtered), not WS3's narrow 9-column block.
- **D1-write-not-git-commit, the defining difference from every other collector in this repo.**
  `collect_held.py` never touches the working tree — it POSTs to the `finviz-positions`
  Worker's authenticated `/ingest/quotes` endpoint (Bearer auth), which writes to D1's
  `ticker_quotes` table (append-only, one row per `(ticker, trade_date)` — see planning doc §5).
  There is no `write_store()` / `MORNING_STORE` analog here and nothing for `write_store()`'s
  `session_config.assert_provisional` guard to apply to. `collect_held.yml` correspondingly has
  no `git commit`/`git push` step and no `finviz-data-commit` concurrency group.
- **Two required env vars** (GitHub Actions secrets, set out of band — not touched by
  `wrangler deploy`): `POSITIONS_WORKER_URL` (base URL of the `finviz-positions` Worker) and
  `POSITIONS_INGEST_TOKEN` (Bearer token for both `GET /held-tickers` and
  `POST /ingest/quotes`). Either missing → `sys.exit(1)` loud (misconfiguration, never a silent
  no-op). 3-places documented: in-code module docstring + README § Configurable parameters +
  here.
- **Held-set source:** `GET {POSITIONS_WORKER_URL}/held-tickers` → `{"tickers": [...]}`, the
  live union of open/managing/closing positions from the Worker's own D1 `positions` table —
  never derived from `picks_latest.csv` or any repo file (§5a: "held feed never depends on the
  picks list"). An empty held set is a normal, expected `sys.exit(0)` ("nothing to fetch"), not
  an error — most days early in WS5's life will have zero open positions.
- **`build_quote_payload(quotes, trade_date, collected_at)`** is the pure, unit-tested core
  (`tests/test_collect_held.py`) — maps each scraped Finviz row to the ingest payload's typed
  fields (`prev_close`, `open`, `high`, `low`, `close`, `change_pct`, `atr`, `volume`, all via
  `collect_morning._to_float`) **plus a `raw` key carrying the entire original 84-column row
  dict verbatim** (#297 — no scraped column is ever dropped, even though only a handful feed
  typed fields today). `days_to_earnings` is left `None` in phase 2; phase 3 derives it from
  `raw["Earnings"]`.
- **Empty-scrape guard:** if the held set was non-empty but the scrape returns 0 rows (the
  Cloudflare-block signature — every page 200s with an empty table), the script refuses to POST
  and exits 1 loud, mirroring `collect_picks.py`'s empty-scrape guard in spirit (simpler here —
  there's no local file whose prior-run data could be silently evicted).
- **Non-trading-day guard** reuses `NYSE_HOLIDAYS`/`_is_trading_day` from `collect.py`, same
  as `collect_morning.py` — settled EOD feed, so a closed day exits 0 with no rollback (unlike
  `collect.py`'s `trading_date()`).
- **Scheduler:** the Cloudflare `finviz-cron-dispatcher`'s `held` job (`worker-cron/src/routing.js`
  `JOB_SCHEDULE`), 17:30 ET Mon–Fri, ungated (same shape as `collect_morning` — the held set
  comes from a live Worker query, nothing to dependency-gate on). Dispatches
  `.github/workflows/collect_held.yml`. See root `CLAUDE.md` § Automation.
- **`--dry-run`:** scrapes + maps + prints row counts, skips the POST.
- **`--advisory` (WS5-8):** runs the same scrape as a 15:40 ET pre-close advisory read instead
  of the 17:30 ET settled feed. Same held-set fetch, same scrape, same `build_quote_payload`,
  but `post_quotes()` targets `POST /positions/preclose-advisory` (via an optional `path=` arg,
  default `/ingest/quotes`) instead of `/ingest/quotes`, and `main()` skips `trigger_advance()`
  entirely — `--advisory` implies no `/advance` call, since the advisory endpoint computes its
  own read and there is nothing to sweep. The advisory endpoint writes NOTHING to D1's
  `positions`/`ticker_quotes` tables (the entire point — a provisional bar must never land in
  the same store the 17:30 settled sweep reads, or it would corrupt that sweep). Scheduler: the
  `held_preclose` job (`worker-cron/src/routing.js` `JOB_SCHEDULE`), 15:40 ET Mon–Fri, ungated,
  dispatching `.github/workflows/collect_held_preclose.yml`. See root `CLAUDE.md` § Automation.

## AI capture constants (`scripts/generate_ai.py`)

> Added in Phase 1 of the AI capture plan (ADR-006). Document changes to these in all three
> places per the configurable-constants rule in root `CLAUDE.md` § Code quality standards.

| Constant | Default | Controls |
|----------|---------|---------|
| `CAPTURE_DIR` | `data/ai/debug/` | Where Tier-2 debug captures are written (one file per date, committed, rolling window) |
| `PROVENANCE_DIR` | `data/ai/provenance/` | Where Tier-1 provenance files are written (one per date, committed permanently, user-facing) |
| `CAPTURE_RETENTION_DAYS` | `30` | Number of Tier-2 debug files kept in HEAD; older files are pruned from HEAD on each run but stay recoverable in git history. ~1 MB total at 30 days. |
| `AI_CAPTURE` env / `--capture` flag | off (on in CI) | Controls whether Tier-2 debug file is written. Set `AI_CAPTURE=1` or pass `--capture` to enable locally. Always enabled in `generate_ai.yml`. |
| `GOOGLE_API_KEY` | (set in env) | Vertex express key — sidesteps ADC and AI Studio 429s. Takes priority over Vertex ADC (`GOOGLE_CLOUD_PROJECT`) when `GOOGLE_GENAI_USE_VERTEXAI=true`. Sets `_backend="vertex_express"`. |

**Auth priority:** `GOOGLE_API_KEY` (Vertex express) > `GOOGLE_CLOUD_PROJECT` (Vertex ADC) > `GEMINI_API_KEY` (AI Studio).

**Preview mode (no creds needed):**
```bash
python scripts/generate_ai.py --preview [--task pulse] [--group sector] [--json]
```
Builds prompts from existing CSVs and writes Tier-1 provenance — no API call, no credentials required. Add `--date YYYY-MM-DD` to use a specific date (defaults to latest snapshot date).

## Playwright scraping dev workflow

We can write, iterate, and debug `collect.py` scraping logic (selectors, parsing, retry
behavior) against non-Cloudflare URLs without needing a local machine or burning GitHub
Actions runs. Only the final Finviz target requires GitHub Actions due to Cloudflare. Before
running Playwright in a Claude Code cloud session, read
`knowledge/investigations/playwright-cloud-session-testing.md` for cloud-specific gotchas.

Do **not** add `playwright install chromium` to the default setup (`requirements.txt`). It's
175MB and only needed for testing/dev tasks. Install it in-session when the task calls for it:
```bash
pip install playwright
python3 -m playwright install chromium --with-deps
```
There is no need for a conditional or auto-detection — just run it when you need it.
