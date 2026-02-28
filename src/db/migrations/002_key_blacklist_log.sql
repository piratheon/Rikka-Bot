-- Create key_blacklist_log table
BEGIN TRANSACTION;

CREATE TABLE IF NOT EXISTS key_blacklist_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  api_key_id INTEGER NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
  reason TEXT,
  blacklisted_at TEXT DEFAULT (datetime('now')),
  unblacklisted_at TEXT
);

COMMIT;
