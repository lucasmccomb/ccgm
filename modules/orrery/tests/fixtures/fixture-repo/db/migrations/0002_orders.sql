CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY,
  charge_id TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now'))
);
