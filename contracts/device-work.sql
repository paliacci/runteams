-- Concrete work on the executing computer. No platform authorization or sync queue.
CREATE TABLE device_work_scope(
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  binding_json TEXT NOT NULL CHECK(json_valid(binding_json)),
  data_epoch TEXT NOT NULL);

-- Immutable copies of the actual assets used by work, not editable definitions.
CREATE TABLE employee_releases(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  employee_id INTEGER NOT NULL,
  version INTEGER NOT NULL CHECK(version>0),
  digest TEXT NOT NULL,
  snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json)),
  source_ref_json TEXT NOT NULL CHECK(json_valid(source_ref_json)),
  created_at TEXT NOT NULL,
  UNIQUE(source_ref_json));
CREATE TRIGGER device_work_frozen_release BEFORE UPDATE ON employee_releases BEGIN
  SELECT RAISE(ABORT, 'Work release snapshots are immutable');
END;

CREATE TABLE tasks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pipeline_id INTEGER, employee_id INTEGER, employee_reference TEXT CHECK(employee_reference IS NULL OR json_valid(employee_reference)), start_column_key TEXT,
  opportunity_key TEXT, title TEXT NOT NULL,
  payload_json TEXT NOT NULL CHECK(json_valid(payload_json)), state TEXT NOT NULL,
  pipeline_snapshot_json TEXT CHECK(pipeline_snapshot_json IS NULL OR json_valid(pipeline_snapshot_json)),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, trashed_at TEXT,
  CHECK ((pipeline_id IS NOT NULL) + (employee_id IS NOT NULL) + (employee_reference IS NOT NULL) = 1));
CREATE UNIQUE INDEX device_work_employee_opportunity ON tasks(employee_id,opportunity_key)
  WHERE employee_id IS NOT NULL AND opportunity_key IS NOT NULL;
CREATE UNIQUE INDEX device_work_pipeline_opportunity ON tasks(pipeline_id,opportunity_key)
  WHERE pipeline_id IS NOT NULL AND opportunity_key IS NOT NULL;

CREATE UNIQUE INDEX device_work_reference_opportunity ON tasks(employee_reference,opportunity_key)
  WHERE employee_reference IS NOT NULL AND opportunity_key IS NOT NULL;

CREATE TABLE workflow_runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL UNIQUE REFERENCES tasks(id),
  state TEXT NOT NULL, available_at TEXT, manual_column_key TEXT, cursor_key TEXT,
  snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json)),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE employee_runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workflow_run_id INTEGER NOT NULL REFERENCES workflow_runs(id), position_key TEXT NOT NULL,
  employee_release_id INTEGER REFERENCES employee_releases(id), attempt INTEGER NOT NULL CHECK(attempt>0),
  state TEXT NOT NULL, input_json TEXT NOT NULL CHECK(json_valid(input_json)),
  output_json TEXT NOT NULL CHECK(json_valid(output_json)), created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(workflow_run_id,position_key,attempt));
CREATE TABLE artifacts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  employee_run_id INTEGER REFERENCES employee_runs(id), name TEXT NOT NULL,
  ref TEXT NOT NULL, meta_json TEXT NOT NULL CHECK(json_valid(meta_json)),
  created_at TEXT NOT NULL, trashed_at TEXT);
CREATE TABLE events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, stream TEXT NOT NULL, type TEXT NOT NULL,
  data_json TEXT NOT NULL CHECK(json_valid(data_json)), created_at TEXT NOT NULL,
  actor_id TEXT, correlation_id TEXT, source TEXT NOT NULL DEFAULT 'system',
  schema_version INTEGER NOT NULL DEFAULT 1, prev_hash TEXT, event_hash TEXT);
CREATE INDEX device_work_events_stream ON events(stream,id);
CREATE INDEX device_work_events_type ON events(type,stream,id);
CREATE INDEX device_work_employee_runs ON employee_runs(workflow_run_id,id);
CREATE INDEX device_work_source_chat ON workflow_runs(
  CAST(json_extract(snapshot_json,'$.source.chat_id') AS INTEGER),id);

CREATE TABLE device_work_resources(
  resource TEXT NOT NULL CHECK(resource IN ('tasks','workflow_runs','employee_runs','artifacts')),
  id INTEGER NOT NULL, identity TEXT NOT NULL UNIQUE,
  PRIMARY KEY(resource,id));
-- Restoring an earlier copy is not a fresh execution grant. Existing work is
-- retained for inspection; new work can still be created normally.
CREATE TABLE device_work_restore_barriers(
  workflow_run_id INTEGER PRIMARY KEY REFERENCES workflow_runs(id),
  restored_at TEXT NOT NULL);
CREATE TRIGGER device_work_scope_immutable_update BEFORE UPDATE ON device_work_scope BEGIN
  SELECT RAISE(ABORT, 'Device work scope is immutable');
END;
CREATE TRIGGER device_work_scope_immutable_delete BEFORE DELETE ON device_work_scope BEGIN
  SELECT RAISE(ABORT, 'Device work scope is immutable');
END;
