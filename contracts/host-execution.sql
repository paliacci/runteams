-- Host execution/security/cache tables only. No saved business data.
CREATE TABLE IF NOT EXISTS credential_entries(
  name TEXT PRIMARY KEY,
  pos INTEGER NOT NULL DEFAULT 0,
  source_name TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS model_channels(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
  provider TEXT NOT NULL DEFAULT 'claude-code', executable TEXT NOT NULL DEFAULT '',
  config_dir TEXT NOT NULL DEFAULT '', default_model TEXT NOT NULL DEFAULT '',
  default_effort TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1, is_default INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS local_asset_grants(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL, path TEXT NOT NULL,
  dev INTEGER NOT NULL DEFAULT 0, ino INTEGER NOT NULL DEFAULT 0,
  is_git INTEGER NOT NULL DEFAULT 0, git_root_commit TEXT NOT NULL DEFAULT '',
  excluded_json TEXT NOT NULL DEFAULT '[]',
  revoked_at TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_used_at TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS chat_runtime_links(
 account_id TEXT NOT NULL, chat_id INTEGER NOT NULL, generation INTEGER NOT NULL,
 provider TEXT NOT NULL, thread_id TEXT NOT NULL,
 PRIMARY KEY(account_id,chat_id));
