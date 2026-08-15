# Build brief — Personal watchlist (WS5 §8b, issue #319)

> **Status:** design locked, ready to build. This doc is a **cold-start brief** — a fresh eng
> should be able to execute from this + the read list without the design-session chat.
> **Design authority:** this doc + the two committed mocks. Where this doc and older notes in
> `planning/trade-lifecycle-engine.md` §8b disagree, **this doc wins** (§8b was the pre-design
> think-big; several of its assumptions were revised — see "What changed from §8b").
>
> **Mocks (committed + published):**
> - `planning/mocks/ws5-watchlist-directions.html` → the **final watch card v2** (authoritative UI).
> - `planning/mocks/ws5-watchlist-surface.html` → the earlier three-surface mock (context only; the card styling there is superseded by v2).

---

## 1. What the feature is

Let the owner add an arbitrary ticker (pick or not) to a **personal watchlist**. It rides the next
**N morning scrapes** and shows a real **Morning status card** — a pre-position radar. One tap
("I took it") **graduates** it to a position via the already-shipped §8a manual-entry path.

**The load-bearing principle:** a watch item is **not a trade ticket**. A stop/size are
position-management concepts, born at entry — so a watch item carries **no stop, no size, ever**.
It carries a ticker and an **optional level of interest**. The full ticket appears only at graduation.

---

## 2. Locked design decisions (do not re-litigate)

- **Privacy posture = (a) "anonymous-public".** Watchlist **membership + levels + TTL live private in
  D1** (`worker-positions`). Only an **anonymous market-data quote/status row** for the ticker rides
  the **public** morning store — no size, no position, no level. Owner accepted the weak signal
  ("which ticker was scraped this morning"). A **fully-private morning store is a tracked follow-up**
  (SPRINT item), not v1.
- **Trigger source = user's own setup ("carry your own"), auto system-read alongside.** The user
  optionally supplies a level of interest; the system read (breakout vs prior high) always shows.
- **ONE status engine, no drift.** The system read MUST run through the existing Python
  `scripts/pick_status.py::compute_pick_status` — **never a re-implementation** (e.g. in the worker).
  Watch tickers are unioned into `scripts/collect_morning.py`'s scrape universe so they hit the same
  engine. Adding a state to `pick_status.py` lights it for picks **and** watch cards automatically.
- **N (TTL) = 10 trading mornings.** Renew resets to 10. Expired entries move to a collapsed bin,
  auto-purge after **14 calendar days**.
- **Your-level wording = "direction + quiet met"** (mock §02 option a): show `above 144.00` + a quiet
  green `now above` (grey `now below` otherwise). **No "crossed", no "approaching".** Store only the
  direction the user was watching; they read the price themselves.
- **Block header = none** (mock §03 option a): the price-read rows are labeled like the current
  Morning card (`Trigger (prior high) / Now / ATR from day low`). The word "System" is **banned** from
  the copy.
- **Reclaim = a real shared-engine state** using **both today's low and yesterday's low**:
  `reclaim(ref) = price > ref AND (today_low < ref OR prior_low < ref)`, where `ref` ∈ {prior low,
  20MA, 50MA}. Mirror of `failed_breakout`.
- **Gauge = on by default, collapsible.** Prior levels labeled on **top** (prior low / prior high),
  today's open + day-low on the **bottom**, user level in violet, price = the dot.
- **Level types** (set at add time): `above` price · `below` price · `reclaim_20ma` · `reclaim_50ma`.
- **Overflow kebab (⋯)** on a card = **Renew · Edit level · Remove** (nothing else).
- **Manage surface = Positions tab** (a collapsible sibling to the shipped "Log a position manually"
  expander). **View surface = Morning tab** ("Your watchlist" section). A **quick-add** button atop the
  Morning section deep-links to the Positions add collapsible.

### What changed from `trade-lifecycle-engine.md` §8b (so the next eng isn't confused)
- §8b said "force-include into the **public picks** scrape." **Rejected.** The picks selector is
  **group-level**, has no ticker force-include seam, and would make the ticker a full public pick.
  Instead: **union into the morning + held feeds**, keep membership private in D1.
- §8b said watch "rides Morning **for free**." **Not quite** — `collect_morning` narrows to the
  Focus top-100, so watch tickers must be **explicitly unioned** into the universe.
- §8b framed watch-add and §8a manual-entry as the **same form**. **Revised:** the add path is a
  **one-field radar-add** (ticker + optional level, no stop/size). The §8a ticket is reused **only at
  graduation**.

---

## 3. Architecture & data flow

```
ADD (PWA, owner-bearer)
   POST /watchlist {ticker, level_type?, level_value?}  ──►  D1 watchlist (private): membership + level + sessions_remaining=10

HELD FEED (EOD 17:30 ET, collect_held.py)   [already shipped; just widen the set]
   heldTickers = positions(open/managing/closing)  ∪  watchlist(active)
   ──► scrapes each ticker ──► ticker_quotes (private D1, append-only, full 84-col `raw` incl. SMAs)
   → gives watch tickers their prior-day High/Low/ATR + MAs (the reference for the system read & reclaim)

MORNING JOB (10:05 ET, collect_morning.py)   [union watch tickers in]
   1. GET /watchlist-tickers (service token) → [{ticker, level_type, level_value,
      prior_high, prior_low, atr}]  (worker joins watchlist→latest ticker_quotes bar)
   2. union those tickers into the scrape universe (they won't pass the Focus filter)
   3. scrape today's OHLC (existing fetch_ticker_quotes, `morning` block)
   4. SYSTEM READ: same compute_pick_status(trigger=prior_high, stop=prior_low, today OHLC)
      → write anonymous status rows to the PUBLIC morning store (tagged list_category='watchlist')
   5. POST /watchlist/tick (service token) → decrement sessions_remaining (idempotent per ET date),
      expire at 0, purge expired > 14 calendar days

VIEW (PWA, Morning tab)
   public morning-status rows (system read)  +  GET /watchlist (owner-bearer: private levels + TTL + ref)
   ──► merge client-side ──► render "Your watchlist" cards.
   YOUR-LEVEL read is computed CLIENT-SIDE (keeps the level value out of the public store).

GRADUATE (PWA)
   "I took it" → existing §8a ticket, prefilled {ticker, entry hint=level}, stop/size BLANK+required
   → POST /positions (meta.source='watchlist')  → DELETE the watch entry.
```

**Why watch tickers ride BOTH feeds:** the held feed (EOD) supplies the **accurate prior-day
High/Low/ATR + MAs** (the morning `morning` block only has *today's* H/L and Prev Close — no prior-day
high, no SMA). The morning feed supplies the **intraday 10:05 read**. A freshly-added ticker has no
`ticker_quotes` bar until the first EOD run → its first morning card is the **"adding — first check
tomorrow AM"** state. Expected.

---

## 4. Component-by-component spec

### 4a. D1 — `worker-positions/migrations/0003_watchlist.sql`
```sql
CREATE TABLE watchlist (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id            TEXT NOT NULL,
  ticker             TEXT NOT NULL,
  level_type         TEXT,            -- 'above' | 'below' | 'reclaim_20ma' | 'reclaim_50ma' | NULL
  level_value        REAL,            -- price for above/below; NULL for MA-reclaim / no-level
  sessions_remaining INTEGER NOT NULL,-- TTL counter; starts at WATCHLIST_TTL_SESSIONS (10)
  status             TEXT NOT NULL DEFAULT 'active',  -- 'active' | 'expired'
  created_at         TEXT NOT NULL,   -- ISO UTC
  updated_at         TEXT,
  expired_at         TEXT,            -- set when sessions_remaining hits 0
  meta               TEXT,            -- JSON bag
  UNIQUE(user_id, ticker)
);
CREATE INDEX idx_watchlist_user_status ON watchlist(user_id, status);
```
Applied out-of-band (like 0001/0002 — `wrangler deploy` does not run migrations). Note in the P1 PR.

### 4b. Worker routes (`worker-positions/src/`)
Add to `src/index.js` (mirror the existing auth gating — see route table in `worker-positions/CLAUDE.md`):

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/watchlist` | owner bearer | add `{ticker, level_type?, level_value?}`; sessions_remaining=10, status='active'; upsert on (user,ticker) |
| GET | `/watchlist` | owner bearer | list user's entries (active+expired) + join latest `ticker_quotes` → `prior_high/prior_low/atr` + current `ref` (20/50MA recovered from `raw`) for rendering |
| PATCH | `/watchlist/:id` | owner bearer | edit level, or **renew** (reset sessions_remaining=10, status='active', clear expired_at) |
| DELETE | `/watchlist/:id` | owner bearer | remove (also called on graduation) |
| GET | `/watchlist-tickers` | **service token** | for `collect_morning`: active tickers + level + `prior_high/prior_low/atr` from latest bar |
| POST | `/watchlist/tick` | **service token** | idempotent-per-ET-date: decrement all active `sessions_remaining`; status→'expired' at 0; purge `expired` older than 14 calendar days |

- Put owner routes **below** the owner-auth gate; the two service routes **above** it (same structure
  as `/held-tickers` + `/ingest/quotes`). Cross-auth isolation must be test-covered (owner token
  rejected on service routes and vice-versa) — copy the existing pattern.
- `src/quotes.js::heldTickers` → **union** `SELECT DISTINCT ticker FROM watchlist WHERE status='active'`
  (still user-less; market data). Add a `watchlistTickers(db)` helper.
- New pure module `src/watchlist.js` (validation + queries), unit-tested like `quotes.js`.
- `/watchlist/tick` idempotency: store `last_tick_date` (ET) in D1 or a `meta` row; a second call the
  same ET date is a no-op (guards double-runs / the GitHub backstop).

**MA-recovery reminder:** Finviz SMA in `ticker_quotes.raw` are **%-distance, not price**. Recover the
level via `close/(1 + pct/100)` — the exact math already in `worker-positions/src/advance.js::normalizeBar`.
Reuse it; don't re-derive.

### 4c. Engine — `scripts/pick_status.py`
Add the **reclaim** state without changing existing pick behavior:
- New helper `compute_reclaim(price, today_low, prior_low, ref)` → bool:
  `price > ref and (today_low < ref or prior_low < ref)`.
- Integrate into `compute_pick_status` via an **optional** `ref=None` (and `prior_low` already present
  as `stop`): when `ref` is None (all current pick callers), behavior is **byte-identical**. When a
  watch caller passes `ref`, `reclaim` is evaluated in the precedence table (place it above
  `setting_up`, below the breakout states — confirm exact precedence in the ADR-013 table and add a
  test pinning it).
- To later light reclaim on **picks** too, pass `prior_low` (or the 50MA) as `ref` in the pick path —
  leave that opt-in; note it, don't force it.
- Tests: `tests/test_pick_status.py` — reclaim true/false at boundaries, both-lows paths, ref=None
  no-op regression.

### 4d. Morning job — `scripts/collect_morning.py`
- After building the Focus universe, **union** the watchlist tickers from `GET /watchlist-tickers`
  (new service call; reuse `collect_held.py`'s `_authed_request` UA + token pattern — see
  `POSITIONS_WORKER_URL`/`POSITIONS_INGEST_TOKEN` env).
- Build `pick_levels`-shaped dicts for watch tickers from the returned `prior_high/prior_low/atr`
  (NOT from `picks_latest` — they aren't picks). Tag `list_category='watchlist'`.
- Run the **same** `build_status_rows` / `compute_pick_status`. For watch rows, also pass `ref`
  (prior_low and/or the MA) so `reclaim` can fire.
- Write watch status rows into the existing public morning store (`data/picks/sessions/morning*.csv`),
  distinguished by `list_category='watchlist'`. **Do NOT write the user's level value** to the public
  store (privacy) — the your-level read is rendered client-side from the private `GET /watchlist`.
- After a successful run, `POST /watchlist/tick`.
- Guards: keep the non-trading-day exit-0 (no tick on closed days — TTL counts trading mornings).
  A `GET /watchlist-tickers` failure should be **non-fatal** (log + proceed with picks-only) so a
  watchlist/worker hiccup never drops the picks morning run.
- Tests: `tests/test_collect_morning.py` — union logic, watch-row building from worker payload,
  level value never written to the store.

### 4e. PWA — `docs/index.html` (+ `docs/sw.js`, `docs/releases.json`, `docs/CLAUDE.md`)
**Manage (Positions tab):** a collapsible `＋ Add to watchlist` **sibling** to the existing
`manualEntry` expander (don't merge them; keep both clearly labeled). Fields: ticker + optional level
(segmented `Above | Below | 20MA | 50MA`; the price input shows only for Above/Below). Submit →
`POST /watchlist`. Copy under the field: *"Saved to your watchlist — it'll show on the Morning tab
each day with a status read, and your level of interest displayed alongside."* Reuse the pos-auth
token (`fv_pos_token`) — writes require sign-in.

**View (Morning tab):** a "Your watchlist" section with a `＋ Watch a ticker` quick-add
(→ `switchTab('positions')` + auto-expand the add collapsible). Cards per the **v2 mock**:
- Header: ticker + optional adornment chip (Coiled/Extended/Overhead — reuse existing
  `computeLaunchReady`) + industry + status pill.
- **Morning read** (no header word): `Trigger (prior high)` / `Now` (+Δ%) / `ATR from day low` rows —
  reuse the current Morning card's exact rows.
- **Your level** block (violet): `above 144.00` + quiet `now above` (green when met, grey otherwise).
  For MA reclaim: `reclaim 50MA (218.40)` + `reclaimed`/quiet. **Computed client-side** from the
  private level + public price (+ ref/lows).
- **Gauge** (on by default, collapsible): prior low/high on top, today open/day-low on bottom, level in
  violet, price = dot.
- **Show chart** top-level one-tap (reuse `tradingViewChartHtml` / the Morning card's chart toggle).
- Footer: `N mornings left` · `▾ Trade ticket` · `I took it →` · `⋯` (Renew/Edit level/Remove).
- Merge: fetch public `morning_latest.csv` rows where `list_category='watchlist'` + `GET /watchlist`
  (private levels/TTL); join by ticker.

**Graduate:** `I took it` opens the shipped §8a ticket prefilled `{ticker, entry hint=level}`, stop/size
**blank + required**; on `POST /positions` success set `meta.source='watchlist'` and `DELETE
/watchlist/:id`. (Nice-to-have: a "held N mornings, triggered [date]" provenance line on the position.)

**Release triplet (same PR as any user-facing `index.html` change):** prepend `docs/releases.json`,
bump `current`, bump `docs/sw.js` CACHE. Update `docs/CLAUDE.md` (new watchlist surface + any display
constants). See root `CLAUDE.md` § Cutting a release.

**Playwright:** new `tests/test_pwa_watchlist.py` → add to the `tests.yml` `--ignore=` list in the
same PR (see `.claude/rules/branch-commit-discipline.md`).

---

## 5. Enum states (what the Morning watchlist can show)

Four independent axes (full gallery in mock §03 of the surface mock / §-axes):
1. **System read** (inherited from `pick_status.py`): `triggered` · `gapped_through` · `failed_breakout`
   · `reclaim` (new) · `setting_up` · `invalidated` (render "Back below low") · `no_quote`.
2. **Your-level overlay** (only if a level set): `above <price>` · `below <price>` · `reclaim_20ma` ·
   `reclaim_50ma` · none. Each shows a quiet met/not-met cue — no "crossed/approaching" text.
3. **Lifecycle/TTL**: adding (first read pending) · active · expiring (1 left) · expired (bin) ·
   graduated (removed).
4. **Section/global**: empty · signed-out (cards viewable, manage prompts sign-in) · stale/non-trading
   day · loading.

---

## 6. Config constants (3-places rule: in-code + README + CLAUDE.md)
- `WATCHLIST_TTL_SESSIONS = 10` (worker-positions).
- `WATCHLIST_PURGE_DAYS = 14` (calendar days an expired entry lingers before purge).
- Document in `worker-positions/README.md` § Configurable parameters + `worker-positions/CLAUDE.md`.

---

## 7. Phasing (each independently shippable; feed is dormant until bars accumulate)
- **P1 — worker/D1:** `0003_watchlist.sql` + CRUD routes + `/watchlist-tickers` + `/watchlist/tick` +
  `heldTickers` union + `src/watchlist.js` + vitest (routes, auth isolation, TTL/tick idempotency,
  purge). No PWA. Auto-deploys via `deploy-workers.yml`.
- **P2 — feed + engine:** `pick_status.py` reclaim + tests; `collect_morning.py` watchlist union +
  reference-level fetch + tick call + tests. (Held feed picks up watch tickers for free once P1's
  `heldTickers` union ships.)
- **P3 — PWA:** Positions add collapsible + Morning "Your watchlist" section + card + gauge +
  graduation wiring + release triplet + Playwright. This is the taste-heavy one — build to the **v2
  mock**; the lead owns final markup review.

P2's live behavior needs a few days of `ticker_quotes` bars to be meaningful (same gate as the rest of
WS5). Surfaces (P3) can ship with the feed still warming.

---

## 8. Testing & guards
- Every `scripts/` change ships a `tests/` change (project rule). `pytest tests/ -q` green before commit.
- Worker: `npm test` in `worker-positions/` (vitest) — routes, cross-auth isolation, tick idempotency,
  purge boundary.
- New Playwright test → `tests.yml --ignore=` list, same PR (else CI `test` job goes red with
  "executable doesn't exist"). Verify locally via the chromium symlink harness
  (`knowledge/investigations/playwright-cloud-session-testing.md`).
- Non-fatal watchlist fetch in `collect_morning` (picks run must survive a worker hiccup).

---

## 9. Read list (in order) for a cold pickup
1. **This doc**, then the **v2 mock** `planning/mocks/ws5-watchlist-directions.html`.
2. `knowledge/decisions/ADR-013-ws3-morning-status.md` — the morning status engine + precedence table.
3. `scripts/pick_status.py` + `scripts/collect_morning.py` — the engine + morning writer (where the
   union goes; `load_pick_levels`, `build_status_rows`, `write_store`).
4. `scripts/collect_held.py` — the held-feed pattern + `_authed_request` (service-token worker call
   from GitHub Actions).
5. `worker-positions/` — `CLAUDE.md` (route table + auth swap-seam), `src/quotes.js` (`heldTickers`),
   `src/index.js` (routing + auth gate), `src/advance.js::normalizeBar` (SMA %→level), `migrations/`.
6. `docs/CLAUDE.md` — PWA display constants, release triplet, Playwright harness; `docs/index.html`
   `manualEntry*` / `renderPositions` (§8a add form to sit beside) + the Morning card renderer to clone.
7. `planning/trade-lifecycle-engine.md` §8a/§8b/§10 — epic context (but see "What changed from §8b").

---

## 10. Deferred / tracked follow-ups
- **Fully-private morning store** (drop the anonymous-public quote row) — SPRINT item; not v1.
- **Multi-day reclaim** (broke down several sessions ago, recovering now) — v1 uses today+yesterday low.
- **Picks opting into `reclaim`** (pass a ref in the pick path) — optional, owner decides.
- **Watch-card adornments** (Focus score / launch-ready chips beyond the one Coiled/Extended chip) —
  kept minimal for v1; richer is a later dial.
- **"held N mornings, triggered [date]" provenance** on graduated positions — nice-to-have.

---

*Epic #264 · issue #319 · design session 2026-08-15 (see session-notes entry of that date).*
