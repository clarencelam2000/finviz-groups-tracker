-- WS5 §8b follow-up (morning subtabs + soft-remove watchlist, issue tracked in SPRINT.md).
--
-- `removed_at` mirrors `expired_at`'s shape for a new terminal status, 'removed': the owner
-- explicitly removed a watch ticker from the Morning tab (as opposed to it running out its TTL).
-- A 'removed' row is EXCLUDED from watchlistTickers()'s "status = 'active'" filter (src/watchlist.js),
-- so heldTickers()'s union stops scraping it on the very next held-feed run — same mechanism that
-- already excludes 'expired' rows, no new filter needed there. The row survives (status='removed')
-- so the PWA can still render it in a collapsed "Recently removed" bin — same convention as the
-- existing "Expired" bin — until tickWatchlist() purges it after WATCHLIST_PURGE_DAYS, mirroring
-- the existing expired-row purge.
ALTER TABLE watchlist ADD COLUMN removed_at TEXT;

-- Applied OUT-OF-BAND like every prior migration — `wrangler deploy` does NOT run migrations:
--   wrangler d1 execute finviz-positions --remote --file migrations/0007_watchlist_removed.sql
