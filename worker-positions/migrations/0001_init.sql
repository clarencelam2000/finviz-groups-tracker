-- WS5 phase 1 — trade-lifecycle positions store (Cloudflare D1: finviz-positions).
-- Design: planning/trade-lifecycle-engine.md § 5; ADR-012.
--
-- Phase 1 creates the two USER-STATE tables only:
--   positions        — the typed, queryable spine (one row per LOT, § 3a)
--   position_events  — append-only audit/replay ledger (corrections are NEW events, never edits)
-- The market-data feed table `ticker_quotes` is intentionally NOT created here: it is written by
-- the phase-2 held-tickers feed and must store the FULL Finviz scrape column set (issue #297,
-- "un-stored bar history is the one thing you can never backfill"). Creating it half-width now
-- would just be rebuilt then, and phase 1 writes no bars, so there is no history to lose by waiting.
--
-- Tenant isolation is APP-LAYER only (D1/SQLite has no row-level security): user_id is on every
-- row and every query is scoped by it. The Worker derives user_id from the auth token and NEVER
-- trusts a client-supplied user_id. At user = 1 this is a constant, but the column exists from day
-- one so user > 1 is a policy change, not a migration (ADR-012).

CREATE TABLE IF NOT EXISTS positions (
  trade_id             TEXT PRIMARY KEY,           -- server-generated UUID; never client-supplied
  user_id              TEXT NOT NULL,              -- scoped on EVERY query; app-layer isolation
  ticker               TEXT NOT NULL,
  state                TEXT NOT NULL,              -- watching|open|managing|closing|closed
  -- frozen-at-entry context (immutable after Open; § 3)
  entry_date           TEXT,
  entry_price          REAL,
  initial_stop         REAL,
  stop_basis           TEXT,                       -- prior_day_low|todays_low|20ma|50ma|manual
  initial_qty          REAL,
  -- exit-signal fields (set on Managing->Closing; modeled, awaiting user confirm; § 4/§ 7)
  expected_exit_price  REAL,
  exit_signal_date     TEXT,
  exit_reason          TEXT,                       -- stop_hit|gap_down_below_stop|close_below_50ma|
                                                   --   severe_breakdown|two_close_below_20ma|manual_close
  -- engine state (advanced by phase-3 advance(); initialized sanely at creation)
  profit_floor         REAL,                       -- monotonic non-decreasing (§ 4 invariant)
  current_stop         REAL,
  trail_basis          TEXT,                       -- 20ma|50ma
  remaining_qty        REAL,
  caution_flag         INTEGER NOT NULL DEFAULT 0, -- 1 after a single close below the 20MA
  highest_trim_atr     INTEGER NOT NULL DEFAULT 0, -- trim ledger (idempotent scale-outs)
  days_to_earnings     INTEGER,
  -- closed-state fields (§ 4/§ 7)
  opened_at            TEXT,
  closed_at            TEXT,
  exit_price           REAL,                       -- the user's CONFIRMED fill, never the modeled price
  confirmation_status  TEXT NOT NULL DEFAULT 'unconfirmed', -- unconfirmed|confirmed|auto
  last_advanced_date   TEXT,                       -- daily-run idempotency guard
  -- JSON bag: notes, tags, UI state, widen_enabled, source ('picks'|'manual'),
  --   group_id (scale-in lots, § 3a), per-position rule overrides (§ 14)
  meta                 TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_positions_user_state ON positions(user_id, state);
CREATE INDEX IF NOT EXISTS idx_positions_user_ticker ON positions(user_id, ticker);

CREATE TABLE IF NOT EXISTS position_events (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  trade_id    TEXT NOT NULL,
  user_id     TEXT NOT NULL,
  ts          TEXT NOT NULL,                       -- ISO-8601 UTC wall-clock of the write
  trade_date  TEXT NOT NULL,                       -- ET trading date the event belongs to
  -- append-only: corrections are NEW events, never destructive edits (§ 7 edit/undo)
  event_type  TEXT NOT NULL,                       -- entered|stop_moved|partial_exit|caution|
                                                   --   exit_signal|closed|exit_corrected|reopened|note
  payload     TEXT NOT NULL DEFAULT '{}'           -- JSON: qty, at_atr, price, reason, message, ...
);
CREATE INDEX IF NOT EXISTS idx_events_trade ON position_events(trade_id, ts);
CREATE INDEX IF NOT EXISTS idx_events_user ON position_events(user_id, ts);
