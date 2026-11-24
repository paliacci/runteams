CREATE TABLE chats(
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL DEFAULT '新对话',
  title_source TEXT NOT NULL DEFAULT 'pending',
  kind TEXT NOT NULL DEFAULT 'general' CHECK(kind IN ('general','employee_design','automation')), context_json TEXT NOT NULL DEFAULT '{}',
  draft_json TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'active',
  channel_id INTEGER, model TEXT NOT NULL DEFAULT '', reasoning_effort TEXT NOT NULL DEFAULT '',
  scope_pipeline_id INTEGER, extensions_enabled INTEGER NOT NULL DEFAULT 0,
  subject_type TEXT NOT NULL DEFAULT 'workspace', employee_id INTEGER,
  employee_release_id INTEGER, employee_release_digest TEXT NOT NULL DEFAULT '',
  scope_type TEXT NOT NULL DEFAULT 'global', scope_run_id INTEGER,
  runtime_provider TEXT NOT NULL DEFAULT '', runtime_generation INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);

CREATE TABLE chat_messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
  role TEXT NOT NULL, text TEXT NOT NULL DEFAULT '', applied TEXT,
  attachments TEXT NOT NULL DEFAULT '[]', capabilities TEXT NOT NULL DEFAULT '[]',
  metadata TEXT NOT NULL DEFAULT '{}', ts TEXT NOT NULL);
