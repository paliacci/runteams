-- Durable personal data on this device. Never authorize cloud business actions.
CREATE TABLE IF NOT EXISTS device_chat_index(
 chat_id INTEGER PRIMARY KEY,
 identity TEXT NOT NULL UNIQUE,
 imported_at TEXT NOT NULL,
 deleted INTEGER NOT NULL DEFAULT 0 CHECK(deleted IN (0,1)));
CREATE TABLE IF NOT EXISTS device_settings(
 key TEXT PRIMARY KEY,
 value TEXT NOT NULL CHECK(json_valid(value)));
CREATE TABLE IF NOT EXISTS device_activity_streams(
 ref TEXT PRIMARY KEY,
 scope TEXT NOT NULL,
 domain TEXT NOT NULL,
 run_id INTEGER NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(scope,domain,run_id));
CREATE TABLE IF NOT EXISTS device_activity_events(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 stream_ref TEXT NOT NULL REFERENCES device_activity_streams(ref) ON DELETE CASCADE,
 ts TEXT NOT NULL,
 content_json TEXT NOT NULL CHECK(json_valid(content_json)));
CREATE INDEX IF NOT EXISTS device_activity_stream_events ON device_activity_events(stream_ref,id);
