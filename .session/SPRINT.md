# Sprint: Pre-Data Improvements
**Branch:** `claude/explore-plan-next-steps-3jlhmh`  
**Goal:** Build robustness, tests, and dashboard features while waiting for data to accumulate (7d deltas arrive ~2026-06-16; full 30d picture ~2026-07-09)

---

## Board

### 🔴 Backlog

#### Data Pipeline

| # | Task | File(s) | Effort | Notes |
|---|------|---------|--------|-------|
| CHORE-1 | **Remove stale `Infrastructure Operations` references** | `data/finviz_sector_industry_map.json`, `data/finviz_sector_industry_map.csv`, `tests/test_seed_taxonomy.py`, `CLAUDE.md` | XS | Finviz no longer carries `Infrastructure Operations`. The picks pipeline slug map (built from `snapshots.csv`) is already clean (144 rows, excludes it). These four taxonomy/seed files still reference it. Clean up in a standalone PR — scoped separately from Phase 2 to avoid touching seed_taxonomy validation during an unrelated implementation sprint. |
| PIPE-1 | **Backfill historical deltas.csv after day-removal formula change** | `data/sectors/deltas.csv`, `data/industries/deltas.csv`, `scripts/compute_deltas.py` | S | `momentum_score` and `rs_score` rows before PR #150 were computed with 7 timeframes (including day); rows after use 6. The `momentum_accel` and `rs_accel` deltas will straddle the discontinuity for ~10 sessions after merge. Fix: run `compute_deltas.py` over all historical dates to recompute from scratch. Do this in a separate PR (don't bundle with the formula change) to keep diffs legible. |
| ~~TAX-0~~ | ~~**Seed sector→industry taxonomy map**~~ | `scripts/seed_taxonomy.py`, `tests/test_seed_taxonomy.py`, `data/finviz_sector_industry_map.{json,csv}` | S | ✅ **Done 2026-06-24.** Replaced PR #109's Playwright/Cloudflare plan with a plain-HTTP parse of fasiha/finviz-git-scraper's `map-sec_all.json`. 11/11 sectors, 144/144 industries match (100%). 1 extra in fasiha (`Infrastructure Operations`) — newer Finviz addition. PR #109 superseded and should be closed. 13 tests pass. |
| ~~INS-7~~ | ~~**Sector Breadth metric**~~ | `dashboard/app.py`, `dashboard/sector_breadth.py`, `tests/test_sector_breadth.py` | M | ✅ **Done 2026-06-24.** Sector Breadth table in Strength tab (Industries view): for each sector, count how many industries rank in top half of full universe. `compute_sector_breadth()` extracted to `dashboard/sector_breadth.py` (10 tests). Rank metric selectbox (week/month/ytd). Full-universe breadth unaffected by sidebar sector filter. PWA breadth bar (Feature B) deferred to Phase 2. |
| ~~TASK-6B~~ | ~~**Streamlit sidebar sector filter**~~ | `dashboard/app.py` | S | ✅ **Done 2026-06-24.** Sidebar selectbox "Sector" (All + 11 sectors) when viewing Industries. Filters snap_df, delta_df, snap_df_full, delta_df_full by selected sector's industries in all tabs. Full-universe copy preserved for INS-7 breadth computation. |

---

#### Stock Picks Pipeline

Full plan: `planning/stock-picks-from-leading-groups.md` · ADR-007 (selector) · ADR-008 (architecture)

| # | Task | File(s) | Effort | Notes |
|---|------|---------|--------|-------|
| ~~PICKS-2~~ | ~~**Phase 2: collect_picks.py + selector + workflow**~~ | `scripts/collect_picks.py`, `scripts/picks_config.py`, `data/picks/selector_versions.json`, `.github/workflows/collect_picks.yml`, `.github/workflows/collect.yml`, `tests/test_collect_picks.py` | L | ✅ **Code complete 2026-06-25 (branch `claude/brave-hypatia-pfzhu1`).** Pure `select_groups()` (4-bucket priority-fill, ≤20 unique, dedup-tagged, 19 `grp_*` snapshot), paginated scrape (`PAGE_CAP`/`GLOBAL_FETCH_CAP=50`), append/dedup + `picks_latest.csv`, G4 `validated` flip, stale-read guard. Shared `concurrency: finviz-data-commit` on BOTH workflows (G1). v1 registry w/ immutability tests. 30 tests, 480 pass. **Remaining: one live Actions dispatch to start daily capture + confirm 84-col scrape on Azure.** |
| ~~PICKS-2-LIVE~~ | ~~**Dispatch collect_picks.yml — start the daily clock**~~ | — | XS | ✅ **Done 2026-06-25.** First green run: 273 picks / 262 unique tickers / 19 industry groups / all 4 buckets populated / 19/19 slugs validated / dedup confirmed (Packaging & Containers in both emerging + accel). `picks_latest.csv` correct (max-date slice = full CSV since day 1). 108 cols per row (84 Finviz + 5 lead + 19 grp_*). |
| ~~PICKS-2-ADR8~~ | ~~**Reconcile ADR-008 grp_* table with the 19-col plan spec**~~ | `knowledge/decisions/ADR-008-picks-collection-architecture.md` | XS | ✅ **Done 2026-06-25.** ADR-008 updated to match the implemented 19-col spec: replaced `grp_selection_priority` with `grp_category_rank`; added `grp_momentum_weighted_mid`, `grp_rank_agreement`, `grp_rs_accel`. Added reconciliation note explaining the drift from the initial draft. |
| PICKS-2-HDR | **Validate scraped Finviz header against `finviz_cols` at scrape time** | `scripts/collect_picks.py`, `tests/test_collect_picks.py` | S | `build_pick_rows` maps each scraped cell by the config's 84 `label`s (`stock.get(col, "")`). If Finviz ever renames/reorders a header label so it no longer matches `screener_config.json`, every affected column writes **blank silently** — no error, just lost data on the irreplaceable capture. The live scrape header IS captured (`paginate_group` returns it) but currently unused for validation. Fast-follow: in `main()`, assert/log when a group's scraped header is not a superset of `finviz_cols(config)` — at minimum a loud WARNING in the run summary listing the mismatched labels; consider failing the run (exit 1) if overlap drops below a threshold so CI goes red and the debug-HTML artifact uploads. The golden-header test only pins the *config*, not the *live* response. Add a unit test feeding a drifted header through a header-check helper. |
| PICKS-2-CRON | **Promote collect_picks.yml to the Cloudflare-cron dispatcher (timing robustness)** | `.github/workflows/collect_picks.yml`, `worker-cron/wrangler.toml` | S | `collect_picks.yml` currently fires on a **single** GitHub `schedule:` cron (`8 20 * * 1-5`, ~20 min after `collect.yml`'s EOD run). Two problems: (1) GitHub cron drifts hours and is dropped under load (CLAUDE.md §Automation documents this for `collect.yml` — the reason the Cloudflare `finviz-cron-dispatcher` exists); (2) the shared `concurrency` group prevents overlap but does **not** order the two workflows — if deltas aren't pushed before picks runs, the stale-read guard aborts (safe no-op) but there is then **no picks capture that day** until a manual dispatch, and the daily list is unrecoverable. Fast-follow: add a new Cloudflare cron entry that POSTs a `workflow_dispatch` to `collect_picks.yml` a safe margin (~20–30 min) after the EOD `collect.yml` dispatch, mirroring the existing dispatcher pattern; keep the GitHub `schedule:` as a backstop. Revisit the margin after live data shows how long `collect`+`compute_deltas`+push actually takes on Azure. |
| PICKS-3 | **Phase 3: PWA surfaces (parent — SPEC LOCKED 2026-06-26)** | — | L | **Spec locked, CEO-aligned.** See plan §"Phase 3 — PWA surfaces (DETAILED SPEC)" — subphases below (3a→3d), acceptance criteria + tests in the plan. Decisions: backend derives raw metrics / PWA holds thresholds (C5); base filter >5B + MA cond (C6); Focus = blended quality rank, no 50MA-proximity reward (C7); no RSI gate (C8); fundamentals + honorable-mentions deferred to 3d (C9). |
| PICKS-3A | **3a: Picks tab MVP + backend derived metrics** | `scripts/picks_metrics.py` (new), `scripts/collect_picks.py`, `data/picks/picks*.csv`, `tests/test_picks_metrics.py`, `docs/index.html`, `docs/sw.js`, `docs/releases.json` | M | Backend cols `atr_ext_50, risk_20ma_pct, risk_50ma_pct, range_atr, stage2` via `ensure_picks_csv()` migration + new Picks tab: base filter (C6, ~141 EOD rows), category→industry→stock, least-extended-first, extension color bands (C4), breadth count. WELCOME/VALID_TAB_IDS/GUIDE_TAB_CHIPS updates + vsmarket gap fix. Release triplet. Worked-example assertions (EOD): ANET≈0.67×, STX≈3.16×, DELL≈3.64×, SNDK≈4.55×. |
| ~~PICKS-3B~~ | ~~**3b: Risk engine + Focus List toggle (SPEC REFINED 2026-06-27)**~~ | `docs/index.html`, `docs/sw.js`, `docs/releases.json`, `tests/test_pwa_picks.py` (NEW), `tests/fixtures/picks_latest.csv` | M | ✅ **Done 2026-06-27.** `renderPickRow()` extracted as top-level helper; expandable risk panel with HoD, 20MA/50MA stops (price/$/%/sh), extension, Range/ATR, Volatility(ATR%), Stop distance(ATR), score debug breakdown. Focus scoring: one min–max ruler, multiplicative discount, nearest-positive-MA stop (TESTAB20 regression row added). All/Focus toggle, A4 reset. Release triplet v2026.06.27. 6 new constants triple-documented. 519 tests pass. `tests/test_pwa_picks.py` created with 13 Playwright tests. **A4 (reset-to-All) reversed 2026-06-30 — see PICKS-STATE-PERSIST.** |
| ~~PICKS-3C~~ | ~~**3c: Lookup Stage-2 section + deep-link button**~~ | `docs/index.html`, `docs/sw.js`, `docs/releases.json`, `tests/test_picks_button_config.py` (NEW) | S | ✅ **Done 2026-06-28.** Stage-2 section added to both `renderLookup()` branches. `slugifyGroup()` + `buildScreenerUrl()` helpers. `BUTTON_*` constants inlined (BUTTON_V, BUTTON_BASE_FILTERS, BUTTON_SORT, BUTTON_FT). `ind_<slug>` button for all 144 industries, `sec_<slug>` for all 11 sectors. 9-test anti-drift guard (`tests/test_picks_button_config.py`). Release triplet v2026.06.28 (sw.js → finviz-v33). Triple-documented. 478 tests pass. |
| ~~PICKS-3E~~ | ~~**Phase A: HoD price-basis toggle (per-card, display-only)**~~ | `docs/index.html`, `docs/sw.js`, `docs/releases.json`, `tests/test_pwa_picks_hod.py` (NEW), `tests/fixtures/picks_latest.csv`, `knowledge/moaty-metrics.md` | M | ✅ **Done 2026-06-30.** `deriveRiskMetrics(row, basis)` pure function; `__buildRiskBasisContent(rowData, basis)` renders basis-dependent HTML; `__setPickBasis(key, basis)` updates button states + re-renders content; `__togglePickRow` resets basis on collapse (ephemeral state rule). `[ Last \| HoD ]` toggle buttons inside every expanded risk panel. trim→extended label in HoD mode. `price_basis` GUIDE entry + moaty-metrics.md entry. TESTHOD fixture row added. 5 Playwright tests in `test_pwa_picks_hod.py`. Release triplet v2026.06.30 (sw.js → finviz-v36). Phase B (global Focus re-rank) tracked below. |
| PICKS-3E-HOD-PHASE-B | **Phase B: Global HoD toggle re-ranks Focus list** | `docs/index.html` | L | Tab-level [ Last \| HoD ] toggle that re-derives Focus scores with HoD as the entry basis, re-ranking the entire Focus pool. Phase A is ephemeral display-only; Phase B changes which stocks appear at the top. Design in `planning/picks-hod-price-basis-toggle.md` §4. Prerequisite: Phase A shipped and validated in prod. |
| ~~PICKS-CHARTS~~ | ~~**Finviz charts-grid deep-links (v=211 multi-ticker view)**~~ | `docs/index.html`, `docs/sw.js`, `docs/releases.json` | S | ✅ **Done 2026-06-30.** `buildChartsUrl(tickers)` (dedupes via Set, no cap). "Charts ↗" links added: per-group header in Picks All view, tab-level "View all N charts in Finviz" in All + Focus views, and beside the Stage-2 screener button in Lookup. Also fixed 2 internal nav-to-Lookup buttons that incorrectly used `↗` (external-link convention) instead of `›` (internal convention) — per-group header button + Focus/Lookup row subtitle button. Scroll position retention added (`state.scrollPos`, restored in `render()`) so tabs keep their scroll position on re-entry. Release triplet v2026.06.30.5 (sw.js → finviz-v41). Verified end-to-end with a real headless Chromium session (fixture-intercept pattern) — confirmed dedup, `›` vs `↗`, and scroll restore all work. |
| ~~PICKS-STATE-PERSIST~~ | ~~**Retain Picks tab expanded-row + All/Focus view state across tab navigation**~~ | `docs/index.html`, `planning/stock-picks-from-leading-groups.md`, `docs/sw.js`, `docs/releases.json` | M | ✅ **Done 2026-06-30 (explicit VP call to reverse A4).** (1) `state.picksExpanded` (Set of stable `ticker_category` keys) persists which risk panels are open; the check lives inside the shared `renderPickRow()` helper, so it also applies to the Lookup tab's Stage-2 section (`renderLookupStage2()`) for free — both call sites use the same function and the same global state, not just the Picks tab. `__togglePickRow(key, expandKey)` updates the set on toggle from either call site. (2) `switchTab()` no longer forces `picksView` back to `'all'` — the All/Focus selection now survives tab navigation. Scroll-save skip-on-Focus logic (added for PICKS-CHARTS) removed since it's no longer needed. A4 reversal documented in `planning/stock-picks-from-leading-groups.md` (note appended, not rewritten) + the `state.picksView` code comment + the All/Focus toggle HTML comment. Per-card price-basis stays ephemeral (resets on collapse) — out of scope for this reversal, that's a separate, intentional design (see `price_basis` GUIDE entry). |
| PICKS-3D | **3d: Polish (optional)** | `scripts/collect_picks.py`, `docs/index.html` | M | True inside-day (prev-day H/L self-join, schema bump) replacing the C1 proxy; loose fundamental floor on Focus + "Honorable mentions (failed fundamental floor)" sub-list (C9); search/filter, sort toggles, target/R framing. Also contains PICKS-3D-STALE + PICKS-3D-STACKEDSTOP (see below). |
| PICKS-3D-MOBILE | **[FAST-FOLLOW] 8-tab flex-1 mobile viewport check** | `docs/index.html` | XS | After adding Picks (8th tab), eyeball the tab bar at 375px (iPhone SE) viewport. 8 × `flex-1` items at 375px = ~47px each — "Picks" (5 chars) fits but is tight. If any label truncates or wraps, abbreviate or shorten. Test at 375px before marking 3a done. |
| PICKS-3D-STALE | **[FAST-FOLLOW] Intraday staleness banner + run_at column** | `scripts/collect_picks.py`, `data/picks/picks*.csv`, `docs/index.html` | S | Add a `run_at` column to `picks.csv` (ISO UTC timestamp stamped at write time in `collect_picks.py`). In the PWA, if `run_at` is < 16:00 ET on the data date, show a subtle banner: "Prices/High captured intraday — trigger levels valid for next session after EOD update." Our cron fires EOD so this is a no-op in normal operation; only fires if someone manually dispatches the workflow earlier in the day. |
| PICKS-3B-FOCUSGATE | **[POST-LIVE] Revisit Focus gate: price>50MA vs full stage2** | `docs/index.html` | XS | 3b admits any Focus name above its 50MA; does NOT require 50MA>200MA. After a few weeks of live Focus data, decide whether sub-Stage-2 names pollute the list and the gate should tighten to `stage2==1`. Also revisit whether freshness-fill leaders should get `momentum_confirmed` credit in the Focus group-strength component (M3). Tracked per CEO 2026-06-27. |
| PICKS-3B-FOCUSTEST | **[FAST-FOLLOW] Deterministic Focus-order regression test** | `tests/test_pwa_picks.py` | S | Freeze a small fixture pool, assert whole-pool ordering + scores within ±0.01 (a single stock's score can't be pinned in isolation — cross-sectionally normalized). Tabled per CEO 2026-06-27; 3b acceptance test asserts qualitative properties (scores∈[0,1], discount observable, below-MA excluded) instead. |
| PICKS-3C-PLAYWRIGHT-GAP | **[FAST-FOLLOW] Playwright tests for Lookup Stage-2 section** | `tests/test_pwa_picks.py` or new `tests/test_pwa_lookup_stage2.py` | S | Phase 3c shipped no Playwright tests for the new `renderLookupStage2()` function (only Python anti-drift tests in `test_picks_button_config.py`). A regression in the Lookup tab rendering — category chips, picks list, screener button URL, empty-state message — would not be caught by CI. Pattern: intercept `picks_latest.csv` and `industries/deltas.csv` with fixture data, look up a group name, assert the Stage-2 section renders. Specific gaps: (1) industry with picks → picks list + category chip appear; (2) industry NOT in picks → empty-state message appears + button still renders; (3) sector lookup → no picks list, only sector button; (4) ticker lookup (both branches) → industry section + sector button; (5) screener button href contains correct `ind_<slug>` token. Use same http.server + Playwright intercept pattern as `test_pwa_picks.py`. Prerequisite: `playwright install chromium`. |
| PICKS-3D-STACKEDSTOP | **[3d POLISH] 50MA double-support bonus on Focus score** | `docs/index.html` | S | Add the "both MAs tight AND close together" reward (`|sma20_price−sma50_price|/price` below threshold = two stacked supports) on top of the v1 nearest-stop component. v1 already gives the "either MA" reward; this adds "both, and close." See plan §3d. |
| PICKS-4 | **Phase 4: attribution (eval_picks.py)** | `scripts/eval_picks.py` | XL | Offline: reconstruct positions from the log, OHLC backfill for exited names (Stooq/yfinance/Tiingo spike), forward returns vs SPY+group, methodology head-to-head. Own session, later. Also the D11 **sunset** review — narrow the stored net back toward tight Stage-2. |
| ~~PICKS-METH~~ | ~~**Picks methodology tracking (versioned display constants + replay CLI)**~~ | `data/picks/display_methodology.json`, `tests/test_picks_methodology.py`, `scripts/replay_picks.py`, `tests/test_replay_picks.py` | M | ✅ **Done 2026-07-01.** Per `planning/picks-methodology-tracking.md`: v1 entry versions the base filter, All-view sort, Focus DQ, 3-component Focus score, and ATR display bands; anti-drift guard checks every param against live `docs/index.html` constants (14 tests); `replay_picks.py` deterministically reconstructs a historical All/Focus view from `picks.csv` + the methodology JSON for A/B testing across versions (20 tests). Triple-documented (CLAUDE.md, README.md § Configurable parameters, in-code). See PICKS-METH-V2 below for the known gap this surfaced. |
| PICKS-METH-V2 | **Extend display_methodology.json to cover Phase 3d/4 Focus haircuts** | `data/picks/display_methodology.json`, `scripts/replay_picks.py`, `tests/test_picks_methodology.py`, `tests/test_replay_picks.py` | M | v1 (PICKS-METH) only versions the original Phase 3b formula. By the time it was implemented, `docs/index.html` had grown a liquidity penalty (`FOCUS_MIN_DOLLAR_VOL` hard gate + `LIQUIDITY_PENALTY_START/MAX` ramp), an earnings-proximity penalty (`EARNINGS_IMMINENT_DAYS`/`EARNINGS_CAUTION_DAYS` + `EARNINGS_PENALTY_MAX`/`POST_EARNINGS_PENALTY_FRAC` ramp), and the opt-in Phase 4 Ariel-match filter (`ARIEL_*`) — none captured in v1's `params`. `replay_picks.py` therefore does not bit-for-bit match live Focus scores/eligibility today. Add a v2 entry once these are considered stable enough to lock, and extend `_replay_focus()`'s multiplicative haircuts (and, if in scope, a separate Ariel-match replay step) to match. |
| DOC-DRIFT-1 | **Fix stale ATR constants in README § PWA display thresholds** | `README.md` | XS | Found while implementing PICKS-METH: `README.md`'s PWA display-thresholds table says `ATR_EXT_ACTIONABLE = 5.0` and `ATR_EXT_PENALTY_START = 3.5`; the live `docs/index.html` (and `CLAUDE.md`, which is correct) has `4.0` / `2.5`. Pure doc fix — no code or JSON change — but touches `docs/index.html`-adjacent doc so double check nothing else in that README block drifted before fixing. |

---

#### Ticker Lookup Feature

Full plan: `planning/PLAN_ticker_lookup.md`

| # | Task | File(s) | Effort | Notes |
|---|------|---------|--------|-------|
| ~~TICKER-0~~ | ~~**Taxonomy map: FMP → Finviz (Claude session)**~~ | `data/taxonomy_map.csv`, `data/fmp_sample_profiles.json`, `knowledge/fmp-api-findings.md` | S | **Done 2026-06-14.** Sampled 242 live FMP profiles → 129 unique FMP industries; built 133-row map, all Finviz names validated, 132/144 Finviz industries reachable (FMP coarser in 12 — documented). 12 low-confidence rows flagged. Evidence + API findings committed. |
| ~~TICKER-1~~ | ~~**CF Worker: /lookup endpoint + KV cache**~~ | `worker/src/index.js`, `worker/wrangler.toml`, `worker/src/taxonomy_map.json`, `worker/package.json`, `worker/README.md`, `worker/test/index.test.js` | M | ✅ **Done — deployed live 2026-06-14:** `https://finviz-ticker-lookup.salmonbaby8.workers.dev`. Code merged PR #74; deployed headlessly via `CLOUDFLARE_API_TOKEN` from a Claude Code web session (KV namespace `3ae4430b…`, FMP key set as Worker secret). 28 vitest tests pass; `/health`, `/lookup?t=AAPL` (→ Technology / Consumer Electronics, conf 1.0, KV cache verified), `/lookup?t=FAKEXYZ` (→ ticker_not_found) all pass live. Headless deploy writeup: `knowledge/cloudflare-headless-deploy.md`. |
| ~~TICKER-2~~ | ~~**PWA Lookup tab**~~ | `docs/index.html` | M | ✅ **Done 2026-06-14.** New "Lookup" tab wired to live Worker (`WORKER_URL`). Ticker input → `/lookup` → company header (logo/exchange/mktcap/confidence) + industry perf card + sector perf card + FAVORABLE/MIXED/CAUTION signal. Joins to already-loaded `state.data.{sectors,industries}.{delta,snap}` by exact Finviz group name (verified match). sessionStorage cache; graceful error cards. |
| ~~TICKER-3~~ | ~~**Streamlit Lookup tab**~~ | `dashboard/app.py`, NEW `dashboard/worker_client.py`, `requirements.txt`, `requirements-test.txt`, NEW `tests/test_worker_client.py` | M | ✅ **Done 2026-06-14.** Tab 8 "Ticker Lookup": calls live Worker via pure `lookup_ticker()` (no st import → testable), renders company header + Finviz classification + industry/sector `_render_group_card` (rank/momentum/perf joined to latest CSV date). `WORKER_URL` from `st.secrets`/env with live default. `requests==2.33.1` pinned. 4 new tests in `test_worker_client.py` (168 passed total, ex-playwright). |
| ~~TICKER-4~~ | ~~**Operations setup**~~ | — | — | ✅ **Done 2026-06-15.** Added FMP call counter (daily KV key `fmp_calls_YYYY-MM-DD`, 7d TTL), `/stats` endpoint returning `{date, fmp_calls_today}`, `DELETE /cache?t=TICKER` for manual cache busting. Counter incremented only on FMP cache misses, never on errors. 34 vitest tests pass. PR #90 merged. |
| TICKER-5 | **[FUTURE] Sector/Industry → Stocks screener** | `worker/src/index.js` (add /stocks endpoint), `docs/index.html`, `dashboard/app.py` | M | New Worker endpoint `/stocks?finviz_sector=&finviz_industry=` calls FMP screener, returns top 25 by market cap, KV cache 7d. Both front-ends add "Show stocks" toggle on group cards. Do NOT start until TICKER-0 through TICKER-4 are validated in production. See Phase 7 in plan. |

| ~~ETF-1~~ | ~~**Curated ETF→Finviz-group override layer (Lookup)**~~ | — | — | ✅ **Done 2026-06-20.** 31 curated ETF overrides (15 thematic/11 sector SPDRs/5 diversified). Build validation against snapshot CSVs. Runtime `lookupEtf()` + `fetchProfile()` wiring. PWA renders ETF kind badges + diversified informational card. ADR-005, worker/README, CLAUDE.md updated. 50 worker tests + 165 Python tests pass. Phase 2 (Finnhub holdings) deferred, design note in ADR-005. |
| ~~RS-3~~ | ~~**Phase 3: Surface RS signals in PWA**~~ | `docs/index.html`, `docs/sw.js`, `docs/releases.json`, `knowledge/moaty-metrics.md`, `tests/test_guide_releases.py`, `README.md`, `CLAUDE.md` | M | ✅ **Done 2026-06-21.** New "vs Mkt" tab (RS Score leaderboard + Emerging/Fading sub-views), Today card rs_month chip + rs_slope glyph, RS_STRONG/RS_SLIGHT constants, GUIDE 6 new entries, release triplet (v19). PR #139 open. Tier 5 discrete flags deferred → RS-4. |
| ~~RS-4~~ | ~~**Tier 5 RS discrete flags**~~ | `scripts/delta_config.py`, `scripts/compute_deltas.py`, `docs/index.html` | L | ✅ **Done 2026-06-21.** `beats_benchmark_{day..ytd}` (0/1), `rs_new_high` (NH badge, 20-session high), `rs_cross` (↑ cross badge, crossed 0 in last 5 sessions). 9 new schema columns auto-migrate. NH + ↑ cross badges on vs-Market RS Score + Regime cards; "beats N/7 tf" sub-line. 3 new GUIDE entries + moaty-metrics.md + README + CLAUDE.md + release triplet (v21). 206 tests pass. |
| RS-4b | **[OPT] Suppress neutral rsChip on Today cards** | `docs/index.html` rsChip() | S | Add `Math.abs(v) < RS_SLIGHT` guard to suppress chip inside ±0.5pp neutral band. Evaluate after SPY data has been live a few weeks to see if grey chips read as useful "data confirmed" signal or as noise. Current behavior (always show) is intentional — see code comment in rsChip(). |
| SW-UPDATE-UX | **[OPT] Soften SW update to toast instead of auto-reload** | `docs/sw.js`, `docs/index.html` | S | Currently the SW broadcasts `SW_RELOAD` on activate → tab auto-reloads silently. If this proves disruptive (e.g. user mid-session loses scroll/state), switch to Option 2: post `{ type: 'SW_UPDATED' }` and show a "New version — tap to refresh" toast instead. The TODO comment in `sw.js` activate handler marks the exact spot. Only do this if Option 1 causes real complaints. |

> **Phase 0:** (1) FMP free account + API key ✅ done. (2) Cloudflare account + KV namespace ✅ done — Worker deployed 2026-06-14.

> **Monthly recurring:** CF analytics check, FMP quota check, taxonomy validity spot-check. See plan Phase 5.

---

#### Lookup Tab Improvements

Full plan: `planning/lookup-tab-improvements.md`. ADRs: `knowledge/decisions/ADR-001..003`. Metric inventory: `knowledge/moaty-metrics.md`. Develop on `claude/lookup-tab-improvements-h7nw9b`. All Phase 1 slices are client-side in `docs/index.html` (no pipeline change, HTML-only — note in commits).

| # | Task | File(s) | Effort | Notes |
|---|------|---------|--------|-------|
| ~~LOOK-0~~ | ~~**Phase 0: knowledge + plan + README moat**~~ | `planning/lookup-tab-improvements.md`, `knowledge/moaty-metrics.md`, `knowledge/decisions/ADR-001..003`, `knowledge/cloudflare-edge-roadmap.md`, `README.md`, `.session/SPRINT.md` | S | Pickup-able plan, metric inventory, 3 ADRs, CF roadmap, README "What makes this different" section. No behavior change. |
| ~~LOOK-1~~ | ~~**Slice 1: retain history + weekly-rank sparkline**~~ | `docs/index.html`, `docs/sw.js` | M | ✅ **Done 2026-06-16.** `loadGroup` now retains full delta history in `state.data[group].deltaAll` (latest-only `.snap`/`.delta` untouched). New `groupRankHistory()` + `rankSparkline()` render an inline SVG of `rank_week` over the last ~30d in each group card, y inverted (up = improving), green/red by net direction, labeled "Weekly rank · last Nd". Hidden when <2 points. SW cache → v4. |
| ~~LOOK-2~~ | ~~**Slice 2: conviction chip + Rank Floor**~~ | `docs/index.html` | M | ✅ **Done 2026-06-16.** New `convictionInfo(delta, n)`: Rank Floor = max(rank_month, rank_quarter, rank_half) → "Top #{floor} across 1/3/6mo" row. Chip = "Sustained" (floor ≤ top quartile, emerald) / "Consistent" (rank_agreement ≥ 0.85 AND floor ≤ top half, sky) / hidden. Returns null gracefully if the 3 ranks aren't all present. Chip shown top-right of each group card. |
| ~~LOOK-3~~ | ~~**Slice 3: breadth dot strip**~~ | `docs/index.html` | S | ✅ **Done 2026-06-16.** `breadthStrip(snap)` renders D·W·M·Q·6M·Y dots (green/red/grey per `perf_*` sign) + an "All green" badge or "k/4 green" count. Verdict gates on month/quarter/half/ytd only via `BREADTH_TFS[].gate`; day & week dots render but don't gate (ADR-003). |
| ~~LOOK-4~~ | ~~**Slice 4: evidence-backed SIGNAL copy**~~ | `docs/index.html` | S | ✅ **Done 2026-06-16.** New `groupReasons(name, gd, n)` extracts concrete signals (30d/7d rank trajectory, conviction+floor, momentum %, breadth k/4). `contextSignalCard` appends the 2–3 strongest (industry first) as an evidence line under the verdict. Scoring spine + thresholds unchanged. |
| ~~LOOK-5~~ | ~~**Slice 5: clarity wins**~~ | `docs/index.html` | S | ✅ **Done 2026-06-16.** Rank label now "Rank (wk)"; added a 30d rank-delta chip (`rank_week_delta_30d`, "▲N over 30d") beside the weekly arrow; replaced "Looking up…" text with `lookupSkeleton()` matching the result layout. |
| ~~LOOK-6~~ | ~~**Slice 6: QoL — glossary + info affordance + deeplinks**~~ | `docs/index.html` | M | ✅ **Done 2026-06-16.** `lookupGlossary()` = collapsed "Why this matters" `<details>` (copy from `knowledge/moaty-metrics.md`) covering rank/floor/sustained/momentum/breadth incl. the percentile basis (folds in the info affordance). Subtle Finviz (`quote.ashx?t=`) + **TradingView** (`/symbols/SYM/`) deeplinks in the company header. Deepvue dropped — no public per-ticker URL (behind login); owner chose TradingView. |
| ~~LOOK-S1~~ | ~~**Lookup group search + typeahead (Ideas 1+2+4)**~~ | `docs/index.html` | M | ✅ **Done 2026-06-20.** Local group name search (case-insensitive, exact match, industries preferred over sectors). Typeahead dropdown ≥2 chars, prefix-first, 6 results, highlighted match, S/I badges, 40px touch, ↑↓ Enter Esc Tab keyboard nav. `doLookup()` refactored: group match → local; no match → Worker ticker path unchanged. Placeholder updated to "Search ticker or group…". `planning/lookup-search-enhancements.md` Ideas 1+2+4. |
| ~~LOOK-S2~~ | ~~**Aggregated group view (Idea 3)**~~ | `docs/index.html` | M | ✅ **Done 2026-06-20.** `groupPerfCard` gains `expanded = true` mode: all-7-timeframe rank+perf grids, YTD rank delta table for all windows, momentum deep dive (confirmed, accel, regime, rank trend). Sparse fields show `—`. Applied to both group-name path and ticker path cards. `lookupGlossary` extended with 5 new metric explanations. GUIDE tabs updated for lookup context. |
| LOOK-B1 | Sparkline rank-timeframe toggle (wk/mo/3mo/6mo) | `docs/index.html` | S | Deferred (Proposal A). |
| LOOK-B2 | Acceleration hint from `perf_*_delta_*` (▲▲/▼) | `docs/index.html` | S | Deferred (Proposal B7). |
| ~~LOOK-B3~~ | ~~Recent searches + pinned favorites (Idea 5)~~ | `docs/index.html` | S | ✅ **Done 2026-06-20.** `localStorage` keys `fvg_lookup_recent` (max 8, FIFO, pinned exempt) + `fvg_lookup_pinned` (no cap). Chips below search bar when empty; hide on typing/result. Pin ☆/★ button on every result card. Graceful degradation on private browsing / storage full. |
| ~~LOOK-B4~~ | ~~Fuzzy / "did you mean" matching (Idea 6)~~ | `docs/index.html` | M | ✅ **Done 2026-06-20.** `GROUP_SYNONYMS` constant maps colloquial names (semis, pharma, banks, biotech, …). Levenshtein fuzzy match with ratio threshold 0.35 catches typos ≥5-char queries; short ticker-like inputs (≤4 chars, no space) skip fuzzy. "Did you mean X?" prompt requires user confirmation. |
| ~~LOOK-B5~~ | ~~Empty-state suggestion chips (Idea 7)~~ | `docs/index.html` | S | ✅ **Done 2026-06-20.** `topMomentumChips()` returns top 5 groups by `momentum_score` from in-memory state. Shown when input is empty and no saved pinned/recents exist; hidden otherwise. Zero network calls. |
| LOOK-B6 | Tap group card → jump to group in Today/Momentum | `docs/index.html` | M | Deferred (Proposal D10). |
| LOOK-B5 | AI rotation-phase line on sector card | `docs/index.html` | S | Deferred. |
| LOOK-B6 | Promote Rank Floor to `compute_deltas.py` column (+ dashboard + tests) | `scripts/compute_deltas.py`, `dashboard/app.py`, `tests/` | M | Deferred. Product-wide consistency. |
| LOOK-B7 | Revisit All-Green week gating; align dashboard | `docs/index.html`, `dashboard/app.py` | S | Deferred. See ADR-003. |

---

#### AI Integration

| # | Task | File(s) | Effort | Notes |
|---|------|---------|--------|-------|
| AI-MIGRATION | **Migrate from Gemini AI Studio to Vertex AI (Phases 1–4)** | `scripts/generate_ai.py`, `.github/workflows/generate_ai.yml`, `tests/test_generate_ai.py`, `CLAUDE.md` | L | Plan in `planning/vertex-ai-migration.md` (PR #67). **Phases 2–4 merged in PR #79** (2026-06-14): dual-mode client, WIF workflow, PR #83+#84 fixes. **Phase 1 (GCP infra) = owner, done** — 3 secrets added; script confirmed on Vertex AI backend. **⚠️ BLOCKER: `sectors.daily_delta` field fails JSON parse** ("Unterminated string" error, column 99). PR #84's 900-token increase insufficient; response appears truncated or wrapped. 6/7 fields generating cleanly. **Next:** Debug actual response format from Vertex AI, increase tokens further or reduce daily_delta scope. |
| PLAN-2 | **Phase 2: Schema Enrichment + Few-Shot** | `scripts/generate_ai.py`, `tests/test_generate_ai.py` | M | Add `description` fields + `additionalProperties: false` to all 5 schemas; fix `_normalize_phase()` confidence bug; add few-shot examples to briefing/watchlist prompts; add validation logging. **BLOCKED** until Phase 1 is deployed and 2+ weeks of `fetch_log.csv` data shows skip logic firing correctly (`ai_outcome=skipped` on no-data days, `=complete` on data days). |
| AI-1 | **Anomaly Detection + LLM Explanation** | `scripts/generate_ai.py`, `dashboard/app.py` | M | Flag rank deltas >2σ from a 14-day rolling window using pandas, then send each flagged group to Gemini for a 1-sentence contextual note. See full spec below. |
| AI-2 | **Natural Language Q&A** | `dashboard/app.py` | M | Text input in AI Insights tab — user types a question, gets a plain-English answer backed by the actual data. Requires a real-time API call; needs an auth/cost-gate decision. See full spec below. |
| ~~AI-3~~ | ~~**Restore per-field resumability in `generate_ai.py`**~~ | — | — | **Done in PR #58** (2026-06-13). Restored incremental partial-file loading. Also fixed daily quota abort (`DailyQuotaExhaustedError`) and delta error tracking. |
| AI-4 | **AI Health widget in Streamlit dashboard** | `dashboard/app.py` | S | PR #53 decoupled AI generation, so `fetch_log.csv` no longer shows AI outcomes. Add a health widget to the AI Insights tab reading from `data/ai/index.json`. No pipeline changes needed. See full spec below. |

**AI-1 spec — Anomaly Detection + LLM Explanation**

_What it does:_ Nightly, detect statistically unusual rank moves and add plain-English context for each one.

_Implementation (all in `scripts/generate_ai.py`):_
1. Add `detect_anomalies(delta_df: pd.DataFrame, min_days: int = 14) -> list` — loads ALL rows of `deltas.csv` (not just latest day), computes per-group rolling 14-day mean and std of `rank_ytd_delta_7d`, then for the latest date flags any group where `|rank_ytd_delta_7d - rolling_mean| / rolling_std > 2`. Returns list of `{"name": str, "delta": float, "z_score": float}`. Return `[]` if fewer than `min_days` rows exist — don't guess.
2. In `generate_for_group()` (after watchlist), if anomalies detected, build a prompt: _"The following groups had unusually large rank moves today (vs. their 14-day baseline). For each, write one sentence explaining what this kind of move might indicate about capital rotation. [anomaly list]. Respond as NAME: [note] one per line."_ Catch exceptions same as the other 3 calls.
3. Parse the response into `result["anomalies"] = [{"name": ..., "delta": ..., "z_score": ..., "note": ...}]`.
4. JSON output already committed nightly alongside other AI content.
5. Dashboard: in `dashboard/app.py` tab 7 (AI Insights, end of file), add a `st.expander("Notable Moves")` after the briefing section. Iterate `ai_data.get(group_key, {}).get("anomalies", [])` and render each with delta + z_score + note. Show "None detected" if list is empty.

_Test additions (`tests/test_generate_ai.py`):_ `test_detect_anomalies_returns_empty_below_min_days`, `test_detect_anomalies_flags_high_z_score`, `test_detect_anomalies_no_false_positive_normal_move`.

_Data gate:_ needs 14+ days of delta history. Gate with `if len(all_dates) < min_days: return []`.

---

**AI-2 spec — Natural Language Q&A**

_What it does:_ A text input in the AI Insights tab — user asks "which industries have improved rank for 30 days straight?" or "show me everything with high momentum but weak recent move" and gets a direct answer.

_Architecture decision required (pick one before starting):_
- **Option A (recommended):** Gate on `GEMINI_API_KEY` in `st.secrets` — if present, show the Q&A widget; if absent, show a muted info message. Key stored in `.streamlit/secrets.toml` (gitignored) locally, or in Streamlit Cloud's secrets UI for deployment. This means the API key lives in the Streamlit environment — acceptable if the dashboard URL is not widely shared.
- **Option B (local-only):** Only enable Q&A when running locally (`os.getenv("GEMINI_API_KEY")` set). No key in Streamlit deployment; hosted dashboard stays key-free. Good for personal use only.

_Implementation (`dashboard/app.py`, tab 7, bottom of the file):_
1. Check `api_key = st.secrets.get("GEMINI_API_KEY", None) or os.getenv("GEMINI_API_KEY")`. If None, show `st.info("Configure GEMINI_API_KEY to enable Q&A.")` and stop.
2. `question = st.text_input("Ask a question about the data...")` + `st.button("Ask")`.
3. On submit: serialize the latest `delta_df` as a compact markdown table (top 30 rows by momentum_score, columns: name / rank_ytd / rank_ytd_delta_7d / momentum_score / rank_agreement). Pass with question to `gemini-1.5-flash`. Cache with `@st.cache_data(ttl=300, show_spinner=False)` keyed on `(question, str(latest_date), group_label)`.
4. Render response with `st.markdown(response)`.

_Token budget:_ 30 rows × 5 columns ≈ ~500 tokens of data context. Well within Flash's 1M limit. Log `len(prompt)` on first run to confirm.

_Test:_ mock `genai.GenerativeModel.generate_content`, verify prompt contains the question and data table, verify cache key includes the date.

---

**AI-3 spec — Restore per-field resumability in `generate_ai.py`**

_Background:_ PR #35 (2026-06-11) implemented field-level resumability — load the existing partial JSON for today, regenerate only missing fields. PR #42 (2026-06-12) removed it entirely: the "if today's file exists, skip everything" idempotency check was causing stale insights on days when Finviz updated after the initial run. The fix in PR #42 swung too far — it removed resumability as collateral damage. PR #50 (2026-06-13) added a run-level skip gate (`_has_new_delta_data`). As of now:

- `existing_output = {}` is hardcoded in `main()` — never populated from file
- The per-field skip logic in `generate_for_group` (`if spec["name"] in result: continue`) is orphaned dead code that never fires
- Every run makes all 7 API calls from scratch, even if 4 already succeeded before a rate-limit failure

_What to implement:_ Before starting generation, if `output_path` (`data/ai/YYYY-MM-DD.json`) already exists for today, load it into `existing_output` and set `was_incremental = True`. If the file is already complete (per `_is_complete()`), skip the whole run — unless `--force-ai` is set. The existing per-field skip logic in `generate_for_group` then fires correctly for any already-present fields.

_Critical constraint — don't restore the PR #42 stale data bug:_ The PR #42 bug was: file existed from an early cron run → second cron run (after Finviz updated) saw the file and skipped everything → stale data persisted all day. The fix: only load the existing file if it is **incomplete** (partial). A complete file skips the run (no stale risk since all fields are done). A partial file resumes only missing fields (correct). `--force-ai` always regenerates everything regardless.

_Decision table:_
| State | Behavior |
|-------|----------|
| No file for today | Generate all 7 fields |
| Partial file for today | Load it; generate only missing fields |
| Complete file for today | Skip (log `outcome=skipped`) |
| Any state + `--force-ai` | Generate all 7 fields from scratch |

_Files:_
- `scripts/generate_ai.py`: modify `main()` — add file-load block before the generation loop (8–10 lines)
- `tests/test_generate_ai.py`: add 2 tests — `test_main_resumes_partial_file` (partial file → only missing fields called), `test_main_skips_complete_file` (complete file, no force → zero API calls)

_Effort:_ S — the scaffolding is already there. The only missing piece is the 8-line block that reads the file into `existing_output`.

---

**AI-4 spec — AI Health widget in Streamlit dashboard**

_Motivation:_ PR #53 decoupled AI generation from `collect.yml` — `ai_outcome` in `fetch_log.csv` is now always `""` for snapshot rows. There is no single place to see "did AI run today, and did it succeed?" without digging into Actions logs or raw JSONL. This adds a lightweight visibility widget to the dashboard.

_Data source:_ `data/ai/index.json` — already committed nightly by `_update_index()` in `generate_ai.py`. Structure: `{"updated_at": "...", "entries": [{"date": "YYYY-MM-DD", "status": "complete|partial|skipped|failed", "model": "...", "generated_at": "...", "rotation_phase": "..."}, ...]}`. Capped at 90 entries. File is ~5KB — fast to read.

_Implementation (`dashboard/app.py`, AI Insights tab):_
1. After the existing AI content renders, add `st.expander("AI Run Health", expanded=False)`.
2. Inside: `index_path = DATA_DIR / "ai" / "index.json"`. If it doesn't exist, show `st.info("No AI run history yet.")`.
3. Load the JSON, take the first 7–10 entries (last 7–10 days). Render as a table or `st.metric` row:
   - Date | Status | Model | Generated at | Phase
   - Color-code `status` with emoji: `complete` → ✓, `partial` → ~, `skipped` → ○, `failed` → ✗ (or use `st.success/warning/info/error` per row)
4. For `partial` entries: the full field-level detail is in `data/ai_run_log.jsonl`. Optionally add a nested expander "Show field detail" that reads that entry from the JSONL (match on `date`). This is a nice-to-have — the outer widget is the priority.

_No test required_ — dashboard-only change. Note it in the commit message.

_Effort:_ S — `index.json` is already being written; this is a pure read.

_Dependency:_ None. Works today.

---

#### Start Here Onboarding — deferred items

| # | Task | File(s) | Effort | Notes |
|---|------|---------|--------|-------|
| PWATEST-LOOKBACK | **Fix 3 pre-existing `TestPWALookbackWindows` failures** | `tests/test_functional_playwright.py` | S | These failures pre-date the Start Here feature and are unrelated to it. Tracked here so they don't get waved off permanently. Likely covered by PWA-TEST-GAP work — resolve together. Do not block Start Here commits on this. |
| ONBOARD-DL-UX | **Revisit carousel deep-link dismiss behavior** | `docs/index.html` | S | Current decision (two-way door): "Open →" on a mid-tour slide calls `switchTab()` + dismisses the carousel immediately (sets `fvt_intro_seen_v1`). Rationale: user chose to navigate; leaving carousel open behind would be confusing; they can re-open via hub "Start Here". Revisit if user feedback shows they want to browse back mid-tour without losing their slide position. Code is marked with `// ONBOARD-DL-UX` comment. |

---

#### Lookback config + momentum variants

Plan: `planning/compute-deltas-lookbacks-and-momentum.md`. Slices 1–5 landed on
`claude/jolly-darwin-fjik54` (config-driven wide schema, trading-day 5/10/20/50
lookbacks, six momentum variants, PWA minimal renumber, generate_ai repointed).

| # | Task | File(s) | Effort | Notes |
|---|------|---------|--------|-------|
| ~~LB-FF1~~ | ~~**[FAST-FOLLOW] PWA full-dynamic lookback windows**~~ | `docs/index.html` | M | ✅ **Done 2026-06-18 (PR #110)**. Buttons now derived from CSV header via `extractWindowsFromHeader()`. Zero literal window values remain in JS. |
| PWA-TEST-GAP | **[FAST-FOLLOW] Fill PWA + Streamlit functional test gaps (PR #105 follow-up)** | `tests/test_functional_playwright.py` | L | The current Playwright tests only guard the Movers tab lookback buttons (PR #105 regression). Ten behavioral gaps remain untested. See the TODO(PWA-TEST-GAP) comment block at the top of `tests/test_functional_playwright.py` for the full gap list with detailed pick-up notes per gap. **Priority order (highest first):** Gap 7 (empty state), Gap 2 (Today tab), Gap 1 (Movers cards data), Gap 3 (Momentum tab), Gap 6 (Lookup tab + Worker intercept), Gaps 4/5/8/9/10. All tests use the same fixture-intercept pattern already in the file. Run with `playwright install chromium` then `pytest tests/test_functional_playwright.py -v`. |

#### PWA Column Gaps (PR#105 new columns not yet surfaced)

Full plan: `planning/compute-deltas-lookbacks-and-momentum.md` (see gap map). Surfaced in PWA as of 2026-06-18:

| # | Column | Status | Notes |
|---|--------|--------|-------|
| ~~MOT-R1~~ | `regime_short_long` | ✅ Done 2026-06-18 | Rotation view in Momentum tab |
| ~~MOT-A2~~ | `momentum_accel` | ✅ Done 2026-06-18 | ▲▲/▲/▼/▼▼ badge on Momentum cards |
| ~~TOD-S3~~ | `rank_trend_slope` | ✅ Done 2026-06-18 | Slope glyph ↑↑/↑/~/↓/↓↓ beside trend arrow on Today cards |
| ~~STR-C4~~ | `momentum_confirmed` | ✅ Done 2026-06-18 | Sort key in Strength tab (replaces momentum_score) |
| ~~TOD-P5~~ | `perf_week_delta_20d`, `perf_ytd_delta_20d` | ✅ Done 2026-06-18 | "vs 20d ago" row in Today expanded card |
| MOT-W1 | `momentum_weighted_mid` | Deferred | Similar concept to momentum_score; low marginal UX until users internalize existing view |
| MOT-W2 | `momentum_weighted_fast` | Deferred | Same rationale as MOT-W1 |
| MOT-M3 | `rank_month_delta_5d/10d/20d/50d` | Deferred | Could surface in Movers view alongside rank_ytd/rank_week deltas |
| GAP-1 | `rank_day`, `rank_year` | Deferred | Low priority; no obvious placement without cluttering existing cards |
| GAP-2 | `perf_month_delta_5d/10d/20d/50d`, `perf_ytd_delta_5d/10d/50d` | Deferred | 20d window surfaced (TOD-P5); other windows deferred |

**Data availability note:** `momentum_accel` and `rank_trend_slope` need 10 sessions (~2026-06-23). `perf_*_delta_20d` needs 20 sessions (~2026-07-10). These columns appear empty until then — their UI elements are hidden gracefully until data arrives.

#### Signal-to-Noise Monitoring

| # | Task | File(s) | Effort | Notes |
|---|------|---------|--------|-------|
| ~~SIG-NOISE-1~~ | ~~**`scripts/signal_noise.py` — rolling churn reporter**~~ | `scripts/signal_noise.py`, `tests/test_signal_noise.py` | S | ✅ **Done 2026-06-23.** Computes `mean \|day-over-day Δmomentum_score\|` over a rolling window (default 20 sessions) separately for sectors and industries. Baseline (8 days, 6-tf formula): sectors 0.058 / industries 0.046 (~40% better than old 7-tf formula). Run: `python scripts/signal_noise.py`. 11 tests. |
| SIG-NOISE-2 | **[FUTURE] Wire churn as CI assertion or dashboard panel** | `.github/workflows/tests.yml` or `dashboard/app.py` | S | Gate on ≥20 sessions of data. Proposed threshold: `mean \|Δmomentum_score\| > 0.07` = regression flag for both sectors and industries. Prevents a future formula change from silently re-introducing noise. Implement once session count crosses 20 (~2026-07-16 at 1 run/day). |

---

#### Data / Insight Features

| # | Task | File(s) | Effort | Notes |
|---|------|---------|--------|-------|
| D1 | **[USER ACTION] Create `main` branch, set as default** | GitHub UI | S | Blocks cron and PWA-1. Merge `claude/elegant-babbage-hlxnfy` → new `main`, then Settings → Branches → change default. |
| PWA-1 | Fix hardcoded `BRANCH` constant in PWA | `docs/index.html` line ~117 | S | Change `'claude/elegant-babbage-hlxnfy'` to `'main'` (or whichever branch receives daily cron data). Depends on D1. |
| INS-4 | **Momentum Velocity (`momentum_score_delta_7d/14d`)** | `scripts/compute_deltas.py` | M | Track momentum_score change over time. "Rising Stars" = positive velocity + currently top-half. Needs 7+ days of data. |
| INS-5 | **Daily Brief card (PWA top-of-screen)** | `docs/index.html` | M | Single card: today's breakout, sustained leaders, what's rolling over. Eliminates tab-hopping on mobile. Needs 7+ days for interesting content. |
| INS-6 | **Momentum Score Heatmap (time × industry)** | `dashboard/app.py` | S | Companion to existing rank-delta heatmap — cells = `momentum_score` over time. Absolute picture of sustained leaders. Needs 7+ days. |
| ~~TAX-0~~ | ~~**Seed sector→industry taxonomy map**~~ | `data/finviz_sector_industry_map.{json,csv}`, `scripts/seed_taxonomy.py` | S | ✅ **Done 2026-06-24 (PR #171).** Plain-HTTP parse of fasiha/finviz-git-scraper. 11/11 sectors, 144/144 industries match (100%). PR #109 superseded. 13 tests pass. |
| TASK-6B | **Streamlit sidebar sector filter** | `dashboard/app.py` | S | ✅ *Unblocked by TAX-0. Build first.* Sidebar `selectbox("Sector", ["All"] + ...)` → filter `industries_df` via `isin(SECTOR_MAP[sector_choice])`. Load map from `data/finviz_sector_industry_map.json`. |
| INS-7 | **Sector Breadth metric** | `dashboard/app.py`, `docs/index.html` | M | ✅ *Unblocked by TAX-0. Build second.* "7 of 12 Technology industries top-half." Streamlit sector view + PWA breadth bar on sector cards. |
| DEBT-1 | `evict_today_rows` concurrency race | `scripts/collect.py` | S | Two simultaneous `collect.py` processes could race on read-modify-write. Non-issue given single scheduled Action + ad-hoc manual runs. Fix would be a file lock (e.g. `fcntl.flock`). Table until concurrency is actually needed. |
| DEBT-2 | `evict_today_rows` I/O errors not caught | `scripts/collect.py` | S | Disk-full / permission errors bubble up as exceptions. Intentional — matches rest of codebase. Could add explicit error message if this causes confusion in prod logs. |
| DEBT-3 | `DISPATCH_REF` in `worker-cron/wrangler.toml` hardcodes non-main branch | `worker-cron/wrangler.toml` | S | Set to `"claude/elegant-babbage-hlxnfy"` during Phase 1 (the current default). **Blocked by D1** — once D1 (create `main`, set as default) is done, change `DISPATCH_REF` to `"main"` and redeploy the Worker. The TODO(D1) comment in `wrangler.toml` marks the spot. |

---

#### Sector → Industry Hierarchy Features

Full plan: `planning/PLAN_sector_industry_hierarchy.md` — 22 features across 5 tiers (Navigation, Signal, Retention, Bridge, Trust). Foundation (TAX-0) ✅ done. All features below are consumers of `data/finviz_sector_industry_map.json`.

| # | Task | File(s) | Effort | Notes |
|---|------|---------|--------|-------|
| HIR-A | **PWA drill-down navigation** | `docs/index.html` | M | Tap sector card → expand inline to show constituent industries ranked with deltas. Biggest UX win from the hierarchy. Build after INS-7. |
| HIR-R | **Market-wide breadth gauge** | `docs/index.html` | S | "68% of industries top-half" at top of PWA home. Risk-on/risk-off dial. |
| HIR-D | **Divergence alerts / Rotation Radar tab** | `docs/index.html`, `dashboard/app.py` | M | Auto-surface sector vs. breadth disagreements: "sector green, only 2/12 industries participating." Highest-signal rotation pattern. VP decision: new tab vs. section before coding. |
| HIR-M | **Crowding / concentration warning** | `docs/index.html`, `dashboard/app.py` | S | Inverse of breadth: flag sector gain carried by 1 industry. Risk signal missing from every momentum tool. |
| HIR-I | **Since-last-look digest** | `docs/index.html` | M | Store last-viewed timestamp in PWA local storage. On open: "Since Tuesday: Energy breadth 4→9, Semis entered top 10." Zero backend. Highest-leverage retention feature. |
| HIR-K | **AI brief with sector context** | `scripts/generate_ai.py` | M | Add sector/breadth context to existing briefing prompt. Prompt-only update — no schema change. |
| HIR-H | **Rotation flow map** | `docs/index.html`, `dashboard/app.py` | L | Sankey/flow: capital leaving fading sectors → entering emerging ones. Signature feature. VP charting library decision required before coding. |
| HIR-E | **Breadth-confirmed momentum column** | `scripts/compute_deltas.py`, `tests/` | S | New `momentum_breadth_confirmed` in `deltas.csv`. Schema migration required. |
| HIR-TAX-TRIPWIRE | **Taxonomy staleness tripwire** | `scripts/collect.py` or `tests/` | S | Warn when live industry name missing from map. Prevents silent breadth denominator errors. Anytime task. |
| HIR-O | **[FUTURE] Sector→Industry→Stocks bridge** | `worker/src/index.js`, `docs/index.html` | M | Entry point for TICKER-5. Do NOT start until TICKER-4 validated + HIR-A built. |
| HIR-N | **[DEFERRED Q4+] Historical analog** | TBD | L | Match breadth fingerprint to past setups. Needs 6+ months data. Revisit ~Q4 2026. |

> **D1 note — the elegant-babbage debt**: `claude/elegant-babbage-hlxnfy` is currently the default branch (no `main` exists). GitHub Actions cron only fires on the default branch, and the PWA hardcodes this branch name. D1 is the root fix; PWA-1 is the code follow-up. Until D1 is done, the cron data will keep landing on `elegant-babbage` — so don't change the `BRANCH` constant before D1 is complete.

---

### 🟡 Ready

| # | Task | File(s) | Effort | Notes |
|---|------|---------|--------|-------|
| PLAN-1 | **Phase 1: Smart Regeneration + Force Flag** | `scripts/generate_ai.py`, `.github/workflows/collect.yml`, `README.md` | M | Add `_has_new_delta_data()` helper (Task 1.1), argparse + force flag + skip gate in `main()` (Task 1.2), workflow input param (Task 1.3). Full spec in `planning/PLAN_smart_regeneration_pydantic.md`. Start new session; generate_ai.py is large. |

---

### 🟢 In Progress

| # | Task | Branch | Notes |
|---|------|--------|-------|
| PICKS-2-CRON | **Promote collect_picks.yml to CF-cron dispatcher** | `claude/picks-cloudflare-cron-f0t7fz` | Plan written + docs updated (planning/cloudflare-cron-scheduler.md Phase 5, CLAUDE.md §Automation). Implementation (worker-cron/ + collect_picks.yml) in next session. VP action item: create healthchecks.io monitor (period=24h, grace=2h) and add `PICKS_HEALTHCHECK_URL` repo secret before implementation merges. |

---

### ✅ Done

| # | Task | Date |
|---|------|------|
| PICKS-SELECTOR-V2 | Selector dedup backfill (ADR-007 amendment, `SELECTOR_VERSION` v1→v2): a group already selected by a higher-priority bucket still gets tagged when it naturally ranks in a lower-priority bucket's top-N (attribution preserved) but no longer consumes one of that bucket's N slots — emerging/accel/rs_new_high backfill past rank N with the next new candidate (`add_bucket_with_backfill`). Verified on real `deltas.csv`: 6/29 and 7/1 both went from 16 to 20 unique groups scraped. Paired with `PAGE_CAP` 15→2 (40-name cap) — historical data showed only Biotechnology (~100 names/day) ever exceeded 40. | 2026-07-02 |
| CF-DEPLOY | Auto-deploy Cloudflare Workers on push: `.github/workflows/deploy-workers.yml` — two independent jobs (ticker-lookup + cron-dispatcher), test-gated, path-filtered, `workflow_dispatch` available | 2026-06-21 |
| ONBOARD | Start Here onboarding: WELCOME constant, 5-slide first-run carousel, hub "Start Here" section, fvt_intro_seen_v1, anti-drift tests, canonical copy in product-intro-copy.md, release cut | 2026-06-21 |
| ETF-1 | Curated ETF→Finviz override layer: 31 overrides (thematic/sector/diversified), build validation, runtime wiring, PWA ETF badges | 2026-06-20 |
| LB-FF1 | PWA full-dynamic lookback buttons derived from CSV header (`extractWindowsFromHeader`) (PR #110) | 2026-06-18 |
| MOT-R1/A2, TOD-S3/P5, STR-C4 | Surface PR#105 momentum metrics in PWA: Rotation view, accel badge, slope glyph, confirmed sort, perf-delta row | 2026-06-18 |
| LB-1..5 | Config-driven delta schema (`delta_config.py`), trading-day 5/10/20/50 lookbacks, momentum variants (confirmed, weighted-mid/fast, regime, accel ⊃ INS-4, rank-trend slope), PWA renumber, generate_ai repoint | 2026-06-17 |
| AI-PWA | AI tab improvements (Items 1–8): key signals, delta card, conviction tags, industries structure, relative timestamp, native share, phase history strip, historical date navigation | 2026-06-12 |
| AI-ARCH | AI architecture revamp: `TASK_SPECS`, `index.json` manifest, `gemini-2.5-flash`, incremental completion (PR #38) | 2026-06-11 |
| MON-1 | Workflow logging + monitoring: AI partial completion fix, `ai_run_log.jsonl`, `fetch_log.csv` AI columns, PWA pipeline diamond (PR #35) | 2026-06-11 |
| AI-0 | Server-side AI pipeline: daily briefing + rotation phase + watchlist (PR #25) | 2026-06-10 |
| INS-1 | Sustained Strength / "Evergreen" list (Streamlit + PWA) | 2026-06-10 |
| INS-2 | `rank_agreement` metric in deltas.csv | 2026-06-10 |
| INS-3 | All Green filter + emoji dot matrix | 2026-06-10 |
| PWA-2 | Add `<link rel="apple-touch-icon">` for iOS homescreen icon | 2026-06-10 |
| PWA-3 | Show error on active tab (not just Today) | 2026-06-10 |
| PWA-4 | Dead code cleanup: `fmtPct` forceSign + `moverCard` delta shadowing | 2026-06-10 |
| — | First live scrape: 11 sectors, 144 industries | 2026-06-09 |
| — | End-to-end pipeline verified (collect → deltas → dashboard) | 2026-06-09 |
| — | GitHub Actions cron wired (weekdays 22:00 UTC) | 2026-06-09 |
| — | Scraper fixes: CSS selector, domcontentloaded, TLS, perf_day | 2026-06-09 |
| 1 | Test infrastructure: 50 tests, all green (`pytest tests/ -v`) | 2026-06-09 |
| 2a | `rank_day` metric added to delta schema; existing CSVs auto-migrated | 2026-06-09 |
| 2b | Momentum score NaN fix: all-NaN columns excluded from mean | 2026-06-09 |
| 3a | Rank columns (rank_day/week/month/ytd) in Snapshot tab | 2026-06-09 |
| 3b | CSV export buttons on Snapshot, Top Movers, Momentum tables | 2026-06-09 |
| 3c | Multi-select Time Series (up to 3 groups, color-coded) | 2026-06-09 |
| 4a | `collect()` post-parse row-count guard (RuntimeError on 0 rows) | 2026-06-09 |
| 4b | Unknown Finviz column names logged as summary line to stderr | 2026-06-09 |
| 4c | `fetch_html()` runtime timing logged | 2026-06-09 |
| 5a | GitHub Actions job timeout: `timeout-minutes: 30` | 2026-06-09 |
| 5b | GitHub Actions post-collect row-count verification step | 2026-06-09 |
| 6a | Heatmap tab (RdYlGn; gated behind ≥7 day data guard) | 2026-06-09 |
| T7 | Test: `collect()` row-count guard — 56 tests, all green | 2026-06-09 |
| T8 | GitHub Actions CI workflow (`tests.yml`) — YAML correct; see note below | 2026-06-09 |
| T9 | Test: `ensure_deltas_csv` all 3 paths | 2026-06-09 |
| R1 | `.claude/rules/commit-discipline.md` — commit sizing, test requirements, handoff checklist | 2026-06-09 |
| M1 | Mobile iPhone PWA (`docs/`): Today / Movers / Momentum tabs; GitHub Pages; Add to Home Screen | 2026-06-09 |

---

## Effort Key
| Label | Time |
|-------|------|
| S | < 1h |
| M | 1–2h |
| L | 2–4h |

---

## Next Milestones

| Date | Event |
|------|-------|
| ~2026-06-16 | 7d deltas available — Heatmap + Top Movers light up |
| ~2026-06-23 | 14d deltas available |
| ~2026-07-09 | 30d deltas available — full picture |

After 7d data arrives: consider adding `rank_day_delta_7d` to the delta schema (same pattern as `rank_week_delta_7d`).

---

## Verification Checklist

- [x] `pytest tests/ -v` — 56 tests pass
- [x] `python scripts/compute_deltas.py` — migrates existing CSVs, `rank_day` in output
- [x] Dashboard: rank cols in Snapshot, download buttons, Time Series multiselect, Heatmap "need 7 days" message
- [x] GH Actions `collect.yml` — timeout + row-count step present
- [x] Push branch; draft PR #3 created
- [x] T7: `collect()` guard tests added (TestCollectRowCountGuard)
- [x] T8: `tests.yml` CI workflow YAML added and correct (runner allocation issue is account-level)
- [x] T9: `ensure_deltas_csv` path tests added (TestEnsureDeltasCsv)
