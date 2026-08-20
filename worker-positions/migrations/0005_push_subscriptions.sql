-- WS5-4b push subscriptions (issue #264 epic). Private, user-scoped Web Push endpoints.
-- One row per (user_id, endpoint); re-subscribe upserts the keys. p256dh/auth are captured now even
-- though v1 sends data-less pushes — they are exactly what the future RFC 8291 payload-encryption
-- fast-follow needs, so capturing them means no re-subscribe later. Applied OUT-OF-BAND like 0001-0004.
CREATE TABLE IF NOT EXISTS push_subscriptions (
  id           TEXT NOT NULL PRIMARY KEY,
  user_id      TEXT NOT NULL,
  endpoint     TEXT NOT NULL,
  p256dh       TEXT NOT NULL,          -- client public key (base64url) — for future payload encryption
  auth         TEXT NOT NULL,          -- client auth secret (base64url) — for future payload encryption
  created_at   TEXT NOT NULL,
  last_seen_at TEXT,
  UNIQUE (user_id, endpoint)
);
CREATE INDEX IF NOT EXISTS idx_push_user ON push_subscriptions(user_id);
