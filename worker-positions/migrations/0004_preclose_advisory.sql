-- WS5-8 pre-close advisory (issue: file when this lands). Provisional, transient, rebuilt daily.
-- One row per (user_id, trade_date): the whole pre-close read for that user that day, upserted so a
-- self-healing 15:40 re-dispatch is last-write-wins. Deliberately DISJOINT from positions/ticker_quotes
-- (the 17:30 sweep is the sole writer of those) — this table holds only the COMPUTED advisory, never a
-- bar and never position state. Applied OUT-OF-BAND like 0001-0003 (wrangler deploy does not run it);
-- test/helpers/d1.js MIGRATIONS array runs it in tests.
CREATE TABLE IF NOT EXISTS preclose_advisory (
  user_id     TEXT NOT NULL,
  trade_date  TEXT NOT NULL,   -- ET trading date of the read (YYYY-MM-DD)
  ran_at      TEXT NOT NULL,   -- ISO-8601 UTC of the compute
  n_checked   INTEGER NOT NULL,-- open/managing positions evaluated
  n_flagged   INTEGER NOT NULL,-- items carrying a signal
  items       TEXT NOT NULL,   -- JSON array; see item shape in preclose.js
  PRIMARY KEY (user_id, trade_date)
);
