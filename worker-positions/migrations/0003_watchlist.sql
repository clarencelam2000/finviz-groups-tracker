-- WS5 §8b — personal watchlist (Cloudflare D1: finviz-positions). Issue #319.
-- Design: planning/watchlist-build-brief-8b.md § 2 / § 4a; worker-positions/CLAUDE.md.
--
-- PRIVACY POSTURE — the opposite of ticker_quotes (migration 0002): membership, level, and TTL are
-- PRIVATE and user-scoped here, deliberately. Only an ANONYMOUS market-data status row for the
-- ticker rides the public morning store (built by scripts/collect_morning.py from the
-- /watchlist-tickers service response, which omits level_value) — no size, no position, no level
-- ever leaves this table's private D1. See build brief § 2 "Locked design decisions".
--
-- `watchlist` — one row per (user, ticker) the owner is watching (not yet a position). No stop, no
-- size, ever — a watch item is not a trade ticket (§1). level_type/level_value are the OPTIONAL
-- "carry your own" trigger the owner set at add time; the system read (breakout vs prior high)
-- always runs regardless of whether a level is set. sessions_remaining is a TTL counter in TRADING
-- MORNINGS (not calendar days), decremented once per ET trading date by POST /watchlist/tick
-- (idempotent — see watchlist_tick_log below). UNIQUE(user_id, ticker): re-adding an existing watch
-- is an UPSERT that renews the TTL and updates the level (src/watchlist.js addWatch), not a second
-- row — mirrors positions' independent-lot stance being the OPPOSITE choice, on purpose: a watch
-- item has no lot/qty concept to make two rows meaningful.
CREATE TABLE IF NOT EXISTS watchlist (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id            TEXT NOT NULL,
  ticker             TEXT NOT NULL,
  level_type         TEXT,            -- 'above'|'below'|'reclaim_20ma'|'reclaim_50ma'|NULL
  level_value        REAL,            -- price for above/below; NULL for MA-reclaim / no-level
  sessions_remaining INTEGER NOT NULL,-- TTL counter; starts at WATCHLIST_TTL_SESSIONS (10)
  status             TEXT NOT NULL DEFAULT 'active',  -- 'active'|'expired'
  created_at         TEXT NOT NULL,   -- ISO UTC
  updated_at         TEXT,
  expired_at         TEXT,            -- set when sessions_remaining hits 0
  meta               TEXT,            -- JSON bag
  UNIQUE(user_id, ticker)
);
CREATE INDEX IF NOT EXISTS idx_watchlist_user_status ON watchlist(user_id, status);

-- `watchlist_tick_log` — idempotency guard for POST /watchlist/tick. One row per ET trading date
-- already ticked; `INSERT OR IGNORE` makes a same-date re-run (a double GitHub Actions dispatch, a
-- manual retry) a true no-op instead of double-decrementing sessions_remaining. Deliberately NOT
-- reusing worker-cron's KV dispatch-guard pattern — this worker has no KV binding, and a dedicated
-- D1 table keeps the guard co-located with the data it protects.
CREATE TABLE IF NOT EXISTS watchlist_tick_log (
  tick_date TEXT PRIMARY KEY          -- ET trading date already ticked; INSERT OR IGNORE guards double-runs
);

-- Applied OUT-OF-BAND like 0001/0002 — `wrangler deploy` does NOT run migrations. Apply manually:
--   wrangler d1 execute finviz-positions --remote --file migrations/0003_watchlist.sql
