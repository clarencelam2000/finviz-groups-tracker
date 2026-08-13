-- WS5 phase 2 — held-tickers quote feed (Cloudflare D1: finviz-positions).
-- Design: planning/trade-lifecycle-engine.md § 5 / § 5a; ADR-012 § 10 / § 11; issues #312, #297.
--
-- APPEND-ONLY across trading days — one row per (ticker, trade_date), NEVER an upsert-latest that
-- forgets yesterday's bar. Keeping the full daily-bar series is the whole point: (a) phase-3
-- advance() gets its 2-close lookback for free, and (b) OFF-PICKS held names accumulate a bar
-- history that the committed data/*.csv files never capture. "The one thing you can never backfill"
-- (#297): you cannot re-capture a bar you didn't save. Within a single (ticker, trade_date) a
-- same-day re-run is idempotent last-write-wins (the ingest does ON CONFLICT DO UPDATE) — same
-- convention as collect.py's per-date last-write-wins, so an EOD re-run cleanly corrects an earlier
-- intraday capture without creating a duplicate day.
--
-- NO user_id here, deliberately: a daily bar for a symbol is PUBLIC market data, not private state.
-- Only the SELECTION of which tickers to fetch (the union of open positions) derives from private
-- data, and that happens at query time (SELECT DISTINCT ticker FROM positions ...), never in the
-- row. (Design § 5.) Keeping this table user-less also means the two feeds stay cleanly separable
-- (§ 5a) and a future second user shares the same market-data rows for free.
--
-- Column strategy (#297 "store the full scrape column set", implemented pragmatically):
--   * Typed columns for the unambiguous price / ATR / volume / earnings fields the phase-3 engine
--     and the PWA read directly — queryable without JSON extraction, correctly typed for math.
--   * `raw` TEXT holds the COMPLETE scraped label->value map (all ~84 Finviz screener columns:
--     SMA %-distances, 52W hi/lo, perf_*, fundamentals, RSI, beta, ...) verbatim as JSON. THIS is
--     the actual "never lose a bar" guarantee — nothing scraped is dropped. A future rule variant
--     that needs, say, RSI or SMA200 reads it out of `raw`, or a later migration promotes that key
--     to a typed column — neither needs a re-scrape, which is impossible after the day has passed.
--
--   NOTE for phase 3 (do not silently mis-read): Finviz's SMA20/SMA50/SMA200 columns are the
--   PERCENT DISTANCE of price from that moving average, NOT the MA price level. advance()'s
--   "close below the 20MA" test needs the LEVEL, recoverable as  close / (1 + pct/100). This is
--   deliberately NOT frozen into a typed column here, so phase 2 does not hard-code a representation
--   phase 3 may want to model differently; the raw %-distance is preserved verbatim in `raw`.
--   See § 5 and § 12.

CREATE TABLE IF NOT EXISTS ticker_quotes (
  ticker            TEXT NOT NULL,
  trade_date        TEXT NOT NULL,          -- ET trading date (YYYY-MM-DD) the bar settles on
  prev_close        REAL,
  open              REAL,
  high              REAL,
  low               REAL,
  close             REAL,                   -- Finviz "Price" (the settled EOD close on this feed)
  change_pct        REAL,                   -- Finviz "Change" (% day move)
  atr               REAL,                   -- absolute ATR (Finviz col 49)
  volume            REAL,
  days_to_earnings  INTEGER,                -- nullable; phase 2 leaves NULL, phase 3 derives from raw "Earnings"
  raw               TEXT NOT NULL DEFAULT '{}',  -- COMPLETE scrape: {finviz_label: value, ...} as JSON
  collected_at      TEXT NOT NULL,          -- ISO-8601 UTC wall-clock of the scrape run
  PRIMARY KEY (ticker, trade_date)          -- market data is not user-scoped; no user_id in the key
);

-- The engine reads a ticker's trailing bars in date order; the feed writes a whole date at once.
CREATE INDEX IF NOT EXISTS idx_quotes_ticker_date ON ticker_quotes(ticker, trade_date);
CREATE INDEX IF NOT EXISTS idx_quotes_date ON ticker_quotes(trade_date);
