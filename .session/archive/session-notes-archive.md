# Session Notes Archive

> Older session entries moved here periodically by a human reviewer. Not auto-loaded.
> Newest entries at the top.

---

## 2026-06-24 — Sector→industry hierarchy foundation complete

`data/finviz_sector_industry_map.json` merged (PR #171) — 11 sectors, 144 industries, 100% match against live snapshots. Full 22-feature hierarchy roadmap written to `planning/PLAN_sector_industry_hierarchy.md`. Sprint board updated with HIR-* tasks. Two items immediately unblocked: TASK-6B (Streamlit sidebar filter) and INS-7 (Sector Breadth).

---

## 2026-06-24 — Phase-1.5 spike: selector policy locked with VP

**Key findings:**
- All-green count: 21–46/day (self-shrinks on weakness — correct).
- `momentum_accel` is all NaN on all 10 dates (needs 11 sessions; unlocks ~Jun 25).
- `rs_score > 0.5` floor on `emerging` essential — drops qualifying count from 39–50 → 3–4 but removes noise.
- Sustained_strength most stable (Jaccard 0.691 avg); momentum_confirmed more responsive (0.605). Hybrid (8+2) captures both.

**Decisions locked (VP 2026-06-24):**
- Leaders metric: 8 by sustained_strength + 2 freshness fills by momentum_confirmed
- Anti-flash floor: Top 40% cross-sectional percentile by `momentum_score`
- Slot split: 10/4/3/3 (cap=20)

**Docs updated:** `planning/stock-picks-from-leading-groups.md` status block + Spike section.

**Not committed (Phase-1, paused per VP):** `scripts/probe_picks.py` + `.github/workflows/probe_picks.yml`.

---

## 2026-06-23 — Cron schedule adjustment for market hours

Updated `worker-cron/wrangler.toml` cron times to better align with US market hours. Key finding: Cloudflare Cron does NOT support timezone/DST. Manual adjustment required on Nov 2, 2026 (EDT→EST) and Mar 9, 2027 (EST→EDT). PR #168 opened.

---

## 2026-06-21 — Start Here onboarding intro

Implemented `planning/start-here-onboarding.md` in full. WELCOME constant (5-slide array), "Start Here" hub section, full-screen carousel, `fvt_intro_seen_v1` localStorage key. Anti-drift tests in `tests/test_pwa_intro.py`. `knowledge/product-intro-copy.md` canonical copy source. Release v2026.06.21, sw.js CACHE → v19.

---

## 2026-06-20 — ETF lookup overrides (ETF-1)

PR #137 merged. `data/etf_overrides.csv` — 31 curated ETFs. `build_taxonomy.js` extended to emit `etf_overrides.json`. `lookupEtf()` in `taxonomy.js`. PWA `renderLookup()` updated with thematic/sector/diversified card variants. ADR-005 written. releases.json 2026.06.20, SW cache v17→v18.

---

## 2026-06-20 — Lookup search enhancements (Ideas 1–7)

Ideas 1–4 (PR #131 merged): local group name search, typeahead dropdown, expanded group card, SW cache v15→v16.
Ideas 5–7 (PR #134): recent searches, pinned favorites, empty-state momentum chips, synonym map, fuzzy "did you mean". SW cache v17→v18, releases.json 2026.06.21.

---

## 2026-06-19 — Cloudflare Cron Scheduler live

PR #122 merged. Worker `finviz-cron-dispatcher` deployed. All three weekday cron triggers active. Live validation: end-to-end POST returned HTTP 204, `collect.yml` run #38 launched. KV namespace connected. Phase 3 (edge-scrape spike) deferred.

---

## 2026-06-19 — Guide & What's New hub

PWA header ℹ️ hub (slide-up sheet) with What's New (`docs/releases.json`) + Guide (11-metric glossary). Unseen dot + one-time banner. Contextual "why this matters →" deep-links. Dashboard sidebar mirrors both. SW cache v9→v10. `tests/test_guide_releases.py` + TestPWAHub Playwright class green.

---

## 2026-06-17 — Lookback config + momentum variants

`scripts/delta_config.py` single source of truth — `LOOKBACK_WINDOWS=[5,10,20,50]`. Trading-day lookbacks via `find_trading_date_back` (position-based, gap-tolerant). Six momentum variants added. PWA minimal window renumber. `generate_ai.py` repointed. 159 tests pass. LB-FF1 tracked in SPRINT (PWA full-dynamic windows).

---

## 2026-06-16 — Date/timezone hardening + stale-delta fix

Real bug: daily cron fired Sat/Sun, re-scraping stale close. `trading_date()` rolled Monday-pre-9am to Sunday. Stale-delta `existing_keys` guard locked first-run ranks. Fixes: `existing_keys` removed (last-write-wins), `trading_date()` rolls weekends + Monday-pre-open to preceding Friday, crons changed to weekday-only. Phantom weekend rows purged (Jun 13/14). CLAUDE.md Automation section updated.

---

## 2026-06-16 — Lookup tab improvements Phase 1

Six Phase 1 slices in `docs/index.html`: rank sparkline, conviction info (Rank Floor + Sustained/Consistent chip), breadth strip, RS spread chips, moat score, export button. Each its own commit with paired SPRINT + plan-doc updates.
