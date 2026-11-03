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
CREATE TABLE IF NOT EXISTS mobile_host_sync(
  singleton_id INTEGER PRIMARY KEY CHECK(singleton_id=1),
  account_id TEXT NOT NULL DEFAULT '',
  host_id TEXT NOT NULL UNIQUE, snapshot_key TEXT NOT NULL, writer_token TEXT NOT NULL,
  created_at TEXT NOT NULL, relay_registered_at TEXT NOT NULL DEFAULT '',
  relay_last_synced_at TEXT NOT NULL DEFAULT '', relay_last_snapshot_version INTEGER NOT NULL DEFAULT 0,
  relay_last_snapshot_hash TEXT NOT NULL DEFAULT '', relay_last_error TEXT NOT NULL DEFAULT '',
  relay_push_state_json TEXT NOT NULL DEFAULT '', relay_device_count INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS mobile_host_retirements(
  host_id TEXT PRIMARY KEY, writer_token TEXT NOT NULL,
  created_at TEXT NOT NULL, last_attempt_at TEXT NOT NULL DEFAULT '', last_error TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS mobile_command_receipts(
  command_id TEXT PRIMARY KEY, device_id TEXT NOT NULL, sequence INTEGER NOT NULL,
  issued_at TEXT NOT NULL, expires_at TEXT NOT NULL, action TEXT NOT NULL,
  target_id TEXT NOT NULL, action_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'processing', result_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL, completed_at TEXT NOT NULL DEFAULT '',
  UNIQUE(device_id,sequence));
CREATE TABLE IF NOT EXISTS mobile_command_result_outbox(
  command_id TEXT PRIMARY KEY, result_json TEXT NOT NULL,
  created_at TEXT NOT NULL, uploaded_at TEXT NOT NULL DEFAULT '');
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
